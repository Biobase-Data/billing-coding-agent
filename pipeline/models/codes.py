"""The candidate code set the mapper produces."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CodeLine(Frozen):
    line_id: str
    code: str
    code_system: str  # "CPT" | "HCPCS" | "ICD10"
    units: int
    modifiers: list[str] = []
    specimen_id: str | None
    fact_ids: list[str]
    confidence: str  # high | medium | low -- the lowest confidence among supporting facts
    rule_id: str  # the named mapping rule that produced this line, e.g. "specimen_units"

    @field_validator("fact_ids")
    @classmethod
    def _must_cite_at_least_one_fact(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a code line with no supporting fact is a bug, not a shortcut")
        return v

    @field_validator("units")
    @classmethod
    def _units_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("units must be >= 1")
        return v


class CodeSet(Frozen):
    case_id: str
    ruleset_id: str
    lines: list[CodeLine] = []
