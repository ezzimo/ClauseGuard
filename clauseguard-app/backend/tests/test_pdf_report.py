"""PDF report export (PROMPT G)."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import _load_state, _save_state, app, settings
from models.schemas import ContractStatus, FinalReport
from services.pdf_report import build_pdf

SAMPLE_REPORT = Path(__file__).parent / "sample_report.json"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _real_report() -> FinalReport:
    data = json.loads(SAMPLE_REPORT.read_text(encoding="utf-8"))
    return FinalReport.model_validate(data)


def test_build_pdf_with_real_fixture_returns_valid_pdf_bytes():
    report = _real_report()
    pdf_bytes = build_pdf(report, "ClauseGuard_Rapport_test1234.pdf", validated_by="clauseguard")
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 5 * 1024


def test_build_pdf_handles_long_rewrite_without_exception():
    """A 600-char proposed_rewrite must wrap across lines, not crash."""
    report = _real_report()
    long_rewrite = "Le Prestataire s'engage à réviser les conditions contractuelles suivantes. " * 9
    assert len(long_rewrite) > 600
    report.clauses[1].proposed_rewrite = long_rewrite

    pdf_bytes = build_pdf(report, "ClauseGuard_Rapport_wraptest.pdf")
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 5 * 1024


@pytest.fixture
def contract_id(client, token):
    """An uploaded contract with no final_report yet (for the 404 case)."""
    upload = client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("contrat.txt", io.BytesIO(b"Contrat. Article 1. Partie A. Partie B."), "text/plain")},
    )
    assert upload.status_code == 200
    cid = upload.json()["contract_id"]
    yield cid
    state_path = Path(settings.storage_dir) / f"{cid}.json"
    if state_path.exists():
        state_path.unlink()


def test_pdf_endpoint_404_before_report_completed(client, token, contract_id):
    resp = client.get(
        f"/api/contracts/{contract_id}/report/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_pdf_endpoint_200_with_correct_headers_after_completion(client, token, contract_id):
    report = _real_report()
    report_data = report.model_copy(update={"contract_id": contract_id})

    state = _load_state(contract_id)
    state.final_report = report_data
    state.status = ContractStatus.COMPLETED
    _save_state(state)

    resp = client.get(
        f"/api/contracts/{contract_id}/report/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    expected_filename = f"ClauseGuard_Rapport_{contract_id[:8]}.pdf"
    assert expected_filename in resp.headers["content-disposition"]
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 5 * 1024


def test_pdf_internal_endpoint_200_on_localhost_without_auth(client, contract_id):
    report = _real_report()
    report_data = report.model_copy(update={"contract_id": contract_id})

    state = _load_state(contract_id)
    state.final_report = report_data
    state.status = ContractStatus.COMPLETED
    _save_state(state)

    resp = client.get(f"/api/contracts/{contract_id}/report/pdf/internal")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_pdf_internal_endpoint_403_from_non_localhost(contract_id):
    external_client = TestClient(app, client=("192.168.1.100", 50000))
    resp = external_client.get(f"/api/contracts/{contract_id}/report/pdf/internal")
    assert resp.status_code == 403
    assert "Forbidden" in resp.json()["detail"] or "forbidden" in resp.json()["detail"].lower()


def test_build_pdf_with_logo_present():
    report = _real_report()
    pdf_bytes = build_pdf(report, "ClauseGuard_Rapport_logotest.pdf")
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 20 * 1024


def test_build_pdf_without_logo_present(monkeypatch):
    import services.pdf_report as pdf_service
    monkeypatch.setattr(pdf_service, "_find_logo_path", lambda: None)
    report = _real_report()
    pdf_bytes = pdf_service.build_pdf(report, "ClauseGuard_Rapport_nologotest.pdf")
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 5 * 1024
