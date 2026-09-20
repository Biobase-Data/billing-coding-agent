"""The mapper: facts + case + ruleset -> candidate code set.

Pure function. No I/O, no model calls, no randomness, no dictionary- or
set-iteration-order dependence -- everything that could vary run to run
is sorted explicitly before it affects output. Every rule below is a
separately named, separately tested function, per the build spec.
"""

from __future__ import annotations

from pipeline.map.catalog import (
    IHC_ADDITIONAL_ANTIBODY_CODE,
    IHC_FIRST_ANTIBODY_CODE,
    MappingGapError,
    categorize_site,
    diagnosis_icd10,
    specimen_level_code,
    stain_code,
)
from pipeline.models.case import BillingArrangement, Case, Certainty
from pipeline.models.codes import CodeLine, CodeSet
from pipeline.models.facts import Fact, FactType
from pipeline.rules.materialize import MappingData
from pipeline.rules.store import Ruleset

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _lowest_confidence(facts: list[Fact]) -> str:
    return max((f.confidence.value for f in facts), key=lambda c: _CONFIDENCE_RANK[c])


def _facts_by_type_and_specimen(facts: list[Fact], fact_type: FactType) -> dict[str, list[Fact]]:
    by_specimen: dict[str, list[Fact]] = {}
    for f in facts:
        if f.fact_type is fact_type and f.specimen_id is not None:
            by_specimen.setdefault(f.specimen_id, []).append(f)
    for specimen_facts in by_specimen.values():
        specimen_facts.sort(key=lambda f: f.fact_id)
    return by_specimen


def map_specimen_units(facts: list[Fact], case: Case) -> list[CodeLine]:
    """One surgical pathology line per separately accessioned specimen.

    The container is the billing unit, never the sites inside it -- see
    ASSUMPTIONS.md #1. A container with more than one site still produces
    exactly one line here; the ambiguity itself is a validator finding,
    not a mapper decision.
    """
    specimen_facts = _facts_by_type_and_specimen(facts, FactType.SPECIMEN)
    lines: list[CodeLine] = []
    for specimen in sorted(case.specimens, key=lambda s: s.specimen_id):
        matching = specimen_facts.get(specimen.specimen_id, [])
        if not matching:
            raise MappingGapError(
                f"specimen {specimen.specimen_id!r} has no supporting 'specimen' fact "
                "-- refusing to bill a specimen the extractor never confirmed"
            )
        fact = matching[0]
        site_category = categorize_site(specimen.sites[0])
        code = specimen_level_code(specimen.procedure_type, site_category)
        lines.append(
            CodeLine(
                line_id=f"{specimen.specimen_id}-level",
                code=code,
                code_system="CPT",
                units=1,
                specimen_id=specimen.specimen_id,
                fact_ids=[fact.fact_id],
                confidence=fact.confidence.value,
                rule_id="specimen_units",
            )
        )
    return lines


def map_stains(facts: list[Fact], case: Case) -> list[CodeLine]:
    """Special stain and IHC lines, unit-counted per specimen.

    IHC distinguishes the first antibody (88342, 1 unit) from each
    additional antibody on the same specimen (88341, N-1 units on one
    line). H&E is never billed here -- it is included in the specimen
    level code from `map_specimen_units`.
    """
    stain_facts = _facts_by_type_and_specimen(facts, FactType.STAIN)
    lines: list[CodeLine] = []
    for specimen_id in sorted(stain_facts):
        facts_for_specimen = stain_facts[specimen_id]
        ihc_facts = [f for f in facts_for_specimen if f.value["kind"] == "ihc"]
        special_facts = [f for f in facts_for_specimen if f.value["kind"] == "special"]

        if ihc_facts:
            # Order of antibody assignment must be deterministic and must
            # not depend on dict/set iteration order: sort by fact_id.
            # A fact may carry an explicit value["sequence"] == "additional"
            # hint -- an addendum run coding a follow-up antibody stain
            # whose first-antibody fact belongs to an earlier, already
            # billed run and is not among this run's facts at all. Absent
            # that hint, the first fact in sorted order is the first
            # antibody, exactly as in a normal single-run extraction.
            ordered = sorted(ihc_facts, key=lambda f: f.fact_id)
            eligible_as_first = [f for f in ordered if f.value.get("sequence") != "additional"]
            if eligible_as_first:
                first = eligible_as_first[0]
                additional = [f for f in ordered if f.fact_id != first.fact_id]
            else:
                first, additional = None, ordered
            if first is not None:
                lines.append(
                    CodeLine(
                        line_id=f"{specimen_id}-ihc-first",
                        code=IHC_FIRST_ANTIBODY_CODE,
                        code_system="CPT",
                        units=1,
                        specimen_id=specimen_id,
                        fact_ids=[first.fact_id],
                        confidence=first.confidence.value,
                        rule_id="ihc_units",
                    )
                )
            if additional:
                lines.append(
                    CodeLine(
                        line_id=f"{specimen_id}-ihc-additional",
                        code=IHC_ADDITIONAL_ANTIBODY_CODE,
                        code_system="CPT",
                        units=len(additional),
                        specimen_id=specimen_id,
                        fact_ids=[f.fact_id for f in additional],
                        confidence=_lowest_confidence(additional),
                        rule_id="ihc_units",
                    )
                )

        if special_facts:
            lines.append(
                CodeLine(
                    line_id=f"{specimen_id}-special-stain",
                    code=stain_code("special"),
                    code_system="CPT",
                    units=len(special_facts),
                    specimen_id=specimen_id,
                    fact_ids=[f.fact_id for f in sorted(special_facts, key=lambda f: f.fact_id)],
                    confidence=_lowest_confidence(special_facts),
                    rule_id="special_stain_units",
                )
            )
    return lines


