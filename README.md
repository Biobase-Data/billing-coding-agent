# Billing and coding agent

This repo holds two builds, in sequence:

- **`src/coding_agent/` — the V0 pathology billing & coding agent** (current
  focus). A stricter, from-scratch architecture: a canonical `Case` object
  with explicit absence semantics, a hard-enforced `extract/` ↔ `rules/`
  layer boundary, bidirectional-always recommendations (every code path
  that can add a code or unit can also flag one for removal or correction),
  first-class abstention, and full version stamping on every output. V0's
  scope started narrow and deliberate — **specimen unit reconciliation,
  offline/retrospective** — and has since grown one capability:
  **CPT surgical-pathology level recommendation** (88302-88309), still
  offline/retrospective, still bare code identifiers only. ICD-10 diagnosis
  coding, stains/IHC, and modifiers remain out of scope for V0 (they exist
  only in the older `pipeline/` build below). See "V0: `src/coding_agent/`"
  below.
- **`pipeline/` — the earlier demo build** (described in the rest of this
  file). A broader, phase-built pipeline (extraction → deterministic
  mapping → validation → coder review UI → evaluation) covering CPT
  leveling and ICD-10 diagnosis mapping, not just unit reconciliation.
  Still present, still tested, but superseded as the active build — new
  work happens in `src/coding_agent/`.

Both run on synthetic data and are not production-hardened. **Read
`ASSUMPTIONS.md` first** — it records every judgment call and open
decision either build made without a commercial AP coder's sign-off, and
every place those calls are encoded in the code.

## V0: `src/coding_agent/`

```
src/coding_agent/
  normalize/   canonical Case object; HL7v2 ORU^R01 and FHIR R4 -> Case;
               free_text.py for signed-out report PDFs (specimens always
               come back Absent there -- see its own docstring).
  extract/     probabilistic layer -- facts + evidence spans only, never
               a billing code.
                 specimens.py: find every specimen label the narrative
                 names, or abstain. Also home to the shared model-client
                 machinery (Anthropic/Groq/Grok adapters) every
                 extraction task uses.
                 procedure_type.py: find each specimen's procedure type
                 (biopsy, excision, polypectomy, ...), or abstain --
                 feeds CPT leveling below.
  rules/       deterministic layer -- pure functions, table-driven,
               versioned, one file per concern.
                 units.py: reconcile the narrative's specimen labels
                 against the accessioning record's list.
                 cpt_level.py: specimen procedure-type + site -> CPT
                 surgical-pathology level (88302-88309); a demo-scale
                 table (ported from the pipeline/ build's own cited
                 table), raises rather than guessing past a combination
                 it doesn't have.
  recommend/   assembles rules/ + extract/ output into a bidirectional
               diff, one file per capability, sharing Blocked/
               BlockedReason/BaselineLine (recommend/schema.py):
                 assemble.py: specimen-unit ADDITION/REMOVAL -- every
                 call computes both candidates together, never one
                 direction only.
                 cpt_level.py: a CptLevelFinding per specimen whose
                 recommended code differs from its baseline (or has
                 none) -- addition and correction from the same call,
                 including corrections that lower what's billed.
  audit/       version-stamps every recommendation, either capability's
               (model, prompt, rules, code-set year) and the append-only
               coder action log.
  api/         local-only FastAPI test console + a single-page vanilla-JS
               UI -- run the offline sample corpus, or paste HL7/FHIR/
               upload a PDF against a live model (Anthropic/Groq/Grok).
               See "Local test console" below.
eval/          corpus harness, metrics (label precision/recall, F1,
               abstention rate), and a run-to-run repeatability check.
               eval/cases/*.json are self-contained fixtures: a Case, a
               recorded model response, and expected ground truth --
               the corpus runs offline, no API key required. (Currently
               specimen-unit reconciliation only; CPT-level recommendation
               isn't in the offline corpus yet -- see ASSUMPTIONS.md.)
tools/
  corpus_inventory.py   normalize/-layer diagnostic: given a directory of
                        raw HL7/FHIR exports, reports which cases can
                        even supply a structured specimen list to
                        reconcile against, before any extraction runs.
tests/         one test file per module above, plus
               test_layer_boundary.py -- an AST-based static check (with
               a self-verifying meta-test) that extract/ and rules/
               never import each other.
```

