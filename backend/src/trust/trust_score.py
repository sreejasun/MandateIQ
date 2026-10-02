"""AI Trust Score — deterministic, component-based, 0-100.

Contract: calculate_trust_score(state, firewall=None, conflicts=None) -> TrustScoreResult
Weights, penalties, caps, bands and gates live in config/trust_score.yaml.
The score is a ROUTING INPUT. It never overrides hard policy failures: those apply caps
and force HUMAN_REVIEW_REQUIRED regardless of the numeric score.
"""
from __future__ import annotations

from typing import Any, Optional

from src import config_loader
from src.evidence.claims import (
    ChallengerResult, ClaimVerificationResult, Conflict, FirewallStatus, Gate, PolicyResult,
    ProponentResult, TrustComponent, TrustScoreResult, VerificationStatus,
)
from src.evidence.conflicts import detect_conflicts
from src.evidence.verifier import EvidenceIndex, sget
from src.trust.hallucination_firewall import verify_agent_claims


def _load(raw, model):
    if raw is None:
        return None
    return raw if isinstance(raw, model) else model.model_validate(raw)


def _clamp(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def calculate_trust_score(
    state: Any,
    firewall: Optional[ClaimVerificationResult] = None,
    conflicts: Optional[list[Conflict]] = None,
) -> TrustScoreResult:
    cfg = config_loader.trust_config()
    w, pen, caps = cfg["weights"], cfg["penalties"], cfg["caps"]
    if abs(sum(w.values()) - 1.0) > 1e-6:
        raise ValueError("trust_score.yaml weights must sum to 1.0")

    firewall = firewall or verify_agent_claims(state)
    conflicts = conflicts if conflicts is not None else detect_conflicts(state, firewall)
    prop = _load(sget(state, "proponent_result"), ProponentResult)
    chal = _load(sget(state, "challenger_result"), ChallengerResult)
    pol = _load(sget(state, "policy_result"), PolicyResult)
    idx = EvidenceIndex(state)
    required = config_loader.rules().get("required_evidence", [])
    comps: dict[str, tuple[float, str]] = {}

    # 1. Evidence coverage: required fields present + share of Proponent claims citing evidence
    req_cov = (sum(idx.has(f) for f in required) / len(required)) if required else 1.0
    pclaims = prop.claims if prop else []
    cite_cov = (sum(bool(c.evidence_ids) for c in pclaims) / len(pclaims)) if pclaims else 0.0
    comps["evidence_coverage"] = (
        100 * (0.6 * req_cov + 0.4 * cite_cov),
        f"{sum(idx.has(f) for f in required)}/{len(required)} required fields present; "
        f"{sum(bool(c.evidence_ids) for c in pclaims)}/{len(pclaims)} Proponent claims cite evidence.")

    # 2. Claim verification (Proponent claims + challenger evidence citations)
    vs = firewall.verifications
    debate = sget(state, "debate") or {}
    # Claims withdrawn during the debate still count against verification if they were
    # unverified when withdrawn: self-correction is rewarded, but the hallucination is not erased.
    withdrawn_bad = [w for w in debate.get("withdrawn_claims", []) if w.get("verification_status") != "VERIFIED"]
    if vs or withdrawn_bad:
        bad = sum(pen["contradicted_claim_weight"] if v.status == VerificationStatus.CONTRADICTED else 1
                  for v in vs if v.status != VerificationStatus.VERIFIED) + len(withdrawn_bad)
        score = 100 * max(0.0, 1 - bad / (len(vs) + len(withdrawn_bad)))
        expl = f"{len(firewall.verified_claim_ids)}/{len(vs)} claims verified; {len(firewall.blocked_claim_ids)} blocked."
        if withdrawn_bad:
            expl += f" {len(withdrawn_bad)} unverified claim(s) withdrawn during debate still counted."
    else:
        score, expl = 0.0, "No verifiable claims were produced."
    comps["claim_verification"] = (score, expl)

    # 3. Data quality
    qs = sget(state, "quality_score")
    if qs is None:
        comps["data_quality"] = (pen["missing_data_quality_default"], "No quality score available (default used).")
    else:
        q = float(qs) * (100 if float(qs) <= 1 else 1)
        comps["data_quality"] = (q, f"Data Steward quality score {float(qs):.2f}.")

    # 4. Agent confidence (mean of reasoning agents; min reported)
    confs = {n: r.confidence for n, r in (("proponent", prop), ("challenger", chal), ("policy", pol)) if r}
    if confs:
        comps["agent_confidence"] = (
            100 * sum(confs.values()) / len(confs),
            "Mean confidence " + ", ".join(f"{k}={v:.2f}" for k, v in confs.items())
            + f"; minimum {min(confs.values()):.2f}.")
    else:
        comps["agent_confidence"] = (0.0, "No agent confidences available.")

    # 5. Agreement / conflict
    mat = [c for c in conflicts if c.material and not c.resolved]
    minor = [c for c in conflicts if not c.material and not c.resolved]
    comps["agent_agreement"] = (
        100 - pen["material_conflict_points"] * len(mat) - pen["minor_conflict_points"] * len(minor),
        f"{len(mat)} material and {len(minor)} minor unresolved conflicts.")

    # 6. Policy integrity
    if pol is None:
        comps["policy_integrity"] = (0.0, "Policy review has not run.")
    elif pol.has_critical_failure:
        comps["policy_integrity"] = (0.0, "Critical illustrative rule failed.")
    else:
        failed = [r for r in pol.rule_results if not r.passed]
        major = sum(r.severity == "MAJOR" for r in failed)
        mnr = sum(r.severity == "MINOR" for r in failed)
        comps["policy_integrity"] = (100 - pen["policy_major_points"] * major - pen["policy_minor_points"] * mnr,
                                     f"{major} major and {mnr} minor rule failures.")

    components = {
        name: TrustComponent(name=name, score=_clamp(s), weight=w[name],
                             weighted=round(_clamp(s) * w[name], 2), explanation=e)
        for name, (s, e) in comps.items()
    }
    raw = round(sum(c.weighted for c in components.values()), 1)

    score, caps_applied = raw, []
    critical = bool(pol and pol.has_critical_failure)
    llm_err = any(r is not None and r.llm_error for r in (prop, chal))
    for cond, key, label in ((firewall.firewall_status == FirewallStatus.FAIL, "firewall_fail", "Firewall FAIL"),
                             (critical, "critical_policy_failure", "Critical policy failure"),
                             (llm_err, "llm_error", "Agent output error")):
        if cond and score > caps[key]:
            score = float(caps[key])
            caps_applied.append(f"{label}: capped at {caps[key]}")

    bands = cfg["bands"]
    band = "HIGH" if score >= bands["high"] else "MEDIUM" if score >= bands["medium"] else "LOW"

    gates = cfg["gates"]
    reasons: list[str] = []
    if critical:
        reasons.append("Critical policy failure (hard control).")
    if firewall.missing_required_evidence:
        reasons.append("Required evidence missing: " + ", ".join(firewall.missing_required_evidence) + ".")
    if llm_err:
        reasons.append("An agent failed to produce a validated result.")
    if debate.get("enabled") and not debate.get("converged", True):
        reasons.append(f"Debate ended without agreement after {debate.get('total_rounds')} round(s): "
                       f"open challenge(s) {', '.join(debate.get('open_challenge_ids', [])) or 'n/a'} "
                       f"({debate.get('stop_reason')}).")
    min_conf = gates.get("min_agent_confidence")
    if min_conf is not None and not llm_err:
        low = [f"{n} {r.confidence:.2f}" for n, r in (("Proponent", prop), ("Challenger", chal))
               if r is not None and r.confidence < min_conf]
        if low:
            reasons.append(f"Low agent confidence ({', '.join(low)} < {min_conf}).")
    # Substantive concerns that re-analysis cannot fix: a deterministic control at REVIEW,
    # or HIGH-severity independent risk findings from the Challenger.
    if pol is not None:
        review_dims = [d for d, s in (("policy", pol.policy_status), ("cost", pol.cost_status),
                                      ("suitability", pol.suitability_status)) if s.value == "REVIEW"]
        if review_dims:
            reasons.append(f"Deterministic {', '.join(review_dims)} control(s) at REVIEW.")
    high_risks = [c for c in (chal.challenges if chal else [])
                  if c.target_claim is None and c.severity.value == "HIGH"]
    if high_risks and not critical:
        reasons.append(f"Challenger raised {len(high_risks)} high-severity risk finding(s): "
                       + "; ".join(c.reason for c in high_risks[:3]))
    if reasons:
        gate = Gate.HUMAN_REVIEW_REQUIRED
    elif score >= gates["finalize_min_score"] and firewall.firewall_status == FirewallStatus.PASS and not mat:
        gate = Gate.FINALIZE_ELIGIBLE
        reasons.append(f"Trust {score} >= {gates['finalize_min_score']}, firewall PASS, no material conflicts.")
        if debate.get("total_rounds", 1) > 1:
            reasons.append(f"Committee converged after {debate['total_rounds']} debate rounds"
                           + (f"; Proponent withdrew {len(debate.get('withdrawn_claims', []))} claim(s)."
                              if debate.get("withdrawn_claims") else "."))
    elif score >= gates["reanalysis_min_score"]:
        gate = Gate.REANALYSIS_SUGGESTED
        if firewall.firewall_status != FirewallStatus.PASS:
            reasons.append(f"Firewall {firewall.firewall_status.value}: {len(firewall.blocked_claim_ids)} claim(s) blocked.")
        if mat:
            reasons.append(f"{len(mat)} material conflict(s) may be resolvable by re-analysis.")
        if not reasons:
            reasons.append(f"Trust {score} below finalize threshold {gates['finalize_min_score']}.")
    else:
        gate = Gate.HUMAN_REVIEW_REQUIRED
        reasons.append(f"Trust {score} below re-analysis threshold {gates['reanalysis_min_score']}.")

    return TrustScoreResult(score=score, raw_score=raw, band=band, components=components,
                            caps_applied=caps_applied, recommended_gate=gate, gate_reasons=reasons,
                            trust_version=cfg.get("trust_version", "unknown"))
