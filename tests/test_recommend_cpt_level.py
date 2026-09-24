"""Tests for recommend/cpt_level.py: recommended-vs-baseline CPT level
findings, bidirectional by construction (a single call can propose
adding a level for an unbilled specimen and a different, lower level
for an over-billed one)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from coding_agent.extract.schema import (
    Abstention,
    AbstentionReason,
    ExtractionMetadata,
    ProcedureTypeExtraction,
    ProcedureTypeMention,
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
from coding_agent.recommend.cpt_level import build_cpt_level_recommendation
from coding_agent.recommend.schema import BaselineLine, BlockedReason

METADATA = ExtractionMetadata(model_version="test-model", prompt_version="procedure_type_v1")


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


def specimen(specimen_id: str, site: str | None) -> Specimen:
    return Specimen(
        specimen_id=specimen_id,
        source_field=SpecimenSourceField.SPM,
        site=Maybe.of(site) if site is not None else Maybe.missing(Absent.NOT_SUPPLIED),
    )


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


def mention(label: str, procedure_type: str) -> ProcedureTypeMention:
    return ProcedureTypeMention(label=label, procedure_type=procedure_type, evidence=evidence_for(label))


def test_addition_when_no_baseline_code_exists_for_the_specimen():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.blocked is None
    assert len(rec.findings) == 1
    finding = rec.findings[0]
    assert finding.specimen_id == "A"
    assert finding.recommended_code == "88305"
    assert finding.baseline_code is None
    assert finding.evidence  # positive evidence always required here


def test_change_when_baseline_code_disagrees():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)
    baseline = (BaselineLine(code="88304", units=1, specimen_id="A"),)

    rec = build_cpt_level_recommendation(case, extraction, baseline=baseline)

    assert len(rec.findings) == 1
    finding = rec.findings[0]
    assert finding.baseline_code == "88304"
    assert finding.recommended_code == "88305"


def test_agreement_produces_no_finding():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)
    baseline = (BaselineLine(code="88305", units=1, specimen_id="A"),)

    rec = build_cpt_level_recommendation(case, extraction, baseline=baseline)

    assert rec.findings == ()
    assert rec.unaddressed_specimen_ids == ()
    assert rec.blocked is None


def test_bidirectional_single_call_can_both_add_and_change_at_once():
    """One call, two specimens: A has no baseline code (addition
    direction), B's baseline code is wrong (change direction, and here
    specifically a downgrade -- proving this path is not additions-only)."""
    case = make_case(
        specimens=Maybe.of(
            (specimen("A", "Skin of left forearm"), specimen("B", "Skin of right shoulder"))
        )
    )
    extraction = ProcedureTypeExtraction(
        mentions=(mention("A", "biopsy"), mention("B", "biopsy")), metadata=METADATA
    )
    baseline = (BaselineLine(code="88307", units=1, specimen_id="B"),)

    rec = build_cpt_level_recommendation(case, extraction, baseline=baseline)

    by_specimen = {f.specimen_id: f for f in rec.findings}
    assert by_specimen["A"].baseline_code is None
    assert by_specimen["A"].recommended_code == "88305"
    assert by_specimen["B"].baseline_code == "88307"
    assert by_specimen["B"].recommended_code == "88305"


def test_specimen_with_no_matching_mention_is_unaddressed_not_silently_skipped():
    case = make_case(
        specimens=Maybe.of(
            (specimen("A", "Skin of left forearm"), specimen("B", "Skin of right shoulder"))
        )
    )
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.unaddressed_specimen_ids == ("B",)
    assert {f.specimen_id for f in rec.findings} == {"A"}


def test_unmapped_procedure_type_site_combination_is_unaddressed():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "excision"),), metadata=METADATA)

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.unaddressed_specimen_ids == ("A",)
    assert rec.findings == ()


def test_absent_site_is_unaddressed():
    case = make_case(specimens=Maybe.of((specimen("A", None),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.unaddressed_specimen_ids == ("A",)


def test_extraction_abstention_blocks_without_guessing():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(
        abstention=Abstention(reason=AbstentionReason.AMBIGUOUS_NARRATIVE, detail="unclear"),
        metadata=METADATA,
    )

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.findings == ()
    assert rec.blocked is not None
    assert rec.blocked.reason is BlockedReason.EXTRACTION_ABSTAINED


def test_absent_accessioning_specimen_list_blocks_without_guessing():
    case = make_case(specimens=Maybe.missing(Absent.NOT_RETRIEVABLE))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)

    rec = build_cpt_level_recommendation(case, extraction, baseline=())

    assert rec.findings == ()
    assert rec.blocked is not None
    assert rec.blocked.reason is BlockedReason.ACCESSIONING_SPECIMEN_LIST_ABSENT


def test_baseline_line_without_specimen_id_is_never_matched():
    """A baseline line with no specimen_id (e.g. from the unit-
    reconciliation capability, which never sets it) must not
    accidentally satisfy this capability's per-specimen lookup."""
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)
    baseline = (BaselineLine(code="88305", units=1),)  # no specimen_id

    rec = build_cpt_level_recommendation(case, extraction, baseline=baseline)

    assert len(rec.findings) == 1
    assert rec.findings[0].baseline_code is None


def test_cpt_level_finding_is_frozen():
    case = make_case(specimens=Maybe.of((specimen("A", "Skin of left forearm"),)))
    extraction = ProcedureTypeExtraction(mentions=(mention("A", "biopsy"),), metadata=METADATA)
    rec = build_cpt_level_recommendation(case, extraction, baseline=())
    with pytest.raises(ValidationError):
        rec.findings[0].recommended_code = "88999"  # type: ignore[misc]
