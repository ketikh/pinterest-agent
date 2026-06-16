"""Unit tests for inspirations_client (all HTTP calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ai_bag_agent.ai_content.services import inspirations_client

MODULE = "ai_bag_agent.ai_content.services.inspirations_client"
KEY_ENV = {"INSPIRATIONS_API_KEY": "tissu_rw_test"}


def _resp(status_code=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    if json_body is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = json_body
    r.text = text
    return r


PHOTOS = {
    "photos": [
        {"id": 2, "category": "necklace", "image_url": "https://c/2.jpg", "caption": "B", "position": 2},
        {"id": 1, "category": "necklace", "image_url": "https://c/1.jpg", "caption": "A", "position": 1},
        {"id": 3, "category": "necklace", "image_url": "", "caption": "no-image", "position": 3},
    ]
}


class TestListInspirations:
    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_sorted_by_position_and_drops_imageless(self, mock_get):
        mock_get.return_value = _resp(200, PHOTOS)
        out = inspirations_client.list_inspirations(category="necklace")
        # id=3 dropped (no image_url); rest sorted by position 1,2
        assert [p["id"] for p in out] == [1, 2]

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_category_passed_as_param(self, mock_get):
        mock_get.return_value = _resp(200, {"photos": []})
        inspirations_client.list_inspirations(category="necklace")
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"category": "necklace"}
        assert kwargs["headers"]["X-API-Key"] == "tissu_rw_test"

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_no_category_means_no_params(self, mock_get):
        mock_get.return_value = _resp(200, {"photos": []})
        inspirations_client.list_inspirations()
        _, kwargs = mock_get.call_args
        assert kwargs["params"] is None

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_bare_list_payload_accepted(self, mock_get):
        mock_get.return_value = _resp(200, PHOTOS["photos"])
        out = inspirations_client.list_inspirations()
        assert [p["id"] for p in out] == [1, 2]

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_401_returns_empty(self, mock_get):
        mock_get.return_value = _resp(401, None, text='{"error":"unauthorized"}')
        assert inspirations_client.list_inspirations("necklace") == []

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_non_json_returns_empty(self, mock_get):
        mock_get.return_value = _resp(200, None, text="<html>oops</html>")
        assert inspirations_client.list_inspirations() == []

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_key_returns_empty(self):
        import os
        os.environ.pop("INSPIRATIONS_API_KEY", None)
        os.environ.pop("STOREFRONT_API_KEY", None)
        assert inspirations_client.list_inspirations("necklace") == []


class TestGetInspiration:
    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_found_by_id(self, mock_get):
        mock_get.return_value = _resp(200, PHOTOS)
        item = inspirations_client.get_inspiration(1, category="necklace")
        assert item is not None and item["id"] == 1

    @patch.dict("os.environ", KEY_ENV)
    @patch(f"{MODULE}.requests.get")
    def test_not_found_returns_none(self, mock_get):
        mock_get.return_value = _resp(200, PHOTOS)
        assert inspirations_client.get_inspiration(999) is None
