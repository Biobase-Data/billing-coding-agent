"""Tests for audit/: version stamping and the append-only coder action log."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from coding_agent.audit.log import ActionLog, CoderAction, record_action
from coding_agent.audit.stamp import PIPELINE_VERSION, stamp
from coding_agent.extract.schema import ExtractionMetadata
from coding_agent.recommend.schema import Recommendation
from coding_agent.rules.units import RULES_VERSION


def test_stamp_carries_every_required_version_field():
    recommendation = Recommendation(case_id="case-1", baseline=(), lines=())
    audited = stamp(
        recommendation,
        extraction_metadata=ExtractionMetadata(model_version="claude-sonnet-5", prompt_version="specimens_v1"),
        rules_version=RULES_VERSION,
        date_of_service=date(2026, 3, 15),
    )
    assert audited.version_stamp.pipeline_version == PIPELINE_VERSION
    assert audited.version_stamp.model_version == "claude-sonnet-5"
    assert audited.version_stamp.prompt_version == "specimens_v1"
    assert audited.version_stamp.rules_version == RULES_VERSION
    assert audited.version_stamp.code_set_year == 2026
    assert audited.recommendation is recommendation


def test_action_log_round_trips_and_is_append_only(tmp_path):
    log = ActionLog(tmp_path / "actions.jsonl")

    record_action(log, case_id="case-1", line_index=0, action=CoderAction.ACCEPTED)
    record_action(log, case_id="case-1", line_index=1, action=CoderAction.REMOVED, reason="not a real specimen")

    records = log.read_all()
    assert len(records) == 2
    assert records[0].action is CoderAction.ACCEPTED
    assert records[0].reason is None
    assert records[1].action is CoderAction.REMOVED
    assert records[1].reason == "not a real specimen"

    # append-only: a fresh ActionLog over the same path sees both prior records
    log2 = ActionLog(tmp_path / "actions.jsonl")
    record_action(log2, case_id="case-1", line_index=2, action=CoderAction.EDITED, reason="wrong specimen id")
    assert len(log2.read_all()) == 3


def test_removed_and_edited_require_a_reason():
    from datetime import datetime, timezone

    from coding_agent.audit.log import CoderActionRecord

    with pytest.raises(ValidationError):
        CoderActionRecord(
            case_id="case-1",
            line_index=0,
            action=CoderAction.REMOVED,
            reason=None,
            recorded_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValidationError):
        CoderActionRecord(
            case_id="case-1",
            line_index=0,
            action=CoderAction.EDITED,
            reason="   ",
            recorded_at=datetime.now(timezone.utc),
        )


def test_accepted_does_not_require_a_reason():
    from datetime import datetime, timezone

    from coding_agent.audit.log import CoderActionRecord

    record = CoderActionRecord(
        case_id="case-1",
        line_index=0,
        action=CoderAction.ACCEPTED,
        recorded_at=datetime.now(timezone.utc),
    )
    assert record.reason is None


def test_empty_log_reads_as_empty_list(tmp_path):
    log = ActionLog(tmp_path / "does_not_exist_yet.jsonl")
    assert log.read_all() == []
