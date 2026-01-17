"""Claude Code executor for WorkNode execution."""

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import yaml

logger = logging.getLogger(__name__)

T = TypeVar("T")

from gotn.context import BuiltContext, ContextBudget, build_execution_context
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


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt using exponential backoff."""
        delay = self.base_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)


class RetryableError(Exception):
    """Error that should trigger a retry."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


def with_retry(
    func: Callable[[], T],
    config: RetryConfig,
    operation_name: str = "operation",
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        func: Function to execute (should raise RetryableError on transient failures)
        config: Retry configuration
        operation_name: Name for logging

    Returns:
        Result of successful function execution

    Raises:
        The last exception if all retries exhausted
    """
    last_error: Optional[Exception] = None

    for attempt in range(config.max_retries + 1):
        try:
            return func()
        except RetryableError as e:
            last_error = e.original_error or e
            if attempt < config.max_retries:
                delay = config.get_delay(attempt)
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{config.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"{operation_name} failed after {config.max_retries + 1} attempts: {e}"
                )
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Don't retry timeouts or user interrupts
            raise

    # Should not reach here, but raise last error if we do
    if last_error:
        raise last_error
    raise RuntimeError(f"{operation_name} failed with no error captured")


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
class BudgetExpansionRequest:
    """Request to expand execution budget.

    When Claude needs more turns to complete a task, it can request
    a budget expansion. This requires human approval before continuing.
    """

    current_turns: int
    requested_additional: int
    justification: str
    estimated_completion_confidence: float
    progress_summary: Optional[str] = None

    @property
    def total_requested(self) -> int:
        return self.current_turns + self.requested_additional


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
    log_file: Optional[str] = None  # Path to execution log file
    budget_request: Optional[BudgetExpansionRequest] = None  # Budget expansion needed
    needs_budget_approval: bool = False  # True if execution paused for budget


@dataclass
class ExecutionContext:
    """Context for node execution.

    Now integrates with the three-tier context model via BuiltContext.
    Legacy fields maintained for backwards compatibility.
    """

    # Legacy fields (backwards compat)
    parent_goal: Optional[str] = None
    sibling_claims: list[Claim] = field(default_factory=list)
    available_evidence: list[Evidence] = field(default_factory=list)
    max_depth: int = 5

    # New three-tier context (preferred)
    built_context: Optional[BuiltContext] = None

    @property
    def has_built_context(self) -> bool:
        """Check if three-tier context is available."""
        return self.built_context is not None


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
        output_section = self._build_output_format(node)

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
        """Build the criteria section of the prompt.

        Includes criterion IDs that must be referenced in output.
        """
        lines = []
        for criterion in node.goal.acceptance_criteria:
            status = "[x]" if criterion.satisfied else "[ ]"
            must_pass = " (REQUIRED)" if criterion.must_pass else ""
            confidence = f" [{criterion.confidence:.0%}]" if criterion.confidence > 0 else ""
            # Include criterion ID for output referencing
            lines.append(
                f"- {status} **{criterion.id}**: {criterion.description} "
                f"(type: {criterion.type.value}){must_pass}{confidence}"
            )
        return "\n".join(lines) or "- No specific criteria defined"

    def _build_context_section(self, node: WorkNode, context: ExecutionContext) -> str:
        """Build the context section of the prompt.

        Uses three-tier context when available, falls back to legacy.
        """
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

        # Use three-tier context if available
        if context.has_built_context:
            bc = context.built_context
            lines.append("")
            lines.append("### Three-Tier Context")
            lines.append(bc.to_prompt_section())

            # Add VoI scores for transparency
            if bc.voi_scores:
                voi_text = ", ".join(f"{k}={v:.2f}" for k, v in bc.voi_scores.items())
                lines.append(f"- VoI scores: {voi_text}")
        else:
            # Legacy context
            if context.parent_goal:
                lines.append(f"- Parent goal: {context.parent_goal}")

        return "\n".join(lines)

    def _build_evidence_section(self, context: ExecutionContext) -> str:
        """Build the evidence section of the prompt.

        Combines legacy evidence with Tier 2 claims when available.
        """
        lines = []

        # Legacy evidence
        if context.available_evidence:
            for ev in context.available_evidence:
                recency = ev.recency.strftime("%Y-%m-%d") if ev.recency else "unknown"
                lines.append(
                    f"- [{ev.id}] {ev.summary} "
                    f"(strength: {ev.strength:.0%}, recency: {recency})"
                )

        # Tier 2 related evidence (from built context)
        if context.has_built_context:
            bc = context.built_context
            if bc.tier2.related_evidence:
                lines.append("\n### Related Evidence (Tier 2)")
                for ev in bc.tier2.related_evidence[:5]:
                    lines.append(f"- [{ev.id}] {ev.summary} ({ev.strength:.0%})")

        if not lines:
            return "No prior evidence available."

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

    def _build_output_format(self, node: WorkNode) -> str:
        """Build the expected output format with actual criterion IDs.

        Includes the node's criterion IDs to ensure correct referencing.
        """
        # Build criterion ID reference list
        criterion_ids = [c.id for c in node.goal.acceptance_criteria]
        criterion_id_list = ", ".join(f'"{cid}"' for cid in criterion_ids)

        # Build example with first actual criterion ID
        example_id = criterion_ids[0] if criterion_ids else "crit-xxx"

        return f"""Return a structured YAML block at the end of your response.

**IMPORTANT**: Use the exact criterion IDs from the Acceptance Criteria section above.
Valid criterion IDs for this node: [{criterion_id_list}]

```yaml
claims:
  - proposition: "..."
    confidence: 0.85
    evidence_ids: [ev-001]
    domain: general

criterion_status:  # Use EXACT criterion IDs from above
  - id: "{example_id}"  # Must match an ID from the criteria list
    satisfied: true
    confidence: 0.9

needs_children:  # Only if blocked and need sub-work
  - goal: "Research X"
    mode: epistemic
    rationale: "Need more information about X"

output:  # Only if complete
  type: knowledge|artifact|commitment|verification|plan
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
        default_timeout_ms: int = 600000,  # 10 minutes
        prefer_skills: bool = True,
        retry_config: Optional[RetryConfig] = None,
        store_path: Optional[Path] = None,
        use_budget_hook: bool = True,
    ):
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.claude_path = claude_path
        self.default_timeout_ms = default_timeout_ms
        self.prefer_skills = prefer_skills
        self.retry_config = retry_config or RetryConfig()
        self.store_path = store_path or Path("store")
        self.logs_dir = self.store_path / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.use_budget_hook = use_budget_hook
        self.budget_state_dir = self.store_path / "budget_states"
        self.budget_state_dir.mkdir(parents=True, exist_ok=True)

    def _init_budget_state(self, node: WorkNode) -> Path:
        """Initialize budget tracking state for a node execution."""
        state_file = self.budget_state_dir / f"{node.id}_budget.json"
        max_turns = node.budget.steps or 50  # Default to 50 turns
        checkpoint_at = max(1, max_turns - 2)  # Checkpoint 2 turns before limit

        state = {
            "turn_count": 0,
            "budget_turns": max_turns,
            "checkpoint_at": checkpoint_at,
            "node_id": node.id,
            "goal": node.goal.statement,
            "checkpointed": False,
            "progress_summary": None,
            "created_at": datetime.now().isoformat(),
        }
        state_file.write_text(json.dumps(state, indent=2))
        return state_file

    def _get_budget_env(self, node: WorkNode) -> dict[str, str]:
        """Get environment variables for budget tracking."""
        state_file = self._init_budget_state(node)
        return {
            "GOTN_EXECUTION": "1",
            "GOTN_BUDGET_STATE": str(state_file),
            "GOTN_NODE_ID": node.id,
        }

    def _parse_budget_request(self, output: str) -> Optional[BudgetExpansionRequest]:
        """Parse budget expansion request from Claude's output."""
        # Look for budget_request YAML block
        yaml_blocks = self._extract_yaml_blocks(output)

        for block in yaml_blocks:
            try:
                data = yaml.safe_load(block)
                if not isinstance(data, dict):
                    continue

                if "budget_request" in data:
                    req = data["budget_request"]
                    return BudgetExpansionRequest(
                        current_turns=int(req.get("current_turns", 0)),
                        requested_additional=int(req.get("requested_additional", 10)),
                        justification=str(req.get("justification", "")),
                        estimated_completion_confidence=float(
                            req.get("estimated_completion_confidence", 0.5)
                        ),
                        progress_summary=req.get("progress_summary"),
                    )
            except (yaml.YAMLError, KeyError, ValueError):
                continue

        return None

    def _write_log(
        self,
        node: WorkNode,
        strategy: "ExecutionStrategy",
        raw_output: str,
        error: Optional[str] = None,
        time_ms: int = 0,
    ) -> str:
        """Write execution log and return log file path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{node.id}_{timestamp}.log"
        log_path = self.logs_dir / log_filename

        with open(log_path, "w") as f:
            f.write(f"=" * 80 + "\n")
            f.write(f"GOTN Execution Log\n")
            f.write(f"=" * 80 + "\n\n")
            f.write(f"Node ID: {node.id}\n")
            f.write(f"Mode: {node.mode.value}\n")
            f.write(f"Goal: {node.goal.statement}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Duration: {time_ms}ms\n")
            f.write(f"\n")
            f.write(f"Strategy:\n")
            f.write(f"  Use Skill: {strategy.use_skill}\n")
            if strategy.skill_name:
                f.write(f"  Skill: {strategy.skill_name}\n")
                f.write(f"  Args: {strategy.skill_args}\n")
            f.write(f"  Reason: {strategy.reason}\n")
            f.write(f"\n")
            if error:
                f.write(f"ERROR: {error}\n")
                f.write(f"\n")
            f.write(f"=" * 80 + "\n")
            f.write(f"OUTPUT\n")
            f.write(f"=" * 80 + "\n\n")
            f.write(raw_output)

        return str(log_path)

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
        If budget is exhausted during execution, returns with needs_budget_approval=True
        and a budget_request for human approval.
        """
        start_time = datetime.now()

        # Determine execution strategy
        strategy = self.determine_strategy(node, context)

        # Calculate timeout
        timeout_ms = node.budget.time_ms or self.default_timeout_ms
        remaining_ms = timeout_ms - node.resource_usage.time_ms
        timeout_seconds = max(1, remaining_ms / 1000)

        # Calculate max turns - use budget.steps as soft limit for checkpointing
        # but allow higher hard limit to avoid premature termination
        soft_limit = node.budget.steps or 20
        remaining_soft = soft_limit - node.resource_usage.steps
        hard_limit = max(remaining_soft + 10, 50)  # Always allow some runway

        # Get budget tracking environment
        budget_env = self._get_budget_env(node) if self.use_budget_hook else {}

        # Execute based on strategy
        try:
            if strategy.use_skill and strategy.skill_name:
                raw_output, tokens_used = self._run_skill(
                    skill_name=strategy.skill_name,
                    skill_args=strategy.skill_args or "",
                    timeout_seconds=timeout_seconds,
                    env_vars=budget_env,
                )
            else:
                raw_output, tokens_used = self._run_claude(
                    prompt=strategy.prompt or "",
                    timeout_seconds=timeout_seconds,
                    max_turns=hard_limit,
                    soft_limit=remaining_soft,
                    env_vars=budget_env,
                )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            error_msg = "Execution timed out"
            log_file = self._write_log(node, strategy, "", error_msg, elapsed_ms)
            return NodeResult(
                error=error_msg,
                time_ms=elapsed_ms,
                raw_output="",
                log_file=log_file,
            )
        except subprocess.CalledProcessError as e:
            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            # Check if this was a max-turns termination
            stdout = e.stdout or ""
            if "Reached max turns" in stdout or "max turns" in (e.stderr or "").lower():
                # Max turns hit - check for budget request in output
                budget_req = self._parse_budget_request(stdout)
                log_file = self._write_log(node, strategy, stdout, "Budget limit reached", elapsed_ms)
                result = self._parse_result(stdout, node)
                result.time_ms = elapsed_ms
                result.raw_output = stdout
                result.log_file = log_file
                result.budget_request = budget_req or BudgetExpansionRequest(
                    current_turns=hard_limit,
                    requested_additional=20,
                    justification="Task requires more turns to complete",
                    estimated_completion_confidence=0.5,
                )
                result.needs_budget_approval = True
                return result

            error_msg = f"Claude execution failed: {e.stderr}"
            log_file = self._write_log(node, strategy, stdout, error_msg, elapsed_ms)
            return NodeResult(
                error=error_msg,
                time_ms=elapsed_ms,
                raw_output=stdout,
                log_file=log_file,
            )

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Check for budget expansion request in successful output
        budget_req = self._parse_budget_request(raw_output)

        # Write execution log
        log_file = self._write_log(node, strategy, raw_output, None, elapsed_ms)

        # Parse result
        result = self._parse_result(raw_output, node)
        result.time_ms = elapsed_ms
        result.tokens_used = tokens_used
        result.raw_output = raw_output
        result.log_file = log_file

        # If budget request found, flag for approval
        if budget_req:
            result.budget_request = budget_req
            result.needs_budget_approval = True

        return result

    def _run_skill(
        self,
        skill_name: str,
        skill_args: str,
        timeout_seconds: float,
        env_vars: Optional[dict[str, str]] = None,
    ) -> tuple[str, int]:
        """Run a Claude Code skill with retry logic.

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

        # Merge environment variables
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        def execute():
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=True,
                    env=env,
                )
                return result
            except subprocess.CalledProcessError as e:
                # Retry on transient failures (non-zero exit codes)
                if self._is_retryable_error(e):
                    raise RetryableError(
                        f"Skill execution failed: {e.stderr or e.returncode}",
                        original_error=e,
                    )
                raise

        result = with_retry(
            execute,
            self.retry_config,
            operation_name=f"skill:{skill_name}",
        )

        tokens_used = len(prompt) // 4 + len(result.stdout) // 4
        return result.stdout, tokens_used

    def _run_claude(
        self,
        prompt: str,
        timeout_seconds: float,
        max_turns: int,
        soft_limit: int = 20,
        env_vars: Optional[dict[str, str]] = None,
    ) -> tuple[str, int]:
        """Run Claude Code subprocess with retry logic.

        Args:
            prompt: The prompt to send to Claude
            timeout_seconds: Maximum execution time
            max_turns: Hard limit on turns (safety net)
            soft_limit: Soft limit - checkpoint instructions added at this point
            env_vars: Environment variables for budget tracking

        Returns (output, tokens_used).
        """
        # Inject budget checkpoint instructions into prompt
        budget_instruction = f"""

## Budget Management
You have a soft budget of {soft_limit} turns to complete this task.
If you're approaching the limit and haven't completed, include a budget_request:

```yaml
budget_request:
  current_turns: <turns used so far>
  requested_additional: <additional turns needed>
  justification: "<brief explanation>"
  estimated_completion_confidence: <0.0-1.0>
  progress_summary: "<what you've accomplished>"
```

This will pause execution for human approval before continuing.
"""
        full_prompt = prompt + budget_instruction

        cmd = [
            self.claude_path,
            "--print",
            "--dangerously-skip-permissions",
            "--max-turns",
            str(max(1, max_turns)),
            full_prompt,
        ]

        # Merge environment variables
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        def execute():
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=True,
                    env=env,
                )
                return result
            except subprocess.CalledProcessError as e:
                # Retry on transient failures
                if self._is_retryable_error(e):
                    raise RetryableError(
                        f"Claude execution failed: {e.stderr or e.returncode}",
                        original_error=e,
                    )
                raise

        result = with_retry(
            execute,
            self.retry_config,
            operation_name="claude",
        )

        # Estimate tokens (rough: ~4 chars per token)
        tokens_used = len(full_prompt) // 4 + len(result.stdout) // 4

        return result.stdout, tokens_used

    def _is_retryable_error(self, error: subprocess.CalledProcessError) -> bool:
        """Determine if an error is retryable.

        Retries on transient failures like:
        - Network/connection errors
        - Rate limiting (429)
        - Server errors (5xx)
        - Temporary unavailability

        Does NOT retry on:
        - Invalid input (permanent failure)
        - Authentication errors
        - Permission errors
        """
        stderr = error.stderr or ""
        returncode = error.returncode

        # Common retryable patterns in stderr
        retryable_patterns = [
            "rate limit",
            "too many requests",
            "temporarily unavailable",
            "connection refused",
            "connection reset",
            "timeout",
            "ECONNREFUSED",
            "ETIMEDOUT",
            "network",
            "503",
            "502",
            "500",
            "overloaded",
        ]

        stderr_lower = stderr.lower()
        for pattern in retryable_patterns:
            if pattern.lower() in stderr_lower:
                return True

        # Retry on generic transient exit codes
        # Exit code 1 could be many things; be conservative
        # Exit codes > 128 usually indicate signals
        if returncode in (75, 69):  # EX_TEMPFAIL, EX_UNAVAILABLE
            return True

        return False

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
    if result.log_file:
        node.resource_usage.log_file = result.log_file

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
            PlanOutput,
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
        elif output_type == "plan":
            node.outputs.append(PlanOutput(**result.output))

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


def create_execution_context_with_tiers(
    node: WorkNode,
    state_manager,
    max_depth: int = 5,
    context_budget: int = 8000,
) -> ExecutionContext:
    """Create ExecutionContext with three-tier context pre-fetched.

    This is the preferred way to create execution context as it
    pre-fetches Tier 2 data based on VoI, eliminating the need for
    runtime queries.

    Args:
        node: Node to execute
        state_manager: StateManager for loading related nodes
        max_depth: Maximum tree depth
        context_budget: Total token budget for context

    Returns:
        ExecutionContext with built_context populated
    """
    # Build three-tier context
    built = build_execution_context(
        node=node,
        state_manager=state_manager,
        total_budget=context_budget,
    )

    # Also populate legacy fields for backwards compatibility
    parent_goal = None
    if node.parent:
        try:
            parent = state_manager.load_node(node.parent)
            parent_goal = parent.goal.statement
        except FileNotFoundError:
            pass

    return ExecutionContext(
        parent_goal=parent_goal,
        sibling_claims=built.tier2.sibling_claims,
        available_evidence=built.tier2.related_evidence,
        max_depth=max_depth,
        built_context=built,
    )
