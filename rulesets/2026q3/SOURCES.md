# Ruleset 2026q3 — sources

Pulled: 2026-09-20, by Claude Code, via web search (this build sandbox's
network egress proxy blocks `cms.gov` directly — see the caveat on each
row below that relies on a search-engine snippet rather than a fetched
primary file). Re-verify every row against the primary CMS file before any
non-demo use; this ruleset is small and deliberately limited to the codes
the fixture corpus exercises.

## MUE (`mue` table)

| code | max_units | adjudication_type | source |
|------|-----------|--------------------|--------|
| 88341 | 13 | date_of_service | CMS NCCI MUE table, update effective 2018-07-01, corroborated via search snippet citing the CMS MUE page (`cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-medically-unlikely-edits-mues`); primary file not directly fetchable from this sandbox. |
| 88342 | 1 | claim_line | CMS NCCI guidance: "only one initial [IHC] stain may be reported per specimen" per date of service; billing more than one unit without an anatomic/59-family modifier is treated as a duplicate. Corroborated via search snippet of CMS NCCI Policy Manual chapter 10 (pathology/laboratory) commentary. |
| 88312 | 9 | date_of_service | CMS NCCI MUE table, corroborated via search snippet (AAPC/Codify code reference summarizing the current published MUE). |
| 88313 | 8 | date_of_service | CMS NCCI MUE table, corroborated via search snippet (AAPC/Codify code reference summarizing the current published MUE). |

## PTP edits (`ptp_edit` table)

**Empty in this ruleset.** The NCCI PTP edit files (column1/column2 code
pairs with modifier indicators) are only published as CMS downloadable
data files, and this sandbox's network policy blocks `cms.gov`, so no
specific pair could be verified rather than guessed. The `validate`
stage's PTP-conflict check is fully implemented and unit-tested against
synthetic in-memory rows (see `pipeline/validate/test_checks.py`) so the
code path is proven correct; it simply has no real pairs to apply yet.
Loading the real file is a data-only change once this sandbox (or a
follow-up session with network access) can reach CMS's NCCI edit
downloads.

## Coverage policy / coverage diagnosis (`coverage_policy`,
`coverage_diagnosis` tables)

**Synthetic, explicitly labeled — not a real LCD.** Which MAC jurisdiction
and payer mix to model is an open decision for Todd (see ASSUMPTIONS.md).
Rather than invent a fake-but-real-looking LCD identifier, this ruleset
ships one clearly synthetic policy, `DEMO-POLICY-88305`, under the
already-synthetic jurisdiction `DEMO-MAC-J5`, applying to CPT 88305/88304
regardless of specimen type (real Medicare documentation-requirement
policies for a level-IV surgical pathology code typically do span many
specimen types under one policy this way). Its diagnosis list uses real,
freely-usable ICD-10-CM codes covering the fixture corpus's skin and GI
specimens (D22.9 melanocytic nevus, L82.1 seborrheic keratosis, L57.0
actinic keratosis, D12.6 benign neoplasm of colon, K63.5 polyp of colon)
— the *codes* are real CMS/WHO identifiers with no licensing restriction,
but the *policy itself* (which diagnoses this fictitious policy covers) is
a structural demo fixture, not a citation to a real LCD. Deliberately
missing from the list: D48.5 (neoplasm of uncertain behavior, skin) --
case 10 exercises "indication present but not on the coverage policy
list" using exactly that gap. Replace this table wholesale once Todd
names the MAC(s) to model.

## Substitution (`substitution` table)

| payer_class | from_code | to_code | condition | source |
|---|---|---|---|---|
| medicare | 88305 | G0416 | Prostate needle biopsy, saturation technique, any method, when 10 or more specimens are submitted from a single encounter — Medicare requires the bundled HCPCS G0416 instead of per-specimen 88305 billing. | Long-standing CMS policy (originating with the 2013 physician fee schedule pathology bundling changes for prostate biopsies), corroborated via search snippets referencing G0416 alongside CPT 88305 billing guidance. Primary CMS transmittal not directly fetchable from this sandbox. |

## CPT descriptors

No CPT descriptor text is stored anywhere in this repository. Code
identifiers appear as bare strings; `rulesets/2026q3/cpt_descriptors.json`
holds clearly-marked placeholder text only. See ASSUMPTIONS.md — AMA
licensing has not been raised with Sam/Todd yet.
