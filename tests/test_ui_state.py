from pathlib import Path

import pandas as pd

from dashboard.data import DatabaseMetadata
from dashboard.models import DatePeriod
from dashboard.ui import (
    _comparison_rule,
    _available_comparison_modes,
    _delta,
    _effective_filter_values,
    _filter_selection_default,
    _filter_accessible_description,
    _format_detail_table,
    _format_value,
    _funnel_has_evidence,
    _has_metric_evidence,
    _metric_formula,
    _metric_help,
    _merge_option_dicts,
    _months,
    _excluded_partial_month,
    _reporting_window_months,
    _refund_measure_label,
    _segment_comparison_frame,
    _option_state_key,
    _product_has_evidence,
    _product_totals,
    _render_product_filters,
    _context_chips,
    filter_trigger_label,
    format_filter_option,
    render_metrics,
    selection_summary,
)


def test_reporting_window_presets_and_custom_dates_are_predictable():
    months = tuple(f"2024-{month:02d}" for month in range(1, 13))

    assert _reporting_window_months(months, "Latest 3 covered months") == (
        "2024-10",
        "2024-12",
    )
    assert _reporting_window_months(months, "Latest 6 covered months") == (
        "2024-07",
        "2024-12",
    )
    assert _reporting_window_months(months, "All covered history") == (
        "2024-01",
        "2024-12",
    )
    assert _reporting_window_months(months, "Custom", "2024-09", "2024-03") == (
        "2024-03",
        "2024-09",
    )

    all_history = DatePeriod.from_months("2024-01", "2024-12")
    late_window = DatePeriod.from_months("2024-11", "2024-12")
    assert _available_comparison_modes(all_history, months[0]) == ("None",)
    assert _available_comparison_modes(late_window, months[0]) == (
        "Previous period",
        "None",
    )


def test_previous_year_is_disabled_when_it_would_overlap_a_long_current_window():
    period = DatePeriod.from_months("2023-01", "2024-01")

    assert period.month_count == 13
    assert _available_comparison_modes(period, "2020-01") == (
        "Previous period",
        "None",
    )


def test_report_numbers_use_two_decimal_places_and_integer_counts():
    assert _format_value(1234.567, "currency") == "$1.23K"
    assert _format_value(0.07654, "percent") == "7.65%"
    assert _delta(125, 100) == "+25.00 (+25.00%)"
    assert _delta(0.06, 0.05, "percent") == "+1.00 pp (+20.00%)"
    assert _format_value(-1234.567, "currency") == "-$1.23K"

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
    assert "percentage-point change" in rate_help
    assert "comparison value is zero" in zero_help


