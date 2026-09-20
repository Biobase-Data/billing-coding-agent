"""Ordered-versus-resulted reconciliation, both directions.

A stain ordered but not resulted is a different situation from one
resulted but never billed, and both are findings -- the same shape as
the one transferable finding from the coder interview (work that
happened but was not on the claim when the coder looked).

H&E is excluded from the resulted-not-billed direction: it is never
billed as its own line (it is included in the specimen level code), so
there is nothing for a fact to corroborate.
"""

from __future__ import annotations

from pipeline.models.case import Case, StainKind
from pipeline.models.facts import Fact, FactType
from pipeline.models.findings import Finding, Severity


def check_ordered_not_resulted(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    for specimen in case.specimens:
        for block in specimen.blocks:
            for stain in block.stains:
                if stain.ordered and not stain.resulted:
                    findings.append(
                        Finding(
                            severity=Severity.REVIEW,
                            line_id=None,
                            rule_id="reconciliation:ordered_not_resulted",
                            message=(
                                f"specimen {specimen.specimen_id} block {block.block_id}: "
                                f"stain {stain.stain_id} ({stain.kind.value}) was ordered but never resulted"
                            ),
                            suggested_action="confirm whether the stain still needs to be performed before billing",
                        )
                    )
    return findings


def check_resulted_not_billed(facts: list[Fact], case: Case) -> list[Finding]:
    billed_keys = {
        (f.specimen_id, f.value.get("block_id"), f.value.get("stain_id"))
        for f in facts
        if f.fact_type is FactType.STAIN
    }
    findings: list[Finding] = []
    for specimen in case.specimens:
        for block in specimen.blocks:
            for stain in block.stains:
                if stain.kind is StainKind.HE:
                    continue
                if stain.resulted and (specimen.specimen_id, block.block_id, stain.stain_id) not in billed_keys:
                    findings.append(
                        Finding(
                            severity=Severity.REVIEW,
                            line_id=None,
                            rule_id="reconciliation:resulted_not_billed",
                            message=(
                                f"specimen {specimen.specimen_id} block {block.block_id}: "
                                f"stain {stain.stain_id} ({stain.kind.value}) is marked resulted in the "
                                "lab log but is not described anywhere in the report"
                            ),
                            suggested_action="confirm the result was reported before billing it",
                        )
                    )
    return findings
