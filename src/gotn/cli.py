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
from gotn.node import NodeMode, NodeStatus, WorkNode
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


def get_state_manager(store_path: Optional[Path] = None) -> StateManager:
    """Get or create state manager."""
    path = store_path or DEFAULT_STORE
    return StateManager(path)


@app.command()
def init(
    goal: str = typer.Argument(..., help="The goal statement for the root node"),
    mode: str = typer.Option(
        "epistemic",
        "--mode",
        "-m",
        help="Node mode: epistemic, instrumental, decision, validation",
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Initialize a new goal tree with a root node."""
    try:
        node_mode = NodeMode(mode)
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        console.print("Valid modes: epistemic, instrumental, decision, validation")
        raise typer.Exit(1)

    state = get_state_manager(store)
    root = WorkNode.create_root(goal, mode=node_mode)
    state.create_node(root)

    console.print(Panel(f"[green]Created root node[/green]"))
    console.print(f"  ID: [cyan]{root.id}[/cyan]")
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
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
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
    state = get_state_manager(store)
    scheduler = Scheduler(state)
    executor = ClaudeExecutor(prefer_skills=not no_skills)

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

        if result.error:
            console.print(f"  [red]Error: {result.error}[/red]")
            state.transition(n, "error")
            return False

        # Apply result
        apply_result_to_node(n, result)

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
        status(store=store)


@app.command()
def status(
    tree: bool = typer.Option(False, "--tree", "-t", help="Show full DAG tree"),
    node_id: Optional[str] = typer.Option(
        None, "--node", "-n", help="Show details for specific node"
    ),
    store: Optional[Path] = typer.Option(
        None, "--store", "-s", help="Path to store directory"
    ),
):
    """Show status of the goal tree."""
    state = get_state_manager(store)
    all_nodes = state.load_all_nodes()

    if not all_nodes:
        console.print("[yellow]No nodes found[/yellow]")
        raise typer.Exit(0)

    if node_id:
        try:
            node = state.load_node(node_id)
            _show_node_detail(node, state)
        except FileNotFoundError:
            console.print(f"[red]Node not found: {node_id}[/red]")
            raise typer.Exit(1)
        return

    if tree:
        _show_tree(state, all_nodes)
    else:
        _show_table(all_nodes)


def _show_table(nodes: dict[str, WorkNode]):
    """Show nodes as a table."""
    table = Table(title="Goal Tree Status")
    table.add_column("ID", style="cyan")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Conf", justify="right")
    table.add_column("Goal")

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

        table.add_row(
            node.id,
            f"[{color}]{node.status.value}[/{color}]",
            node.mode.value,
            conf,
            goal,
        )

    console.print(table)


def _show_tree(state: StateManager, nodes: dict[str, WorkNode]):
    """Show nodes as a tree."""
    root_nodes = [n for n in nodes.values() if n.parent is None]

    if not root_nodes:
        console.print("[yellow]No root nodes found[/yellow]")
        return

    for root in root_nodes:
        tree = Tree(f"[bold]{root.id}[/bold] - {root.goal.statement[:40]}")
        _build_tree(tree, root, state)
        console.print(tree)


def _build_tree(tree: Tree, node: WorkNode, state: StateManager):
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
            branch = tree.add(label)
            _build_tree(branch, child, state)
        except FileNotFoundError:
            tree.add(f"[dim]{child_id} (missing)[/dim]")


def _show_node_detail(node: WorkNode, state: StateManager):
    """Show detailed view of a single node."""
    console.print(Panel(f"[bold]Node: {node.id}[/bold]"))
    console.print(f"  Status: {node.status.value}")
    console.print(f"  Mode: {node.mode.value}")
    console.print(f"  Depth: {node.depth}")
    console.print(f"  Goal: {node.goal.statement}")

    if node.parent:
        console.print(f"  Parent: {node.parent}")

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
                console.print(f"  • {child_id}: {child.status.value} - {child.goal.statement[:40]}")
            except FileNotFoundError:
                console.print(f"  • {child_id}: [dim]missing[/dim]")

    console.print(f"\n[bold]Resource Usage:[/bold]")
    console.print(f"  Tokens: {node.resource_usage.tokens}")
    console.print(f"  Time: {node.resource_usage.time_ms}ms")
    console.print(f"  Steps: {node.resource_usage.steps}")


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


if __name__ == "__main__":
    app()
