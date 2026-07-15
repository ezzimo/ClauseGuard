import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.schemas import (
    AnalysisResponse,
    AuditLogEntry,
    AuditedFindings,
    ContractContext,
    ContractState,
    ContractStatus,
    ContractUploadResponse,
    DecisionSubmission,
    DecisionsResponse,
    FinalReport,
    HealthResponse,
    TokenPair,
    UserLogin,
)
from services.auth import authenticate_user, create_token_pair, get_current_user, refresh_access_token
from services.extract import extract_text
from services.fusion import FusionClient
from services.anonymizer import AnonymizationLeakError, mask_pii

app = FastAPI(title="ClauseGuard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_PATH = Path(settings.storage_dir).resolve()
STORAGE_PATH.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_PATH = STORAGE_PATH / "audit_log.jsonl"

fusion_client = FusionClient()


def _contract_path(contract_id: str) -> Path:
    return STORAGE_PATH / f"{contract_id}.json"


def _save_state(state: ContractState) -> None:
    path = _contract_path(state.contract_id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state.model_dump(mode="json"), fh, ensure_ascii=False, indent=2)


def _load_state(contract_id: str) -> ContractState:
    path = _contract_path(contract_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract not found",
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return ContractState(**data)


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _append_audit(entry: AuditLogEntry) -> None:
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _append_human_decision_audit(contract_id: str, decision: dict) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "contract_id": contract_id,
        "actor": "human",
        "decision": decision,
    }
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _run_analysis(flow_id: str, masked_text: str) -> dict:
    context = "CONTEXTE: {side=client, type=prestation_services}\n\nCONTRAT:\n"
    input_text = context + masked_text
    result = fusion_client.run_flow(flow_id, input_text)
    _append_audit(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            flow_id=flow_id,
            latency_ms=result["duration_ms"],
            status=str(result["status_code"]),
            actor="system",
        )
    )
    return result


def _parse_findings(raw_text: str) -> AuditedFindings:
    cleaned = _strip_markdown_fences(raw_text)
    return AuditedFindings.model_validate_json(cleaned)


def _parse_report(raw_text: str) -> FinalReport:
    cleaned = _strip_markdown_fences(raw_text)
    return FinalReport.model_validate_json(cleaned)


def _is_high_risk(level: str) -> bool:
    return level.lower() in {
        "orange", "rouge", "red", "high", "élevé", "critique", "critical",
        "moyen", "medium", "modéré", "modere",
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/auth/login", response_model=TokenPair)
async def login(credentials: UserLogin) -> TokenPair:
    user = authenticate_user(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return create_token_pair(user["username"])


@app.post("/api/auth/refresh", response_model=TokenPair)
async def refresh(refresh_token: str) -> TokenPair:
    new_access = refresh_access_token(refresh_token)
    return TokenPair(access_token=new_access, refresh_token=refresh_token)


@app.post("/api/contracts/upload", response_model=ContractUploadResponse)
async def upload_contract(
    file: UploadFile,
    contract_type: str = Form(default=""),
    cote: str = Form(default=""),
    montant: str = Form(default=""),
    parties: str = Form(default="[]"),
    user: dict = Depends(get_current_user),
) -> ContractUploadResponse:
    text, char_count = await extract_text(file)
    try:
        party_names = json.loads(parties)
        if not isinstance(party_names, list):
            party_names = []
    except Exception:
        party_names = []
    try:
        masked_text, pii_mapping, _stats = mask_pii(text, party_names)
    except AnonymizationLeakError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"document non anonymisable automatiquement, revue manuelle requise: {exc}",
        ) from exc
    contract_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    state = ContractState(
        contract_id=contract_id,
        filename=file.filename or "untitled",
        content_type=file.content_type or "application/octet-stream",
        text=text,
        masked_text=masked_text,
        pii_mapping=pii_mapping,
        char_count=char_count,
        status=ContractStatus.UPLOADED,
        created_at=now,
        updated_at=now,
        context=ContractContext(
            contract_type=contract_type,
            cote=cote,
            montant=montant,
            parties=party_names,
        ),
    )
    _save_state(state)
    preview = masked_text[:500] + ("..." if char_count > 500 else "")
    return ContractUploadResponse(
        contract_id=contract_id,
        filename=state.filename,
        content_type=state.content_type,
        text_preview=preview,
        char_count=char_count,
        status=state.status,
        pii_mapping=pii_mapping,
    )


def _run_analysis_background(contract_id: str, flow_id: str, masked_text: str) -> None:
    """Background task: call Fusion analysis flow, parse response, update state."""
    path = _contract_path(contract_id)

    def _update(**kwargs) -> None:
        try:
            state = ContractState(**json.load(path.open("r", encoding="utf-8")))
            for key, value in kwargs.items():
                setattr(state, key, value)
            state.updated_at = datetime.now(timezone.utc)
            _save_state(state)
        except Exception:
            pass

    raw_text: str | None = None
    try:
        _update(status=ContractStatus.PROCESSING, progress_hint="calling_flow")
        result = _run_analysis(flow_id, masked_text)
        raw_text = result["response_text"]
        _update(progress_hint="parsing")
        findings = _parse_findings(raw_text)
        _update(
            status=ContractStatus.AWAITING_HUMAN_REVIEW,
            analysis_result=findings,
            raw_analysis_response=raw_text,
            progress_hint="done",
            error_message=None,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        _update(
            status=ContractStatus.PARSE_ERROR,
            raw_analysis_response=raw_text or "",
            progress_hint="done",
            error_message=f"Parse error: {exc}",
        )
    except Exception as exc:
        logging.exception("Analysis background task failed for contract %s", contract_id)
        _update(
            status=ContractStatus.FLOW_ERROR,
            progress_hint="done",
            error_message=f"Analysis failed: {exc}",
        )


@app.post(
    "/api/contracts/{contract_id}/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_contract(
    contract_id: str,
    user: dict = Depends(get_current_user),
) -> AnalysisResponse:
    state = _load_state(contract_id)

    if state.status == ContractStatus.PROCESSING:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "processing"},
        )

    flow_id = settings.flow_analysis_id
    if not flow_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FLOW_ANALYSIS_ID not configured",
        )

    state.status = ContractStatus.PROCESSING
    state.progress_hint = "calling_flow"
    state.error_message = None
    state.updated_at = datetime.now(timezone.utc)
    _save_state(state)

    thread = threading.Thread(
        target=_run_analysis_background,
        args=(contract_id, flow_id, state.masked_text),
        daemon=True,
    )
    thread.start()

    return AnalysisResponse(
        contract_id=contract_id,
        status=ContractStatus.PROCESSING,
        message="Analysis started",
    )


