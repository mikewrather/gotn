"""Claude Code executor for WorkNode execution."""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from gotn.node import (
    Claim,
    ClaimDomain,
    Evidence,
    EvidenceType,
    NodeMode,
    WorkNode,
)
from gotn.tools import (
    get_tool_instructions,
    get_toolkit,
    should_use_deep_research,
    should_use_triad,
)


@dataclass
class ChildRequest:
    """Request to spawn a child node."""

    goal: str
    mode: NodeMode
    rationale: str
    criteria: Optional[list[dict]] = None


@dataclass
class CriterionStatus:
    """Status update for a criterion."""

    id: str
    satisfied: bool
    confidence: float


@dataclass
class NodeResult:
    """Result of executing a node."""

    claims: list[Claim] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    criterion_status: list[CriterionStatus] = field(default_factory=list)
    child_requests: list[ChildRequest] = field(default_factory=list)
    output: Optional[dict[str, Any]] = None
    raw_output: str = ""
    tokens_used: int = 0
    time_ms: int = 0
    error: Optional[str] = None


@dataclass
class ExecutionContext:
    """Context for node execution."""

    parent_goal: Optional[str] = None
    sibling_claims: list[Claim] = field(default_factory=list)
    available_evidence: list[Evidence] = field(default_factory=list)
    max_depth: int = 5


class PromptBuilder:
    """Builds execution prompts for different node modes."""

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir or Path(__file__).parent.parent / "prompts"

    def build_prompt(self, node: WorkNode, context: ExecutionContext) -> str:
        """Build the execution prompt for a node."""
        # Load mode-specific template if exists
        template = self._load_template(node.mode)

        # Build prompt sections
        goal_section = self._build_goal_section(node)
        criteria_section = self._build_criteria_section(node)
        context_section = self._build_context_section(node, context)
        evidence_section = self._build_evidence_section(context)
        instructions_section = self._build_instructions(node)
        output_section = self._build_output_format()

        if template:
            return template.format(
                goal=goal_section,
                criteria=criteria_section,
                context=context_section,
                evidence=evidence_section,
                instructions=instructions_section,
                output_format=output_section,
            )

        # Default prompt structure
        return f"""# WorkNode Execution

## Goal
{goal_section}

## Acceptance Criteria
{criteria_section}

## Context
{context_section}

## Available Evidence
{evidence_section}

## Instructions
{instructions_section}

## Output Format
{output_section}
"""

    def _load_template(self, mode: NodeMode) -> Optional[str]:
        """Load mode-specific prompt template."""
        template_path = self.prompts_dir / f"{mode.value}.md"
        if template_path.exists():
            return template_path.read_text()
        return None

    def _build_goal_section(self, node: WorkNode) -> str:
        """Build the goal section of the prompt."""
        lines = [node.goal.statement]
        if node.goal.original_question:
            lines.append(f"\nOriginal question: {node.goal.original_question}")
        return "\n".join(lines)

    def _build_criteria_section(self, node: WorkNode) -> str:
        """Build the criteria section of the prompt."""
        lines = []
        for criterion in node.goal.acceptance_criteria:
            status = "[x]" if criterion.satisfied else "[ ]"
            must_pass = " (REQUIRED)" if criterion.must_pass else ""
            confidence = f" [{criterion.confidence:.0%}]" if criterion.confidence > 0 else ""
            lines.append(
                f"- {status} {criterion.description} "
                f"(type: {criterion.type.value}){must_pass}{confidence}"
            )
        return "\n".join(lines) or "- No specific criteria defined"

    def _build_context_section(self, node: WorkNode, context: ExecutionContext) -> str:
        """Build the context section of the prompt."""
        lines = [
            f"- Mode: {node.mode.value}",
            f"- Depth: {node.depth} / {context.max_depth}",
        ]

        if node.budget.tokens:
            remaining = node.budget.tokens - node.resource_usage.tokens
            lines.append(f"- Token budget: {remaining} remaining of {node.budget.tokens}")

        if node.budget.time_ms:
            remaining = node.budget.time_ms - node.resource_usage.time_ms
            lines.append(f"- Time budget: {remaining}ms remaining")

        if node.budget.steps:
            remaining = node.budget.steps - node.resource_usage.steps
            lines.append(f"- Step budget: {remaining} remaining")

        if context.parent_goal:
            lines.append(f"- Parent goal: {context.parent_goal}")

        return "\n".join(lines)

    def _build_evidence_section(self, context: ExecutionContext) -> str:
        """Build the evidence section of the prompt."""
        if not context.available_evidence:
            return "No prior evidence available."

        lines = []
        for ev in context.available_evidence:
            recency = ev.recency.strftime("%Y-%m-%d") if ev.recency else "unknown"
            lines.append(
                f"- [{ev.id}] {ev.summary} "
                f"(strength: {ev.strength:.0%}, recency: {recency})"
            )
        return "\n".join(lines)

    def _build_instructions(self, node: WorkNode) -> str:
        """Build mode-specific instructions with tool guidance."""
        base_instructions = [
            "1. Work toward the goal, generating claims with confidence scores",
            "2. For each claim, cite evidence using [evidence-id] format",
            "3. Report confidence per criterion as you progress",
            "4. If you need information you don't have, request a child node",
        ]

        threshold = node.autonomy_gate.proceed_threshold
        base_instructions.append(
            f"5. Stop when: confidence >= {threshold:.0%} OR budget exhausted"
        )

        # Add tool-specific instructions from toolkit
        tool_instructions = get_tool_instructions(node.mode)

        instructions = base_instructions + ["", "---", "", tool_instructions]
        return "\n".join(instructions)

    def _build_output_format(self) -> str:
        """Build the expected output format."""
        return """Return a structured YAML block at the end of your response:

```yaml
claims:
  - proposition: "..."
    confidence: 0.85
    evidence_ids: [ev-001]
    domain: general

criterion_status:
  - id: "crit-xxx"
    satisfied: true
    confidence: 0.9

needs_children:  # Only if blocked and need sub-work
  - goal: "Research X"
    mode: epistemic
    rationale: "Need more information about X"

output:  # Only if complete
  type: knowledge|artifact|commitment|verification
  # ... type-specific fields
```
"""


