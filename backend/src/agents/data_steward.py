"""
MandateIQ Data Steward
Owner: Sreeja Sunkeswaram

Produces deterministic, evidence-backed fund data for downstream
Proponent, Challenger, Policy, Firewall and Trust Score modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, Field

from src.evidence.ledger import (
    EvidenceRecord,
    add_evidence,
)
from src.tools.finance_metrics import (
    calculate_financial_metrics,
)
from src.tools.profiler import profile_dataset
from src.tools.quality import assess_quality
from src.tools.transforms import clean_dataset


CANONICAL_FIELDS = [
    "expense_ratio",
    "asset_class",
    "risk_level",
    "history_years",
    "expense_ratio_percentile",
    "category",
    "manager_tenure_years",
    "return_3y",
    "return_5y",
    "volatility",
]


REQUIRED_FIELDS = [
    "expense_ratio",
    "asset_class",
    "risk_level",
    "history_years",
]


DEFAULT_ALIASES = {
    "expense_ratio": [
        "expense_ratio",
        "fund_expense_ratio",
        "net_expense_ratio",
        "expense",
    ],
    "asset_class": [
        "asset_class",
        "asset_type",
        "fund_asset_class",
    ],
    "risk_level": [
        "risk_level",
        "risk_rating",
        "risk",
    ],
    "history_years": [
        "history_years",
        "fund_age",
        "fund_age_years",
        "track_record_years",
    ],
    "expense_ratio_percentile": [
        "expense_ratio_percentile",
        "expense_percentile",
    ],
    "category": [
        "category",
        "fund_category",
    ],
    "manager_tenure_years": [
        "manager_tenure_years",
        "manager_tenure",
    ],
    "return_3y": [
        "return_3y",
        "three_year_return",
        "return_3_year",
    ],
    "return_5y": [
        "return_5y",
        "five_year_return",
        "return_5_year",
    ],
    "volatility": [
        "volatility",
        "annualized_volatility",
        "std_dev",
    ],
}


RISK_MAP = {
    "very low": "very_low",
    "very_low": "very_low",
    "low": "low",
    "medium low": "medium_low",
    "medium_low": "medium_low",
    "moderate low": "medium_low",
    "medium": "medium",
    "moderate": "medium",
    "medium high": "medium_high",
    "medium_high": "medium_high",
    "moderate high": "medium_high",
    "high": "high",
    "very high": "very_high",
    "very_high": "very_high",
}


class DataStewardResult(BaseModel):
    """Structured output consumed by downstream MandateIQ modules."""

    case_id: str
    quality_score: float
    profile: dict[str, Any]
    quality_report: dict[str, Any]
    transformations: list[dict[str, Any]] = Field(
        default_factory=list
    )
    evidence_ledger: list[EvidenceRecord] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


def _load_dataset(
    dataset: pd.DataFrame | str | Path,
) -> tuple[pd.DataFrame, str]:
    if isinstance(dataset, pd.DataFrame):
        return dataset.copy(), "dataframe"

    path = Path(dataset)

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path}"
        )

    return pd.read_csv(path), path.name


def _normalize_name(value: str) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _find_column(
    dataset: pd.DataFrame,
    canonical_field: str,
) -> str | None:
    """
    Resolve common field aliases.

    Dataset-specific aliases should additionally be placed in
    config/rules.yaml as required by the integration contract.
    """
    normalized_columns = {
        _normalize_name(column): str(column)
        for column in dataset.columns
    }

    aliases = DEFAULT_ALIASES.get(
        canonical_field,
        [canonical_field],
    )

    for alias in aliases:
        normalized = _normalize_name(alias)

        if normalized in normalized_columns:
            return normalized_columns[normalized]

    return None


def _normalize_risk(value: Any) -> Any:
    if value is None or pd.isna(value):
        return value

    if isinstance(value, (int, float)):
        number = int(value)

        if 1 <= number <= 7:
            return number

    normalized = (
        str(value)
        .strip()
        .lower()
        .replace("-", " ")
    )

    return RISK_MAP.get(
        normalized,
        normalized.replace(" ", "_"),
    )


def _python_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass

    return value


def run_data_steward(
    dataset: pd.DataFrame | str | Path,
    case_id: str | None = None,
) -> DataStewardResult:
    """
    Run the complete MandateIQ Data Steward pipeline.

    Every fund produces individual evidence records for each supported
    canonical field.
    """
    raw, source = _load_dataset(dataset)

    case_id = case_id or f"CASE-{uuid4().hex[:8].upper()}"

    profile = profile_dataset(raw)

    quality_report = assess_quality(raw)

    cleaned, transformations = clean_dataset(raw)

    enriched = calculate_financial_metrics(cleaned)

    evidence_records: list[EvidenceRecord] = []

    for row_index, row in enriched.iterrows():

        # Identify a useful fund identifier when available.
        fund_identifier = None

        for identifier_field in [
            "fund_id",
            "ticker",
            "fund_name",
            "name",
        ]:
            identifier_column = _find_column(
                enriched,
                identifier_field,
            )

            if (
                identifier_column
                and pd.notna(row[identifier_column])
            ):
                fund_identifier = str(
                    row[identifier_column]
                )
                break

        if fund_identifier is None:
            fund_identifier = f"row_{row_index}"

        for canonical_field in CANONICAL_FIELDS:
            column = _find_column(
                enriched,
                canonical_field,
            )

            if column is None:
                continue

            value = _python_value(row[column])

            if value is None:
                continue

            if canonical_field == "risk_level":
                value = _normalize_risk(value)

            # All percentage fields remain in percent units.
            if canonical_field in {
                "expense_ratio",
                "expense_ratio_percentile",
                "return_3y",
                "return_5y",
                "volatility",
            }:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass

            if canonical_field in {
                "history_years",
                "manager_tenure_years",
            }:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass

            metadata = {
                "fund_id": fund_identifier,
                "row_index": int(row_index),
                "original_field": column,
                "imputed": False,
            }

            record = add_evidence(
                case_id=case_id,
                field=canonical_field,
                value=value,
                source=source,
                calculation=(
                    "category_percentile"
                    if canonical_field
                    == "expense_ratio_percentile"
                    else "direct_observation"
                ),
                created_by="data_steward",
                metadata=metadata,
            )

            evidence_records.append(record)

    return DataStewardResult(
        case_id=case_id,
        quality_score=float(
            quality_report["quality_score"]
        ),
        profile=profile,
        quality_report=quality_report,
        transformations=transformations,
        evidence_ledger=evidence_records,
        metadata={
            "source": source,
            "row_count": len(enriched),
            "required_fields": REQUIRED_FIELDS,
        },
    )