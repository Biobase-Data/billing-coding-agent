"""Pathology billing & coding agent (V0: specimen unit reconciliation).

See the top-level README and this package's submodule docstrings for the
architectural commitments this code encodes -- most importantly, that
`extract/` (probabilistic) never imports from `rules/` (deterministic),
and that a recommendation with no evidence span is never emitted.
"""
