"""Proponent Agent — builds the strongest EVIDENCE-SUPPORTED case for approval.

Contract: run_proponent(state) -> ProponentResult
Every claim cites evidence IDs from the ledger; numbers it quotes go into cited_values so the
Hallucination Firewall can check them. It may not invent evidence, hide missing data, or
rewrite calculated values.

Demo seeding (mock and Bedrock): state["metadata"]["demo_injections"]["proponent_claims"]
appends scripted claims (e.g. an unsupported one) so Demo Case B is reproducible. Injected
claims are tagged [SEEDED] in the claim text so nothing is hidden.
"""
from __future__ import annotations

import json

from typing import Any

from src import config_loader
from src.agents import llm_bridge, run_log
from src.agents.tools import ReviewTools
from src.evidence.claims import AgentClaim, CitedValue, Position, ProponentResult, Status
from src.evidence.verifier import EvidenceIndex, norm_label, risk_rank, sget


def _claim(n: int, text: str, idx: EvidenceIndex, fields: list[str], cite: list[str]) -> AgentClaim:
    ids = idx.ids(fields)
    cited = [CitedValue(evidence_id=idx.eid(f)[0], value=idx.value(f)) for f in cite if idx.eid(f)]
    return AgentClaim(
        claim_id=f"PROP-{n:02d}", agent="proponent", claim=text,
        evidence_ids=ids, cited_values=cited, field=idx.canonical(fields[0]),
    )


def _mock(state: Any) -> ProponentResult:
    idx = EvidenceIndex(state)
    rules = config_loader.rules()
    th = rules["thresholds"]
    mandate = config_loader.resolve_mandate(sget(state, "mandate"))
    claims: list[AgentClaim] = []
    weaknesses: list[str] = []

    def add(text: str, fields: list[str], cite: list[str] | None = None) -> None:
        claims.append(_claim(len(claims) + 1, text, idx, fields, cite if cite is not None else fields))

    er, er_max = idx.number("expense_ratio"), mandate.get("max_expense_ratio")
    if er is not None and er_max is not None:
        if 0 <= er <= er_max:
            add(f"Expense ratio of {er:g}% is within the mandate maximum of {er_max:g}%.", ["expense_ratio"])
        else:
            weaknesses.append(f"Expense ratio {er:g}% is outside the mandate range (max {er_max:g}%).")

    pct = idx.number("expense_ratio_percentile")
    if pct is not None:
        if pct <= th["low_fee_percentile"]:
            add(f"Fees are at the {pct:g}th percentile of the category, at or below the median.",
                ["expense_ratio_percentile"])
        elif pct >= th["high_fee_percentile"]:
            weaknesses.append(f"Fees sit at the {pct:g}th category percentile (high-fee tail).")

    ac = norm_label(idx.value("asset_class"))
    allowed = [norm_label(a) for a in mandate.get("allowed_asset_classes", [])]
    if ac:
        if ac in allowed:
            add(f"Asset class '{idx.value('asset_class')}' is permitted by the mandate.", ["asset_class"])
        else:
            weaknesses.append(f"Asset class '{idx.value('asset_class')}' is not in the mandate's allowed list.")

    rr, rmax = risk_rank(idx.value("risk_level")), risk_rank(mandate.get("max_risk_level"))
    if rr is not None and rmax is not None:
        if rr <= rmax:
            add(f"Risk level '{idx.value('risk_level')}' is within the mandate maximum "
                f"'{mandate.get('max_risk_level')}'.", ["risk_level"])
        else:
            weaknesses.append(f"Risk level '{idx.value('risk_level')}' exceeds the mandate maximum.")

    hist, hmin = idx.number("history_years"), mandate.get("minimum_history_years")
    if hist is not None and hmin is not None:
        if hist >= hmin:
            add(f"Fund has {hist:g} years of history, meeting the {hmin:g}-year minimum.", ["history_years"])
        else:
            weaknesses.append(f"Only {hist:g} years of history versus a {hmin:g}-year minimum.")

    for f, label in (("return_5y", "5-year"), ("return_3y", "3-year")):
        r = idx.number(f)
        if r is not None:
            if r > 0:
                add(f"Annualized {label} return is positive at {r:g}%.", [f])
            else:
                weaknesses.append(f"Annualized {label} return is {r:g}% (not positive).")
            break

    tenure = idx.number("manager_tenure_years")
    if tenure is not None:
        if tenure >= th["stable_manager_tenure_years"]:
            add(f"Manager tenure of {tenure:g} years indicates stable management.", ["manager_tenure_years"])
        elif tenure < th["short_manager_tenure_years"]:
            weaknesses.append(f"Manager tenure is short ({tenure:g} years).")

    missing = [f for f in rules.get("required_evidence", []) if not idx.has(f)]
    for c in claims:
        c.confidence = 0.85 if c.evidence_ids else 0.3

    confidence = 0.55 + 0.06 * len(claims) - 0.08 * len(weaknesses) - 0.12 * len(missing)
    confidence = max(0.2, min(0.92, confidence))
    if missing or len(weaknesses) >= 2:
        position, rec = Position.CONDITIONAL_SUPPORT, Status.REVIEW
    else:
        position, rec = Position.SUPPORT, Status.PASS
    if not claims:
        position, rec = Position.OPPOSE, Status.REVIEW

    rationale = (f"{len(claims)} evidence-backed supporting claims; "
                 f"{len(weaknesses)} weaknesses acknowledged; {len(missing)} required fields missing.")
    return ProponentResult(
        position=position, recommended_status=rec, confidence=confidence, claims=claims,
        weaknesses_acknowledged=weaknesses, missing_evidence=missing,
        rationale=rationale, generation_mode="mock",
    )


