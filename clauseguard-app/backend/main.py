import io
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import Body, Depends, FastAPI, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
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
from services import report_store
from services.auth import authenticate_user, create_token_pair, get_current_user, refresh_access_token
from services.extract import extract_text
from services.fusion import FusionClient
from services.pdf_report import build_pdf
from services.anonymizer import AnonymizationLeakError, mask_pii
from services.anonymizer.party_extractor import extract_party_names

# Report background job polling schedule: wait REPORT_POLL_INITIAL_DELAY_S before
# the first DB check (the flow rarely finishes faster than that), then poll every
# REPORT_POLL_INTERVAL_S until REPORT_POLL_BUDGET_S total has elapsed. Module-level
# so tests can monkeypatch them down to run fast.
REPORT_POLL_INITIAL_DELAY_S = 60
REPORT_POLL_INTERVAL_S = 5
REPORT_POLL_BUDGET_S = 180

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if not settings.flow_report_fallback_id:
        logging.error(
            "FLOW_REPORT_FALLBACK_ID is not set: if the primary report flow "
            "fails AND the MCP SQLite DB poll finds nothing, report generation "
            "has no recovery path and contracts will end up in 'report_error'."
        )
    yield


app = FastAPI(title="ClauseGuard API", version="0.1.0", lifespan=_lifespan)

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
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(state.model_dump(mode="json"), fh, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


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


def _extract_json_object(text: str) -> str:
    """Slice from the first '{' to the last '}'.

    LLM responses sometimes carry a conversational preamble ("Souhaitez-vous
    que je...") before/after the actual JSON payload. Raises ValueError (a
    parse-failure, not a crash) if no JSON object delimiters are found.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in response")
    return text[start : end + 1]


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
    cleaned = _extract_json_object(_strip_markdown_fences(raw_text))
    return AuditedFindings.model_validate_json(cleaned)


def _parse_report(raw_text: str) -> FinalReport:
    cleaned = _extract_json_object(_strip_markdown_fences(raw_text))
    return FinalReport.model_validate_json(cleaned)


def _http_status_label(exc: Exception) -> str:
    """Best-effort short label for an exception, for the audit log's status column."""
    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        if response is not None:
            return str(response.status_code)
        return "http_error"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    return "error"


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
    if not party_names:
        party_names = extract_party_names(text)
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
        if f.human_review_required and f.clause_id not in decided_ids
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


def _run_report_background(
    contract_id: str,
    flow_id: str,
    fallback_id: str,
    payload: dict,
    request_id: str,
) -> None:
    """Background job: dispatch the v2 report flow, then recover the result
    from the MCP SQLite DB if the HTTP response never came back (504/timeout
    is EXPECTED here — the platform gateway cuts the connection but the flow
    keeps running server-side and still writes to SQLite / sends the email).
    """
    path = _contract_path(contract_id)

    def _update(**kwargs) -> None:
        try:
            state = ContractState(**json.load(path.open("r", encoding="utf-8")))
            for key, value in kwargs.items():
                setattr(state, key, value)
            state.updated_at = datetime.now(timezone.utc)
            _save_state(state)
        except Exception:
            logging.exception(
                "Failed to update contract %s during report generation", contract_id
            )

    payload_json = json.dumps(payload)
    job_started_at = datetime.now(timezone.utc)
    candidate_fallback: FinalReport | None = None
    primary_error: Exception | None = None

    # a. Call the v2 flow. ANY exception (including a 504) is expected and
    #    non-fatal: never abort here, just fall through to DB polling.
    try:
        primary_result = fusion_client.run_flow(
            flow_id, payload_json, retry_on_5xx=False
        )
        _append_audit(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                flow_id=flow_id,
                latency_ms=primary_result["duration_ms"],
                status=str(primary_result["status_code"]),
                actor="system",
                action="report_primary_response",
                detail=f"request_id={request_id}",
            )
        )
        try:
            candidate_fallback = _parse_report(primary_result["response_text"])
            candidate_fallback.delivery = "fallback_flow_response"
        except Exception as parse_exc:
            logging.warning(
                "Primary report response for %s failed to parse: %s",
                contract_id,
                parse_exc,
            )
    except Exception as exc:
        primary_error = exc
        _append_audit(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                flow_id=flow_id,
                latency_ms=0,
                status=_http_status_label(exc),
                actor="system",
                action="report_primary_dispatch_failed",
                detail=f"request_id={request_id}; {str(exc)[:200]}",
            )
        )

    # b. Poll the MCP SQLite DB for the side effects the flow writes even
    #    when the HTTP response was lost.
    report: FinalReport | None = None
    since_iso = job_started_at.isoformat()
    time.sleep(REPORT_POLL_INITIAL_DELAY_S)
    found_json = report_store.find_report(contract_id, since_iso)
    elapsed = REPORT_POLL_INITIAL_DELAY_S
    while found_json is None and elapsed < REPORT_POLL_BUDGET_S:
        time.sleep(REPORT_POLL_INTERVAL_S)
        elapsed += REPORT_POLL_INTERVAL_S
        found_json = report_store.find_report(contract_id, since_iso)

    if found_json is not None:
        try:
            report = FinalReport.model_validate_json(found_json)
            report.delivery = "full_db"
            _append_audit(
                AuditLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    flow_id=flow_id,
                    latency_ms=0,
                    status="found",
                    actor="system",
                    action="report_found_in_db",
                    detail=f"request_id={request_id}",
                )
            )
        except Exception:
            logging.exception(
                "Report row in DB for contract %s failed validation", contract_id
            )

    # c. Fall back in priority order: the primary's own (possibly late)
    #    response, then the pure-LLM v1 fallback flow (no side effects).
    if report is None and candidate_fallback is not None:
        report = candidate_fallback

    if report is None and fallback_id:
        try:
            fallback_result = fusion_client.run_flow(
                fallback_id, payload_json, retry_on_5xx=True
            )
            _append_audit(
                AuditLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    flow_id=fallback_id,
                    latency_ms=fallback_result["duration_ms"],
                    status=str(fallback_result["status_code"]),
                    actor="system",
                    action="report_fallback_response",
                    detail=f"request_id={request_id}",
                )
            )
            report = _parse_report(fallback_result["response_text"])
            report.delivery = "fallback_no_dispatch"
        except Exception as exc:
            logging.exception("Fallback report flow failed for contract %s", contract_id)
            _append_audit(
                AuditLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    flow_id=fallback_id,
                    latency_ms=0,
                    status="failed",
                    actor="system",
                    action="report_fallback_failed",
                    detail=f"request_id={request_id}; {str(exc)[:200]}",
                )
            )
    elif report is None and not fallback_id:
        logging.warning(
            "No FLOW_REPORT_FALLBACK_ID configured; contract %s has no report fallback path",
            contract_id,
        )

    if report is None:
        _update(
            status=ContractStatus.REPORT_ERROR,
            progress_hint="done",
            error_message=f"Report generation failed: {primary_error}",
        )
        return

    _update(
        status=ContractStatus.COMPLETED,
        final_report=report,
        progress_hint="done",
        error_message=None,
    )


