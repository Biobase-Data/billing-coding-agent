"""CLI entry point: run the full corpus, score it, write the eval report.

    python -m pipeline.cli.eval [--report-path runs/eval_report.txt]

Exits non-zero if any case has a missed, spurious, or wrong-units/
modifiers line, or a missed/false-alarm finding -- this repo's fixtures
are ground truth we authored ourselves, so a discrepancy here means the
code regressed against what we already believed, exactly what
pipeline/eval/test_golden.py also asserts via pytest. This CLI exists
for CI to produce the human-readable report artifact alongside that gate,
per the build spec: the evaluator "runs in CI, not just by hand."
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pipeline.adapters import fixture as fixture_adapter
from pipeline.eval.report import build_report
from pipeline.eval.scorer import CaseScore, score_case
from pipeline.extract.hand_facts import load_hand_facts
from pipeline.map.mapper import map_codes
from pipeline.rules import loader as rules_loader
from pipeline.rules.materialize import load_mapping_data, load_validation_data
from pipeline.rules.store import RuleStore
from pipeline.validate.validator import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
GOLDEN_ROOT = REPO_ROOT / "fixtures" / "golden"
RULESET_DIRS = [REPO_ROOT / "rulesets" / "2026q3"]
DEFAULT_RULE_STORE_DB = REPO_ROOT / "runs" / ".rules_cache.db"
DEFAULT_REPORT_PATH = REPO_ROOT / "runs" / "eval_report.txt"


def _golden_case_ids() -> list[str]:
    return sorted(p.name for p in GOLDEN_ROOT.iterdir() if (p / "golden.json").exists())


def run_corpus(rule_store_db: Path = DEFAULT_RULE_STORE_DB) -> list[CaseScore]:
    rule_store_db.parent.mkdir(parents=True, exist_ok=True)
    rules_loader.build_store(rule_store_db, RULESET_DIRS)
    case_scores = []
    with RuleStore(rule_store_db) as store:
        for case_id in _golden_case_ids():
            case_dir = FIXTURES_ROOT / case_id
            golden = json.loads((GOLDEN_ROOT / case_id / "golden.json").read_text())

            case = fixture_adapter.load_case(case_dir)
            facts = load_hand_facts(case_dir, case)
            ruleset = store.resolve_ruleset(case.date_of_service)
            mapping_data = load_mapping_data(store, ruleset.ruleset_id)
            validation_data = load_validation_data(store, ruleset.ruleset_id)
            codes = map_codes(facts, case, ruleset, mapping_data)
            findings = validate(codes, case, facts, validation_data)

            case_scores.append(score_case(case_id, codes, findings, golden))
    return case_scores


def has_any_discrepancy(case_scores: list[CaseScore]) -> bool:
    return any(
        cs.lines.missed or cs.lines.spurious or cs.lines.wrong_units_or_modifiers
        or cs.findings.missed or cs.findings.false_alarm
        for cs in case_scores
    )


@click.command()
@click.option("--report-path", type=click.Path(path_type=Path), default=DEFAULT_REPORT_PATH, show_default=True)
def main(report_path: Path) -> None:
    case_scores = run_corpus()
    report_text = build_report(case_scores)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text)
    click.echo(report_text)
    click.echo(f"wrote report to {report_path}")
    if has_any_discrepancy(case_scores):
        sys.exit(1)


if __name__ == "__main__":
    main()
