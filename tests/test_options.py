import sqlite3

from dashboard.models import DatePeriod, FilterSpec
from dashboard.options import (
    acquisition_filter_options,
    funnel_filter_options,
    product_filter_options,
    session_dimension_values,
)


APRIL = DatePeriod.from_months("2014-04", "2014-04")
MAY = DatePeriod.from_months("2014-05", "2014-05")


def test_session_options_only_include_values_present_in_period(analytics_db):
    assert session_dimension_values(
        analytics_db, APRIL, FilterSpec(), "traffic_source"
    ) == ("Paid Search",)
    assert session_dimension_values(
        analytics_db, MAY, FilterSpec(), "traffic_source"
    ) == ("Paid Search", "Paid Social", "Organic Search")


def test_page_options_follow_period_and_global_filters(analytics_db):
    april_acquisition = acquisition_filter_options(analytics_db, APRIL, FilterSpec())
    may_funnel = funnel_filter_options(analytics_db, MAY, FilterSpec())

    assert april_acquisition["landing"] == ("/home",)
    assert may_funnel["landing"] == ("/home", "/lander-2")
    assert may_funnel["product_page"] == (
        "/the-original-mr-fuzzy",
        "/the-forever-love-bear",
    )


def test_product_options_include_items_sold_or_refunded_in_period(analytics_db):
    april = product_filter_options(analytics_db, APRIL, FilterSpec())
    may = product_filter_options(analytics_db, MAY, FilterSpec())

    assert april == {
        "product": ("Original Fuzzy",),
        "item_role": ("Primary",),
        "order_size": ("Single-item",),
    }
    assert may == {
        "product": ("Original Fuzzy", "Love Bear"),
        "item_role": ("Primary", "Add-on"),
        "order_size": ("Single-item", "Multi-item"),
    }


def test_refund_only_product_remains_available_without_a_comparison_period(
    analytics_db,
):
    with sqlite3.connect(analytics_db) as connection:
        connection.execute(
            "INSERT INTO order_item_refunds VALUES (2, '2014-06-15 12:00:00', 3, 2, 30)"
        )
    june = DatePeriod.from_months("2014-06", "2014-06")

    options = product_filter_options(analytics_db, june, FilterSpec())

    assert options == {
        "product": ("Original Fuzzy",),
        "item_role": ("Primary",),
        "order_size": ("Single-item",),
    }
