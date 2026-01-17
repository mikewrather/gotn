"""Tests for workflow state machine."""

import pytest

from gotn.node import (
    Claim,
    ClaimDomain,
    CommitmentOutput,
    KnowledgeOutput,
    NodeMode,
    PlanOutput,
    PlannedSubGoal,
    WorkNode,
)
from gotn.workflow import (
    TransitionResult,
    WorkflowContext,
    WorkflowState,
    WorkflowStateMachine,
    classify_and_route,
)


class TestGoalClassification:
    """Tests for goal classification."""

    def test_research_goal_classified_as_uncertain(self):
        """Research goals should start with epistemic mode."""
        machine = WorkflowStateMachine()
        goals = [
            "Research best practices for authentication",
            "Investigate memory leak in the application",
            "Explore options for database migration",
            "Understand the current architecture",
            "Learn about GraphQL federation",
        ]
        for goal in goals:
            state = machine.classify_goal(goal)
            assert state == WorkflowState.UNCERTAIN, f"Failed for: {goal}"

    def test_question_goal_classified_as_uncertain(self):
        """Question goals should start with epistemic mode."""
        machine = WorkflowStateMachine()
        goals = [
            "What is the best way to implement caching?",
            "How does the authentication system work?",
            "Why does the query timeout on large datasets?",
        ]
        for goal in goals:
            state = machine.classify_goal(goal)
            assert state == WorkflowState.UNCERTAIN, f"Failed for: {goal}"

    def test_decision_goal_classified_as_uncertain(self):
        """Decision goals still need research first."""
        machine = WorkflowStateMachine()
        goals = [
            "Choose the best database for our use case",
            "Decide between microservices and monolith",
            "Select a cloud provider for deployment",
        ]
        for goal in goals:
            state = machine.classify_goal(goal)
            assert state == WorkflowState.UNCERTAIN, f"Failed for: {goal}"

    def test_build_goal_classified_as_decided(self):
        """Build goals assume a decision has been made."""
        machine = WorkflowStateMachine()
        goals = [
            "Build a REST API for user management",
            "Create a dashboard component",
            "Implement the authentication middleware",
            "Develop the notification service",
        ]
        for goal in goals:
            state = machine.classify_goal(goal)
            assert state == WorkflowState.DECIDED, f"Failed for: {goal}"

    def test_validation_goal_classified_as_building(self):
        """Validation goals assume an artifact exists."""
        machine = WorkflowStateMachine()
        goals = [
            "Test the new API endpoints",
            "Verify the deployment configuration",
            "Validate the schema migration",
            "Check the security headers",
        ]
        for goal in goals:
            state = machine.classify_goal(goal)
            assert state == WorkflowState.BUILDING, f"Failed for: {goal}"


class TestComplexityEstimation:
    """Tests for goal complexity estimation."""

    def test_simple_goal_low_complexity(self):
        """Short, focused goals should be low complexity."""
        machine = WorkflowStateMachine()
        goals = [
            "Fix the bug",
            "Add a button",
            "Update the README",
        ]
        for goal in goals:
            level, score = machine.estimate_complexity(goal)
            assert level == "simple", f"Failed for: {goal}"
            assert score < 0.3

    def test_moderate_goal_medium_complexity(self):
        """Goals with some signals should be moderate."""
        machine = WorkflowStateMachine()
        goal = "Build a REST API with authentication and logging"
        level, score = machine.estimate_complexity(goal)
        assert level in ("simple", "moderate"), f"Level: {level}, Score: {score}"

    def test_complex_goal_high_complexity(self):
        """System-level goals should be complex."""
        machine = WorkflowStateMachine()
        goals = [
            "Design and implement a distributed system architecture with multiple services and orchestration",
            "Build a scalable pipeline with orchestration and monitoring infrastructure for production",
            "Create a production distributed framework including deployment, scaling, integration and orchestration",
        ]
        for goal in goals:
            level, score = machine.estimate_complexity(goal)
            assert level == "complex", f"Failed for: {goal}, got {level} with score {score}"


