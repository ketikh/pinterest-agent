"""Unit tests for the Seedance video-prompt builder."""

from __future__ import annotations

from ai_bag_agent.ai_content.config.video_prompt import (
    _BAG_STYLES,
    BAG_VIDEO_SUFFIX,
    VIDEO_STYLES,
    VIDEO_SUFFIX,
    build_bag_video_prompt,
    build_video_prompt,
    build_video_prompt_for,
)


class TestBuildVideoPrompt:
    def test_returns_valid_style_key(self):
        out = build_video_prompt()
        assert out["style"] in VIDEO_STYLES

    def test_always_ends_with_mandatory_suffix(self):
        for key in VIDEO_STYLES:
            for worn in (True, False):
                out = build_video_prompt(style=key, worn=worn)
                assert out["prompt"].endswith(VIDEO_SUFFIX)

    def test_prompt_length_bounded(self):
        # Kept reasonably short for the video model (relaxed from the original
        # 60 as fidelity rules — eyes-open, no-extras, loop — were added).
        for key in VIDEO_STYLES:
            for worn in (True, False):
                out = build_video_prompt(style=key, worn=worn)
                words = out["prompt"].split()
                assert len(words) <= 85, f"{key}/{worn} had {len(words)} words"

    def test_keeps_eyes_open(self):
        out = build_video_prompt(style="A", worn=True)["prompt"]
        assert "eyes open" in out

    def test_never_repeats_previous_style(self):
        for prev in VIDEO_STYLES:
            for _ in range(30):
                out = build_video_prompt(previous_style=prev)
                assert out["style"] != prev

    def test_worn_vs_flatlay_motion_differs(self):
        worn = build_video_prompt(style="A", worn=True)["prompt"]
        flat = build_video_prompt(style="A", worn=False)["prompt"]
        assert "micro-motion" in worn
        assert "micro-motion" not in flat
        assert "soft shadows" in flat

    def test_single_line(self):
        out = build_video_prompt(style="C")
        assert "\n" not in out["prompt"]

    def test_explicit_style_is_used(self):
        assert build_video_prompt(style="D")["style"] == "D"

    def test_necklace_catches_light(self):
        assert "shimmer" in build_video_prompt(style="B")["prompt"]

    def test_prompt_is_loop_friendly(self):
        for key in VIDEO_STYLES:
            assert "seamless loop" in build_video_prompt(style=key)["prompt"]


class TestBuildBagVideoPrompt:
    def test_ends_with_bag_suffix(self):
        for key in _BAG_STYLES:
            assert build_bag_video_prompt(style=key)["prompt"].endswith(BAG_VIDEO_SUFFIX)

    def test_protects_pattern_and_label(self):
        p = build_bag_video_prompt(style="p")["prompt"]
        assert "TISSU label" in p and "fabric pattern" in p

    def test_no_logo_zoom_or_flicker(self):
        p = build_bag_video_prompt(style="p")["prompt"]
        assert "no zoom" in p and "no flicker" in p

    def test_max_60_words(self):
        for key in _BAG_STYLES:
            words = build_bag_video_prompt(style=key)["prompt"].split()
            assert len(words) <= 60, f"{key} had {len(words)} words"

    def test_never_repeats_previous_style(self):
        for prev in _BAG_STYLES:
            for _ in range(20):
                assert build_bag_video_prompt(previous_style=prev)["style"] != prev


class TestDispatcher:
    def test_bag_routes_to_bag_builder(self):
        out = build_video_prompt_for("bag", style="A")
        assert out["prompt"].endswith(BAG_VIDEO_SUFFIX)

    def test_necklace_routes_to_necklace_builder(self):
        out = build_video_prompt_for("necklace", style="A")
        assert out["prompt"].endswith(VIDEO_SUFFIX)
        assert "seamless loop" in out["prompt"]

    def test_totebag_routes_to_bag_builder(self):
        out = build_video_prompt_for("totebag", style="p")
        assert out["prompt"].endswith(BAG_VIDEO_SUFFIX)
