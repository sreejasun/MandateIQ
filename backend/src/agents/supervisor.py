"""
MandateIQ Adaptive Supervisor.

Owner: Narahari

The Supervisor coordinates workflow routing by inspecting the shared
WorkflowState, invoking the deterministic routing engine, updating
workflow state, and recording every transition for auditability.

Bedrock-assisted reasoning can be added later for ambiguous situations.
Hard routing gates remain deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.orchestration.routing import (
    Route,
    RouteDecision,
    RoutingConfig,
    choose_next_route,
)
from src.orchestration.state import (
    WorkflowState,
    add_route_record,
)


# ============================================================
# SUPERVISOR RESULT
# ============================================================

class SupervisorResult(BaseModel):
    """
    Structured result produced by the MandateIQ Adaptive Supervisor.

    The result describes the selected workflow route and the reason
    for that route. It does not independently perform policy,
    evidence-verification, Trust Score, or financial calculations.
    """

    route: Route

    reason_code: str

    reason: str

    human_review_required: bool = False

    final_status: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# CURRENT-STAGE DETECTION
# ============================================================

def determine_current_stage(state: WorkflowState) -> str:
    """
    Infer the current logical workflow stage from WorkflowState.

    The inferred stage is primarily used when recording an auditable
    route transition.

    The function does not determine the next route. That responsibility
    belongs to the routing engine.
    """

    if state.final_status is not None:
        return "finalized"

    if state.human_review_required:
        return "human_review"

    if state.firewall_status is not None:
        return "verification"

    if state.policy_result is not None:
        return "policy_review"

    if state.challenger_result is not None:
        return "challenger"

    if state.proponent_result is not None:
        return "proponent"

    if state.quality_report or state.quality_score > 0:
        return "data_steward"

    return "ingested"


# ============================================================
# ROUTE SIDE EFFECTS
# ============================================================

def _apply_route_effects(
    state: WorkflowState,
    decision: RouteDecision,
) -> None:
    """
    Apply orchestration-level state changes associated with a route.

    The Supervisor deliberately does not implement another module's
    business logic.

    Examples:
        HUMAN_REVIEW -> mark the case for human review.
        REANALYSIS   -> increment the bounded retry counter.
        FINALIZE     -> record that the case is ready for final
                        decision consolidation.

    FINALIZE does NOT automatically mean APPROVE. The final business
    status may later be APPROVE, REVIEW, or REJECT depending on the
    verified downstream decision logic.
    """

    if decision.route == Route.HUMAN_REVIEW:
        state.human_review_required = True

        # Preserve the original escalation reason when the case was
        # already marked for human review by the orchestration graph
        # or another workflow component.
        if state.human_review_reason is None:
            state.human_review_reason = decision.reason

    elif decision.route == Route.REANALYSIS:
        state.retry_count += 1

    elif decision.route == Route.FINALIZE:
        state.final_rationale = decision.reason


# ============================================================
# ADAPTIVE SUPERVISOR
# ============================================================

def run_supervisor(
    state: WorkflowState,
    config: RoutingConfig | None = None,
) -> SupervisorResult:
    """
    Execute one MandateIQ Adaptive Supervisor decision cycle.

    Workflow:
        1. Determine the current logical stage.
        2. Evaluate WorkflowState using the routing engine.
        3. Apply orchestration-level route effects.
        4. Record the transition in route history.
        5. Produce a structured SupervisorResult.
        6. Store the result in WorkflowState.

    This function performs one decision cycle only. The orchestration
    graph is responsible for executing the selected downstream node
    and invoking the Supervisor again when appropriate.
    """

    # --------------------------------------------------------
    # Determine where the case currently is
    # --------------------------------------------------------

    current_stage = determine_current_stage(state)

    # --------------------------------------------------------
    # Determine what should happen next
    # --------------------------------------------------------

    decision = choose_next_route(
        state=state,
        config=config,
    )

    # --------------------------------------------------------
    # Apply orchestration-level state changes
    # --------------------------------------------------------

    _apply_route_effects(
        state=state,
        decision=decision,
    )

    # --------------------------------------------------------
    # Record the routing decision for auditability
    # --------------------------------------------------------

    add_route_record(
        state=state,
        from_stage=current_stage,
        to_stage=decision.route.value,
        reason_code=decision.reason_code.value,
        reason=decision.reason,
    )

    # --------------------------------------------------------
    # Build structured Supervisor output
    # --------------------------------------------------------

    result = SupervisorResult(
        route=decision.route,
        reason_code=decision.reason_code.value,
        reason=decision.reason,
        human_review_required=state.human_review_required,
        final_status=state.final_status,
        metadata={
            "current_stage": current_stage,
            "selected_route": decision.route.value,
            "retry_count": state.retry_count,
            "trust_score": state.trust_score,
            "firewall_status": state.firewall_status,
            "quality_score": state.quality_score,
            "disagreement_count": len(state.disagreements),
            "risk_flag_count": len(state.risk_flags),
        },
    )

    # --------------------------------------------------------
    # Persist Supervisor result into shared workflow state
    # --------------------------------------------------------

    state.supervisor_result = result.model_dump(mode="json")

    return result