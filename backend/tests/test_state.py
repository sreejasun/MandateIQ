import pytest
from pydantic import ValidationError

from src.orchestration.state import WorkflowState, add_route_record


def test_minimal_workflow_state():
    state = WorkflowState(case_id="CASE-001")

    assert state.case_id == "CASE-001"
    assert state.dataset_uri is None
    assert state.quality_score == 0.0
    assert state.trust_score is None
    assert state.retry_count == 0
    assert state.route_history == []
    assert state.human_review_required is False
    assert state.final_status is None


def test_workflow_state_does_not_share_mutable_defaults():
    first = WorkflowState(case_id="CASE-001")
    second = WorkflowState(case_id="CASE-002")

    first.risk_flags.append({"code": "TEST_FLAG"})

    assert len(first.risk_flags) == 1
    assert second.risk_flags == []


def test_empty_case_id_is_rejected():
    with pytest.raises(ValidationError):
        WorkflowState(case_id="   ")


def test_invalid_quality_score_is_rejected():
    with pytest.raises(ValidationError):
        WorkflowState(
            case_id="CASE-001",
            quality_score=1.5,
        )


def test_invalid_trust_score_is_rejected():
    with pytest.raises(ValidationError):
        WorkflowState(
            case_id="CASE-001",
            trust_score=101,
        )


def test_negative_retry_count_is_rejected():
    with pytest.raises(ValidationError):
        WorkflowState(
            case_id="CASE-001",
            retry_count=-1,
        )


def test_add_route_record():
    state = WorkflowState(case_id="CASE-001")

    record = add_route_record(
        state=state,
        from_stage="data_steward",
        to_stage="proponent",
        reason_code="QUALITY_PASSED",
        reason="Data quality requirements were satisfied.",
    )

    assert len(state.route_history) == 1
    assert record.from_stage == "data_steward"
    assert record.to_stage == "proponent"
    assert record.reason_code == "QUALITY_PASSED"
    assert state.route_history[0] == record


def test_route_record_supporting_claims():
    state = WorkflowState(case_id="CASE-002")

    record = add_route_record(
        state=state,
        from_stage="challenger",
        to_stage="human_review",
        reason_code="UNRESOLVED_CONFLICT",
        reason="Material disagreement could not be resolved.",
        supporting_claims=["CHAL-02", "PROP-03"],
    )

    assert record.supporting_claims == ["CHAL-02", "PROP-03"]