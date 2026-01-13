# GOTN Architecture Overview

**Goal-Oriented Task Network** - A recursive orchestration framework for complex AI workflows.

---

## The Problem

When AI agents tackle complex goals, they face a fundamental challenge: **depth vs. context**.

```mermaid
flowchart LR
    subgraph Problem["The Depth Problem"]
        direction TB
        A["Complex Goal"] --> B["Subtask 1"]
        A --> C["Subtask 2"]
        B --> D["Sub-subtask 1.1"]
        B --> E["Sub-subtask 1.2"]
        D --> F["...deeper"]
        F --> G["Lost context!"]
    end

    style G fill:#f66,stroke:#333
```

As tasks decompose deeper:
- **Context gets lost** - Deep subtasks forget the original objective
- **Goals drift** - Intermediate work diverges from what was actually needed
- **Confidence is uncertain** - No clear signal when "enough" research is done
- **Resources exhaust** - Unbounded exploration without delivery

**Real example**: Ask an AI to "build a children's story generator" and watch it:
1. Research TTS options endlessly
2. Evaluate 47 voice providers
3. Never actually build anything
4. Run out of context window mid-task

---

## The Solution: Self-Similar WorkNodes

GOTN solves this with a single, recursive abstraction: **the WorkNode**.

```mermaid
flowchart TB
    subgraph WorkNode["Every WorkNode has the same structure"]
        Goal["Goal + Criteria"]
        Mode["Mode (what kind of work)"]
        Confidence["Confidence tracking"]
        Budget["Resource budget"]
        Children["Child nodes (optional)"]
    end

    Root["Root Goal"] --> W1["WorkNode"]
    W1 --> W2["WorkNode"]
    W1 --> W3["WorkNode"]
    W2 --> W4["WorkNode"]
    W2 --> W5["WorkNode"]

    style WorkNode fill:#e6f3ff,stroke:#333
```

**Key insight**: The same structure works at every level. A root goal and its deepest subtask both have:
- A goal with acceptance criteria
- A mode (research, build, decide, verify)
- Confidence tracking
- Resource constraints
- The ability to spawn children

This uniformity enables:
- **Consistent scheduling** at any depth
- **Uniform confidence aggregation** up the tree
- **Predictable resource management** everywhere

---

## The Four Modes

Each WorkNode operates in one of four modes, depending on what work it needs to do:

```mermaid
flowchart LR
    E["Epistemic<br/>(Research)"] --> D["Decision<br/>(Commit)"]
    D --> I["Instrumental<br/>(Build)"]
    I --> V["Validation<br/>(Verify)"]

    style E fill:#e6f3ff,stroke:#333
    style D fill:#fff3e6,stroke:#f90
    style I fill:#e6ffe6,stroke:#393
    style V fill:#ffe6e6,stroke:#933
```

| Mode | Purpose | Output | Example |
|------|---------|--------|---------|
| **Epistemic** | Gather knowledge | Claims with confidence | "Research TTS providers" |
| **Decision** | Commit to a choice | Binding commitment | "Select ElevenLabs" |
| **Instrumental** | Build something | Artifacts | "Implement TTS integration" |
| **Validation** | Verify correctness | Pass/fail verdict | "Test audio quality" |

### The Shipping Gate

**Decision nodes are shipping gates** - they force the transition from research to implementation.

```mermaid
flowchart TB
    subgraph Research["Research Phase"]
        R1["Research TTS options"]
        R2["Compare pricing"]
        R3["Evaluate quality"]
    end

    subgraph Gate["Shipping Gate"]
        D["Decision: Select provider"]
    end

    subgraph Build["Build Phase"]
        I1["Implement integration"]
        I2["Add error handling"]
        V1["Validate output"]
    end

    Research --> Gate
    Gate --> Build

    style Gate fill:#fff3e6,stroke:#f90
```

Without shipping gates, research can spiral indefinitely. The decision node forces commitment: "Based on what we know, we're going with X."

---

## Confidence and Autonomy

Every WorkNode tracks **confidence** - how certain we are that the goal is achieved.

