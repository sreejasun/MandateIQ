"""
MandateIQ Evidence Ledger
Owner: Sreeja Sunkeswaram

Provides the canonical evidence contract consumed by the
Proponent, Challenger, Policy, Firewall and Trust Score modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    """Canonical MandateIQ evidence record."""

    evidence_id: str
    case_id: str
    source: str
    field: str
    value: Any
    calculation: str
    created_by: str
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Process-local evidence registry.
# It lets downstream modules resolve evidence IDs during a workflow run.
_EVIDENCE_STORE: dict[str, EvidenceRecord] = {}
_EVIDENCE_COUNTER = 0


def _next_evidence_id() -> str:
    """Generate a unique human-readable evidence ID."""
    global _EVIDENCE_COUNTER

    _EVIDENCE_COUNTER += 1

    while True:
        evidence_id = f"EV-{_EVIDENCE_COUNTER:03d}"

        if evidence_id not in _EVIDENCE_STORE:
            return evidence_id

        _EVIDENCE_COUNTER += 1


def add_evidence(
    case_id: str,
    field: str,
    value: Any,
    source: str = "data_steward",
    calculation: str = "direct_observation",
    created_by: str = "data_steward",
    metadata: dict[str, Any] | None = None,
) -> EvidenceRecord:
    """
    Add one evidence item and return the created EvidenceRecord.

    Parameters match the integration contract used by the review and
    governance agents.
    """
    record = EvidenceRecord(
        evidence_id=_next_evidence_id(),
        case_id=str(case_id),
        source=str(source),
        field=str(field),
        value=value,
        calculation=str(calculation),
        created_by=str(created_by),
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=dict(metadata or {}),
    )

    _EVIDENCE_STORE[record.evidence_id] = record

    return record


def get_evidence(evidence_id: str) -> EvidenceRecord | None:
    """Resolve an evidence ID."""
    return _EVIDENCE_STORE.get(evidence_id)


def get_case_evidence(case_id: str) -> list[EvidenceRecord]:
    """Return all evidence records belonging to one case."""
    return [
        record
        for record in _EVIDENCE_STORE.values()
        if record.case_id == str(case_id)
    ]


def clear_evidence() -> None:
    """Clear the in-memory ledger, primarily for tests/new workflow runs."""
    global _EVIDENCE_COUNTER

    _EVIDENCE_STORE.clear()
    _EVIDENCE_COUNTER = 0