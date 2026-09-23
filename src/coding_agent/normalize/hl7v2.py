"""HL7 v2 ORU^R01 -> canonical Case.

Scope and known limitations (V0):

- Assumes the standard encoding characters (field `|`, component `^`,
  repetition `~`, subcomponent `&`, escape `\\`) taken from MSH-1/MSH-2.
  A feed using non-standard delimiters is out of scope; that is a
  per-LIS integration detail to handle before this parser, not something
  to silently guess at.
- HL7 escape sequences inside field text (`\\F\\`, `\\.br\\`, ...) are not
  decoded. A feed that relies on them will produce narrative text
  containing the raw escape sequence. Flagged here rather than adding an
  encoder we haven't tested against a real feed.
- No PHI is read into the canonical Case. PID name/DOB fields are parsed
  only far enough to be discarded; this module never stores them.
- The clinical indication and ordering-provider fields on the resulting
  `Requisition` are read from the same ORU message as the specimens, so
  they are always `ACCESSION_NUMBER`-matched by construction -- there is
  no separate paper-requisition ingestion path in V0 that would need a
  fuzzy name/DOB match. If one is added later, it must go through its
  own matching step and set `RequisitionMatchMethod.FUZZY_NAME_DOB`
  honestly; this parser must not be extended to guess a fuzzy match from
  a single message.
"""

from __future__ import annotations

from datetime import date

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

FIELD_SEP = "|"
COMPONENT_SEP = "^"
SUBCOMPONENT_SEP = "&"

_OBX_IDENTIFIER_TO_NARRATIVE_KIND: dict[str, NarrativeKind] = {
    "CLINHX": NarrativeKind.CLINICAL_HISTORY,
    "CLINICAL HISTORY": NarrativeKind.CLINICAL_HISTORY,
    "GROSS": NarrativeKind.GROSS,
    "GROSS DESCRIPTION": NarrativeKind.GROSS,
    "MICRO": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC DESCRIPTION": NarrativeKind.MICROSCOPIC,
    "DX": NarrativeKind.DIAGNOSIS,
    "DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "FINAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
}


class Hl7NormalizationError(Exception):
    """A required field could not be found or parsed. Raised only for
    fields the canonical Case requires outright (date_of_service,
    accession_number) -- everything optional degrades to `Maybe.missing`
    instead of raising."""


def _split_segments(message: str) -> list[list[str]]:
    raw_segments = [line for line in message.replace("\r\n", "\r").replace("\n", "\r").split("\r") if line]
    return [segment.split(FIELD_SEP) for segment in raw_segments]


def _components(field: str) -> list[str]:
    return field.split(COMPONENT_SEP)


def _field(segment: list[str], index: int) -> str | None:
    """1-based HL7 field index (segment[0] is the segment name itself,
    so field N is at list index N)."""
    if index >= len(segment):
        return None
    value = segment[index]
    return value if value != "" else None


def _first_component(field: str | None) -> str | None:
    if field is None:
        return None
    parts = _components(field)
    return parts[0] if parts and parts[0] != "" else None


def _maybe_str(field: str | None) -> Maybe[str]:
    if field is None:
        return Maybe.missing(Absent.NOT_SUPPLIED)
    if field == "":
        return Maybe.missing(Absent.EMPTY)
    return Maybe.of(field)


def _readable_component(field: str | None) -> str | None:
    """For CE-typed fields (identifier^text^coding system): prefer the
    human-readable text component, falling back to the identifier."""
    if field is None:
        return None
    parts = _components(field)
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return parts[0] if parts and parts[0] else None


def _by_segment_type(segments: list[list[str]]) -> dict[str, list[list[str]]]:
    grouped: dict[str, list[list[str]]] = {}
    for segment in segments:
        grouped.setdefault(segment[0], []).append(segment)
    return grouped


