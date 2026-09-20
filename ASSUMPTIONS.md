# Open decisions and interim assumptions

The build spec lists four coding judgments that need a commercial AP coder to
settle, plus five open decisions that block shipping outside the team. None of
them block *starting* the build, so this file records the interim, clearly-
flagged default used in the demo for each one, and what changes if a coder or
stakeholder answers differently. Every place in the code that encodes one of
these guesses points back here with a comment.

## Judgment calls (need an AP coder) — Owner: Todd, then Vamsi

1. **Counting rule for multiple sites in one container.**
   Interim: each *separately accessioned container* is one specimen/unit for
   surgical pathology leveling, regardless of how many sites are listed
   inside it (`map/rules/specimen_units.py`). The multi-site case (fixture 3)
   is always surfaced as a `review`-severity finding so a human confirms the
   count before it ships — never billed silently as multiple units.

2. **Qualified diagnosis -> code mapping.**
   Interim: a `qualified` certainty diagnosis ("suspicious for", "cannot
   exclude") maps to the ICD-10 code for the *presenting finding actually
   described* (e.g. the lesion/biopsy finding), never to the code for the
   *suspected* condition. This is the outpatient/AP-safe default — coding the
   suspected condition is inpatient-only guidance per ICD-10-CM Official
   Guidelines Section IV, and our one coder interview described inpatient
   practice, which the spec explicitly says not to copy across without
   checking. `negative` certainty never contributes a code for the negated
   condition. This is a `review` finding, never silently applied without a
   trace back to the source fact.

3. **Site-to-level mappings for surgical pathology codes.**
   Interim: a small, explicitly cited table in `map/catalog.py` covering only
   the specimen types the fixtures exercise (skin biopsy, GI biopsy, simple
   excision, etc.) mapped to CPT 88302-88309 levels per the AMA's own
   published level descriptions (levels only, no descriptor text copied —
   see licensing note below). Anything not in the table raises rather than
   guessing a level.

4. **Which findings are `blocker` vs `review`.**
   Interim severity table in `validate/severity.py`:
   `blocker` = MUE unit cap exceeded, PTP conflict with no allowed modifier,
   add-on code with no base code present, coverage-policy diagnosis linkage
   failure. `review` = everything else that changes what gets billed
   (ordered/not-resulted, resulted/not in report, ambiguous specimen count,
   qualified diagnosis, missing antibody name). `informational` = no clinical
   indication documented in the requisition. This list is deliberately short
   per the spec's own instruction that it must stay scannable.

## Standing decisions — do not block the build, block shipping it

- **CPT licence.** No CPT descriptor text appears anywhere in this repo.
  `rulesets/*/cpt_descriptors.json` ships with placeholder strings clearly
  marked `"PLACEHOLDER — no AMA licence"`. A licensed descriptor file drops
  in at the same path/shape later. Flag to Sam/Todd before any customer-
  facing use. CI greps the repo for CPT descriptor text patterns as a guard.
- **AP coder for golden-file sign-off.** Every `golden.json` in this repo
  carries `"unreviewed": true` until a coder signs off. The eval report
  states the unreviewed count at the top, always.
- **MAC jurisdiction / payer mix.** Demo uses a single synthetic MAC
  jurisdiction (`"DEMO-MAC-J5"`) and a single synthetic commercial payer
  class plus Medicare, sourced from public CMS NCCI/MUE files (not
  jurisdiction-specific LCDs, which need Todd's answer on which MACs to
  model). `rulesets/2026q3/source_note` fields record exactly what was
  pulled and when.
- **Repeatability threshold.** Not yet measured — Phase 4 requires live
  `ANTHROPIC_API_KEY` access, unavailable in this build environment. The
  repeatability test (`pipeline/eval/test_repeatability.py`) and CLI flag
  exist and run against N=20 once a key is available; the threshold is a
  `TODO` in `pyproject.toml` pending that measurement, per spec instructions
  to observe first and set the gate second.
- **Whether to build the review UI before a coder is interviewed.** Built
  anyway per the phase sequence in the spec, since the task specifies all six
  phases; flagging here that Phase 5 is the one most likely to be reworked
  once a coder has used it.
