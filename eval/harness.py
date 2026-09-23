"""Run the V0 pipeline -- extract, reconcile, recommend, stamp -- over a
corpus of synthetic eval cases and report per-case results.

Each eval case is a self-contained JSON fixture (see eval/cases/*.json):
a canonical Case, a recorded model response, and the expected ground
truth. `ReplayClient` feeds the recorded response into the real
`extract_specimen_mentions` code path, so the harness exercises actual
JSON parsing and span-locating rather than a mocked-out shortcut, with no
live API key or network access required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from coding_agent.audit.stamp import AuditedRecommendation, stamp
from coding_agent.extract.specimens import ModelClient, extract_specimen_mentions
from coding_agent.normalize.case import Case
from coding_agent.recommend.assemble import build_recommendation
from coding_agent.recommend.schema import BaselineLine, Recommendation
from coding_agent.rules.units import RULES_VERSION

CASES_DIR = Path(__file__).with_name("cases")


class ReplayClient:
    """A ModelClient that always returns one recorded response, regardless
    of the prompt it is given. This is what lets the eval corpus run
    offline and deterministically: the recorded text stands in for a
    real model call, but everything downstream of it -- JSON parsing,
    section/quote validation, span-locating -- runs for real."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        return self._response_text, 0, 0


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    case: Case
    model_response_text: str
    expected_labels: frozenset[str] | None
    """The narrative specimen labels this fixture is known to describe.
    `None` means this case is expected to abstain rather than produce
    mentions -- see `CaseResult.actual_labels` for the matching contract."""
    primary_code: str
    baseline: tuple[BaselineLine, ...]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected_labels: frozenset[str] | None
    actual_labels: frozenset[str] | None
    abstained: bool
    recommendation: Recommendation
    audited: AuditedRecommendation


def load_eval_case(path: Path) -> EvalCase:
    raw = json.loads(path.read_text())
    case = Case.model_validate(raw["case"])
    expected_labels = (
        frozenset(raw["expected_labels"]) if raw.get("expected_labels") is not None else None
    )
    baseline = tuple(BaselineLine(**line) for line in raw.get("baseline", []))
    return EvalCase(
        case_id=case.case_id,
        case=case,
        model_response_text=raw.get("model_response_text", ""),
        expected_labels=expected_labels,
        primary_code=raw["primary_code"],
        baseline=baseline,
    )


def load_corpus(cases_dir: Path = CASES_DIR) -> list[EvalCase]:
    return [load_eval_case(path) for path in sorted(cases_dir.glob("*.json"))]


def run_eval_case(eval_case: EvalCase, model: str = "eval-replay") -> CaseResult:
    client: ModelClient = ReplayClient(eval_case.model_response_text)
    extraction, _metrics = extract_specimen_mentions(eval_case.case, client=client, model=model)

    actual_labels = (
        None
        if extraction.abstained
        else frozenset(mention.label for mention in extraction.mentions)
    )

    recommendation = build_recommendation(
        eval_case.case, extraction, eval_case.baseline, eval_case.primary_code
    )
    audited = stamp(
        recommendation,
        extraction_metadata=extraction.metadata,
        rules_version=RULES_VERSION,
        date_of_service=eval_case.case.date_of_service,
    )
    return CaseResult(
        case_id=eval_case.case_id,
        expected_labels=eval_case.expected_labels,
        actual_labels=actual_labels,
        abstained=extraction.abstained,
        recommendation=recommendation,
        audited=audited,
    )


def run_corpus(cases_dir: Path = CASES_DIR) -> list[CaseResult]:
    return [run_eval_case(eval_case) for eval_case in load_corpus(cases_dir)]
