"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
You are a commercial product photographer. Your task is to create a professional \
advertising photo of the bag shown in the PRIMARY image.

THE BAG IS SACRED — IT MUST NOT CHANGE.
The output bag must be a pixel-faithful copy of the input bag. The SHAPE,
SILHOUETTE, OUTLINE, and CONTOUR are immutable. The SIZE inside the frame
must not shrink. If you change the bag in any way, the output is wrong.

RULES:
1. PRIMARY IMAGE (first): the exact bag/product being sold.
   - SHAPE & SILHOUETTE: identical — do not redraw, restyle, or "fix" any
     curve, edge, corner, or contour. The outline must match the input.
   - SIZE IN FRAME: the bag must occupy AT LEAST as much of the canvas as
     it did in the input. Never shrink it. Never push it to the background.
   - ORIENTATION: portrait bags stay portrait (taller than wide), landscape
     bags stay landscape (wider than tall), square stays square. Never
     rotate, flip, or change a portrait bag into a square or horizontal one.
   - PROPORTIONS: keep height, width, depth and aspect ratio exactly.
   - PATTERN: preserve any print, stripe, check, embroidery, or weave
     pattern EXACTLY — same colors, same direction (vertical stripes stay
     vertical, horizontal stay horizontal), same density and spacing.
   - TEXTURE: preserve quilted channels, padded sections, woven texture,
     embossing, perforations, pebbling, or smooth surfaces exactly as
     visible in the input.
   - CLOSURE: preserve the closure type and shape — top flap (note its
     rounded vs sharp corners), zipper, magnetic snap, drawstring, buckle —
     and its exact position.
   - LABEL & LOGO POSITION: any brand label (e.g. TISSU), tag, or logo
     stays in the SAME spot on the bag, same size, same orientation.
   - Preserve 100%: color, brand details, hardware, stitching, straps,
     buckles, zippers, seams, stitching pattern.
   - Do NOT crop, stretch, squash, scale down, rotate, mirror, or distort.
   - Do NOT add, remove, or modify any part of the bag (no extra straps,
     handles, pockets, hardware, decorations, or accessories).
   - The bag is the HERO of the photo — center it, keep it prominent,
     give it the same visual weight it has in the input.
2. REFERENCE IMAGE (second): photography style guide ONLY.
   - LIGHTING IS THE PRIMARY MATCH: copy the reference's lighting direction,
     color temperature, intensity, shadow softness, and highlights — and
     APPLY THAT SAME LIGHTING TO THE BAG. The bag must look like it was
     photographed in the reference's lighting environment.
   - Copy the background mood, staging, and composition as well.
   - Do NOT copy any products, models, bags, or items from the reference.
   - Do NOT let the reference's bag size/shape influence the primary bag.
   - The reference is inspiration for the SCENE and LIGHT, not the SUBJECT.

OUTPUT REQUIREMENTS:
- Photorealistic, commercial studio-quality photograph
- Sharp focus on product details
- No text, no watermarks, no logos (except those on the bag itself)
- Clean, professional composition suitable for Instagram feed (1:1)
- The bag should fill a significant portion of the frame (60% or more)
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
