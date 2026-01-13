# GOTN Architecture

## What Problem Are We Solving?

Complex projects require **recursive decomposition**. A goal breaks into sub-goals, which break into sub-sub-goals, potentially many levels deep.

```
"Build story content generation system"
  └── "Research TTS options"
       └── "Evaluate ElevenLabs"
            └── "Test voice quality for children's content"
                 └── "Run sample generation with emotional tags"
```

The challenge: **each level needs to stay aligned with all levels above it**.

Without alignment, deep tasks drift:
```
"Build story content generation system"
  └── "Research TTS options"
       └── "Understand voice synthesis technology"
            └── "Study acoustic phonetics"
                 └── "Review papers on formant frequencies"  ← DRIFT
```

The phonetics research might be interesting, but it doesn't serve the root goal. We're building a story app, not writing a PhD thesis on acoustics.

**GOTN solves this with:**
1. **Recursive self-similar structure** - Same pattern at every level
2. **Automatic alignment** - Each node validates against its full ancestry
3. **Confidence tracking** - Know when a level has "enough" to proceed
4. **Thresholds** - Gates that control advancement

---

## The Core Model: Recursive Self-Similarity

Every node in GOTN has the same structure, regardless of depth:

```yaml
WorkNode:
  goal: "What are we trying to achieve?"
  criteria: "How do we know we succeeded?"
  confidence: "How sure are we?" (per criterion)
  threshold: "How sure do we need to be to proceed?"
  parent: "What spawned this node?"
  children: "What sub-tasks did we spawn?"
```

**Self-similarity means**: A node at depth 5 looks exactly like a node at depth 1. Same fields, same lifecycle, same rules.

```
Depth 0: Build story app           [goal, criteria, confidence, threshold]
  Depth 1: Research TTS            [goal, criteria, confidence, threshold]
    Depth 2: Evaluate ElevenLabs   [goal, criteria, confidence, threshold]
      Depth 3: Test voice quality  [goal, criteria, confidence, threshold]
```

This recursion is what enables complex projects - you can decompose to whatever depth is needed, and the system handles it uniformly.

---

## Alignment: The Key Mechanism

### The Problem

When a node spawns a child, the child might not actually serve the parent's goal. And even if it serves the parent, it might not serve the grandparent, or the root.

**Alignment ensures**: Every child node serves ALL ancestors up to the root.

### How It Works

Before spawning a child, GOTN checks:

1. **Does the child goal relate to the parent goal?**
2. **Does the child goal relate to the root goal?**
3. **Does the child inherit critical constraints from ancestors?**

```python
def spawn_child(parent, child_goal):
    # Check alignment with parent
    parent_alignment = compute_alignment(child_goal, parent.goal)

    # Check alignment with root (through full ancestry)
    root = get_root(parent)
    root_alignment = compute_alignment(child_goal, root.goal)

    # Weighted: 60% parent, 40% root
    overall = 0.6 * parent_alignment + 0.4 * root_alignment

    if overall < threshold:
        raise AlignmentError("Child goal doesn't serve tree objectives")

    # Propagate must-pass constraints from ancestors
    child.inherited_constraints = collect_must_pass(parent)

    return child
```

### The Goal Chain

To check alignment without passing the entire tree (context explosion), we compress the ancestry into a **Goal Chain**:

```
Goal Chain for depth-4 node:
┌─────────────────────────────────────────────────────┐
│ ROOT (depth 0): Build story content generation      │
│   └─ Key constraint: Age-appropriate (3-8 years)    │
│                                                     │
│ PARENT (depth 3): Test voice quality                │
│   └─ Key constraint: Must sound natural             │
│                                                     │
│ CURRENT (depth 4): Run sample with emotional tags   │
│                                                     │
│ Inherited constraints:                              │
│   - Age-appropriate content                         │
│   - Natural voice quality                           │
│   - Under budget ($0.01/minute)                     │
│                                                     │
│ Alignment score: 82%                                │
└─────────────────────────────────────────────────────┘
```

