from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.hand_facts import load_hand_facts
from pipeline.map.catalog import MappingGapError
from pipeline.map.mapper import (
    apply_component_modifiers,
    apply_substitutions,
    map_codes,
    map_diagnoses,
    map_specimen_units,
    map_stains,
)
from pipeline.models.case import BillingArrangement
from pipeline.models.facts import FactType
from pipeline.rules import loader
from pipeline.rules.materialize import MappingData, load_mapping_data
from pipeline.rules.store import RuleStore, Substitution
from pipeline.testing import make_case, make_fact, make_specimen

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
RULESET_2026Q3 = Path(__file__).resolve().parents[2] / "rulesets" / "2026q3"


@pytest.fixture()
def store(tmp_path) -> RuleStore:
    db_path = tmp_path / "rules.db"
    loader.build_store(db_path, [RULESET_2026Q3])
    s = RuleStore(db_path)
    yield s
    s.close()


def _load(case_id: str):
    case_dir = FIXTURES_ROOT / case_id
    case = fixture_adapter.load_case(case_dir)
    facts = load_hand_facts(case_dir, case)
    return case, facts


# ---------------------------------------------------------------------------
# End-to-end against the fixture corpus
# ---------------------------------------------------------------------------


def test_case_01_single_specimen_single_he(store):
    case, facts = _load("case_01")
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)

    codes_by_system = {(l.code_system, l.code) for l in codes.lines}
    assert ("CPT", "88305") in codes_by_system
    assert ("ICD10", "D22.9") in codes_by_system
    assert len(codes.lines) == 2


def test_case_02_six_specimens_five_diagnoses(store):
    """F is a negative finding -- no diagnosis line for it."""
    case, facts = _load("case_02")
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)

    level_lines = [l for l in codes.lines if l.rule_id == "specimen_units"]
    dx_lines = [l for l in codes.lines if l.code_system == "ICD10"]
    assert len(level_lines) == 6
    assert len(dx_lines) == 5
    assert all(l.specimen_id != "F" for l in dx_lines)


def test_case_03_multi_site_container_bills_as_one_line(store):
    case, facts = _load("case_03")
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)

    level_lines = [l for l in codes.lines if l.rule_id == "specimen_units"]
    assert len(level_lines) == 1
    assert level_lines[0].units == 1


@pytest.mark.parametrize("case_id", ["case_01", "case_02", "case_03"])
def test_every_line_traces_to_at_least_one_fact(store, case_id):
    case, facts = _load(case_id)
    fact_ids = {f.fact_id for f in facts}
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    codes = map_codes(facts, case, ruleset, mapping_data)
    for line in codes.lines:
        assert line.fact_ids, f"{line.line_id} has no supporting fact"
        assert set(line.fact_ids) <= fact_ids, f"{line.line_id} cites an unknown fact id"


# ---------------------------------------------------------------------------
# map_specimen_units
# ---------------------------------------------------------------------------


def test_specimen_units_raises_without_a_supporting_fact():
    case = make_case()
    with pytest.raises(MappingGapError):
        map_specimen_units([], case)


def test_specimen_units_raises_for_uncataloged_procedure_type():
    case = make_case(specimens=[make_specimen(procedure_type="frozen_section")])
    fact = make_fact("f1", FactType.SPECIMEN, {"sites": ["skin, left forearm"]})
    with pytest.raises(MappingGapError):
        map_specimen_units([fact], case)


# ---------------------------------------------------------------------------
# map_stains: IHC unit counting (positive / boundary / negative)
# ---------------------------------------------------------------------------


def test_ihc_single_antibody_only_bills_first(  ):
    facts = [
        make_fact("ihc1", FactType.STAIN, {"kind": "ihc", "block_id": "A1", "stain_id": "A1-IHC-1", "antibody": "CK7"}),
    ]
    lines = map_stains(facts, make_case())
    assert len(lines) == 1
    assert lines[0].code == "88342"
    assert lines[0].units == 1


def test_ihc_four_antibodies_first_and_additional():
    facts = [
        make_fact(f"ihc{i}", FactType.STAIN, {"kind": "ihc", "block_id": "A1", "stain_id": f"A1-IHC-{i}", "antibody": ab})
        for i, ab in enumerate(["CK7", "CK20", "CDX2", "TTF1"], start=1)
    ]
    lines = map_stains(facts, make_case())
    first = next(l for l in lines if l.code == "88342")
    additional = next(l for l in lines if l.code == "88341")
    assert first.units == 1
    assert additional.units == 3
    assert set(first.fact_ids) | set(additional.fact_ids) == {f.fact_id for f in facts}


def test_ihc_addendum_sequence_hint_produces_only_additional_line():
    """An addendum run coding a follow-up antibody whose first-antibody
    fact belongs to an earlier, already-billed run bills only 88341 --
    this is how case 13's add-on-without-base scenario legitimately
    arises from real facts rather than only from a validator unit test."""
    facts = [
        make_fact("ihc1", FactType.STAIN, {"kind": "ihc", "block_id": "A1", "stain_id": "A1-IHC-2", "antibody": "CDX2", "sequence": "additional"}),
    ]
    lines = map_stains(facts, make_case())
    assert len(lines) == 1
    assert lines[0].code == "88341"
    assert lines[0].units == 1


def test_no_ihc_facts_produces_no_ihc_lines():
    lines = map_stains([], make_case())
    assert lines == []


