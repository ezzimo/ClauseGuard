from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ContractStatus(str, Enum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    PROCESSING = "processing"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    PENDING_HUMAN_VALIDATION = "pending_human_validation"
    DECISIONS_RECORDED = "decisions_recorded"
    COMPLETED = "completed"
    PARSE_ERROR = "parse_error"
    FLOW_ERROR = "flow_error"
    ERROR = "error"


class ContractUploadResponse(BaseModel):
    contract_id: str
    filename: str
    content_type: str
    text_preview: str
    char_count: int
    status: ContractStatus
    pii_mapping: dict = {}


class Finding(BaseModel):
    clause_id: str
    reference: str
    clause_text: str
    type: str
    original_risk_level: str
    audit_decision: str
    audit_reason: str
    corrected_risk_level: str
    risk_summary: str
    source_excerpts: list[str]
    proposed_rewrite: Optional[str] = None
    human_review_required: bool


class AuditedFindings(BaseModel):
    audit_status: str
    audited_findings: list[Finding]
    global_audit_notes: list[str]
    disclaimer: str


class DecisionAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    RECLASSIFY = "reclassify"
    REQUEST_LAWYER_REVIEW = "request_lawyer_review"
    ASK_FOR_MORE_CONTEXT = "ask_for_more_context"


class Decision(BaseModel):
    clause_id: str
    action: DecisionAction
    new_risk_level: Optional[str] = None
    comment: Optional[str] = ""


class DecisionSubmission(BaseModel):
    decisions: list[Decision]


class DecisionsResponse(BaseModel):
    contract_id: str
    status: ContractStatus
    pending_clauses: list[str]


class ReportClause(BaseModel):
    clause_id: str
    reference: str
    original_risk_level: str
    corrected_risk_level: str
    human_decision: Optional[str] = None
    comment: Optional[str] = None


class DashboardMetrics(BaseModel):
    total_clauses: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    pending_decisions: int


class FinalReport(BaseModel):
    contract_id: str
    analysis_date: str
    overall_risk: str
    executive_summary: str
    clauses: list[ReportClause]
    audit_log: list[dict]
    dashboard_metrics: DashboardMetrics
    disclaimer: str


class ContractContext(BaseModel):
    contract_type: str = ""
    cote: str = ""
    montant: str = ""
    parties: list[str] = []


class ContractState(BaseModel):
    contract_id: str
    filename: str
    content_type: str
    text: str
    masked_text: str
    pii_mapping: dict
    char_count: int
    status: ContractStatus
    progress_hint: str = ""
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    context: ContractContext = ContractContext()
    analysis_result: Optional[AuditedFindings] = None
    raw_analysis_response: Optional[str] = None
    human_decisions: list[Decision] = []
    final_report: Optional[FinalReport] = None


class AnalysisResponse(BaseModel):
    contract_id: str
    status: ContractStatus
    message: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    type: Optional[str] = None
    exp: Optional[int] = None


class UserLogin(BaseModel):
    username: str
    password: str


class HealthResponse(BaseModel):
    status: str


class AuditLogEntry(BaseModel):
    timestamp: datetime
    flow_id: str
    latency_ms: int
    status: str
    actor: str = "system"
