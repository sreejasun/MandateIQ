"""Seeded WorkflowState fixtures for the review/governance modules.

These stand in for the Data Steward's output (Evidence Ledger) so Dileep's modules can be
built and tested independently. Values are SYNTHETIC.
"""
from __future__ import annotations

import copy

_BASE_FIELDS = {
    "expense_ratio": 0.45,
    "expense_ratio_percentile": 30,
    "asset_class": "Equity",
    "category": "Large Blend",
    "risk_level": "medium",
    "history_years": 12,
    "manager_tenure_years": 8,
    "return_5y": 9.4,
    "volatility": 15.2,
}


def _ledger(case_id: str, fields: dict) -> list[dict]:
    out = []
    for i, (f, v) in enumerate(fields.items(), start=1):
        out.append({
            "evidence_id": f"EV-{i:03d}", "case_id": case_id, "source": "computed_metric",
            "field": f, "value": v, "calculation": "raw field validation",
            "created_by": "finance_metrics_tool", "timestamp": "2026-09-23T00:00:00Z", "metadata": {},
        })
    return out


def make_state(case_id: str, fields: dict | None = None, quality_score: float = 0.95,
               mandate: str | dict | None = "balanced_growth", metadata: dict | None = None) -> dict:
    f = copy.deepcopy(_BASE_FIELDS if fields is None else fields)
    return {
        "case_id": case_id, "dataset_uri": None,
        "fund_record": {"ticker": "SYNX", "fund_name": "Synthetic Large Blend Fund"},
        "mandate": mandate, "metadata": metadata or {}, "data_profile": {}, "quality_report": {},
        "quality_score": quality_score, "transformation_log": [], "computed_metrics": {},
        "evidence_ledger": _ledger(case_id, f),
        "proponent_result": None, "challenger_result": None, "policy_result": None,
        "claim_verifications": [], "hallucination_flags": [], "firewall_status": None,
        "trust_score": None, "trust_components": {}, "disagreements": [], "risk_flags": [],
        "agent_confidences": {}, "route_history": [], "retry_count": 0,
        "supervisor_result": None, "human_review_required": False, "human_review_reason": None,
        "final_status": None, "final_rationale": None, "sandbox_original": None,
        "sandbox_counterfactual": None, "model_version": None,
        "prompt_version": "review-prompts-v1.0", "rule_version": "rules-v1.1",
    }


def case_a_clean() -> dict:
    """A — clean agreement: everything within mandate, good data."""
    return make_state("CASE-A")


def case_b_unsupported_claim() -> dict:
    """B — Proponent makes a claim citing evidence that does not exist, and misquotes a value."""
    return make_state("CASE-B", metadata={"demo_injections": {"proponent_claims": [
        {"claim": "[SEEDED] Fund ranked top-decile by Morningstar for 10 straight years.",
         "evidence_ids": ["EV-999"], "field": "rating"},
        {"claim": "[SEEDED] Expense ratio is only 0.15%, far below peers.",
         "evidence_ids": ["EV-001"], "cited_values": [{"evidence_id": "EV-001", "value": 0.15}],
         "field": "expense_ratio"},
    ]}})


def case_c_policy_failure() -> dict:
    """C — hard policy failure: negative expense ratio + disallowed asset class."""
    f = dict(_BASE_FIELDS, expense_ratio=-0.20, asset_class="Commodity")
    return make_state("CASE-C", f)


def case_e_low_evidence() -> dict:
    """E — insufficient evidence: required fields missing, weak data quality."""
    f = {"expense_ratio": 0.70, "category": "Large Growth"}
    return make_state("CASE-E", f, quality_score=0.62)


def case_high_fee_review() -> dict:
    """Extra — cost concern: fee above mandate and in the high-fee tail."""
    f = dict(_BASE_FIELDS, expense_ratio=1.25, expense_ratio_percentile=88)
    return make_state("CASE-FEE", f)


def case_f_persistent_disagreement() -> dict:
    """F - the expense ratio was IMPUTED by the Data Steward. The Proponent relies on it, the
    Challenger objects (HIGH, required field), the Proponent has no independent evidence and
    defends; the Challenger maintains -> debate ends without agreement -> human review."""
    s = make_state("CASE-F")
    for rec in s["evidence_ledger"]:
        if rec["field"] == "expense_ratio":
            rec["metadata"] = {"imputed": True, "note": "filled from category median"}
    return s
