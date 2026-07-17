"""Read-only polling of the ClauseGuard MCP SQLite DB.

The v2 report flow has side effects (SQLite upsert via `sauvegarder_rapport`,
email via `envoyer_email_juriste`) that are dispatched server-side by the
platform's MCP tool-calling. When the platform gateway cuts the HTTP
connection with a 504 before the flow finishes, those side effects can still
land after the fact. Polling this DB is how we recover the report without
depending on the unreliable HTTP response.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from config import settings


def _db_path() -> Path:
    return Path(settings.mcp_sqlite_path).resolve()


def find_report(contract_id: str, since_iso: str) -> Optional[str]:
    """Return the report_json for contract_id if a row was created at/after
    since_iso, else None. Never raises — DB absence/lock/corruption is treated
    as "not found yet", since this is a best-effort recovery path."""
    path = _db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT report_json FROM reports
                WHERE contract_id = ? AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (contract_id, since_iso),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        return None
