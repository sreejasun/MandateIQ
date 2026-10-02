"""Business helpers used by the API.

These functions turn a completed WorkflowState (as JSON) into the summaries,
comparisons and aggregates the web interface shows. They contain no FastAPI
code so they can be tested directly.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

import pandas as pd

from src import config_loader

# Columns a dataset must contain for a review to run.
REQUIRED_COLUMNS = [
    "fund_id",
    "fund_name",
    "ticker",
    "expense_ratio",
    "asset_class",
    "risk_level",
    "history_years",
]

# Fields the What-if panel may change, with input metadata for the UI.
SCENARIO_FIELDS: dict[str, dict[str, Any]] = {
    "expense_ratio": {"label": "Expense ratio", "unit": "%", "type": "number", "min": 0, "max": 5, "step": 0.01},
    "risk_level": {"label": "Risk level", "type": "select"},
    "manager_tenure_years": {"label": "Manager tenure", "unit": "years", "type": "number", "min": 0, "max": 50,
                             "step": 1},
    "volatility": {"label": "Volatility", "unit": "%", "type": "number", "min": 0, "max": 100, "step": 0.1},
    "history_years": {"label": "Track record", "unit": "years", "type": "number", "min": 0, "max": 100,
                      "step": 1},
}

# Demonstration claims that cite missing or misquoted evidence. Used when a
# review is started with "seed unsupported claims", to show the Hallucination
# Firewall and the debate catching them.
SEEDED_CLAIMS: list[dict[str, Any]] = [
    {"claim": "[SEEDED] Fund ranked top-decile by Morningstar for 10 straight years.",
     "evidence_ids": ["EV-999"], "field": "rating"},
    {"claim": "[SEEDED] Expense ratio is only 0.15%, far below peers.",
     "evidence_ids": ["EV-001"], "cited_values": [{"evidence_id": "EV-001", "value": 0.15}],
     "field": "expense_ratio"},
]

OUTCOMES: dict[str, dict[str, str]] = {
    "finalize": {"label": "Eligible to finalize", "tone": "positive"},
    "human_review": {"label": "Human review", "tone": "caution"},
    "blocked": {"label": "Blocked by policy", "tone": "negative"},
    "rework": {"label": "Needs rework", "tone": "rework"},
    "failed": {"label": "Review failed", "tone": "neutral"},
    "pending": {"label": "In progress", "tone": "neutral"},
}


# ============================================================
# DATASETS
# ============================================================

class DatasetError(ValueError):
    pass


def parse_dataset(raw: bytes | str) -> pd.DataFrame:
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as exc:
        raise DatasetError(f"The file could not be read as CSV: {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]

    if df.empty:
        raise DatasetError("The file has a header row but no funds.")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DatasetError("Missing required columns: " + ", ".join(missing))

    ids = df["fund_id"].astype(str).str.strip()
    if ids.duplicated().any():
        dupes = sorted(set(ids[ids.duplicated()]))
        raise DatasetError("Each fund_id must be unique. Repeated: " + ", ".join(dupes[:5]))

    return df


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe row dictionaries (NaN becomes None)."""
    out = []
    for row in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()})
    return out


def find_fund(df: pd.DataFrame, fund_id: str) -> dict[str, Any]:
    mask = df["fund_id"].astype(str).str.strip() == str(fund_id).strip()
    if not mask.any():
        raise DatasetError(f"Fund {fund_id} is not in this dataset.")
    return records(df[mask])[0]


def apply_changes(df: pd.DataFrame, fund_id: str, changes: dict[str, Any]) -> pd.DataFrame:
    """Return a copy of the dataset with the scenario changes applied to one fund."""
    unknown = set(changes) - set(SCENARIO_FIELDS)
    if unknown:
        raise DatasetError("These fields cannot be changed: " + ", ".join(sorted(unknown)))

    out = df.copy(deep=True)
    mask = out["fund_id"].astype(str).str.strip() == str(fund_id).strip()
    if not mask.any():
        raise DatasetError(f"Fund {fund_id} is not in this dataset.")

    for field, value in changes.items():
        if field not in out.columns:
            out[field] = None
        if SCENARIO_FIELDS[field]["type"] == "number":
            out[field] = out[field].astype("float64")
            out.loc[mask, field] = float(value)
        else:
            out[field] = out[field].astype("object")
            out.loc[mask, field] = str(value)
    return out


