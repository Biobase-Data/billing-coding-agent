import json
from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.parser import ExtractionRejectedError, parse_facts
from pipeline.models.facts import FactType

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"


@pytest.fixture()
def case_01():
    return fixture_adapter.load_case(FIXTURES_ROOT / "case_01")


def test_parses_a_valid_specimen_fact(case_01):
    raw = json.dumps(
        [
            {
                "specimen_id": "A",
                "value": {"sites": ["skin, left forearm"], "container_label": "A: skin, left forearm"},
                "document_id": "doc-report",
                "quoted": "A. Skin, left forearm, shave biopsy",
                "confidence": "high",
            }
        ]
    )
    facts = parse_facts(raw, case_01, FactType.SPECIMEN, "spec")
    assert len(facts) == 1
    assert facts[0].fact_id == "spec-1"
    assert facts[0].evidence.quoted == "A. Skin, left forearm, shave biopsy"
    assert case_01.document("doc-report").text[facts[0].evidence.start : facts[0].evidence.end] == facts[0].evidence.quoted


def test_rejects_non_json(case_01):
    with pytest.raises(ExtractionRejectedError):
        parse_facts("not json at all", case_01, FactType.SPECIMEN, "spec")


def test_rejects_non_array(case_01):
    with pytest.raises(ExtractionRejectedError):
        parse_facts(json.dumps({"not": "a list"}), case_01, FactType.SPECIMEN, "spec")


def test_rejects_unknown_document_id(case_01):
    raw = json.dumps(
        [{"specimen_id": "A", "value": {"sites": ["x"]}, "document_id": "doc-nonexistent", "quoted": "x", "confidence": "high"}]
    )
    with pytest.raises(ExtractionRejectedError):
        parse_facts(raw, case_01, FactType.SPECIMEN, "spec")


def test_rejects_hallucinated_quote_not_in_document(case_01):
    raw = json.dumps(
        [
            {
                "specimen_id": "A",
                "value": {"sites": ["skin, left forearm"]},
                "document_id": "doc-report",
                "quoted": "this text does not appear anywhere in the report",
                "confidence": "high",
            }
        ]
    )
    with pytest.raises(ExtractionRejectedError):
        parse_facts(raw, case_01, FactType.SPECIMEN, "spec")


def test_one_bad_fact_rejects_the_whole_batch_even_with_good_facts_present(case_01):
    raw = json.dumps(
        [
            {
                "specimen_id": "A",
                "value": {"sites": ["skin, left forearm"]},
                "document_id": "doc-report",
                "quoted": "A. Skin, left forearm, shave biopsy",
                "confidence": "high",
            },
            {
                "specimen_id": "A",
                "value": {"sites": ["hallucinated"]},
                "document_id": "doc-report",
                "quoted": "text that is not in the document",
                "confidence": "low",
            },
        ]
    )
    with pytest.raises(ExtractionRejectedError):
        parse_facts(raw, case_01, FactType.SPECIMEN, "spec")


def test_missing_required_key_rejects(case_01):
    raw = json.dumps([{"specimen_id": "A", "value": {"sites": ["x"]}, "quoted": "x", "confidence": "high"}])
    with pytest.raises(ExtractionRejectedError):
        parse_facts(raw, case_01, FactType.SPECIMEN, "spec")


def test_bad_confidence_value_rejects(case_01):
    raw = json.dumps(
        [
            {
                "specimen_id": "A",
                "value": {"sites": ["skin, left forearm"]},
                "document_id": "doc-report",
                "quoted": "A. Skin, left forearm, shave biopsy",
                "confidence": "extremely sure",
            }
        ]
    )
    with pytest.raises(ExtractionRejectedError):
        parse_facts(raw, case_01, FactType.SPECIMEN, "spec")


def test_empty_array_is_valid_absence_of_facts(case_01):
    assert parse_facts("[]", case_01, FactType.STAIN, "stain") == []
