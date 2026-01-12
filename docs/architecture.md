# GOTN Architecture

## What Problem Are We Solving?

You ask Claude to do something complex: *"Build me a bedtime story app with text-to-speech."*

Claude starts working. It researches TTS providers. Then it researches more. Then it finds an interesting tangent about voice synthesis. Three hours later, you have 47 pages of research and no app.

**Or the opposite happens**: Claude picks the first TTS provider it finds, builds something quickly, and you discover later it made a poor choice that requires a rewrite.

The core tension:

| Behavior | When It Helps | When It Hurts |
|----------|---------------|---------------|
| **Research more** | Avoids bad decisions | Can spiral forever |
| **Decide faster** | Gets things done | Commits to bad choices |

GOTN tries to solve this by making the tradeoff **explicit and tunable**.

---

## The Core Hypothesis

**Hypothesis**: If Claude can track *how confident* it is about each piece of work, it can make better decisions about when to research more vs. commit and build.

Instead of implicit judgment ("I think I know enough"), GOTN makes it explicit:

```
Goal: Select a TTS provider
Criteria:
  - Voice quality is acceptable → 85% confident (tested 3 providers)
  - Cost is under budget → 95% confident (verified pricing)
  - API is stable → 60% confident (only read docs, no testing)

Overall: 75% confident

Threshold to proceed: 80%

Decision: Need more research on API stability before committing
```

**Will this work?** That's the key question. It depends on:

1. **Can Claude accurately self-assess confidence?** If Claude says "85% confident" but it's actually wrong 50% of the time, the whole system fails.

2. **Can we detect goal drift?** If a sub-task wanders off-topic, can we catch it before wasting resources?

3. **Is the overhead worth it?** All this tracking has a cost. Is it better than just letting Claude work naturally?

---

## What GOTN Actually Does

GOTN is a **meta-layer** on top of Claude's work. Think of it as a project manager that:

1. **Tracks goals** - What are we trying to achieve?
2. **Tracks confidence** - How sure are we about each piece?
3. **Enforces thresholds** - Don't commit until confidence is high enough
4. **Prevents drift** - Make sure sub-tasks relate to the parent goal
5. **Knows when to stop** - Budget limits prevent infinite research

### The WorkNode: One Universal Abstraction

Everything in GOTN is a **WorkNode**. Whether you're researching, building, or deciding, it's the same structure:

```
WorkNode:
  goal: "What are we trying to do?"
  criteria: "How do we know we succeeded?"
  confidence: "How sure are we?" (0-100%)
  threshold: "How sure do we need to be?" (e.g., 80%)
  budget: "How much time/effort can we spend?"
  children: "What sub-tasks did we spawn?"
```

The insight: **questions and tasks are the same thing** at different abstraction levels.

```
Question: "What TTS provider should we use?"
     ↓ reframe
Task: "Achieve 80% confidence in TTS provider selection"
     ↓ with criteria
- Voice quality meets needs (test samples)
- Cost within budget (verify pricing)
- API is reliable (test integration)
```

### The Four Modes

WorkNodes come in four flavors, based on what they produce:

| Mode | Purpose | Output |
|------|---------|--------|
| **Epistemic** | Learn something | Knowledge (claims + confidence) |
| **Instrumental** | Build something | Artifact (code, content, config) |
| **Decision** | Commit to something | Binding choice + rationale |
| **Validation** | Verify something | Pass/fail + evidence |

**The key insight**: Research (epistemic) nodes must eventually lead to Decision nodes. You can't research forever—at some point you have to commit and build.

```
[Research TTS options] → [Evaluate Provider A] → [Evaluate Provider B]
                                    ↓                      ↓
                              [DECISION: Pick Provider A]
                                    ↓
                              [Build integration]
```

The Decision node is a **shipping gate**—it forces you to stop learning and start doing.

---

## How It Relates to Claude Code

Here's the honest question: **Do we need GOTN, or can Claude Code already do this?**

Claude Code already has:
- **Task agents** for delegation
- **Deep research skill** for thorough investigation
- **TodoWrite** for tracking progress
- **AskUserQuestion** for human-in-the-loop

So what does GOTN add?

