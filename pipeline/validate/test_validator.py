from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.hand_facts import load_hand_facts
from pipeline.map.mapper import map_codes
from pipeline.models.codes import CodeLine, CodeSet
from pipeline.models.facts import FactType
from pipeline.models.findings import Severity
from pipeline.rules import loader
from pipeline.rules.materialize import ValidationData, load_mapping_data, load_validation_data
from pipeline.rules.store import PtpEdit, RuleStore
from pipeline.testing import make_case, make_fact, make_specimen
from pipeline.validate.checks.add_on import check_add_on_dependencies
from pipeline.validate.checks.coverage import check_coverage_linkage
from pipeline.validate.checks.diagnosis import check_qualified_diagnosis
from pipeline.validate.checks.documentation import (
    check_clinical_indication_present,
    check_ihc_missing_antibody,
)
from pipeline.validate.checks.ptp_pairs import check_ptp_pairs
from pipeline.validate.checks.reconciliation import (
    check_ordered_not_resulted,
    check_resulted_not_billed,
)
from pipeline.validate.checks.specimen import check_specimen_ambiguity
from pipeline.validate.checks.unit_caps import check_unit_caps
from pipeline.validate.rule_registry import resolve_rule_id
from pipeline.validate.validator import validate

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
RULESET_2026Q3 = Path(__file__).resolve().parents[2] / "rulesets" / "2026q3"

EMPTY_VALIDATION_DATA = ValidationData(mue={}, ptp_edits=[], coverage_policies={}, covered_diagnoses={})


def _line(code="88342", units=1, code_system="CPT", specimen_id="A", line_id="L1", fact_ids=("f1",)):
    return CodeLine(
        line_id=line_id, code=code, code_system=code_system, units=units,
        specimen_id=specimen_id, fact_ids=list(fact_ids), confidence="high", rule_id="test",
    )


def _codeset(lines):
    return CodeSet(case_id="TEST-0001", ruleset_id="test", lines=lines)


@pytest.fixture()
def store(tmp_path) -> RuleStore:
    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    s = RuleStore(db_path)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# unit caps: positive (exceeds) / negative (within) / boundary (== cap)
# ---------------------------------------------------------------------------


def test_unit_cap_exceeded_is_a_blocker():
    data = ValidationData(mue={"88341": 13}, ptp_edits=[], coverage_policies={}, covered_diagnoses={})
    findings = check_unit_caps(_codeset([_line(code="88341", units=14)]), data)
    assert len(findings) == 1
    assert findings[0].severity == Severity.BLOCKER


def test_unit_cap_at_boundary_is_not_a_finding():
    data = ValidationData(mue={"88341": 13}, ptp_edits=[], coverage_policies={}, covered_diagnoses={})
    findings = check_unit_caps(_codeset([_line(code="88341", units=13)]), data)
    assert findings == []


def test_unit_cap_within_limit_is_not_a_finding():
    data = ValidationData(mue={"88341": 13}, ptp_edits=[], coverage_policies={}, covered_diagnoses={})
    findings = check_unit_caps(_codeset([_line(code="88341", units=1)]), data)
    assert findings == []


def test_unit_cap_no_mue_configured_is_not_a_finding():
    findings = check_unit_caps(_codeset([_line(code="99999", units=999)]), EMPTY_VALIDATION_DATA)
    assert findings == []


# ---------------------------------------------------------------------------
# PTP pairs
# ---------------------------------------------------------------------------


def test_ptp_conflict_no_modifier_allowed_is_a_blocker():
    data = ValidationData(mue={}, ptp_edits=[PtpEdit("88305", "88342", 0)], coverage_policies={}, covered_diagnoses={})
    lines = [_line(code="88305", line_id="L1"), _line(code="88342", line_id="L2")]
    findings = check_ptp_pairs(_codeset(lines), data)
    assert len(findings) == 1
    assert findings[0].severity == Severity.BLOCKER


def test_ptp_conflict_with_override_modifier_is_not_a_finding():
    data = ValidationData(mue={}, ptp_edits=[PtpEdit("88305", "88342", 1)], coverage_policies={}, covered_diagnoses={})
    lines = [
        _line(code="88305", line_id="L1"),
        CodeLine(line_id="L2", code="88342", code_system="CPT", units=1, specimen_id="A", fact_ids=["f1"], confidence="high", rule_id="test", modifiers=["59"]),
    ]
    findings = check_ptp_pairs(_codeset(lines), data)
    assert findings == []


