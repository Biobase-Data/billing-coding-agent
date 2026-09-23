"""rules/ -- the deterministic layer.

This package answers "what is legal to bill" (and, in V0, "does the
narrative-described specimen count agree with what was accessioned").
Table-driven, versioned, auditable, and 100% repeatable -- any run-to-run
variance here is a bug, never accepted noise (see eval/repeatability.py).

`extract/` must never be imported here, and this package must never
import `extract/` either: the deterministic layer consumes extraction
*output* (already-verified facts) as plain data, not by reaching back
into the probabilistic layer's internals.
"""
