# GOTN Architecture

## Overview

Goal-Oriented Task Network (GOTN) is a recursive workflow orchestration model that unifies knowledge acquisition and artifact production under a single abstraction: the **WorkNode**.

## The Core Problem

Traditional workflow systems face a tension:

| Approach | Strength | Weakness |
|----------|----------|----------|
| **Question-driven** | Good for research/discovery | Doesn't encode outcomes; can spiral infinitely |
| **Objective-driven** | Good for delivery | Assumes you know what to build; brittle to unknowns |

Real-world projects require both: you need to **learn** things to **build** things, and building reveals what you still need to learn.

## The Solution: Unified WorkNode

GOTN resolves this by recognizing that questions and objectives are the same thing at different abstraction levels:

```
"What TTS provider should we use?"
    ↓ reframe as objective
"Determine optimal TTS provider for children's narration"
    ↓ with success criteria
"Achieve ≥0.8 confidence in TTS selection based on quality, cost, and API availability"
```

Both are **goals with acceptance criteria**. The only difference is what they produce:
- Questions produce **knowledge** (findings, claims)
- Build tasks produce **artifacts** (code, content, configs)
- Decisions produce **commitments** (binding choices with rationale)

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     INTENT LAYER                             │
│  What are we trying to achieve? Why does this node exist?    │
│  • Goal statement (action-oriented)                          │
│  • Acceptance criteria                                       │
│  • Parent relationship (who spawned us)                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     EVIDENCE LAYER                           │
│  How confident are we? What do we know?                      │
│  • Claims (propositions with confidence + expiry)            │
│  • Evidence items (sources, experiments, validations)        │
│  • Aggregated confidence score                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     CONTROL LAYER                            │
│  When do we proceed? When do we stop?                        │
│  • Autonomy gate (confidence threshold for auto-proceed)     │
│  • Budget (time, tokens, steps)                              │
│  • Exit policy (on success, on exhaustion, on blocked)       │
└─────────────────────────────────────────────────────────────┘
```

## Self-Similar Pattern

Every WorkNode, regardless of mode, follows the same lifecycle:

```
┌─────────────────────────────────────────────────────────────┐
│                      WorkNode Lifecycle                      │
│                                                              │
│  PENDING → READY → RUNNING → [BLOCKED] → COMPLETE           │
│                        │          │           │              │
│                        │          ▼           │              │
│                        │    spawn children    │              │
│                        │          │           │              │
│                        │          ▼           │              │
│                        │    children run      │              │
│                        │          │           │              │
│                        │          ▼           │              │
│                        └──── resume ──────────┘              │
│                                                              │
│  Alternative exits:                                          │
│  • DEGRADED (budget exhausted, minimal viable output)        │
│  • ESCALATED (human intervention required)                   │
│  • FAILED (unrecoverable error)                              │
└─────────────────────────────────────────────────────────────┘
```

**Self-similarity**: A child WorkNode has the exact same structure. "Research TTS options" spawns "Evaluate ElevenLabs v3" which spawns "Test emotive tag performance"—each following the same cycle.

## The DAG Structure

WorkNodes form a Directed Acyclic Graph with typed edges:

| Edge Type | Meaning | Blocking? |
|-----------|---------|-----------|
| `depends_on` | Must complete before I can start | Yes |
| `informs` | Findings are useful but not required | No |
| `blocks` | Risk that could halt progress | Conditional |
| `enables` | Completion unlocks new possibilities | No |

```
┌──────────────────┐
│ ROOT OBJECTIVE   │
│ "Build product"  │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐  ┌───────┐
│ R1    │  │ R2    │  (Research nodes)
│ "What │  │ "What │
│ tech?"│  │ UX?"  │
└───┬───┘  └───┬───┘
    │          │
    │   ┌──────┘
    ▼   ▼
┌───────────┐
│ D1        │  (Decision node - SHIPPING GATE)
│ "Commit   │
│ to stack" │
└─────┬─────┘
      │
      ▼
