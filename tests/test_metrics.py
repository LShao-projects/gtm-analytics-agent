import sqlite3

import pandas as pd
import pytest

from dashboard.metrics import (
    acquisition_performance,
    aggregate_product_trend,
    basket_mix,
    funnel_breakdown,
    funnel_summary,
    overview_drivers,
    overview_kpis,
    overview_trend,
    product_performance,
    revenue_driver_contributions,
    segment_contributions,
)
from dashboard.models import DatePeriod, FilterSpec


MAY = DatePeriod.from_months("2014-05", "2014-05")


def test_overview_kpis_reconcile_without_pageview_or_item_duplication(analytics_db):
    result = overview_kpis(analytics_db, FilterSpec(), MAY, revenue_basis="Gross")

    assert result == {
        "revenue": 130.0,
        "gross_revenue": 130.0,
        "net_revenue": 80.0,
        "orders": 2,
        "sessions": 3,
        "conversion_rate": pytest.approx(2 / 3),
        "aov": 65.0,
        "gross_margin": 80.0,
        "margin_after_recorded_refunds": 30.0,
        "refund_amount": 50.0,
        "refund_rate": pytest.approx(1 / 3),
    }


def test_overview_net_basis_changes_revenue_without_relabeling_gross_margin(analytics_db):
    result = overview_kpis(analytics_db, FilterSpec(), MAY, revenue_basis="Net")

    assert result["revenue"] == 80.0
    assert result["gross_margin"] == 80.0
    assert result["margin_after_recorded_refunds"] == 30.0


def test_overview_and_acquisition_use_order_timestamp_at_month_boundary(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO website_sessions VALUES (6, '2014-04-30 23:59:00', 6, 0, 'gsearch', 'brand', 'g_ad_2', 'desktop', 'https://www.gsearch.com')"
        )
        connection.execute(
            "INSERT INTO orders VALUES (4, '2014-05-01 00:01:00', 6, 6, 2, 1, 30, 10)"
        )
        connection.execute(
            "INSERT INTO order_items VALUES (5, '2014-05-01 00:01:00', 4, 2, 1, 30, 10)"
        )

    result = overview_kpis(analytics_db, FilterSpec(), MAY)

    assert result["gross_revenue"] == 160.0
    assert result["orders"] == 3
    drivers = overview_drivers(analytics_db, FilterSpec(), MAY)
    assert drivers["revenue"].sum() == 160.0
    acquisition = acquisition_performance(
        analytics_db, FilterSpec(), MAY, dimension="Traffic source"
    ).set_index("segment")
    assert acquisition.loc["Paid Search", "sessions"] == 1
    assert acquisition.loc["Paid Search", "orders"] == 2
    assert acquisition.loc["Paid Search", "revenue"] == 110.0
    trend = overview_trend(analytics_db, FilterSpec(), MAY, grain="Day")
    assert not trend["conversion_rate"].isin([float("inf"), float("-inf")]).any()
    assert trend["conversion_rate"].isna().any()


def test_acquisition_groups_real_session_and_order_grains(analytics_db):
    result = acquisition_performance(
        analytics_db, FilterSpec(), MAY, dimension="Traffic source"
    ).set_index("segment")

    assert result.loc["Paid Search", "sessions"] == 1
    assert result.loc["Paid Search", "revenue"] == 80.0
    assert result.loc["Paid Social", "sessions"] == 1
    assert result.loc["Paid Social", "orders"] == 0
    assert result.loc["Organic Search", "conversion_rate"] == 1.0


def test_acquisition_does_not_duplicate_sessions_when_one_session_has_multiple_orders(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO orders VALUES (4, '2014-05-05 11:00:00', 1, 1, 1, 1, 20, 8)"
        )

    result = acquisition_performance(
        analytics_db, FilterSpec(), MAY, dimension="UTM source"
    ).set_index("segment")

    assert result.loc["gsearch", "sessions"] == 1
    assert result.loc["gsearch", "orders"] == 2
    assert result.loc["gsearch", "revenue"] == 100.0


