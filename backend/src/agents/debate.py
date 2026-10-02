"""Multi-round adversarial debate between the Proponent and the Risk Challenger.

    updates = run_committee(state)     # {"proponent_result", "challenger_result", "debate"}
    state.update(updates)

Round 1 (opening): Proponent builds its case, Challenger attacks it.
Round 2..N (rebuttal): for every OPEN challenge (HIGH severity against a claim, or a claim the
Hallucination Firewall blocked) the Proponent must CONCEDE, DEFEND with new evidence, or
REVISE the claim; the Challenger then ACCEPTs or MAINTAINs each objection.
Stops when no open challenges remain (converged) or at max_rounds (not converged -> the
governance gate escalates to human review). Bounded by config/agents.yaml.
"""
from __future__ import annotations

import json
from typing import Any

from src import config_loader
from src.agents import llm_bridge
from src.agents.challenger import run_challenger
from src.agents.proponent import run_proponent
from src.agents.tools import ReviewTools
from src.evidence.claims import (
    AgentClaim, Challenge, ChallengerResult, ChallengeType, CitedValue, DebateResult, DebateRound,
    Position, ProponentResult, Rebuttal, Severity, Status, Verdict, WithdrawnClaim,
)
from src.evidence.verifier import sget
from src.trust.hallucination_firewall import verify_agent_claims

REBUTTAL_SCHEMA = {
    "type": "object",
    "properties": {"rebuttals": {"type": "array", "items": {"type": "object", "properties": {
        "challenge_id": {"type": "string"},
        "action": {"type": "string", "enum": ["CONCEDE", "DEFEND", "REVISE"]},
        "response": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "revised_claim": {"type": "string"},
        "cited_values": {"type": "array", "items": {"type": "object", "properties": {
            "evidence_id": {"type": "string"}, "value": {}}}}},
        "required": ["challenge_id", "action", "response"]}}},
    "required": ["rebuttals"],
}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "challenge_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["ACCEPT", "MAINTAIN"]},
        "reason": {"type": "string"}},
        "required": ["challenge_id", "verdict", "reason"]}}},
    "required": ["verdicts"],
}
TOOLS = ["list_evidence", "get_evidence", "get_mandate", "list_rules", "check_rule", "verify_claim"]


def _cfg() -> dict:
    return config_loader.load("agents.yaml").get("debate", {})


def _with(state: Any, **kv) -> dict:
    base = dict(state) if isinstance(state, dict) else state.model_dump()
    base.update({k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v) for k, v in kv.items()})
    return base


def _open_challenges(chal: ChallengerResult, prop: ProponentResult, blocked: set[str],
                     severities: set[str]) -> list[Challenge]:
    live = {c.claim_id for c in prop.claims}
    return [c for c in chal.challenges
            if not c.resolved and c.target_claim in live
            and (c.severity.value in severities or c.target_claim in blocked)]


def _firewall_challenges(chal: ChallengerResult, prop: ProponentResult, fw) -> None:
    """Blocked claims the Challenger missed get a synthetic FIREWALL challenge so they must be answered."""
    targeted = {c.target_claim for c in chal.challenges if not c.resolved}
    problems = {v.claim_id: " ".join(v.problems) for v in fw.verifications}
    for cid in fw.blocked_claim_ids:
        if cid.startswith("PROP-") and cid not in targeted and cid in {c.claim_id for c in prop.claims}:
            chal.challenges.append(Challenge(
                challenge_id=f"FW-{cid}", target_claim=cid, challenge_type=ChallengeType.UNSUPPORTED,
                severity=Severity.HIGH, reason=f"Hallucination Firewall: {problems.get(cid, 'unverified')}"))


