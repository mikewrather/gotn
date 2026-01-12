"""Tests for scheduler implementation."""

import tempfile
from pathlib import Path

import pytest

from gotn.node import NodeMode, NodeStatus, WorkNode
from gotn.scheduler import CycleDetected, Scheduler
from gotn.state import StateManager


# Disable alignment enforcement for existing tests
def make_scheduler(manager, **kwargs):
    """Create scheduler with alignment disabled for basic tests."""
    return Scheduler(manager, enforce_alignment=False, **kwargs)


class TestScheduler:
    """Tests for Scheduler class."""

    def test_priority_ordering(self):
        """Test that nodes are prioritized by mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = make_scheduler(manager)

            # Create nodes in reverse priority order
            epistemic = WorkNode.create_root("Research something important", mode=NodeMode.EPISTEMIC)
            epistemic.status = NodeStatus.READY
            manager.create_node(epistemic)

            decision = WorkNode.create_root("Decide on the approach", mode=NodeMode.DECISION)
            decision.status = NodeStatus.READY
            manager.create_node(decision)

            instrumental = WorkNode.create_root("Build the feature", mode=NodeMode.INSTRUMENTAL)
            instrumental.status = NodeStatus.READY
            manager.create_node(instrumental)

            # Decision should come first
            next_node = scheduler.get_next_node()
            assert next_node.mode == NodeMode.DECISION

    def test_concurrency_limit(self):
        """Test that max_concurrent is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = make_scheduler(manager, max_concurrent=2)

            # Create 3 ready nodes
            for i in range(3):
                node = WorkNode.create_root(f"Test node number {i}", mode=NodeMode.EPISTEMIC)
                node.status = NodeStatus.READY
                manager.create_node(node)
                scheduler.enqueue(node)

            # Get first two
            n1 = scheduler.get_next_node()
            scheduler.mark_running(n1)
            n2 = scheduler.get_next_node()
            scheduler.mark_running(n2)

            # Third should be blocked by concurrency
            n3 = scheduler.get_next_node()
            assert n3 is None

            # Complete one, third should be available
            scheduler.mark_complete(n1)
            n3 = scheduler.get_next_node()
            assert n3 is not None

    def test_spawn_child(self):
        """Test spawning child nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = make_scheduler(manager)

            # Create parent
            parent = WorkNode.create_root("Parent goal statement", mode=NodeMode.INSTRUMENTAL)
            parent.status = NodeStatus.RUNNING
            manager.create_node(parent)

            # Spawn child
            child = scheduler.spawn_child(
                parent,
                NodeMode.EPISTEMIC,
                "Research something new",
            )

            # Verify child
            assert child.parent == parent.id
            assert child.depth == 1
            assert child.mode == NodeMode.EPISTEMIC

            # Verify parent updated
            loaded_parent = manager.load_node(parent.id)
            assert child.id in loaded_parent.children

    def test_cycle_detection(self):
        """Test that cycles are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = make_scheduler(manager)

            from gotn.node import EdgeType, TypedEdge

            # Create A -> B -> C
            a = WorkNode.create_root("Node A goal statement", mode=NodeMode.EPISTEMIC)
            a.status = NodeStatus.READY
            manager.create_node(a)

            b = WorkNode.create_root("Node B goal statement", mode=NodeMode.EPISTEMIC)
            b.status = NodeStatus.READY
            b.edges.append(TypedEdge(target=a.id, type=EdgeType.DEPENDS_ON))
            manager.create_node(b)

            c = WorkNode.create_root("Node C goal statement", mode=NodeMode.EPISTEMIC)
            c.status = NodeStatus.READY
            c.edges.append(TypedEdge(target=b.id, type=EdgeType.DEPENDS_ON))
            manager.create_node(c)

            # Adding C -> A would create cycle
            with pytest.raises(CycleDetected) as exc_info:
                scheduler.add_edge(a, c.id, EdgeType.DEPENDS_ON)

            assert a.id in exc_info.value.cycle_path

    def test_get_stats(self):
        """Test scheduler statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)
            scheduler = make_scheduler(manager)

            # Create some nodes
            for i in range(3):
                node = WorkNode.create_root(f"Test node number {i}", mode=NodeMode.EPISTEMIC)
                node.status = NodeStatus.READY
                manager.create_node(node)

            stats = scheduler.get_stats()
            assert stats["total_nodes"] == 3
            assert stats["by_status"]["ready"] == 3
            assert stats["by_mode"]["epistemic"] == 3
