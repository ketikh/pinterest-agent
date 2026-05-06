"""Unit tests for pinterest_client (all HTTP calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services.pinterest_client import (
    _slug_from_url,
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
