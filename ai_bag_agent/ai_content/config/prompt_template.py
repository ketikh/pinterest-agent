"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
TASK: Generate a commercial product photograph.

You are given TWO input images:
  • FIRST image = SCENE REFERENCE. Only its lighting, background mood,
    materials, and overall styling matter. IGNORE any bag, product,
    model, or accessory shown in this image — do not copy them.
  • SECOND image = THE BAG. This is the actual product to photograph.
    Keep it exactly as shown — same shape, same colour, same pattern,
    same fabric texture, same stitching, same label, same closure,
    same proportions, same orientation. The bag in the output must be
    the SECOND image, not the FIRST.

Output:
A single photorealistic photo of the SECOND image's bag, placed
naturally inside a new scene that takes its style cues from the FIRST
image. The bag appears ONCE — one solid silhouette, no transparency,
no ghosting, no duplicated copies, no blending with the reference's
bag. 1:1 square, sharp focus, no text or watermarks.
"""

GLOBAL_STYLE_SUFFIX = (
    "Commercial product photography. "
    "High-end fashion e-commerce. "
    "Professional studio lighting that matches the scene reference's mood."
)


def build_prompt(custom_prompt: str = "") -> str:
    """Combine global template with optional per-bag custom prompt."""
    parts = [GLOBAL_SYSTEM_PROMPT.strip()]
    if custom_prompt and custom_prompt.strip():
        parts.append(f"\nADDITIONAL NOTES:\n{custom_prompt.strip()}")
    parts.append(f"\n{GLOBAL_STYLE_SUFFIX}")
    return "\n".join(parts)
