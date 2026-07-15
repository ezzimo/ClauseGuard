import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from main import app, fusion_client, settings

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
def mock_fusion(monkeypatch):
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")
    report_template = SAMPLE_REPORT.read_text(encoding="utf-8")

    original = fusion_client.run_flow

    def mock_run(flow_id, message, session_id=None):
        if isinstance(message, str) and message.strip().startswith("{"):
            payload = json.loads(message)
            cid = payload.get("contract_id", "test-contract")
            text = report_template.replace('"test-contract"', json.dumps(cid))
            return {"response_text": text, "status_code": 200, "duration_ms": 120}
        return {"response_text": findings_text, "status_code": 200, "duration_ms": 100}

    fusion_client.run_flow = mock_run
    yield
    fusion_client.run_flow = original


def _upload(client, token, filename, content, parties=None):
    return client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, io.BytesIO(content), "text/plain")},
        data={"parties": json.dumps(parties or []), "contract_type": "prestation_services"},
    )


def _wait_for_status(client, token, cid, target_statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status in target_statuses:
            return resp.json()
        time.sleep(0.2)
    raise RuntimeError(f"Timeout waiting for status in {target_statuses}")


def test_full_happy_path(client, token):
    upload = _upload(client, token, "contrat.txt", b"Contrat. Article 1. Partie A. Partie B.")
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze.status_code == 202
    assert analyze.json()["status"] == "processing"

    final = _wait_for_status(client, token, cid, {"awaiting_human_review"})
    assert final["status"] == "awaiting_human_review"

    decisions = client.post(
        f"/api/contracts/{cid}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"decisions": [{"clause_id": "ART_1", "action": "approve"}]},
    )
    assert decisions.status_code == 200

    report = client.post(f"/api/contracts/{cid}/report", headers={"Authorization": f"Bearer {token}"})
    assert report.status_code == 200
    assert report.json()["contract_id"] == cid


def test_analyze_returns_202_then_transitions(client, token, monkeypatch):
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")

    def slow_run(flow_id, message, session_id=None):
        time.sleep(2)
        return {"response_text": findings_text, "status_code": 200, "duration_ms": 2000}

    monkeypatch.setattr(fusion_client, "run_flow", slow_run)

    upload = _upload(client, token, "contrat.txt", b"Contrat. Article 1. Partie A. Partie B.")
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze.status_code == 202
    assert analyze.json()["status"] == "processing"

    # Immediately after 202, status should be processing.
    state = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert state["status"] == "processing"

    final = _wait_for_status(client, token, cid, {"awaiting_human_review"}, timeout=10)
    assert final["status"] == "awaiting_human_review"


def test_double_analyze_returns_409(client, token, monkeypatch):
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")

    def slow_run(flow_id, message, session_id=None):
        time.sleep(5)
        return {"response_text": findings_text, "status_code": 200, "duration_ms": 5000}

    monkeypatch.setattr(fusion_client, "run_flow", slow_run)

    upload = _upload(client, token, "contrat.txt", b"Contrat. Article 1. Partie A. Partie B.")
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    first = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 202

    second = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert second.status_code == 409
    assert second.json()["status"] == "processing"


def test_flow_exception_becomes_flow_error_not_stuck(client, token, monkeypatch):
    def failing_run(flow_id, message, session_id=None):
        raise RuntimeError("Fusion failure")

    monkeypatch.setattr(fusion_client, "run_flow", failing_run)

    upload = _upload(client, token, "contrat.txt", b"Contrat. Article 1. Partie A. Partie B.")
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]

    analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze.status_code == 202

    final = _wait_for_status(client, token, cid, {"flow_error"}, timeout=5)
    assert final["status"] == "flow_error"
    assert final["error_message"]
    assert final["progress_hint"] == "done"


def test_empty_file_rejected(client, token):
    resp = _upload(client, token, "empty.txt", b"")
    assert resp.status_code == 400


def test_non_contract_text_rejected(client, token):
    resp = _upload(client, token, "random.txt", b"Le ciel est bleu. La mer est calme.")
    assert resp.status_code == 400


def test_oversized_file_rejected(client, token):
    big = b"Contrat. Article 1. " * 110000
    resp = _upload(client, token, "big.txt", big)
    assert resp.status_code == 413
