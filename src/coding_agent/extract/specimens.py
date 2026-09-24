"""V0 core: extract every specimen label the narrative text describes,
with evidence, or abstain.

This is deliberately the only extraction task in V0. It answers a
counting question with verifiable ground truth (rules/units.py
reconciles the result against Case.specimens, the accessioning record)
rather than a judgment call -- see the top-level README, "V0 scope:
specimen unit capture".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from coding_agent.extract.schema import (
    Abstention,
    AbstentionReason,
    ExtractionMetadata,
    SpecimenExtraction,
    SpecimenMention,
)
from coding_agent.extract.spans import SpanNotFoundError, locate
from coding_agent.normalize.case import Case, NarrativeKind

PROMPTS_DIR = Path(__file__).with_name("prompts")
PROMPT_FILE = "specimens_v1.txt"
PROMPT_VERSION = "specimens_v1"
DEFAULT_MODEL = "claude-sonnet-5"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROK_DEFAULT_MODEL = "grok-4"
MAX_TOKENS = 4096

_SEARCHABLE_SECTIONS = (
    NarrativeKind.GROSS,
    NarrativeKind.MICROSCOPIC,
    NarrativeKind.DIAGNOSIS,
    NarrativeKind.CLINICAL_HISTORY,
)


class SpecimenExtractionRejectedError(ValueError):
    """The whole extraction is rejected -- never a partial result. Raised
    when the model's output cannot be trusted: malformed JSON, a quote
    that isn't found verbatim, or a section that doesn't exist on this
    case."""


@dataclass(frozen=True)
class ExtractionMetrics:
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int


class ModelClient(Protocol):
    """The one method a model backend needs to supply -- typed as a
    Protocol, deliberately provider-agnostic, so tests can pass a stub
    without importing any real SDK, and this module is never coupled to
    a single vendor. `AnthropicClient` and `GroqClient` below are two
    interchangeable implementations; `extract_specimen_mentions` doesn't
    care which one it's given."""

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        """Return (response_text, input_tokens, output_tokens)."""
        ...


class AnthropicClient:
    """Thin adapter over the real `anthropic` SDK, built lazily so this
    module imports fine where the `anthropic` package or an API key
    isn't available."""

    def __init__(self) -> None:
        import anthropic  # local import: optional dependency at import time

        self._client = anthropic.Anthropic()

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        # No `temperature` override: determinism here comes from the schema
        # (abstain rather than guess, every claim evidence-verified), not
        # from sampling settings -- and newer models reject `temperature`
        # as a deprecated parameter outright.
        response = self._client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = response.usage
        return text, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)


class ModelRequestError(RuntimeError):
    """Raised when a live model backend's HTTP call fails -- carries the
    decoded error body (when available) rather than letting a bare
    HTTPError surface, since that body is where an invalid-key or
    rate-limit reason lives."""


GroqRequestError = ModelRequestError
"""Kept as a name-compatible alias: earlier code imported this name
specifically for Groq. It is the same exception type every
OpenAI-compatible backend below raises -- there is nothing
Groq-specific about the class itself."""


def _call_openai_compatible_chat(
    *, endpoint: str, api_key: str, model: str, prompt: str
) -> tuple[str, int, int]:
    """Shared HTTP call for any OpenAI-compatible chat completions
    endpoint (Groq, xAI's Grok, and others that copy the same shape).
    Stdlib-only (`urllib`) rather than pulling in the `openai` SDK just
    for one request/response shape this module already knows how to
    build and parse directly.
    """
    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelRequestError(f"{endpoint} returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelRequestError(f"could not reach {endpoint}: {exc.reason}") from exc

    text = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class GroqClient:
    """Adapter over Groq's free-tier hosting of open-source models
    (https://console.groq.com), via its OpenAI-compatible chat
    completions endpoint."""

    _ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self) -> None:
        import os

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self._api_key = api_key

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        return _call_openai_compatible_chat(
            endpoint=self._ENDPOINT, api_key=self._api_key, model=model, prompt=prompt
        )


