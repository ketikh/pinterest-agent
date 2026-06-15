"""Global prompt template for kie.ai Nano Banana Pro image generation."""

GLOBAL_SYSTEM_PROMPT = """\
You are a commercial product photographer. Your task is to create a professional \
advertising photo of the bag shown in the PRIMARY image.

THE BAG IS SACRED — IT MUST NOT CHANGE.
The output bag must be a pixel-faithful copy of the input bag. The SHAPE,
SILHOUETTE, OUTLINE, CONTOUR, WIDTH, HEIGHT, DEPTH, and aspect ratio are
ALL immutable. If the reference photo shows a wider/narrower/taller/
shorter bag, IGNORE the reference's bag entirely — its dimensions must
NOT bleed into the primary bag. If you change the bag in any way, the
output is wrong.

RULES:
1. PRIMARY IMAGE (first): the exact bag/product being sold.
   - SHAPE & SILHOUETTE: identical — do not redraw, restyle, or "fix" any
     curve, edge, corner, or contour. The outline must match the input.
   - SIZE IN FRAME: the bag must occupy AT LEAST as much of the canvas as
     it did in the input (60% or more). Never shrink it. Never push it to
     the background. Never make it smaller, taller, wider, or thinner.
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
   - CLOSURE: preserve the closure type and shape EXACTLY — top flap (note
     its rounded vs sharp corners), zipper, magnetic snap, drawstring,
     buckle, fold-over, open-top — and its exact position. DO NOT replace
     the original closure with a different one. If the bag has a flap, the
     output has a flap (not a zipper). If the bag is open-top, the output
     stays open-top.
   - HARDWARE: only the hardware visible in the PRIMARY image. DO NOT add
     zippers, buckles, studs, chains, straps, handles, pockets, rivets,
     magnetic snaps, D-rings, eyelets, or any other part that is not in
     the PRIMARY image. If the bag has no zipper, the output has no zipper.
   - LABEL & LOGO POSITION: any brand label (e.g. TISSU), tag, or logo
     stays in the SAME spot on the bag, same size, same orientation.
   - Preserve 100%: color, brand details, stitching, straps, seams, and
     stitching pattern.
   - Do NOT crop, stretch, squash, scale down, rotate, mirror, or distort.
   - Do NOT add, remove, or modify any part of the bag (no extra straps,
     handles, pockets, hardware, decorations, or accessories).
   - The bag is the HERO of the photo — center it, keep it prominent,
     give it the same visual weight it has in the input.

2. REFERENCE IMAGE (second): photography style guide ONLY — never a shape source.
   - LIGHTING IS THE PRIMARY MATCH: copy the reference's lighting direction,
     color temperature, intensity, shadow softness, and highlights — and
     APPLY THAT SAME LIGHTING TO THE BAG. The bag must look like it was
     photographed in the reference's lighting environment.
   - Copy the background mood, staging, and composition as well.
   - Do NOT copy any products, models, bags, or items from the reference.
   - The reference is inspiration for the SCENE and LIGHT, not the SUBJECT.

   *** ANTI-DIMENSION-BLEEDING — READ TWICE ***
   The reference photo may contain a bag that is WIDER, TALLER, FATTER,
   SLIMMER, BOXIER, or otherwise SHAPED DIFFERENTLY than the PRIMARY bag.
   This is IRRELEVANT and FORBIDDEN as a source of dimensions. Common
   failure mode: the model sees a wide bag in the reference and silently
   widens the primary bag to "harmonise" with the scene. THIS IS WRONG.
   - Width: the PRIMARY bag's width-to-height ratio is LOCKED. If the
     primary is portrait (taller than wide), the output STAYS portrait
     by the exact same ratio, even if the reference shows a wide tote.
   - Height: same rule — primary's height is locked.
   - Depth (front-back thickness): same rule — flat clutches stay flat,
     boxy bags stay boxy. Do not puff or flatten to match the reference.
   - Volume: don't add roundness, sag, or stuffing inferred from the
     reference. Keep the primary bag's actual fullness.
   - Aspect ratio of the bag's bounding box must match the primary image
     within 5%. If it doesn't, the output is wrong — redo it.
   - The reference's bag shape, width, height, and proportions DO NOT
     EXIST for the purposes of rendering the primary bag.

3. SINGLE-BAG RULE (anti-overlay / anti-ghosting):
   - The output contains the PRIMARY bag exactly ONCE — one solid silhouette.
   - NO transparency on the bag, NO ghosting, NO duplicate copies, NO
     blending with the reference's bag, NO double-exposure effects.
   - If the reference image contains any bag/product, IGNORE it completely.
   - Treat the reference bag as if it weren't there at all when choosing
     the primary bag's shape and dimensions.

OUTPUT REQUIREMENTS:
- Photorealistic, commercial studio-quality photograph
- Sharp focus on product details
- No text, no watermarks, no logos (except those on the bag itself)
- Clean, professional composition suitable for Instagram feed (1:1)
- The bag fills at least 60% of the canvas
"""

GLOBAL_STYLE_SUFFIX = (
    "Commercial product photography. "
    "High-end fashion e-commerce. "
    "Clean white or neutral background unless reference suggests otherwise. "
    "Professional studio lighting that matches the reference's mood."
)


OPEN_BAG_REFERENCE_NOTE = """\
ADDITIONAL CONTEXT — THIRD IMAGE (OPEN VIEW):
The third input image shows the SAME bag photographed open. Use it ONLY as
a shape/interior reference so you understand the bag's true depth, lining,
and proportions. DO NOT include the open view in the output — the output
must show the bag in the EXACT closed/posed state of the PRIMARY (first)
image. The open photo is for your understanding only, never for rendering.
"""


def build_prompt(custom_prompt: str = "", has_open_bag: bool = False) -> str:
    """Combine global template with optional per-bag custom prompt.

    When `has_open_bag` is True we append a note explaining the third image
    so kie.ai treats it as reference-only and doesn't try to merge an open
    bag into the final shot.
    """
    parts = [GLOBAL_SYSTEM_PROMPT.strip()]
    if has_open_bag:
        parts.append(f"\n{OPEN_BAG_REFERENCE_NOTE.strip()}")
    if custom_prompt and custom_prompt.strip():
        parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{custom_prompt.strip()}")
    parts.append(f"\n{GLOBAL_STYLE_SUFFIX}")
    return "\n".join(parts)
