"""Tests for MCP server envoyer_email_juriste tool (PROMPT J v2)."""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock mcp imports so backend test venv can load mcp_server without mcp dependency
mock_mcp_mod = MagicMock()
class MockFastMCP:
    def __init__(self, *args, **kwargs):
        pass
    def tool(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator
    def run(self, *args, **kwargs):
        pass

mock_mcp_mod.FastMCP = MockFastMCP
sys.modules["mcp"] = mock_mcp_mod
sys.modules["mcp.server"] = mock_mcp_mod
sys.modules["mcp.server.fastmcp"] = mock_mcp_mod
sys.modules["mcp.server.transport_security"] = mock_mcp_mod

MCP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "clauseguard-mcp"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import mcp_server


@pytest.fixture(autouse=True)
def mock_smtp_config(monkeypatch):
    monkeypatch.setattr(mcp_server, "GMAIL_SENDER", "sender@gmail.com")
    monkeypatch.setattr(mcp_server, "GMAIL_APP_PASSWORD", "secret")
    monkeypatch.setattr(mcp_server, "JURISTE_EMAIL", "juriste@example.com")


import uuid


def test_envoyer_email_juriste_with_valid_pdf_url(monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    mock_pdf_bytes = b"%PDF-1.4 sample pdf content"

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return mock_pdf_bytes

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=15: MockResponse())

    sent_messages = []

    class MockSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, recipient, msg_str):
            sent_messages.append((sender, recipient, msg_str))

    monkeypatch.setattr("smtplib.SMTP", lambda host, port: MockSMTP())
    log_calls = []
    monkeypatch.setattr(mcp_server, "_log", lambda actor, action, detail, request_id="": log_calls.append((action, detail)))

    res = mcp_server.envoyer_email_juriste(
        contract_id=cid,
        overall_risk="FAIBLE",
        resume="Resume test",
        request_id="req1",
        pdf_url=f"http://127.0.0.1:8000/api/contracts/{cid}/report/pdf/internal",
        pdf_filename=f"ClauseGuard_{cid}.pdf",
    )

    assert "Email envoye" in res
    assert len(sent_messages) == 1
    _, _, msg_str = sent_messages[0]
    assert "Content-Type: multipart/mixed" in msg_str
    assert f"ClauseGuard_{cid}.pdf" in msg_str
    assert len(log_calls) == 1
    action, _ = log_calls[0]
    assert action == "email_sent_with_pdf"


def test_envoyer_email_juriste_pdf_timeout_falls_back_to_text_only(monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"

    def mock_failing_urlopen(url, timeout=15):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr("urllib.request.urlopen", mock_failing_urlopen)

    sent_messages = []

    class MockSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, recipient, msg_str):
            sent_messages.append((sender, recipient, msg_str))

    monkeypatch.setattr("smtplib.SMTP", lambda host, port: MockSMTP())
    log_calls = []
    monkeypatch.setattr(mcp_server, "_log", lambda actor, action, detail, request_id="": log_calls.append((action, detail)))

    res = mcp_server.envoyer_email_juriste(
        contract_id=cid,
        overall_risk="ELEVE",
        resume="Resume test timeout",
        request_id="req2",
        pdf_url=f"http://127.0.0.1:8000/api/contracts/{cid}/report/pdf/internal",
        pdf_filename=f"ClauseGuard_{cid}.pdf",
    )

    assert "Email envoye" in res
    assert len(sent_messages) == 1
    _, _, msg_str = sent_messages[0]
    assert "Content-Type: text/plain" in msg_str
    assert len(log_calls) == 1
    action, _ = log_calls[0]
    assert action.startswith("email_sent_text_only_pdf_error:")


def test_envoyer_email_juriste_empty_pdf_url_sends_text_only(monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    sent_messages = []

    class MockSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, recipient, msg_str):
            sent_messages.append((sender, recipient, msg_str))

    monkeypatch.setattr("smtplib.SMTP", lambda host, port: MockSMTP())
    log_calls = []
    monkeypatch.setattr(mcp_server, "_log", lambda actor, action, detail, request_id="": log_calls.append((action, detail)))

    res = mcp_server.envoyer_email_juriste(
        contract_id=cid,
        overall_risk="MOYEN",
        resume="Resume test empty pdf_url",
        request_id="req3",
        pdf_url="",
        pdf_filename="",
    )

    assert "Email envoye" in res
    assert len(sent_messages) == 1
    _, _, msg_str = sent_messages[0]
    assert "Content-Type: text/plain" in msg_str
    assert len(log_calls) == 1
    action, _ = log_calls[0]
    assert action == "email_sent_text_only"
