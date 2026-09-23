"""Fact types, evidence spans, and abstention for the extract/ layer.

Two things are deliberately kept apart here, because they answer
different questions:

- `Absent` (in `normalize/case.py`) is about *data provenance*: why a
  field the canonical Case could have held is missing. It is produced by
  normalize/ and consumed by everything downstream.
- `AbstentionReason` (here) is about the *model's epistemic state*: why
  extract/ could not produce a fact from data that *was* present. It is
  produced only by extract/.

A pipeline that conflates these loses the distinction that matters most
to a coder: "the LIS never sent us a gross description" is a different
problem, with a different fix, than "the gross description is here and
the model can't tell what it means."
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from coding_agent.normalize.case import EvidenceSpan


class AbstentionReason(str, Enum):
    AMBIGUOUS_NARRATIVE = "ambiguous_narrative"
    """The text does not clearly support a determination either way."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"
    """Two spans in the same case point to different answers and neither
    can be preferred without guessing."""

    SECTION_ABSENT = "section_absent"
    """The narrative section this extraction needs is not present on the
    case (see `Case.section` / `Absent`) -- there is nothing to read."""

    LOW_MODEL_CONFIDENCE = "low_model_confidence"
    """A catch-all for the model self-reporting it cannot determine an
    answer with the confidence this pipeline requires. Used sparingly:
    prefer one of the more specific reasons above when it applies."""


class Abstention(BaseModel):
    """First-class output, not a fallback. Abstention rate is a metric
    this project tracks and does not try to drive to zero -- see
    eval/metrics.py. A silent wrong answer is worse than either error
    direction, because it consumes the coder's trust invisibly.
    """

    model_config = ConfigDict(frozen=True)

    reason: AbstentionReason
    detail: str
    """Short, human-readable, and PHI-free explanation for the coder and
    for logs -- see the repo-wide "never log narrative text or
    identifiers" convention. Describe *why* extraction abstained, not
    *what the narrative said*."""


class SpecimenMention(BaseModel):
    """One specimen label as the narrative describes it, independent of
    the accessioning record's structured specimen list. This is what
    `extract/specimens.py` V0 produces; `rules/units.py` reconciles it
    against `Case.specimens`, the ground truth.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    """The specimen label as written in the narrative, e.g. "A". Not
    normalized against the accessioning record's specimen_id -- that
    comparison belongs to rules/units.py, not to this fact."""

    evidence: tuple[EvidenceSpan, ...]

    @model_validator(mode="after")
    def _at_least_one_evidence_span(self) -> "SpecimenMention":
        if not self.evidence:
            raise ValueError(
                "a fact with no evidence is not a fact -- it must not be emitted"
            )
        return self


class ExtractionMetadata(BaseModel):
    """Recorded on every extraction result so a regression is
    interpretable and an audit response is possible -- see the
    "Everything is versioned" design rule. `recommend/` and `audit/`
    propagate this into the final recommendation's version stamp.
    """

    model_config = ConfigDict(frozen=True)

    model_version: str
    prompt_version: str


class SpecimenExtraction(BaseModel):
    """The result of running specimen-mention extraction on one case:
    either a (possibly empty) tuple of mentions, or an abstention.
    Exactly one is set -- there is no state representing "some mentions,
    plus we're also not sure," because that would let a caller silently
    drop the abstention and keep only the mentions.
    """

    model_config = ConfigDict(frozen=True)

    mentions: tuple[SpecimenMention, ...] | None = None
    abstention: Abstention | None = None
    metadata: ExtractionMetadata

    @model_validator(mode="after")
    def _exactly_one_of_mentions_or_abstention(self) -> "SpecimenExtraction":
        if (self.mentions is None) == (self.abstention is None):
            raise ValueError(
                "SpecimenExtraction requires exactly one of `mentions` or `abstention`"
            )
        return self

    @property
    def abstained(self) -> bool:
        return self.abstention is not None
