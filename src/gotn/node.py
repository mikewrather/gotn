"""WorkNode data model and related types."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from nanoid import generate
from pydantic import BaseModel, Field, field_validator


def generate_id(prefix: str = "node") -> str:
    """Generate a unique node ID."""
    return f"{prefix}-{generate(size=8)}"


class NodeStatus(str, Enum):
    """WorkNode execution status."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    ESCALATED = "escalated"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (
            NodeStatus.COMPLETE,
            NodeStatus.DEGRADED,
            NodeStatus.ESCALATED,
            NodeStatus.FAILED,
            NodeStatus.CANCELLED,
        )


class NodeMode(str, Enum):
    """WorkNode execution mode."""

    PLANNING = "planning"  # Decompose complex goals into sub-goals
    EPISTEMIC = "epistemic"  # Acquire knowledge, reduce uncertainty
    DECISION = "decision"  # Make binding choices based on evidence
    INSTRUMENTAL = "instrumental"  # Produce artifacts (code, content)
    VALIDATION = "validation"  # Verify artifacts or claims


class DeliverableType(str, Enum):
    """Type of output the node produces."""

    PLAN = "plan"  # Decomposition into sub-goals
    KNOWLEDGE = "knowledge"  # Claims and evidence
    COMMITMENT = "commitment"  # Binding decision
    ARTIFACT = "artifact"  # Code, content, config
    VERIFICATION = "verification"  # Pass/fail result


class CriterionType(str, Enum):
    """Type of acceptance criterion."""

    KNOWLEDGE = "knowledge"
    ARTIFACT = "artifact"
    VALIDATION = "validation"
    METRIC = "metric"
    COMMITMENT = "commitment"


class ClaimDomain(str, Enum):
    """Domain for claim recency decay rates."""

    API_DOCUMENTATION = "api_documentation"
    ACADEMIC_RESEARCH = "academic_research"
    MARKET_DATA = "market_data"
    EXPERIMENT_RESULT = "experiment_result"
    CONFIGURATION = "configuration"
    USER_PREFERENCE = "user_preference"
    GENERAL = "general"

    @property
    def half_life_days(self) -> int:
        """Get decay half-life in days for this domain."""
        rates = {
            ClaimDomain.API_DOCUMENTATION: 90,
            ClaimDomain.ACADEMIC_RESEARCH: 730,
            ClaimDomain.MARKET_DATA: 30,
            ClaimDomain.EXPERIMENT_RESULT: 180,
            ClaimDomain.CONFIGURATION: 60,
            ClaimDomain.USER_PREFERENCE: 365,
            ClaimDomain.GENERAL: 180,
        }
        return rates[self]


class EvidenceType(str, Enum):
    """Type of evidence."""

    RESEARCH = "research"
    EXPERIMENT = "experiment"
    EXPERT = "expert"
    DOCUMENTATION = "documentation"
    VALIDATION = "validation"


class EdgeType(str, Enum):
    """Type of relationship between nodes."""

    DEPENDS_ON = "depends_on"
    INFORMS = "informs"
    BLOCKS = "blocks"
    ENABLES = "enables"
    SPAWNED_BY = "spawned_by"
    SUPERSEDES = "supersedes"

    @property
    def is_blocking(self) -> bool:
        """Check if this edge type participates in cycle detection."""
        return self in (EdgeType.DEPENDS_ON, EdgeType.BLOCKS)


class RiskFlag(str, Enum):
    """Risk flags that affect autonomy decisions."""

    SAFETY = "safety"
    COST = "cost"
    APPROPRIATENESS = "appropriateness"
    LEGAL = "legal"
    IRREVERSIBLE = "irreversible"


class Deadline(BaseModel):
    """Deadline for goal completion."""

    type: str = Field(description="soft or hard")
    timestamp: datetime
    consequence: str = Field(description="What happens if missed")


class Criterion(BaseModel):
    """Acceptance criterion for a goal."""

    id: str = Field(default_factory=lambda: generate_id("crit"))
    description: str
    type: CriterionType
    satisfied: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    must_pass: bool = False


class Goal(BaseModel):
    """What we're trying to achieve."""

    statement: str = Field(min_length=10)
    original_question: Optional[str] = None
    acceptance_criteria: list[Criterion] = Field(min_length=1)
    deadline: Optional[Deadline] = None


class Budget(BaseModel):
    """Resource constraints for a node."""

    time_ms: Optional[int] = Field(default=None, ge=0)
    tokens: Optional[int] = Field(default=None, ge=0)
    steps: Optional[int] = Field(default=None, ge=0)
    cost_dollars: Optional[float] = Field(default=None, ge=0.0)
    exhausted: bool = False


class ResourceUsage(BaseModel):
    """Actual resource consumption (tracked at runtime)."""

    time_ms: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    steps: int = Field(default=0, ge=0)
    cost_dollars: float = Field(default=0.0, ge=0.0)
    started_at: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=datetime.now)
    log_file: Optional[str] = None  # Path to execution log file


