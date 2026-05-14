"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
TASK: Photograph the exact bag from Image 1 placed inside a scene that
matches the lighting, mood and styling of Image 2.

IMAGE 1 — THE BAG (subject):
Use this bag exactly as shown. Keep its shape, colour, pattern, fabric
texture, stitching, label, closure and proportions identical to the
input. Do not redraw, redesign, recolour, resize, rotate, flip,
duplicate, ghost, or overlay the bag. The bag appears ONCE in the
output, with one solid clean silhouette — no transparency, no double
exposure, no blended copies.

IMAGE 2 — THE SCENE (reference for style only):
Take the lighting direction, colour temperature, shadow softness,
background materials, and overall mood from this image. Build a new
scene around the bag using that look. Do not copy the bag, model, or
product from this image.

OUTPUT:
A single, photorealistic product photograph. The bag from Image 1
sits naturally in the scene inspired by Image 2 — like a real
commercial shoot. 1:1 square, sharp focus, clean composition, no
text or watermarks, no extra products.
"""

GLOBAL_STYLE_SUFFIX = (
    "Commercial product photography. "
    "High-end fashion e-commerce. "
    "Professional studio lighting that matches the reference's mood."
)


def build_prompt(custom_prompt: str = "") -> str:
    """Combine global template with optional per-bag custom prompt."""
    parts = [GLOBAL_SYSTEM_PROMPT.strip()]
    if custom_prompt and custom_prompt.strip():
        parts.append(f"\nADDITIONAL NOTES:\n{custom_prompt.strip()}")
    parts.append(f"\n{GLOBAL_STYLE_SUFFIX}")
    return "\n".join(parts)
