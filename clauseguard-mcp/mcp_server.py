import json
import os
import sqlite3
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from init_sqlite import init_db

load_dotenv()
init_db()

DB_PATH = os.getenv("SQLITE_PATH", "reports.db")
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
JURISTE_EMAIL = os.getenv("JURISTE_EMAIL", "")


def _transport_security():
    """Return transport security settings.

    DNS rebinding protection is enabled by default for localhost, but it rejects
    public tunnel hostnames (serveo.net, cloudflare, etc.). Set
    MCP_DISABLE_DNS_PROTECTION=true to allow tunnelled traffic.
    """
    flag = os.getenv("MCP_DISABLE_DNS_PROTECTION", "false").lower()
    if flag in ("1", "true", "yes", "on"):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return None


mcp = FastMCP(
    "clauseguard-mcp",
    host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
    port=int(os.getenv("FASTMCP_PORT", "8001")),
    transport_security=_transport_security(),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(actor: str, action: str, detail: str = "", request_id: str = "") -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_log (timestamp, actor, action, detail, request_id) VALUES (?, ?, ?, ?, ?)",
            (_now(), actor, action, detail, request_id or None),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _last_request_id_for_contract(contract_id: str) -> str:
    """Best-effort lookup of the request_id from the most recently saved
    report for this contract. Returns "" (nullable, not raised) if absent."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT request_id FROM reports WHERE contract_id = ? ORDER BY created_at DESC LIMIT 1",
            (contract_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


@mcp.tool()
def sauvegarder_rapport(contract_id: str, request_id: str, report_json: str) -> str:
    """Sauvegarde un rapport ClauseGuard dans SQLite et journalise l'action."""
    try:
        data = json.loads(report_json)
        canonical = json.dumps(data, ensure_ascii=False)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO reports (contract_id, report_json, created_at, request_id)
            VALUES (?, ?, ?, ?)
            """,
            (contract_id, canonical, _now(), request_id or None),
        )
        conn.commit()
        conn.close()
        _log(
            "reporting_agent",
            "save_report",
            f"contract_id={contract_id}; request_id={request_id}",
            request_id=request_id,
        )
        return f"Rapport sauvegarde pour {contract_id} le {_now()}"
    except Exception as exc:
        return f"Erreur sauvegarde rapport : {exc}"


@mcp.tool()
def envoyer_email_juriste(
    contract_id: str, overall_risk: str, resume: str, request_id: str = ""
) -> str:
    """Envoie un email recapitulatif au juriste via SMTP Gmail.

    Idempotent : si un email a deja ete envoye pour (contract_id, request_id),
    l'appel est ignore.
    """
    try:
        if not all([GMAIL_SENDER, GMAIL_APP_PASSWORD, JURISTE_EMAIL]):
            return "Configuration SMTP incomplete (GMAIL_SENDER, GMAIL_APP_PASSWORD, JURISTE_EMAIL)"

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sent_emails WHERE contract_id = ? AND request_id = ?",
            (contract_id, request_id),
        )
        if cursor.fetchone() is not None:
            conn.close()
            return "deja envoye, ignore"
        conn.close()

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

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sent_emails (contract_id, request_id, sent_at) VALUES (?, ?, ?)",
            (contract_id, request_id, _now()),
        )
        conn.commit()
        conn.close()

        # Best effort: the caller's request_id may be blank, so fall back to
        # whatever was recorded on the last saved report for this contract.
        logged_request_id = request_id or _last_request_id_for_contract(contract_id)
        _log(
            "reporting_agent",
            "email_sent",
            f"contract_id={contract_id}; risk={overall_risk}; request_id={logged_request_id}",
            request_id=logged_request_id,
        )
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
            "SELECT id, timestamp, actor, action, detail, request_id FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        entries = []
        for r in rows:
            entry = {"id": r[0], "timestamp": r[1], "actor": r[2], "action": r[3], "detail": r[4]}
            if r[5]:
                entry["request_id"] = r[5]
            entries.append(entry)
        return json.dumps(entries, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Erreur lecture journal : {exc}"


if __name__ == "__main__":
    mcp.run(transport="sse")
