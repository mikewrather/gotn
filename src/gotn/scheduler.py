"""DAG scheduler for WorkNode execution."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from heapq import heappop, heappush
from typing import Callable, Optional

from gotn.alignment import AlignmentMonitor, propagate_constraints
from gotn.node import EdgeType, NodeMode, NodeStatus, TypedEdge, WorkNode
from gotn.state import StateManager
from gotn.workflow import WorkflowContext, WorkflowStateMachine, TransitionResult


# Default limits for tree size
MAX_DEPTH = 10  # Maximum tree depth
MAX_NODES = 100  # Maximum total nodes in tree


@dataclass
class CycleDetected(Exception):
    """Raised when adding an edge would create a cycle."""

    source_id: str
    target_id: str
    cycle_path: list[str]

    def __init__(self, source_id: str, target_id: str, cycle_path: list[str]):
        self.source_id = source_id
        self.target_id = target_id
        self.cycle_path = cycle_path
        super().__init__(
            f"Adding edge {source_id} -> {target_id} would create cycle: "
            f"{' -> '.join(cycle_path)}"
        )


class DepthLimitExceeded(Exception):
    """Raised when spawning would exceed maximum tree depth."""

    def __init__(self, current_depth: int, max_depth: int):
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(
            f"Cannot spawn child at depth {current_depth + 1}: "
            f"exceeds maximum depth of {max_depth}"
        )


class NodeLimitExceeded(Exception):
    """Raised when spawning would exceed maximum node count."""

    def __init__(self, current_count: int, max_nodes: int):
        self.current_count = current_count
        self.max_nodes = max_nodes
        super().__init__(
            f"Cannot spawn child: tree has {current_count} nodes, "
            f"maximum is {max_nodes}"
        )


@dataclass(order=True)
class PriorityItem:
    """Priority queue item for node scheduling."""

    priority: int
    timestamp: datetime = field(compare=False)
    node_id: str = field(compare=False)


class Scheduler:
    """Manages node execution order and concurrency."""

    # Priority by mode (lower = higher priority)
    MODE_PRIORITY = {
        NodeMode.DECISION: 0,  # Decisions unblock the most work
        NodeMode.PLANNING: 1,  # Planning enables parallel execution
        NodeMode.INSTRUMENTAL: 2,  # Building produces artifacts
        NodeMode.VALIDATION: 3,  # Verification after build
        NodeMode.EPISTEMIC: 4,  # Research can wait
    }

    def __init__(
        self,
        state: StateManager,
        max_concurrent: int = 10,
        on_node_complete: Optional[Callable[[WorkNode], None]] = None,
        alignment_threshold: float = 0.3,
        enforce_alignment: bool = True,
        enforce_workflow: bool = True,
        max_depth: int = MAX_DEPTH,
        max_nodes: int = MAX_NODES,
    ):
        self.state = state
        self.max_concurrent = max_concurrent
        self.running: set[str] = set()
        self._priority_queue: list[PriorityItem] = []
        self._on_node_complete = on_node_complete
        self.enforce_alignment = enforce_alignment
        self.enforce_workflow = enforce_workflow
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.alignment_monitor = AlignmentMonitor(
            load_node_fn=state.load_node,
            alignment_threshold=alignment_threshold,
        )
        self.workflow_machine = WorkflowStateMachine()

    def _compute_priority(self, node: WorkNode) -> int:
        """Compute scheduling priority for a node.

        Lower values = higher priority.
        Priority is based on: mode, depth (deeper = more urgent), age.
        """
        mode_priority = self.MODE_PRIORITY.get(node.mode, 10)
        depth_bonus = -node.depth  # Deeper nodes get slight priority boost
        return mode_priority * 100 + depth_bonus

    def enqueue(self, node: WorkNode) -> None:
        """Add a ready node to the priority queue."""
        if node.status != NodeStatus.READY:
            return

        priority = self._compute_priority(node)
        item = PriorityItem(
            priority=priority,
            timestamp=node.created_at,
            node_id=node.id,
        )
        heappush(self._priority_queue, item)

    def get_next_node(self) -> Optional[WorkNode]:
        """Get the highest priority ready node that can run."""
        if len(self.running) >= self.max_concurrent:
            return None

        while self._priority_queue:
            item = heappop(self._priority_queue)

            try:
                node = self.state.load_node(item.node_id)
            except FileNotFoundError:
                continue

            # Skip if no longer ready or already running
            if node.status != NodeStatus.READY or node.id in self.running:
                continue

            return node

        # Queue exhausted, scan for ready nodes
        ready_nodes = self.state.get_ready_nodes()
        if not ready_nodes:
            return None

        # Sort by priority and return highest
        ready_nodes.sort(key=lambda n: (self._compute_priority(n), n.created_at))
        for node in ready_nodes:
            if node.id not in self.running:
                return node

        return None

    def mark_running(self, node: WorkNode) -> None:
        """Mark a node as running."""
        self.running.add(node.id)

    def mark_complete(self, node: WorkNode) -> list[WorkNode]:
        """Mark a node as complete and unblock waiting parents.

        Returns list of nodes that became unblocked.
        """
        self.running.discard(node.id)

        if self._on_node_complete:
            self._on_node_complete(node)

        # Check if any blocked parents can now resume
        unblocked = []
        all_nodes = self.state.get_all_nodes()

        for potential_parent in all_nodes:
            if potential_parent.status != NodeStatus.BLOCKED:
                continue
            if node.id not in potential_parent.children:
                continue

            # Check if all children are now terminal
            if self.state.check_all_children_terminal(potential_parent):
                self.state.transition(potential_parent, "children_done")
                unblocked.append(potential_parent)
                self.enqueue(potential_parent)

        return unblocked

    def spawn_child(
        self,
        parent: WorkNode,
        mode: NodeMode,
        goal_statement: str,
        criteria: Optional[list[dict]] = None,
        budget_fraction: float = 0.5,
        skip_alignment_check: bool = False,
    ) -> WorkNode:
        """Spawn a child node under a parent.

        Args:
            parent: The parent node
            mode: Mode for the child
            goal_statement: Goal for the child
            criteria: Optional acceptance criteria
            budget_fraction: Fraction of parent's remaining budget
            skip_alignment_check: Skip alignment validation (for tests)

        Returns:
            The created child node

        Raises:
            CycleDetected: If this would create a cycle
            ValueError: If child goal doesn't align with tree objectives
            DepthLimitExceeded: If child would exceed max depth
            NodeLimitExceeded: If tree would exceed max nodes
        """
        from gotn.node import (
            Budget,
            Criterion,
            CriterionType,
            DeliverableType,
            Goal,
            generate_id,
        )

        # Check depth limit before spawning
        child_depth = parent.depth + 1
        if child_depth > self.max_depth:
            raise DepthLimitExceeded(parent.depth, self.max_depth)

        # Check node count limit before spawning
        total_nodes = len(self.state.get_all_nodes())
        if total_nodes >= self.max_nodes:
            raise NodeLimitExceeded(total_nodes, self.max_nodes)

        # Check alignment before spawning
        if self.enforce_alignment and not skip_alignment_check:
            result = self.alignment_monitor.check_spawn_alignment(
                parent, goal_statement, mode.value
            )
            if not result.aligned:
                raise ValueError(
                    f"Child goal misaligned (score: {result.score:.0%}). "
                    f"Issues: {'; '.join(result.issues)}. "
                    f"Suggestions: {'; '.join(result.suggestions)}"
                )

        # Check workflow preconditions
        if self.enforce_workflow:
            workflow_result = self._check_workflow_preconditions(parent, mode)
            if not workflow_result.allowed:
                if workflow_result.suggested_mode:
                    raise ValueError(
                        f"Workflow precondition not met: {workflow_result.reason}. "
                        f"Suggested mode: {workflow_result.suggested_mode.value}"
                    )
                raise ValueError(
                    f"Workflow precondition not met: {workflow_result.reason}"
                )

        # Create default criteria if not provided
        if criteria is None:
            criteria = [
                {
                    "description": "Sub-goal achieved",
                    "type": CriterionType.KNOWLEDGE,
                }
            ]

        # Map mode to deliverable type
        deliverable_map = {
            NodeMode.PLANNING: DeliverableType.PLAN,
            NodeMode.EPISTEMIC: DeliverableType.KNOWLEDGE,
            NodeMode.INSTRUMENTAL: DeliverableType.ARTIFACT,
            NodeMode.DECISION: DeliverableType.COMMITMENT,
            NodeMode.VALIDATION: DeliverableType.VERIFICATION,
        }

        # Calculate child budget
        child_budget = Budget()
        if parent.budget.tokens:
            remaining = parent.budget.tokens - parent.resource_usage.tokens
            child_budget.tokens = int(remaining * budget_fraction)
        if parent.budget.time_ms:
            remaining = parent.budget.time_ms - parent.resource_usage.time_ms
            child_budget.time_ms = int(remaining * budget_fraction)
        if parent.budget.steps:
            remaining = parent.budget.steps - parent.resource_usage.steps
            child_budget.steps = int(remaining * budget_fraction)
        if parent.budget.cost_dollars:
            remaining = parent.budget.cost_dollars - parent.resource_usage.cost_dollars
            child_budget.cost_dollars = remaining * budget_fraction

        # Create child node
        child = WorkNode(
            id=generate_id("node"),
            depth=parent.depth + 1,
            mode=mode,
            goal=Goal(
                statement=goal_statement,
                acceptance_criteria=[Criterion(**c) for c in criteria],
            ),
            parent=parent.id,
            production_anchor=parent.production_anchor or parent.id,
            deliverable_type=deliverable_map[mode],
            budget=child_budget,
            status=NodeStatus.PENDING,
            edges=[
                TypedEdge(target=parent.id, type=EdgeType.SPAWNED_BY),
            ],
        )

        # Propagate must-pass constraints from parent
        inherited = propagate_constraints(parent, child)
        child.goal.acceptance_criteria.extend(inherited)

        # Check for cycles before adding
        self._check_cycle(child.id, parent.id)

        # Add child to parent's children list
        parent.children.append(child.id)

        # Persist both nodes
        self.state.create_node(child)
        self.state.save_node(parent)

        # Check if child is ready (dependencies met)
        if self.state.check_dependencies_met(child):
            self.state.transition(child, "dependencies_met")
            self.enqueue(child)

        return child

    def materialize_plan(self, parent: WorkNode) -> list[WorkNode]:
        """Materialize a PlanOutput's sub-goals into executable child nodes.

        Creates child nodes for each sub-goal and wires up dependency edges
        based on the depends_on indices in the plan.

        Args:
            parent: The planning node with a PlanOutput

        Returns:
            List of created child nodes
        """
        from gotn.node import (
            Budget,
            Criterion,
            CriterionType,
            DeliverableType,
            Goal,
            PlanOutput,
            generate_id,
        )

        # Find the PlanOutput
        plan_output = None
        for output in parent.outputs:
            if isinstance(output, PlanOutput):
                plan_output = output
                break

        if not plan_output or not plan_output.sub_goals:
            return []

        # Map mode to deliverable type
        deliverable_map = {
            "planning": DeliverableType.PLAN,
            "epistemic": DeliverableType.KNOWLEDGE,
            "instrumental": DeliverableType.ARTIFACT,
            "decision": DeliverableType.COMMITMENT,
            "validation": DeliverableType.VERIFICATION,
        }

        # Map mode string to NodeMode
        mode_map = {
            "planning": NodeMode.PLANNING,
            "epistemic": NodeMode.EPISTEMIC,
            "instrumental": NodeMode.INSTRUMENTAL,
            "decision": NodeMode.DECISION,
            "validation": NodeMode.VALIDATION,
        }

        # Create nodes for each sub-goal, tracking index -> node_id mapping
        index_to_node: dict[int, WorkNode] = {}
        children: list[WorkNode] = []

        for i, sg in enumerate(plan_output.sub_goals):
            mode = mode_map.get(sg.mode, NodeMode.EPISTEMIC)
            deliverable = deliverable_map.get(sg.mode, DeliverableType.KNOWLEDGE)

            # Convert acceptance_criteria to proper format
            criteria = []
            for ac in sg.acceptance_criteria:
                if isinstance(ac, str):
                    criteria.append({
                        "description": ac,
                        "type": CriterionType.KNOWLEDGE,
                    })
                elif isinstance(ac, dict):
                    if "type" not in ac:
                        ac["type"] = CriterionType.KNOWLEDGE
                    criteria.append(ac)

            if not criteria:
                criteria = [{
                    "description": "Sub-goal achieved",
                    "type": CriterionType.KNOWLEDGE,
                }]

            # Create child node
            child = WorkNode(
                id=generate_id("node"),
                depth=parent.depth + 1,
                mode=mode,
                goal=Goal(
                    statement=sg.goal_statement,
                    acceptance_criteria=[Criterion(**c) for c in criteria],
                ),
                parent=parent.id,
                production_anchor=parent.production_anchor or parent.id,
                deliverable_type=deliverable,
                budget=Budget(),
                status=NodeStatus.PENDING,
                edges=[
                    TypedEdge(target=parent.id, type=EdgeType.SPAWNED_BY),
                ],
            )

            index_to_node[i] = child
            children.append(child)
            parent.children.append(child.id)

        # Now add DEPENDS_ON edges based on depends_on indices
        for i, sg in enumerate(plan_output.sub_goals):
            child = index_to_node[i]
            for dep_idx in sg.depends_on:
                if dep_idx in index_to_node:
                    dep_node = index_to_node[dep_idx]
                    child.edges.append(
                        TypedEdge(target=dep_node.id, type=EdgeType.DEPENDS_ON)
                    )

        # Persist all nodes
        for child in children:
            self.state.create_node(child)

            # Check if child is ready (no dependencies or all deps met)
            if self.state.check_dependencies_met(child):
                self.state.transition(child, "dependencies_met")
                self.enqueue(child)

        # Save parent with updated children list
        self.state.save_node(parent)

        return children

    def _check_cycle(self, source_id: str, target_id: str) -> None:
        """Check if adding an edge would create a cycle.

        Uses DFS to detect if target can reach source through blocking edges.
        """
        visited = set()
        path = []

        def dfs(node_id: str) -> bool:
            if node_id == source_id:
                path.append(node_id)
                return True

            if node_id in visited:
                return False

            visited.add(node_id)
            path.append(node_id)

            try:
                node = self.state.load_node(node_id)
            except FileNotFoundError:
                path.pop()
                return False

            # Check blocking edges (depends_on, blocks)
            for edge in node.edges:
                if edge.type.is_blocking:
                    if dfs(edge.target):
                        return True

            # Also check parent relationship
            if node.parent:
                if dfs(node.parent):
                    return True

            path.pop()
            return False

        if dfs(target_id):
            path.append(source_id)
            raise CycleDetected(source_id, target_id, path)

    def add_edge(self, source: WorkNode, target_id: str, edge_type: EdgeType) -> None:
        """Add an edge between nodes with cycle detection.

        Args:
            source: Source node
            target_id: Target node ID
            edge_type: Type of edge

        Raises:
            CycleDetected: If this would create a cycle
        """
        # Only check cycles for blocking edges
        if edge_type.is_blocking:
            self._check_cycle(source.id, target_id)

        source.edges.append(TypedEdge(target=target_id, type=edge_type))
        self.state.save_node(source)

    def get_runnable_count(self) -> int:
        """Get number of nodes that could run right now."""
        return len(self.state.get_ready_nodes())

    def get_running_count(self) -> int:
        """Get number of currently running nodes."""
        return len(self.running)

    def get_available_slots(self) -> int:
        """Get number of available concurrency slots."""
        return max(0, self.max_concurrent - len(self.running))

    def refresh_ready_queue(self) -> int:
        """Scan for pending nodes that can become ready.

        Returns the number of nodes transitioned to ready.
        """
        count = 0
        all_nodes = self.state.get_all_nodes()

        for node in all_nodes:
            if node.status != NodeStatus.PENDING:
                continue

            if self.state.check_dependencies_met(node):
                self.state.transition(node, "dependencies_met")
                self.enqueue(node)
                count += 1

        return count

    def get_stats(self) -> dict:
        """Get scheduler statistics."""
        all_nodes = self.state.get_all_nodes()

        status_counts = defaultdict(int)
        mode_counts = defaultdict(int)

        for node in all_nodes:
            status_counts[node.status.value] += 1
            mode_counts[node.mode.value] += 1

        return {
            "total_nodes": len(all_nodes),
            "running": len(self.running),
            "max_concurrent": self.max_concurrent,
            "queue_size": len(self._priority_queue),
            "by_status": dict(status_counts),
            "by_mode": dict(mode_counts),
        }

    def _check_workflow_preconditions(
        self, parent: WorkNode, target_mode: NodeMode
    ) -> TransitionResult:
        """Check if workflow preconditions are met for spawning a child.

        Builds a WorkflowContext from the parent node and checks if the
        target mode's preconditions are satisfied.
        """
        from gotn.node import (
            ArtifactOutput,
            CommitmentOutput,
            KnowledgeOutput,
            PlanOutput,
        )

        # Gather claims from parent and siblings
        sibling_claims = []
        for output in parent.outputs:
            if isinstance(output, KnowledgeOutput):
                sibling_claims.extend(output.claims)
        sibling_claims.extend(parent.claims)

        # Check for commitment in parent's outputs
        has_commitment = any(
            isinstance(o, CommitmentOutput) for o in parent.outputs
        )

        # Check for plan in parent's outputs
        has_plan = any(isinstance(o, PlanOutput) for o in parent.outputs)

        # Check for artifact in parent's outputs
        has_artifact = any(isinstance(o, ArtifactOutput) for o in parent.outputs)

        # Estimate goal complexity
        complexity, _ = self.workflow_machine.estimate_complexity(
            parent.goal.statement
        )

        # Build context
        context = WorkflowContext(
            node=parent,
            parent_node=None,  # We don't have grandparent context
            sibling_claims=sibling_claims,
            has_commitment=has_commitment,
            has_plan=has_plan,
            has_artifact=has_artifact,
            goal_complexity=complexity,
        )

        return self.workflow_machine.check_preconditions(target_mode, context)

    def suggest_child_mode(self, parent: WorkNode) -> NodeMode:
        """Suggest the appropriate mode for a child node based on workflow state.

        Args:
            parent: The parent node

        Returns:
            Suggested NodeMode for the child
        """
        from gotn.node import (
            ArtifactOutput,
            CommitmentOutput,
            KnowledgeOutput,
            PlanOutput,
        )

        # Check what outputs we have
        has_claims = bool(parent.claims) or any(
            isinstance(o, KnowledgeOutput) and o.claims for o in parent.outputs
        )
        has_commitment = any(
            isinstance(o, CommitmentOutput) for o in parent.outputs
        )
        has_plan = any(isinstance(o, PlanOutput) for o in parent.outputs)
        has_artifact = any(isinstance(o, ArtifactOutput) for o in parent.outputs)

        # Determine suggested mode based on workflow state
        if has_artifact:
            return NodeMode.VALIDATION
        if has_plan:
            return NodeMode.INSTRUMENTAL
        if has_commitment:
            # Check complexity to decide between planning and instrumental
            if self.workflow_machine.should_use_planning(
                WorkflowContext(
                    node=parent,
                    has_commitment=True,
                    goal_complexity=self.workflow_machine.estimate_complexity(
                        parent.goal.statement
                    )[0],
                )
            ):
                return NodeMode.PLANNING
            return NodeMode.INSTRUMENTAL
        if has_claims:
            return NodeMode.DECISION
        return NodeMode.EPISTEMIC
