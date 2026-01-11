# GOTN: Goal-Oriented Task Network

A generalizable framework for recursive, self-similar workflow orchestration with confidence-gated autonomy.

## Core Insight

**Questions are objectives operating in the knowledge domain.**

The traditional tension between "question-driven" and "objective-driven" workflows dissolves when you recognize:
- A **question** is an objective with deliverable_type = `knowledge`
- A **build task** is an objective with deliverable_type = `artifact`
- A **decision** is an objective with deliverable_type = `commitment`

All three follow the same self-similar pattern.

## Architecture

```
docs/
├── architecture.md      # Complete GOTN specification
├── worknode-schema.md   # WorkNode interface definitions
├── mechanisms.md        # Control mechanisms (shipping gates, VOI, etc.)
└── examples/
    └── bedtime-story-pipeline.md
```

## Quick Start

See [docs/architecture.md](docs/architecture.md) for the full specification.

## Key Concepts

| Concept | Purpose |
|---------|---------|
| **WorkNode** | Universal unit of work (research, build, or decide) |
| **Epistemic Mode** | Knowledge acquisition ("What TTS options exist?") |
| **Instrumental Mode** | Artifact production ("Build the TTS pipeline") |
| **Decision Mode** | Commitment ("Use ElevenLabs v3") |
| **Shipping Gate** | Forces research to terminate with explicit commitment |
| **VOI Gating** | Prevents infinite research (value vs cost check) |
| **Confidence Aggregation** | Determines autonomy (auto-proceed vs human review) |

## Design Principles

1. **Self-similar recursion**: Every node follows the same Research → Build → Validate cycle
2. **Confidence-gated autonomy**: High confidence = auto-proceed, low = human review
3. **Production anchors**: Research must connect to something we're building
4. **Explicit commitments**: Decisions emit artifacts that downstream work depends on
5. **Bounded execution**: Global limits prevent runaway recursion

## Framework Lineage

GOTN synthesizes concepts from:
- **HTN (Hierarchical Task Networks)**: Recursive decomposition
- **BDI (Belief-Desire-Intention)**: Evidence=Belief, Goal=Desire, Commitment=Intention
- **OODA Loop**: Research→Build→Validate ≈ Observe→Orient→Decide→Act
- **Goal Trees**: Hierarchical goal decomposition with success criteria

## License

MIT
