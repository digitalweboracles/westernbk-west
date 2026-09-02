import logging

from sqlalchemy import inspect, text

from database import engine

logger = logging.getLogger(__name__)


def ensure_columns():
    inspector = inspect(engine);
    tables = inspector.get_table_names();
    column_map = {}
    for table in tables:
        names = [c["name"] for c in inspector.get_columns(table)]
        column_map[table] = names

    statements = []
    if "users" in column_map and "is_admin" not in column_map["users"]:
        statements.append("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0");
    if "contact_messages" in column_map and "is_read" not in column_map["contact_messages"]:
        statements.append("ALTER TABLE contact_messages ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT 0");
    if "bank_accounts" in column_map:
        for col, ddl in (
            ("balance", "FLOAT NOT NULL DEFAULT 0"),
            ("currency", "VARCHAR(10) NOT NULL DEFAULT 'USD'"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'Active'"),
            ("account_type", "VARCHAR(30) NOT NULL DEFAULT 'Checking'"),
        ):
            if col not in column_map["bank_accounts"]:
                statements.append(f"ALTER TABLE bank_accounts ADD COLUMN {col} {ddl}");
    if "transactions" in column_map:
        for col, ddl in (
            ("fee", "FLOAT NOT NULL DEFAULT 0"),
            ("currency", "VARCHAR(10) NOT NULL DEFAULT 'USD'"),
            ("reference", "VARCHAR(255)"),
        ):
            if col not in column_map["transactions"]:
                statements.append(f"ALTER TABLE transactions ADD COLUMN {col} {ddl}");

    for sql in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql));
            logger.warning("Applied migration: %s", sql)
        except Exception as exc:
            logger.warning("Migration failed (%s): %s", exc, sql)

if __name__ == "__main__":
    ensure_columns();
