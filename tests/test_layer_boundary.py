"""Enforces the one non-negotiable architectural rule: extract/ (the
probabilistic layer) must never import rules/ (the deterministic layer).

If this test fails, the fix is never to add an exception -- it is to
move whatever logic leaked across back to the correct side of the
boundary. See both packages' __init__.py docstrings.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "coding_agent"


def _imported_module_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Prefix with the right number of leading dots is irrelevant
            # here -- coding_agent.extract and coding_agent.rules are
            # siblings, so any relative import reaching rules/ must be
            # expressed as `from .. import rules` or `from ...rules import
            # x`, both of which surface `module="rules"` or
            # `module="rules.X"` when `node.level > 0`. We check the bare
            # module name too, to catch that case.
            names.add(node.module)
    return names


def _package_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def _references_package(module_names: set[str], package: str) -> bool:
    return any(
        name == f"coding_agent.{package}" or name.startswith(f"coding_agent.{package}.") or name == package or name.startswith(f"{package}.")
        for name in module_names
    )


def test_extract_never_imports_rules():
    offenders = []
    for py_file in _package_files("extract"):
        module_names = _imported_module_names(py_file)
        if _references_package(module_names, "rules"):
            offenders.append(py_file)
    assert not offenders, f"extract/ must never import rules/, but found imports in: {offenders}"


def test_rules_never_imports_extract():
    offenders = []
    for py_file in _package_files("rules"):
        module_names = _imported_module_names(py_file)
        if _references_package(module_names, "extract"):
            offenders.append(py_file)
    assert not offenders, f"rules/ must never import extract/, but found imports in: {offenders}"


def test_boundary_test_itself_finds_something_when_violated(tmp_path, monkeypatch):
    """A meta-test: prove the AST scan actually detects a violation,
    so a bug in the scanner itself can't make this whole file vacuous."""
    fake_extract = tmp_path / "coding_agent" / "extract"
    fake_extract.mkdir(parents=True)
    (fake_extract / "bad.py").write_text("from coding_agent.rules import units\n")

    monkeypatch.setattr(sys.modules[__name__], "SRC", tmp_path / "coding_agent")
    offenders = []
    for py_file in _package_files("extract"):
        if _references_package(_imported_module_names(py_file), "rules"):
            offenders.append(py_file)
    assert offenders, "the AST scanner failed to detect a deliberately-introduced violation"
