"""Tests for extract/specimens.py: evidence-span verification, abstention
(both model-declared and the no-narrative short circuit), and rejection
of untrustworthy model output."""

from __future__ import annotations

import json
from datetime import date

import pytest

from coding_agent.extract.schema import AbstentionReason
from coding_agent.extract.specimens import (
    SpecimenExtractionRejectedError,
    extract_specimen_mentions,
)
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
    """A client that raises if called -- used to prove a code path never
    reaches the model."""

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
    gross_text = "Received in formalin, two specimens labeled A and B."
    dx_text = "A. Skin, left forearm: compound nevus.\nB. Skin, right shoulder: compound nevus."
    return make_case(
        (
            NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of(gross_text)),
            NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of(dx_text)),
        )
    )


def test_extracts_two_mentions_with_evidence():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {"label": "A", "section": "gross", "quoted": "two specimens labeled A and B"},
                {"label": "A", "section": "diagnosis", "quoted": "A. Skin, left forearm"},
                {"label": "B", "section": "diagnosis", "quoted": "B. Skin, right shoulder"},
            ],
        }
    )
    extraction, metrics = extract_specimen_mentions(case, client=FakeClient(response))

    assert not extraction.abstained
    assert metrics is not None
    labels = {m.label for m in extraction.mentions}
    assert labels == {"A", "B"}

    mention_a = next(m for m in extraction.mentions if m.label == "A")
    assert len(mention_a.evidence) == 2  # supported in both gross and diagnosis
    assert {span.section for span in mention_a.evidence} == {
        NarrativeKind.GROSS,
        NarrativeKind.DIAGNOSIS,
    }


def test_model_declared_abstention_is_returned_not_swallowed():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": True,
            "reason": "ambiguous_narrative",
            "detail": "labeling scheme is inconsistent across sections",
            "mentions": [],
        }
    )
    extraction, metrics = extract_specimen_mentions(case, client=FakeClient(response))

    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.AMBIGUOUS_NARRATIVE
    assert metrics is not None  # the model *was* called before it abstained


def test_no_narrative_text_abstains_without_calling_the_model():
    case = make_case((NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.missing(Absent.NOT_SUPPLIED)),))
    extraction, metrics = extract_specimen_mentions(case, client=ExplodingClient())

    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.SECTION_ABSENT
    assert metrics is None


def test_hallucinated_quote_rejects_the_whole_batch():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {"label": "A", "section": "gross", "quoted": "this text is not in the report"}
            ],
        }
    )
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(case, client=FakeClient(response))


def test_malformed_json_rejects():
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(two_specimen_case(), client=FakeClient("not json"))


def test_unrecognized_section_rejects():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [{"label": "A", "section": "impression", "quoted": "A."}],
        }
    )
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(case, client=FakeClient(response))


def test_empty_mentions_without_abstain_is_a_valid_zero_specimen_result():
    case = make_case(
        (NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of("No lesion identified.")),)
    )
    response = json.dumps({"abstain": False, "mentions": []})
    extraction, _ = extract_specimen_mentions(case, client=FakeClient(response))
    assert not extraction.abstained
    assert extraction.mentions == ()
