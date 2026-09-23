"""Tests for recommend/assemble.py: bidirectionality is the load-bearing
invariant here -- a single call must be able to emit both ADDITION and
REMOVAL lines, never only one direction."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from coding_agent.extract.schema import (
    Abstention,
    AbstentionReason,
    ExtractionMetadata,
    SpecimenExtraction,
    SpecimenMention,
)
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
from coding_agent.recommend.assemble import build_recommendation
from coding_agent.recommend.schema import (
    BaselineLine,
    BlockedReason,
    DiffKind,
    RecommendationLine,
)

METADATA = ExtractionMetadata(model_version="test-model", prompt_version="specimens_v1")


def make_case(specimens, narrative=()) -> Case:
    return Case(
        case_id="case-1",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.HL7V2,
        source_document_id="S26-0001",
        specimens=specimens,
        narrative=narrative
        or (NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of("placeholder")),),
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )


def specimen(specimen_id: str) -> Specimen:
    return Specimen(specimen_id=specimen_id, source_field=SpecimenSourceField.SPM)


def evidence_for(label: str) -> tuple[EvidenceSpan, ...]:
    return (
        EvidenceSpan(
            document_id="S26-0001",
            section=NarrativeKind.DIAGNOSIS,
            start=0,
            end=len(label),
            quoted=label,
        ),
    )


def test_bidirectional_single_call_emits_both_addition_and_removal():
    """B was billed/accessioned but never described (removal candidate);
    C was described but never accessioned (addition candidate). One call
    to build_recommendation surfaces both -- there is no toggle that
    selects only one direction."""
    case = make_case(specimens=Maybe.of((specimen("A"), specimen("B"))))
    extraction = SpecimenExtraction(
        mentions=(
            SpecimenMention(label="A", evidence=evidence_for("A")),
            SpecimenMention(label="C", evidence=evidence_for("C")),
        ),
        metadata=METADATA,
    )

    rec = build_recommendation(case, extraction, baseline=(), primary_code="88305")

    assert rec.blocked is None
    kinds = {line.diff_kind for line in rec.lines}
    assert kinds == {DiffKind.REMOVAL, DiffKind.ADDITION}

    removal = next(line for line in rec.lines if line.diff_kind is DiffKind.REMOVAL)
    assert removal.specimen_id == "B"
    assert removal.evidence == ()

    addition = next(line for line in rec.lines if line.diff_kind is DiffKind.ADDITION)
    assert addition.specimen_id == "C"
    assert addition.evidence  # must carry the supporting quote


def test_full_agreement_produces_no_lines():
    case = make_case(specimens=Maybe.of((specimen("A"), specimen("B"))))
    extraction = SpecimenExtraction(
        mentions=(
            SpecimenMention(label="A", evidence=evidence_for("A")),
            SpecimenMention(label="B", evidence=evidence_for("B")),
        ),
        metadata=METADATA,
    )
    rec = build_recommendation(case, extraction, baseline=(), primary_code="88305")
    assert rec.lines == ()
    assert rec.blocked is None


def test_extraction_abstention_blocks_without_guessing():
    case = make_case(specimens=Maybe.of((specimen("A"),)))
    extraction = SpecimenExtraction(
        abstention=Abstention(reason=AbstentionReason.AMBIGUOUS_NARRATIVE, detail="unclear"),
        metadata=METADATA,
    )
    rec = build_recommendation(case, extraction, baseline=(), primary_code="88305")
    assert rec.lines == ()
    assert rec.blocked is not None
    assert rec.blocked.reason is BlockedReason.EXTRACTION_ABSTAINED


def test_absent_accessioning_specimen_list_blocks_without_guessing():
    case = make_case(specimens=Maybe.missing(Absent.NOT_RETRIEVABLE))
    extraction = SpecimenExtraction(
        mentions=(SpecimenMention(label="A", evidence=evidence_for("A")),), metadata=METADATA
    )
    rec = build_recommendation(case, extraction, baseline=(), primary_code="88305")
    assert rec.lines == ()
    assert rec.blocked is not None
    assert rec.blocked.reason is BlockedReason.ACCESSIONING_SPECIMEN_LIST_ABSENT


def test_addition_line_without_evidence_is_rejected():
    with pytest.raises(ValidationError):
        RecommendationLine(
            code="88305",
            diff_kind=DiffKind.ADDITION,
            specimen_id="C",
            evidence=(),
            rationale="should have evidence but doesn't",
        )


def test_removal_line_with_evidence_is_rejected():
    with pytest.raises(ValidationError):
        RecommendationLine(
            code="88305",
            diff_kind=DiffKind.REMOVAL,
            specimen_id="B",
            evidence=evidence_for("B"),
            rationale="should not carry evidence",
        )


def test_recommendation_rejects_lines_alongside_blocked():
    from coding_agent.recommend.schema import Blocked, Recommendation

    with pytest.raises(ValidationError):
        Recommendation(
            case_id="case-1",
            baseline=(),
            lines=(
                RecommendationLine(
                    code="88305",
                    diff_kind=DiffKind.REMOVAL,
                    specimen_id="B",
                    evidence=(),
                    rationale="x",
                ),
            ),
            blocked=Blocked(reason=BlockedReason.EXTRACTION_ABSTAINED, detail="x"),
        )


def test_baseline_passes_through_unchanged():
    case = make_case(specimens=Maybe.of((specimen("A"),)))
    extraction = SpecimenExtraction(
        mentions=(SpecimenMention(label="A", evidence=evidence_for("A")),), metadata=METADATA
    )
    baseline = (BaselineLine(code="88305", units=1),)
    rec = build_recommendation(case, extraction, baseline=baseline, primary_code="88305")
    assert rec.baseline == baseline