@app.post("/api/contracts/{contract_id}/decisions", response_model=DecisionsResponse)
async def record_decisions(
    contract_id: str,
    submission: DecisionSubmission,
    user: dict = Depends(get_current_user),
) -> DecisionsResponse:
    state = _load_state(contract_id)
    if not state.analysis_result:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No analysis result available",
        )

    finding_ids = {f.clause_id for f in state.analysis_result.audited_findings}
    for decision in submission.decisions:
        if decision.clause_id not in finding_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clause_id: {decision.clause_id}",
            )

    existing_ids = {d.clause_id for d in state.human_decisions}
    for decision in submission.decisions:
        if decision.clause_id in existing_ids:
            state.human_decisions = [
                d for d in state.human_decisions if d.clause_id != decision.clause_id
            ]
        state.human_decisions.append(decision)
        _append_human_decision_audit(contract_id, decision.model_dump(mode="json"))

    decided_ids = {d.clause_id for d in state.human_decisions}
    pending_clauses = [
        f.clause_id
        for f in state.analysis_result.audited_findings
        if _is_high_risk(f.corrected_risk_level) and f.clause_id not in decided_ids
    ]

    if pending_clauses:
        state.status = ContractStatus.PENDING_HUMAN_VALIDATION
    else:
        state.status = ContractStatus.DECISIONS_RECORDED
    state.updated_at = datetime.now(timezone.utc)
    _save_state(state)

    return DecisionsResponse(
        contract_id=contract_id,
        status=state.status,
        pending_clauses=pending_clauses,
    )


@app.post("/api/contracts/{contract_id}/report")
async def generate_report(
    contract_id: str,
    user: dict = Depends(get_current_user),
):
    state = _load_state(contract_id)
    if not state.analysis_result:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No analysis result available",
        )

    flow_id = settings.flow_report_id
    if not flow_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FLOW_REPORT_ID not configured",
        )

    payload = {
        "audited_findings": state.analysis_result.model_dump(mode="json"),
        "human_decisions": [d.model_dump(mode="json") for d in state.human_decisions],
        "contract_id": contract_id,
        "analysis_date": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = fusion_client.run_flow(flow_id, json.dumps(payload))
        _append_audit(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                flow_id=flow_id,
                latency_ms=result["duration_ms"],
                status=str(result["status_code"]),
                actor="system",
            )
        )
        report = _parse_report(result["response_text"])
        state.final_report = report
        state.status = ContractStatus.COMPLETED
        state.updated_at = datetime.now(timezone.utc)
        _save_state(state)
        return report.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Report generation failed: {exc}",
        ) from exc


@app.get("/api/contracts/{contract_id}/report")
async def get_report(
    contract_id: str,
    user: dict = Depends(get_current_user),
):
    state = _load_state(contract_id)
    if not state.final_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    return state.final_report.model_dump(mode="json")


@app.get("/api/contracts/{contract_id}", response_model=ContractState)
async def get_contract(
    contract_id: str,
    user: dict = Depends(get_current_user),
) -> ContractState:
    return _load_state(contract_id)