This compresses to ~500 tokens regardless of depth. The current node knows:
- What the root is trying to achieve
- What the immediate parent needs
- What constraints must be satisfied

### Constraint Propagation

**Must-pass constraints cascade down the tree.** If the root says "must be age-appropriate", every descendant inherits that constraint.

```yaml
# Root node
goal: "Build story content generation"
criteria:
  - description: "Age-appropriate for 3-8 years"
    must_pass: true  # ← This propagates to ALL children

# Depth 3 child automatically inherits:
inherited_constraints:
  - "[Inherited] Age-appropriate for 3-8 years"
```

This ensures that no matter how deep the decomposition goes, critical requirements aren't forgotten.

---

## Confidence and Thresholds

### Why Confidence Matters

At each level, you need to know: **Do I have enough information to proceed?**

Without confidence tracking:
- Research might stop too early (missed important considerations)
- Research might continue forever (analysis paralysis)
- Parent nodes don't know if children actually answered the question

### Per-Criterion Confidence

Each criterion on a goal gets its own confidence score:

```yaml
goal: "Evaluate ElevenLabs for children's TTS"
criteria:
  - description: "Voice quality acceptable for children"
    confidence: 0.85
    evidence: ["Tested 5 voice samples", "Kids focus group positive"]

  - description: "Cost within budget"
    confidence: 0.95
    evidence: ["Pricing confirmed at $0.008/minute"]

  - description: "API reliable"
    confidence: 0.60
    evidence: ["Read docs, no live testing yet"]
```

### Threshold Logic

```
If confidence >= threshold:
    → Mark complete, return to parent

If confidence < threshold AND budget remaining:
    → Spawn more research

If confidence < threshold AND budget exhausted:
    → Degrade (partial answer) OR escalate (ask human)
```

### Aggregation

Overall confidence combines criteria:

```python
def aggregate(criteria):
    must_pass = [c for c in criteria if c.must_pass]
    optional = [c for c in criteria if not c.must_pass]

    # Must-pass: use minimum (if any fails, overall fails)
    must_pass_score = min(c.confidence for c in must_pass) if must_pass else 1.0

    # Optional: weighted average
    optional_score = weighted_mean(c.confidence for c in optional) if optional else 1.0

    # Combine: 60% must-pass, 40% optional
    return 0.6 * must_pass_score + 0.4 * optional_score
```

---

## The Recursive Workflow

Here's how it all fits together:

```
1. Start with root goal
   └── Check: confidence >= threshold?
       └── NO: Spawn children to fill gaps
           └── Each child:
               └── Validate alignment with ancestry
               └── Inherit must-pass constraints
               └── Execute (may spawn its own children)
               └── Return confidence + outputs
           └── Aggregate child results
           └── Re-check: confidence >= threshold?
               └── YES: Complete
               └── NO: Spawn more OR degrade OR escalate
```

### Example Trace

```
[ROOT] Build story content generation (confidence: 0%)
  │
  ├─ Spawn: Research TTS (aligned: 95%)
  │   │
  │   ├─ Spawn: Evaluate ElevenLabs (aligned: 88%)
  │   │   │
  │   │   ├─ Spawn: Test voice quality (aligned: 85%)
  │   │   │   └─ COMPLETE (confidence: 90%)
  │   │   │
  │   │   ├─ Spawn: Check pricing (aligned: 92%)
  │   │   │   └─ COMPLETE (confidence: 98%)
  │   │   │
  │   │   └─ COMPLETE (confidence: 87%)
  │   │
  │   ├─ Spawn: Evaluate Google TTS (aligned: 86%)
  │   │   └─ ... (similar structure)
  │   │
  │   └─ COMPLETE (confidence: 85%)
  │
  ├─ Spawn: Research story structure (aligned: 91%)
  │   └─ ... (similar structure)
  │
  └─ DECISION: Commit to ElevenLabs (confidence: 88%)
      │
      └─ Spawn: Build TTS integration (aligned: 94%)
          └─ ... (instrumental work)
```

