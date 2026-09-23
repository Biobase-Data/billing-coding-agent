"""Stamp a Recommendation with the versions that produced it.

Nothing here is inferred at read time: the pipeline version is a
constant bumped by hand when this codebase's recommend/rules assembly
logic changes; the model and prompt versions come from the extraction
that fed the recommendation; the rules version comes from rules/units.py
itself; the code-set year comes from the case's date of service.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict

from coding_agent.extract.schema import ExtractionMetadata
from coding_agent.recommend.schema import Recommendation

PIPELINE_VERSION = "coding_agent_v0"


class VersionStamp(BaseModel):
    model_config = ConfigDict(frozen=True)

    pipeline_version: str
    model_version: str
    prompt_version: str
    rules_version: str
    code_set_year: int


class AuditedRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommendation: Recommendation
    version_stamp: VersionStamp
    produced_at: datetime


def stamp(
    recommendation: Recommendation,
    *,
    extraction_metadata: ExtractionMetadata,
    rules_version: str,
    date_of_service: date,
    produced_at: datetime | None = None,
) -> AuditedRecommendation:
    version_stamp = VersionStamp(
        pipeline_version=PIPELINE_VERSION,
        model_version=extraction_metadata.model_version,
        prompt_version=extraction_metadata.prompt_version,
        rules_version=rules_version,
        code_set_year=date_of_service.year,
    )
    return AuditedRecommendation(
        recommendation=recommendation,
        version_stamp=version_stamp,
        produced_at=produced_at or datetime.now(timezone.utc),
    )
