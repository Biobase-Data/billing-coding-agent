"""Procedure-to-procedure pairs: conflicting code pairs, and whether a
modifier can override.

This demo's ruleset ships no PTP edit rows (see rulesets/2026q3/SOURCES.md
-- the CMS NCCI PTP files were not reachable from this build sandbox), so
this check never fires against the real fixture corpus. It is exercised
directly in tests against synthetic ValidationData.
"""

from __future__ import annotations

from itertools import combinations

from pipeline.models.codes import CodeSet
from pipeline.models.findings import Finding, Severity
from pipeline.rules.materialize import ValidationData

_HAS_OVERRIDE_MODIFIER = {"59", "XE", "XS", "XP", "XU"}


def check_ptp_pairs(codes: CodeSet, validation_data: ValidationData) -> list[Finding]:
    findings: list[Finding] = []
    cpt_lines = sorted(
        (line for line in codes.lines if line.code_system == "CPT"),
        key=lambda l: l.line_id,
    )
    for line_a, line_b in combinations(cpt_lines, 2):
        for edit in validation_data.ptp_edits:
            if {edit.column1, edit.column2} != {line_a.code, line_b.code}:
                continue
            if edit.modifier_allowed == 9:
                continue  # edit does not apply
            has_override = any(
                m in _HAS_OVERRIDE_MODIFIER for line in (line_a, line_b) for m in line.modifiers
            )
            if edit.modifier_allowed == 0 or not has_override:
                severity = Severity.BLOCKER if edit.modifier_allowed == 0 else Severity.REVIEW
                findings.append(
                    Finding(
                        severity=severity,
                        line_id=line_b.line_id,
                        rule_id=f"ptp:{edit.column1}|{edit.column2}",
                        message=f"{line_a.code} and {line_b.code} conflict under this ruleset's PTP edits",
                        suggested_action=(
                            "these codes cannot be billed together"
                            if edit.modifier_allowed == 0
                            else "add an appropriate override modifier if clinically justified"
                        ),
                    )
                )
    return findings
