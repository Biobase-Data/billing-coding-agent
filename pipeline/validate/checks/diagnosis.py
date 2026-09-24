"""Qualified diagnoses always need a human to confirm the coding choice.

The mapper already applies the interim rule (code the presenting finding,
never the suspected condition -- ASSUMPTIONS.md #2); this check exists so
that choice is never silent.
"""

from __future__ import annotations

from pipeline.models.case import Certainty
from pipeline.models.facts import Fact, FactType
from pipeline.models.findings import Finding, Severity


def check_qualified_diagnosis(facts: list[Fact]) -> list[Finding]:
    findings: list[Finding] = []
    for fact in facts:
        if fact.fact_type is FactType.DIAGNOSIS and fact.value["certainty"] == Certainty.QUALIFIED.value:
            findings.append(
                Finding(
                    severity=Severity.REVIEW,
                    line_id=f"{fact.fact_id}-dx",
                    rule_id="diagnosis:qualified_certainty",
                    message=(
                        f"specimen {fact.specimen_id}: {fact.value['text']!r} was qualified "
                        f"({fact.value.get('qualifier')!r}) -- coded to the presenting finding, "
                        "not the suspected condition"
                    ),
                    suggested_action="confirm the coding choice reflects this payer's guidance for qualified diagnoses",
                )
            )
    return findings
