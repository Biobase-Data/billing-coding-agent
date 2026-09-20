"""Parse and verify a model's raw JSON fact output.

The model is asked for the quoted evidence text but never for character
offsets -- LLMs are unreliable at raw character arithmetic, and asking
for it buys nothing: what actually needs verifying is whether the quoted
text is real, not whether the model can count. So the parser locates each
quote in the cited document itself (`pipeline.extract.spans.locate`,
first occurrence) and rejects the *whole* extraction if any single fact's
quote cannot be found verbatim, or if any fact cites a document that
doesn't exist on the case. This is the backbone of the evidence guarantee
described in the build spec: a model that hallucinates evidence fails
loudly rather than producing a recommendation nobody can trace, and one
bad fact does not get to quietly poison a batch alongside good ones.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from pipeline.extract.spans import SpanNotFoundError, locate
from pipeline.models.case import Case
from pipeline.models.facts import Evidence, Fact, FactType


class ExtractionRejectedError(ValueError):
    """The whole extraction batch is rejected -- never a partial result."""


class _RawExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specimen_id: str | None = None
    value: dict
    document_id: str
    quoted: str
    confidence: str


def parse_facts(raw_json_text: str, case: Case, fact_type: FactType, id_prefix: str) -> list[Fact]:
    """Turn one prompt's raw model output into verified Facts.

    Raises ExtractionRejectedError -- never returns a partial list -- if
    the output isn't a JSON array, if any element doesn't match the
    expected raw shape, if any fact cites an unknown document, or if any
    fact's quoted text isn't found verbatim in that document.
    """
    try:
        raw_list = json.loads(raw_json_text)
    except json.JSONDecodeError as exc:
        raise ExtractionRejectedError(f"model output was not valid JSON: {exc}") from exc
    if not isinstance(raw_list, list):
        raise ExtractionRejectedError("model output must be a JSON array")

    facts: list[Fact] = []
    for i, item in enumerate(raw_list):
        try:
            raw = _RawExtractedFact(**item)
        except ValidationError as exc:
            raise ExtractionRejectedError(f"fact {i} did not match the expected shape: {exc}") from exc

        try:
            document_text = case.document(raw.document_id).text
        except KeyError as exc:
            raise ExtractionRejectedError(f"fact {i} cites unknown document {raw.document_id!r}") from exc

        try:
            start, end = locate(document_text, raw.quoted)
        except SpanNotFoundError as exc:
            raise ExtractionRejectedError(
                f"fact {i} ({fact_type.value}): quoted text not found verbatim -- {exc}"
            ) from exc

        try:
            fact = Fact(
                fact_id=f"{id_prefix}-{i + 1}",
                fact_type=fact_type,
                value=raw.value,
                specimen_id=raw.specimen_id,
                evidence=Evidence(document_id=raw.document_id, start=start, end=end, quoted=raw.quoted),
                confidence=raw.confidence,
            )
        except ValidationError as exc:
            raise ExtractionRejectedError(f"fact {i} ({fact_type.value}) failed validation: {exc}") from exc
        facts.append(fact)
    return facts
