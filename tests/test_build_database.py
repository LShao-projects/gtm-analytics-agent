import csv
import sqlite3

from dashboard.data import validate_database
from scripts.build_database import build_database


ROWS = {
    "website_sessions.csv": (
        ["website_session_id", "created_at", "user_id", "is_repeat_session", "utm_source", "utm_campaign", "utm_content", "device_type", "http_referer"],
        [1, "2014-01-01 00:00:00", 1, 0, "NULL", "NULL", "NULL", "desktop", "NULL"],
    ),
    "website_pageviews.csv": (
        ["website_pageview_id", "created_at", "website_session_id", "pageview_url"],
        [1, "2014-01-01 00:00:00", 1, "/home"],
    ),
    "orders.csv": (
        ["order_id", "created_at", "website_session_id", "user_id", "primary_product_id", "items_purchased", "price_usd", "cogs_usd"],
        [1, "2014-01-01 00:10:00", 1, 1, 1, 1, 49.99, 19.49],
    ),
    "order_items.csv": (
        ["order_item_id", "created_at", "order_id", "product_id", "is_primary_item", "price_usd", "cogs_usd"],
        [1, "2014-01-01 00:10:00", 1, 1, 1, 49.99, 19.49],
    ),
    "order_item_refunds.csv": (
        ["order_item_refund_id", "created_at", "order_item_id", "order_id", "refund_amount_usd"],
        [1, "2014-01-10 00:00:00", 1, 1, 49.99],
    ),
    "products.csv": (
        ["product_id", "created_at", "product_name"],
        [1, "2012-03-19 08:00:00", "The Original Mr. Fuzzy"],
    ),
}


def test_build_database_loads_all_six_csvs_and_replaces_atomically(tmp_path):
    source = tmp_path / "Data"
    source.mkdir()
    for filename, (header, row) in ROWS.items():
        with (source / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerow(row)
    output = tmp_path / "nested" / "maven.db"

    counts = build_database(source, output, force=True)

    assert counts == {
        "website_sessions": 1,
        "website_pageviews": 1,
        "orders": 1,
        "order_items": 1,
        "order_item_refunds": 1,
        "products": 1,
    }
    assert validate_database(output).table_count == 6
    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT SUM(price_usd) FROM orders").fetchone()[0] == 49.99
        assert connection.execute("SELECT utm_source IS NULL FROM website_sessions").fetchone()[0] == 1
        stat_tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'sqlite_stat%'"
            )
        }
        assert "sqlite_stat1" in stat_tables and "sqlite_stat4" not in stat_tables
