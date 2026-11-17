from __future__ import annotations

from datetime import datetime

from dashboard.models import DatePeriod, FilterSpec, _add_months


TRAFFIC_SOURCE_SQL = """CASE
    WHEN NULLIF({alias}.utm_source, 'NULL') IN ('gsearch', 'bsearch') THEN 'Paid Search'
    WHEN NULLIF({alias}.utm_source, 'NULL') = 'socialbook' THEN 'Paid Social'
    WHEN NULLIF({alias}.utm_source, 'NULL') IS NULL AND NULLIF({alias}.http_referer, 'NULL') IS NOT NULL THEN 'Organic Search'
    WHEN NULLIF({alias}.utm_source, 'NULL') IS NULL AND NULLIF({alias}.http_referer, 'NULL') IS NULL THEN 'Direct'
    ELSE 'Other'
END"""

REFERRER_TYPE_SQL = """CASE
    WHEN NULLIF({alias}.utm_source, 'NULL') IS NOT NULL THEN 'Paid'
    WHEN NULLIF({alias}.http_referer, 'NULL') IS NOT NULL THEN 'Organic'
    ELSE 'Direct'
END"""

CAMPAIGN_LABEL_TO_RAW = {
    "Brand": "brand",
    "Nonbrand": "nonbrand",
    "Desktop targeted": "desktop_targeted",
    "Pilot": "pilot",
    "Untracked": None,
}

SOURCE_CAMPAIGNS = {
    "Paid Search": ("Brand", "Nonbrand"),
    "Paid Social": ("Desktop targeted", "Pilot"),
    "Organic Search": ("Untracked",),
    "Direct": ("Untracked",),
    "Other": ("Untracked",),
}


def comparison_period(current: DatePeriod, mode: str) -> DatePeriod | None:
    if mode == "None":
        return None
    if mode == "Previous period":
        return DatePeriod(_add_months(current.start, -current.month_count), current.start)
    if mode == "Previous year":
        return DatePeriod(_add_months(current.start, -12), _add_months(current.end, -12))
    raise ValueError(f"Unsupported comparison mode: {mode}")


def campaign_options_for_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    values: set[str] = set()
    for source in sources:
        values.update(SOURCE_CAMPAIGNS.get(source, ()))
    order = ("Brand", "Nonbrand", "Desktop targeted", "Pilot", "Untracked")
    return tuple(value for value in order if value in values)


def _in_clause(expression: str, values: tuple[object, ...], params: list[object]) -> str:
    if not values:
        return "1 = 0"
    params.extend(values)
    return f"{expression} IN ({','.join('?' for _ in values)})"


def build_session_predicate(
    filters: FilterSpec,
    period: DatePeriod,
    *,
    alias: str = "s",
    include_period: bool = True,
) -> tuple[str, list[object]]:
    """Build a parameterized predicate with OR within and AND across dimensions."""

    start, end = period.sql_bounds()
    params: list[object] = [start, end] if include_period else []
    clauses = (
        [f"{alias}.created_at >= ?", f"{alias}.created_at < ?"]
        if include_period
        else []
    )

    if filters.traffic_sources is not None:
        expression = TRAFFIC_SOURCE_SQL.format(alias=alias)
        clauses.append(_in_clause(expression, filters.traffic_sources, params))

    if filters.campaigns is not None:
        raw_values = tuple(
            CAMPAIGN_LABEL_TO_RAW[value]
            for value in filters.campaigns
            if CAMPAIGN_LABEL_TO_RAW.get(value) is not None
        )
        includes_null = "Untracked" in filters.campaigns
        pieces: list[str] = []
        if raw_values:
            pieces.append(_in_clause(f"NULLIF({alias}.utm_campaign, 'NULL')", raw_values, params))
        if includes_null:
            pieces.append(f"NULLIF({alias}.utm_campaign, 'NULL') IS NULL")
        clauses.append(f"({' OR '.join(pieces)})" if pieces else "1 = 0")

    if filters.devices is not None:
        clauses.append(_in_clause(f"{alias}.device_type", filters.devices, params))

    if filters.session_types is not None:
        session_values = tuple(1 if value == "Repeat" else 0 for value in filters.session_types)
        clauses.append(_in_clause(f"{alias}.is_repeat_session", session_values, params))

    if filters.ad_contents is not None:
        pieces = []
        raw_values = tuple(value for value in filters.ad_contents if value != "Untracked")
        if raw_values:
            pieces.append(_in_clause(f"NULLIF({alias}.utm_content, 'NULL')", raw_values, params))
        if "Untracked" in filters.ad_contents:
            pieces.append(f"NULLIF({alias}.utm_content, 'NULL') IS NULL")
        clauses.append(f"({' OR '.join(pieces)})" if pieces else "1 = 0")

    if filters.referrer_types is not None:
        expression = REFERRER_TYPE_SQL.format(alias=alias)
        clauses.append(_in_clause(expression, filters.referrer_types, params))

    return (" AND ".join(clauses) if clauses else "1 = 1"), params

