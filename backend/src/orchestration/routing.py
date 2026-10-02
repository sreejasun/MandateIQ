"""
MandateIQ deterministic routing engine.

Owner: Narahari

This module evaluates WorkflowState and determines the next workflow
stage using deterministic routing gates.

The Adaptive Supervisor can later provide reasoning for ambiguous
situations, but hard routing conditions remain deterministic.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from config.settings import MandateIQSettings, load_settings
from src.orchestration.state import WorkflowState


# ============================================================
# ROUTES
# ============================================================

class Route(str, Enum):
    """
    Valid destinations in the MandateIQ workflow.
    """

    DATA_REMEDIATION = "data_remediation"
    PROPONENT = "proponent"
    CHALLENGER = "challenger"
    POLICY_REVIEW = "policy_review"
    VERIFY_CLAIMS = "verify_claims"
    REANALYSIS = "reanalysis"
    MORE_EVIDENCE = "more_evidence"
    HUMAN_REVIEW = "human_review"
    FINALIZE = "finalize"


# ============================================================
# ROUTING REASON CODES
# ============================================================

class RouteReason(str, Enum):
    """
    Stable reason codes used for workflow auditing.
    """

    QUALITY_BELOW_THRESHOLD = "QUALITY_BELOW_THRESHOLD"

    PROPONENT_REQUIRED = "PROPONENT_REQUIRED"
    CHALLENGER_REQUIRED = "CHALLENGER_REQUIRED"
    POLICY_REVIEW_REQUIRED = "POLICY_REVIEW_REQUIRED"

    CLAIM_VERIFICATION_REQUIRED = "CLAIM_VERIFICATION_REQUIRED"

    CRITICAL_POLICY_FAILURE = "CRITICAL_POLICY_FAILURE"
    FIREWALL_FAILURE = "FIREWALL_FAILURE"
    MISSING_REQUIRED_EVIDENCE = "MISSING_REQUIRED_EVIDENCE"

    MATERIAL_DISAGREEMENT = "MATERIAL_DISAGREEMENT"
    RETRY_LIMIT_REACHED = "RETRY_LIMIT_REACHED"

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LOW_TRUST = "LOW_TRUST"

    HUMAN_REVIEW_ALREADY_REQUIRED = "HUMAN_REVIEW_ALREADY_REQUIRED"

    READY_TO_FINALIZE = "READY_TO_FINALIZE"


# ============================================================
# ROUTING CONFIGURATION
# ============================================================

class RoutingConfig(BaseModel):
    """
    Configuration used by deterministic routing gates.

    These values can later be loaded from project configuration
    instead of being scattered throughout routing logic.
    """

    quality_threshold: float = 0.80
    confidence_threshold: float = 0.70
    trust_threshold: float = 70.0
    max_retries: int = 1


def routing_config_from_settings(
    settings: MandateIQSettings | None = None,
) -> RoutingConfig:
    """
    Build RoutingConfig from centralized MandateIQ settings.
    """

    settings = settings or load_settings()

    return RoutingConfig(
        quality_threshold=settings.quality_threshold,
        confidence_threshold=settings.confidence_threshold,
        trust_threshold=settings.trust_threshold,
        max_retries=settings.max_retries,
    )


# ============================================================
# ROUTE DECISION
# ============================================================

class RouteDecision(BaseModel):
    """
    Structured output produced by the routing engine.
    """

    route: Route
    reason_code: RouteReason
    reason: str


# ============================================================
# ROUTING HELPERS
# ============================================================

def has_critical_policy_failure(
    state: WorkflowState,
) -> bool:
    """
    Determine whether the policy module reported a critical failure.

    The policy module is owned by another MandateIQ component, so this
    helper reads the agreed structured result without implementing the
    policy rules themselves.
    """

    if state.policy_result is None:
        return False

    return bool(
        state.policy_result.get(
            "has_critical_failure",
            False,
        )
    )


def has_missing_required_evidence(
    state: WorkflowState,
) -> bool:
    """
    Determine whether required evidence is reported as missing.
    """

    if state.policy_result:
        if state.policy_result.get(
            "missing_required_evidence",
            False,
        ):
            return True

    # Agents also list nice-to-have data (e.g. benchmark_comparison) as
    # missing; only gaps in the required evidence fields block the case.
    required = _required_evidence_names()

    for result in (state.proponent_result, state.challenger_result):
        if not result:
            continue
        missing = result.get("missing_evidence") or []
        if any(_normalize_field(m) in required for m in missing):
            return True

    return False


def _normalize_field(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _required_evidence_names() -> set[str]:
    """Required evidence fields plus their accepted aliases (config/rules.yaml)."""

    from src import config_loader

    cfg = config_loader.rules()
    aliases = cfg.get("field_aliases") or {}
    names: set[str] = set()
    for field in cfg.get("required_evidence") or []:
        names.add(_normalize_field(field))
        names.update(_normalize_field(a) for a in aliases.get(field) or [])
    return names


def has_material_disagreement(
    state: WorkflowState,
) -> bool:
    """
    Determine whether an unresolved material disagreement exists.

    Governance may preserve resolved or non-material disagreements
    in WorkflowState for auditability. Only disagreements explicitly
    marked as material and unresolved should trigger re-analysis.

    Legacy disagreement records that do not expose the newer
    material/resolved fields are conservatively treated as material
    to preserve backward compatibility.
    """

    for disagreement in state.disagreements:

        # Defensive handling for unexpected or legacy records.
        if not isinstance(
            disagreement,
            dict,
        ):
            return True

        material = disagreement.get(
            "material"
        )

        resolved = disagreement.get(
            "resolved",
            False,
        )

        # ----------------------------------------------------
        # Agents v2 / governance conflict contract
        # ----------------------------------------------------
        #
        # A disagreement should cause re-analysis only when it
        # is explicitly material and remains unresolved.
        # ----------------------------------------------------

        if material is not None:

            if (
                bool(material)
                and not bool(resolved)
            ):
                return True

            # Explicitly non-material or already resolved.
            continue

        # ----------------------------------------------------
        # Legacy disagreement contract
        # ----------------------------------------------------
        #
        # Older disagreement records did not contain a
        # `material` field. Preserve the original conservative
        # routing behavior for those records.
        # ----------------------------------------------------

        return True

    return False


def minimum_agent_confidence(
    state: WorkflowState,
) -> float | None:
    """
    Return the lowest available reasoning-agent confidence.

    Returns None when no confidence values are available.
    """

    if not state.agent_confidences:
        return None

    return min(
        state.agent_confidences.values()
    )


# ============================================================
# MAIN ROUTER
# ============================================================

def choose_next_route(
    state: WorkflowState,
    config: RoutingConfig | None = None,
) -> RouteDecision:
    """
    Determine the next MandateIQ workflow stage.

    Routing precedence intentionally handles hard safety/governance
    conditions before ordinary workflow progression.
    """

    config = (
        config
        or routing_config_from_settings()
    )

    # --------------------------------------------------------
    # 1. Existing human-review requirement
    # --------------------------------------------------------

    if state.human_review_required:
        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.HUMAN_REVIEW_ALREADY_REQUIRED
            ),
            reason=(
                "The case has already been marked "
                "for human review."
            ),
        )

    # --------------------------------------------------------
    # 2. Data quality gate
    # --------------------------------------------------------

    if (
        state.quality_score
        < config.quality_threshold
    ):
        return RouteDecision(
            route=Route.DATA_REMEDIATION,
            reason_code=(
                RouteReason.QUALITY_BELOW_THRESHOLD
            ),
            reason=(
                f"Data quality score "
                f"{state.quality_score:.2f} is below "
                f"the configured threshold "
                f"{config.quality_threshold:.2f}."
            ),
        )

    # --------------------------------------------------------
    # 3. Required workflow stages
    # --------------------------------------------------------

    if state.proponent_result is None:
        return RouteDecision(
            route=Route.PROPONENT,
            reason_code=(
                RouteReason.PROPONENT_REQUIRED
            ),
            reason=(
                "The Proponent review has not yet "
                "been completed."
            ),
        )

    if state.challenger_result is None:
        return RouteDecision(
            route=Route.CHALLENGER,
            reason_code=(
                RouteReason.CHALLENGER_REQUIRED
            ),
            reason=(
                "The Challenger review has not yet "
                "been completed."
            ),
        )

    if state.policy_result is None:
        return RouteDecision(
            route=Route.POLICY_REVIEW,
            reason_code=(
                RouteReason.POLICY_REVIEW_REQUIRED
            ),
            reason=(
                "Policy, cost, and suitability "
                "review is required."
            ),
        )

    # --------------------------------------------------------
    # 4. Hard policy gate
    # --------------------------------------------------------

    if has_critical_policy_failure(
        state
    ):
        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.CRITICAL_POLICY_FAILURE
            ),
            reason=(
                "A critical deterministic policy "
                "rule failed."
            ),
        )

    # --------------------------------------------------------
    # 5. Missing evidence gate
    # --------------------------------------------------------

    if has_missing_required_evidence(
        state
    ):
        return RouteDecision(
            route=Route.MORE_EVIDENCE,
            reason_code=(
                RouteReason.MISSING_REQUIRED_EVIDENCE
            ),
            reason=(
                "Required evidence is missing "
                "and must be resolved."
            ),
        )

    # --------------------------------------------------------
    # 6. Claim verification / firewall stage
    # --------------------------------------------------------

    if state.firewall_status is None:
        return RouteDecision(
            route=Route.VERIFY_CLAIMS,
            reason_code=(
                RouteReason.CLAIM_VERIFICATION_REQUIRED
            ),
            reason=(
                "Agent claims must pass "
                "evidence verification."
            ),
        )

    if (
        state.firewall_status.upper()
        == "FAIL"
    ):
        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.FIREWALL_FAILURE
            ),
            reason=(
                "The Hallucination Firewall reported "
                "a failed verification."
            ),
        )

    # --------------------------------------------------------
    # 7. Material disagreement / bounded re-analysis
    # --------------------------------------------------------

    if has_material_disagreement(
        state
    ):

        if (
            state.retry_count
            < config.max_retries
        ):
            return RouteDecision(
                route=Route.REANALYSIS,
                reason_code=(
                    RouteReason.MATERIAL_DISAGREEMENT
                ),
                reason=(
                    "An unresolved material disagreement "
                    "exists and the configured retry limit "
                    "has not been reached."
                ),
            )

        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.RETRY_LIMIT_REACHED
            ),
            reason=(
                "Material disagreement remains "
                "unresolved after the configured "
                "re-analysis limit."
            ),
        )

    # --------------------------------------------------------
    # 8. Confidence gate
    # --------------------------------------------------------

    min_confidence = (
        minimum_agent_confidence(
            state
        )
    )

    if (
        min_confidence is not None
        and min_confidence
        < config.confidence_threshold
    ):
        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.LOW_CONFIDENCE
            ),
            reason=(
                f"Minimum agent confidence "
                f"{min_confidence:.2f} is below "
                f"the configured threshold "
                f"{config.confidence_threshold:.2f}."
            ),
        )

    # --------------------------------------------------------
    # 9. Trust Score gate
    # --------------------------------------------------------

    if (
        state.trust_score is not None
        and state.trust_score
        < config.trust_threshold
    ):
        return RouteDecision(
            route=Route.HUMAN_REVIEW,
            reason_code=(
                RouteReason.LOW_TRUST
            ),
            reason=(
                f"Trust Score "
                f"{state.trust_score:.2f} is below "
                f"the configured threshold "
                f"{config.trust_threshold:.2f}."
            ),
        )

    # --------------------------------------------------------
    # 10. Finalization
    # --------------------------------------------------------

    return RouteDecision(
        route=Route.FINALIZE,
        reason_code=(
            RouteReason.READY_TO_FINALIZE
        ),
        reason=(
            "Required reviews and verification "
            "completed with no configured condition "
            "requiring another route."
        ),
    )