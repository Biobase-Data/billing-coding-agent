"""FastAPI app backing the local test UI. Three ways to exercise the
pipeline:

- Sample corpus (`GET/POST /api/cases*`): the eval/cases/ fixtures,
  replayed through the real parsing/reconciliation code path with no
  API key required -- see eval/harness.py's ReplayClient.
- Custom HL7v2/FHIR input (`POST /api/custom/run`): paste raw text and
  run it through a live model call.
- Custom PDF report (`POST /api/custom/pdf-run`): upload a signed-out
  report PDF; text is extracted and section-split by
  normalize/free_text.py. Specimens always come back Absent here (a
  bare report has no structured accessioning specimen list), so
  reconciliation is expected to report Blocked -- see that module's
  docstring.

Both custom-input endpoints need a live model call, picked by
`_resolve_live_client()` from whichever provider has a key set in the
server's environment (`ANTHROPIC_API_KEY`, the free-tier `GROQ_API_KEY`,
or `XAI_API_KEY` for xAI's Grok -- see extract/specimens.py's
`ModelClient` Protocol, deliberately provider-agnostic).

Coder actions (accept/edit/remove) recorded against a sample case are
appended to `runs/coding_agent_actions/<case_id>.jsonl` -- gitignored,
local scratch state, not a production audit store.
"""

from __future__ import annotations

import json
import os
from datetime import date as date_cls
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import anthropic
import pypdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from coding_agent.audit.log import ActionLog, CoderAction, record_action
from coding_agent.audit.stamp import stamp
from coding_agent.extract.specimens import (
    DEFAULT_MODEL,
    GROK_DEFAULT_MODEL,
    GROQ_DEFAULT_MODEL,
    AnthropicClient,
    GrokClient,
    GroqClient,
    ModelClient,
    ModelRequestError,
    extract_specimen_mentions,
)
from coding_agent.normalize.case import Case
from coding_agent.normalize.fhir import FhirNormalizationError, parse_bundle
from coding_agent.normalize.free_text import FreeTextNormalizationError, parse_report_text
from coding_agent.normalize.hl7v2 import Hl7NormalizationError, parse_oru
from coding_agent.recommend.assemble import build_recommendation
from coding_agent.rules.units import RULES_VERSION
from eval.harness import load_corpus, run_eval_case

STATIC_DIR = Path(__file__).with_name("static")
ACTIONS_DIR = Path(__file__).resolve().parents[3] / "runs" / "coding_agent_actions"

_NO_API_KEY_DETAIL = (
    "No live model backend configured -- set ANTHROPIC_API_KEY, GROQ_API_KEY "
    "for a free-tier alternative (console.groq.com), or XAI_API_KEY for xAI's "
    "Grok, in the environment the server runs in. Try a sample case instead, "
    "which runs offline."
)

app = FastAPI(title="coding_agent V0 test console")


def _resolve_live_client() -> tuple[ModelClient, str]:
    """Pick a live ModelClient from whichever provider has a key set in
    the server's environment, checked in this order: Anthropic (this
    project's default model), then Groq's free tier, then xAI's Grok.
    Raises HTTPException(400) if none is configured.

    Each provider's model name can be overridden with its own env var
    (`ANTHROPIC_MODEL` / `GROQ_MODEL` / `XAI_MODEL`) rather than only a
    code change -- Groq's and xAI's catalogs in particular change fast
    enough that a hardcoded default has already gone stale once during
    this project's own testing (see ASSUMPTIONS.md).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient(), os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    if os.environ.get("GROQ_API_KEY"):
        return GroqClient(), os.environ.get("GROQ_MODEL", GROQ_DEFAULT_MODEL)
    if os.environ.get("XAI_API_KEY"):
        return GrokClient(), os.environ.get("XAI_MODEL", GROK_DEFAULT_MODEL)
    raise HTTPException(status_code=400, detail=_NO_API_KEY_DETAIL)


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


def _run_live_pipeline(
    case: Case, primary_code: str, client: ModelClient, model: str
) -> dict[str, Any]:
    """Shared tail of both custom-input endpoints: live extraction ->
    bidirectional recommendation -> version stamp -> response dict."""
    try:
        extraction, _metrics = extract_specimen_mentions(case, client=client, model=model)
    except ModelRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except anthropic.APIError as exc:
        # AnthropicClient doesn't wrap the SDK's own exceptions the way
        # GroqClient/GrokClient wrap urllib's -- catch its actual base
        # class here instead of letting a credit-balance/rate-limit/auth
        # failure surface as a bare 500 with no readable detail.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    recommendation = build_recommendation(case, extraction, baseline=(), primary_code=primary_code)
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


@app.post("/api/custom/run")
def run_custom(body: CustomRunRequest) -> dict[str, Any]:
    client, model = _resolve_live_client()

    try:
        case: Case = (
            parse_oru(body.raw_text)
            if body.source_format == "hl7v2"
            else parse_bundle(json.loads(body.raw_text))
        )
    except (Hl7NormalizationError, FhirNormalizationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"could not normalize input: {exc}") from exc

    return _run_live_pipeline(case, body.primary_code, client, model)


def _extract_pdf_text(data: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@app.post("/api/custom/pdf-run")
async def run_custom_pdf(
    file: UploadFile = File(...),
    accession_number: str = Form(...),
    date_of_service: str = Form(...),
    primary_code: str = Form(...),
) -> dict[str, Any]:
    client, model = _resolve_live_client()

    try:
        service_date = date_cls.fromisoformat(date_of_service)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"date_of_service must be YYYY-MM-DD: {exc}"
        ) from exc

    pdf_bytes = await file.read()
    try:
        raw_text = _extract_pdf_text(pdf_bytes)
    except pypdf.errors.PyPdfError as exc:
        raise HTTPException(status_code=422, detail=f"could not read PDF: {exc}") from exc

    try:
        case = parse_report_text(
            raw_text,
            case_id=accession_number,
            accession_number=accession_number,
            date_of_service=service_date,
        )
    except FreeTextNormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _run_live_pipeline(case, primary_code, client, model)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
