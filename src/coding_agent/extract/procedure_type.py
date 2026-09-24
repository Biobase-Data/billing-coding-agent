"""Extract each specimen's procedure type (biopsy, excision, polypectomy,
...) from the narrative, with evidence, or abstain.

The second extraction task in V0 (see specimens.py's updated module
docstring), added to support CPT surgical-pathology leveling
(rules/cpt_level.py, recommend/cpt_level.py): a specimen's billing level
depends on both its site (already a structured field on
`Specimen.site`, sourced from the LIS -- no need to re-extract it) and
its procedure type, which only the narrative states.

Shares its model-client machinery (`ModelClient`, `AnthropicClient`,
`GroqClient`, `GrokClient`, the OpenAI-compatible HTTP helper) with
specimens.py rather than duplicating it -- everything below this line is
specific to this task's own schema and prompt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from coding_agent.extract.schema import (
    Abstention,
    AbstentionReason,
    ExtractionMetadata,
    ProcedureTypeExtraction,
    ProcedureTypeMention,
)
from coding_agent.extract.spans import SpanNotFoundError, locate
from coding_agent.extract.specimens import (
    DEFAULT_MODEL,
    AnthropicClient,
    ModelClient,
    render_narrative,
)
from coding_agent.normalize.case import Case, NarrativeKind

PROMPTS_DIR = Path(__file__).with_name("prompts")
PROMPT_FILE = "procedure_type_v1.txt"
PROMPT_VERSION = "procedure_type_v1"


class ProcedureTypeExtractionRejectedError(ValueError):
    """The whole extraction is rejected -- never a partial result. Same
    posture as SpecimenExtractionRejectedError: malformed JSON, a quote
    that isn't found verbatim, or a section that doesn't exist on this
    case."""


@dataclass(frozen=True)
class ExtractionMetrics:
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int


class _RawMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    procedure_type: str
    section: str
    quoted: str


class _RawResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: bool
    mentions: list[_RawMention] = []
    reason: str | None = None
    detail: str | None = None


_REASON_BY_VALUE = {reason.value: reason for reason in AbstentionReason}


def _parse_response(
    raw_text: str, case: Case, metadata: ExtractionMetadata
) -> ProcedureTypeExtraction:
    try:
        raw_obj = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProcedureTypeExtractionRejectedError(f"model output was not valid JSON: {exc}") from exc

    try:
        response = _RawResponse(**raw_obj)
    except ValidationError as exc:
        raise ProcedureTypeExtractionRejectedError(
            f"model output did not match the expected shape: {exc}"
        ) from exc

    if response.abstain:
        if response.reason not in _REASON_BY_VALUE:
            raise ProcedureTypeExtractionRejectedError(
                f"model abstained with an unrecognized reason: {response.reason!r}"
            )
        return ProcedureTypeExtraction(
            abstention=Abstention(
                reason=_REASON_BY_VALUE[response.reason],
                detail=response.detail or "",
            ),
            metadata=metadata,
        )

    # Group by label like specimens.py does, but also track each label's
    # procedure_type so a contradictory response (the same label given
    # two different procedure types, without abstaining) is rejected
    # outright rather than silently resolved by picking one.
    procedure_type_by_label: dict[str, str] = {}
    spans_by_label: dict[str, list] = {}
    order: list[str] = []
    for i, raw_mention in enumerate(response.mentions):
        try:
            section = NarrativeKind(raw_mention.section)
        except ValueError as exc:
            raise ProcedureTypeExtractionRejectedError(
                f"mention {i} cites an unrecognized section {raw_mention.section!r}"
            ) from exc

        try:
            span = locate(case, section=section, quoted=raw_mention.quoted)
        except SpanNotFoundError as exc:
            raise ProcedureTypeExtractionRejectedError(
                f"mention {i} ({raw_mention.label!r}): {exc}"
            ) from exc

        label = raw_mention.label
        if label in procedure_type_by_label:
            if procedure_type_by_label[label] != raw_mention.procedure_type:
                raise ProcedureTypeExtractionRejectedError(
                    f"specimen {label!r} was given two different procedure types "
                    f"({procedure_type_by_label[label]!r} and {raw_mention.procedure_type!r}) "
                    "without abstaining -- this is a contradictory response, not a fact"
                )
        else:
            procedure_type_by_label[label] = raw_mention.procedure_type
            spans_by_label[label] = []
            order.append(label)
        spans_by_label[label].append(span)

    mentions = tuple(
        ProcedureTypeMention(
            label=label,
            procedure_type=procedure_type_by_label[label],
            evidence=tuple(spans_by_label[label]),
        )
        for label in order
    )
    return ProcedureTypeExtraction(mentions=mentions, metadata=metadata)


def extract_procedure_types(
    case: Case,
    client: ModelClient | None = None,
    model: str = DEFAULT_MODEL,
) -> tuple[ProcedureTypeExtraction, ExtractionMetrics | None]:
    """Run procedure-type extraction on one case.

    Returns (extraction, metrics). `metrics` is None when extraction
    abstained without calling the model (no searchable narrative text
    was present).

    Raises ProcedureTypeExtractionRejectedError if the model's output
    cannot be trusted. Never emits a mention with no evidence span;
    never mentions billing, CPT, or ICD-10 to the model -- see the
    prompt file.
    """
    metadata = ExtractionMetadata(model_version=model, prompt_version=PROMPT_VERSION)

    narrative_block = render_narrative(case)
    if narrative_block is None:
        return (
            ProcedureTypeExtraction(
                abstention=Abstention(
                    reason=AbstentionReason.SECTION_ABSENT,
                    detail="no narrative section on this case has any text to search",
                ),
                metadata=metadata,
            ),
            None,
        )

    if client is None:
        client = AnthropicClient()

    template = (PROMPTS_DIR / PROMPT_FILE).read_text()
    prompt = f"{template}\n\n{narrative_block}"

    t0 = time.monotonic()
    raw_text, input_tokens, output_tokens = client.create_message(model=model, prompt=prompt)
    wall_time = time.monotonic() - t0

    extraction = _parse_response(raw_text, case, metadata)
    metrics = ExtractionMetrics(
        wall_time_seconds=wall_time, input_tokens=input_tokens, output_tokens=output_tokens
    )
    return extraction, metrics
