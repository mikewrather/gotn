"""Confidence aggregation and recency decay logic."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from gotn.node import (
    AggregatedConfidence,
    Claim,
    ClaimDomain,
    Criterion,
    Evidence,
    WorkNode,
)


@dataclass
class ConfidenceResult:
    """Result of confidence computation."""

    aggregate: float
    by_criterion: dict[str, float]
    must_pass_satisfied: bool
    all_satisfied: bool
    weakest_criterion: Optional[str] = None
    weakest_confidence: float = 1.0


def compute_recency_factor(
    timestamp: datetime,
    domain: ClaimDomain,
    reference_time: Optional[datetime] = None,
) -> float:
    """Compute recency decay factor for a claim or evidence.

    Uses exponential decay based on domain-specific half-life.

    Args:
        timestamp: When the claim/evidence was created
        domain: Domain for decay rate lookup
        reference_time: Reference time (defaults to now)

    Returns:
        Factor between 0 and 1, where 1 is fully fresh
    """
    if reference_time is None:
        reference_time = datetime.now()

    age_days = (reference_time - timestamp).total_seconds() / 86400
    half_life = domain.half_life_days

    # Exponential decay: factor = 0.5^(age/half_life)
    return math.pow(0.5, age_days / half_life)


def adjust_claim_confidence(
    claim: Claim,
    reference_time: Optional[datetime] = None,
) -> float:
    """Get time-adjusted confidence for a claim.

    Args:
        claim: The claim to evaluate
        reference_time: Reference time for recency calculation

    Returns:
        Adjusted confidence value
    """
    if claim.expiry and datetime.now() > claim.expiry:
        return 0.0

    base_confidence = claim.confidence

    # Apply recency decay based on domain
    # Note: Claims don't have a timestamp field, so we use expiry as a proxy
    # In practice, you'd add a created_at field to Claim
    if claim.expiry:
        # Estimate age from expiry and domain half-life
        half_life_days = claim.domain.half_life_days
        estimated_creation = claim.expiry - timedelta(days=half_life_days * 2)
        recency = compute_recency_factor(
            estimated_creation, claim.domain, reference_time
        )
        return base_confidence * recency

    return base_confidence


def aggregate_evidence_strength(
    evidence_list: list[Evidence],
    reference_time: Optional[datetime] = None,
) -> float:
    """Aggregate strength across multiple evidence items.

    Uses a weighted combination that accounts for recency and relevance.

    Args:
        evidence_list: List of evidence items
        reference_time: Reference time for recency

    Returns:
        Aggregated strength between 0 and 1
    """
    if not evidence_list:
        return 0.0

    if reference_time is None:
        reference_time = datetime.now()

    total_weight = 0.0
    weighted_sum = 0.0

    for ev in evidence_list:
        # Compute recency factor (evidence uses GENERAL domain by default)
        recency = compute_recency_factor(
            ev.recency, ClaimDomain.GENERAL, reference_time
        )

        # Weight by relevance and recency
        weight = ev.relevance * recency
        weighted_sum += ev.strength * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return weighted_sum / total_weight


def compute_criterion_confidence(
    criterion: Criterion,
    claims: list[Claim],
    evidence: list[Evidence],
    reference_time: Optional[datetime] = None,
) -> float:
    """Compute confidence for a single criterion.

    Combines:
    - Direct criterion confidence
    - Supporting claims (with recency adjustment)
    - Supporting evidence strength

    Args:
        criterion: The criterion to evaluate
        claims: Claims that may support this criterion
        evidence: Evidence items
        reference_time: Reference time for recency

    Returns:
        Confidence value between 0 and 1
    """
    # Start with base criterion confidence
    base = criterion.confidence

    if not criterion.evidence_ids:
        return base

    # Find supporting evidence
    supporting_evidence = [
        ev for ev in evidence if ev.id in criterion.evidence_ids
    ]

    if supporting_evidence:
        evidence_strength = aggregate_evidence_strength(
            supporting_evidence, reference_time
        )
        # Combine: higher of criterion confidence or evidence-backed confidence
        return max(base, evidence_strength)

    return base


def compute_node_confidence(
    node: WorkNode,
    reference_time: Optional[datetime] = None,
) -> ConfidenceResult:
    """Compute aggregated confidence for a node.

    Uses weighted mean with must_pass criteria weighted 2x.

    Args:
        node: The node to evaluate
        reference_time: Reference time for recency calculations

    Returns:
        ConfidenceResult with all computed values
    """
    criteria = node.goal.acceptance_criteria
    if not criteria:
        return ConfidenceResult(
            aggregate=0.0,
            by_criterion={},
            must_pass_satisfied=True,
            all_satisfied=True,
        )

    if reference_time is None:
        reference_time = datetime.now()

    by_criterion: dict[str, float] = {}
    total_weight = 0.0
    weighted_sum = 0.0
    must_pass_satisfied = True
    all_satisfied = True
    weakest_id = None
    weakest_conf = 1.0

    for criterion in criteria:
        # Compute confidence for this criterion
        conf = compute_criterion_confidence(
            criterion, node.claims, node.evidence, reference_time
        )
        by_criterion[criterion.id] = conf

        # Track weakest
        if conf < weakest_conf:
            weakest_conf = conf
            weakest_id = criterion.id

        # Track satisfaction
        if not criterion.satisfied:
            all_satisfied = False
            if criterion.must_pass:
                must_pass_satisfied = False

        # Weighted aggregation
        weight = 2.0 if criterion.must_pass else 1.0
        weighted_sum += conf * weight
        total_weight += weight

    aggregate = weighted_sum / total_weight if total_weight > 0 else 0.0

    return ConfidenceResult(
        aggregate=aggregate,
        by_criterion=by_criterion,
        must_pass_satisfied=must_pass_satisfied,
        all_satisfied=all_satisfied,
        weakest_criterion=weakest_id,
        weakest_confidence=weakest_conf,
    )


def update_node_confidence(node: WorkNode) -> ConfidenceResult:
    """Update a node's aggregated confidence in place.

    Args:
        node: The node to update

    Returns:
        The computed confidence result
    """
    result = compute_node_confidence(node)

    node.confidence = AggregatedConfidence(
        aggregate=result.aggregate,
        by_criterion=result.by_criterion,
        aggregation_method="weighted_mean",
        last_computed=datetime.now(),
    )

    return result


def should_proceed(node: WorkNode) -> tuple[bool, str]:
    """Check if a node meets its autonomy gate threshold.

    Args:
        node: The node to check

    Returns:
        Tuple of (can_proceed, reason)
    """
    result = compute_node_confidence(node)
    gate = node.autonomy_gate

    # Check human required flag
    if gate.human_required:
        return False, "Human review required"

    # Check must-pass criteria
    if not result.must_pass_satisfied:
        failed = [
            c.id for c in node.goal.acceptance_criteria
            if c.must_pass and not c.satisfied
        ]
        return False, f"Must-pass criteria not satisfied: {failed}"

    # Check specific must-pass criteria from gate
    for crit_id in gate.must_pass_criteria:
        conf = result.by_criterion.get(crit_id, 0.0)
        if conf < gate.proceed_threshold:
            return False, f"Required criterion {crit_id} below threshold ({conf:.0%})"

    # Check overall threshold
    if result.aggregate < gate.proceed_threshold:
        return (
            False,
            f"Confidence {result.aggregate:.0%} below threshold {gate.proceed_threshold:.0%}",
        )

    return True, "All criteria met"


def needs_escalation(node: WorkNode) -> tuple[bool, Optional[str]]:
    """Check if a node should escalate to human review.

    Args:
        node: The node to check

    Returns:
        Tuple of (should_escalate, trigger_reason)
    """
    gate = node.autonomy_gate

    # Check explicit triggers
    for trigger in gate.escalation_triggers:
        # Triggers are string patterns to match against node state
        if _matches_trigger(node, trigger):
            return True, trigger

    # Check risk flags
    if gate.risk_flags:
        from gotn.node import RiskFlag

        for flag in gate.risk_flags:
            if flag in (RiskFlag.SAFETY, RiskFlag.LEGAL, RiskFlag.IRREVERSIBLE):
                return True, f"Risk flag: {flag.value}"

    return False, None


def _matches_trigger(node: WorkNode, trigger: str) -> bool:
    """Check if a node state matches an escalation trigger."""
    trigger_lower = trigger.lower()

    # Budget triggers
    if "budget" in trigger_lower and node.budget.exhausted:
        return True

    # Low confidence trigger
    if "low_confidence" in trigger_lower:
        result = compute_node_confidence(node)
        if result.aggregate < 0.3:
            return True

    # Failed criterion trigger
    if "criterion_failed" in trigger_lower:
        for c in node.goal.acceptance_criteria:
            if c.must_pass and not c.satisfied and c.confidence < 0.5:
                return True

    return False


def suggest_next_action(node: WorkNode) -> str:
    """Suggest what to do next based on confidence state.

    Args:
        node: The node to analyze

    Returns:
        Suggested action string
    """
    result = compute_node_confidence(node)
    can_proceed, reason = should_proceed(node)

    if can_proceed:
        return "complete"

    should_escalate, trigger = needs_escalation(node)
    if should_escalate:
        return f"escalate: {trigger}"

    # Check if more research would help
    if result.weakest_confidence < 0.5:
        return f"spawn_research: strengthen {result.weakest_criterion}"

    # Check budget
    if node.budget.exhausted:
        return "degrade: budget exhausted"

    return "continue: gather more evidence"