Each spawn is validated for alignment. Each completion rolls up confidence. The tree grows and contracts as needed.

---

## Dual Recursion: Task + Data

GOTN supports two orthogonal recursion modes that can be composed:

### Task Recursion (GOTN-Style)

Traditional goal decomposition: a WorkNode spawns child WorkNodes.

```
WorkNode (Research TTS)
  ├── spawn → WorkNode (Evaluate ElevenLabs)
  ├── spawn → WorkNode (Evaluate Google TTS)
  └── spawn → WorkNode (Evaluate Azure)

Parent BLOCKED until children complete
Results aggregated via confidence model
Each child is a separate execution context
```

**Use for**: Goal decomposition, heterogeneous sub-tasks, explicit contracts.

### Data Recursion (RLM-Style)

Process large data within a single node via recursive self-calls on segments.

```
WorkNode (Analyze 50 research papers)
  │
  ├── segment_call(papers[0:10]) → claims[]
  ├── segment_call(papers[10:20]) → claims[]
  ├── segment_call(papers[20:30]) → claims[]
  ├── segment_call(papers[30:40]) → claims[]
  └── segment_call(papers[40:50]) → claims[]
  │
  └── aggregate(all_claims) → final_output

Same node identity throughout
Shared environment/store across calls
No child WorkNodes spawned (cheaper)
```

**Use for**: Homogeneous data processing, when spawning nodes is overhead.

### Composition: Hybrid Patterns

The two modes compose naturally:

```
┌─────────────────────────────────────────────────────────────┐
│ Task Node: Research TTS Options                             │
│   └── Uses data recursion internally to process 50 papers  │
│       └── Writes claims to shared store                     │
│                                                             │
│ Task Node: Decision - Select TTS Provider                   │
│   └── Queries claims from store (Tier 2)                    │
│   └── Runs ContextFilter to score options vs constraints    │
│   └── Outputs: Commitment to ElevenLabs                     │
│                                                             │
│ Task Node: Implementation - Build TTS Integration           │
│   └── Queries decision + constraints (Tier 2)               │
│   └── Uses data recursion for large codebase analysis       │
│   └── Outputs: Working integration                          │
└─────────────────────────────────────────────────────────────┘
```

### When to Use Which

| Pattern | Characteristics | Example |
|---------|-----------------|---------|
| Task Recursion | Different goals, explicit contracts, need isolation | Research → Decision → Build |
| Data Recursion | Same operation on segments, shared context, cheap | Analyze 50 papers, process log files |
| Hybrid | Task decomposition with data-heavy sub-tasks | Research node internally uses data recursion |

### Implementation

Data recursion is implemented as a **segment processor mode** on WorkNode:

```python
class WorkNode:
    # ... existing fields ...

    # Data recursion support
    segment_mode: bool = False
    segment_schema: Optional[str] = None  # Expected output format
    aggregation_fn: Optional[str] = None  # How to combine results

def execute_with_data_recursion(node: WorkNode, data: list, chunk_size: int = 10):
    """Execute node with RLM-style data recursion."""
    claims = []

    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]

        # Same node, different data segment
        result = execute_segment(node, chunk)
        claims.extend(result.claims)

        # Write to shared store immediately
        graph.save_claims(node.id, result.claims)

    # Aggregate all claims
    return aggregate_claims(claims, node.aggregation_fn)
```

---

## The Four Node Types

All nodes have the same structure, but differ in what they produce:

| Type | Purpose | Output | Typical Children |
|------|---------|--------|------------------|
| **Epistemic** | Learn something | Knowledge, findings | More epistemic, or decision |
| **Decision** | Commit to something | Binding choice | Instrumental |
| **Instrumental** | Build something | Artifacts | Validation, more instrumental |
| **Validation** | Verify something | Pass/fail | None (usually leaf) |

### The Flow

```
Epistemic → Epistemic → Decision → Instrumental → Validation
(research)   (refine)    (commit)    (build)       (verify)
```

**Decision nodes are shipping gates** - they force the transition from research to implementation. You can't build until you've committed.