# ------------------------------------------------------------------ mock (deterministic) turns
def _mock_rebuttals(state, prop, open_, tools: ReviewTools) -> list[Rebuttal]:
    claims = {c.claim_id: c for c in prop.claims}
    out = []
    for ch in open_:
        c = claims[ch.target_claim]
        v, _ = tools.call("verify_claim", {"claim": c.claim, "evidence_ids": c.evidence_ids,
                                           "cited_values": [x.model_dump() for x in c.cited_values]})
        if v.get("status") != "VERIFIED" or ch.challenge_type in (ChallengeType.UNSUPPORTED,
                                                                   ChallengeType.CONTRADICTED):
            out.append(Rebuttal(challenge_id=ch.challenge_id, target_claim=c.claim_id, action="CONCEDE",
                                response=f"Conceded: the claim did not verify ({v.get('status')})."))
            continue
        # Look for independent, unflagged evidence for the same field.
        ev, _ = tools.call("list_evidence")
        alt = [e["evidence_id"] for e in ev["evidence"]
               if tools.idx.canonical(e["field"] or "") == (c.field or "")
               and e["evidence_id"] not in c.evidence_ids and not e["flagged"]]
        out.append(Rebuttal(
            challenge_id=ch.challenge_id, target_claim=c.claim_id, action="DEFEND",
            response=("Defended with independent evidence." if alt else
                      "Defended: the cited value matches the ledger and satisfies the mandate."),
            evidence_ids=alt or list(c.evidence_ids)))
    tools.record("submit_rebuttals", {}, f"{len(out)} rebuttals")
    return out


def _mock_verdicts(state, prop, open_, rebuttals, tools: ReviewTools) -> list[Verdict]:
    claims = {c.claim_id: c for c in prop.claims}
    chal_by_id = {c.challenge_id: c for c in open_}
    out = []
    for r in rebuttals:
        if r.action == "CONCEDE":
            out.append(Verdict(challenge_id=r.challenge_id, verdict="ACCEPT", reason="Claim withdrawn."))
            continue
        orig = claims.get(r.target_claim)
        new_ids = [e for e in r.evidence_ids if orig is None or e not in orig.evidence_ids]
        text = r.revised_claim or (orig.claim if orig else "")
        v, _ = tools.call("verify_claim", {"claim": text, "evidence_ids": r.evidence_ids or
                                           (orig.evidence_ids if orig else [])})
        fresh_ok = bool(new_ids) and not any(tools.idx.is_flagged(e) for e in new_ids)
        if v.get("status") == "VERIFIED" and (fresh_ok or r.action == "REVISE" and
                                              chal_by_id[r.challenge_id].challenge_type != ChallengeType.WEAK_EVIDENCE):
            out.append(Verdict(challenge_id=r.challenge_id, verdict="ACCEPT",
                               reason="Answered with verified, unflagged evidence."))
        else:
            out.append(Verdict(challenge_id=r.challenge_id, verdict="MAINTAIN",
                               reason="No new unflagged evidence; the objection still stands."))
    tools.record("submit_verdicts", {}, f"{len(out)} verdicts")
    return out


# ------------------------------------------------------------------ bedrock (tool-use) turns
def _llm_rebuttals(state, prop, open_, fw, tools: ReviewTools, rnd: int) -> list[Rebuttal]:
    from src.agents.tool_agent import run_tool_agent
    p = config_loader.prompts()
    ids = {c.challenge_id for c in open_}
    user = json.dumps({
        "your_claims": [c.model_dump(mode="json", exclude={"confidence"}) for c in prop.claims],
        "open_challenges": [c.model_dump(mode="json") for c in open_],
        "firewall_findings": [v.model_dump(mode="json") for v in fw.verifications
                              if v.claim_id in {c.target_claim for c in open_}],
    }, default=str)

    def validate(d):
        rs = [Rebuttal(**{**r, "target_claim": next(c.target_claim for c in open_
                                                     if c.challenge_id == r["challenge_id"])})
              for r in d["rebuttals"] if r.get("challenge_id") in ids]
        missing = ids - {r.challenge_id for r in rs}
        if missing:
            raise ValueError(f"missing rebuttals for {sorted(missing)}")
        return rs
    return run_tool_agent(tools=tools, system=p["proponent_rebuttal"]["system"].format(round=rnd),
                          user=user, tool_names=TOOLS, submit_name="submit_rebuttals",
                          submit_description="Submit one rebuttal per open challenge.",
                          submit_schema=REBUTTAL_SCHEMA, validate=validate)


