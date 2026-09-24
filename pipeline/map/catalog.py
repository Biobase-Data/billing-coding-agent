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

import re


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
#
# "compound nevus" and "malignant melanoma" are handled separately, below,
# because their ICD-10-CM families (D22.-, C43.-) are subdivided by
# anatomic site and, for the limbs, laterality -- coding every nevus to
# the unspecified-site code regardless of the specimen's actual site
# throws away real specificity the report already gives us. Found via
# live testing (a user compared this demo's D22.9 output for a
# right-shoulder nevus against a more specific D22.61 and asked why);
# verified against icd10data.com/AAPC before adding, not guessed.
# ---------------------------------------------------------------------------

DIAGNOSIS_ICD10_TABLE: dict[str, str] = {
    "actinic keratosis": "L57.0",
    "seborrheic keratosis": "L82.1",
    "tubular adenoma": "D12.6",
    "tubulovillous adenoma": "D12.6",
    "hyperplastic polyp": "K63.5",
    # D48.5 has no site subdivision in ICD-10-CM -- it is already maximally
    # specific as a single code, unlike the nevus/melanoma families below.
    "atypical melanocytic proliferation": "D48.5",
    # standard ICD-10-CM code for lichen planus, unspecified (L43.9);
    # WHO/CMS public material, high confidence -- fixture cases 9-10
    # (coverage-linkage gap demo: deliberately not on the covered list).
    "lichen planus": "L43.9",
}

# Diagnoses whose ICD-10 family is subdivided by site/laterality, each
# mapped to the site-suffix -> code table that applies to it.
_SITE_SPECIFIC_DIAGNOSES = {"compound nevus", "malignant melanoma"}

# D22.- Melanocytic nevi. D22.5 (trunk) and D22.9 (unspecified) are single
# codes; the limb categories require a laterality suffix (.60/.61/.62 etc).
_NEVUS_ICD10_BY_SITE_SUFFIX: dict[str, str] = {
    "lip": "D22.0",
    "eyelid": "D22.1",
    "ear": "D22.2",
    "face": "D22.3",
    "scalp_neck": "D22.4",
    "trunk": "D22.5",
    "upper_limb_unspecified": "D22.60",
    "upper_limb_right": "D22.61",
    "upper_limb_left": "D22.62",
    "lower_limb_unspecified": "D22.70",
    "lower_limb_right": "D22.71",
    "lower_limb_left": "D22.72",
    "unspecified": "D22.9",
}

# C43.- Malignant melanoma of skin. Same anatomic breakdown as D22.- above
# (trunk uses C43.59, "other part of trunk" -- C43.51/.52 are anal/breast
# skin specifically and don't apply to our fixture corpus).
_MELANOMA_ICD10_BY_SITE_SUFFIX: dict[str, str] = {
    "lip": "C43.0",
    "eyelid": "C43.1",
    "ear": "C43.2",
    "face": "C43.3",
    "scalp_neck": "C43.4",
    "trunk": "C43.59",
    "upper_limb_unspecified": "C43.60",
    "upper_limb_right": "C43.61",
    "upper_limb_left": "C43.62",
    "lower_limb_unspecified": "C43.70",
    "lower_limb_right": "C43.71",
    "lower_limb_left": "C43.72",
    "unspecified": "C43.9",
}

_LIP_KEYWORDS = ("lip",)
_EYELID_KEYWORDS = ("eyelid",)
_EAR_KEYWORDS = ("ear",)
_FACE_KEYWORDS = ("face", "cheek", "forehead", "nose", "chin")
_SCALP_NECK_KEYWORDS = ("scalp", "neck")
_TRUNK_KEYWORDS = ("trunk", "back", "chest", "abdomen", "flank", "breast", "buttock")
_UPPER_LIMB_KEYWORDS = ("shoulder", "arm", "forearm", "elbow", "wrist", "hand")
_LOWER_LIMB_KEYWORDS = ("leg", "calf", "thigh", "hip", "knee", "ankle", "foot")
_LEFT_KEYWORDS = ("left",)
_RIGHT_KEYWORDS = ("right",)


def _contains_word(text: str, keywords: tuple[str, ...]) -> bool:
    """Whole-word match only -- a plain substring test would match "ear"
    inside "forearm" or "arm" inside "pharmacy". Found by a failing test
    while adding site-specific nevus/melanoma coding."""
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def _site_suffix_for_skin_neoplasm(site: str | None) -> str:
    """Map a free-text specimen site to a D22./C43. site-suffix category.

    Unrecognized or missing sites fall back to "unspecified" rather than
    guessing -- the same posture as an ambiguous multi-site container
    (ASSUMPTIONS.md #1): code the safe, less-specific line, and let the
    specimen-ambiguity or documentation findings (already independently
    checked) tell the coder to confirm it.
    """
    if not site:
        return "unspecified"
    s = site.lower()
    if _contains_word(s, _LIP_KEYWORDS):
        return "lip"
    if _contains_word(s, _EYELID_KEYWORDS):
        return "eyelid"
    if _contains_word(s, _EAR_KEYWORDS):
        return "ear"
    if _contains_word(s, _FACE_KEYWORDS):
        return "face"
    if _contains_word(s, _SCALP_NECK_KEYWORDS):
        return "scalp_neck"
    if _contains_word(s, _TRUNK_KEYWORDS):
        return "trunk"
    if _contains_word(s, _UPPER_LIMB_KEYWORDS):
        if _contains_word(s, _RIGHT_KEYWORDS):
            return "upper_limb_right"
        if _contains_word(s, _LEFT_KEYWORDS):
            return "upper_limb_left"
        return "upper_limb_unspecified"
    if _contains_word(s, _LOWER_LIMB_KEYWORDS):
        if _contains_word(s, _RIGHT_KEYWORDS):
            return "lower_limb_right"
        if _contains_word(s, _LEFT_KEYWORDS):
            return "lower_limb_left"
        return "lower_limb_unspecified"
    return "unspecified"


def diagnosis_icd10(diagnosis_text: str, site: str | None = None) -> str:
    key = diagnosis_text.strip().lower()
    if key in _SITE_SPECIFIC_DIAGNOSES:
        suffix = _site_suffix_for_skin_neoplasm(site)
        table = _NEVUS_ICD10_BY_SITE_SUFFIX if key == "compound nevus" else _MELANOMA_ICD10_BY_SITE_SUFFIX
        return table[suffix]
    if key not in DIAGNOSIS_ICD10_TABLE:
        raise MappingGapError(
            f"no ICD-10 mapping for diagnosis text {diagnosis_text!r} -- add it to "
            "DIAGNOSIS_ICD10_TABLE, or flag this specimen for coder review"
        )
    return DIAGNOSIS_ICD10_TABLE[key]