def test_ptp_edit_does_not_apply_indicator_9():
    data = ValidationData(mue={}, ptp_edits=[PtpEdit("88305", "88342", 9)], coverage_policies={}, covered_diagnoses={})
    lines = [_line(code="88305", line_id="L1"), _line(code="88342", line_id="L2")]
    findings = check_ptp_pairs(_codeset(lines), data)
    assert findings == []


def test_no_ptp_pair_no_finding():
    data = ValidationData(mue={}, ptp_edits=[], coverage_policies={}, covered_diagnoses={})
    lines = [_line(code="88305", line_id="L1"), _line(code="88342", line_id="L2")]
    assert check_ptp_pairs(_codeset(lines), data) == []


# ---------------------------------------------------------------------------
# add-on dependency
# ---------------------------------------------------------------------------


def test_add_on_without_base_is_a_blocker():
    lines = [_line(code="88341", units=2, line_id="L1", specimen_id="A")]
    findings = check_add_on_dependencies(_codeset(lines))
    assert len(findings) == 1
    assert findings[0].severity == Severity.BLOCKER


def test_add_on_with_base_present_is_not_a_finding():
    lines = [
        _line(code="88342", line_id="L1", specimen_id="A"),
        _line(code="88341", units=2, line_id="L2", specimen_id="A"),
    ]
    assert check_add_on_dependencies(_codeset(lines)) == []


def test_add_on_base_on_a_different_specimen_still_missing():
    lines = [
        _line(code="88342", line_id="L1", specimen_id="A"),
        _line(code="88341", units=2, line_id="L2", specimen_id="B"),
    ]
    findings = check_add_on_dependencies(_codeset(lines))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# coverage linkage
# ---------------------------------------------------------------------------


def test_coverage_linkage_covered_diagnosis_no_finding():
    data = ValidationData(
        mue={}, ptp_edits={} if False else [],
        coverage_policies={("DEMO-MAC-J5", "88305"): ["POLICY"]},
        covered_diagnoses={"POLICY": {"D22.9"}},
    )
    case = make_case()
    lines = [_line(code="88305", line_id="L1", specimen_id="A"), _line(code="D22.9", code_system="ICD10", line_id="L2", specimen_id="A")]
    assert check_coverage_linkage(_codeset(lines), case, data) == []


def test_coverage_linkage_uncovered_diagnosis_is_a_blocker():
    data = ValidationData(
        mue={}, ptp_edits=[],
        coverage_policies={("DEMO-MAC-J5", "88305"): ["POLICY"]},
        covered_diagnoses={"POLICY": {"D22.9"}},
    )
    case = make_case()
    lines = [_line(code="88305", line_id="L1", specimen_id="A"), _line(code="L57.0", code_system="ICD10", line_id="L2", specimen_id="A")]
    findings = check_coverage_linkage(_codeset(lines), case, data)
    assert len(findings) == 1
    assert findings[0].severity == Severity.BLOCKER


def test_coverage_linkage_no_policy_configured_is_not_a_finding():
    case = make_case()
    lines = [_line(code="88305", line_id="L1", specimen_id="A")]
    assert check_coverage_linkage(_codeset(lines), case, EMPTY_VALIDATION_DATA) == []


# ---------------------------------------------------------------------------
# documentation gaps
# ---------------------------------------------------------------------------


def test_ihc_missing_antibody_is_a_review_finding():
    facts = [make_fact("f1", FactType.STAIN, {"kind": "ihc", "block_id": "A1", "stain_id": "A1-1", "antibody": None})]
    findings = check_ihc_missing_antibody(facts)
    assert len(findings) == 1
    assert findings[0].severity == Severity.REVIEW


def test_ihc_with_antibody_named_is_not_a_finding():
    facts = [make_fact("f1", FactType.STAIN, {"kind": "ihc", "block_id": "A1", "stain_id": "A1-1", "antibody": "CK7"})]
    assert check_ihc_missing_antibody(facts) == []


def test_no_clinical_indication_is_informational():
    case = make_case()
    case = case.model_copy(update={"requisition": case.requisition.model_copy(update={"clinical_indication": None})})
    findings = check_clinical_indication_present(case)
    assert len(findings) == 1
    assert findings[0].severity == Severity.INFORMATIONAL


def test_clinical_indication_present_is_not_a_finding():
    assert check_clinical_indication_present(make_case()) == []


# ---------------------------------------------------------------------------
# ordered/resulted reconciliation
# ---------------------------------------------------------------------------


