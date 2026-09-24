import json
from pathlib import Path

from pipeline.cli.run import run_case
from pipeline.extract.runner import ExtractionMetrics

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"


def test_run_case_hand_facts_produces_all_artifacts(tmp_path):
    runs_root = tmp_path / "runs"
    run_dir = run_case(
        "case_01",
        fixtures_root=FIXTURES_ROOT,
        runs_root=runs_root,
        ruleset_dirs=[RULESET_2026Q3],
        rule_store_db=tmp_path / "rules.db",
    )
    for name in ("case.json", "facts.json", "codes.json", "findings.json", "recommendation.json", "manifest.json"):
        assert (run_dir / name).exists(), name

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["ruleset_id"] == "2026q3"
    assert manifest["model_id"] is None
    assert manifest["stages_completed"] == ["adapter", "extract", "map", "validate"]

    codes = json.loads((run_dir / "codes.json").read_text())
    assert any(line["code"] == "88305" for line in codes["lines"])


def test_run_case_extract_facts_source_uses_the_runner(tmp_path, monkeypatch):
    called = {}

    def fake_extract_facts(case, model):
        called["model"] = model
        from pipeline.extract.hand_facts import load_hand_facts

        facts = load_hand_facts(FIXTURES_ROOT / "case_01", case)
        return facts, {"specimen": ExtractionMetrics(wall_time_seconds=0.1, input_tokens=10, output_tokens=5)}, {"specimen": "v1"}

    import pipeline.cli.run as run_module

    monkeypatch.setattr(run_module.extract_runner, "extract_facts", fake_extract_facts)

    run_dir = run_case(
        "case_01",
        fixtures_root=FIXTURES_ROOT,
        runs_root=tmp_path / "runs",
        ruleset_dirs=[RULESET_2026Q3],
        rule_store_db=tmp_path / "rules.db",
        facts_source="extract",
        model="claude-sonnet-5",
    )
    assert called["model"] == "claude-sonnet-5"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["model_id"] == "claude-sonnet-5"
    assert manifest["prompt_versions"]["specimen"] == "v1"