def _parse_specimens(spm_segments: list[list[str]]) -> tuple[Specimen, ...]:
    specimens: list[Specimen] = []
    for spm in spm_segments:
        raw_id = _field(spm, 2)
        specimen_id = raw_id
        if raw_id is not None and SUBCOMPONENT_SEP in raw_id:
            specimen_id = raw_id.split(SUBCOMPONENT_SEP)[-1]
        elif raw_id is not None and COMPONENT_SEP in raw_id:
            specimen_id = _components(raw_id)[-1]
        if not specimen_id:
            # A specimen segment with no identifiable specimen id is a
            # parse failure for that entry, not an empty-but-valid one.
            continue
        site_field = _field(spm, 8)
        type_field = _field(spm, 4)
        specimens.append(
            Specimen(
                specimen_id=specimen_id,
                source_field=SpecimenSourceField.SPM,
                site=_maybe_str(_readable_component(site_field)) if site_field is not None else Maybe.missing(Absent.NOT_SUPPLIED),
                container_description=_maybe_str(_readable_component(type_field)) if type_field is not None else Maybe.missing(Absent.NOT_SUPPLIED),
            )
        )
    return tuple(specimens)


def _parse_narrative(obx_segments: list[list[str]]) -> tuple[NarrativeSection, ...]:
    lines_by_kind: dict[NarrativeKind, list[str]] = {}
    for obx in obx_segments:
        identifier_field = _field(obx, 3)
        value = _field(obx, 5)
        if identifier_field is None or value is None:
            continue
        identifier = (_readable_component(identifier_field) or "").strip().upper()
        kind = _OBX_IDENTIFIER_TO_NARRATIVE_KIND.get(identifier, NarrativeKind.OTHER)
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


def _parse_date_of_service(obr: list[str] | None) -> date:
    if obr is None:
        raise Hl7NormalizationError("no OBR segment present; cannot determine date of service")
    raw = _field(obr, 7)
    if raw is None:
        raise Hl7NormalizationError("OBR-7 (observation date/time) is empty; cannot determine date of service")
    digits = _first_component(raw) or raw
    try:
        return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
    except (ValueError, IndexError) as exc:
        raise Hl7NormalizationError(f"could not parse OBR-7 date/time {raw!r}") from exc


def _parse_accession_number(obr: list[str] | None) -> str:
    if obr is None:
        raise Hl7NormalizationError("no OBR segment present; cannot determine accession number")
    filler_order_number = _first_component(_field(obr, 3))
    if not filler_order_number:
        raise Hl7NormalizationError("OBR-3 (filler order number) is empty; cannot determine accession number")
    return filler_order_number


def _parse_requisition(obr: list[str] | None) -> Requisition:
    if obr is None:
        return Requisition(
            match_method=RequisitionMatchMethod.UNMATCHED,
            clinical_indication=Maybe.missing(Absent.NOT_SUPPLIED),
            ordering_provider_npi=Maybe.missing(Absent.NOT_SUPPLIED),
        )
    return Requisition(
        match_method=RequisitionMatchMethod.ACCESSION_NUMBER,
        clinical_indication=_maybe_str(_field(obr, 13)),  # OBR-13: Relevant Clinical Information
        ordering_provider_npi=_maybe_str(_first_component(_field(obr, 16))),  # OBR-16: Ordering Provider
    )


def parse_oru(message: str) -> Case:
    """Parse one HL7 v2 ORU^R01 message into a canonical Case.

    Raises `Hl7NormalizationError` if a field the Case model requires
    outright (date_of_service, accession_number) cannot be determined.
    Every optional field degrades to an explicit `Maybe.missing` instead.
    """
    segments = _by_segment_type(_split_segments(message))
    obr = segments.get("OBR", [None])[0]
    spm_segments = segments.get("SPM", [])
    obx_segments = segments.get("OBX", [])

    accession_number = _parse_accession_number(obr)
    date_of_service = _parse_date_of_service(obr)
    specimens = _parse_specimens(spm_segments)
    narrative = _parse_narrative(obx_segments)
    requisition = _parse_requisition(obr)

    return Case(
        case_id=accession_number,
        accession_number=accession_number,
        date_of_service=date_of_service,
        source_format=SourceFormat.HL7V2,
        source_document_id=accession_number,
        specimens=Maybe.of(specimens) if spm_segments else Maybe.missing(Absent.NOT_SUPPLIED),
        narrative=narrative,
        requisition=requisition,
    )