def _llm_verdicts(state, prop, open_, rebuttals, tools: ReviewTools, rnd: int) -> list[Verdict]:
    from src.agents.tool_agent import run_tool_agent
    p = config_loader.prompts()
    ids = {r.challenge_id for r in rebuttals}
    user = json.dumps({
        "your_challenges": [c.model_dump(mode="json") for c in open_],
        "proponent_rebuttals": [r.model_dump(mode="json") for r in rebuttals],
        "claims_under_dispute": [c.model_dump(mode="json", exclude={"confidence"}) for c in prop.claims
                                 if c.claim_id in {r.target_claim for r in rebuttals}],
    }, default=str)

    def validate(d):
        vs = [Verdict(**v) for v in d["verdicts"] if v.get("challenge_id") in ids]
        missing = ids - {v.challenge_id for v in vs}
        if missing:
            raise ValueError(f"missing verdicts for {sorted(missing)}")
        return vs
    return run_tool_agent(tools=tools, system=p["challenger_verdict"]["system"].format(round=rnd),
                          user=user, tool_names=TOOLS, submit_name="submit_verdicts",
                          submit_description="Submit one verdict per rebuttal.",
                          submit_schema=VERDICT_SCHEMA, validate=validate)


# ------------------------------------------------------------------ apply outcomes
def _apply(prop: ProponentResult, chal: ChallengerResult, rebuttals, verdicts, fw, rnd,
           result: DebateResult) -> None:
    status = {v.claim_id: v.status.value for v in fw.verifications}
    verdict = {v.challenge_id: v for v in verdicts}
    by_id = {c.claim_id: c for c in prop.claims}
    for r in rebuttals:
        v = verdict.get(r.challenge_id)
        if r.action == "CONCEDE" and r.target_claim in by_id:
            c = by_id.pop(r.target_claim)
            prop.withdrawn_claims.append(c)
            result.withdrawn_claims.append(WithdrawnClaim(
                claim_id=c.claim_id, claim=c.claim, round=rnd, reason=r.response,
                verification_status=status.get(c.claim_id, "VERIFIED")))
        elif r.action == "REVISE" and r.target_claim in by_id and r.revised_claim:
            c = by_id[r.target_claim]
            c.claim, c.evidence_ids = r.revised_claim, (r.evidence_ids or c.evidence_ids)
            c.cited_values = list(r.cited_values)
            result.revised_claim_ids.append(c.claim_id)
        elif r.action == "DEFEND" and r.target_claim in by_id and v and v.verdict == "ACCEPT":
            c = by_id[r.target_claim]
            c.evidence_ids = list(dict.fromkeys(c.evidence_ids + r.evidence_ids))
        if v and v.verdict == "ACCEPT":
            for ch in chal.challenges:
                if ch.challenge_id == r.challenge_id:
                    ch.resolved, ch.resolution = True, f"Round {rnd}: {r.action} accepted: {v.reason}"
                    result.resolved_challenge_ids.append(ch.challenge_id)
    prop.claims = [c for c in prop.claims if c.claim_id in by_id]


