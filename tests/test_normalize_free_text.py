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


def test_split_sections_strips_raw_billed_code_stamp_with_no_label():
    """Regression coverage for a real live finding: a code-with-unit
    stamp like "Regional Pathology Associates 88304(1)" was leaking
    straight into the GROSS section because it carries no "CPT
    CODE(S):" label for the existing pattern to catch -- just the raw
    digits. extract/ must never see a billing code, labeled or not."""
    sections = split_sections(MESSY_REAL_WORLD_REPORT)
    gross = sections[NarrativeKind.GROSS]
    assert "88304" not in gross
    assert "Regional Pathology Associates" not in gross


def test_split_sections_strips_a_multi_code_billed_stamp_line():
    report = (
        "CLINICAL HISTORY\n"
        "Colonic polyps.\n"
        "GROSS DESCRIPTION\n"
        "Received in formalin, one specimen labeled A.\n"
        "Regional Pathology Associates 88307(1), 88309(1), 88342(3), 88341(21)\n"
        "DIAGNOSIS\n"
        "A. Colon, polyp: tubular adenoma.\n"
    )
    sections = split_sections(report)
    assert "88307" not in sections[NarrativeKind.GROSS]
    assert sections[NarrativeKind.GROSS] == "Received in formalin, one specimen labeled A."


# A real signed-out report's flattened text (pypdf-extracted, page breaks
# joined with "\n" exactly as api/app.py does), reproduced verbatim.
# Regression coverage for a real live finding: this report's actual
# specimen label ("Specimen A") and its entire final diagnosis
# (malignant melanoma, with staging) were being silently discarded --
# not stripped as boilerplate, just dropped -- because its section
# headers ("SPECIMEN RECEIVED", "CLINICAL HISTORY / PRE-OPERATIVE
# DIAGNOSIS", "FINAL PATHOLOGIC DIAGNOSIS") didn't exactly match any
# entry in _HEADER_TO_NARRATIVE_KIND. The abstention a coder saw
# downstream ("no distinct specimen labels given") was correct given
# what the model was shown, but the model was shown a mutilated report:
# this is the "silent normalization degradation" failure mode the
# strategy doc warns about, not a genuinely ambiguous narrative.
REAL_MELANOMA_REPORT = """\
APEX METROPOLITAN MEDICAL CENTER
 DEPARTMENT OF PATHOLOGY & LABORATORY MEDICINE
 100 Medical Plaza, Suite 400 | Tel: (555) 019-2834
Patient Name:
Doe, Jane
Accession No:
SP-26-9876
DOB:
05/12/1980
Medical Record #:
MRN-774-921
Gender:
Female
Facility:
Apex Memorial Hospital
Date of
Collection:
09/18/2026
Ordering Physician:
Dr. Robert Smith, M.D.
Date of Receipt:
09/18/2026
Report Status:
FINAL
CLINICAL HISTORY / PRE-OPERATIVE DIAGNOSIS
Left forearm skin lesion, irregular borders and progressive color changes over the past 3 months. Rule out malignant
melanoma vs. dysplastic nevus.
SPECIMEN RECEIVED
Specimen A: Left forearm lesion
FINAL PATHOLOGIC DIAGNOSIS
SKIN, LEFT FOREARM, EXCISION:
— SUPERFICIAL SPREADING MALIGNANT MELANOMA, INVASIVE.
— BRESLOW THICKNESS: 0.45 MM.
— CLARK LEVEL: II.
— ULCERATION: ABSENT.
— MITOTIC RATE: 1 / MM².
— PERIPHERAL AND DEEP SURGICAL MARGINS ARE NEGATIVE FOR MALIGNANCY (CLOSEST PERIPHERAL
MARGIN IS 3.0 MM).
GROSS DESCRIPTION
Received in formal fixation, labeled with the patient's name and 'left forearm lesion,' is an elliptical fragment of skin
measuring 1.5 x 0.8 x 0.4 cm. The epithelial surface exhibits an asymmetrical, irregular, tan-brown to black pigmented
flat lesion measuring 0.6 cm in its greatest dimension. The lesion is located 0.3 cm from the nearest peripheral surgical
margin. Cross sectioning reveals a flat macule with no deep dermal extension visible macroscopically. The deep margin
is inked black, and the peripheral margins are inked green. The specimen is serially sectioned and entirely submitted in
cassette A1.
MICROSCOPIC DESCRIPTION

Sections of block A1 demonstrate an asymmetrical, poorly circumscribed melanocytic proliferation arranged singly and
in nests along the dermal-epidermal junction. Marked cytologic atypia is noted, with melanocytes exhibiting enlarged,
hyperchromatic nuclei, prominent irregular nucleoli, and frequent pagetoid ascent into the higher levels of the stratum
spinosum. In the papillary dermis, small clusters of atypical melanocytes are noted, confirming microinvasion. The
maximum thickness of the invasive component (Breslow Thickness) is measured manually using an ocular micrometer
as 0.45 mm from the granular cell layer. No ulceration or lymphovascular invasion is detected. The deep surgical
margin and all peripheral margins are completely clear of atypical melanocytic proliferation.
Electronically Signed By:
Dr. Jonathan Vance, M.D., FCAP
Board Certified Pathologist
Sign-off Date/Time: 09/20/2026 14:22 CDT
 This is for informational purposes only. For medical advice or diagnosis, consult a professional. AI responses may include mistakes.
"""


def test_split_sections_no_longer_drops_clinical_history_with_a_compound_header():
    sections = split_sections(REAL_MELANOMA_REPORT)
    assert "Rule out malignant" in sections[NarrativeKind.CLINICAL_HISTORY]


def test_split_sections_recognizes_specimen_received_and_keeps_the_real_label():
    sections = split_sections(REAL_MELANOMA_REPORT)
    assert "Specimen A: Left forearm lesion" in sections[NarrativeKind.GROSS]


def test_split_sections_recognizes_final_pathologic_diagnosis_header():
    sections = split_sections(REAL_MELANOMA_REPORT)
    assert "MALIGNANT MELANOMA" in sections[NarrativeKind.DIAGNOSIS]


def test_split_sections_strips_signing_pathologist_credential_and_disclaimer_lines():
    sections = split_sections(REAL_MELANOMA_REPORT)
    microscopic = sections[NarrativeKind.MICROSCOPIC]
    for noise in (
        "Dr. Jonathan Vance",
        "Board Certified Pathologist",
        "Sign-off Date",
        "informational purposes only",
        "AI responses may include mistakes",
    ):
        assert noise not in microscopic
    assert "melanocytic proliferation" in microscopic
