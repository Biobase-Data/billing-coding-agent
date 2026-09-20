# Billing and coding agent — demo build

An end-to-end pipeline that takes a finalized surgical pathology report
plus a lab's procedure records, produces a reconciled code set with
evidence attached to every line, validates it against payer rules
effective on the date of service, and presents it to a coder who
accepts, edits, or removes — with every decision logged and an
evaluation harness scoring the output against ground truth.

Runs on synthetic data (`fixtures/`) and is not production-hardened.
**Read `ASSUMPTIONS.md` first** — it records every judgment call and
open decision this build made without a commercial AP coder's sign-off,
and every place those calls are encoded in the code.

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

`pytest -q` runs everything: model/contract tests, the mapper and
validator's per-rule unit tests (positive/negative/boundary), golden
tests across the corpus, determinism tests, the rule-version-replay
test, the review API's contract tests, and the repo-wide CPT-descriptor
guard. Repeatability (extraction called live, N=20) skips itself without
`ANTHROPIC_API_KEY` — see `pipeline/eval/test_repeatability.py`.

CI (`.github/workflows/ci.yml`) runs the suite plus `pipeline.cli.eval`
and uploads the report as a build artifact.

## What's deliberately not here

Claim construction/submission, denial management, EHR integration, real
patient data, auth/multi-tenancy, live LIS connectivity, CPT descriptor
text (AMA-licensed — see ASSUMPTIONS.md), and UI component tests (the
API contract is tested; the screens are expected to change once a coder
has used them).
