from config.settings import MandateIQSettings

from src.orchestration.routing import (
    Route,
    RouteReason,
    RoutingConfig,
    choose_next_route,
    routing_config_from_settings,
)
from src.orchestration.state import WorkflowState


# ============================================================
# TEST FIXTURE
# ============================================================

def completed_state(**overrides):
    """
    Create a workflow state where all normal review stages
    have completed successfully.

    Individual tests override only the condition they need.
    """

    data = {
        "case_id": "CASE-TEST",
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
# DATA QUALITY ROUTING
# ============================================================

def test_low_quality_routes_to_data_remediation():
    state = WorkflowState(
        case_id="CASE-QUALITY",
        quality_score=0.50,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.DATA_REMEDIATION

    assert (
        decision.reason_code
        == RouteReason.QUALITY_BELOW_THRESHOLD
    )


# ============================================================
# REQUIRED WORKFLOW STAGES
# ============================================================

def test_missing_proponent_routes_to_proponent():
    state = WorkflowState(
        case_id="CASE-PROPONENT",
        quality_score=0.95,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.PROPONENT

    assert (
        decision.reason_code
        == RouteReason.PROPONENT_REQUIRED
    )


def test_missing_challenger_routes_to_challenger():
    state = WorkflowState(
        case_id="CASE-CHALLENGER",
        quality_score=0.95,
        proponent_result={
            "position": "SUPPORT",
            "missing_evidence": [],
        },
    )

    decision = choose_next_route(state)

    assert decision.route == Route.CHALLENGER

    assert (
        decision.reason_code
        == RouteReason.CHALLENGER_REQUIRED
    )


def test_missing_policy_routes_to_policy_review():
    state = WorkflowState(
        case_id="CASE-POLICY",
        quality_score=0.95,
        proponent_result={
            "position": "SUPPORT",
            "missing_evidence": [],
        },
        challenger_result={
            "position": "SUPPORT",
            "missing_evidence": [],
        },
    )

    decision = choose_next_route(state)

    assert decision.route == Route.POLICY_REVIEW

    assert (
        decision.reason_code
        == RouteReason.POLICY_REVIEW_REQUIRED
    )


# ============================================================
# POLICY / EVIDENCE ROUTING
# ============================================================

def test_critical_policy_failure_routes_to_human_review():
    state = completed_state(
        policy_result={
            "has_critical_failure": True,
            "missing_required_evidence": False,
        }
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.CRITICAL_POLICY_FAILURE
    )


def test_optional_missing_evidence_does_not_block_finalize():
    state = completed_state(
        proponent_result={
            "missing_evidence": ["performance_metrics", "benchmark_comparison"],
        },
        challenger_result={
            "position": "CHALLENGE",
            "missing_evidence": ["manager_tenure"],
        },
    )

    assert choose_next_route(state).route == Route.FINALIZE


def test_missing_evidence_routes_to_more_evidence():
    state = completed_state(
        challenger_result={
            "position": "CHALLENGE",
            "missing_evidence": [
                "Track record years",
            ],
        }
    )

    decision = choose_next_route(state)

    assert decision.route == Route.MORE_EVIDENCE

    assert (
        decision.reason_code
        == RouteReason.MISSING_REQUIRED_EVIDENCE
    )


# ============================================================
# CLAIM VERIFICATION / FIREWALL
# ============================================================

def test_unverified_claims_route_to_verification():
    state = completed_state(
        firewall_status=None,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.VERIFY_CLAIMS

    assert (
        decision.reason_code
        == RouteReason.CLAIM_VERIFICATION_REQUIRED
    )


def test_firewall_failure_routes_to_human_review():
    state = completed_state(
        firewall_status="FAIL",
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.FIREWALL_FAILURE
    )


# ============================================================
# DISAGREEMENT / REANALYSIS
# ============================================================

def test_material_disagreement_routes_to_reanalysis():
    state = completed_state(
        disagreements=[
            {
                "claim_id": "PROP-03",
                "reason": "Material evidence conflict",
            }
        ],
        retry_count=0,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.REANALYSIS

    assert (
        decision.reason_code
        == RouteReason.MATERIAL_DISAGREEMENT
    )


def test_retry_limit_routes_disagreement_to_human_review():
    state = completed_state(
        disagreements=[
            {
                "claim_id": "PROP-03",
                "reason": "Unresolved conflict",
            }
        ],
        retry_count=1,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.RETRY_LIMIT_REACHED
    )


# ============================================================
# CONFIDENCE / TRUST ROUTING
# ============================================================

def test_low_confidence_routes_to_human_review():
    state = completed_state(
        agent_confidences={
            "proponent": 0.90,
            "challenger": 0.55,
            "policy": 0.91,
        }
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.LOW_CONFIDENCE
    )


def test_low_trust_routes_to_human_review():
    state = completed_state(
        trust_score=60.0,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.LOW_TRUST
    )


# ============================================================
# EXISTING HUMAN REVIEW
# ============================================================

def test_existing_human_review_flag_has_priority():
    state = completed_state(
        human_review_required=True,
        human_review_reason="Previously escalated.",
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.HUMAN_REVIEW_ALREADY_REQUIRED
    )


# ============================================================
# FINALIZATION
# ============================================================

def test_clean_case_routes_to_finalize():
    state = completed_state()

    decision = choose_next_route(state)

    assert decision.route == Route.FINALIZE

    assert (
        decision.reason_code
        == RouteReason.READY_TO_FINALIZE
    )


# ============================================================
# EXPLICIT ROUTING CONFIGURATION
# ============================================================

def test_custom_configuration_changes_route_without_code_change():
    state = completed_state(
        trust_score=75.0,
    )

    default_decision = choose_next_route(state)

    stricter_config = RoutingConfig(
        quality_threshold=0.80,
        confidence_threshold=0.70,
        trust_threshold=80.0,
        max_retries=1,
    )

    stricter_decision = choose_next_route(
        state,
        config=stricter_config,
    )

    assert default_decision.route == Route.FINALIZE

    assert stricter_decision.route == Route.HUMAN_REVIEW

    assert (
        stricter_decision.reason_code
        == RouteReason.LOW_TRUST
    )


# ============================================================
# CENTRALIZED MANDATEIQ SETTINGS
# ============================================================

def test_routing_config_is_created_from_mandateiq_settings():
    """
    Central MandateIQ settings should translate directly into
    the deterministic routing configuration.
    """

    settings = MandateIQSettings(
        quality_threshold=0.91,
        confidence_threshold=0.82,
        trust_threshold=88.0,
        max_retries=3,
    )

    config = routing_config_from_settings(
        settings
    )

    assert config.quality_threshold == 0.91

    assert config.confidence_threshold == 0.82

    assert config.trust_threshold == 88.0

    assert config.max_retries == 3


def test_environment_configuration_changes_default_routing(
    monkeypatch,
):
    """
    Changing environment-backed configuration should change
    routing behavior without changing source code.
    """

    monkeypatch.setenv(
        "TRUST_THRESHOLD",
        "95",
    )

    state = completed_state(
        trust_score=90.0,
    )

    decision = choose_next_route(state)

    assert decision.route == Route.HUMAN_REVIEW

    assert (
        decision.reason_code
        == RouteReason.LOW_TRUST
    )