"""End-to-end regression coverage on a real (non-synthetic) signed-out
report, past the point every other live PDF run in this project has
stopped at so far: a bare PDF never carries a structured accessioning
specimen list (see normalize/free_text.py), so every prior live run
blocked on `ACCESSIONING_SPECIMEN_LIST_ABSENT` before rules/units.py or
rules/cpt_level.py ever executed. This file attaches a synthetic
accessioning record -- one specimen, "A", site "left forearm skin" --
grounded in exactly what this report's own narrative supports (see
test_normalize_free_text.py's REAL_MELANOMA_REPORT, the same report),
to prove the reconciliation and CPT-level code paths themselves are
correct on real clinical prose, not just on synthetic fixtures.

The specimen-extraction response used below is real: it matches the
live model output actually observed running this exact PDF through the
test console (`Extracted labels: A`). The procedure-type response is
NOT live-verified -- that path was blocked before this fix existed, so
there is no live answer to reproduce yet. It's a constructed response
using a real, verbatim quote from the report's own diagnosis header,
built to exercise the CPT-level rules path honestly, not to assert
what a live model would actually say.
"""

from __future__ import annotations

import json
from datetime import date

from coding_agent.extract.procedure_type import extract_procedure_types
from coding_agent.extract.specimens import extract_specimen_mentions
from coding_agent.normalize.case import Maybe, Specimen, SpecimenSourceField
from coding_agent.normalize.free_text import parse_report_text
from coding_agent.recommend.cpt_level import build_cpt_level_recommendation
from coding_agent.recommend.assemble import build_recommendation

# Identical to REAL_MELANOMA_REPORT in test_normalize_free_text.py --
# duplicated rather than imported across test files, matching this
# repo's existing convention of each test file owning its own fixture
# text (see that file's own MESSY_REAL_WORLD_REPORT).
REAL_MELANOMA_REPORT = """\
APEX METROPOLITAN MEDICAL CENTER
 DEPARTMENT OF PATHOLOGY & LABORATORY MEDICINE
 100 Medical Plaza, Suite 400 | Tel: (555) 019-2834
Patient Name:
Doe, Jane
Accession No:
SP-26-9876
DOB:
05/12/1980
Medical Record #:
MRN-774-921
Gender:
Female
Facility:
Apex Memorial Hospital
Date of
Collection:
09/18/2026
Ordering Physician:
Dr. Robert Smith, M.D.
Date of Receipt:
09/18/2026
Report Status:
FINAL
CLINICAL HISTORY / PRE-OPERATIVE DIAGNOSIS
Left forearm skin lesion, irregular borders and progressive color changes over the past 3 months. Rule out malignant
melanoma vs. dysplastic nevus.
SPECIMEN RECEIVED
Specimen A: Left forearm lesion
FINAL PATHOLOGIC DIAGNOSIS
SKIN, LEFT FOREARM, EXCISION:
— SUPERFICIAL SPREADING MALIGNANT MELANOMA, INVASIVE.
— BRESLOW THICKNESS: 0.45 MM.
— CLARK LEVEL: II.
— ULCERATION: ABSENT.
— MITOTIC RATE: 1 / MM².
— PERIPHERAL AND DEEP SURGICAL MARGINS ARE NEGATIVE FOR MALIGNANCY (CLOSEST PERIPHERAL
MARGIN IS 3.0 MM).
GROSS DESCRIPTION
Received in formal fixation, labeled with the patient's name and 'left forearm lesion,' is an elliptical fragment of skin
measuring 1.5 x 0.8 x 0.4 cm. The epithelial surface exhibits an asymmetrical, irregular, tan-brown to black pigmented
flat lesion measuring 0.6 cm in its greatest dimension. The lesion is located 0.3 cm from the nearest peripheral surgical
margin. Cross sectioning reveals a flat macule with no deep dermal extension visible macroscopically. The deep margin
is inked black, and the peripheral margins are inked green. The specimen is serially sectioned and entirely submitted in
cassette A1.
MICROSCOPIC DESCRIPTION

Sections of block A1 demonstrate an asymmetrical, poorly circumscribed melanocytic proliferation arranged singly and
in nests along the dermal-epidermal junction. Marked cytologic atypia is noted, with melanocytes exhibiting enlarged,
hyperchromatic nuclei, prominent irregular nucleoli, and frequent pagetoid ascent into the higher levels of the stratum
spinosum. In the papillary dermis, small clusters of atypical melanocytes are noted, confirming microinvasion. The
maximum thickness of the invasive component (Breslow Thickness) is measured manually using an ocular micrometer
as 0.45 mm from the granular cell layer. No ulceration or lymphovascular invasion is detected. The deep surgical
margin and all peripheral margins are completely clear of atypical melanocytic proliferation.
Electronically Signed By:
Dr. Jonathan Vance, M.D., FCAP
Board Certified Pathologist
Sign-off Date/Time: 09/20/2026 14:22 CDT
 This is for informational purposes only. For medical advice or diagnosis, consult a professional. AI responses may include mistakes.
"""


