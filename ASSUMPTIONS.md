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

8. **Three interchangeable model backends, not one.** `extract/
   specimens.py`'s `ModelClient` Protocol was already provider-agnostic
   by design (one method, `create_message`); `GroqClient` and
   `GrokClient` are two more real implementations, added when Anthropic
   account credits ran out mid-testing and alternatives were wanted.
   Both are stdlib-only (`urllib`) adapters over an OpenAI-compatible
   chat completions endpoint (Groq's and xAI's respectively, sharing
   one private helper, `_call_openai_compatible_chat`), no new
   dependency. `api/app.py`'s `_resolve_live_client()` picks Anthropic
   over Groq over Grok when more than one key is set, purely because
   Anthropic is this project's default model (`claude-sonnet-5`) — not
   a statement that any one backend produces better extractions than
   the others; that comparison hasn't been run (and would be a good use
   of `eval/repeatability.py` later). `GROQ_DEFAULT_MODEL`
   (`llama-3.3-70b-versatile`) and `GROK_DEFAULT_MODEL` (`grok-4`) are
   each provider's current general-purpose model at time of writing;
   both catalogs change faster than Anthropic's, so these are more
   likely to need bumping later than `DEFAULT_MODEL` is. Only
   `AnthropicClient` was ever verified against a live call from this
   build environment: this sandbox's outbound network policy rejects
   the CONNECT for both `api.groq.com` and `api.x.ai`, so `GroqClient`
   and `GrokClient` are written and unit-tested (mocked HTTP, matching
   each provider's documented request/response shape) but their live
   verification happens on whoever actually runs the server with a real
   key, not here.

   That gap showed up in practice, twice, on the very first live tries:

   - A real Groq key returned `403: error code 1010` first, which is
     Cloudflare's own bot-signature block (Groq's API sits behind
     Cloudflare), not an error from Groq's application at all -- caused
     by `urllib`'s default User-Agent (`Python-urllib/3.x`), which such
     WAFs commonly fingerprint and reject outright.
     `_call_openai_compatible_chat` now sends an explicit `User-Agent`
     header for this reason. xAI's key didn't trip the same block (it
     returned a proper JSON `permission-denied` from xAI's own
     application layer), so this is apparently Groq-specific WAF
     behavior, but the fix applies to both clients since they share the
     one HTTP helper.
   - Past that block, Groq then returned `404: model_not_found` for
     `GROQ_DEFAULT_MODEL`'s original value (`llama-3.3-70b-versatile`)
     -- exactly the "Groq's catalog changes faster" risk this note
     already predicted, playing out within the same session. Guessed a
     second default (`llama-3.1-8b-instant`, usually Groq's most
     universally-available model) that *also* 404'd, which is what
     motivated adding `ANTHROPIC_MODEL`/`GROQ_MODEL`/`XAI_MODEL` env var
     overrides in `_resolve_live_client()` rather than guessing a third
     time -- the actual fix was to have the real account list its own
     models via `GET /openai/v1/models`, which turned up something not
     assumed going in: **this account has no Llama chat models at all**
     (only OpenAI OSS models, Qwen, a couple of small/regional ones, plus
     Whisper for audio and Orpheus for speech synthesis, neither
     relevant here). `GROQ_DEFAULT_MODEL` is now `openai/gpt-oss-20b`,
     confirmed present in that real listing (text-only, `json_mode`
     support, 131k context) -- but which models exist on a *different*
     Groq account is still not something this codebase can assume; the
     env var override exists precisely because this catalog is per-
     account, not just per-provider-and-changing-over-time as first
     assumed.

