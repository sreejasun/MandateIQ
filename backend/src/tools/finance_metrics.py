"""
MandateIQ deterministic financial metrics.
Owner: Sreeja Sunkeswaram
"""

from __future__ import annotations

import pandas as pd


def add_expense_ratio_percentile(
    dataset: pd.DataFrame,
    expense_field: str = "expense_ratio",
    category_field: str = "category",
) -> pd.DataFrame:
    """
    Calculate expense-ratio percentile on a 0-100 scale.

    When category exists, percentile is calculated within category.
    Otherwise it is calculated across the available dataset.
    """
    output = dataset.copy()

    if expense_field not in output.columns:
        return output

    values = pd.to_numeric(
        output[expense_field],
        errors="coerce",
    )

    if category_field in output.columns:
        output["expense_ratio_percentile"] = (
            output.assign(_expense_numeric=values)
            .groupby(category_field)["_expense_numeric"]
            .rank(
                method="average",
                pct=True,
            )
            .mul(100)
        )
    else:
        output["expense_ratio_percentile"] = (
            values.rank(
                method="average",
                pct=True,
            ).mul(100)
        )

    return output


def calculate_financial_metrics(
    dataset: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add deterministic metrics supported by the dataset.

    Existing expense ratios, returns and volatility are preserved in
    percent units as required by the MandateIQ integration contract.
    """
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("dataset must be a pandas DataFrame")

    output = dataset.copy()

    output = add_expense_ratio_percentile(output)

    return output