"""Unit tests for the necklace prompt builder."""

from __future__ import annotations

from ai_bag_agent.ai_content.config.necklace_prompt import build_necklace_prompt


class TestBuildNecklacePrompt:
    def test_contains_core_fidelity_terms(self):
        prompt = build_necklace_prompt()
        lowered = prompt.lower()
        for term in ("sacred", "fabric", "shell", "charm", "must not change"):
            assert term in lowered, f"missing fidelity term: {term}"

    def test_on_neck_note_added_only_when_ref_present(self):
        with_ref = build_necklace_prompt(has_neck_ref=True)
        without_ref = build_necklace_prompt(has_neck_ref=False)
        assert "ON-NECK SIZE REFERENCE" in with_ref
        assert "size/fit reference only" in with_ref.lower()
        assert "ON-NECK SIZE REFERENCE" not in without_ref

    def test_custom_prompt_is_appended(self):
        prompt = build_necklace_prompt(custom_prompt="outdoor golden hour")
        assert "ADDITIONAL INSTRUCTIONS:" in prompt
        assert "outdoor golden hour" in prompt

    def test_blank_custom_prompt_not_appended(self):
        prompt = build_necklace_prompt(custom_prompt="   ")
        assert "ADDITIONAL INSTRUCTIONS:" not in prompt

    def test_style_suffix_present(self):
        assert "jewelry photography" in build_necklace_prompt().lower()
