"""Risk Challenger Agent — tries to FALSIFY the Proponent's case.

Contract: run_challenger(state) -> ChallengerResult   (requires state["proponent_result"])
Challenges target specific Proponent claim IDs where possible, and every challenge cites
evidence IDs (or names the missing field). Independent risks use target_claim=None.
"""
from __future__ import annotations

import json

from typing import Any

from src import config_loader
from src.agents import llm_bridge, run_log
from src.agents.tools import ReviewTools
from src.evidence.claims import (
    Challenge, ChallengerResult, ChallengeType, Position, ProponentResult, Severity, Status,
)
from src.evidence.verifier import EvidenceIndex, as_number, norm_label, risk_rank, sget


def _proponent(state: Any) -> ProponentResult | None:
    raw = sget(state, "proponent_result")
    if raw is None:
        return None
    return raw if isinstance(raw, ProponentResult) else ProponentResult.model_validate(raw)


def _values_match(cited: Any, stored: Any) -> bool:
    a, b = as_number(cited), as_number(stored)
    if a is None or b is None:
        return norm_label(cited) == norm_label(stored)
    tol = config_loader.firewall_config()["numeric_tolerance"]
    return abs(a - b) <= tol["absolute"] or (b != 0 and abs(a - b) / abs(b) <= tol["relative"])


