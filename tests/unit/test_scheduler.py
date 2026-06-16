"""Unit tests for scheduler time parsing (regression for the '22:00' crash)."""

from __future__ import annotations

import os
from unittest.mock import patch

from ai_bag_agent.ai_content.services.scheduler import _parse_time


class TestParseTime:
    def test_hh_mm_string_in_hour_var(self):
        # Regression: operator set NECKLACE_POST_HOUR="22:00" → int() crashed
        # the whole scheduler. Now it parses to (22, 0).
        with patch.dict("os.environ", {"NK_HOUR": "22:00"}):
            assert _parse_time("NK_HOUR", "NK_MIN", 9, 0) == (22, 0)

    def test_hh_mm_with_minutes(self):
        with patch.dict("os.environ", {"NK_HOUR": "22:30"}):
            assert _parse_time("NK_HOUR", "NK_MIN", 9, 0) == (22, 30)

    def test_bare_hour_and_minute(self):
        with patch.dict("os.environ", {"NK_HOUR": "20", "NK_MIN": "15"}):
            assert _parse_time("NK_HOUR", "NK_MIN", 9, 0) == (20, 15)

    def test_invalid_falls_back_to_default(self):
        with patch.dict("os.environ", {"NK_HOUR": "abc"}):
            assert _parse_time("NK_HOUR", "NK_MIN", 9, 5) == (9, 5)

    def test_missing_uses_default(self):
        os.environ.pop("ZZ_HOUR", None)
        os.environ.pop("ZZ_MIN", None)
        assert _parse_time("ZZ_HOUR", "ZZ_MIN", 12, 0) == (12, 0)
