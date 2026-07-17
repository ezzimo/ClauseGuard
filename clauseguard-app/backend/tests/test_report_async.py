"""Tests for the async report-generation job (PROMPT F).

The platform gateway returns 504 on long-running v2 flow calls by design; the
background job must treat that as expected and fall through to DB polling
instead of aborting.
"""

import io
import json
import time
from pathlib import Path

import pytest
from requests import Response
from requests.exceptions import HTTPError
from fastapi.testclient import TestClient

import main
from main import app, fusion_client, report_store, settings
from models.schemas import ContractStatus

SAMPLE_FINDINGS = Path(__file__).parent / "sample_finding.json"
SAMPLE_REPORT = Path(__file__).parent / "sample_report.json"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(autouse=True)
def fast_report_polling(monkeypatch):
    monkeypatch.setattr(main, "REPORT_POLL_INITIAL_DELAY_S", 0)
    monkeypatch.setattr(main, "REPORT_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(main, "REPORT_POLL_BUDGET_S", 0)


@pytest.fixture
def contract_id(client, token, monkeypatch):
    """A contract with one recorded decision, ready for report generation."""
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"
    settings.flow_report_fallback_id = "report-fallback-flow"
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")

    original = fusion_client.run_flow
    fusion_client.run_flow = lambda flow_id, message, session_id=None, retry_on_5xx=True: {
        "response_text": findings_text,
        "status_code": 200,
        "duration_ms": 100,
    }

    upload = client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("contrat.txt", io.BytesIO(b"Contrat. Article 1. Partie A."), "text/plain")},
    )
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze.status_code == 202

    deadline = time.time() + 10
    while time.time() < deadline:
        state = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"}).json()
        if state["status"] == ContractStatus.AWAITING_HUMAN_REVIEW.value:
            break
        time.sleep(0.05)

    decisions = client.post(
        f"/api/contracts/{cid}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"decisions": [{"clause_id": "ART_1", "action": "approve"}]},
    )
    assert decisions.status_code == 200

    fusion_client.run_flow = original
    yield cid

    fusion_client.run_flow = original
    state_path = Path("storage") / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()
    audit_path = Path("storage") / "audit_log.jsonl"
    if audit_path.exists():
        audit_path.unlink()


def _wait_for_status(client, token, cid, target_statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status in target_statuses:
            return resp.json()
        time.sleep(0.02)
    raise RuntimeError(f"Timeout waiting for status in {target_statuses}")


def _raise_504(*args, **kwargs):
    response = Response()
    response.status_code = 504
    raise HTTPError("504 Gateway Timeout", response=response)


def test_504_then_db_hit_yields_full_db(client, token, contract_id, monkeypatch):
    """Primary flow raises a 504 (expected, non-fatal); the job continues to
    DB polling, finds the row, and delivers it as full_db."""
    original = fusion_client.run_flow
    report_json = SAMPLE_REPORT.read_text(encoding="utf-8").replace(
        '"test-contract"', json.dumps(contract_id)
    )

    def mock_runner(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id == settings.flow_report_id:
            _raise_504()
        return original(flow_id, message, session_id, retry_on_5xx)

    fusion_client.run_flow = mock_runner
    monkeypatch.setattr(report_store, "find_report", lambda cid, since: report_json)
    try:
        resp = client.post(
            f"/api/contracts/{contract_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

        state = _wait_for_status(client, token, contract_id, {ContractStatus.COMPLETED.value})
        assert state["final_report"]["delivery"] == "full_db"
        assert state["final_report"]["contract_id"] == contract_id
    finally:
        fusion_client.run_flow = original


def test_504_then_db_miss_falls_back_to_v1(client, token, contract_id, monkeypatch):
    """Primary flow raises a 504, DB polling finds nothing, so the job falls
    through to the v1 fallback flow and delivers fallback_no_dispatch."""
    original = fusion_client.run_flow
    report_json = SAMPLE_REPORT.read_text(encoding="utf-8").replace(
        '"test-contract"', json.dumps(contract_id)
    )

    def mock_runner(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id == settings.flow_report_id:
            _raise_504()
        if flow_id == settings.flow_report_fallback_id:
            return {"response_text": report_json, "status_code": 200, "duration_ms": 90}
        return original(flow_id, message, session_id, retry_on_5xx)

    fusion_client.run_flow = mock_runner
    monkeypatch.setattr(report_store, "find_report", lambda cid, since: None)
    try:
        resp = client.post(
            f"/api/contracts/{contract_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

        state = _wait_for_status(client, token, contract_id, {ContractStatus.COMPLETED.value})
        assert state["final_report"]["delivery"] == "fallback_no_dispatch"
    finally:
        fusion_client.run_flow = original


def test_report_with_french_preamble_parses(contract_id):
    """LLM response with a conversational preamble before the JSON object
    must still parse — no crash, no parse failure."""
    report_json = SAMPLE_REPORT.read_text(encoding="utf-8").replace(
        '"test-contract"', json.dumps(contract_id)
    )
    chatty = (
        "Souhaitez-vous que je vous fournisse davantage de details ? "
        "Voici le rapport demande :\n" + report_json + "\nN'hesitez pas si besoin."
    )
    report = main._parse_report(chatty)
    assert report.contract_id == contract_id


def test_findings_with_french_preamble_parses():
    findings_json = SAMPLE_FINDINGS.read_text(encoding="utf-8")
    chatty = "Bien sur, voici l'analyse :\n" + findings_json
    parsed = main._parse_findings(chatty)
    assert parsed.audit_status == "completed"


def test_report_with_no_json_object_raises_value_error():
    with pytest.raises(ValueError):
        main._parse_report("Souhaitez-vous que je poursuive l'analyse ?")


def test_empty_findings_returns_422_without_flow_call(client, token, monkeypatch):
    """A contract whose analysis found zero clauses must be rejected with 422
    before any report flow is dispatched."""
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"
    empty_findings = json.dumps(
        {
            "audit_status": "completed",
            "audited_findings": [],
            "global_audit_notes": [],
            "disclaimer": "Cette analyse ne constitue pas un avis juridique.",
        }
    )
    original = fusion_client.run_flow
    fusion_client.run_flow = lambda flow_id, message, session_id=None, retry_on_5xx=True: {
        "response_text": empty_findings,
        "status_code": 200,
        "duration_ms": 50,
    }

    calls = {"report": 0}

    def guard(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id == settings.flow_report_id:
            calls["report"] += 1
        return {"response_text": empty_findings, "status_code": 200, "duration_ms": 50}

    fusion_client.run_flow = guard

    upload = client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("contrat.txt", io.BytesIO(b"Contrat. Article 1. Partie A."), "text/plain")},
    )
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze.status_code == 202

    deadline = time.time() + 10
    while time.time() < deadline:
        state = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"}).json()
        if state["status"] == ContractStatus.AWAITING_HUMAN_REVIEW.value:
            break
        time.sleep(0.05)

    try:
        resp = client.post(
            f"/api/contracts/{cid}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert "aucun constat" in resp.json()["detail"]
        assert calls["report"] == 0
    finally:
        fusion_client.run_flow = original
        state_path = Path("storage") / f"{cid}.json"
        if state_path.exists():
            state_path.unlink()
        audit_path = Path("storage") / "audit_log.jsonl"
        if audit_path.exists():
            audit_path.unlink()