def _mock(state: Any) -> ChallengerResult:
    idx = EvidenceIndex(state)
    rules = config_loader.rules()
    th = rules["thresholds"]
    mandate = config_loader.resolve_mandate(sget(state, "mandate"))
    prop = _proponent(state)
    out: list[Challenge] = []

    def add(target, ctype, sev, reason, eids, field=None):
        out.append(Challenge(challenge_id=f"CHAL-{len(out) + 1:02d}", target_claim=target,
                             challenge_type=ctype, severity=sev, reason=reason,
                             evidence_ids=eids, field=field))

    # 1) Claim-level attacks on the Proponent's case.
    for c in (prop.claims if prop else []):
        if not c.evidence_ids:
            add(c.claim_id, ChallengeType.UNSUPPORTED, Severity.HIGH,
                "Claim cites no evidence at all.", [], c.field)
            continue
        missing_ids = [e for e in c.evidence_ids if idx.get(e) is None]
        if missing_ids:
            add(c.claim_id, ChallengeType.UNSUPPORTED, Severity.HIGH,
                f"Claim relies on evidence not present in the ledger: {', '.join(missing_ids)}.",
                [e for e in c.evidence_ids if idx.get(e)], c.field)
            continue
        bad = [cv for cv in c.cited_values if idx.get(cv.evidence_id)
               and not _values_match(cv.value, idx.get(cv.evidence_id).get("value"))]
        if bad:
            cv = bad[0]
            add(c.claim_id, ChallengeType.CONTRADICTED, Severity.HIGH,
                f"Claim quotes {cv.value} but {cv.evidence_id} records "
                f"{idx.get(cv.evidence_id).get('value')}.", [cv.evidence_id], c.field)
            continue
        flagged = [e for e in c.evidence_ids if idx.is_flagged(e)]
        if flagged:
            required = set(rules.get("required_evidence", []))
            on_required = any(idx.canonical((idx.get(e) or {}).get("field", "")) in required for e in flagged)
            add(c.claim_id, ChallengeType.WEAK_EVIDENCE, Severity.HIGH if on_required else Severity.MEDIUM,
                "Claim relies on evidence the Data Steward flagged as imputed or low quality"
                + (" for a REQUIRED field; the value cannot be confirmed from source data." if on_required else "."),
                flagged, c.field)

    # 2) Independent risk findings the Proponent may have glossed over.
    for f in rules.get("required_evidence", []):
        if not idx.has(f):
            add(None, ChallengeType.MISSING_EVIDENCE, Severity.HIGH,
                f"Required evidence '{f}' is missing; approval cannot be fully supported.", [], f)

    pct = idx.number("expense_ratio_percentile")
    if pct is not None and pct >= th["high_fee_percentile"]:
        add(None, ChallengeType.RISK_CONCERN, Severity.MEDIUM,
            f"Expense ratio is at the {pct:g}th category percentile (high-fee tail).",
            idx.eid("expense_ratio_percentile"), "expense_ratio_percentile")

    er, er_max = idx.number("expense_ratio"), mandate.get("max_expense_ratio")
    if er is not None and er < th["expense_ratio_min"]:
        add(None, ChallengeType.RISK_CONCERN, Severity.HIGH,
            f"Expense ratio {er:g}% is negative, which is not a valid fee; the record is unreliable.",
            idx.eid("expense_ratio"), "expense_ratio")
    ac = norm_label(idx.value("asset_class"))
    allowed = [norm_label(a) for a in mandate.get("allowed_asset_classes", [])]
    if ac and ac not in allowed:
        add(None, ChallengeType.MANDATE_CONFLICT, Severity.HIGH,
            f"Asset class '{idx.value('asset_class')}' is not allowed by the mandate.",
            idx.eid("asset_class"), "asset_class")
    if er is not None and er_max is not None and er > er_max:
        add(None, ChallengeType.MANDATE_CONFLICT, Severity.HIGH,
            f"Expense ratio {er:g}% exceeds the mandate maximum {er_max:g}%.",
            idx.eid("expense_ratio"), "expense_ratio")

    rr, rmax = risk_rank(idx.value("risk_level")), risk_rank(mandate.get("max_risk_level"))
    if rr is not None and rmax is not None and rr > rmax:
        add(None, ChallengeType.MANDATE_CONFLICT, Severity.HIGH,
            f"Risk level '{idx.value('risk_level')}' exceeds mandate maximum "
            f"'{mandate.get('max_risk_level')}'.", idx.eid("risk_level"), "risk_level")

    tenure = idx.number("manager_tenure_years")
    if tenure is not None and tenure < th["short_manager_tenure_years"]:
        add(None, ChallengeType.RISK_CONCERN, Severity.MEDIUM,
            f"Manager tenure is only {tenure:g} years.", idx.eid("manager_tenure_years"),
            "manager_tenure_years")
    elif tenure is None:
        add(None, ChallengeType.MISSING_EVIDENCE, Severity.LOW,
            "Manager tenure evidence is unavailable.", [], "manager_tenure_years")

    for f in ("return_5y", "return_3y"):
        r = idx.number(f)
        if r is not None:
            if r <= 0:
                add(None, ChallengeType.RISK_CONCERN, Severity.MEDIUM,
                    f"Annualized return {f} is {r:g}%.", idx.eid(f), f)
            break

    qs = sget(state, "quality_score")
    if qs is not None and float(qs) < 0.8:
        add(None, ChallengeType.WEAK_EVIDENCE, Severity.MEDIUM,
            f"Data quality score is {float(qs):.2f}; evidence reliability is reduced.", [], "quality_score")

    high = sum(1 for c in out if c.severity == Severity.HIGH)
    med = sum(1 for c in out if c.severity == Severity.MEDIUM)
    if high or med >= 2:
        position, rec = Position.CHALLENGE, Status.REVIEW
    else:
        position, rec = Position.NO_MATERIAL_OBJECTION, Status.PASS
    evidence_ok = len(idx.records) >= 3
    confidence = 0.9 if evidence_ok else 0.45
    if high == 0 and med == 0 and not evidence_ok:
        confidence = 0.4
    questions = [c.reason for c in out if c.challenge_type == ChallengeType.MISSING_EVIDENCE]
    return ChallengerResult(
        position=position, recommended_status=rec, confidence=confidence, challenges=out,
        unresolved_questions=questions,
        rationale=f"{len(out)} challenges ({high} high, {med} medium severity).",
        generation_mode="mock",
    )


def _postprocess(data: dict) -> dict:
    ch = [{**c, "challenge_id": f"CHAL-{i:02d}"} for i, c in enumerate(data.get("challenges", []), 1)]
    return {**data, "challenges": ch, "generation_mode": llm_bridge.provider_name()}


