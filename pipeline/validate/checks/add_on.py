"""Add-on dependencies: an additional-unit code present without its base."""

from __future__ import annotations

from pipeline.map.catalog import IHC_ADDITIONAL_ANTIBODY_CODE, IHC_FIRST_ANTIBODY_CODE
from pipeline.models.codes import CodeSet
from pipeline.models.findings import Finding, Severity

# code -> the base code it always requires, on the same specimen.
ADD_ON_DEPENDENCIES: dict[str, str] = {
    IHC_ADDITIONAL_ANTIBODY_CODE: IHC_FIRST_ANTIBODY_CODE,
}


def check_add_on_dependencies(codes: CodeSet) -> list[Finding]:
    findings: list[Finding] = []
    by_specimen_codes: dict[str | None, set[str]] = {}
    for line in codes.lines:
        by_specimen_codes.setdefault(line.specimen_id, set()).add(line.code)

    for line in codes.lines:
        base_code = ADD_ON_DEPENDENCIES.get(line.code)
        if base_code is None:
            continue
        if base_code not in by_specimen_codes.get(line.specimen_id, set()):
            findings.append(
                Finding(
                    severity=Severity.BLOCKER,
                    line_id=line.line_id,
                    rule_id=f"add_on:{line.code}",
                    message=f"{line.code} is an add-on code requiring {base_code} on the same specimen, which is absent",
                    suggested_action=f"add {base_code} or remove {line.code}",
                )
            )
    return findings
