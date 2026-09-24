"""Call Claude to extract facts from a case's documents.

One extraction task per prompt (specimen enumeration, stain and antibody
identification, diagnosis with certainty) -- independently testable,
independently versioned; a regression in one never contaminates the
others. Temperature 0. The model id and every prompt's version are
returned alongside the facts so the caller (the CLI) can record them in
the run manifest -- "what does this cost per case" and "why did this
change" both need this data to exist from the first run, not added later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipeline.extract.parser import parse_facts
from pipeline.models.case import Case
from pipeline.models.facts import Fact, FactType

PROMPTS_DIR = Path(__file__).with_name("prompts")
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096

# (prompt filename, fact id prefix, version) -- bump the version string
# whenever the prompt text changes; the old file stays for history.
_PROMPT_SPECS: dict[FactType, tuple[str, str, str]] = {
    FactType.SPECIMEN: ("specimen_v1.txt", "spec", "v1"),
    FactType.STAIN: ("stain_v1.txt", "stain", "v1"),
    FactType.DIAGNOSIS: ("diagnosis_v1.txt", "dx", "v1"),
}


@dataclass(frozen=True)
class ExtractionMetrics:
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int


class ModelClient(Protocol):
    """The one method this module needs from an Anthropic SDK client --
    typed as a Protocol so tests can pass a stub instead of a live client
    without importing the real SDK."""

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        """Return (response_text, input_tokens, output_tokens)."""
        ...


class AnthropicClient:
    """Thin adapter over the real `anthropic` SDK, built lazily so this
    module imports fine even where the `anthropic` package or an API key
    isn't available (this build sandbox has neither)."""

    def __init__(self) -> None:
        import anthropic  # local import: optional dependency at import time

        self._client = anthropic.Anthropic()

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        # `temperature` is passed via extra_body rather than as a typed
        # kwarg: it is a genuine Messages API parameter, but not every
        # anthropic SDK build exposes it as a named argument, and
        # extra_body merges into the request body on all of them.
        response = self._client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"temperature": 0},
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = response.usage
        return text, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)


def render_documents(case: Case) -> str:
    parts = [
        f"=== document: {doc.document_id} (kind={doc.kind.value}) ===\n{doc.text}"
        for doc in case.documents
    ]
    return "\n\n".join(parts)


def extract_facts(
    case: Case,
    client: ModelClient | None = None,
    model: str = DEFAULT_MODEL,
) -> tuple[list[Fact], dict[str, ExtractionMetrics], dict[str, str]]:
    """Run all three extraction prompts against one case.

    Returns (facts, metrics_by_stage, prompt_versions). Never emits a
    code, never mentions billing to the model -- see the prompt files
    themselves. Raises ExtractionRejectedError (propagated from the
    parser) if any single prompt's output fails span verification; the
    caller decides whether to retry, not this function.
    """
    if client is None:
        client = AnthropicClient()

    documents_block = render_documents(case)
    all_facts: list[Fact] = []
    metrics_by_stage: dict[str, ExtractionMetrics] = {}
    prompt_versions: dict[str, str] = {}

    for fact_type, (filename, id_prefix, version) in _PROMPT_SPECS.items():
        template = (PROMPTS_DIR / filename).read_text()
        prompt = f"{template}\n\n{documents_block}"

        t0 = time.monotonic()
        raw_text, input_tokens, output_tokens = client.create_message(model=model, prompt=prompt)
        wall_time = time.monotonic() - t0

        facts = parse_facts(raw_text, case, fact_type, id_prefix)
        all_facts.extend(facts)
        metrics_by_stage[fact_type.value] = ExtractionMetrics(
            wall_time_seconds=wall_time, input_tokens=input_tokens, output_tokens=output_tokens
        )
        prompt_versions[fact_type.value] = version

    return all_facts, metrics_by_stage, prompt_versions
