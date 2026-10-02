"""Groq provider: Converse adapter, settings and full committee run with a scripted model.

No network access or API key is needed: `groq_client._create` is patched.
"""
import json
from types import SimpleNamespace as NS

import pytest

from config.settings import MandateIQSettings
from src.agents.committee_pipeline import run_full_review
from src.llm import groq_client
from src.llm.provider import get_llm_provider
from src.llm.schemas import LLMRequest
from tests.fixtures import review_cases as rc


def _completion(content=None, tool_calls=None, finish="stop"):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg, finish_reason=finish)],
              usage=NS(prompt_tokens=10, completion_tokens=5))


def _call(name, args, i):
    return _completion(tool_calls=[NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))],
                       finish="tool_calls")


# ------------------------------------------------------------------ translation
def test_converse_messages_translate_to_openai_format():
    messages = [
        {"role": "user", "content": [{"text": "start"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "get_mandate", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "content": [{"json": {"ok": 1}}],
                                                      "status": "error"}}]},
    ]
    out = groq_client._messages_to_openai([{"text": "sys"}], messages)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "start"}
    assert out[2]["tool_calls"][0]["function"]["name"] == "get_mandate"
    assert out[3]["role"] == "tool" and out[3]["tool_call_id"] == "t1"
    assert out[3]["content"].startswith("ERROR:")


def test_tool_config_translates_and_any_means_required():
    tools, choice = groq_client._tools_to_openai({
        "tools": [{"toolSpec": {"name": "x", "description": "d", "inputSchema": {"json": {"type": "object"}}}}],
        "toolChoice": {"any": {}},
    })
    assert tools[0]["function"]["name"] == "x" and choice == "required"


def test_converse_returns_converse_shape(monkeypatch):
    monkeypatch.setattr(groq_client, "_create", lambda **kw: _call("list_evidence", {}, 1))
    resp = groq_client.converse(modelId="m", system=[{"text": "s"}],
                                messages=[{"role": "user", "content": [{"text": "u"}]}])
    use = resp["output"]["message"]["content"][0]["toolUse"]
    assert use == {"toolUseId": "call_1", "name": "list_evidence", "input": {}}
    assert resp["stopReason"] == "tool_use"


def test_unparseable_tool_arguments_are_returned_to_the_agent(monkeypatch):
    bad = _completion(tool_calls=[NS(id="c", function=NS(name="submit_case", arguments="{not json"))])
    monkeypatch.setattr(groq_client, "_create", lambda **kw: bad)
    resp = groq_client.converse(messages=[{"role": "user", "content": [{"text": "u"}]}])
    assert "_unparseable_arguments" in resp["output"]["message"]["content"][0]["toolUse"]["input"]


# ------------------------------------------------------------------ settings / factory
def test_settings_accept_groq(monkeypatch):
    s = MandateIQSettings(llm_provider="GROQ")
    assert s.llm_provider == "groq"


def test_factory_builds_groq_provider(monkeypatch):
    monkeypatch.setattr(groq_client, "_create", lambda **kw: _completion("hello"))
    provider = get_llm_provider(settings=MandateIQSettings(llm_provider="groq", llm_cache_enabled=False))
    out = provider.invoke(LLMRequest(system_prompt="s", user_prompt="u"))
    assert provider.provider_name == "groq" and out.content == "hello"


def test_missing_api_key_fails_explicitly(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(groq_client.GroqError, match="GROQ_API_KEY"):
        groq_client._client()


# ------------------------------------------------------------------ end to end
def test_full_committee_on_groq_with_scripted_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("MANDATEIQ_AGENT_MODE", "tool_use")
    monkeypatch.setenv("GROQ_MODEL", "test-groq-model")
    n = {"i": 0}

    def fake(**kw):
        n["i"] += 1
        names = [t["function"]["name"] for t in kw["tools"]]
        assert kw["tool_choice"] == "required"
        first = len(kw["messages"]) == 2      # system + first user turn
        if "submit_case" in names:
            if first:
                return _call("list_evidence", {}, n["i"])
            return _call("submit_case", {"position": "SUPPORT", "recommended_status": "PASS", "confidence": 0.85,
                                         "claims": [
                {"claim": "Expense ratio 0.45% is within the 1.0% mandate cap.", "evidence_ids": ["EV-001"]},
                {"claim": "Fund has 12 years of history.", "evidence_ids": ["EV-999"]}]}, n["i"])
        if "submit_challenges" in names:
            return _call("submit_challenges", {"position": "CHALLENGE", "recommended_status": "REVIEW",
                                               "confidence": 0.9, "challenges": [
                {"target_claim": "PROP-02", "challenge_type": "UNSUPPORTED", "severity": "HIGH",
                 "reason": "EV-999 does not exist.", "evidence_ids": []}]}, n["i"])
        if "submit_rebuttals" in names:
            return _call("submit_rebuttals", {"rebuttals": [
                {"challenge_id": "CHAL-01", "action": "REVISE", "response": "Cite the real record.",
                 "revised_claim": "Fund has 12 years of history.", "evidence_ids": ["EV-006"]}]}, n["i"])
        if "submit_verdicts" in names:
            return _call("submit_verdicts", {"verdicts": [
                {"challenge_id": "CHAL-01", "verdict": "ACCEPT", "reason": "EV-006 supports it."}]}, n["i"])
        raise AssertionError(names)

    monkeypatch.setattr(groq_client, "_create", fake)
    s = run_full_review(rc.case_a_clean())
    assert s["proponent_result"]["generation_mode"] == "groq"
    assert s["proponent_result"]["run_log"]["model_id"] == "test-groq-model"
    assert s["debate"]["converged"] and s["debate"]["revised_claim_ids"] == ["PROP-02"]
    assert s["firewall_status"] == "PASS"
    assert s["governance_gate"]["gate"] == "FINALIZE_ELIGIBLE"


# ------------------------------------------------------------------ misnamed submit recovery
_TOOLS = [{"type": "function", "function": {"name": "list_evidence"}},
          {"type": "function", "function": {"name": "submit_challenges",
                                            "parameters": {"required": ["position"]}}}]


def _tool_use_failed(generation):
    exc = Exception("Error code: 400 - tool_use_failed")
    exc.body = {"error": {"code": "tool_use_failed", "failed_generation": generation}}
    return exc


def test_unknown_tool_call_is_readdressed_to_submit_tool():
    gen = json.dumps({"name": "json", "arguments": {"position": "NO_MATERIAL_OBJECTION"}})
    resp = groq_client._recover_misnamed_submit(_tool_use_failed(gen), _TOOLS)
    call = resp.choices[0].message.tool_calls[0]
    assert call.function.name == "submit_challenges"
    assert json.loads(call.function.arguments) == {"position": "NO_MATERIAL_OBJECTION"}


def test_recovery_skips_known_tools_and_unparseable_generations():
    known = json.dumps({"name": "list_evidence", "arguments": {}})
    assert groq_client._recover_misnamed_submit(_tool_use_failed(known), _TOOLS) is None
    assert groq_client._recover_misnamed_submit(_tool_use_failed("not json"), _TOOLS) is None
    gen = json.dumps({"name": "json", "arguments": {"position": "PASS"}})
    assert groq_client._recover_misnamed_submit(_tool_use_failed(gen), _TOOLS[:1]) is None
    stray = json.dumps({"name": "check_rule", "arguments": {"rule_id": "SUIT-004"}})
    assert groq_client._recover_misnamed_submit(_tool_use_failed(stray), _TOOLS) is None
