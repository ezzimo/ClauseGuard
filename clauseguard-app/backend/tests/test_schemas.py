import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pydantic import ValidationError

from models.schemas import (
    AuditedFindings,
    ContractState,
    ContractStatus,
    ContractUploadResponse,
    Decision,
    FinalReport,
    Finding,
)


def _finding():
    return {
        "clause_id": "C1",
        "reference": "Article 1",
        "clause_text": "text",
        "type": "responsabilité",
        "original_risk_level": "moyen",
        "audit_decision": "accept",
        "audit_reason": "ok",
        "corrected_risk_level": "moyen",
        "risk_summary": "résumé",
        "source_excerpts": ["extrait"],
        "proposed_rewrite": None,
        "human_review_required": False,
    }


class TestFinding:
    def test_valid_findings(self):
        for ref in ["Article 1", "Section 2", "Clause 3", "Art. 4", "5"]:
            data = _finding()
            data["reference"] = ref
            Finding.model_validate(data)

    def test_invalid_findings(self):
        with pytest.raises(ValidationError):
            Finding.model_validate({**_finding(), "clause_id": 123})
        with pytest.raises(ValidationError):
            Finding.model_validate({**_finding(), "human_review_required": "maybe"})
        with pytest.raises(ValidationError):
            Finding.model_validate({**_finding(), "source_excerpts": "not a list"})
        with pytest.raises(ValidationError):
            Finding.model_validate({**_finding(), "original_risk_level": 123})
        with pytest.raises(ValidationError):
            Finding.model_validate({**_finding(), "proposed_rewrite": 456})


class TestAuditedFindings:
    def test_valid_payloads(self):
        for status in ["completed", "partial", "error", "validated", "pending"]:
            AuditedFindings.model_validate({
                "audit_status": status,
                "audited_findings": [_finding()],
                "global_audit_notes": [],
                "disclaimer": "disc",
            })

    def test_invalid_payloads(self):
        with pytest.raises(ValidationError):
            AuditedFindings.model_validate({
                "audit_status": "ok",
                "audited_findings": "bad",
                "global_audit_notes": [],
                "disclaimer": "disc",
            })
        with pytest.raises(ValidationError):
            AuditedFindings.model_validate({
                "audit_status": "ok",
                "audited_findings": [],
                "global_audit_notes": "bad",
                "disclaimer": "disc",
            })
        with pytest.raises(ValidationError):
            AuditedFindings.model_validate({
                "audited_findings": [],
                "global_audit_notes": [],
                "disclaimer": "disc",
            })
        with pytest.raises(ValidationError):
            AuditedFindings.model_validate({
                "audit_status": "ok",
                "audited_findings": [{**_finding(), "clause_id": 123}],
                "global_audit_notes": [],
                "disclaimer": "disc",
            })
        with pytest.raises(ValidationError):
            AuditedFindings.model_validate({
                "audit_status": "ok",
                "audited_findings": [_finding()],
                "global_audit_notes": [],
            })


class TestDecision:
    def test_valid_decisions(self):
        for action in ["approve", "reject", "reclassify", "request_lawyer_review", "ask_for_more_context"]:
            Decision.model_validate({
                "clause_id": "C1",
                "action": action,
                "new_risk_level": "moyen",
                "comment": "ok",
            })

    def test_invalid_decisions(self):
        with pytest.raises(ValidationError):
            Decision.model_validate({"clause_id": "C1", "action": "ignore"})
        with pytest.raises(ValidationError):
            Decision.model_validate({"action": "approve"})
        with pytest.raises(ValidationError):
            Decision.model_validate({"clause_id": "C1", "action": "approve", "new_risk_level": 123})
        with pytest.raises(ValidationError):
            Decision.model_validate({"clause_id": 123, "action": "approve"})
        with pytest.raises(ValidationError):
            Decision.model_validate({"clause_id": "C1", "action": "approve", "comment": 123})


