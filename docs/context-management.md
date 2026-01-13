# Context Management

## Overview

GOTN uses a three-tier context strategy to manage information flow across deep goal trees. This document covers the implementation details of context budgeting, VoI-gated retrieval, and ancestor summarization.

## Context Budget Allocation

### Budget Distribution

```python
class ContextBudget:
    """Token budget allocation across context tiers."""

    def __init__(self, total_tokens: int = 8000):
        self.total = total_tokens
        self.tier1_budget = int(total_tokens * 0.08)   # Goal chain, capsule
        self.tier2_budget = int(total_tokens * 0.20)   # Query responses
        self.work_budget = int(total_tokens * 0.60)    # Claude's reasoning
        self.reserve = int(total_tokens * 0.12)        # Output buffer
```

### Ancestor Allocation with Decay

The goal chain budget is distributed across ancestors using exponential decay with guaranteed root allocation.

**Principle**:
- Root always gets context (alignment to ultimate objective)
- Parent gets the most (immediate task context)
- Intermediate ancestors decay exponentially

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

### Example Allocations

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
- Intermediate ancestors decay because their goals are progressively summarized by their children

## VoI-Gated Retrieval

### Value of Information Calculation

```python
@dataclass
class VoIFactors:
    """Factors for Value of Information calculation."""
    uncertainty: float      # 1 - confidence
    decision_impact: float  # Higher for decision/validation modes
    query_cost: float       # Estimated cost of Tier 2 query

    @property
    def value(self) -> float:
        """Calculate VoI score."""
        return (self.uncertainty * self.decision_impact) / self.query_cost

VOI_THRESHOLD = 0.3  # Query Tier 2 when VoI >= threshold
```

### When to Query Tier 2

```python
def should_query_tier2(node: WorkNode, context: Context) -> bool:
    """Determine if Tier 2 query is worthwhile."""
    voi = VoIFactors(
        uncertainty=1 - node.confidence.aggregate,
        decision_impact=get_decision_impact(node.mode),
        query_cost=1.0 + (node.depth * 0.1),  # Deeper = more expensive
    )
    return voi.value >= VOI_THRESHOLD

def get_decision_impact(mode: NodeMode) -> float:
    """Decision impact by mode."""
    return {
        NodeMode.DECISION: 1.0,     # Highest impact
        NodeMode.VALIDATION: 0.8,
        NodeMode.INSTRUMENTAL: 0.5,
        NodeMode.EPISTEMIC: 0.3,    # Lowest impact
    }.get(mode, 0.5)
```

## Summarization

### Budget-Aware Summarization

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
     | summarized for depth 2+
Depth 0 summary: Goal essence + must-pass only
     | further summarized for depth 4+
Depth 0 micro: Single sentence objective

Same pattern applies to each ancestor at each level.
```

**The "summary frontier"**: At any depth, you have:
- Full detail for parent
- Medium detail for grandparent
- Compressed detail for great-grandparent
- Minimal detail for ancestors beyond that
- Always some root context

## Goal Chain Building

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

## Evidence Selection

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

## Output Collapse

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

## Budget Validation

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

## ContextFilter

Before LLM reasoning, nodes can run **deterministic code filters** on retrieved data:

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
