from sqlalchemy import inspect, text

from database import engine

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

    for sql in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql));
        except Exception:
            pass

if __name__ == "__main__":
    ensure_columns();