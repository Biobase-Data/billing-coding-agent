"""The canonical case object -- the contract between normalization and
everything downstream (extract/, rules/, recommend/, audit/).

Design rules this encodes (see top-level README, "The canonical case
object"):

- The specimen list is first-class and structured, separate from the
  narrative. It is the V0 ground truth for unit reconciliation.
- Narrative sections (clinical history, gross, microscopic, diagnosis) are
  delineated and stay separable, because coding rules treat them
  differently.
- Character offsets are preserved so evidence spans resolve to exact
  source locations. `Case.resolve_span` re-slices the source text and
  checks it against the span's stored `quoted` text, so a normalization
  bug that shifts offsets fails loudly instead of poisoning an audit
  trail.
- The requisition is joined with provenance: an accession-number match
  and a fuzzy name/DOB match are not the same evidentiary object, and
  code that trusts a match must be able to tell them apart.
- Absence is explicit. A field is `None` in this module only for
  optional-and-genuinely-absent-from-the-model structure (e.g. an
  omitted `Maybe`); every domain value that can be missing carries a
  reason (`Absent`) rather than collapsing to a bare `None`, because a
  model reasoning over silently-missing data confabulates.
- Date of service travels with the case; it determines which code-set
  and rules-table version is active.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class Absent(str, Enum):
    """Why a value is missing. Never collapse this to `None` or `""` --
    the three reasons imply different downstream handling."""

    NOT_SUPPLIED = "not_supplied"
    """The source system has no field for this (e.g. this HL7 feed never
    sends OBR-31)."""

    NOT_RETRIEVABLE = "not_retrievable"
    """The field exists upstream but this fetch/parse couldn't get it
    (timeout, ACL, malformed segment). Distinct from NOT_SUPPLIED because
    it is a transient integration problem, not a structural one."""

    EMPTY = "empty"
    """The source explicitly returned an empty value (e.g. SPM-8 present
    but blank). Distinct from NOT_SUPPLIED because the source system
    *tried* to answer."""


class Maybe(BaseModel, Generic[T]):
    """A value that may be absent, with the reason recorded.

    Exactly one of `value` or `absent` is set. Downstream code must check
    `is_present` before touching `value` -- there is no silent `None`
    fallback that a caller could mistake for "empty string" or "zero".
    """

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    absent: Absent | None = None

    @model_validator(mode="after")
    def _exactly_one_set(self) -> "Maybe[T]":
        if (self.value is None) == (self.absent is None):
            raise ValueError(
                "Maybe requires exactly one of `value` or `absent` to be set"
            )
        return self

    @property
    def is_present(self) -> bool:
        return self.absent is None

    @classmethod
    def of(cls, value: T) -> "Maybe[T]":
        return cls(value=value)

    @classmethod
    def missing(cls, reason: Absent) -> "Maybe[T]":
        return cls(absent=reason)


class NarrativeKind(str, Enum):
    CLINICAL_HISTORY = "clinical_history"
    GROSS = "gross"
    MICROSCOPIC = "microscopic"
    DIAGNOSIS = "diagnosis"
    OTHER = "other"


class NarrativeSection(BaseModel):
    """One narrative section of the report. `text` is `Maybe` so a report
    that never had a gross description (vs. one whose gross section
    failed to parse) can be told apart."""

    model_config = ConfigDict(frozen=True)

    kind: NarrativeKind
    text: Maybe[str] = Field(default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED))


class EvidenceSpan(BaseModel):
    """A pointer into exact source text.

    `quoted` stores the span's text redundantly (not just `start`/`end`)
    so that verification never has to trust the offsets alone -- see
    `Case.resolve_span`. Normalization must keep offsets valid for the
    *original* section text; if a section is re-wrapped or re-indented
    after normalization, the offsets must be transformed with it.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    section: NarrativeKind
    start: int
    end: int
    quoted: str

    @model_validator(mode="after")
    def _range_matches_quoted(self) -> "EvidenceSpan":
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span range [{self.start}, {self.end})")
        if self.end - self.start != len(self.quoted):
            raise ValueError(
                "quoted text length does not match end - start "
                f"({len(self.quoted)} != {self.end - self.start})"
            )
        return self


class SpecimenSourceField(str, Enum):
    SPM = "SPM"
    FHIR_SPECIMEN = "fhir_specimen"
    MANUAL = "manual"


class Specimen(BaseModel):
    """One accessioned specimen -- the V0 ground-truth unit.

    This is an entry from the accessioning record's structured specimen
    list, never a count derived from reading the narrative. Surgical
    pathology bills per accessioned specimen, so this list is the
    reconciliation target for `rules/units.py`.
    """

    model_config = ConfigDict(frozen=True)

    specimen_id: str
    """The accession's part identifier, e.g. "A", "B1". Unique within the case."""

    source_field: SpecimenSourceField
    site: Maybe[str] = Field(default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED))
    container_description: Maybe[str] = Field(
        default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED)
    )


