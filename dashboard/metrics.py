from __future__ import annotations

from itertools import permutations
from pathlib import Path

import pandas as pd

from dashboard.data import query_df
from dashboard.filters import (
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
PRODUCT_ROLE_VALUES = {"Primary": 1, "Add-on": 0}
VALID_ORDER_SIZES = {"Single-item", "Multi-item"}


def _filtered_sessions_cte(filters: FilterSpec, period: DatePeriod) -> tuple[str, list[object]]:
    where, params = build_session_predicate(filters, period, alias="s")
    return f"""
        filtered_sessions AS (
            SELECT s.*,
                   {TRAFFIC_SOURCE_SQL.format(alias='s')} AS traffic_source,
                   {REFERRER_TYPE_SQL.format(alias='s')} AS referrer_type,
                   CASE WHEN s.is_repeat_session = 1 THEN 'Repeat' ELSE 'New' END AS session_type,
                   COALESCE(NULLIF(s.utm_campaign, 'NULL'), 'Untracked') AS campaign,
                   COALESCE(NULLIF(s.utm_content, 'NULL'), 'Untracked') AS ad_content
            FROM website_sessions s
            WHERE {where}
        )
    """, params


def _dimension_where(filters: FilterSpec, period: DatePeriod, alias: str = "s") -> tuple[str, list[object]]:
    return build_session_predicate(filters, period, alias=alias, include_period=False)


def _number(value: object, default: float = 0.0) -> float:
    return default if value is None or pd.isna(value) else float(value)


def overview_kpis(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    revenue_basis: str = "Gross",
) -> dict[str, float | int]:
    if revenue_basis not in {"Gross", "Net"}:
        raise ValueError(f"Unsupported revenue basis: {revenue_basis}")
    sessions_cte, session_params = _filtered_sessions_cte(filters, period)
    sessions = int(
        query_df(path, f"WITH {sessions_cte} SELECT COUNT(*) AS value FROM filtered_sessions", session_params)
        .iloc[0]["value"]
    )
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    order_stats = query_df(
        path,
        f"""
        SELECT COUNT(o.order_id) AS orders,
               COALESCE(SUM(o.price_usd), 0) AS gross_revenue,
               COALESCE(SUM(o.cogs_usd), 0) AS cogs
        FROM orders o
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE o.created_at >= ? AND o.created_at < ? AND {dimension_where}
        """,
        [start, end, *dimension_params],
    ).iloc[0]
    item_stats = query_df(
        path,
        f"""
        SELECT COUNT(oi.order_item_id) AS sold_items
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE oi.created_at >= ? AND oi.created_at < ? AND {dimension_where}
        """,
        [start, end, *dimension_params],
    ).iloc[0]
    refunds = query_df(
        path,
        f"""
        SELECT COUNT(r.order_item_refund_id) AS refunded_items,
               COALESCE(SUM(r.refund_amount_usd), 0) AS refund_amount
        FROM order_item_refunds r
        JOIN order_items oi ON oi.order_item_id = r.order_item_id
        JOIN orders o ON o.order_id = oi.order_id
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE r.created_at >= ? AND r.created_at < ? AND {dimension_where}
        """,
        [start, end, *dimension_params],
    ).iloc[0]

    orders = int(order_stats["orders"] or 0)
    sold_items = int(item_stats["sold_items"] or 0)
    gross_revenue = _number(order_stats["gross_revenue"])
    cogs = _number(order_stats["cogs"])
    refund_amount = _number(refunds["refund_amount"])
    refunded_items = int(refunds["refunded_items"] or 0)
    net_revenue = gross_revenue - refund_amount
    revenue = net_revenue if revenue_basis == "Net" else gross_revenue
    gross_margin = gross_revenue - cogs
    return {
        "revenue": revenue,
        "gross_revenue": gross_revenue,
        "net_revenue": net_revenue,
        "orders": orders,
        "sessions": sessions,
        "conversion_rate": orders / sessions if sessions else pd.NA,
        "aov": gross_revenue / orders if orders else pd.NA,
        "gross_margin": gross_margin,
        "margin_after_recorded_refunds": gross_margin - refund_amount,
        "refund_amount": refund_amount,
        "refund_rate": refunded_items / sold_items if sold_items else pd.NA,
    }


def _grain_expression(column: str, grain: str) -> str:
    if grain == "Day":
        return f"date({column})"
    if grain == "Week":
        return f"date({column}, '-' || ((strftime('%w', {column}) + 6) % 7) || ' days')"
    if grain == "Quarter":
        return f"strftime('%Y', {column}) || '-Q' || CAST(((CAST(strftime('%m', {column}) AS INTEGER) - 1) / 3 + 1) AS INTEGER)"
    return f"strftime('%Y-%m', {column})"


def _period_labels(period: DatePeriod, grain: str) -> list[str]:
    start = pd.Timestamp(period.start)
    final = pd.Timestamp(period.end) - pd.Timedelta(days=1)
    if grain == "Day":
        return [value.strftime("%Y-%m-%d") for value in pd.date_range(start, final, freq="D")]
    if grain == "Week":
        monday = start - pd.Timedelta(days=start.weekday())
        return [value.strftime("%Y-%m-%d") for value in pd.date_range(monday, final, freq="7D")]
    if grain == "Quarter":
        return [f"{value.year}-Q{value.quarter}" for value in pd.period_range(start, final, freq="Q")]
    return [value.strftime("%Y-%m") for value in pd.date_range(start, final, freq="MS")]


def overview_trend(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    grain: str = "Month",
    revenue_basis: str = "Gross",
) -> pd.DataFrame:
    if revenue_basis not in {"Gross", "Net"}:
        raise ValueError(f"Unsupported revenue basis: {revenue_basis}")
    sessions_cte, session_params = _filtered_sessions_cte(filters, period)
    session_bucket = _grain_expression("s.created_at", grain)
    sessions = query_df(
        path,
        f"""
        WITH {sessions_cte}
        SELECT {session_bucket} AS period, COUNT(*) AS sessions
        FROM filtered_sessions s
        GROUP BY 1 ORDER BY 1
        """,
        session_params,
    )
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    order_bucket = _grain_expression("o.created_at", grain)
    orders = query_df(
        path,
        f"""
        SELECT {order_bucket} AS period,
               COUNT(o.order_id) AS orders,
               COALESCE(SUM(o.price_usd), 0) AS gross_revenue,
               COALESCE(SUM(o.cogs_usd), 0) AS cogs
        FROM orders o
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE o.created_at >= ? AND o.created_at < ? AND {dimension_where}
        GROUP BY 1 ORDER BY 1
        """,
        [start, end, *dimension_params],
    )
    item_bucket = _grain_expression("oi.created_at", grain)
    sold = query_df(
        path,
        f"""
        SELECT {item_bucket} AS period, COUNT(oi.order_item_id) AS sold_items
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE oi.created_at >= ? AND oi.created_at < ? AND {dimension_where}
        GROUP BY 1 ORDER BY 1
        """,
        [start, end, *dimension_params],
    )
    refund_bucket = _grain_expression("r.created_at", grain)
    refunds = query_df(
        path,
        f"""
        SELECT {refund_bucket} AS period,
               COUNT(r.order_item_refund_id) AS refunded_items,
               COALESCE(SUM(r.refund_amount_usd), 0) AS refund_amount
        FROM order_item_refunds r
        JOIN order_items oi ON oi.order_item_id = r.order_item_id
        JOIN orders o ON o.order_id = oi.order_id
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE r.created_at >= ? AND r.created_at < ? AND {dimension_where}
        GROUP BY 1
        """,
        [start, end, *dimension_params],
    )
    frame = pd.DataFrame({"period": _period_labels(period, grain)})
    for component in (sessions, orders, sold, refunds):
        frame = frame.merge(component, on="period", how="left")
    numeric = ["sessions", "orders", "gross_revenue", "cogs", "sold_items", "refunded_items", "refund_amount"]
    frame[numeric] = frame[numeric].fillna(0).apply(pd.to_numeric)
    frame["net_revenue"] = frame["gross_revenue"] - frame["refund_amount"]
    frame["revenue"] = frame["net_revenue"] if revenue_basis == "Net" else frame["gross_revenue"]
    frame["conversion_rate"] = frame["orders"].div(
        frame["sessions"].replace(0, pd.NA)
    )
    frame["aov"] = frame["gross_revenue"].div(frame["orders"].replace(0, pd.NA))
    frame["refund_rate"] = frame["refunded_items"].div(
        frame["sold_items"].replace(0, pd.NA)
    )
    frame["gross_margin"] = frame["gross_revenue"] - frame["cogs"]
    frame["margin_after_recorded_refunds"] = frame["gross_margin"] - frame["refund_amount"]
    return frame


def revenue_driver_contributions(
    current: dict[str, float | int],
    prior: dict[str, float | int] | None,
    *,
    revenue_basis: str = "Gross",
) -> pd.DataFrame:
    """Return an order-independent accounting decomposition of revenue change.

    The three gross-revenue terms use the Shapley value across every ordering of
    sessions, order rate, and gross AOV. If event-period orders exist without
    event-period sessions, an explicit timing residual preserves reconciliation.
    Net revenue adds the signed impact of recorded refunds. These are accounting
    contributions, not causal effects.
    """

    columns = [
        "driver",
        "current",
        "comparison",
        "value_label",
        "value_format",
        "contribution",
    ]
    if revenue_basis not in {"Gross", "Net"}:
        raise ValueError(f"Unsupported revenue basis: {revenue_basis}")
    if prior is None:
        return pd.DataFrame(
            {
                "driver": pd.Series(dtype="object"),
                "current": pd.Series(dtype="float64"),
                "comparison": pd.Series(dtype="float64"),
                "value_label": pd.Series(dtype="object"),
                "value_format": pd.Series(dtype="object"),
                "contribution": pd.Series(dtype="float64"),
            }
        )

    factor_keys = ("sessions", "conversion_rate", "aov")
    labels = {
        "sessions": "Sessions",
        "conversion_rate": "Order rate",
        "aov": "Gross AOV",
    }
    formats = {
        "sessions": "integer",
        "conversion_rate": "percent",
        "aov": "currency",
    }
    current_values = {key: _number(current.get(key, 0)) for key in factor_keys}
    prior_values = {key: _number(prior.get(key, 0)) for key in factor_keys}
    contributions = {key: 0.0 for key in factor_keys}

    def gross_revenue(values: dict[str, float]) -> float:
        return values["sessions"] * values["conversion_rate"] * values["aov"]

    orderings = tuple(permutations(factor_keys))
    for ordering in orderings:
        state = dict(prior_values)
        for factor in ordering:
            before = gross_revenue(state)
            state[factor] = current_values[factor]
            contributions[factor] += gross_revenue(state) - before

    rows = [
        {
            "driver": labels[factor],
            "current": current_values[factor],
            "comparison": prior_values[factor],
            "value_label": labels[factor],
            "value_format": formats[factor],
            "contribution": contributions[factor] / len(orderings),
        }
        for factor in factor_keys
    ]
    factor_total = sum(row["contribution"] for row in rows)
    current_gross = _number(
        current.get("gross_revenue"), gross_revenue(current_values)
    )
    prior_gross = _number(
        prior.get("gross_revenue"), gross_revenue(prior_values)
    )
    timing_residual = (current_gross - prior_gross) - factor_total
    if abs(timing_residual) >= 0.005:
        rows.append(
            {
                "driver": "Order/session timing residual",
                "current": pd.NA,
                "comparison": pd.NA,
                "value_label": "Order/session timing residual",
                "value_format": "currency",
                "contribution": timing_residual,
            }
        )
    if revenue_basis == "Net":
        current_refunds = _number(current.get("refund_amount", 0))
        prior_refunds = _number(prior.get("refund_amount", 0))
        rows.append(
            {
                "driver": "Recorded-refund impact",
                "current": current_refunds,
                "comparison": prior_refunds,
                "value_label": "Recorded refunds",
                "value_format": "currency",
                "contribution": -(current_refunds - prior_refunds),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def segment_contributions(
    current: pd.DataFrame,
    prior: pd.DataFrame | None,
    *,
    value_column: str = "revenue",
    segment_column: str = "segment",
) -> pd.DataFrame:
    """Outer-join segment values and calculate additive change contributions."""

    result_columns = [
        segment_column,
        "current",
        "comparison",
        "absolute_delta",
        "share_of_total_delta",
    ]
    if prior is None:
        return pd.DataFrame(
            {
                segment_column: pd.Series(dtype="object"),
                "current": pd.Series(dtype="float64"),
                "comparison": pd.Series(dtype="float64"),
                "absolute_delta": pd.Series(dtype="float64"),
                "share_of_total_delta": pd.Series(dtype="float64"),
            }
        )
    for name, frame in (("current", current), ("comparison", prior)):
        missing = {segment_column, value_column} - set(frame.columns)
        if missing:
            raise ValueError(f"{name} segment frame is missing: {', '.join(sorted(missing))}")

    current_values = (
        current.groupby(segment_column, dropna=False)[value_column]
        .sum()
        .rename("current")
    )
    prior_values = (
        prior.groupby(segment_column, dropna=False)[value_column]
        .sum()
        .rename("comparison")
    )
    result = pd.concat([current_values, prior_values], axis=1).fillna(0).reset_index()
    result["absolute_delta"] = result["current"] - result["comparison"]
    total_delta = float(result["absolute_delta"].sum())
    if abs(total_delta) >= 0.005:
        result["share_of_total_delta"] = result["absolute_delta"] / total_delta
    else:
        result["share_of_total_delta"] = pd.Series(pd.NA, index=result.index, dtype="Float64")
    result["_sort"] = result["absolute_delta"].abs()
    return (
        result.sort_values(["_sort", segment_column], ascending=[False, True])
        .drop(columns="_sort")
        .reset_index(drop=True)[result_columns]
    )


SESSION_DIMENSION_EXPRESSIONS = {
    "Traffic source": TRAFFIC_SOURCE_SQL.format(alias="s"),
    "UTM source": "COALESCE(NULLIF(s.utm_source, 'NULL'), 'Untracked')",
    "Campaign": "COALESCE(NULLIF(s.utm_campaign, 'NULL'), 'Untracked')",
    "Device": "s.device_type",
    "Session type": "CASE WHEN s.is_repeat_session = 1 THEN 'Repeat' ELSE 'New' END",
    "Referrer type": REFERRER_TYPE_SQL.format(alias="s"),
}

DIMENSION_EXPRESSIONS = {
    **SESSION_DIMENSION_EXPRESSIONS,
    "Ad content": "COALESCE(NULLIF(s.utm_content, 'NULL'), 'Untracked')",
    "Landing page": "COALESCE(fp.pageview_url, 'No pageview')",
}


def acquisition_performance(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    dimension: str = "Traffic source",
    landing_pages: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    if dimension not in DIMENSION_EXPRESSIONS:
        raise ValueError(f"Unsupported acquisition dimension: {dimension}")
    landing_clause = ""
    landing_params: list[object] = []
    if landing_pages is not None:
        if not landing_pages:
            landing_clause = "AND 1 = 0"
        else:
            landing_clause = f"AND fp.pageview_url IN ({','.join('?' for _ in landing_pages)})"
            landing_params.extend(landing_pages)
    segment = DIMENSION_EXPRESSIONS[dimension]
    first_page_cte = """
        first_page AS (
            SELECT p.website_session_id, p.pageview_url
            FROM website_pageviews p
            JOIN (
                SELECT website_session_id, MIN(website_pageview_id) AS first_id
                FROM website_pageviews GROUP BY website_session_id
            ) x ON x.first_id = p.website_pageview_id
        )
    """
    session_where, session_params = build_session_predicate(filters, period, alias="s")
    sessions = query_df(
        path,
        f"""
        WITH {first_page_cte}
        SELECT {segment} AS segment,
               COUNT(s.website_session_id) AS sessions
        FROM website_sessions s
        LEFT JOIN first_page fp ON fp.website_session_id = s.website_session_id
        WHERE {session_where} {landing_clause}
        GROUP BY 1
        """,
        [*session_params, *landing_params],
    )
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    orders = query_df(
        path,
        f"""
        WITH {first_page_cte}
        SELECT {segment} AS segment,
               COUNT(o.order_id) AS orders,
               COALESCE(SUM(o.price_usd), 0) AS revenue,
               COALESCE(SUM(o.price_usd - o.cogs_usd), 0) AS gross_margin
        FROM orders o
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        LEFT JOIN first_page fp ON fp.website_session_id = s.website_session_id
        WHERE o.created_at >= ? AND o.created_at < ? AND {dimension_where} {landing_clause}
        GROUP BY 1
        """,
        [start, end, *dimension_params, *landing_params],
    )
    frame = sessions.merge(orders, on="segment", how="outer")
    if frame.empty:
        return frame.assign(conversion_rate=pd.Series(dtype=float), revenue_per_session=pd.Series(dtype=float), margin_per_session=pd.Series(dtype=float))
    numeric = ["sessions", "orders", "revenue", "gross_margin"]
    frame[numeric] = frame[numeric].fillna(0).apply(pd.to_numeric)
    denominator = frame["sessions"].replace(0, pd.NA)
    frame["conversion_rate"] = frame["orders"].div(denominator)
    frame["revenue_per_session"] = frame["revenue"].div(denominator)
    frame["margin_per_session"] = frame["gross_margin"].div(denominator)
    return frame.sort_values(["revenue", "sessions"], ascending=False).reset_index(drop=True)


def overview_drivers(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    dimension: str = "Traffic source",
    revenue_basis: str = "Gross",
) -> pd.DataFrame:
    if revenue_basis not in {"Gross", "Net"}:
        raise ValueError(f"Unsupported revenue basis: {revenue_basis}")
    if dimension not in SESSION_DIMENSION_EXPRESSIONS:
        raise ValueError(f"Unsupported overview driver dimension: {dimension}")
    expression = SESSION_DIMENSION_EXPRESSIONS[dimension]
    session_where, session_params = build_session_predicate(filters, period, alias="s")
    sessions = query_df(
        path,
        f"""
        SELECT {expression} AS segment, COUNT(*) AS sessions
        FROM website_sessions s
        WHERE {session_where}
        GROUP BY 1
        """,
        session_params,
    )
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    orders = query_df(
        path,
        f"""
        SELECT {expression} AS segment,
               COUNT(o.order_id) AS orders,
               COALESCE(SUM(o.price_usd), 0) AS gross_revenue,
               COALESCE(SUM(o.price_usd - o.cogs_usd), 0) AS gross_margin
        FROM orders o
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE o.created_at >= ? AND o.created_at < ? AND {dimension_where}
        GROUP BY 1
        """,
        [start, end, *dimension_params],
    )
    refunds = query_df(
        path,
        f"""
        SELECT {expression} AS segment,
               COALESCE(SUM(r.refund_amount_usd), 0) AS refund_amount
        FROM order_item_refunds r
        JOIN order_items oi ON oi.order_item_id = r.order_item_id
        JOIN orders o ON o.order_id = oi.order_id
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE r.created_at >= ? AND r.created_at < ? AND {dimension_where}
        GROUP BY 1
        """,
        [start, end, *dimension_params],
    )
    frame = sessions.merge(orders, on="segment", how="outer").merge(refunds, on="segment", how="outer").fillna(0)
    if frame.empty:
        return frame.assign(
            net_revenue=pd.Series(dtype=float),
            revenue=pd.Series(dtype=float),
            conversion_rate=pd.Series(dtype=float),
            revenue_per_session=pd.Series(dtype=float),
            margin_per_session=pd.Series(dtype=float),
        )
    frame["net_revenue"] = frame["gross_revenue"] - frame["refund_amount"]
    frame["revenue"] = frame["net_revenue"] if revenue_basis == "Net" else frame["gross_revenue"]
    denominator = frame["sessions"].replace(0, pd.NA)
    frame["conversion_rate"] = frame["orders"].div(denominator)
    frame["revenue_per_session"] = frame["revenue"].div(denominator)
    frame["margin_per_session"] = frame["gross_margin"].div(denominator)
    return frame.sort_values(["revenue", "sessions"], ascending=False).reset_index(drop=True)


def _value_clause(values: tuple[str, ...] | None, params: list[object]) -> str:
    if values is None:
        return "1 = 1"
    if not values:
        return "1 = 0"
    params.extend(values)
    return f"IN ({','.join('?' for _ in values)})"


def _funnel_ctes(
    filters: FilterSpec,
    period: DatePeriod,
    product_pages: tuple[str, ...] | None,
    funnel_version: str,
) -> tuple[str, list[object]]:
    sessions_cte, params = _filtered_sessions_cte(filters, period)
    selected_products = PRODUCT_URLS if product_pages is None else product_pages
    if not selected_products:
        selected_products = ("__no_product_page__",)
    product_marks = ",".join("?" for _ in selected_products)
    params.extend(selected_products)
    billing_urls = {
        "All": ("/billing", "/billing-2"),
        "/billing": ("/billing",),
        "/billing-2": ("/billing-2",),
    }.get(funnel_version)
    if billing_urls is None:
        raise ValueError(f"Unsupported funnel version: {funnel_version}")
    billing_marks = ",".join("?" for _ in billing_urls)
    params.extend(billing_urls)
    ctes = f"""
        {sessions_cte},
        first_page AS (
            SELECT p.website_session_id,
                   p.website_pageview_id AS landing_id,
                   p.pageview_url AS landing_page
            FROM website_pageviews p
            JOIN (
                SELECT website_session_id, MIN(website_pageview_id) AS first_id
                FROM website_pageviews GROUP BY website_session_id
            ) x ON x.first_id = p.website_pageview_id
        ),
        events AS (
            SELECT s.website_session_id, s.traffic_source, s.campaign,
                   s.device_type, s.session_type, fp.landing_page, fp.landing_id,
                   MIN(CASE WHEN p.pageview_url = '/products' THEN p.website_pageview_id END) AS products_id,
                   MIN(CASE WHEN p.pageview_url IN ({product_marks}) THEN p.website_pageview_id END) AS product_id,
                   MIN(CASE WHEN p.pageview_url = '/cart' THEN p.website_pageview_id END) AS cart_id,
                   MIN(CASE WHEN p.pageview_url = '/shipping' THEN p.website_pageview_id END) AS shipping_id,
                   MIN(CASE WHEN p.pageview_url IN ({billing_marks}) THEN p.website_pageview_id END) AS billing_id,
                   MIN(CASE WHEN p.pageview_url = '/thank-you-for-your-order' THEN p.website_pageview_id END) AS thank_id
            FROM filtered_sessions s
            LEFT JOIN first_page fp ON fp.website_session_id = s.website_session_id
            LEFT JOIN website_pageviews p ON p.website_session_id = s.website_session_id
            GROUP BY s.website_session_id, s.traffic_source, s.campaign,
                     s.device_type, s.session_type, fp.landing_page, fp.landing_id
        ),
        reached AS (
            SELECT *,
                   CASE WHEN products_id > landing_id THEN 1 ELSE 0 END AS products,
                   CASE WHEN product_id > products_id AND products_id > landing_id THEN 1 ELSE 0 END AS product_detail,
                   CASE WHEN cart_id > product_id AND product_id > products_id AND products_id > landing_id THEN 1 ELSE 0 END AS cart,
                   CASE WHEN shipping_id > cart_id AND cart_id > product_id AND product_id > products_id AND products_id > landing_id THEN 1 ELSE 0 END AS shipping,
                   CASE WHEN billing_id > shipping_id AND shipping_id > cart_id AND cart_id > product_id AND product_id > products_id AND products_id > landing_id THEN 1 ELSE 0 END AS billing,
                   CASE WHEN thank_id > billing_id AND billing_id > shipping_id AND shipping_id > cart_id AND cart_id > product_id AND product_id > products_id AND products_id > landing_id THEN 1 ELSE 0 END AS thank_you
            FROM events
        )
    """
    return ctes, params


def _funnel_cohort_filter(
    landing_pages: tuple[str, ...] | None,
    product_pages: tuple[str, ...] | None,
    params: list[object],
) -> str:
    clauses = ["1 = 1"]
    if landing_pages is not None:
        if landing_pages:
            clauses.append(f"landing_page IN ({','.join('?' for _ in landing_pages)})")
            params.extend(landing_pages)
        else:
            clauses.append("1 = 0")
    if product_pages is not None and not product_pages:
        clauses.append("1 = 0")
    return " AND ".join(clauses)


def funnel_summary(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    landing_pages: tuple[str, ...] | None = None,
    product_pages: tuple[str, ...] | None = None,
    funnel_version: str = "All",
) -> pd.DataFrame:
    ctes, params = _funnel_ctes(filters, period, product_pages, funnel_version)
    cohort_filter = _funnel_cohort_filter(landing_pages, product_pages, params)
    result = query_df(
        path,
        f"""
        WITH {ctes}
        SELECT COUNT(*) AS landing,
               COALESCE(SUM(products), 0) AS products,
               COALESCE(SUM(product_detail), 0) AS product_detail,
               COALESCE(SUM(cart), 0) AS cart,
               COALESCE(SUM(shipping), 0) AS shipping,
               COALESCE(SUM(billing), 0) AS billing,
               COALESCE(SUM(thank_you), 0) AS thank_you
        FROM reached WHERE {cohort_filter}
        """,
        params,
    ).iloc[0]
    stages = [
        ("Landing", int(result["landing"])),
        ("Products", int(result["products"])),
        ("Product detail", int(result["product_detail"])),
        ("Cart", int(result["cart"])),
        ("Shipping", int(result["shipping"])),
        ("Billing", int(result["billing"])),
        ("Thank-you", int(result["thank_you"])),
    ]
    rows = []
    total = stages[0][1]
    previous = total
    previous_name: str | None = None
    for name, count in stages:
        rows.append(
            {
                "stage": name,
                "transition": None if previous_name is None else f"{previous_name} → {name}",
                "sessions": count,
                "step_conversion": count / previous if previous else pd.NA,
                "total_conversion": count / total if total else pd.NA,
                "drop_off": max(previous - count, 0),
            }
        )
        previous = count
        previous_name = name
    return pd.DataFrame(rows)


def funnel_breakdown(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    compare_by: str = "Device",
    landing_pages: tuple[str, ...] | None = None,
    product_pages: tuple[str, ...] | None = None,
    funnel_version: str = "All",
) -> pd.DataFrame:
    segment_columns = {
        "Device": "device_type",
        "Traffic source": "traffic_source",
        "Campaign": "campaign",
        "Landing page": "landing_page",
        "Session type": "session_type",
    }
    if compare_by not in segment_columns:
        raise ValueError(f"Unsupported funnel comparison: {compare_by}")
    ctes, params = _funnel_ctes(filters, period, product_pages, funnel_version)
    cohort_filter = _funnel_cohort_filter(landing_pages, product_pages, params)
    segment = segment_columns[compare_by]
    frame = query_df(
        path,
        f"""
        WITH {ctes}
        SELECT COALESCE({segment}, 'Untracked') AS segment,
               COUNT(*) AS sessions,
               COALESCE(SUM(thank_you), 0) AS orders
        FROM reached
        WHERE {cohort_filter}
        GROUP BY 1 ORDER BY sessions DESC
        """,
        params,
    )
    if frame.empty:
        return frame.assign(conversion_rate=pd.Series(dtype=float))
    frame["conversion_rate"] = frame["orders"].div(frame["sessions"].replace(0, pd.NA))
    return frame


def _validate_product_filter_values(
    item_roles: tuple[str, ...],
    order_sizes: tuple[str, ...],
) -> None:
    unknown_roles = sorted(set(item_roles) - set(PRODUCT_ROLE_VALUES))
    if unknown_roles:
        raise ValueError("Unsupported item roles: " + ", ".join(unknown_roles))
    unknown_order_sizes = sorted(set(order_sizes) - VALID_ORDER_SIZES)
    if unknown_order_sizes:
        raise ValueError(
            "Unsupported order sizes: " + ", ".join(unknown_order_sizes)
        )


def _product_filter_sql(
    products: tuple[str, ...],
    item_roles: tuple[str, ...],
    order_sizes: tuple[str, ...],
    params: list[object],
) -> str:
    _validate_product_filter_values(item_roles, order_sizes)

    clauses: list[str] = []
    if not products or not item_roles or not order_sizes:
        return "1 = 0"
    clauses.append(f"p.product_name IN ({','.join('?' for _ in products)})")
    params.extend(products)
    roles = tuple(PRODUCT_ROLE_VALUES[value] for value in item_roles)
    clauses.append(f"oi.is_primary_item IN ({','.join('?' for _ in roles)})")
    params.extend(roles)
    size_expressions = []
    if "Single-item" in order_sizes:
        size_expressions.append("o.items_purchased = 1")
    if "Multi-item" in order_sizes:
        size_expressions.append("o.items_purchased > 1")
    clauses.append(f"({' OR '.join(size_expressions)})")
    return " AND ".join(clauses)


def product_performance(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    products: tuple[str, ...],
    item_roles: tuple[str, ...],
    order_sizes: tuple[str, ...],
    date_basis: str = "Purchase date",
) -> pd.DataFrame:
    result_columns = [
        "product", "units", "revenue", "cogs", "addon_units", "units_refunded",
        "refunded_amount", "gross_margin", "net_revenue", "refund_rate", "addon_unit_share",
    ]
    if not products or not item_roles or not order_sizes:
        return pd.DataFrame({column: pd.Series(dtype="object" if column == "product" else "float64") for column in result_columns})
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    dimension_sessions_cte = f"""
        dimension_sessions AS (
            SELECT s.* FROM website_sessions s WHERE {dimension_where}
        )
    """
    sales_params = [*dimension_params, start, end]
    sales_filter = _product_filter_sql(products, item_roles, order_sizes, sales_params)
    sales = query_df(
        path,
        f"""
        WITH {dimension_sessions_cte}
        SELECT p.product_name AS product,
               COUNT(oi.order_item_id) AS units,
               COALESCE(SUM(oi.price_usd), 0) AS revenue,
               COALESCE(SUM(oi.cogs_usd), 0) AS cogs,
               SUM(CASE WHEN oi.is_primary_item = 0 THEN 1 ELSE 0 END) AS addon_units
        FROM dimension_sessions s
        JOIN orders o ON o.website_session_id = s.website_session_id
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE oi.created_at >= ? AND oi.created_at < ? AND {sales_filter}
        GROUP BY p.product_name
        """,
        sales_params,
    )

    refund_params: list[object] = []
    if date_basis == "Purchase date":
        refund_params.extend([*dimension_params, start, end])
        refund_filter = _product_filter_sql(products, item_roles, order_sizes, refund_params)
        refund_sql = f"""
            WITH {dimension_sessions_cte}
            SELECT p.product_name AS product,
                   COUNT(DISTINCT r.order_item_id) AS units_refunded,
                   COALESCE(SUM(r.refund_amount_usd), 0) AS refunded_amount
            FROM dimension_sessions s
            JOIN orders o ON o.website_session_id = s.website_session_id
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            JOIN order_item_refunds r ON r.order_item_id = oi.order_item_id
            WHERE oi.created_at >= ? AND oi.created_at < ? AND {refund_filter}
            GROUP BY p.product_name
        """
    elif date_basis == "Refund date":
        dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
        refund_params.extend([start, end, *dimension_params])
        refund_filter = _product_filter_sql(products, item_roles, order_sizes, refund_params)
        refund_sql = f"""
            SELECT p.product_name AS product,
                   COUNT(r.order_item_refund_id) AS units_refunded,
                   COALESCE(SUM(r.refund_amount_usd), 0) AS refunded_amount
            FROM order_item_refunds r
            JOIN order_items oi ON oi.order_item_id = r.order_item_id
            JOIN orders o ON o.order_id = oi.order_id
            JOIN website_sessions s ON s.website_session_id = o.website_session_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE r.created_at >= ? AND r.created_at < ?
              AND {dimension_where} AND {refund_filter}
            GROUP BY p.product_name
        """
    else:
        raise ValueError(f"Unsupported date basis: {date_basis}")
    refunds = query_df(path, refund_sql, refund_params)

    base = pd.DataFrame({"product": pd.Series(list(products), dtype="object")})
    result = base.merge(sales, on="product", how="left").merge(refunds, on="product", how="left")
    numeric = ["units", "revenue", "cogs", "addon_units", "units_refunded", "refunded_amount"]
    result[numeric] = result[numeric].fillna(0)
    result[["units", "addon_units", "units_refunded"]] = result[["units", "addon_units", "units_refunded"]].astype(int)
    result["gross_margin"] = result["revenue"] - result["cogs"]
    result["net_revenue"] = result["revenue"] - result["refunded_amount"]
    result["refund_rate"] = result["units_refunded"].div(
        result["units"].replace(0, pd.NA)
    )
    result["addon_unit_share"] = result["addon_units"].div(
        result["units"].replace(0, pd.NA)
    )
    return result


def product_trend(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    products: tuple[str, ...],
    item_roles: tuple[str, ...],
    order_sizes: tuple[str, ...],
    date_basis: str = "Purchase date",
) -> pd.DataFrame:
    rows = []
    current = period.start
    while current < period.end:
        next_month = DatePeriod(current, DatePeriod.from_months(current.strftime("%Y-%m"), current.strftime("%Y-%m")).end)
        frame = product_performance(
            path,
            filters,
            next_month,
            products=products,
            item_roles=item_roles,
            order_sizes=order_sizes,
            date_basis=date_basis,
        )
        frame.insert(0, "period", current.strftime("%Y-%m"))
        rows.append(frame)
        current = next_month.end
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def aggregate_product_trend(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["period", metric])
    if metric == "refund_rate":
        grouped = frame.groupby("period", as_index=False)[["units_refunded", "units"]].sum()
        grouped[metric] = grouped["units_refunded"].div(
            grouped["units"].replace(0, pd.NA)
        )
        return grouped[["period", metric]]
    if metric == "addon_unit_share":
        grouped = frame.groupby("period", as_index=False)[["addon_units", "units"]].sum()
        grouped[metric] = grouped["addon_units"].div(
            grouped["units"].replace(0, pd.NA)
        )
        return grouped[["period", metric]]
    return frame.groupby("period", as_index=False)[metric].sum()


def basket_mix(
    path: str | Path,
    filters: FilterSpec,
    period: DatePeriod,
    *,
    products: tuple[str, ...] | None = None,
    item_roles: tuple[str, ...] | None = None,
    order_sizes: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    _validate_product_filter_values(item_roles or (), order_sizes or ())
    dimension_where, dimension_params = _dimension_where(filters, period, alias="s")
    start, end = period.sql_bounds()
    params: list[object] = [start, end, *dimension_params]
    clauses = ["o.created_at >= ?", "o.created_at < ?", dimension_where]
    if order_sizes is not None:
        size_parts = []
        if "Single-item" in order_sizes:
            size_parts.append("o.items_purchased = 1")
        if "Multi-item" in order_sizes:
            size_parts.append("o.items_purchased > 1")
        clauses.append(f"({' OR '.join(size_parts)})" if size_parts else "1 = 0")
    if products is not None or item_roles is not None:
        if products is not None and not products or item_roles is not None and not item_roles:
            clauses.append("1 = 0")
        else:
            exists_parts = ["oi.order_id = o.order_id"]
            if products is not None:
                exists_parts.append(f"p.product_name IN ({','.join('?' for _ in products)})")
                params.extend(products)
            if item_roles is not None:
                role_values = tuple(PRODUCT_ROLE_VALUES[value] for value in item_roles)
                exists_parts.append(f"oi.is_primary_item IN ({','.join('?' for _ in role_values)})")
                params.extend(role_values)
            clauses.append(
                "EXISTS (SELECT 1 FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
                f"WHERE {' AND '.join(exists_parts)})"
            )
    return query_df(
        path,
        f"""
        SELECT CASE WHEN o.items_purchased = 1 THEN 'Single-item' ELSE 'Multi-item' END AS order_size,
               COUNT(*) AS orders,
               COALESCE(SUM(o.price_usd), 0) AS revenue,
               COALESCE(AVG(o.price_usd), 0) AS aov
        FROM orders o
        JOIN website_sessions s ON s.website_session_id = o.website_session_id
        WHERE {' AND '.join(clauses)}
        GROUP BY 1 ORDER BY order_size DESC
        """,
        params,
    )
