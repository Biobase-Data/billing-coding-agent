"""FastAPI app backing the local test UI. Two ways to exercise the
pipeline:

- Sample corpus (`GET/POST /api/cases*`): the eval/cases/ fixtures,
  replayed through the real parsing/reconciliation code path with no
  API key required -- see eval/harness.py's ReplayClient.
- Custom input (`POST /api/custom/run`): paste raw HL7v2 or FHIR text
  and run it through a live model call. Requires ANTHROPIC_API_KEY.

Coder actions (accept/edit/remove) recorded against a sample case are
appended to `runs/coding_agent_actions/<case_id>.jsonl` -- gitignored,
local scratch state, not a production audit store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from coding_agent.audit.log import ActionLog, CoderAction, record_action
from coding_agent.audit.stamp import stamp
from coding_agent.extract.specimens import AnthropicClient, extract_specimen_mentions
from coding_agent.normalize.case import Case
from coding_agent.normalize.fhir import FhirNormalizationError, parse_bundle
from coding_agent.normalize.hl7v2 import Hl7NormalizationError, parse_oru
from coding_agent.recommend.assemble import build_recommendation
from coding_agent.rules.units import RULES_VERSION
from eval.harness import load_corpus, run_eval_case

STATIC_DIR = Path(__file__).with_name("static")
ACTIONS_DIR = Path(__file__).resolve().parents[3] / "runs" / "coding_agent_actions"

app = FastAPI(title="coding_agent V0 test console")


def _action_log(case_id: str) -> ActionLog:
    return ActionLog(ACTIONS_DIR / f"{case_id}.jsonl")


def _dump(model: BaseModel) -> Any:
    return model.model_dump(mode="json")


@app.get("/api/cases")
def list_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": eval_case.case_id,
            "source_format": eval_case.case.source_format.value,
            "primary_code": eval_case.primary_code,
            "expected_labels": (
                sorted(eval_case.expected_labels) if eval_case.expected_labels is not None else None
            ),
        }
        for eval_case in load_corpus()
    ]


def _find_eval_case(case_id: str):
    for eval_case in load_corpus():
        if eval_case.case_id == case_id:
            return eval_case
    raise HTTPException(status_code=404, detail=f"no sample case {case_id!r}")


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    eval_case = _find_eval_case(case_id)
    return {
        "case_id": eval_case.case_id,
        "primary_code": eval_case.primary_code,
        "expected_labels": (
            sorted(eval_case.expected_labels) if eval_case.expected_labels is not None else None
        ),
        "case": _dump(eval_case.case),
    }


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str) -> dict[str, Any]:
    eval_case = _find_eval_case(case_id)
    result = run_eval_case(eval_case)
    return {
        "case_id": result.case_id,
        "expected_labels": sorted(result.expected_labels) if result.expected_labels is not None else None,
        "actual_labels": sorted(result.actual_labels) if result.actual_labels is not None else None,
        "abstained": result.abstained,
        "recommendation": _dump(result.recommendation),
        "audited": _dump(result.audited),
    }


class ActionRequest(BaseModel):
    line_index: int
    action: Literal["accepted", "edited", "removed"]
    reason: str | None = None


@app.get("/api/cases/{case_id}/actions")
def list_actions(case_id: str) -> list[dict[str, Any]]:
    _find_eval_case(case_id)
    return [_dump(record) for record in _action_log(case_id).read_all()]


@app.post("/api/cases/{case_id}/actions")
def create_action(case_id: str, body: ActionRequest) -> dict[str, Any]:
    _find_eval_case(case_id)
    try:
        record = record_action(
            _action_log(case_id),
            case_id=case_id,
            line_index=body.line_index,
            action=CoderAction(body.action),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _dump(record)


class CustomRunRequest(BaseModel):
    source_format: Literal["hl7v2", "fhir_r4"]
    raw_text: str
    primary_code: str


@app.post("/api/custom/run")
def run_custom(body: CustomRunRequest) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY is not set -- custom input requires a live model call. "
            "Try a sample case instead, which runs offline.",
        )

    try:
        case: Case = (
            parse_oru(body.raw_text)
            if body.source_format == "hl7v2"
            else parse_bundle(json.loads(body.raw_text))
        )
    except (Hl7NormalizationError, FhirNormalizationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"could not normalize input: {exc}") from exc

    extraction, _metrics = extract_specimen_mentions(case, client=AnthropicClient())
    recommendation = build_recommendation(case, extraction, baseline=(), primary_code=body.primary_code)
    audited = stamp(
        recommendation,
        extraction_metadata=extraction.metadata,
        rules_version=RULES_VERSION,
        date_of_service=case.date_of_service,
    )
    actual_labels = (
        None if extraction.abstained else sorted(m.label for m in extraction.mentions)
    )
    return {
        "case_id": case.case_id,
        "actual_labels": actual_labels,
        "abstained": extraction.abstained,
        "case": _dump(case),
        "recommendation": _dump(recommendation),
        "audited": _dump(audited),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
