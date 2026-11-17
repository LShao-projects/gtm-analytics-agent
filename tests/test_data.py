import sqlite3

import pytest

from dashboard.data import (
    DatabaseQueryError,
    DatabaseValidationError,
    query_df,
    validate_database,
)


REQUIRED_SCHEMAS = {
    "website_sessions": (
        "website_session_id INTEGER PRIMARY KEY, created_at TEXT, user_id INTEGER, "
        "is_repeat_session INTEGER, utm_source TEXT, utm_campaign TEXT, "
        "utm_content TEXT, device_type TEXT, http_referer TEXT"
    ),
    "website_pageviews": (
        "website_pageview_id INTEGER PRIMARY KEY, created_at TEXT, "
        "website_session_id INTEGER, pageview_url TEXT"
    ),
    "orders": (
        "order_id INTEGER PRIMARY KEY, created_at TEXT, website_session_id INTEGER, "
        "user_id INTEGER, primary_product_id INTEGER, items_purchased INTEGER, "
        "price_usd REAL, cogs_usd REAL"
    ),
    "order_items": (
        "order_item_id INTEGER PRIMARY KEY, created_at TEXT, order_id INTEGER, "
        "product_id INTEGER, is_primary_item INTEGER, price_usd REAL, cogs_usd REAL"
    ),
    "order_item_refunds": (
        "order_item_refund_id INTEGER PRIMARY KEY, created_at TEXT, "
        "order_item_id INTEGER, order_id INTEGER, refund_amount_usd REAL"
    ),
    "products": "product_id INTEGER PRIMARY KEY, created_at TEXT, product_name TEXT",
}


def create_schema(path, schemas=REQUIRED_SCHEMAS):
    with sqlite3.connect(path) as connection:
        for table, columns in schemas.items():
            connection.execute(f"CREATE TABLE {table} ({columns})")


def test_validate_database_accepts_all_required_tables_and_columns(tmp_path):
    path = tmp_path / "valid.db"
    create_schema(path)

    metadata = validate_database(path)

    assert metadata.table_count == 6
    assert metadata.session_min is None
    assert metadata.session_max is None
    assert metadata.pageview_max is None
    assert metadata.order_max is None
    assert metadata.item_max is None
    assert metadata.refund_max is None


def test_validate_database_reports_fact_specific_freshness(tmp_path):
    path = tmp_path / "freshness.db"
    create_schema(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO website_sessions VALUES "
            "(1, '2015-03-19 07:59:08', 1, 0, 'gsearch', 'nonbrand', "
            "'g_ad_1', 'desktop', 'https://www.gsearch.com')"
        )
        connection.execute(
            "INSERT INTO website_pageviews VALUES "
            "(1, '2015-03-19 07:59:32', 1, '/home')"
        )
        connection.execute(
            "INSERT INTO orders VALUES "
            "(1, '2015-03-19 05:38:31', 1, 1, 1, 1, 49.99, 19.49)"
        )
        connection.execute(
            "INSERT INTO order_items VALUES "
            "(1, '2015-03-19 05:38:31', 1, 1, 1, 49.99, 19.49)"
        )
        connection.execute(
            "INSERT INTO order_item_refunds VALUES "
            "(1, '2015-04-01 18:11:08', 1, 1, 49.99)"
        )

    metadata = validate_database(path)

    assert metadata.session_min == "2015-03-19 07:59:08"
    assert metadata.session_max == "2015-03-19 07:59:08"
    assert metadata.pageview_max == "2015-03-19 07:59:32"
    assert metadata.order_max == "2015-03-19 05:38:31"
    assert metadata.item_max == "2015-03-19 05:38:31"
    assert metadata.refund_max == "2015-04-01 18:11:08"


def test_validate_database_reports_missing_table(tmp_path):
    path = tmp_path / "missing.db"
    schemas = dict(REQUIRED_SCHEMAS)
    schemas.pop("products")
    create_schema(path, schemas)

    with pytest.raises(DatabaseValidationError, match="products"):
        validate_database(path)


def test_validate_database_reports_missing_column(tmp_path):
    path = tmp_path / "bad_column.db"
    schemas = dict(REQUIRED_SCHEMAS)
    schemas["products"] = "product_id INTEGER PRIMARY KEY, created_at TEXT"
    create_schema(path, schemas)

    with pytest.raises(DatabaseValidationError, match="product_name"):
        validate_database(path)


def test_query_df_wraps_pandas_database_errors(tmp_path):
    path = tmp_path / "invalid_query.db"
    create_schema(path)

    with pytest.raises(DatabaseQueryError, match="Unable to query database"):
        query_df(path, "SELECT missing_column FROM orders")
