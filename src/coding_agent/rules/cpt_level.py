"""Deterministic CPT surgical-pathology level assignment (88302-88309),
keyed by specimen procedure type and site category.

Pure and deterministic: two plain strings in, one bare CPT code out (or
a clear raise). No model call. The table below is a demo-scale
placeholder covering only the procedure-type/site combinations this
project's own fixtures exercise -- ported from the earlier `pipeline/`
demo's `map/catalog.py`, which cites its provenance: this is standard,
widely published AP-coding convention (specimen-type-to-level tables
appear in essentially every public pathology billing guide), never AMA
descriptor text, and every code here is a bare CPT *number* (fine to
commit) with no descriptor string attached -- see ASSUMPTIONS.md and the
top-level README's legal constraints. A combination not in the table
raises `CptLevelUnmappedError` rather than guessing a level; add the
combination with a cited source, or leave it for a coder to level by
hand.

Takes plain strings for procedure_type and site, not extract/ types --
this keeps rules/ and extract/ independent of each other, the same
import boundary `rules/units.py` and `tests/test_layer_boundary.py`
already enforce.
"""

from __future__ import annotations

import re

RULES_VERSION = "cpt_level_v1"


class CptLevelUnmappedError(ValueError):
    """This procedure-type/site combination has no CPT level mapping in
    the table below. Raised rather than guessed -- see this module's
    docstring."""


_SKIN_KEYWORDS = (
    "skin", "cheek", "forearm", "forehead", "scalp", "back", "face", "neck",
    "arm", "leg", "chest", "abdomen", "trunk",
)
_GI_KEYWORDS = (
    "colon", "rectum", "sigmoid", "cecum", "ascending", "transverse",
    "descending", "duodenum", "stomach", "esophagus", "ileum",
)
_PROSTATE_KEYWORDS = ("prostate",)


def categorize_site(site: str | None) -> str | None:
    """Bucket a free-text site into the coarse category
    `SPECIMEN_LEVEL_TABLE` is keyed on. Returns None for an absent or
    unrecognized site -- the caller must then raise via
    `specimen_level_code`, never guess a category.

    Whole-word matching, not plain substring matching (unlike this
    keyword list's origin in `pipeline/map/catalog.py`): that codebase's
    own later addition of a site-suffix table for nevus/melanoma coding
    found a real bug from plain substring matching ("ear" inside
    "forearm"), fixed there with the same whole-word approach used here
    from the start.
    """
    if not site:
        return None
    s = site.lower()
    if any(re.search(rf"\b{re.escape(k)}\b", s) for k in _SKIN_KEYWORDS):
        return "skin"
    if any(re.search(rf"\b{re.escape(k)}\b", s) for k in _GI_KEYWORDS):
        return "gi"
    if any(re.search(rf"\b{re.escape(k)}\b", s) for k in _PROSTATE_KEYWORDS):
        return "prostate"
    return None


SPECIMEN_LEVEL_TABLE: dict[tuple[str, str], str] = {
    ("biopsy", "skin"): "88305",
    ("polypectomy", "gi"): "88305",
    ("biopsy", "prostate"): "88305",
}


def specimen_level_code(procedure_type: str, site_category: str | None) -> str:
    """Look up the bare CPT level code for one specimen.

    `procedure_type` is matched case-insensitively and stripped of
    surrounding whitespace (it comes from a model's free-text report,
    not a controlled vocabulary -- see extract/schema.py's
    `ProcedureTypeMention`). Raises `CptLevelUnmappedError` for any
    combination not in `SPECIMEN_LEVEL_TABLE`, including a `None`
    `site_category` (an unrecognized or absent site).
    """
    key = (procedure_type.strip().lower(), site_category)
    if key not in SPECIMEN_LEVEL_TABLE:
        raise CptLevelUnmappedError(
            f"no CPT level mapping for procedure_type={procedure_type!r} "
            f"site_category={site_category!r} -- add it to SPECIMEN_LEVEL_TABLE with a "
            "cited source, or leave this specimen for a coder to level by hand"
        )
    return SPECIMEN_LEVEL_TABLE[key]