CHALLENGER_SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "position": {"type": "string", "enum": ["CHALLENGE", "NO_MATERIAL_OBJECTION"]},
        "recommended_status": {"type": "string", "enum": ["PASS", "REVIEW", "REJECT"]},
        "confidence": {"type": "number"},
        "challenges": {"type": "array", "items": {"type": "object", "properties": {
            "target_claim": {"type": ["string", "null"]},
            "challenge_type": {"type": "string", "enum": [t.value for t in ChallengeType]},
            "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "reason": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "field": {"type": "string"}},
            "required": ["challenge_type", "severity", "reason"]}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["position", "recommended_status", "confidence", "challenges"],
}


def _mock_with_trace(state: Any, tools: ReviewTools) -> ChallengerResult:
    """Deterministic stand-in that investigates through the real tools, so the trace is real."""
    prop = _proponent(state)
    tools.call("list_evidence")
    tools.call("get_mandate")
    for c in (prop.claims if prop else []):
        tools.call("verify_claim", {"claim": c.claim, "evidence_ids": c.evidence_ids,
                                    "cited_values": [cv.model_dump() for cv in c.cited_values]})
    for rule_id in ("COST-001", "SUIT-001", "SUIT-002"):
        tools.call("check_rule", {"rule_id": rule_id})
    result = _mock(state)
    tools.record("submit_challenges", {}, f"{len(result.challenges)} challenges submitted")
    return result


def _tool_use(state: Any, tools: ReviewTools, prompts: dict, prop) -> ChallengerResult:
    from src.agents.tool_agent import run_tool_agent
    user = json.dumps({
        "task": "Attempt to falsify the Proponent's case. Target specific claim_ids.",
        "case_id": sget(state, "case_id"),
        "required_evidence_fields": config_loader.rules().get("required_evidence", []),
        "proponent_position": prop.position.value if prop else None,
        "proponent_claims": [c.model_dump(mode="json", exclude={"confidence"}) for c in prop.claims] if prop else [],
    }, default=str)
    return run_tool_agent(
        tools=tools, system=prompts["challenger"]["system"] + "\n" + prompts["tool_mode_addendum"],
        user=user, tool_names=["list_evidence", "get_evidence", "get_mandate", "list_rules", "check_rule", "verify_claim"],
        submit_name="submit_challenges", submit_description="Submit your challenges.",
        submit_schema=CHALLENGER_SUBMIT_SCHEMA,
        validate=lambda d: ChallengerResult.model_validate(_postprocess(d)),
    )


def run_challenger(state: Any) -> ChallengerResult:
    from src.agents.tool_agent import agent_mode
    timer = run_log.Timer()
    idx = EvidenceIndex(state)
    prompts = config_loader.prompts()
    prop = _proponent(state)
    tools = ReviewTools(state, "challenger")
    payload = {
        "case_id": sget(state, "case_id"),
        "mandate": config_loader.resolve_mandate(sget(state, "mandate")),
        "quality_score": sget(state, "quality_score"),
        "required_evidence": config_loader.rules().get("required_evidence", []),
        "evidence": idx.compact_summary(),
        "proponent_claims": [c.model_dump() for c in prop.claims] if prop else [],
        "proponent_position": prop.position.value if prop else None,
    }
    try:
        if llm_bridge.provider_name() == "mock":
            result = _mock_with_trace(state, tools)
        elif agent_mode() == "tool_use":
            result = _tool_use(state, tools, prompts, prop)
        else:
            result = llm_bridge.generate(
                agent="challenger", system=prompts["challenger"]["system"], payload=payload,
                model=ChallengerResult, mock_fn=lambda: _mock(state), postprocess=_postprocess,
            )
    except llm_bridge.LLMError as exc:
        result = ChallengerResult(
            position=Position.CHALLENGE, recommended_status=Status.REVIEW, confidence=0.0,
            challenges=[], rationale="Challenger could not produce a validated result; escalate.",
            generation_mode=llm_bridge.provider_name(), llm_error=str(exc),
        )
    result.prompt_version = prompts.get("prompt_version")
    result.trace = tools.trace
    return run_log.attach(result, "challenger", state, timer, [c.challenge_id for c in result.challenges],
                          llm=True, prompt_version=result.prompt_version)
