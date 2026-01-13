# GOTN Development Log

## 2026-01-11: Goal Alignment System Complete

### Completed
- **Alignment module** (`src/gotn/alignment.py`) - Prevents goal drift in hierarchical task trees
  - `GoalChain` - Compressed ancestry context (~500 tokens regardless of depth)
  - `AlignmentMonitor` - Validates child goals against tree objectives before spawning
  - `compute_alignment_score()` - Keyword overlap with concept expansion for semantic matching
  - `propagate_constraints()` - Cascades must-pass criteria from parents to children

- **Concept expansion** for alignment scoring using domain-specific keyword groups:
  - API/REST/service concepts
  - Web frameworks (FastAPI, Flask, Django, etc.)
  - Authentication (JWT, OAuth, session, etc.)
  - Testing/benchmarking concepts
  - And more...

- **Scheduler integration** - `spawn_child()` now validates alignment before creating children
  - Configurable threshold (default 0.3)
  - Can be disabled for testing with `enforce_alignment=False`

### Test Results
- 24 tests passing (12 alignment + 7 scheduler + 5 state)

### Architecture
The alignment system solves the "goal drift" problem where deep subtasks lose sight of root objectives:
1. **Goal Chain** - Compressed ancestry context passed to each node
2. **Alignment Score** - Semantic similarity validated before spawning
3. **Constraint Propagation** - Critical criteria flow down the tree
4. **Alignment Checkpoints** - Validate at state transitions

### Next Steps
- Integrate goal chain context into executor prompts
- Add alignment warnings to CLI status output
- Consider embedding-based alignment when sentence-transformers available

## 2026-01-12: RLM + GOTN Synthesis Architecture Update

### Completed
- **Architecture documentation** (`docs/architecture.md`) - Major update synthesizing RLM paper concepts with GOTN

### Key Concepts Added

1. **Three-Tier Context Model**
   - Tier 1 (Eager): Always stuffed - goal chain, capsule, parent contract (~5-8%)
   - Tier 2 (Query): On-demand tools - sibling summaries, ancestor research
   - Tier 3 (Lazy): External fetch - documentation, domain knowledge

2. **Goal Capsule** - Immutable, checksummed anchor containing root goal + constraints + success criteria
   - Prevents drift at arbitrary depth
   - SHA256 checksum for tamper detection

3. **VoI-Gated Retrieval** - Formula: `(uncertainty × decision_impact) / query_cost > threshold`
   - Query Tier 2 only when value exceeds cost
   - Triggers: high uncertainty, decision nodes, explicit queries

4. **ContextFilter** - Code-based pre-processing (Python/SQL) before LLM reasoning
   - 10x cheaper than LLM filtering
   - Deterministic, testable extraction

5. **Dual Recursion Model**
   - Task recursion (GOTN-style): Spawns child WorkNodes with contracts
   - Data recursion (RLM-style): Processes segments within same node
   - Choice based on: independence, shared state, output structure

6. **Schema Updates** - New Kuzu tables:
   - `GoalCapsule` - Root goal anchoring
   - `Claim` - Evidence tracking with scope/domain
   - `ANCHORED_BY` relationship connecting WorkNodes to capsules

### Source
- arxiv paper 2512.24601 on Recursive Language Models
- Multi-agent triad research synthesis (Claude + Codex + Gemini)

### Next Steps
- Implement `GoalCapsule` class in code
- Add `ContextPolicy` with tier configuration
- Create Tier 2 query tools for executor
- Update GraphStore schema with new tables
