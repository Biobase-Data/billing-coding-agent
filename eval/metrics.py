"""Aggregate metrics over eval/harness.py's per-case results.

Two axes matter and must not be conflated (see
src/coding_agent/extract/schema.py's module docstring): label-extraction
accuracy against synthetic ground truth, and abstention rate, which this
project tracks as a first-class metric and does not try to drive to
zero. A corpus where abstention rate is falling only because the model
is guessing on ambiguous cases is a regression, not an improvement --
`CorpusMetrics` reports both so that tradeoff is visible, not hidden
inside a single blended accuracy number.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.harness import CaseResult


@dataclass(frozen=True)
class CorpusMetrics:
    total_cases: int
    abstained_cases: int
    label_precision: float | None
    """Over non-abstained cases with a known expected label set: of the
    labels actually extracted, the fraction that were expected. `None`
    when there are no non-abstained cases to score."""
    label_recall: float | None
    """Of the expected labels, the fraction actually extracted. `None`
    under the same condition as `label_precision`."""
    exact_match_cases: int
    """Non-abstained cases whose extracted label set exactly equals the
    expected label set -- the strict pass/fail count a coder-facing
    dashboard would lead with."""

    @property
    def abstention_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.abstained_cases / self.total_cases

    @property
    def label_f1(self) -> float | None:
        if self.label_precision is None or self.label_recall is None:
            return None
        if self.label_precision + self.label_recall == 0:
            return 0.0
        return 2 * self.label_precision * self.label_recall / (self.label_precision + self.label_recall)


def compute_metrics(results: list[CaseResult]) -> CorpusMetrics:
    total_cases = len(results)
    abstained_cases = sum(1 for r in results if r.abstained)

    scorable = [
        r for r in results if not r.abstained and r.expected_labels is not None
    ]

    true_positives = 0
    predicted_count = 0
    expected_count = 0
    exact_match_cases = 0

    for result in scorable:
        actual = result.actual_labels or frozenset()
        expected = result.expected_labels or frozenset()
        true_positives += len(actual & expected)
        predicted_count += len(actual)
        expected_count += len(expected)
        if actual == expected:
            exact_match_cases += 1

    label_precision = true_positives / predicted_count if predicted_count else None
    label_recall = true_positives / expected_count if expected_count else None

    return CorpusMetrics(
        total_cases=total_cases,
        abstained_cases=abstained_cases,
        label_precision=label_precision,
        label_recall=label_recall,
        exact_match_cases=exact_match_cases,
    )
