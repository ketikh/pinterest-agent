"""Unit tests for pinterest_client (all HTTP calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services.pinterest_client import (
    PinData,
    _extract_image_url,
    _to_jpg_url,
    get_random_reference_pin,
)

FAKE_TOKEN = "pina_test_token_abc123"
FAKE_BOARD_ID = "123456789"

FAKE_PIN = {
    "id": "pin_001",
    "title": "Nice Bag",
    "description": "A beautiful bag",
    "media": {
        "images": {
            "1200x": {"url": "https://i.pinimg.com/1200x/ab/cd/ef/abcdef.jpg", "width": 1200, "height": 900},
            "736x": {"url": "https://i.pinimg.com/736x/ab/cd/ef/abcdef.jpg", "width": 736, "height": 552},
        }
    },
}

FAKE_PINS_RESPONSE = {"items": [FAKE_PIN], "bookmark": None}


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.text = str(json_data)
    return r


# ---------------------------------------------------------------------------
# _to_jpg_url
# ---------------------------------------------------------------------------

class TestToJpgUrl:
    def test_webp_converted_to_jpg(self):
        url = "https://i.pinimg.com/webp70/1200x/ab/cd/ef/hash.webp"
        result = _to_jpg_url(url)
        assert result.endswith(".jpg")
        assert "webp" not in result

    def test_jpg_url_unchanged(self):
        url = "https://i.pinimg.com/736x/ab/cd/ef/hash.jpg"
        assert _to_jpg_url(url) == url


# ---------------------------------------------------------------------------
# _extract_image_url
# ---------------------------------------------------------------------------

class TestExtractImageUrl:
    def test_returns_1200x_first(self):
        url = _extract_image_url(FAKE_PIN)
        assert "1200x" in url

    def test_falls_back_to_736x(self):
        pin = {
            "media": {
                "images": {
                    "736x": {"url": "https://i.pinimg.com/736x/ab/cd/ef/hash.jpg"}
                }
            }
        }
        url = _extract_image_url(pin)
        assert "736x" in url

    def test_returns_none_if_no_images(self):
        assert _extract_image_url({"media": {}}) is None
        assert _extract_image_url({}) is None


# ---------------------------------------------------------------------------
# get_random_reference_pin
# ---------------------------------------------------------------------------

class TestGetRandomReferencePin:
    def test_no_token_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("PINTEREST_ACCESS_TOKEN", None)
            result = get_random_reference_pin(FAKE_BOARD_ID)
        assert result is None

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_successful_returns_pin_data(self, mock_get):
        mock_get.return_value = _make_response(FAKE_PINS_RESPONSE)
        pin = get_random_reference_pin(FAKE_BOARD_ID, exclude_recent=False)

        assert pin is not None
        assert isinstance(pin, PinData)
        assert pin.pin_id == "pin_001"
        assert pin.image_url.endswith(".jpg")
        assert pin.pin_url == "https://www.pinterest.com/pin/pin_001/"

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_401_returns_none(self, mock_get):
        mock_get.return_value = _make_response({}, status_code=401)
        pin = get_random_reference_pin(FAKE_BOARD_ID, exclude_recent=False)
        assert pin is None

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_empty_board_returns_none(self, mock_get):
        mock_get.return_value = _make_response({"items": [], "bookmark": None})
        pin = get_random_reference_pin(FAKE_BOARD_ID, exclude_recent=False)
        assert pin is None

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_pagination_fetches_multiple_pages(self, mock_get):
        page1 = {"items": [FAKE_PIN] * 50, "bookmark": "cursor_abc"}
        page2 = {"items": [FAKE_PIN] * 10, "bookmark": None}
        mock_get.side_effect = [
            _make_response(page1),
            _make_response(page2),
        ]
        pin = get_random_reference_pin(FAKE_BOARD_ID, exclude_recent=False)
        assert pin is not None
        assert mock_get.call_count == 2

    @patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": FAKE_TOKEN})
    @patch("ai_bag_agent.ai_content.services.pinterest_client.requests.get")
    def test_image_url_is_jpg_not_webp(self, mock_get):
        webp_pin = {
            "id": "pin_webp",
            "title": "",
            "description": "",
            "media": {
                "images": {
                    "1200x": {"url": "https://i.pinimg.com/webp70/1200x/aa/bb/cc/hash.webp"}
                }
            },
        }
        mock_get.return_value = _make_response({"items": [webp_pin], "bookmark": None})
        pin = get_random_reference_pin(FAKE_BOARD_ID, exclude_recent=False)
        assert pin is not None
        assert pin.image_url.endswith(".jpg")
        assert "webp" not in pin.image_url
