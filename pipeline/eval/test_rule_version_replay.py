"""Rule-version replay: the same case, coded against two different
rulesets by date of service, produces different validation output.

This is the property that makes retrospective scoring possible: proving
date-based rule selection actually changes what the validator says, not
just that it resolves to a ruleset_id. The two rulesets here are a
synthetic test fixture (clearly not real CMS content, same as the
synthetic PTP rows in pipeline/validate/test_validator.py) -- only to
exercise the *mechanism*.
"""

from __future__ import annotations

import json
from datetime import date

from pipeline.models.codes import CodeLine, CodeSet
from pipeline.rules import loader
from pipeline.rules.materialize import load_validation_data
from pipeline.rules.store import RuleStore
from pipeline.validate.checks.unit_caps import check_unit_caps

_BASE_RULESET = {
    "ruleset_id": None,
    "effective_from": None,
    "effective_to": None,
    "source_note": "synthetic test fixture, not real CMS content",
    "mue": [],
    "ptp_edit": [],
    "coverage_policy": [],
    "coverage_diagnosis": [],
    "substitution": [],
}


def _write_ruleset(tmp_path, ruleset_id, effective_from, effective_to, mue_88312):
    d = tmp_path / ruleset_id
    d.mkdir()
    data = dict(_BASE_RULESET)
    data.update(
        ruleset_id=ruleset_id,
        effective_from=effective_from,
        effective_to=effective_to,
        mue=[{"code": "88312", "max_units": mue_88312, "adjudication_type": "date_of_service"}],
    )
    (d / "ruleset.json").write_text(json.dumps(data))
    return d


def test_same_code_set_scored_differently_under_two_rulesets(tmp_path):
    early_dir = _write_ruleset(tmp_path, "2026q1-test", "2026-01-01", "2026-06-30", mue_88312=5)
    late_dir = _write_ruleset(tmp_path, "2026q3-test", "2026-07-01", None, mue_88312=9)

    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [early_dir, late_dir])

    codes = CodeSet(
        case_id="TEST",
        ruleset_id="irrelevant-for-this-check",
        lines=[
            CodeLine(
                line_id="A-special", code="88312", code_system="CPT", units=6,
                specimen_id="A", fact_ids=["f1"], confidence="high", rule_id="special_stain_units",
            )
        ],
    )

    with RuleStore(db_path) as store:
        early_ruleset = store.resolve_ruleset(date(2026, 3, 1))
        late_ruleset = store.resolve_ruleset(date(2026, 8, 1))
        assert early_ruleset.ruleset_id == "2026q1-test"
        assert late_ruleset.ruleset_id == "2026q3-test"

        early_data = load_validation_data(store, early_ruleset.ruleset_id)
        late_data = load_validation_data(store, late_ruleset.ruleset_id)

    early_findings = check_unit_caps(codes, early_data)
    late_findings = check_unit_caps(codes, late_data)

    # 6 units exceeds the early ruleset's MUE of 5 but not the later
    # ruleset's MUE of 9 -- same code set, same units, different rule
    # version, different validation outcome.
    assert len(early_findings) == 1
    assert early_findings[0].rule_id == "mue:88312"
    assert late_findings == []
