"""Inventory a directory of raw LIS exports (HL7 v2 ORU^R01 messages,
FHIR R4 bundles) for V0 integration health, before any extraction or
rules logic ever runs.

This is a normalize/-layer diagnostic, not part of the pipeline: it
answers "can this corpus even be normalized into a canonical Case with a
structured specimen list to reconcile against" -- the question
`Case.specimens` being `Maybe.missing` exists to let downstream code
answer honestly (see normalize/case.py's module docstring). A corpus
where most files can't supply a specimen list is not a V0 unit-
reconciliation opportunity yet; it's an LIS integration gap to fix first.

Usage:
    python -m tools.corpus_inventory <directory> [--json]
"""

from __future__ import annotations

import json as json_module
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from coding_agent.normalize.case import Absent, Case
from coding_agent.normalize.fhir import FhirNormalizationError, parse_bundle
from coding_agent.normalize.hl7v2 import Hl7NormalizationError, parse_oru

_HL7_SUFFIXES = {".hl7"}
_FHIR_SUFFIXES = {".json"}


@dataclass(frozen=True)
class FileInventory:
    path: str
    ok: bool
    case_id: str | None = None
    specimens_present: bool | None = None
    specimen_count: int | None = None
    specimens_absent_reason: str | None = None
    narrative_sections_with_text: int | None = None
    narrative_sections_total: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class InventorySummary:
    total_files: int
    parsed: int
    parse_failures: int
    specimens_absent: int
    """Parsed cases whose accessioning record could not supply a
    structured specimen list at all -- the integration blocker this tool
    exists to surface."""
    no_narrative_text: int
    """Parsed cases with zero narrative sections carrying any text."""


def _case_from_file(path: Path) -> Case:
    if path.suffix in _HL7_SUFFIXES:
        return parse_oru(path.read_text())
    if path.suffix in _FHIR_SUFFIXES:
        return parse_bundle(json_module.loads(path.read_text()))
    raise ValueError(f"unsupported file extension {path.suffix!r} -- expected one of {_HL7_SUFFIXES | _FHIR_SUFFIXES}")


def inspect_file(path: Path) -> FileInventory:
    try:
        case = _case_from_file(path)
    except (Hl7NormalizationError, FhirNormalizationError, ValueError, json_module.JSONDecodeError) as exc:
        return FileInventory(path=str(path), ok=False, error=str(exc))

    specimens_present = case.specimens.is_present
    narrative_with_text = sum(1 for section in case.narrative if section.text.is_present)

    return FileInventory(
        path=str(path),
        ok=True,
        case_id=case.case_id,
        specimens_present=specimens_present,
        specimen_count=len(case.specimens.value) if specimens_present else None,
        specimens_absent_reason=(
            None if specimens_present else _absent_reason_label(case.specimens.absent)
        ),
        narrative_sections_with_text=narrative_with_text,
        narrative_sections_total=len(case.narrative),
    )


def _absent_reason_label(reason: Absent | None) -> str | None:
    return reason.value if reason is not None else None


def inspect_directory(directory: Path) -> list[FileInventory]:
    paths = sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix in (_HL7_SUFFIXES | _FHIR_SUFFIXES)
    )
    return [inspect_file(path) for path in paths]


def summarize(inventories: list[FileInventory]) -> InventorySummary:
    parsed = [inv for inv in inventories if inv.ok]
    return InventorySummary(
        total_files=len(inventories),
        parsed=len(parsed),
        parse_failures=len(inventories) - len(parsed),
        specimens_absent=sum(1 for inv in parsed if inv.specimens_present is False),
        no_narrative_text=sum(1 for inv in parsed if inv.narrative_sections_with_text == 0),
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1

    as_json = "--json" in argv
    positional = [arg for arg in argv if arg != "--json"]
    if len(positional) != 1:
        print("usage: python -m tools.corpus_inventory <directory> [--json]", file=sys.stderr)
        return 1

    directory = Path(positional[0])
    if not directory.is_dir():
        print(f"not a directory: {directory}", file=sys.stderr)
        return 1

    inventories = inspect_directory(directory)
    summary = summarize(inventories)

    if as_json:
        print(
            json_module.dumps(
                {
                    "summary": asdict(summary),
                    "files": [asdict(inv) for inv in inventories],
                },
                indent=2,
            )
        )
        return 0

    for inv in inventories:
        if not inv.ok:
            print(f"FAIL  {inv.path}: {inv.error}")
            continue
        specimen_note = (
            f"{inv.specimen_count} specimen(s)"
            if inv.specimens_present
            else f"specimens ABSENT ({inv.specimens_absent_reason})"
        )
        print(
            f"OK    {inv.path}: case_id={inv.case_id} {specimen_note}, "
            f"narrative {inv.narrative_sections_with_text}/{inv.narrative_sections_total} sections with text"
        )

    print()
    print(
        f"{summary.parsed}/{summary.total_files} parsed "
        f"({summary.parse_failures} failure(s)); "
        f"{summary.specimens_absent} with no structured specimen list; "
        f"{summary.no_narrative_text} with no narrative text at all"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
