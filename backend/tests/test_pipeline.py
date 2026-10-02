"""
Tests for the integrated MandateIQ application pipeline.
"""

import pandas as pd
import pytest

from src.orchestration.pipeline import run_mandateiq
from src.orchestration.state import WorkflowState


DATASET = "data/sample/fund_sample.csv"


def test_multifund_dataset_requires_fund_id():
    with pytest.raises(
        ValueError,
        match="multiple funds",
    ):
        run_mandateiq(
            DATASET,
            case_id="CASE-MULTI",
        )


def test_unknown_fund_is_rejected():
    with pytest.raises(
        ValueError,
        match="was not found",
    ):
        run_mandateiq(
            DATASET,
            fund_id="DOES-NOT-EXIST",
            case_id="CASE-UNKNOWN",
        )


def test_selected_fund_is_isolated():
    state = run_mandateiq(
        DATASET,
        fund_id="F001",
        case_id="CASE-F001-TEST",
        mandate="balanced_growth",
    )

    assert isinstance(state, WorkflowState)

    assert state.metadata["row_count"] == 1
    assert state.metadata["selected_fund_id"] == "F001"
    assert state.fund_record["fund_id"] == "F001"

    evidence_fund_ids = {
        record["metadata"]["fund_id"]
        for record in state.evidence_ledger
    }

    assert evidence_fund_ids == {"F001"}


def test_single_row_dataframe_does_not_require_fund_id():
    frame = pd.read_csv(DATASET)

    frame = frame[
        frame["fund_id"] == "F002"
    ].copy()

    state = run_mandateiq(
        frame,
        case_id="CASE-SINGLE",
        mandate="balanced_growth",
    )

    assert state.metadata["row_count"] == 1
    assert state.fund_record["fund_id"] == "F002"


def test_f002_reaches_finalize():
    state = run_mandateiq(
        DATASET,
        fund_id="F002",
        case_id="CASE-F002-TEST",
        mandate="balanced_growth",
    )

    assert state.policy_result["policy_status"] == "PASS"
    assert state.policy_result["cost_status"] == "PASS"
    assert state.policy_result["suitability_status"] == "PASS"

    assert state.firewall_status == "PASS"

    assert (
        state.governance_gate["gate"]
        == "FINALIZE_ELIGIBLE"
    )

    assert (
        state.supervisor_result["route"]
        == "finalize"
    )

    assert state.human_review_required is False


def test_f003_requires_human_review():
    state = run_mandateiq(
        DATASET,
        fund_id="F003",
        case_id="CASE-F003-TEST",
        mandate="balanced_growth",
    )

    assert (
        state.policy_result["suitability_status"]
        == "FAIL"
    )

    assert (
        state.governance_gate["gate"]
        == "HUMAN_REVIEW_REQUIRED"
    )

    assert (
        state.supervisor_result["route"]
        == "human_review"
    )

    assert state.human_review_required is True