def test_acquisition_order_only_segment_keeps_zero_sessions_and_null_rates(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO website_sessions VALUES "
            "(6, '2014-04-30 23:58:00', 6, 0, 'lateorder', 'brand', "
            "'late_ad', 'desktop', 'https://www.gsearch.com')"
        )
        connection.execute(
            "INSERT INTO website_pageviews VALUES "
            "(27, '2014-04-30 23:58:30', 6, '/home')"
        )
        connection.execute(
            "INSERT INTO orders VALUES "
            "(4, '2014-05-01 00:01:00', 6, 6, 2, 1, 30, 10)"
        )

    result = acquisition_performance(
        analytics_db, FilterSpec(), MAY, dimension="UTM source"
    ).set_index("segment")

    assert result.loc["lateorder", "sessions"] == 0
    assert result.loc["lateorder", "orders"] == 1
    assert pd.isna(result.loc["lateorder", "conversion_rate"])
    assert pd.isna(result.loc["lateorder", "revenue_per_session"])
    assert pd.isna(result.loc["lateorder", "margin_per_session"])


def test_literal_null_acquisition_values_are_filterable_as_untracked(analytics_db):
    result = overview_kpis(
        analytics_db,
        FilterSpec(traffic_sources=("Organic Search",), campaigns=("Untracked",)),
        MAY,
    )

    assert result["sessions"] == 1
    assert result["orders"] == 1


def test_funnel_counts_ordered_stages_and_dropoff(analytics_db):
    result = funnel_summary(analytics_db, FilterSpec(), MAY)

    assert result["stage"].tolist() == [
        "Landing", "Products", "Product detail", "Cart", "Shipping", "Billing", "Thank-you"
    ]
    assert result["sessions"].tolist() == [3, 3, 3, 3, 2, 2, 2]
    assert result.loc[result["stage"] == "Shipping", "step_conversion"].item() == pytest.approx(2 / 3)
    assert result.loc[result["stage"] == "Thank-you", "total_conversion"].item() == pytest.approx(2 / 3)


def test_funnel_version_uses_selected_billing_page(analytics_db):
    billing = funnel_summary(analytics_db, FilterSpec(), MAY, funnel_version="/billing")
    billing_2 = funnel_summary(
        analytics_db, FilterSpec(), MAY, funnel_version="/billing-2"
    )

    assert billing.loc[billing["stage"] == "Billing", "sessions"].item() == 1
    assert billing_2.loc[billing_2["stage"] == "Billing", "sessions"].item() == 1


def test_selected_product_page_constrains_all_downstream_funnel_stages(analytics_db):
    result = funnel_summary(
        analytics_db,
        FilterSpec(),
        MAY,
        product_pages=("/the-forever-love-bear",),
    )

    assert result["sessions"].tolist() == [3, 3, 1, 1, 0, 0, 0]
    assert (result["step_conversion"].dropna() <= 1).all()
    assert result.loc[result["stage"] == "Cart", "transition"].item() == "Product detail → Cart"


def test_empty_product_page_selection_returns_empty_funnel_cohort(analytics_db):
    result = funnel_summary(analytics_db, FilterSpec(), MAY, product_pages=())

    assert result["sessions"].tolist() == [0, 0, 0, 0, 0, 0, 0]
    assert result["step_conversion"].isna().all()
    assert result["total_conversion"].isna().all()


def test_funnel_breakdown_uses_same_landing_product_and_version_controls(analytics_db):
    result = funnel_breakdown(
        analytics_db,
        FilterSpec(),
        MAY,
        compare_by="Device",
        landing_pages=("/home",),
        product_pages=("/the-original-mr-fuzzy",),
        funnel_version="/billing",
    ).set_index("segment")

    assert result.loc["desktop", "sessions"] == 2
    assert result.loc["desktop", "orders"] == 1
    assert result.loc["desktop", "conversion_rate"] == 0.5


def test_product_purchase_cohort_uses_items_not_order_totals(analytics_db):
    result = product_performance(
        analytics_db,
        FilterSpec(),
        MAY,
        products=("Original Fuzzy", "Love Bear"),
        item_roles=("Primary", "Add-on"),
        order_sizes=("Single-item", "Multi-item"),
        date_basis="Purchase date",
    ).set_index("product")

    assert result.loc["Original Fuzzy", "units"] == 2
    assert result.loc["Original Fuzzy", "revenue"] == 100.0
    assert result.loc["Original Fuzzy", "refund_rate"] == 0.5
    assert result.loc["Love Bear", "units"] == 1
    assert result.loc["Love Bear", "addon_unit_share"] == 1.0


def test_product_refund_date_basis_counts_period_events(analytics_db):
    april = DatePeriod.from_months("2014-04", "2014-04")
    result = product_performance(
        analytics_db,
        FilterSpec(),
        april,
        products=("Original Fuzzy",),
        item_roles=("Primary",),
        order_sizes=("Single-item", "Multi-item"),
        date_basis="Refund date",
    )

    assert result.loc[0, "units_refunded"] == 0
    assert result.loc[0, "refunded_amount"] == 0.0
    assert result.loc[0, "refund_rate"] == 0.0
    assert result.loc[0, "addon_unit_share"] == 0.0


