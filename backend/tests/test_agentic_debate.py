"""Agents v2: tool-using agents + multi-round Proponent/Challenger debate (Dileep)."""
import copy
import json

import pytest

from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
from src.agents import tool_agent
from src.agents.committee_pipeline import run_full_review
from src.agents.debate import run_committee
from src.agents.tools import ReviewTools
from src.evidence.claims import ProponentResult
from tests.fixtures import review_cases as rc


# ------------------------------------------------------------------ tools
def test_tools_answer_from_the_ledger_and_record_a_trace():
    t = ReviewTools(rc.case_a_clean(), "proponent")
    assert t.call("get_evidence", {"field": "expense_ratio"})[0]["value"] == 0.45
    assert t.call("check_rule", {"rule_id": "COST-001"})[0]["passed"] is True
    bad = t.call("verify_claim", {"claim": "Fee is 0.15%", "evidence_ids": ["EV-001"]})[0]
    assert bad["status"] == "UNSUPPORTED"
    out, ok = t.call("no_such_tool")
    assert not ok and "error" in out                      # tool errors go back to the agent
    assert [c.tool for c in t.trace] == ["get_evidence", "check_rule", "verify_claim", "no_such_tool"]


def test_mock_agents_investigate_through_tools():
    s = run_full_review(rc.case_a_clean())
    ptools = [c["tool"] for c in s["proponent_result"]["trace"]]
    ctools = [c["tool"] for c in s["challenger_result"]["trace"]]
    assert ptools[:2] == ["list_evidence", "get_mandate"] and "verify_claim" in ptools
    assert ptools[-1] == "submit_case"
    assert "check_rule" in ctools and ctools[-1] == "submit_challenges"


# ------------------------------------------------------------------ debate outcomes
def test_clean_case_agrees_in_opening_round():
    s = run_full_review(rc.case_a_clean())
    assert s["debate"]["total_rounds"] == 1 and s["debate"]["converged"]
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


def test_hallucinating_proponent_concedes_in_debate_and_is_penalised():
    clean = run_full_review(rc.case_a_clean())
    s = run_full_review(rc.case_b_unsupported_claim())
    d = s["debate"]
    assert d["total_rounds"] == 2 and d["converged"]
    assert {w["claim_id"] for w in d["withdrawn_claims"]} == {"PROP-08", "PROP-09"}
    r2 = d["rounds"][0]
    assert r2["firewall_status_before"] == "FAIL"
    assert {r["action"] for r in r2["rebuttals"]} == {"CONCEDE"}
    assert {v["verdict"] for v in r2["verdicts"]} == {"ACCEPT"}
    assert all("[SEEDED]" not in c["claim"] for c in s["proponent_result"]["claims"])
    assert s["firewall_status"] == "PASS"
    assert s["trust_score"] < clean["trust_score"], "withdrawn hallucinations must still cost trust"
    assert "withdrawn during debate" in s["trust_components"]["claim_verification"]["explanation"]


def test_unresolvable_disagreement_escalates_to_human_after_max_rounds():
    s = run_full_review(rc.case_f_persistent_disagreement())
    d = s["debate"]
    assert not d["converged"] and d["total_rounds"] == d["max_rounds"] == 3
    assert d["open_challenge_ids"]
    assert all(r["rebuttals"][0]["action"] == "DEFEND" for r in d["rounds"])
    assert all(r["verdicts"][0]["verdict"] == "MAINTAIN" for r in d["rounds"])
    assert s["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
    assert any("Debate ended without agreement" in r for r in s["governance_gate"]["reasons"])


def test_debate_is_bounded_by_config(monkeypatch):
    from src import config_loader
    real = config_loader.load
    monkeypatch.setattr(config_loader, "load", lambda n: {**real(n), "debate": {
        "enabled": True, "max_rounds": 2, "respond_to_severities": ["HIGH"]}} if n == "agents.yaml" else real(n))
    d = run_committee(rc.case_f_persistent_disagreement())["debate"]
    assert d["total_rounds"] == 2 and not d["converged"]


def test_debate_can_be_disabled(monkeypatch):
    from src import config_loader
    real = config_loader.load
    monkeypatch.setattr(config_loader, "load", lambda n: {**real(n), "debate": {"enabled": False}}
                        if n == "agents.yaml" else real(n))
    d = run_committee(rc.case_b_unsupported_claim())["debate"]
    assert d["enabled"] is False and d["total_rounds"] == 1 and d["rounds"] == []


def test_debate_transcript_is_json_serialisable_for_dashboard_and_s3():
    json.dumps(run_full_review(rc.case_f_persistent_disagreement()))


# ------------------------------------------------------------------ Bedrock tool-use wiring (simulated)
def _tool_use(name, inp, i):
    return {"output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": f"t{i}", "name": name, "input": inp}}]}}}


