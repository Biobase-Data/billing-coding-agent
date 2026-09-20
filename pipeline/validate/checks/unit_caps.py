"""Unit caps: line units against the MUE for that code in this ruleset."""

from __future__ import annotations

from pipeline.models.codes import CodeSet
from pipeline.models.findings import Finding, Severity
from pipeline.rules.materialize import ValidationData


def check_unit_caps(codes: CodeSet, validation_data: ValidationData) -> list[Finding]:
    findings: list[Finding] = []
    for line in codes.lines:
        mue = validation_data.mue.get(line.code)
        if mue is not None and line.units > mue:
            findings.append(
                Finding(
                    severity=Severity.BLOCKER,
                    line_id=line.line_id,
                    rule_id=f"mue:{line.code}",
                    message=(
                        f"{line.code} billed at {line.units} units, exceeding the "
                        f"MUE of {mue} for this ruleset"
                    ),
                    suggested_action="reduce units or split across dates of service with justification",
                )
            )
    return findings