def test_purchase_cohort_counts_refunded_items_not_duplicate_refund_events(
    analytics_db,
):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO order_item_refunds VALUES (2, '2014-06-15 12:00:00', 1, 1, 10)"
        )

    result = product_performance(
        analytics_db,
        FilterSpec(),
        MAY,
        products=("Original Fuzzy",),
        item_roles=("Primary",),
        order_sizes=("Single-item", "Multi-item"),
        date_basis="Purchase date",
    )

    assert result.loc[0, "units_refunded"] == 1
    assert result.loc[0, "refunded_amount"] == 60.0
    assert result.loc[0, "refund_rate"] == 0.5


def test_refund_date_basis_preserves_refund_only_product_activity(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO order_item_refunds VALUES (2, '2014-06-15 12:00:00', 3, 2, 30)"
        )
    june = DatePeriod.from_months("2014-06", "2014-06")

    result = product_performance(
        analytics_db,
        FilterSpec(),
        june,
        products=("Original Fuzzy",),
        item_roles=("Primary",),
        order_sizes=("Single-item", "Multi-item"),
        date_basis="Refund date",
    )

    assert result.loc[0, "units"] == 0
    assert result.loc[0, "units_refunded"] == 1
    assert result.loc[0, "refunded_amount"] == 30.0
    assert pd.isna(result.loc[0, "refund_rate"])


def test_empty_product_selection_returns_typed_empty_frame(analytics_db):
    result = product_performance(
        analytics_db,
        FilterSpec(),
        MAY,
        products=(),
        item_roles=("Primary", "Add-on"),
        order_sizes=("Single-item", "Multi-item"),
    )

    assert result.empty
    assert "product" in result.columns


@pytest.mark.parametrize(
    ("item_roles", "order_sizes", "message"),
    [
        (("Primary", "Bundle"), ("Single-item",), "Unsupported item roles: Bundle"),
        (("Primary",), ("Bulk",), "Unsupported order sizes: Bulk"),
    ],
)
def test_product_filters_reject_unknown_values_before_querying(
    analytics_db,
    item_roles,
    order_sizes,
    message,
):
    with pytest.raises(ValueError, match=message):
        product_performance(
            analytics_db,
            FilterSpec(),
            MAY,
            products=("Original Fuzzy",),
            item_roles=item_roles,
            order_sizes=order_sizes,
        )


def test_purchase_date_uses_item_timestamp_not_session_timestamp(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO website_sessions VALUES (6, '2014-04-30 23:59:00', 6, 0, 'gsearch', 'brand', 'g_ad_2', 'desktop', 'https://www.gsearch.com')"
        )
        connection.execute(
            "INSERT INTO orders VALUES (4, '2014-05-01 00:01:00', 6, 6, 2, 1, 30, 10)"
        )
        connection.execute(
            "INSERT INTO order_items VALUES (5, '2014-05-01 00:01:00', 4, 2, 1, 30, 10)"
        )
    result = product_performance(
        analytics_db,
        FilterSpec(),
        MAY,
        products=("Love Bear",),
        item_roles=("Primary", "Add-on"),
        order_sizes=("Single-item", "Multi-item"),
    )

    assert result.loc[0, "units"] == 2
    assert result.loc[0, "revenue"] == 60.0


def test_basket_mix_reports_single_and_multi_order_counts(analytics_db):
    result = basket_mix(analytics_db, FilterSpec(), MAY).set_index("order_size")

    assert result.loc["Single-item", "orders"] == 1
    assert result.loc["Multi-item", "orders"] == 1


def test_basket_mix_applies_order_size_filter(analytics_db):
    result = basket_mix(
        analytics_db,
        FilterSpec(),
        MAY,
        products=("Original Fuzzy", "Love Bear"),
        item_roles=("Primary", "Add-on"),
        order_sizes=("Multi-item",),
    )

    assert result["order_size"].tolist() == ["Multi-item"]


@pytest.mark.parametrize(
    ("item_roles", "order_sizes", "message"),
    [
        (("Primary", "Bundle"), ("Single-item",), "Unsupported item roles: Bundle"),
        (("Primary",), ("Bulk",), "Unsupported order sizes: Bulk"),
    ],
)
def test_basket_mix_rejects_unknown_filter_values(
    analytics_db, item_roles, order_sizes, message
):
    with pytest.raises(ValueError, match=message):
        basket_mix(
            analytics_db,
            FilterSpec(),
            MAY,
            item_roles=item_roles,
            order_sizes=order_sizes,
        )