┌───────────┐
│ B1        │  (Build node)
│ "Build    │
│ feature"  │
└─────┬─────┘
      │
      ▼
┌───────────┐
│ V1        │  (Validate node)
│ "Test &   │
│ verify"   │
└───────────┘
```

## Node Modes

### Epistemic Mode (Research)

**Purpose**: Acquire knowledge to reduce uncertainty

```yaml
mode: epistemic
goal: "Determine optimal TTS provider"
deliverable_type: knowledge
outputs:
  - claims: [{proposition, evidence, confidence, expiry}]
  - findings: [{source, summary, relevance}]
```

### Instrumental Mode (Build)

**Purpose**: Produce artifacts

```yaml
mode: instrumental
goal: "Build TTS pipeline"
deliverable_type: artifact
outputs:
  - artifacts: [{path, type, hash, metadata}]
```

### Decision Mode (Commit)

**Purpose**: Make binding choices that downstream work depends on

```yaml
mode: decision
goal: "Commit to ElevenLabs v3 as TTS provider"
deliverable_type: commitment
outputs:
  - commitment:
      choice_set: [ElevenLabs, Google, Amazon]
      selected: ElevenLabs
      rationale: "Best emotive quality, acceptable cost"
      residual_risks: ["Rate limits at scale"]
      rollback_plan: "Abstract TTS interface allows swap"
```

## Confidence Model

### Per-Criterion Confidence

Each acceptance criterion has its own confidence score:

```yaml
acceptance_criteria:
  - id: quality
    description: "TTS output sounds natural"
    confidence: 0.85
    evidence: [exp-001, exp-002]
  - id: cost
    description: "Cost < $0.01 per minute"
    confidence: 0.95
    evidence: [pricing-doc]
  - id: api_stability
    description: "API is stable and well-documented"
    confidence: 0.70
    evidence: [docs-review]
```

### Aggregation Strategy

```python
def aggregate_confidence(node):
    must_pass = node.autonomy_gate.must_pass_criteria
    must_pass_scores = [node.confidence.by_criterion[c] for c in must_pass]
    other_scores = [v for k, v in node.confidence.by_criterion.items()
                    if k not in must_pass]

    # Safety-critical: use minimum of must-pass
    must_pass_min = min(must_pass_scores) if must_pass_scores else 1.0

    # Others: weighted mean
    other_mean = weighted_mean(other_scores) if other_scores else 1.0

    # Risk flags can force lower aggregate
    if 'safety' in node.autonomy_gate.risk_flags:
        return min(must_pass_min, other_mean)

    return (must_pass_min * 0.6) + (other_mean * 0.4)
```

## Autonomy Decisions

```
┌─────────────────────────────────────────────────────────────┐
│                    Confidence Check                          │
│                                                              │
│   confidence >= proceed_threshold?                           │
│        │                                                     │
│   YES  │  NO                                                 │
│   ▼    │  ▼                                                  │
│  Auto  │  confidence >= 0.5?                                 │
│  proceed│       │                                            │
│        │  YES   │  NO                                        │
│        │  ▼     │  ▼                                         │
│        │ Spawn  │ Human                                      │
│        │ research│ review                                    │
│        │ to fill │ required                                  │
│        │ gaps    │                                           │
└─────────────────────────────────────────────────────────────┘
```

### Autonomy Gate Configuration

```yaml
autonomy_gate:
  proceed_threshold: 0.8      # Auto-proceed above this
  must_pass_criteria: [safety, appropriateness]
  risk_flags: [safety]        # Forces stricter evaluation
  human_required: false       # Override to always require human
  escalation_triggers:
    - "cost exceeds $100"
    - "affects production data"
```

## Shipping Gates

**Problem**: Epistemic nodes could research forever without producing anything.

**Solution**: Every research branch must terminate in a **Decision node** (shipping gate) that explicitly commits to stop learning and start building.

```
[Epistemic] "What are the TTS options?"
    │
    ├─► [Epistemic] "Evaluate ElevenLabs"
    │       └─► findings ladder up
    │
    └─► [Epistemic] "Evaluate Google TTS"
            └─► findings ladder up
    │
    ▼
