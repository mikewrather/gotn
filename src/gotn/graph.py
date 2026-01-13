"""Graph storage using Kuzu for WorkNode persistence and traversal."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import kuzu

from gotn.node import (
    EdgeType,
    NodeMode,
    NodeStatus,
    WorkNode,
    Evidence,
    Claim,
)


class GraphStore:
    """Kuzu-based graph storage for WorkNodes and relationships."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        store_path.mkdir(parents=True, exist_ok=True)
        self.db_path = store_path / "graph"
        self.db = kuzu.Database(str(self.db_path))
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _result_to_dicts(self, result) -> list[dict[str, Any]]:
        """Convert Kuzu query result to list of dicts without polars dependency."""
        rows = []
        column_names = result.get_column_names()
        while result.has_next():
            values = result.get_next()
            rows.append(dict(zip(column_names, values)))
        return rows

    def _init_schema(self):
        """Initialize the Kuzu schema if not exists."""
        # Node tables
        self.conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS WorkNode (
                id STRING PRIMARY KEY,
                depth INT64,
                mode STRING,
                status STRING,
                parent STRING,
                production_anchor STRING,
                deliverable_type STRING,
                goal_json STRING,
                budget_json STRING,
                resource_usage_json STRING,
                autonomy_gate_json STRING,
                exit_policy_json STRING,
                confidence_json STRING,
                escalation_context_json STRING,
                error_json STRING,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                data_json STRING
            )
        """)

        self.conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Evidence (
                id STRING PRIMARY KEY,
                type STRING,
                source STRING,
                summary STRING,
                strength DOUBLE,
                recency TIMESTAMP,
                relevance DOUBLE,
                node_id STRING
            )
        """)

        self.conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Claim (
                id STRING PRIMARY KEY,
                proposition STRING,
                confidence DOUBLE,
                expiry TIMESTAMP,
                scope STRING,
                domain STRING,
                node_id STRING
            )
        """)

        # Relationship tables
        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS PARENT_OF (
                FROM WorkNode TO WorkNode
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS DEPENDS_ON (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS INFORMS (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS BLOCKS (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS ENABLES (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS SPAWNED_BY (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS SUPERSEDES (
                FROM WorkNode TO WorkNode,
                metadata STRING
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS HAS_EVIDENCE (
                FROM WorkNode TO Evidence
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS HAS_CLAIM (
                FROM WorkNode TO Claim
            )
        """)

        self.conn.execute("""
            CREATE REL TABLE IF NOT EXISTS SUPPORTS (
                FROM Evidence TO Claim
            )
        """)

    def _node_to_row(self, node: WorkNode) -> dict[str, Any]:
        """Convert WorkNode to Kuzu row data."""
        data = node.model_dump(mode="json", exclude_none=True)

        # Extract nested objects as JSON strings
        goal_json = json.dumps(data.pop("goal", {}))
        budget_json = json.dumps(data.pop("budget", {}))
        resource_usage_json = json.dumps(data.pop("resource_usage", {}))
        autonomy_gate_json = json.dumps(data.pop("autonomy_gate", {}))
        exit_policy_json = json.dumps(data.pop("exit_policy", {}))
        confidence_json = json.dumps(data.pop("confidence", {}))
        escalation_context_json = json.dumps(data.pop("escalation_context", None))
        error_json = json.dumps(data.pop("error", None))

        # Remove fields stored separately
        data.pop("claims", None)
        data.pop("evidence", None)
        data.pop("edges", None)
        data.pop("children", None)
        data.pop("outputs", None)

        return {
            "id": node.id,
            "depth": node.depth,
            "mode": node.mode.value,
            "status": node.status.value,
            "parent": node.parent,
            "production_anchor": node.production_anchor,
            "deliverable_type": node.deliverable_type.value,
            "goal_json": goal_json,
            "budget_json": budget_json,
            "resource_usage_json": resource_usage_json,
            "autonomy_gate_json": autonomy_gate_json,
            "exit_policy_json": exit_policy_json,
            "confidence_json": confidence_json,
            "escalation_context_json": escalation_context_json,
            "error_json": error_json,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "data_json": json.dumps(data),
        }

    def _row_to_node(self, row: dict[str, Any]) -> WorkNode:
        """Convert Kuzu row data to WorkNode."""
        # Parse JSON fields
        data = json.loads(row.get("data_json") or "{}")
        data["id"] = row["id"]
        data["depth"] = row["depth"]
        data["mode"] = row["mode"]
        data["status"] = row["status"]
        data["parent"] = row["parent"]
        data["production_anchor"] = row["production_anchor"]
        data["deliverable_type"] = row["deliverable_type"]
        data["goal"] = json.loads(row["goal_json"])
        data["budget"] = json.loads(row["budget_json"])
        data["resource_usage"] = json.loads(row["resource_usage_json"])
        data["autonomy_gate"] = json.loads(row["autonomy_gate_json"])
        data["exit_policy"] = json.loads(row["exit_policy_json"])
        data["confidence"] = json.loads(row["confidence_json"])

        esc = row.get("escalation_context_json")
        if esc and esc != "null":
            data["escalation_context"] = json.loads(esc)

        err = row.get("error_json")
        if err and err != "null":
            data["error"] = json.loads(err)

        data["created_at"] = row["created_at"]
        data["updated_at"] = row["updated_at"]

        # Load children and edges from graph
        node_id = row["id"]
        data["children"] = self._get_child_ids(node_id)
        data["edges"] = self._get_edges(node_id)
        data["claims"] = self._get_claims(node_id)
        data["evidence"] = self._get_evidence(node_id)
        data["outputs"] = []  # TODO: store outputs

        return WorkNode.model_validate(data)

    def _get_child_ids(self, node_id: str) -> list[str]:
        """Get child node IDs via PARENT_OF relationship."""
        result = self.conn.execute(
            "MATCH (p:WorkNode)-[:PARENT_OF]->(c:WorkNode) WHERE p.id = $id RETURN c.id AS child_id",
            {"id": node_id}
        )
        return [row["child_id"] for row in self._result_to_dicts(result)]

    def _get_edges(self, node_id: str) -> list[dict]:
        """Get typed edges from a node."""
        edges = []
        edge_types = ["DEPENDS_ON", "INFORMS", "BLOCKS", "ENABLES", "SPAWNED_BY", "SUPERSEDES"]

        for edge_type in edge_types:
            result = self.conn.execute(
                f"MATCH (n:WorkNode)-[e:{edge_type}]->(t:WorkNode) WHERE n.id = $id RETURN t.id AS target_id, e.metadata AS metadata",
                {"id": node_id}
            )
            for row in self._result_to_dicts(result):
                edges.append({
                    "target": row["target_id"],
                    "type": edge_type.lower(),
                    "metadata": json.loads(row.get("metadata") or "{}"),
                })

        return edges

    def _get_claims(self, node_id: str) -> list[dict]:
        """Get claims for a node."""
        result = self.conn.execute(
            """MATCH (n:WorkNode)-[:HAS_CLAIM]->(c:Claim) WHERE n.id = $id
            RETURN c.id AS id, c.proposition AS proposition, c.confidence AS confidence,
                   c.expiry AS expiry, c.scope AS scope, c.domain AS domain""",
            {"id": node_id}
        )
        claims = []
        for row in self._result_to_dicts(result):
            claims.append({
                "id": row["id"],
                "proposition": row["proposition"],
                "confidence": row["confidence"],
                "expiry": row.get("expiry"),
                "scope": row["scope"],
                "domain": row["domain"],
                "evidence_ids": [],  # TODO: load from SUPPORTS
            })
        return claims

    def _get_evidence(self, node_id: str) -> list[dict]:
        """Get evidence for a node."""
        result = self.conn.execute(
            """MATCH (n:WorkNode)-[:HAS_EVIDENCE]->(e:Evidence) WHERE n.id = $id
            RETURN e.id AS id, e.type AS type, e.source AS source, e.summary AS summary,
                   e.strength AS strength, e.recency AS recency, e.relevance AS relevance""",
            {"id": node_id}
        )
        evidence = []
        for row in self._result_to_dicts(result):
            evidence.append({
                "id": row["id"],
                "type": row["type"],
                "source": row["source"],
                "summary": row["summary"],
                "strength": row["strength"],
                "recency": row.get("recency"),
                "relevance": row["relevance"],
            })
        return evidence

    def save_node(self, node: WorkNode) -> None:
        """Save or update a WorkNode in the graph."""
        node.updated_at = datetime.now()
        row = self._node_to_row(node)

        # Upsert the node
        self.conn.execute(
            """
            MERGE (n:WorkNode {id: $id})
            SET n.depth = $depth,
                n.mode = $mode,
                n.status = $status,
                n.parent = $parent,
                n.production_anchor = $production_anchor,
                n.deliverable_type = $deliverable_type,
                n.goal_json = $goal_json,
                n.budget_json = $budget_json,
                n.resource_usage_json = $resource_usage_json,
                n.autonomy_gate_json = $autonomy_gate_json,
                n.exit_policy_json = $exit_policy_json,
                n.confidence_json = $confidence_json,
                n.escalation_context_json = $escalation_context_json,
                n.error_json = $error_json,
                n.created_at = $created_at,
                n.updated_at = $updated_at,
                n.data_json = $data_json
            """,
            row
        )

        # Create parent relationship if parent exists
        if node.parent:
            self.conn.execute(
                """
                MATCH (p:WorkNode {id: $parent_id}), (c:WorkNode {id: $child_id})
                MERGE (p)-[:PARENT_OF]->(c)
                """,
                {"parent_id": node.parent, "child_id": node.id}
            )

        # Save typed edges
        for edge in node.edges:
            edge_type = edge.type.value.upper()
            self.conn.execute(
                f"""
                MATCH (s:WorkNode {{id: $source_id}}), (t:WorkNode {{id: $target_id}})
                MERGE (s)-[e:{edge_type}]->(t)
                SET e.metadata = $metadata
                """,
                {
                    "source_id": node.id,
                    "target_id": edge.target,
                    "metadata": json.dumps(edge.metadata),
                }
            )

        # Save claims
        for claim in node.claims:
            self.conn.execute(
                """
                MERGE (c:Claim {id: $id})
                SET c.proposition = $proposition,
                    c.confidence = $confidence,
                    c.expiry = $expiry,
                    c.scope = $scope,
                    c.domain = $domain,
                    c.node_id = $node_id
                """,
                {
                    "id": claim.id,
                    "proposition": claim.proposition,
                    "confidence": claim.confidence,
                    "expiry": claim.expiry,
                    "scope": claim.scope,
                    "domain": claim.domain.value,
                    "node_id": node.id,
                }
            )
            self.conn.execute(
                """
                MATCH (n:WorkNode {id: $node_id}), (c:Claim {id: $claim_id})
                MERGE (n)-[:HAS_CLAIM]->(c)
                """,
                {"node_id": node.id, "claim_id": claim.id}
            )

        # Save evidence
        for ev in node.evidence:
            self.conn.execute(
                """
                MERGE (e:Evidence {id: $id})
                SET e.type = $type,
                    e.source = $source,
                    e.summary = $summary,
                    e.strength = $strength,
                    e.recency = $recency,
                    e.relevance = $relevance,
                    e.node_id = $node_id
                """,
                {
                    "id": ev.id,
                    "type": ev.type.value,
                    "source": ev.source,
                    "summary": ev.summary,
                    "strength": ev.strength,
                    "recency": ev.recency,
                    "relevance": ev.relevance,
                    "node_id": node.id,
                }
            )
            self.conn.execute(
                """
                MATCH (n:WorkNode {id: $node_id}), (e:Evidence {id: $ev_id})
                MERGE (n)-[:HAS_EVIDENCE]->(e)
                """,
                {"node_id": node.id, "ev_id": ev.id}
            )

    def load_node(self, node_id: str) -> Optional[WorkNode]:
        """Load a WorkNode by ID."""
        result = self.conn.execute(
            "MATCH (n:WorkNode {id: $id}) RETURN n.*",
            {"id": node_id}
        )
        rows = self._result_to_dicts(result)
        if not rows:
            return None

        # Flatten the row keys (remove 'n.' prefix)
        row = {k.replace("n.", ""): v for k, v in rows[0].items()}
        return self._row_to_node(row)

    def create_node(self, node: WorkNode) -> WorkNode:
        """Create a new node in the graph."""
        self.save_node(node)
        return node

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its relationships."""
        self.conn.execute(
            "MATCH (n:WorkNode {id: $id}) DETACH DELETE n",
            {"id": node_id}
        )
        return True

    def get_all_nodes(self) -> list[WorkNode]:
        """Get all WorkNodes."""
        result = self.conn.execute("MATCH (n:WorkNode) RETURN n.*")
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("n.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_nodes_by_status(self, status: NodeStatus) -> list[WorkNode]:
        """Get all nodes with a specific status."""
        result = self.conn.execute(
            "MATCH (n:WorkNode {status: $status}) RETURN n.*",
            {"status": status.value}
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("n.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_ready_nodes(self) -> list[WorkNode]:
        """Get all nodes in READY state."""
        return self.get_nodes_by_status(NodeStatus.READY)

    def get_running_nodes(self) -> list[WorkNode]:
        """Get all nodes in RUNNING state."""
        return self.get_nodes_by_status(NodeStatus.RUNNING)

    def get_blocked_nodes(self) -> list[WorkNode]:
        """Get all nodes in BLOCKED state."""
        return self.get_nodes_by_status(NodeStatus.BLOCKED)

    def get_root_nodes(self) -> list[WorkNode]:
        """Get all root nodes (depth=0, no parent)."""
        result = self.conn.execute(
            "MATCH (n:WorkNode) WHERE n.parent IS NULL RETURN n.*"
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("n.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_children(self, node_id: str) -> list[WorkNode]:
        """Get all children of a node."""
        result = self.conn.execute(
            "MATCH (p:WorkNode {id: $id})-[:PARENT_OF]->(c:WorkNode) RETURN c.*",
            {"id": node_id}
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("c.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_parent(self, node_id: str) -> Optional[WorkNode]:
        """Get parent of a node."""
        result = self.conn.execute(
            "MATCH (p:WorkNode)-[:PARENT_OF]->(c:WorkNode {id: $id}) RETURN p.*",
            {"id": node_id}
        )
        rows = self._result_to_dicts(result)
        if not rows:
            return None
        row = {k.replace("p.", ""): v for k, v in rows[0].items()}
        return self._row_to_node(row)

    def get_ancestors(self, node_id: str) -> list[WorkNode]:
        """Get all ancestors of a node (parent chain to root), ordered from root to immediate parent."""
        result = self.conn.execute(
            """
            MATCH (ancestor:WorkNode)-[:PARENT_OF*1..]->(n:WorkNode {id: $id})
            RETURN ancestor.*
            ORDER BY ancestor.depth ASC
            """,
            {"id": node_id}
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("ancestor.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_descendants(self, node_id: str) -> list[WorkNode]:
        """Get all descendants of a node."""
        result = self.conn.execute(
            "MATCH (n:WorkNode {id: $id})-[:PARENT_OF*]->(d:WorkNode) RETURN d.*",
            {"id": node_id}
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("d.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def get_dependencies(self, node_id: str) -> list[WorkNode]:
        """Get nodes that this node depends on."""
        result = self.conn.execute(
            "MATCH (n:WorkNode {id: $id})-[:DEPENDS_ON]->(d:WorkNode) RETURN d.*",
            {"id": node_id}
        )
        nodes = []
        for row in self._result_to_dicts(result):
            row = {k.replace("d.", ""): v for k, v in row.items()}
            nodes.append(self._row_to_node(row))
        return nodes

    def check_dependencies_met(self, node_id: str) -> bool:
        """Check if all dependencies are satisfied (COMPLETE or DEGRADED)."""
        deps = self.get_dependencies(node_id)
        return all(d.status in (NodeStatus.COMPLETE, NodeStatus.DEGRADED) for d in deps)

    def check_all_children_terminal(self, node_id: str) -> bool:
        """Check if all children are in terminal state."""
        children = self.get_children(node_id)
        return all(c.status.is_terminal for c in children)

    def detect_cycle(self, source_id: str, target_id: str, edge_type: EdgeType) -> bool:
        """Check if adding an edge would create a cycle (for blocking edge types)."""
        if not edge_type.is_blocking:
            return False

        # Check if target can reach source via blocking edges
        result = self.conn.execute(
            """
            MATCH path = (t:WorkNode {id: $target})-[:DEPENDS_ON|BLOCKS*]->(s:WorkNode {id: $source})
            RETURN count(path) > 0 as has_cycle
            """,
            {"source": source_id, "target": target_id}
        )
        rows = self._result_to_dicts(result)
        return rows[0]["has_cycle"] if rows else False

    def get_context_fingerprint(self, node_id: str) -> str:
        """Compute context fingerprint for cache keying."""
        node = self.load_node(node_id)
        if not node:
            return ""

        # Get root node for root_id
        ancestors = self.get_ancestors(node_id)
        root_id = ancestors[0].id if ancestors else node_id

        # Collect constraint hashes from ancestors
        constraint_hashes = []
        for ancestor in ancestors + [node]:
            for crit in ancestor.goal.acceptance_criteria:
                if crit.must_pass:
                    constraint_hashes.append(hash(crit.description))

        import hashlib
        fingerprint_data = f"{root_id}:{node.production_anchor or ''}:{node.depth}:{sorted(constraint_hashes)}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

    def close(self):
        """Close the database connection."""
        # Kuzu connections are automatically cleaned up
        pass
