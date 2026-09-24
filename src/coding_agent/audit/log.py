"""The coder action log: append-only, one JSON record per accept, edit,
or removal a coder makes against a recommendation line.

Append-only because this is the record a False Claims Act defense or an
audit response leans on -- "what did the coder actually decide, and
when" must never be edited after the fact, only added to.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


class CoderAction(str, Enum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    REMOVED = "removed"


class CoderActionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    line_index: int
    """Index into the Recommendation's `lines` tuple this action concerns."""

    action: CoderAction
    reason: str | None = None
    recorded_at: datetime

    @model_validator(mode="after")
    def _reason_required_unless_accepted(self) -> "CoderActionRecord":
        if self.action is not CoderAction.ACCEPTED and not (self.reason or "").strip():
            raise ValueError(f"{self.action.value} actions must carry a non-empty reason")
        return self


class ActionLog:
    """Append-only, newline-delimited JSON log at `path`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, record: CoderActionRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def read_all(self) -> list[CoderActionRecord]:
        if not self._path.exists():
            return []
        records = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(CoderActionRecord.model_validate_json(line))
        return records


def record_action(
    log: ActionLog,
    *,
    case_id: str,
    line_index: int,
    action: CoderAction,
    reason: str | None = None,
) -> CoderActionRecord:
    record = CoderActionRecord(
        case_id=case_id,
        line_index=line_index,
        action=action,
        reason=reason,
        recorded_at=datetime.now(timezone.utc),
    )
    log.append(record)
    return record
