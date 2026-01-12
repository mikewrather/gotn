"""Tool and skill mappings for Claude Code integration."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from gotn.node import NodeMode


class ToolType(str, Enum):
    """Types of Claude Code tools available."""

    # Core tools
    READ = "Read"
    WRITE = "Write"
    EDIT = "Edit"
    BASH = "Bash"
    GLOB = "Glob"
    GREP = "Grep"
    WEB_SEARCH = "WebSearch"
    WEB_FETCH = "WebFetch"

    # Agent tools
    TASK_EXPLORE = "Task:Explore"
    TASK_GENERAL = "Task:general-purpose"
    TASK_CODEX = "Task:codex-default"
    TASK_GEMINI = "Task:gemini-default"
    TASK_DEEP_RESEARCH = "Task:deep-research-supervisor"
    TASK_PLAYWRIGHT = "Task:playwright-test-executor"

    # Skills
    SKILL_DEEP_RESEARCH = "Skill:deep-research"
    SKILL_TRIAD = "Skill:triad-orchestrator:run"


@dataclass
class ToolSpec:
    """Specification for a tool to use."""

    tool: ToolType
    purpose: str
    priority: int = 0  # Higher = prefer this tool
    constraints: Optional[str] = None


@dataclass
class ModeToolkit:
    """Tools available for a specific node mode."""

    mode: NodeMode
    primary_tools: list[ToolSpec] = field(default_factory=list)
    secondary_tools: list[ToolSpec] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    instructions: str = ""


# Define toolkits for each mode
EPISTEMIC_TOOLKIT = ModeToolkit(
    mode=NodeMode.EPISTEMIC,
    primary_tools=[
        ToolSpec(
            ToolType.SKILL_DEEP_RESEARCH,
            "Comprehensive multi-source research on complex topics",
            priority=10,
            constraints="Use for topics requiring multiple perspectives or sources",
        ),
        ToolSpec(
            ToolType.WEB_SEARCH,
            "Quick fact-finding and current information",
            priority=8,
        ),
        ToolSpec(
            ToolType.TASK_EXPLORE,
            "Codebase exploration and understanding",
            priority=7,
            constraints="Use when researching code patterns or architecture",
        ),
    ],
    secondary_tools=[
        ToolSpec(ToolType.WEB_FETCH, "Fetch and analyze specific URLs", priority=5),
        ToolSpec(ToolType.READ, "Read local documentation files", priority=4),
        ToolSpec(ToolType.GREP, "Search codebase for patterns", priority=3),
    ],
    skills=["deep-research"],
    instructions="""
For epistemic (research) work:
1. Start with /deep-research for comprehensive topics requiring multiple sources
2. Use WebSearch for quick fact-finding or current information
3. Use Task(Explore) when investigating codebase patterns
4. Cross-reference multiple sources before making claims
5. Always cite sources with URLs or file paths
""",
)

INSTRUMENTAL_TOOLKIT = ModeToolkit(
    mode=NodeMode.INSTRUMENTAL,
    primary_tools=[
        ToolSpec(
            ToolType.WRITE,
            "Create new files",
            priority=10,
        ),
        ToolSpec(
            ToolType.EDIT,
            "Modify existing files",
            priority=10,
        ),
        ToolSpec(
            ToolType.BASH,
            "Run commands, build, test",
            priority=9,
        ),
    ],
    secondary_tools=[
        ToolSpec(ToolType.READ, "Understand existing code before changes", priority=8),
        ToolSpec(ToolType.GLOB, "Find files to modify", priority=6),
        ToolSpec(
            ToolType.TASK_GENERAL,
            "Delegate complex sub-tasks",
            priority=5,
        ),
    ],
    skills=[],
    instructions="""
For instrumental (building) work:
1. ALWAYS read existing code before modifying
2. Use Edit for modifications, Write only for new files
3. Run tests after changes with Bash
4. Follow existing code patterns and conventions
5. Keep changes minimal and focused
""",
)

DECISION_TOOLKIT = ModeToolkit(
    mode=NodeMode.DECISION,
    primary_tools=[
        ToolSpec(
            ToolType.TASK_CODEX,
            "Get expert review of options and trade-offs",
            priority=10,
        ),
        ToolSpec(
            ToolType.TASK_GEMINI,
            "Get diverse perspective on decision",
            priority=9,
        ),
        ToolSpec(
            ToolType.SKILL_TRIAD,
            "Multi-model consensus for critical decisions",
            priority=8,
            constraints="Use for high-stakes architectural decisions",
        ),
    ],
    secondary_tools=[
        ToolSpec(ToolType.READ, "Review relevant code/docs", priority=7),
        ToolSpec(ToolType.WEB_SEARCH, "Research best practices", priority=5),
    ],
    skills=["triad-orchestrator:run"],
    instructions="""
