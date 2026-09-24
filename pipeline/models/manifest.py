"""The run manifest — what makes "why did this change" answerable.

Written by every run, regardless of which stages actually executed. Later
stages fill in more of it (ruleset version once the mapper runs, prompt
version and model id once the extractor runs); earlier stages leave those
fields ``None`` rather than a guessed placeholder.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StageMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall_time_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    created_at: datetime
    adapter_version: str
    input_hash: str
    stages_completed: list[str] = []
    ruleset_id: str | None = None
    ruleset_content_hash: str | None = None
    prompt_versions: dict[str, str] = {}
    model_id: str | None = None
    stage_metrics: dict[str, StageMetrics] = {}
