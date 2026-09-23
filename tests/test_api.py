"""Tests for src/coding_agent/api/app.py: the local-only test console
backend. Sample-corpus endpoints run offline; the custom-input and
custom-PDF endpoints are tested for their parsing/validation paths and
their "no API key" guard, never against a live model."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from coding_agent.api.app import ACTIONS_DIR, app

client = TestClient(app)


def _pdf_bytes(lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        pdf.cell(0, 6, text=line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


REPORT_PDF_LINES = [
    "SYNTHETIC PATHOLOGY ASSOCIATES",
    "Accession #: S26-0099001",
    "CLINICAL HISTORY:",
    "Rash on bilateral upper extremities.",
    "GROSS DESCRIPTION:",
    "Received in formalin, two specimens labeled A and B.",
    "MICROSCOPIC DESCRIPTION:",
    "Sections show compound melanocytic proliferation.",
    "DIAGNOSIS:",
    "A. Skin, left forearm: compound nevus.",
    "B. Skin, right shoulder: compound nevus.",
]


@pytest.fixture(autouse=True)
def _clean_actions_dir():
    if ACTIONS_DIR.exists():
        shutil.rmtree(ACTIONS_DIR)
    yield
    if ACTIONS_DIR.exists():
        shutil.rmtree(ACTIONS_DIR)


def test_index_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "coding_agent" in resp.text


def test_list_cases_returns_the_eval_corpus():
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    case_ids = {c["case_id"] for c in resp.json()}
    assert "eval-agreement-001" in case_ids
    assert "eval-removal-001" in case_ids


def test_get_unknown_case_is_404():
    resp = client.get("/api/cases/does-not-exist")
    assert resp.status_code == 404


def test_get_case_returns_full_case_detail():
    resp = client.get("/api/cases/eval-agreement-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_code"] == "88305"
    assert body["case"]["specimens"]["value"]


def test_run_removal_case_flags_the_unmentioned_specimen():
    resp = client.post("/api/cases/eval-removal-001/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["actual_labels"] == ["A", "B"]
    removal_ids = {
        line["specimen_id"] for line in body["recommendation"]["lines"] if line["diff_kind"] == "removal"
    }
    assert removal_ids == {"C"}
    assert body["audited"]["version_stamp"]["rules_version"] == "units_v1"


def test_run_abstention_case_reports_blocked():
    resp = client.post("/api/cases/eval-abstain-no-narrative-001/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["abstained"] is True
    assert body["recommendation"]["blocked"] is not None


def test_record_and_list_actions_round_trip():
    resp = client.post(
        "/api/cases/eval-removal-001/actions",
        json={"line_index": 0, "action": "accepted"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "accepted"

    resp = client.get("/api/cases/eval-removal-001/actions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_record_action_without_reason_for_removed_is_rejected():
    resp = client.post(
        "/api/cases/eval-removal-001/actions",
        json={"line_index": 0, "action": "removed"},
    )
    assert resp.status_code == 422


def test_actions_scoped_per_case():
    client.post("/api/cases/eval-removal-001/actions", json={"line_index": 0, "action": "accepted"})
    resp = client.get("/api/cases/eval-agreement-001/actions")
    assert resp.json() == []


def test_custom_run_without_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/custom/run",
        json={"source_format": "hl7v2", "raw_text": "MSH|...", "primary_code": "88305"},
    )
    assert resp.status_code == 400
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_pdf_run_without_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/custom/pdf-run",
        files={"file": ("report.pdf", _pdf_bytes(REPORT_PDF_LINES), "application/pdf")},
        data={"accession_number": "S26-0099001", "date_of_service": "2026-01-20", "primary_code": "88305"},
    )
    assert resp.status_code == 400
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_pdf_run_rejects_bad_date_format(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-parsing-path-only-not-real")
    resp = client.post(
        "/api/custom/pdf-run",
        files={"file": ("report.pdf", _pdf_bytes(REPORT_PDF_LINES), "application/pdf")},
        data={"accession_number": "S26-0099001", "date_of_service": "not-a-date", "primary_code": "88305"},
    )
    assert resp.status_code == 422
    assert "date_of_service" in resp.json()["detail"]


def test_pdf_run_rejects_non_pdf_bytes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-parsing-path-only-not-real")
    resp = client.post(
        "/api/custom/pdf-run",
        files={"file": ("report.pdf", b"this is not a pdf at all", "application/pdf")},
        data={"accession_number": "S26-0099001", "date_of_service": "2026-01-20", "primary_code": "88305"},
    )
    assert resp.status_code == 422
    assert "could not read PDF" in resp.json()["detail"]


def test_pdf_run_rejects_text_with_no_recognized_sections(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-parsing-path-only-not-real")
    resp = client.post(
        "/api/custom/pdf-run",
        files={"file": ("report.pdf", _pdf_bytes(["just some unrelated text"]), "application/pdf")},
        data={"accession_number": "S26-0099001", "date_of_service": "2026-01-20", "primary_code": "88305"},
    )
    assert resp.status_code == 422
    assert "no recognized section" in resp.json()["detail"]
