"""The review API: serves the assembled recommendation, records coder
decisions with reason codes, writes an append-only decision log.

Reads whatever run directories `pipeline.cli.run` has already written
under `runs/<case_id>/<run_id>/`. This service does not run the pipeline
itself -- it is a read/decide layer on top of run artifacts that already
exist, exactly like the architecture diagram's stage boundary implies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pipeline.api.decision_log import append, read_all
from pipeline.api.models import DecisionLogEntry, DecisionRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "runs"
DECISION_LOG_PATH = RUNS_ROOT / "decision_log.jsonl"

app = FastAPI(title="Billing Coding Agent -- Review API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo only -- see ASSUMPTIONS.md, no auth/multi-tenancy posture yet
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_dir(case_id: str, run_id: str) -> Path:
    d = RUNS_ROOT / case_id / run_id
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"no run {run_id!r} for case {case_id!r}")
    return d


def _read_json(path: Path):
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} not found in this run")
    return json.loads(path.read_text())


def _latest_run_id(case_dir: Path) -> str | None:
    run_dirs = [p for p in case_dir.iterdir() if p.is_dir()]
    if not run_dirs:
        return None
    return sorted(run_dirs, key=lambda p: p.name)[-1].name


@app.get("/api/cases")
def list_cases():
    """The queue: one row per case, its most recent run's finding counts."""
    if not RUNS_ROOT.exists():
        return []
    rows = []
    for case_dir in sorted(RUNS_ROOT.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        run_id = _latest_run_id(case_dir)
        if run_id is None:
            continue
        run_dir = case_dir / run_id
        case = _read_json(run_dir / "case.json")
        findings = _read_json(run_dir / "findings.json")
        decisions = [d for d in read_all(DECISION_LOG_PATH) if d.case_id == case["case_id"] and d.run_id == run_id]
        severity_counts = {"blocker": 0, "review": 0, "informational": 0}
        for f in findings:
            severity_counts[f["severity"]] += 1
        rows.append(
            {
                "case_id": case["case_id"],
                "run_id": run_id,
                "date_of_service": case["date_of_service"],
                "subspecialty": case["subspecialty"],
                "specimen_count": len(case["specimens"]),
                "finding_counts": severity_counts,
                "decided": len(decisions) > 0,
            }
        )
    return rows


@app.get("/api/cases/{case_id}/runs/{run_id}")
def get_recommendation(case_id: str, run_id: str):
    """The case review screen's payload: case, codes, findings, documents."""
    run_dir = _run_dir(case_id, run_id)
    return {
        "case": _read_json(run_dir / "case.json"),
        "codes": _read_json(run_dir / "codes.json"),
        "findings": _read_json(run_dir / "findings.json"),
        "facts": _read_json(run_dir / "facts.json"),
        "manifest": _read_json(run_dir / "manifest.json"),
    }


@app.get("/api/cases/{case_id}/runs/{run_id}/documents/{document_id}")
def get_document(case_id: str, run_id: str, document_id: str):
    """A single document's text, for the evidence panel."""
    run_dir = _run_dir(case_id, run_id)
    case = _read_json(run_dir / "case.json")
    for doc in case["documents"]:
        if doc["document_id"] == document_id:
            return doc
    raise HTTPException(status_code=404, detail=f"no document {document_id!r} on this case")


@app.get("/api/cases/{case_id}/runs/{run_id}/decisions")
def list_run_decisions(case_id: str, run_id: str):
    _run_dir(case_id, run_id)  # 404s if the run doesn't exist
    return [
        d.model_dump(mode="json")
        for d in read_all(DECISION_LOG_PATH)
        if d.case_id == case_id and d.run_id == run_id
    ]


@app.get("/api/decisions")
def list_decisions(actor: str | None = None, case_id: str | None = None):
    """The decision log screen: append-only, filterable by actor."""
    entries = read_all(DECISION_LOG_PATH)
    if actor is not None:
        entries = [e for e in entries if e.actor == actor]
    if case_id is not None:
        entries = [e for e in entries if e.case_id == case_id]
    return [e.model_dump(mode="json") for e in entries]


@app.post("/api/cases/{case_id}/runs/{run_id}/decisions")
def record_decision(case_id: str, run_id: str, decision: DecisionRequest):
    run_dir = _run_dir(case_id, run_id)
    manifest = _read_json(run_dir / "manifest.json")

    if decision.line_id is not None:
        codes = _read_json(run_dir / "codes.json")
        line_ids = {line["line_id"] for line in codes["lines"]}
        if decision.line_id not in line_ids:
            raise HTTPException(status_code=422, detail=f"no line {decision.line_id!r} in this run's code set")

    entry = DecisionLogEntry(
        timestamp=datetime.now(timezone.utc),
        case_id=case_id,
        run_id=run_id,
        ruleset_id=manifest["ruleset_id"],
        actor=decision.actor,
        action=decision.action,
        line_id=decision.line_id,
        reason_code=decision.reason_code,
        edit=decision.edit,
        note=decision.note,
    )
    append(DECISION_LOG_PATH, entry)
    return entry.model_dump(mode="json")
