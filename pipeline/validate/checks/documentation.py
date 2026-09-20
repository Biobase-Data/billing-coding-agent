"""Documentation gaps: IHC without a named antibody; requisition with no
clinical indication.

("Stain resulted but no supporting text in the report" lives in
reconciliation.py, alongside ordered-not-resulted, since both are the
same LIS-vs-narrative comparison.)
"""

from __future__ import annotations

from pipeline.models.case import Case
from pipeline.models.facts import Fact, FactType
from pipeline.models.findings import Finding, Severity


def check_ihc_missing_antibody(facts: list[Fact]) -> list[Finding]:
    findings: list[Finding] = []
    for fact in facts:
        if fact.fact_type is FactType.STAIN and fact.value["kind"] == "ihc" and not fact.value.get("antibody"):
            findings.append(
                Finding(
                    severity=Severity.REVIEW,
                    line_id=None,
                    rule_id="documentation:ihc_missing_antibody",
                    message=(
                        f"specimen {fact.specimen_id}: an IHC stain has no named antibody "
                        f"(evidence: {fact.evidence.quoted!r})"
                    ),
                    suggested_action="confirm the antibody name with the pathologist before billing 88342/88341",
                )
            )
    return findings


def check_clinical_indication_present(case: Case) -> list[Finding]:
    if case.requisition.clinical_indication:
        return []
    return [
        Finding(
            severity=Severity.INFORMATIONAL,
            line_id=None,
            rule_id="documentation:no_clinical_indication",
            message="requisition carries no clinical indication",
            suggested_action="request a clinical indication from the ordering provider",
        )
    ]