class GrokClient:
    """Adapter over xAI's Grok API (https://api.x.ai), via its
    OpenAI-compatible chat completions endpoint. Unlike Groq's free
    tier, this is a paid/metered API -- see ASSUMPTIONS.md for why it's
    a separate backend from Groq rather than the same one, despite the
    near-identical names.
    """

    _ENDPOINT = "https://api.x.ai/v1/chat/completions"

    def __init__(self) -> None:
        import os

        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY is not set")
        self._api_key = api_key

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        return _call_openai_compatible_chat(
            endpoint=self._ENDPOINT, api_key=self._api_key, model=model, prompt=prompt
        )


class _RawMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    section: str
    quoted: str


class _RawResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: bool
    mentions: list[_RawMention] = []
    reason: str | None = None
    detail: str | None = None


_REASON_BY_VALUE = {reason.value: reason for reason in AbstentionReason}


def render_narrative(case: Case) -> str | None:
    """Join every present, non-empty searchable section into one prompt
    block, headed by section name. Returns None if no searchable section
    has any text -- the caller should abstain without calling the model
    in that case; there is nothing to read."""
    parts = []
    for kind in _SEARCHABLE_SECTIONS:
        section = case.section(kind)
        if section is not None and section.text.is_present:
            parts.append(f"=== {kind.value} ===\n{section.text.value}")
    if not parts:
        return None
    return "\n\n".join(parts)


def _parse_response(raw_text: str, case: Case, metadata: ExtractionMetadata) -> SpecimenExtraction:
    try:
        raw_obj = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SpecimenExtractionRejectedError(f"model output was not valid JSON: {exc}") from exc

    try:
        response = _RawResponse(**raw_obj)
    except ValidationError as exc:
        raise SpecimenExtractionRejectedError(f"model output did not match the expected shape: {exc}") from exc

    if response.abstain:
        if response.reason not in _REASON_BY_VALUE:
            raise SpecimenExtractionRejectedError(
                f"model abstained with an unrecognized reason: {response.reason!r}"
            )
        return SpecimenExtraction(
            abstention=Abstention(
                reason=_REASON_BY_VALUE[response.reason],
                detail=response.detail or "",
            ),
            metadata=metadata,
        )

    spans_by_label: dict[str, list] = {}
    order: list[str] = []
    for i, raw_mention in enumerate(response.mentions):
        try:
            section = NarrativeKind(raw_mention.section)
        except ValueError as exc:
            raise SpecimenExtractionRejectedError(
                f"mention {i} cites an unrecognized section {raw_mention.section!r}"
            ) from exc

        try:
            span = locate(case, section=section, quoted=raw_mention.quoted)
        except SpanNotFoundError as exc:
            raise SpecimenExtractionRejectedError(f"mention {i} ({raw_mention.label!r}): {exc}") from exc

        if raw_mention.label not in spans_by_label:
            spans_by_label[raw_mention.label] = []
            order.append(raw_mention.label)
        spans_by_label[raw_mention.label].append(span)

    mentions = tuple(
        SpecimenMention(label=label, evidence=tuple(spans_by_label[label])) for label in order
    )
    return SpecimenExtraction(mentions=mentions, metadata=metadata)


def extract_specimen_mentions(
    case: Case,
    client: ModelClient | None = None,
    model: str = DEFAULT_MODEL,
) -> tuple[SpecimenExtraction, ExtractionMetrics | None]:
    """Run V0 specimen-mention extraction on one case.

    Returns (extraction, metrics). `metrics` is None when extraction
    abstained without calling the model (no searchable narrative text
    was present) -- there is no API call to report on.

    Raises SpecimenExtractionRejectedError if the model's output cannot
    be trusted. Never emits a mention with no evidence span; never
    mentions billing, CPT, or ICD-10 to the model -- see the prompt file.
    """
    metadata = ExtractionMetadata(model_version=model, prompt_version=PROMPT_VERSION)

    narrative_block = render_narrative(case)
    if narrative_block is None:
        return (
            SpecimenExtraction(
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