def map_diagnoses(facts: list[Fact]) -> list[CodeLine]:
    """ICD-10 lines from diagnosis facts.

    A `negative` certainty diagnosis never produces a code (there is
    nothing to bill for a finding that was ruled out). A `qualified`
    diagnosis is coded to the presenting finding named in the fact's
    `text`, never to whatever the qualifier speculates about -- see
    ASSUMPTIONS.md #2. `value["text"]` is always already the presenting
    finding; the speculative language lives only in `qualifier`.
    """
    diagnosis_facts = _facts_by_type_and_specimen(facts, FactType.DIAGNOSIS)
    lines: list[CodeLine] = []
    for specimen_id in sorted(diagnosis_facts):
        for fact in diagnosis_facts[specimen_id]:
            if fact.value["certainty"] == Certainty.NEGATIVE.value:
                continue
            code = diagnosis_icd10(fact.value["text"])
            lines.append(
                CodeLine(
                    line_id=f"{fact.fact_id}-dx",
                    code=code,
                    code_system="ICD10",
                    units=1,
                    specimen_id=specimen_id,
                    fact_ids=[fact.fact_id],
                    confidence=fact.confidence.value,
                    rule_id="diagnosis_selection",
                )
            )
    return lines


_COMPONENT_MODIFIER = {
    BillingArrangement.GLOBAL: None,
    BillingArrangement.PROFESSIONAL: "26",
    BillingArrangement.TECHNICAL: "TC",
}


def apply_component_modifiers(lines: list[CodeLine], case: Case) -> list[CodeLine]:
    """Component modifiers are driven by case.billing_arrangement, applied
    uniformly to every CPT line -- never inferred per line."""
    modifier = _COMPONENT_MODIFIER[case.billing_arrangement]
    if modifier is None:
        return lines
    return [
        line.model_copy(update={"modifiers": [*line.modifiers, modifier]})
        if line.code_system == "CPT"
        else line
        for line in lines
    ]


def _prostate_saturation_applies(line: CodeLine, case: Case) -> bool:
    """The one substitution rule this demo ships (ASSUMPTIONS.md /
    SOURCES.md): Medicare requires G0416 instead of per-specimen 88305
    billing for a saturation prostate biopsy with >=10 specimens."""
    if line.code != "88305":
        return False
    prostate_specimens = [
        s for s in case.specimens if categorize_site(s.sites[0]) == "prostate"
    ]
    return len(prostate_specimens) >= 10 and line.specimen_id in {
        s.specimen_id for s in prostate_specimens
    }


def apply_substitutions(lines: list[CodeLine], case: Case, mapping_data: MappingData) -> list[CodeLine]:
    """Payer-class-conditional code swaps, read from the substitution
    table rather than hardcoded -- only the *condition test* for the one
    rule this demo ships is code (see SOURCES.md); the from/to codes and
    payer class come from the rule store snapshot."""
    payer_class = case.requisition.payer.payer_class
    prostate_lines = [line for line in lines if _prostate_saturation_applies(line, case)]
    if not prostate_lines:
        return lines
    sub = mapping_data.substitutions.get((payer_class, "88305"))
    if sub is None:
        return lines
    replaced_ids = {line.line_id for line in prostate_lines}
    kept = [line for line in lines if line.line_id not in replaced_ids]
    all_fact_ids = sorted({fid for line in prostate_lines for fid in line.fact_ids})
    kept.append(
        CodeLine(
            line_id="prostate-saturation-substitution",
            code=sub.to_code,
            code_system="HCPCS",
            units=1,
            specimen_id=None,
            fact_ids=all_fact_ids,
            # A substituted line no longer traces to one specimen's
            # confidence; "medium" flags it for coder attention uniformly
            # rather than picking one contributing line's confidence.
            confidence="medium",
            rule_id="substitution",
        )
    )
    return kept


def map_codes(facts: list[Fact], case: Case, ruleset: Ruleset, mapping_data: MappingData) -> CodeSet:
    """Facts + case + ruleset -> candidate code set. Pure: everything the
    rule store might say has already been snapshotted into `mapping_data`
    by `pipeline.rules.materialize` before this function is ever called."""
    lines: list[CodeLine] = []
    lines += map_specimen_units(facts, case)
    lines += map_stains(facts, case)
    lines += map_diagnoses(facts)
    lines = apply_component_modifiers(lines, case)
    lines = apply_substitutions(lines, case, mapping_data)
    lines.sort(key=lambda line: line.line_id)
    return CodeSet(case_id=case.case_id, ruleset_id=ruleset.ruleset_id, lines=lines)
