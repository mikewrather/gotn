"""Three-tier context management with VoI-gated retrieval.

Implements the context strategy from architecture.md:
- Tier 1 (Eager): Always stuffed - goal chain, capsule, parent contract (~5-8%)
- Tier 2 (Query): Pre-fetched based on VoI - ancestors, siblings, claims
- Tier 3 (Lazy): External fetch - deferred to Claude's native tools

This module pre-fetches Tier 2 data before Claude execution, eliminating the need
for runtime queries that would require Bash access.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from gotn.node import Claim, Evidence, NodeMode, WorkNode


# Token budget defaults (chars * 0.25 ≈ tokens)
DEFAULT_TOTAL_BUDGET = 8000  # Conservative default for context
TIER1_RATIO = 0.08  # 8% for goal chain, capsule, constraints
TIER2_RATIO = 0.20  # 20% for ancestors, siblings, claims
WORK_RATIO = 0.60   # 60% for working memory (Claude's reasoning)
RESERVE_RATIO = 0.12  # 12% for output buffer


@dataclass
class ContextBudget:
    """Token budget allocation across context tiers.

    Tracks token usage and enforces limits to prevent context overflow
    at deep tree depths.
    """

    total_tokens: int = DEFAULT_TOTAL_BUDGET
    tier1_budget: int = field(init=False)
    tier2_budget: int = field(init=False)
    work_budget: int = field(init=False)
    reserve_budget: int = field(init=False)

    # Usage tracking
    tier1_used: int = 0
    tier2_used: int = 0

    def __post_init__(self):
        self.tier1_budget = int(self.total_tokens * TIER1_RATIO)
        self.tier2_budget = int(self.total_tokens * TIER2_RATIO)
        self.work_budget = int(self.total_tokens * WORK_RATIO)
        self.reserve_budget = int(self.total_tokens * RESERVE_RATIO)

    @property
    def tier1_remaining(self) -> int:
        return max(0, self.tier1_budget - self.tier1_used)

    @property
    def tier2_remaining(self) -> int:
        return max(0, self.tier2_budget - self.tier2_used)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text (rough: ~4 chars per token)."""
        return len(text) // 4

    def can_fit_tier1(self, text: str) -> bool:
        """Check if text fits in remaining Tier 1 budget."""
        return self.estimate_tokens(text) <= self.tier1_remaining

    def can_fit_tier2(self, text: str) -> bool:
        """Check if text fits in remaining Tier 2 budget."""
        return self.estimate_tokens(text) <= self.tier2_remaining

    def add_tier1(self, text: str) -> bool:
        """Add text to Tier 1 if it fits. Returns success."""
        tokens = self.estimate_tokens(text)
        if tokens <= self.tier1_remaining:
            self.tier1_used += tokens
            return True
        return False

    def add_tier2(self, text: str) -> bool:
        """Add text to Tier 2 if it fits. Returns success."""
        tokens = self.estimate_tokens(text)
        if tokens <= self.tier2_remaining:
            self.tier2_used += tokens
            return True
        return False


@dataclass
class VoIFactors:
    """Factors for calculating Value of Information.

    VoI = (uncertainty × decision_impact) / query_cost
    """

    uncertainty: float = 0.5  # 0-1, how uncertain is current state
    decision_impact: float = 0.5  # 0-1, how much does this affect outcomes
    query_cost: float = 1.0  # Relative cost of the query (tokens)

    @property
    def value(self) -> float:
        """Calculate VoI score."""
        if self.query_cost <= 0:
            return 0.0
        return (self.uncertainty * self.decision_impact) / self.query_cost


# VoI threshold for Tier 2 queries
VOI_THRESHOLD = 0.3


@dataclass
class GoalChainEntry:
    """Compressed entry in the goal chain."""

    goal: str
    depth: int
    mode: str
    confidence: float
    constraints: list[str] = field(default_factory=list)


@dataclass
class GoalCapsule:
    """Immutable goal anchor passed to all descendants.

    Contains the root goal and constraints that must be preserved
    throughout the tree execution.
    """

    root_goal: str
    success_criteria: list[str]
    constraints: list[str]
    checksum: str = ""  # SHA256 for tamper detection

    def compute_checksum(self) -> str:
        """Compute checksum of capsule contents."""
        import hashlib
        content = f"{self.root_goal}|{'|'.join(self.success_criteria)}|{'|'.join(self.constraints)}"
        return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    def __post_init__(self):
        if not self.checksum:
            self.checksum = self.compute_checksum()