class Claim(BaseModel):
    """A proposition we believe to be true, with confidence."""

    id: str = Field(default_factory=lambda: generate_id("claim"))
    proposition: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    expiry: Optional[datetime] = None
    scope: str = Field(default="global")
    domain: ClaimDomain = ClaimDomain.GENERAL

    @field_validator("domain", mode="before")
    @classmethod
    def validate_domain(cls, v):
        """Handle unknown domain values gracefully."""
        if isinstance(v, ClaimDomain):
            return v
        if isinstance(v, str):
            try:
                return ClaimDomain(v)
            except ValueError:
                return ClaimDomain.GENERAL
        return ClaimDomain.GENERAL


class Evidence(BaseModel):
    """Supporting material for claims and decisions."""

    id: str = Field(default_factory=lambda: generate_id("ev"))
    type: EvidenceType
    source: str
    summary: str
    strength: float = Field(ge=0.0, le=1.0)
    recency: datetime = Field(default_factory=datetime.now)
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)


class AggregatedConfidence(BaseModel):
    """Aggregated confidence across all criteria."""

    aggregate: float = Field(default=0.0, ge=0.0, le=1.0)
    by_criterion: dict[str, float] = Field(default_factory=dict)
    aggregation_method: str = "weighted_mean"
    last_computed: datetime = Field(default_factory=datetime.now)


class AutonomyGate(BaseModel):
    """Controls when the node can proceed autonomously."""

    proceed_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    must_pass_criteria: list[str] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    human_required: bool = False
    escalation_triggers: list[str] = Field(default_factory=list)


class ExitPolicy(BaseModel):
    """What to do when the node can't complete normally."""

    on_success: str = "complete"
    on_budget_exhausted: str = "degrade"
    on_blocked: str = "spawn_child"
    on_low_confidence: str = "spawn_research"
    degradation_output: Optional[str] = None
    rollback_plan: Optional[str] = None


class TypedEdge(BaseModel):
    """Relationship between nodes."""

    target: str  # Node ID
    type: EdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlaggedItem(BaseModel):
    """Content flagged for human review."""

    id: str = Field(default_factory=lambda: generate_id("flag"))
    content: str
    concern: str
    location: Optional[str] = None


class EscalationOption(BaseModel):
    """Choice presented to human during escalation."""

    action: str
    description: str
    impact: Optional[str] = None


class EscalationContext(BaseModel):
    """Context provided when a node escalates to human review."""

    reason: str
    criterion_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    flagged_content: list[FlaggedItem] = Field(default_factory=list)
    options: list[EscalationOption] = Field(default_factory=list)
    timeout: Optional[str] = None
    default_action: Optional[str] = None


class ErrorInfo(BaseModel):
    """Error information when a node fails."""

    code: str
    message: str
    recoverable: bool = False
    occurred_at: datetime = Field(default_factory=datetime.now)
    stack_trace: Optional[str] = None
    context: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """A research finding."""

    id: str = Field(default_factory=lambda: generate_id("find"))
    source: str
    summary: str
    relevance: float = Field(ge=0.0, le=1.0)
    raw_content: Optional[str] = None


class Assumption(BaseModel):
    """An assumption underlying a decision."""

    id: str = Field(default_factory=lambda: generate_id("assum"))
    statement: str
    basis: str
    expiry: Optional[datetime] = None
    invalidation_trigger: str


class CriterionResult(BaseModel):
    """Result of evaluating a criterion during validation."""

    criterion_id: str
    passed: bool
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    evidence_id: Optional[str] = None


class ValidationIssue(BaseModel):
    """Issue found during validation."""

    severity: str  # critical, major, minor, info
    description: str
    location: Optional[str] = None
    suggestion: Optional[str] = None


class KnowledgeOutput(BaseModel):
    """Output from epistemic nodes."""

    type: str = "knowledge"
    claims: list[Claim] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    content: Optional[str] = None  # Alternative field name Claude might use


class ArtifactOutput(BaseModel):
    """Output from instrumental nodes."""

    type: str = "artifact"
    path: Optional[str] = None
    artifact_type: Optional[str] = None
    hash: Optional[str] = None
    content: Optional[str] = None  # For inline content without file path
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommitmentOutput(BaseModel):
    """Output from decision nodes."""

    type: str = "commitment"
    choice_set: list[str] = Field(default_factory=list)
    selected: Optional[str] = None
    rationale: str = ""
    # Accept both list (simple) and dict (detailed) formats
    constraints: list[str] | dict[str, Any] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    rollback_plan: str = ""
    # Accept strings, Assumption objects, or dicts with any assumption-related fields
    assumption_ledger: list[str | Assumption | dict[str, Any]] = Field(default_factory=list)


