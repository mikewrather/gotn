# GOTN Architecture

## What Problem Are We Solving?

When you ask Claude to "build me a sleep app", it just... builds it. Uses training data, makes reasonable choices, ships something. That's fine for simple tasks.

But for complex projects - like building a story content generation system - you need a **research-to-implementation workflow**:

1. Research each component
2. Consolidate the research
3. Evaluate findings for your specific use case
4. Create an implementation plan
5. Break the plan into segments
6. Build a test POC
7. Execute the full plan
8. Iterate

Right now, **you have to orchestrate this manually**:

```
You: "Research TTS providers for children's narration"
Claude: [does research]
You: "Now consolidate those findings"
Claude: [consolidates]
You: "Evaluate which option fits our use case"
Claude: [evaluates]
You: "Create an implementation plan"
Claude: [plans]
You: "Break that into segments"
...
```

This is tedious. You're basically acting as a **workflow scheduler** and **context router** - pointing each task to the right information and deciding what comes next.

**GOTN should automate this orchestration.**

---

## The Core Problem: Orchestration + Context

Two things you're doing manually that GOTN should handle:

### 1. Workflow Orchestration

You have a mental model of how research flows into implementation:

```
Research → Consolidate → Evaluate → Plan → Segment → POC → Execute
```

This isn't rigid - it's "vibes-based" and flexible. Sometimes you skip steps, sometimes you loop back. But there's a general flow.

**GOTN should**: Know this flow and advance through it automatically, with the flexibility to adapt.

### 2. Context Management

Each step needs different context:
- Research step needs: the question, constraints, what we already know
- Consolidation needs: all the research outputs
- Evaluation needs: consolidated findings + your specific use case criteria
- Planning needs: evaluation results + technical constraints
- Execution needs: the plan segment + relevant code context

Right now you're manually routing this - copy-pasting outputs, pointing Claude to the right files, reminding it of earlier decisions.

**GOTN should**: Automatically route the right context to each step.

---

## What GOTN Actually Is

GOTN is a **workflow orchestrator with context management** for research-to-implementation flows.

