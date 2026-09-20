"""Ambiguous specimen count: multiple sites arrived in one container.

The mapper always bills the container as one unit (ASSUMPTIONS.md #1),
but that count is a guess about what the submitting clinician meant, so
it always needs a human to confirm -- never a silent pass-through.
"""

from __future__ import annotations

from pipeline.models.case import Case
from pipeline.models.findings import Finding, Severity


def check_specimen_ambiguity(case: Case) -> list[Finding]:
    findings: list[Finding] = []
    for specimen in case.specimens:
        if len(specimen.sites) > 1:
            findings.append(
                Finding(
                    severity=Severity.REVIEW,
                    line_id=f"{specimen.specimen_id}-level",
                    rule_id="specimen:ambiguous_site_count",
                    message=(
                        f"specimen {specimen.specimen_id} container held {len(specimen.sites)} sites "
                        f"({', '.join(specimen.sites)}) submitted together -- billed as one unit"
                    ),
                    suggested_action="confirm with the submitting clinician whether separate units apply",
                )
            )
    return findings
