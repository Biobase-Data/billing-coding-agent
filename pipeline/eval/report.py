"""Render CaseScores into the evaluation report.

Rules this report follows, non-negotiably (see the build spec's
"Guardrails"): misses and spurious additions are always two separate
numbers, never netted, never expressed as one accuracy figure or as
dollars found. The unreviewed-ground-truth count is stated first, before
anything else, if it is above zero -- a scoreboard built on unreviewed
ground truth that doesn't say so is the most dangerous artifact this
project could produce.
"""

from __future__ import annotations

from pipeline.eval.scorer import CaseScore


def _fmt_keys(keys: list[tuple]) -> str:
    return ", ".join(f"{code}/{system}/{specimen}" for code, system, specimen in keys) or "none"


def build_report(case_scores: list[CaseScore], repeatability: dict[str, float] | None = None) -> str:
    lines: list[str] = []

    unreviewed = [cs.case_id for cs in case_scores if cs.unreviewed]
    if unreviewed:
        lines.append(
            f"** {len(unreviewed)} of {len(case_scores)} cases have UNREVIEWED ground truth "
            f"({', '.join(sorted(unreviewed))}) -- this is an engineering signal against our own "
            "assumptions, not evidence the product is right. Do not quote these scores outside the team. **"
        )
        lines.append("")

    total_correct = sum(len(cs.lines.correct) for cs in case_scores)
    total_missed = sum(len(cs.lines.missed) for cs in case_scores)
    total_spurious = sum(len(cs.lines.spurious) for cs in case_scores)
    total_wrong = sum(len(cs.lines.wrong_units_or_modifiers) for cs in case_scores)

    total_caught = sum(len(cs.findings.caught) for cs in case_scores)
    total_finding_missed = sum(len(cs.findings.missed) for cs in case_scores)
    total_false_alarm = sum(len(cs.findings.false_alarm) for cs in case_scores)

    lines.append(f"Corpus: {len(case_scores)} cases")
    lines.append("")
    lines.append("Lines (never netted):")
    lines.append(f"  correct:                 {total_correct}")
    lines.append(f"  missed:                  {total_missed}")
    lines.append(f"  spurious:                {total_spurious}")
    lines.append(f"  wrong units/modifiers:   {total_wrong}")
    lines.append("")
    lines.append("Findings:")
    lines.append(f"  caught:      {total_caught}")
    lines.append(f"  missed:      {total_finding_missed}")
    lines.append(f"  false alarm: {total_false_alarm}")
    lines.append("")

    if repeatability:
        lines.append("Repeatability (fraction of N runs identical to the first):")
        for case_id, fraction in sorted(repeatability.items()):
            lines.append(f"  {case_id}: {fraction:.0%}")
        lines.append("")

    lines.append("Per case:")
    for cs in sorted(case_scores, key=lambda c: c.case_id):
        flag = " [UNREVIEWED]" if cs.unreviewed else ""
        lines.append(f"  {cs.case_id}{flag}")
        lines.append(f"    lines   correct={len(cs.lines.correct)} missed={_fmt_keys(cs.lines.missed)} "
                      f"spurious={_fmt_keys(cs.lines.spurious)} wrong={_fmt_keys(cs.lines.wrong_units_or_modifiers)}")
        lines.append(f"    findings caught={cs.findings.caught or 'none'} missed={cs.findings.missed or 'none'} "
                      f"false_alarm={cs.findings.false_alarm or 'none'}")

    return "\n".join(lines) + "\n"
