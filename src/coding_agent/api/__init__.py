"""api/ -- a local-only FastAPI service for exercising the V0 pipeline by
hand: run the sample corpus (eval/cases/, no API key required) or paste
your own HL7v2/FHIR text through the real model, and record coder
actions against the result. Not a production review service -- see
pipeline/api/ for that pattern against the older demo build; this exists
purely to make src/coding_agent/ testable without writing Python.
"""
