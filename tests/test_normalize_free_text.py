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


def test_split_sections_folds_trailing_signature_into_last_open_section():
    sections = split_sections(REPORT)
    assert "Electronically signed by Jane Smith, MD" in sections[NarrativeKind.DIAGNOSIS]


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