---

## Context Management

### The Problem at Depth

A node at depth 5 needs context, but passing the entire tree would explode the context window. Yet alignment requires understanding the full ancestry—immediate parent for task context, root for ultimate objective.

**The tension**: Alignment patches imperfectly articulated sub-goals. Every sub-goal is imperfectly articulated (natural language is lossy), so deeper nodes need MORE ancestor context to stay aligned, but have LESS budget to spend on it.

### Hybrid Context Strategy: RLM + GOTN

Traditional approaches stuff all context into the prompt upfront. This wastes tokens on information that may not be needed and limits recursion depth.

GOTN uses a **hybrid approach** inspired by Recursive Language Models (RLM):

1. **Eager (Tier 1)**: Always-present alignment-critical context
2. **Query (Tier 2)**: On-demand access to graph via tools
3. **Lazy (Tier 3)**: External fetches only when gaps detected

```
┌────────────────────────────────────────────────────────┐
│ TIER 1: ALWAYS STUFFED (5-8% budget)                   │
│   • Goal Capsule (immutable root goal + constraints)   │
│   • Immediate parent goal + key constraint             │
│   • Production anchor reference                        │
│   Why: Prevents drift, always available                │
├────────────────────────────────────────────────────────┤
│ TIER 2: QUERY INTERFACE (Tools)                        │
│   • Full ancestor context via graph queries            │
│   • Sibling node outputs (completed peers)             │
│   • Evidence store with semantic search                │
│   • Cached research claims                             │
│   Why: Cheaper than stuffing, allows deep recursion    │
├────────────────────────────────────────────────────────┤
│ TIER 3: ON-DEMAND EXTERNAL (Lazy Fetch)                │
│   • Web search / documentation                         │
│   • Code analysis                                      │
│   • External API calls                                 │
│   Why: Only when gaps detected                         │
└────────────────────────────────────────────────────────┘
```

### When to Use Which Tier

| Scenario | Tier | Rationale |
|----------|------|-----------|
| Root goal + must-pass constraints | Tier 1 | Alignment-critical, always needed |
| Parent goal + immediate context | Tier 1 | Task relevance, always needed |
| Grandparent+ ancestry | Tier 2 | Query when confidence < threshold |
| Sibling research findings | Tier 2 | Query when synthesizing |
| External documentation | Tier 3 | Only when gaps identified |

### Goal Capsule

The **Goal Capsule** is an immutable, checksummed object that anchors alignment:

```yaml
GoalCapsule:
  id: "capsule-abc123"
  root_goal: "Build NES story content generation system"
  constraints:
    - "Age-appropriate for 3-8 years"
    - "Budget under $0.01/minute for TTS"
  success_criteria:
    - "Working story generation pipeline"
    - "Content passes quality review"
  checksum: "sha256:a1b2c3..."  # Tamper detection
```

**Every node must**:
1. Reference a Goal Capsule at spawn time
2. Validate capsule checksum before output
3. Include capsule ID in completion report

If the checksum mismatches, execution halts—the goal has drifted.

### VoI-Gated Retrieval

When should a node query Tier 2 instead of proceeding with Tier 1 only?

Use **Value of Information (VoI) gating**:

```
query_tier2 = (uncertainty × decision_impact) / query_cost > threshold

Where:
  uncertainty = 1 - confidence
  decision_impact = ancestor_depth_weight × contract_criticality
  query_cost = estimated_tokens + latency_penalty
```

**Triggers for mandatory Tier 2 retrieval**:
- Confidence < 0.7 on any must-pass criterion
- Contract constraint unresolved
- Parent explicitly requires ancestor context

### ContextFilter: Code-Based Pre-Processing

Before LLM reasoning, nodes can run **deterministic code filters** on retrieved data. This is inspired by RLM's Python REPL approach.

