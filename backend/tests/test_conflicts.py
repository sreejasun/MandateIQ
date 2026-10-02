"""Conflict detection + escalation behaviour (Dileep)."""
from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from src.evidence.claims import (
    Challenge, ChallengerResult, ChallengeType, Position, ProponentResult, Severity, Status,
)
from src.evidence.conflicts import detect_conflicts, disagreement_is_material
from src.trust.hallucination_firewall import verify_agent_claims
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review


def _challenger(*sev_targets, rec=Status.REVIEW):
    return ChallengerResult(
        position=Position.CHALLENGE, recommended_status=rec, confidence=0.8,
        challenges=[Challenge(challenge_id=f"CHAL-{i:02d}", target_claim=t,
                              challenge_type=ChallengeType.RISK_CONCERN, severity=sev,
                              reason="x", evidence_ids=["EV-001"])
                    for i, (sev, t) in enumerate(sev_targets, 1)]).model_dump(mode="json")


def test_material_disagreement():
    s = run_review(rc.case_b_unsupported_claim())
    types = {d["conflict_type"] for d in s["disagreements"] if d["material"]}
    assert "POSITION_DISAGREEMENT" in types and "CLAIM_CHALLENGED" in types


def test_high_challenge_on_claim_is_material():
    s = rc.case_a_clean()
    s["proponent_result"] = run_review(rc.case_a_clean())["proponent_result"]
    s["challenger_result"] = _challenger((Severity.HIGH, "PROP-01"))
    assert disagreement_is_material(detect_conflicts(s))


def test_low_challenges_are_not_material():
    s = rc.case_a_clean()
    s["proponent_result"] = run_review(rc.case_a_clean())["proponent_result"]
    s["challenger_result"] = _challenger((Severity.LOW, "PROP-01"), (Severity.MEDIUM, "PROP-02"),
                                         (Severity.MEDIUM, None))
    assert not disagreement_is_material(detect_conflicts(s))


def test_firewall_blocked_claim_missed_by_challenger_is_material():
    s = run_review(rc.case_b_unsupported_claim())
    s["challenger_result"] = _challenger(rec=Status.PASS)   # Challenger caught nothing
    fw = verify_agent_claims(s)
    conflicts = detect_conflicts(s, fw)
    assert any(c.conflict_type == "UNCHALLENGED_UNVERIFIED_CLAIM" and c.material for c in conflicts)


def test_proponent_pass_vs_policy_fail_is_material():
    s = run_review(rc.case_c_policy_failure())
    p = ProponentResult.model_validate(s["proponent_result"])
    p.recommended_status = Status.PASS
    s["proponent_result"] = p.model_dump(mode="json")
    assert any(c.conflict_type == "POLICY_VS_PROPONENT" and c.material for c in detect_conflicts(s))


def test_low_confidence_escalation():
    s = run_review(rc.case_a_clean())
    p = ProponentResult.model_validate(s["proponent_result"])
    p.confidence = 0.3
    s["proponent_result"] = p.model_dump(mode="json")
    from src.trust.governance import run_governance
    out = run_governance(s)
    assert out["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
    assert any("Low agent confidence" in r for r in out["governance_gate"]["reasons"])


def test_clean_case_finalization():
    s = run_review(rc.case_a_clean())
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"
    assert s.get("human_review_required") is False
