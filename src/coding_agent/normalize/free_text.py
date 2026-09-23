"""Free-text surgical pathology report -> canonical Case.

A signed-out report (typically handed over as a PDF) is a different
input shape from HL7v2/FHIR: it carries the pathologist's narrative, but
never a structured accessioning specimen list -- that lives in the LIS,
not on the printed report. So unlike `normalize/hl7v2.py` and
`normalize/fhir.py`, this module always sets `Case.specimens` to
`Maybe.missing(Absent.NOT_SUPPLIED)`. That is not a parsing failure: it
is the honest state of a bare report with no paired LIS feed, and it is
exactly what `rules/units.py` needs to correctly report
`ReconciliationStatus.UNDETERMINABLE` rather than inventing a specimen
count by reading the narrative -- see `Specimen`'s docstring in
normalize/case.py ("never a count derived from reading the narrative").

Section-splitting is a header-keyword heuristic, not a structured-field
parse (there is no equivalent of HL7's OBX-3 or FHIR's Observation.code
here) -- it will miss a section whose report uses an unrecognized
heading, and degrades that section to `Absent.NOT_SUPPLIED` rather than
guessing. `case_id`, `accession_number`, and `date_of_service` are not
inferred from the report text (the same guess-vs-abstain posture): the
caller must supply them.
"""

from __future__ import annotations

import re
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
)

_HEADER_TO_NARRATIVE_KIND: dict[str, NarrativeKind] = {
    "CLINICAL HISTORY": NarrativeKind.CLINICAL_HISTORY,
    "CLINICAL INDICATION": NarrativeKind.CLINICAL_HISTORY,
    "HISTORY": NarrativeKind.CLINICAL_HISTORY,
    "GROSS DESCRIPTION": NarrativeKind.GROSS,
    "GROSS": NarrativeKind.GROSS,
    "SPECIMEN": NarrativeKind.GROSS,
    "MICROSCOPIC DESCRIPTION": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC EXAMINATION": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC": NarrativeKind.MICROSCOPIC,
    "DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "FINAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "PATHOLOGIC DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "PATHOLOGICAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
}

# A line consisting only of a known header, optionally followed by ':' and
# nothing else meaningful (allows trailing whitespace) -- deliberately
# strict, so a header keyword used mid-sentence in a diagnosis line is
# never mistaken for a new section boundary.
_HEADER_LINE = re.compile(
    r"^\s*(" + "|".join(re.escape(h) for h in _HEADER_TO_NARRATIVE_KIND) + r")\s*:?\s*$",
    re.IGNORECASE,
)


class FreeTextNormalizationError(Exception):
    """Raised when the report text carries no recognizable content at
    all (e.g. an empty or image-only PDF whose text layer extracted to
    nothing) -- there is nothing here to build even a narrative-only
    Case from."""


def split_sections(raw_text: str) -> dict[NarrativeKind, str]:
    """Split report text into sections by recognized header lines.

    Text before the first recognized header is discarded (typically
    demographics/letterhead this module never reads). A recognized
    header with no following text before the next header contributes no
    section. Unrecognized headers are folded into whichever section is
    currently open.
    """
    sections: dict[NarrativeKind, list[str]] = {}
    current: NarrativeKind | None = None

    for line in raw_text.splitlines():
        match = _HEADER_LINE.match(line)
        if match:
            current = _HEADER_TO_NARRATIVE_KIND[match.group(1).upper()]
            sections.setdefault(current, [])
            continue
        if current is not None and line.strip():
            sections[current].append(line.strip())

    return {kind: "\n".join(lines) for kind, lines in sections.items() if lines}


def parse_report_text(
    raw_text: str,
    *,
    case_id: str,
    accession_number: str,
    date_of_service: date,
    source_document_id: str | None = None,
) -> Case:
    """Build a canonical Case from a free-text (e.g. PDF-extracted)
    surgical pathology report.

    `Case.specimens` is always `Maybe.missing(Absent.NOT_SUPPLIED)` --
    see this module's docstring. Raises `FreeTextNormalizationError` if
    no recognized narrative section could be found at all.
    """
    found = split_sections(raw_text)
    if not found:
        raise FreeTextNormalizationError(
            "no recognized section headers (Clinical History / Gross Description / "
            "Microscopic Description / Diagnosis) found in this text -- if this came "
            "from a PDF, check that it has an extractable text layer (not a scanned image)"
        )

    narrative = tuple(
        NarrativeSection(
            kind=kind,
            text=Maybe.of(found[kind]) if kind in found else Maybe.missing(Absent.NOT_SUPPLIED),
        )
        for kind in NarrativeKind
        if kind is not NarrativeKind.OTHER
    )

    return Case(
        case_id=case_id,
        accession_number=accession_number,
        date_of_service=date_of_service,
        source_format=SourceFormat.MANUAL,
        source_document_id=source_document_id or accession_number,
        specimens=Maybe.missing(Absent.NOT_SUPPLIED),
        narrative=narrative,
        requisition=Requisition(match_method=RequisitionMatchMethod.UNMATCHED),
    )
