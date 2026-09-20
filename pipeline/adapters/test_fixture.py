"""Contract tests for the fixture adapter.

These tests assert only things true of the *canonical Case shape*, not
things specific to fixture.py's implementation. When a NovoPath adapter
lands, the same test module (parametrized over its own case ids) proves
the new adapter is source-agnostic in exactly the same way.
"""

from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.models.case import Case

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
CASE_IDS = ["case_01", "case_02", "case_03"]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_produces_valid_canonical_case(case_id: str):
    case = fixture_adapter.load_case(FIXTURES_ROOT / case_id)
    assert isinstance(case, Case)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_every_required_field_populated(case_id: str):
    case = fixture_adapter.load_case(FIXTURES_ROOT / case_id)
    assert case.case_id
    assert case.lab_id
    assert case.date_of_service is not None
    assert case.date_reported is not None
    assert case.subspecialty is not None
    assert len(case.specimens) >= 1
    assert len(case.documents) >= 1
    assert case.requisition.payer.mac_jurisdiction
    assert case.billing_arrangement is not None
    assert case.source.system == "fixture"
    for specimen in case.specimens:
        assert specimen.specimen_id
        assert len(specimen.sites) >= 1


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_document_text_matches_file_on_disk(case_id: str):
    case = fixture_adapter.load_case(FIXTURES_ROOT / case_id)
    for doc in case.documents:
        assert doc.text.strip() != ""


def test_case_01_single_specimen_single_he():
    case = fixture_adapter.load_case(FIXTURES_ROOT / "case_01")
    assert len(case.specimens) == 1
    specimen = case.specimens[0]
    assert specimen.sites == ["skin, left forearm"]
    all_stains = [s for b in specimen.blocks for s in b.stains]
    assert len(all_stains) == 1
    assert all_stains[0].kind.value == "he"


def test_case_02_six_specimens_one_accession():
    case = fixture_adapter.load_case(FIXTURES_ROOT / "case_02")
    assert len(case.specimens) == 6
    assert {s.specimen_id for s in case.specimens} == {"A", "B", "C", "D", "E", "F"}


def test_case_03_three_sites_in_one_container():
    """The silent unit-loss case: one container, a three-item site list."""
    case = fixture_adapter.load_case(FIXTURES_ROOT / "case_03")
    assert len(case.specimens) == 1
    specimen = case.specimens[0]
    assert specimen.site is None, "site must not collapse a multi-site container to one guess"
    assert specimen.sites == ["left cheek", "right cheek", "forehead"]
    assert "x3" in specimen.container_label


def test_missing_source_json_raises(tmp_path):
    with pytest.raises(fixture_adapter.FixtureLoadError):
        fixture_adapter.load_case(tmp_path)


def test_list_case_ids_finds_all_fixtures():
    ids = fixture_adapter.list_case_ids(FIXTURES_ROOT)
    for case_id in CASE_IDS:
        assert case_id in ids
