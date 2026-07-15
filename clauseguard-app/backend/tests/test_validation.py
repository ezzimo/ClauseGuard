import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schemas import AuditedFindings


def main() -> int:
    sample_path = Path(__file__).parent / "sample_finding.json"
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    findings = AuditedFindings.model_validate(data)
    assert findings.audit_status == "completed"
    assert len(findings.audited_findings) == 1
    assert findings.audited_findings[0].clause_id == "ART_1"
    print("Pydantic validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
