import json
import os
import sqlite3
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from init_sqlite import init_db

load_dotenv()
init_db()

DB_PATH = os.getenv("SQLITE_PATH", "reports.db")
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
JURISTE_EMAIL = os.getenv("JURISTE_EMAIL", "")

mcp = FastMCP(
    "clauseguard-mcp",
    host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
    port=int(os.getenv("FASTMCP_PORT", "8001")),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(actor: str, action: str, detail: str = "") -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_log (timestamp, actor, action, detail) VALUES (?, ?, ?, ?)",
            (_now(), actor, action, detail),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


@mcp.tool()
def sauvegarder_rapport(contract_id: str, report_json: str) -> str:
    """Sauvegarde un rapport ClauseGuard dans SQLite et journalise l'action."""
    try:
        data = json.loads(report_json)
        canonical = json.dumps(data, ensure_ascii=False)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reports (contract_id, report_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(contract_id) DO UPDATE SET
                report_json = excluded.report_json,
                created_at = excluded.created_at
            """,
            (contract_id, canonical, _now()),
        )
        conn.commit()
        conn.close()
        _log("reporting_agent", "save_report", f"contract_id={contract_id}")
        return f"Rapport sauvegarde pour {contract_id} le {_now()}"
    except Exception as exc:
        return f"Erreur sauvegarde rapport : {exc}"


@mcp.tool()
def envoyer_email_juriste(contract_id: str, overall_risk: str, resume: str) -> str:
    """Envoie un email recapitulatif au juriste via SMTP Gmail."""
    try:
        if not all([GMAIL_SENDER, GMAIL_APP_PASSWORD, JURISTE_EMAIL]):
            return "Configuration SMTP incomplete (GMAIL_SENDER, GMAIL_APP_PASSWORD, JURISTE_EMAIL)"

        subject = f"ClauseGuard - Rapport {contract_id} - Risque {overall_risk}"
        body = (
            f"{resume}\n\n"
            "Rapport complet disponible dans l'application. "
            "Ceci n'est pas un conseil juridique."
        )

        msg = MIMEMultipart()
        msg["From"] = GMAIL_SENDER
        msg["To"] = JURISTE_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER, JURISTE_EMAIL, msg.as_string())

        _log("reporting_agent", "email_sent", f"contract_id={contract_id}; risk={overall_risk}")
        return f"Email envoye a {JURISTE_EMAIL} pour le rapport {contract_id}"
    except Exception as exc:
        return f"Erreur envoi email : {exc}"


@mcp.tool()
def lire_rapport(contract_id: str) -> str:
    """Lit un rapport ClauseGuard precedemment sauvegarde dans SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT report_json FROM reports WHERE contract_id = ?",
            (contract_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
        return "aucun rapport"
    except Exception as exc:
        return f"Erreur lecture rapport : {exc}"


@mcp.tool()
def journal_audit(limit: int = 20) -> str:
    """Retourne les N dernieres entrees du journal d'audit au format JSON."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        entries = [
            {"id": r[0], "timestamp": r[1], "actor": r[2], "action": r[3], "detail": r[4]}
            for r in rows
        ]
        return json.dumps(entries, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Erreur lecture journal : {exc}"


if __name__ == "__main__":
    mcp.run(transport="sse")