```python
class ContextFilter:
    """Code-based pre-processing for retrieved context."""

    def __init__(self, filter_code: str, timeout_ms: int = 1000):
        self.code = filter_code
        self.timeout = timeout_ms
        self.env = {"re": re, "json": json}  # Safe subset

    def apply(self, raw_context: dict) -> dict:
        """Execute filter code on retrieved data."""
        # Sandboxed execution - no filesystem/network
        exec(self.code, self.env, {"ctx": raw_context})
        return self.env.get("result", raw_context)
```

**Example filter for an implementation node**:

```python
# Attached to instrumental node - runs before LLM prompt
result = {
    # Only committed decisions, not exploratory research
    "decisions": [c for c in ctx["claims"] if "committed:" in c["scope"]],

    # Only configuration constraints from ancestors
    "constraints": [c for c in ctx["ancestor_claims"]
                    if c["domain"] == "configuration"],

    # Just the API spec, not the full research
    "api_specs": ctx.get("artifacts", {}).get("api_design"),
}
```

**Benefits**:
- 10x cheaper than LLM token consumption
- Deterministic, reproducible filtering
- Reduces noise before semantic processing

### Context Budget Model (Updated)

With the hybrid approach, the budget shifts:

```
┌─────────────────────────────────────────────────┐
│ CONTEXT BUDGET (100%)                           │
├─────────────────────────────────────────────────┤
│ Tier 1 (Goal Capsule + Parent)  8%   ~640 tk    │
│ Work Context                   60%   ~4800 tk   │
│ Query Tool Responses (Tier 2)  20%   ~1600 tk   │
│ Filter Script Output           7%    ~560 tk    │
│ Reserved for Output            5%    ~400 tk    │
└─────────────────────────────────────────────────┘
```

The 20% previously allocated to ancestor chain is now available for work context, with ancestors accessed on-demand via Tier 2 queries.

### Ancestor Allocation with Decay

The 20% goal chain budget is distributed across ancestors using **exponential decay with guaranteed root allocation**.

**Principle**:
- Root always gets context (alignment to ultimate objective)
- Parent gets the most (immediate task context)
- Intermediate ancestors decay exponentially

**Formula**:

```python
def allocate_ancestor_budget(depth: int, total_budget: float = 0.20) -> dict[str, float]:
    """
    Allocate goal chain budget across ancestors.

    Returns dict mapping ancestor level to budget fraction.
    Level 0 = parent, Level (depth-1) = root
    """
    if depth == 0:
        return {}  # Root node has no ancestors

    if depth == 1:
        return {"root": total_budget}  # Parent IS root

    # Guaranteed allocations
    ROOT_FLOOR = 0.05      # Root always gets at least 5%
    PARENT_FLOOR = 0.08    # Parent always gets at least 8%

    # Remaining budget for intermediate ancestors
    remaining = total_budget - ROOT_FLOOR - PARENT_FLOOR

    if depth == 2:
        # Only parent and root, no intermediates
        return {
            "parent": PARENT_FLOOR + remaining,  # 15%
            "root": ROOT_FLOOR                    # 5%
        }

    # Distribute remaining among intermediate ancestors with decay
    # Decay factor: each level up gets half the previous
    intermediate_count = depth - 2  # Exclude parent and root

    allocations = {
        "parent": PARENT_FLOOR,
        "root": ROOT_FLOOR
    }

    # Geometric series for intermediates: r + r/2 + r/4 + ...
    # Sum = r * (1 - 0.5^n) / (1 - 0.5) = r * 2 * (1 - 0.5^n)
    # Solve for r: r = remaining / (2 * (1 - 0.5^n))
    decay = 0.5
    series_sum = (1 - decay**intermediate_count) / (1 - decay)
    base_rate = remaining / series_sum if series_sum > 0 else 0

    for i in range(intermediate_count):
        level_name = f"ancestor_{i+1}"  # ancestor_1 = grandparent
        allocations[level_name] = base_rate * (decay ** i)

    return allocations
```

**Example allocations**:

