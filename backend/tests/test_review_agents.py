from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
import pytest

from src.agents import llm_bridge
from src.agents.challenger import run_challenger
from src.agents.policy_suitability import run_policy_review
from src.agents.proponent import run_proponent
from src.evidence.claims import ChallengerResult, PolicyResult, ProponentResult
from src.evidence.conflicts import detect_conflicts, disagreement_is_material
from tests.fixtures import review_cases as rc
from tests.review_pipeline import run_review


# ---------------- schemas
def test_proponent_schema():
    r = run_proponent(rc.case_a_clean())
    ProponentResult.model_validate(r.model_dump())
    assert r.claims and all(c.evidence_ids for c in r.claims)
    assert all(c.claim_id.startswith("PROP-") for c in r.claims)


def test_challenger_schema_and_targets_claims():
    s = rc.case_b_unsupported_claim()
    s["proponent_result"] = run_proponent(s).model_dump(mode="json")
    r = run_challenger(s)
    ChallengerResult.model_validate(r.model_dump())
    targets = {c.target_claim for c in r.challenges if c.target_claim}
    assert targets, "Challenger must target specific Proponent claims"


def test_proponent_acknowledges_missing_evidence():
    r = run_proponent(rc.case_e_low_evidence())
    assert set(r.missing_evidence) >= {"asset_class", "risk_level", "history_years"}
    assert r.recommended_status.value != "PASS"


# ---------------- policy
def test_policy_rule_negative_expense_ratio_is_critical():
    r = run_policy_review(rc.case_c_policy_failure())
    PolicyResult.model_validate(r.model_dump())
    assert r.has_critical_failure
    failed = {x.rule_id for x in r.rule_results if not x.passed}
    assert {"POL-002", "SUIT-001"} <= failed


def test_policy_clean_case_passes():
    r = run_policy_review(rc.case_a_clean())
    assert (r.policy_status.value, r.cost_status.value, r.suitability_status.value) == ("PASS",) * 3


def test_cost_review_on_high_fee():
    r = run_policy_review(rc.case_high_fee_review())
    assert r.cost_status.value == "REVIEW" and not r.has_critical_failure


def test_rule_results_carry_evidence_ids():
    r = run_policy_review(rc.case_a_clean())
    assert all(x.evidence_ids for x in r.rule_results if x.passed)


# ---------------- conflicts
def test_material_disagreement_detected():
    s = run_review(rc.case_b_unsupported_claim())
    assert any(d["material"] for d in s["disagreements"])
    assert any(d["confirmed_by_firewall"] for d in s["disagreements"])


def test_no_conflict_on_clean_case():
    s = run_review(rc.case_a_clean())
    assert not disagreement_is_material(detect_conflicts(s))


# ---------------- LLM bridge failure handling
def test_bedrock_failure_is_explicit_not_silent(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setattr(llm_bridge, "_team_provider", lambda: None)
    r = run_proponent(rc.case_a_clean())
    assert r.llm_error and r.confidence == 0.0 and r.generation_mode == "bedrock"
    s = rc.case_a_clean()
    s["proponent_result"] = r.model_dump(mode="json")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    s["challenger_result"] = run_challenger(s).model_dump(mode="json")
    s["policy_result"] = run_policy_review(s).model_dump(mode="json")
    from src.trust.governance import run_governance
    out = run_governance(s)
    assert out["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"


def test_bedrock_invalid_json_retries_then_validates(monkeypatch):
    calls = []

    def fake(system, user, agent):
        calls.append(user)
        if len(calls) == 1:
            return {"position": "SUPPORT"}  # invalid: missing fields
        return {"position": "SUPPORT", "recommended_status": "PASS", "confidence": 0.8,
                "claims": [{"claim": "ok", "evidence_ids": ["EV-001"]}]}

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("MANDATEIQ_AGENT_MODE", "single_shot")
    monkeypatch.setattr(llm_bridge, "_raw_call", fake)
    r = run_proponent(rc.case_a_clean())
    assert len(calls) == 2 and "invalid" in calls[1]
    assert r.claims[0].claim_id == "PROP-01" and r.generation_mode == "bedrock"


def test_minor_nitpicks_are_not_material():
    """A Challenger that says REVIEW over LOW/MEDIUM nitpicks must not force re-analysis."""
    from src.evidence.claims import Challenge, ChallengerResult, ChallengeType, Position, Severity, Status
    s = rc.case_a_clean()
    s["proponent_result"] = run_proponent(s).model_dump(mode="json")
    s["challenger_result"] = ChallengerResult(
        position=Position.NO_MATERIAL_OBJECTION, recommended_status=Status.REVIEW, confidence=0.6,
        challenges=[Challenge(challenge_id="CHAL-01", target_claim="PROP-01",
                              challenge_type=ChallengeType.WEAK_EVIDENCE, severity=Severity.LOW,
                              reason="nitpick", evidence_ids=["EV-001"]),
                    Challenge(challenge_id="CHAL-02", target_claim="PROP-02",
                              challenge_type=ChallengeType.WEAK_EVIDENCE, severity=Severity.MEDIUM,
                              reason="nitpick", evidence_ids=["EV-002"])],
    ).model_dump(mode="json")
    s["policy_result"] = run_policy_review(s).model_dump(mode="json")
    from src.trust.governance import run_governance
    out = run_governance(s)
    assert out["governance_gate"]["material_conflicts"] == 0
    assert out["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


def test_seeded_claims_injected_in_bedrock_mode(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("MANDATEIQ_AGENT_MODE", "single_shot")
    monkeypatch.setattr(llm_bridge, "_raw_call", lambda system, user, agent: {
        "position": "SUPPORT", "recommended_status": "PASS", "confidence": 0.9,
        "claims": [{"claim": "Fee within mandate.", "evidence_ids": ["EV-001"],
                    "cited_values": [{"evidence_id": "EV-001", "value": 0.45}]}]})
    r = run_proponent(rc.case_b_unsupported_claim())
    assert [c.claim_id for c in r.claims] == ["PROP-01", "PROP-02", "PROP-03"]
    assert "[SEEDED]" in r.claims[1].claim and r.generation_mode == "bedrock"


def test_run_log_records_observability_fields():
    """Requirements §42 (observability) and §18 (model/prompt/rule version in the decision packet)."""
    s = run_review(rc.case_b_unsupported_claim())
    for key, agent in (("proponent_result", "proponent"), ("challenger_result", "challenger"),
                       ("policy_result", "policy_suitability")):
        log = s[key]["run_log"]
        assert log["agent"] == agent and log["case_id"] == "CASE-B"
        assert log["started_at"] <= log["ended_at"] and log["latency_ms"] >= 0
        assert log["input_evidence_ids"] and log["model_id"]
    assert s["proponent_result"]["run_log"]["output_ids"][0] == "PROP-01"
    assert s["proponent_result"]["run_log"]["prompt_version"]
    assert s["policy_result"]["run_log"]["rule_version"] == "rules-v1.1"
    assert s["policy_result"]["run_log"]["model_id"] == "deterministic"
