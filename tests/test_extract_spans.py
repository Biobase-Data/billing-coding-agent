"""Tests for extract/spans.py's locate(): exact matching, the
whitespace-tolerant fallback (a real bug found via a live PDF upload --
a mid-sentence PDF line wrap survives as a literal newline in the
source text, but a model reproducing a "verbatim" quote normalizes it
to a plain space), and that evidence spans always carry the real source
substring, never the model's normalized one."""

from __future__ import annotations

from datetime import date

import pytest

from coding_agent.extract.spans import SpanNotFoundError, locate
from coding_agent.normalize.case import (
    Case,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
)


def make_case(gross_text: str) -> Case:
    return Case(
        case_id="case-x",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.MANUAL,
        source_document_id="S26-0001",
        narrative=(NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of(gross_text)),),
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )


def test_exact_match_is_still_the_fast_path():
    case = make_case("Received in formalin, a shave biopsy labeled A.")
    span = locate(case, section=NarrativeKind.GROSS, quoted="shave biopsy labeled A")
    assert span.quoted == "shave biopsy labeled A"
    assert span.start == case.section(NarrativeKind.GROSS).text.value.find("shave biopsy labeled A")


def test_whitespace_tolerant_match_across_a_pdf_line_wrap():
    """Reproduces the exact bug: pypdf preserves a mid-sentence PDF line
    wrap as a literal newline, but the model quoted the same text with a
    plain space instead."""
    source = (
        "an attached 12.5 x 2.5 cm excision of grossly unremarkable\n"
        "pink-tan skin. The external surface is inked blue."
    )
    case = make_case(source)
    model_quote = "excision of grossly unremarkable pink-tan skin"  # space, not \n

    span = locate(case, section=NarrativeKind.GROSS, quoted=model_quote)

    # the returned span's `quoted` is the REAL source substring
    # (newline included), never the model's normalized version --
    # otherwise Case.resolve_span's later re-slice-and-compare would
    # fail against this same evidence span.
    assert span.quoted == "excision of grossly unremarkable\npink-tan skin"
    assert source[span.start : span.end] == span.quoted


def test_whitespace_tolerant_match_handles_multiple_internal_spaces():
    case = make_case("Received in formalin,   a specimen labeled A.")
    span = locate(case, section=NarrativeKind.GROSS, quoted="a specimen labeled A")
    assert span.quoted == "a specimen labeled A"


def test_resolved_span_passes_case_resolve_span_after_whitespace_fallback():
    source = "excision of grossly unremarkable\npink-tan skin. More text follows."
    case = make_case(source)
    span = locate(case, section=NarrativeKind.GROSS, quoted="excision of grossly unremarkable pink-tan skin")
    assert case.resolve_span(span) == span.quoted


def test_non_whitespace_differences_are_not_tolerated():
    """The fallback only bridges whitespace -- a genuinely different
    word must still fail, not be silently accepted."""
    case = make_case("Received in formalin, a shave biopsy labeled A.")
    with pytest.raises(SpanNotFoundError):
        locate(case, section=NarrativeKind.GROSS, quoted="a punch biopsy labeled A")


def test_missing_section_raises():
    case = make_case("some gross text")
    with pytest.raises(SpanNotFoundError):
        locate(case, section=NarrativeKind.DIAGNOSIS, quoted="anything")


def test_absent_text_raises():
    from coding_agent.normalize.case import Absent

    case = Case(
        case_id="case-x",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.MANUAL,
        source_document_id="S26-0001",
        narrative=(NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.missing(Absent.NOT_SUPPLIED)),),
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )
    with pytest.raises(SpanNotFoundError):
        locate(case, section=NarrativeKind.GROSS, quoted="anything")
