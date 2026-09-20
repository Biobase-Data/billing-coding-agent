"""Diff two runs of the same case -- the amended-report re-run case.

When a lab issues an amended report, the fix in the coder interview was
an email asking someone to re-finalize; a system that re-runs cleanly on
the amendment and shows what changed addresses that gap directly. A
run's case_id is stable across an amendment (same accession); only the
report content, the facts extracted from it, and therefore the code set
and findings change -- diffing two run directories under the same
case_id shows exactly that, and nothing else, since the manifest also
says whether the *rule version* changed underneath the case (it should
not, here, because date_of_service is unchanged) or only the extraction
did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _line_key(line: dict) -> tuple:
    return (line["code"], line["code_system"], line["specimen_id"])


def _finding_key(finding: dict) -> tuple:
    return (finding["rule_id"], finding["line_id"])


@dataclass(frozen=True)
class LineDiff:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[tuple[dict, dict]] = field(default_factory=list)  # (before, after)


@dataclass(frozen=True)
class FindingDiff:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RunDiff:
    case_id: str
    run_a: str
    run_b: str
    lines: LineDiff
    findings: FindingDiff
    manifest_changes: dict[str, tuple[object, object]]  # field -> (before, after)


def _load(run_dir: Path, name: str) -> dict | list:
    return json.loads((run_dir / name).read_text())


def diff_runs(run_a_dir: Path, run_b_dir: Path) -> RunDiff:
    codes_a = _load(run_a_dir, "codes.json")
    codes_b = _load(run_b_dir, "codes.json")
    findings_a = _load(run_a_dir, "findings.json")
    findings_b = _load(run_b_dir, "findings.json")
    manifest_a = _load(run_a_dir, "manifest.json")
    manifest_b = _load(run_b_dir, "manifest.json")

    if codes_a["case_id"] != codes_b["case_id"]:
        raise ValueError(
            f"refusing to diff runs from different cases: {codes_a['case_id']!r} vs {codes_b['case_id']!r}"
        )

    by_key_a = {_line_key(l): l for l in codes_a["lines"]}
    by_key_b = {_line_key(l): l for l in codes_b["lines"]}

    added = [by_key_b[k] for k in by_key_b if k not in by_key_a]
    removed = [by_key_a[k] for k in by_key_a if k not in by_key_b]
    changed = [
        (by_key_a[k], by_key_b[k])
        for k in by_key_a.keys() & by_key_b.keys()
        if (by_key_a[k]["units"], sorted(by_key_a[k]["modifiers"]))
        != (by_key_b[k]["units"], sorted(by_key_b[k]["modifiers"]))
    ]

    findings_by_key_a = {_finding_key(f): f for f in findings_a}
    findings_by_key_b = {_finding_key(f): f for f in findings_b}
    findings_added = [findings_by_key_b[k] for k in findings_by_key_b if k not in findings_by_key_a]
    findings_removed = [findings_by_key_a[k] for k in findings_by_key_a if k not in findings_by_key_b]

    manifest_changes = {}
    for field_name in ("ruleset_id", "ruleset_content_hash", "adapter_version", "model_id", "input_hash"):
        if manifest_a.get(field_name) != manifest_b.get(field_name):
            manifest_changes[field_name] = (manifest_a.get(field_name), manifest_b.get(field_name))

    return RunDiff(
        case_id=codes_a["case_id"],
        run_a=manifest_a["run_id"],
        run_b=manifest_b["run_id"],
        lines=LineDiff(added=added, removed=removed, changed=changed),
        findings=FindingDiff(added=findings_added, removed=findings_removed),
        manifest_changes=manifest_changes,
    )


def format_diff(diff: RunDiff) -> str:
    lines = [f"Case {diff.case_id}: {diff.run_a} -> {diff.run_b}", ""]

    if diff.manifest_changes:
        lines.append("Manifest changes:")
        for field_name, (before, after) in diff.manifest_changes.items():
            lines.append(f"  {field_name}: {before!r} -> {after!r}")
    else:
        lines.append("Manifest changes: none (same rule version, same adapter)")
    lines.append("")

    def fmt_line(l: dict) -> str:
        mods = f" [{','.join(l['modifiers'])}]" if l["modifiers"] else ""
        return f"{l['code']} ({l['code_system']}) x{l['units']}{mods} -- specimen {l['specimen_id']}"

    lines.append(f"Lines added ({len(diff.lines.added)}):")
    lines += [f"  + {fmt_line(l)}" for l in diff.lines.added] or ["  none"]
    lines.append(f"Lines removed ({len(diff.lines.removed)}):")
    lines += [f"  - {fmt_line(l)}" for l in diff.lines.removed] or ["  none"]
    lines.append(f"Lines changed ({len(diff.lines.changed)}):")
    lines += [f"  ~ {fmt_line(a)}  ->  {fmt_line(b)}" for a, b in diff.lines.changed] or ["  none"]
    lines.append("")

    lines.append(f"Findings added ({len(diff.findings.added)}):")
    lines += [f"  + {f['severity']} {f['rule_id']}: {f['message']}" for f in diff.findings.added] or ["  none"]
    lines.append(f"Findings removed ({len(diff.findings.removed)}):")
    lines += [f"  - {f['severity']} {f['rule_id']}: {f['message']}" for f in diff.findings.removed] or ["  none"]

    return "\n".join(lines) + "\n"
