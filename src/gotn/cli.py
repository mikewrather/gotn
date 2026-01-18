"""GOTN Command Line Interface."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from gotn.confidence import compute_node_confidence, should_proceed, suggest_next_action
from gotn.executor import ClaudeExecutor, ExecutionContext, ExecutionStrategy, apply_result_to_node
from datetime import datetime
from gotn.node import ErrorInfo, NodeMode, NodeStatus, WorkNode
from gotn.scheduler import Scheduler
from gotn.state import StateManager

app = typer.Typer(
    name="gotn",
    help="Goal-Oriented Task Network - Recursive workflow orchestration for LLM agents",
    no_args_is_help=True,
)
console = Console()

# Default store path
DEFAULT_STORE = Path.cwd() / "store"


def get_state_manager(
    store_path: Optional[Path] = None,
    project: str = "gotn",
    backend: str = "neo4j",
) -> StateManager:
    """Get or create state manager."""
    if backend == "neo4j":
        return StateManager(project=project, backend="neo4j")
    else:
        path = store_path or DEFAULT_STORE
        return StateManager(store_path=path, backend="kuzu")


@app.command()
def init(
    goal: str = typer.Argument(..., help="The goal statement for the root node"),
    mode: str = typer.Option(
        "epistemic",
        "--mode",
        "-m",
        help="Node mode: epistemic, instrumental, decision, validation",
    ),
    project: str = typer.Option(
        "gotn",
        "--project",
        "-p",
        help="Project name for Neo4j namespace",
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory (kuzu backend only)"
    ),
):
    """Initialize a new goal tree with a root node."""
    try:
        node_mode = NodeMode(mode)
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        console.print("Valid modes: epistemic, instrumental, decision, validation")
        raise typer.Exit(1)

    state = get_state_manager(store_path=store, project=project)
    root = WorkNode.create_root(goal, mode=node_mode)
    state.create_node(root)

    console.print(Panel(f"[green]Created root node[/green]"))
    console.print(f"  ID: [cyan]{root.id}[/cyan]")
    console.print(f"  Project: {project}")
    console.print(f"  Mode: {root.mode.value}")
    console.print(f"  Goal: {root.goal.statement}")
    console.print(f"  Status: {root.status.value}")
    console.print(f"\nStore: {state.store_path}")


@app.command()
def run(
    continuous: bool = typer.Option(
        False, "--continuous", "-c", help="Run until blocked or complete"
    ),
    node_id: Optional[str] = typer.Option(
        None, "--node", "-n", help="Specific node ID to run"
    ),
    project: str = typer.Option(
        "gotn", "--project", "-p", help="Project name for Neo4j namespace"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory (kuzu only)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be executed without running"
    ),
    show_strategy: bool = typer.Option(
        False, "--show-strategy", help="Show execution strategy before running"
    ),
    no_skills: bool = typer.Option(
        False, "--no-skills", help="Disable skill-based execution, use prompts only"
    ),
):
    """Run the next ready node or a specific node."""
    state = get_state_manager(store_path=store, project=project)
    scheduler = Scheduler(state)
    log_path = store or Path.cwd() / "store"
    executor = ClaudeExecutor(prefer_skills=not no_skills, store_path=log_path)

    if node_id:
        try:
            node = state.load_node(node_id)
        except FileNotFoundError:
            console.print(f"[red]Node not found: {node_id}[/red]")
            raise typer.Exit(1)
    else:
        scheduler.refresh_ready_queue()
        node = scheduler.get_next_node()

    if not node:
        console.print("[yellow]No ready nodes to execute[/yellow]")
        stats = scheduler.get_stats()
        console.print(f"Total nodes: {stats['total_nodes']}")
        console.print(f"By status: {stats['by_status']}")
        raise typer.Exit(0)

    def run_single_node(n: WorkNode) -> bool:
        """Run a single node. Returns True if should continue."""
        # Build context for strategy determination
        exec_context = ExecutionContext(max_depth=5)
        if n.parent:
            try:
                parent = state.load_node(n.parent)
                exec_context.parent_goal = parent.goal.statement
                exec_context.available_evidence = parent.evidence
            except FileNotFoundError:
                pass

        # Determine and optionally show strategy
        strategy = executor.determine_strategy(n, exec_context)

        if dry_run or show_strategy:
            console.print(f"\n[bold]Node: {n.id}[/bold]")
            console.print(f"  Goal: {n.goal.statement}")
            console.print(f"  Mode: {n.mode.value}")
            console.print(f"\n[bold]Execution Strategy:[/bold]")
            if strategy.use_skill:
                console.print(f"  [cyan]Skill:[/cyan] /{strategy.skill_name}")
                if strategy.skill_args:
                    console.print(f"  [dim]Args: {strategy.skill_args[:60]}...[/dim]")
            else:
                console.print(f"  [cyan]Prompt-based execution[/cyan]")
            console.print(f"  [dim]Reason: {strategy.reason}[/dim]")

            if dry_run:
                return False

        console.print(f"\n[bold]Running node: {n.id}[/bold]")
        console.print(f"  Goal: {n.goal.statement}")
        console.print(f"  Mode: {n.mode.value}")

        # Transition to running
        state.transition(n, "start")
        scheduler.mark_running(n)

        # Execute (reuse exec_context from strategy determination)
        if strategy.use_skill:
            console.print(f"  [dim]Executing via /{strategy.skill_name}...[/dim]")
        else:
            console.print("  [dim]Executing...[/dim]")
        result = executor.execute_node(n, exec_context)

        if result.error and not result.needs_budget_approval:
            console.print(f"  [red]Error: {result.error}[/red]")
            # Save error info and log file to node before transitioning
            n.error = ErrorInfo(
                code="EXECUTION_ERROR",
                message=result.error,
                recoverable="timeout" in result.error.lower(),
                occurred_at=datetime.now(),
            )
            if result.log_file:
                n.resource_usage.log_file = result.log_file
                console.print(f"  [dim]Log: {result.log_file}[/dim]")
            state.save_node(n)
            state.transition(n, "error")
            return False

        # Handle budget expansion request
        if result.needs_budget_approval and result.budget_request:
            req = result.budget_request
            console.print("\n[yellow]═══ Budget Checkpoint ═══[/yellow]")
            console.print(f"  Current turns used: {req.current_turns}")
            console.print(f"  Additional requested: {req.requested_additional}")
            console.print(f"  Completion confidence: {req.estimated_completion_confidence:.0%}")
            console.print(f"  Justification: {req.justification}")
            if req.progress_summary:
                console.print(f"\n  [dim]Progress: {req.progress_summary}[/dim]")
            console.print()

            # Ask for approval
            approve = typer.confirm(
                f"Approve budget expansion to {req.total_requested} total turns?",
                default=True,
            )

            if approve:
                # Update node budget and continue
                n.budget.steps = req.total_requested
                state.save_node(n)
                console.print(f"  [green]Budget expanded to {req.total_requested} turns[/green]")
                # Re-execute with new budget
                return run_single_node(n)
            else:
                console.print("  [red]Budget expansion denied[/red]")
                n.error = ErrorInfo(
                    code="BUDGET_DENIED",
                    message=f"User denied budget expansion from {req.current_turns} to {req.total_requested}",
                    recoverable=True,
                    occurred_at=datetime.now(),
                )
                state.save_node(n)
                state.transition(n, "escalate")
                return False

        # Apply result
        apply_result_to_node(n, result)

        # Materialize plan sub-goals if this is a planning node with a PlanOutput
        if n.mode == NodeMode.PLANNING:
            from gotn.node import PlanOutput
            has_plan = any(isinstance(o, PlanOutput) for o in n.outputs)
            if has_plan:
                children = scheduler.materialize_plan(n)
                if children:
                    console.print(f"  [cyan]Materialized {len(children)} sub-goals from plan[/cyan]")
                    for child in children[:5]:  # Show first 5
                        console.print(f"    {child.id}: {child.mode.value} - {child.goal.statement[:50]}...")
                    if len(children) > 5:
                        console.print(f"    ... and {len(children) - 5} more")
                    state.transition(n, "spawn_child")
                    return True

        # Check for child requests
        if result.child_requests:
            console.print(f"  [yellow]Node requested {len(result.child_requests)} children[/yellow]")
            state.transition(n, "spawn_child")

            for req in result.child_requests:
                child = scheduler.spawn_child(
                    n, req.mode, req.goal, req.criteria
                )
                console.print(f"    Spawned: {child.id} ({req.mode.value})")

            return True

        # Check if complete
        can_proceed, reason = should_proceed(n)
        if can_proceed:
            console.print(f"  [green]Complete: {reason}[/green]")
            state.transition(n, "complete")
            scheduler.mark_complete(n)
            return True

        # Check next action
        action = suggest_next_action(n)
        console.print(f"  [dim]Next action: {action}[/dim]")

        if action.startswith("escalate"):
            state.transition(n, "escalate")
            console.print(f"  [yellow]Escalated: requires human review[/yellow]")
            return False

        if action.startswith("degrade"):
            state.transition(n, "degrade")
            console.print(f"  [yellow]Degraded: {action}[/yellow]")
            return True

        if action.startswith("spawn_research"):
            # Extract criterion ID from action like "spawn_research: strengthen crit-123"
            parts = action.split(": ", 1)
            criterion_info = parts[1] if len(parts) > 1 else "gather evidence"

            # Create research goal based on the criterion
            research_goal = f"Research to {criterion_info} for: {n.goal.statement[:50]}"

            state.transition(n, "spawn_child")
            child = scheduler.spawn_child(n, NodeMode.EPISTEMIC, research_goal)
            console.print(f"  [yellow]Spawned research: {child.id}[/yellow]")
            return True

        # Continue working
        state.save_node(n)
        return True

    # Run once or continuously
    if continuous:
        console.print("[bold]Running in continuous mode[/bold]")
        iterations = 0
        max_iterations = 100  # Safety limit

        while iterations < max_iterations:
            if node is None:
                scheduler.refresh_ready_queue()
                node = scheduler.get_next_node()

            if node is None:
                break

            should_continue = run_single_node(node)
            iterations += 1

            if not should_continue and node.status == NodeStatus.ESCALATED:
                break

            node = None  # Get next node on next iteration

        console.print(f"\n[bold]Completed {iterations} iterations[/bold]")
    else:
        run_single_node(node)

    # Show final status (unless dry-run)
    if not dry_run:
        _status_impl(store=store, project=project)


def _status_impl(
    store: Optional[Path] = None,
    tree: bool = False,
    node_id: Optional[str] = None,
    verbose: bool = False,
    project: str = "gotn",
):
    """Internal status implementation (can be called from other commands)."""
    state = get_state_manager(store_path=store, project=project)
    all_nodes = state.load_all_nodes()

    if not all_nodes:
        console.print("[yellow]No nodes found[/yellow]")
        return

    if node_id:
        try:
            node = state.load_node(node_id)
            _show_node_detail(node, state, verbose=verbose)
        except FileNotFoundError:
            console.print(f"[red]Node not found: {node_id}[/red]")
            raise typer.Exit(1)
        return

    if tree:
        _show_tree(state, all_nodes, verbose=verbose)
    else:
        _show_table(all_nodes, state, verbose=verbose)


@app.command()
def status(
    tree: bool = typer.Option(False, "--tree", "-t", help="Show full DAG tree"),
    node_id: Optional[str] = typer.Option(
        None, "--node", "-n", help="Show details for specific node"
    ),
    project: str = typer.Option(
        "gotn", "--project", "-p", help="Project name for Neo4j namespace"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory (kuzu only)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show why nodes are blocked/failed"
    ),
):
    """Show status of the goal tree."""
    _status_impl(store=store, tree=tree, node_id=node_id, verbose=verbose, project=project)


def _get_blocking_reason(node: WorkNode, state: StateManager) -> str:
    """Get reason why a node is blocked or failed."""
    if node.status == NodeStatus.FAILED:
        if node.error:
            return f"Error: {node.error.message[:60]}"
        return "Failed (no error details)"

    if node.status == NodeStatus.BLOCKED:
        if not node.children:
            return "Blocked (no children)"
        # Find which children are not complete
        blocking_children = []
        for child_id in node.children:
            try:
                child = state.load_node(child_id)
                if child.status not in [NodeStatus.COMPLETE, NodeStatus.CANCELLED]:
                    blocking_children.append(f"{child_id[:12]}({child.status.value})")
            except FileNotFoundError:
                blocking_children.append(f"{child_id[:12]}(missing)")
        if blocking_children:
            return f"Waiting: {', '.join(blocking_children[:3])}" + (
                f" +{len(blocking_children)-3} more" if len(blocking_children) > 3 else ""
            )
        return "Blocked (all children complete - check dependencies)"

    if node.status == NodeStatus.ESCALATED:
        if node.escalation_context:
            return f"Escalated: {node.escalation_context.reason[:50]}"
        return "Escalated (awaiting human input)"

    return ""


def _show_table(nodes: dict[str, WorkNode], state: StateManager = None, verbose: bool = False):
    """Show nodes as a table."""
    table = Table(title="Goal Tree Status")
    table.add_column("ID", style="cyan")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Conf", justify="right")
    table.add_column("Goal")
    if verbose:
        table.add_column("Reason", style="dim")

    status_colors = {
        NodeStatus.PENDING: "dim",
        NodeStatus.READY: "yellow",
        NodeStatus.RUNNING: "blue",
        NodeStatus.BLOCKED: "magenta",
        NodeStatus.COMPLETE: "green",
        NodeStatus.DEGRADED: "yellow",
        NodeStatus.ESCALATED: "red",
        NodeStatus.FAILED: "red",
        NodeStatus.CANCELLED: "dim",
    }

    for node in sorted(nodes.values(), key=lambda n: (n.depth, n.created_at)):
        color = status_colors.get(node.status, "white")
        conf = f"{node.confidence.aggregate:.0%}" if node.confidence.aggregate else "-"
        goal = node.goal.statement[:50] + "..." if len(node.goal.statement) > 50 else node.goal.statement

        row = [
            node.id,
            f"[{color}]{node.status.value}[/{color}]",
            node.mode.value,
            conf,
            goal,
        ]
        if verbose and state:
            reason = _get_blocking_reason(node, state)
            row.append(reason)
        elif verbose:
            row.append("")

        table.add_row(*row)

    console.print(table)


def _show_tree(state: StateManager, nodes: dict[str, WorkNode], verbose: bool = False):
    """Show nodes as a tree."""
    root_nodes = [n for n in nodes.values() if n.parent is None]

    if not root_nodes:
        console.print("[yellow]No root nodes found[/yellow]")
        return

    for root in root_nodes:
        root_label = f"[bold]{root.id}[/bold] - {root.goal.statement[:40]}"
        if verbose and root.status in [NodeStatus.BLOCKED, NodeStatus.FAILED, NodeStatus.ESCALATED]:
            reason = _get_blocking_reason(root, state)
            if reason:
                root_label += f"\n  [dim]{reason}[/dim]"
        tree = Tree(root_label)
        _build_tree(tree, root, state, verbose=verbose)
        console.print(tree)


def _build_tree(tree: Tree, node: WorkNode, state: StateManager, verbose: bool = False):
    """Recursively build tree display."""
    status_icons = {
        NodeStatus.PENDING: "⏳",
        NodeStatus.READY: "🟡",
        NodeStatus.RUNNING: "🔵",
        NodeStatus.BLOCKED: "🟣",
        NodeStatus.COMPLETE: "✅",
        NodeStatus.DEGRADED: "⚠️",
        NodeStatus.ESCALATED: "🚨",
        NodeStatus.FAILED: "❌",
        NodeStatus.CANCELLED: "⬜",
    }

    for child_id in node.children:
        try:
            child = state.load_node(child_id)
            icon = status_icons.get(child.status, "")
            conf = f" [{child.confidence.aggregate:.0%}]" if child.confidence.aggregate else ""
            label = f"{icon} {child.id} ({child.mode.value}){conf} - {child.goal.statement[:30]}"
            if verbose and child.status in [NodeStatus.BLOCKED, NodeStatus.FAILED, NodeStatus.ESCALATED]:
                reason = _get_blocking_reason(child, state)
                if reason:
                    label += f"\n     [dim]{reason}[/dim]"
            branch = tree.add(label)
            _build_tree(branch, child, state, verbose=verbose)
        except FileNotFoundError:
            tree.add(f"[dim]{child_id} (missing)[/dim]")


def _show_node_detail(node: WorkNode, state: StateManager, verbose: bool = False):
    """Show detailed view of a single node."""
    console.print(Panel(f"[bold]Node: {node.id}[/bold]"))
    console.print(f"  Status: {node.status.value}")
    console.print(f"  Mode: {node.mode.value}")
    console.print(f"  Depth: {node.depth}")
    console.print(f"  Goal: {node.goal.statement}")

    if node.parent:
        console.print(f"  Parent: {node.parent}")

    # Show blocking reason for non-complete statuses
    if node.status in [NodeStatus.BLOCKED, NodeStatus.FAILED, NodeStatus.ESCALATED]:
        reason = _get_blocking_reason(node, state)
        if reason:
            console.print(f"\n[bold red]Status Reason:[/bold red]")
            console.print(f"  {reason}")

    # Show error details if present
    if node.error:
        console.print(f"\n[bold red]Error Details:[/bold red]")
        console.print(f"  Code: {node.error.code}")
        console.print(f"  Message: {node.error.message}")
        console.print(f"  Recoverable: {'Yes' if node.error.recoverable else 'No'}")
        console.print(f"  Occurred: {node.error.occurred_at}")
        if node.error.stack_trace and verbose:
            console.print(f"  Stack trace:\n{node.error.stack_trace}")

    # Show suggested remediation
    if node.status == NodeStatus.FAILED and node.error:
        console.print(f"\n[bold yellow]Suggested Actions:[/bold yellow]")
        if node.error.recoverable:
            console.print(f"  • Retry: gotn resume {node.id}")
        if "timeout" in node.error.message.lower():
            console.print(f"  • Increase timeout: gotn run --timeout 300000")
        console.print(f"  • Cancel: gotn cancel {node.id}")

    console.print("\n[bold]Acceptance Criteria:[/bold]")
    for c in node.goal.acceptance_criteria:
        status = "✅" if c.satisfied else "⬜"
        must = " (REQUIRED)" if c.must_pass else ""
        console.print(f"  {status} {c.description}{must} [{c.confidence:.0%}]")

    result = compute_node_confidence(node)
    console.print(f"\n[bold]Confidence:[/bold] {result.aggregate:.0%}")
    if result.weakest_criterion:
        console.print(f"  Weakest: {result.weakest_criterion} ({result.weakest_confidence:.0%})")

    if node.claims:
        console.print(f"\n[bold]Claims ({len(node.claims)}):[/bold]")
        for claim in node.claims[:5]:
            console.print(f"  • {claim.proposition[:60]} [{claim.confidence:.0%}]")
        if len(node.claims) > 5:
            console.print(f"  ... and {len(node.claims) - 5} more")

    if node.children:
        console.print(f"\n[bold]Children ({len(node.children)}):[/bold]")
        for child_id in node.children:
            try:
                child = state.load_node(child_id)
                child_info = f"  • {child_id}: {child.status.value} - {child.goal.statement[:40]}"
                if verbose and child.status in [NodeStatus.BLOCKED, NodeStatus.FAILED]:
                    child_reason = _get_blocking_reason(child, state)
                    if child_reason:
                        child_info += f"\n      [dim]{child_reason}[/dim]"
                console.print(child_info)
            except FileNotFoundError:
                console.print(f"  • {child_id}: [dim]missing[/dim]")

    console.print(f"\n[bold]Resource Usage:[/bold]")
    console.print(f"  Tokens: {node.resource_usage.tokens}")
    console.print(f"  Time: {node.resource_usage.time_ms}ms")
    console.print(f"  Steps: {node.resource_usage.steps}")
    if node.resource_usage.log_file:
        console.print(f"  Log: {node.resource_usage.log_file}")


@app.command()
def spawn(
    parent_id: str = typer.Argument(..., help="Parent node ID"),
    goal: str = typer.Option(..., "--goal", "-g", help="Goal for the child node"),
    mode: str = typer.Option(
        "epistemic", "--mode", "-m", help="Node mode"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Spawn a child node under an existing node."""
    try:
        node_mode = NodeMode(mode)
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        raise typer.Exit(1)

    state = get_state_manager(store)
    scheduler = Scheduler(state)

    try:
        parent = state.load_node(parent_id)
    except FileNotFoundError:
        console.print(f"[red]Parent node not found: {parent_id}[/red]")
        raise typer.Exit(1)

    if parent.status not in (NodeStatus.RUNNING, NodeStatus.BLOCKED):
        console.print(
            f"[red]Parent must be RUNNING or BLOCKED, got: {parent.status.value}[/red]"
        )
        raise typer.Exit(1)

    child = scheduler.spawn_child(parent, node_mode, goal)

    console.print(Panel("[green]Spawned child node[/green]"))
    console.print(f"  ID: [cyan]{child.id}[/cyan]")
    console.print(f"  Mode: {child.mode.value}")
    console.print(f"  Goal: {child.goal.statement}")
    console.print(f"  Parent: {parent.id}")