@dataclass
class ExecutionStrategy:
    """Strategy for executing a node."""

    use_skill: bool = False
    skill_name: Optional[str] = None
    skill_args: Optional[str] = None
    prompt: Optional[str] = None
    reason: str = ""


class ClaudeExecutor:
    """Executes WorkNodes via Claude Code subprocess."""

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        claude_path: str = "claude",
        default_timeout_ms: int = 120000,
        prefer_skills: bool = True,
    ):
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.claude_path = claude_path
        self.default_timeout_ms = default_timeout_ms
        self.prefer_skills = prefer_skills

    def determine_strategy(
        self,
        node: WorkNode,
        context: ExecutionContext,
    ) -> ExecutionStrategy:
        """Determine the best execution strategy for a node."""
        goal = node.goal.statement

        # Check if deep research skill should be used
        if self.prefer_skills and should_use_deep_research(goal, node.mode):
            return ExecutionStrategy(
                use_skill=True,
                skill_name="deep-research",
                skill_args=goal,
                reason="Goal requires comprehensive multi-source research",
            )

        # Check if triad orchestrator should be used for decisions
        if self.prefer_skills and should_use_triad(goal, node.mode):
            return ExecutionStrategy(
                use_skill=True,
                skill_name="triad-orchestrator:run",
                skill_args=f"Analyze and decide: {goal}",
                reason="Critical decision benefits from multi-model consensus",
            )

        # Default: use prompt-based execution
        prompt = self.prompt_builder.build_prompt(node, context)
        return ExecutionStrategy(
            use_skill=False,
            prompt=prompt,
            reason=f"Standard {node.mode.value} execution",
        )

    def execute_node(
        self,
        node: WorkNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Execute a single node using Claude.

        Automatically determines the best execution strategy (skill vs prompt).
        """
        start_time = datetime.now()

        # Determine execution strategy
        strategy = self.determine_strategy(node, context)

        # Calculate timeout
        timeout_ms = node.budget.time_ms or self.default_timeout_ms
        remaining_ms = timeout_ms - node.resource_usage.time_ms
        timeout_seconds = max(1, remaining_ms / 1000)

        # Calculate max turns from step budget
        max_turns = node.budget.steps or 10
        remaining_turns = max_turns - node.resource_usage.steps

        # Execute based on strategy
        try:
            if strategy.use_skill and strategy.skill_name:
                raw_output, tokens_used = self._run_skill(
                    skill_name=strategy.skill_name,
                    skill_args=strategy.skill_args or "",
                    timeout_seconds=timeout_seconds,
                )
            else:
                raw_output, tokens_used = self._run_claude(
                    prompt=strategy.prompt or "",
                    timeout_seconds=timeout_seconds,
                    max_turns=remaining_turns,
                )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return NodeResult(
                error="Execution timed out",
                time_ms=elapsed_ms,
                raw_output="",
            )
        except subprocess.CalledProcessError as e:
            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return NodeResult(
                error=f"Claude execution failed: {e.stderr}",
                time_ms=elapsed_ms,
                raw_output=e.stdout or "",
            )

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Parse result
        result = self._parse_result(raw_output, node)
        result.time_ms = elapsed_ms
        result.tokens_used = tokens_used
        result.raw_output = raw_output

        return result

    def _run_skill(
        self,
        skill_name: str,
        skill_args: str,
        timeout_seconds: float,
    ) -> tuple[str, int]:
        """Run a Claude Code skill.

        Returns (output, tokens_used).
        """
        # Build prompt that invokes the skill
        prompt = f"/{skill_name} {skill_args}"

        cmd = [
            self.claude_path,
            "--print",
            "--dangerously-skip-permissions",
            prompt,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=True,
        )

        tokens_used = len(prompt) // 4 + len(result.stdout) // 4
        return result.stdout, tokens_used

    def _run_claude(
        self,
        prompt: str,
        timeout_seconds: float,
        max_turns: int,
    ) -> tuple[str, int]:
        """Run Claude Code subprocess.

        Returns (output, tokens_used).
        """
        cmd = [
            self.claude_path,
            "--print",
            "--dangerously-skip-permissions",
            "--max-turns",
            str(max(1, max_turns)),
            prompt,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=True,
        )

        # Estimate tokens (rough: ~4 chars per token)
        tokens_used = len(prompt) // 4 + len(result.stdout) // 4

        return result.stdout, tokens_used

    def _parse_result(self, output: str, node: WorkNode) -> NodeResult:
        """Parse structured output from Claude response."""
        result = NodeResult()

        # Extract YAML blocks
        yaml_blocks = self._extract_yaml_blocks(output)

        for block in yaml_blocks:
            try:
                data = yaml.safe_load(block)
                if not isinstance(data, dict):
                    continue

                # Parse claims
                if "claims" in data:
                    result.claims = self._parse_claims(data["claims"])

                # Parse criterion status
                if "criterion_status" in data:
                    result.criterion_status = self._parse_criterion_status(
                        data["criterion_status"]
                    )

                # Parse child requests
                if "needs_children" in data:
                    result.child_requests = self._parse_child_requests(
                        data["needs_children"]
                    )

                # Parse output
                if "output" in data:
                    result.output = data["output"]

            except yaml.YAMLError:
                continue

        # Also try to extract evidence from the response
        result.evidence = self._extract_evidence(output)

        return result

    def _extract_yaml_blocks(self, text: str) -> list[str]:
        """Extract YAML code blocks from text."""
        pattern = r"```yaml\s*(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return matches

    def _parse_claims(self, claims_data: list[dict]) -> list[Claim]:
        """Parse claims from YAML data."""
        claims = []
        for item in claims_data:
            if not isinstance(item, dict):
                continue

            domain = ClaimDomain.GENERAL
            if "domain" in item:
                try:
                    domain = ClaimDomain(item["domain"])
                except ValueError:
                    pass

            claim = Claim(
                proposition=item.get("proposition", ""),
                confidence=float(item.get("confidence", 0.5)),
                evidence_ids=item.get("evidence_ids", []),
                domain=domain,
            )
            claims.append(claim)

        return claims

    def _parse_criterion_status(
        self, status_data: list[dict]
    ) -> list[CriterionStatus]:
        """Parse criterion status from YAML data."""
        statuses = []
        for item in status_data:
            if not isinstance(item, dict):
                continue

            status = CriterionStatus(
                id=item.get("id", ""),
                satisfied=bool(item.get("satisfied", False)),
                confidence=float(item.get("confidence", 0.0)),
            )
            statuses.append(status)

        return statuses

    def _parse_child_requests(self, children_data: list[dict]) -> list[ChildRequest]:
        """Parse child node requests from YAML data."""
        requests = []
        for item in children_data:
            if not isinstance(item, dict):
                continue

            mode = NodeMode.EPISTEMIC
            if "mode" in item:
                try:
                    mode = NodeMode(item["mode"])
                except ValueError:
                    pass

            request = ChildRequest(
                goal=item.get("goal", ""),
                mode=mode,
                rationale=item.get("rationale", ""),
                criteria=item.get("criteria"),
            )
            requests.append(request)

        return requests

    def _extract_evidence(self, output: str) -> list[Evidence]:
        """Extract evidence items from response (e.g., from web searches)."""
        evidence = []

        # Look for source citations
        url_pattern = r"https?://[^\s\)\"'>\]]+"
        urls = re.findall(url_pattern, output)

        for url in set(urls):  # Dedupe
            # Extract domain for summary
            domain_match = re.search(r"https?://([^/]+)", url)
            domain = domain_match.group(1) if domain_match else "unknown"

            ev = Evidence(
                type=EvidenceType.RESEARCH,
                source=url,
                summary=f"Source from {domain}",
                strength=0.7,  # Default for web sources
            )
            evidence.append(ev)

        return evidence


def apply_result_to_node(node: WorkNode, result: NodeResult) -> None:
    """Apply execution result to update node state."""
    # Add claims
    node.claims.extend(result.claims)

    # Add evidence
    node.evidence.extend(result.evidence)

    # Update resource usage
    node.resource_usage.tokens += result.tokens_used
    node.resource_usage.time_ms += result.time_ms
    node.resource_usage.steps += 1
    node.resource_usage.last_updated = datetime.now()

    # Update criterion confidence with flexible ID matching
    criteria = node.goal.acceptance_criteria
    statuses = result.criterion_status

    for i, status in enumerate(statuses):
        matched = False

        # First try exact ID match
        for criterion in criteria:
            if criterion.id == status.id:
                criterion.satisfied = status.satisfied
                criterion.confidence = status.confidence
                matched = True
                break

        # If no exact match and single criterion, apply to it
        if not matched and len(criteria) == 1:
            criteria[0].satisfied = status.satisfied
            criteria[0].confidence = status.confidence
            matched = True

        # If no exact match, try positional matching
        if not matched and i < len(criteria):
            criteria[i].satisfied = status.satisfied
            criteria[i].confidence = status.confidence

    # Update aggregated confidence
    _update_aggregated_confidence(node)

    # Store output if provided
    if result.output:
        from gotn.node import (
            ArtifactOutput,
            CommitmentOutput,
            KnowledgeOutput,
            ValidationOutput,
        )

        output_type = result.output.get("type", "knowledge")
        if output_type == "knowledge":
            node.outputs.append(KnowledgeOutput(**result.output))
        elif output_type == "artifact":
            node.outputs.append(ArtifactOutput(**result.output))
        elif output_type == "commitment":
            node.outputs.append(CommitmentOutput(**result.output))
        elif output_type == "verification":
            node.outputs.append(ValidationOutput(**result.output))

    # Update timestamp
    node.updated_at = datetime.now()


def _update_aggregated_confidence(node: WorkNode) -> None:
    """Recalculate aggregated confidence from criteria."""
    if not node.goal.acceptance_criteria:
        return

    total_weight = 0.0
    weighted_sum = 0.0

    for criterion in node.goal.acceptance_criteria:
        weight = 2.0 if criterion.must_pass else 1.0
        weighted_sum += criterion.confidence * weight
        total_weight += weight

    if total_weight > 0:
        node.confidence.aggregate = weighted_sum / total_weight
        node.confidence.by_criterion = {
            c.id: c.confidence for c in node.goal.acceptance_criteria
        }
        node.confidence.last_computed = datetime.now()