def test_ordered_not_resulted_is_a_review_finding():
    from pipeline.models.case import Stain

    specimen = make_specimen(stains=[Stain(stain_id="A1-1", kind="special", ordered=True, resulted=False)])
    case = make_case(specimens=[specimen])
    findings = check_ordered_not_resulted(case)
    assert len(findings) == 1
    assert findings[0].severity == Severity.REVIEW


def test_ordered_and_resulted_is_not_a_finding():
    from pipeline.models.case import Stain

    specimen = make_specimen(stains=[Stain(stain_id="A1-1", kind="special", ordered=True, resulted=True)])
    case = make_case(specimens=[specimen])
    assert check_ordered_not_resulted(case) == []


def test_resulted_not_billed_is_a_review_finding():
    from pipeline.models.case import Stain

    specimen = make_specimen(stains=[Stain(stain_id="A1-1", kind="special", ordered=True, resulted=True)])
    case = make_case(specimens=[specimen])
    findings = check_resulted_not_billed([], case)
    assert len(findings) == 1
    assert findings[0].severity == Severity.REVIEW


def test_resulted_and_billed_is_not_a_finding():
    from pipeline.models.case import Stain

    specimen = make_specimen(stains=[Stain(stain_id="A1-1", kind="special", ordered=True, resulted=True)])
    case = make_case(specimens=[specimen])
    fact = make_fact("f1", FactType.STAIN, {"kind": "special", "block_id": "A1", "stain_id": "A1-1"})
    assert check_resulted_not_billed([fact], case) == []


def test_he_resulted_never_flagged_as_not_billed():
    from pipeline.models.case import Stain

    specimen = make_specimen(stains=[Stain(stain_id="A1-1", kind="he", ordered=True, resulted=True)])
    case = make_case(specimens=[specimen])
    assert check_resulted_not_billed([], case) == []


# ---------------------------------------------------------------------------
# specimen ambiguity / qualified diagnosis
# ---------------------------------------------------------------------------


def test_multi_site_container_is_a_review_finding():
    specimen = make_specimen(sites=["left cheek", "right cheek"])
    case = make_case(specimens=[specimen])
    findings = check_specimen_ambiguity(case)
    assert len(findings) == 1
    assert findings[0].severity == Severity.REVIEW


def test_single_site_container_is_not_a_finding():
    case = make_case(specimens=[make_specimen(sites=["skin, left forearm"])])
    assert check_specimen_ambiguity(case) == []


def test_qualified_diagnosis_is_a_review_finding():
    facts = [make_fact("dx1", FactType.DIAGNOSIS, {"text": "atypical melanocytic proliferation", "certainty": "qualified", "qualifier": "cannot exclude melanoma"})]
    findings = check_qualified_diagnosis(facts)
    assert len(findings) == 1
    assert findings[0].severity == Severity.REVIEW


def test_definitive_diagnosis_is_not_a_finding():
    facts = [make_fact("dx1", FactType.DIAGNOSIS, {"text": "compound nevus", "certainty": "definitive", "qualifier": None})]
    assert check_qualified_diagnosis(facts) == []


# ---------------------------------------------------------------------------
# rule_id resolution against the real ruleset, and end to end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", ["case_01", "case_02", "case_03"])
def test_every_finding_rule_id_resolves(store, case_id):
    case_dir = FIXTURES_ROOT / case_id
    case = fixture_adapter.load_case(case_dir)
    facts = load_hand_facts(case_dir, case)
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    validation_data = load_validation_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)
    findings = validate(codes, case, facts, validation_data)
    for finding in findings:
        assert resolve_rule_id(finding.rule_id, validation_data), (
            f"finding rule_id {finding.rule_id!r} does not resolve"
        )


def test_case_03_produces_the_ambiguous_specimen_finding(store):
    case_dir = FIXTURES_ROOT / "case_03"
    case = fixture_adapter.load_case(case_dir)
    facts = load_hand_facts(case_dir, case)
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    validation_data = load_validation_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)
    findings = validate(codes, case, facts, validation_data)
    assert any(f.rule_id == "specimen:ambiguous_site_count" for f in findings)


def test_validate_is_deterministic(store):
    case_dir = FIXTURES_ROOT / "case_02"
    case = fixture_adapter.load_case(case_dir)
    facts = load_hand_facts(case_dir, case)
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    validation_data = load_validation_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)
    first = validate(codes, case, facts, validation_data)
    second = validate(codes, case, list(reversed(facts)), validation_data)
    assert [f.model_dump() for f in first] == [f.model_dump() for f in second]