class ValidationOutput(BaseModel):
    """Output from validation nodes."""

    type: str = "verification"
    target_node: str
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    passed: bool
    coverage: float = Field(ge=0.0, le=1.0)
    issues_found: list[ValidationIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PlannedSubGoal(BaseModel):
    """A sub-goal identified during planning."""

    goal_statement: str = Field(min_length=10)
    mode: str  # NodeMode value as string for flexibility
    rationale: str = Field(description="Why this sub-goal is needed")
    # Accept both string (simple) and dict (detailed) formats from LLM
    acceptance_criteria: list[str | dict[str, Any]] = Field(default_factory=list)
    depends_on: list[int] = Field(
        default_factory=list,
        description="Indices of other sub-goals this depends on",
    )
    estimated_complexity: str = Field(
        default="medium",
        description="low, medium, high - affects budget allocation",
    )


class PlanOutput(BaseModel):
    """Output from planning nodes."""

    type: str = "plan"
    sub_goals: list[PlannedSubGoal] = Field(default_factory=list)
    decomposition_rationale: str = Field(
        default="",
        description="Why the goal was decomposed this way",
    )
    execution_order: list[int] = Field(
        default_factory=list,
        description="Suggested order of sub-goal execution (indices)",
    )
    # Accept both simple list[int] and detailed dict formats from LLM
    parallel_groups: list[list[int] | dict[str, Any]] = Field(
        default_factory=list,
        description="Groups of sub-goals that can run in parallel",
    )
    # Accept both simple list[int] and detailed dict formats from LLM
    critical_path: list[int] | dict[str, Any] = Field(
        default_factory=list,
        description="Indices of sub-goals on the critical path",
    )


Output = KnowledgeOutput | ArtifactOutput | CommitmentOutput | ValidationOutput | PlanOutput


class WorkNode(BaseModel):
    """The fundamental unit of work in GOTN."""

    id: str = Field(default_factory=lambda: generate_id("node"))
    depth: int = Field(default=0, ge=0)

    # Intent Layer
    mode: NodeMode
    goal: Goal
    parent: Optional[str] = None
    production_anchor: Optional[str] = None

    # Work Layer
    deliverable_type: DeliverableType
    budget: Budget = Field(default_factory=Budget)
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)

    # Evidence Layer
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: AggregatedConfidence = Field(default_factory=AggregatedConfidence)

    # Control Layer
    autonomy_gate: AutonomyGate = Field(default_factory=AutonomyGate)
    exit_policy: ExitPolicy = Field(default_factory=ExitPolicy)
    status: NodeStatus = NodeStatus.PENDING
    escalation_context: Optional[EscalationContext] = None

    # Graph Layer
    edges: list[TypedEdge] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)

    # Outputs
    outputs: list[Output] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_yaml(self) -> str:
        """Serialize to YAML."""
        return yaml.dump(
            self.model_dump(mode="json", exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

    @classmethod
    def from_yaml(cls, content: str) -> "WorkNode":
        """Deserialize from YAML."""
        data = yaml.safe_load(content)
        return cls.model_validate(data)

    def save(self, store_path: Path) -> None:
        """Save node to YAML file."""
        path = store_path / "nodes" / f"{self.id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml())

    @classmethod
    def load(cls, store_path: Path, node_id: str) -> "WorkNode":
        """Load node from YAML file."""
        path = store_path / "nodes" / f"{node_id}.yaml"
        return cls.from_yaml(path.read_text())

    def get_dependencies(self) -> list[str]:
        """Get IDs of nodes this depends on."""
        return [e.target for e in self.edges if e.type == EdgeType.DEPENDS_ON]

    def get_blockers(self) -> list[str]:
        """Get IDs of nodes that could block this."""
        return [e.target for e in self.edges if e.type == EdgeType.BLOCKS]

    @classmethod
    def create_root(
        cls,
        goal_statement: str,
        mode: NodeMode = NodeMode.EPISTEMIC,
        criteria: Optional[list[dict]] = None,
    ) -> "WorkNode":
        """Create a root node for a new goal tree."""
        if criteria is None:
            criteria = [
                {
                    "description": "Goal achieved with sufficient confidence",
                    "type": CriterionType.KNOWLEDGE,
                    "must_pass": True,
                }
            ]

        deliverable_map = {
            NodeMode.PLANNING: DeliverableType.PLAN,
            NodeMode.EPISTEMIC: DeliverableType.KNOWLEDGE,
            NodeMode.INSTRUMENTAL: DeliverableType.ARTIFACT,
            NodeMode.DECISION: DeliverableType.COMMITMENT,
            NodeMode.VALIDATION: DeliverableType.VERIFICATION,
        }

        return cls(
            mode=mode,
            goal=Goal(
                statement=goal_statement,
                acceptance_criteria=[Criterion(**c) for c in criteria],
            ),
            deliverable_type=deliverable_map[mode],
            status=NodeStatus.READY,  # Root starts ready
        )