```mermaid
flowchart TB
    subgraph Confidence["Confidence Aggregation"]
        C1["Criterion 1: 0.9"]
        C2["Criterion 2: 0.7"]
        C3["Criterion 3 (must-pass): 0.85"]
    end

    Confidence --> Agg["Aggregate: 0.81"]
    Agg --> Check{"≥ threshold?"}
    Check -->|Yes| Complete["Complete"]
    Check -->|No| Action{"What to do?"}
    Action --> Spawn["Spawn research"]
    Action --> Escalate["Ask human"]
    Action --> Degrade["Deliver minimum"]
```

### Confidence Gating

The **autonomy gate** determines when a node can proceed:

| Confidence | Action |
|------------|--------|
| **≥ 0.8** | Auto-proceed (high confidence) |
| **0.5 - 0.8** | Spawn child research to fill gaps |
| **< 0.5** | Escalate to human review |

**Must-pass criteria** can block completion regardless of overall confidence. If a safety criterion scores 0.3, the node cannot complete even if everything else is 0.95.

---

## Goal Alignment

As goals decompose deeper, there's a risk of **goal drift** - subtasks that technically complete but don't serve the root objective.

```mermaid
flowchart TB
    Root["Build story generator<br/>for 5-year-olds"]

    subgraph Aligned["Aligned Work"]
        A1["Research child-appropriate voices"]
        A2["Implement content filtering"]
    end

    subgraph Drifted["Goal Drift"]
        D1["Optimize for maximum throughput"]
        D2["Add enterprise SSO"]
    end

    Root --> Aligned
    Root -.->|"drift"| Drifted

    style Drifted fill:#ffe6e6,stroke:#933
    style Aligned fill:#e6ffe6,stroke:#393
```

### The Goal Capsule

GOTN anchors every tree with a **Goal Capsule** - an immutable, checksummed root objective:

```mermaid
flowchart TB
    subgraph Capsule["Goal Capsule (Immutable)"]
        RG["Root Goal"]
        MC["Must-pass Constraints"]
        SC["Success Criteria"]
        Hash["SHA256 Checksum"]
    end

    Capsule --> N1["Node depth 1"]
    Capsule --> N2["Node depth 2"]
    Capsule --> N3["Node depth 5"]
    Capsule --> N4["Node depth 10"]

    style Capsule fill:#fff3e6,stroke:#f90
```

**Every node**, no matter how deep, can reference the capsule to verify alignment. Before spawning a child, the system checks:
- Does this child's goal serve the root objective?
- Does it violate any must-pass constraints?
- Is the alignment score above threshold?

---

## Context Management

Deep recursion creates a context problem: how do you give a depth-10 node enough information to work without exceeding context limits?

### Three-Tier Context Strategy

```mermaid
flowchart TB
    subgraph Tier1["Tier 1: Always Present (8%)"]
        direction LR
        T1A["Goal Capsule"]
        T1B["Parent Goal"]
        T1C["Key Constraints"]
    end

    subgraph Tier2["Tier 2: Query on Demand (20%)"]
        direction LR
        T2A["Ancestor Context"]
        T2B["Sibling Outputs"]
        T2C["Research Claims"]
    end

    subgraph Tier3["Tier 3: Fetch When Needed"]
        direction LR
        T3A["Web Search"]
        T3B["Documentation"]
        T3C["External APIs"]
    end

    Tier1 -->|"Always stuffed"| Execution["Node Execution"]
    Tier2 -->|"Pre-fetched based on value"| Execution
    Tier3 -->|"Fetched during execution"| Execution

    style Tier1 fill:#e6ffe6,stroke:#393
    style Tier2 fill:#fff3e6,stroke:#f90
    style Tier3 fill:#e6f3ff,stroke:#333
```

| Tier | What | When | Budget |
|------|------|------|--------|
| **Tier 1** | Goal capsule, parent goal, constraints | Always present | ~8% |
| **Tier 2** | Ancestor research, sibling outputs | Pre-fetched based on value | ~20% |
| **Tier 3** | External docs, web search | During execution if needed | Variable |

### Value of Information Gating

Not all context retrieval is worth the cost. GOTN uses **Value of Information (VoI)** to decide what to fetch:

