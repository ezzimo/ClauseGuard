import json
from pathlib import Path

import uvicorn

from main import app, fusion_client

SAMPLE_FINDINGS = Path(__file__).parent / "tests" / "sample_finding.json"
SAMPLE_REPORT = Path(__file__).parent / "tests" / "sample_report.json"

findings_text = SAMPLE_FINDINGS.read_text(encoding="utf-8")
report_template = SAMPLE_REPORT.read_text(encoding="utf-8")


def mock_run_flow(flow_id, message, session_id=None):
    if isinstance(message, str) and message.strip().startswith("{"):
        payload = json.loads(message)
        contract_id = payload.get("contract_id", "test-contract")
        report_text = report_template.replace('"test-contract"', json.dumps(contract_id))
        return {
            "response_text": report_text,
            "status_code": 200,
            "duration_ms": 120,
        }
    return {
        "response_text": findings_text,
        "status_code": 200,
        "duration_ms": 100,
    }


fusion_client.run_flow = mock_run_flow

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
