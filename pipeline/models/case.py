"""The canonical case model.

Every adapter (fixture.py today, a NovoPath adapter later) produces this
shape. Nothing downstream — extractor, mapper, validator, UI — knows what
source system a case came from. The specimen is the unit of everything:
AP billing is per separately accessioned specimen, so blocks, stains and
diagnoses hang off Specimen rather than off the report as a whole.

All models are frozen (immutable) so a case, once built by an adapter,
cannot be silently mutated by a later stage — any transformation produces
a new object.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Subspecialty(str, Enum):
    SURGICAL = "surgical"
    CYTO = "cyto"
    HEME = "heme"
    DERM = "derm"


class BillingArrangement(str, Enum):
    GLOBAL = "global"
    PROFESSIONAL = "professional"
    TECHNICAL = "technical"


class StainKind(str, Enum):
    HE = "he"
    SPECIAL = "special"
    IHC = "ihc"
    ISH = "ish"
    MOLECULAR = "molecular"


class Certainty(str, Enum):
    DEFINITIVE = "definitive"
    QUALIFIED = "qualified"
    NEGATIVE = "negative"


class DocumentKind(str, Enum):
    REPORT = "report"
    REQUISITION = "requisition"
    STAIN_LOG = "stain_log"
    ORDER = "order"


class Stain(Frozen):
    stain_id: str
    kind: StainKind
    antibody: str | None = None
    ordered: bool
    resulted: bool
    performed_at: datetime | None = None

    @field_validator("antibody")
    @classmethod
    def _antibody_only_meaningful_for_ihc(cls, v: str | None, info) -> str | None:
        # ISH panels can also carry a probe/antibody-like name; only IHC is
        # required. Free text is preserved verbatim, never inferred.
        return v


class Block(Frozen):
    block_id: str
    stains: list[Stain] = []


class Diagnosis(Frozen):
    text: str
    certainty: Certainty
    qualifier: str | None = None

    @field_validator("qualifier")
    @classmethod
    def _qualifier_required_when_qualified(cls, v: str | None, info) -> str | None:
        certainty = info.data.get("certainty")
        if certainty == Certainty.QUALIFIED and not v:
            raise ValueError("qualified certainty requires a verbatim qualifier")
        return v


class Specimen(Frozen):
    """One separately accessioned container — the AP billing unit.

    ``sites`` is the verbatim, ordered list of every site the requisition
    or gross description lists inside this one container. A container
    with a single site has ``sites == [site]``. A container with more than
    one site (the silent unit-loss case) has ``site is None`` and
    ``len(sites) > 1`` — nothing downstream is allowed to collapse that
    list back into a single guessed value. See ASSUMPTIONS.md #1: the
    mapper counts *containers*, never sites, and always raises a review
    finding when ``len(sites) > 1``.
    """

    specimen_id: str
    site: str | None = None
    sites: list[str]
    procedure_type: str | None = None
    container_label: str | None = None
    blocks: list[Block] = []
    diagnoses: list[Diagnosis] = []

    @model_validator(mode="before")
    @classmethod
    def _derive_sites(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        sites = data.get("sites")
        site = data.get("site")
        if sites is None:
            if site is None:
                raise ValueError("specimen needs either 'site' or 'sites'")
            data["sites"] = [site]
        elif len(sites) == 1 and site is None:
            data["site"] = sites[0]
        elif len(sites) > 1 and site is not None:
            raise ValueError("site must be None when sites has more than one entry")
        return data

    @field_validator("sites")
    @classmethod
    def _sites_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("sites must not be empty")
        return v


class PayerRef(Frozen):
    plan: str
    mac_jurisdiction: str
    payer_class: str  # e.g. "medicare" | "commercial" | "medicaid"


class Requisition(Frozen):
    clinical_indication: str | None = None
    ordering_provider_npi: str | None = None
    tests_ordered: list[str] = []
    payer: PayerRef


class Document(Frozen):
    document_id: str
    kind: DocumentKind
    text: str
    received_at: datetime


class SourceMeta(Frozen):
    system: str  # e.g. "fixture" | "novopath"
    adapter_version: str
    ingest_time: datetime


class Case(Frozen):
    case_id: str
    lab_id: str
    date_of_service: date
    date_reported: datetime
    subspecialty: Subspecialty
    specimens: list[Specimen]
    requisition: Requisition
    documents: list[Document]
    billing_arrangement: BillingArrangement
    source: SourceMeta

    @field_validator("specimens")
    @classmethod
    def _at_least_one_specimen(cls, v: list[Specimen]) -> list[Specimen]:
        if not v:
            raise ValueError("a case must have at least one specimen")
        return v

    @field_validator("documents")
    @classmethod
    def _at_least_one_document(cls, v: list[Document]) -> list[Document]:
        if not v:
            raise ValueError("a case must have at least one document")
        return v

    def document(self, document_id: str) -> Document:
        for d in self.documents:
            if d.document_id == document_id:
                return d
        raise KeyError(f"no document {document_id!r} on case {self.case_id!r}")

    def specimen(self, specimen_id: str) -> Specimen:
        for s in self.specimens:
            if s.specimen_id == specimen_id:
                return s
        raise KeyError(f"no specimen {specimen_id!r} on case {self.case_id!r}")
