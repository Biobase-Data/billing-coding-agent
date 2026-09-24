"""Full coverage for rules/cpt_level.py -- deterministic, so it must be."""

from __future__ import annotations

import pytest

from coding_agent.rules.cpt_level import (
    RULES_VERSION,
    CptLevelUnmappedError,
    categorize_site,
    specimen_level_code,
)


def test_categorize_skin_sites():
    assert categorize_site("Skin of left forearm") == "skin"
    assert categorize_site("Skin, right shoulder") == "skin"
    assert categorize_site("cheek") == "skin"


def test_categorize_gi_sites():
    assert categorize_site("Sigmoid colon polyp") == "gi"
    assert categorize_site("Ascending colon") == "gi"


def test_categorize_prostate_sites():
    assert categorize_site("Prostate, needle core") == "prostate"


def test_categorize_unrecognized_site_returns_none():
    assert categorize_site("lymph node") is None


def test_categorize_absent_site_returns_none():
    assert categorize_site(None) is None
    assert categorize_site("") is None


def test_whole_word_matching_does_not_false_positive_on_substrings():
    # "forearm" is correctly recognized as skin (it's an explicit
    # keyword), and a site with no skin/gi/prostate keyword as a whole
    # word -- "ear canal" contains none of them, including no accidental
    # substring hit -- stays unrecognized. Regression coverage for the
    # same class of bug this module's docstring cites as already found
    # once in pipeline/map/catalog.py's plain-substring version.
    assert categorize_site("Skin of left forearm") == "skin"
    assert categorize_site("ear canal") is None


def test_specimen_level_code_known_combinations():
    assert specimen_level_code("biopsy", "skin") == "88305"
    assert specimen_level_code("polypectomy", "gi") == "88305"
    assert specimen_level_code("biopsy", "prostate") == "88305"


def test_specimen_level_code_is_case_and_whitespace_insensitive():
    assert specimen_level_code("  Biopsy  ", "skin") == "88305"
    assert specimen_level_code("BIOPSY", "skin") == "88305"


def test_specimen_level_code_unmapped_procedure_type_raises():
    with pytest.raises(CptLevelUnmappedError):
        specimen_level_code("excision", "skin")


def test_specimen_level_code_unmapped_site_category_raises():
    with pytest.raises(CptLevelUnmappedError):
        specimen_level_code("biopsy", "gi")


def test_specimen_level_code_none_site_category_raises():
    with pytest.raises(CptLevelUnmappedError):
        specimen_level_code("biopsy", None)


def test_rules_version_constant():
    assert RULES_VERSION == "cpt_level_v1"
