# Planning WorkNode: Goal Decomposition

## Goal
{goal}

## Acceptance Criteria
{criteria}

## Context
{context}

## Available Evidence
{evidence}

## Planning Instructions

You are in **planning mode** - your objective is to decompose a complex goal into executable sub-goals.

1. **Analyze the goal** - understand what needs to be achieved
2. **Identify major components** - what are the distinct pieces of work?
3. **Determine dependencies** - which components depend on others?
4. **Assign modes** to each sub-goal (epistemic, decision, instrumental, validation)
5. **Define acceptance criteria** for each sub-goal
6. **Identify parallelizable work** - what can run concurrently?
7. **Find the critical path** - what sequence gates progress?

### Decomposition Principles

- **Atomic sub-goals**: Each should be achievable by a single agent
- **Clear boundaries**: Sub-goals shouldn't overlap
- **Mode-appropriate**: Match the sub-goal to the right execution mode
- **Testable outcomes**: Each must have verifiable completion criteria

### Mode Selection Guide

- **epistemic**: Research, investigation, knowledge gathering
- **decision**: Choosing between options, making commitments
- **instrumental**: Building artifacts (code, content, configs)
- **validation**: Testing, verifying, checking quality

### Plan Output

Your output must include:
- `sub_goals`: List of sub-goals, each with:
  - `goal_statement`: Clear description (min 10 chars)
  - `mode`: One of (epistemic, decision, instrumental, validation)
  - `rationale`: Why this sub-goal is needed
  - `acceptance_criteria`: How to know it's complete
  - `depends_on`: Indices of prerequisite sub-goals
  - `estimated_complexity`: low, medium, high
- `decomposition_rationale`: Why you decomposed it this way
- `execution_order`: Suggested order of execution
- `parallel_groups`: Groups that can run concurrently
- `critical_path`: The longest dependency chain

### When Planning is Complete

Your plan is complete when:
- Every aspect of the original goal is covered by sub-goals
- Dependencies form a valid DAG (no cycles)
- Each sub-goal has clear acceptance criteria
- The critical path is identified

### Example Plan Structure

```
sub_goals:
  - goal_statement: "Research authentication patterns for REST APIs"
    mode: epistemic
    rationale: "Need to understand options before deciding"
    depends_on: []
    estimated_complexity: medium

  - goal_statement: "Decide on authentication approach"
    mode: decision
    rationale: "Must commit to approach before building"
    depends_on: [0]
    estimated_complexity: low

  - goal_statement: "Implement authentication middleware"
    mode: instrumental
    rationale: "Build the chosen approach"
    depends_on: [1]
    estimated_complexity: high
```

{output_format}
