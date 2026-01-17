"""GOTN - Goal-Oriented Task Network.

Recursive workflow orchestration for LLM agents.
"""

__version__ = "0.1.0"

from gotn.node import (
    WorkNode,
    Goal,
    Criterion,
    Budget,
    ResourceUsage,
    Claim,
    Evidence,
    NodeStatus,
    NodeMode,
    PlanOutput,
    PlannedSubGoal,
)
from gotn.workflow import (
    WorkflowStateMachine,
    WorkflowState,
    WorkflowContext,
    TransitionResult,
    classify_and_route,
)

__all__ = [
    "WorkNode",
    "Goal",
    "Criterion",
    "Budget",
    "ResourceUsage",
    "Claim",
    "Evidence",
    "NodeStatus",
    "NodeMode",
    "PlanOutput",
    "PlannedSubGoal",
    "WorkflowStateMachine",
    "WorkflowState",
    "WorkflowContext",
    "TransitionResult",
    "classify_and_route",
]
