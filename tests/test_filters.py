from datetime import datetime

from dashboard.filters import (
    build_session_predicate,
    campaign_options_for_sources,
    comparison_period,
)
from dashboard.models import DatePeriod, FilterSpec


def test_month_period_uses_half_open_boundaries():
    period = DatePeriod.from_months("2014-05", "2014-06")

    assert period.start == datetime(2014, 5, 1)
    assert period.end == datetime(2014, 7, 1)
    assert period.label == "May 1–Jun 30, 2014"


def test_previous_period_keeps_same_number_of_calendar_months():
    current = DatePeriod.from_months("2014-05", "2014-06")

    previous = comparison_period(current, "Previous period")

    assert previous.start == datetime(2014, 3, 1)
    assert previous.end == datetime(2014, 5, 1)


def test_previous_year_handles_year_boundary():
    current = DatePeriod.from_months("2015-01", "2015-03")

    previous = comparison_period(current, "Previous year")

    assert previous.start == datetime(2014, 1, 1)
    assert previous.end == datetime(2014, 4, 1)


def test_campaign_choices_follow_selected_sources():
    assert campaign_options_for_sources(("Paid Search",)) == ("Brand", "Nonbrand")
    assert campaign_options_for_sources(("Paid Social",)) == (
        "Desktop targeted",
        "Pilot",
    )
    assert campaign_options_for_sources(("Direct", "Paid Search")) == (
        "Brand",
        "Nonbrand",
        "Untracked",
    )


def test_session_predicate_uses_or_within_dimension_and_and_across_dimensions():
    filters = FilterSpec(
        traffic_sources=("Paid Search", "Paid Social"),
        campaigns=("Nonbrand", "Pilot"),
        devices=("desktop",),
        session_types=("New",),
    )
    period = DatePeriod.from_months("2014-05", "2014-05")

    sql, params = build_session_predicate(filters, period, alias="s")

    assert " IN (?,?)" in sql
    assert " AND " in sql
    assert params == [
        "2014-05-01 00:00:00",
        "2014-06-01 00:00:00",
        "Paid Search",
        "Paid Social",
        "nonbrand",
        "pilot",
        "desktop",
        0,
    ]


def test_empty_selected_dimension_matches_no_sessions():
    filters = FilterSpec(devices=())
    period = DatePeriod.from_months("2014-05", "2014-05")

    sql, _ = build_session_predicate(filters, period, alias="s")

    assert "1 = 0" in sql
