import pandas as pd

from dashboard.models import DatePeriod
from dashboard.ui import (
    _comparison_rule,
    _delta,
    _filter_accessible_description,
    _format_detail_table,
    _format_value,
    _metric_formula,
    _metric_help,
    _reporting_window_months,
    _option_state_key,
    filter_trigger_label,
    format_filter_option,
    selection_summary,
)


def test_reporting_window_presets_and_custom_dates_are_predictable():
    months = tuple(f"2024-{month:02d}" for month in range(1, 13))

    assert _reporting_window_months(months, "Latest 3 months") == ("2024-10", "2024-12")
    assert _reporting_window_months(months, "Latest 6 months") == ("2024-07", "2024-12")
    assert _reporting_window_months(months, "All history") == ("2024-01", "2024-12")
    assert _reporting_window_months(months, "Custom", "2024-09", "2024-03") == (
        "2024-03",
        "2024-09",
    )


def test_report_numbers_use_two_decimal_places_and_integer_counts():
    assert _format_value(1234.567, "currency") == "$1.23K"
    assert _format_value(0.07654, "percent") == "7.65%"
    assert _delta(125, 100) == "+25.00%"

    display = _format_detail_table(
        pd.DataFrame(
            {
                "sessions": [1234.0],
                "conversion_rate": [0.07654321],
                "revenue_per_session": [4.87654321],
            }
        )
    )
    assert display.loc[0, "Sessions"] == 1234
    assert display.loc[0, "Conversion Rate (%)"] == 7.65
    assert display.loc[0, "Revenue Per Session"] == 4.88


def test_metric_help_explains_business_formula_and_exact_comparison_window():
    current = DatePeriod.from_months("2014-06", "2014-06")
    prior = DatePeriod.from_months("2014-05", "2014-05")
    previous_year = DatePeriod.from_months("2013-06", "2013-06")

    currency_help = _metric_help(
        "revenue",
        125,
        100,
        "currency",
        "Previous period",
        current,
        prior,
        "overview",
        {"revenue_basis": "Gross"},
    )
    rate_help = _metric_help(
        "conversion_rate",
        0.06,
        0.05,
        "percent",
        "Previous year",
        current,
        previous_year,
        "acquisition",
    )
    zero_help = _metric_help(
        "orders", 10, 0, "integer", "Previous period", current, prior, "overview"
    )

    assert currency_help.startswith("##### Metric formula")
    assert "> Revenue (gross basis) = sum of order revenue (orders.price_usd)" in currency_help
    assert "| Current | Jun 1–Jun 30, 2014 | **$125.00** |" in currency_help
    assert "| Previous period | May 1–May 31, 2014 | **$100.00** |" in currency_help
    assert f" {chr(183)} " not in currency_help
    assert "Immediately preceding 1 calendar month" in currency_help
    assert "Change shown on card" not in currency_help
    assert "current metric − comparison metric" not in currency_help
    assert "percentage-point differences" not in rate_help
    assert "comparison value is zero" in zero_help


def test_metric_help_uses_page_specific_formulas_and_dynamic_controls():
    period = DatePeriod.from_months("2014-01", "2014-06")

    assert "gross order revenue − refund amount" in _metric_help(
        "revenue", 100, None, "currency", "None", period, None, "overview", {"revenue_basis": "Net"}
    )
    assert "linked orders ÷ selected sessions" in _metric_help(
        "conversion_rate", 0.1, None, "percent", "None", period, None, "acquisition"
    )
    assert "Thank-you-stage sessions ÷ landing-stage sessions" in _metric_help(
        "conversion_rate", 0.1, None, "percent", "None", period, None, "funnel"
    )
    assert "selected order-item prices" in _metric_help(
        "revenue", 100, None, "currency", "None", period, None, "products"
    )
    assert "refund events in the selected period" in _metric_help(
        "refund_rate",
        0.1,
        None,
        "percent",
        "None",
        period,
        None,
        "products",
        {"date_basis": "Refund date"},
    )
    assert "Immediately preceding 6 calendar months" in _comparison_rule("Previous period", period)
    assert "No comparison selected" in _metric_help(
        "units", 10, None, "integer", "None", period, None, "products"
    )


def test_every_rendered_card_has_a_scope_specific_formula():
    card_sets = {
        "overview": (
            "revenue",
            "orders",
            "sessions",
            "conversion_rate",
            "aov",
            "gross_margin",
            "refund_rate",
            "net_revenue",
        ),
        "acquisition": ("sessions", "orders", "conversion_rate", "revenue_per_session"),
        "funnel": ("sessions", "orders", "conversion_rate"),
        "products": ("revenue", "units", "gross_margin", "refund_rate"),
    }
    contexts = {
        "overview": {"revenue_basis": "Gross"},
        "products": {"date_basis": "Purchase date"},
    }

    for scope, keys in card_sets.items():
        for key in keys:
            assert "=" in _metric_formula(scope, key, contexts.get(scope))


def test_checkbox_state_key_depends_on_value_not_position():
    assert _option_state_key("campaign", "Pilot") == _option_state_key("campaign", "Pilot")
    assert _option_state_key("campaign", "Pilot") != _option_state_key("campaign", "Nonbrand")


def test_filter_summary_reports_all_one_partial_and_none():
    options = ("desktop", "mobile")

    assert selection_summary("Device", options, options, all_label="All devices") == "All devices"
    assert selection_summary("Device", options, ("desktop",), all_label="All devices") == "Desktop"
    assert selection_summary("Device", options, (), all_label="All devices") == "No devices"


def test_filter_summary_uses_two_short_names_or_a_count():
    assert (
        selection_summary(
            "Traffic source",
            ("Paid Search", "Direct", "Organic Search"),
            ("Paid Search", "Direct"),
            all_label="All traffic sources",
        )
        == "Paid Search + Direct"
    )
    assert (
        selection_summary(
            "Campaign",
            ("Desktop targeted", "Nonbrand", "Pilot"),
            ("Desktop targeted", "Nonbrand"),
            all_label="All campaigns",
        )
        == "2 selected"
    )


def test_filter_summary_handles_long_and_empty_options():
    long_options = (
        "/the-original-mr-fuzzy",
        "/the-forever-love-bear",
        "/the-birthday-sugar-panda",
    )

    assert (
        selection_summary(
            "Product page",
            long_options,
            long_options[:2],
            all_label="All product pages",
        )
        == "2 selected"
    )
    assert selection_summary("Campaign", (), (), all_label="All campaigns") == "No compatible campaigns"
    assert format_filter_option("desktop") == "Desktop"


def test_filter_accessible_description_names_group_and_current_selection():
    assert (
        _filter_accessible_description("Device", "Desktop")
        == "Device filter. Current selection: Desktop."
    )
    assert filter_trigger_label("Device", "Desktop") == "Device: Desktop"
