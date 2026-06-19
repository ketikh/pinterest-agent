"""Prompt template for necklace (scarf-necklace) generation on kie.ai.

Product type: scarf-necklaces — a printed fabric band worn as a choker, with
sewn-on shells (cowrie) and small metal charms (e.g. a silver bow, teardrop
pendant). The product is SACRED and must be reproduced pixel-faithfully.

Approach: take the REFERENCE photo's scene (pose, model, lighting, background),
ERASE any necklace present in it, and place ONLY the user's product necklace,
worn the same single-wrap way and at the same real-world size as the product.

Image slots (same order kie.ai receives them — see ai_generator._submit_task):
    [0] PRODUCT   — the exact scarf-necklace being sold (ground truth).
    [1] REFERENCE — Pinterest "jewelry" pin: keep its scene, erase its necklace,
                    insert the product necklace.
    [2] ON-NECK   — (optional) photo showing the real SIZE/scale + single-wrap fit.
"""

NECKLACE_SYSTEM_PROMPT = """\
You are a commercial jewelry photographer. Create ONE photorealistic image of \
the EXACT scarf-necklace from the PRODUCT image, placed into the scene of the \
REFERENCE image.

IMAGE ROLES:
- IMAGE 1 (PRODUCT, first): the exact scarf-necklace being sold — the ONLY
  source of the necklace's design, size, and how it is worn. Reproduce it
  pixel-faithfully.
- IMAGE 2 (REFERENCE, second): use ONLY its scene — pose, model, framing, hair,
  skin, clothing, background, and lighting. Do NOT copy how any necklace is
  worn in it.

ERASE THE REFERENCE'S NECKLACE COMPLETELY:
- If the person in IMAGE 2 is wearing ANY necklace, choker, pendant, beads, or
  cord, REMOVE it entirely — it must not appear anywhere in the output.
- If any necklace or jewelry is lying in the scene of IMAGE 2, remove it too.
- Then place the PRODUCT necklace from IMAGE 1 on the neck.
- The only necklace in the final image is the IMAGE 1 necklace. NEVER keep,
  copy, or blend the IMAGE 2 necklace or any of its parts.

THE NECKLACE IS SACRED — IT MUST NOT CHANGE.
Reproduce the IMAGE 1 necklace exactly:
- WRAP, LAYERS & CLOSURE — IT IS A NECKLACE, NOT A SCARF: the fabric band goes
  around the neck exactly ONCE as a single, smooth, narrow choker band, worn as
  jewelry. The closure is plain and hidden at the BACK of the neck — NEVER at the
  front and NEVER on the side. Do NOT tie a decorative bow, do NOT make a
  scarf-style knot, and do NOT show draped or dangling scarf ends anywhere. The
  front shows only the smooth band with its charms. Do NOT double it, stack it,
  coil it twice, or show two loops. Ignore how any necklace in the REFERENCE
  (IMAGE 2) was worn.
- PROPORTIONS & SIZE: keep the true real-world size. The band is relatively thin
  and the shells/charms are small and delicate — do NOT enlarge or thicken them.
  Match the proportions in the product / size-reference images; the necklace must
  not look chunky, oversized, or bulky on the neck.
- FABRIC: same print, pattern, colors, motif scale and direction, texture and
  sheen; same width, length, folds, and the way it is tied.
- SHELLS: every shell (e.g. cowrie) — same count, color and natural markings,
  shape, size, and position along the band.
- CHARMS — EXACT COUNT, ORDER & PLACEMENT: reproduce ONLY the charms visible in
  IMAGE 1 — the same NUMBER (count them carefully), the same left-to-right order
  and positions along the band, the same shapes, sizes, and metal/enamel colors.
- CHARM SPACING: spread the charms EVENLY along the band, spaced apart exactly
  as in IMAGE 1. Each charm hangs from its OWN separate point — NEVER cluster,
  group, or hang two charms from the same spot. A typical necklace has 3 charms
  spaced across the front (sometimes 1, rarely 4) — match IMAGE 1's count and
  spacing precisely.
- Do NOT duplicate any charm (e.g. do not add a second shell), do NOT add a
  charm or shell hanging in the center unless IMAGE 1 shows one there, and do
  NOT move a charm to a different spot.
- Do NOT invent or add any charm. Do NOT add flowers, daisies, beads, or
  pendants that are not in IMAGE 1. Do NOT substitute one charm for another.

OUTPUT REQUIREMENTS:
- Photorealistic, commercial e-commerce quality, square 1:1 composition.
- The necklace is the hero and is sharp: fabric print, shells, and charms crisp.
- Match the reference's lighting and mood. No text, no watermarks, no logos.
"""

ON_NECK_REFERENCE_NOTE = """\
ADDITIONAL CONTEXT — IMAGE 3 (ON-NECK SIZE REFERENCE):
The third image shows the same product worn on a neck — THIS is exactly how the
necklace must be worn. Match it precisely: the real-world SIZE and scale, the
SINGLE-WRAP fit (one loop around the neck, fastened/tied at the BACK, never
doubled), and how tightly it sits (choker length). The band width and charm
sizes in the output must match what is shown here; do not make them bigger. Do
NOT copy this image's model, face, skin, hair, clothing, or background. It is a
size/fit reference only.
"""

NECKLACE_STYLE_SUFFIX = (
    "Commercial jewelry photography. High-end fashion e-commerce. "
    "Soft, flattering lighting that matches the reference. "
    "Keep the reference's background unless it hides the necklace."
)


def build_necklace_prompt(custom_prompt: str = "", has_neck_ref: bool = False) -> str:
    """Combine the necklace template with an optional per-item custom prompt.

    When `has_neck_ref` is True we append the on-neck note so kie.ai treats the
    third image as a size/fit reference and never copies the model/background.
    """
    parts = [NECKLACE_SYSTEM_PROMPT.strip()]
    if has_neck_ref:
        parts.append(f"\n{ON_NECK_REFERENCE_NOTE.strip()}")
    if custom_prompt and custom_prompt.strip():
        parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{custom_prompt.strip()}")
    parts.append(f"\n{NECKLACE_STYLE_SUFFIX}")
    return "\n".join(parts)