def _apply_demo_injections(result: ProponentResult, state: Any) -> ProponentResult:
    """Seeded demo claims (Demo Case B), applied in BOTH mock and Bedrock mode so the
    Firewall demo is reproducible. Injected claims are tagged [SEEDED] in the scenario.
    On re-analysis after the firewall blocked Proponent claims, the revised Proponent
    withdraws them instead of repeating them."""
    inj = (sget(state, "metadata", {}) or {}).get("demo_injections", {}) or {}
    seeded = inj.get("proponent_claims", [])
    if not seeded or result.llm_error:
        return result
    if _previously_blocked(state):
        result.rationale = (f"REVISED after firewall findings: withdrew {len(seeded)} unverified "
                            f"claim(s). " + result.rationale)
        return result
    for raw in seeded:
        n = len(result.claims) + 1
        result.claims.append(AgentClaim(
            claim_id=f"PROP-{n:02d}", agent="proponent", claim=raw["claim"],
            evidence_ids=list(raw.get("evidence_ids", [])),
            cited_values=[CitedValue(**c) for c in raw.get("cited_values", [])],
            field=raw.get("field"), confidence=0.85,
        ))
    return result


def _previously_blocked(state: Any) -> list[dict]:
    """Proponent claims the firewall blocked in an earlier pass (present on re-analysis)."""
    return [v for v in (sget(state, "claim_verifications", []) or [])
            if (v.get("agent") if isinstance(v, dict) else v.agent) == "proponent"
            and (v.get("status") if isinstance(v, dict) else v.status.value) != "VERIFIED"]


def _postprocess(data: dict) -> dict:
    """Assign deterministic claim IDs to LLM claims; never trust model-chosen IDs."""
    claims = []
    for i, c in enumerate(data.get("claims", []), start=1):
        claims.append({**c, "claim_id": f"PROP-{i:02d}", "agent": "proponent"})
    return {**data, "claims": claims, "generation_mode": llm_bridge.provider_name()}


