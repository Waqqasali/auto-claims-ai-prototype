"""Live vision provider (Anthropic).

Set VLM_PROVIDER=anthropic and ANTHROPIC_API_KEY to use this.

Note what is and is not model-dependent here. The model produces damage line
items, reasoning and per-item confidence. It does NOT decide routing, compute
the claim confidence score, apply the ADAS penalty or set thresholds. Those
are deterministic and live outside this file, so a model swap cannot change
the system's safety behavior.
"""

import base64
import json
import mimetypes
import os

from config import ANTHROPIC_MODEL
from pipeline.models import ClaimContext, Photo
from providers.vlm_base import VLMProvider

_MAX_IMAGES = 8          # keep payloads sane
_MAX_EDGE = 1568         # Anthropic downsizes above this anyway


def _encode(path: str) -> dict | None:
    """Base64-encode an image, downscaling first to keep the request small."""
    media_type, _ = mimetypes.guess_type(path)
    if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        media_type = "image/jpeg"

    try:
        from PIL import Image
        import io

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((_MAX_EDGE, _MAX_EDGE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            raw = buf.getvalue()
        media_type = "image/jpeg"
    except Exception:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return None

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(raw).decode("ascii"),
        },
    }


_COVERAGE_PROMPT = """You are checking whether a policyholder's photographs of a
DAMAGED AREA are enough to write the repair estimate for that area. You are
NOT estimating damage yet, and you are NOT inspecting the whole vehicle.

Vehicle: {vehicle}

What the policyholder reported: {report}

This report sets the scope. Judge the photos against the damage it describes.
Ask about another area only if the photos themselves show damage extending
beyond what was reported.

Valid panel names (use these exactly, no others, in panels_visible only):
{panels}

The standard. Photos are sufficient when, together, they show:
  - the whole damaged area, and where it sits on the vehicle, and
  - the damage clearly enough to judge its type and severity.
A wide shot plus one or two sharp close-ups usually meets it. Undamaged parts
of the vehicle do not need photographs.

Decide:
1. Which panels are clearly visible and assessable.
2. Which additional photographs are NECESSARY. List a photo only if, without
   it, you could not write the line items for the damage you can see. If the
   photos already allow that, return an empty list, even if more views would
   be nice to have. Never ask for photos to confirm there is no other damage.
   Ask for at most three, most important first. Write each one as a plain
   instruction a policyholder can follow on a phone: what to photograph, from
   where, and in what light. Do not use the panel names above in these
   instructions; say "the front bumper", not "front_bumper".
3. Whether any condition makes resubmission pointless. Use one of:
   wrong_vehicle, occluded_by_object, no_light_available, vehicle_not_present,
   or an empty string if none apply.
4. A coverage score from 0 to 1 for the damaged area only.

Return ONLY valid JSON:
{{"panels_visible": [...], "missing": [...], "unfixable": "", "coverage_score": 0.0, "notes": ""}}"""


_DAMAGE_PROMPT = """You are writing the line items for a vehicle repair estimate from
photographs. Be conservative: only include operations you can justify from
what is actually visible.

Vehicle: {vehicle}

What the policyholder reported: {report}
Use it to know where to look. Estimate only what the photographs show; a
report is not evidence of damage.

Valid panel names (use these exactly, no others):
{panels}

Valid operations: replace, repair, refinish, blend, R&I

For each line item give:
  operation, part, panel, damage_type, severity (light|moderate|heavy),
  reasoning (why this operation, from what is visible),
  confidence (0-1, your honest confidence in THIS line specifically)

Rules:
- You cannot see behind panels. Do not infer structural damage you cannot see.
- If a part must be removed and refitted to service another repair, use R&I.
- Lower your confidence on any item where the photo angle is unhelpful.
- Do NOT include sensor calibration operations. Whether calibration is required
  cannot be established from a photograph and is handled elsewhere.

Return ONLY valid JSON:
{{"line_items": [...], "damage_panels": [...], "notes": ""}}"""


class AnthropicVLM(VLMProvider):
    name = "anthropic"
    is_live = True

    def __init__(self):
        from anthropic import Anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Either export it, or run with "
                "VLM_PROVIDER=mock (the default) which needs no key."
            )
        # Keys issued to a person in the Claude Console can reach more than one
        # workspace, and the API then requires the workspace to be named on
        # every request. Keys limited to a single workspace need nothing. The
        # optional setting covers both without the user editing code.
        workspace = (os.environ.get("ANTHROPIC_WORKSPACE_ID") or "").strip()
        self.client = Anthropic(
            default_headers={"anthropic-workspace-id": workspace} if workspace else None
        )

    # -- internals ---------------------------------------------------------

    def _call(self, prompt: str, photos: list[Photo]) -> dict:
        blocks: list[dict] = []
        for p in photos[:_MAX_IMAGES]:
            enc = _encode(p.path)
            if enc:
                blocks.append(enc)
        blocks.append({"type": "text", "text": prompt})

        resp = self.client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": blocks}],
        )

        text = "".join(b.text for b in resp.content if b.type == "text").strip()

        # Models sometimes wrap JSON in a fence despite instructions.
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Model did not return parseable JSON. First 300 chars:\n{text[:300]}"
            ) from exc

    # -- interface ---------------------------------------------------------

    def assess_coverage(self, photos, ctx: ClaimContext, panel_vocabulary):
        out = self._call(
            _COVERAGE_PROMPT.format(
                vehicle=ctx.vehicle_label,
                report=(ctx.loss_description or "No description was given."),
                panels=", ".join(panel_vocabulary),
            ),
            photos,
        )
        out.setdefault("panels_visible", [])
        out.setdefault("missing", [])
        out.setdefault("unfixable", "")
        out.setdefault("coverage_score", 0.0)
        out.setdefault("notes", "")
        return out

    def assess_damage(self, photos, ctx: ClaimContext, panel_vocabulary):
        out = self._call(
            _DAMAGE_PROMPT.format(
                vehicle=ctx.vehicle_label,
                report=(ctx.loss_description or "No description was given."),
                panels=", ".join(panel_vocabulary),
            ),
            photos,
        )
        out.setdefault("line_items", [])
        out.setdefault("damage_panels", [])
        out.setdefault("notes", "")
        return out
