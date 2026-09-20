"""Date-based read API onto the rule store.

There is no "current" query path. Every lookup takes a date; a caller
that wants today's rules passes today's date. This is what makes running
a case retrospectively -- against the ruleset that was actually in force
on its date of service -- a normal query rather than a special case.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class NoRulesetForDateError(LookupError):
    """No ruleset row covers the requested date -- never default silently."""


@dataclass(frozen=True)
class Ruleset:
    ruleset_id: str
    effective_from: date
    effective_to: date | None
    source_note: str
    content_hash: str


@dataclass(frozen=True)
class PtpEdit:
    column1: str
    column2: str
    modifier_allowed: int  # 0 = never, 1 = with modifier, 9 = edit does not apply


@dataclass(frozen=True)
class Substitution:
    from_code: str
    to_code: str
    condition: str


class RuleStore:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RuleStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def resolve_ruleset(self, effective_date: date) -> Ruleset:
        row = self._conn.execute(
            "SELECT ruleset_id, effective_from, effective_to, source_note, content_hash "
            "FROM ruleset "
            "WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?) "
            "ORDER BY effective_from DESC LIMIT 1",
            (effective_date.isoformat(), effective_date.isoformat()),
        ).fetchone()
        if row is None:
            raise NoRulesetForDateError(
                f"no ruleset covers {effective_date.isoformat()} -- "
                "refusing to default to the current ruleset"
            )
        return Ruleset(
            ruleset_id=row["ruleset_id"],
            effective_from=date.fromisoformat(row["effective_from"]),
            effective_to=date.fromisoformat(row["effective_to"]) if row["effective_to"] else None,
            source_note=row["source_note"],
            content_hash=row["content_hash"],
        )

    def mue(self, ruleset_id: str, code: str) -> int | None:
        row = self._conn.execute(
            "SELECT max_units FROM mue WHERE ruleset_id = ? AND code = ?",
            (ruleset_id, code),
        ).fetchone()
        return row["max_units"] if row else None

    def ptp_edit(self, ruleset_id: str, code_a: str, code_b: str) -> PtpEdit | None:
        """Look up a PTP edit between two codes, in either stored direction."""
        row = self._conn.execute(
            "SELECT column1, column2, modifier_allowed FROM ptp_edit "
            "WHERE ruleset_id = ? AND ((column1 = ? AND column2 = ?) OR (column1 = ? AND column2 = ?))",
            (ruleset_id, code_a, code_b, code_b, code_a),
        ).fetchone()
        if row is None:
            return None
        return PtpEdit(
            column1=row["column1"], column2=row["column2"], modifier_allowed=row["modifier_allowed"]
        )

    def coverage_policies_for_code(self, ruleset_id: str, mac_jurisdiction: str, code: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT policy_id FROM coverage_policy "
            "WHERE ruleset_id = ? AND mac_jurisdiction = ? AND code = ?",
            (ruleset_id, mac_jurisdiction, code),
        ).fetchall()
        return [r["policy_id"] for r in rows]

    def covered_diagnoses(self, ruleset_id: str, policy_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT icd10 FROM coverage_diagnosis WHERE ruleset_id = ? AND policy_id = ?",
            (ruleset_id, policy_id),
        ).fetchall()
        return {r["icd10"] for r in rows}

    def substitution(self, ruleset_id: str, payer_class: str, from_code: str) -> Substitution | None:
        row = self._conn.execute(
            "SELECT from_code, to_code, condition FROM substitution "
            "WHERE ruleset_id = ? AND payer_class = ? AND from_code = ?",
            (ruleset_id, payer_class, from_code),
        ).fetchone()
        if row is None:
            return None
        return Substitution(from_code=row["from_code"], to_code=row["to_code"], condition=row["condition"])
