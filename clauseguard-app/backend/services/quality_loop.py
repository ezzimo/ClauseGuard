"""A2A quality loop: a critic flow scores the audited findings, and — if the
score falls short — a refiner flow proposes corrections that get merged back
in, up to a fixed number of iterations. Feature-flagged (QUALITY_LOOP); when
disabled this module is never called and the analysis pipeline is unchanged.

Design contract: this loop must NEVER block or fail the analysis it runs
inside. Any flow/parse failure anywhere in the loop is caught, logged, and
surfaces as a `quality.error` + `quality_warning` flag on the best findings
seen so far (falling back to the untouched input if nothing succeeded).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from models.schemas import Finding
from services.parsing import extract_json_object, strip_markdown_fences

logger = logging.getLogger(__name__)

AuditFn = Callable[[str, str, str, str], None]
"""(flow_id, status_label, action, detail) -> None"""


@dataclass
class QualityTrace:
    contract_id: str
    request_id: str
    fusion_client: Any  # services.fusion.FusionClient
    audit_fn: AuditFn
    critic_flow_id: str
    refiner_flow_id: str
    threshold: float = 0.75
    max_iterations: int = 2


class CriticIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clause_id: str
    problem: str = ""


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    global_score: float
    criteria_scores: dict = {}
    verdict: str
    issues: list[CriticIssue] = []


def _parse_json(raw_text: str) -> dict:
    cleaned = extract_json_object(strip_markdown_fences(raw_text))
    return json.loads(cleaned)


def _compact_findings_json(findings: list[Finding]) -> str:
    """clause_text truncated to 300 chars; no disclaimer/global notes (those
    live on AuditedFindings, not on the individual findings passed in)."""
    compact = []
    for f in findings:
        d = f.model_dump(mode="json")
        d["clause_text"] = d["clause_text"][:300]
        compact.append(d)
    return json.dumps(compact, separators=(",", ":"), ensure_ascii=False)


def _call_critic(findings: list[Finding], trace: QualityTrace) -> CriticResult:
    logger.info(
        "[QUALITY_LOOP] Sending request to Fusion CRITIC flow (flow_id=%s, session_id=%s, n_findings=%d)",
        trace.critic_flow_id,
        trace.request_id,
        len(findings),
    )
    result = trace.fusion_client.run_flow(
        trace.critic_flow_id,
        _compact_findings_json(findings),
        session_id=trace.request_id,
    )
    data = _parse_json(result["response_text"])
    critic = CriticResult.model_validate(data)
    logger.info(
        "[QUALITY_LOOP] Received CRITIC response (flow_id=%s, duration=%d ms): global_score=%s, verdict=%s, n_issues=%d",
        trace.critic_flow_id,
        result.get("duration_ms", 0),
        critic.global_score,
        critic.verdict,
        len(critic.issues),
    )
    return critic


def _call_refiner(
    findings: list[Finding], issues: list[CriticIssue], flagged_ids: set[str], trace: QualityTrace
) -> list[dict]:
    payload = {
        # Refiner needs the FULL clause_text (unlike the critic's compact view).
        "constats_a_corriger": [
            f.model_dump(mode="json") for f in findings if f.clause_id in flagged_ids
        ],
        "problemes": [i.model_dump(mode="json") for i in issues],
    }
    logger.info(
        "[QUALITY_LOOP] Sending request to Fusion REFINER flow (flow_id=%s, session_id=%s, n_flagged=%d, n_issues=%d)",
        trace.refiner_flow_id,
        trace.request_id,
        len(flagged_ids),
        len(issues),
    )
    result = trace.fusion_client.run_flow(
        trace.refiner_flow_id,
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        session_id=trace.request_id,
    )
    data = _parse_json(result["response_text"])
    refined = data.get("refined_findings", [])
    logger.info(
        "[QUALITY_LOOP] Received REFINER response (flow_id=%s, duration=%d ms): n_refined=%d",
        trace.refiner_flow_id,
        result.get("duration_ms", 0),
        len(refined) if isinstance(refined, list) else 0,
    )
    return refined if isinstance(refined, list) else []


def _merge_refined(
    findings: list[Finding], refined_raw: list[dict], trace: QualityTrace
) -> tuple[list[Finding], int]:
    """Validate each refined item against the Finding schema and require
    clause_id/reference/clause_text to be unchanged before accepting it.
    Anything that fails either check is skipped and the original is kept."""
    by_id = {f.clause_id: f for f in findings}
    merged_count = 0

    for item in refined_raw:
        clause_id = item.get("clause_id") if isinstance(item, dict) else None
        original = by_id.get(clause_id) if clause_id else None
        if original is None:
            trace.audit_fn(
                trace.refiner_flow_id,
                "skipped",
                "merge_skipped",
                f"reason=unknown_clause_id; clause_id={clause_id}",
            )
            continue
        try:
            candidate = Finding.model_validate(item)
        except ValidationError as exc:
            trace.audit_fn(
                trace.refiner_flow_id,
                "skipped",
                "merge_skipped",
                f"reason=invalid_schema; clause_id={clause_id}; {str(exc)[:150]}",
            )
            continue
        if (
            candidate.clause_id != original.clause_id
            or candidate.reference != original.reference
            or candidate.clause_text != original.clause_text
        ):
            trace.audit_fn(
                trace.refiner_flow_id,
                "skipped",
                "merge_skipped",
                f"reason=identity_mismatch; clause_id={clause_id}",
            )
            continue
        by_id[clause_id] = candidate
        merged_count += 1

    merged_findings = [by_id[f.clause_id] for f in findings]
    return merged_findings, merged_count


def run_quality_loop(findings: list[Finding], trace: QualityTrace) -> tuple[list[Finding], dict]:
    best_findings = findings
    best_score: Optional[float] = None
    criteria_scores: dict = {}
    iterations_run = 0
    issues_fixed_count = 0

    try:
        current = findings
        for i in range(trace.max_iterations):
            iterations_run = i + 1
            critic = _call_critic(current, trace)
            criteria_scores = critic.criteria_scores
            trace.audit_fn(
                trace.critic_flow_id,
                "ok",
                "critic_scored",
                f"score={critic.global_score}; verdict={critic.verdict}",
            )

            if best_score is None or critic.global_score > best_score:
                best_score = critic.global_score
                best_findings = current

            if critic.verdict == "pass" or critic.global_score >= trace.threshold:
                break
            if i == trace.max_iterations - 1:
                break

            flagged_ids = {issue.clause_id for issue in critic.issues}
            if not flagged_ids:
                break

            trace.audit_fn(
                trace.refiner_flow_id,
                "ok",
                "refiner_called",
                f"n_findings={len(flagged_ids)}",
            )
            refined_raw = _call_refiner(current, critic.issues, flagged_ids, trace)
            current, merged_count = _merge_refined(current, refined_raw, trace)
            issues_fixed_count += merged_count
            trace.audit_fn(
                trace.refiner_flow_id,
                "ok",
                "refined_merged",
                f"n={merged_count}",
            )
    except Exception as exc:
        logging.exception("Quality loop failed for contract %s", trace.contract_id)
        return best_findings, {
            "enabled": True,
            "score": best_score,
            "criteria_scores": criteria_scores,
            "iterations": iterations_run,
            "issues_fixed_count": issues_fixed_count,
            "error": str(exc)[:300],
            "quality_warning": True,
        }

    quality_warning = best_score is None or best_score < trace.threshold
    trace.audit_fn(
        trace.critic_flow_id,
        "ok",
        "quality_loop_done",
        f"score={best_score}; iterations={iterations_run}",
    )
    return best_findings, {
        "enabled": True,
        "score": best_score,
        "criteria_scores": criteria_scores,
        "iterations": iterations_run,
        "issues_fixed_count": issues_fixed_count,
        "quality_warning": quality_warning,
    }
