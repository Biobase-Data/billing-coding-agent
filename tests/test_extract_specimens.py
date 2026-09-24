"""Tests for extract/specimens.py: evidence-span verification, abstention
(both model-declared and the no-narrative short circuit), and rejection
of untrustworthy model output."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from coding_agent.extract.schema import AbstentionReason
from coding_agent.extract.specimens import (
    GrokClient,
    GroqClient,
    GroqRequestError,
    SpecimenExtractionRejectedError,
    extract_specimen_mentions,
)
from coding_agent.normalize.case import (
    Absent,
    Case,
    Maybe,
    NarrativeKind,
    NarrativeSection,
    Requisition,
    RequisitionMatchMethod,
    SourceFormat,
)


class FakeClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        self.calls += 1
        return self.response_text, 100, 50


class ExplodingClient:
    """A client that raises if called -- used to prove a code path never
    reaches the model."""

    def create_message(self, *, model: str, prompt: str) -> tuple[str, int, int]:
        raise AssertionError("model should not have been called")


def make_case(narrative: tuple[NarrativeSection, ...]) -> Case:
    return Case(
        case_id="case-x",
        accession_number="S26-0001",
        date_of_service=date(2026, 1, 1),
        source_format=SourceFormat.HL7V2,
        source_document_id="S26-0001",
        specimens=Maybe.missing(Absent.NOT_SUPPLIED),
        narrative=narrative,
        requisition=Requisition(match_method=RequisitionMatchMethod.ACCESSION_NUMBER),
    )


def two_specimen_case() -> Case:
    gross_text = "Received in formalin, two specimens labeled A and B."
    dx_text = "A. Skin, left forearm: compound nevus.\nB. Skin, right shoulder: compound nevus."
    return make_case(
        (
            NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.of(gross_text)),
            NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of(dx_text)),
        )
    )


def test_extracts_two_mentions_with_evidence():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {"label": "A", "section": "gross", "quoted": "two specimens labeled A and B"},
                {"label": "A", "section": "diagnosis", "quoted": "A. Skin, left forearm"},
                {"label": "B", "section": "diagnosis", "quoted": "B. Skin, right shoulder"},
            ],
        }
    )
    extraction, metrics = extract_specimen_mentions(case, client=FakeClient(response))

    assert not extraction.abstained
    assert metrics is not None
    labels = {m.label for m in extraction.mentions}
    assert labels == {"A", "B"}

    mention_a = next(m for m in extraction.mentions if m.label == "A")
    assert len(mention_a.evidence) == 2  # supported in both gross and diagnosis
    assert {span.section for span in mention_a.evidence} == {
        NarrativeKind.GROSS,
        NarrativeKind.DIAGNOSIS,
    }


def test_model_declared_abstention_is_returned_not_swallowed():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": True,
            "reason": "ambiguous_narrative",
            "detail": "labeling scheme is inconsistent across sections",
            "mentions": [],
        }
    )
    extraction, metrics = extract_specimen_mentions(case, client=FakeClient(response))

    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.AMBIGUOUS_NARRATIVE
    assert metrics is not None  # the model *was* called before it abstained


def test_no_narrative_text_abstains_without_calling_the_model():
    case = make_case((NarrativeSection(kind=NarrativeKind.GROSS, text=Maybe.missing(Absent.NOT_SUPPLIED)),))
    extraction, metrics = extract_specimen_mentions(case, client=ExplodingClient())

    assert extraction.abstained
    assert extraction.abstention.reason is AbstentionReason.SECTION_ABSENT
    assert metrics is None


def test_hallucinated_quote_rejects_the_whole_batch():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [
                {"label": "A", "section": "gross", "quoted": "this text is not in the report"}
            ],
        }
    )
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(case, client=FakeClient(response))


def test_malformed_json_rejects():
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(two_specimen_case(), client=FakeClient("not json"))


def test_unrecognized_section_rejects():
    case = two_specimen_case()
    response = json.dumps(
        {
            "abstain": False,
            "mentions": [{"label": "A", "section": "impression", "quoted": "A."}],
        }
    )
    with pytest.raises(SpecimenExtractionRejectedError):
        extract_specimen_mentions(case, client=FakeClient(response))


def test_empty_mentions_without_abstain_is_a_valid_zero_specimen_result():
    case = make_case(
        (NarrativeSection(kind=NarrativeKind.DIAGNOSIS, text=Maybe.of("No lesion identified.")),)
    )
    response = json.dumps({"abstain": False, "mentions": []})
    extraction, _ = extract_specimen_mentions(case, client=FakeClient(response))
    assert not extraction.abstained
    assert extraction.mentions == ()


class TestGroqClient:
    """GroqClient is a stdlib-only (urllib) adapter over Groq's
    OpenAI-compatible chat completions API -- mocked here rather than
    making a real network call."""

    def test_requires_api_key_at_construction(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            GroqClient()

    def test_create_message_parses_response_and_usage(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        client = GroqClient()

        payload = json.dumps(
            {
                "choices": [{"message": {"content": '{"abstain": false, "mentions": []}'}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            }
        ).encode("utf-8")
        fake_response = MagicMock()
        fake_response.__enter__.return_value = fake_response
        fake_response.read.return_value = payload

        with patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
            text, input_tokens, output_tokens = client.create_message(
                model="llama-3.3-70b-versatile", prompt="hello"
            )

        assert text == '{"abstain": false, "mentions": []}'
        assert (input_tokens, output_tokens) == (42, 7)

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-groq-key"
        sent_body = json.loads(request.data)
        assert sent_body["model"] == "llama-3.3-70b-versatile"
        assert sent_body["messages"] == [{"role": "user", "content": "hello"}]

    def test_http_error_becomes_groq_request_error_with_body(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        client = GroqClient()

        error_body = io.BytesIO(b'{"error": {"message": "invalid api key"}}')
        http_error = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=error_body,
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(GroqRequestError, match="invalid api key"):
                client.create_message(model="llama-3.3-70b-versatile", prompt="hello")

    def test_url_error_becomes_groq_request_error(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        client = GroqClient()

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("no route to host"),
        ):
            with pytest.raises(GroqRequestError, match="could not reach"):
                client.create_message(model="llama-3.3-70b-versatile", prompt="hello")


class TestGrokClient:
    """GrokClient (xAI) shares its HTTP call with GroqClient via
    _call_openai_compatible_chat -- these tests cover only what's
    specific to it: its own env var, endpoint, and error type."""

    def test_requires_api_key_at_construction(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="XAI_API_KEY"):
            GrokClient()

    def test_create_message_hits_the_xai_endpoint(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
        client = GrokClient()

        payload = json.dumps(
            {
                "choices": [{"message": {"content": '{"abstain": false, "mentions": []}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }
        ).encode("utf-8")
        fake_response = MagicMock()
        fake_response.__enter__.return_value = fake_response
        fake_response.read.return_value = payload

        with patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
            text, input_tokens, output_tokens = client.create_message(model="grok-4", prompt="hello")

        assert text == '{"abstain": false, "mentions": []}'
        assert (input_tokens, output_tokens) == (10, 3)
        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://api.x.ai/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-xai-key"

    def test_http_error_becomes_a_model_request_error(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
        client = GrokClient()

        error_body = io.BytesIO(b'{"error": "invalid api key"}')
        http_error = urllib.error.HTTPError(
            url="https://api.x.ai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=error_body,
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(GroqRequestError, match="invalid api key"):
                client.create_message(model="grok-4", prompt="hello")