class RequisitionMatchMethod(str, Enum):
    ACCESSION_NUMBER = "accession_number"
    """Exact identifier match -- strong evidentiary weight."""

    FUZZY_NAME_DOB = "fuzzy_name_dob"
    """Probabilistic match -- weak evidentiary weight. Code that consumes
    a fuzzy-matched requisition must not treat it the same as an
    accession-number match; carry `match_confidence` through to any
    downstream flag."""

    MANUAL = "manual"
    UNMATCHED = "unmatched"
    """A requisition-matching pass ran and found nothing. Distinct from a
    case that never had a requisition-matching pass attempted at all,
    which normalize/ should refuse to represent as `UNMATCHED` -- if
    matching didn't run, say so at the integration layer, don't guess."""


class Requisition(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_method: RequisitionMatchMethod
    match_confidence: float | None = None
    """Only meaningful when `match_method` is FUZZY_NAME_DOB. `None` for
    every other method (an exact identifier match has no confidence
    score to report)."""

    clinical_indication: Maybe[str] = Field(
        default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED)
    )
    ordering_provider_npi: Maybe[str] = Field(
        default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED)
    )

    @model_validator(mode="after")
    def _confidence_only_for_fuzzy(self) -> "Requisition":
        if (
            self.match_method != RequisitionMatchMethod.FUZZY_NAME_DOB
            and self.match_confidence is not None
        ):
            raise ValueError(
                "match_confidence is only meaningful for FUZZY_NAME_DOB matches"
            )
        return self


class SourceFormat(str, Enum):
    HL7V2 = "hl7v2"
    FHIR_R4 = "fhir_r4"
    MANUAL = "manual"


class Case(BaseModel):
    """The canonical, LIS-agnostic representation of one accessioned case.

    Every field that can be legitimately missing is `Maybe`-typed rather
    than `None`-typed; a bare `None` in this model always means "this
    concept does not apply", never "we don't know".
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    """An internal, de-identified case identifier. Never an MRN. May be
    derived from the accession number, but is not required to be."""

    accession_number: str
    date_of_service: date
    """Determines the active code-set year and rules-table version."""

    source_format: SourceFormat
    source_document_id: str
    """The `document_id` that every `EvidenceSpan` in this case's facts
    must reference."""

    specimens: Maybe[tuple[Specimen, ...]] = Field(
        default_factory=lambda: Maybe(absent=Absent.NOT_SUPPLIED)
    )
    """`Maybe`-wrapped, not a bare tuple: a case with zero specimens
    (source supplied an empty list) is a different state from a source
    that cannot supply a structured specimen list at all. The latter is
    an integration blocker for `tools/corpus_inventory.py` to surface,
    not something extract/ should try to paper over by reading the
    narrative instead."""

    narrative: tuple[NarrativeSection, ...]
    requisition: Requisition

    @model_validator(mode="after")
    def _one_section_per_kind(self) -> "Case":
        kinds = [section.kind for section in self.narrative]
        if len(kinds) != len(set(kinds)):
            raise ValueError("narrative must have at most one section per NarrativeKind")
        return self

    def section(self, kind: NarrativeKind) -> NarrativeSection | None:
        """The narrative section of this kind, or None if this case's
        narrative tuple never included one (distinct from the section
        being present-but-`Maybe`-absent -- see `NarrativeSection.text`)."""
        for candidate in self.narrative:
            if candidate.kind is kind:
                return candidate
        return None

    def specimen(self, specimen_id: str) -> Specimen | None:
        if not self.specimens.is_present:
            return None
        for candidate in self.specimens.value:
            if candidate.specimen_id == specimen_id:
                return candidate
        return None

    def resolve_span(self, span: EvidenceSpan) -> str:
        """Re-slice this case's source text at `span`'s offsets and
        verify it matches `span.quoted`. Raises ValueError on any
        mismatch -- document id, section, or drifted offsets -- rather
        than returning a value that might silently be wrong.

        This is the audit-trail check: a passing call proves the
        evidence span still points at what it claims to, in the exact
        source text this case carries today.
        """
        if span.document_id != self.source_document_id:
            raise ValueError(
                f"span references document {span.document_id!r}, "
                f"case source document is {self.source_document_id!r}"
            )
        section = self.section(span.section)
        if section is None:
            raise ValueError(f"case has no {span.section.value} section")
        if not section.text.is_present:
            raise ValueError(
                f"{span.section.value} section text is absent ({section.text.absent.value})"
            )
        text = section.text.value
        if span.end > len(text):
            raise ValueError(
                f"span end {span.end} exceeds {span.section.value} section length {len(text)}"
            )
        actual = text[span.start : span.end]
        if actual != span.quoted:
            raise ValueError(
                f"span offsets resolve to {actual!r}, expected {span.quoted!r} "
                "-- evidence span has drifted from its source text"
            )
        return actual