| Capability | Claude Code | GOTN Adds |
|------------|-------------|-----------|
| Research | Deep research skill | **Confidence tracking** - know when you've researched "enough" |
| Delegation | Task agents | **Goal alignment** - ensure sub-tasks serve the parent goal |
| Progress | TodoWrite | **State machine** - formal lifecycle with clear transitions |
| HITL | AskUserQuestion | **Escalation policies** - know *when* to ask based on confidence |
| Budget | Timeout flags | **Resource tracking** - tokens, time, steps with enforcement |

**The case for GOTN**: Claude Code gives you the tools, but GOTN gives you the *discipline*. It's the difference between having a hammer and having a construction plan.

**The case against GOTN**: Maybe the overhead isn't worth it. Maybe Claude's natural judgment is good enough for most tasks, and formal tracking just adds friction.

### Potential Simplification

Instead of bespoke Python code, we could implement GOTN as:
- A **Claude Code skill** that enforces the discipline
- Using **existing tools** (Task, TodoWrite, AskUserQuestion) under the hood
- With a **simple state file** (YAML/JSON) tracking goals and confidence

The question is whether the formal structure helps or hinders.

---

## The Confidence Model (Critical Component)

This is where GOTN succeeds or fails. The entire system depends on confidence scores being meaningful.

### How Confidence Works

Each criterion on a goal has its own confidence:

```yaml
goal: "Select TTS provider"
criteria:
  - description: "Voice quality acceptable"
    confidence: 0.85
    evidence: ["Tested 3 providers", "User feedback positive"]

  - description: "Cost within budget"
    confidence: 0.95
    evidence: ["Verified pricing docs", "Calculated monthly cost"]

  - description: "API stable"
    confidence: 0.60
    evidence: ["Read documentation"]  # No actual testing
```

### Aggregation

The overall confidence combines criteria, with **must-pass** criteria acting as a floor:

```
must_pass criteria → use MINIMUM (if any fails, overall fails)
optional criteria → use WEIGHTED AVERAGE

Example:
  must_pass: [voice_quality: 0.85, cost: 0.95] → min = 0.85
  optional: [api_stability: 0.60, docs: 0.90] → avg = 0.75

  overall = 0.6 * must_pass_min + 0.4 * optional_avg
          = 0.6 * 0.85 + 0.4 * 0.75
          = 0.81
```

### The Calibration Problem

**This is the biggest risk.** If Claude says "85% confident" but is actually right only 60% of the time, the thresholds become meaningless.

Ways to address this:
1. **Evidence requirements** - Confidence must be backed by specific evidence
2. **Validation nodes** - Explicitly test claims before proceeding
3. **Calibration feedback** - Track historical accuracy and adjust

---

## Goal Alignment (Preventing Drift)

The second critical component. When you spawn sub-tasks, they can drift away from the original goal.

**Example of drift:**
```
Root: "Build a bedtime story app"
  └── "Research TTS providers"
       └── "Understand voice synthesis technology"
            └── "Study acoustic phonetics"  ← DRIFT! Not helping build the app
```

### How Alignment Works

Before spawning a child node, GOTN checks if the child goal relates to the parent and root goals.

**Current implementation**: Keyword matching with concept expansion
- "TTS" relates to "voice", "speech", "audio"
- "authentication" relates to "JWT", "OAuth", "login"

**Limitation**: Keyword matching is crude. Semantic embeddings would be better but add complexity.

**The question**: Is simple keyword matching good enough, or do we need more sophisticated NLP?

---

## The Lifecycle (State Machine)

Every WorkNode follows the same lifecycle:

```
PENDING → READY → RUNNING → COMPLETE
                    ↓
                 BLOCKED (waiting for children)
                    ↓
                 RUNNING (children done)
                    ↓
           COMPLETE / DEGRADED / ESCALATED / FAILED
```

### Key States

| State | Meaning |
|-------|---------|
| **PENDING** | Created but dependencies not met |
| **READY** | Dependencies met, waiting to execute |
| **RUNNING** | Actively working |
| **BLOCKED** | Spawned children, waiting for them |
| **COMPLETE** | Confidence threshold met |
| **DEGRADED** | Budget exhausted, partial output |
| **ESCALATED** | Needs human decision |
| **FAILED** | Unrecoverable error |