@app.command()
def resume(
    node_id: str = typer.Argument(..., help="Node ID to resume"),
    decision: str = typer.Option(
        ..., "--decision", "-d", help="Decision: proceed, cancel, modify"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Resume an escalated node after human review."""
    state = get_state_manager(store)

    try:
        node = state.load_node(node_id)
    except FileNotFoundError:
        console.print(f"[red]Node not found: {node_id}[/red]")
        raise typer.Exit(1)

    if node.status != NodeStatus.ESCALATED:
        console.print(f"[red]Node is not escalated: {node.status.value}[/red]")
        raise typer.Exit(1)

    decision_lower = decision.lower()

    if decision_lower == "proceed":
        state.transition(node, "resume")
        console.print(f"[green]Resumed node {node_id}[/green]")
    elif decision_lower == "cancel":
        state.transition(node, "cancel")
        console.print(f"[yellow]Cancelled node {node_id}[/yellow]")
    else:
        console.print(f"[red]Unknown decision: {decision}[/red]")
        console.print("Valid decisions: proceed, cancel")
        raise typer.Exit(1)


@app.command()
def retry(
    node_id: str = typer.Argument(..., help="Node ID to retry"),
    reset_budget: bool = typer.Option(
        True, "--reset-budget/--no-reset-budget", help="Reset resource usage for fresh budget"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Retry a failed node with fresh budget."""
    state = get_state_manager(store)

    try:
        node = state.load_node(node_id)
    except FileNotFoundError:
        console.print(f"[red]Node not found: {node_id}[/red]")
        raise typer.Exit(1)

    if node.status != NodeStatus.FAILED:
        console.print(f"[red]Node is not failed: {node.status.value}[/red]")
        console.print("Only failed nodes can be retried")
        raise typer.Exit(1)

    # Clear error info
    node.error = None

    # Reset resource usage if requested
    if reset_budget:
        node.resource_usage.time_ms = 0
        node.resource_usage.tokens = 0
        node.resource_usage.steps = 0
        node.resource_usage.cost_dollars = 0.0
        console.print("  [dim]Reset resource usage for fresh budget[/dim]")

    # Transition to ready
    state.transition(node, "retry")
    console.print(f"[green]Node {node_id} is now ready to retry[/green]")
    console.print(f"  Status: {node.status.value}")
    console.print(f"  Run 'gotn run' to execute")


@app.command()
def export(
    format: str = typer.Option(
        "yaml", "--format", "-f", help="Export format: yaml, json, mermaid"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file (default: stdout)"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Export the goal tree."""
    import json as json_lib

    import yaml as yaml_lib

    state = get_state_manager(store)
    all_nodes = state.load_all_nodes()

    if format == "yaml":
        data = {
            node_id: node.model_dump(mode="json", exclude_none=True)
            for node_id, node in all_nodes.items()
        }
        content = yaml_lib.dump(data, default_flow_style=False, sort_keys=False)

    elif format == "json":
        data = {
            node_id: node.model_dump(mode="json", exclude_none=True)
            for node_id, node in all_nodes.items()
        }
        content = json_lib.dumps(data, indent=2)

    elif format == "mermaid":
        content = _export_mermaid(all_nodes)

    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)

    if output:
        output.write_text(content)
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


def _export_mermaid(nodes: dict[str, WorkNode]) -> str:
    """Export nodes as Mermaid diagram."""
    lines = ["flowchart TB"]

    status_styles = {
        NodeStatus.PENDING: ":::pending",
        NodeStatus.READY: ":::ready",
        NodeStatus.RUNNING: ":::running",
        NodeStatus.BLOCKED: ":::blocked",
        NodeStatus.COMPLETE: ":::complete",
        NodeStatus.DEGRADED: ":::degraded",
        NodeStatus.ESCALATED: ":::escalated",
        NodeStatus.FAILED: ":::failed",
        NodeStatus.CANCELLED: ":::cancelled",
    }

    # Add nodes
    for node in nodes.values():
        label = node.goal.statement[:30].replace('"', "'")
        style = status_styles.get(node.status, "")
        lines.append(f'    {node.id}["{label}"]{style}')

    # Add edges
    for node in nodes.values():
        for child_id in node.children:
            lines.append(f"    {node.id} --> {child_id}")

        for edge in node.edges:
            if edge.type.value == "depends_on":
                lines.append(f"    {edge.target} --> {node.id}")

    # Add styles
    lines.extend([
        "",
        "    classDef pending fill:#gray",
        "    classDef ready fill:#yellow",
        "    classDef running fill:#blue",
        "    classDef blocked fill:#purple",
        "    classDef complete fill:#green",
        "    classDef degraded fill:#orange",
        "    classDef escalated fill:#red",
        "    classDef failed fill:#darkred",
        "    classDef cancelled fill:#lightgray",
    ])

    return "\n".join(lines)


@app.command()
def cancel(
    node_id: str = typer.Argument(..., help="Node ID to cancel"),
    cascade: bool = typer.Option(
        True, "--cascade/--no-cascade", help="Also cancel all descendants"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Cancel a node and optionally its descendants."""
    state = get_state_manager(store)

    try:
        node = state.load_node(node_id)
    except FileNotFoundError:
        console.print(f"[red]Node not found: {node_id}[/red]")
        raise typer.Exit(1)

    if cascade:
        cancelled = state.cascade_cancel(node)
        console.print(f"[yellow]Cancelled {len(cancelled)} nodes[/yellow]")
        for n in cancelled:
            console.print(f"  • {n.id}")
    else:
        if not node.status.is_terminal:
            state.transition(node, "cancel")
            console.print(f"[yellow]Cancelled node {node_id}[/yellow]")
        else:
            console.print(f"[dim]Node already terminal: {node.status.value}[/dim]")


@app.command()
def projects(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed stats"),
):
    """List all projects in the Neo4j database."""
    from gotn.neo4j_graph import Neo4jGraphStore

    graph = Neo4jGraphStore()
    project_list = graph.list_projects()
    graph.close()

    if not project_list:
        console.print("[yellow]No projects found[/yellow]")
        return

    table = Table(title="GOTN Projects")
    table.add_column("Project", style="cyan")
    table.add_column("Nodes", justify="right")
    table.add_column("Complete", justify="right", style="green")
    table.add_column("Running", justify="right", style="blue")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Last Activity")

    for p in project_list:
        by_status = p["by_status"]
        # Handle both string and Neo4j DateTime objects
        newest = p["newest_node"]
        if newest:
            newest_str = str(newest)[:10] if hasattr(newest, '__str__') else newest[:10]
        else:
            newest_str = "-"
        table.add_row(
            p["project"],
            str(p["total_nodes"]),
            str(by_status.get("complete", 0)),
            str(by_status.get("running", 0) + by_status.get("blocked", 0)),
            str(by_status.get("failed", 0)),
            newest_str,
        )

    console.print(table)

    if verbose:
        console.print(f"\n[dim]Total: {len(project_list)} projects, {sum(p['total_nodes'] for p in project_list)} nodes[/dim]")


@app.command("delete-project")
def delete_project(
    project_name: str = typer.Argument(..., help="Name of the project to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete all nodes belonging to a project."""
    from gotn.neo4j_graph import Neo4jGraphStore

    graph = Neo4jGraphStore()
    stats = graph.get_project_stats(project_name)

    if stats["total_nodes"] == 0:
        console.print(f"[yellow]Project '{project_name}' not found or empty[/yellow]")
        graph.close()
        return

    console.print(f"\n[bold]Project: {project_name}[/bold]")
    console.print(f"  Total nodes: {stats['total_nodes']}")
    console.print(f"  By status: {stats['by_status']}")
    console.print(f"  By mode: {stats['by_mode']}")

    if not force:
        confirm = typer.confirm(f"\nDelete all {stats['total_nodes']} nodes?", default=False)
        if not confirm:
            console.print("[dim]Cancelled[/dim]")
            graph.close()
            return

    deleted = graph.delete_project(project_name)
    graph.close()

    console.print(f"\n[green]Deleted {deleted} nodes from project '{project_name}'[/green]")


@app.command("gc")
def garbage_collect(
    older_than_days: int = typer.Option(7, "--older-than", help="Delete projects older than N days"),
    status: str = typer.Option("failed", "--status", help="Only delete projects where all nodes have this status"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Show what would be deleted without deleting"),
):
    """Garbage collect old/stale projects."""
    from datetime import datetime, timedelta

    from gotn.neo4j_graph import Neo4jGraphStore

    graph = Neo4jGraphStore()
    project_list = graph.list_projects()

    cutoff = datetime.now() - timedelta(days=older_than_days)
    cutoff_str = cutoff.isoformat()

    candidates = []
    for p in project_list:
        # Check age - handle both string and Neo4j DateTime objects
        newest = p["newest_node"]
        if newest:
            newest_str = str(newest)[:19] if hasattr(newest, 'isoformat') else str(newest)[:19]
            if newest_str > cutoff_str[:19]:
                continue

        # Check status filter
        if status:
            by_status = p["by_status"]
            total = p["total_nodes"]
            if by_status.get(status, 0) != total:
                continue

        candidates.append(p)

    if not candidates:
        console.print(f"[green]No projects match cleanup criteria[/green]")
        console.print(f"  Criteria: older than {older_than_days} days, status={status}")
        graph.close()
        return

    console.print(f"\n[bold]Projects matching cleanup criteria:[/bold]")
    for p in candidates:
        newest = p["newest_node"]
        newest_str = str(newest)[:10] if newest else "unknown"
        console.print(f"  • {p['project']}: {p['total_nodes']} nodes, last activity: {newest_str}")

    total_nodes = sum(p["total_nodes"] for p in candidates)

    if dry_run:
        console.print(f"\n[yellow]DRY RUN: Would delete {len(candidates)} projects ({total_nodes} nodes)[/yellow]")
        console.print("[dim]Use --execute to actually delete[/dim]")
    else:
        confirm = typer.confirm(f"\nDelete {len(candidates)} projects ({total_nodes} nodes)?", default=False)
        if confirm:
            deleted_total = 0
            for p in candidates:
                deleted = graph.delete_project(p["project"])
                deleted_total += deleted
                console.print(f"  [dim]Deleted {p['project']} ({deleted} nodes)[/dim]")
            console.print(f"\n[green]Deleted {deleted_total} nodes from {len(candidates)} projects[/green]")
        else:
            console.print("[dim]Cancelled[/dim]")

    graph.close()


if __name__ == "__main__":
    app()
