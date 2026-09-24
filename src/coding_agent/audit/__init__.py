"""audit/ -- version stamping and the coder action log.

Every recommendation this project produces must be traceable to exactly
which model, prompt, rules table, and code-set year produced it (the
"Everything is versioned" design rule): without this, no regression
result is interpretable and no audit response is possible. This package
is where that stamp is attached, and where a coder's accept/edit/remove
decision on a recommendation line is durably recorded, append-only.
"""
