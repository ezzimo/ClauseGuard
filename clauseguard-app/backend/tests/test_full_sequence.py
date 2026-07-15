import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app, fusion_client, settings
from models.schemas import ContractStatus


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def contract_id(client, token):
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"

    sample_findings = Path(__file__).parent / "sample_finding.json"
    sample_report = Path(__file__).parent / "sample_report.json"

    original = fusion_client.run_flow

    class MockRunner:
        contract_id: str | None = None

        def __call__(self, flow_id, message, session_id=None):
            if flow_id == settings.flow_analysis_id:
                return {
                    "response_text": sample_findings.read_text(encoding="utf-8"),
                    "status_code": 200,
                    "duration_ms": 100,
                }
            if flow_id == settings.flow_report_id:
                text = sample_report.read_text(encoding="utf-8")
                if self.contract_id:
                    text = text.replace('"test-contract"', json.dumps(self.contract_id))
                return {
                    "response_text": text,
                    "status_code": 200,
                    "duration_ms": 120,
                }
            raise ValueError(f"Unexpected flow_id: {flow_id}")

    runner = MockRunner()
    fusion_client.run_flow = runner

    resp = client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.txt", io.BytesIO(b"Contrat de prestation. Article 1. Partie A. Partie B. contact@example.com"), "text/plain")},
    )
    assert resp.status_code == 200
    cid = resp.json()["contract_id"]
    runner.contract_id = cid

    yield cid

    fusion_client.run_flow = original
    state_path = Path("storage") / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()
    audit_path = Path("storage") / "audit_log.jsonl"
    if audit_path.exists():
        audit_path.unlink()


def _wait_for_status(client, token, contract_id, target_statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(
            f"/api/contracts/{contract_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status in target_statuses:
            return resp.json()
        time.sleep(0.05)
    raise RuntimeError(f"Timeout waiting for status in {target_statuses}")


def test_full_sequence(client, token, contract_id):
    # Analyze
    resp = client.post(
        f"/api/contracts/{contract_id}/analyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == ContractStatus.PROCESSING.value

    state = _wait_for_status(
        client, token, contract_id, {ContractStatus.AWAITING_HUMAN_REVIEW.value}
    )
    assert state["status"] == ContractStatus.AWAITING_HUMAN_REVIEW.value

    # Decisions
    resp = client.post(
        f"/api/contracts/{contract_id}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "decisions": [
                {
                    "clause_id": "ART_1",
                    "action": "approve",
                    "new_risk_level": "moyen",
                    "comment": "Validé",
                }
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == ContractStatus.DECISIONS_RECORDED.value
    assert body["pending_clauses"] == []

    # Report
    resp = client.post(
        f"/api/contracts/{contract_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["contract_id"] == contract_id
    assert report["overall_risk"] == "moyen"

    # GET report
    resp = client.get(
        f"/api/contracts/{contract_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["contract_id"] == contract_id

    # Contract state
    resp = client.get(
        f"/api/contracts/{contract_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["status"] == ContractStatus.COMPLETED.value
    assert state["final_report"] is not None


def test_decisions_reject_unknown_clause(client, token, contract_id):
    resp = client.post(
        f"/api/contracts/{contract_id}/analyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    _wait_for_status(
        client, token, contract_id, {ContractStatus.AWAITING_HUMAN_REVIEW.value}
    )
    resp = client.post(
        f"/api/contracts/{contract_id}/decisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"decisions": [{"clause_id": "UNKNOWN", "action": "approve"}]},
    )
    assert resp.status_code == 422
