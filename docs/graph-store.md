# Graph Store (Kuzu)

## Overview

GOTN uses **Kuzu**, an embedded graph database, for storage and queries. The data model is naturally a graph - nodes with typed relationships, ancestry traversal, and dependency edges.

## Why Kuzu

| Need | Solution |
|------|----------|
| Tree traversal (ancestors, descendants) | Native Cypher path queries |
| Relationship queries (parent, children, enables) | Graph-native, O(1) edge traversal |
| Embedded deployment | Single directory, no server |
| Python integration | `pip install kuzu`, in-process |

## Schema

```cypher
-- Core node types
CREATE NODE TABLE GoalCapsule(
    id STRING,
    root_goal STRING,
    constraints STRING[],       -- Must-pass constraints
    success_criteria STRING[],  -- Top-level success criteria
    checksum STRING,            -- SHA256 for tamper detection
    created_at TIMESTAMP,
    PRIMARY KEY(id)
)

CREATE NODE TABLE WorkNode(
    id STRING,
    goal STRING,
    mode STRING,          -- epistemic, decision, instrumental, validation
    status STRING,        -- pending, ready, running, blocked, complete, etc.
    depth INT64,
    confidence DOUBLE,
    capsule_ref STRING,   -- Reference to GoalCapsule
    context_policy STRING, -- JSON: tier1_budget, tier2_enabled, filter_script
    contract STRING,       -- JSON: inputs, outputs, invariants
    segment_mode BOOL,     -- Data recursion enabled
    data STRING,          -- Full node JSON for complex fields
    created_at TIMESTAMP,
    PRIMARY KEY(id)
)

CREATE NODE TABLE Claim(
    id STRING,
    proposition STRING,
    confidence DOUBLE,
    domain STRING,        -- api_documentation, configuration, experiment, etc.
    scope STRING,         -- global, committed:decision-id, etc.
    source_node STRING,
    created_at TIMESTAMP,
    PRIMARY KEY(id)
)

CREATE NODE TABLE Evidence(
    id STRING,
    content STRING,
    summary STRING,       -- For Tier 2 queries
    domain STRING,        -- technical, contextual, user_provided
    strength DOUBLE,
    created_at TIMESTAMP,
    PRIMARY KEY(id)
)

-- Relationships
CREATE REL TABLE PARENT(FROM WorkNode TO WorkNode)
CREATE REL TABLE SPAWNED_BY(FROM WorkNode TO WorkNode)
CREATE REL TABLE DEPENDS_ON(FROM WorkNode TO WorkNode)
CREATE REL TABLE ENABLES(FROM WorkNode TO WorkNode)
CREATE REL TABLE HAS_CAPSULE(FROM WorkNode TO GoalCapsule)
CREATE REL TABLE HAS_CLAIM(FROM WorkNode TO Claim)
CREATE REL TABLE HAS_EVIDENCE(FROM WorkNode TO Evidence)
CREATE REL TABLE SUPPORTS(FROM Evidence TO Claim)
CREATE REL TABLE ANCHORED_TO(FROM WorkNode TO WorkNode)  -- production_anchor
```

## Key Queries

### Ancestry

```cypher
-- Get full ancestry (goal chain)
MATCH (n:WorkNode {id: $node_id})-[:PARENT*]->(ancestor)
RETURN ancestor.id, ancestor.goal, ancestor.depth
ORDER BY ancestor.depth DESC

-- Get all descendants
MATCH (n:WorkNode {id: $node_id})<-[:PARENT*]-(descendant)
RETURN descendant
```

### Scheduling

```cypher
-- Find ready nodes (scheduling)
MATCH (n:WorkNode {status: 'ready'})
RETURN n ORDER BY n.depth DESC, n.created_at

-- Check if all children are terminal
MATCH (parent:WorkNode {id: $node_id})<-[:PARENT]-(child)
WHERE child.status NOT IN ['complete', 'failed', 'cancelled', 'degraded']
RETURN count(child) AS pending_children
```

### Research Anchors

```cypher
-- Find research anchored to a decision
MATCH (research:WorkNode)-[:ANCHORED_TO]->(decision:WorkNode {mode: 'decision'})
WHERE decision.id = $decision_id
RETURN research
```

### Cycle Detection

```cypher
-- Validate no cycles (before adding edge)
MATCH path = (target:WorkNode {id: $target_id})-[:DEPENDS_ON|PARENT*]->(source:WorkNode {id: $source_id})
RETURN count(path) > 0 AS would_create_cycle
```

### Context Fingerprinting

```cypher
-- Compute context fingerprint for cache lookup
MATCH (n:WorkNode {id: $node_id})-[:PARENT*]->(root)
WITH n, root, collect(root.id) AS ancestry
MATCH (n)-[:ANCHORED_TO]->(anchor)
RETURN
    root.id AS root_id,
    anchor.id AS anchor_id,
    n.depth AS depth,
    ancestry AS ancestor_chain
```

