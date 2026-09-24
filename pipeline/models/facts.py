"""Facts: what the extractor emits, and what every code line must trace to.

A fact never carries a code. It carries a claim about the case ("this
antibody was named", "this diagnosis was qualified as suspicious") plus
the exact character span it came from. The mapper reads facts; it never
reads report text directly.

``fact_id`` is not in the illustrative schema in the build spec, but a
CodeLine has to cite facts by id (`CodeLine.fact_ids`), so every fact
needs a stable identifier -- assigned by whatever produces the fact (hand
-written fixtures in Phase 3, the extractor's parser from Phase 4 on).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FactType(str, Enum):
    SPECIMEN = "specimen"      # value: {sites: [str, ...], container_label}
    STAIN = "stain"            # value: {block_id, kind, antibody}
    DIAGNOSIS = "diagnosis"    # value: {text, certainty, qualifier}
    INDICATION = "indication"  # value: {text}  -- reserved; unused while
                                # Requisition.clinical_indication already
                                # captures this without extraction


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Evidence(Frozen):
    document_id: str
    start: int
    end: int
    quoted: str


class Fact(Frozen):
    fact_id: str
    fact_type: FactType
    value: dict
    specimen_id: str | None
    evidence: Evidence
    confidence: Confidence

    @model_validator(mode="after")
    def _value_shape_matches_fact_type(self) -> "Fact":
        required = {
            FactType.SPECIMEN: {"sites"},
            FactType.STAIN: {"kind"},
            FactType.DIAGNOSIS: {"text", "certainty"},
            FactType.INDICATION: {"text"},
        }[self.fact_type]
        missing = required - self.value.keys()
        if missing:
            raise ValueError(f"{self.fact_type} fact missing required value keys {missing}")
        return self
