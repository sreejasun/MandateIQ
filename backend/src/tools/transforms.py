"""
MandateIQ deterministic transformations.
Owner: Sreeja Sunkeswaram
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def clean_dataset(
    dataset: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Apply conservative deterministic cleanup.

    The function deliberately does not invent missing financial values.
    Any future imputation must be explicitly logged.
    """
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("dataset must be a pandas DataFrame")

    cleaned = dataset.copy()
    transformations: list[dict[str, Any]] = []

    # Strip surrounding whitespace from text values.
    for column in cleaned.select_dtypes(
        include=["object", "string"]
    ).columns:
        original = cleaned[column].copy()

        cleaned[column] = cleaned[column].apply(
            lambda value: value.strip()
            if isinstance(value, str)
            else value
        )

        changed = int(
            (
                original.fillna("__NULL__").astype(str)
                != cleaned[column]
                .fillna("__NULL__")
                .astype(str)
            ).sum()
        )

        if changed:
            transformations.append(
                {
                    "operation": "strip_whitespace",
                    "field": str(column),
                    "affected_rows": changed,
                    "imputed": False,
                }
            )

    # Remove exact duplicates.
    duplicate_count = int(cleaned.duplicated().sum())

    if duplicate_count:
        cleaned = (
            cleaned.drop_duplicates()
            .reset_index(drop=True)
        )

        transformations.append(
            {
                "operation": "remove_duplicates",
                "affected_rows": duplicate_count,
                "imputed": False,
            }
        )

    return cleaned, transformations


def impute_numeric_median(
    dataset: pd.DataFrame,
    field: str,
) -> tuple[pd.DataFrame, list[int]]:
    """
    Explicit optional remediation helper.

    Returns the cleaned dataframe and indexes of imputed rows so
    evidence can be marked metadata.imputed=True.
    """
    output = dataset.copy()

    if field not in output.columns:
        return output, []

    values = pd.to_numeric(
        output[field],
        errors="coerce",
    )

    missing_mask = values.isna()

    if not missing_mask.any():
        return output, []

    median = values.median()

    if pd.isna(median):
        return output, []

    indexes = output.index[missing_mask].tolist()

    output.loc[missing_mask, field] = float(median)

    return output, indexes


# Backwards-friendly alias.
transform_dataset = clean_dataset