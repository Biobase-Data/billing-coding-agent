"""Repo-wide CI guards that don't belong to any one stage.

CPT is AMA copyrighted material Biobase does not have a licence for (see
ASSUMPTIONS.md). The one place a descriptor mapping is allowed to exist is
``rulesets/*/cpt_descriptors.json``, and every value there must stay a
marked placeholder. This guard does not blocklist specific real descriptor
phrases -- doing that would mean typing real CPT descriptor text into this
very file, which is exactly what it exists to prevent. Instead it
structurally flags any *other* file that defines a CPT/HCPCS-code-shaped
JSON mapping to non-trivial text, which is what a pasted-in descriptor
file would look like.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DESCRIPTOR_FILES = {REPO_ROOT / "rulesets" / "2026q3" / "cpt_descriptors.json"}
CODE_KEY_RE = re.compile(r"^[A-Z]?\d{4,5}$")
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "runs", "__pycache__"}


def _iter_json_files():
    for path in REPO_ROOT.rglob("*.json"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def test_cpt_descriptor_file_entries_are_all_placeholders():
    for path in ALLOWED_DESCRIPTOR_FILES:
        data = json.loads(path.read_text())
        for code, text in data.items():
            if code == "_notice":
                continue
            assert isinstance(text, str) and text.startswith("PLACEHOLDER"), (
                f"{path}:{code} must be a marked placeholder, never real descriptor text"
            )


def test_no_other_file_defines_a_code_to_descriptor_mapping():
    for path in _iter_json_files():
        if path in ALLOWED_DESCRIPTOR_FILES:
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        code_like_keys = [k for k in data if isinstance(k, str) and CODE_KEY_RE.match(k)]
        if len(code_like_keys) < 3:
            continue  # a handful of incidental numeric-looking keys is fine
        for key in code_like_keys:
            value = data[key]
            if isinstance(value, str) and len(value) > 15:
                raise AssertionError(
                    f"{path} looks like a CPT/HCPCS descriptor mapping outside the "
                    "one allowed placeholder file -- if this is real AMA descriptor "
                    "text, remove it; if it's meant to be a real licensed drop-in, "
                    "it belongs at rulesets/*/cpt_descriptors.json"
                )