def test_daily_overview_trend_keeps_refund_only_days_and_refund_rate(analytics_db):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO order_item_refunds VALUES (2, '2014-06-15 12:00:00', 2, 1, 30)"
        )
    june = DatePeriod.from_months("2014-06", "2014-06")

    kpis = overview_kpis(analytics_db, FilterSpec(), june, revenue_basis="Net")
    trend = overview_trend(analytics_db, FilterSpec(), june, grain="Day", revenue_basis="Net")

    assert trend["net_revenue"].sum() == kpis["net_revenue"] == -30.0
    assert "2014-06-15" in trend["period"].tolist()
    assert "refund_rate" in trend.columns
    assert trend["gross_margin"].sum() == 0.0
    assert trend["margin_after_recorded_refunds"].sum() == -30.0
    assert kpis["conversion_rate"] == 0.0
    assert pd.isna(kpis["aov"])
    assert pd.isna(kpis["refund_rate"])
    refund_day = trend.loc[trend["period"] == "2014-06-15"].iloc[0]
    assert pd.isna(refund_day["conversion_rate"])
    assert pd.isna(refund_day["aov"])
    assert pd.isna(refund_day["refund_rate"])


def test_overview_trend_keeps_gross_margin_invariant_across_revenue_bases(analytics_db):
    gross = overview_trend(
        analytics_db, FilterSpec(), MAY, grain="Day", revenue_basis="Gross"
    )
    net = overview_trend(
        analytics_db, FilterSpec(), MAY, grain="Day", revenue_basis="Net"
    )

    pd.testing.assert_series_equal(
        gross["gross_margin"], net["gross_margin"], check_names=False
    )
    assert gross["gross_margin"].sum() == net["gross_margin"].sum() == 80.0


def test_aggregate_product_trend_uses_weighted_rates():
    frame = pd.DataFrame(
        {
            "period": ["2014-05", "2014-05"],
            "units": [10, 90],
            "units_refunded": [2, 3],
            "addon_units": [5, 10],
            "refund_rate": [0.2, 1 / 30],
            "addon_unit_share": [0.5, 1 / 9],
        }
    )

    refunds = aggregate_product_trend(frame, "refund_rate")
    addon_mix = aggregate_product_trend(frame, "addon_unit_share")

    assert refunds.loc[0, "refund_rate"] == pytest.approx(0.05)
    assert addon_mix.loc[0, "addon_unit_share"] == pytest.approx(0.15)


def test_revenue_driver_contributions_reconcile_gross_and_net_change():
    prior = {
        "sessions": 100,
        "conversion_rate": 0.10,
        "aov": 50.0,
        "gross_revenue": 500.0,
        "refund_amount": 20.0,
    }
    current = {
        "sessions": 120,
        "conversion_rate": 0.12,
        "aov": 55.0,
        "gross_revenue": 792.0,
        "refund_amount": 30.0,
    }

    gross = revenue_driver_contributions(current, prior, revenue_basis="Gross")
    net = revenue_driver_contributions(current, prior, revenue_basis="Net")

    assert gross["contribution"].sum() == pytest.approx(292.0)
    assert net["contribution"].sum() == pytest.approx(282.0)
    assert net.set_index("driver").loc["Recorded refunds", "contribution"] == -10.0


def test_revenue_driver_contributions_reconcile_order_session_timing_residual():
    prior = {
        "sessions": 0,
        "conversion_rate": 0.0,
        "aov": 0.0,
        "gross_revenue": 0.0,
        "refund_amount": 0.0,
    }
    current = {
        "sessions": 0,
        "conversion_rate": 0.0,
        "aov": 50.0,
        "gross_revenue": 50.0,
        "refund_amount": 10.0,
    }

    gross = revenue_driver_contributions(current, prior, revenue_basis="Gross")
    net = revenue_driver_contributions(current, prior, revenue_basis="Net")

    assert gross["contribution"].sum() == pytest.approx(50.0)
    assert net["contribution"].sum() == pytest.approx(40.0)
    assert (
        gross.set_index("driver").loc["Order/session timing residual", "contribution"]
        == pytest.approx(50.0)
    )