The fingerprint is: `hash(root_id + anchor_id + depth + constraint_hashes)`

Same context = same fingerprint = safe to reuse cached research.

## Tier 2 Query Commands

Nodes access the graph via CLI commands (invoked during pre-fetch):

```bash
# Get ancestor goals and constraints
gotn query ancestors [--depth-limit N] [--format compact|full]

# Get claims from sibling/ancestor research
gotn query claims [--domain X] [--min-confidence 0.5] [--scope "committed:*"]

# Get committed decisions in ancestry
gotn query decisions [--format summary]

# Get outputs from sibling nodes
gotn query siblings [--status complete] [--format summary]

# Semantic search over evidence store
gotn query evidence "<search query>" [--limit 10]

# Get the goal capsule for this tree
gotn query capsule
```

**Context-aware output**: Each query command respects a `--max-tokens` flag:

```bash
# Compact output for context-constrained situations
gotn query ancestors --max-tokens 200

# Full detail when budget allows
gotn query ancestors --format full
```

## CLI Implementation

```python
@app.command("query")
def query_cmd():
    """Tier 2 context queries."""
    pass

@query_cmd.command("ancestors")
def query_ancestors(
    depth_limit: Optional[int] = None,
    format: str = "compact",
    max_tokens: int = 500,
    node: Optional[str] = None,  # Defaults to current node from env
):
    """Fetch ancestor goals and constraints."""
    store = get_graph_store()
    node_id = node or os.environ.get("GOTN_CURRENT_NODE")

    ancestors = store.get_ancestors(node_id)

    if format == "compact":
        # Summarize to fit token budget
        output = summarize_ancestors(ancestors, max_tokens)
    else:
        output = [a.to_dict() for a in ancestors]

    console.print_json(data=output)

@query_cmd.command("claims")
def query_claims(
    domain: Optional[str] = None,
    min_confidence: float = 0.5,
    scope: Optional[str] = None,
    max_tokens: int = 500,
):
    """Fetch relevant claims from the evidence store."""
    store = get_graph_store()

    claims = store.query_claims(
        domain=domain,
        min_confidence=min_confidence,
        scope_pattern=scope,
    )

    # Truncate to fit token budget
    output = truncate_to_tokens(claims, max_tokens)
    console.print_json(data=output)
```

## Python Integration

```python
import kuzu

class GraphStore:
    def __init__(self, path: str = "./store/graph"):
        self.db = kuzu.Database(path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def get_ancestors(self, node_id: str) -> list[WorkNode]:
        """Get full ancestry for goal chain."""
        result = self.conn.execute("""
            MATCH (n:WorkNode {id: $id})-[:PARENT*]->(ancestor)
            RETURN ancestor.id, ancestor.goal, ancestor.depth, ancestor.data
            ORDER BY ancestor.depth DESC
        """, {"id": node_id})
        return [self._to_worknode(row) for row in result]

    def get_ready_nodes(self) -> list[WorkNode]:
        """Get nodes ready for execution."""
        result = self.conn.execute("""
            MATCH (n:WorkNode {status: 'ready'})
            RETURN n
            ORDER BY n.depth DESC, n.created_at
        """)
        return [self._to_worknode(row) for row in result]

    def spawn_child(self, parent_id: str, child: WorkNode) -> None:
        """Create child node with parent relationship."""
        self.conn.execute("""
            CREATE (c:WorkNode {
                id: $child_id,
                goal: $goal,
                mode: $mode,
                status: 'pending',
                depth: $depth,
                data: $data
            })
        """, child.to_params())

        self.conn.execute("""
            MATCH (c:WorkNode {id: $child_id}), (p:WorkNode {id: $parent_id})
            CREATE (c)-[:PARENT]->(p)
            CREATE (c)-[:SPAWNED_BY]->(p)
        """, {"child_id": child.id, "parent_id": parent_id})
```

## Storage Layout

```
store/
├── graph/                    # Kuzu database directory
│   ├── nodes.kz
│   ├── rels.kz
│   └── ...
├── outputs/                  # Large artifacts (not in graph)
│   └── {node_id}/
│       ├── result.md
│       └── artifacts/
└── cache/                    # Semantic cache (optional)
    └── embeddings.kz         # Separate Kuzu DB for cache
```

## Benefits Over SQLite

| Operation | SQLite | Kuzu |
|-----------|--------|------|
| Get ancestors | Recursive CTE (verbose) | `[:PARENT*]` (one line) |
| Check cycles | Multiple queries | Single path query |
| Find connected subgraph | Complex joins | Native traversal |
| Add relationship types | Schema migration | Just add REL TABLE |

The data model matches the domain, so queries are intuitive.
