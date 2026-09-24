"""Repeatability: run one case N=20 times end to end (including
extraction) and assert the final code sets are identical.

The mapper and validator are deterministic by construction (see their
own determinism tests) -- any variance here comes from the model. This
test is a direct measure of extraction stability, and it is the number
Sam asked for (see ASSUMPTIONS.md: "the repeatability threshold").

It needs a live ANTHROPIC_API_KEY, which this build sandbox does not
have -- it is skipped here rather than faked. Run it wherever a key is
available (e.g. CI with the secret configured) with:

    ANTHROPIC_API_KEY=... pytest pipeline/eval/test_repeatability.py -v -s

and record the observed figure in ASSUMPTIONS.md; only then set a CI
threshold, per the build spec's instruction to observe first and gate
second.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.runner import extract_facts
from pipeline.map.mapper import map_codes
from pipeline.rules import loader
from pipeline.rules.materialize import load_mapping_data
from pipeline.rules.store import RuleStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "cases"
RULESET_2026Q3 = REPO_ROOT / "rulesets" / "2026q3"

N = 20

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="repeatability measurement needs a live ANTHROPIC_API_KEY -- see module docstring",
)


@pytest.mark.parametrize("case_id", ["case_01", "case_02", "case_03"])
def test_repeatability_n20(tmp_path, case_id):
    case = fixture_adapter.load_case(FIXTURES_ROOT / case_id)

    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    with RuleStore(db_path) as store:
        ruleset = store.resolve_ruleset(case.date_of_service)
        mapping_data = load_mapping_data(store, ruleset.ruleset_id)

    code_sets_json = []
    for _ in range(N):
        facts, _metrics, _versions = extract_facts(case)
        codes = map_codes(facts, case, ruleset, mapping_data)
        code_sets_json.append(codes.model_dump_json())

    distinct = set(code_sets_json)
    identical_fraction = code_sets_json.count(code_sets_json[0]) / N
    print(f"\n{case_id}: {len(distinct)} distinct code sets out of {N} runs "
          f"({identical_fraction:.0%} identical to the first)")

    # Not asserted against a fixed threshold yet -- see module docstring.
    # This print is the "figure written down" the build spec asks for;
    # once observed, replace this comment with an explicit `assert
    # identical_fraction >= <observed threshold>`.
