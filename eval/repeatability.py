"""Measure run-to-run repeatability of specimen extraction on one case.

"Everything is versioned" pins down *what* produced a result; this
module answers the companion question of whether the same versioned
pipeline gives the same answer twice. It is written against the
`ModelClient` protocol, not against any particular implementation, so
the same check runs offline in CI against `eval.harness.ReplayClient`
(where it is a no-op sanity check on the parsing code path) and, when an
API key is available, against the real `AnthropicClient` to measure the
model's actual empirical agreement rate across repeated calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from coding_agent.extract.specimens import ModelClient, extract_specimen_mentions
from coding_agent.normalize.case import Case


@dataclass(frozen=True)
class RepeatabilityResult:
    case_id: str
    run_count: int
    agreement_count: int
    """Number of runs whose (abstained, label-set) outcome matched the
    first run's outcome."""

    @property
    def agreement_rate(self) -> float:
        if self.run_count == 0:
            return 0.0
        return self.agreement_count / self.run_count


def _outcome(case: Case, client: ModelClient, model: str) -> tuple[bool, frozenset[str]]:
    extraction, _metrics = extract_specimen_mentions(case, client=client, model=model)
    if extraction.abstained:
        return True, frozenset()
    return False, frozenset(mention.label for mention in extraction.mentions)


def check_repeatability(
    case: Case,
    client: ModelClient,
    *,
    model: str = "claude-sonnet-5",
    runs: int = 3,
) -> RepeatabilityResult:
    """Run extraction on `case` `runs` times against `client` and report
    how many runs agreed with the first run's outcome.

    Raises no error on disagreement -- disagreement is a metric this
    project tracks (a low agreement rate is a real finding about the
    model or the case), not a hard pass/fail assertion. Callers that want
    a threshold enforce it themselves against `agreement_rate`.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")

    outcomes = [_outcome(case, client, model) for _ in range(runs)]
    baseline = outcomes[0]
    agreement_count = sum(1 for outcome in outcomes if outcome == baseline)
    return RepeatabilityResult(
        case_id=case.case_id, run_count=runs, agreement_count=agreement_count
    )
