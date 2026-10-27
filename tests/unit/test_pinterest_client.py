"""Unit tests for pinterest_client (all HTTP calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services.pinterest_client import (
    _slug_from_url,
    _slugify,
    _to_jpg_url,
    get_best_image_url,
    get_random_pin,
    get_user_boards,
)

FAKE_TOKEN = "pina_test_abc"
BOARD_URL = "https://www.pinterest.com/tissugeorgia/laptop-bags/"

FAKE_BOARD = {
    "id": "123456789",
    "name": "Laptop Bags",
    "url": "https://www.pinterest.com/tissugeorgia/laptop-bags/",
    "pin_count": 42,
    "privacy": "PUBLIC",
}

FAKE_PIN = {
    "id": "pin_001",
    "title": "Nice Bag",
    "description": "A great bag",
    "media": {
        "images": {
            "1200x": {"url": "https://i.pinimg.com/1200x/aa/bb/cc/hash.jpg", "width": 1200},
            "736x": {"url": "https://i.pinimg.com/736x/aa/bb/cc/hash.jpg", "width": 736},
        }
    },
}


def _resp(data: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    r.text = str(data)
    r.headers = {}
    return r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestSlugFromUrl:
    def test_extracts_slug(self):
        assert _slug_from_url(BOARD_URL) == "tissugeorgia/laptop-bags"

    def test_trailing_slash_handled(self):
        assert _slug_from_url(BOARD_URL.rstrip("/")) == "tissugeorgia/laptop-bags"

    def test_invalid_url_returns_none(self):
        assert _slug_from_url("https://example.com") is None


class TestSlugify:
    def test_simple_name_lowercased_and_dashed(self):
        assert _slugify("Laptop Bags") == "laptop-bags"

    def test_punctuation_collapsed(self):
        assert _slugify("Bag's Collection!") == "bag-s-collection"

    def test_empty_returns_empty(self):
        assert _slugify("") == ""

    def test_multiple_spaces(self):
        assert _slugify("Many   Spaces") == "many-spaces"


class TestToJpgUrl:
    def test_webp_converted(self):
        url = "https://i.pinimg.com/webp70/1200x/aa/bb/cc/hash.webp"
        result = _to_jpg_url(url)
        assert result.endswith(".jpg")
        assert "webp" not in result

    def test_jpg_unchanged(self):
        url = "https://i.pinimg.com/736x/aa/bb/cc/hash.jpg"
        assert _to_jpg_url(url) == url


class TestGetBestImageUrl:
    def test_prefers_1200x(self):
        url = get_best_image_url(FAKE_PIN)
        assert "1200x" in url

    def test_fallback_to_736x(self):
        pin = {"media": {"images": {"736x": {"url": "https://i.pinimg.com/736x/aa/bb/cc/h.jpg"}}}}
        assert "736x" in get_best_image_url(pin)

    def test_raises_if_no_images(self):
        with pytest.raises(ValueError):
            get_best_image_url({})


# ---------------------------------------------------------------------------
# get_user_boards
# ---------------------------------------------------------------------------

class TestGetUserBoards:
    def test_no_token_returns_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            import os; os.environ.pop("PINTEREST_ACCESS_TOKEN", None)
            result = get_user_boards()
        assert result == []

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_returns_boards(self, mock_get):
        mock_get.return_value = _resp({"items": [FAKE_BOARD], "bookmark": None})
        boards = get_user_boards()
        assert len(boards) == 1
        assert boards[0]["id"] == "123456789"
        assert boards[0]["name"] == "Laptop Bags"

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_401_returns_empty(self, mock_get):
        mock_get.return_value = _resp({}, status=401)
        boards = get_user_boards()
        assert boards == []


# ---------------------------------------------------------------------------
# get_random_pin
# ---------------------------------------------------------------------------

class TestGetRandomPin:
    def test_no_token_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            import os; os.environ.pop("PINTEREST_ACCESS_TOKEN", None)
            result = get_random_pin(BOARD_URL)
        assert result["success"] is False
        assert result["error"] is not None

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_success_returns_all_keys(self, mock_pins, mock_board_id):
        mock_board_id.return_value = "123456789"
        mock_pins.return_value = [FAKE_PIN]

        result = get_random_pin(BOARD_URL, exclude_recent_days=0)

        assert result["success"] is True
        assert result["pin_id"] == "pin_001"
        assert result["image_url"].endswith(".jpg")
        assert result["pin_url"] == "https://www.pinterest.com/pin/pin_001/"
        assert result["error"] is None

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_empty_board_returns_error(self, mock_pins, mock_board_id):
        mock_board_id.return_value = "123456789"
        mock_pins.return_value = []

        result = get_random_pin(BOARD_URL)
        assert result["success"] is False
        assert "no pins" in result["error"].lower()

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    def test_board_not_found_returns_error(self, mock_board_id):
        mock_board_id.return_value = None
        result = get_random_pin(BOARD_URL)
        assert result["success"] is False

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_image_url_is_jpg(self, mock_pins, mock_board_id):
        mock_board_id.return_value = "123456789"
        webp_pin = {
            "id": "pin_webp",
            "title": "", "description": "",
            "media": {"images": {"1200x": {"url": "https://i.pinimg.com/webp70/1200x/aa/bb/cc/h.webp"}}},
        }
        mock_pins.return_value = [webp_pin]

        result = get_random_pin(BOARD_URL, exclude_recent_days=0)
        assert result["success"] is True
        assert result["image_url"].endswith(".jpg")
        assert "webp" not in result["image_url"]


# ---------------------------------------------------------------------------
# get_best_image_url — every v5 media shape
# ---------------------------------------------------------------------------

class TestGetBestImageUrlMediaShapes:
    def test_api_v5_sizes_without_1200x_pick_600x(self):
        pin = {"media": {"media_type": "image", "images": {
            "150x150": {"url": "https://i.pinimg.com/150x150/a/h.jpg", "width": 150},
            "400x300": {"url": "https://i.pinimg.com/400x300/a/h.jpg", "width": 400},
            "600x": {"url": "https://i.pinimg.com/600x/a/h.jpg", "width": 600},
        }}}
        assert get_best_image_url(pin).startswith("https://i.pinimg.com/600x/")

    def test_video_pin_uses_cover_image(self):
        pin = {"media": {"media_type": "video",
                         "cover_image_url": "https://i.pinimg.com/736x/v/cover.jpg"}}
        assert get_best_image_url(pin) == "https://i.pinimg.com/736x/v/cover.jpg"

    def test_carousel_pin_uses_first_item_with_images(self):
        pin = {"media": {"media_type": "multiple_images", "items": [
            {"item_type": "image", "images": {}},
            {"item_type": "image", "images": {
                "1200x": {"url": "https://i.pinimg.com/1200x/c/two.jpg"}}},
        ]}}
        assert get_best_image_url(pin) == "https://i.pinimg.com/1200x/c/two.jpg"

    def test_unknown_size_keys_pick_widest(self):
        pin = {"media": {"images": {
            "small": {"url": "https://i.pinimg.com/s.jpg", "width": 300},
            "large": {"url": "https://i.pinimg.com/l.jpg", "width": 900},
        }}}
        assert get_best_image_url(pin) == "https://i.pinimg.com/l.jpg"

    def test_bare_repin_payload_raises(self):
        pin = {"id": "repin", "media": {"media_type": "image", "images": {}}}
        with pytest.raises(ValueError):
            get_best_image_url(pin)


# ---------------------------------------------------------------------------
# Candidate ordering + repin fallback inside get_random_pin
# ---------------------------------------------------------------------------

def _pin(pin_id: str, created: str, with_image: bool = True) -> dict:
    media = {"media_type": "image", "images": {}}
    if with_image:
        media["images"] = {"1200x": {"url": f"https://i.pinimg.com/1200x/x/{pin_id}.jpg"}}
    return {"id": pin_id, "created_at": created, "media": media}


class TestOrderCandidates:
    def test_never_used_newest_first_then_used_least_recent_first(self):
        from ai_bag_agent.ai_content.services.pinterest_client import _order_candidates
        pins = [
            _pin("old_fresh", "2026-01-01T00:00:00"),
            _pin("new_fresh", "2026-06-01T00:00:00"),
            _pin("used_recent", "2025-01-01T00:00:00"),
            _pin("used_long_ago", "2025-01-01T00:00:00"),
        ]
        last_used = {"used_recent": 200.0, "used_long_ago": 100.0}
        ordered = [p["id"] for p in _order_candidates(pins, last_used)]
        assert ordered == ["new_fresh", "old_fresh", "used_long_ago", "used_recent"]


class TestGetRandomPinRepinFallback:
    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_pin_image.resolve_pin_image_fallback")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_bare_pin_recovered_via_fallback(self, mock_pins, mock_board_id, mock_resolve):
        mock_board_id.return_value = "123456789"
        mock_pins.return_value = [_pin("repin_1", "2026-06-01", with_image=False)]
        mock_resolve.return_value = ("https://i.pinimg.com/736x/r/one.jpg", "pin-page")

        result = get_random_pin(BOARD_URL)

        assert result["success"] is True
        assert result["pin_id"] == "repin_1"
        assert result["image_url"] == "https://i.pinimg.com/736x/r/one.jpg"
        mock_resolve.assert_called_once_with("repin_1")

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_pin_image.resolve_pin_image_fallback")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pin_last_used_map")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_used_pin_with_image_beats_failing_fresh_repin(
        self, mock_pins, mock_board_id, mock_last_used, mock_resolve
    ):
        mock_board_id.return_value = "123456789"
        mock_pins.return_value = [
            _pin("repin_fresh", "2026-06-01", with_image=False),
            _pin("own_used", "2026-01-01", with_image=True),
        ]
        mock_last_used.return_value = {"own_used": 1.0}
        mock_resolve.return_value = (None, None)

        result = get_random_pin(BOARD_URL)

        assert result["success"] is True
        assert result["pin_id"] == "own_used"

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.MAX_IMAGE_FALLBACK_ATTEMPTS", 2)
    @patch("ai_bag_agent.ai_content.services.pinterest_pin_image.resolve_pin_image_fallback")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_board_id_from_url")
    @patch("ai_bag_agent.ai_content.services.pinterest_client.get_pins_from_board")
    def test_fallback_attempts_are_capped(self, mock_pins, mock_board_id, mock_resolve):
        mock_board_id.return_value = "123456789"
        mock_pins.return_value = [
            _pin(f"repin_{i}", f"2026-0{i + 1}-01", with_image=False) for i in range(5)
        ]
        mock_resolve.return_value = (None, None)

        result = get_random_pin(BOARD_URL)

        assert result["success"] is False
        assert "usable image" in result["error"].lower()
        assert mock_resolve.call_count == 2