9. **CPT surgical-pathology level recommendation — a demo-scale table,
   ported not reinvented.** `rules/cpt_level.py`'s `SPECIMEN_LEVEL_TABLE`
   and `categorize_site` are a faithful port of `pipeline/map/catalog.py`'s
   already-cited table (biopsy/skin, polypectomy/gi, biopsy/prostate ->
   88305 — the only combinations this project's own fixtures exercise),
   not a reinvention: same provenance claim (standard, widely published
   AP-coding convention, never AMA descriptor text), same posture
   (`CptLevelUnmappedError` rather than guessing a level for anything not
   in the table). One deliberate improvement carried over: whole-word
   keyword matching from the start, rather than pipeline's original
   plain-substring matching (which had a real, later-fixed bug there —
   "ear" matching inside "forearm" — for a different table in the same
   file). This table needs the same commercial-AP-coder sign-off
   `pipeline/`'s original judgment calls do before any real use.

   `extract/procedure_type.py` supplies the other half (each specimen's
   procedure type, e.g. "biopsy") the table needs; `Specimen.site` — a
   structured field from the LIS, already present on the canonical
   `Case` — supplies the site half without needing narrative extraction
   at all. A specimen with an absent or unrecognized site, or a
   procedure-type/site combination not in the table, is reported in
   `CptLevelRecommendation.unaddressed_specimen_ids` rather than
   guessed past or silently dropped.

10. **A second recommendation shape, not a shoehorned reuse of the
    first.** `recommend/cpt_level.py`'s `CptLevelFinding` carries both
    `baseline_code` and `recommended_code` on one object, rather than
    reusing `RecommendationLine`'s ADDITION/REMOVAL split. The two
    capabilities' "absence" semantics genuinely differ: a unit-
    reconciliation REMOVAL's evidence is a true absence (nothing to
    quote, so `RecommendationLine` forbids evidence on it); a wrong CPT
    level is always backed by *positive* evidence (the procedure-type
    extraction that drove the correct code), so forcing it through the
    same evidence-forbidden-on-REMOVAL rule would misrepresent the
    finding, not just reshape it. This still satisfies "never an
    additions-only code path": the same call that proposes adding a
    level for an unbilled specimen can just as easily propose a *lower*
    level for an over-billed one (see
    `test_bidirectional_single_call_can_both_add_and_change_at_once`).

    `BaselineLine` gained an optional `specimen_id` field for this
    (backward compatible — unit reconciliation never reads it, and
    every existing baseline in tests/eval fixtures omits it, defaulting
    to `None`). `audit/stamp.py`'s `stamp()` was generalized to accept
    either recommendation type via a `Recommendation | CptLevelRecommendation`
    union rather than duplicated into a second stamping function, since
    it never inspects a recommendation's contents anyway.

11. **CPT-level recommendation is live-only for now — not in the offline
    eval corpus.** `eval/cases/*.json` fixtures only ever recorded a
    specimens_v1 model response; extending them to also cover
    procedure_type_v1 (a second recorded response per fixture, plus
    expected procedure-type/CPT-level ground truth) is real, undone
    work. Until then, `eval/harness.py`'s `run_eval_case` and the test
    console's sample-corpus path only exercise unit reconciliation; CPT-
    level recommendation is only reachable through the two live-model
    custom-input paths (`/api/custom/run`, `/api/custom/pdf-run`), which
    now run both extraction tasks against the same case and return both
    recommendations together — verified end-to-end with a fake client
    standing in for the live model
    (`test_custom_run_wires_in_cpt_level_recommendation_alongside_unit_reconciliation`),
    not yet verified against a real model call from this build
    environment (same caveat as the Groq/Grok backends themselves).

12. **Evidence-span matching tolerates whitespace differences, not
    content differences.** Found via a real live PDF upload:
    `extract/spans.py`'s `locate()` rejected a real, correct model quote
    ("excision of grossly unremarkable pink-tan skin") because the PDF's
    text extraction preserved a mid-sentence line wrap as a literal
    newline in the source (`"...unremarkable\npink-tan skin..."`), while
    the model naturally reproduced its "verbatim" quote with a plain
    space instead. This was rejecting a formatting artifact as if it
    were a hallucination. `locate()` now falls back to a whitespace-
    tolerant match (any run of whitespace in the quote matches any run
    of whitespace in the source) only after an exact match fails; every
    non-whitespace character still must match exactly, and the returned
    `EvidenceSpan.quoted` is always the real source substring (offsets
    and text), never the model's normalized version -- so
    `Case.resolve_span`'s later re-verification still holds. This is
    shared by both extraction tasks (`extract/specimens.py` and
    `extract/procedure_type.py`), since both call the same `locate()`.

