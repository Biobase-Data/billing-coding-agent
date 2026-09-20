"""Load the hand-written fact fixtures used before the extractor exists.

Phase 3 proves the deterministic core (mapper + validator) is correct
before any non-determinism enters, by running the pipeline end to end on
facts a human wrote instead of facts a model extracted. Phase 4 replaces
the *source* of these facts with the real extractor; this loader (and the
`hand_facts.json` files it reads) stays afterward as the regression
target extraction is diffed against.

Span verification applies here exactly as it will in the extractor's
parser: a fact whose `quoted` text doesn't literally match the document
at its offset is a fixture-authoring bug and fails loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.extract.spans import verify
from pipeline.models.case import Case
from pipeline.models.facts import Fact


class SpanMismatchError(ValueError):
    pass


def load_hand_facts(case_dir: str | Path, case: Case) -> list[Fact]:
    path = Path(case_dir) / "hand_facts.json"
    raw = json.loads(path.read_text())
    facts = [Fact(**item) for item in raw]
    for f in facts:
        document_text = case.document(f.evidence.document_id).text
        if not verify(document_text, f.evidence.start, f.evidence.end, f.evidence.quoted):
            raise SpanMismatchError(
                f"{path}: fact {f.fact_id} evidence span does not match "
                f"document {f.evidence.document_id} text"
            )
    return facts
