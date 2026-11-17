from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd


DEFAULT_DATABASE = Path("tmp/maven-analysis/maven_fuzzy.db")

REQUIRED_COLUMNS = {
    "website_sessions": {
        "website_session_id", "created_at", "user_id", "is_repeat_session",
        "utm_source", "utm_campaign", "utm_content", "device_type", "http_referer",
    },
    "website_pageviews": {"website_pageview_id", "created_at", "website_session_id", "pageview_url"},
    "orders": {
        "order_id", "created_at", "website_session_id", "user_id", "primary_product_id",
        "items_purchased", "price_usd", "cogs_usd",
    },
    "order_items": {
        "order_item_id", "created_at", "order_id", "product_id", "is_primary_item",
        "price_usd", "cogs_usd",
    },
    "order_item_refunds": {
        "order_item_refund_id", "created_at", "order_item_id", "order_id", "refund_amount_usd",
    },
    "products": {"product_id", "created_at", "product_name"},
}


class DatabaseValidationError(RuntimeError):
    pass


class DatabaseQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseMetadata:
    path: Path
    table_count: int
    session_min: str | None
    session_max: str | None
    pageview_max: str | None
    order_max: str | None
    item_max: str | None
    refund_max: str | None


def _read_only_uri(path: Path) -> str:
    return f"file:{path.resolve()}?mode=ro"


def validate_database(path: str | Path = DEFAULT_DATABASE) -> DatabaseMetadata:
    database_path = Path(path)
    if not database_path.is_file():
        raise DatabaseValidationError(
            f"Database not found at {database_path}. Run: python scripts/build_database.py"
        )
    try:
        with sqlite3.connect(_read_only_uri(database_path), uri=True) as connection:
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            available = {row[0] for row in table_rows}
            missing_tables = set(REQUIRED_COLUMNS) - available
            if missing_tables:
                raise DatabaseValidationError(
                    "Database is missing required tables: " + ", ".join(sorted(missing_tables))
                )
            for table, required in REQUIRED_COLUMNS.items():
                actual = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                missing_columns = required - actual
                if missing_columns:
                    raise DatabaseValidationError(
                        f"Table {table} is missing columns: {', '.join(sorted(missing_columns))}"
                    )
            session_min, session_max = connection.execute(
                "SELECT MIN(created_at), MAX(created_at) FROM website_sessions"
            ).fetchone()
            pageview_max = connection.execute(
                "SELECT MAX(created_at) FROM website_pageviews"
            ).fetchone()[0]
            order_max = connection.execute(
                "SELECT MAX(created_at) FROM orders"
            ).fetchone()[0]
            item_max = connection.execute(
                "SELECT MAX(created_at) FROM order_items"
            ).fetchone()[0]
            refund_max = connection.execute(
                "SELECT MAX(created_at) FROM order_item_refunds"
            ).fetchone()[0]
    except sqlite3.Error as exc:
        raise DatabaseValidationError(f"Unable to read database {database_path}: {exc}") from exc
    return DatabaseMetadata(
        path=database_path,
        table_count=len(REQUIRED_COLUMNS),
        session_min=session_min,
        session_max=session_max,
        pageview_max=pageview_max,
        order_max=order_max,
        item_max=item_max,
        refund_max=refund_max,
    )


def query_df(
    path: str | Path,
    sql: str,
    params: Sequence[object] = (),
) -> pd.DataFrame:
    database_path = Path(path)
    try:
        with sqlite3.connect(_read_only_uri(database_path), uri=True) as connection:
            return pd.read_sql_query(sql, connection, params=list(params))
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        raise DatabaseQueryError(
            f"Unable to query database {database_path}: {exc}"
        ) from exc

