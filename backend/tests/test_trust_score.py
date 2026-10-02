from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from src.trust.trust_score import calculate_trust_score
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review

COMPONENTS = {"evidence_coverage", "claim_verification", "data_quality",
              "agent_confidence", "agent_agreement", "policy_integrity"}


def test_components_present_and_bounded():
    s = run_review(rc.case_a_clean())
    assert set(s["trust_components"]) == COMPONENTS
    assert all(0 <= c["score"] <= 100 for c in s["trust_components"].values())
    assert 0 <= s["trust_score"] <= 100


def test_deterministic_and_reproducible():
    a = calculate_trust_score(run_review(rc.case_b_unsupported_claim()))
    b = calculate_trust_score(run_review(rc.case_b_unsupported_claim()))
    assert a.score == b.score and a.raw_score == b.raw_score


def test_clean_case_high_trust_finalize_eligible():
    s = run_review(rc.case_a_clean())
    assert s["trust_score"] >= 80
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


def test_firewall_fail_caps_score():
    s = run_review(rc.case_b_unsupported_claim())
    g = s["governance_gate"]
    assert g["raw_score"] > s["trust_score"]
    assert any("Firewall FAIL" in c for c in g["caps_applied"])


def test_critical_policy_overrides_score():
    s = run_review(rc.case_c_policy_failure())
    assert s["trust_score"] <= 40
    assert s["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
    assert s["human_review_required"] is True


def test_policy_review_blocks_finalize_even_with_high_score():
    s = run_review(rc.case_high_fee_review())
    assert s["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
