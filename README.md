# Billing and coding agent

This repo holds two builds, in sequence:

- **`src/coding_agent/` — the V0 pathology billing & coding agent** (current
  focus). A stricter, from-scratch architecture: a canonical `Case` object
  with explicit absence semantics, a hard-enforced `extract/` ↔ `rules/`
  layer boundary, bidirectional-always recommendations (every code path
  that can add a unit can also flag one for removal), first-class
  abstention, and full version stamping on every output. V0's scope is
  narrow and deliberate: **specimen unit reconciliation, offline/
  retrospective** — reconciling the narrative's specimen labels against
  the accessioning record's specimen list, nothing more. See "V0:
  `src/coding_agent/`" below.
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
  normalize/   canonical Case object; HL7v2 ORU^R01 and FHIR R4 -> Case
  extract/     probabilistic layer -- facts + evidence spans only, never
               a billing code. specimens.py: find every specimen label
               the narrative names, or abstain.
  rules/       deterministic layer -- units.py: reconcile the narrative's
               specimen labels against the accessioning record's list.
               Pure functions, table-driven, versioned.
  recommend/   assembles rules/ + extract/ output into a bidirectional
               diff: every call computes both addition and removal
               candidates together, never one direction only.
  audit/       version-stamps every recommendation (model, prompt, rules,
               code-set year) and the append-only coder action log.
eval/          corpus harness, metrics (label precision/recall, F1,
               abstention rate), and a run-to-run repeatability check.
               eval/cases/*.json are self-contained fixtures: a Case, a
               recorded model response, and expected ground truth --
               the corpus runs offline, no API key required.
tools/
  corpus_inventory.py   normalize/-layer diagnostic: given a directory of
                        raw HL7/FHIR exports, reports which cases can
                        even supply a structured specimen list to
                        reconcile against, before any extraction runs.
tests/         test_case.py, test_normalize.py, test_extract_specimens.py,
               test_rules_units.py, test_recommend.py, test_audit.py,
               test_eval.py, test_corpus_inventory.py, and
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
  Bundle JSON and run it through a **live** model call; requires
  `ANTHROPIC_API_KEY` in the environment the server runs in, and returns
  a clear 400 without one rather than silently falling back to anything.
- **Custom PDF report** — upload a signed-out surgical pathology report
  PDF directly (`normalize/free_text.py` extracts text via `pypdf` and
  splits it into narrative sections by header keyword: Clinical History /
  Gross Description / Microscopic Description / Diagnosis). A bare PDF
  has no structured accessioning specimen list the way an HL7/FHIR feed
  does, so `Case.specimens` always comes back `Absent` here and
  reconciliation correctly reports **Blocked** rather than inventing a
  specimen count from the narrative — you'll still see what labels the
  narrative itself names. Also requires `ANTHROPIC_API_KEY`.

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
