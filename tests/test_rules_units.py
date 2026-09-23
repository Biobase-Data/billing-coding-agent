"""Full coverage for rules/units.py -- deterministic, so it must be."""

from __future__ import annotations

from coding_agent.rules.units import ReconciliationStatus, reconcile


def test_agreement():
    result = reconcile(frozenset({"A", "B"}), frozenset({"A", "B"}))
    assert result.status is ReconciliationStatus.AGREED
    assert result.missing_from_narrative == frozenset()
    assert result.missing_from_accessioning == frozenset()


def test_narrative_undercounts_flags_missing_from_narrative():
    result = reconcile(frozenset({"A", "B"}), frozenset({"A"}))
    assert result.status is ReconciliationStatus.DISAGREED
    assert result.missing_from_narrative == frozenset({"B"})
    assert result.missing_from_accessioning == frozenset()


def test_narrative_overcounts_flags_missing_from_accessioning():
    result = reconcile(frozenset({"A"}), frozenset({"A", "B"}))
    assert result.status is ReconciliationStatus.DISAGREED
    assert result.missing_from_narrative == frozenset()
    assert result.missing_from_accessioning == frozenset({"B"})


def test_disjoint_sets_flag_both_directions():
    result = reconcile(frozenset({"A"}), frozenset({"B"}))
    assert result.status is ReconciliationStatus.DISAGREED
    assert result.missing_from_narrative == frozenset({"A"})
    assert result.missing_from_accessioning == frozenset({"B"})


def test_empty_narrative_against_accessioned_specimens_is_a_full_disagreement():
    result = reconcile(frozenset({"A", "B"}), frozenset())
    assert result.status is ReconciliationStatus.DISAGREED
    assert result.missing_from_narrative == frozenset({"A", "B"})


def test_accessioning_specimen_list_absent_is_undeterminable_not_disagreed():
    result = reconcile(None, frozenset({"A", "B"}))
    assert result.status is ReconciliationStatus.UNDETERMINABLE
    assert result.missing_from_narrative == frozenset()
    assert result.missing_from_accessioning == frozenset()
    assert result.narrative_labels == frozenset({"A", "B"})


def test_zero_specimens_both_sides_agrees():
    result = reconcile(frozenset(), frozenset())
    assert result.status is ReconciliationStatus.AGREED


def test_rules_version_is_stamped():
    result = reconcile(frozenset({"A"}), frozenset({"A"}))
    assert result.rules_version == "units_v1"


def test_reconciliation_is_frozen():
    import pytest
    from pydantic import ValidationError

    result = reconcile(frozenset({"A"}), frozenset({"A"}))
    with pytest.raises(ValidationError):
        result.status = ReconciliationStatus.DISAGREED  # type: ignore[misc]
