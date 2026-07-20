"""Tests for the report_error recovery path (?recover=true).

Covers: the real report JSON pulled from a live run (tests/sample_report.json,
now literally the f3ff5109... payload) validates against the fixed schema;
recovering serves it straight from the DB with zero fusion_client calls (no
re-run of the flow, no duplicate email); and the dashboard metrics survive
the round trip.
"""

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import _contract_path, _load_state, _save_state, app, fusion_client, report_store, settings
from models.schemas import ContractStatus, FinalReport

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
def contract_id(client, token):
    """An uploaded, analyzed contract, forced into report_error — the exact
    state the app was in for f3ff5109... before recovery."""
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

    # Force report_error directly, as if a prior report generation attempt
    # had exhausted every recovery path (the scenario this endpoint fixes).
    state = _load_state(cid)
    state.status = ContractStatus.REPORT_ERROR
    state.error_message = "Report generation failed: simulated failure"
    state.report_request_id = "74de152ca17e46ad95d073c7ca877a64"
    _save_state(state)

    fusion_client.run_flow = original
    yield cid

    fusion_client.run_flow = original
    state_path = Path(settings.storage_dir) / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()
    audit_path = Path(settings.storage_dir) / "audit_log.jsonl"
    if audit_path.exists():
        audit_path.unlink()


def test_real_report_fixture_validates_against_fixed_schema():
    """The exact JSON pulled from reports.db for a real run must validate."""
    data = json.loads(SAMPLE_REPORT.read_text(encoding="utf-8"))
    report = FinalReport.model_validate(data)
    assert report.overall_risk == "ROUGE"
    assert len(report.clauses) == 5
    assert report.clauses[0].risk_level == "VERT"
    assert report.dashboard_metrics.total_clauses_processed == 5
    assert report.dashboard_metrics.orange_red_detection_count == 3


def test_recover_serves_db_row_without_any_fusion_call(client, token, contract_id, monkeypatch):
    report_json = SAMPLE_REPORT.read_text(encoding="utf-8").replace(
        '"test-contract"', json.dumps(contract_id)
    )
    monkeypatch.setattr(report_store, "find_report", lambda cid, since_iso: report_json)

    calls = {"count": 0}
    original = fusion_client.run_flow

    def guard(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    fusion_client.run_flow = guard
    try:
        resp = client.post(
            f"/api/contracts/{contract_id}/report?recover=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        report = resp.json()
        assert report["contract_id"] == contract_id
        assert report["delivery"] == "full_db_recovered"
        assert calls["count"] == 0  # no flow call, no re-dispatched email

        state = client.get(
            f"/api/contracts/{contract_id}", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert state["status"] == ContractStatus.COMPLETED.value
        assert state["final_report"]["delivery"] == "full_db_recovered"
    finally:
        fusion_client.run_flow = original


def test_recovered_report_metrics_render(client, token, contract_id, monkeypatch):
    """Dashboard metrics survive the recovery round trip intact."""
    report_json = SAMPLE_REPORT.read_text(encoding="utf-8").replace(
        '"test-contract"', json.dumps(contract_id)
    )
    monkeypatch.setattr(report_store, "find_report", lambda cid, since_iso: report_json)

    resp = client.post(
        f"/api/contracts/{contract_id}/report?recover=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    metrics = resp.json()["dashboard_metrics"]
    assert metrics["total_clauses_processed"] == 5
    assert metrics["orange_red_detection_count"] == 3
    assert metrics["citation_rate"] == 0.6
    assert metrics["human_validation_pending_count"] == 1

    clauses = resp.json()["clauses"]
    rouge_or_orange = [c for c in clauses if c["risk_level"] in ("ROUGE", "ORANGE")]
    assert len(rouge_or_orange) == 3


def test_recover_requires_report_error_status(client, token, contract_id):
    # Flip the contract to completed; recovery should now be rejected.
    state = _load_state(contract_id)
    state.status = ContractStatus.COMPLETED
    _save_state(state)

    resp = client.post(
        f"/api/contracts/{contract_id}/report?recover=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_recover_404_when_nothing_in_db(client, token, contract_id, monkeypatch):
    monkeypatch.setattr(report_store, "find_report", lambda cid, since_iso: None)
    resp = client.post(
        f"/api/contracts/{contract_id}/report?recover=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
