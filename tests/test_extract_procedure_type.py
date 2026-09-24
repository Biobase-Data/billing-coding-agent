"""Tests for extract/procedure_type.py: evidence-span verification,
abstention, label-grouping/contradiction detection, and rejection of
untrustworthy model output -- the same rigor as test_extract_specimens.py,
adapted for this task's own schema."""

from __future__ import annotations

import json
from datetime import date

import pytest

from coding_agent.extract.procedure_type import (
    ProcedureTypeExtractionRejectedError,
    extract_procedure_types,
)
from coding_agent.extract.schema import AbstentionReason
from coding_agent.normalize.case import (
    Absent,
    Case,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
)


class FakeClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        self.calls += 1
        return self.response_text, 100, 50


class ExplodingClient:
    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        raise AssertionError("model should not have been called")


def make_case(narrative: tuple[NarrativeSection, ...]) -> Case:
    return Case(
        case_id="case-x",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.HL7V2,
        source_document_id="S26-0001",
        specimens=Maybe.missing(Absent.NOT_SUPPLIED),
        narrative=narrative,
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )


def two_specimen_case() -> Case:
    gross_text = "Received in formalin, a shave biopsy labeled A and a punch biopsy labeled B."
    dx_text = "A. Skin, left forearm: compound nevus.\nB. Skin, right shoulder: compound nevus."
    return make_case(
        (
            NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of(gross_text)),
            NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of(dx_text)),
        )
    )


def test_extracts_procedure_types_with_evidence():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "a shave biopsy labeled A",
                },
                {
                    "label": "B",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "a punch biopsy labeled B",
                },
            ],
        }
    )
    extraction, metrics = extract_procedure_types(case, client=FakeClient(response))

    assert not extraction.abstained
    assert metrics is not None
    by_label = {m.label: m for m in extraction.mentions}
    assert by_label["A"].procedure_type == "biopsy"
    assert by_label["B"].procedure_type == "biopsy"
    assert by_label["A"].evidence[0].quoted == "a shave biopsy labeled A"


def test_merges_multiple_evidence_spans_for_the_same_consistent_label():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "a shave biopsy labeled A",
                },
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "diagnosis",
                    "quoted": "A. Skin, left forearm",
                },
            ],
        }
    )
    extraction, _ = extract_procedure_types(case, client=FakeClient(response))
    assert len(extraction.mentions) == 1
    assert len(extraction.mentions[0].evidence) == 2


def test_contradictory_procedure_types_for_the_same_label_are_rejected():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "a shave biopsy labeled A",
                },
                {
                    "label": "A",
                    "procedure_type": "excision",
                    "section": "diagnosis",
                    "quoted": "A. Skin, left forearm",
                },
            ],
        }
    )
    with pytest.raises(ProcedureTypeExtractionRejectedError):
        extract_procedure_types(case, client=FakeClient(response))


def test_model_declared_abstention_is_returned_not_swallowed():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": True,
            "reason": "ambiguous_narrative",
            "detail": "cannot tell how each specimen was obtained",
            "mentions": [],
        }
    )
    extraction, metrics = extract_procedure_types(case, client=FakeClient(response))
    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.AMBIGUOUS_NARRATIVE
    assert metrics is not None


def test_no_narrative_text_abstains_without_calling_the_model():
    case = make_case((NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.missing(Absent.NOT_SUPPLIED)),))
    extraction, metrics = extract_procedure_types(case, client=ExplodingClient())
    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.SECTION_ABSENT
    assert metrics is None


def test_hallucinated_quote_rejects_the_whole_batch():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "this text is not in the report",
                }
            ],
        }
    )
    with pytest.raises(ProcedureTypeExtractionRejectedError):
        extract_procedure_types(case, client=FakeClient(response))


def test_malformed_json_rejects():
    with pytest.raises(ProcedureTypeExtractionRejectedError):
        extract_procedure_types(two_specimen_case(), client=FakeClient("not json"))


def test_unrecognized_section_rejects():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {"label": "A", "procedure_type": "biopsy", "section": "impression", "quoted": "A."}
            ],
        }
    )
    with pytest.raises(ProcedureTypeExtractionRejectedError):
        extract_procedure_types(case, client=FakeClient(response))


def test_empty_mentions_without_abstain_is_valid_when_narrative_names_no_procedure_types():
    case = make_case(
        (NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of("No lesion identified.")),)
    )
    response = json.dumps({"abstain": False, "mentions": []})
    extraction, _ = extract_procedure_types(case, client=FakeClient(response))
    assert not extraction.abstained
    assert extraction.mentions == ()


def test_can_omit_one_specimen_while_reporting_another():
    """The prompt explicitly allows partial coverage: naming a
    procedure type for A but not B is not the same as abstaining for
    the whole case."""
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "biopsy",
                    "section": "gross",
                    "quoted": "a shave biopsy labeled A",
                }
            ],
        }
    )
    extraction, _ = extract_procedure_types(case, client=FakeClient(response))
    assert not extraction.abstained
    assert {m.label for m in extraction.mentions} == {"A"}


def test_prompt_distinguishes_cassette_ids_from_specimen_labels():
    """Same regression coverage as
    test_extract_specimens.test_prompt_distinguishes_cassette_ids_from_specimen_labels
    -- this task shares the same "label" concept and the same real bug
    (see ASSUMPTIONS.md #13), from a separate model call over the same
    narrative."""
    from coding_agent.extract.procedure_type import PROMPTS_DIR, PROMPT_FILE

    prompt_text = (PROMPTS_DIR / PROMPT_FILE).read_text()
    assert "cassette" in prompt_text.lower()
