"""Round-trip tests for the HL7v2 and FHIR normalizers: both must produce
the same shape of canonical Case, and both must handle a structured
specimen list vs. a source that never supplies one.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from coding_agent.normalize import fhir, hl7v2
from coding_agent.normalize.case import (
    Absent,
    NarrativeKind,
    RequisitionMatchMethod,
    SourceFormat,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_hl7_two_specimens_round_trip():
    message = (FIXTURES / "hl7v2" / "case_two_specimens.hl7").read_text()
    case = hl7v2.parse_oru(message)

    assert case.accession_number == "S26-0042760"
    assert case.date_of_service == date(2026, 1, 15)
    assert case.source_format is SourceFormat.HL7V2

    assert case.specimens.is_present
    assert {s.specimen_id for s in case.specimens.value} == {"A", "B"}
    specimen_a = case.specimen("A")
    assert specimen_a.site.value == "Skin of left forearm"
    assert specimen_a.container_description.value == "Tissue"

    diagnosis = case.section(NarrativeKind.DIAGNOSIS).text.value
    assert "A. Skin, left forearm: compound nevus." in diagnosis
    assert "B. Skin, right shoulder: compound nevus." in diagnosis

    assert case.requisition.match_method is RequisitionMatchMethod.ACCESSION_NUMBER
    assert case.requisition.clinical_indication.value == "Rule out malignancy"
    assert case.requisition.ordering_provider_npi.value == "1234567890"


def test_hl7_no_specimens_leaves_specimens_absent_not_empty():
    message = (FIXTURES / "hl7v2" / "case_no_specimens.hl7").read_text()
    case = hl7v2.parse_oru(message)

    assert not case.specimens.is_present
    assert case.specimens.absent is Absent.NOT_SUPPLIED

    assert case.section(NarrativeKind.GROSS).text.absent is Absent.NOT_SUPPLIED
    assert case.section(NarrativeKind.DIAGNOSIS).text.value == "Benign nevus, skin."

    assert case.requisition.match_method is RequisitionMatchMethod.ACCESSION_NUMBER
    assert case.requisition.clinical_indication.absent is Absent.NOT_SUPPLIED


def test_hl7_missing_obr_raises():
    message = "MSH|^~\\&|LIS|SYNTHLAB|RECV|RECV|20260101000000||ORU^R01|MSG1|P|2.5.1"
    with pytest.raises(hl7v2.Hl7NormalizationError):
        hl7v2.parse_oru(message)


def test_fhir_two_specimens_round_trip():
    bundle = json.loads((FIXTURES / "fhir" / "case_two_specimens.json").read_text())
    case = fhir.parse_bundle(bundle)

    assert case.accession_number == "S26-0042762"
    assert case.date_of_service == date(2026, 1, 17)
    assert case.source_format is SourceFormat.FHIR_R4

    assert case.specimens.is_present
    assert {s.specimen_id for s in case.specimens.value} == {"A", "B"}
    specimen_b = case.specimen("B")
    assert specimen_b.site.value == "Skin of right shoulder"

    diagnosis = case.section(NarrativeKind.DIAGNOSIS).text.value
    assert "A. Skin, left forearm: compound nevus." in diagnosis
    assert "B. Skin, right shoulder: compound nevus." in diagnosis

    assert case.requisition.match_method is RequisitionMatchMethod.ACCESSION_NUMBER
    assert case.requisition.clinical_indication.value == "Rule out malignancy"
    assert case.requisition.ordering_provider_npi.value == "1234567890"


def test_fhir_no_specimens_leaves_specimens_absent_not_empty():
    bundle = json.loads((FIXTURES / "fhir" / "case_no_specimens.json").read_text())
    case = fhir.parse_bundle(bundle)

    assert not case.specimens.is_present
    assert case.specimens.absent is Absent.NOT_SUPPLIED
    assert case.requisition.match_method is RequisitionMatchMethod.UNMATCHED
    assert case.section(NarrativeKind.DIAGNOSIS).text.value == "Benign nevus, skin."


def test_fhir_missing_diagnostic_report_raises():
    with pytest.raises(fhir.FhirNormalizationError):
        fhir.parse_bundle({"resourceType": "Bundle", "type": "collection", "entry": []})


def test_hl7_and_fhir_agree_on_specimen_ids_for_the_same_case_shape():
    hl7_case = hl7v2.parse_oru((FIXTURES / "hl7v2" / "case_two_specimens.hl7").read_text())
    fhir_case = fhir.parse_bundle(json.loads((FIXTURES / "fhir" / "case_two_specimens.json").read_text()))

    hl7_ids = {s.specimen_id for s in hl7_case.specimens.value}
    fhir_ids = {s.specimen_id for s in fhir_case.specimens.value}
    assert hl7_ids == fhir_ids == {"A", "B"}
