from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pipeline.api.app as app_module
from pipeline.cli.run import run_case

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    decision_log = runs_root / "decision_log.jsonl"
    monkeypatch.setattr(app_module, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(app_module, "DECISION_LOG_PATH", decision_log)

    run_case(
        "case_03",
        fixtures_root=FIXTURES_ROOT,
        runs_root=runs_root,
        ruleset_dirs=[RULESET_2026Q3],
        rule_store_db=tmp_path / "rules.db",
    )
    return TestClient(app_module.app)


def _run_id(client) -> str:
    return client.get("/api/cases").json()[0]["run_id"]


def test_list_cases_returns_the_seeded_case(client):
    rows = client.get("/api/cases").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["case_id"] == "S26-0042110"
    assert row["finding_counts"]["review"] == 1
    assert row["decided"] is False


def test_get_recommendation_returns_case_codes_findings(client):
    run_id = _run_id(client)
    payload = client.get(f"/api/cases/S26-0042110/runs/{run_id}").json()
    assert payload["case"]["case_id"] == "S26-0042110"
    assert len(payload["codes"]["lines"]) == 3
    assert len(payload["findings"]) == 1


def test_get_recommendation_404_for_unknown_run(client):
    resp = client.get("/api/cases/S26-0042110/runs/nonexistent")
    assert resp.status_code == 404


def test_get_document_returns_text(client):
    run_id = _run_id(client)
    resp = client.get(f"/api/cases/S26-0042110/runs/{run_id}/documents/doc-report")
    assert resp.status_code == 200
    assert "shave biopsy" in resp.json()["text"]


def test_get_document_404_for_unknown_document(client):
    run_id = _run_id(client)
    resp = client.get(f"/api/cases/S26-0042110/runs/{run_id}/documents/nope")
    assert resp.status_code == 404


def test_record_accept_all_decision(client):
    run_id = _run_id(client)
    resp = client.post(
        f"/api/cases/S26-0042110/runs/{run_id}/decisions",
        json={"actor": "coder-1", "action": "accept_all"},
    )
    assert resp.status_code == 200
    entry = resp.json()
    assert entry["action"] == "accept_all"
    assert entry["ruleset_id"] == "2026q3"

    decisions = client.get(f"/api/cases/S26-0042110/runs/{run_id}/decisions").json()
    assert len(decisions) == 1


def test_remove_without_reason_code_is_rejected(client):
    run_id = _run_id(client)
    codes = client.get(f"/api/cases/S26-0042110/runs/{run_id}").json()["codes"]
    line_id = codes["lines"][0]["line_id"]
    resp = client.post(
        f"/api/cases/S26-0042110/runs/{run_id}/decisions",
        json={"actor": "coder-1", "action": "remove", "line_id": line_id},
    )
    assert resp.status_code == 422


def test_remove_with_reason_code_is_recorded(client):
    run_id = _run_id(client)
    codes = client.get(f"/api/cases/S26-0042110/runs/{run_id}").json()["codes"]
    line_id = codes["lines"][0]["line_id"]
    resp = client.post(
        f"/api/cases/S26-0042110/runs/{run_id}/decisions",
        json={"actor": "coder-1", "action": "remove", "line_id": line_id, "reason_code": "clinical_judgment"},
    )
    assert resp.status_code == 200
    assert resp.json()["reason_code"] == "clinical_judgment"


def test_remove_unknown_line_id_is_rejected(client):
    run_id = _run_id(client)
    resp = client.post(
        f"/api/cases/S26-0042110/runs/{run_id}/decisions",
        json={"actor": "coder-1", "action": "remove", "line_id": "not-a-real-line", "reason_code": "other"},
    )
    assert resp.status_code == 422


def test_decision_log_filterable_by_actor(client):
    run_id = _run_id(client)
    client.post(f"/api/cases/S26-0042110/runs/{run_id}/decisions", json={"actor": "coder-1", "action": "accept_all"})
    client.post(f"/api/cases/S26-0042110/runs/{run_id}/decisions", json={"actor": "coder-2", "action": "accept_all"})

    all_decisions = client.get("/api/decisions").json()
    assert len(all_decisions) == 2

    coder1_decisions = client.get("/api/decisions", params={"actor": "coder-1"}).json()
    assert len(coder1_decisions) == 1
    assert coder1_decisions[0]["actor"] == "coder-1"


def test_decision_log_is_append_only_on_disk(client):
    run_id = _run_id(client)
    client.post(f"/api/cases/S26-0042110/runs/{run_id}/decisions", json={"actor": "coder-1", "action": "accept_all"})
    log_path = app_module.DECISION_LOG_PATH
    contents_after_first = log_path.read_text()

    client.post(f"/api/cases/S26-0042110/runs/{run_id}/decisions", json={"actor": "coder-1", "action": "accept_all"})
    contents_after_second = log_path.read_text()

    assert contents_after_second.startswith(contents_after_first)
    assert contents_after_second != contents_after_first
