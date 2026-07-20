"""Integration tests: the quality loop wired into the real analysis
background job, gated by QUALITY_LOOP."""

import io
import json
import time
from pathlib import Path

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


def _wait_for_status(client, token, cid, target_statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status in target_statuses:
            return resp.json()
        time.sleep(0.05)
    raise RuntimeError(f"Timeout waiting for status in {target_statuses}")


def _cleanup(cid):
    state_path = Path("storage") / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()
    audit_path = Path("storage") / "audit_log.jsonl"
    if audit_path.exists():
        audit_path.unlink()


def test_quality_loop_off_makes_zero_quality_calls(client, token, monkeypatch):
    """Default (flag off): pipeline behaves exactly like before this prompt —
    no critic/refiner flow calls, no quality field populated."""
    settings.flow_analysis_id = "analysis-flow"
    monkeypatch.setattr(settings, "quality_loop", "off")
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")

    calls = []
    original = fusion_client.run_flow

    def mock_run(flow_id, message, session_id=None, retry_on_5xx=True):
        calls.append(flow_id)
        return {"response_text": findings_text, "status_code": 200, "duration_ms": 50}

    fusion_client.run_flow = mock_run
    try:
        upload = client.post(
            "/api/contracts/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("contrat.txt", io.BytesIO(b"Contrat. Article 1. Partie A."), "text/plain")},
        )
        assert upload.status_code == 200
        cid = upload.json()["contract_id"]

        analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
        assert analyze.status_code == 202

        final = _wait_for_status(client, token, cid, {ContractStatus.AWAITING_HUMAN_REVIEW.value})
        assert final["status"] == ContractStatus.AWAITING_HUMAN_REVIEW.value
        assert final["quality"] is None
        assert calls == ["analysis-flow"]
    finally:
        fusion_client.run_flow = original
        _cleanup(cid)


def test_quality_loop_on_shows_chip_data_and_audit_trail(client, token, monkeypatch):
    """Flag on, critic passes first try: quality is populated on the
    contract and the loop's steps appear in the audit trail."""
    settings.flow_analysis_id = "analysis-flow"
    monkeypatch.setattr(settings, "quality_loop", "on")
    monkeypatch.setattr(settings, "flow_critic_id", "critic-flow")
    monkeypatch.setattr(settings, "flow_refiner_id", "refiner-flow")
    findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")
    critic_response = json.dumps(
        {"global_score": 0.9, "criteria_scores": {"clarity": 0.9}, "verdict": "pass", "issues": []}
    )

    original = fusion_client.run_flow

    def mock_run(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id == "critic-flow":
            return {"response_text": critic_response, "status_code": 200, "duration_ms": 30}
        return {"response_text": findings_text, "status_code": 200, "duration_ms": 50}

    fusion_client.run_flow = mock_run
    try:
        upload = client.post(
            "/api/contracts/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("contrat.txt", io.BytesIO(b"Contrat. Article 1. Partie A."), "text/plain")},
        )
        assert upload.status_code == 200
        cid = upload.json()["contract_id"]

        analyze = client.post(f"/api/contracts/{cid}/analyze", headers={"Authorization": f"Bearer {token}"})
        assert analyze.status_code == 202

        final = _wait_for_status(client, token, cid, {ContractStatus.AWAITING_HUMAN_REVIEW.value})
        assert final["quality"]["enabled"] is True
        assert final["quality"]["score"] == 0.9
        assert final["quality"]["iterations"] == 1
        assert final["quality"]["quality_warning"] is False

        activity = client.get("/api/activity?limit=20", headers={"Authorization": f"Bearer {token}"})
        actions = [e.get("action") for e in activity.json()]
        assert "critic_scored" in actions
        assert "quality_loop_done" in actions
    finally:
        fusion_client.run_flow = original
        _cleanup(cid)