```
Depth 1 (child of root):
  root: 20%

Depth 2:
  parent: 15%
  root: 5%

Depth 3:
  parent: 8%
  grandparent: 7%
  root: 5%

Depth 4:
  parent: 8%
  grandparent: 4.7%
  great-grandparent: 2.3%
  root: 5%

Depth 5:
  parent: 8%
  grandparent: 3.5%
  great-grandparent: 1.75%
  great-great-grandparent: 0.75%
  root: 5%
```

**Why this works**:
- Root context ensures alignment to ultimate objective regardless of depth
- Parent context provides immediate task relevance
- Intermediate ancestors decay because their goals are progressively summarized by their children—the parent's goal already incorporates grandparent intent

### Summarization Levels

Each ancestor is summarized to fit its budget. More budget = more detail:

```python
def summarize_for_budget(node: WorkNode, token_budget: int) -> str:
    """Summarize a node to fit within token budget."""

    if token_budget >= 400:
        # Full context: goal, all criteria, key constraints
        return f"""
        Goal: {node.goal.statement}
        Criteria: {format_criteria(node.goal.acceptance_criteria)}
        Key constraint: {get_key_constraint(node)}
        """

    elif token_budget >= 200:
        # Medium context: goal, must-pass criteria only
        must_pass = [c for c in node.goal.acceptance_criteria if c.must_pass]
        return f"""
        Goal: {node.goal.statement}
        Must satisfy: {format_criteria(must_pass)}
        """

    elif token_budget >= 100:
        # Compressed: goal summary + single constraint
        return f"""
        Goal: {summarize_goal(node.goal.statement, 60)}
        Key: {get_key_constraint(node) or 'None'}
        """

    else:
        # Minimal: just the goal essence
        return summarize_goal(node.goal.statement, 40)
```

### Progressive Summarization

As nodes complete, their context gets progressively summarized for use by descendants:

```
Depth 0 (root): Full goal statement + all criteria
     ↓ summarized for depth 2+
Depth 0 summary: Goal essence + must-pass only
     ↓ further summarized for depth 4+
Depth 0 micro: Single sentence objective

Same pattern applies to each ancestor at each level.
```

**The "summary frontier"**: At any depth, you have:
- Full detail for parent
- Medium detail for grandparent
- Compressed detail for great-grandparent
- Minimal detail for ancestors beyond that
- Always some root context

### Building the Goal Chain

```python
def build_goal_chain(node: WorkNode, load_fn, context_budget: int) -> GoalChain:
    """Build goal chain with budget-aware summarization."""

    # Calculate allocations
    allocations = allocate_ancestor_budget(node.depth, total_budget=0.20)

    # Walk up the tree
    ancestors = []
    current = node
    level = 0

    while current.parent:
        parent = load_fn(current.parent)

        # Determine budget for this level
        if level == 0:
            budget_fraction = allocations.get("parent", 0)
        elif parent.parent is None:
            budget_fraction = allocations.get("root", 0)
        else:
            budget_fraction = allocations.get(f"ancestor_{level}", 0)

        token_budget = int(context_budget * budget_fraction)

        # Summarize to fit budget
        summary = summarize_for_budget(parent, token_budget)

        ancestors.append(GoalChainEntry(
            node_id=parent.id,
            depth=parent.depth,
            goal_summary=summary,
            mode=parent.mode.value,
            token_budget=token_budget,
        ))

        current = parent
        level += 1

    return GoalChain(
        root=ancestors[-1] if ancestors else None,
        ancestors=ancestors[:-1],  # Exclude root
        current=make_current_entry(node),
        total_depth=node.depth,
    )
```

### Evidence Selection

The 15% evidence budget uses **semantic relevance**, not "include everything":

```python
def select_evidence(node: WorkNode, evidence_pool: list[Evidence],
                    token_budget: int) -> list[Evidence]:
    """Select most relevant evidence for this node's goal."""

    # Score each evidence item by relevance to current goal
    scored = []
    for ev in evidence_pool:
        relevance = compute_semantic_similarity(
            ev.summary,
            node.goal.statement
        )
        scored.append((relevance, ev))

    # Sort by relevance, take top items that fit budget
    scored.sort(reverse=True, key=lambda x: x[0])

    selected = []
    used_tokens = 0

    for relevance, ev in scored:
        ev_tokens = estimate_tokens(ev.to_context())
        if used_tokens + ev_tokens <= token_budget:
            selected.append(ev)
            used_tokens += ev_tokens

        # Stop if relevance drops too low
        if relevance < 0.3:
            break

    return selected
```

