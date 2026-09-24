import json
from pathlib import Path

import pytest

from pipeline.adapters import fixture as fixture_adapter
from pipeline.extract.parser import ExtractionRejectedError
from pipeline.extract.runner import extract_facts

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"


class FakeClient:
    """Stands in for the Anthropic SDK: returns canned JSON per call, in
    the order the three prompts are issued (specimen, stain, diagnosis)."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        self.calls.append({"model": model, "prompt": prompt})
        text = self._responses[len(self.calls) - 1]
        return text, 100, 50


@pytest.fixture()
def case_01():
    return fixture_adapter.load_case(FIXTURES_ROOT / "case_01")


def test_extract_facts_end_to_end_with_a_fake_client(case_01):
    specimen_json = json.dumps(
        [{"specimen_id": "A", "value": {"sites": ["skin, left forearm"]}, "document_id": "doc-report", "quoted": "A. Skin, left forearm, shave biopsy", "confidence": "high"}]
    )
    stain_json = json.dumps(
        [{"specimen_id": "A", "value": {"block_id": "A1", "stain_id": "A1-1", "kind": "he", "antibody": None}, "document_id": "doc-report", "quoted": "Hematoxylin and eosin stained sections", "confidence": "high"}]
    )
    diagnosis_json = json.dumps(
        [{"specimen_id": "A", "value": {"text": "compound nevus", "certainty": "definitive", "qualifier": None}, "document_id": "doc-report", "quoted": "Compound nevus, margins appear clear in this specimen.", "confidence": "high"}]
    )
    client = FakeClient([specimen_json, stain_json, diagnosis_json])

    facts, metrics, prompt_versions = extract_facts(case_01, client=client, model="claude-sonnet-5")

    assert len(facts) == 3
    assert len(client.calls) == 3
    assert all(call["model"] == "claude-sonnet-5" for call in client.calls)
    assert set(prompt_versions) == {"specimen", "stain", "diagnosis"}
    assert set(metrics) == {"specimen", "stain", "diagnosis"}
    for m in metrics.values():
        assert m.input_tokens == 100
        assert m.output_tokens == 50

    # The prompt text sent to the model must never mention billing terms.
    for call in client.calls:
        lowered = call["prompt"].lower()
        for banned in ("cpt", "icd-10", "icd10", "billing", "reimburse"):
            assert banned not in lowered


def test_extract_facts_propagates_rejection_from_any_stage(case_01):
    client = FakeClient(["not json", "[]", "[]"])
    with pytest.raises(ExtractionRejectedError):
        extract_facts(case_01, client=client, model="claude-sonnet-5")


def test_documents_are_all_rendered_into_the_prompt(case_01):
    client = FakeClient(["[]", "[]", "[]"])
    extract_facts(case_01, client=client, model="claude-sonnet-5")
    prompt = client.calls[0]["prompt"]
    for doc in case_01.documents:
        assert doc.document_id in prompt
        assert doc.text in prompt