### Why a Formal State Machine?

It might seem like overkill, but the state machine provides:
- **Clear invariants** - You can't be RUNNING without dependencies met
- **Deterministic transitions** - Same inputs always produce same state
- **Debuggability** - Can trace exactly how a node reached its state

---

## Shipping Gates (Forcing Decisions)

**Problem**: Research can spiral forever. There's always more to learn.

**Solution**: Every research branch must terminate in a **Decision node**.

```
[Research] → [Research] → [Research] → [DECISION] → [Build]
```

The Decision node is a **shipping gate**. It forces you to:
1. Stop gathering information
2. Commit to a choice
3. Document the rationale
4. Acknowledge residual risks

**Why this matters**: Without shipping gates, you can have 100 research nodes with no output. The gate ensures research serves a purpose.

---

## Resource Limits (Circuit Breakers)

Prevent runaway behavior:

```python
MAX_DEPTH = 5           # No more than 5 levels of nesting
MAX_NODES = 200         # No more than 200 nodes per tree
MAX_EPISTEMIC = 0.4     # No more than 40% research nodes
```

**Why these exist**: Without limits, a malformed goal or edge case could spawn infinite nodes. The limits provide a safety net.

---

## Will It Actually Work?

### Reasons for Optimism

1. **Structure helps** - Having explicit criteria and thresholds forces clearer thinking
2. **Confidence is useful** - Even imperfect confidence tracking is better than none
3. **Alignment catches errors** - Even crude drift detection catches obvious mistakes
4. **Shipping gates work** - Forcing decisions prevents analysis paralysis

### Reasons for Skepticism

1. **Overhead** - All this tracking might slow things down without adding value
2. **Calibration** - If confidence isn't calibrated, thresholds are meaningless
3. **Complexity** - More code means more bugs and maintenance
4. **Duplication** - Claude Code already handles much of this implicitly

### What Would Prove It Works?

1. **Complex task completion** - Can GOTN complete a multi-step project that Claude alone would fumble?
2. **Appropriate escalation** - Does it ask for help at the right times?
3. **No infinite loops** - Does it actually stop researching when appropriate?
4. **Goal coherence** - Do all sub-tasks actually contribute to the root goal?

---

## Implementation Options

### Option A: Full Python Implementation (Current)

```
gotn/
├── node.py       # WorkNode data model
├── state.py      # State machine
├── scheduler.py  # DAG execution
├── executor.py   # Claude subprocess
├── alignment.py  # Goal drift detection
├── confidence.py # Confidence aggregation
└── cli.py        # Command interface
```

**Pros**: Full control, testable, explicit
**Cons**: Lots of code to maintain, might duplicate Claude Code

### Option B: Claude Code Skill (Lighter)

A single skill file that:
- Uses TodoWrite for tracking
- Uses Task for delegation
- Uses AskUserQuestion for HITL
- Maintains state in a simple YAML file

**Pros**: Leverages existing tools, less code
**Cons**: Less control, harder to test

### Option C: Hybrid

Use GOTN for the meta-layer (goals, confidence, alignment) but delegate execution to Claude Code's existing tools.

**Pros**: Best of both worlds
**Cons**: Integration complexity

---

## Next Steps to Validate

1. **Test confidence calibration** - Give Claude tasks with known answers, measure accuracy of confidence scores

2. **Test goal alignment** - Deliberately try to drift off-topic, see if detection catches it

3. **Test shipping gates** - Create research-heavy tasks, verify they eventually produce decisions

4. **Compare to baseline** - Same task with and without GOTN, measure quality and efficiency

5. **Simplification experiment** - Try Option B (pure skill), compare to Option A (Python)

---

## Summary

GOTN is a hypothesis: **explicit confidence tracking and goal alignment will help Claude work autonomously on complex tasks**.

The system adds:
- Structured goal tracking with criteria
- Confidence scores with thresholds
- Goal alignment validation
- Shipping gates to force decisions
- Resource limits to prevent runaway

Whether this is better than just using Claude Code directly is an open question. The value depends on:
- How well confidence scores calibrate
- How much the structure helps vs. hinders
- Whether the complexity is worth the discipline

The best way to find out is to try it on real tasks and measure.
