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

## 2026-01-12: Build & Runtime Fixes

### Completed
- **Package build verified** - `uv venv && uv pip install -e ".[dev]"` works
- **24 tests passing** - All unit tests pass

### Runtime Bug Fixes

1. **CLI status() internal call** - Typer OptionInfo objects were leaking when `status()` was called internally from `run()`. Fixed by extracting `_status_impl()` helper function.

2. **Claim domain validation** - Claude returns arbitrary domain strings (e.g., "mathematical_axiom") that aren't in the `ClaimDomain` enum. Added `field_validator` to default unknown values to `GENERAL`.

3. **Output model flexibility** - Made output model fields optional to handle variable Claude responses:
   - `KnowledgeOutput.summary` now defaults to empty string
   - `ArtifactOutput.path/artifact_type/hash` now optional
   - `CommitmentOutput` fields have sensible defaults

4. **Criterion ID matching** - Claude returns generic IDs like "crit-goal-achieved" instead of actual node criterion IDs. Fixed with flexible matching: exact match → single-criterion fallback → positional matching.

### Test Results
```bash
$ gotn init "What is 2+2?" --store /tmp/test --mode epistemic
$ gotn run --store /tmp/test --no-skills
# Result: complete, 100% confidence

$ gotn init "List three Python web frameworks" --store /tmp/test2 --mode epistemic
$ gotn run --store /tmp/test2 --no-skills
# Result: complete, 95% confidence
```

### Next Steps
- Test child node spawning workflow
- Test decision mode
- Add integration tests for full execution

## 2026-01-13: Claude Code Integration Architecture

### Research Completed
- **Skills**: Folder-based workflows with SKILL.md, auto/manual invocation
- **Subagents**: Mode-specific specialists via Task tool, tool restrictions
- **Hooks**: PreToolUse, PostToolUse, SubagentStop lifecycle events
- **MCP**: Considered and rejected for Tier 2 queries (too heavy)
- **Plugin Marketplace**: Distribution via GitHub/npm

### Key Design Decisions

1. **CLI over MCP** for Tier 2 queries
   - `gotn query ancestors/claims/siblings` commands
   - Token-budget-aware output (`--max-tokens`)
   - No external process to manage

2. **`--json-schema` for structured output**
   - Claude uses internal StructuredOutput tool
   - Guaranteed schema compliance
   - No more YAML parsing from freeform text

3. **Self-contained package**
   - `pip install gotn && gotn install --global`
   - Skills, agents, hooks bundled
   - Plugin manifest for marketplace

### Architecture Documentation Updated
- `docs/architecture.md` now includes:
  - Complete Claude Code integration section
  - CLI invocation patterns with all flags
  - GOTN_OUTPUT_SCHEMA definition
  - Skills/Subagents/Hooks specifications
  - Packaging and distribution guide
  - Environment variables for context

### Sources
- [Claude Code Skills Docs](https://code.claude.com/docs/en/skills)
- [Claude Code Hooks Docs](https://code.claude.com/docs/en/hooks)
- [Claude Code Subagents Docs](https://code.claude.com/docs/en/sub-agents)
- [Anthropic Skills Repo](https://github.com/anthropics/skills)

### Next Steps
- Refactor executor.py to use `--json-schema`
- Create skills/ and agents/ directories with actual files
- Implement `gotn query` subcommands
- Implement `gotn install` command

## 2026-01-13: Architecture Review (Triad)

### Review Method
- **Agents**: Claude, Codex, Gemini (adversarial sequential)
- **Turns**: 8
- **Verdict**: Conceptually sound, implementation-incomplete

### Critical Issues (P0)
1. **Tier 2 queries blocked** - `gotn query` needs Bash, but epistemic/decision modes don't allow it
2. **Shell injection in hooks** - Raw `$TOOL_INPUT` interpolation without escaping
3. **Context management not implemented** - 3-tier strategy is docs-only
4. **Self-attestation flaw** - Nodes can mark own criteria satisfied
5. **Evidence fabrication** - Auto-created at 0.7 strength from model output

### Major Issues (P1)
- VOI gating documented but not enforced
- Storage model inconsistent (Kuzu vs YAML)
- Schema lacks criterion IDs (order-dependent)
- CLI subprocess has no retry/recovery logic
- Alignment threshold (0.3) gameable via keyword stuffing
- MAX_DEPTH/MAX_NODES limits not enforced
- Goal Capsule checksum insufficient (no signatures)

### Strengths Confirmed
- Self-similar WorkNode structure is elegant
- Confidence aggregation model is sound
- Shipping gates pattern prevents analysis paralysis
- State machine design is clean
- CLI + Skills + Subagents integration is pragmatic

### Documentation
- Full findings: `docs/architecture-review-2026-01-13.md`
- Triad transcript: `.triad/runs/gotn-architecture-review/thread.jsonl`

### Next Steps (Updated)
1. **P0**: Fix Tier 2 query access for all node modes
2. **P0**: Implement context budget tracking
3. **P0**: Fix hook shell injection
4. **P1**: Add criterion IDs to schema
5. **P1**: Implement CLI retry logic
6. **P1**: Enforce depth/node limits
