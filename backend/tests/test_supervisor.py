from src.agents.supervisor import (
    determine_current_stage,
    run_supervisor,
)
from src.orchestration.routing import Route
from src.orchestration.state import WorkflowState


# ============================================================
# TEST FIXTURE
# ============================================================

def completed_state(**overrides):
    """
    Create a clean workflow state where all upstream review stages
    have completed successfully.

    Individual tests can override only the fields needed for the
    scenario being tested.
    """

    data = {
        "case_id": "CASE-SUPERVISOR",
        "quality_score": 0.95,
        "proponent_result": {
            "position": "SUPPORT",
            "missing_evidence": [],
        },
        "challenger_result": {
            "position": "SUPPORT",
            "missing_evidence": [],
        },
        "policy_result": {
            "has_critical_failure": False,
            "missing_required_evidence": False,
        },
        "firewall_status": "PASS",
        "trust_score": 90.0,
        "agent_confidences": {
            "proponent": 0.90,
            "challenger": 0.88,
            "policy": 0.92,
        },
    }

    data.update(overrides)

    return WorkflowState(**data)


# ============================================================
# CURRENT-STAGE TESTS
# ============================================================

def test_determine_current_stage_for_new_case():
    state = WorkflowState(
        case_id="CASE-001"
    )

    assert determine_current_stage(state) == "ingested"


def test_determine_current_stage_after_data_steward():
    state = WorkflowState(
        case_id="CASE-002",
        quality_score=0.95,
    )

    assert determine_current_stage(state) == "data_steward"


# ============================================================
# DATA QUALITY ROUTING
# ============================================================

def test_supervisor_routes_low_quality_to_remediation():
    state = WorkflowState(
        case_id="CASE-QUALITY",
        quality_score=0.50,
    )

    result = run_supervisor(state)

    assert result.route == Route.DATA_REMEDIATION

    assert len(state.route_history) == 1

    record = state.route_history[0]

    assert record.from_stage == "data_steward"

    assert record.to_stage == "data_remediation"

    assert record.reason_code == "QUALITY_BELOW_THRESHOLD"


# ============================================================
# REANALYSIS TESTS
# ============================================================

def test_supervisor_routes_material_disagreement_to_reanalysis():
    state = completed_state(
        disagreements=[
            {
                "claim_id": "PROP-03",
                "reason": "Material conflict",
            }
        ],
        retry_count=0,
    )

    result = run_supervisor(state)

    assert result.route == Route.REANALYSIS

    assert state.retry_count == 1

    assert len(state.route_history) == 1

    assert state.route_history[0].to_stage == "reanalysis"


def test_supervisor_escalates_after_retry_limit():
    state = completed_state(
        disagreements=[
            {
                "claim_id": "PROP-03",
                "reason": "Unresolved material conflict",
            }
        ],
        retry_count=1,
    )

    result = run_supervisor(state)

    assert result.route == Route.HUMAN_REVIEW

    assert state.human_review_required is True

    assert state.human_review_reason is not None

    assert state.route_history[-1].to_stage == "human_review"


# ============================================================
# POLICY / FIREWALL ESCALATION
# ============================================================

def test_supervisor_escalates_critical_policy_failure():
    state = completed_state(
        policy_result={
            "has_critical_failure": True,
            "missing_required_evidence": False,
        }
    )

    result = run_supervisor(state)

    assert result.route == Route.HUMAN_REVIEW

    assert state.human_review_required is True

    assert (
        state.route_history[-1].reason_code
        == "CRITICAL_POLICY_FAILURE"
    )


def test_supervisor_escalates_firewall_failure():
    state = completed_state(
        firewall_status="FAIL",
    )

    result = run_supervisor(state)

    assert result.route == Route.HUMAN_REVIEW

    assert state.human_review_required is True

    assert (
        state.route_history[-1].reason_code
        == "FIREWALL_FAILURE"
    )


# ============================================================
# EXISTING HUMAN REVIEW
# ============================================================

def test_supervisor_preserves_existing_human_review_reason():
    """
    If another workflow component has already escalated the case
    with a specific explanation, the Supervisor must not replace
    that explanation with a generic human-review message.
    """

    state = completed_state(
        human_review_required=True,
        human_review_reason=(
            "Re-analysis handler is unavailable."
        ),
    )

    result = run_supervisor(state)

    assert result.route == Route.HUMAN_REVIEW

    assert state.human_review_required is True

    assert state.human_review_reason == (
        "Re-analysis handler is unavailable."
    )

    assert (
        state.route_history[-1].reason_code
        == "HUMAN_REVIEW_ALREADY_REQUIRED"
    )


# ============================================================
# FINALIZATION
# ============================================================

def test_supervisor_routes_clean_case_to_finalize():
    state = completed_state()

    result = run_supervisor(state)

    assert result.route == Route.FINALIZE

    # FINALIZE is a workflow route.
    # It must not automatically imply APPROVE.
    assert state.final_status is None

    assert state.final_rationale is not None

    assert state.route_history[-1].to_stage == "finalize"


# ============================================================
# SUPERVISOR RESULT PERSISTENCE
# ============================================================

def test_supervisor_result_is_stored_in_state():
    state = completed_state()

    result = run_supervisor(state)

    assert state.supervisor_result is not None

    assert (
        state.supervisor_result["route"]
        == result.route.value
    )

    assert (
        state.supervisor_result["reason_code"]
        == result.reason_code
    )


# ============================================================
# MULTI-STEP ROUTING
# ============================================================

def test_supervisor_records_multiple_route_decisions():
    state = WorkflowState(
        case_id="CASE-MULTI",
        quality_score=0.95,
    )

    # First Supervisor cycle
    first = run_supervisor(state)

    assert first.route == Route.PROPONENT

    # Simulate completion of the Proponent stage
    state.proponent_result = {
        "position": "SUPPORT",
        "missing_evidence": [],
    }

    # Second Supervisor cycle
    second = run_supervisor(state)

    assert second.route == Route.CHALLENGER

    assert len(state.route_history) == 2

    assert (
        state.route_history[0].to_stage
        == "proponent"
    )

    assert (
        state.route_history[1].to_stage
        == "challenger"
    )


# ============================================================
# SUPERVISOR METADATA
# ============================================================

def test_supervisor_metadata_contains_routing_context():
    state = completed_state()

    result = run_supervisor(state)

    assert result.metadata["retry_count"] == 0

    assert result.metadata["trust_score"] == 90.0

    assert result.metadata["firewall_status"] == "PASS"

    assert result.metadata["quality_score"] == 0.95

    assert result.metadata["disagreement_count"] == 0

    assert result.metadata["risk_flag_count"] == 0


def test_supervisor_metadata_contains_extended_context():
    state = completed_state(
        risk_flags=[
            {
                "code": "FEE_RISK",
            }
        ]
    )

    result = run_supervisor(state)

    assert (
        result.metadata["current_stage"]
        == "verification"
    )

    assert (
        result.metadata["selected_route"]
        == "finalize"
    )

    assert result.metadata["quality_score"] == 0.95

    assert result.metadata["disagreement_count"] == 0

    assert result.metadata["risk_flag_count"] == 1