@dataclass
class Tier2Context:
    """Pre-fetched Tier 2 context data."""

    ancestor_chain: list[GoalChainEntry] = field(default_factory=list)
    sibling_claims: list[Claim] = field(default_factory=list)
    related_evidence: list[Evidence] = field(default_factory=list)
    domain_claims: list[Claim] = field(default_factory=list)


@dataclass
class BuiltContext:
    """Complete built context for node execution."""

    # Tier 1: Always included
    goal_capsule: Optional[GoalCapsule] = None
    goal_chain: list[GoalChainEntry] = field(default_factory=list)
    parent_contract: Optional[str] = None
    constraints: list[str] = field(default_factory=list)

    # Tier 2: VoI-gated, pre-fetched
    tier2: Tier2Context = field(default_factory=Tier2Context)

    # Metadata
    budget: ContextBudget = field(default_factory=ContextBudget)
    voi_scores: dict[str, float] = field(default_factory=dict)

    def to_prompt_section(self) -> str:
        """Render context as a prompt section."""
        sections = []

        # Goal Capsule (if present)
        if self.goal_capsule:
            sections.append(f"""## Root Goal (Immutable)
{self.goal_capsule.root_goal}

Success Criteria:
{chr(10).join(f'- {c}' for c in self.goal_capsule.success_criteria)}
""")

        # Goal Chain
        if self.goal_chain:
            chain_text = "\n".join(
                f"  {'  ' * e.depth}→ [{e.mode}] {e.goal} ({e.confidence:.0%})"
                for e in self.goal_chain
            )
            sections.append(f"""## Goal Ancestry
{chain_text}
""")

        # Constraints
        if self.constraints:
            sections.append(f"""## Constraints
{chr(10).join(f'- {c}' for c in self.constraints)}
""")

        # Tier 2: Ancestor summaries
        if self.tier2.ancestor_chain:
            ancestor_text = "\n".join(
                f"- [{a.mode}] {a.goal[:80]}{'...' if len(a.goal) > 80 else ''}"
                for a in self.tier2.ancestor_chain
            )
            sections.append(f"""## Ancestor Context
{ancestor_text}
""")

        # Tier 2: Sibling claims
        if self.tier2.sibling_claims:
            claims_text = "\n".join(
                f"- {c.proposition[:100]}{'...' if len(c.proposition) > 100 else ''} ({c.confidence:.0%})"
                for c in self.tier2.sibling_claims[:5]  # Limit to top 5
            )
            sections.append(f"""## Related Claims from Siblings
{claims_text}
""")

        # Tier 2: Domain claims
        if self.tier2.domain_claims:
            domain_text = "\n".join(
                f"- [{c.domain.value}] {c.proposition[:80]}... ({c.confidence:.0%})"
                for c in self.tier2.domain_claims[:5]
            )
            sections.append(f"""## Domain Knowledge
{domain_text}
""")

        return "\n".join(sections)


