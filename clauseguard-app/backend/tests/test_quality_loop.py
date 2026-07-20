"""Unit tests for the A2A quality loop (PROMPT H)."""

import json

import pytest
from requests import Response
from requests.exceptions import HTTPError

from models.schemas import Finding
from services.quality_loop import QualityTrace, run_quality_loop

CRITIC_FLOW = "critic-flow"
REFINER_FLOW = "refiner-flow"


def _finding(clause_id="C-1", clause_text="Texte original de la clause.", **overrides):
    data = dict(
        clause_id=clause_id,
        reference=f"Article {clause_id}",
        clause_text=clause_text,
        type="standard",
        original_risk_level="ORANGE",
        audit_decision="requires_human_check",
        audit_reason="motif",
        corrected_risk_level="UNKNOWN",
        risk_summary="resume",
        source_excerpts=[],
        proposed_rewrite=None,
        human_review_required=True,
    )
    data.update(overrides)
    return Finding.model_validate(data)


class FakeFusionClient:
    """Records calls and dispatches to a per-flow_id queue of canned
    responses (or a callable) so each test controls exactly what each call
    returns, including raising exceptions."""

    def __init__(self, responses: dict):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str]] = []

    def run_flow(self, flow_id, message, session_id=None, retry_on_5xx=True):
        self.calls.append((flow_id, message))
        queue = self.responses.get(flow_id, [])
        if not queue:
            raise AssertionError(f"No canned response left for flow {flow_id}")
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"response_text": outcome, "status_code": 200, "duration_ms": 42}


def _critic_response(score, verdict, issues=None):
    return json.dumps(
        {
            "global_score": score,
            "criteria_scores": {"clarity": score, "coverage": score},
            "verdict": verdict,
            "issues": issues or [],
        }
    )


def _refiner_response(findings):
    return json.dumps({"refined_findings": findings})


def _make_trace(fusion_client, audit_log, threshold=0.75, max_iterations=2):
    return QualityTrace(
        contract_id="cid-1",
        request_id="req-1",
        fusion_client=fusion_client,
        audit_fn=lambda flow_id, status, action, detail: audit_log.append(
            (flow_id, status, action, detail)
        ),
        critic_flow_id=CRITIC_FLOW,
        refiner_flow_id=REFINER_FLOW,
        threshold=threshold,
        max_iterations=max_iterations,
    )


def test_pass_first_try_one_critic_call_zero_refiner():
    findings = [_finding()]
    client = FakeFusionClient({CRITIC_FLOW: [_critic_response(0.9, "pass")]})
    audit_log = []
    trace = _make_trace(client, audit_log)

    result, quality = run_quality_loop(findings, trace)

    assert [f.clause_id for f in result] == ["C-1"]
    assert result[0].clause_text == findings[0].clause_text
    assert quality["score"] == 0.9
    assert quality["iterations"] == 1
    assert quality["quality_warning"] is False
    critic_calls = [c for c in client.calls if c[0] == CRITIC_FLOW]
    refiner_calls = [c for c in client.calls if c[0] == REFINER_FLOW]
    assert len(critic_calls) == 1
    assert len(refiner_calls) == 0
    assert any(a == "critic_scored" for _, _, a, _ in audit_log)
    assert any(a == "quality_loop_done" for _, _, a, _ in audit_log)


def test_fail_then_pass_merges_only_flagged_ids():
    findings = [_finding("C-1", "Texte 1"), _finding("C-2", "Texte 2")]
    refined_c1 = {
        **findings[0].model_dump(mode="json"),
        "risk_summary": "resume corrige",
        "audit_reason": "motif corrige",
    }
    client = FakeFusionClient(
        {
            CRITIC_FLOW: [
                _critic_response(0.5, "fail", issues=[{"clause_id": "C-1", "problem": "vague"}]),
                _critic_response(0.85, "pass"),
            ],
            REFINER_FLOW: [_refiner_response([refined_c1])],
        }
    )
    audit_log = []
    trace = _make_trace(client, audit_log)

    result, quality = run_quality_loop(findings, trace)

    by_id = {f.clause_id: f for f in result}
    assert by_id["C-1"].risk_summary == "resume corrige"
    assert by_id["C-1"].clause_text == "Texte 1"  # identity fields unchanged
    # C-2 was never flagged: byte-identical to the original.
    assert by_id["C-2"].model_dump(mode="json") == findings[1].model_dump(mode="json")

    assert quality["score"] == 0.85
    assert quality["iterations"] == 2
    assert quality["issues_fixed_count"] == 1
    assert quality["quality_warning"] is False

    critic_calls = [c for c in client.calls if c[0] == CRITIC_FLOW]
    refiner_calls = [c for c in client.calls if c[0] == REFINER_FLOW]
    assert len(critic_calls) == 2
    assert len(refiner_calls) == 1
    assert any(a == "refined_merged" for _, _, a, _ in audit_log)


