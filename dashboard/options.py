from __future__ import annotations

from pathlib import Path

from dashboard.data import query_df
from dashboard.filters import (
    CAMPAIGN_LABEL_TO_RAW,
    REFERRER_TYPE_SQL,
    TRAFFIC_SOURCE_SQL,
    build_session_predicate,
)
from dashboard.models import DatePeriod, FilterSpec


PRODUCT_URLS = (
    "/the-original-mr-fuzzy",
    "/the-forever-love-bear",
    "/the-birthday-sugar-panda",
    "/the-hudson-river-mini-bear",
)

_ORDERS = {
    "traffic_source": ("Paid Search", "Paid Social", "Organic Search", "Direct", "Other"),
    "campaign": ("Brand", "Nonbrand", "Desktop targeted", "Pilot", "Untracked"),
    "device": ("desktop", "mobile"),
    "session_type": ("New", "Repeat"),
    "referrer": ("Paid", "Organic", "Direct"),
    "item_role": ("Primary", "Add-on"),
    "order_size": ("Single-item", "Multi-item"),
}


def _ordered(values: set[str], dimension: str) -> tuple[str, ...]:
    preferred = _ORDERS.get(dimension)
    if preferred is None:
        return tuple(sorted(values))
    return tuple(value for value in preferred if value in values)


def session_dimension_values(
    path: str | Path,
    period: DatePeriod,
    filters: FilterSpec,
    dimension: str,
) -> tuple[str, ...]:
    expressions = {
        "traffic_source": TRAFFIC_SOURCE_SQL.format(alias="s"),
        "campaign": "COALESCE(NULLIF(s.utm_campaign, 'NULL'), 'Untracked')",
        "device": "s.device_type",
        "session_type": "CASE WHEN s.is_repeat_session = 1 THEN 'Repeat' ELSE 'New' END",
        "ad": "COALESCE(NULLIF(s.utm_content, 'NULL'), 'Untracked')",
        "referrer": REFERRER_TYPE_SQL.format(alias="s"),
    }
    if dimension not in expressions:
        raise ValueError(f"Unsupported option dimension: {dimension}")
    where, params = build_session_predicate(filters, period, alias="s")
    frame = query_df(
        path,
        f"SELECT DISTINCT {expressions[dimension]} AS value FROM website_sessions s "
        f"WHERE {where} ORDER BY value",
        params,
    )
    values = set(frame["value"].dropna().astype(str))
    if dimension == "campaign":
        raw_to_label = {
            raw: label for label, raw in CAMPAIGN_LABEL_TO_RAW.items() if raw is not None
        }
        values = {
            "Untracked" if value == "Untracked" else raw_to_label.get(value, value)
            for value in values
        }
    return _ordered(values, dimension)


def _landing_pages(
    path: str | Path,
    period: DatePeriod,
    filters: FilterSpec,
) -> tuple[str, ...]:
    where, params = build_session_predicate(filters, period, alias="s")
    frame = query_df(
        path,
        f"""
        WITH first_page AS (
            SELECT p.website_session_id, p.pageview_url
            FROM website_pageviews p
            JOIN (
                SELECT website_session_id, MIN(website_pageview_id) AS first_id
                FROM website_pageviews GROUP BY website_session_id
            ) x ON x.first_id = p.website_pageview_id
        )
        SELECT DISTINCT fp.pageview_url AS value
        FROM website_sessions s
        JOIN first_page fp ON fp.website_session_id = s.website_session_id
        WHERE {where}
        ORDER BY value
        """,
        params,
    )
    return tuple(frame["value"].dropna().astype(str))


def acquisition_filter_options(
    path: str | Path,
    period: DatePeriod,
    filters: FilterSpec,
) -> dict[str, tuple[str, ...]]:
    return {
        "ad": session_dimension_values(path, period, filters, "ad"),
        "referrer": session_dimension_values(path, period, filters, "referrer"),
        "landing": _landing_pages(path, period, filters),
    }


def funnel_filter_options(
    path: str | Path,
    period: DatePeriod,
    filters: FilterSpec,
) -> dict[str, tuple[str, ...]]:
    where, params = build_session_predicate(filters, period, alias="s")
    marks = ",".join("?" for _ in PRODUCT_URLS)
    frame = query_df(
        path,
        f"""
        SELECT DISTINCT p.pageview_url AS value
        FROM website_sessions s
        JOIN website_pageviews p ON p.website_session_id = s.website_session_id
        WHERE {where} AND p.pageview_url IN ({marks})
        """,
        [*params, *PRODUCT_URLS],
    )
    present = set(frame["value"].dropna().astype(str))
    return {
        "landing": _landing_pages(path, period, filters),
        "product_page": tuple(value for value in PRODUCT_URLS if value in present),
    }


def product_filter_options(
    path: str | Path,
    period: DatePeriod,
    filters: FilterSpec,
) -> dict[str, tuple[str, ...]]:
    where, dimension_params = build_session_predicate(
        filters, period, alias="s", include_period=False
    )
    start, end = period.sql_bounds()
    frame = query_df(
        path,
        f"""
        SELECT DISTINCT product_id, product, item_role, order_size
        FROM (
            SELECT p.product_id, p.product_name AS product,
                   CASE WHEN oi.is_primary_item = 1 THEN 'Primary' ELSE 'Add-on' END AS item_role,
                   CASE WHEN o.items_purchased = 1 THEN 'Single-item' ELSE 'Multi-item' END AS order_size
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN website_sessions s ON s.website_session_id = o.website_session_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE oi.created_at >= ? AND oi.created_at < ? AND {where}

            UNION

            SELECT p.product_id, p.product_name AS product,
                   CASE WHEN oi.is_primary_item = 1 THEN 'Primary' ELSE 'Add-on' END AS item_role,
                   CASE WHEN o.items_purchased = 1 THEN 'Single-item' ELSE 'Multi-item' END AS order_size
            FROM order_item_refunds r
            JOIN order_items oi ON oi.order_item_id = r.order_item_id
            JOIN orders o ON o.order_id = oi.order_id
            JOIN website_sessions s ON s.website_session_id = o.website_session_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE r.created_at >= ? AND r.created_at < ? AND {where}
        )
        ORDER BY product_id
        """,
        [
            start,
            end,
            *dimension_params,
            start,
            end,
            *dimension_params,
        ],
    )
    return {
        "product": tuple(frame["product"].dropna().astype(str).drop_duplicates()),
        "item_role": _ordered(set(frame["item_role"].dropna().astype(str)), "item_role"),
        "order_size": _ordered(set(frame["order_size"].dropna().astype(str)), "order_size"),
    }