`extract/` never imports `rules/`, and `rules/` never imports `extract/`
— this is enforced by `tests/test_layer_boundary.py`, not just convention.
A `RecommendationLine` of kind `ADDITION` must carry evidence; one of kind
`REMOVAL` must not (its finding *is* the absence of narrative support) —
enforced by a pydantic validator in `recommend/schema.py`.

Run just this build's tests:

```bash
source .venv/bin/activate
pytest tests/ -q
python -m tools.corpus_inventory tests/fixtures/hl7v2 tests/fixtures/fhir --json
```

### Local test console (`src/coding_agent/api/`)

A small FastAPI service + single-page vanilla-JS UI for exercising the
pipeline by hand, no build step required:

```bash
source .venv/bin/activate
PYTHONPATH=src:. uvicorn coding_agent.api.app:app --reload --port 8010
# open http://localhost:8010
```

It gives you three ways to try it:

- **Sample corpus** — the `eval/cases/` fixtures, run through the real
  normalize/extract/rules/recommend/audit code path with a *recorded*
  model response (`eval/harness.py`'s `ReplayClient`), so it works with
  **no API key**. Pick a case, click "Run pipeline", see the
  recommendation lines and accept/edit/remove them (recorded to
  `runs/coding_agent_actions/<case_id>.jsonl`, gitignored).
- **Custom HL7v2/FHIR input** — paste your own HL7v2 message or FHIR R4
  Bundle JSON and run it through a **live** model call; returns a clear
  400 without a key configured rather than silently falling back to
  anything. Both extraction tasks run against it: specimen-unit
  reconciliation *and* CPT-level recommendation, shown as two separate
  result cards.
- **Custom PDF report** — upload a signed-out surgical pathology report
  PDF directly (`normalize/free_text.py` extracts text via `pypdf` and
  splits it into narrative sections by header keyword: Clinical History /
  Gross Description / Microscopic Description / Diagnosis, stripping a
  narrow allowlist of signature-block/CLIA/legal boilerplate before the
  text reaches the model). A bare PDF has no structured accessioning
  specimen list the way an HL7/FHIR feed does, so `Case.specimens`
  always comes back `Absent` here and **both** capabilities correctly
  report Blocked rather than inventing a specimen count or a site from
  the narrative — you'll still see what labels and procedure types the
  narrative itself names.

The two live-model paths need a key for **any one** of three
interchangeable backends (`extract/specimens.py`'s `ModelClient` Protocol
is provider-agnostic by design — `_resolve_live_client()` in `api/app.py`
just picks whichever is set, in this order):

- `ANTHROPIC_API_KEY` — this project's default, `claude-sonnet-5`.
- `GROQ_API_KEY` — a free-tier alternative hosting open-source models
  (get one at [console.groq.com](https://console.groq.com)), useful for
  testing without any Anthropic spend. Defaults to `openai/gpt-oss-20b`.
  Which models a given Groq account can use varies (verified against a
  real account: no Llama chat models at all, only OpenAI OSS/Qwen/a few
  others — see `GET /openai/v1/models` with your own key), so if the
  default 404s as `model_not_found`, list your account's actual models
  and set `GROQ_MODEL` to one of them. Not to be confused with the next
  one — "Groq" (the inference host) and "Grok" (xAI's model) are easy
  to mix up but are different services with different keys.
- `XAI_API_KEY` — xAI's Grok API (api.x.ai), a paid/metered API like
  Anthropic's, not a free tier. Defaults to `grok-4`.

Each backend's model can be overridden without a code change —
`ANTHROPIC_MODEL` / `GROQ_MODEL` / `XAI_MODEL` — since Groq's and xAI's
catalogs move fast enough that a hardcoded default can go stale (this
happened once already during this project's own testing: a "model does
not exist" 404 from Groq).

This is a hand-testing console, not a production review service — see
`pipeline/api/` for that pattern applied to the older demo build.

There is no CLI wiring the layers together outside of the API/eval
harness yet; see `ASSUMPTIONS.md` for what else V0 has deliberately
deferred.

---

## `pipeline/` — the earlier demo build

An end-to-end pipeline that takes a finalized surgical pathology report
plus a lab's procedure records, produces a reconciled code set with
evidence attached to every line, validates it against payer rules
effective on the date of service, and presents it to a coder who
accepts, edits, or removes — with every decision logged and an
evaluation harness scoring the output against ground truth.

Runs on synthetic data (`fixtures/`) and is not production-hardened.

## The one principle

The language model extracts facts (with a character-span citation for
every one). A deterministic engine assigns codes and validates them. No
code is ever produced by sampling from a model — if you find a prompt
asking the model for a CPT code, that's a bug.

## Architecture

```
fixtures  ->  [adapter]  ->  canonical Case
                                  |
                     [extractor] (LLM; Phase 4)  ->  Facts (with evidence spans)
                                  |
                          [mapper] (pure)  ->  CodeSet
                                  |
                        [validator] (pure)  ->  Findings
                                  |
                    [review API + UI]  ->  coder decisions (append-only log)
                                  |
                           [evaluator]  ->  scored report
```

Every run writes a directory under `runs/<case_id>/<run_id>/` (case,
facts, codes, findings, recommendation, manifest) — gitignored, one CLI
invocation away from being regenerated.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                    # full suite (see below)

python -m pipeline.cli.run --case case_01    # one case, hand-written facts
python -m pipeline.cli.run --case case_01 --facts-source extract  # needs ANTHROPIC_API_KEY
python -m pipeline.cli.eval                  # score the whole golden corpus, write a report
python -m pipeline.cli.diff --case-id <id> --run-a <run> --run-b <run>  # e.g. case 15's amendment

python -m pipeline.cli.seed_runs             # populate runs/ for the API/UI to serve
uvicorn pipeline.api.app:app --port 8000     # review API
cd ui && npm install && npm run dev          # review UI (proxies /api to :8000)
```

## Repo layout

```
pipeline/
  adapters/   source-specific -> canonical Case (fixture.py today)
  models/     Pydantic schemas: Case, Fact, CodeLine/CodeSet, Finding, RunManifest
  extract/    the three extraction prompts, runner, span-verifying parser,
              hand_facts.py (Phase 3's stand-in for the extractor)
  rules/      SQLite rule store: schema, loader, date-based resolution
  map/        map_codes -- pure, every rule named and separately tested
  validate/   validate -- pure, one check module per rule
  eval/       scorer, report, corpus diff, repeatability/rule-version-replay tests
  api/        FastAPI review service + append-only decision log
  cli/        run.py, eval.py, diff.py, seed_runs.py
fixtures/
  cases/      15 synthetic cases (case_15 has an initial + amended variant)
  golden/     expected output per case, all "unreviewed": true
rulesets/2026q3/  one dated ruleset; see SOURCES.md for exactly where every
                  row came from (and its limits — this sandbox's network
                  policy blocked cms.gov directly)
ui/           React + TypeScript review interface (Queue, Case Review, Decision Log)
```

## Testing

`pytest -q` from the repo root runs both builds' suites together (V0's
`tests/` plus `pipeline/`'s own tests, per `pyproject.toml`'s
`testpaths`). For `pipeline/` specifically: model/contract tests, the
mapper and validator's per-rule unit tests (positive/negative/boundary),
golden tests across the corpus, determinism tests, the rule-version-replay
test, the review API's contract tests, and the repo-wide CPT-descriptor
guard. Repeatability (extraction called live, N=20) skips itself without
`ANTHROPIC_API_KEY` — see `pipeline/eval/test_repeatability.py`. V0 has
its own offline repeatability check (`eval/repeatability.py`) that runs
against any `ModelClient`, including a live one when a key is available.

CI (`.github/workflows/ci.yml`) runs the suite plus `pipeline.cli.eval`
and uploads the report as a build artifact.

## What's deliberately not here

Claim construction/submission, denial management, EHR integration, real
patient data, auth/multi-tenancy, live LIS connectivity, CPT descriptor
text (AMA-licensed — see ASSUMPTIONS.md), and UI component tests (the
API contract is tested; the screens are expected to change once a coder
has used them). This section describes `pipeline/`; V0's own scope
boundary is the "specimen unit reconciliation, offline/retrospective"
line above — CPT/ICD-10 leveling, live/streaming ingestion, and a coder
review UI for V0's output are all out of scope for this iteration.
