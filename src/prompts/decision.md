# Decision WorkNode: Analysis & Commitment

## Goal
{goal}

## Acceptance Criteria
{criteria}

## Context
{context}

## Available Evidence
{evidence}

## Decision-Making Instructions

You are in **decision mode** - your objective is to make a reasoned choice among options.

1. **Enumerate all viable options** - don't prematurely eliminate choices
2. **Analyze trade-offs** for each option against criteria
3. **Weight evidence** supporting or opposing each option
4. **Make a clear selection** with explicit rationale
5. **Document assumptions** underlying your decision
6. **Define a rollback plan** in case the decision proves wrong

### Decision Framework

For each option, evaluate:
- Alignment with stated goal
- Evidence strength (pro and con)
- Risk factors (safety, cost, reversibility)
- Dependencies and constraints

### Commitment Output

Your output must include:
- `choice_set`: All options considered
- `selected`: The chosen option
- `rationale`: Why this option was selected
- `constraints`: Conditions that must hold for this to work
- `residual_risks`: Known risks being accepted
- `rollback_plan`: How to reverse if wrong
- `assumption_ledger`: Assumptions that could invalidate this

### When to Request Child Nodes

Request a child node if you need:
- More research on a specific option (epistemic)
- Prototype to evaluate feasibility (instrumental)
- Expert input on risk assessment (epistemic)

{output_format}
