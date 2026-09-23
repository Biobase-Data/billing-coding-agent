"""Turn one case's extraction result into a Recommendation.

Orchestrates rules/units.py's reconciliation and extract/specimens.py's
mentions into the bidirectional flags a coder reviews. Never produces
lines without also being *able* to produce the other direction from the
same call -- there is exactly one code path here, and it always
computes both `missing_from_narrative` (removal candidates) and
`missing_from_accessioning` (addition candidates) together.
"""

from __future__ import annotations

from coding_agent.extract.schema import SpecimenExtraction
from coding_agent.normalize.case import Case
from coding_agent.recommend.schema import (
    BaselineLine,
    Blocked,
    BlockedReason,
    DiffKind,
    Recommendation,
    RecommendationLine,
)
from coding_agent.rules.units import ReconciliationStatus, reconcile


def build_recommendation(
    case: Case,
    extraction: SpecimenExtraction,
    baseline: tuple[BaselineLine, ...],
    primary_code: str,
) -> Recommendation:
    """Assemble a Recommendation for one case.

    `primary_code` is the bare identifier for the single per-specimen
    code assumed to apply uniformly across this case's specimens (see
    recommend/schema.py's module docstring for the V0 simplification
    this represents).
    """
    if extraction.abstained:
        abstention = extraction.abstention
        return Recommendation(
            case_id=case.case_id,
            baseline=baseline,
            lines=(),
            blocked=Blocked(
                reason=BlockedReason.EXTRACTION_ABSTAINED,
                detail=f"{abstention.reason.value}: {abstention.detail}",
            ),
        )

    accessioned_ids = (
        frozenset(specimen.specimen_id for specimen in case.specimens.value)
        if case.specimens.is_present
        else None
    )
    narrative_labels = frozenset(mention.label for mention in extraction.mentions)
    reconciliation = reconcile(accessioned_ids, narrative_labels)

    if reconciliation.status is ReconciliationStatus.UNDETERMINABLE:
        return Recommendation(
            case_id=case.case_id,
            baseline=baseline,
            lines=(),
            blocked=Blocked(
                reason=BlockedReason.ACCESSIONING_SPECIMEN_LIST_ABSENT,
                detail=(
                    "the accessioning record could not supply a structured specimen "
                    "list for this case -- there is nothing to reconcile the "
                    "narrative against"
                ),
            ),
        )

    evidence_by_label = {mention.label: mention.evidence for mention in extraction.mentions}

    lines: list[RecommendationLine] = []
    for specimen_id in sorted(reconciliation.missing_from_narrative):
        lines.append(
            RecommendationLine(
                code=primary_code,
                diff_kind=DiffKind.REMOVAL,
                specimen_id=specimen_id,
                evidence=(),
                rationale=(
                    f"Specimen {specimen_id} was accessioned but the narrative names "
                    "no supporting text for it -- confirm before billing a unit for it."
                ),
            )
        )
    for label in sorted(reconciliation.missing_from_accessioning):
        lines.append(
            RecommendationLine(
                code=primary_code,
                diff_kind=DiffKind.ADDITION,
                specimen_id=label,
                evidence=evidence_by_label[label],
                rationale=(
                    f"The narrative names specimen {label}, which has no matching "
                    "accessioned specimen -- confirm whether a unit should be added."
                ),
            )
        )

    return Recommendation(case_id=case.case_id, baseline=baseline, lines=tuple(lines))