class TestWorkflowPreconditions:
    """Tests for workflow precondition checking."""

    def test_epistemic_always_allowed(self):
        """Epistemic mode has no preconditions."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Test goal statement", NodeMode.EPISTEMIC)
        context = WorkflowContext(node=node)

        result = machine.check_preconditions(NodeMode.EPISTEMIC, context)
        assert result.allowed

    def test_decision_requires_claims(self):
        """Decision mode requires claims/evidence."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Test goal statement", NodeMode.EPISTEMIC)

        # No claims
        context = WorkflowContext(node=node, sibling_claims=[])
        result = machine.check_preconditions(NodeMode.DECISION, context)
        assert not result.allowed
        assert "has_claims" in result.missing_preconditions
        assert result.suggested_mode == NodeMode.EPISTEMIC

        # With claims
        claim = Claim(
            proposition="Test claim",
            confidence=0.8,
            domain=ClaimDomain.GENERAL,
        )
        context_with_claims = WorkflowContext(node=node, sibling_claims=[claim])
        result = machine.check_preconditions(NodeMode.DECISION, context_with_claims)
        assert result.allowed

    def test_planning_requires_commitment(self):
        """Planning mode requires a commitment."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Test goal statement", NodeMode.EPISTEMIC)

        # No commitment
        context = WorkflowContext(node=node, has_commitment=False)
        result = machine.check_preconditions(NodeMode.PLANNING, context)
        assert not result.allowed
        assert "has_commitment" in result.missing_preconditions

        # With commitment
        context_with_commitment = WorkflowContext(node=node, has_commitment=True)
        result = machine.check_preconditions(NodeMode.PLANNING, context_with_commitment)
        assert result.allowed

    def test_instrumental_requires_direction(self):
        """Instrumental mode requires commitment or plan."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Test goal statement", NodeMode.EPISTEMIC)

        # No direction
        context = WorkflowContext(node=node, has_commitment=False, has_plan=False)
        result = machine.check_preconditions(NodeMode.INSTRUMENTAL, context)
        assert not result.allowed
        assert "has_direction" in result.missing_preconditions

        # With commitment
        context_with_commitment = WorkflowContext(node=node, has_commitment=True)
        result = machine.check_preconditions(NodeMode.INSTRUMENTAL, context_with_commitment)
        assert result.allowed

        # With plan
        context_with_plan = WorkflowContext(node=node, has_plan=True)
        result = machine.check_preconditions(NodeMode.INSTRUMENTAL, context_with_plan)
        assert result.allowed

    def test_validation_requires_artifact(self):
        """Validation mode requires an artifact."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Test goal statement", NodeMode.EPISTEMIC)

        # No artifact
        context = WorkflowContext(node=node, has_artifact=False)
        result = machine.check_preconditions(NodeMode.VALIDATION, context)
        assert not result.allowed
        assert "has_artifact" in result.missing_preconditions

        # With artifact
        context_with_artifact = WorkflowContext(node=node, has_artifact=True)
        result = machine.check_preconditions(NodeMode.VALIDATION, context_with_artifact)
        assert result.allowed


class TestModeTransitions:
    """Tests for valid mode transitions."""

    def test_epistemic_can_transition_to_decision(self):
        """Epistemic nodes can spawn decision nodes."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Research authentication options", NodeMode.EPISTEMIC)
        claim = Claim(proposition="Test claim proposition", confidence=0.8, domain=ClaimDomain.GENERAL)
        context = WorkflowContext(node=node, sibling_claims=[claim])

        result = machine.can_transition(NodeMode.EPISTEMIC, NodeMode.DECISION, context)
        assert result.allowed

    def test_decision_can_transition_to_planning(self):
        """Decision nodes can spawn planning nodes."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Choose authentication method", NodeMode.DECISION)
        context = WorkflowContext(node=node, has_commitment=True)

        result = machine.can_transition(NodeMode.DECISION, NodeMode.PLANNING, context)
        assert result.allowed

    def test_decision_can_transition_to_instrumental(self):
        """Decision nodes can spawn instrumental nodes."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Choose authentication method", NodeMode.DECISION)
        context = WorkflowContext(node=node, has_commitment=True)

        result = machine.can_transition(NodeMode.DECISION, NodeMode.INSTRUMENTAL, context)
        assert result.allowed

    def test_planning_can_transition_to_instrumental(self):
        """Planning nodes spawn instrumental nodes."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Plan authentication implementation", NodeMode.PLANNING)
        context = WorkflowContext(node=node, has_plan=True)

        result = machine.can_transition(NodeMode.PLANNING, NodeMode.INSTRUMENTAL, context)
        assert result.allowed

    def test_instrumental_can_transition_to_validation(self):
        """Instrumental nodes spawn validation nodes."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Build authentication module", NodeMode.INSTRUMENTAL)
        context = WorkflowContext(node=node, has_artifact=True)

        result = machine.can_transition(NodeMode.INSTRUMENTAL, NodeMode.VALIDATION, context)
        assert result.allowed

    def test_invalid_transition_blocked(self):
        """Invalid transitions are blocked."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Research authentication options", NodeMode.EPISTEMIC)
        context = WorkflowContext(node=node, has_artifact=True)

        # Epistemic cannot go directly to validation
        result = machine.can_transition(NodeMode.EPISTEMIC, NodeMode.VALIDATION, context)
        assert not result.allowed

    def test_any_mode_can_go_back_to_epistemic(self):
        """Any mode can spawn epistemic children for research."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Build authentication module", NodeMode.INSTRUMENTAL)
        context = WorkflowContext(node=node)

        result = machine.can_transition(NodeMode.INSTRUMENTAL, NodeMode.EPISTEMIC, context)
        assert result.allowed


