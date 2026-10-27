"""Unit tests for bag_metrics (synthetic images, HTTP mocked)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import requests

from ai_bag_agent.ai_content.services import bag_metrics as bm

pytest.importorskip("PIL")  # Pillow is a prod dependency; the local venv may lack it


def _png(size=(200, 200), rect=None, bg=(255, 255, 255), fg=(40, 30, 20)) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, bg)
    if rect:
        ImageDraw.Draw(img).rectangle(rect, fill=fg)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestGeometryFromBytes:
    def test_portrait_bag_on_white(self):
        g = bm.geometry_from_bytes(_png(rect=(70, 20, 129, 179)))  # 60 x 160
        assert g["orientation"] == "portrait"
        assert abs(g["ratio"] - 0.38) < 0.02

    def test_landscape_bag_on_grey(self):
        g = bm.geometry_from_bytes(_png(rect=(20, 70, 179, 129), bg=(230, 230, 230)))
        assert g["orientation"] == "landscape"
        assert abs(g["ratio"] - 2.67) < 0.05

    def test_square_bag(self):
        g = bm.geometry_from_bytes(_png(rect=(50, 50, 149, 149)))
        assert g["orientation"] == "square" and g["ratio"] == 1.0

    def test_blank_image_returns_none(self):
        assert bm.geometry_from_bytes(_png()) is None

    def test_large_image_is_downscaled_but_ratio_kept(self):
        g = bm.geometry_from_bytes(_png(size=(2000, 2000), rect=(500, 200, 1499, 1799)))
        assert g["orientation"] == "portrait"
        assert abs(g["ratio"] - 0.62) < 0.02


class TestMeasureBagGeometry:
    @patch("ai_bag_agent.ai_content.services.bag_metrics.requests.get")
    def test_downloads_and_measures(self, mock_get):
        resp = MagicMock(status_code=200, content=_png(rect=(70, 20, 129, 179)))
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        g = bm.measure_bag_geometry("https://res.cloudinary.com/x/bag.jpg")
        assert g["orientation"] == "portrait"

    @patch("ai_bag_agent.ai_content.services.bag_metrics.requests.get",
           side_effect=requests.ConnectionError("down"))
    def test_network_error_returns_none(self, _get):
        assert bm.measure_bag_geometry("https://x/y.jpg") is None

    @patch("ai_bag_agent.ai_content.services.bag_metrics.requests.get")
    def test_garbage_bytes_return_none(self, mock_get):
        resp = MagicMock(status_code=200, content=b"not an image")
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        assert bm.measure_bag_geometry("https://x/y.jpg") is None


class TestDescribeGeometry:
    def test_portrait_text(self):
        text = bm.describe_geometry({"ratio": 0.72, "orientation": "portrait",
                                     "box_w": 72, "box_h": 100})
        assert "0.72 : 1.00" in text and "portrait" in text and "39% taller" in text

    def test_landscape_text(self):
        text = bm.describe_geometry({"ratio": 1.5, "orientation": "landscape",
                                     "box_w": 150, "box_h": 100})
        assert "50% wider" in text

    def test_none_is_empty(self):
        assert bm.describe_geometry(None) == ""
