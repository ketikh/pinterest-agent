"""Unit tests for caption_generator — all Anthropic API calls mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services import caption_generator as cg


FAKE_ENV = {"ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_MODEL": "claude-haiku-test"}

# Helper — mimic an anthropic Message.content list of TextBlock objects
def _msg(text: str) -> MagicMock:
    block = SimpleNamespace(text=text, type="text")
    return SimpleNamespace(content=[block])


# ---------------------------------------------------------------------------
# Pre-flight / input validation
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_no_api_key_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            result = cg.generate_captions("Test Bag")
        assert result["success"] is False
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_empty_bag_name_rejected(self):
        with patch.dict("os.environ", FAKE_ENV):
            result = cg.generate_captions("")
        assert result["success"] is False
        assert "bag_name" in result["error"]


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

class TestParseJson:
    def test_plain_json(self):
        assert cg._parse_json('{"a": 1}') == {"a": 1}

    def test_strips_code_fences(self):
        assert cg._parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_finds_json_in_prose(self):
        assert cg._parse_json('Here you go: {"x": "y"} done') == {"x": "y"}

    def test_returns_none_on_garbage(self):
        assert cg._parse_json("not json at all") is None

    def test_empty_returns_none(self):
        assert cg._parse_json("") is None


# ---------------------------------------------------------------------------
# generate_captions — full path with mocked Anthropic client
# ---------------------------------------------------------------------------

class TestGenerateCaptions:
    def test_success_returns_two_captions(self):
        fake_response = _msg(
            '{"fb_caption": "ლამაზი ჩანთა ✨ #TissuGeorgia",'
            ' "ig_caption": "Beautiful bag 🤎\\n\\n#TissuGeorgia #HandcraftedBags"}'
        )
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(cg.anthropic, "Anthropic", return_value=fake_client):
            result = cg.generate_captions("Black Tote", reference_url="https://x")

        assert result["success"] is True
        assert "TissuGeorgia" in result["fb_caption"]
        assert "HandcraftedBags" in result["ig_caption"]
        assert result["model_used"] == cg.DEFAULT_MODEL

        # Verify system + user prompts were sent
        call = fake_client.messages.create.call_args
        assert "Tissu Georgia" in call.kwargs["system"]
        assert "Black Tote" in call.kwargs["messages"][0]["content"]

    def test_missing_caption_field_returns_error(self):
        fake_response = _msg('{"fb_caption": "only fb"}')  # ig_caption missing
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(cg.anthropic, "Anthropic", return_value=fake_client):
            result = cg.generate_captions("Bag")

        assert result["success"] is False
        assert "Missing caption fields" in result["error"]

    def test_unparseable_response_returns_error(self):
        fake_response = _msg("this is not JSON at all")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(cg.anthropic, "Anthropic", return_value=fake_client):
            result = cg.generate_captions("Bag")

        assert result["success"] is False
        assert "Could not parse JSON" in result["error"]

    def test_api_error_returns_error(self):
        fake_client = MagicMock()
        # Raise the real anthropic.APIError so the except branch matches
        fake_client.messages.create.side_effect = cg.anthropic.APIError(
            message="rate limit", request=MagicMock(), body=None,
        )

        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(cg.anthropic, "Anthropic", return_value=fake_client):
            result = cg.generate_captions("Bag")

        assert result["success"] is False
        assert "Anthropic API error" in result["error"]
        assert "rate limit" in result["error"]

    def test_string_content_also_supported(self):
        # Some mocked responses might return plain string content
        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content='{"fb_caption": "x #TissuGeorgia", "ig_caption": "y #TissuGeorgia #HandcraftedBags"}',
        )

        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(cg.anthropic, "Anthropic", return_value=fake_client):
            result = cg.generate_captions("Bag")

        assert result["success"] is True
