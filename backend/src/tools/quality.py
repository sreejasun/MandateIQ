"""
MandateIQ deterministic data-quality checks.
Owner: Sreeja Sunkeswaram
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def assess_quality(
    dataset: pd.DataFrame,
    required_columns: list[str] | None = None,
) -> dict[str, Any]:
    """
    Assess dataset quality.

    quality_score is always between 0.0 and 1.0.
    """
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("dataset must be a pandas DataFrame")

    issues: list[dict[str, Any]] = []

    if dataset.empty:
        return {
            "quality_score": 0.0,
            "passed": False,
            "issues": [
                {
                    "type": "empty_dataset",
                    "severity": "critical",
                    "message": "Dataset contains no records.",
                }
            ],
        }

    # Missing required columns.
    for column in required_columns or []:
        if column not in dataset.columns:
            issues.append(
                {
                    "type": "missing_required_column",
                    "severity": "critical",
                    "field": column,
                    "message": f"Required field '{column}' is missing.",
                }
            )

    # Missing values.
    for column in dataset.columns:
        missing = int(dataset[column].isna().sum())

        if missing:
            rate = missing / len(dataset)

            issues.append(
                {
                    "type": "missing_values",
                    "severity": (
                        "critical"
                        if rate >= 0.25
                        else "warning"
                    ),
                    "field": str(column),
                    "count": missing,
                    "rate": float(rate),
                    "message": (
                        f"{column} contains {missing} missing values."
                    ),
                }
            )

    # Duplicate rows.
    duplicates = int(dataset.duplicated().sum())

    if duplicates:
        issues.append(
            {
                "type": "duplicate_rows",
                "severity": "warning",
                "count": duplicates,
                "message": (
                    f"Dataset contains {duplicates} duplicate rows."
                ),
            }
        )

    # Calculate deterministic score.
    critical_count = sum(
        issue["severity"] == "critical"
        for issue in issues
    )

    warning_count = sum(
        issue["severity"] == "warning"
        for issue in issues
    )

    penalty = (
        critical_count * 0.20
        + warning_count * 0.05
    )

    quality_score = max(0.0, min(1.0, 1.0 - penalty))

    return {
        "quality_score": float(quality_score),
        "passed": critical_count == 0,
        "issues": issues,
    }


# Backwards-friendly name.
run_quality_checks = assess_quality