### Output Collapse

When a node completes, its internal trace collapses to a summary for parent consumption:

```python
# Before collapse (full trace - could be 10k+ tokens)
{
    "id": "node-xyz",
    "goal": "Evaluate ElevenLabs for children's TTS",
    "criteria": [...],
    "children": [...],      # Full child trees
    "trace": [...],         # Execution log
    "evidence": [...],      # All gathered evidence
    "outputs": [...]
}

# After collapse (summary - ~200 tokens)
{
    "id": "node-xyz",
    "status": "complete",
    "confidence": 0.87,
    "summary": "ElevenLabs suitable: good voice quality (4.2/5), acceptable cost ($0.008/min), stable API",
    "key_findings": [
        "Voice quality rated 4.2/5 in children's content test",
        "Cost $0.008/minute within budget",
        "99.9% uptime over past 6 months"
    ],
    "deliverable_ref": "outputs/elevenlabs-evaluation.md"
}
```

Parents see the summary. The full trace is persisted to disk but not loaded into context.

### Fail-Fast on Budget Overflow

Before execution, validate that the prompt fits:

```python
def validate_context_budget(prompt: str, max_tokens: int) -> None:
    """Fail fast if prompt exceeds budget."""
    actual = estimate_tokens(prompt)
    if actual > max_tokens:
        raise ContextOverflowError(
            f"Prompt ({actual} tokens) exceeds budget ({max_tokens}). "
            f"Reduce evidence or increase summarization."
        )
```

This prevents discovering overflow mid-execution.

---

## How It Relates to Claude Code

GOTN orchestrates Claude Code, not replaces it.

```
GOTN                          Claude Code
─────                         ───────────
Workflow orchestration   →    Task agents
Alignment validation     →    (GOTN provides this)
Confidence tracking      →    (GOTN provides this)
Context routing          →    Skill selection
                              Tool execution
                              File operations
```

Each node executes via Claude Code:
- Epistemic nodes → deep-research skill, web search, Explore
- Decision nodes → triad-orchestrator, analysis
- Instrumental nodes → code tools, file operations
- Validation nodes → test runners

GOTN adds the meta-layer: alignment, confidence, recursion management.

---

## Data Strategy: Kuzu Graph Database

GOTN's data model is naturally a graph - nodes with typed relationships, ancestry traversal, dependency edges. We use **Kuzu**, an embedded graph database, for storage and queries.

### Why Kuzu

| Need | Solution |
|------|----------|
| Tree traversal (ancestors, descendants) | Native Cypher path queries |
| Relationship queries (parent, children, enables) | Graph-native, O(1) edge traversal |
| Embedded deployment | Single directory, no server |
| Python integration | `pip install kuzu`, in-process |

### Schema

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

### Tier 2 Query Tools

Nodes access the graph via these tool functions (exposed during execution):

```python
# Query tools available to executing nodes
def query_ancestors(depth_limit: int = None) -> list[GoalSummary]:
    """Fetch ancestor goals and constraints."""

def query_claims(domain: str = None, min_confidence: float = 0.5) -> list[Claim]:
    """Fetch relevant claims from ancestor nodes."""

def query_decisions() -> list[Commitment]:
    """Fetch all committed decisions in ancestry."""

def query_sibling_outputs(status: str = "complete") -> list[Output]:
    """Fetch outputs from sibling nodes."""

def search_evidence(query: str, limit: int = 10) -> list[Evidence]:
    """Semantic search over evidence store."""

def get_goal_capsule() -> GoalCapsule:
    """Get the immutable goal capsule for this tree."""
```

### Key Queries

