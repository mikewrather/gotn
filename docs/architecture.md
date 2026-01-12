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

A node at depth 5 needs context, but passing the entire tree would explode the context window.

### The Solution: Compressed Context

Each node receives:

1. **Goal Chain** (~500 tokens) - Compressed ancestry
2. **Relevant Outputs** - Only from direct ancestors and siblings
3. **Inherited Constraints** - Must-pass criteria from above

```python
def build_context(node):
    return {
        "goal_chain": compress_ancestry(node),  # ~500 tokens
        "parent_output": node.parent.outputs[-1] if node.parent else None,
        "sibling_outputs": [s.outputs[-1] for s in get_siblings(node) if s.complete],
        "inherited_constraints": node.inherited_constraints,
    }
```

### Output Collapse

When a node completes, its internal trace collapses to a summary:

```python
# Before collapse (full trace)
{
    "id": "node-xyz",
    "goal": "Evaluate ElevenLabs",
    "criteria": [...],
    "children": [...],  # Full child trees
    "trace": [...],     # Execution log
    "outputs": [...]
}

# After collapse (summary only)
{
    "id": "node-xyz",
    "status": "complete",
    "confidence": 0.87,
    "summary": "ElevenLabs suitable: good voice quality, acceptable cost",
    "key_findings": ["Voice quality 4.2/5", "Cost $0.008/min", "API stable"]
}
```

Parents see the summary, not the full trace. This keeps context manageable at scale.

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

**GOTN is a recursive orchestration system where:**

1. **Goals decompose recursively** - Each level can spawn children as needed
2. **Every level has the same structure** - Self-similar nodes all the way down
3. **Alignment is automatic** - Children validate against full ancestry before spawning
4. **Confidence gates progress** - Nodes complete when they have "enough"
5. **Constraints propagate** - Must-pass criteria cascade to all descendants
6. **Context is compressed** - Goal chains keep context manageable at depth

The system handles the manual orchestration burden while ensuring that no matter how deep the decomposition goes, every node serves the root objective.
