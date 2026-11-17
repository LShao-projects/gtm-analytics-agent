import sqlite3

import pytest


@pytest.fixture
def analytics_db(tmp_path):
    path = tmp_path / "analytics.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE website_sessions (
                website_session_id INTEGER PRIMARY KEY, created_at TEXT, user_id INTEGER,
                is_repeat_session INTEGER, utm_source TEXT, utm_campaign TEXT,
                utm_content TEXT, device_type TEXT, http_referer TEXT
            );
            CREATE TABLE website_pageviews (
                website_pageview_id INTEGER PRIMARY KEY, created_at TEXT,
                website_session_id INTEGER, pageview_url TEXT
            );
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY, created_at TEXT, website_session_id INTEGER,
                user_id INTEGER, primary_product_id INTEGER, items_purchased INTEGER,
                price_usd REAL, cogs_usd REAL
            );
            CREATE TABLE order_items (
                order_item_id INTEGER PRIMARY KEY, created_at TEXT, order_id INTEGER,
                product_id INTEGER, is_primary_item INTEGER, price_usd REAL, cogs_usd REAL
            );
            CREATE TABLE order_item_refunds (
                order_item_refund_id INTEGER PRIMARY KEY, created_at TEXT,
                order_item_id INTEGER, order_id INTEGER, refund_amount_usd REAL
            );
            CREATE TABLE products (
                product_id INTEGER PRIMARY KEY, created_at TEXT, product_name TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?)",
            [
                (1, "2012-03-19 08:00:00", "Original Fuzzy"),
                (2, "2013-01-06 13:00:00", "Love Bear"),
            ],
        )
        connection.executemany(
            "INSERT INTO website_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2014-05-05 10:00:00", 1, 0, "gsearch", "nonbrand", "g_ad_1", "desktop", "https://www.gsearch.com"),
                (2, "2014-05-06 10:00:00", 2, 0, "socialbook", "pilot", "social_ad_1", "mobile", "https://www.socialbook.com"),
                (3, "2014-05-07 10:00:00", 1, 1, "NULL", "NULL", "NULL", "desktop", "https://www.gsearch.com"),
                (4, "2014-06-02 10:00:00", 4, 0, "NULL", "NULL", "NULL", "mobile", "NULL"),
                (5, "2014-04-05 10:00:00", 5, 0, "gsearch", "brand", "g_ad_2", "desktop", "https://www.gsearch.com"),
            ],
        )
        pageviews = [
            (1, "2014-05-05 10:00:00", 1, "/home"),
            (2, "2014-05-05 10:01:00", 1, "/products"),
            (3, "2014-05-05 10:02:00", 1, "/the-original-mr-fuzzy"),
            (4, "2014-05-05 10:03:00", 1, "/cart"),
            (5, "2014-05-05 10:04:00", 1, "/shipping"),
            (6, "2014-05-05 10:05:00", 1, "/billing-2"),
            (7, "2014-05-05 10:06:00", 1, "/thank-you-for-your-order"),
            (8, "2014-05-06 10:00:00", 2, "/lander-2"),
            (9, "2014-05-06 10:01:00", 2, "/products"),
            (10, "2014-05-06 10:02:00", 2, "/the-forever-love-bear"),
            (11, "2014-05-06 10:03:00", 2, "/cart"),
            (12, "2014-05-07 10:00:00", 3, "/home"),
            (13, "2014-05-07 10:01:00", 3, "/products"),
            (14, "2014-05-07 10:02:00", 3, "/the-original-mr-fuzzy"),
            (15, "2014-05-07 10:03:00", 3, "/cart"),
            (16, "2014-05-07 10:04:00", 3, "/shipping"),
            (17, "2014-05-07 10:05:00", 3, "/billing"),
            (18, "2014-05-07 10:06:00", 3, "/thank-you-for-your-order"),
            (19, "2014-06-02 10:00:00", 4, "/home"),
            (20, "2014-04-05 10:00:00", 5, "/home"),
            (21, "2014-04-05 10:01:00", 5, "/products"),
            (22, "2014-04-05 10:02:00", 5, "/the-original-mr-fuzzy"),
            (23, "2014-04-05 10:03:00", 5, "/cart"),
            (24, "2014-04-05 10:04:00", 5, "/shipping"),
            (25, "2014-04-05 10:05:00", 5, "/billing-2"),
            (26, "2014-04-05 10:06:00", 5, "/thank-you-for-your-order"),
        ]
        connection.executemany("INSERT INTO website_pageviews VALUES (?, ?, ?, ?)", pageviews)
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2014-05-05 10:06:00", 1, 1, 1, 2, 80.0, 30.0),
                (2, "2014-05-07 10:06:00", 3, 1, 1, 1, 50.0, 20.0),
                (3, "2014-04-05 10:06:00", 5, 5, 1, 1, 50.0, 20.0),
            ],
        )
        connection.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2014-05-05 10:06:00", 1, 1, 1, 50.0, 20.0),
                (2, "2014-05-05 10:06:00", 1, 2, 0, 30.0, 10.0),
                (3, "2014-05-07 10:06:00", 2, 1, 1, 50.0, 20.0),
                (4, "2014-04-05 10:06:00", 3, 1, 1, 50.0, 20.0),
            ],
        )
        connection.execute(
            "INSERT INTO order_item_refunds VALUES (?, ?, ?, ?, ?)",
            (1, "2014-05-20 12:00:00", 1, 1, 50.0),
        )
    return path