def risk_levels() -> list[str]:
    scale = config_loader.rules().get("risk_scale", {}) or {}
    return [k for k, _ in sorted(scale.items(), key=lambda kv: kv[1])]


# ============================================================
# OUTCOME / SUMMARY
# ============================================================

def outcome_of(state: dict[str, Any] | None, status: str) -> str:
    if status == "failed":
        return "failed"
    if status != "completed" or not state:
        return "pending"

    policy = state.get("policy_result") or {}
    if policy.get("has_critical_failure"):
        return "blocked"

    route = (state.get("supervisor_result") or {}).get("route")
    if state.get("human_review_required") or route == "human_review":
        return "human_review"
    if route == "finalize":
        return "finalize"
    return "rework"


def outcome_meta(key: str) -> dict[str, str]:
    return {"key": key, **OUTCOMES.get(key, OUTCOMES["pending"])}


def _split_reasons(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r";\s+", text) if p.strip()]


def overview(state: dict[str, Any]) -> dict[str, Any]:
    """Executive summary of one completed case."""
    gate = state.get("governance_gate") or {}
    supervisor = state.get("supervisor_result") or {}
    policy = state.get("policy_result") or {}
    prop = state.get("proponent_result") or {}
    chal = state.get("challenger_result") or {}

    reasons = list(gate.get("reasons") or [])
    if not reasons and supervisor.get("reason"):
        reasons = [supervisor["reason"]]

    open_high = [
        c for c in chal.get("challenges", []) or []
        if c.get("severity") == "HIGH" and not c.get("resolved")
    ]

    return {
        "reasons": reasons,
        "human_review_items": _split_reasons(state.get("human_review_reason")),
        "route": supervisor.get("route"),
        "route_reason": supervisor.get("reason"),
        "gate": gate.get("gate"),
        "band": gate.get("band"),
        "trust_score": state.get("trust_score"),
        "quality_score": state.get("quality_score"),
        "firewall_status": state.get("firewall_status"),
        "policy": {
            "policy": policy.get("policy_status"),
            "cost": policy.get("cost_status"),
            "suitability": policy.get("suitability_status"),
            "passed": sum(1 for r in policy.get("rule_results", []) if r.get("passed")),
            "total": len(policy.get("rule_results", []) or []),
        },
        "committee": {
            "proponent_position": prop.get("position"),
            "proponent_confidence": prop.get("confidence"),
            "challenger_position": chal.get("position"),
            "challenger_confidence": chal.get("confidence"),
            "claims": len(prop.get("claims", []) or []),
            "challenges": len(chal.get("challenges", []) or []),
            "open_high_challenges": len(open_high),
        },
        "risk_flags": state.get("risk_flags") or [],
    }


# ============================================================
# SCENARIO COMPARISON
# ============================================================

def _components(state: dict[str, Any]) -> dict[str, float]:
    out = {}
    for key, value in (state.get("trust_components") or {}).items():
        score = value.get("score") if isinstance(value, dict) else value
        try:
            out[key] = float(score)
        except (TypeError, ValueError):
            out[key] = 0.0
    return out


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    policy = state.get("policy_result") or {}
    return {
        "outcome": outcome_meta(outcome_of(state, "completed")),
        "trust_score": state.get("trust_score"),
        "gate": (state.get("governance_gate") or {}).get("gate"),
        "route": (state.get("supervisor_result") or {}).get("route"),
        "firewall_status": state.get("firewall_status"),
        "policy_status": policy.get("policy_status"),
        "cost_status": policy.get("cost_status"),
        "suitability_status": policy.get("suitability_status"),
        "failed_rules": [
            {"rule_id": r.get("rule_id"), "description": r.get("description"), "detail": r.get("detail")}
            for r in policy.get("rule_results", []) if not r.get("passed")
        ],
        "components": _components(state),
    }