13. **Cassette/block identifiers were being extracted as if they were
    specimen labels -- found by inspecting a live PDF run's output, not
    a crash.** A real report described one unlettered specimen ("left
    shoulder mass") divided into cassettes for processing
    ("representative sections are submitted in cassettes A1-A7"). The
    specimen extractor reported all seven cassette identifiers
    (`A1`..`A7`) as seven distinct specimen labels. Every one of those
    quotes was real and verbatim, so span verification correctly passed
    them -- the bug was semantic, not mechanical: `specimens_v1.txt`
    never told the model that a cassette/block identifier names a
    sub-part of one specimen, not a specimen itself.

    This case happened to render harmlessly (`Blocked` on
    `accessioning_specimen_list_absent`, since a bare PDF upload has no
    structured specimen list for `rules/units.py` to reconcile against),
    but that is incidental to this input, not a property of the fix.
    Had a real accessioning record been attached showing one specimen,
    `rules/units.py` would have confidently reported six phantom
    "missing from accessioning" specimens: a false-positive specimen
    miscount, which is the exact failure mode the strategy doc names as
    highest-priority to get right, since specimen-count reconciliation
    is the entire evidentiary basis of the Phase 1 wedge.

    Fixed in the prompts (`specimens_v1.txt`, `procedure_type_v1.txt`):
    both now explicitly define cassette/block identifiers as sub-parts
    of a specimen, never a specimen in their own right, and instruct
    the model to abstain (specimens_v1) or omit that specimen
    (procedure_type_v1) rather than invent a specimen-level label from
    cassette numbers when the narrative gives a specimen no label of
    its own. This is a prompt fix, not a code fix -- there is no
    deterministic guard against it, deliberately: a regex heuristic
    distinguishing "real" labels from cassette-shaped ones would be a
    judgment call smuggled into extract/ disguised as a rule, which is
    exactly what this architecture's extract/rules split says not to
    do. Not yet re-verified against a real model call from this build
    environment (same network-access caveat as every other live-model
    claim in this document) -- the next live PDF run against this exact
    report is the actual regression test for this fix. It was verified
    live: the re-run correctly abstained (`ambiguous_narrative`, "the
    narrative only references cassette identifiers and a descriptive
    label, not a specimen-level identifier") instead of reporting seven
    phantom specimens.

14. **A raw billed-code stamp was leaking into the model's prompt --
    found by noticing it printed inside the GROSS section in the test
    console, on the same live PDF as #13.** The text right after
    "cassettes A1-A7" read "Regional Pathology Associates 88304(1)":
    a CPT code with a unit count, stamped directly onto the report with
    no "CPT CODE(S):" label at all. `normalize/free_text.py` already
    strips a *labeled* code line (`cpt code\(s\)\s*:`), but this
    unlabeled, raw form matched no existing boilerplate pattern, so it
    rode straight into the narrative text both extraction prompts
    receive. This is a real breach of the stated invariant that
    extract/ never sees a billing code -- not a hypothetical one, an
    actual live one, sitting in a prompt.

    Fixed by adding a targeted pattern, `\b\d{5}\(\d+\)`, to
    `_BOILERPLATE_LINE_PATTERNS` -- a 5-digit code immediately followed
    by a parenthesized count is distinctive enough (real narrative
    prose does not produce that shape) to strip with the same
    high-precision, allowlist-only posture as every other boilerplate
    pattern in this module. Covered by two new tests: one against the
    exact real line from #13's report, one against a multi-code stamp
    line ("88307(1), 88309(1), 88342(3), 88341(21)") seen on a second
    live PDF the same day.

15. **A different, more serious variant of the same class of bug:
    unrecognized section headers were silently discarding a real
    specimen label and an entire final diagnosis, not just noise.**
    Follows from the same-day finding above (`BC19-00056.redacted.pdf`)
    that a live narrative came back as almost nothing -- that report's
    actual extracted text was unavailable from this build environment
    at the time, so it was left open rather than guessed at.

    A second real report (uploaded directly to this session,
    `sample_surgical_pathology_report.pdf`) made the same failure mode
    reproducible with the actual source text in hand. Its real content
    included `SPECIMEN RECEIVED` / `Specimen A: Left forearm lesion`
    and a full `FINAL PATHOLOGIC DIAGNOSIS` (malignant melanoma, with
    Breslow thickness, Clark level, and margins) -- none of which
    appeared anywhere in the narrative the test console showed. Cause:
    `split_sections`' header matching requires an *exact* full-line
    match against `_HEADER_TO_NARRATIVE_KIND`, and this report used
    realistic but slightly different header wording ("SPECIMEN
    RECEIVED" vs. the recognized "SPECIMEN"; "CLINICAL HISTORY /
    PRE-OPERATIVE DIAGNOSIS" vs. "CLINICAL HISTORY"; "FINAL PATHOLOGIC
    DIAGNOSIS" vs. "PATHOLOGIC DIAGNOSIS"). An unrecognized header line
    is folded into whichever section is "currently open" -- but nothing
    was open yet (no header had matched), so the header line and every
    line after it, up to the next *recognized* header, was silently
    dropped. Not stripped as boilerplate; just gone, with no signal
    anywhere that it happened.

    This is worse than #13/#14: those produced a wrong-but-visible
    extraction. This one produced a correct-looking abstention
    ("no distinct specimen labels given") over an invisibly mutilated
    input -- exactly the "silent normalization degradation" failure
    mode the strategy doc names as one that "will be found late unless
    instrumented." It was found this time only because the actual PDF
    was available to diff against the rendered narrative by hand.

    Fixed by adding the three concretely-observed header variants to
    `_HEADER_TO_NARRATIVE_KIND` (`"CLINICAL HISTORY / PRE-OPERATIVE
    DIAGNOSIS"`, `"SPECIMEN RECEIVED"`/`"SPECIMEN(S) RECEIVED"`/
    `"SPECIMENS RECEIVED"`, `"FINAL PATHOLOGIC DIAGNOSIS"`/`"FINAL
    PATHOLOGICAL DIAGNOSIS"`) -- the same narrow, evidence-based
    allowlist growth this module's docstring already describes as its
    maintenance model, not a change of approach. Also added boilerplate
    patterns for the signing pathologist's name/credential line and the
    disclaimer that followed it in this same report, which were
    leaking into `MICROSCOPIC` (lower-severity noise, not a silent
    drop). Covered by four new tests reproducing this exact report's
    text verbatim.

    Still unresolved, and worth being explicit about: this fix closes
    the two concrete variants found so far, not the general problem.
    The header list remains a finite allowlist against an unbounded
    space of real report formats -- every LIS/lab template not yet seen
    can silently drop content the same way, with no error and no log
    line marking that it happened. There is no monitoring today that
    would catch this other than a human comparing the source PDF to
    the rendered narrative by hand, which does not scale past a demo.
    Instrumenting this (at minimum: surfacing when text was dropped
    because no section was open, distinct from the already-correct
    "this section was never present" case) is real, undone work, not
    something to treat as covered by the fixes above.

16. **First end-to-end proof, on a real report, that both recommend/
    capabilities work past the accessioning-absent block -- and a real,
    pre-existing gap it surfaced.** Every live PDF run this session
    stopped at `ACCESSIONING_SPECIMEN_LIST_ABSENT`, since a bare PDF
    never carries a structured specimen list (by design -- see
    normalize/free_text.py). `tests/test_pipeline_real_report_end_to_end.py`
    attaches a synthetic accessioning record (one specimen, "A", site
    "left forearm skin") to the real melanoma-excision report from #15,
    grounded in exactly what that narrative supports, to exercise
    `rules/units.py` and `rules/cpt_level.py` themselves rather than
    stopping at the block.

    Result: unit reconciliation reaches `AGREED` with zero discrepancy
    lines -- the narrative-extracted label ("A", from the real,
    live-verified model response) matches the accessioning record
    exactly. This is the first time in this project's history the
    actual reconciliation logic, not just extraction or abstention, has
    run to completion on a real (non-synthetic) report.

    CPT-level recommendation reaches the rules layer too, but the one
    specimen comes back in `unaddressed_specimen_ids`, not as a
    finding: `rules/cpt_level.py`'s `SPECIMEN_LEVEL_TABLE` has no entry
    for `("excision", "skin")` -- or any site category -- at all. This
    is not a regression from anything built this session: checked
    against `pipeline/map/catalog.py`, the table this was ported from,
    which never had an excision entry either. It is a real, standing
    gap: "excision" is one of only four categories
    `procedure_type_v1.txt`'s own prompt asks the model to recognize,
    yet the rules table cannot level a single one of them. Not filled
    in here -- `rules/cpt_level.py`'s own stated policy requires a
    cited source before a new table entry ("add the combination with a
    cited source, or leave it for a coder to level by hand"), and none
    is available from this build environment. Tracked as its own issue
    (github.com/Biobase-Data/billing-coding-agent#2) rather than folded
    silently into this entry, so it has a place to carry a citation
    when one is added.

    The test file is explicit, in its own docstring, about which of its
    two model responses is live-verified (specimen extraction: yes,
    matches the actual "Extracted labels: A" result observed in the
    test console) and which is not (procedure-type: a constructed
    response using a real, verbatim quote, built to exercise the rules
    path honestly -- not a claim about what a live model would say).
