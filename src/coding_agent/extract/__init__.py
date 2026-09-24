"""extract/ -- the probabilistic layer.

This package answers "what happened in this case": how many specimens
were described, what a span of text supports, whether the model can
determine something at all. It must never answer "what is legal to
bill" -- that is `rules/`, and there is a test
(`tests/test_layer_boundary.py`) enforcing that this package does not
import from it.

Every extraction function returns either facts with evidence spans, or
an explicit abstention. There is no third option where a function
returns a best-effort guess with no evidence -- see `schema.py`.
"""