def _finalize_positions(prop: ProponentResult, chal: ChallengerResult, result: DebateResult) -> None:
    unresolved_high = [c for c in chal.challenges if not c.resolved and c.severity == Severity.HIGH]
    if unresolved_high:
        chal.position, chal.recommended_status = Position.CHALLENGE, (
            chal.recommended_status if chal.recommended_status != Status.PASS else Status.REVIEW)
    else:
        chal.position, chal.recommended_status = Position.NO_MATERIAL_OBJECTION, Status.PASS
    if result.withdrawn_claims:
        prop.rationale = (f"REVISED in debate: withdrew {len(result.withdrawn_claims)} claim(s) "
                          f"({', '.join(w.claim_id for w in result.withdrawn_claims)}). " + prop.rationale)
    chal.rationale = (f"After {result.total_rounds} debate round(s): {len(result.resolved_challenge_ids)} "
                      f"objection(s) resolved, {len(unresolved_high)} HIGH still open. " + chal.rationale)


# ------------------------------------------------------------------ entry point
def run_committee(state: Any) -> dict:
    """Opening statements + bounded rebuttal rounds. Returns WorkflowState updates."""
    cfg = _cfg()
    enabled, max_rounds = bool(cfg.get("enabled", True)), int(cfg.get("max_rounds", 3))
    severities = set(cfg.get("respond_to_severities", ["HIGH"]))

    prop = run_proponent(state)
    chal = run_challenger(_with(state, proponent_result=prop))
    result = DebateResult(enabled=enabled, max_rounds=max_rounds, converged=True,
                          stop_reason="debate disabled" if not enabled else "no open challenges")
    if enabled and not (prop.llm_error or chal.llm_error):
        mock = llm_bridge.provider_name() == "mock"
        for rnd in range(2, max_rounds + 1):
            fw = verify_agent_claims(_with(state, proponent_result=prop, challenger_result=chal))
            _firewall_challenges(chal, prop, fw)
            open_ = _open_challenges(chal, prop, set(fw.blocked_claim_ids), severities)
            if not open_:
                break
            ptools, ctools = ReviewTools(state, "proponent"), ReviewTools(state, "challenger")
            try:
                rebuttals = (_mock_rebuttals(state, prop, open_, ptools) if mock
                             else _llm_rebuttals(state, prop, open_, fw, ptools, rnd))
                verdicts = (_mock_verdicts(state, prop, open_, rebuttals, ctools) if mock
                            else _llm_verdicts(state, prop, open_, rebuttals, ctools, rnd))
            except llm_bridge.LLMError as exc:
                result.stop_reason = f"debate stopped in round {rnd}: {exc}"
                result.rounds.append(DebateRound(round=rnd, open_challenge_ids=[c.challenge_id for c in open_],
                                                 proponent_trace=ptools.trace, challenger_trace=ctools.trace))
                result.total_rounds = rnd
                break
            result.rounds.append(DebateRound(
                round=rnd, open_challenge_ids=[c.challenge_id for c in open_], rebuttals=rebuttals,
                verdicts=verdicts, firewall_status_before=fw.firewall_status.value,
                blocked_claim_ids_before=fw.blocked_claim_ids,
                proponent_trace=ptools.trace, challenger_trace=ctools.trace))
            result.total_rounds = rnd
            _apply(prop, chal, rebuttals, verdicts, fw, rnd, result)
        # Final check after the last round.
        fw = verify_agent_claims(_with(state, proponent_result=prop, challenger_result=chal))
        _firewall_challenges(chal, prop, fw)
        still_open = _open_challenges(chal, prop, set(fw.blocked_claim_ids), severities)
        result.open_challenge_ids = [c.challenge_id for c in still_open]
        result.converged = not still_open
        if still_open and not result.stop_reason.startswith("debate stopped"):
            result.stop_reason = f"max_rounds ({max_rounds}) reached with {len(still_open)} open challenge(s)"
        elif result.converged and result.total_rounds > 1:
            result.stop_reason = f"converged after {result.total_rounds} round(s)"
        _finalize_positions(prop, chal, result)
    elif enabled:
        result.converged, result.stop_reason = False, "agent error before debate"
    return {"proponent_result": prop.model_dump(mode="json"),
            "challenger_result": chal.model_dump(mode="json"),
            "debate": result.model_dump(mode="json")}
