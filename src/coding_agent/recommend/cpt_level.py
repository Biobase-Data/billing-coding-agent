"""Turn one case's procedure-type extraction into a CPT surgical-
pathology level recommendation -- the second recommend/ capability,
alongside recommend/assemble.py's specimen-unit reconciliation.

Bidirectional by construction, but differently shaped than
assemble.py's ADDITION/REMOVAL split: a wrong level is a single
`CptLevelFinding` carrying both `baseline_code` (what's currently
billed, or `None`) and `recommended_code` (what the rules table says it
should be) side by side, rather than two separate lines. This still
satisfies "never an additions-only code path" -- the same call that can
propose adding a level for an unbilled specimen can just as easily
propose a *lower* level for an over-billed one; nothing about this
code path can only ever move billing upward. Splitting into a
REMOVAL-of-the-wrong-code plus an ADDITION-of-the-right-code would also
misrepresent the finding: unlike unit reconciliation's REMOVAL (whose
evidence is a genuine *absence* of narrative support), a wrong CPT level
here is always justified by *positive* evidence -- the procedure-type
extraction that drove the recommended code -- so forcing it through
`RecommendationLine`'s evidence-forbidden-on-REMOVAL rule would be
wrong, not just differently shaped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from coding_agent.extract.schema import ProcedureTypeExtraction
from coding_agent.normalize.case import Case, EvidenceSpan
from coding_agent.recommend.schema import BaselineLine, Blocked, BlockedReason
from coding_agent.rules.cpt_level import CptLevelUnmappedError, categorize_site, specimen_level_code


class CptLevelFinding(BaseModel):
    """One specimen whose recommended CPT level differs from what's
    currently billed (or has nothing billed at all)."""

    model_config = ConfigDict(frozen=True)

    specimen_id: str
    recommended_code: str
    baseline_code: str | None
    """`None` when no baseline line named this specimen -- the addition
    direction. A differing non-`None` value is the change direction."""

    evidence: tuple[EvidenceSpan, ...]
    rationale: str


class CptLevelRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    baseline: tuple[BaselineLine, ...]
    findings: tuple[CptLevelFinding, ...]
    unaddressed_specimen_ids: tuple[str, ...] = ()
    """Accessioned specimens this recommendation could not address at
    all -- no procedure-type mention matched them (extraction covered
    other specimens but not this one, or its site is absent/
    unrecognized). Named explicitly rather than silently omitted, so a
    coder can tell "this specimen agrees with its baseline" apart from
    "this specimen was never evaluated"."""
    blocked: Blocked | None = None


def build_cpt_level_recommendation(
    case: Case,
    extraction: ProcedureTypeExtraction,
    baseline: tuple[BaselineLine, ...],
) -> CptLevelRecommendation:
    """Assemble a CptLevelRecommendation for one case.

    Requires `Case.specimens` to be present (a structured accessioning
    specimen list) -- CPT leveling needs each specimen's `site`, a
    structured field this package never derives from narrative text.
    """
    if extraction.abstained:
        abstention = extraction.abstention
        return CptLevelRecommendation(
            case_id=case.case_id,
            baseline=baseline,
            findings=(),
            blocked=Blocked(
                reason=BlockedReason.EXTRACTION_ABSTAINED,
                detail=f"{abstention.reason.value}: {abstention.detail}",
            ),
        )

    if not case.specimens.is_present:
        return CptLevelRecommendation(
            case_id=case.case_id,
            baseline=baseline,
            findings=(),
            blocked=Blocked(
                reason=BlockedReason.ACCESSIONING_SPECIMEN_LIST_ABSENT,
                detail=(
                    "the accessioning record could not supply a structured specimen "
                    "list for this case -- CPT leveling needs each specimen's "
                    "structured site, which this package never derives from the "
                    "narrative"
                ),
            ),
        )

    mentions_by_label = {mention.label: mention for mention in extraction.mentions}
    baseline_by_specimen = {
        line.specimen_id: line.code for line in baseline if line.specimen_id is not None
    }

    findings: list[CptLevelFinding] = []
    unaddressed: list[str] = []

    for specimen in sorted(case.specimens.value, key=lambda s: s.specimen_id):
        mention = mentions_by_label.get(specimen.specimen_id)
        if mention is None:
            unaddressed.append(specimen.specimen_id)
            continue

        site = specimen.site.value if specimen.site.is_present else None
        site_category = categorize_site(site)
        try:
            recommended_code = specimen_level_code(mention.procedure_type, site_category)
        except CptLevelUnmappedError:
            unaddressed.append(specimen.specimen_id)
            continue

        baseline_code = baseline_by_specimen.get(specimen.specimen_id)
        if baseline_code == recommended_code:
            continue  # agreement -- no finding

        findings.append(
            CptLevelFinding(
                specimen_id=specimen.specimen_id,
                recommended_code=recommended_code,
                baseline_code=baseline_code,
                evidence=mention.evidence,
                rationale=(
                    f"Specimen {specimen.specimen_id}'s narrative supports a "
                    f"{mention.procedure_type} procedure, which levels to "
                    f"{recommended_code} -- "
                    + (
                        f"no baseline code was found for this specimen."
                        if baseline_code is None
                        else f"the baseline code ({baseline_code}) does not match."
                    )
                ),
            )
        )

    return CptLevelRecommendation(
        case_id=case.case_id,
        baseline=baseline,
        findings=tuple(findings),
        unaddressed_specimen_ids=tuple(sorted(unaddressed)),
    )
