"""FHIR R4 (DiagnosticReport / Specimen / Observation / ServiceRequest)
-> canonical Case.

Takes an already-decoded Bundle (a `dict`, as produced by any standard
JSON client), not raw JSON text -- decoding is the caller's concern.

Scope and known limitations (V0):

- Assumes exactly one `DiagnosticReport` per bundle. A bundle representing
  more than one report is out of scope for this parser; split it upstream.
- Narrative sections come from `Observation` resources referenced by
  `DiagnosticReport.result`, matched to a `NarrativeKind` by
  `code.text`/`code.coding[].display`. Only `valueString` observations are
  read; an Observation carrying a `valueCodeableConcept` or `component[]`
  for narrative text is not supported yet.
- The clinical indication and ordering provider are read from the
  `ServiceRequest` resolved via `DiagnosticReport.basedOn`, so -- as with
  the HL7 parser -- the resulting `Requisition` is always
  `ACCESSION_NUMBER`-matched by construction. No separate paper-requisition
  ingestion path exists in V0.
- No PHI (Patient resource fields) is read into the canonical Case.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .case import (
    Absent,
    Case,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
    Specimen,
    SpecimenSourceField,
)

_OBSERVATION_CODE_TO_NARRATIVE_KIND: dict[str, NarrativeKind] = {
    "clinical history": NarrativeKind.CLINICAL_HISTORY,
    "clinical indication": NarrativeKind.CLINICAL_HISTORY,
    "gross description": NarrativeKind.GROSS,
    "gross": NarrativeKind.GROSS,
    "microscopic description": NarrativeKind.MICROSCOPIC,
    "microscopic": NarrativeKind.MICROSCOPIC,
    "diagnosis": NarrativeKind.DIAGNOSIS,
    "final diagnosis": NarrativeKind.DIAGNOSIS,
}


class FhirNormalizationError(Exception):
    """A required field could not be found or parsed. Raised only for
    fields the canonical Case requires outright."""


def _resource_index(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if not resource:
            continue
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if resource_type and resource_id:
            index[f"{resource_type}/{resource_id}"] = resource
    return index


def _resolve(index: dict[str, dict[str, Any]], reference: dict[str, Any] | None) -> dict[str, Any] | None:
    if not reference:
        return None
    ref = reference.get("reference")
    if not ref:
        return None
    return index.get(ref)


def _first(bundle: dict[str, Any], resource_type: str) -> dict[str, Any] | None:
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if resource and resource.get("resourceType") == resource_type:
            return resource
    return None


def _codeable_concept_text(concept: dict[str, Any] | None) -> str | None:
    if not concept:
        return None
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return None


def _identifier_value(resource: dict[str, Any], *, system_contains: str | None = None) -> str | None:
    identifiers = resource.get("identifier") or []
    if system_contains is not None:
        for identifier in identifiers:
            system = (identifier.get("system") or "").lower()
            if system_contains.lower() in system and identifier.get("value"):
                return identifier["value"]
    for identifier in identifiers:
        if identifier.get("value"):
            return identifier["value"]
    return None


def _maybe_str(value: str | None) -> Maybe[str]:
    if value is None:
        return Maybe.missing(Absent.NOT_SUPPLIED)
    if value == "":
        return Maybe.missing(Absent.EMPTY)
    return Maybe.of(value)


def _parse_date(value: str) -> date:
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return date.fromisoformat(value[:10])


def _parse_specimens(
    report: dict[str, Any], index: dict[str, dict[str, Any]]
) -> Maybe[tuple[Specimen, ...]]:
    if "specimen" not in report:
        return Maybe.missing(Absent.NOT_SUPPLIED)

    specimens: list[Specimen] = []
    for ref in report.get("specimen", []):
        resource = _resolve(index, ref)
        if resource is None:
            continue
        # `identifier[]` carries the specimen's own id (e.g. "A"), distinct
        # from the case-level `accessionIdentifier` some LIS also stamp
        # onto the Specimen resource -- we deliberately do not read that
        # field here, since it would collapse every specimen in the case
        # to the same identifier.
        specimen_id = _identifier_value(resource) or resource.get("id")
        if not specimen_id:
            continue
        collection = resource.get("collection", {})
        site = _codeable_concept_text(collection.get("bodySite"))
        container = _codeable_concept_text(resource.get("type"))
        specimens.append(
            Specimen(
                specimen_id=specimen_id,
                source_field=SpecimenSourceField.FHIR_SPECIMEN,
                site=_maybe_str(site),
                container_description=_maybe_str(container),
            )
        )
    return Maybe.of(tuple(specimens))


def _parse_narrative(
    report: dict[str, Any], index: dict[str, dict[str, Any]]
) -> tuple[NarrativeSection, ...]:
    lines_by_kind: dict[NarrativeKind, list[str]] = {}
    for ref in report.get("result", []):
        observation = _resolve(index, ref)
        if observation is None:
            continue
        code_text = (_codeable_concept_text(observation.get("code")) or "").strip().lower()
        kind = _OBSERVATION_CODE_TO_NARRATIVE_KIND.get(code_text, NarrativeKind.OTHER)
        value = observation.get("valueString")
        if value is None:
            continue
        lines_by_kind.setdefault(kind, []).append(value)

    sections: list[NarrativeSection] = []
    for kind in NarrativeKind:
        lines = lines_by_kind.get(kind)
        if lines is None:
            sections.append(NarrativeSection(kind=kind, text=Maybe.missing(Absent.NOT_SUPPLIED)))
        else:
            joined = "\n".join(lines)
            text = Maybe.missing(Absent.EMPTY) if joined == "" else Maybe.of(joined)
            sections.append(NarrativeSection(kind=kind, text=text))
    return tuple(sections)


def _parse_requisition(
    report: dict[str, Any], index: dict[str, dict[str, Any]]
) -> Requisition:
    service_request: dict[str, Any] | None = None
    for ref in report.get("basedOn", []):
        resolved = _resolve(index, ref)
        if resolved and resolved.get("resourceType") == "ServiceRequest":
            service_request = resolved
            break

    if service_request is None:
        return Requisition(
            match_method=RequisitionMatchMethod.UNMATCHED,
            clinical_indication=Maybe.missing(Absent.NOT_SUPPLIED),
            ordering_provider_npi=Maybe.missing(Absent.NOT_SUPPLIED),
        )

    reason_codes = service_request.get("reasonCode", [])
    clinical_indication = _codeable_concept_text(reason_codes[0]) if reason_codes else None

    requester = service_request.get("requester", {})
    requester_resource = _resolve(index, requester) if requester else None
    npi = (
        _identifier_value(requester_resource, system_contains="us-npi")
        if requester_resource
        else None
    )

    return Requisition(
        match_method=RequisitionMatchMethod.ACCESSION_NUMBER,
        clinical_indication=_maybe_str(clinical_indication),
        ordering_provider_npi=_maybe_str(npi),
    )


def parse_bundle(bundle: dict[str, Any]) -> Case:
    """Parse a FHIR R4 Bundle containing exactly one DiagnosticReport
    into a canonical Case.

    Raises `FhirNormalizationError` if a field the Case model requires
    outright (date_of_service, accession_number) cannot be determined.
    """
    if bundle.get("resourceType") != "Bundle":
        raise FhirNormalizationError(f"expected a Bundle, got resourceType={bundle.get('resourceType')!r}")

    index = _resource_index(bundle)
    report = _first(bundle, "DiagnosticReport")
    if report is None:
        raise FhirNormalizationError("bundle contains no DiagnosticReport resource")

    accession_number = _identifier_value(report, system_contains="accession")
    if not accession_number:
        raise FhirNormalizationError("DiagnosticReport has no accession-number identifier")

    effective = report.get("effectiveDateTime") or (report.get("effectivePeriod") or {}).get("start")
    if not effective:
        raise FhirNormalizationError("DiagnosticReport has no effectiveDateTime/effectivePeriod.start")
    try:
        date_of_service = _parse_date(effective)
    except ValueError as exc:
        raise FhirNormalizationError(f"could not parse DiagnosticReport date {effective!r}") from exc

    return Case(
        case_id=accession_number,
        accession_number=accession_number,
        date_of_service=date_of_service,
        source_format=SourceFormat.FHIR_R4,
        source_document_id=accession_number,
        specimens=_parse_specimens(report, index),
        narrative=_parse_narrative(report, index),
        requisition=_parse_requisition(report, index),
    )
