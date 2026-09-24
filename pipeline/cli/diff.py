"""CLI entry point: diff two runs of the same case.

    python -m pipeline.cli.diff --case-id S26-0042900 --run-a <run_id> --run-b <run_id>

The canonical use is the amended-report scenario: run the original
report, run the amendment, diff the two run ids under the same case_id.
"""

from __future__ import annotations

from pathlib import Path

import click

from pipeline.eval.diff import diff_runs, format_diff

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"


@click.command()
@click.option("--case-id", required=True, help="The case_id shared by both runs, e.g. S26-0042900")
@click.option("--run-a", required=True, help="The earlier run_id (the 'before')")
@click.option("--run-b", required=True, help="The later run_id (the 'after')")
@click.option("--runs-root", type=click.Path(path_type=Path), default=DEFAULT_RUNS_ROOT, show_default=True)
def main(case_id: str, run_a: str, run_b: str, runs_root: Path) -> None:
    diff = diff_runs(runs_root / case_id / run_a, runs_root / case_id / run_b)
    click.echo(format_diff(diff))


if __name__ == "__main__":
    main()
