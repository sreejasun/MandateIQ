"""Hallucination Firewall — deterministic verification of agent claims BEFORE routing.

Contract: verify_agent_claims(state) -> ClaimVerificationResult

Checks (per claim / challenge):
  * evidence IDs are cited at all
  * every cited evidence ID exists in the ledger            -> INVALID_REFERENCE
  * every cited evidence ID belongs to this case            -> FOREIGN_EVIDENCE
  * every cited numeric/label value matches the stored value -> CONTRADICTED
  * a cited value's evidence ID is also in evidence_ids      -> UNSUPPORTED
  * every number written in a Proponent claim's TEXT appears in the ledger or the
    mandate/rule config (catches misquoted numbers even when the model omits
    cited_values)                                             -> UNSUPPORTED
Case-level checks:
  * required evidence present                                -> MISSING_REQUIRED_EVIDENCE
  * agent outputs passed schema validation / no LLM errors   -> SCHEMA_INVALID
Blocked claims are listed so the Supervisor and Trust Score never count them as support.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from src import config_loader
from src.evidence.claims import (
    AgentClaim, ChallengerResult, ClaimVerification, ClaimVerificationResult, FirewallStatus,
    HallucinationFlag, ProponentResult, VerificationStatus,
)
from src.evidence.verifier import EvidenceIndex, as_number, norm_label, sget


def _load(raw: Any, model):
    if raw is None:
        return None
    return raw if isinstance(raw, model) else model.model_validate(raw)


def values_match(cited: Any, stored: Any) -> bool:
    a, b = as_number(cited), as_number(stored)
    if a is None or b is None:
        return norm_label(cited) == norm_label(stored)
    tol = config_loader.firewall_config()["numeric_tolerance"]
    return abs(a - b) <= tol["absolute"] or (b != 0 and abs(a - b) / abs(b) <= tol["relative"])


_ID_TOKEN = re.compile(r"\b(?:EV|PROP|CHAL|CONF|HF|CASE)-[A-Za-z0-9-]+\b|\b\w*_\w*\b")
_NUMBER = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)(\s*-?\s*(?:year|yr)s?\b)?", re.I)


def _allowed_numbers(idx: EvidenceIndex, mandate: dict) -> list[float]:
    """Numbers a claim may legitimately quote: ledger values, mandate values, rule thresholds."""
    vals: list[float] = []
    for r in idx.records:
        n = as_number(r.get("value"))
        if n is not None:
            vals.append(n)
    for v in list(mandate.values()) + list(config_loader.rules().get("thresholds", {}).values()):
        n = as_number(v)
        if n is not None:
            vals.append(n)
    return vals


def unverified_numbers(text: str, allowed: Iterable[float]) -> list[str]:
    """Numbers in claim text that match no allowed value (within tolerance).
    Ignores evidence/claim IDs, field names like return_5y, small 'N-year' horizon labels,
    and calendar years."""
    allowed = list(allowed)
    cleaned = _ID_TOKEN.sub(" ", text or "")
    bad = []
    for m in _NUMBER.finditer(cleaned):
        raw, year_suffix = m.group(1), m.group(2)
        num = float(raw)
        if year_suffix and 0 < num <= 10:        # "5-year return", "3-year minimum"
            continue
        if 1900 <= num <= 2100 and "." not in raw:  # calendar year
            continue
        if not any(values_match(num, a) for a in allowed):
            bad.append(raw)
    return bad


def _verify_claim(c: AgentClaim, idx: EvidenceIndex, allowed: list[float] | None = None) -> ClaimVerification:
    checks, problems = [], []
    status = VerificationStatus.VERIFIED
    if not c.evidence_ids:
        return ClaimVerification(claim_id=c.claim_id, agent=c.agent,
                                 status=VerificationStatus.NO_EVIDENCE_CITED,
                                 checks=["evidence cited: no"], problems=["Claim cites no evidence."])
    for e in c.evidence_ids:
        if idx.get(e) is None:
            problems.append(f"{e} does not exist in the Evidence Ledger.")
            status = VerificationStatus.INVALID_REFERENCE
        elif not idx.belongs_to_case(e):
            problems.append(f"{e} belongs to case {idx.get(e).get('case_id')}, not {idx.case_id}.")
            if status == VerificationStatus.VERIFIED:
                status = VerificationStatus.FOREIGN_EVIDENCE
        else:
            checks.append(f"{e} exists and belongs to case")
    for cv in c.cited_values:
        rec = idx.get(cv.evidence_id)
        if rec is None:
            if cv.evidence_id not in c.evidence_ids:
                problems.append(f"Cited value references unknown {cv.evidence_id}.")
                status = VerificationStatus.INVALID_REFERENCE
            continue
        if cv.evidence_id not in c.evidence_ids:
            problems.append(f"Value cited from {cv.evidence_id} which is not in the claim's evidence list.")
            if status == VerificationStatus.VERIFIED:
                status = VerificationStatus.UNSUPPORTED
        if values_match(cv.value, rec.get("value")):
            checks.append(f"{cv.evidence_id}: cited {cv.value} matches stored {rec.get('value')}")
        else:
            problems.append(f"{cv.evidence_id}: cited {cv.value} but ledger records {rec.get('value')}.")
            if status in (VerificationStatus.VERIFIED, VerificationStatus.UNSUPPORTED):
                status = VerificationStatus.CONTRADICTED
    if allowed is not None:
        bad = unverified_numbers(c.claim, allowed)
        if bad:
            problems.append(f"Number(s) {', '.join(bad)} in the claim text are not found in the "
                            f"Evidence Ledger or mandate.")
            if status == VerificationStatus.VERIFIED:
                status = VerificationStatus.UNSUPPORTED
        else:
            checks.append("all numbers in claim text match ledger/mandate values")
    return ClaimVerification(claim_id=c.claim_id, agent=c.agent, status=status,
                             checks=checks, problems=problems, evidence_ids=list(c.evidence_ids))


def verify_agent_claims(state: Any) -> ClaimVerificationResult:
    cfg = config_loader.firewall_config()
    idx = EvidenceIndex(state)
    prop = _load(sget(state, "proponent_result"), ProponentResult)
    chal = _load(sget(state, "challenger_result"), ChallengerResult)

    claims: list[AgentClaim] = list(prop.claims) if prop else []
    # Challenger challenges are verified too (the Challenger can hallucinate as well).
    for ch in (chal.challenges if chal else []):
        if ch.evidence_ids:
            claims.append(AgentClaim(claim_id=ch.challenge_id, agent="challenger",
                                     claim=ch.reason, evidence_ids=ch.evidence_ids, field=ch.field))

    mandate = config_loader.resolve_mandate(sget(state, "mandate"))
    allowed = _allowed_numbers(idx, mandate)
    # Text-number check applies to Proponent claims (the ones that argue for approval).
    verifications = [_verify_claim(c, idx, allowed if c.agent == "proponent" else None) for c in claims]
    fail_codes, warn_codes = set(cfg["fail_on"]), set(cfg["warn_on"])
    flags: list[HallucinationFlag] = []

    def flag(code: str, detail: str, agent=None, claim_id=None):
        flags.append(HallucinationFlag(flag_id=f"HF-{len(flags) + 1:02d}", code=code, agent=agent,
                                       claim_id=claim_id, detail=detail, blocking=code in fail_codes))

    for v in verifications:
        if v.status != VerificationStatus.VERIFIED:
            flag(v.status.value, " ".join(v.problems) or v.status.value, v.agent, v.claim_id)

    missing = [f for f in config_loader.rules().get("required_evidence", []) if not idx.has(f)]
    for f in missing:
        flag("MISSING_REQUIRED_EVIDENCE", f"Required evidence '{f}' is not in the ledger.")

    for name, res in (("proponent", prop), ("challenger", chal)):
        if res is not None and res.llm_error:
            flag("SCHEMA_INVALID", f"{name} output invalid: {res.llm_error}", name)

    codes = {f.code for f in flags}
    if codes & fail_codes:
        status = FirewallStatus.FAIL
    elif codes & warn_codes:
        status = FirewallStatus.WARN
    else:
        status = FirewallStatus.PASS

    verified = [v.claim_id for v in verifications if v.status == VerificationStatus.VERIFIED]
    blocked = [v.claim_id for v in verifications if v.status != VerificationStatus.VERIFIED]
    return ClaimVerificationResult(
        firewall_status=status, verifications=verifications, flags=flags,
        verified_claim_ids=verified, blocked_claim_ids=blocked,
        missing_required_evidence=missing, firewall_version=cfg.get("firewall_version", "unknown"),
    )
