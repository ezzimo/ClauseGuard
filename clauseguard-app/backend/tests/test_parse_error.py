import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from main import app, fusion_client, settings
from models.schemas import ContractState, ContractStatus


def _token() -> str:
    resp = TestClient(app).post(
        "/api/auth/login",
        json={"username": "clauseguard", "password": "clauseguard"},
    )
    return resp.json()["access_token"]


def main() -> int:
    contract_id = uuid4().hex
    state = ContractState(
        contract_id=contract_id,
        filename="test.txt",
        content_type="text/plain",
        text="Contrat de test",
        masked_text="Contrat de test",
        pii_mapping={},
        char_count=17,
        status=ContractStatus.UPLOADED,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    state_path = Path(settings.storage_dir) / f"{contract_id}.json"
    state_path.write_text(json.dumps(state.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")

    original_run_flow = fusion_client.run_flow
    fusion_client.run_flow = lambda flow_id, message, session_id=None: {
        "response_text": "not valid json",
        "status_code": 200,
        "duration_ms": 123,
    }

    try:
        settings.flow_analysis_id = "test-flow"
        token = _token()
        resp = TestClient(app).post(
            f"/api/contracts/{contract_id}/analyze",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.json()
        assert resp.status_code == 200, body
        assert body["status"] == ContractStatus.PARSE_ERROR.value

        stored = json.loads(state_path.read_text(encoding="utf-8"))
        assert stored["status"] == ContractStatus.PARSE_ERROR.value
        assert stored["raw_analysis_response"] == "not valid json"

        audit_lines = Path(settings.storage_dir) / "audit_log.jsonl"
        if audit_lines.exists():
            last = json.loads(audit_lines.read_text(encoding="utf-8").strip().split("\n")[-1])
            assert last["flow_id"] != ""
            assert last["actor"] == "system"

        print("Parse error path: PASS")
        return 0
    finally:
        fusion_client.run_flow = original_run_flow
        if state_path.exists():
            state_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