def test_special_stain_units_count_each_stain():
    facts = [
        make_fact("sp1", FactType.STAIN, {"kind": "special", "block_id": "A1", "stain_id": "A1-SP-1"}),
        make_fact("sp2", FactType.STAIN, {"kind": "special", "block_id": "A1", "stain_id": "A1-SP-2"}),
    ]
    lines = map_stains(facts, make_case())
    assert len(lines) == 1
    assert lines[0].code == "88312"
    assert lines[0].units == 2


# ---------------------------------------------------------------------------
# map_diagnoses: certainty handling
# ---------------------------------------------------------------------------


def test_negative_certainty_produces_no_line():
    facts = [make_fact("dx1", FactType.DIAGNOSIS, {"text": "compound nevus", "certainty": "negative", "qualifier": None})]
    assert map_diagnoses(facts) == []


def test_qualified_certainty_codes_the_presenting_finding():
    facts = [
        make_fact(
            "dx1", FactType.DIAGNOSIS,
            {"text": "atypical melanocytic proliferation", "certainty": "qualified", "qualifier": "cannot exclude melanoma in situ"},
        )
    ]
    lines = map_diagnoses(facts)
    assert len(lines) == 1
    assert lines[0].code == "D48.5"


def test_definitive_certainty_codes_directly():
    facts = [make_fact("dx1", FactType.DIAGNOSIS, {"text": "actinic keratosis", "certainty": "definitive", "qualifier": None})]
    lines = map_diagnoses(facts)
    assert lines[0].code == "L57.0"


def test_unmapped_diagnosis_text_raises():
    facts = [make_fact("dx1", FactType.DIAGNOSIS, {"text": "some novel finding", "certainty": "definitive", "qualifier": None})]
    with pytest.raises(MappingGapError):
        map_diagnoses(facts)


# ---------------------------------------------------------------------------
# component modifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arrangement,expected_modifier",
    [
        (BillingArrangement.GLOBAL, None),
        (BillingArrangement.PROFESSIONAL, "26"),
        (BillingArrangement.TECHNICAL, "TC"),
    ],
)
def test_component_modifiers_applied_uniformly(arrangement, expected_modifier):
    case = make_case(billing_arrangement=arrangement)
    fact = make_fact("f1", FactType.SPECIMEN, {"sites": ["skin, left forearm"]})
    lines = map_specimen_units([fact], case)
    lines = apply_component_modifiers(lines, case)
    if expected_modifier is None:
        assert lines[0].modifiers == []
    else:
        assert expected_modifier in lines[0].modifiers


def test_component_modifiers_never_applied_to_icd10_lines():
    case = make_case(billing_arrangement=BillingArrangement.PROFESSIONAL)
    fact = make_fact("dx1", FactType.DIAGNOSIS, {"text": "compound nevus", "certainty": "definitive", "qualifier": None})
    lines = map_diagnoses([fact])
    lines = apply_component_modifiers(lines, case)
    assert lines[0].modifiers == []


# ---------------------------------------------------------------------------
# substitution
# ---------------------------------------------------------------------------


def _prostate_case(payer_class: str, count: int):
    specimens = [
        make_specimen(specimen_id=f"S{i}", sites=["prostate, left"], procedure_type="biopsy")
        for i in range(count)
    ]
    return make_case(specimens=specimens, payer_class=payer_class)


def test_prostate_saturation_substitution_applies_at_ten_specimens():
    case = _prostate_case("medicare", 10)
    facts = [
        make_fact(f"f{i}", FactType.SPECIMEN, {"sites": ["prostate, left"]}, specimen_id=f"S{i}")
        for i in range(10)
    ]
    lines = map_specimen_units(facts, case)
    mapping_data = MappingData(substitutions={("medicare", "88305"): Substitution("medicare", "88305", "G0416", "saturation")})
    lines = apply_substitutions(lines, case, mapping_data)
    assert len(lines) == 1
    assert lines[0].code == "G0416"
    assert set(lines[0].fact_ids) == {f.fact_id for f in facts}


def test_prostate_substitution_does_not_apply_under_ten_specimens():
    case = _prostate_case("medicare", 9)
    facts = [
        make_fact(f"f{i}", FactType.SPECIMEN, {"sites": ["prostate, left"]}, specimen_id=f"S{i}")
        for i in range(9)
    ]
    lines = map_specimen_units(facts, case)
    mapping_data = MappingData(substitutions={("medicare", "88305"): Substitution("medicare", "88305", "G0416", "saturation")})
    lines = apply_substitutions(lines, case, mapping_data)
    assert len(lines) == 9
    assert all(l.code == "88305" for l in lines)


def test_substitution_does_not_apply_to_non_medicare_payer():
    case = _prostate_case("commercial", 10)
    facts = [
        make_fact(f"f{i}", FactType.SPECIMEN, {"sites": ["prostate, left"]}, specimen_id=f"S{i}")
        for i in range(10)
    ]
    lines = map_specimen_units(facts, case)
    mapping_data = MappingData(substitutions={("medicare", "88305"): Substitution("medicare", "88305", "G0416", "saturation")})
    lines = apply_substitutions(lines, case, mapping_data)
    assert len(lines) == 10


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_map_codes_is_deterministic(store):
    case, facts = _load("case_02")
    ruleset = store.resolve_ruleset(case.date_of_service)
    mapping_data = load_mapping_data(store, ruleset.ruleset_id)
    first = map_codes(facts, case, ruleset, mapping_data)
    second = map_codes(list(reversed(facts)), case, ruleset, mapping_data)
    assert first.model_dump_json() == second.model_dump_json()
