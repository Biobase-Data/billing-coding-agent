"""Case 15: an amended report re-run and diffed against the original.

Exercises every layer: adapter (two source directories sharing one
case_id), extraction (hand facts standing in), the mapper and validator
(different diagnosis, different findings), the run manifest (proving the
rule version did *not* change even though the diagnosis did -- the
amendment didn't cross a ruleset boundary), and the diff tool itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.cli.run import run_case
from pipeline.eval.diff import diff_runs

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"


@pytest.fixture()
def two_runs(tmp_path):
    runs_root = tmp_path / "runs"
    common_kwargs = dict(
        fixtures_root=FIXTURES_ROOT,
        runs_root=runs_root,
        ruleset_dirs=[RULESET_2026Q3],
        rule_store_db=tmp_path / "rules.db",
    )
    run_a_dir = run_case("case_15_initial", **common_kwargs)
    run_b_dir = run_case("case_15_amended", **common_kwargs)
    return run_a_dir, run_b_dir


def test_amendment_shares_one_case_id(two_runs):
    run_a_dir, run_b_dir = two_runs
    assert run_a_dir.parent == run_b_dir.parent  # same runs/<case_id>/ directory
    assert run_a_dir.parent.name == "S26-0042900"


def test_rule_version_unchanged_across_the_amendment(two_runs):
    """date_of_service is the same accession date in both reports -- the
    amendment must not silently pick up a different ruleset."""
    run_a_dir, run_b_dir = two_runs
    diff = diff_runs(run_a_dir, run_b_dir)
    assert "ruleset_id" not in diff.manifest_changes
    assert "ruleset_content_hash" not in diff.manifest_changes


def test_diagnosis_line_changes_from_compound_nevus_to_atypical(two_runs):
    run_a_dir, run_b_dir = two_runs
    diff = diff_runs(run_a_dir, run_b_dir)

    removed_codes = {l["code"] for l in diff.lines.removed}
    added_codes = {l["code"] for l in diff.lines.added}
    assert removed_codes == {"D22.5"}  # compound nevus, skin/upper back -> trunk
    assert added_codes == {"D48.5"}
    assert diff.lines.changed == []  # the level code (88305) is identical in both


def test_new_findings_surface_on_the_amendment(two_runs):
    run_a_dir, run_b_dir = two_runs
    diff = diff_runs(run_a_dir, run_b_dir)

    added_rule_ids = {f["rule_id"] for f in diff.findings.added}
    assert added_rule_ids == {"coverage:DEMO-POLICY-88305", "diagnosis:qualified_certainty"}
    assert diff.findings.removed == []


def test_diffing_runs_from_different_cases_raises(tmp_path):
    runs_root = tmp_path / "runs"
    common_kwargs = dict(
        fixtures_root=FIXTURES_ROOT,
        runs_root=runs_root,
        ruleset_dirs=[RULESET_2026Q3],
        rule_store_db=tmp_path / "rules.db",
    )
    run_a_dir = run_case("case_01", **common_kwargs)
    run_b_dir = run_case("case_15_initial", **common_kwargs)
    with pytest.raises(ValueError):
        diff_runs(run_a_dir, run_b_dir)
