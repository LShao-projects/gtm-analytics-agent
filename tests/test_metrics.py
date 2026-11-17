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
        "refund_amount": 50.0,
        "refund_rate": pytest.approx(1 / 3),
    }


def test_overview_net_basis_changes_revenue_and_margin(analytics_db):
    result = overview_kpis(analytics_db, FilterSpec(), MAY, revenue_basis="Net")

    assert result["revenue"] == 80.0
    assert result["gross_margin"] == 30.0


def test_overview_revenue_uses_order_timestamp_at_month_boundary(analytics_db):
    import sqlite3

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
    trend = overview_trend(analytics_db, FilterSpec(), MAY, grain="Day")
    assert trend["conversion_rate"].replace([float("inf"), float("-inf")], __import__("pandas").NA).notna().all()


def test_acquisition_groups_real_session_and_order_grains(analytics_db):
    result = acquisition_performance(
        analytics_db, FilterSpec(), MAY, dimension="Traffic source"
    ).set_index("segment")

    assert result.loc["Paid Search", "sessions"] == 1
    assert result.loc["Paid Search", "revenue"] == 80.0
    assert result.loc["Paid Social", "sessions"] == 1
    assert result.loc["Paid Social", "orders"] == 0
    assert result.loc["Organic Search", "conversion_rate"] == 1.0


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
    original = funnel_summary(analytics_db, FilterSpec(), MAY, funnel_version="Original")
    optimized = funnel_summary(analytics_db, FilterSpec(), MAY, funnel_version="Optimized")

    assert original.loc[original["stage"] == "Billing", "sessions"].item() == 1
    assert optimized.loc[optimized["stage"] == "Billing", "sessions"].item() == 1


def test_selected_product_page_constrains_all_downstream_funnel_stages(analytics_db):
    result = funnel_summary(
        analytics_db,
        FilterSpec(),
        MAY,
        product_pages=("/the-forever-love-bear",),
    )

    assert result["sessions"].tolist() == [1, 1, 1, 1, 0, 0, 0]
    assert (result["step_conversion"] <= 1).all()


def test_empty_product_page_selection_returns_empty_funnel_cohort(analytics_db):
    result = funnel_summary(analytics_db, FilterSpec(), MAY, product_pages=())

    assert result["sessions"].tolist() == [0, 0, 0, 0, 0, 0, 0]


def test_funnel_breakdown_uses_same_landing_product_and_version_controls(analytics_db):
    result = funnel_breakdown(
        analytics_db,
        FilterSpec(),
        MAY,
        compare_by="Device",
        landing_pages=("/home",),
        product_pages=("/the-original-mr-fuzzy",),
        funnel_version="Original",
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
    assert result.loc["Love Bear", "attachment_rate"] == 1.0


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


def test_purchase_date_uses_item_timestamp_not_session_timestamp(analytics_db):
    import sqlite3

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


def test_daily_overview_trend_keeps_refund_only_days_and_refund_rate(analytics_db):
    import sqlite3

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


def test_aggregate_product_trend_uses_weighted_rates():
    frame = __import__("pandas").DataFrame(
        {
            "period": ["2014-05", "2014-05"],
            "units": [10, 90],
            "units_refunded": [2, 3],
            "addon_units": [5, 10],
            "refund_rate": [0.2, 1 / 30],
            "attachment_rate": [0.5, 1 / 9],
        }
    )

    refunds = aggregate_product_trend(frame, "refund_rate")
    attachment = aggregate_product_trend(frame, "attachment_rate")

    assert refunds.loc[0, "refund_rate"] == pytest.approx(0.05)
    assert attachment.loc[0, "attachment_rate"] == pytest.approx(0.15)