class FakeClient:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        return self.response_text, 0, 0


def _case_with_synthetic_accessioning() -> "Case":  # noqa: F821 - typing only
    case = parse_report_text(
        REAL_MELANOMA_REPORT,
        case_id="SP-26-9876",
        accession_number="SP-26-9876",
        date_of_service=date(2026, 9, 23),
    )
    # The one thing a bare PDF can never supply (see
    # normalize/free_text.py's module docstring). Grounded in what this
    # narrative actually describes -- one specimen, left forearm skin
    # -- not invented to make the test pass.
    return case.model_copy(
        update={
            "specimens": Maybe.of(
                (
                    Specimen(
                        specimen_id="A",
                        source_field=SpecimenSourceField.MANUAL,
                        site=Maybe.of("left forearm skin"),
                    ),
                )
            )
        }
    )


def test_unit_reconciliation_agrees_on_a_real_report_once_accessioning_is_attached():
    case = _case_with_synthetic_accessioning()

    # Real, live-verified model output -- matches the "Extracted
    # labels: A" result actually observed running this PDF through the
    # test console after the header-recognition fix (ASSUMPTIONS.md #15).
    specimen_response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "section": "gross",
                    "quoted": "Specimen A: Left forearm lesion",
                }
            ],
        }
    )
    extraction, _ = extract_specimen_mentions(case, client=FakeClient(specimen_response))
    assert not extraction.abstained
    assert {m.label for m in extraction.mentions} == {"A"}

    recommendation = build_recommendation(case, extraction, baseline=(), primary_code="88305")

    # AGREED: the narrative-derived label set exactly matches the
    # synthetic accessioning record -- the first time this session the
    # actual reconciliation logic (not just extraction/abstention) has
    # run to completion on a real, non-synthetic report.
    assert recommendation.blocked is None
    assert recommendation.lines == ()


def test_cpt_level_recommendation_cannot_yet_level_an_excision():
    """Locks in a real, pre-existing gap rather than papering over it:
    rules/cpt_level.py's SPECIMEN_LEVEL_TABLE has no entry for
    "excision" at all (not a regression -- pipeline/map/catalog.py,
    the table this was ported from, never had one either), despite
    "excision" being one of the four categories procedure_type_v1.txt's
    own prompt asks the model to recognize. See ASSUMPTIONS.md #16 and
    the tracked follow-up issue for why this isn't just filled in with
    a guessed code: the module's own policy requires a cited source
    before a new table entry, and none is available from this build
    environment.

    When a properly-cited excision mapping is added, this specimen
    should start producing a real CptLevelFinding instead of landing in
    unaddressed_specimen_ids -- updating this test's assertion at that
    point is the intended outcome, not a regression.
    """
    case = _case_with_synthetic_accessioning()

    # NOT live-verified (see module docstring): a constructed response
    # using a real, verbatim quote from this report's own diagnosis
    # header, built to exercise the rules path honestly.
    procedure_response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {
                    "label": "A",
                    "procedure_type": "excision",
                    "section": "diagnosis",
                    "quoted": "SKIN, LEFT FOREARM, EXCISION:",
                }
            ],
        }
    )
    extraction, _ = extract_procedure_types(case, client=FakeClient(procedure_response))
    assert not extraction.abstained

    cpt_recommendation = build_cpt_level_recommendation(case, extraction, baseline=())

    assert cpt_recommendation.blocked is None  # reached the rules layer -- not blocked
    assert cpt_recommendation.findings == ()
    assert cpt_recommendation.unaddressed_specimen_ids == ("A",)
