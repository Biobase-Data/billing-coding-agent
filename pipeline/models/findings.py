"""Findings: what the validator attaches to a code line, or to the case."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Severity(str, Enum):
    BLOCKER = "blocker"
    REVIEW = "review"
    INFORMATIONAL = "informational"


class Finding(Frozen):
    severity: Severity
    line_id: str | None
    rule_id: str
    message: str
    suggested_action: str | None = None
