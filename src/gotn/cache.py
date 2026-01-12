"""Semantic cache for evidence and claims with vector similarity."""

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np

from gotn.node import Claim, ClaimDomain, Evidence


@dataclass
class CacheEntry:
    """A cached item with metadata."""

    key: str
    goal: str
    context_fingerprint: str
    content: dict[str, Any]
    embedding: Optional[list[float]]
    created_at: datetime
    accessed_at: datetime
    access_count: int
    domain: ClaimDomain


@dataclass
class CacheHit:
    """Result of a cache lookup."""

    entry: CacheEntry
    similarity: float
    recency_factor: float
    final_score: float


class EmbeddingModel:
    """Wrapper for sentence-transformers embedding model."""

    _instance: Optional["EmbeddingModel"] = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_model(self):
        """Lazy load the embedding model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )

    def encode(self, text: str) -> list[float]:
        """Encode text to embedding vector."""
        self._load_model()
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to embeddings."""
        self._load_model()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)

    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot / (norm_a * norm_b))


def compute_context_fingerprint(context: dict[str, Any]) -> str:
    """Compute a fingerprint for execution context.

    This ensures cache entries are scoped to similar contexts.
    """
    # Extract key context elements
    relevant = {
        "parent_goal": context.get("parent_goal", ""),
        "mode": context.get("mode", ""),
        "depth": context.get("depth", 0),
        "evidence_ids": sorted(context.get("evidence_ids", [])),
    }

    content = json.dumps(relevant, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class SemanticCache:
    """Two-level semantic cache with SQLite backend.

    L1: Exact match on (goal, context_fingerprint)
    L2: Vector similarity on goal embeddings (within same fingerprint)
    """

    def __init__(
        self,
        db_path: Path,
        similarity_threshold: float = 0.85,
        recency_weight: float = 0.3,
    ):
        self.db_path = db_path
        self.similarity_threshold = similarity_threshold
        self.recency_weight = recency_weight
        self.embedder = EmbeddingModel()
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    context_fingerprint TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    domain TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fingerprint
                ON cache_entries(context_fingerprint)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_goal
                ON cache_entries(goal)
            """)

            # FTS5 for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS cache_fts
                USING fts5(key, goal, content='cache_entries', content_rowid='rowid')
            """)

            conn.commit()

    def _serialize_embedding(self, embedding: list[float]) -> bytes:
        """Serialize embedding to bytes."""
        return np.array(embedding, dtype=np.float32).tobytes()

    def _deserialize_embedding(self, data: bytes) -> list[float]:
        """Deserialize embedding from bytes."""
        return np.frombuffer(data, dtype=np.float32).tolist()

    def put(
        self,
        goal: str,
        context: dict[str, Any],
        content: dict[str, Any],
        domain: ClaimDomain = ClaimDomain.GENERAL,
    ) -> str:
        """Store an entry in the cache.

        Args:
            goal: The goal statement
            context: Execution context for fingerprinting
            content: The content to cache (claims, evidence, etc.)
            domain: Domain for recency decay

        Returns:
            Cache key
        """
        fingerprint = compute_context_fingerprint(context)
        key = f"{hashlib.sha256(goal.encode()).hexdigest()[:12]}_{fingerprint}"

        # Generate embedding
        embedding = self.embedder.encode(goal)

        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache_entries
                (key, goal, context_fingerprint, content, embedding, domain, created_at, accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                key,
                goal,
                fingerprint,
                json.dumps(content),
                self._serialize_embedding(embedding),
                domain.value,
                now,
                now,
            ))
            conn.commit()

        return key

    def get_exact(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> Optional[CacheHit]:
        """L1 cache: Exact match lookup.

        Args:
            goal: The goal statement
            context: Execution context

        Returns:
            CacheHit if found, None otherwise
        """
        fingerprint = compute_context_fingerprint(context)
        key = f"{hashlib.sha256(goal.encode()).hexdigest()[:12]}_{fingerprint}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT key, goal, context_fingerprint, content, embedding, domain,
                       created_at, accessed_at, access_count
                FROM cache_entries
                WHERE key = ?
            """, (key,))

            row = cursor.fetchone()
            if row is None:
                return None

            entry = self._row_to_entry(row)

            # Update access stats
            conn.execute("""
                UPDATE cache_entries
                SET accessed_at = ?, access_count = access_count + 1
                WHERE key = ?
            """, (datetime.now().isoformat(), key))
            conn.commit()

            recency = self._compute_recency_factor(entry)
            return CacheHit(
                entry=entry,
                similarity=1.0,
                recency_factor=recency,
                final_score=1.0 * recency,
            )

    def get_similar(
        self,
        goal: str,
        context: dict[str, Any],
        limit: int = 5,
    ) -> list[CacheHit]:
        """L2 cache: Semantic similarity lookup.

        Args:
            goal: The goal statement
            context: Execution context (for fingerprint matching)
            limit: Maximum results to return

        Returns:
            List of similar cache hits, sorted by score
        """
        fingerprint = compute_context_fingerprint(context)
        query_embedding = self.embedder.encode(goal)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT key, goal, context_fingerprint, content, embedding, domain,
                       created_at, accessed_at, access_count
                FROM cache_entries
                WHERE context_fingerprint = ?
            """, (fingerprint,))

            hits = []
            for row in cursor.fetchall():
                entry = self._row_to_entry(row)
                if entry.embedding is None:
                    continue

                similarity = cosine_similarity(query_embedding, entry.embedding)
                if similarity < self.similarity_threshold:
                    continue

                recency = self._compute_recency_factor(entry)
                final_score = (
                    similarity * (1 - self.recency_weight) +
                    recency * self.recency_weight
                )

                hits.append(CacheHit(
                    entry=entry,
                    similarity=similarity,
                    recency_factor=recency,
                    final_score=final_score,
                ))

            # Sort by final score
            hits.sort(key=lambda h: h.final_score, reverse=True)

            # Update access stats for top hits
            for hit in hits[:limit]:
                conn.execute("""
                    UPDATE cache_entries
                    SET accessed_at = ?, access_count = access_count + 1
                    WHERE key = ?
                """, (datetime.now().isoformat(), hit.entry.key))

            conn.commit()

            return hits[:limit]

    def get(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> Optional[CacheHit]:
        """Combined L1 + L2 lookup.

        First tries exact match, then falls back to similarity.

        Args:
            goal: The goal statement
            context: Execution context

        Returns:
            Best cache hit, or None
        """
        # Try L1 first
        exact = self.get_exact(goal, context)
        if exact:
            return exact

        # Fall back to L2
        similar = self.get_similar(goal, context, limit=1)
        return similar[0] if similar else None

    def search_text(
        self,
        query: str,
        limit: int = 10,
    ) -> list[CacheEntry]:
        """Full-text search across cached goals.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching entries
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT e.key, e.goal, e.context_fingerprint, e.content, e.embedding,
                       e.domain, e.created_at, e.accessed_at, e.access_count
                FROM cache_entries e
                JOIN cache_fts f ON e.rowid = f.rowid
                WHERE cache_fts MATCH ?
                LIMIT ?
            """, (query, limit))

            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def invalidate(self, key: str) -> bool:
        """Remove an entry from the cache.

        Args:
            key: Cache key to remove

        Returns:
            True if entry was removed
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE key = ?",
                (key,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def invalidate_by_domain(
        self,
        domain: ClaimDomain,
        older_than: Optional[timedelta] = None,
    ) -> int:
        """Invalidate entries by domain and optionally age.

        Args:
            domain: Domain to invalidate
            older_than: Only invalidate entries older than this

        Returns:
            Number of entries removed
        """
        with sqlite3.connect(self.db_path) as conn:
            if older_than:
                cutoff = (datetime.now() - older_than).isoformat()
                cursor = conn.execute("""
                    DELETE FROM cache_entries
                    WHERE domain = ? AND created_at < ?
                """, (domain.value, cutoff))
            else:
                cursor = conn.execute(
                    "DELETE FROM cache_entries WHERE domain = ?",
                    (domain.value,)
                )
            conn.commit()
            return cursor.rowcount

    def prune_expired(self) -> int:
        """Remove entries past their domain's half-life.

        Returns:
            Number of entries removed
        """
        removed = 0
        for domain in ClaimDomain:
            half_life = timedelta(days=domain.half_life_days)
            removed += self.invalidate_by_domain(domain, older_than=half_life * 2)
        return removed

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(access_count) as total_accesses,
                    AVG(access_count) as avg_accesses
                FROM cache_entries
            """)
            row = cursor.fetchone()

            cursor2 = conn.execute("""
                SELECT domain, COUNT(*) as count
                FROM cache_entries
                GROUP BY domain
            """)
            by_domain = {r[0]: r[1] for r in cursor2.fetchall()}

            return {
                "total_entries": row[0] or 0,
                "total_accesses": row[1] or 0,
                "avg_accesses": row[2] or 0,
                "by_domain": by_domain,
            }

    def _row_to_entry(self, row: tuple) -> CacheEntry:
        """Convert database row to CacheEntry."""
        return CacheEntry(
            key=row[0],
            goal=row[1],
            context_fingerprint=row[2],
            content=json.loads(row[3]),
            embedding=self._deserialize_embedding(row[4]) if row[4] else None,
            domain=ClaimDomain(row[5]) if row[5] else ClaimDomain.GENERAL,
            created_at=datetime.fromisoformat(row[6]),
            accessed_at=datetime.fromisoformat(row[7]),
            access_count=row[8],
        )

    def _compute_recency_factor(self, entry: CacheEntry) -> float:
        """Compute recency factor for an entry."""
        age_days = (datetime.now() - entry.created_at).total_seconds() / 86400
        half_life = entry.domain.half_life_days
        return math.pow(0.5, age_days / half_life)