def _recover_report(contract_id: str, state: ContractState) -> JSONResponse:
    """Serve an already-saved report straight from the MCP SQLite DB, without
    calling any flow or sending any email. Used when a prior run actually
    completed on the platform side (SQLite upsert + email both happened) but
    our job gave up and marked the contract report_error — re-running the
    flow here would re-send the lawyer email."""
    if state.status != ContractStatus.REPORT_ERROR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Recovery only allowed from report_error (current: {state.status.value})",
        )

    # No request_id filter: we want whatever is in the DB for this contract,
    # regardless of which dispatch attempt produced it.
    found_json = report_store.find_report(contract_id, since_iso="1970-01-01T00:00:00+00:00")
    if found_json is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No report found in the MCP database for this contract",
        )

    try:
        report = FinalReport.model_validate_json(found_json)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DB report row failed validation: {exc}",
        ) from exc

    if state.report_request_id and report.request_id and report.request_id != state.report_request_id:
        logging.warning(
            "Recovered report request_id (%s) differs from contract's last "
            "dispatched request_id (%s) for %s",
            report.request_id,
            state.report_request_id,
            contract_id,
        )
        _append_audit(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                flow_id=settings.flow_report_id,
                latency_ms=0,
                status="request_id_mismatch",
                actor="system",
                action="report_recovery_request_id_mismatch",
                detail=f"db_request_id={report.request_id}; contract_request_id={state.report_request_id}",
            )
        )

    report.delivery = "full_db_recovered"
    state.final_report = report
    state.status = ContractStatus.COMPLETED
    state.progress_hint = "done"
    state.error_message = None
    state.updated_at = datetime.now(timezone.utc)
    _save_state(state)

    _append_audit(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            flow_id=settings.flow_report_id or "",
            latency_ms=0,
            status="recovered",
            actor="system",
            action="report_recovered_from_db",
            detail=f"contract_id={contract_id}",
        )
    )

    return JSONResponse(status_code=status.HTTP_200_OK, content=report.model_dump(mode="json"))


