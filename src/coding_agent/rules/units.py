"""V0 core: reconcile the accessioning record's specimen list against
the narrative's specimen labels.

Pure and deterministic: two sets in, one comparison out. No model call,
no table lookup (V0 has no NCCI/MUE tables to consult -- see the
top-level README's explicit V0 scope). Every other rules/ module that
gets added later must keep this same shape: a plain function over plain
data, fully covered by tests, with 100% run-to-run repeatability.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

RULES_VERSION = "units_v1"


class ReconciliationStatus(str, Enum):
    AGREED = "agreed"
    """The accessioned specimen ids and the narrative-described labels
    are exactly the same set."""

    DISAGREED = "disagreed"
    """The two sets differ in at least one direction. See
    `missing_from_narrative` / `missing_from_accessioning` for which."""

    UNDETERMINABLE = "undeterminable"
    """The accessioning record's specimen list itself is absent (see
    `Absent` on `Case.specimens`) -- there is nothing to reconcile
    against. This is an integration blocker to surface, not a finding
    about the narrative."""


class UnitReconciliation(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ReconciliationStatus
    accessioned_ids: frozenset[str]
    narrative_labels: frozenset[str]

    missing_from_narrative: frozenset[str]
    """Accessioned specimen ids the narrative never described. Each one
    is a candidate over-billing finding: a unit may currently be billed
    for a specimen the report gives no textual support for."""

    missing_from_accessioning: frozenset[str]
    """Narrative-described labels with no matching accessioned specimen
    id. Each one is a candidate under-billing finding, or a labeling
    mismatch between the LIS and the report -- both worth a coder's
    look."""

    rules_version: str = RULES_VERSION


def reconcile(
    accessioned_ids: frozenset[str] | None, narrative_labels: frozenset[str]
) -> UnitReconciliation:
    """Compare the accessioning record's specimen ids against the
    narrative's specimen labels.

    `accessioned_ids=None` means the accessioning record could not
    supply a structured specimen list at all (`Case.specimens` was
    `Maybe.missing`, not an empty tuple) -- the caller must not pass an
    empty frozenset to represent that; the two are different states with
    different handling.
    """
    if accessioned_ids is None:
        return UnitReconciliation(
            status=ReconciliationStatus.UNDETERMINABLE,
            accessioned_ids=frozenset(),
            narrative_labels=narrative_labels,
            missing_from_narrative=frozenset(),
            missing_from_accessioning=frozenset(),
        )

    missing_from_narrative = accessioned_ids - narrative_labels
    missing_from_accessioning = narrative_labels - accessioned_ids
    status = (
        ReconciliationStatus.AGREED
        if not missing_from_narrative and not missing_from_accessioning
        else ReconciliationStatus.DISAGREED
    )
    return UnitReconciliation(
        status=status,
        accessioned_ids=accessioned_ids,
        narrative_labels=narrative_labels,
        missing_from_narrative=missing_from_narrative,
        missing_from_accessioning=missing_from_accessioning,
    )
