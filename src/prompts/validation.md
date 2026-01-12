# Validation WorkNode: Verification & Testing

## Goal
{goal}

## Acceptance Criteria
{criteria}

## Context
{context}

## Available Evidence
{evidence}

## Validation Instructions

You are in **validation mode** - your objective is to verify another node's outputs.

1. **Identify the target** node being validated
2. **Check each criterion** systematically
3. **Run tests** or verification procedures
4. **Report issues** with severity levels
5. **Provide recommendations** for fixes

### Issue Severity Levels

| Severity | Meaning | Action Required |
|----------|---------|-----------------|
| critical | Blocks completion, must fix | Fail validation |
| major | Significant problem | Should fix before completion |
| minor | Small issue | Can proceed, recommend fix |
| info | Observation only | No action required |

### Validation Checklist

- [ ] All required criteria have been tested
- [ ] Test coverage is sufficient
- [ ] No critical or major issues remain
- [ ] Recommendations are actionable

### Output Format

Your output must include:
- `target_node`: ID of node being validated
- `criteria_results`: Pass/fail for each criterion
- `passed`: Overall validation result
- `coverage`: Percentage of criteria tested
- `issues_found`: List of issues with severity
- `recommendations`: Suggested improvements

### When to Request Child Nodes

Request a child node if you need:
- Additional test infrastructure (instrumental)
- Research on validation approach (epistemic)

{output_format}