def test_fail_twice_keeps_best_version_and_warns():
    findings = [_finding("C-1", "Texte 1")]
    worse_c1 = {**findings[0].model_dump(mode="json"), "risk_summary": "pire"}
    client = FakeFusionClient(
        {
            CRITIC_FLOW: [
                _critic_response(0.6, "fail", issues=[{"clause_id": "C-1", "problem": "x"}]),
                _critic_response(0.4, "fail", issues=[{"clause_id": "C-1", "problem": "y"}]),
            ],
            REFINER_FLOW: [_refiner_response([worse_c1])],
        }
    )
    audit_log = []
    trace = _make_trace(client, audit_log, max_iterations=2)

    result, quality = run_quality_loop(findings, trace)

    # Best score (0.6, iteration 1) beats the post-refine score (0.4), so the
    # ORIGINAL (pre-refine) findings must be what's returned.
    assert result[0].risk_summary == "resume"
    assert quality["score"] == 0.6
    assert quality["iterations"] == 2
    assert quality["quality_warning"] is True

    critic_calls = [c for c in client.calls if c[0] == CRITIC_FLOW]
    refiner_calls = [c for c in client.calls if c[0] == REFINER_FLOW]
    assert len(critic_calls) == 2
    # Last iteration is never refined (nothing left to re-evaluate it).
    assert len(refiner_calls) == 1


def test_refiner_corrupted_clause_id_merge_skipped_original_kept():
    findings = [_finding("C-1", "Texte 1")]
    corrupted = {**findings[0].model_dump(mode="json"), "clause_id": "C-999"}
    client = FakeFusionClient(
        {
            CRITIC_FLOW: [
                _critic_response(0.5, "fail", issues=[{"clause_id": "C-1", "problem": "x"}]),
                _critic_response(0.5, "fail", issues=[{"clause_id": "C-1", "problem": "x"}]),
            ],
            REFINER_FLOW: [_refiner_response([corrupted])],
        }
    )
    audit_log = []
    trace = _make_trace(client, audit_log, max_iterations=2)

    result, quality = run_quality_loop(findings, trace)

    assert result[0].model_dump(mode="json") == findings[0].model_dump(mode="json")
    assert quality["issues_fixed_count"] == 0
    assert any(a == "merge_skipped" for _, _, a, _ in audit_log)


def test_refiner_identity_mismatch_merge_skipped():
    findings = [_finding("C-1", "Texte original")]
    tampered = {**findings[0].model_dump(mode="json"), "clause_text": "Texte modifie par erreur"}
    client = FakeFusionClient(
        {
            CRITIC_FLOW: [
                _critic_response(0.5, "fail", issues=[{"clause_id": "C-1", "problem": "x"}]),
                _critic_response(0.5, "fail", issues=[{"clause_id": "C-1", "problem": "x"}]),
            ],
            REFINER_FLOW: [_refiner_response([tampered])],
        }
    )
    audit_log = []
    trace = _make_trace(client, audit_log, max_iterations=2)

    result, _quality = run_quality_loop(findings, trace)

    assert result[0].clause_text == "Texte original"
    assert any(a == "merge_skipped" for _, _, a, _ in audit_log)


def test_critic_flow_500_returns_quality_error_never_raises():
    findings = [_finding("C-1")]
    response = Response()
    response.status_code = 500
    client = FakeFusionClient({CRITIC_FLOW: [HTTPError("500 Server Error", response=response)]})
    audit_log = []
    trace = _make_trace(client, audit_log)

    result, quality = run_quality_loop(findings, trace)

    assert result[0].model_dump(mode="json") == findings[0].model_dump(mode="json")
    assert quality["enabled"] is True
    assert quality["quality_warning"] is True
    assert "error" in quality
