"""
MandateIQ generic dataset profiler.
Owner: Sreeja Sunkeswaram
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def profile_dataset(dataset: pd.DataFrame) -> dict[str, Any]:
    """
    Profile an arbitrary dataframe without assuming a fixed schema.

    This allows Dataset A and an altered Dataset B to use the same
    profiler without source-code changes.
    """
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("dataset must be a pandas DataFrame")

    columns: dict[str, dict[str, Any]] = {}

    for column in dataset.columns:
        series = dataset[column]

        info: dict[str, Any] = {
            "dtype": str(series.dtype),
            "missing_count": int(series.isna().sum()),
            "missing_rate": (
                float(series.isna().mean())
                if len(series)
                else 0.0
            ),
            "unique_count": int(series.nunique(dropna=True)),
        }

        if pd.api.types.is_numeric_dtype(series):
            clean = pd.to_numeric(
                series,
                errors="coerce",
            ).dropna()

            if not clean.empty:
                info.update(
                    {
                        "min": float(clean.min()),
                        "max": float(clean.max()),
                        "mean": float(clean.mean()),
                        "median": float(clean.median()),
                    }
                )

        columns[str(column)] = info

    return {
        "row_count": int(len(dataset)),
        "column_count": int(len(dataset.columns)),
        "duplicate_count": int(dataset.duplicated().sum()),
        "missing_count": int(dataset.isna().sum().sum()),
        "columns": columns,
    }