"""Goal alignment mechanisms for hierarchical task decomposition.

Solves the "goal drift" problem where deep subtasks lose sight of root objectives.

Key mechanisms:
1. Goal Chain - Compressed ancestry from root to current node
2. Alignment Score - Semantic similarity validation before spawning
3. Constraint Propagation - Critical criteria flow down the tree
4. Alignment Checkpoints - Validate at state transitions
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from gotn.node import Criterion, WorkNode


@dataclass
class GoalChainEntry:
    """A single entry in the goal chain."""

    node_id: str
    depth: int
    goal_summary: str  # Compressed goal (max ~50 chars)
    mode: str
    key_constraint: Optional[str] = None  # Most important constraint


@dataclass
class GoalChain:
    """Compressed ancestry from root to current node.

    Strategy: Keep root and immediate ancestors, compress middle.
    Target: ~500 tokens regardless of depth.
    """

    root: GoalChainEntry
    ancestors: list[GoalChainEntry]  # Immediate ancestors (parent, grandparent)
    current: GoalChainEntry
    total_depth: int

    # Propagated constraints from ancestors
    inherited_constraints: list[str] = field(default_factory=list)

    # Alignment metadata
    alignment_score: float = 1.0  # 0-1, how aligned current is with root
    last_validated: Optional[datetime] = None

    def to_context(self, max_tokens: int = 500) -> str:
        """Render goal chain as context string within token budget."""
        lines = [
            "## Goal Alignment Context",
            "",
            f"**Root Objective** (depth 0): {self.root.goal_summary}",
        ]

        if self.root.key_constraint:
            lines.append(f"  └─ Key constraint: {self.root.key_constraint}")

        # Add compressed ancestors (skip if too many)
        if len(self.ancestors) <= 3:
            for a in self.ancestors:
                lines.append(f"**Ancestor** (depth {a.depth}): {a.goal_summary}")
        else:
            # Show first, last, and count
            lines.append(f"**...{len(self.ancestors)} intermediate goals...**")
            lines.append(f"**Parent** (depth {self.ancestors[-1].depth}): {self.ancestors[-1].goal_summary}")

        lines.extend([
            "",
            f"**Current Goal** (depth {self.current.depth}): {self.current.goal_summary}",
            "",
        ])

        if self.inherited_constraints:
            lines.append("**Inherited Constraints** (must satisfy):")
            for c in self.inherited_constraints[:5]:  # Limit to 5
                lines.append(f"  - {c}")

        if self.alignment_score < 1.0:
            lines.append(f"\n⚠️ Alignment score: {self.alignment_score:.0%}")

        return "\n".join(lines)


@dataclass
class AlignmentResult:
    """Result of alignment validation."""

    aligned: bool
    score: float  # 0-1 semantic similarity
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def summarize_goal(goal: str, max_chars: int = 60) -> str:
    """Compress a goal statement to fit context budget."""
    if len(goal) <= max_chars:
        return goal

    # Try to find a natural break point
    truncated = goal[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        return truncated[:last_space] + "..."
    return truncated + "..."


def extract_key_constraint(node: WorkNode) -> Optional[str]:
    """Extract the most important constraint from a node."""
    must_pass = [c for c in node.goal.acceptance_criteria if c.must_pass]
    if must_pass:
        return must_pass[0].description
    if node.goal.acceptance_criteria:
        return node.goal.acceptance_criteria[0].description
    return None


def build_goal_chain(
    node: WorkNode,
    load_node_fn,  # Callable[[str], WorkNode]
    max_ancestors: int = 3,
) -> GoalChain:
    """Build a compressed goal chain from root to node.

    Args:
        node: The current node
        load_node_fn: Function to load nodes by ID
        max_ancestors: Max number of ancestors to include

    Returns:
        GoalChain with compressed ancestry
    """
    # Walk up the tree to collect ancestors
    ancestors: list[GoalChainEntry] = []
    inherited_constraints: list[str] = []
    current = node
    root = None

    while current.parent:
        try:
            parent = load_node_fn(current.parent)

            entry = GoalChainEntry(
                node_id=parent.id,
                depth=parent.depth,
                goal_summary=summarize_goal(parent.goal.statement),
                mode=parent.mode.value,
                key_constraint=extract_key_constraint(parent),
            )
            ancestors.insert(0, entry)

            # Collect must-pass constraints
            for c in parent.goal.acceptance_criteria:
                if c.must_pass and c.description not in inherited_constraints:
                    inherited_constraints.append(c.description)

            current = parent

        except FileNotFoundError:
            break

    # The last current is the root
    if ancestors:
        root = ancestors.pop(0)
    else:
        # Node is root
        root = GoalChainEntry(
            node_id=node.id,
            depth=node.depth,
            goal_summary=summarize_goal(node.goal.statement),
            mode=node.mode.value,
            key_constraint=extract_key_constraint(node),
        )

    # Trim to max_ancestors (keep most recent)
    if len(ancestors) > max_ancestors:
        ancestors = ancestors[-max_ancestors:]

    current_entry = GoalChainEntry(
        node_id=node.id,
        depth=node.depth,
        goal_summary=summarize_goal(node.goal.statement),
        mode=node.mode.value,
        key_constraint=extract_key_constraint(node),
    )

    return GoalChain(
        root=root,
        ancestors=ancestors,
        current=current_entry,
        total_depth=node.depth,
        inherited_constraints=inherited_constraints[:5],  # Limit propagation
    )


def compute_alignment_score(
    child_goal: str,
    parent_goal: str,
    root_goal: str,
    embedder=None,  # Optional embedding model
) -> float:
    """Compute alignment score between child and parent/root goals.

    Uses keyword overlap as fallback if no embedder available.
    """
    if embedder:
        # Use semantic similarity
        try:
            from gotn.cache import cosine_similarity

            child_emb = embedder.encode(child_goal)
            parent_emb = embedder.encode(parent_goal)
            root_emb = embedder.encode(root_goal)

            parent_sim = cosine_similarity(child_emb, parent_emb)
            root_sim = cosine_similarity(child_emb, root_emb)

            # Weight: 60% parent alignment, 40% root alignment
            return 0.6 * parent_sim + 0.4 * root_sim

        except Exception:
            pass

    # Fallback: keyword overlap with stemming and concept expansion

    # Domain-specific concept mappings for software development
    CONCEPT_GROUPS = [
        {"api", "rest", "endpoint", "service", "backend", "server", "http", "request", "response"},
        {"web", "framework", "fastapi", "flask", "django", "express", "rails", "spring"},
        {"database", "sql", "postgres", "mysql", "mongodb", "redis", "cache", "storage", "query"},
        {"auth", "authentication", "jwt", "token", "session", "oauth", "login", "password", "security"},
        {"test", "testing", "benchmark", "performance", "speed", "optimize", "profile", "metric"},
        {"research", "compare", "evaluate", "analyze", "review", "study", "investigate", "explore"},
        {"build", "create", "implement", "develop", "make", "construct", "design", "write"},
        {"python", "javascript", "typescript", "rust", "go", "java", "code", "programming"},
        {"user", "account", "profile", "member", "customer", "client"},
        {"data", "model", "schema", "structure", "format", "json", "xml"},
    ]

    def get_concept_group(word: str) -> set[str]:
        """Find all related concepts for a word."""
        related = set()
        word_lower = word.lower()
        for group in CONCEPT_GROUPS:
            if word_lower in group:
                related.update(group)
        return related

    def extract_keywords(text: str) -> set[str]:
        # Simple keyword extraction with basic stemming
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "is", "are", "be", "this", "that", "with", "from",
            "by", "as", "it", "its", "how", "what", "which", "who", "when",
        }
        words = text.lower().split()
        keywords = set()
        for w in words:
            w = w.strip(".,!?()-\"'")
            if len(w) > 2 and w not in stop_words:
                keywords.add(w)
                # Add stem approximation (remove common suffixes)
                for suffix in ["ing", "tion", "ment", "ness", "ity", "ies", "es", "ed", "ly", "s"]:
                    if w.endswith(suffix) and len(w) > len(suffix) + 2:
                        keywords.add(w[:-len(suffix)])
                        break
        return keywords

    def expand_with_concepts(keywords: set[str]) -> set[str]:
        """Expand keywords with related concepts."""
        expanded = set(keywords)
        for kw in keywords:
            expanded.update(get_concept_group(kw))
        return expanded

    child_kw = extract_keywords(child_goal)
    parent_kw = extract_keywords(parent_goal)
    root_kw = extract_keywords(root_goal)

    if not child_kw:
        return 0.5  # Neutral

    # Expand keywords with related concepts
    child_expanded = expand_with_concepts(child_kw)
    parent_expanded = expand_with_concepts(parent_kw)
    root_expanded = expand_with_concepts(root_kw)

    # Calculate overlap with both directions using expanded concepts
    parent_overlap = len(child_expanded & parent_expanded) / max(len(child_expanded), 1)
    root_overlap = len(child_expanded & root_expanded) / max(len(child_expanded), 1)

    # Also check reverse direction
    reverse_parent = len(child_expanded & parent_expanded) / max(len(parent_expanded), 1)
    reverse_root = len(child_expanded & root_expanded) / max(len(root_expanded), 1)

    # Combine forward and reverse
    combined_parent = (parent_overlap + reverse_parent) / 2
    combined_root = (root_overlap + reverse_root) / 2

    # Weight: 60% parent alignment, 40% root alignment
    score = 0.6 * combined_parent + 0.4 * combined_root

    # Boost if any direct keyword matches (partial credit)
    if len(child_kw & parent_kw) > 0 or len(child_kw & root_kw) > 0:
        score = max(score, 0.3)

    # Boost if concept groups overlap (weaker signal)
    if len(child_expanded & parent_expanded) > 0 or len(child_expanded & root_expanded) > 0:
        score = max(score, 0.2)

    return min(score, 1.0)


def validate_alignment(
    child_goal: str,
    parent: WorkNode,
    root: WorkNode,
    threshold: float = 0.3,
    embedder=None,
) -> AlignmentResult:
    """Validate that a proposed child goal aligns with ancestry.

    Args:
        child_goal: Proposed goal for child node
        parent: Parent node
        root: Root node of the tree
        threshold: Minimum alignment score
        embedder: Optional embedding model for semantic similarity

    Returns:
        AlignmentResult with score and issues
    """
    score = compute_alignment_score(
        child_goal,
        parent.goal.statement,
        root.goal.statement,
        embedder,
    )

    issues = []
    suggestions = []

    if score < threshold:
        issues.append(
            f"Low alignment ({score:.0%}) - child goal may not serve root objective"
        )
        suggestions.append(
            f"Consider rephrasing to explicitly connect to: {summarize_goal(root.goal.statement, 40)}"
        )

    # Check constraint compatibility
    for c in parent.goal.acceptance_criteria:
        if c.must_pass:
            # Child should somehow contribute to parent's must-pass criteria
            if c.description.lower() not in child_goal.lower():
                suggestions.append(
                    f"Parent requires: {c.description[:50]}"
                )

    return AlignmentResult(
        aligned=score >= threshold,
        score=score,
        issues=issues,
        suggestions=suggestions,
    )


def propagate_constraints(
    parent: WorkNode,
    child: WorkNode,
    inherit_must_pass: bool = True,
    max_inherited: int = 3,
) -> list[Criterion]:
    """Propagate constraints from parent to child.

    Args:
        parent: Parent node
        child: Child node to update
        inherit_must_pass: Whether must-pass criteria cascade
        max_inherited: Max constraints to inherit

    Returns:
        List of inherited criteria added to child
    """
    inherited = []

    if not inherit_must_pass:
        return inherited

    for c in parent.goal.acceptance_criteria:
        if not c.must_pass:
            continue
        if len(inherited) >= max_inherited:
            break

        # Create inherited version (not must_pass for child, but tracked)
        inherited_criterion = Criterion(
            description=f"[Inherited] {c.description}",
            type=c.type,
            must_pass=False,  # Child can degrade gracefully
        )
        inherited.append(inherited_criterion)

    return inherited


class AlignmentMonitor:
    """Monitors goal alignment across the tree.

    Used by scheduler/executor to validate alignment at checkpoints.
    """

    def __init__(
        self,
        load_node_fn,
        alignment_threshold: float = 0.3,
        embedder=None,
    ):
        self.load_node = load_node_fn
        self.threshold = alignment_threshold
        self.embedder = embedder
        self._alignment_cache: dict[str, float] = {}

    def check_spawn_alignment(
        self,
        parent: WorkNode,
        child_goal: str,
        child_mode: str,
    ) -> AlignmentResult:
        """Check if spawning a child is aligned with tree objectives."""
        # Find root
        root = parent
        while root.parent:
            try:
                root = self.load_node(root.parent)
            except FileNotFoundError:
                break

        return validate_alignment(
            child_goal,
            parent,
            root,
            self.threshold,
            self.embedder,
        )

    def get_goal_chain(self, node: WorkNode) -> GoalChain:
        """Get the goal chain for a node."""
        chain = build_goal_chain(node, self.load_node)

        # Compute alignment score
        if node.parent:
            try:
                root = node
                while root.parent:
                    root = self.load_node(root.parent)

                chain.alignment_score = compute_alignment_score(
                    node.goal.statement,
                    chain.ancestors[-1].goal_summary if chain.ancestors else root.goal.statement,
                    root.goal.statement,
                    self.embedder,
                )
            except FileNotFoundError:
                pass

        chain.last_validated = datetime.now()
        return chain

    def validate_tree_alignment(
        self,
        root: WorkNode,
    ) -> dict[str, AlignmentResult]:
        """Validate alignment of entire tree from root.

        Returns dict of node_id -> AlignmentResult for misaligned nodes.
        """
        misaligned = {}

        def check_subtree(node: WorkNode, depth: int = 0):
            for child_id in node.children:
                try:
                    child = self.load_node(child_id)
                    result = validate_alignment(
                        child.goal.statement,
                        node,
                        root,
                        self.threshold,
                        self.embedder,
                    )
                    if not result.aligned:
                        misaligned[child_id] = result

                    check_subtree(child, depth + 1)
                except FileNotFoundError:
                    pass

        check_subtree(root)
        return misaligned
