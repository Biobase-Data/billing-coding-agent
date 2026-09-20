"""Coverage-policy diagnosis linkage.

For each line under a coverage policy in the case's MAC jurisdiction,
does any diagnosis on that same specimen appear on that policy's list?
"""

from __future__ import annotations

from pipeline.models.case import Case
from pipeline.models.codes import CodeSet
from pipeline.models.findings import Finding, Severity
from pipeline.rules.materialize import ValidationData


def check_coverage_linkage(codes: CodeSet, case: Case, validation_data: ValidationData) -> list[Finding]:
    findings: list[Finding] = []
    mac = case.requisition.payer.mac_jurisdiction

    diagnoses_by_specimen: dict[str | None, set[str]] = {}
    for line in codes.lines:
        if line.code_system == "ICD10":
            diagnoses_by_specimen.setdefault(line.specimen_id, set()).add(line.code)

    for line in codes.lines:
        if line.code_system != "CPT":
            continue
        policy_ids = validation_data.coverage_policies.get((mac, line.code), [])
        if not policy_ids:
            continue  # no coverage policy configured for this code/jurisdiction
        specimen_diagnoses = diagnoses_by_specimen.get(line.specimen_id, set())
        if not specimen_diagnoses:
            # No diagnosis at all (e.g. a definitively negative finding)
            # is a different situation from "a diagnosis that doesn't
            # match the policy" -- linkage has nothing to link, so it is
            # silent here rather than a false coverage blocker.
            continue
        covered = any(
            specimen_diagnoses & validation_data.covered_diagnoses.get(policy_id, set())
            for policy_id in policy_ids
        )
        if not covered:
            findings.append(
                Finding(
                    severity=Severity.BLOCKER,
                    line_id=line.line_id,
                    rule_id=f"coverage:{policy_ids[0]}",
                    message=(
                        f"{line.code} is under coverage policy {policy_ids[0]} in {mac}, "
                        f"but no diagnosis on specimen {line.specimen_id} is on that policy's list"
                    ),
                    suggested_action="confirm the diagnosis or request a physician query",
                )
            )
    return findings
