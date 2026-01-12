"""Tests for goal alignment mechanisms."""

import tempfile
from pathlib import Path

import pytest

from gotn.alignment import (
    AlignmentMonitor,
    GoalChain,
    build_goal_chain,
    compute_alignment_score,
    summarize_goal,
    validate_alignment,
)
from gotn.node import NodeMode, NodeStatus, WorkNode
from gotn.scheduler import Scheduler
from gotn.state import StateManager


class TestGoalSummarization:
    """Tests for goal summarization."""

    def test_short_goal_unchanged(self):
        """Short goals should not be truncated."""
        goal = "Build API"
        result = summarize_goal(goal)
        assert result == goal

    def test_long_goal_truncated(self):
        """Long goals should be truncated at word boundary."""
        goal = "Research and evaluate the best Python web frameworks for building high-performance REST APIs"
        result = summarize_goal(goal, max_chars=40)
        assert len(result) <= 43  # 40 + "..."
        assert result.endswith("...")


class TestAlignmentScore:
    """Tests for alignment score computation."""

    def test_identical_goals_high_score(self):
        """Identical goals should have perfect alignment."""
        goal = "Research Python frameworks"
        score = compute_alignment_score(goal, goal, goal)
        assert score >= 0.9

    def test_related_goals_moderate_score(self):
        """Related goals should have moderate alignment."""
        child = "Compare FastAPI performance benchmarks"
        parent = "Research Python web frameworks"
        root = "Build a REST API service"
        score = compute_alignment_score(child, parent, root)
        # Should have some overlap from shared keywords
        assert 0.2 <= score <= 0.8

    def test_unrelated_goals_low_score(self):
        """Unrelated goals should have low alignment."""
        child = "Optimize database query performance"
        parent = "Research TTS voice providers"
        root = "Build children's story narration app"
        score = compute_alignment_score(child, parent, root)
        assert score < 0.5


class TestGoalChain:
    """Tests for goal chain building."""

    def test_build_chain_single_node(self):
        """Root node should have minimal chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            root = WorkNode.create_root(
                "Build a REST API for user management",
                mode=NodeMode.INSTRUMENTAL,
            )
            manager.create_node(root)

            chain = build_goal_chain(root, manager.load_node)

            assert chain.root.node_id == root.id
            assert chain.current.node_id == root.id
            assert chain.total_depth == 0
            assert len(chain.ancestors) == 0

    def test_build_chain_with_ancestry(self):
        """Chain should include compressed ancestry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = Scheduler(manager, enforce_alignment=False)

            # Create root
            root = WorkNode.create_root(
                "Build a TTS pipeline for children's stories",
                mode=NodeMode.INSTRUMENTAL,
            )
            root.status = NodeStatus.RUNNING
            manager.create_node(root)

            # Spawn child
            child = scheduler.spawn_child(
                root,
                NodeMode.EPISTEMIC,
                "Research TTS providers suitable for children",
            )

            chain = build_goal_chain(child, manager.load_node)

            assert chain.root.node_id == root.id
            assert chain.current.node_id == child.id
            assert chain.total_depth == 1
            assert "TTS" in chain.root.goal_summary

    def test_chain_context_rendering(self):
        """Chain should render to context string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = Scheduler(manager, enforce_alignment=False)

            root = WorkNode.create_root(
                "Build a REST API for user management",
                mode=NodeMode.INSTRUMENTAL,
            )
            root.status = NodeStatus.RUNNING
            manager.create_node(root)

            child = scheduler.spawn_child(
                root,
                NodeMode.EPISTEMIC,
                "Research authentication best practices",
            )

            chain = build_goal_chain(child, manager.load_node)
            context = chain.to_context()

            assert "Goal Alignment Context" in context
            assert "Root Objective" in context
            assert "Current Goal" in context


class TestAlignmentValidation:
    """Tests for alignment validation."""

    def test_aligned_child_passes(self):
        """Aligned child goals should pass validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            root = WorkNode.create_root(
                "Build a REST API for user authentication",
                mode=NodeMode.INSTRUMENTAL,
            )
            manager.create_node(root)

            result = validate_alignment(
                "Research JWT token best practices",
                root,
                root,
                threshold=0.2,
            )

            # Should pass with reasonable alignment
            assert result.score > 0

    def test_misaligned_child_fails(self):
        """Misaligned child goals should fail validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            root = WorkNode.create_root(
                "Build a REST API for user authentication",
                mode=NodeMode.INSTRUMENTAL,
            )
            manager.create_node(root)

            result = validate_alignment(
                "Optimize PostgreSQL vacuum settings",  # Unrelated
                root,
                root,
                threshold=0.5,
            )

            # Should fail or have low score
            assert result.score < 0.5


class TestSchedulerAlignment:
    """Tests for scheduler alignment enforcement."""

    def test_spawn_aligned_child_succeeds(self):
        """Spawning aligned child should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = Scheduler(
                manager,
                enforce_alignment=True,
                alignment_threshold=0.1,  # Low threshold for test
            )

            root = WorkNode.create_root(
                "Research Python web frameworks for REST APIs",
                mode=NodeMode.EPISTEMIC,
            )
            root.status = NodeStatus.RUNNING
            manager.create_node(root)

            # Should succeed - related goal
            child = scheduler.spawn_child(
                root,
                NodeMode.EPISTEMIC,
                "Compare FastAPI and Flask for REST API development",
            )
            assert child is not None
            assert child.parent == root.id

    def test_constraint_propagation(self):
        """Must-pass constraints should propagate to children."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = Scheduler(manager, enforce_alignment=False)

            root = WorkNode.create_root(
                "Build secure authentication system",
                mode=NodeMode.INSTRUMENTAL,
                criteria=[
                    {
                        "description": "Must use industry-standard encryption",
                        "type": "artifact",
                        "must_pass": True,
                    }
                ],
            )
            root.status = NodeStatus.RUNNING
            manager.create_node(root)

            child = scheduler.spawn_child(
                root,
                NodeMode.EPISTEMIC,
                "Research encryption libraries",
            )

            # Child should have inherited constraint
            inherited = [c for c in child.goal.acceptance_criteria if "[Inherited]" in c.description]
            assert len(inherited) > 0
            assert "encryption" in inherited[0].description.lower()
