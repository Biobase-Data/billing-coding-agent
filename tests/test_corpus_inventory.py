"""Tests for tools/corpus_inventory.py: the normalize/-layer diagnostic
that surfaces integration blockers (a missing structured specimen list,
missing narrative text) before extraction or rules ever runs."""

from __future__ import annotations

from pathlib import Path

from tools.corpus_inventory import inspect_directory, inspect_file, main, summarize

FIXTURES = Path(__file__).with_name("fixtures")


def test_inspect_hl7_case_with_specimens():
    inv = inspect_file(FIXTURES / "hl7v2" / "case_two_specimens.hl7")
    assert inv.ok
    assert inv.specimens_present is True
    assert inv.specimen_count == 2


def test_inspect_hl7_case_missing_specimens_is_flagged_absent():
    inv = inspect_file(FIXTURES / "hl7v2" / "case_no_specimens.hl7")
    assert inv.ok
    assert inv.specimens_present is False
    assert inv.specimens_absent_reason == "not_supplied"


def test_inspect_fhir_case_with_specimens():
    inv = inspect_file(FIXTURES / "fhir" / "case_two_specimens.json")
    assert inv.ok
    assert inv.specimens_present is True
    assert inv.specimen_count == 2


def test_inspect_fhir_case_missing_specimens_is_flagged_absent():
    inv = inspect_file(FIXTURES / "fhir" / "case_no_specimens.json")
    assert inv.ok
    assert inv.specimens_present is False


def test_inspect_unsupported_extension_is_a_failure(tmp_path):
    bogus = tmp_path / "note.txt"
    bogus.write_text("not a supported format")
    inv = inspect_file(bogus)
    assert not inv.ok
    assert "unsupported" in inv.error


def test_inspect_malformed_hl7_is_a_failure(tmp_path):
    bad = tmp_path / "broken.hl7"
    bad.write_text("MSH|^~\\&|LIS\nOBX|1|TX|DX||no OBR at all||||||F")
    inv = inspect_file(bad)
    assert not inv.ok
    assert inv.error


def test_inspect_directory_covers_both_formats_and_ignores_others(tmp_path):
    (tmp_path / "ignored.txt").write_text("skip me")
    (tmp_path / "a.hl7").write_text((FIXTURES / "hl7v2" / "case_two_specimens.hl7").read_text())
    (tmp_path / "b.json").write_text((FIXTURES / "fhir" / "case_no_specimens.json").read_text())

    inventories = inspect_directory(tmp_path)
    assert len(inventories) == 2
    assert {Path(inv.path).name for inv in inventories} == {"a.hl7", "b.json"}


def test_summarize_counts_absent_specimens_and_parse_failures():
    inventories = inspect_directory(FIXTURES)
    summary = summarize(inventories)

    assert summary.total_files == 4
    assert summary.parsed == 4
    assert summary.parse_failures == 0
    assert summary.specimens_absent == 2  # the two "no_specimens" fixtures


def test_main_prints_a_report_and_returns_zero(capsys):
    exit_code = main([str(FIXTURES)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "parsed" in captured.out


def test_main_json_output_is_valid_json(capsys):
    import json

    exit_code = main([str(FIXTURES), "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["summary"]["total_files"] == 4


def test_main_rejects_a_non_directory(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    exit_code = main([str(missing)])
    assert exit_code == 1
