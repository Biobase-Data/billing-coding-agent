"""Normalization: N LIS wire formats -> one canonical Case object.

Everything downstream (extract/, rules/, recommend/) depends only on the
`Case` object defined in `case.py`, never on HL7 or FHIR shapes directly.
"""
