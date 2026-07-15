import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH", "reports.db")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            contract_id TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"Base SQLite initialisee : {DB_PATH}")


def log_action(actor: str, action: str, detail: str = "") -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_log (timestamp, actor, action, detail) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), actor, action, detail),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
