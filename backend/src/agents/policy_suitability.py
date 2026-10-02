"""Policy, Cost & Suitability Agent — deterministic illustrative rules.

Contract: run_policy_review(state) -> PolicyResult
Rules, severities and thresholds come from config/rules.yaml and config/mandates.yaml.
No LLM: hard controls must override persuasive language.
"""
from __future__ import annotations

from typing import Any, Callable

from src import config_loader
from src.agents import run_log
from src.evidence.claims import PolicyResult, RuleResult, Status
from src.evidence.verifier import EvidenceIndex, norm_label, risk_rank, sget

Check = Callable[[EvidenceIndex, dict, dict], tuple[bool | None, str, list[str]]]
# returns (passed | None if not evaluable, detail, evidence_ids)


def _required_evidence_present(idx, mandate, cfg):
    missing = [f for f in cfg.get("required_evidence", []) if not idx.has(f)]
    present = idx.ids([f for f in cfg.get("required_evidence", []) if idx.has(f)])
    if missing:
        return False, f"Missing required evidence: {', '.join(missing)}.", present
    return True, "All required evidence present.", present


def _required_evidence_not_imputed(idx, mandate, cfg):
    required = [f for f in cfg.get("required_evidence", []) if idx.has(f)]
    flagged = [f for f in required if idx.is_flagged(idx.eid(f)[0])]
    if flagged:
        return False, (f"Required evidence {', '.join(flagged)} was imputed/flagged by the Data "
                       "Steward and must be confirmed from source data by a human."), idx.ids(flagged)
    return True, "All required evidence comes from source data.", idx.ids(required)


def _expense_ratio_nonnegative(idx, mandate, cfg):
    er = idx.number("expense_ratio")
    if er is None:
        return None, "Expense ratio unavailable.", []
    ok = er >= cfg["thresholds"]["expense_ratio_min"]
    return ok, f"Expense ratio = {er:g}%.", idx.eid("expense_ratio")


def _expense_ratio_plausible(idx, mandate, cfg):
    er = idx.number("expense_ratio")
    if er is None:
        return None, "Expense ratio unavailable.", []
    cap = cfg["thresholds"]["expense_ratio_max_plausible"]
    return er <= cap, f"Expense ratio {er:g}% vs plausible max {cap:g}%.", idx.eid("expense_ratio")


def _asset_class_recognized(idx, mandate, cfg):
    ac = norm_label(idx.value("asset_class"))
    if ac is None:
        return None, "Asset class unavailable.", []
    ok = ac in [norm_label(a) for a in cfg.get("recognized_asset_classes", [])]
    return ok, f"Asset class '{idx.value('asset_class')}'.", idx.eid("asset_class")


def _expense_ratio_within_mandate(idx, mandate, cfg):
    er, mx = idx.number("expense_ratio"), mandate.get("max_expense_ratio")
    if er is None or mx is None:
        return None, "Expense ratio or mandate maximum unavailable.", []
    return er <= mx, f"Expense ratio {er:g}% vs mandate max {mx:g}%.", idx.eid("expense_ratio")


def _fee_percentile_not_high(idx, mandate, cfg):
    p = idx.number("expense_ratio_percentile")
    if p is None:
        return None, "Category fee percentile unavailable.", []
    lim = cfg["thresholds"]["high_fee_percentile"]
    return p < lim, f"Fee percentile {p:g} vs high-fee threshold {lim}.", idx.eid("expense_ratio_percentile")


def _asset_class_allowed(idx, mandate, cfg):
    ac = norm_label(idx.value("asset_class"))
    if ac is None:
        return None, "Asset class unavailable.", []
    allowed = [norm_label(a) for a in mandate.get("allowed_asset_classes", [])]
    return ac in allowed, f"Asset class '{idx.value('asset_class')}' vs allowed {allowed}.", idx.eid("asset_class")


def _risk_within_mandate(idx, mandate, cfg):
    rr, mx = risk_rank(idx.value("risk_level")), risk_rank(mandate.get("max_risk_level"))
    if rr is None or mx is None:
        return None, "Risk level or mandate maximum unavailable.", []
    return rr <= mx, (f"Risk '{idx.value('risk_level')}' vs mandate max "
                      f"'{mandate.get('max_risk_level')}'."), idx.eid("risk_level")


