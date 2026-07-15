import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from main import app, fusion_client, settings
from models.schemas import ContractStatus

SAMPLE_FINDINGS = Path(__file__).parent / "sample_finding.json"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def contract_id(client, token, monkeypatch):
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"
    original = fusion_client.run_flow
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")
    fusion_client.run_flow = lambda flow_id, message, session_id=None: {
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

    yield cid

    fusion_client.run_flow = original
    state_path = Path("storage") / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()


def test_unknown_clause_decision_returns_422(client, token, contract_id):
    resp = client.post(
        f"/api/contracts/{contract_id}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"decisions": [{"clause_id": "UNKNOWN", "action": "approve"}]},
    )
    assert resp.status_code == 422


def test_report_before_decisions_marks_pending(client, token, contract_id):
    resp = client.post(
        f"/api/contracts/{contract_id}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"decisions": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_human_validation"
    assert len(body["pending_clauses"]) > 0