It's NOT:
- A "discipline layer" to stop Claude from over-researching (Claude doesn't over-research unprompted)
- A complex confidence/threshold system (overkill for most cases)
- A replacement for Claude's judgment

It IS:
- A way to define repeatable workflows
- A context router that connects steps
- A state tracker so you can pause/resume
- A way to parallelize independent research

### The Workflow Model

A workflow is a sequence of **phases**, each with a type:

```yaml
workflow: "research-to-implementation"
phases:
  - name: "Research"
    type: epistemic
    parallel: true  # Can research multiple things at once

  - name: "Consolidate"
    type: epistemic
    inputs: [Research.*]  # Gets all research outputs

  - name: "Evaluate"
    type: decision
    inputs: [Consolidate, use_case_criteria]

  - name: "Plan"
    type: epistemic
    inputs: [Evaluate]

  - name: "Segment"
    type: epistemic
    inputs: [Plan]

  - name: "POC"
    type: instrumental
    inputs: [Segment[0]]  # Just the first segment

  - name: "Execute"
    type: instrumental
    inputs: [Segment, POC.learnings]
    parallel: true  # Can execute segments in parallel
```

### Phase Types

| Type | Purpose | What It Produces |
|------|---------|------------------|
| **Epistemic** | Learn/research | Findings, summaries, options |
| **Decision** | Evaluate and commit | A choice with rationale |
| **Instrumental** | Build something | Artifacts (code, content) |
| **Validation** | Test something | Pass/fail with evidence |

### Context Routing

Each phase declares its **inputs** - what context it needs. GOTN automatically:
1. Collects outputs from the specified phases
2. Formats them appropriately
3. Passes them to the executing agent

```yaml
# Evaluate phase gets:
# - The consolidated research (Consolidate output)
# - The use case criteria (from config or user input)

- name: "Evaluate"
  inputs:
    - Consolidate           # Output from previous phase
    - use_case_criteria     # Config value or file reference
```

---

## How It Works with Claude Code

GOTN doesn't replace Claude Code - it orchestrates it.

```
GOTN Orchestrator
    ↓
    ├── Phase: Research TTS
    │   └── [Claude Code: deep-research skill]
    │
    ├── Phase: Research Voice Styles
    │   └── [Claude Code: deep-research skill]
    │
    ├── Phase: Consolidate
    │   └── [Claude Code: summarization task]
    │
    ├── Phase: Evaluate
    │   └── [Claude Code: analysis task]
    │
    └── Phase: Execute
        └── [Claude Code: implementation task]
```

Each phase invokes Claude Code with:
- The phase goal
- The routed context (inputs from previous phases)
- Any phase-specific tools or skills

### Tool Selection by Phase Type

| Phase Type | Default Tools |
|------------|---------------|
| Epistemic | deep-research, web-search, Explore |
| Decision | triad-orchestrator (multi-model), analysis |
| Instrumental | code tools, file operations |
| Validation | test runners, verification tools |

---

## Minimal Implementation

The simplest GOTN could be a **Claude Code skill** that:

1. Reads a workflow definition (YAML file)
2. Tracks current phase in a state file
3. Routes context between phases
4. Advances to next phase when current completes

```yaml
# .gotn/workflow.yaml
name: "NES Story Generation"
phases:
  - research-tts
  - research-story-structure
  - consolidate
  - evaluate
  - plan
  - execute

# .gotn/state.yaml
current_phase: "consolidate"
completed:
  research-tts: "outputs/research-tts.md"
  research-story-structure: "outputs/research-story.md"
```

The skill would:
1. Read state to know where we are
2. Gather inputs for current phase
3. Execute the phase (using Claude Code tools)
4. Save outputs
5. Advance state
6. Repeat or pause for human input

---

## What About Confidence and Alignment?

These might still be useful, but they're **secondary features**, not the core:

**Confidence tracking**: Useful for knowing when a research phase has "enough" information to move on. But can be simple - "do I have answers to my key questions?" rather than numerical thresholds.

**Goal alignment**: Useful for catching when parallel research tasks drift. But can be lightweight - just checking that outputs relate to the workflow goal.

**Shipping gates**: The Decision phases already serve this purpose - they force you to commit before moving to implementation.

These can be added incrementally if the basic orchestration proves valuable.

---

## Example: NES Story Content Workflow

Here's how your actual workflow might look:

```yaml
name: "NES Story Content Generation"

context:
  project: "Interactive bedtime stories for children"
  constraints:
    - "Age-appropriate content (3-8 years)"
    - "Must work offline after initial load"
    - "Voice narration required"

phases:
  - name: "Research TTS Options"
    type: epistemic
    goal: "Find TTS providers suitable for children's content"
    parallel_with: ["Research Story Structures"]

  - name: "Research Story Structures"
    type: epistemic
    goal: "Understand interactive story formats for children"

  - name: "Consolidate Research"
    type: epistemic
    inputs: ["Research TTS Options", "Research Story Structures"]
    goal: "Synthesize findings into coherent options"

  - name: "Evaluate for Use Case"
    type: decision
    inputs: ["Consolidate Research", "context.constraints"]
    goal: "Select TTS provider and story format"
    outputs:
      - tts_choice
      - story_format
      - rationale

  - name: "Implementation Plan"
    type: epistemic
    inputs: ["Evaluate for Use Case"]
    goal: "Create detailed implementation plan"

  - name: "Segment Plan"
    type: epistemic
    inputs: ["Implementation Plan"]
    goal: "Break into independently testable segments"
    outputs:
      - segments[]  # Array of segments

  - name: "POC"
    type: instrumental
    inputs: ["Segment Plan.segments[0]"]
    goal: "Build minimal working proof of concept"

  - name: "Execute Segments"
    type: instrumental
    inputs: ["Segment Plan.segments", "POC.learnings"]
    goal: "Implement remaining segments"
    parallel: true
```

Running this:

```bash
gotn run nes-story-workflow.yaml

# GOTN executes each phase, routing context automatically
# You can pause/resume at any point
# Parallel phases run concurrently
```

---

## Implementation Options

### Option A: Claude Code Skill (Simplest)

A skill file that implements the orchestration loop. State lives in YAML files in the project.

**Pros**: No external dependencies, uses existing Claude Code tools
**Cons**: Limited parallelism, skill-based state management can be fragile

### Option B: Lightweight Python CLI

A Python CLI that:
- Parses workflow definitions
- Manages state (SQLite or YAML)
- Invokes Claude Code for each phase
- Routes context

**Pros**: Better state management, easier parallelism, testable
**Cons**: Separate tool to install/run

### Option C: Current Implementation (Overkill?)

The full Python package with state machines, confidence aggregation, alignment scoring, etc.

**Pros**: Full featured
**Cons**: Lots of code for features that might not be needed

**Recommendation**: Start with Option A or B. Add complexity only if the basic orchestration proves valuable.

---

## Key Questions to Answer

1. **Is workflow definition worth it?** Or is ad-hoc orchestration actually fine?

2. **How much context routing is needed?** Is "just pass all previous outputs" good enough, or do we need precise routing?

3. **Where should state live?** Files in the project? Separate database?

4. **How to handle parallelism?** Run multiple Claude instances? Or just sequential with async potential?

5. **What's the right granularity?** Are "phases" the right unit, or should it be more/less granular?

---

## Summary

**The real problem**: You have to manually orchestrate research-to-implementation workflows, acting as scheduler and context router.

**GOTN should be**: A workflow orchestrator that automates this - defining flows, routing context, tracking state, invoking Claude Code for each step.

**The confidence/alignment/threshold stuff**: Secondary features that can be added if basic orchestration proves valuable.

**Next step**: Try the simplest implementation (Option A or B) on a real workflow and see if it actually helps.