def _history_meets_minimum(idx, mandate, cfg):
    h, mn = idx.number("history_years"), mandate.get("minimum_history_years")
    if h is None or mn is None:
        return None, "History or mandate minimum unavailable.", []
    return h >= mn, f"History {h:g} yrs vs minimum {mn:g} yrs.", idx.eid("history_years")


def _manager_tenure_adequate(idx, mandate, cfg):
    t = idx.number("manager_tenure_years")
    if t is None:
        return None, "Manager tenure unavailable.", []
    lim = cfg["thresholds"]["short_manager_tenure_years"]
    return t >= lim, f"Manager tenure {t:g} yrs vs {lim} yr threshold.", idx.eid("manager_tenure_years")


CHECKS: dict[str, Check] = {
    "required_evidence_present": _required_evidence_present,
    "required_evidence_not_imputed": _required_evidence_not_imputed,
    "expense_ratio_nonnegative": _expense_ratio_nonnegative,
    "expense_ratio_plausible": _expense_ratio_plausible,
    "asset_class_recognized": _asset_class_recognized,
    "expense_ratio_within_mandate": _expense_ratio_within_mandate,
    "fee_percentile_not_high": _fee_percentile_not_high,
    "asset_class_allowed": _asset_class_allowed,
    "risk_within_mandate": _risk_within_mandate,
    "history_meets_minimum": _history_meets_minimum,
    "manager_tenure_adequate": _manager_tenure_adequate,
}


def _dimension_status(results: list[RuleResult], dim: str) -> Status:
    failed = [r for r in results if r.dimension == dim and not r.passed]
    if any(r.severity == "CRITICAL" for r in failed):
        return Status.FAIL
    if any(r.severity == "MAJOR" for r in failed):
        return Status.REVIEW
    return Status.PASS


def run_policy_review(state: Any) -> PolicyResult:
    timer = run_log.Timer()
    cfg = config_loader.rules()
    mandate = config_loader.resolve_mandate(sget(state, "mandate"))
    idx = EvidenceIndex(state)
    results: list[RuleResult] = []
    not_evaluable = 0
    for rule in cfg["rules"]:
        fn = CHECKS.get(rule["check"])
        if fn is None:
            raise KeyError(f"rules.yaml references unknown check '{rule['check']}'")
        passed, detail, eids = fn(idx, mandate, cfg)
        if passed is None:
            # Missing inputs are caught by POL-001 (required evidence); here they are
            # recorded as not evaluable rather than silently passed.
            not_evaluable += 1
            detail = "NOT EVALUABLE: " + detail
            passed = rule["severity"] == "MINOR"
        results.append(RuleResult(rule_id=rule["id"], dimension=rule["dimension"],
                                  severity=rule["severity"], passed=passed,
                                  description=rule["description"], detail=detail, evidence_ids=eids))

    flags = [f"{r.rule_id}: {r.description} — {r.detail}" for r in results if not r.passed]
    critical = any(not r.passed and r.severity == "CRITICAL" for r in results)
    confidence = max(0.5, 0.98 - 0.08 * not_evaluable)
    statuses = {d: _dimension_status(results, d) for d in ("policy", "cost", "suitability")}
    rationale = ("Critical illustrative rule failed; deterministic control requires human review."
                 if critical else
                 f"{sum(r.passed for r in results)}/{len(results)} illustrative rules passed.")
    result = PolicyResult(
        policy_status=statuses["policy"], cost_status=statuses["cost"],
        suitability_status=statuses["suitability"], has_critical_failure=critical,
        confidence=confidence, rule_results=results, risk_flags=flags,
        evidence_ids=sorted({e for r in results for e in r.evidence_ids}),
        mandate_id=mandate.get("id"), rule_version=cfg.get("rule_version", "unknown"),
        rationale=rationale,
    )
    return run_log.attach(result, "policy_suitability", state, timer,
                          [r.rule_id for r in results if not r.passed], llm=False,
                          rule_version=result.rule_version)