For decision work:
1. Enumerate all viable options explicitly
2. Use Task(codex-default) or Task(gemini-default) for expert review
3. For critical decisions, use /triad-orchestrator:run for multi-model consensus
4. Document trade-offs for each option
5. Always define a rollback plan
""",
)

VALIDATION_TOOLKIT = ModeToolkit(
    mode=NodeMode.VALIDATION,
    primary_tools=[
        ToolSpec(
            ToolType.BASH,
            "Run test suites (pytest, jest, etc.)",
            priority=10,
        ),
        ToolSpec(
            ToolType.TASK_PLAYWRIGHT,
            "Run Playwright E2E tests",
            priority=9,
            constraints="Use when validating UI/frontend changes",
        ),
    ],
    secondary_tools=[
        ToolSpec(ToolType.READ, "Review code being validated", priority=8),
        ToolSpec(ToolType.GREP, "Search for test coverage", priority=5),
        ToolSpec(
            ToolType.TASK_CODEX,
            "Code review for quality issues",
            priority=6,
        ),
    ],
    skills=[],
    instructions="""
For validation work:
1. Run existing test suites first with Bash
2. Use Task(playwright-test-executor) for UI validation
3. Use Task(codex-default) for code review
4. Check each acceptance criterion systematically
5. Report issues with severity levels
""",
)

# Registry of all toolkits
MODE_TOOLKITS: dict[NodeMode, ModeToolkit] = {
    NodeMode.EPISTEMIC: EPISTEMIC_TOOLKIT,
    NodeMode.INSTRUMENTAL: INSTRUMENTAL_TOOLKIT,
    NodeMode.DECISION: DECISION_TOOLKIT,
    NodeMode.VALIDATION: VALIDATION_TOOLKIT,
}


def get_toolkit(mode: NodeMode) -> ModeToolkit:
    """Get the toolkit for a node mode."""
    return MODE_TOOLKITS.get(mode, EPISTEMIC_TOOLKIT)


def get_tool_instructions(mode: NodeMode) -> str:
    """Get tool usage instructions for a mode."""
    toolkit = get_toolkit(mode)

    lines = [toolkit.instructions.strip(), "", "## Available Tools", ""]

    lines.append("### Primary (prefer these):")
    for tool in sorted(toolkit.primary_tools, key=lambda t: -t.priority):
        constraint = f" - {tool.constraints}" if tool.constraints else ""
        lines.append(f"- **{tool.tool.value}**: {tool.purpose}{constraint}")

    lines.append("")
    lines.append("### Secondary:")
    for tool in sorted(toolkit.secondary_tools, key=lambda t: -t.priority):
        lines.append(f"- **{tool.tool.value}**: {tool.purpose}")

    if toolkit.skills:
        lines.append("")
        lines.append("### Skills:")
        for skill in toolkit.skills:
            lines.append(f"- `/{skill}`")

    return "\n".join(lines)


def should_use_deep_research(goal: str, mode: NodeMode) -> bool:
    """Determine if deep research skill should be used."""
    if mode != NodeMode.EPISTEMIC:
        return False

    # Keywords that suggest comprehensive research is needed
    research_keywords = [
        "research",
        "investigate",
        "compare",
        "analyze",
        "evaluate",
        "understand",
        "comprehensive",
        "thorough",
        "best practices",
        "state of the art",
        "options for",
        "alternatives",
    ]

    goal_lower = goal.lower()
    return any(kw in goal_lower for kw in research_keywords)


def should_use_triad(goal: str, mode: NodeMode) -> bool:
    """Determine if triad orchestrator should be used for decisions."""
    if mode != NodeMode.DECISION:
        return False

    # Keywords that suggest multi-perspective review is valuable
    critical_keywords = [
        "architecture",
        "security",
        "critical",
        "important",
        "design",
        "strategy",
        "framework",
        "infrastructure",
        "migration",
    ]

    goal_lower = goal.lower()
    return any(kw in goal_lower for kw in critical_keywords)
