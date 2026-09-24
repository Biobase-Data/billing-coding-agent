from pipeline.eval.scorer import score_findings, score_lines
from pipeline.models.codes import CodeLine, CodeSet
from pipeline.models.findings import Finding, Severity


def _line(code, code_system, units, modifiers, specimen_id, line_id="L"):
    return CodeLine(
        line_id=line_id, code=code, code_system=code_system, units=units,
        modifiers=modifiers, specimen_id=specimen_id, fact_ids=["f1"],
        confidence="high", rule_id="test",
    )


def test_correct_line():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[_line("88305", "CPT", 1, [], "A")])
    golden = [{"code": "88305", "code_system": "CPT", "units": 1, "modifiers": [], "specimen_id": "A"}]
    result = score_lines(actual, golden)
    assert len(result.correct) == 1
    assert not result.missed and not result.spurious and not result.wrong_units_or_modifiers


def test_missed_line():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[])
    golden = [{"code": "88305", "code_system": "CPT", "units": 1, "modifiers": [], "specimen_id": "A"}]
    result = score_lines(actual, golden)
    assert len(result.missed) == 1
    assert not result.correct and not result.spurious


def test_spurious_line():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[_line("88305", "CPT", 1, [], "A")])
    result = score_lines(actual, [])
    assert len(result.spurious) == 1
    assert not result.correct and not result.missed


def test_wrong_units():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[_line("88341", "CPT", 2, [], "A")])
    golden = [{"code": "88341", "code_system": "CPT", "units": 3, "modifiers": [], "specimen_id": "A"}]
    result = score_lines(actual, golden)
    assert len(result.wrong_units_or_modifiers) == 1
    assert not result.correct and not result.missed and not result.spurious


def test_wrong_modifiers():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[_line("88305", "CPT", 1, ["26"], "A")])
    golden = [{"code": "88305", "code_system": "CPT", "units": 1, "modifiers": [], "specimen_id": "A"}]
    result = score_lines(actual, golden)
    assert len(result.wrong_units_or_modifiers) == 1


def test_modifier_order_does_not_matter():
    actual = CodeSet(case_id="C", ruleset_id="r", lines=[_line("88305", "CPT", 1, ["59", "26"], "A")])
    golden = [{"code": "88305", "code_system": "CPT", "units": 1, "modifiers": ["26", "59"], "specimen_id": "A"}]
    result = score_lines(actual, golden)
    assert len(result.correct) == 1


def test_findings_caught_missed_false_alarm():
    actual = [
        Finding(severity=Severity.REVIEW, line_id=None, rule_id="specimen:ambiguous_site_count", message="m"),
        Finding(severity=Severity.BLOCKER, line_id=None, rule_id="mue:88312", message="m"),
    ]
    golden = [{"rule_id": "specimen:ambiguous_site_count", "severity": "review"}, {"rule_id": "coverage:X", "severity": "blocker"}]
    result = score_findings(actual, golden)
    assert result.caught == ["specimen:ambiguous_site_count"]
    assert result.missed == ["coverage:X"]
    assert result.false_alarm == ["mue:88312"]