```cypher
-- Get full ancestry (goal chain)
MATCH (n:WorkNode {id: $node_id})-[:PARENT*]->(ancestor)
RETURN ancestor.id, ancestor.goal, ancestor.depth
ORDER BY ancestor.depth DESC

-- Get all descendants
MATCH (n:WorkNode {id: $node_id})<-[:PARENT*]-(descendant)
RETURN descendant

-- Find ready nodes (scheduling)
MATCH (n:WorkNode {status: 'ready'})
RETURN n ORDER BY n.depth DESC, n.created_at

-- Check if all children are terminal
MATCH (parent:WorkNode {id: $node_id})<-[:PARENT]-(child)
WHERE child.status NOT IN ['complete', 'failed', 'cancelled', 'degraded']
RETURN count(child) AS pending_children

-- Find research anchored to a decision
MATCH (research:WorkNode)-[:ANCHORED_TO]->(decision:WorkNode {mode: 'decision'})
WHERE decision.id = $decision_id
RETURN research

-- Validate no cycles (before adding edge)
MATCH path = (target:WorkNode {id: $target_id})-[:DEPENDS_ON|PARENT*]->(source:WorkNode {id: $source_id})
RETURN count(path) > 0 AS would_create_cycle
```

### Storage Layout

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

### Context Fingerprinting

With Kuzu, fingerprinting becomes a graph query:

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

### Python Integration

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

### Benefits Over SQLite

| Operation | SQLite | Kuzu |
|-----------|--------|------|
| Get ancestors | Recursive CTE (verbose) | `[:PARENT*]` (one line) |
| Check cycles | Multiple queries | Single path query |
| Find connected subgraph | Complex joins | Native traversal |
| Add relationship types | Schema migration | Just add REL TABLE |

The data model matches the domain, so queries are intuitive.

---

## Implementation Approach

Given that alignment, confidence, and recursion are all essential:

### Keep from Current Implementation

- **WorkNode structure** - The self-similar node model
- **State machine** - Node lifecycle management
- **Alignment module** - Goal chain, alignment scoring, constraint propagation
- **Confidence aggregation** - Per-criterion tracking, must-pass logic
- **Scheduler** - Manages execution order, concurrency

### Simplify or Remove

- **Complex edge types** - Keep spawned_by and depends_on, simplify others
- **VOI gating** - Can add later if needed
- **Semantic cache** - Nice to have, not essential for core

### Add

- **Workflow definitions** - YAML files that define common patterns
- **Better context compression** - More sophisticated goal chain building
- **Output collapse** - Automatic summarization on completion

---

## Summary

**GOTN is a recursive orchestration system combining goal-oriented task networks with RLM-inspired context efficiency:**

### Core Principles

1. **Goals decompose recursively** - Each level can spawn children as needed
2. **Every level has the same structure** - Self-similar nodes all the way down
3. **Alignment is automatic** - Children validate against Goal Capsule before spawning
4. **Confidence gates progress** - Nodes complete when they have "enough"
5. **Constraints propagate** - Must-pass criteria cascade to all descendants

### Context Efficiency (RLM Synthesis)

6. **Three-tier context** - Eager (Tier 1) + Query (Tier 2) + Lazy (Tier 3)
7. **Goal Capsule anchoring** - Immutable, checksummed root goal prevents drift
8. **Code-based filtering** - ContextFilter scripts reduce token consumption 10x
9. **Dual recursion** - Task recursion for goals, data recursion for large datasets
10. **VoI-gated retrieval** - Query Tier 2 only when value exceeds cost

### Trade-off Summary

| Scenario | Strategy |
|----------|----------|
| Alignment-critical context | Tier 1 (always stuff) |
| Ancestor research | Tier 2 (query on demand) |
| External documentation | Tier 3 (lazy fetch) |
| 50+ papers to analyze | Data recursion (no child nodes) |
| Research → Decision → Build | Task recursion (explicit contracts) |

The system handles the manual orchestration burden while ensuring that no matter how deep the decomposition goes, every node serves the root objective—with efficient context access that scales to arbitrary depth.
