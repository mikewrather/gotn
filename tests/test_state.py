"""Tests for state machine implementation."""

import tempfile
from pathlib import Path

import pytest

from gotn.node import NodeMode, NodeStatus, WorkNode
from gotn.state import InvalidTransition, StateMachine, StateManager


class TestStateMachine:
    """Tests for StateMachine class."""

    def test_valid_transitions(self):
        """Test valid state transitions."""
        sm = StateMachine()

        # Create a minimal node (goal must be >= 10 chars)
        node = WorkNode.create_root("Test goal statement statement", mode=NodeMode.EPISTEMIC)
        node.status = NodeStatus.PENDING

        # Test pending -> ready
        assert sm.can_transition(node, "dependencies_met")
        new_status = sm.transition(node, "dependencies_met")
        assert new_status == NodeStatus.READY

    def test_invalid_transition_raises(self):
        """Test that invalid transitions raise InvalidTransition."""
        sm = StateMachine()
        node = WorkNode.create_root("Test goal statement statement", mode=NodeMode.EPISTEMIC)
        node.status = NodeStatus.PENDING

        # Can't start from pending
        assert not sm.can_transition(node, "start")

        with pytest.raises(InvalidTransition) as exc_info:
            sm.transition(node, "start")

        assert exc_info.value.current == NodeStatus.PENDING
        assert exc_info.value.event == "start"

    def test_get_valid_events(self):
        """Test getting valid events for a status."""
        sm = StateMachine()

        # Running has many valid events
        running_events = sm.get_valid_events(NodeStatus.RUNNING)
        assert "spawn_child" in running_events
        assert "complete" in running_events
        assert "error" in running_events

        # Complete has no events (terminal)
        complete_events = sm.get_valid_events(NodeStatus.COMPLETE)
        assert complete_events == []


class TestStateManager:
    """Tests for StateManager class."""

    def test_create_and_load_node(self):
        """Test creating and loading a node."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            # Create node
            node = WorkNode.create_root("Test goal statement", mode=NodeMode.EPISTEMIC)
            manager.create_node(node)

            # Load it back
            loaded = manager.load_node(node.id)
            assert loaded.id == node.id
            assert loaded.goal.statement == "Test goal statement"

    def test_transition_persists(self):
        """Test that transitions persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            # Create and transition
            node = WorkNode.create_root("Test goal statement", mode=NodeMode.EPISTEMIC)
            node.status = NodeStatus.PENDING
            manager.create_node(node)
            manager.transition(node, "dependencies_met")

            # Reload from disk
            fresh_manager = StateManager(store_path)
            loaded = fresh_manager.load_node(node.id)
            assert loaded.status == NodeStatus.READY

    def test_check_dependencies_met(self):
        """Test dependency checking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            # Create dependency node
            dep = WorkNode.create_root("Dependency goal statement", mode=NodeMode.EPISTEMIC)
            dep.status = NodeStatus.COMPLETE
            manager.create_node(dep)

            # Create dependent node
            from gotn.node import EdgeType, TypedEdge

            node = WorkNode.create_root("Dependent goal statement", mode=NodeMode.EPISTEMIC)
            node.status = NodeStatus.PENDING
            node.edges.append(TypedEdge(target=dep.id, type=EdgeType.DEPENDS_ON))
            manager.create_node(node)

            # Dependencies should be met
            assert manager.check_dependencies_met(node)

            # Change dep to running
            dep.status = NodeStatus.RUNNING
            manager.save_node(dep)

            # Now dependencies not met
            assert not manager.check_dependencies_met(node)

    def test_get_ready_nodes(self):
        """Test getting all ready nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir)
            manager = StateManager(store_path)

            # Create nodes in various states
            ready1 = WorkNode.create_root("Ready node one goal", mode=NodeMode.EPISTEMIC)
            ready1.status = NodeStatus.READY
            manager.create_node(ready1)

            ready2 = WorkNode.create_root("Ready node two goal", mode=NodeMode.INSTRUMENTAL)
            ready2.status = NodeStatus.READY
            manager.create_node(ready2)

            pending = WorkNode.create_root("Pending node goal", mode=NodeMode.EPISTEMIC)
            pending.status = NodeStatus.PENDING
            manager.create_node(pending)

            ready_nodes = manager.get_ready_nodes()
            assert len(ready_nodes) == 2
            assert all(n.status == NodeStatus.READY for n in ready_nodes)
