"""Recommendation types: a diff against baseline coding, plus the
first-class "why there is no diff" states.

V0 scope note: `BaselineLine.code` and `RecommendationLine.code` are bare
CPT/HCPCS identifiers only -- never descriptors, never fee data (see the
top-level README's legal constraints). V0 assumes one uniform
per-specimen code applies to the whole case (the common case for a
mid-size lab's routine biopsy volume); a lab that bills different code
levels per specimen based on complexity needs a follow-on capability
this package does not yet have -- see ASSUMPTIONS.md.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from coding_agent.normalize.case import EvidenceSpan


class BaselineLine(BaseModel):
    """One line of the lab's already-submitted or already-drafted coding
    for this case -- the diff target. Untouched by this package; V0
    never proposes changing `units` or `modifiers` on this object, only
    flags specimen-level findings alongside it for a coder to weigh."""

    model_config = ConfigDict(frozen=True)

    code: str
    units: int
    modifiers: tuple[str, ...] = ()
    specimen_id: str | None = None
    """Which specimen this baseline line was billed against, when known.
    Optional and defaulted to `None` for backward compatibility with the
    unit-reconciliation capability, which never reads it (that
    capability's baseline is informational only -- see this module's
    docstring). `recommend/cpt_level.py` requires it: matching a
    recommended code against what was already billed for that specific
    specimen is the whole point of that capability's diff.
    """


class DiffKind(str, Enum):
    ADDITION = "addition"
    """The narrative supports a unit that does not appear to be billed."""

    REMOVAL = "removal"
    """A billed unit has no narrative support -- the over-billing
    direction this project exists to catch (see the top-level README,
    "Bidirectional, always")."""

    UNIT_CHANGE = "unit_change"
    """Reserved for a future capability; V0's reconciliation logic never
    emits this -- it always reasons per specimen, one line each, rather
    than proposing a single aggregate unit delta."""

    MODIFIER_CHANGE = "modifier_change"
    """Reserved; V0 has no modifier logic."""


class RecommendationLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    diff_kind: DiffKind
    specimen_id: str
    """The accessioned specimen id (for a REMOVAL line) or the
    narrative-described label (for an ADDITION line) this finding
    concerns."""

    evidence: tuple[EvidenceSpan, ...]
    rationale: str

    @model_validator(mode="after")
    def _evidence_matches_diff_kind(self) -> "RecommendationLine":
        if not self.rationale.strip():
            raise ValueError("a recommendation line must carry a non-empty rationale")
        if self.diff_kind is DiffKind.ADDITION and not self.evidence:
            raise ValueError(
                "an ADDITION line must cite the narrative evidence that supports it "
                "-- a line with no evidence is not emitted"
            )
        if self.diff_kind is DiffKind.REMOVAL and self.evidence:
            raise ValueError(
                "a REMOVAL line's finding is the *absence* of narrative support; "
                "it must not carry evidence spans, which would misrepresent the "
                "specimen as having textual support after all"
            )
        return self


class BlockedReason(str, Enum):
    EXTRACTION_ABSTAINED = "extraction_abstained"
    ACCESSIONING_SPECIMEN_LIST_ABSENT = "accessioning_specimen_list_absent"


class Blocked(BaseModel):
    """Why no recommendation lines were produced. Unifies the two lower
    layers' reasons (extract/'s Abstention, rules/'s UNDETERMINABLE
    status) into the one thing a coder needs: an explanation, not a
    silently empty result that looks the same as "nothing to flag"."""

    model_config = ConfigDict(frozen=True)

    reason: BlockedReason
    detail: str


class Recommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    baseline: tuple[BaselineLine, ...]
    lines: tuple[RecommendationLine, ...]
    blocked: Blocked | None = None

    @model_validator(mode="after")
    def _blocked_xor_lines_state(self) -> "Recommendation":
        if self.blocked is not None and self.lines:
            raise ValueError(
                "a blocked recommendation must not also carry lines -- "
                "never guess past a reason we could not determine one"
            )
        return self
