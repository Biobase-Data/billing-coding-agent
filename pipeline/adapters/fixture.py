"""The fixture adapter: synthetic source files -> canonical Case.

All source-specific knowledge lives here and nowhere else. A case
directory holds a ``source.json`` describing the LIS-shaped procedure
record (specimens, blocks, stains, diagnoses, requisition) plus a
``documents/`` folder of the raw text every document points at. This is
the boundary a later NovoPath adapter replaces without anything
downstream changing: the contract tests in this package are written
against the canonical ``Case`` shape, not against fixture.py itself, so
the same tests run unchanged against that future adapter.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.models.case import (
    Block,
    Case,
    Diagnosis,
    Document,
    DocumentKind,
    PayerRef,
    Requisition,
    SourceMeta,
    Specimen,
    Stain,
)

ADAPTER_VERSION = "1.0.0"


class FixtureLoadError(ValueError):
    """Raised when a fixture case directory does not describe a valid Case."""


def load_case(case_dir: str | Path) -> Case:
    """Read a fixture case directory and return a validated canonical Case.

    Raises FixtureLoadError (or a pydantic ValidationError) rather than
    guessing at any missing or malformed field — a fixture that cannot be
    represented correctly must fail loudly, exactly like a real adapter.
    """
    case_dir = Path(case_dir)
    source_path = case_dir / "source.json"
    if not source_path.exists():
        raise FixtureLoadError(f"no source.json in {case_dir}")

    raw = json.loads(source_path.read_text())

    try:
        documents = [_load_document(case_dir, d) for d in raw["documents"]]
        specimens = [_build_specimen(s) for s in raw["specimens"]]
        requisition = Requisition(
            clinical_indication=raw["requisition"].get("clinical_indication"),
            ordering_provider_npi=raw["requisition"].get("ordering_provider_npi"),
            tests_ordered=raw["requisition"].get("tests_ordered", []),
            payer=PayerRef(**raw["requisition"]["payer"]),
        )
        case = Case(
            case_id=raw["case_id"],
            lab_id=raw["lab_id"],
            date_of_service=raw["date_of_service"],
            date_reported=raw["date_reported"],
            subspecialty=raw["subspecialty"],
            specimens=specimens,
            requisition=requisition,
            documents=documents,
            billing_arrangement=raw["billing_arrangement"],
            source=SourceMeta(
                system="fixture",
                adapter_version=ADAPTER_VERSION,
                ingest_time=datetime.now(timezone.utc),
            ),
        )
    except KeyError as exc:
        raise FixtureLoadError(f"{case_dir}: missing required field {exc}") from exc

    return case


def _load_document(case_dir: Path, spec: dict) -> Document:
    text_path = case_dir / spec["file"]
    if not text_path.exists():
        raise FixtureLoadError(f"document file {text_path} does not exist")
    return Document(
        document_id=spec["document_id"],
        kind=DocumentKind(spec["kind"]),
        text=text_path.read_text(),
        received_at=spec["received_at"],
    )


def _build_specimen(spec: dict) -> Specimen:
    return Specimen(
        specimen_id=spec["specimen_id"],
        site=spec.get("site"),
        sites=spec.get("sites"),
        procedure_type=spec.get("procedure_type"),
        container_label=spec.get("container_label"),
        blocks=[_build_block(b) for b in spec.get("blocks", [])],
        diagnoses=[Diagnosis(**d) for d in spec.get("diagnoses", [])],
    )


def _build_block(spec: dict) -> Block:
    return Block(
        block_id=spec["block_id"],
        stains=[Stain(**s) for s in spec.get("stains", [])],
    )


def list_case_ids(fixtures_root: str | Path) -> list[str]:
    root = Path(fixtures_root)
    return sorted(p.name for p in root.iterdir() if (p / "source.json").exists())
