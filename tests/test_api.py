"""Tests for src/coding_agent/api/app.py: the local-only test console
backend. Sample-corpus endpoints run offline; the custom-input endpoint
is tested only for its "no API key" guard, not against a live model."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coding_agent.api.app import ACTIONS_DIR, app

client = TestClient(app)


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
