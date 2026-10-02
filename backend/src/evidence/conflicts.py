"""Conflict detection between the Proponent, Challenger and Policy review.

Contract: detect_conflicts(state, firewall=None) -> list[Conflict]
A conflict is MATERIAL when it should stop straight-through finalization:
  * a HIGH-severity challenge against a Proponent claim,
  * any challenge the Firewall independently confirms (claim blocked),
  * Proponent recommends PASS while a policy dimension FAILs,
  * Proponent SUPPORT vs Challenger CHALLENGE with REVIEW/REJECT recommendation.
"""
from __future__ import annotations

from typing import Any, Optional

from src.evidence.claims import (
    ChallengerResult, ClaimVerificationResult, Conflict, PolicyResult, Position, ProponentResult,
    Severity, Status,
)
from src.evidence.verifier import sget


def _load(raw, model):
    if raw is None:
        return None
    return raw if isinstance(raw, model) else model.model_validate(raw)


def detect_conflicts(state: Any, firewall: Optional[ClaimVerificationResult] = None) -> list[Conflict]:
    prop = _load(sget(state, "proponent_result"), ProponentResult)
    chal = _load(sget(state, "challenger_result"), ChallengerResult)
    pol = _load(sget(state, "policy_result"), PolicyResult)
    blocked = set(firewall.blocked_claim_ids) if firewall else set()
    out: list[Conflict] = []

    def add(ctype, material, sev, desc, claim_ids=(), eids=(), confirmed=False):
        out.append(Conflict(conflict_id=f"CONF-{len(out) + 1:02d}", conflict_type=ctype,
                            material=material, severity=sev, description=desc,
                            claim_ids=list(claim_ids), evidence_ids=list(eids),
                            confirmed_by_firewall=confirmed))

    # Position-level disagreement. Material only when the Challenger has at least one HIGH
    # finding (factual error, unsupported claim, rule/mandate breach, missing required
    # evidence) — judged by its findings, not by the label an LLM happens to choose, so
    # context requests ("no benchmark given") cannot force re-analysis of a clean case.
    if prop and chal and prop.recommended_status == Status.PASS and chal.recommended_status != Status.PASS:
        highs = sum(c.severity == Severity.HIGH for c in chal.challenges)
        mediums = sum(c.severity == Severity.MEDIUM for c in chal.challenges)
        substantive = highs >= 1
        add("POSITION_DISAGREEMENT", substantive, Severity.HIGH if substantive else Severity.LOW,
            f"Proponent recommends {prop.recommended_status.value} ({prop.position.value}); "
            f"Challenger recommends {chal.recommended_status.value} ({chal.position.value}) "
            f"with {highs} high / {mediums} medium findings"
            + ("." if substantive else " — minor objections only, not material."))

    # Claim-level challenges
    for ch in (chal.challenges if chal else []):
        if not ch.target_claim:
            continue
        confirmed = ch.target_claim in blocked
        material = confirmed or ch.severity == Severity.HIGH
        add("CLAIM_CHALLENGED", material, Severity.HIGH if confirmed else ch.severity,
            f"{ch.challenge_id} challenges {ch.target_claim} ({ch.challenge_type.value}): {ch.reason}"
            + (" Firewall confirms the claim is not verified." if confirmed else "")
            + (f" RESOLVED - {ch.resolution}" if ch.resolved else ""),
            [ch.target_claim, ch.challenge_id], ch.evidence_ids, confirmed)
        out[-1].resolved = ch.resolved

    # Firewall-blocked Proponent claims that the Challenger did NOT catch
    targeted = {ch.target_claim for ch in (chal.challenges if chal else []) if ch.target_claim}
    for cid in sorted(blocked - targeted):
        if cid.startswith("PROP-"):
            add("UNCHALLENGED_UNVERIFIED_CLAIM", True, Severity.HIGH,
                f"{cid} failed firewall verification and was not caught by the Challenger.",
                [cid], confirmed=True)

    # Proponent vs deterministic policy
    if prop and pol and prop.recommended_status == Status.PASS:
        failed_dims = [d for d, s in (("policy", pol.policy_status), ("cost", pol.cost_status),
                                      ("suitability", pol.suitability_status)) if s == Status.FAIL]
        review_dims = [d for d, s in (("policy", pol.policy_status), ("cost", pol.cost_status),
                                      ("suitability", pol.suitability_status)) if s == Status.REVIEW]
        if failed_dims:
            add("POLICY_VS_PROPONENT", True, Severity.HIGH,
                f"Proponent recommends PASS but deterministic {', '.join(failed_dims)} check(s) FAILED.",
                eids=pol.evidence_ids)
        elif review_dims:
            add("POLICY_VS_PROPONENT", False, Severity.MEDIUM,
                f"Proponent recommends PASS but {', '.join(review_dims)} status is REVIEW.",
                eids=pol.evidence_ids)

    # Large confidence gap between the two agents
    if prop and chal and abs(prop.confidence - chal.confidence) >= 0.4:
        add("CONFIDENCE_GAP", False, Severity.LOW,
            f"Agent confidence differs sharply (Proponent {prop.confidence:.2f} vs "
            f"Challenger {chal.confidence:.2f}).")
    return out


def disagreement_is_material(conflicts: list[Conflict]) -> bool:
    return any(c.material and not c.resolved for c in conflicts)
