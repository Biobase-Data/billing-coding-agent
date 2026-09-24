"""Build a SQLite rule store from a ruleset source directory.

A ruleset directory (e.g. ``rulesets/2026q3/``) holds one ``ruleset.json``
describing everything in schema.sql's child tables for that one dated
ruleset, plus a ``SOURCES.md`` recording where every row came from (not
loaded by code — it is there for a human to audit).

Rulesets are immutable once written: loading a ruleset id a second time
with different content raises rather than overwriting the row, so a
quarterly update always requires a new ruleset id / effective_from rather
than silently mutating history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class RulesetConflictError(ValueError):
    """A ruleset id already exists in the store with different content."""


def _content_hash(ruleset: dict) -> str:
    payload = {k: v for k, v in ruleset.items() if k != "source_note"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


def load_ruleset_dir(conn: sqlite3.Connection, ruleset_dir: str | Path) -> str:
    """Load one ruleset directory's ruleset.json into the store.

    Returns the ruleset_id. Safe to call twice with the same, unmodified
    directory (no-op the second time); raises if the on-disk content for
    an existing ruleset_id has changed underneath it.
    """
    ruleset_dir = Path(ruleset_dir)
    raw = json.loads((ruleset_dir / "ruleset.json").read_text())
    ruleset_id = raw["ruleset_id"]
    content_hash = _content_hash(raw)

    cur = conn.execute(
        "SELECT content_hash FROM ruleset WHERE ruleset_id = ?", (ruleset_id,)
    )
    row = cur.fetchone()
    if row is not None:
        if row[0] != content_hash:
            raise RulesetConflictError(
                f"ruleset {ruleset_id!r} already loaded with a different "
                "content hash -- rulesets are immutable once written; use "
                "a new ruleset_id / effective_from for a revision"
            )
        return ruleset_id

    conn.execute(
        "INSERT INTO ruleset (ruleset_id, effective_from, effective_to, "
        "source_note, content_hash) VALUES (?, ?, ?, ?, ?)",
        (
            ruleset_id,
            raw["effective_from"],
            raw.get("effective_to"),
            raw["source_note"],
            content_hash,
        ),
    )
    for m in raw.get("mue", []):
        conn.execute(
            "INSERT INTO mue (ruleset_id, code, max_units, adjudication_type) "
            "VALUES (?, ?, ?, ?)",
            (ruleset_id, m["code"], m["max_units"], m["adjudication_type"]),
        )
    for p in raw.get("ptp_edit", []):
        conn.execute(
            "INSERT INTO ptp_edit (ruleset_id, column1, column2, modifier_allowed) "
            "VALUES (?, ?, ?, ?)",
            (ruleset_id, p["column1"], p["column2"], p["modifier_allowed"]),
        )
    for cp in raw.get("coverage_policy", []):
        conn.execute(
            "INSERT INTO coverage_policy (ruleset_id, policy_id, mac_jurisdiction, code) "
            "VALUES (?, ?, ?, ?)",
            (ruleset_id, cp["policy_id"], cp["mac_jurisdiction"], cp["code"]),
        )
    for cd in raw.get("coverage_diagnosis", []):
        conn.execute(
            "INSERT INTO coverage_diagnosis (ruleset_id, policy_id, icd10) "
            "VALUES (?, ?, ?)",
            (ruleset_id, cd["policy_id"], cd["icd10"]),
        )
    for s in raw.get("substitution", []):
        conn.execute(
            "INSERT INTO substitution (ruleset_id, payer_class, from_code, to_code, condition) "
            "VALUES (?, ?, ?, ?, ?)",
            (ruleset_id, s["payer_class"], s["from_code"], s["to_code"], s["condition"]),
        )
    conn.commit()
    return ruleset_id


def build_store(db_path: str | Path, ruleset_dirs: list[str | Path]) -> None:
    """Create (or reopen) a rule store db and load a list of ruleset dirs."""
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        for d in ruleset_dirs:
            load_ruleset_dir(conn, d)
    finally:
        conn.close()
