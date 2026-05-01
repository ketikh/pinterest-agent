"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
You are a commercial product photographer. Your task is to create a professional \
advertising photo of the bag shown in the PRIMARY image.

RULES:
1. PRIMARY IMAGE (first): the exact bag/product being sold.
   - Preserve 100%: shape, color, brand details, hardware, stitching
   - Do NOT alter, resize, distort or replace the product in any way
2. REFERENCE IMAGE (second): photography style guide only.
   - Copy the lighting, background mood, staging, and composition
   - Do NOT copy any products, models, or items from the reference

OUTPUT REQUIREMENTS:
- Photorealistic, commercial studio-quality photograph
- Sharp focus on product details
- No text, no watermarks, no logos (except those on the bag itself)
- Clean, professional composition suitable for Instagram feed (1:1)
"""

GLOBAL_STYLE_SUFFIX = (
    "Commercial product photography. "
    "High-end fashion e-commerce. "
    "Clean white or neutral background unless reference suggests otherwise. "
    "Professional studio lighting."
)


def build_prompt(custom_prompt: str = "") -> str:
    """Combine global template with optional per-bag custom prompt."""
    parts = [GLOBAL_SYSTEM_PROMPT.strip()]
    if custom_prompt and custom_prompt.strip():
        parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{custom_prompt.strip()}")
    parts.append(f"\n{GLOBAL_STYLE_SUFFIX}")
    return "\n".join(parts)
