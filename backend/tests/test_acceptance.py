"""Acceptance test for the review committee and governance modules:

"A seeded unsupported/contradicted claim is flagged and changes conflict/trust/routing state."

The Supervisor belongs to Narahari; here we assert on the governance gate it consumes and
on the state keys it reads (firewall_status, disagreements, trust_score).
"""

from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review


def test_seeded_unsupported_claim_changes_conflict_trust_and_route():
    clean = run_review(rc.case_a_clean())
    seeded = run_review(rc.case_b_unsupported_claim())

    # 1. flagged
    blocked = seeded["governance_gate"]["blocked_claim_ids"]
    assert len(blocked) == 2
    assert {f["code"] for f in seeded["hallucination_flags"]} >= {"INVALID_REFERENCE", "CONTRADICTED"}
    assert seeded["firewall_status"] == "FAIL" and clean["firewall_status"] == "PASS"

    # 2. conflict state changes
    assert not any(d["material"] for d in clean["disagreements"])
    assert any(d["material"] for d in seeded["disagreements"])

    # 3. trust changes
    assert seeded["trust_score"] < clean["trust_score"] - 20

    # 4. routing input changes
    assert clean["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"
    assert seeded["governance_gate"]["gate"] in {"REANALYSIS_SUGGESTED", "HUMAN_REVIEW_REQUIRED"}


def test_reanalysis_withdraws_blocked_claims_and_recovers():
    s = run_review(rc.case_b_unsupported_claim())
    assert s["governance_gate"]["gate"] == "REANALYSIS_SUGGESTED"
    s["retry_count"] = 1
    s = run_review(s)
    assert s["proponent_result"]["rationale"].startswith("REVISED")
    assert s["firewall_status"] == "PASS"
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


def test_seeded_cases_produce_distinct_gates():
    gates = {name: run_review(fn())["governance_gate"]["gate"] for name, fn in {
        "A": rc.case_a_clean, "B": rc.case_b_unsupported_claim,
        "C": rc.case_c_policy_failure, "E": rc.case_e_low_evidence}.items()}
    assert gates == {"A": "FINALIZE_ELIGIBLE", "B": "REANALYSIS_SUGGESTED",
                     "C": "HUMAN_REVIEW_REQUIRED", "E": "HUMAN_REVIEW_REQUIRED"}


def test_acceptance_with_agentic_debate():
    """Same acceptance criterion through the v2 committee (tool use + debate)."""
    from src.agents.committee_pipeline import run_full_review
    clean = run_full_review(rc.case_a_clean())
    seeded = run_full_review(rc.case_b_unsupported_claim())
    d = seeded["debate"]
    # flagged: the firewall blocked both seeded claims going into the rebuttal round
    assert set(d["rounds"][0]["blocked_claim_ids_before"]) == {"PROP-08", "PROP-09"}
    # conflict state changed: two HIGH challenges raised, then resolved through debate
    assert set(d["resolved_challenge_ids"]) == {"CHAL-01", "CHAL-02"}
    # trust changed: withdrawn hallucinations still lower trust
    assert seeded["trust_score"] < clean["trust_score"]
    # routing changed: an extra debate round was required before the gate
    assert d["total_rounds"] == 2 and clean["debate"]["total_rounds"] == 1
