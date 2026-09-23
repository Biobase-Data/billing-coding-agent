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

   Diagnosis codes need the same site-awareness and only partly have it:
   melanocytic nevi (D22.-) and malignant melanoma (C43.-) are coded by
   the specimen's site and, for the limbs, laterality
   (`_site_suffix_for_skin_neoplasm` in `map/catalog.py`) rather than the
   unspecified code, because real ICD-10-CM convention discourages the
   unspecified parent code when a specific one is available -- found via a
   user comparing this demo's D22.9 output against a real coder's D22.61
   for the same right-shoulder specimen. **Colon adenomas/polyps
   (D12.6/K63.5) still collapse every colonic subsite to one unspecified
   code**, the same class of simplification, not yet fixed -- flagging it
   here rather than leaving it silently inconsistent with the nevus/
   melanoma fix.

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

## V0 (`src/coding_agent/`) — interim assumptions

This build is newer and narrower in scope than `pipeline/` above (see
README.md); its own open decisions, distinct from the judgment calls
above:

1. **One uniform per-specimen code per case.** `recommend/assemble.py`
   takes a single externally-supplied `primary_code` and only ever
   proposes specimen-level ADDITION/REMOVAL flags against it
   (`recommend/schema.py`'s module docstring). A lab that bills different
   code levels per specimen based on complexity needs a follow-on
   capability this package does not yet have — V0 assumes the common
   case for routine biopsy volume, where one code level applies
   uniformly across a case's specimens.

2. **Requisition matching is always `ACCESSION_NUMBER`.** Both
   normalizers (`normalize/hl7v2.py`, `normalize/fhir.py`) read the
   clinical indication and ordering provider from the same message/
   bundle that carries the specimens, so the resulting `Requisition` is
   always exact-identifier-matched by construction. `FUZZY_NAME_DOB`
   exists on `RequisitionMatchMethod` and is tested
   (`tests/test_case.py`), but nothing produces it yet — V0 has no
   separate paper-requisition ingestion path that would need a fuzzy
   name/DOB match. Adding one means a real matching step that sets
   `match_confidence` honestly, not extending either normalizer to guess
   a fuzzy match from a single message.

3. **HL7 v2 parser limitations.** Assumes standard encoding characters
   from MSH-1/MSH-2 (a non-standard-delimiter feed is a per-LIS
   integration detail to handle upstream). HL7 escape sequences (`\F\`,
   `\.br\`, ...) inside field text are not decoded — a feed relying on
   them will produce narrative text containing the raw escape sequence.
   No PHI (PID name/DOB) is ever read into the canonical `Case`.

4. **FHIR R4 parser limitations.** Assumes exactly one `DiagnosticReport`
   per bundle; a bundle with more than one is out of scope, split it
   upstream. Only `Observation.valueString` is read for narrative text —
   `valueCodeableConcept` or `component[]`-based narrative observations
   are not supported yet. No PHI (`Patient` resource fields) is read into
   the canonical `Case`.

5. **No end-to-end CLI yet.** Each layer (`normalize/` → `extract/` →
   `rules/` → `recommend/` → `audit/`) is exercised directly by its own
   tests and by `eval/harness.py`, but nothing wires them into one
   command a lab could point at a live HL7/FHIR feed. `eval/harness.py`'s
   `run_eval_case` is the closest thing to that wiring today, and is
   deliberately eval-only (it takes a recorded model response, not a
   live `ModelClient`, by default).

6. **Free-text/PDF reports always have `specimens` absent.**
   `normalize/free_text.py` (added for the local test console's PDF
   upload path) never sets `Case.specimens` to anything but
   `Maybe.missing(Absent.NOT_SUPPLIED)` — a bare report PDF has no
   structured accessioning specimen list the way an HL7/FHIR feed does,
   and V0's own rule (`Specimen`'s docstring in `normalize/case.py`) is
   that this list is never derived by reading the narrative. This means
   a PDF-only input always reconciles to `Blocked` — correct behavior,
   not a bug, but it does mean the PDF path is only useful for seeing
   what the narrative claims, not for a real reconciliation, until it's
   paired with an actual LIS specimen list some other way.

7. **Section-splitting is a header-keyword heuristic.** Unlike the HL7/
   FHIR parsers (which read a structured field for section identity —
   OBX-3, `Observation.code`), `free_text.py` recognizes section
   boundaries only by matching a line against a fixed vocabulary of
   header spellings (`_HEADER_TO_NARRATIVE_KIND`). A report using an
   unrecognized heading degrades that section to `Absent.NOT_SUPPLIED`
   rather than guessing; it does not raise, unless *no* section is
   recognized at all. `case_id`/`accession_number`/`date_of_service` are
   never inferred from the report text — the caller (the UI form) must
   supply them, for the same guess-vs-abstain reason.

   A real PDF's flattened text also has no marker for where a section
   *ends* except the next recognized header, so signature blocks, CLIA
   numbers, and standard FDA/CLIA legal disclaimer boilerplate land
   inside whichever section is still open — found via a real redacted
   report where a cover-page disclaimer, a CPT/ICD signature line, and
   a wall of lab-legal text all ended up inside `CLINICAL_HISTORY`/
   `GROSS`. `_is_boilerplate_line` / `_END_OF_REPORT_LINE` strip a
   narrow, high-precision allowlist of such patterns (chosen to be
   generic US-clinical-lab boilerplate, not overfit to that one report)
   before the text reaches the model, because this narrative feeds a
   coder-facing recommendation and noise there is a real quality
   problem. It is not exhaustive: a facility-name/provider-code
   fragment with no matching pattern can still survive into a section,
   and a report using different disclaimer wording than the patterns
   here will pass its own boilerplate through untouched.
