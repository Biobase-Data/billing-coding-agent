"""CLI entry point: run.py --case <id> produces a full run directory.

Works from Phase 1 onward. Each later phase adds another artifact to the
run directory (facts.json, codes.json, findings.json, recommendation.json)
without changing how earlier artifacts are produced — the CLI stays
runnable at every commit, per the build spec.
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
from pipeline.models.manifest import RunManifest, StageMetrics

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"


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
) -> Path:
    """Run the pipeline for one fixture case and return the run directory.

    Phase 1: adapter only. Later phases extend this function to call the
    extractor, mapper, validator and evaluator in sequence, writing one
    artifact per stage and appending to ``stages_completed`` as they land.
    """
    case_dir = fixtures_root / case_id
    t0 = time.monotonic()
    case = fixture_adapter.load_case(case_dir)
    adapter_wall_time = time.monotonic() - t0

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir = runs_root / case.case_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "case.json").write_text(case.model_dump_json(indent=2))

    manifest = RunManifest(
        run_id=run_id,
        case_id=case.case_id,
        created_at=datetime.now(timezone.utc),
        adapter_version=case.source.adapter_version,
        input_hash=_hash_case_dir(case_dir),
        stages_completed=["adapter"],
        stage_metrics={"adapter": StageMetrics(wall_time_seconds=adapter_wall_time)},
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
def main(case_id: str, fixtures_root: Path, runs_root: Path) -> None:
    run_dir = run_case(case_id, fixtures_root=fixtures_root, runs_root=runs_root)
    click.echo(f"wrote run to {run_dir}")


if __name__ == "__main__":
    main()