class ContextBuilder:
    """Builds execution context with VoI-gated Tier 2 pre-fetching.

    This class pre-fetches all context before Claude execution, eliminating
    the need for runtime queries that would require Bash access.
    """

    def __init__(
        self,
        load_node_fn,
        get_ancestors_fn,
        get_siblings_fn,
        get_claims_by_domain_fn=None,
        total_budget: int = DEFAULT_TOTAL_BUDGET,
        voi_threshold: float = VOI_THRESHOLD,
    ):
        """Initialize the context builder.

        Args:
            load_node_fn: Function to load a node by ID
            get_ancestors_fn: Function to get ancestor nodes
            get_siblings_fn: Function to get sibling nodes
            get_claims_by_domain_fn: Optional function to get domain claims
            total_budget: Total token budget for context
            voi_threshold: Minimum VoI score for Tier 2 queries
        """
        self.load_node = load_node_fn
        self.get_ancestors = get_ancestors_fn
        self.get_siblings = get_siblings_fn
        self.get_claims_by_domain = get_claims_by_domain_fn
        self.total_budget = total_budget
        self.voi_threshold = voi_threshold

    def build_context(
        self,
        node: WorkNode,
        root_node: Optional[WorkNode] = None,
    ) -> BuiltContext:
        """Build complete context for a node.

        Args:
            node: The node to build context for
            root_node: Optional root node (fetched if not provided)

        Returns:
            BuiltContext with Tier 1 and VoI-gated Tier 2 data
        """
        budget = ContextBudget(total_tokens=self.total_budget)
        context = BuiltContext(budget=budget)

        # === Tier 1: Always included ===

        # Build goal capsule from root
        if root_node is None:
            ancestors = self.get_ancestors(node.id)
            if ancestors:
                root_node = ancestors[0]
            else:
                root_node = node  # Node is the root

        context.goal_capsule = self._build_capsule(root_node)
        budget.add_tier1(str(context.goal_capsule))

        # Build goal chain (compressed ancestry)
        context.goal_chain = self._build_goal_chain(node, budget)

        # Extract constraints
        context.constraints = self._extract_constraints(node)
        budget.add_tier1("\n".join(context.constraints))

        # Parent contract (if exists)
        if node.parent:
            try:
                parent = self.load_node(node.parent)
                context.parent_contract = self._build_parent_contract(parent)
                budget.add_tier1(context.parent_contract)
            except FileNotFoundError:
                pass

        # === Tier 2: VoI-gated pre-fetch ===

        # Calculate VoI factors for this node
        voi = self._calculate_voi(node)
        context.voi_scores["base"] = voi.value

        # Ancestor summaries (VoI: important for deep nodes)
        ancestor_voi = VoIFactors(
            uncertainty=1 - node.confidence.aggregate,
            decision_impact=0.3 + (node.depth * 0.1),  # More important deeper
            query_cost=0.5,
        )
        context.voi_scores["ancestors"] = ancestor_voi.value

        if ancestor_voi.value >= self.voi_threshold:
            context.tier2.ancestor_chain = self._fetch_ancestor_summaries(
                node, budget
            )

        # Sibling claims (VoI: important for collaborative work)
        sibling_voi = VoIFactors(
            uncertainty=1 - node.confidence.aggregate,
            decision_impact=0.5 if node.mode == NodeMode.DECISION else 0.3,
            query_cost=0.3,
        )
        context.voi_scores["siblings"] = sibling_voi.value

        if sibling_voi.value >= self.voi_threshold:
            context.tier2.sibling_claims = self._fetch_sibling_claims(
                node, budget
            )

        # Domain claims (VoI: important for epistemic nodes)
        if self.get_claims_by_domain and node.mode == NodeMode.EPISTEMIC:
            domain_voi = VoIFactors(
                uncertainty=1 - node.confidence.aggregate,
                decision_impact=0.6,  # High for research
                query_cost=0.4,
            )
            context.voi_scores["domain"] = domain_voi.value

            if domain_voi.value >= self.voi_threshold:
                context.tier2.domain_claims = self._fetch_domain_claims(
                    node, budget
                )

        return context

    def _build_capsule(self, root: WorkNode) -> GoalCapsule:
        """Build goal capsule from root node."""
        success_criteria = [
            c.description for c in root.goal.acceptance_criteria
            if c.must_pass
        ]
        constraints = self._extract_constraints(root)

        return GoalCapsule(
            root_goal=root.goal.statement,
            success_criteria=success_criteria,
            constraints=constraints,
        )

    def _build_goal_chain(
        self,
        node: WorkNode,
        budget: ContextBudget,
    ) -> list[GoalChainEntry]:
        """Build compressed goal chain from ancestors.

        Uses progressive summarization to fit within budget:
        - Recent ancestors: Full goal
        - Older ancestors: Summarized goal (first 50 chars)
        """
        chain = []
        ancestors = self.get_ancestors(node.id)

        # Process ancestors from root to parent
        for i, ancestor in enumerate(ancestors):
            # Decay budget allocation with depth
            chars_allowed = max(50, 200 - (i * 30))

            goal_text = ancestor.goal.statement
            if len(goal_text) > chars_allowed:
                goal_text = goal_text[:chars_allowed-3] + "..."

            entry = GoalChainEntry(
                goal=goal_text,
                depth=ancestor.depth,
                mode=ancestor.mode.value,
                confidence=ancestor.confidence.aggregate,
                constraints=[
                    c.description for c in ancestor.goal.acceptance_criteria
                    if c.must_pass
                ],
            )

            entry_text = f"{entry.goal} ({entry.mode})"
            if not budget.can_fit_tier1(entry_text):
                break  # Budget exhausted

            budget.add_tier1(entry_text)
            chain.append(entry)

        return chain

    def _extract_constraints(self, node: WorkNode) -> list[str]:
        """Extract constraints from node criteria."""
        return [
            c.description
            for c in node.goal.acceptance_criteria
            if c.must_pass
        ]

    def _build_parent_contract(self, parent: WorkNode) -> str:
        """Build parent contract summary."""
        criteria = [c.description for c in parent.goal.acceptance_criteria]
        return f"Parent expects: {'; '.join(criteria[:3])}"

    def _calculate_voi(self, node: WorkNode) -> VoIFactors:
        """Calculate base VoI factors for a node."""
        # Uncertainty: inverse of confidence
        uncertainty = 1 - node.confidence.aggregate

        # Decision impact: higher for decision/validation modes
        impact_by_mode = {
            NodeMode.DECISION: 0.9,
            NodeMode.VALIDATION: 0.8,
            NodeMode.INSTRUMENTAL: 0.6,
            NodeMode.EPISTEMIC: 0.4,
        }
        decision_impact = impact_by_mode.get(node.mode, 0.5)

        # Query cost: increases with depth (more context to process)
        query_cost = 1.0 + (node.depth * 0.1)

        return VoIFactors(
            uncertainty=uncertainty,
            decision_impact=decision_impact,
            query_cost=query_cost,
        )

    def _fetch_ancestor_summaries(
        self,
        node: WorkNode,
        budget: ContextBudget,
    ) -> list[GoalChainEntry]:
        """Fetch ancestor summaries for Tier 2."""
        summaries = []
        ancestors = self.get_ancestors(node.id)

        for ancestor in ancestors:
            # Compressed summary
            entry = GoalChainEntry(
                goal=ancestor.goal.statement[:100],
                depth=ancestor.depth,
                mode=ancestor.mode.value,
                confidence=ancestor.confidence.aggregate,
            )

            entry_text = str(entry)
            if not budget.can_fit_tier2(entry_text):
                break

            budget.add_tier2(entry_text)
            summaries.append(entry)

        return summaries

    def _fetch_sibling_claims(
        self,
        node: WorkNode,
        budget: ContextBudget,
    ) -> list[Claim]:
        """Fetch claims from sibling nodes."""
        claims = []
        siblings = self.get_siblings(node.id)

        for sibling in siblings:
            for claim in sibling.claims:
                claim_text = f"{claim.proposition} ({claim.confidence})"
                if not budget.can_fit_tier2(claim_text):
                    return claims  # Budget exhausted

                budget.add_tier2(claim_text)
                claims.append(claim)

        # Sort by confidence, return top claims
        claims.sort(key=lambda c: c.confidence, reverse=True)
        return claims[:10]  # Limit to top 10

    def _fetch_domain_claims(
        self,
        node: WorkNode,
        budget: ContextBudget,
    ) -> list[Claim]:
        """Fetch claims from same domain."""
        if not self.get_claims_by_domain:
            return []

        # Get claims matching node's domain
        domain = node.claims[0].domain if node.claims else None
        if not domain:
            return []

        all_claims = self.get_claims_by_domain(domain)
        claims = []

        for claim in all_claims:
            claim_text = f"[{claim.domain}] {claim.proposition}"
            if not budget.can_fit_tier2(claim_text):
                break

            budget.add_tier2(claim_text)
            claims.append(claim)

        return claims[:10]


def build_execution_context(
    node: WorkNode,
    state_manager,
    total_budget: int = DEFAULT_TOTAL_BUDGET,
) -> BuiltContext:
    """Convenience function to build context using StateManager.

    Args:
        node: Node to build context for
        state_manager: StateManager instance
        total_budget: Token budget for context

    Returns:
        Built context ready for execution
    """
    def get_siblings(node_id: str) -> list[WorkNode]:
        """Get sibling nodes (same parent)."""
        try:
            node = state_manager.load_node(node_id)
            if not node.parent:
                return []
            parent = state_manager.load_node(node.parent)
            siblings = []
            for child_id in parent.children:
                if child_id != node_id:
                    try:
                        siblings.append(state_manager.load_node(child_id))
                    except FileNotFoundError:
                        pass
            return siblings
        except FileNotFoundError:
            return []

    builder = ContextBuilder(
        load_node_fn=state_manager.load_node,
        get_ancestors_fn=lambda nid: state_manager.get_ancestors(
            state_manager.load_node(nid)
        ),
        get_siblings_fn=get_siblings,
        total_budget=total_budget,
    )

    return builder.build_context(node)
