"""Unit tests for the Seedance video-prompt builder."""

from __future__ import annotations

from ai_bag_agent.ai_content.config.video_prompt import (
    VIDEO_STYLES,
    VIDEO_SUFFIX,
    build_video_prompt,
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