def compare(before_state: dict[str, Any], after_state: dict[str, Any],
            before_fund: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    before, after = _snapshot(before_state), _snapshot(after_state)

    before_rules = {r["rule_id"] for r in before["failed_rules"]}
    after_rules = {r["rule_id"] for r in after["failed_rules"]}

    return {
        "changes": [
            {"field": f, "label": SCENARIO_FIELDS[f]["label"], "before": before_fund.get(f), "after": v}
            for f, v in changes.items()
        ],
        "before": before,
        "after": after,
        "trust_delta": (
            round(after["trust_score"] - before["trust_score"], 1)
            if before["trust_score"] is not None and after["trust_score"] is not None else None
        ),
        "outcome_changed": before["outcome"]["key"] != after["outcome"]["key"],
        "rules_now_failing": sorted(after_rules - before_rules),
        "rules_now_passing": sorted(before_rules - after_rules),
    }


# ============================================================
# INSIGHTS
# ============================================================

_FLAG_CODE = re.compile(r"^([A-Z]+-\d+)")


def insights(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics over completed reviews.

    `rows` are review records with parsed `state`, `outcome`, `provider`.
    """
    completed = [r for r in rows if r.get("status") == "completed" and r.get("state")]
    total = len(completed)

    outcome_counts = Counter(r["outcome"] for r in completed)
    scores = [float(r["state"]["trust_score"]) for r in completed if r["state"].get("trust_score") is not None]

    buckets = [(0, 40), (40, 60), (60, 80), (80, 101)]
    distribution = [
        {"range": f"{lo}–{min(hi, 100)}", "count": sum(1 for s in scores if lo <= s < hi)}
        for lo, hi in buckets
    ]

    comp_values: dict[str, list[float]] = defaultdict(list)
    for r in completed:
        for k, v in _components(r["state"]).items():
            comp_values[k].append(v)

    flag_counter: Counter[str] = Counter()
    flag_text: dict[str, str] = {}
    for r in completed:
        for flag in r["state"].get("risk_flags") or []:
            m = _FLAG_CODE.match(str(flag))
            code = m.group(1) if m else str(flag)[:40]
            flag_counter[code] += 1
            flag_text.setdefault(code, str(flag))

    latency: dict[str, list[float]] = defaultdict(list)
    for r in completed:
        for key in ("proponent_result", "challenger_result", "policy_result"):
            log = (r["state"].get(key) or {}).get("run_log") or {}
            if log.get("latency_ms") is not None:
                latency[key.replace("_result", "")].append(float(log["latency_ms"]))

    debate_rounds = [
        int((r["state"].get("debate") or {}).get("total_rounds") or 0) for r in completed
    ]

    by_mandate: dict[str, list[float]] = defaultdict(list)
    for r in completed:
        if r["state"].get("trust_score") is not None:
            by_mandate[str(r.get("mandate"))].append(float(r["state"]["trust_score"]))

    return {
        "total_reviews": total,
        "average_trust": round(mean(scores), 1) if scores else None,
        "human_review_rate": (
            round(100 * sum(1 for r in completed if r["state"].get("human_review_required")) / total, 1)
            if total else None
        ),
        "firewall_failures": sum(1 for r in completed if r["state"].get("firewall_status") == "FAIL"),
        "average_debate_rounds": round(mean(debate_rounds), 2) if debate_rounds else None,
        "outcomes": [
            {**outcome_meta(k), "count": outcome_counts.get(k, 0)}
            for k in ("finalize", "human_review", "blocked", "rework")
        ],
        "trust_distribution": distribution,
        "components": [
            {"key": k, "average": round(mean(v), 1)} for k, v in sorted(comp_values.items())
        ],
        "risk_flags": [
            {"code": code, "count": n, "example": flag_text[code]}
            for code, n in flag_counter.most_common(8)
        ],
        "agent_latency_ms": [
            {"agent": k, "average": round(mean(v), 1)} for k, v in sorted(latency.items())
        ],
        "providers": [
            {"provider": k, "count": n} for k, n in Counter(r.get("provider") for r in completed).most_common()
        ],
        "trust_by_mandate": [
            {"mandate": k, "average": round(mean(v), 1), "count": len(v)} for k, v in sorted(by_mandate.items())
        ],
    }
