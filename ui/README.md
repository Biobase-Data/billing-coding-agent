# Review UI

Three screens against the FastAPI review service in `pipeline/api/`:
Queue, Case Review (recommendation + evidence panel, side by side, never
a modal), Decision Log.

Completeness and evidence occupy the primary position on the case review
screen; the charge summary sits below the fold, deliberately -- see the
build spec's rationale (`billing-coding-agent` root, "What changes from
the PRD").

## Running locally

```
# from the repo root, in one terminal:
python -m pipeline.cli.seed_runs      # populate runs/ so the API has data
uvicorn pipeline.api.app:app --port 8000

# in another terminal:
cd ui
npm install
npm run dev
```

Vite proxies `/api/*` to `localhost:8000` in dev (see `vite.config.ts`).

## What's not tested

Per the build spec: the UI, beyond the API contract. `pipeline/api/test_app.py`
covers the contract; these screens have been exercised manually (and via
a one-off Playwright script during development) rather than with
component tests, since they're expected to change once a coder has
actually used them.