class TestEntryModeSelection:
    """Tests for entry mode selection."""

    def test_research_goal_enters_epistemic(self):
        """Research goals enter via epistemic mode."""
        machine = WorkflowStateMachine()
        mode, state = machine.get_entry_mode("Research authentication patterns")
        assert mode == NodeMode.EPISTEMIC
        assert state == WorkflowState.UNCERTAIN

    def test_build_goal_enters_decided(self):
        """Build goals assume decision made."""
        machine = WorkflowStateMachine()
        mode, state = machine.get_entry_mode("Build the user dashboard")
        assert mode == NodeMode.PLANNING  # DECIDED maps to PLANNING
        assert state == WorkflowState.DECIDED


class TestPlanningModeSelection:
    """Tests for planning mode selection based on complexity."""

    def test_complex_goal_uses_planning(self):
        """Complex goals should use planning mode."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root(
            "Build a distributed microservices architecture with orchestration",
            NodeMode.EPISTEMIC,
        )
        context = WorkflowContext(node=node, has_commitment=True)

        should_plan = machine.should_use_planning(context)
        assert should_plan

    def test_simple_goal_skips_planning(self):
        """Simple goals should skip planning mode."""
        machine = WorkflowStateMachine()
        node = WorkNode.create_root("Add a button component", NodeMode.EPISTEMIC)
        context = WorkflowContext(node=node, has_commitment=True)

        should_plan = machine.should_use_planning(context)
        assert not should_plan


class TestConvenienceFunction:
    """Tests for the classify_and_route convenience function."""

    def test_classify_and_route(self):
        """Quick classification returns mode and complexity."""
        mode, complexity, score = classify_and_route(
            "Research distributed system patterns"
        )
        assert mode == NodeMode.EPISTEMIC
        assert complexity in ("simple", "moderate", "complex")
        assert 0.0 <= score <= 1.0


class TestPlanOutput:
    """Tests for PlanOutput model."""

    def test_plan_output_creation(self):
        """PlanOutput can be created with sub-goals."""
        plan = PlanOutput(
            sub_goals=[
                PlannedSubGoal(
                    goal_statement="Research authentication patterns",
                    mode="epistemic",
                    rationale="Need to understand options",
                    depends_on=[],
                ),
                PlannedSubGoal(
                    goal_statement="Choose authentication approach",
                    mode="decision",
                    rationale="Must decide before building",
                    depends_on=[0],
                ),
                PlannedSubGoal(
                    goal_statement="Implement authentication middleware",
                    mode="instrumental",
                    rationale="Build the chosen approach",
                    depends_on=[1],
                ),
            ],
            decomposition_rationale="Standard auth implementation flow",
            execution_order=[0, 1, 2],
            parallel_groups=[],
            critical_path=[0, 1, 2],
        )

        assert len(plan.sub_goals) == 3
        assert plan.sub_goals[0].mode == "epistemic"
        assert plan.sub_goals[1].depends_on == [0]

    def test_plan_output_type(self):
        """PlanOutput has type 'plan'."""
        plan = PlanOutput(sub_goals=[])
        assert plan.type == "plan"
