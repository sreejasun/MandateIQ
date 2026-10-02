"""One-call governance step for the orchestration graph.

    updates = run_governance(state)
    state.update(updates)          # or merge into the LangGraph state

Runs Firewall -> Conflict Detection -> Trust Score in order and returns ONLY WorkflowState keys
(plus `governance_gate`, a proposed state key the Supervisor can read directly).
Call it after proponent, challenger and policy results are in state.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.evidence.claims import Gate, PolicyResult
from src.evidence.conflicts import detect_conflicts
from src.evidence.verifier import sget
from src.trust.hallucination_firewall import verify_agent_claims
from src.trust.trust_score import calculate_trust_score


def run_governance(state: Any) -> dict:
    fw = verify_agent_claims(state)
    conflicts = detect_conflicts(state, fw)
    trust = calculate_trust_score(state, fw, conflicts)

    risk_flags = list(sget(state, "risk_flags", []) or [])
    pol = sget(state, "policy_result")
    if pol is not None:
        pol = pol if isinstance(pol, PolicyResult) else PolicyResult.model_validate(pol)
        risk_flags += [f for f in pol.risk_flags if f not in risk_flags]

    confidences = dict(sget(state, "agent_confidences", {}) or {})
    for name in ("proponent_result", "challenger_result", "policy_result"):
        r = sget(state, name)
        if r is not None:
            conf = r.get("confidence") if isinstance(r, dict) else getattr(r, "confidence", None)
            confidences[name.replace("_result", "")] = conf

    update = {
        "claim_verifications": [v.model_dump(mode="json") for v in fw.verifications],
        "hallucination_flags": [f.model_dump(mode="json") for f in fw.flags],
        "firewall_status": fw.firewall_status.value,
        "disagreements": [c.model_dump(mode="json") for c in conflicts],
        "trust_score": trust.score,
        "trust_components": {k: v.model_dump(mode="json") for k, v in trust.components.items()},
        "risk_flags": risk_flags,
        "agent_confidences": confidences,
        "governance_gate": {
            "gate": trust.recommended_gate.value,
            "reasons": trust.gate_reasons,
            "band": trust.band,
            "raw_score": trust.raw_score,
            "caps_applied": trust.caps_applied,
            "blocked_claim_ids": fw.blocked_claim_ids,
            "material_conflicts": sum(c.material and not c.resolved for c in conflicts),
        },
    }
    debate = sget(state, "debate")
    if debate:
        update["governance_gate"]["debate"] = {
            "rounds": debate.get("total_rounds"), "converged": debate.get("converged"),
            "stop_reason": debate.get("stop_reason"),
            "withdrawn_claim_ids": [w["claim_id"] for w in debate.get("withdrawn_claims", [])],
            "resolved_challenge_ids": debate.get("resolved_challenge_ids", []),
            "open_challenge_ids": debate.get("open_challenge_ids", []),
        }
    logging.getLogger("mandateiq.review").info(json.dumps({
        "event": "governance", "case_id": sget(state, "case_id"),
        "firewall_status": fw.firewall_status.value, "trust_score": trust.score,
        "gate": trust.recommended_gate.value, "blocked_claim_ids": fw.blocked_claim_ids,
        "material_conflicts": update["governance_gate"]["material_conflicts"],
        "trust_version": trust.trust_version, "firewall_version": fw.firewall_version}))
    if trust.recommended_gate == Gate.HUMAN_REVIEW_REQUIRED:
        update["human_review_required"] = True
        update["human_review_reason"] = "; ".join(trust.gate_reasons)
    return update
