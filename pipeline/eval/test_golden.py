"""Golden tests across the corpus.

A diff against a golden file fails the build and prints the diff.
Updating a golden file is a deliberate act that shows up in code review,
never an automatic fixup -- so this test only reads golden.json, it never
writes one.

Every golden file in this repo is marked ``"unreviewed": true`` until an
AP coder signs off (ASSUMPTIONS.md); this test enforces the code matches
what we currently believe, not that the belief itself is correct.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.hand_facts import load_hand_facts
from pipeline.map.mapper import map_codes
from pipeline.rules import loader
from pipeline.rules.materialize import load_mapping_data, load_validation_data
from pipeline.rules.store import RuleStore
from pipeline.validate.validator import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
GOLDEN_ROOT = REPO_ROOT / "fixtures" / "golden"
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"


def _golden_case_ids() -> list[str]:
    return sorted(p.name for p in GOLDEN_ROOT.iterdir() if (p / "golden.json").exists())


def _line_key(line: dict) -> tuple:
    return (line["code"], line["code_system"], line["units"], tuple(sorted(line["modifiers"])), line["specimen_id"])


@pytest.fixture()
def store(tmp_path):
    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    s = RuleStore(db_path)
    yield s
    s.close()


@pytest.mark.parametrize("case_id", _golden_case_ids())
def test_golden(store, case_id):
    case_dir = FIXTURES_ROOT / case_id
    golden = json.loads((GOLDEN_ROOT / case_id / "golden.json").read_text())

    case = fixture_adapter.load_case(case_dir)
    facts = load_hand_facts(case_dir, case)
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    validation_data = load_validation_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)
    findings = validate(codes, case, facts, validation_data)

    actual_lines = {_line_key(line.model_dump(mode="json")) for line in codes.lines}
    expected_lines = {_line_key(line) for line in golden["expected_lines"]}
    missed = expected_lines - actual_lines
    spurious = actual_lines - expected_lines
    assert not missed and not spurious, (
        f"{case_id}: golden mismatch\n  missed:   {sorted(missed)}\n  spurious: {sorted(spurious)}"
    )

    actual_finding_ids = {(f.rule_id, f.severity.value) for f in findings}
    expected_finding_ids = {(f["rule_id"], f["severity"]) for f in golden["expected_findings"]}
    assert actual_finding_ids == expected_finding_ids, (
        f"{case_id}: finding mismatch\n  expected: {sorted(expected_finding_ids)}\n  actual:   {sorted(actual_finding_ids)}"
    )


def test_at_least_one_golden_case_exists():
    assert _golden_case_ids()