def test_metric_help_uses_page_specific_formulas_and_dynamic_controls():
    period = DatePeriod.from_months("2014-01", "2014-06")

    assert "gross order revenue − refund amount" in _metric_help(
        "revenue", 100, None, "currency", "None", period, None, "overview", {"revenue_basis": "Net"}
    )
    assert "event-period order events ÷ event-period session events" in _metric_help(
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
            "gross_revenue",
            "orders",
            "sessions",
            "conversion_rate",
            "aov",
            "gross_margin",
            "margin_after_recorded_refunds",
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


def test_filter_all_mode_survives_option_expansion_while_subsets_remain_explicit():
    original = ("desktop", "mobile")
    expanded = (*original, "tablet")

    inferred, inferred_all, removed = _filter_selection_default(
        original,
        original,
        original,
        None,
    )
    assert (inferred, inferred_all, removed) == ((), True, ())

    expanded_default, expanded_all, removed = _filter_selection_default(
        expanded,
        (),
        original,
        True,
    )
    assert (expanded_default, expanded_all, removed) == ((), True, ())

    subset_default, subset_all, removed = _filter_selection_default(
        expanded,
        ("desktop",),
        original,
        False,
    )
    assert (subset_default, subset_all, removed) == (("desktop",), False, ())


def test_filter_summary_reports_all_one_partial_and_none():
    options = ("desktop", "mobile")

    assert selection_summary("Device", options, options, all_label="All devices") == "All devices"
    assert selection_summary("Device", options, ("desktop",), all_label="All devices") == "Desktop"
    assert selection_summary("Device", options, (), all_label="All devices") == "No devices"
    assert _effective_filter_values(options, options) is None
    assert _effective_filter_values(options, ("desktop",)) == ("desktop",)
    assert _effective_filter_values((), ()) == ()


def test_comparison_options_merge_current_and_prior_without_gap_values():
    merged = _merge_option_dicts(
        {"landing": ("/current",), "device": ("desktop",)},
        {"landing": ("/prior",), "device": ("mobile", "desktop")},
    )

    assert merged == {
        "landing": ("/current", "/prior"),
        "device": ("desktop", "mobile"),
    }


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
            "Product-detail page",
            long_options,
            long_options[:2],
            all_label="All product-detail pages",
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


def test_complete_months_exclude_partial_first_and_last_core_months():
    metadata = DatabaseMetadata(
        path=Path("example.db"),
        table_count=6,
        session_min="2012-03-19 08:04:16",
        session_max="2015-03-19 07:59:08",
        pageview_max="2015-03-19 07:59:32",
        order_max="2015-03-19 05:38:31",
        item_max="2015-03-19 05:38:31",
        refund_max="2015-04-01 18:11:08",
    )

    months = _months(metadata)

    assert months[0] == "2012-04"
    assert months[-1] == "2015-02"
    assert len(months) == 35
    exclusion = _excluded_partial_month(metadata)
    assert "Mar 2012" in exclusion
    assert "Mar 2015" in exclusion


def test_complete_month_cutoff_uses_earliest_core_fact_boundary():
    metadata = DatabaseMetadata(
        path=Path("example.db"),
        table_count=6,
        session_min="2024-01-01 00:01:00",
        session_max="2024-06-30 23:59:00",
        pageview_max="2024-06-30 23:59:30",
        order_max="2024-05-17 12:00:00",
        item_max="2024-06-30 23:58:00",
        refund_max="2024-07-03 09:00:00",
    )

    assert _months(metadata) == ("2024-01", "2024-02", "2024-03", "2024-04")
    assert "May 2024" in _excluded_partial_month(metadata)


def test_refund_measure_label_is_explicit_about_date_basis():
    assert _refund_measure_label("Purchase date") == "Purchase-cohort refund rate"
    assert _refund_measure_label("Refund date") == "Refund event ratio"


def test_product_totals_do_not_report_zero_rate_without_a_denominator():
    frame = pd.DataFrame(
        {
            "units": [0],
            "units_refunded": [1],
            "revenue": [0.0],
            "gross_margin": [0.0],
            "refunded_amount": [30.0],
        }
    )

    totals = _product_totals(frame)

    assert pd.isna(totals["refund_rate"])
    assert totals["refunded_amount"] == 30.0


def test_empty_state_evidence_helpers_accept_prior_only_business_evidence():
    empty_funnel = pd.DataFrame({"sessions": [0]})
    prior_funnel = pd.DataFrame({"sessions": [12]})
    empty_products = pd.DataFrame(
        {"units": [0], "units_refunded": [0], "refunded_amount": [0.0]}
    )
    prior_products = pd.DataFrame(
        {"units": [2], "units_refunded": [0], "refunded_amount": [0.0]}
    )

    assert not _has_metric_evidence(
        {"sessions": 0, "orders": 0}, ("sessions", "orders")
    )
    assert _has_metric_evidence(
        {"sessions": 12, "orders": 0}, ("sessions", "orders")
    )
    assert not _funnel_has_evidence(empty_funnel)
    assert _funnel_has_evidence(prior_funnel)
    assert not _product_has_evidence(empty_products)
    assert _product_has_evidence(prior_products)


def test_metric_cards_use_four_columns_per_complete_row(monkeypatch):
    column_counts = []

    class FakeColumn:
        def metric(self, *args, **kwargs):
            return None

    def fake_columns(count, **kwargs):
        column_counts.append(count)
        return [FakeColumn() for _ in range(count)]

    monkeypatch.setattr("dashboard.ui.st.columns", fake_columns)
    keys = (
        "gross_revenue",
        "orders",
        "sessions",
        "conversion_rate",
        "aov",
        "gross_margin",
        "refund_rate",
        "net_revenue",
    )
    render_metrics(
        {key: 1 for key in keys},
        None,
        keys,
        "None",
        DatePeriod.from_months("2014-01", "2014-01"),
        None,
        "overview",
    )

    assert column_counts == [4, 4]


def test_page_context_is_compact_labeled_summary_without_pills(monkeypatch):
    markup = []
    monkeypatch.setattr(
        "dashboard.ui.st.markdown",
        lambda value, **kwargs: markup.append(value),
    )

    _context_chips(
        DatePeriod.from_months("2014-04", "2014-04"),
        DatePeriod.from_months("2014-03", "2014-03"),
        "Previous period",
        ("Traffic source: Paid Social",),
        ("Revenue basis: Gross",),
        ("Last observed sessions: Mar 19, 2015",),
    )

    summary = markup[0]
    assert "context-summary" in summary
    assert "context-chip" not in summary
    assert all(
        f"context-label'>{label}" in summary
        for label in ("Current", "Compare", "Scope", "Freshness", "Calendar")
    )
    assert f" {chr(183)} " not in summary


def test_add_on_only_products_force_multi_item_order_size(monkeypatch):
    seen_options = {}

    def fake_checkbox(label, options, key, *, all_label):
        seen_options[label] = options
        if label == "Item role":
            return ("Add-on",)
        return options

    monkeypatch.setattr("dashboard.ui._section", lambda *args, **kwargs: None)
    monkeypatch.setattr("dashboard.ui.checkbox_group", fake_checkbox)
    monkeypatch.setattr(
        "dashboard.ui._ui_select",
        lambda label, options, key, **kwargs: options[0],
    )
    monkeypatch.setattr("dashboard.ui.st.caption", lambda *args, **kwargs: None)

    controls = _render_product_filters(
        {
            "product": ("Original Mr. Fuzzy",),
            "item_role": ("Primary", "Add-on"),
            "order_size": ("Single-item", "Multi-item"),
        }
    )

    assert seen_options["Order size"] == ("Multi-item",)
    assert controls["sizes"] == ("Multi-item",)


def test_segment_comparison_handles_metric_that_is_also_default_denominator():
    current = pd.DataFrame({"segment": ["A", "B"], "sessions": [10, 5]})
    prior = pd.DataFrame({"segment": ["A", "C"], "sessions": [8, 4]})

    result = _segment_comparison_frame(current, prior, "sessions")

    assert result.set_index("segment")["absolute_delta"].to_dict() == {
        "A": 2,
        "B": 5,
        "C": -4,
    }
    assert "current_denominator" not in result
