# Fixture case index

Every case here has a matching `fixtures/golden/case_XX/golden.json`
checked by `pipeline/eval/test_golden.py`. All golden files carry
`"unreviewed": true` until an AP coder signs off (see ASSUMPTIONS.md).

| case | exercises |
|------|-----------|
| case_01 | baseline single-specimen skin biopsy, definitive covered diagnosis, no findings |
| case_02 | six-specimen GI polypectomy panel, mixed adenoma/hyperplastic/negative diagnoses |
| case_03 | one container with 3 sites -> `specimen:ambiguous_site_count` review finding |
| case_04 | 4-antibody IHC melanoma panel, all antibodies named -> 88342 (first) + 88341 x3 (additional); C43.9 is on the covered-diagnosis list (a malignant finding is at least as clear a medical-necessity justification as a benign one), so no coverage finding fires |
| case_05 | 2-antibody IHC panel, one antibody named, one unnamed -> `documentation:ihc_missing_antibody` review finding, no coverage finding (same C43.9 diagnosis as case_04) |
| case_06 | a special stain (PAS) resulted in the lab log but never mentioned in the report -> `reconciliation:resulted_not_billed` review finding, no stain fact/line for it |
| case_07 | a special stain (GMS) ordered but never resulted -> `reconciliation:ordered_not_resulted` review finding, no stain fact/line for it |
| case_08 | qualified diagnosis ("cannot exclude melanoma in situ") -> `diagnosis:qualified_certainty` review finding, coded to the presenting finding (D48.5), plus `coverage:DEMO-POLICY-88305` blocker since D48.5 isn't covered |
| case_09 | requisition with no clinical indication + definitive, uncovered diagnosis (lichen planus, L43.9) -> `documentation:no_clinical_indication` informational finding plus `coverage:DEMO-POLICY-88305` blocker |
| case_10 | same lichen planus scenario as case_09 but with a clinical indication present -> only the coverage blocker fires, no informational finding |
| case_11 | prostate saturation biopsy, 10 separately accessioned specimens, Medicare payer -> `apply_substitutions` collapses ten 88305 lines into one G0416 (HCPCS) line, no findings |
| case_12 | 10 distinct special stains on one specimen -> 88312 billed at 10 units, exceeding the ruleset's MUE of 9 -> `mue:88312` blocker finding |
| case_13 | addendum run billing a follow-up IHC antibody (CDX2) with `sequence: "additional"` and no first-antibody fact in this run -> 88341 with no 88342 -> `add_on:88341` blocker finding |
| case_14 | professional-only billing arrangement -> CPT line carries modifier `26`, ICD10 line carries no modifier, no findings |
| case_15_initial / case_15_amended | same case_id (`S26-0042900`), same date_of_service -- an amended report changes the diagnosis from compound nevus (D22.9) to a qualified atypical melanocytic proliferation (D48.5). `pipeline/cli/diff.py` diffs the two runs: the level code (88305) and rule version are unchanged; the diagnosis line and two findings (`coverage:DEMO-POLICY-88305`, `diagnosis:qualified_certainty`) are new. See `pipeline/eval/test_diff.py`. |