```mermaid
flowchart LR
    Query["Potential Query"]

    subgraph VoI["Value of Information"]
        U["Uncertainty"]
        I["Decision Impact"]
        C["Query Cost"]
    end

    Query --> VoI
    VoI --> Calc["(U × I) / C"]
    Calc --> Check{"≥ threshold?"}
    Check -->|Yes| Fetch["Fetch Context"]
    Check -->|No| Skip["Skip Query"]
```

**High VoI scenarios**:
- Decision node with low confidence (high uncertainty, high impact)
- Must-pass criterion not yet satisfied
- Validation node checking critical output

**Low VoI scenarios**:
- Already high confidence (low uncertainty)
- Optional criterion on epistemic node
- Deep in a research branch with tight budget

---

## Node Lifecycle

Every WorkNode follows the same state machine:

```mermaid
stateDiagram-v2
    [*] --> PENDING: Created

    PENDING --> READY: Dependencies met
    READY --> RUNNING: Execution starts

    RUNNING --> BLOCKED: Needs child work
    BLOCKED --> READY: Children complete

    RUNNING --> COMPLETE: Confidence met
    RUNNING --> DEGRADED: Budget exhausted
    RUNNING --> ESCALATED: Human needed
    RUNNING --> FAILED: Unrecoverable error

    COMPLETE --> [*]
    DEGRADED --> [*]
    FAILED --> [*]

    ESCALATED --> RUNNING: Human responds
```

| State | Meaning |
|-------|---------|
| **PENDING** | Waiting for dependencies |
| **READY** | Can be scheduled for execution |
| **RUNNING** | Actively being worked on |
| **BLOCKED** | Waiting for child nodes to complete |
| **COMPLETE** | Successfully achieved goal |
| **DEGRADED** | Delivered minimum viable output |
| **ESCALATED** | Waiting for human input |
| **FAILED** | Unrecoverable error |

---

## The Execution Flow

Here's how a complex goal flows through GOTN:

```mermaid
sequenceDiagram
    participant User
    participant Orchestrator
    participant Scheduler
    participant Executor
    participant Claude

    User->>Orchestrator: "Build story generator"
    Orchestrator->>Orchestrator: Create Goal Capsule
    Orchestrator->>Orchestrator: Create root WorkNode

    loop Until complete or escalated
        Scheduler->>Scheduler: Find highest-priority ready node
        Scheduler->>Executor: Execute node
        Executor->>Executor: Build context (Tier 1 + Tier 2)
        Executor->>Claude: Execute with goal + context
        Claude->>Executor: Return output + confidence

        alt Needs more work
            Executor->>Orchestrator: Spawn child nodes
            Orchestrator->>Scheduler: Schedule children
        else Confidence met
            Executor->>Orchestrator: Mark complete
            Orchestrator->>Scheduler: Unblock parent
        else Budget exhausted
            Executor->>Orchestrator: Degrade or escalate
        end
    end

    Orchestrator->>User: Final output
```

---

## Resource Protection

GOTN includes multiple safeguards against runaway execution:

### Circuit Breakers

```mermaid
flowchart TB
    subgraph Limits["Global Limits"]
        D["Max Depth: 10"]
        N["Max Nodes: 100"]
        R["Max Research Ratio: 40%"]
        C["Max Concurrent: 10"]
    end

    Check{"Limit exceeded?"}

    Limits --> Check
    Check -->|Yes| Halt["Halt + Escalate"]
    Check -->|No| Continue["Continue"]

    style Halt fill:#f66,stroke:#333
```

### Budget Enforcement

Every node has resource constraints:
- **Token budget** - Maximum LLM tokens
- **Time budget** - Maximum wall-clock time
- **Cost budget** - Maximum API spend
- **Step budget** - Maximum discrete operations

When budget exhausts, the node's **exit policy** determines what happens:
- **Degrade**: Deliver minimum viable output
- **Escalate**: Ask human for guidance
- **Fail**: Mark as failed, let parent handle

---

## Tree Structure Example

Here's how a real goal decomposes:

