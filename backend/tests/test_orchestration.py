import pytest

from config.settings import MandateIQSettings

from src.orchestration.graph import (
    MandateIQGraph,
    WorkflowDependencies,
)
from src.orchestration.routing import (
    Route,
    RoutingConfig,
)
from src.orchestration.state import WorkflowState


# ============================================================
# FAKE SPECIALIST MODULES
# ============================================================

def fake_data_steward(state: WorkflowState) -> WorkflowState:
    """
    Simulate successful Data Steward processing.
    """

    state.quality_score = 0.95

    state.quality_report = {
        "status": "PASS",
    }

    state.data_profile = {
        "rows": 100,
    }

    return state


def fake_proponent(state: WorkflowState) -> WorkflowState:
    """
    Simulate a successful Proponent review.
    """

    state.proponent_result = {
        "position": "SUPPORT",
        "confidence": 0.90,
        "missing_evidence": [],
    }

    state.agent_confidences["proponent"] = 0.90

    return state


def fake_challenger_clean(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate a Challenger with no material disagreement.
    """

    state.challenger_result = {
        "position": "SUPPORT",
        "confidence": 0.88,
        "missing_evidence": [],
    }

    state.agent_confidences["challenger"] = 0.88

    return state


def fake_challenger_conflict(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate a Challenger discovering a material conflict.
    """

    state.challenger_result = {
        "position": "CHALLENGE",
        "confidence": 0.90,
        "missing_evidence": [],
    }

    state.agent_confidences["challenger"] = 0.90

    state.disagreements = [
        {
            "claim_id": "PROP-03",
            "reason": "Material evidence conflict",
        }
    ]

    return state


def fake_policy_pass(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate successful deterministic policy review.
    """

    state.policy_result = {
        "has_critical_failure": False,
        "missing_required_evidence": False,
    }

    state.agent_confidences["policy"] = 0.92

    return state


def fake_policy_failure(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate a critical deterministic policy failure.
    """

    state.policy_result = {
        "has_critical_failure": True,
        "missing_required_evidence": False,
    }

    state.agent_confidences["policy"] = 0.95

    return state


def fake_verify_claims(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate successful Hallucination Firewall verification.
    """

    state.firewall_status = "PASS"

    state.claim_verifications = [
        {
            "claim_id": "PROP-01",
            "status": "VERIFIED",
        }
    ]

    return state


def fake_trust_score(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate successful deterministic Trust Score calculation.
    """

    state.trust_score = 90.0

    state.trust_components = {
        "evidence": 92.0,
        "quality": 95.0,
        "agreement": 85.0,
    }

    return state


def fake_reanalysis_resolves_conflict(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate targeted re-analysis resolving a disagreement.
    """

    state.disagreements = []

    state.challenger_result = {
        "position": "SUPPORT",
        "confidence": 0.86,
        "missing_evidence": [],
    }

    state.agent_confidences["challenger"] = 0.86

    return state


def fake_reanalysis_keeps_conflict(
    state: WorkflowState,
) -> WorkflowState:
    """
    Simulate unsuccessful re-analysis.
    """

    return state


# ============================================================
# DEPENDENCY FACTORY
# ============================================================

def clean_dependencies() -> WorkflowDependencies:
    """
    Build a clean set of fake workflow dependencies.
    """

    return WorkflowDependencies(
        run_data_steward=fake_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_clean,
        run_policy_review=fake_policy_pass,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
        run_reanalysis=fake_reanalysis_resolves_conflict,
    )


# ============================================================
# CASE A - CLEAN FINALIZATION
# ============================================================

def test_clean_case_reaches_finalize():
    graph = MandateIQGraph(
        dependencies=clean_dependencies()
    )

    state = WorkflowState(
        case_id="CASE-A"
    )

    result = graph.run(state)

    assert result.completed is True

    assert result.terminal_route == Route.FINALIZE

    assert result.state.quality_score == 0.95

    assert result.state.proponent_result is not None

    assert result.state.challenger_result is not None

    assert result.state.policy_result is not None

    assert result.state.firewall_status == "PASS"

    assert result.state.trust_score == 90.0

    routes = [
        record.to_stage
        for record in result.state.route_history
    ]

    assert "proponent" in routes
    assert "challenger" in routes
    assert "policy_review" in routes
    assert "verify_claims" in routes
    assert "finalize" in routes


# ============================================================
# CASE B - CONFLICT / REANALYSIS
# ============================================================

def test_conflict_case_takes_reanalysis_route():
    dependencies = WorkflowDependencies(
        run_data_steward=fake_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_conflict,
        run_policy_review=fake_policy_pass,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
        run_reanalysis=fake_reanalysis_resolves_conflict,
    )

    graph = MandateIQGraph(
        dependencies=dependencies
    )

    state = WorkflowState(
        case_id="CASE-B"
    )

    result = graph.run(state)

    assert result.completed is True

    assert result.terminal_route == Route.FINALIZE

    assert result.state.retry_count == 1

    routes = [
        record.to_stage
        for record in result.state.route_history
    ]

    assert "reanalysis" in routes
    assert "finalize" in routes


# ============================================================
# CASE C - CRITICAL POLICY FAILURE
# ============================================================

def test_policy_failure_routes_to_human_review():
    dependencies = WorkflowDependencies(
        run_data_steward=fake_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_clean,
        run_policy_review=fake_policy_failure,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
    )

    graph = MandateIQGraph(
        dependencies=dependencies
    )

    state = WorkflowState(
        case_id="CASE-C"
    )

    result = graph.run(state)

    assert result.completed is True

    assert (
        result.terminal_route
        == Route.HUMAN_REVIEW
    )

    assert (
        result.state.human_review_required
        is True
    )

    routes = [
        record.to_stage
        for record in result.state.route_history
    ]

    assert "policy_review" in routes
    assert "human_review" in routes

    # Verification should never run after a critical
    # deterministic policy failure.
    assert "verify_claims" not in routes


# ============================================================
# CASE D - UNRESOLVED CONFLICT
# ============================================================

def test_unresolved_conflict_eventually_escalates():
    dependencies = WorkflowDependencies(
        run_data_steward=fake_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_conflict,
        run_policy_review=fake_policy_pass,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
        run_reanalysis=fake_reanalysis_keeps_conflict,
    )

    graph = MandateIQGraph(
        dependencies=dependencies
    )

    state = WorkflowState(
        case_id="CASE-D"
    )

    result = graph.run(state)

    assert result.completed is True

    assert (
        result.terminal_route
        == Route.HUMAN_REVIEW
    )

    assert result.state.retry_count == 1

    routes = [
        record.to_stage
        for record in result.state.route_history
    ]

    assert "reanalysis" in routes
    assert "human_review" in routes


# ============================================================
# MISSING OPTIONAL HANDLER
# ============================================================

def test_missing_reanalysis_handler_escalates():
    dependencies = WorkflowDependencies(
        run_data_steward=fake_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_conflict,
        run_policy_review=fake_policy_pass,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
        run_reanalysis=None,
    )

    graph = MandateIQGraph(
        dependencies=dependencies
    )

    state = WorkflowState(
        case_id="CASE-NO-REANALYSIS"
    )

    result = graph.run(state)

    assert (
        result.terminal_route
        == Route.HUMAN_REVIEW
    )

    assert result.state.human_review_required is True

    assert "no re-analysis handler" in (
        result.state.human_review_reason.lower()
    )


# ============================================================
# NODE CONTRACT VALIDATION
# ============================================================

def test_invalid_node_return_type_is_rejected():
    def invalid_data_steward(state):
        return {
            "not": "WorkflowState"
        }

    dependencies = WorkflowDependencies(
        run_data_steward=invalid_data_steward,
        run_proponent=fake_proponent,
        run_challenger=fake_challenger_clean,
        run_policy_review=fake_policy_pass,
        verify_claims=fake_verify_claims,
        calculate_trust_score=fake_trust_score,
    )

    graph = MandateIQGraph(
        dependencies=dependencies
    )

    state = WorkflowState(
        case_id="CASE-INVALID"
    )

    with pytest.raises(
        TypeError,
        match="must return WorkflowState",
    ):
        graph.run(state)


# ============================================================
# SAFETY LIMIT
# ============================================================

def test_graph_rejects_invalid_max_steps():
    with pytest.raises(
        ValueError,
        match="max_steps must be greater than zero",
    ):
        MandateIQGraph(
            dependencies=clean_dependencies(),
            max_steps=0,
        )


# ============================================================
# RESUMABLE STATE
# ============================================================

def test_graph_can_resume_preprocessed_state():
    state = WorkflowState(
        case_id="CASE-RESUME",
        quality_score=0.95,
        quality_report={
            "status": "PASS",
        },
    )

    graph = MandateIQGraph(
        dependencies=clean_dependencies()
    )

    result = graph.run(state)

    assert result.completed is True

    assert result.terminal_route == Route.FINALIZE

    assert result.state.quality_score == 0.95


# ============================================================
# CENTRALIZED GRAPH CONFIGURATION
# ============================================================

def test_graph_uses_centralized_routing_settings():
    """
    The graph should use routing thresholds supplied through
    centralized MandateIQ settings.
    """

    settings = MandateIQSettings(
        trust_threshold=95.0,
    )

    graph = MandateIQGraph(
        dependencies=clean_dependencies(),
        settings=settings,
    )

    state = WorkflowState(
        case_id="CASE-CONFIG-TRUST"
    )

    result = graph.run(state)

    # fake_trust_score() generates a Trust Score of 90.
    # Because the configured threshold is 95, this case
    # must be escalated to human review.
    assert (
        result.terminal_route
        == Route.HUMAN_REVIEW
    )

    assert (
        result.state.human_review_required
        is True
    )

    assert (
        result.state.route_history[-1].reason_code
        == "LOW_TRUST"
    )


def test_graph_uses_configured_max_workflow_steps():
    """
    max_workflow_steps should come from centralized settings
    when max_steps is not explicitly supplied.
    """

    settings = MandateIQSettings(
        max_workflow_steps=2,
    )

    graph = MandateIQGraph(
        dependencies=clean_dependencies(),
        settings=settings,
    )

    assert graph.max_steps == 2


def test_explicit_graph_values_override_settings():
    """
    Explicit graph constructor values should take precedence
    over centralized MandateIQ settings.
    """

    settings = MandateIQSettings(
        max_workflow_steps=10,
        trust_threshold=95.0,
    )

    explicit_config = RoutingConfig(
        quality_threshold=0.80,
        confidence_threshold=0.70,
        trust_threshold=70.0,
        max_retries=1,
    )

    graph = MandateIQGraph(
        dependencies=clean_dependencies(),
        settings=settings,
        routing_config=explicit_config,
        max_steps=30,
    )

    assert graph.max_steps == 30

    assert (
        graph.routing_config.trust_threshold
        == 70.0
    )