def cache_claims(
    cache: SemanticCache,
    goal: str,
    context: dict[str, Any],
    claims: list[Claim],
    evidence: list[Evidence],
) -> str:
    """Cache claims and evidence for a goal.

    Args:
        cache: The semantic cache
        goal: Goal statement
        context: Execution context
        claims: Claims to cache
        evidence: Evidence to cache

    Returns:
        Cache key
    """
    content = {
        "claims": [c.model_dump(mode="json") for c in claims],
        "evidence": [e.model_dump(mode="json") for e in evidence],
    }

    # Use the most specific domain from claims
    domain = ClaimDomain.GENERAL
    if claims:
        domain = claims[0].domain

    return cache.put(goal, context, content, domain)


def retrieve_cached_claims(
    cache: SemanticCache,
    goal: str,
    context: dict[str, Any],
) -> Optional[tuple[list[Claim], list[Evidence], float]]:
    """Retrieve cached claims and evidence.

    Args:
        cache: The semantic cache
        goal: Goal statement
        context: Execution context

    Returns:
        Tuple of (claims, evidence, score) or None
    """
    hit = cache.get(goal, context)
    if not hit:
        return None

    claims = [Claim.model_validate(c) for c in hit.entry.content.get("claims", [])]
    evidence = [Evidence.model_validate(e) for e in hit.entry.content.get("evidence", [])]

    return claims, evidence, hit.final_score
