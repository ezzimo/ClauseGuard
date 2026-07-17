"""TXT upload extraction: routing must be by filename extension only (never
content_type), with a utf-8 -> cp1252 -> latin-1 decode fallback chain."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "clauseguard", "password": "clauseguard"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _upload(client, token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/contracts/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


def test_txt_utf8_with_accents_uploads_and_masks_pii(client, token):
    content = (
        "Contrat de prestation de services entre les parties.\n"
        "Article 1 - Conditions générales convenues entre le Client et le Prestataire.\n"
        "Contact : jean.dupont@example.com\n"
    ).encode("utf-8")

    resp = _upload(client, token, "contrat_accents.txt", content)
    assert resp.status_code == 200
    body = resp.json()
    assert "générales" in body["text_preview"]
    assert body["char_count"] > 0
    # PII masking still runs on the decoded text.
    assert any("EMAIL" in key or "@" in value for key, value in body["pii_mapping"].items()) or body["pii_mapping"]


def test_txt_cp1252_bytes_decoded_correctly(client, token):
    raw = (
        b"CONTRAT DE PRESTATION DE SERVICES\n\n"
        b"Article 1 - Conditions. La soci\xe9t\xe9 XYZ fournira ses services selon les "
        b"conditions convenues entre les parties.\n"
        b"Article 2 - Accord entre les parties.\n"
    )
    resp = _upload(client, token, "contrat_cp1252.txt", raw)
    assert resp.status_code == 200
    assert "société" in resp.json()["text_preview"]


def test_csv_rejected_regardless_of_content_type(client, token):
    content = (
        b"Contrat de prestation de services entre les parties.\n"
        b"Article 1 - Conditions convenues entre le Client et le Prestataire.\n"
    )
    # A .csv is frequently sent with content_type text/plain by real clients;
    # routing must key off the extension, not this header.
    resp = _upload(client, token, "contrat.csv", content, content_type="text/plain")
    assert resp.status_code == 415
    assert "format non supporte" in resp.json()["detail"]


def test_line_endings_normalized_to_lf(client, token):
    content = (
        b"Contrat de prestation de services entre les parties.\r\n"
        b"Article 1 - Conditions convenues entre le Client et le Prestataire.\r\n"
    )
    resp = _upload(client, token, "contrat_crlf.txt", content)
    assert resp.status_code == 200
    assert "\r" not in resp.json()["text_preview"]


def test_real_e2e_fixture_uploads_end_to_end(client, token):
    raw = (Path(__file__).parent / "contrat_test_e2e.txt").read_bytes()
    resp = _upload(client, token, "contrat_test_e2e.txt", raw)
    assert resp.status_code == 200
    assert resp.json()["char_count"] > 0