[Decision] "Commit to ElevenLabs v3"  ◄── SHIPPING GATE
    │
    ▼
[Instrumental] "Build TTS integration"
```

**Rule**: A research node without a downstream Decision node is flagged for review. Why are we learning this if we're not going to commit to something?

## VOI Gating (Value of Information)

Before spawning a child research node:

```python
def should_spawn_research(parent, question):
    voi = estimate_value_of_information(question, parent.goal)
    cost = estimate_research_cost(question)

    # Deadline pressure
    if parent.goal.deadline:
        time_remaining = parent.goal.deadline - now()
        deadline_factor = time_remaining / parent.budget.time
    else:
        deadline_factor = 1.0

    # Don't research if VOI < cost or deadline too close
    if voi < cost or deadline_factor < 0.2:
        return False

    return True
```

## Exit Policies

Every node defines what happens when it can't complete normally:

```yaml
exit_policy:
  on_success: complete          # Normal completion
  on_budget_exhausted: degrade  # Produce minimal viable output
  on_blocked: spawn_child       # Create child to resolve blocker
  degradation_output: "Use ElevenLabs v3 as default (known working)"
```

### Exit States

| State | Meaning |
|-------|---------|
| `complete` | All criteria met, deliverable produced |
| `degraded` | Budget exhausted, minimal viable output produced |
| `escalated` | Human intervention required |
| `failed` | Unrecoverable error, no output |

## Global Circuit Breakers

Prevent runaway recursion:

```python
GLOBAL_LIMITS = {
    'MAX_DEPTH': 5,              # Maximum nesting level
    'MAX_NODES_PER_ROOT': 200,   # Maximum nodes in one tree
    'MAX_EPISTEMIC_RATIO': 0.4,  # No more than 40% research nodes
    'CYCLE_DETECTION': True,     # Runtime DAG validation
}
```

## Performance Optimizations

### Semantic Caching

Cache research findings to avoid redundant work:

```python
# Key: hash of goal + context
cache_key = hash(goal.statement + context_fingerprint)

# Before spawning research
if cache.has(cache_key) and not cache.expired(cache_key):
    return cache.get(cache_key)  # Return cached claims
```

### Cascading Cancellation

When a parent achieves sufficient confidence from one child, cancel sibling research:

```python
def on_child_complete(parent, child):
    new_confidence = aggregate_confidence(parent)
    if new_confidence >= parent.autonomy_gate.proceed_threshold:
        for sibling in parent.children:
            if sibling.mode == 'epistemic' and sibling.status == 'running':
                sibling.cancel()  # No longer needed
```

### Context Window Management

Completed nodes collapse to summaries:

```python
def collapse_node(node):
    return {
        'id': node.id,
        'status': 'complete',
        'deliverable': node.outputs[-1],  # Just the final output
        'confidence': node.confidence.aggregate,
        # Internal trace is NOT passed to parent
    }
```

## Implementation Checklist

1. [ ] Define WorkNode schema (TypeScript/Python interface)
2. [ ] Implement node state machine (pending → complete)
3. [ ] Build DAG manager with cycle detection
4. [ ] Implement confidence aggregation
5. [ ] Build autonomy decision engine
6. [ ] Add shipping gate enforcement
7. [ ] Implement VOI gating
8. [ ] Add global circuit breakers
9. [ ] Build semantic cache
10. [ ] Create CLI orchestrator
11. [ ] Add HITL notification system

## References

- **HTN Planning**: Erol, Hendler, Nau (1994) - Hierarchical Task Network Planning
- **BDI Architecture**: Rao & Georgeff (1995) - Belief-Desire-Intention model
- **OODA Loop**: Boyd (1987) - Observe-Orient-Decide-Act
- **Goal Trees**: Dardenne, van Lamsweerde, Fickas (1993) - Goal-directed requirements acquisition
