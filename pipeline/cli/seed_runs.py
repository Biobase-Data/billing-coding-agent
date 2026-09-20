"""Populate runs/ with one run per corpus case, so the review API has
something to serve. The API itself never runs the pipeline -- it only
reads run directories `pipeline.cli.run` has already written.

    python -m pipeline.cli.seed_runs
"""

from __future__ import annotations

import click

from pipeline.adapters import fixture as fixture_adapter
from pipeline.cli.run import DEFAULT_FIXTURES_ROOT, DEFAULT_RUNS_ROOT, run_case


@click.command()
def main() -> None:
    case_ids = fixture_adapter.list_case_ids(DEFAULT_FIXTURES_ROOT)
    for case_id in case_ids:
        run_dir = run_case(case_id, fixtures_root=DEFAULT_FIXTURES_ROOT, runs_root=DEFAULT_RUNS_ROOT)
        click.echo(f"{case_id}: wrote {run_dir}")


if __name__ == "__main__":
    main()
