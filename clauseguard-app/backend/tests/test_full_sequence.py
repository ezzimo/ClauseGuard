import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import app, fusion_client, report_store, settings
from models.schemas import ContractStatus


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def fast_report_polling(monkeypatch):
    """Report generation runs in a background thread that normally waits 60s
    before its first DB poll. Zero that out so tests run fast, and stub the
    DB lookup so tests don't depend on a real MCP SQLite file."""
    monkeypatch.setattr(main, "REPORT_POLL_INITIAL_DELAY_S", 0)
    monkeypatch.setattr(main, "REPORT_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(main, "REPORT_POLL_BUDGET_S", 0)
    monkeypatch.setattr(report_store, "find_report", lambda contract_id, since_iso: None)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def contract_id(client, token):
    settings.flow_analysis_id = "analysis-flow"
    settings.flow_report_id = "report-flow"
    settings.flow_report_fallback_id = "report-fallback-flow"

    sample_findings = Path(__file__).parent / "sample_finding.json"
    sample_report = Path(__file__).parent / "sample_report.json"

    original = fusion_client.run_flow

    class MockRunner:
        contract_id: str | None = None

        def __call__(self, flow_id, message, session_id=None, retry_on_5xx=True):
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
            if flow_id == settings.flow_report_fallback_id:
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

    # Report: fire-and-poll, no more synchronous 502/504 on this endpoint.
    resp = client.post(
        f"/api/contracts/{contract_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == ContractStatus.REPORT_PROCESSING.value

    state = _wait_for_status(client, token, contract_id, {ContractStatus.COMPLETED.value})
    assert state["status"] == ContractStatus.COMPLETED.value
    assert state["final_report"] is not None
    assert state["final_report"]["contract_id"] == contract_id
    assert state["final_report"]["overall_risk"] == "ROUGE"

    # GET report
    resp = client.get(
        f"/api/contracts/{contract_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["contract_id"] == contract_id


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



def _build_report_state(client, token, contract_id):
    """Run analysis + decisions so the contract is ready for report generation."""
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


def test_report_fallback_on_v2_500(client, token, contract_id):
    """v2 report flow returns 500 once; fallback is used, delivery flag is set,
    and exactly one v2 call is attempted (no retries because of side effects)."""
    sample_report = Path(__file__).parent / "sample_report.json"
    original = fusion_client.run_flow

    calls = {"v2": 0, "fallback": 0}

    def mock_runner(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id == settings.flow_report_id:
            calls["v2"] += 1
            # Simulate a 500 from the MCP-dispatch flow.
            from requests import Response

            response = Response()
            response.status_code = 500
            from requests.exceptions import HTTPError

            raise HTTPError("500 Server Error", response=response)
        if flow_id == settings.flow_report_fallback_id:
            calls["fallback"] += 1
            text = sample_report.read_text(encoding="utf-8").replace(
                '"test-contract"', json.dumps(contract_id)
            )
            return {
                "response_text": text,
                "status_code": 200,
                "duration_ms": 120,
            }
        # analysis flow still works via the original runner
        return original(flow_id, message, session_id, retry_on_5xx)

    fusion_client.run_flow = mock_runner
    try:
        _build_report_state(client, token, contract_id)

        resp = client.post(
            f"/api/contracts/{contract_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

        state = _wait_for_status(client, token, contract_id, {ContractStatus.COMPLETED.value})
        report = state["final_report"]
        assert report["contract_id"] == contract_id
        assert report["delivery"] == "fallback_no_dispatch"

        # Exactly one v2 attempt (no retries), and one fallback call.
        assert calls["v2"] == 1
        assert calls["fallback"] == 1

        # GET report also returns the fallback flag.
        resp = client.get(
            f"/api/contracts/{contract_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["delivery"] == "fallback_no_dispatch"
    finally:
        fusion_client.run_flow = original


def test_report_error_when_primary_and_fallback_fail(client, token, contract_id):
    """When v2, DB polling, and the fallback flow all fail, the contract lands
    in report_error instead of the endpoint hanging on a synchronous 502."""
    original = fusion_client.run_flow

    def mock_runner(flow_id, message, session_id=None, retry_on_5xx=True):
        if flow_id in (settings.flow_report_id, settings.flow_report_fallback_id):
            from requests import Response

            response = Response()
            response.status_code = 500
            from requests.exceptions import HTTPError

            raise HTTPError("500 Server Error", response=response)
        return original(flow_id, message, session_id, retry_on_5xx)

    fusion_client.run_flow = mock_runner
    try:
        _build_report_state(client, token, contract_id)

        resp = client.post(
            f"/api/contracts/{contract_id}/report",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

        state = _wait_for_status(client, token, contract_id, {ContractStatus.REPORT_ERROR.value})
        assert state["status"] == ContractStatus.REPORT_ERROR.value
        assert state["error_message"]
    finally:
        fusion_client.run_flow = original
