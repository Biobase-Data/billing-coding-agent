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

A real PDF's flattened text commonly interleaves non-clinical content
into whatever section happens to be open -- signature blocks, CLIA
numbers, "for information purposes only" legal boilerplate, page-number
footers -- because there is nothing in plain text marking where a
section actually *ends* except the next recognized header.
`_is_boilerplate_line` strips a narrow, high-precision allowlist of such
patterns before they reach the model; it is deliberately conservative
(a missed pattern degrades to noise in the narrative, not a wrong
clinical claim) rather than an attempt at fully general cleanup. This
matters because that narrative text feeds a coder-facing recommendation
downstream, and noise there is a real quality problem, not merely
cosmetic.
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
    "CLINICAL HISTORY / PRE-OPERATIVE DIAGNOSIS": NarrativeKind.CLINICAL_HISTORY,
    "CLINICAL INDICATION": NarrativeKind.CLINICAL_HISTORY,
    "HISTORY": NarrativeKind.CLINICAL_HISTORY,
    "GROSS DESCRIPTION": NarrativeKind.GROSS,
    "GROSS": NarrativeKind.GROSS,
    "SPECIMEN": NarrativeKind.GROSS,
    "SPECIMEN RECEIVED": NarrativeKind.GROSS,
    "SPECIMEN(S) RECEIVED": NarrativeKind.GROSS,
    "SPECIMENS RECEIVED": NarrativeKind.GROSS,
    "MICROSCOPIC DESCRIPTION": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC EXAMINATION": NarrativeKind.MICROSCOPIC,
    "MICROSCOPIC": NarrativeKind.MICROSCOPIC,
    "DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "FINAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "PATHOLOGIC DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "PATHOLOGICAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "FINAL PATHOLOGIC DIAGNOSIS": NarrativeKind.DIAGNOSIS,
    "FINAL PATHOLOGICAL DIAGNOSIS": NarrativeKind.DIAGNOSIS,
}

# A line consisting only of a known header, optionally followed by ':' and
# nothing else meaningful (allows trailing whitespace) -- deliberately
# strict, so a header keyword used mid-sentence in a diagnosis line is
# never mistaken for a new section boundary.
_HEADER_LINE = re.compile(
    r"^\s*(" + "|".join(re.escape(h) for h in _HEADER_TO_NARRATIVE_KIND) + r")\s*:?\s*$",
    re.IGNORECASE,
)

# Signature blocks, billing/legal boilerplate, and footer artifacts that
# commonly land inside a still-open section when a PDF's text is
# flattened -- see the module docstring. Matched anywhere in the line
# (not anchored) except where noted, and the whole line is dropped, not
# just the matched portion.
_BOILERPLATE_LINE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"electronically signed",
        r"please disregard this page",
        r"proceed to next page",
        r"cpt code\(s\)\s*:",
        r"icd-?10 code\(s\)\s*:",
        # A raw billed-code-with-unit-count stamp (e.g. "88304(1)",
        # "88307(1), 88309(1)") -- some LIS report exports print this
        # directly after the gross description with no "CPT CODE(S):"
        # label at all. This is exactly the kind of content extract/
        # must never see (see this module's and specimens.py's "never
        # mentions billing... to the model" invariant): stripping the
        # labeled form above but not this raw form was a real, live gap
        # -- found by a coder feeding this exact PDF through the console
        # and noticing the code stamp printed inside the GROSS section.
        r"\b\d{5}\(\d+\)",
        r"^page\s+\d+\s+of\s+\d+\s*$",
        r"clia\s*#",
        r"screening location\s*:",
        r"cpt codes provided are for information purposes only",
        r"illustrative purposes only",
        r"analyte specific reagent",
        r"cleared by the fda",
        r"regarded as investigational",
        r"clinical improvement amendments",
        r"high complexity clinical laboratory testing",
        r"specimens processed by",
        r"^ph:?\s*\d{3}[.\-]\d{3}[.\-]\d{4}",
        r"^\d{4}$",  # a bare 4-digit year with nothing else -- a page/table
        # extraction artifact; real narrative sentences never consist of
        # just a year.
        # A signing pathologist's name/credential/sign-off line, and the
        # boilerplate disclaimer that follows it -- these consistently
        # trail the microscopic description in a real signed-out PDF's
        # flattened text (the "electronically signed" label line above
        # is already caught; these are the lines that follow it, found
        # via a real live PDF upload where they leaked into MICROSCOPIC).
        r"^dr\.\s+\S+.*\bm\.d\.,",
        r"board certified pathologist",
        r"sign-?off date\s*/\s*time",
        r"for medical advice or diagnosis,?\s*consult a professional",
        r"ai responses may include mistakes",
    )
]

# An explicit end-of-document marker: everything after it (signature
# blocks, footers, page furniture) is discarded outright by closing
# whichever section is open, rather than relying on catching every
# individual boilerplate pattern that might follow it.
_END_OF_REPORT_LINE = re.compile(r"end of report", re.IGNORECASE)


def _is_boilerplate_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in _BOILERPLATE_LINE_PATTERNS)


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
    currently open. A line matching a known boilerplate pattern, or an
    explicit end-of-report marker, is dropped rather than appended --
    see the module docstring.
    """
    sections: dict[NarrativeKind, list[str]] = {}
    current: NarrativeKind | None = None

    for line in raw_text.splitlines():
        match = _HEADER_LINE.match(line)
        if match:
            current = _HEADER_TO_NARRATIVE_KIND[match.group(1).upper()]
            sections.setdefault(current, [])
            continue
        if _END_OF_REPORT_LINE.search(line):
            current = None
            continue
        if current is not None and line.strip() and not _is_boilerplate_line(line):
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