```mermaid
flowchart TB
    Root["Build children's story generator<br/><i>Mode: Instrumental</i>"]

    subgraph Research["Research Phase"]
        R1["Research TTS options<br/><i>Epistemic</i>"]
        R2["Research content safety<br/><i>Epistemic</i>"]
        R3["Research story structures<br/><i>Epistemic</i>"]
    end

    subgraph Decisions["Decision Phase"]
        D1["Select TTS provider<br/><i>Decision</i>"]
        D2["Define safety rules<br/><i>Decision</i>"]
    end

    subgraph Build["Build Phase"]
        I1["Implement TTS integration<br/><i>Instrumental</i>"]
        I2["Implement content filter<br/><i>Instrumental</i>"]
        I3["Build story generator<br/><i>Instrumental</i>"]
    end

    subgraph Validate["Validation Phase"]
        V1["Test with sample stories<br/><i>Validation</i>"]
        V2["Verify content safety<br/><i>Validation</i>"]
    end

    Root --> Research
    Research --> Decisions
    Decisions --> Build
    Build --> Validate
    Validate --> Root

    R1 --> D1
    R2 --> D2
    D1 --> I1
    D2 --> I2
    I1 --> I3
    I2 --> I3
    I3 --> V1
    I3 --> V2
```

Each node in this tree:
- Has the same structure (goal, criteria, confidence, budget)
- Tracks its own completion independently
- Can spawn additional children if needed
- Reports confidence back to its parent
- Is anchored to the same Goal Capsule

---

## Integration with Claude Code

GOTN runs as a **Claude Code extension**, integrating through:

```mermaid
flowchart TB
    subgraph GOTN["GOTN Package"]
        CLI["CLI Commands<br/>gotn init/run/status"]
        Scheduler["Scheduler"]
        Executor["Executor"]
    end

    subgraph ClaudeCode["Claude Code"]
        Skills["Skills<br/>/gotn workflow"]
        Agents["Subagents<br/>Mode-specific specialists"]
        Hooks["Hooks<br/>Lifecycle events"]
    end

    subgraph Execution["Execution"]
        Claude["Claude"]
    end

    GOTN --> ClaudeCode
    ClaudeCode --> Execution
    Execution --> GOTN
```

### Mode-Specific Tool Restrictions

Each mode gets appropriate tools:

| Mode | Allowed Tools |
|------|--------------|
| **Epistemic** | Read, Search, WebFetch |
| **Decision** | Read, Search (no modifications) |
| **Instrumental** | Read, Write, Edit, Bash |
| **Validation** | Read, Bash (tests only) |

This prevents research nodes from accidentally modifying code, or decision nodes from taking premature action.

---

## Key Benefits

```mermaid
flowchart LR
    subgraph Problems["Without GOTN"]
        P1["Context lost at depth"]
        P2["Goals drift over time"]
        P3["No completion signal"]
        P4["Resources exhausted"]
    end

    subgraph Solutions["With GOTN"]
        S1["Goal Capsule anchoring"]
        S2["Alignment validation"]
        S3["Confidence gating"]
        S4["Budget enforcement"]
    end

    P1 -.-> S1
    P2 -.-> S2
    P3 -.-> S3
    P4 -.-> S4

    style Problems fill:#ffe6e6,stroke:#933
    style Solutions fill:#e6ffe6,stroke:#393
```

| Problem | Solution |
|---------|----------|
| Context lost at depth | Three-tier context with Goal Capsule always present |
| Goals drift | Alignment validation before spawning children |
| No completion signal | Confidence aggregation with autonomy gating |
| Resources exhausted | Budget tracking with circuit breakers |
| Endless research | Shipping gates force decision/build phases |

---

## Summary

GOTN enables complex AI workflows through:

1. **Self-similar structure** - Same WorkNode abstraction at every level
2. **Four modes** - Epistemic, Decision, Instrumental, Validation
3. **Confidence gating** - Clear signals for when work is "enough"
4. **Goal alignment** - Immutable Goal Capsule prevents drift
5. **Context efficiency** - Three-tier strategy scales to arbitrary depth
6. **Resource protection** - Budgets and circuit breakers prevent runaway
7. **Shipping gates** - Decision nodes force research → build transitions

The result: Complex goals decompose naturally, stay aligned to the root objective, and complete with appropriate confidence - all while respecting resource constraints.
