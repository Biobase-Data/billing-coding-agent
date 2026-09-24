"""recommend/ -- assembles extract/'s facts and rules/'s deterministic
findings into what a coder actually sees: a diff against the lab's
baseline coding, always bidirectional, every line carrying evidence or
an explicit reason it has none.

This package may import both extract/ and rules/ -- it sits above the
extract/rules boundary, it does not participate in it.
"""