class TestFinalReport:
    def test_valid_reports(self):
        for overall in ["faible", "moyen", "élevé", "critique", "inconnu"]:
            FinalReport.model_validate({
                "contract_id": "id",
                "analysis_date": "2026-07-14",
                "overall_risk": overall,
                "executive_summary": "résumé",
                "clauses": [],
                "audit_log": [],
                "dashboard_metrics": {
                    "total_clauses": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "pending_decisions": 0,
                },
                "disclaimer": "disc",
            })

    def test_invalid_reports(self):
        base = {
            "contract_id": "id",
            "analysis_date": "2026-07-14",
            "overall_risk": "moyen",
            "executive_summary": "résumé",
            "clauses": [],
            "audit_log": [],
            "dashboard_metrics": {
                "total_clauses": 0,
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 0,
                "pending_decisions": 0,
            },
            "disclaimer": "disc",
        }
        with pytest.raises(ValidationError):
            FinalReport.model_validate({**base, "dashboard_metrics": {}})
        with pytest.raises(ValidationError):
            FinalReport.model_validate({**base, "clauses": "bad"})
        with pytest.raises(ValidationError):
            FinalReport.model_validate({**base, "audit_log": "bad"})
        with pytest.raises(ValidationError):
            FinalReport.model_validate({**base, "executive_summary": 123})
        with pytest.raises(ValidationError):
            FinalReport.model_validate({**base, "overall_risk": None})
        with pytest.raises(ValidationError):
            FinalReport.model_validate({k: v for k, v in base.items() if k != "disclaimer"})


class TestContractUploadResponse:
    def test_valid_responses(self):
        for preview in ["abc", "x" * 500, "", "text...", "prévisualisation"]:
            ContractUploadResponse.model_validate({
                "contract_id": "id",
                "filename": "c.pdf",
                "content_type": "application/pdf",
                "text_preview": preview,
                "char_count": 3,
                "status": "uploaded",
                "pii_mapping": {},
            })

    def test_invalid_responses(self):
        base = {
            "contract_id": "id",
            "filename": "c.pdf",
            "content_type": "application/pdf",
            "text_preview": "abc",
            "char_count": 3,
            "status": "uploaded",
            "pii_mapping": {},
        }
        with pytest.raises(ValidationError):
            ContractUploadResponse.model_validate({**base, "contract_id": 123})
        with pytest.raises(ValidationError):
            ContractUploadResponse.model_validate({**base, "char_count": "three"})
        with pytest.raises(ValidationError):
            ContractUploadResponse.model_validate({**base, "status": "unknown"})
        with pytest.raises(ValidationError):
            ContractUploadResponse.model_validate({**base, "pii_mapping": "bad"})
        with pytest.raises(ValidationError):
            ContractUploadResponse.model_validate({**base, "filename": 123})


class TestContractState:
    def test_valid_states(self):
        for status in ContractStatus:
            ContractState.model_validate({
                "contract_id": "id",
                "filename": "c.txt",
                "content_type": "text/plain",
                "text": "text",
                "masked_text": "text",
                "pii_mapping": {},
                "char_count": 4,
                "status": status.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    def test_invalid_states(self):
        base = {
            "contract_id": "id",
            "filename": "c.txt",
            "content_type": "text/plain",
            "text": "text",
            "masked_text": "text",
            "pii_mapping": {},
            "char_count": 4,
            "status": "uploaded",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with pytest.raises(ValidationError):
            ContractState.model_validate({**base, "char_count": "four"})
        with pytest.raises(ValidationError):
            ContractState.model_validate({**base, "created_at": "bad"})
        with pytest.raises(ValidationError):
            ContractState.model_validate({**base, "status": "missing"})
        with pytest.raises(ValidationError):
            ContractState.model_validate({**base, "pii_mapping": [1, 2]})
        with pytest.raises(ValidationError):
            ContractState.model_validate({**base, "human_decisions": "bad"})
