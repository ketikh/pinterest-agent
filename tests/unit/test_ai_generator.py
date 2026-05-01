"""Unit tests for ai_generator service (all external calls are mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from ai_bag_agent.ai_content.services.ai_generator import (
    GenerationResult,
    _poll_for_result,
    _resolve_image_url,
    _submit_task,
    generate_image,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_API_KEY = "sk-test-key"
BAG_URL = "https://example.com/bag.jpg"
REF_URL = "https://example.com/ref.jpg"
TASK_ID = "task_nano-banana-pro_test123"
GENERATED_URL = "https://example.com/generated.png"


def _make_submit_response(task_id: str = TASK_ID) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"code": 200, "msg": "success", "data": {"taskId": task_id}}
    return r


def _make_poll_response(state: str, result_url: str = GENERATED_URL) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    result_json = json.dumps({"resultUrls": [result_url]}) if state == "success" else "{}"
    r.json.return_value = {
        "code": 200,
        "data": {
            "taskId": TASK_ID,
            "state": state,
            "resultJson": result_json,
            "failMsg": "task error" if state == "fail" else "",
        },
    }
    return r


# ---------------------------------------------------------------------------
# _resolve_image_url
# ---------------------------------------------------------------------------

class TestResolveImageUrl:
    def test_https_url_returned_as_is(self):
        assert _resolve_image_url("https://example.com/bag.jpg") == "https://example.com/bag.jpg"

    def test_http_url_returned_as_is(self):
        assert _resolve_image_url("http://example.com/bag.jpg") == "http://example.com/bag.jpg"

    def test_local_path_returns_none(self):
        assert _resolve_image_url("/Users/me/bag.jpg") is None

    def test_relative_path_returns_none(self):
        assert _resolve_image_url("storage/bags/sample.jpg") is None


# ---------------------------------------------------------------------------
# _submit_task
# ---------------------------------------------------------------------------

class TestSubmitTask:
    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    def test_successful_submit(self, mock_post):
        mock_post.return_value = _make_submit_response()
        task_id = _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "test prompt")
        assert task_id == TASK_ID
        mock_post.assert_called_once()

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.sleep")
    def test_retries_on_503(self, mock_sleep, mock_post):
        error_resp = MagicMock()
        error_resp.status_code = 503
        success_resp = _make_submit_response()
        mock_post.side_effect = [error_resp, success_resp]

        task_id = _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "prompt", max_retries=3)
        assert task_id == TASK_ID
        assert mock_post.call_count == 2

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.sleep")
    def test_returns_none_after_max_retries(self, mock_sleep, mock_post):
        error_resp = MagicMock()
        error_resp.status_code = 503
        mock_post.return_value = error_resp

        task_id = _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "prompt", max_retries=3)
        assert task_id is None
        assert mock_post.call_count == 3

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    def test_returns_none_on_400(self, mock_post):
        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.text = "bad request"
        mock_post.return_value = bad_resp

        task_id = _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "prompt")
        assert task_id is None

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    def test_payload_contains_both_images(self, mock_post):
        mock_post.return_value = _make_submit_response()
        _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "prompt")

        _, kwargs = mock_post.call_args
        image_input = kwargs["json"]["input"]["image_input"]
        assert BAG_URL in image_input
        assert REF_URL in image_input

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.post")
    def test_payload_aspect_ratio_and_resolution(self, mock_post):
        mock_post.return_value = _make_submit_response()
        _submit_task(FAKE_API_KEY, "nano-banana-pro", BAG_URL, REF_URL, "prompt")

        _, kwargs = mock_post.call_args
        inp = kwargs["json"]["input"]
        assert inp["aspect_ratio"] == "1:1"
        assert inp["resolution"] == "2K"


# ---------------------------------------------------------------------------
# _poll_for_result
# ---------------------------------------------------------------------------

class TestPollForResult:
    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.get")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.sleep")
    def test_returns_url_on_success(self, mock_sleep, mock_get):
        # First poll returns "generating", second returns "success"
        mock_get.side_effect = [
            _make_poll_response("generating"),
            _make_poll_response("success"),
        ]
        url, error = _poll_for_result(FAKE_API_KEY, TASK_ID, poll_interval=0)
        assert url == GENERATED_URL
        assert error is None

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.get")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.sleep")
    def test_returns_error_on_fail(self, mock_sleep, mock_get):
        mock_get.return_value = _make_poll_response("fail")
        url, error = _poll_for_result(FAKE_API_KEY, TASK_ID, poll_interval=0)
        assert url is None
        assert "failed" in error

    @patch("ai_bag_agent.ai_content.services.ai_generator.requests.get")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.monotonic")
    @patch("ai_bag_agent.ai_content.services.ai_generator.time.sleep")
    def test_timeout_returns_error(self, mock_sleep, mock_monotonic, mock_get):
        # Simulate time progressing past timeout immediately
        mock_monotonic.side_effect = [0, 9999]
        mock_get.return_value = _make_poll_response("generating")

        url, error = _poll_for_result(FAKE_API_KEY, TASK_ID, poll_interval=0, timeout=10)
        assert url is None
        assert "Timed out" in error


# ---------------------------------------------------------------------------
# generate_image (integration of all steps)
# ---------------------------------------------------------------------------

class TestGenerateImage:
    @patch.dict("os.environ", {"KIE_AI_API_KEY": FAKE_API_KEY})
    @patch("ai_bag_agent.ai_content.services.ai_generator._download_generated")
    @patch("ai_bag_agent.ai_content.services.ai_generator._poll_for_result")
    @patch("ai_bag_agent.ai_content.services.ai_generator._submit_task")
    def test_full_success_flow(self, mock_submit, mock_poll, mock_download):
        mock_submit.return_value = TASK_ID
        mock_poll.return_value = (GENERATED_URL, None)
        mock_download.return_value = "/tmp/generated.png"

        result = generate_image(BAG_URL, REF_URL, "nice bag", "default")

        assert result["success"] is True
        assert result["generated_url"] == GENERATED_URL
        assert result["local_path"] == "/tmp/generated.png"
        assert result["error"] is None

    @patch.dict("os.environ", {"KIE_AI_API_KEY": FAKE_API_KEY})
    def test_local_path_returns_failure(self):
        result = generate_image("/Users/me/bag.jpg", REF_URL)
        assert result["success"] is False
        assert "local path" in result["error"].lower() or "cloudinary" in result["error"].lower()

    def test_missing_api_key_returns_failure(self):
        with patch.dict("os.environ", {}, clear=True):
            # Ensure key is definitely absent
            import os
            os.environ.pop("KIE_AI_API_KEY", None)
            os.environ.pop("KIEAI_API_KEY", None)
            result = generate_image(BAG_URL, REF_URL)
        assert result["success"] is False
        assert "KIE_AI_API_KEY" in result["error"]

    @patch.dict("os.environ", {"KIE_AI_API_KEY": FAKE_API_KEY})
    @patch("ai_bag_agent.ai_content.services.ai_generator._submit_task")
    def test_submit_failure_returns_error(self, mock_submit):
        mock_submit.return_value = None
        result = generate_image(BAG_URL, REF_URL)
        assert result["success"] is False
        assert result["error"] is not None

    @patch.dict("os.environ", {"KIE_AI_API_KEY": FAKE_API_KEY})
    @patch("ai_bag_agent.ai_content.services.ai_generator._download_generated")
    @patch("ai_bag_agent.ai_content.services.ai_generator._poll_for_result")
    @patch("ai_bag_agent.ai_content.services.ai_generator._submit_task")
    def test_result_dict_has_all_keys(self, mock_submit, mock_poll, mock_download):
        mock_submit.return_value = TASK_ID
        mock_poll.return_value = (GENERATED_URL, None)
        mock_download.return_value = None

        result = generate_image(BAG_URL, REF_URL)
        required_keys = {"success", "generated_url", "local_path", "model_used",
                         "generation_time_sec", "error"}
        assert required_keys.issubset(result.keys())
