"""Graph storage using Neo4j for WorkNode persistence and traversal."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from neo4j import GraphDatabase

from gotn.node import (
    ArtifactOutput,
    CommitmentOutput,
    EdgeType,
    KnowledgeOutput,
    NodeMode,
    NodeStatus,
    PlanOutput,
    ValidationOutput,
    WorkNode,
)


class Neo4jGraphStore:
    """Neo4j-based graph storage for WorkNodes and relationships."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "agent-db-password",
        project: str = "gotn",
    ):
        self.uri = uri
        self.project = project
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self._init_schema()

    def _init_schema(self):
        """Initialize Neo4j constraints and indexes."""
        with self.driver.session() as session:
            # Create constraint for unique node IDs within project
            session.run("""
                CREATE CONSTRAINT worknode_id IF NOT EXISTS
                FOR (n:WorkNode) REQUIRE (n.id, n.project) IS UNIQUE
            """)
            # Create index for status queries
            session.run("""
                CREATE INDEX worknode_status IF NOT EXISTS
                FOR (n:WorkNode) ON (n.status, n.project)
            """)

    def _node_to_props(self, node: WorkNode) -> dict[str, Any]:
        """Convert WorkNode to Neo4j properties."""
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
        outputs_json = json.dumps(data.pop("outputs", []))

        # Remove fields stored as relationships
        data.pop("claims", None)
        data.pop("evidence", None)
        data.pop("edges", None)
        data.pop("children", None)

        return {
            "id": node.id,
            "project": self.project,
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
            "outputs_json": outputs_json,
            "log_file": node.resource_usage.log_file,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
            "data_json": json.dumps(data),
        }

    def _row_to_node(self, row: dict[str, Any]) -> WorkNode:
        """Convert Neo4j row to WorkNode."""
        data = json.loads(row.get("data_json") or "{}")
        data["id"] = row["id"]
        data["depth"] = row.get("depth", 0)
        data["mode"] = row["mode"]
        data["status"] = row["status"]
        data["parent"] = row.get("parent")
        data["production_anchor"] = row.get("production_anchor")
        data["deliverable_type"] = row["deliverable_type"]
        data["goal"] = json.loads(row.get("goal_json") or "{}")
        data["budget"] = json.loads(row.get("budget_json") or "{}")
        data["resource_usage"] = json.loads(row.get("resource_usage_json") or "{}")
        data["autonomy_gate"] = json.loads(row.get("autonomy_gate_json") or "{}")
        data["exit_policy"] = json.loads(row.get("exit_policy_json") or "{}")
        data["confidence"] = json.loads(row.get("confidence_json") or "{}")

        esc = row.get("escalation_context_json")
        if esc and esc != "null":
            data["escalation_context"] = json.loads(esc)

        err = row.get("error_json")
        if err and err != "null":
            data["error"] = json.loads(err)

        if row.get("created_at"):
            data["created_at"] = row["created_at"]
        if row.get("updated_at"):
            data["updated_at"] = row["updated_at"]

        # Load outputs from JSON
        outputs_raw = json.loads(row.get("outputs_json") or "[]")
        data["outputs"] = self._parse_outputs(outputs_raw)

        # Load children and edges from graph
        node_id = row["id"]
        data["children"] = self._get_child_ids(node_id)
        data["edges"] = self._get_edges(node_id)
        data["claims"] = self._get_claims(node_id)
        data["evidence"] = self._get_evidence(node_id)

        return WorkNode.model_validate(data)

    def _parse_outputs(self, outputs_raw: list[dict]) -> list:
        """Parse output dicts into typed Output objects."""
        outputs = []
        type_map = {
            "knowledge": KnowledgeOutput,
            "artifact": ArtifactOutput,
            "commitment": CommitmentOutput,
            "verification": ValidationOutput,
            "plan": PlanOutput,
        }
        for out in outputs_raw:
            output_type = out.get("type", "")
            if output_type in type_map:
                try:
                    outputs.append(type_map[output_type].model_validate(out))
                except Exception:
                    # If validation fails, keep as dict
                    outputs.append(out)
            else:
                outputs.append(out)
        return outputs

    def _get_child_ids(self, node_id: str) -> list[str]:
        """Get child node IDs via PARENT_OF relationship."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (p:WorkNode {id: $id, project: $project})-[:PARENT_OF]->(c:WorkNode)
                RETURN c.id AS child_id
                """,
                id=node_id, project=self.project
            )
            return [record["child_id"] for record in result]

    def _get_edges(self, node_id: str) -> list[dict]:
        """Get typed edges from a node."""
        edges = []
        edge_types = ["DEPENDS_ON", "INFORMS", "BLOCKS", "ENABLES", "SPAWNED_BY", "SUPERSEDES"]

        with self.driver.session() as session:
            for edge_type in edge_types:
                result = session.run(
                    f"""
                    MATCH (n:WorkNode {{id: $id, project: $project}})-[e:{edge_type}]->(t:WorkNode)
                    RETURN t.id AS target_id, e.metadata AS metadata
                    """,
                    id=node_id, project=self.project
                )
                for record in result:
                    edges.append({
                        "target": record["target_id"],
                        "type": edge_type.lower(),
                        "metadata": json.loads(record.get("metadata") or "{}") if record.get("metadata") else {},
                    })
        return edges

    def _get_claims(self, node_id: str) -> list[dict]:
        """Get claims for a node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})-[:HAS_CLAIM]->(c:Claim)
                RETURN c.id AS id, c.proposition AS proposition, c.confidence AS confidence,
                       c.expiry AS expiry, c.scope AS scope, c.domain AS domain
                """,
                id=node_id, project=self.project
            )
            claims = []
            for record in result:
                claims.append({
                    "id": record["id"],
                    "proposition": record["proposition"],
                    "confidence": record["confidence"],
                    "expiry": record.get("expiry"),
                    "scope": record["scope"],
                    "domain": record["domain"],
                    "evidence_ids": [],
                })
            return claims

    def _get_evidence(self, node_id: str) -> list[dict]:
        """Get evidence for a node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})-[:HAS_EVIDENCE]->(e:Evidence)
                RETURN e.id AS id, e.type AS type, e.source AS source, e.summary AS summary,
                       e.strength AS strength, e.recency AS recency, e.relevance AS relevance
                """,
                id=node_id, project=self.project
            )
            evidence = []
            for record in result:
                evidence.append({
                    "id": record["id"],
                    "type": record["type"],
                    "source": record["source"],
                    "summary": record["summary"],
                    "strength": record["strength"],
                    "recency": record.get("recency"),
                    "relevance": record["relevance"],
                })
            return evidence

    def save_node(self, node: WorkNode) -> None:
        """Save or update a WorkNode in the graph."""
        node.updated_at = datetime.now()
        props = self._node_to_props(node)

        with self.driver.session() as session:
            # Upsert the node with mode-specific label
            mode_label = node.mode.value.capitalize()
            session.run(
                f"""
                MERGE (n:WorkNode:{mode_label} {{id: $id, project: $project}})
                SET n += $props
                """,
                id=node.id, project=self.project, props=props
            )

            # Create parent relationship if parent exists
            if node.parent:
                session.run(
                    """
                    MATCH (p:WorkNode {id: $parent_id, project: $project})
                    MATCH (c:WorkNode {id: $child_id, project: $project})
                    MERGE (p)-[:PARENT_OF]->(c)
                    """,
                    parent_id=node.parent, child_id=node.id, project=self.project
                )

            # Save typed edges
            for edge in node.edges:
                edge_type = edge.type.value.upper()
                session.run(
                    f"""
                    MATCH (s:WorkNode {{id: $source_id, project: $project}})
                    MATCH (t:WorkNode {{id: $target_id, project: $project}})
                    MERGE (s)-[e:{edge_type}]->(t)
                    SET e.metadata = $metadata
                    """,
                    source_id=node.id, target_id=edge.target,
                    project=self.project, metadata=json.dumps(edge.metadata)
                )

            # Save claims
            for claim in node.claims:
                session.run(
                    """
                    MERGE (c:Claim {id: $id, project: $project})
                    SET c.proposition = $proposition,
                        c.confidence = $confidence,
                        c.expiry = $expiry,
                        c.scope = $scope,
                        c.domain = $domain,
                        c.node_id = $node_id
                    WITH c
                    MATCH (n:WorkNode {id: $node_id, project: $project})
                    MERGE (n)-[:HAS_CLAIM]->(c)
                    """,
                    id=claim.id, proposition=claim.proposition,
                    confidence=claim.confidence, expiry=str(claim.expiry) if claim.expiry else None,
                    scope=claim.scope, domain=claim.domain.value,
                    node_id=node.id, project=self.project
                )

            # Save evidence
            for ev in node.evidence:
                session.run(
                    """
                    MERGE (e:Evidence {id: $id, project: $project})
                    SET e.type = $type,
                        e.source = $source,
                        e.summary = $summary,
                        e.strength = $strength,
                        e.recency = $recency,
                        e.relevance = $relevance,
                        e.node_id = $node_id
                    WITH e
                    MATCH (n:WorkNode {id: $node_id, project: $project})
                    MERGE (n)-[:HAS_EVIDENCE]->(e)
                    """,
                    id=ev.id, type=ev.type.value, source=ev.source,
                    summary=ev.summary, strength=ev.strength,
                    recency=str(ev.recency) if ev.recency else None,
                    relevance=ev.relevance, node_id=node.id, project=self.project
                )

    def load_node(self, node_id: str) -> Optional[WorkNode]:
        """Load a WorkNode by ID."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})
                RETURN properties(n) AS props
                """,
                id=node_id, project=self.project
            )
            record = result.single()
            if not record:
                return None
            return self._row_to_node(record["props"])

    def create_node(self, node: WorkNode) -> WorkNode:
        """Create a new node in the graph."""
        self.save_node(node)
        return node

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its relationships."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})
                DETACH DELETE n
                """,
                id=node_id, project=self.project
            )
        return True

    def get_all_nodes(self) -> list[WorkNode]:
        """Get all WorkNodes for this project."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {project: $project})
                RETURN properties(n) AS props
                """,
                project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def get_nodes_by_status(self, status: NodeStatus) -> list[WorkNode]:
        """Get all nodes with a specific status."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {status: $status, project: $project})
                RETURN properties(n) AS props
                """,
                status=status.value, project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

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
        """Get all root nodes (no parent)."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {project: $project})
                WHERE n.parent IS NULL
                RETURN properties(n) AS props
                """,
                project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def get_children(self, node_id: str) -> list[WorkNode]:
        """Get all children of a node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (p:WorkNode {id: $id, project: $project})-[:PARENT_OF]->(c:WorkNode)
                RETURN properties(c) AS props
                """,
                id=node_id, project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def get_parent(self, node_id: str) -> Optional[WorkNode]:
        """Get parent of a node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (p:WorkNode)-[:PARENT_OF]->(c:WorkNode {id: $id, project: $project})
                RETURN properties(p) AS props
                """,
                id=node_id, project=self.project
            )
            record = result.single()
            if not record:
                return None
            return self._row_to_node(record["props"])

    def get_ancestors(self, node_id: str) -> list[WorkNode]:
        """Get all ancestors of a node, ordered from root to immediate parent."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (ancestor:WorkNode)-[:PARENT_OF*]->(n:WorkNode {id: $id, project: $project})
                WHERE ancestor.project = $project
                RETURN properties(ancestor) AS props
                ORDER BY ancestor.depth ASC
                """,
                id=node_id, project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def get_descendants(self, node_id: str) -> list[WorkNode]:
        """Get all descendants of a node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})-[:PARENT_OF*]->(d:WorkNode)
                WHERE d.project = $project
                RETURN properties(d) AS props
                """,
                id=node_id, project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def get_dependencies(self, node_id: str) -> list[WorkNode]:
        """Get nodes that this node depends on."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n:WorkNode {id: $id, project: $project})-[:DEPENDS_ON]->(d:WorkNode)
                WHERE d.project = $project
                RETURN properties(d) AS props
                """,
                id=node_id, project=self.project
            )
            return [self._row_to_node(record["props"]) for record in result]

    def check_dependencies_met(self, node_id: str) -> bool:
        """Check if all dependencies are satisfied (COMPLETE or DEGRADED)."""
        deps = self.get_dependencies(node_id)
        return all(d.status in (NodeStatus.COMPLETE, NodeStatus.DEGRADED) for d in deps)

    def check_all_children_terminal(self, node_id: str) -> bool:
        """Check if all children are in terminal state."""
        children = self.get_children(node_id)
        return all(c.status.is_terminal for c in children)

    def detect_cycle(self, source_id: str, target_id: str, edge_type: EdgeType) -> bool:
        """Check if adding an edge would create a cycle."""
        if not edge_type.is_blocking:
            return False

        with self.driver.session() as session:
            result = session.run(
                """
                MATCH path = (t:WorkNode {id: $target, project: $project})
                      -[:DEPENDS_ON|BLOCKS*]->(s:WorkNode {id: $source, project: $project})
                RETURN count(path) > 0 AS has_cycle
                """,
                source=source_id, target=target_id, project=self.project
            )
            record = result.single()
            return record["has_cycle"] if record else False

    def get_context_fingerprint(self, node_id: str) -> str:
        """Compute context fingerprint for cache keying."""
        node = self.load_node(node_id)
        if not node:
            return ""

        ancestors = self.get_ancestors(node_id)
        root_id = ancestors[0].id if ancestors else node_id

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
        self.driver.close()

    # Project management methods

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects with node counts and status summary.

        Returns list of dicts with:
            - project: project name
            - total_nodes: total node count
            - by_status: dict of status -> count
            - oldest_node: datetime of oldest node
            - newest_node: datetime of newest node
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:WorkNode)
                WITH n.project AS project,
                     count(n) AS total_nodes,
                     min(n.created_at) AS oldest,
                     max(n.created_at) AS newest,
                     collect(n.status) AS statuses
                RETURN project, total_nodes, oldest, newest, statuses
                ORDER BY newest DESC
            """)

            projects = []
            for record in result:
                statuses = record["statuses"]
                by_status = {}
                for s in statuses:
                    by_status[s] = by_status.get(s, 0) + 1

                projects.append({
                    "project": record["project"],
                    "total_nodes": record["total_nodes"],
                    "by_status": by_status,
                    "oldest_node": record["oldest"],
                    "newest_node": record["newest"],
                })

            return projects

    def delete_project(self, project_name: str) -> int:
        """Delete all nodes belonging to a project.

        Args:
            project_name: Name of the project to delete

        Returns:
            Number of nodes deleted
        """
        with self.driver.session() as session:
            # First count
            count_result = session.run(
                "MATCH (n:WorkNode {project: $project}) RETURN count(n) AS count",
                project=project_name
            )
            count = count_result.single()["count"]

            # Delete all relationships and nodes for this project
            session.run("""
                MATCH (n:WorkNode {project: $project})
                DETACH DELETE n
            """, project=project_name)

            return count

    def get_project_stats(self, project_name: str) -> dict[str, Any]:
        """Get detailed statistics for a project.

        Returns dict with:
            - total_nodes: total count
            - by_status: status breakdown
            - by_mode: mode breakdown
            - root_nodes: list of root node summaries
            - depth_distribution: nodes per depth level
        """
        with self.driver.session() as session:
            # Basic counts
            result = session.run("""
                MATCH (n:WorkNode {project: $project})
                RETURN
                    count(n) AS total,
                    collect(DISTINCT n.status) AS statuses,
                    collect(DISTINCT n.mode) AS modes
            """, project=project_name)
            record = result.single()

            if not record or record["total"] == 0:
                return {"total_nodes": 0, "by_status": {}, "by_mode": {}, "root_nodes": []}

            # Status breakdown
            status_result = session.run("""
                MATCH (n:WorkNode {project: $project})
                RETURN n.status AS status, count(n) AS count
            """, project=project_name)
            by_status = {r["status"]: r["count"] for r in status_result}

            # Mode breakdown
            mode_result = session.run("""
                MATCH (n:WorkNode {project: $project})
                RETURN n.mode AS mode, count(n) AS count
            """, project=project_name)
            by_mode = {r["mode"]: r["count"] for r in mode_result}

            # Root nodes (no parent)
            root_result = session.run("""
                MATCH (n:WorkNode {project: $project})
                WHERE n.parent IS NULL
                RETURN n.id AS id, n.goal AS goal, n.status AS status, n.created_at AS created
                ORDER BY n.created_at DESC
                LIMIT 10
            """, project=project_name)
            root_nodes = [
                {"id": r["id"], "goal": r["goal"][:50] if r["goal"] else "", "status": r["status"]}
                for r in root_result
            ]

            # Depth distribution
            depth_result = session.run("""
                MATCH (n:WorkNode {project: $project})
                RETURN n.depth AS depth, count(n) AS count
                ORDER BY n.depth
            """, project=project_name)
            depth_dist = {r["depth"]: r["count"] for r in depth_result}

            return {
                "total_nodes": record["total"],
                "by_status": by_status,
                "by_mode": by_mode,
                "root_nodes": root_nodes,
                "depth_distribution": depth_dist,
            }
