"""OPT-IN real-Bedrock smoke test (about 4 model calls). Skipped unless RUN_BEDROCK=1.

    RUN_BEDROCK=1 BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-5 AWS_REGION=us-east-1 \
        python3 -m pytest -q tests/test_bedrock_smoke.py

The committee tests (tool use + debate) make roughly 10-20 Bedrock calls in total.

Needs fresh AWS credentials in the same terminal. Real AI varies between runs, so these
assertions check behaviour that must ALWAYS hold, not exact wording.
"""
import os

import pytest

from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BEDROCK") != "1" or not os.environ.get("BEDROCK_MODEL_ID"),
    reason="set RUN_BEDROCK=1 and BEDROCK_MODEL_ID to run the real-Bedrock smoke test",
)


@pytest.fixture(autouse=True)
def _bedrock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")


@pytest.fixture(scope="module")
def case_a():
    os.environ["LLM_PROVIDER"] = "bedrock"
    return run_review(rc.case_a_clean())


@pytest.fixture(scope="module")
def case_b():
    os.environ["LLM_PROVIDER"] = "bedrock"
    return run_review(rc.case_b_unsupported_claim())


def test_real_agents_return_valid_output(case_a):
    for key in ("proponent_result", "challenger_result"):
        r = case_a[key]
        assert r["llm_error"] is None, f"{key}: {r['llm_error']}"
        assert r["generation_mode"] == "bedrock"


def test_real_proponent_cites_existing_evidence(case_a):
    ledger_ids = {e["evidence_id"] for e in case_a["evidence_ledger"]}
    claims = case_a["proponent_result"]["claims"]
    assert len(claims) >= 3
    for c in claims:
        assert c["evidence_ids"] and set(c["evidence_ids"]) <= ledger_ids, c


def test_real_clean_case_is_not_escalated_to_human(case_a):
    assert case_a["governance_gate"]["gate"] in {"FINALIZE_ELIGIBLE", "REANALYSIS_SUGGESTED"}, \
        case_a["governance_gate"]


def test_real_run_catches_seeded_lies(case_b):
    blocked = set(case_b["governance_gate"]["blocked_claim_ids"])
    seeded = {c["claim_id"] for c in case_b["proponent_result"]["claims"] if "[SEEDED]" in c["claim"]}
    assert seeded and seeded <= blocked, (seeded, blocked)
    assert case_b["firewall_status"] == "FAIL"
    assert case_b["governance_gate"]["gate"] != "FINALIZE_ELIGIBLE"


# ------------------------------------------------------------------ agents v2: tool use + debate
@pytest.fixture(scope="module")
def committee_b():
    os.environ["LLM_PROVIDER"] = "bedrock"
    os.environ["MANDATEIQ_AGENT_MODE"] = "tool_use"
    from src.agents.committee_pipeline import run_full_review
    return run_full_review(rc.case_b_unsupported_claim())


def test_real_agents_investigate_with_tools(committee_b):
    for key in ("proponent_result", "challenger_result"):
        r = committee_b[key]
        assert r["llm_error"] is None, r["llm_error"]
        tools = [t["tool"] for t in r["trace"]]
        assert len(tools) >= 2 and tools[-1].startswith("submit_"), tools


def test_real_debate_removes_seeded_lies(committee_b):
    d = committee_b["debate"]
    live = {c["claim_id"]: c for c in committee_b["proponent_result"]["claims"]}
    seeded_live = [c for c in live.values() if "[SEEDED]" in c["claim"]]
    blocked = set(committee_b["governance_gate"]["blocked_claim_ids"])
    # every seeded lie is either withdrawn in the debate or still blocked by the firewall
    assert all(c["claim_id"] in blocked for c in seeded_live), (seeded_live, blocked)
    assert d["total_rounds"] >= 2 or seeded_live
    assert committee_b["governance_gate"]["gate"] in {"FINALIZE_ELIGIBLE", "REANALYSIS_SUGGESTED",
                                                      "HUMAN_REVIEW_REQUIRED"}
