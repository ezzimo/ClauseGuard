import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH", "reports.db")


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, coltype: str) -> None:
    """Add `column` to `table` if it doesn't already exist (migration for DBs
    created before this column was introduced)."""
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            contract_id TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            request_id TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            request_id TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_emails (
            contract_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(contract_id, request_id)
        )
    """)

    # Migrate DBs created before request_id existed.
    _ensure_column(cursor, "reports", "request_id", "TEXT")
    _ensure_column(cursor, "audit_log", "request_id", "TEXT")

    conn.commit()
    conn.close()
    print(f"Base SQLite initialisee : {DB_PATH}")


def log_action(actor: str, action: str, detail: str = "", request_id: str | None = None) -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_log (timestamp, actor, action, detail, request_id) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), actor, action, detail, request_id),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
