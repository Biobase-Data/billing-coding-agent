# Fixture case index

Every case here has a matching `fixtures/golden/case_XX/golden.json`
checked by `pipeline/eval/test_golden.py`. All golden files carry
`"unreviewed": true` until an AP coder signs off (see ASSUMPTIONS.md).

| case | exercises |
|------|-----------|
| case_01 | baseline single-specimen skin biopsy, definitive covered diagnosis, no findings |
| case_02 | six-specimen GI polypectomy panel, mixed adenoma/hyperplastic/negative diagnoses |
| case_03 | one container with 3 sites -> `specimen:ambiguous_site_count` review finding |
| case_04 | 4-antibody IHC melanoma panel, all antibodies named -> 88342 (first) + 88341 x3 (additional); also trips `coverage:DEMO-POLICY-88305` since malignant melanoma (C43.9) isn't on the demo policy's covered list |
| case_05 | 2-antibody IHC panel, one antibody named, one unnamed -> `documentation:ihc_missing_antibody` review finding (plus the same coverage blocker as case_04) |
| case_06 | a special stain (PAS) resulted in the lab log but never mentioned in the report -> `reconciliation:resulted_not_billed` review finding, no stain fact/line for it |
| case_07 | a special stain (GMS) ordered but never resulted -> `reconciliation:ordered_not_resulted` review finding, no stain fact/line for it |
| case_08 | qualified diagnosis ("cannot exclude melanoma in situ") -> `diagnosis:qualified_certainty` review finding, coded to the presenting finding (D48.5), plus `coverage:DEMO-POLICY-88305` blocker since D48.5 isn't covered |
| case_09 | requisition with no clinical indication + definitive, uncovered diagnosis (lichen planus, L43.9) -> `documentation:no_clinical_indication` informational finding plus `coverage:DEMO-POLICY-88305` blocker |
| case_10 | same lichen planus scenario as case_09 but with a clinical indication present -> only the coverage blocker fires, no informational finding |
| case_11 | prostate saturation biopsy, 10 separately accessioned specimens, Medicare payer -> `apply_substitutions` collapses ten 88305 lines into one G0416 (HCPCS) line, no findings |
| case_12 | 10 distinct special stains on one specimen -> 88312 billed at 10 units, exceeding the ruleset's MUE of 9 -> `mue:88312` blocker finding |
| case_13 | addendum run billing a follow-up IHC antibody (CDX2) with `sequence: "additional"` and no first-antibody fact in this run -> 88341 with no 88342 -> `add_on:88341` blocker finding |
| case_14 | professional-only billing arrangement -> CPT line carries modifier `26`, ICD10 line carries no modifier, no findings |
