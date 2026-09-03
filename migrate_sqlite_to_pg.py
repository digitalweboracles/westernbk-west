#!/usr/bin/env python3
"""One-shot migration: copy every row from the local SQLite dev.db into Postgres.

Usage (run from anywhere Postgres is reachable; e.g. on your machine after
`railway login` + `railway connect <postgres-service>`, or with Postgres public
networking enabled):

    PG_URL="postgresql://postgres:pass@localhost:15432/railway" python3 migrate_sqlite_to_pg.py
    # or omit PG_URL and export DATABASE_URL instead:
    python3 migrate_sqlite_to_pg.py

Idempotent: rows whose primary key already exists in Postgres are skipped, and
Postgres identity sequences are bumped to max(id) per table after copying.
"""
import os
import sqlite3
import sys
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

TABLES = [  # FK-safe copy order
    "users",
    "bank_accounts",
    "loan_applications",
    "transactions",
    "contact_messages",
    "newsletter_subscribers",
]

# SQLite stores booleans as integers; Postgres needs explicit ::boolean casts
COLUMN_TYPES = {
    "users": {"is_active", "is_admin"},
    "contact_messages": {"is_read"},
    "newsletter_subscribers": {"is_active"},
}

SQLITE_PATH = os.environ.get("SQLITE_PATH", "dev.db")


def _pg_connect(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError("DATABASE_URL must start with postgresql:// or postgres://")
    return psycopg2.connect(
        host=parsed.hostname or "",
        port=parsed.port or 5432,
        user=parsed.username or "",
        password=parsed.password or "",
        dbname=(parsed.path or "/").lstrip("/") or "railway",
        connect_timeout=15,
    )


def _sqlite_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info({})".format(table)).fetchall()]


def _pg_columns(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def _sqlite_rows(con: sqlite3.Connection, table: str, cols: list[str]) -> list[tuple]:
    q = "SELECT {} FROM {}".format(", ".join(cols), table)
    return con.execute(q).fetchall()


def main() -> int:
    pg_url = os.environ.get("PG_URL") or os.environ.get("DATABASE_URL", "")
    if not pg_url:
        print("Set PG_URL (or DATABASE_URL) to the target Postgres, e.g.:", file=sys.stderr)
        print('  PG_URL="postgresql://user:pass@host:5432/db" python3 migrate_sqlite_to_pg.py', file=sys.stderr)
        return 2

    print(f"Source: {SQLITE_PATH}")
    sq = sqlite3.connect(SQLITE_PATH)
    pg = _pg_connect(pg_url)
    pg.autocommit = False
    inserted_total = 0
    skipped_total = 0
    try:
        with pg.cursor() as cur:
            for table in TABLES:
                cols_pg = _pg_columns(cur, table)
                if not cols_pg:
                    print(f"!! table {table} does not exist yet in Postgres "
                          f"- start the app once first so create_all() builds it")
                    continue
                cols_sqlite = [c for c in _sqlite_columns(sq, table) if c in cols_pg]
                if not cols_sqlite:
                    print(f"  {table}: no overlapping columns, skipping")
                    continue
                id_col = "id" if "id" in cols_sqlite else None
                rows = _sqlite_rows(sq, table, cols_sqlite)
                if not rows:
                    print(f"  {table}: 0 rows")
                    continue

                existing = set()
                if id_col:
                    cur.execute(f"SELECT {id_col} FROM {table}")
                    existing = {r[0] for r in cur.fetchall()}

                insert_rows = []
                for row in rows:
                    if id_col and row[cols_sqlite.index(id_col)] in existing:
                        skipped_total += 1
                        continue
                    insert_rows.append(row)

                if not insert_rows:
                    print(f"  {table}: 0 new (all {len(rows)} already exist)")
                    continue

                insert_cols_sql = ", ".join(cols_sqlite)
                bool_cols = COLUMN_TYPES.get(table, set())
                placeholders = ", ".join(
                    "%s::boolean" if c in bool_cols else "%s" for c in cols_sqlite
                )
                insert_sql = (
                    f"INSERT INTO {table} ({insert_cols_sql}) "
                    f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                )
                psycopg2.extras.execute_batch(cur, insert_sql, insert_rows, page_size=500)
                inserted_total += len(insert_rows)

                if id_col:
                    seq = f"pg_get_serial_sequence('{table}', '{id_col}')"
                    cur.execute(
                        f"SELECT setval({seq}, GREATEST(COALESCE(MAX({id_col}), 1), 1)) FROM {table}"
                    )
                print(f"  {table}: {len(insert_rows)} inserted "
                      f"({len(rows) - len(insert_rows)} existed/skipped)")
            pg.commit()
    except Exception as exc:
        pg.rollback()
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No changes committed (transaction rolled back)", file=sys.stderr)
        return 1
    finally:
        sq.close()
        pg.close()
    print(f"\nDONE - inserted {inserted_total} rows, skipped {skipped_total} existing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
