"""Workflow state machine for mode sequencing and preconditions.

This module governs the valid transitions between WorkNode modes and
enforces preconditions that must be met before a mode can be entered.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from gotn.node import (
    Claim,
    CommitmentOutput,
    KnowledgeOutput,
    NodeMode,
    PlanOutput,
    WorkNode,
)


class WorkflowState(str, Enum):
    """High-level workflow states that govern mode sequencing."""

    UNCERTAIN = "uncertain"  # Need research to understand the problem
    INFORMED = "informed"  # Have claims, can make decisions
    DECIDED = "decided"  # Have commitment, can plan or build
    PLANNED = "planned"  # Have plan, ready to execute
    BUILDING = "building"  # Producing artifacts
    VALIDATING = "validating"  # Verifying artifacts


@dataclass
class TransitionResult:
    """Result of attempting a workflow transition."""

    allowed: bool
    reason: str = ""
    suggested_mode: Optional[NodeMode] = None
    missing_preconditions: list[str] = field(default_factory=list)


@dataclass
class WorkflowContext:
    """Context for evaluating workflow preconditions."""

    node: WorkNode
    parent_node: Optional[WorkNode] = None
    sibling_claims: list[Claim] = field(default_factory=list)
    has_commitment: bool = False
    has_plan: bool = False
    has_artifact: bool = False
    goal_complexity: str = "unknown"  # simple, moderate, complex


class WorkflowStateMachine:
    """State machine governing mode transitions and preconditions.

    The workflow follows this general pattern:

    1. UNCERTAIN goals → EPISTEMIC mode (research to gather claims)
    2. INFORMED (have claims) → DECISION mode (choose approach)
    3. DECIDED (have commitment) → PLANNING or INSTRUMENTAL mode
       - Complex goals → PLANNING (decompose into sub-goals)
       - Simple goals → INSTRUMENTAL (build directly)
    4. PLANNED (have plan) → spawn INSTRUMENTAL children
    5. BUILDING (have artifacts) → VALIDATION mode

    The state machine prevents:
    - Making decisions without evidence
    - Building without a clear direction
    - Validating non-existent artifacts
    """

    # Mode preconditions: what must be true to enter each mode
    PRECONDITIONS: dict[NodeMode, list[str]] = {
        NodeMode.EPISTEMIC: [],  # Can always research
        NodeMode.DECISION: ["has_claims"],  # Need evidence to decide
        NodeMode.PLANNING: ["has_commitment"],  # Need decision before planning
        NodeMode.INSTRUMENTAL: ["has_direction"],  # Need commitment or plan
        NodeMode.VALIDATION: ["has_artifact"],  # Need something to validate
    }

    # Valid mode transitions
    VALID_TRANSITIONS: dict[NodeMode, list[NodeMode]] = {
        NodeMode.EPISTEMIC: [NodeMode.DECISION, NodeMode.EPISTEMIC],
        NodeMode.DECISION: [NodeMode.PLANNING, NodeMode.INSTRUMENTAL, NodeMode.EPISTEMIC],
        NodeMode.PLANNING: [NodeMode.INSTRUMENTAL, NodeMode.EPISTEMIC],
        NodeMode.INSTRUMENTAL: [NodeMode.VALIDATION, NodeMode.EPISTEMIC],
        NodeMode.VALIDATION: [NodeMode.INSTRUMENTAL, NodeMode.EPISTEMIC],
    }

    # Workflow state to suggested entry mode
    STATE_TO_MODE: dict[WorkflowState, NodeMode] = {
        WorkflowState.UNCERTAIN: NodeMode.EPISTEMIC,
        WorkflowState.INFORMED: NodeMode.DECISION,
        WorkflowState.DECIDED: NodeMode.PLANNING,  # Or INSTRUMENTAL for simple goals
        WorkflowState.PLANNED: NodeMode.INSTRUMENTAL,
        WorkflowState.BUILDING: NodeMode.INSTRUMENTAL,
        WorkflowState.VALIDATING: NodeMode.VALIDATION,
    }

    def __init__(self, complexity_threshold: float = 0.6):
        """Initialize the workflow state machine.

        Args:
            complexity_threshold: Score above which goals are considered complex
                                 and require PLANNING mode (0.0-1.0)
        """
        self.complexity_threshold = complexity_threshold
        self._precondition_checkers: dict[str, Callable[[WorkflowContext], bool]] = {
            "has_claims": self._check_has_claims,
            "has_commitment": self._check_has_commitment,
            "has_direction": self._check_has_direction,
            "has_artifact": self._check_has_artifact,
        }

    def classify_goal(self, goal_statement: str) -> WorkflowState:
        """Classify a goal to determine its initial workflow state.

        This is a heuristic classification based on goal keywords and patterns.
        More sophisticated classification could use LLM analysis.
        """
        goal_lower = goal_statement.lower()

        # Research/question patterns → UNCERTAIN
        research_patterns = [
            "research", "investigate", "explore", "understand",
            "learn about", "find out", "discover", "analyze",
            "what is", "how does", "why does", "when should",
            "compare", "evaluate", "assess",
        ]
        if any(p in goal_lower for p in research_patterns):
            return WorkflowState.UNCERTAIN

        # Decision patterns → needs research first if no context
        decision_patterns = [
            "choose", "decide", "select", "pick", "determine",
            "should i", "which", "best approach",
        ]
        if any(p in goal_lower for p in decision_patterns):
            return WorkflowState.UNCERTAIN  # Need research before deciding

        # Build/create patterns → DECIDED (assumes commitment exists)
        build_patterns = [
            "build", "create", "implement", "develop", "write",
            "make", "generate", "produce", "construct",
        ]
        if any(p in goal_lower for p in build_patterns):
            return WorkflowState.DECIDED

        # Validation patterns → BUILDING (assumes artifact exists)
        validation_patterns = [
            "test", "verify", "validate", "check", "ensure",
            "confirm", "review", "audit",
        ]
        if any(p in goal_lower for p in validation_patterns):
            return WorkflowState.BUILDING

        # Default to uncertain - research first
        return WorkflowState.UNCERTAIN

    def estimate_complexity(self, goal_statement: str) -> tuple[str, float]:
        """Estimate the complexity of a goal.

        Returns:
            Tuple of (complexity_level, score) where level is 'simple',
            'moderate', or 'complex' and score is 0.0-1.0.
        """
        goal_lower = goal_statement.lower()
        score = 0.0

        # Complexity indicators
        complexity_signals = {
            # Multi-component indicators
            "and": 0.1,
            "with": 0.05,
            "including": 0.1,
            "multiple": 0.15,
            "various": 0.1,
            "several": 0.1,
            # System-level indicators
            "system": 0.15,
            "architecture": 0.2,
            "framework": 0.15,
            "infrastructure": 0.2,
            "pipeline": 0.15,
            # Integration indicators
            "integrate": 0.15,
            "connect": 0.1,
            "orchestrat": 0.2,
            "coordinat": 0.15,
            # Scale indicators
            "scalab": 0.15,
            "distributed": 0.2,
            "production": 0.1,
        }

        for signal, weight in complexity_signals.items():
            if signal in goal_lower:
                score += weight

        # Length of goal statement is a rough proxy
        word_count = len(goal_statement.split())
        if word_count > 20:
            score += 0.15
        elif word_count > 10:
            score += 0.05

        # Cap at 1.0
        score = min(1.0, score)

        if score >= self.complexity_threshold:
            return ("complex", score)
        elif score >= 0.3:
            return ("moderate", score)
        else:
            return ("simple", score)

    def get_entry_mode(self, goal_statement: str) -> tuple[NodeMode, WorkflowState]:
        """Determine the appropriate entry mode for a new goal.

        Returns:
            Tuple of (entry_mode, workflow_state)
        """
        state = self.classify_goal(goal_statement)
        mode = self.STATE_TO_MODE[state]
        return (mode, state)

    def check_preconditions(
        self, target_mode: NodeMode, context: WorkflowContext
    ) -> TransitionResult:
        """Check if preconditions are met to enter a mode.

        Args:
            target_mode: The mode we want to transition to
            context: Current workflow context

        Returns:
            TransitionResult indicating if transition is allowed
        """
        required = self.PRECONDITIONS.get(target_mode, [])
        missing = []

        for precondition in required:
            checker = self._precondition_checkers.get(precondition)
            if checker and not checker(context):
                missing.append(precondition)

        if missing:
            suggested = self._suggest_mode_for_missing(missing, context)
            return TransitionResult(
                allowed=False,
                reason=f"Missing preconditions: {', '.join(missing)}",
                suggested_mode=suggested,
                missing_preconditions=missing,
            )

        return TransitionResult(allowed=True)

    def can_transition(
        self, from_mode: NodeMode, to_mode: NodeMode, context: WorkflowContext
    ) -> TransitionResult:
        """Check if a transition from one mode to another is valid.

        Args:
            from_mode: Current mode
            to_mode: Target mode
            context: Workflow context

        Returns:
            TransitionResult
        """
        # Check if transition is in valid set
        valid_targets = self.VALID_TRANSITIONS.get(from_mode, [])
        if to_mode not in valid_targets:
            return TransitionResult(
                allowed=False,
                reason=f"Invalid transition: {from_mode.value} → {to_mode.value}",
                suggested_mode=valid_targets[0] if valid_targets else None,
            )

        # Check preconditions for target mode
        return self.check_preconditions(to_mode, context)

    def should_use_planning(self, context: WorkflowContext) -> bool:
        """Determine if a goal should use PLANNING mode.

        Complex goals benefit from explicit decomposition.
        Simple goals can go directly to INSTRUMENTAL.
        """
        if not context.has_commitment:
            return False

        complexity, score = self.estimate_complexity(context.node.goal.statement)
        return complexity == "complex" or score >= self.complexity_threshold

    def _check_has_claims(self, context: WorkflowContext) -> bool:
        """Check if we have claims to base decisions on."""
        # Check node's own claims
        if context.node.claims:
            return True
        # Check claims from parent or siblings
        if context.sibling_claims:
            return True
        # Check if parent has knowledge output
        if context.parent_node:
            for output in context.parent_node.outputs:
                if isinstance(output, KnowledgeOutput) and output.claims:
                    return True
        return False

    def _check_has_commitment(self, context: WorkflowContext) -> bool:
        """Check if we have a commitment/decision."""
        if context.has_commitment:
            return True
        # Check node outputs for commitment
        for output in context.node.outputs:
            if isinstance(output, CommitmentOutput):
                return True
        # Check parent for commitment
        if context.parent_node:
            for output in context.parent_node.outputs:
                if isinstance(output, CommitmentOutput):
                    return True
        return False

    def _check_has_direction(self, context: WorkflowContext) -> bool:
        """Check if we have direction (commitment or plan)."""
        return context.has_commitment or context.has_plan

    def _check_has_artifact(self, context: WorkflowContext) -> bool:
        """Check if we have an artifact to validate."""
        return context.has_artifact

    def _suggest_mode_for_missing(
        self, missing: list[str], context: WorkflowContext
    ) -> Optional[NodeMode]:
        """Suggest a mode to address missing preconditions."""
        if "has_claims" in missing:
            return NodeMode.EPISTEMIC
        if "has_commitment" in missing:
            return NodeMode.DECISION
        if "has_direction" in missing:
            return NodeMode.DECISION
        if "has_artifact" in missing:
            return NodeMode.INSTRUMENTAL
        return None


# Convenience function for quick classification
def classify_and_route(goal_statement: str) -> tuple[NodeMode, str, float]:
    """Classify a goal and determine routing.

    Returns:
        Tuple of (entry_mode, complexity_level, complexity_score)
    """
    machine = WorkflowStateMachine()
    mode, _ = machine.get_entry_mode(goal_statement)
    complexity, score = machine.estimate_complexity(goal_statement)
    return (mode, complexity, score)
