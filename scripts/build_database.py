from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import tempfile
from pathlib import Path


TABLES = {
    "website_sessions": """
        website_session_id INTEGER PRIMARY KEY, created_at TEXT, user_id INTEGER,
        is_repeat_session INTEGER, utm_source TEXT, utm_campaign TEXT,
        utm_content TEXT, device_type TEXT, http_referer TEXT
    """,
    "website_pageviews": """
        website_pageview_id INTEGER PRIMARY KEY, created_at TEXT,
        website_session_id INTEGER, pageview_url TEXT
    """,
    "orders": """
        order_id INTEGER PRIMARY KEY, created_at TEXT, website_session_id INTEGER,
        user_id INTEGER, primary_product_id INTEGER, items_purchased INTEGER,
        price_usd REAL, cogs_usd REAL
    """,
    "order_items": """
        order_item_id INTEGER PRIMARY KEY, created_at TEXT, order_id INTEGER,
        product_id INTEGER, is_primary_item INTEGER, price_usd REAL, cogs_usd REAL
    """,
    "order_item_refunds": """
        order_item_refund_id INTEGER PRIMARY KEY, created_at TEXT,
        order_item_id INTEGER, order_id INTEGER, refund_amount_usd REAL
    """,
    "products": "product_id INTEGER PRIMARY KEY, created_at TEXT, product_name TEXT",
}

INTEGER_COLUMNS = {
    "website_session_id", "user_id", "is_repeat_session", "website_pageview_id",
    "order_id", "primary_product_id", "items_purchased", "order_item_id",
    "product_id", "is_primary_item", "order_item_refund_id",
}
FLOAT_COLUMNS = {"price_usd", "cogs_usd", "refund_amount_usd"}

INDEXES = (
    "CREATE INDEX idx_sessions_created ON website_sessions(created_at)",
    "CREATE INDEX idx_sessions_source ON website_sessions(utm_source, utm_campaign, device_type, created_at)",
    "CREATE INDEX idx_pageviews_session ON website_pageviews(website_session_id, created_at)",
    "CREATE INDEX idx_pageviews_url ON website_pageviews(pageview_url, created_at)",
    "CREATE INDEX idx_orders_session ON orders(website_session_id)",
    "CREATE INDEX idx_orders_created ON orders(created_at)",
    "CREATE INDEX idx_items_order ON order_items(order_id)",
    "CREATE INDEX idx_items_product ON order_items(product_id, created_at)",
    "CREATE INDEX idx_refunds_item ON order_item_refunds(order_item_id)",
)


def _cast(column: str, value: str):
    if value == "" or value == "NULL":
        return None
    if column in INTEGER_COLUMNS:
        return int(value)
    if column in FLOAT_COLUMNS:
        return float(value)
    return value


def _load_csv(connection: sqlite3.Connection, table: str, path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        columns = tuple(reader.fieldnames)
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
        count = 0
        batch = []
        for row in reader:
            batch.append(tuple(_cast(column, row[column]) for column in columns))
            if len(batch) >= 10_000:
                connection.executemany(sql, batch)
                count += len(batch)
                batch.clear()
        if batch:
            connection.executemany(sql, batch)
            count += len(batch)
        return count


def build_database(source_dir: str | Path, output_path: str | Path, *, force: bool = False) -> dict[str, int]:
    source = Path(source_dir)
    output = Path(output_path)
    missing = [str(source / f"{table}.csv") for table in TABLES if not (source / f"{table}.csv").is_file()]
    if missing:
        raise FileNotFoundError("Missing source CSVs: " + ", ".join(missing))
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False).name
    )
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            for table, schema in TABLES.items():
                connection.execute(f"CREATE TABLE {table} ({schema})")
                counts[table] = _load_csv(connection, table, source / f"{table}.csv")
            for statement in INDEXES:
                connection.execute(statement)
            connection.execute("ANALYZE")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Maven Fuzzy Factory SQLite database")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("tmp/maven-fuzzy-source/Data"),
        help="Directory containing the six source CSV files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/maven-analysis/maven_fuzzy.db"),
        help="SQLite output path",
    )
    parser.add_argument("--force", action="store_true", help="Atomically replace an existing output database")
    args = parser.parse_args()
    counts = build_database(args.source, args.output, force=args.force)
    for table, count in counts.items():
        print(f"{table}: {count:,}")
    print(f"Built {args.output} with {sum(counts.values()):,} rows")


if __name__ == "__main__":
    main()

