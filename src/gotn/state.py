"""State machine for WorkNode lifecycle management."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

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
    """Manages WorkNode persistence and state transitions."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.nodes: dict[str, WorkNode] = {}
        self.event_bus = NodeEventBus()
        self._ensure_store()

    def _ensure_store(self):
        """Ensure store directories exist."""
        (self.store_path / "nodes").mkdir(parents=True, exist_ok=True)
        (self.store_path / "evidence").mkdir(parents=True, exist_ok=True)
        (self.store_path / "cache").mkdir(parents=True, exist_ok=True)

    def load_node(self, node_id: str) -> WorkNode:
        """Load a node from the store."""
        if node_id in self.nodes:
            return self.nodes[node_id]

        node = WorkNode.load(self.store_path, node_id)
        self.nodes[node_id] = node
        return node

    def save_node(self, node: WorkNode) -> None:
        """Save a node to the store."""
        node.updated_at = datetime.now()
        node.save(self.store_path)
        self.nodes[node.id] = node

    def create_node(self, node: WorkNode) -> WorkNode:
        """Create and persist a new node."""
        self.save_node(node)
        return node

    def transition(self, node: WorkNode, event: str) -> WorkNode:
        """Apply a state transition to a node."""
        old_status = node.status
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

    def load_all_nodes(self) -> dict[str, WorkNode]:
        """Load all nodes from the store."""
        nodes_dir = self.store_path / "nodes"
        for path in nodes_dir.glob("*.yaml"):
            node_id = path.stem
            if node_id not in self.nodes:
                self.load_node(node_id)
        return self.nodes

    def get_ready_nodes(self) -> list[WorkNode]:
        """Get all nodes in READY state."""
        self.load_all_nodes()
        return [n for n in self.nodes.values() if n.status == NodeStatus.READY]

    def get_running_nodes(self) -> list[WorkNode]:
        """Get all nodes in RUNNING state."""
        self.load_all_nodes()
        return [n for n in self.nodes.values() if n.status == NodeStatus.RUNNING]

    def get_blocked_nodes(self) -> list[WorkNode]:
        """Get all nodes in BLOCKED state."""
        self.load_all_nodes()
        return [n for n in self.nodes.values() if n.status == NodeStatus.BLOCKED]

    def get_root_nodes(self) -> list[WorkNode]:
        """Get all root nodes (no parent)."""
        self.load_all_nodes()
        return [n for n in self.nodes.values() if n.parent is None]

    def get_children(self, node: WorkNode) -> list[WorkNode]:
        """Get all child nodes."""
        return [self.load_node(child_id) for child_id in node.children]

    def get_parent(self, node: WorkNode) -> Optional[WorkNode]:
        """Get parent node if exists."""
        if node.parent:
            return self.load_node(node.parent)
        return None

    def check_dependencies_met(self, node: WorkNode) -> bool:
        """Check if all dependencies are satisfied."""
        for dep_id in node.get_dependencies():
            try:
                dep = self.load_node(dep_id)
                if dep.status not in (NodeStatus.COMPLETE, NodeStatus.DEGRADED):
                    return False
            except FileNotFoundError:
                return False
        return True

    def check_all_children_terminal(self, node: WorkNode) -> bool:
        """Check if all children are in terminal state."""
        for child_id in node.children:
            try:
                child = self.load_node(child_id)
                if not child.status.is_terminal:
                    return False
            except FileNotFoundError:
                return False
        return True

    def cascade_cancel(self, node: WorkNode) -> list[WorkNode]:
        """Cancel a node and all its descendants."""
        cancelled = []

        if not node.status.is_terminal:
            self.transition(node, "cancel")
            cancelled.append(node)

        for child_id in node.children:
            try:
                child = self.load_node(child_id)
                cancelled.extend(self.cascade_cancel(child))
            except FileNotFoundError:
                pass

        return cancelled