def test_revenue_driver_contributions_missing_prior_returns_stable_typed_schema():
    current = {
        "sessions": 120,
        "conversion_rate": 0.12,
        "aov": 55.0,
        "gross_revenue": 792.0,
        "refund_amount": 30.0,
    }

    result = revenue_driver_contributions(current, None)

    assert result.empty
    assert result.columns.tolist() == ["driver", "contribution"]
    assert result["driver"].dtype == "object"
    assert result["contribution"].dtype == "float64"


@pytest.mark.parametrize("metric_function", [overview_kpis, overview_trend])
def test_overview_metrics_reject_invalid_revenue_basis(analytics_db, metric_function):
    with pytest.raises(ValueError, match="Unsupported revenue basis"):
        metric_function(
            analytics_db,
            FilterSpec(),
            MAY,
            revenue_basis="Adjusted",
        )


@pytest.mark.parametrize("prior", [None, {}])
def test_revenue_driver_contributions_reject_invalid_basis_with_or_without_prior(prior):
    current = {
        "sessions": 120,
        "conversion_rate": 0.12,
        "aov": 55.0,
        "gross_revenue": 792.0,
        "refund_amount": 30.0,
    }

    with pytest.raises(ValueError, match="Unsupported revenue basis"):
        revenue_driver_contributions(current, prior, revenue_basis="Adjusted")


def test_segment_contributions_outer_join_and_reconcile_total_delta():
    current = pd.DataFrame(
        {"segment": ["Continuing", "New"], "revenue": [80.0, 30.0]}
    )
    prior = pd.DataFrame(
        {"segment": ["Continuing", "Exited"], "revenue": [100.0, 10.0]}
    )

    result = segment_contributions(current, prior).set_index("segment")

    assert result.loc["Continuing", "absolute_delta"] == -20.0
    assert result.loc["New", "absolute_delta"] == 30.0
    assert result.loc["Exited", "absolute_delta"] == -10.0
    assert result["absolute_delta"].sum() == 0.0
    assert result["share_of_total_delta"].isna().all()


def test_segment_contributions_sort_and_share_reconcile_nonzero_total_delta():
    current = pd.DataFrame(
        {"segment": ["Continuing", "New"], "revenue": [80.0, 50.0]}
    )
    prior = pd.DataFrame(
        {"segment": ["Continuing", "Exited"], "revenue": [100.0, 10.0]}
    )

    result = segment_contributions(current, prior)
    indexed = result.set_index("segment")

    assert result["segment"].tolist() == ["New", "Continuing", "Exited"]
    assert result["absolute_delta"].sum() == pytest.approx(20.0)
    assert result["share_of_total_delta"].sum() == pytest.approx(1.0)
    assert indexed.loc["New", "share_of_total_delta"] == pytest.approx(2.5)
    assert indexed.loc["Continuing", "share_of_total_delta"] == pytest.approx(-1.0)
    assert indexed.loc["Exited", "share_of_total_delta"] == pytest.approx(-0.5)


def test_segment_contribution_share_is_unavailable_for_sub_cent_float_residual():
    current = pd.DataFrame({"segment": ["A", "B"], "revenue": [0.1, 0.2]})
    prior = pd.DataFrame({"segment": ["A", "B"], "revenue": [0.3, 0.0]})

    result = segment_contributions(current, prior)

    assert abs(result["absolute_delta"].sum()) < 0.005
    assert result["share_of_total_delta"].isna().all()


def test_overview_driver_net_basis_includes_refunds_and_raw_utm_source(analytics_db):
    gross = overview_drivers(
        analytics_db, FilterSpec(), MAY, dimension="UTM source", revenue_basis="Gross"
    ).set_index("segment")
    net = overview_drivers(
        analytics_db, FilterSpec(), MAY, dimension="UTM source", revenue_basis="Net"
    ).set_index("segment")

    assert gross.loc["gsearch", "gross_revenue"] == 80.0
    assert gross.loc["gsearch", "refund_amount"] == 50.0
    assert gross.loc["gsearch", "revenue"] == 80.0
    assert net.loc["gsearch", "revenue"] == 30.0


@pytest.mark.parametrize("revenue_basis", ["Gross", "Net"])
def test_overview_drivers_empty_result_keeps_complete_revenue_schema(
    analytics_db, revenue_basis
):
    empty_period = DatePeriod.from_months("2016-01", "2016-01")

    result = overview_drivers(
        analytics_db,
        FilterSpec(),
        empty_period,
        dimension="UTM source",
        revenue_basis=revenue_basis,
    )

    assert result.empty
    assert {"gross_revenue", "refund_amount", "net_revenue", "revenue"} <= set(
        result.columns
    )
