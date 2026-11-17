from pathlib import Path

import pytest

from dashboard.data import DatabaseMetadata, REQUIRED_COLUMNS
from dashboard.guide import (
    CAMPAIGN_DEFINITIONS,
    GUIDE_SECTIONS,
    METRIC_GUIDES,
    RELATIONSHIP_ROWS,
    TABLE_SPECS,
    campaign_distribution,
    fact_freshness_inventory,
    masked_value_inventory,
    table_profile,
    table_sample,
    traffic_source_distribution,
    url_inventory,
)


def test_raw_data_guide_covers_every_required_table_and_field():
    assert set(TABLE_SPECS) == set(REQUIRED_COLUMNS)
    for table, required_columns in REQUIRED_COLUMNS.items():
        documented = {field for field, _, _ in TABLE_SPECS[table]["fields"]}
        assert documented == required_columns


def test_table_profiles_and_samples_come_from_the_active_database(analytics_db):
    session_profile = table_profile(analytics_db, "website_sessions")
    assert session_profile == {
        "rows": 5,
        "first_at": "2014-04-05 10:00:00",
        "last_at": "2014-06-02 10:00:00",
    }

    sample = table_sample(analytics_db, "website_sessions")
    assert sample["website_session_id"].tolist() == [1, 2, 3, 4, 5]
    assert len(table_sample(analytics_db, "products")) == 2


def test_guide_rejects_unknown_tables_and_unsafe_sample_sizes(analytics_db):
    with pytest.raises(ValueError, match="Unsupported guide table"):
        table_sample(analytics_db, "unknown")
    with pytest.raises(ValueError, match="between 1 and 20"):
        table_sample(analytics_db, "orders", 21)


def test_traffic_source_guide_shows_only_categories_present_in_data(analytics_db):
    frame = traffic_source_distribution(analytics_db).set_index("traffic_source")

    assert set(frame.index) == {"Paid Search", "Paid Social", "Organic Search", "Direct"}
    assert "Other" not in frame.index
    assert frame["sessions"].to_dict() == {
        "Paid Search": 2,
        "Paid Social": 1,
        "Organic Search": 1,
        "Direct": 1,
    }


def test_campaign_guide_has_concise_meanings_and_current_counts(analytics_db):
    frame = campaign_distribution(analytics_db).set_index("campaign")

    assert set(frame.index) == set(CAMPAIGN_DEFINITIONS)
    assert "trial campaign" in frame.loc["Pilot", "description"]
    assert "desktop users" in frame.loc["Desktop targeted", "description"]
    assert frame.loc["Untracked", "sessions"] == 2
    assert frame.loc["Desktop targeted", "sessions"] == 0


def test_masked_values_are_documented_without_claiming_unknown_content():
    ads, landings = masked_value_inventory()

    assert set(ads["raw_value"]) == {
        "g_ad_1", "g_ad_2", "b_ad_1", "b_ad_2", "social_ad_1", "social_ad_2"
    }
    assert ads.loc[ads["raw_value"] == "b_ad_1", "known_context"].item() == "Bsearch (Nonbrand campaign)"
    assert not ads["known_context"].str.contains(" · ", regex=False).any()
    assert set(landings["raw_value"]) == {
        "/home", "/lander-1", "/lander-2", "/lander-3", "/lander-4", "/lander-5"
    }
    assert landings["known_context"].str.contains("not included").all()


def test_url_inventory_counts_pageviews_and_sessions(analytics_db):
    frame = url_inventory(analytics_db).set_index("pageview_url")

    assert frame.loc["/products", "pageviews"] == 4
    assert frame.loc["/products", "sessions"] == 4


def test_guide_has_three_reference_sections_without_a_free_form_qa_page():
    assert GUIDE_SECTIONS == (
        "Raw Data Dictionary",
        "Derived Dimensions",
        "Metrics & Charts",
    )
    assert set(METRIC_GUIDES) == {
        "Executive Overview",
        "Acquisition",
        "Website Funnel",
        "Products & Refunds",
    }
    assert all("FAQ" not in section and "Q&A" not in section for section in GUIDE_SECTIONS)


def test_product_refund_metrics_use_basis_specific_names():
    product_labels = {row[0] for row in METRIC_GUIDES["Products & Refunds"]}

    assert "Purchase-cohort refund rate (Purchase date)" in product_labels
    assert "Refund event ratio (Refund date)" in product_labels
    assert "Refund rate — Refund date" not in product_labels


def test_funnel_guide_names_thank_you_reach_as_sessions_not_orders():
    funnel_labels = {row[0] for row in METRIC_GUIDES["Website Funnel"]}

    assert "Observed thank-you sessions" in funnel_labels
    assert "Orders" not in funnel_labels


def test_fact_freshness_inventory_keeps_each_table_cutoff_distinct():
    metadata = DatabaseMetadata(
        path=Path("example.db"),
        table_count=6,
        session_min="2012-03-19 08:04:16",
        session_max="2015-03-19 07:59:08",
        pageview_max="2015-03-18 23:59:59",
        order_max="2015-03-17 22:00:00",
        item_max="2015-03-16 21:00:00",
        refund_max="2015-04-01 18:11:08",
    )

    freshness = fact_freshness_inventory(metadata).set_index("Fact table")

    assert freshness["Data through"].to_dict() == {
        "website_sessions": "2015-03-19",
        "website_pageviews": "2015-03-18",
        "orders": "2015-03-17",
        "order_items": "2015-03-16",
        "order_item_refunds": "2015-04-01",
    }


def test_fact_freshness_inventory_marks_missing_cutoffs_unavailable():
    metadata = DatabaseMetadata(
        path=Path("empty.db"),
        table_count=6,
        session_min=None,
        session_max=None,
        pageview_max=None,
        order_max=None,
        item_max=None,
        refund_max=None,
    )

    freshness = fact_freshness_inventory(metadata)

    assert freshness["Data through"].tolist() == ["Unavailable"] * 5


def test_relationship_reference_covers_each_logical_join_once():
    pairs = [(source, target) for source, _, target, _ in RELATIONSHIP_ROWS]

    assert pairs == [
        ("website_sessions", "website_pageviews"),
        ("website_sessions", "orders"),
        ("orders", "order_items"),
        ("order_items", "products"),
        ("order_items", "order_item_refunds"),
    ]
    assert len(pairs) == len(set(pairs))
