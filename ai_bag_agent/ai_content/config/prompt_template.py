"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
TASK: Generate a commercial product photograph.

You are given TWO input images:
  • FIRST image = SCENE REFERENCE. Use only its lighting, background
    mood, materials, and overall styling. IGNORE any bag, product,
    model, or accessory shown in this image — do not copy them.
  • SECOND image = THE BAG. This is the actual product to photograph.
    The bag in the output must be the SECOND image, not the FIRST.

PRESERVE THE BAG EXACTLY:
  • SIZE: keep the bag's height, width, depth and proportions
    identical. Do NOT make it smaller, larger, taller, wider or
    thinner. The bag must fill the same share of the frame it does
    in the second input image (at least 60% of the canvas).
  • SHAPE & SILHOUETTE: identical outline. Do not redraw curves,
    corners, edges or contours.
  • HARDWARE: only the hardware visible in the second image. Do NOT
    add zippers, buckles, studs, chains, straps, handles, pockets,
    rivets, magnetic snaps or any other parts that are not in the
    second image. If the bag has no zipper, the output has no zipper.
  • CLOSURE: keep the original closure (flap, drawstring, fold-over,
    open-top, etc.) exactly as shown. Do not replace it with a zipper.
  • COLOUR, PATTERN, FABRIC, TEXTURE, STITCHING, LABEL POSITION:
    pixel-faithful to the second image.

OUTPUT:
A single photorealistic photo of the second image's bag, placed
naturally in a new scene styled after the first image. The bag
appears ONCE — one solid silhouette, no transparency, no ghosting,
no duplicated copies, no blending with the reference's bag.
1:1 square, sharp focus, no text or watermarks, no extra products.
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
