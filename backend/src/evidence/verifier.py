"""Read-only view over the Evidence Ledger stored in WorkflowState.

The ledger itself (add_evidence / get_evidence) is owned by the Data Steward module.
This helper only *reads* ledger records so the review modules work whether the state is a
dict, a Pydantic model, or whether records are dicts or Pydantic EvidenceRecord objects.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from src import config_loader


def sget(state: Any, key: str, default: Any = None) -> Any:
    """Get a key from a dict-like or attribute-style WorkflowState."""
    if state is None:
        return default
    if isinstance(state, dict):
        val = state.get(key, default)
    else:
        val = getattr(state, key, default)
    return default if val is None else val


def _as_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(vars(obj))


def as_number(value: Any) -> Optional[float]:
    """Convert '0.62', '0.62%', 0.62 -> 0.62; anything non-numeric -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").rstrip("%").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


class EvidenceIndex:
    """Lookup of ledger records by ID and by canonical field name (using configured aliases)."""

    def __init__(self, state: Any):
        self.case_id: Optional[str] = sget(state, "case_id")
        self.records: list[dict] = [_as_dict(r) for r in sget(state, "evidence_ledger", [])]
        self.by_id: dict[str, dict] = {r["evidence_id"]: r for r in self.records if r.get("evidence_id")}
        aliases = config_loader.rules().get("field_aliases", {})
        self._alias_to_canonical: dict[str, str] = {}
        for canonical, names in aliases.items():
            for n in names:
                self._alias_to_canonical[n.lower()] = canonical
        self.by_field: dict[str, dict] = {}
        for r in self.records:           # later records win (e.g. post-remediation values)
            f = r.get("field")
            if f:
                self.by_field[self.canonical(f)] = r

    def canonical(self, field: str) -> str:
        return self._alias_to_canonical.get(field.lower(), field.lower())

    def get(self, evidence_id: str) -> Optional[dict]:
        return self.by_id.get(evidence_id)

    def field(self, name: str) -> Optional[dict]:
        return self.by_field.get(self.canonical(name))

    def value(self, name: str) -> Any:
        rec = self.field(name)
        return None if rec is None else rec.get("value")

    def number(self, name: str) -> Optional[float]:
        return as_number(self.value(name))

    def eid(self, name: str) -> list[str]:
        rec = self.field(name)
        return [rec["evidence_id"]] if rec else []

    def has(self, name: str) -> bool:
        rec = self.field(name)
        return rec is not None and rec.get("value") not in (None, "")

    def belongs_to_case(self, evidence_id: str) -> bool:
        rec = self.get(evidence_id)
        if rec is None:
            return False
        rec_case = rec.get("case_id")
        return self.case_id is None or rec_case is None or rec_case == self.case_id

    def is_flagged(self, evidence_id: str) -> bool:
        """True if the Data Steward marked this record as imputed / low-quality."""
        rec = self.get(evidence_id) or {}
        md = rec.get("metadata") or {}
        return bool(md.get("imputed") or md.get("quality_flag") or md.get("low_confidence"))

    def ids(self, names: Iterable[str]) -> list[str]:
        out: list[str] = []
        for n in names:
            out.extend(self.eid(n))
        return out

    def compact_summary(self) -> list[dict]:
        """Small evidence payload for LLM prompts (never the raw dataset)."""
        keep = ("evidence_id", "field", "value", "source", "calculation")
        return [{k: r.get(k) for k in keep} for r in self.records]


def risk_rank(level: Any) -> Optional[int]:
    if level is None:
        return None
    scale = config_loader.rules().get("risk_scale", {})
    key = str(level).strip().lower().replace(" ", "_").replace("-", "_")
    if key in scale:
        return scale[key]
    num = as_number(level)
    return int(num) if num is not None else None


def norm_label(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")
