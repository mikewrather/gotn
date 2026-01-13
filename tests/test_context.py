"""Tests for three-tier context management."""

import pytest
from gotn.context import (
    ContextBudget,
    ContextBuilder,
    GoalCapsule,
    GoalChainEntry,
    VoIFactors,
    VOI_THRESHOLD,
)
from gotn.node import NodeMode, NodeStatus, WorkNode, Goal, Criterion, CriterionType, DeliverableType


class TestContextBudget:
    """Tests for ContextBudget token tracking."""

    def test_default_budget_allocation(self):
        """Budget allocates correctly across tiers."""
        budget = ContextBudget(total_tokens=10000)

        assert budget.tier1_budget == 800  # 8%
        assert budget.tier2_budget == 2000  # 20%
        assert budget.work_budget == 6000  # 60%
        assert budget.reserve_budget == 1200  # 12%

    def test_estimate_tokens(self):
        """Token estimation works correctly."""
        budget = ContextBudget()
        text = "a" * 400  # 400 chars = ~100 tokens
        assert budget.estimate_tokens(text) == 100

    def test_can_fit_tier1(self):
        """Check if text fits in Tier 1."""
        budget = ContextBudget(total_tokens=1000)  # tier1 = 80 tokens

        short_text = "a" * 200  # 50 tokens
        long_text = "a" * 400  # 100 tokens

        assert budget.can_fit_tier1(short_text)
        assert not budget.can_fit_tier1(long_text)

    def test_add_tier1_tracks_usage(self):
        """Adding to Tier 1 tracks usage correctly."""
        budget = ContextBudget(total_tokens=1000)

        text = "a" * 200  # 50 tokens
        assert budget.add_tier1(text)
        assert budget.tier1_used == 50
        assert budget.tier1_remaining == 30  # 80 - 50

    def test_tier2_exhaustion(self):
        """Tier 2 correctly reports exhaustion."""
        budget = ContextBudget(total_tokens=100)  # tier2 = 20 tokens

        text1 = "a" * 40  # 10 tokens
        text2 = "a" * 60  # 15 tokens

        assert budget.add_tier2(text1)
        assert not budget.add_tier2(text2)  # Would exceed


class TestVoIFactors:
    """Tests for Value of Information calculation."""

    def test_voi_calculation(self):
        """VoI formula calculates correctly."""
        voi = VoIFactors(
            uncertainty=0.8,
            decision_impact=0.5,
            query_cost=1.0,
        )
        assert voi.value == pytest.approx(0.4)

    def test_voi_zero_cost(self):
        """Zero cost returns zero (avoid division by zero)."""
        voi = VoIFactors(uncertainty=0.5, decision_impact=0.5, query_cost=0.0)
        assert voi.value == 0.0

    def test_high_uncertainty_high_voi(self):
        """High uncertainty increases VoI."""
        low_uncertainty = VoIFactors(uncertainty=0.2, decision_impact=0.5, query_cost=1.0)
        high_uncertainty = VoIFactors(uncertainty=0.9, decision_impact=0.5, query_cost=1.0)

        assert high_uncertainty.value > low_uncertainty.value


class TestGoalCapsule:
    """Tests for goal capsule creation."""

    def test_capsule_checksum(self):
        """Capsule computes checksum on creation."""
        capsule = GoalCapsule(
            root_goal="Build a web application",
            success_criteria=["Has login", "Has dashboard"],
            constraints=["Must use Python"],
        )

        assert capsule.checksum.startswith("sha256:")
        assert len(capsule.checksum) > 20

    def test_capsule_checksum_deterministic(self):
        """Same content produces same checksum."""
        capsule1 = GoalCapsule(
            root_goal="Test goal",
            success_criteria=["Criterion 1"],
            constraints=["Constraint 1"],
        )
        capsule2 = GoalCapsule(
            root_goal="Test goal",
            success_criteria=["Criterion 1"],
            constraints=["Constraint 1"],
        )

        assert capsule1.checksum == capsule2.checksum


class TestContextBuilder:
    """Tests for context building with VoI gating."""

    @pytest.fixture
    def mock_nodes(self):
        """Create mock node hierarchy."""
        root = WorkNode(
            id="root-001",
            depth=0,
            mode=NodeMode.EPISTEMIC,
            deliverable_type=DeliverableType.KNOWLEDGE,
            goal=Goal(
                statement="Build a REST API for user management",
                acceptance_criteria=[
                    Criterion(
                        description="API handles user CRUD",
                        type=CriterionType.KNOWLEDGE,
                        must_pass=True,
                    )
                ],
            ),
            status=NodeStatus.RUNNING,
        )

        child = WorkNode(
            id="child-001",
            depth=1,
            mode=NodeMode.EPISTEMIC,
            deliverable_type=DeliverableType.KNOWLEDGE,
            parent="root-001",
            goal=Goal(
                statement="Research authentication options",
                acceptance_criteria=[
                    Criterion(
                        description="Compare OAuth vs JWT",
                        type=CriterionType.KNOWLEDGE,
                    )
                ],
            ),
            status=NodeStatus.READY,
        )

        return {"root": root, "child": child}

    def test_builds_goal_capsule(self, mock_nodes):
        """Builder creates goal capsule from root."""
        nodes = {n.id: n for n in mock_nodes.values()}

        def load_node(node_id):
            return nodes[node_id]

        def get_ancestors(node_id):
            node = nodes[node_id]
            if node.parent:
                return [nodes[node.parent]]
            return []

        def get_siblings(node_id):
            return []

        builder = ContextBuilder(
            load_node_fn=load_node,
            get_ancestors_fn=get_ancestors,
            get_siblings_fn=get_siblings,
        )

        context = builder.build_context(
            mock_nodes["child"],
            root_node=mock_nodes["root"],
        )

        assert context.goal_capsule is not None
        assert "REST API" in context.goal_capsule.root_goal

    def test_voi_scores_populated(self, mock_nodes):
        """VoI scores are calculated and stored."""
        nodes = {n.id: n for n in mock_nodes.values()}

        builder = ContextBuilder(
            load_node_fn=lambda nid: nodes[nid],
            get_ancestors_fn=lambda nid: [nodes["root-001"]] if nid == "child-001" else [],
            get_siblings_fn=lambda nid: [],
        )

        context = builder.build_context(mock_nodes["child"])

        assert "base" in context.voi_scores
        assert "ancestors" in context.voi_scores
        assert "siblings" in context.voi_scores

    def test_budget_tracked(self, mock_nodes):
        """Token budget is tracked during building."""
        nodes = {n.id: n for n in mock_nodes.values()}

        builder = ContextBuilder(
            load_node_fn=lambda nid: nodes[nid],
            get_ancestors_fn=lambda nid: [nodes["root-001"]] if nid == "child-001" else [],
            get_siblings_fn=lambda nid: [],
            total_budget=5000,
        )

        context = builder.build_context(mock_nodes["child"])

        # Some budget should have been used
        assert context.budget.tier1_used > 0 or context.budget.tier2_used > 0


class TestGoalChainEntry:
    """Tests for goal chain entries."""

    def test_entry_stores_data(self):
        """Entry stores all required fields."""
        entry = GoalChainEntry(
            goal="Research web frameworks",
            depth=2,
            mode="epistemic",
            confidence=0.7,
            constraints=["Must be Python-based"],
        )

        assert entry.goal == "Research web frameworks"
        assert entry.depth == 2
        assert entry.confidence == 0.7
