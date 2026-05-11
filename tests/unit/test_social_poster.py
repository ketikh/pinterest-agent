"""Unit tests for social_poster — all Meta Graph API calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services import social_poster as sp

FAKE_ENV = {
    "FB_PAGE_TOKEN": "EAA-fake-token",
    "FB_PAGE_ID": "1234567890",
    "IG_BUSINESS_ACCOUNT_ID": "9876543210",
    "META_API_VERSION": "v21.0",
}


def _resp(json_body=None, status: int = 200, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = text or str(json_body or {})
    r.headers = {}
    return r


# ---------------------------------------------------------------------------
# generate_caption
# ---------------------------------------------------------------------------

class TestGenerateCaption:
    def test_fb_default_includes_bag_name(self):
        approval = MagicMock(bag=MagicMock(bag_name="Laptop Bag XL", id=42))
        with patch("ai_bag_agent.ai_content.models.Setting.get",
                   return_value=sp.DEFAULT_FB_TEMPLATE):
            caption = sp.generate_caption(approval, "fb")
        assert "Laptop Bag XL" in caption
        assert "TissuGeorgia" in caption

    def test_ig_default_has_more_hashtags(self):
        approval = MagicMock(bag=MagicMock(bag_name="Tote", id=1))
        with patch("ai_bag_agent.ai_content.models.Setting.get",
                   return_value=sp.DEFAULT_IG_TEMPLATE):
            caption = sp.generate_caption(approval, "ig")
        assert caption.count("#") > sp.DEFAULT_FB_TEMPLATE.count("#")

    def test_custom_template_from_settings(self):
        approval = MagicMock(bag=MagicMock(bag_name="Custom", id=7))
        with patch("ai_bag_agent.ai_content.models.Setting.get",
                   return_value="Hello {bag_name} #{bag_id}"):
            caption = sp.generate_caption(approval, "fb")
        assert caption == "Hello Custom #7"

    def test_invalid_template_falls_back_to_default(self):
        approval = MagicMock(bag=MagicMock(bag_name="Foo", id=5))
        with patch("ai_bag_agent.ai_content.models.Setting.get",
                   return_value="Bad {unknown_variable}"):
            caption = sp.generate_caption(approval, "fb")
        assert "Foo" in caption  # default template was used

    def test_invalid_platform_raises(self):
        approval = MagicMock(bag=MagicMock(bag_name="X", id=1))
        with pytest.raises(ValueError):
            sp.generate_caption(approval, "twitter")


# ---------------------------------------------------------------------------
# post_to_facebook
# ---------------------------------------------------------------------------

class TestPostToFacebook:
    def test_missing_token_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            result = sp.post_to_facebook("https://x.jpg", "caption")
        assert result["success"] is False
        assert "FB_PAGE_TOKEN" in result["error"]

    def test_success_returns_post_id(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "post") as mock_post:
            mock_post.return_value = _resp({"id": "9999_8888", "post_id": "9999_8888"})
            result = sp.post_to_facebook("https://x.jpg", "caption")
        assert result["success"] is True
        assert result["post_id"] == "9999_8888"

    def test_401_marks_failure_and_logs(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "post") as mock_post, \
             patch.object(sp, "_notify_admin"):
            mock_post.return_value = _resp(
                {"error": {"code": 190, "message": "token expired"}}, status=401,
            )
            result = sp.post_to_facebook("https://x.jpg", "caption")
        assert result["success"] is False
        assert "401" in result["error"] or "token" in result["error"].lower()

    def test_5xx_retries(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "post") as mock_post, \
             patch.object(sp.time, "sleep"):
            mock_post.side_effect = [
                _resp(status=502, text="bad gateway"),
                _resp(status=503, text="unavailable"),
                _resp({"id": "ok"}),
            ]
            result = sp.post_to_facebook("https://x.jpg", "caption")
        assert result["success"] is True
        assert mock_post.call_count == 3


# ---------------------------------------------------------------------------
# post_to_instagram
# ---------------------------------------------------------------------------

class TestPostToInstagram:
    def test_full_flow_success(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "post") as mock_post, \
             patch.object(sp.requests, "get") as mock_get, \
             patch.object(sp.time, "sleep"), \
             patch.object(sp.time, "monotonic", side_effect=[0, 1, 2]):
            mock_post.side_effect = [
                _resp({"id": "container_123"}),  # create container
                _resp({"id": "media_456"}),      # publish
            ]
            mock_get.return_value = _resp({"status_code": "FINISHED"})
            result = sp.post_to_instagram("https://x.jpg", "caption")
        assert result["success"] is True
        assert result["post_id"] == "media_456"

    def test_container_error_status(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "post") as mock_post, \
             patch.object(sp.requests, "get") as mock_get, \
             patch.object(sp.time, "sleep"), \
             patch.object(sp.time, "monotonic", side_effect=[0, 1]):
            mock_post.return_value = _resp({"id": "container_X"})
            mock_get.return_value = _resp({"status_code": "ERROR"})
            result = sp.post_to_instagram("https://x.jpg", "caption")
        assert result["success"] is False
        assert "ERROR" in result["error"]

    def test_missing_token_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            result = sp.post_to_instagram("https://x.jpg", "caption")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# check_token
# ---------------------------------------------------------------------------

class TestCheckToken:
    def test_no_token(self):
        with patch.dict("os.environ", {}, clear=True):
            result = sp.check_token()
        assert result["valid"] is False

    def test_valid_long_lived(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "get") as mock_get:
            mock_get.side_effect = [
                _resp({"id": "1", "name": "Tissu Georgia"}),  # /me
                _resp({"data": {"expires_at": 0}}),            # debug_token
            ]
            result = sp.check_token()
        assert result["valid"] is True
        assert result["name"] == "Tissu Georgia"
        assert result["expires_in_days"] == "never"

    def test_invalid_token(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(sp.requests, "get") as mock_get:
            mock_get.return_value = _resp({}, status=400, text="invalid")
            result = sp.check_token()
        assert result["valid"] is False