@app.post(
    "/api/contracts/{contract_id}/report",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_report(
    contract_id: str,
    recover: bool = False,
    user: dict = Depends(get_current_user),
):
    state = _load_state(contract_id)

    if recover:
        return _recover_report(contract_id, state)

    if not state.analysis_result:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No analysis result available",
        )

    if not state.analysis_result.audited_findings:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="aucun constat a rapporter",
        )

    if state.status == ContractStatus.REPORT_PROCESSING:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "report_processing"},
        )

    flow_id = settings.flow_report_id
    if not flow_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FLOW_REPORT_ID not configured",
        )

    fallback_id = settings.flow_report_fallback_id
    request_id = uuid.uuid4().hex

    payload = {
        "audited_findings": state.analysis_result.model_dump(mode="json"),
        "human_decisions": [d.model_dump(mode="json") for d in state.human_decisions],
        "contract_id": contract_id,
        "analysis_date": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
    }
    payload_json = json.dumps(payload)

    # Trace the exact payload sent to the report flow so a chatting/off-script
    # LLM response can be traced back to its input.
    _append_audit(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            flow_id=flow_id,
            latency_ms=0,
            status="dispatched",
            actor="system",
            action="report_payload_size",
            detail=f"size={len(payload_json)}; preview={payload_json[:200]!r}; request_id={request_id}",
        )
    )

    state.status = ContractStatus.REPORT_PROCESSING
    state.progress_hint = "generating_report"
    state.report_request_id = request_id
    state.error_message = None
    state.updated_at = datetime.now(timezone.utc)
    _save_state(state)

    thread = threading.Thread(
        target=_run_report_background,
        args=(contract_id, flow_id, fallback_id, payload, request_id),
        daemon=True,
    )
    thread.start()

    return {
        "contract_id": contract_id,
        "status": ContractStatus.REPORT_PROCESSING.value,
        "message": "Report generation started",
        "request_id": request_id,
    }


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


@app.get("/api/contracts/{contract_id}/report/pdf")
async def get_report_pdf(
    contract_id: str,
    user: dict = Depends(get_current_user),
):
    state = _load_state(contract_id)
    if not state.final_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    contract_id_short = contract_id[:8]
    filename = f"ClauseGuard_Rapport_{contract_id_short}.pdf"
    pdf_bytes = build_pdf(state.final_report, filename, validated_by=user.get("username"))

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/contracts")
async def list_contracts(user: dict = Depends(get_current_user)) -> list[dict]:
    """Return a summary list of all stored contracts."""
    contracts: list[dict] = []
    for path in STORAGE_PATH.glob("*.json"):
        if path.name == "audit_log.jsonl":
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            contracts.append({
                "contract_id": data["contract_id"],
                "filename": data["filename"],
                "status": data["status"],
                "updated_at": data["updated_at"],
                "analysis_result": data.get("analysis_result"),
                "human_decisions": data.get("human_decisions", []),
                "final_report": data.get("final_report"),
            })
        except Exception:
            continue
    contracts.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return contracts


@app.get("/api/activity")
async def get_activity(limit: int = 15, user: dict = Depends(get_current_user)) -> list[dict]:
    """Return the most recent audit log entries."""
    entries: list[dict] = []
    if not AUDIT_LOG_PATH.exists():
        return entries
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in reversed(lines[-limit:]):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return entries


@app.get("/api/contracts/{contract_id}", response_model=ContractState)
async def get_contract(
    contract_id: str,
    user: dict = Depends(get_current_user),
) -> ContractState:
    return _load_state(contract_id)
