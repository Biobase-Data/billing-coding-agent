"""Score a run's code set and findings against a case's golden file.

Per line: correct / missed / spurious / wrong units-or-modifiers. Findings
score separately: caught / missed / false alarm. Misses and spurious
additions are always kept as separate counts -- never netted into one
number, because direction is the whole ethical content of this product: a
system that adds five wrong lines and misses five right ones is not a
system with zero error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.models.codes import CodeSet
from pipeline.models.findings import Finding


def _line_key(line: dict) -> tuple:
    return (line["code"], line["code_system"], line["specimen_id"])


@dataclass(frozen=True)
class LineScore:
    correct: list[tuple] = field(default_factory=list)
    missed: list[tuple] = field(default_factory=list)
    spurious: list[tuple] = field(default_factory=list)
    wrong_units_or_modifiers: list[tuple] = field(default_factory=list)


@dataclass(frozen=True)
class FindingScore:
    caught: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    false_alarm: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    unreviewed: bool
    lines: LineScore
    findings: FindingScore


def score_lines(actual: CodeSet, golden_expected_lines: list[dict]) -> LineScore:
    actual_by_key = {_line_key(l.model_dump(mode="json")): l for l in actual.lines}
    golden_by_key = {_line_key(l): l for l in golden_expected_lines}

    correct, wrong, missed, spurious = [], [], [], []
    for key, golden_line in golden_by_key.items():
        actual_line = actual_by_key.get(key)
        if actual_line is None:
            missed.append(key)
            continue
        actual_dump = actual_line.model_dump(mode="json")
        if actual_dump["units"] == golden_line["units"] and sorted(actual_dump["modifiers"]) == sorted(
            golden_line["modifiers"]
        ):
            correct.append(key)
        else:
            wrong.append(key)
    for key in actual_by_key:
        if key not in golden_by_key:
            spurious.append(key)

    return LineScore(correct=correct, missed=missed, spurious=spurious, wrong_units_or_modifiers=wrong)


def score_findings(actual: list[Finding], golden_expected_findings: list[dict]) -> FindingScore:
    actual_rule_ids = {f.rule_id for f in actual}
    golden_rule_ids = {f["rule_id"] for f in golden_expected_findings}

    caught = sorted(actual_rule_ids & golden_rule_ids)
    missed = sorted(golden_rule_ids - actual_rule_ids)
    false_alarm = sorted(actual_rule_ids - golden_rule_ids)
    return FindingScore(caught=caught, missed=missed, false_alarm=false_alarm)


def score_case(
    case_id: str,
    actual_codes: CodeSet,
    actual_findings: list[Finding],
    golden: dict,
) -> CaseScore:
    return CaseScore(
        case_id=case_id,
        unreviewed=golden.get("unreviewed", True),
        lines=score_lines(actual_codes, golden["expected_lines"]),
        findings=score_findings(actual_findings, golden["expected_findings"]),
    )
