"""Unit tests for pinterest_pin_image (all HTTP calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from ai_bag_agent.ai_content.services import pinterest_pin_image as ppi

MOD = "ai_bag_agent.ai_content.services.pinterest_pin_image"
OG_URL = "https://i.pinimg.com/736x/47/24/b0/4724b0edea86be9bcb47762592512b82.jpg"


def _resp(status: int = 200, text: str = "", json_body=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_body
    return r


class TestParseOgImage:
    def test_content_before_property(self):
        html = f'<meta content="{OG_URL}" data-app="true" property="og:image"/>'
        assert ppi.parse_og_image(html) == OG_URL

    def test_property_before_content(self):
        html = f'<meta property="og:image" content="{OG_URL}">'
        assert ppi.parse_og_image(html) == OG_URL

    def test_ignores_non_pinimg_and_empty(self):
        assert ppi.parse_og_image('<meta property="og:image" content="https://x.com/a.jpg">') is None
        assert ppi.parse_og_image("") is None
        assert ppi.parse_og_image(None) is None


class TestFetchPinPageImage:
    @patch(f"{MOD}.requests.get")
    def test_returns_og_image(self, mock_get):
        mock_get.return_value = _resp(200, f'<meta property="og:image" content="{OG_URL}">')
        assert ppi.fetch_pin_page_image("123") == OG_URL
        assert mock_get.call_args.args[0] == "https://www.pinterest.com/pin/123/"

    @patch(f"{MOD}.requests.get")
    def test_non_200_returns_none(self, mock_get):
        mock_get.return_value = _resp(404, "nope")
        assert ppi.fetch_pin_page_image("123") is None

    @patch(f"{MOD}.requests.get", side_effect=requests.ConnectionError("down"))
    def test_network_error_returns_none(self, _mock_get):
        assert ppi.fetch_pin_page_image("123") is None


class TestGetPinDetail:
    @patch(f"{MOD}.pc._get_token", return_value="tok")
    @patch(f"{MOD}.requests.get")
    def test_returns_pin_dict(self, mock_get, _tok):
        mock_get.return_value = _resp(200, json_body={"id": "1", "media": {}})
        assert ppi.get_pin_detail("1") == {"id": "1", "media": {}}

    @patch(f"{MOD}.pc._get_token", return_value="tok")
    @patch(f"{MOD}.requests.get")
    def test_non_200_returns_none(self, mock_get, _tok):
        mock_get.return_value = _resp(404, json_body={"message": "not found"})
        assert ppi.get_pin_detail("1") is None

    @patch(f"{MOD}.pc._get_token", return_value=None)
    def test_no_token_returns_none(self, _tok):
        assert ppi.get_pin_detail("1") is None


class TestResolvePinImageFallback:
    @patch(f"{MOD}.fetch_pin_page_image")
    @patch(f"{MOD}.get_pin_detail")
    def test_detail_with_image_wins(self, mock_detail, mock_page):
        mock_detail.return_value = {"media": {"images": {"1200x": {"url": OG_URL}}}}
        assert ppi.resolve_pin_image_fallback("1") == (OG_URL, "pin-detail")
        mock_page.assert_not_called()

    @patch(f"{MOD}.fetch_pin_page_image", return_value=OG_URL)
    @patch(f"{MOD}.get_pin_detail", return_value={"media": {"images": {}}})
    def test_bare_detail_falls_through_to_page(self, _detail, _page):
        assert ppi.resolve_pin_image_fallback("1") == (OG_URL, "pin-page")

    @patch(f"{MOD}.fetch_pin_page_image", return_value=None)
    @patch(f"{MOD}.get_pin_detail", return_value=None)
    def test_nothing_found(self, _detail, _page):
        assert ppi.resolve_pin_image_fallback("1") == (None, None)


class TestBoardImageDiagnostics:
    @patch(f"{MOD}.resolve_pin_image_fallback", return_value=(OG_URL, "pin-page"))
    def test_counts_sample_and_probe(self, mock_resolve):
        pins = [
            {"id": "a", "is_owner": True, "media": {"media_type": "image",
             "images": {"600x": {"url": OG_URL}}}},
            {"id": "b", "is_owner": False, "parent_pin_id": "9",
             "media": {"media_type": "image", "images": {}}},
        ]
        out = ppi.board_image_diagnostics(pins)
        assert out["usable_in_listing"] == 1 and out["bare"] == 1
        assert out["sample"][1] == {
            "id": "b", "is_owner": False, "has_parent": True,
            "media_type": "image", "media_keys": ["images", "media_type"],
            "image_sizes": [],
        }
        assert out["fallback_test"] == {"pin_id": "b", "resolved": True, "via": "pin-page"}
        mock_resolve.assert_called_once_with("b")

    def test_probe_can_be_skipped(self):
        pins = [{"id": "b", "media": {"images": {}}}]
        out = ppi.board_image_diagnostics(pins, test_fallback=False)
        assert "fallback_test" not in out
