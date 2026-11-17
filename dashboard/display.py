from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import streamlit as st


CURRENCY_COLUMNS = frozenset(
    {
        "revenue",
        "gross_revenue",
        "net_revenue",
        "gross_margin",
        "cogs",
        "refund_amount",
        "refunded_amount",
        "revenue_per_session",
        "margin_per_session",
        "price_usd",
        "cogs_usd",
        "refund_amount_usd",
    }
)


def is_currency_column(column: str) -> bool:
    return column in CURRENCY_COLUMNS or column.endswith("_usd")


def dataframe_column_config(
    frame: pd.DataFrame,
    display_names: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return consistent left-aligned display settings for a dataframe."""
    labels = display_names or {}
    config: dict[str, object] = {}
    for column in frame.columns:
        label = labels.get(column, column)
        if pd.api.types.is_numeric_dtype(frame[column]):
            options: dict[str, str] = {"alignment": "left"}
            if is_currency_column(column):
                options["format"] = "$%.2f"
            config[label] = st.column_config.NumberColumn(**options)
        else:
            config[label] = st.column_config.TextColumn(alignment="left")
    return config
