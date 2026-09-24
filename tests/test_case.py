"""Sanity tests for the canonical Case object: the Maybe/Absent contract,
evidence-span resolution and drift detection, and narrative-kind uniqueness.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from coding_agent.normalize.case import (
    Absent,
    Case,
    EvidenceSpan,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
    Specimen,
    SpecimenSourceField,
)


def make_case(**overrides) -> Case:
    defaults = dict(
        case_id="case-0001",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 15),
        source_format=SourceFormat.HL7V2,
        source_document_id="doc-1",
        specimens=Maybe.of(
            (
                Specimen(specimen_id="A", source_field=SpecimenSourceField.SPM),
                Specimen(specimen_id="B", source_field=SpecimenSourceField.SPM),
            )
        ),
        narrative=(
            NarrativeSection(
                kind=NarrativeKind.DIAGNOSIS,
                text=Maybe.of("A. Skin, left arm: compound nevus."),
            ),
        ),
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )
    defaults.update(overrides)
    return Case(**defaults)


def test_maybe_requires_exactly_one_of_value_or_absent():
    with pytest.raises(ValidationError):
        Maybe(value="x", absent=Absent.EMPTY)
    with pytest.raises(ValidationError):
        Maybe()


def test_maybe_is_present():
    assert Maybe.of("x").is_present
    assert not Maybe.missing(Absent.NOT_SUPPLIED).is_present


def test_case_specimen_lookup():
    case = make_case()
    assert case.specimen("A") is not None
    assert case.specimen("Z") is None


def test_case_with_specimens_not_supplied_has_no_lookup_results():
    case = make_case(specimens=Maybe.missing(Absent.NOT_RETRIEVABLE))
    assert case.specimen("A") is None
    assert not case.specimens.is_present
    assert case.specimens.absent is Absent.NOT_RETRIEVABLE


def test_narrative_rejects_duplicate_kind():
    with pytest.raises(ValidationError):
        make_case(
            narrative=(
                NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of("a")),
                NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of("b")),
            )
        )


def test_resolve_span_round_trip():
    case = make_case()
    text = case.section(NarrativeKind.DIAGNOSIS).text.value
    start = text.index("compound nevus")
    span = EvidenceSpan(
        document_id="doc-1",
        section=NarrativeKind.DIAGNOSIS,
        start=start,
        end=start + len("compound nevus"),
        quoted="compound nevus",
    )
    assert case.resolve_span(span) == "compound nevus"


def test_resolve_span_detects_drift():
    case = make_case()
    span = EvidenceSpan(
        document_id="doc-1",
        section=NarrativeKind.DIAGNOSIS,
        start=0,
        end=1,
        quoted="X",  # does not match the real character at offset 0
    )
    with pytest.raises(ValueError, match="evidence span has drifted"):
        case.resolve_span(span)


def test_resolve_span_rejects_wrong_document():
    case = make_case()
    span = EvidenceSpan(
        document_id="some-other-doc",
        section=NarrativeKind.DIAGNOSIS,
        start=0,
        end=1,
        quoted="A",
    )
    with pytest.raises(ValueError, match="case source document is"):
        case.resolve_span(span)


def test_resolve_span_rejects_absent_section_text():
    case = make_case(
        narrative=(NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.missing(Absent.NOT_SUPPLIED)),)
    )
    span = EvidenceSpan(
        document_id="doc-1", section=NarrativeKind.GROSS, start=0, end=1, quoted="x"
    )
    with pytest.raises(ValueError, match="section text is absent"):
        case.resolve_span(span)


def test_evidence_span_length_must_match_quoted_text():
    with pytest.raises(ValidationError):
        EvidenceSpan(
            document_id="doc-1", section=NarrativeKind.GROSS, start=0, end=5, quoted="ab"
        )


def test_requisition_confidence_only_for_fuzzy_match():
    with pytest.raises(ValidationError):
        Requisition(
            match_method=RequisitionMatchMethod.ACCESSION_NUMBER,
            match_confidence=0.9,
        )
    # fuzzy match with confidence is fine
    Requisition(match_method=RequisitionMatchMethod.FUZZY_NAME_DOB, match_confidence=0.72)


def test_case_is_frozen():
    case = make_case()
    with pytest.raises(ValidationError):
        case.case_id = "different"  # type: ignore[misc]
