"""Snapshot the rule store into plain, immutable data.

The mapper and validator are pure functions: no I/O, no live database
handle. This module is the one place that touches `RuleStore` on the
pipeline's behalf, once per run, so `map_codes` and `validate` receive
already-materialized data and stay provably deterministic and testable
with nothing more than plain Python objects.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.rules.store import PtpEdit, RuleStore, Substitution


@dataclass(frozen=True)
class MappingData:
    substitutions: dict[tuple[str, str], Substitution]  # (payer_class, from_code) -> Substitution


@dataclass(frozen=True)
class ValidationData:
    mue: dict[str, int]
    ptp_edits: list[PtpEdit]
    coverage_policies: dict[tuple[str, str], list[str]]  # (mac_jurisdiction, code) -> [policy_id]
    covered_diagnoses: dict[str, set[str]]  # policy_id -> {icd10, ...}


def load_mapping_data(store: RuleStore, ruleset_id: str) -> MappingData:
    subs = store.all_substitutions(ruleset_id)
    return MappingData(substitutions={(s.payer_class, s.from_code): s for s in subs})


def load_validation_data(store: RuleStore, ruleset_id: str) -> ValidationData:
    return ValidationData(
        mue=store.all_mue(ruleset_id),
        ptp_edits=store.all_ptp_edits(ruleset_id),
        coverage_policies=store.all_coverage_policies(ruleset_id),
        covered_diagnoses=store.all_covered_diagnoses(ruleset_id),
    )
