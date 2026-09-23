"""Tests for eval/: the corpus harness, aggregate metrics, and the
run-to-run repeatability check."""

from __future__ import annotations

import json
from datetime import date

from coding_agent.normalize.case import (
    Absent,
    Case,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
)
from eval.harness import ReplayClient, load_corpus, run_corpus, run_eval_case
from eval.metrics import compute_metrics
from eval.repeatability import check_repeatability


def test_corpus_loads_every_fixture():
    corpus = load_corpus()
    case_ids = {eval_case.case_id for eval_case in corpus}
    assert case_ids == {
        "eval-agreement-001",
        "eval-removal-001",
        "eval-addition-001",
        "eval-abstain-no-narrative-001",
        "eval-abstain-ambiguous-001",
    }


def test_agreement_case_extracts_expected_labels_and_produces_no_lines():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-agreement-001")
    result = run_eval_case(eval_case)
    assert not result.abstained
    assert result.actual_labels == frozenset({"A", "B"})
    assert result.recommendation.lines == ()
    assert result.recommendation.blocked is None


def test_removal_case_flags_the_unmentioned_accessioned_specimen():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-removal-001")
    result = run_eval_case(eval_case)
    assert result.actual_labels == frozenset({"A", "B"})

    from coding_agent.recommend.schema import DiffKind

    removal_ids = {
        line.specimen_id for line in result.recommendation.lines if line.diff_kind is DiffKind.REMOVAL
    }
    assert removal_ids == {"C"}


def test_addition_case_flags_the_unaccessioned_narrative_label():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-addition-001")
    result = run_eval_case(eval_case)
    assert result.actual_labels == frozenset({"A", "D"})

    from coding_agent.recommend.schema import DiffKind

    addition_ids = {
        line.specimen_id for line in result.recommendation.lines if line.diff_kind is DiffKind.ADDITION
    }
    assert addition_ids == {"D"}


def test_no_narrative_case_abstains_without_a_model_call():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-abstain-no-narrative-001")
    result = run_eval_case(eval_case)
    assert result.abstained
    assert result.actual_labels is None
    assert result.recommendation.blocked is not None


def test_ambiguous_narrative_case_abstains_via_model_declared_abstention():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-abstain-ambiguous-001")
    result = run_eval_case(eval_case)
    assert result.abstained
    assert result.actual_labels is None


def test_audited_recommendation_carries_a_version_stamp():
    corpus = load_corpus()
    eval_case = next(c for c in corpus if c.case_id == "eval-agreement-001")
    result = run_eval_case(eval_case)
    assert result.audited.version_stamp.code_set_year == 2026
    assert result.audited.version_stamp.rules_version == "units_v1"


def test_metrics_over_the_full_corpus_report_both_axes():
    results = run_corpus()
    metrics = compute_metrics(results)

    assert metrics.total_cases == 5
    assert metrics.abstained_cases == 2
    assert metrics.abstention_rate == 2 / 5

    # the three non-abstained cases all extracted their expected label
    # sets exactly, so precision/recall/exact-match should all be perfect
    assert metrics.label_precision == 1.0
    assert metrics.label_recall == 1.0
    assert metrics.label_f1 == 1.0
    assert metrics.exact_match_cases == 3


def test_metrics_handles_an_empty_result_set():
    metrics = compute_metrics([])
    assert metrics.total_cases == 0
    assert metrics.abstention_rate == 0.0
    assert metrics.label_precision is None
    assert metrics.label_recall is None
    assert metrics.label_f1 is None


def _one_specimen_case_with_text(text: str) -> Case:
    return Case(
        case_id="repeat-case",
        accession_number="S26-2001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.HL7V2,
        source_document_id="S26-2001",
        specimens=Maybe.missing(Absent.NOT_SUPPLIED),
        narrative=(NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of(text)),),
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )


def test_repeatability_is_perfect_against_a_replay_client():
    case = _one_specimen_case_with_text("A. Skin, left forearm: compound nevus.")
    response = json.dumps(
        {"abstain": False, "mentions": [{"label": "A", "section": "diagnosis", "quoted": "A. Skin, left forearm"}]}
    )
    client = ReplayClient(response)

    result = check_repeatability(case, client, runs=5)
    assert result.run_count == 5
    assert result.agreement_count == 5
    assert result.agreement_rate == 1.0


def test_repeatability_detects_disagreement():
    case = _one_specimen_case_with_text("A. Skin, left forearm: compound nevus.")

    class AlternatingClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
            self.calls += 1
            if self.calls % 2 == 1:
                return (
                    json.dumps(
                        {
                            "abstain": False,
                            "mentions": [
                                {"label": "A", "section": "diagnosis", "quoted": "A. Skin, left forearm"}
                            ],
                        }
                    ),
                    10,
                    5,
                )
            return (
                json.dumps(
                    {
                        "abstain": True,
                        "reason": "low_model_confidence",
                        "detail": "second-guessing itself",
                        "mentions": [],
                    }
                ),
                10,
                5,
            )

    result = check_repeatability(case, AlternatingClient(), runs=4)
    assert result.run_count == 4
    assert result.agreement_count == 2
    assert result.agreement_rate == 0.5


def test_repeatability_rejects_zero_runs():
    import pytest

    case = _one_specimen_case_with_text("A. Skin, left forearm: compound nevus.")
    with pytest.raises(ValueError):
        check_repeatability(case, ReplayClient(""), runs=0)
