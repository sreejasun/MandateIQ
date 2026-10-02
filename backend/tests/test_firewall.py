from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from src.evidence.claims import AgentClaim, CitedValue, FirewallStatus, ProponentResult, Position, Status
from src.trust.hallucination_firewall import verify_agent_claims
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review


def _with_claims(state, claims):
    state["proponent_result"] = ProponentResult(
        position=Position.SUPPORT, recommended_status=Status.PASS, confidence=0.8, claims=claims
    ).model_dump(mode="json")
    return state


def _claim(cid, eids, cited=()):
    return AgentClaim(claim_id=cid, agent="proponent", claim="x", evidence_ids=list(eids),
                      cited_values=[CitedValue(evidence_id=e, value=v) for e, v in cited])


def test_clean_claims_pass():
    s = _with_claims(rc.case_a_clean(), [_claim("PROP-01", ["EV-001"], [("EV-001", 0.45)])])
    r = verify_agent_claims(s)
    assert r.firewall_status == FirewallStatus.PASS
    assert r.verified_claim_ids == ["PROP-01"]


def test_missing_evidence_reference_is_invalid():
    s = _with_claims(rc.case_a_clean(), [_claim("PROP-01", ["EV-999"])])
    r = verify_agent_claims(s)
    assert r.firewall_status == FirewallStatus.FAIL
    assert r.verifications[0].status.value == "INVALID_REFERENCE"
    assert "PROP-01" in r.blocked_claim_ids


def test_numeric_mismatch_is_contradicted():
    s = _with_claims(rc.case_a_clean(), [_claim("PROP-01", ["EV-001"], [("EV-001", 0.15)])])
    r = verify_agent_claims(s)
    assert r.verifications[0].status.value == "CONTRADICTED"
    assert r.firewall_status == FirewallStatus.FAIL


def test_numeric_within_tolerance_passes():
    s = _with_claims(rc.case_a_clean(), [_claim("PROP-01", ["EV-001"], [("EV-001", "0.45%")])])
    assert verify_agent_claims(s).firewall_status == FirewallStatus.PASS


def test_foreign_case_evidence_flagged():
    s = rc.case_a_clean()
    s["evidence_ledger"][0]["case_id"] = "OTHER-CASE"
    s = _with_claims(s, [_claim("PROP-01", ["EV-001"])])
    r = verify_agent_claims(s)
    assert r.verifications[0].status.value == "FOREIGN_EVIDENCE"


def test_no_evidence_cited_warns():
    s = _with_claims(rc.case_a_clean(), [_claim("PROP-01", [])])
    r = verify_agent_claims(s)
    assert r.firewall_status == FirewallStatus.WARN


def test_missing_required_evidence_fails():
    s = run_review(rc.case_e_low_evidence())
    assert s["firewall_status"] == "FAIL"
    codes = {f["code"] for f in s["hallucination_flags"]}
    assert "MISSING_REQUIRED_EVIDENCE" in codes


def test_flags_recorded_in_state_for_audit():
    s = run_review(rc.case_b_unsupported_claim())
    assert s["hallucination_flags"], "firewall findings must be recorded, never silently dropped"
    assert all("claim_id" in f and "detail" in f for f in s["hallucination_flags"])


def test_misquoted_number_in_text_is_caught_without_cited_values():
    """Real LLMs often omit cited_values; the firewall must still catch a wrong number in the text."""
    c = AgentClaim(claim_id="PROP-01", agent="proponent",
                   claim="Expense ratio is only 0.15%, far below the 1.0% cap.", evidence_ids=["EV-001"])
    r = verify_agent_claims(_with_claims(rc.case_a_clean(), [c]))
    assert r.verifications[0].status.value == "UNSUPPORTED"
    assert "0.15" in r.verifications[0].problems[0]
    assert r.firewall_status != FirewallStatus.PASS


def test_correct_numbers_in_text_pass():
    c = AgentClaim(claim_id="PROP-01", agent="proponent",
                   claim="Fund has 12 years of history vs the 3-year minimum; 5-year return 9.4% (EV-008).",
                   evidence_ids=["EV-006", "EV-008"])
    assert verify_agent_claims(_with_claims(rc.case_a_clean(), [c])).firewall_status == FirewallStatus.PASS


def test_verification_recorded_for_every_claim():
    s = run_review(rc.case_a_clean())
    ids = {v["claim_id"] for v in s["claim_verifications"]}
    assert {c["claim_id"] for c in s["proponent_result"]["claims"]} <= ids