def test_tool_agent_loop_runs_tools_and_self_corrects_invalid_submission(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    script = iter([
        _tool_use("get_evidence", {"field": "expense_ratio"}, 1),
        _tool_use("submit_case", {"position": "SUPPORT"}, 2),               # invalid -> rejected
        _tool_use("submit_case", {"position": "SUPPORT", "recommended_status": "PASS",
                                  "confidence": 0.8, "claims": [
                                      {"claim": "Fee 0.45% within 1.0% cap.", "evidence_ids": ["EV-001"]}]}, 3),
    ])
    sent = []

    def fake(**kw):
        sent.append(copy.deepcopy(kw))     # the loop reuses one message list; snapshot it
        return next(script)
    monkeypatch.setattr(tool_agent, "_converse", fake)
    from src.agents.proponent import PROPONENT_SUBMIT_SCHEMA, _postprocess
    tools = ReviewTools(rc.case_a_clean(), "proponent")
    r = tool_agent.run_tool_agent(
        tools=tools, system="s", user="u", tool_names=["get_evidence"], submit_name="submit_case",
        submit_description="d", submit_schema=PROPONENT_SUBMIT_SCHEMA,
        validate=lambda d: ProponentResult.model_validate(_postprocess(d)))
    assert r.claims[0].claim_id == "PROP-01"
    assert [c.tool for c in tools.trace] == ["get_evidence", "submit_case", "submit_case"]
    assert tools.trace[1].ok is False and tools.trace[2].ok is True
    # the rejection was sent back to the model as a tool error
    last_user = sent[2]["messages"][-1]["content"][0]["toolResult"]
    assert last_user["status"] == "error" and "rejected" in json.dumps(last_user["content"])
    assert sent[0]["toolConfig"]["toolChoice"] == {"any": {}}


def test_tool_agent_is_bounded(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr(tool_agent, "_converse", lambda **kw: _tool_use("list_evidence", {}, 1))
    with pytest.raises(tool_agent.LLMError, match="did not submit"):
        tool_agent.run_tool_agent(tools=ReviewTools(rc.case_a_clean(), "proponent"), system="s", user="u",
                                  tool_names=["list_evidence"], submit_name="submit_case",
                                  submit_description="d", submit_schema={}, validate=lambda d: d,
                                  max_steps=3)


def test_full_bedrock_committee_with_simulated_model(monkeypatch):
    """End-to-end Bedrock path (tool-use + debate) with a scripted model: no AWS needed."""
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("MANDATEIQ_AGENT_MODE", "tool_use")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    counter = {"n": 0}

    def fake(**kw):
        counter["n"] += 1
        sysmsg, names = kw["system"][0]["text"], [t["toolSpec"]["name"] for t in kw["toolConfig"]["tools"]]
        first = len(kw["messages"]) == 1
        if "submit_case" in names:
            if first:
                return _tool_use("list_evidence", {}, counter["n"])
            return _tool_use("submit_case", {"position": "SUPPORT", "recommended_status": "PASS",
                                             "confidence": 0.85, "claims": [
                {"claim": "Expense ratio 0.45% is within the 1.0% mandate cap.", "evidence_ids": ["EV-001"]},
                {"claim": "Fund has 12 years of history.", "evidence_ids": ["EV-999"]}]}, counter["n"])
        if "submit_challenges" in names:
            return _tool_use("submit_challenges", {"position": "CHALLENGE", "recommended_status": "REVIEW",
                                                   "confidence": 0.9, "challenges": [
                {"target_claim": "PROP-02", "challenge_type": "UNSUPPORTED", "severity": "HIGH",
                 "reason": "EV-999 does not exist.", "evidence_ids": []}]}, counter["n"])
        if "submit_rebuttals" in names:
            return _tool_use("submit_rebuttals", {"rebuttals": [
                {"challenge_id": "CHAL-01", "action": "REVISE", "response": "Cite the real record.",
                 "revised_claim": "Fund has 12 years of history.", "evidence_ids": ["EV-006"]}]}, counter["n"])
        if "submit_verdicts" in names:
            return _tool_use("submit_verdicts", {"verdicts": [
                {"challenge_id": "CHAL-01", "verdict": "ACCEPT", "reason": "EV-006 supports it."}]}, counter["n"])
        raise AssertionError(names)

    monkeypatch.setattr(tool_agent, "_converse", fake)
    s = run_full_review(rc.case_a_clean())
    d = s["debate"]
    assert s["proponent_result"]["generation_mode"] == "bedrock"
    assert d["total_rounds"] == 2 and d["converged"] and d["revised_claim_ids"] == ["PROP-02"]
    revised = next(c for c in s["proponent_result"]["claims"] if c["claim_id"] == "PROP-02")
    assert revised["evidence_ids"] == ["EV-006"]
    assert s["firewall_status"] == "PASS"
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"
    assert s["proponent_result"]["trace"][0]["tool"] == "list_evidence"


# ------------------------------------------------------------------ hard control beats agent agreement
def test_imputed_required_evidence_forces_human_review_even_if_agents_agree():
    """Real-AI finding: agents converged on a 'provisional' claim built on imputed data.
    POL-005 is deterministic, so agreement between agents cannot approve it."""
    from src.agents.policy_suitability import run_policy_review
    from src.trust.governance import run_governance
    s = rc.case_f_persistent_disagreement()
    s.update(run_committee(s))
    d = dict(s["debate"])
    d.update(converged=True, open_challenge_ids=[], stop_reason="converged after 2 round(s)")
    s["debate"] = d                                   # simulate the agents agreeing
    for ch in s["challenger_result"]["challenges"]:
        ch["resolved"] = True
    s["challenger_result"]["recommended_status"] = "PASS"
    s["challenger_result"]["position"] = "NO_MATERIAL_OBJECTION"
    s["policy_result"] = run_policy_review(s).model_dump(mode="json")
    failed = {r["rule_id"] for r in s["policy_result"]["rule_results"] if not r["passed"]}
    assert "POL-005" in failed and s["policy_result"]["policy_status"] == "REVIEW"
    out = run_governance(s)
    assert out["governance_gate"]["gate"] == "HUMAN_REVIEW_REQUIRED"
    assert any("policy" in r for r in out["governance_gate"]["reasons"])


def test_clean_evidence_passes_pol_005():
    from src.agents.policy_suitability import run_policy_review
    r = run_policy_review(rc.case_a_clean())
    assert next(x for x in r.rule_results if x.rule_id == "POL-005").passed


def test_list_rules_tool_and_unknown_rule_is_an_error():
    t = ReviewTools(rc.case_a_clean(), "proponent")
    ids = [r["rule_id"] for r in t.call("list_rules")[0]["rules"]]
    assert "POL-005" in ids and "COST-001" in ids
    out, ok = t.call("check_rule", {"rule_id": "HIST-001"})
    assert not ok and "unknown rule" in out["error"]
