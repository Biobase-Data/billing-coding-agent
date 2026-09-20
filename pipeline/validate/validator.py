"""The validator: code set + case + rule store snapshot -> findings.

Pure function, exactly like the mapper -- no I/O, no model calls, no
randomness. `validation_data` is a plain-data snapshot of the rule store
(`pipeline.rules.materialize.load_validation_data`), never a live
database handle.
"""

from __future__ import annotations

from pipeline.models.case import Case
from pipeline.models.codes import CodeSet
from pipeline.models.facts import Fact
from pipeline.models.findings import Finding
from pipeline.rules.materialize import ValidationData
from pipeline.validate.checks.add_on import check_add_on_dependencies
from pipeline.validate.checks.coverage import check_coverage_linkage
from pipeline.validate.checks.diagnosis import check_qualified_diagnosis
from pipeline.validate.checks.documentation import (
    check_clinical_indication_present,
    check_ihc_missing_antibody,
)
from pipeline.validate.checks.ptp_pairs import check_ptp_pairs
from pipeline.validate.checks.reconciliation import (
    check_ordered_not_resulted,
    check_resulted_not_billed,
)
from pipeline.validate.checks.specimen import check_specimen_ambiguity
from pipeline.validate.checks.unit_caps import check_unit_caps


def validate(codes: CodeSet, case: Case, facts: list[Fact], validation_data: ValidationData) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_unit_caps(codes, validation_data)
    findings += check_ptp_pairs(codes, validation_data)
    findings += check_add_on_dependencies(codes)
    findings += check_coverage_linkage(codes, case, validation_data)
    findings += check_ihc_missing_antibody(facts)
    findings += check_clinical_indication_present(case)
    findings += check_ordered_not_resulted(case)
    findings += check_resulted_not_billed(facts, case)
    findings += check_specimen_ambiguity(case)
    findings += check_qualified_diagnosis(facts)
    return findings
