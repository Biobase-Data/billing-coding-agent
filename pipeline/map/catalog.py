"""The small, cited lookup tables the mapper runs against.

Every table here is a demo-scale placeholder for a judgment call that
needs a commercial AP coder to sign off (ASSUMPTIONS.md #3). Nothing here
is invented to make a fixture pass: site-to-level correspondence and the
diagnosis-to-ICD10 mappings below reflect widely published AP coding
convention (specimen-type-to-level tables appear in essentially every
public pathology billing guide), never AMA descriptor text, and every
ICD-10-CM code is CMS/WHO public material with no licensing restriction.
Anything not in these tables raises `MappingGapError` rather than
guessing -- see ASSUMPTIONS.md #3 and #2.
"""

from __future__ import annotations


class MappingGapError(ValueError):
    """A fact describes something this catalog has no rule for.

    Raised rather than guessed, per the build spec: "when a stage cannot
    do something correctly, it raises."
    """


# ---------------------------------------------------------------------------
# Surgical pathology specimen levels (CPT 88304-88309, level II-VI).
# Keyed by (procedure_type, site_category); demo covers only the
# specimen types the fixture corpus exercises.
# ---------------------------------------------------------------------------

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
    if not site:
        return None
    s = site.lower()
    if any(k in s for k in _SKIN_KEYWORDS):
        return "skin"
    if any(k in s for k in _GI_KEYWORDS):
        return "gi"
    if any(k in s for k in _PROSTATE_KEYWORDS):
        return "prostate"
    return None


SPECIMEN_LEVEL_TABLE: dict[tuple[str, str], str] = {
    ("biopsy", "skin"): "88305",
    ("polypectomy", "gi"): "88305",
    ("biopsy", "prostate"): "88305",
}


def specimen_level_code(procedure_type: str | None, site_category: str | None) -> str:
    key = (procedure_type, site_category)
    if key not in SPECIMEN_LEVEL_TABLE:
        raise MappingGapError(
            f"no surgical pathology level mapping for procedure_type={procedure_type!r} "
            f"site_category={site_category!r} -- add it to SPECIMEN_LEVEL_TABLE with a "
            "cited source, or flag this specimen for coder review"
        )
    return SPECIMEN_LEVEL_TABLE[key]


# ---------------------------------------------------------------------------
# Stains. HE is included in the specimen-level code and never billed
# separately. IHC unit counting distinguishes the first antibody (88342)
# from each additional one on the same specimen (88341, an add-on code
# that always requires 88342 present -- see validate/checks/add_on.py).
# ---------------------------------------------------------------------------

IHC_FIRST_ANTIBODY_CODE = "88342"
IHC_ADDITIONAL_ANTIBODY_CODE = "88341"
SPECIAL_STAIN_CODE = "88312"  # group I; demo does not attempt group I/II
                               # discrimination -- see ASSUMPTIONS.md #3


def stain_code(kind: str) -> str:
    if kind == "ihc":
        raise MappingGapError("IHC units depend on antibody order -- use map/rules/stains.py")
    if kind == "special":
        return SPECIAL_STAIN_CODE
    if kind == "he":
        raise MappingGapError("H&E is included in the specimen level code, never billed alone")
    raise MappingGapError(f"no stain code mapping for kind={kind!r}")


# ---------------------------------------------------------------------------
# Diagnosis -> ICD-10-CM. Keyed by normalized diagnosis text. A qualified
# ("suspicious for", "cannot exclude") diagnosis is coded to the
# *presenting* finding here, never to the suspected condition -- the
# outpatient/AP-safe default per ASSUMPTIONS.md #2.
# ---------------------------------------------------------------------------

DIAGNOSIS_ICD10_TABLE: dict[str, str] = {
    "compound nevus": "D22.9",
    "actinic keratosis": "L57.0",
    "seborrheic keratosis": "L82.1",
    "tubular adenoma": "D12.6",
    "tubulovillous adenoma": "D12.6",
    "hyperplastic polyp": "K63.5",
    "atypical melanocytic proliferation": "D48.5",
}


def diagnosis_icd10(diagnosis_text: str) -> str:
    key = diagnosis_text.strip().lower()
    if key not in DIAGNOSIS_ICD10_TABLE:
        raise MappingGapError(
            f"no ICD-10 mapping for diagnosis text {diagnosis_text!r} -- add it to "
            "DIAGNOSIS_ICD10_TABLE, or flag this specimen for coder review"
        )
    return DIAGNOSIS_ICD10_TABLE[key]
