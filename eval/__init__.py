"""eval/ -- run the V0 pipeline over a synthetic corpus and report metrics.

This is a top-level package (not under src/coding_agent/) because it is a
consumer of that package's public surface, not part of it: nothing under
src/coding_agent/ may import from here. Cases live in eval/cases/ as
self-contained JSON fixtures -- a canonical Case, a recorded model
response, and the expected ground truth -- so the corpus runs offline,
with no live API key or network access required, while still exercising
the real extraction parsing and span-locating code paths (see
eval/harness.py's ReplayClient).
"""