PROPONENT_SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "position": {"type": "string", "enum": ["SUPPORT", "CONDITIONAL_SUPPORT", "OPPOSE"]},
        "recommended_status": {"type": "string", "enum": ["PASS", "REVIEW", "REJECT"]},
        "confidence": {"type": "number"},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "cited_values": {"type": "array", "items": {"type": "object", "properties": {
                "evidence_id": {"type": "string"}, "value": {}}}},
            "field": {"type": "string"}}, "required": ["claim", "evidence_ids"]}},
        "weaknesses_acknowledged": {"type": "array", "items": {"type": "string"}},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["position", "recommended_status", "confidence", "claims"],
}


def _mock_with_trace(state: Any, tools: ReviewTools) -> ProponentResult:
    """Deterministic stand-in that still investigates through the real tools, so the trace is real."""
    tools.call("list_evidence")
    tools.call("get_mandate")
    result = _mock(state)
    for c in result.claims:
        tools.call("verify_claim", {"claim": c.claim, "evidence_ids": c.evidence_ids,
                                    "cited_values": [cv.model_dump() for cv in c.cited_values]})
    tools.record("submit_case", {}, f"{len(result.claims)} claims submitted")
    return result


def _tool_use(state: Any, tools: ReviewTools, prompts: dict) -> ProponentResult:
    from src.agents.tool_agent import run_tool_agent
    user = json.dumps({
        "task": "Build the evidence-backed case for approving this fund nomination.",
        "case_id": sget(state, "case_id"),
        "fund": sget(state, "fund_record", {}),
        "required_evidence_fields": config_loader.rules().get("required_evidence", []),
        "previous_firewall_findings": _previously_blocked(state),
    }, default=str)
    return run_tool_agent(
        tools=tools, system=prompts["proponent"]["system"] + "\n" + prompts["tool_mode_addendum"],
        user=user, tool_names=["list_evidence", "get_evidence", "get_mandate", "list_rules", "check_rule", "verify_claim"],
        submit_name="submit_case", submit_description="Submit your final case for approval.",
        submit_schema=PROPONENT_SUBMIT_SCHEMA,
        validate=lambda d: ProponentResult.model_validate(_postprocess(d)),
    )


def run_proponent(state: Any) -> ProponentResult:
    from src.agents.tool_agent import agent_mode
    timer = run_log.Timer()
    idx = EvidenceIndex(state)
    prompts = config_loader.prompts()
    tools = ReviewTools(state, "proponent")
    payload = {
        "case_id": sget(state, "case_id"),
        "fund": sget(state, "fund_record", {}),
        "mandate": config_loader.resolve_mandate(sget(state, "mandate")),
        "quality_score": sget(state, "quality_score"),
        "required_evidence": config_loader.rules().get("required_evidence", []),
        "evidence": idx.compact_summary(),
        # On re-analysis the model sees exactly which of its earlier claims failed verification.
        "previous_firewall_findings": _previously_blocked(state),
    }
    try:
        if llm_bridge.provider_name() == "mock":
            result = _mock_with_trace(state, tools)
        elif agent_mode() == "tool_use":
            result = _tool_use(state, tools, prompts)
        else:
            result = llm_bridge.generate(
                agent="proponent", system=prompts["proponent"]["system"], payload=payload,
                model=ProponentResult, mock_fn=lambda: _mock(state), postprocess=_postprocess,
            )
    except llm_bridge.LLMError as exc:
        result = ProponentResult(
            position=Position.OPPOSE, recommended_status=Status.REVIEW, confidence=0.0, claims=[],
            rationale="Proponent could not produce a validated result; escalate.",
            generation_mode=llm_bridge.provider_name(), llm_error=str(exc),
        )
    result = _apply_demo_injections(result, state)
    result.prompt_version = prompts.get("prompt_version")
    result.trace = tools.trace
    return run_log.attach(result, "proponent", state, timer, [c.claim_id for c in result.claims],
                          llm=True, prompt_version=result.prompt_version)
