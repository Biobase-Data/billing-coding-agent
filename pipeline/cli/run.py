"""CLI entry point: run.py --case <id> produces a full run directory.

Works from Phase 1 onward. Each phase has added another artifact to the
run directory without changing how earlier artifacts are produced:

  Phase 1: case.json          (adapter)
  Phase 3: facts.json, codes.json, findings.json, recommendation.json
           (hand-written facts -- the extractor doesn't exist yet, so the
           CLI runs on facts a human wrote, per the build spec: this
           proves the deterministic core before any non-determinism
           enters)

Phase 4 adds a real ``--facts-source extract`` path calling the model;
``hand`` stays available afterward so the deterministic core can always
be re-verified independent of the model. ``extract`` requires a live
ANTHROPIC_API_KEY -- there is no fallback, per the build spec's rule that
a stage which cannot do something correctly raises rather than guessing.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.hand_facts import load_hand_facts
from pipeline.extract.runner import DEFAULT_MODEL
from pipeline.extract import runner as extract_runner
from pipeline.map.mapper import map_codes
from pipeline.models.manifest import RunManifest, StageMetrics
from pipeline.rules import loader as rules_loader
from pipeline.rules.materialize import load_mapping_data, load_validation_data
from pipeline.rules.store import RuleStore
from pipeline.validate.validator import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"
DEFAULT_RULESET_DIRS = [REPO_ROOT / "rulesets" / "2026q3"]
DEFAULT_RULE_STORE_DB = REPO_ROOT / "runs" / ".rules_cache.db"


def _hash_case_dir(case_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(case_dir.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(case_dir).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def run_case(
    case_id: str,
    fixtures_root: Path = DEFAULT_FIXTURES_ROOT,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    ruleset_dirs: list[Path] = DEFAULT_RULESET_DIRS,
    rule_store_db: Path = DEFAULT_RULE_STORE_DB,
    facts_source: str = "hand",
    model: str = DEFAULT_MODEL,
) -> Path:
    """Run the pipeline for one fixture case and return the run directory."""
    if facts_source not in ("hand", "extract"):
        raise ValueError(f"unknown facts_source {facts_source!r}")

    case_dir = fixtures_root / case_id
    stage_metrics: dict[str, StageMetrics] = {}
    prompt_versions: dict[str, str] = {}
    model_id: str | None = None

    t0 = time.monotonic()
    case = fixture_adapter.load_case(case_dir)
    stage_metrics["adapter"] = StageMetrics(wall_time_seconds=time.monotonic() - t0)

    if facts_source == "hand":
        t0 = time.monotonic()
        facts = load_hand_facts(case_dir, case)
        stage_metrics["extract"] = StageMetrics(wall_time_seconds=time.monotonic() - t0)
    else:
        t0 = time.monotonic()
        facts, extract_metrics, prompt_versions = extract_runner.extract_facts(case, model=model)
        for stage_name, m in extract_metrics.items():
            stage_metrics[f"extract:{stage_name}"] = StageMetrics(
                wall_time_seconds=m.wall_time_seconds,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
            )
        stage_metrics["extract_total"] = StageMetrics(wall_time_seconds=time.monotonic() - t0)
        model_id = model

    rule_store_db.parent.mkdir(parents=True, exist_ok=True)
    rules_loader.build_store(rule_store_db, ruleset_dirs)
    with RuleStore(rule_store_db) as store:
        ruleset = store.resolve_ruleset(case.date_of_service)
        mapping_data = load_mapping_data(store, ruleset.ruleset_id)
        validation_data = load_validation_data(store, ruleset.ruleset_id)

    t0 = time.monotonic()
    codes = map_codes(facts, case, ruleset, mapping_data)
    stage_metrics["map"] = StageMetrics(wall_time_seconds=time.monotonic() - t0)

    t0 = time.monotonic()
    findings = validate(codes, case, facts, validation_data)
    stage_metrics["validate"] = StageMetrics(wall_time_seconds=time.monotonic() - t0)

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir = runs_root / case.case_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "case.json").write_text(case.model_dump_json(indent=2))
    (run_dir / "facts.json").write_text(json.dumps([f.model_dump(mode="json") for f in facts], indent=2))
    (run_dir / "codes.json").write_text(codes.model_dump_json(indent=2))
    (run_dir / "findings.json").write_text(json.dumps([f.model_dump(mode="json") for f in findings], indent=2))
    (run_dir / "recommendation.json").write_text(
        json.dumps(
            {
                "case_id": case.case_id,
                "ruleset_id": ruleset.ruleset_id,
                "lines": [line.model_dump(mode="json") for line in codes.lines],
                "findings": [f.model_dump(mode="json") for f in findings],
            },
            indent=2,
        )
    )

    manifest = RunManifest(
        run_id=run_id,
        case_id=case.case_id,
        created_at=datetime.now(timezone.utc),
        adapter_version=case.source.adapter_version,
        input_hash=_hash_case_dir(case_dir),
        stages_completed=["adapter", "extract", "map", "validate"],
        ruleset_id=ruleset.ruleset_id,
        ruleset_content_hash=ruleset.content_hash,
        prompt_versions={"facts_source": facts_source, **prompt_versions},
        model_id=model_id,
        stage_metrics=stage_metrics,
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))

    return run_dir


@click.command()
@click.option("--case", "case_id", required=True, help="Fixture case directory name, e.g. case_01")
@click.option(
    "--fixtures-root",
    type=click.Path(path_type=Path),
    default=DEFAULT_FIXTURES_ROOT,
    show_default=True,
)
@click.option(
    "--runs-root",
    type=click.Path(path_type=Path),
    default=DEFAULT_RUNS_ROOT,
    show_default=True,
)
@click.option(
    "--facts-source",
    type=click.Choice(["hand", "extract"]),
    default="hand",
    show_default=True,
    help="'hand' replays fixtures/cases/<id>/hand_facts.json; 'extract' calls the model (needs ANTHROPIC_API_KEY)",
)
@click.option("--model", default=DEFAULT_MODEL, show_default=True, help="only used with --facts-source extract")
def main(case_id: str, fixtures_root: Path, runs_root: Path, facts_source: str, model: str) -> None:
    run_dir = run_case(case_id, fixtures_root=fixtures_root, runs_root=runs_root, facts_source=facts_source, model=model)
    click.echo(f"wrote run to {run_dir}")


if __name__ == "__main__":
    main()
