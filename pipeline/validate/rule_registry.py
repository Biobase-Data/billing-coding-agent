"""Every rule_id a Finding is allowed to cite, and how to resolve it.

Findings tied to CMS-sourced rule store content (MUE, PTP, coverage) cite
an id that resolves to a real row in that ruleset. The remaining checks
encode structural/documentation judgment calls (ASSUMPTIONS.md #1, #2,
#4) that are not CMS data at all -- there is no database row for them,
so their rule_ids are enumerated in `INTERNAL_RULE_IDS` (or, for
code-parameterized ones like the add-on table, checked against the fixed
mapping that defines them). A finding citing anything outside this
resolves as unresolved and fails the CI gate exactly like a dangling MUE
citation would -- see test_validator.py::test_every_finding_rule_id_resolves.
"""

from __future__ import annotations

from pipeline.rules.materialize import ValidationData

INTERNAL_RULE_IDS: frozenset[str] = frozenset(
    {
        "documentation:ihc_missing_antibody",
        "documentation:no_clinical_indication",
        "reconciliation:ordered_not_resulted",
        "reconciliation:resulted_not_billed",
        "specimen:ambiguous_site_count",
        "diagnosis:qualified_certainty",
    }
)


def resolve_rule_id(rule_id: str, validation_data: ValidationData) -> bool:
    if rule_id in INTERNAL_RULE_IDS:
        return True

    if rule_id.startswith("mue:"):
        return rule_id.removeprefix("mue:") in validation_data.mue

    if rule_id.startswith("ptp:"):
        col1, _, col2 = rule_id.removeprefix("ptp:").partition("|")
        return any({e.column1, e.column2} == {col1, col2} for e in validation_data.ptp_edits)

    if rule_id.startswith("coverage:"):
        policy_id = rule_id.removeprefix("coverage:")
        return policy_id in validation_data.covered_diagnoses

    if rule_id.startswith("add_on:"):
        # imported lazily to avoid a cycle with checks/add_on.py
        from pipeline.validate.checks.add_on import ADD_ON_DEPENDENCIES

        return rule_id.removeprefix("add_on:") in ADD_ON_DEPENDENCIES

    return False
