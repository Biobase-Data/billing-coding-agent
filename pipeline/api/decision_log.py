"""The append-only decision log.

One JSONL file, one line per entry, opened in append mode and never
rewritten -- this is the audit posture the build spec promotes from a
demo panel to a real requirement (PRD FR-34 to FR-37), and it is also the
labelled dataset the evaluator reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.api.models import DecisionLogEntry


def append(log_path: Path, entry: DecisionLogEntry) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(entry.model_dump_json() + "\n")


def read_all(log_path: Path) -> list[DecisionLogEntry]:
    if not log_path.exists():
        return []
    entries = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(DecisionLogEntry(**json.loads(line)))
    return entries
