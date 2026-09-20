"""Small builders for synthetic Case/Fact objects used by unit tests.

Kept separate from any one test module so mapper and validator tests
share exactly the same construction logic for their boundary cases.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pipeline.models.case import (
    BillingArrangement,
    Block,
    Case,
    Document,
    DocumentKind,
    PayerRef,
    Requisition,
    SourceMeta,
    Specimen,
    Stain,
)
from pipeline.models.facts import Confidence, Evidence, Fact, FactType

DEFAULT_DOC_TEXT = "Synthetic report text for unit tests. Nevus present."


def make_document(document_id: str = "doc-report", text: str = DEFAULT_DOC_TEXT) -> Document:
    return Document(
        document_id=document_id,
        kind=DocumentKind.REPORT,
        text=text,
        received_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def make_specimen(
    specimen_id: str = "A",
    sites: list[str] | None = None,
    procedure_type: str = "biopsy",
    stains: list[Stain] | None = None,
) -> Specimen:
    return Specimen(
        specimen_id=specimen_id,
        sites=sites or ["skin, left forearm"],
        procedure_type=procedure_type,
        container_label=f"{specimen_id}: synthetic",
        blocks=[Block(block_id=f"{specimen_id}1", stains=stains or [])],
    )


def make_case(
    specimens: list[Specimen] | None = None,
    documents: list[Document] | None = None,
    billing_arrangement: BillingArrangement = BillingArrangement.GLOBAL,
    payer_class: str = "commercial",
    mac_jurisdiction: str = "DEMO-MAC-J5",
    date_of_service: date = date(2026, 8, 1),
) -> Case:
    return Case(
        case_id="TEST-0001",
        lab_id="LAB-TEST",
        date_of_service=date_of_service,
        date_reported=datetime(2026, 8, 2, tzinfo=timezone.utc),
        subspecialty="surgical",
        specimens=specimens or [make_specimen()],
        requisition=Requisition(
            clinical_indication="Test indication",
            ordering_provider_npi="1234567890",
            tests_ordered=["Test"],
            payer=PayerRef(plan="Test Plan", mac_jurisdiction=mac_jurisdiction, payer_class=payer_class),
        ),
        documents=documents or [make_document()],
        billing_arrangement=billing_arrangement,
        source=SourceMeta(system="test", adapter_version="0.0.0", ingest_time=datetime.now(timezone.utc)),
    )


def make_fact(
    fact_id: str,
    fact_type: FactType,
    value: dict,
    specimen_id: str | None = "A",
    document_id: str = "doc-report",
    quoted: str = "Nevus present.",
    confidence: Confidence = Confidence.HIGH,
) -> Fact:
    document_text = DEFAULT_DOC_TEXT
    start = document_text.index(quoted)
    return Fact(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        specimen_id=specimen_id,
        evidence=Evidence(document_id=document_id, start=start, end=start + len(quoted), quoted=quoted),
        confidence=confidence,
    )
