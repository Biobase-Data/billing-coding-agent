"""Tests for normalize/free_text.py: header-based section splitting and
the free-text -> Case builder. Specimens must always come back Absent
here -- a bare report text has no structured accessioning specimen list
to assert otherwise."""

from __future__ import annotations

from datetime import date

import pytest

from coding_agent.normalize.case import Absent, NarrativeKind, SourceFormat
from coding_agent.normalize.free_text import (
    FreeTextNormalizationError,
    parse_report_text,
    split_sections,
)

REPORT = """\
SYNTHETIC PATHOLOGY ASSOCIATES
123 Lab Way, Anytown, ST 00000

Patient: TEST, SYNTHETIC   DOB: 01/01/1980
Accession #: S26-0099001   Date of Service: 01/20/2026

CLINICAL HISTORY:
Rash on bilateral upper extremities.

GROSS DESCRIPTION:
Received in formalin, two specimens labeled A and B.

MICROSCOPIC DESCRIPTION:
Sections show compound melanocytic proliferation.

DIAGNOSIS:
A. Skin, left forearm: compound nevus.
B. Skin, right shoulder: compound nevus.

Electronically signed by Jane Smith, MD
"""


def test_split_sections_finds_all_four_kinds():
    sections = split_sections(REPORT)
    assert set(sections) == {
        NarrativeKind.CLINICAL_HISTORY,
        NarrativeKind.GROSS,
        NarrativeKind.MICROSCOPIC,
        NarrativeKind.DIAGNOSIS,
    }
    assert sections[NarrativeKind.GROSS] == "Received in formalin, two specimens labeled A and B."
    assert "A. Skin, left forearm" in sections[NarrativeKind.DIAGNOSIS]
    assert "B. Skin, right shoulder" in sections[NarrativeKind.DIAGNOSIS]


def test_split_sections_ignores_letterhead_before_first_header():
    sections = split_sections(REPORT)
    for text in sections.values():
        assert "SYNTHETIC PATHOLOGY ASSOCIATES" not in text
        assert "Patient: TEST" not in text


def test_split_sections_strips_trailing_signature_boilerplate():
    sections = split_sections(REPORT)
    assert "Electronically signed by Jane Smith, MD" not in sections[NarrativeKind.DIAGNOSIS]
    assert sections[NarrativeKind.DIAGNOSIS] == (
        "A. Skin, left forearm: compound nevus.\nB. Skin, right shoulder: compound nevus."
    )


def test_split_sections_alternate_header_spellings():
    text = "FINAL DIAGNOSIS\nBenign.\n\nMICROSCOPIC EXAMINATION:\nUnremarkable.\n"
    sections = split_sections(text)
    assert sections[NarrativeKind.DIAGNOSIS] == "Benign."
    assert sections[NarrativeKind.MICROSCOPIC] == "Unremarkable."


def test_split_sections_returns_empty_for_unrecognized_headers_only():
    assert split_sections("SOME RANDOM REPORT\nNo recognizable headers here.\n") == {}


def test_parse_report_text_builds_case_with_specimens_absent():
    case = parse_report_text(
        REPORT,
        case_id="pdf-case-1",
        accession_number="S26-0099001",
        date_of_service=date(2026, 1, 20),
    )
    assert case.source_format is SourceFormat.MANUAL
    assert not case.specimens.is_present
    assert case.specimens.absent is Absent.NOT_SUPPLIED
    assert case.section(NarrativeKind.GROSS).text.value == (
        "Received in formalin, two specimens labeled A and B."
    )
    assert case.requisition.match_method.value == "unmatched"


def test_parse_report_text_missing_section_is_explicitly_absent():
    case = parse_report_text(
        "GROSS DESCRIPTION:\nOne specimen.\n",
        case_id="pdf-case-2",
        accession_number="S26-0099002",
        date_of_service=date(2026, 1, 20),
    )
    diagnosis = case.section(NarrativeKind.DIAGNOSIS)
    assert diagnosis is not None
    assert not diagnosis.text.is_present
    assert diagnosis.text.absent is Absent.NOT_SUPPLIED


def test_parse_report_text_rejects_text_with_no_recognized_sections():
    with pytest.raises(FreeTextNormalizationError):
        parse_report_text(
            "not a pathology report at all",
            case_id="pdf-case-3",
            accession_number="S26-0099003",
            date_of_service=date(2026, 1, 20),
        )


# A reconstruction of a real messy PDF's flattened text (disclaimer banner,
# CPT/ICD signature line, lab CLIA/legal boilerplate, an end-of-report
# marker, and trailing page/table artifacts) -- regression coverage for
# the boilerplate-stripping this module does before handing narrative
# text to the model.
MESSY_REAL_WORLD_REPORT = """\
CLINICAL HISTORY
***Please disregard this page! This is NOT the official report. Proceed to next page to view report. ***NG
Left shoulder mass.
GROSS DESCRIPTION
Received in formalin labeled "left shoulder mass" is a 13.5 x 9.5 x 5.5 cm piece of tissue.
ELECTRONIC SIGNATURE CPT CODE(S): ICD10 CODE(S):
Regional Pathology Associates 88304(1)
Screening Location:2701 Hospital Drive, Victoria, TX 77901
Note: The CPT codes provided are for information purposes only and are based on AMA Guidelines.
One or more analyte specific reagents may have been used to evaluate this case.
This test has not been cleared by the FDA and should not be regarded as investigational or for research.
This laboratory is certified under the Clinical Improvement Amendments of 1988 (CLIA) as qualified to
perform high complexity clinical laboratory testing.
Specimens Processed by Gastroenterology & Liver Associates PLLC. CLIA # 45D2020900 Ph: 713.783.4252
*** END OF REPORT ****
Page 1 of 1
2019
2019
MICROSCOPIC DESCRIPTION:
Microscopic examination was performed. The findings are included in the diagnosis rendered.
DIAGNOSIS:
Skin, left shoulder: lipoma.
"""


def test_split_sections_strips_disclaimer_banner():
    sections = split_sections(MESSY_REAL_WORLD_REPORT)
    assert "disregard this page" not in sections[NarrativeKind.CLINICAL_HISTORY].lower()
    assert sections[NarrativeKind.CLINICAL_HISTORY] == "Left shoulder mass."


def test_split_sections_strips_signature_and_lab_legal_boilerplate():
    sections = split_sections(MESSY_REAL_WORLD_REPORT)
    gross = sections[NarrativeKind.GROSS]
    for noise in (
        "CPT CODE(S)",
        "Screening Location",
        "information purposes only",
        "analyte specific reagent",
        "cleared by the FDA",
        "Clinical Improvement Amendments",
        "high complexity clinical laboratory testing",
        "Specimens Processed by",
        "CLIA #",
    ):
        assert noise not in gross


def test_split_sections_discards_everything_after_end_of_report_marker():
    sections = split_sections(MESSY_REAL_WORLD_REPORT)
    assert "diagnosis rendered" in sections[NarrativeKind.MICROSCOPIC]
    for section_text in sections.values():
        assert "Page 1 of 1" not in section_text
        assert "2019" not in section_text


def test_split_sections_keeps_genuine_diagnosis_text_after_all_the_noise():
    sections = split_sections(MESSY_REAL_WORLD_REPORT)
    assert sections[NarrativeKind.DIAGNOSIS] == "Skin, left shoulder: lipoma."
