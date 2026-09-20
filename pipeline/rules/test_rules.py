import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from pipeline.rules import loader
from pipeline.rules.store import NoRulesetForDateError, RuleStore

REPO_ROOT = Path(__file__).resolve().parents[2]
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"


@pytest.fixture()
def store(tmp_path) -> RuleStore:
    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    s = RuleStore(db_path)
    yield s
    s.close()


def test_resolves_ruleset_on_effective_date(store: RuleStore):
    ruleset = store.resolve_ruleset(date(2026, 8, 3))
    assert ruleset.ruleset_id == "2026q3"
    assert ruleset.effective_to is None


def test_date_before_any_ruleset_raises(store: RuleStore):
    with pytest.raises(NoRulesetForDateError):
        store.resolve_ruleset(date(2020, 1, 1))


def test_every_ruleset_row_has_a_nonempty_source_note(store: RuleStore):
    ruleset = store.resolve_ruleset(date(2026, 8, 3))
    assert ruleset.source_note.strip() != ""


def test_mue_lookup(store: RuleStore):
    assert store.mue("2026q3", "88342") == 1
    assert store.mue("2026q3", "88341") == 13
    assert store.mue("2026q3", "unknown-code") is None


def test_ptp_edit_lookup_both_directions(store: RuleStore):
    # This ruleset ships no PTP pairs (see SOURCES.md); assert the lookup
    # path itself behaves correctly rather than asserting content that
    # doesn't exist yet.
    assert store.ptp_edit("2026q3", "88305", "88342") is None


def test_ptp_edit_lookup_finds_reverse_direction(tmp_path):
    db_path = tmp_path / "synthetic.db"
    conn = sqlite3.connect(db_path)
    loader.ensure_schema(conn)
    conn.execute(
        "INSERT INTO ruleset VALUES ('t1', '2026-01-01', NULL, 'test', 'hash')"
    )
    conn.execute(
        "INSERT INTO ptp_edit VALUES ('t1', 'AAAAA', 'BBBBB', 1)"
    )
    conn.commit()
    conn.close()
    with RuleStore(db_path) as s:
        edit = s.ptp_edit("t1", "BBBBB", "AAAAA")
        assert edit is not None
        assert edit.modifier_allowed == 1


def test_coverage_linkage(store: RuleStore):
    policies = store.coverage_policies_for_code("2026q3", "DEMO-MAC-J5", "88305")
    assert "DEMO-POLICY-SKIN-BX" in policies
    diagnoses = store.covered_diagnoses("2026q3", "DEMO-POLICY-SKIN-BX")
    assert "D22.9" in diagnoses
    assert "Z00.00" not in diagnoses


def test_substitution_lookup(store: RuleStore):
    sub = store.substitution("2026q3", "medicare", "88305")
    assert sub.to_code == "G0416"
    assert store.substitution("2026q3", "commercial", "88305") is None


def test_reloading_same_ruleset_dir_is_a_noop(tmp_path):
    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    loader.build_store(db_path, [RULESET_2026Q3])  # must not raise
    with RuleStore(db_path) as s:
        assert s.mue("2026q3", "88342") == 1


def test_mutating_a_loaded_ruleset_raises(tmp_path):
    db_path = tmp_path / "rules.db"
    scratch_ruleset = tmp_path / "2026q3-scratch"
    scratch_ruleset.mkdir()
    original = json.loads((RULESET_2026Q3 / "ruleset.json").read_text())
    (scratch_ruleset / "ruleset.json").write_text(json.dumps(original))

    loader.build_store(db_path, [scratch_ruleset])

    mutated = dict(original)
    mutated["mue"] = [*original["mue"], {"code": "99999", "max_units": 1, "adjudication_type": "date_of_service"}]
    (scratch_ruleset / "ruleset.json").write_text(json.dumps(mutated))

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(loader.RulesetConflictError):
            loader.load_ruleset_dir(conn, scratch_ruleset)
    finally:
        conn.close()


def test_no_cpt_descriptor_text_in_ruleset_json():
    raw = (RULESET_2026Q3 / "ruleset.json").read_text()
    assert "PLACEHOLDER" not in raw  # descriptors live only in cpt_descriptors.json
    descriptors = json.loads((RULESET_2026Q3 / "cpt_descriptors.json").read_text())
    for code, text in descriptors.items():
        if code == "_notice":
            continue
        assert "PLACEHOLDER" in text, f"{code} descriptor must stay a marked placeholder"
