"""State machine for WorkNode lifecycle management."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from gotn.graph import GraphStore
from gotn.node import NodeStatus, WorkNode


@dataclass
class Transition:
    """A state machine transition."""

    source: NodeStatus
    event: str
    target: NodeStatus
    guard: Optional[Callable[[WorkNode], bool]] = None


class InvalidTransition(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, node_id: str, current: NodeStatus, event: str):
        self.node_id = node_id
        self.current = current
        self.event = event
        super().__init__(
            f"Invalid transition: {node_id} in state {current.value} cannot handle event '{event}'"
        )


class StateMachine:
    """State machine for WorkNode status transitions."""

    def __init__(self):
        self.transitions: dict[tuple[NodeStatus, str], Transition] = {}
        self._build_transitions()

    def _build_transitions(self):
        """Define all valid state transitions."""
        transitions = [
            # From PENDING
            Transition(NodeStatus.PENDING, "dependencies_met", NodeStatus.READY),
            Transition(NodeStatus.PENDING, "cancel", NodeStatus.CANCELLED),
            # From READY
            Transition(NodeStatus.READY, "start", NodeStatus.RUNNING),
            Transition(NodeStatus.READY, "cancel", NodeStatus.CANCELLED),
            # From RUNNING
            Transition(NodeStatus.RUNNING, "spawn_child", NodeStatus.BLOCKED),
            Transition(NodeStatus.RUNNING, "complete", NodeStatus.COMPLETE),
            Transition(NodeStatus.RUNNING, "degrade", NodeStatus.DEGRADED),
            Transition(NodeStatus.RUNNING, "escalate", NodeStatus.ESCALATED),
            Transition(NodeStatus.RUNNING, "error", NodeStatus.FAILED),
            Transition(NodeStatus.RUNNING, "cancel", NodeStatus.CANCELLED),
            # From BLOCKED
            Transition(NodeStatus.BLOCKED, "children_done", NodeStatus.RUNNING),
            Transition(NodeStatus.BLOCKED, "escalate", NodeStatus.ESCALATED),
            Transition(NodeStatus.BLOCKED, "error", NodeStatus.FAILED),
            Transition(NodeStatus.BLOCKED, "cancel", NodeStatus.CANCELLED),
            # From ESCALATED (can be resumed)
            Transition(NodeStatus.ESCALATED, "resume", NodeStatus.RUNNING),
            Transition(NodeStatus.ESCALATED, "cancel", NodeStatus.CANCELLED),
        ]

        for t in transitions:
            self.transitions[(t.source, t.event)] = t

    def can_transition(self, node: WorkNode, event: str) -> bool:
        """Check if a transition is valid for the given node and event."""
        key = (node.status, event)
        if key not in self.transitions:
            return False

        transition = self.transitions[key]
        if transition.guard and not transition.guard(node):
            return False

        return True

    def transition(self, node: WorkNode, event: str) -> NodeStatus:
        """Apply a transition and return the new status."""
        key = (node.status, event)
        if key not in self.transitions:
            raise InvalidTransition(node.id, node.status, event)

        transition = self.transitions[key]
        if transition.guard and not transition.guard(node):
            raise InvalidTransition(node.id, node.status, event)

        return transition.target

    def get_valid_events(self, status: NodeStatus) -> list[str]:
        """Get all valid events for a given status."""
        return [event for (s, event) in self.transitions.keys() if s == status]


# Global state machine instance
STATE_MACHINE = StateMachine()


@dataclass
class NodeEvent:
    """Event emitted when a node changes state."""

    type: str
    source_id: str
    status: NodeStatus
    outputs: Optional[list] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class NodeEventBus:
    """Pub/sub event bus for node state changes."""

    def __init__(self):
        self.subscribers: dict[str, list[Callable[[NodeEvent], None]]] = defaultdict(list)
        self.global_subscribers: list[Callable[[NodeEvent], None]] = []

    def subscribe(self, node_id: str, callback: Callable[[NodeEvent], None]):
        """Subscribe to events from a specific node."""
        self.subscribers[node_id].append(callback)

    def subscribe_all(self, callback: Callable[[NodeEvent], None]):
        """Subscribe to all node events."""
        self.global_subscribers.append(callback)

    def unsubscribe(self, node_id: str, callback: Callable[[NodeEvent], None]):
        """Unsubscribe from a specific node."""
        if callback in self.subscribers[node_id]:
            self.subscribers[node_id].remove(callback)

    def publish(self, event: NodeEvent):
        """Publish an event to all subscribers."""
        for callback in self.subscribers[event.source_id]:
            callback(event)
        for callback in self.global_subscribers:
            callback(event)


class StateManager:
    """Manages WorkNode persistence and state transitions using graph storage."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.graph = GraphStore(store_path)
        self.event_bus = NodeEventBus()

    def load_node(self, node_id: str) -> WorkNode:
        """Load a node from the store."""
        node = self.graph.load_node(node_id)
        if node is None:
            raise FileNotFoundError(f"Node not found: {node_id}")
        return node

    def save_node(self, node: WorkNode) -> None:
        """Save a node to the store."""
        self.graph.save_node(node)

    def create_node(self, node: WorkNode) -> WorkNode:
        """Create and persist a new node."""
        return self.graph.create_node(node)

    def transition(self, node: WorkNode, event: str) -> WorkNode:
        """Apply a state transition to a node."""
        new_status = STATE_MACHINE.transition(node, event)

        node.status = new_status
        node.updated_at = datetime.now()
        self.save_node(node)

        # Publish event
        self.event_bus.publish(
            NodeEvent(
                type=event,
                source_id=node.id,
                status=new_status,
                outputs=node.outputs if new_status.is_terminal else None,
            )
        )

        return node

    def get_all_nodes(self) -> list[WorkNode]:
        """Get all nodes from the store."""
        return self.graph.get_all_nodes()

    def load_all_nodes(self) -> dict[str, WorkNode]:
        """Load all nodes as a dict (for backwards compatibility)."""
        nodes = self.get_all_nodes()
        return {n.id: n for n in nodes}

    def get_ready_nodes(self) -> list[WorkNode]:
        """Get all nodes in READY state."""
        return self.graph.get_ready_nodes()

    def get_running_nodes(self) -> list[WorkNode]:
        """Get all nodes in RUNNING state."""
        return self.graph.get_running_nodes()

    def get_blocked_nodes(self) -> list[WorkNode]:
        """Get all nodes in BLOCKED state."""
        return self.graph.get_blocked_nodes()

    def get_root_nodes(self) -> list[WorkNode]:
        """Get all root nodes (no parent)."""
        return self.graph.get_root_nodes()

    def get_children(self, node: WorkNode) -> list[WorkNode]:
        """Get all child nodes."""
        return self.graph.get_children(node.id)

    def get_parent(self, node: WorkNode) -> Optional[WorkNode]:
        """Get parent node if exists."""
        return self.graph.get_parent(node.id)

    def get_ancestors(self, node: WorkNode) -> list[WorkNode]:
        """Get all ancestors from root to immediate parent."""
        return self.graph.get_ancestors(node.id)

    def get_descendants(self, node: WorkNode) -> list[WorkNode]:
        """Get all descendants of a node."""
        return self.graph.get_descendants(node.id)

    def check_dependencies_met(self, node: WorkNode) -> bool:
        """Check if all dependencies are satisfied."""
        return self.graph.check_dependencies_met(node.id)

    def check_all_children_terminal(self, node: WorkNode) -> bool:
        """Check if all children are in terminal state."""
        return self.graph.check_all_children_terminal(node.id)

    def get_context_fingerprint(self, node: WorkNode) -> str:
        """Get context fingerprint for cache keying."""
        return self.graph.get_context_fingerprint(node.id)

    def cascade_cancel(self, node: WorkNode) -> list[WorkNode]:
        """Cancel a node and all its descendants."""
        cancelled = []

        if not node.status.is_terminal:
            self.transition(node, "cancel")
            cancelled.append(node)

        for child in self.get_children(node):
            cancelled.extend(self.cascade_cancel(child))

        return cancelled

    def close(self):
        """Close the underlying graph store."""
        self.graph.close()
