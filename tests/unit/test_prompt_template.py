"""Unit tests for the bag prompt template (shared by bags and totebags)."""

from __future__ import annotations

from ai_bag_agent.ai_content.config.prompt_template import (
    GLOBAL_STYLE_SUFFIX,
    OPEN_BAG_REFERENCE_NOTE,
    build_prompt,
)


class TestBuildPrompt:
    def test_locks_handles_shapes_and_proportions(self):
        prompt = build_prompt()
        assert "HANDLES & STRAPS — EXACT LENGTH, LOCKED" in prompt
        assert "NEVER lengthen or shorten a handle" in prompt
        assert "NO NEW SHAPES OR ELEMENTS" in prompt
        assert "PROPORTIONS: keep height, width, depth and aspect ratio exactly" in prompt
        assert "FINAL CHECK BEFORE OUTPUT" in prompt

    def test_custom_prompt_appended_before_style_suffix(self):
        prompt = build_prompt("show it on a marble table")
        assert "ADDITIONAL INSTRUCTIONS:\nshow it on a marble table" in prompt
        assert prompt.index("ADDITIONAL INSTRUCTIONS") < prompt.index(GLOBAL_STYLE_SUFFIX)

    def test_blank_custom_prompt_is_ignored(self):
        assert "ADDITIONAL INSTRUCTIONS" not in build_prompt("   ")

    def test_open_bag_note_only_when_requested(self):
        note = OPEN_BAG_REFERENCE_NOTE.strip()
        assert note in build_prompt(has_open_bag=True)
        assert note not in build_prompt(has_open_bag=False)
