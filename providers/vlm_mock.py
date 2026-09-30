"""Deterministic mock provider. Runs with no API key, no network, no cost.

WHY THIS IS THE DEFAULT
A reviewer should be able to clone the repo and see the system work in one
command. Any friction between a panel and a running demo is friction you
chose to create.

WHAT IT IS NOT
It is not a simulation of model quality. It returns scripted assessments so
the DECISION ARCHITECTURE is observable: the refusal path, the confidence
arithmetic, the ADAS penalty, the routing outcome. Those are the parts under
evaluation, and they are real code operating on real inputs.

The deterministic image measurements (sharpness, brightness, resolution) and
the authenticity checks (EXIF, C2PA presence, perceptual hashing) are NEVER
mocked — they run against the actual files in every mode.
"""

from pipeline.models import ClaimContext, Photo
from providers.vlm_base import VLMProvider


# Scripted responses for the demo claims. Keyed by claim_id so the scenarios
# behave predictably when recording.
_SCRIPTS: dict[str, dict] = {
    # Clean path, real photographs. The damaged panels carry no sensors
    # on this vehicle, so nothing complicates the assessment.
    "CLM-1001": {
        "coverage": {
            "panels_visible": ["front_bumper", "left_front_fender", "front_grille"],
            "missing": [],
            "unfixable": "",
            "coverage_score": 0.94,
            "notes": "Three angles: whole front in frame, the left front "
                     "corner at the fender seam, and a close-up of the damage.",
        },
        "damage": {
            "line_items": [
                {
                    "operation": "replace", "part": "front bumper cover",
                    "panel": "front_bumper", "damage_type": "crease and tear",
                    "severity": "moderate",
                    "reasoning": "Crease runs from below the left headlamp "
                                 "across the cover, and the cover has parted "
                                 "at the fender seam with the mounting tab "
                                 "deformed. A torn mounting point cannot be "
                                 "pulled back to a factory fit, so this is a "
                                 "replacement rather than a repair.",
                    "confidence": 0.90,
                },
                {
                    "operation": "refinish", "part": "front bumper cover",
                    "panel": "front_bumper", "damage_type": "paint",
                    "severity": "moderate",
                    "reasoning": "Replacement covers are supplied in primer "
                                 "and require refinishing to the vehicle's "
                                 "metallic grey.",
                    "confidence": 0.92,
                },
                {
                    "operation": "blend", "part": "left front fender",
                    "panel": "left_front_fender", "damage_type": "n/a",
                    "severity": "light",
                    "reasoning": "Adjacent panel blend so the refinished cover "
                                 "matches across the seam. Metallic finishes "
                                 "show a hard edge without it.",
                    "confidence": 0.86,
                },
            ],
            "damage_panels": ["front_bumper", "left_front_fender"],
            "notes": "Damage confined to the left front corner. No evidence of "
                     "intrusion past the bumper reinforcement in these angles.",
        },
    },

    "CLM-1002": {
        "coverage": {
            "panels_visible": ["left_rear_wheel"],
            "missing": [
                "A straight-on photo of the damaged wheel with the whole rim "
                "in frame",
                "A photo of the tire sidewall alongside the damaged area",
                "A photo from a few steps back showing which corner of the "
                "vehicle the wheel is on",
            ],
            "unfixable": "",
            "coverage_score": 0.3,
            "notes": "Only one usable angle; the rim runs off the frame edge.",
        },
        # Used once evidence passes, which for this claim means a
        # resubmission. Describes samples/navigator_wheel_*.jpg.
        "damage": {
            "line_items": [
                {
                    "operation": "repair", "part": "left rear alloy wheel",
                    "panel": "left_rear_wheel", "damage_type": "kerb damage",
                    "severity": "moderate",
                    "reasoning": "Gouging confined to the outer lip, through "
                                 "the gloss black finish to bare alloy across "
                                 "roughly a third of the circumference. No "
                                 "flat-spotting or cracking visible at this "
                                 "angle, so machine and recondition rather "
                                 "than replace.",
                    "confidence": 0.88,
                },
                {
                    "operation": "refinish", "part": "left rear alloy wheel",
                    "panel": "left_rear_wheel", "damage_type": "finish",
                    "severity": "moderate",
                    "reasoning": "Refinish to the factory gloss black once the "
                                 "lip has been reconditioned.",
                    "confidence": 0.90,
                },
            ],
            "damage_panels": ["left_rear_wheel"],
            "notes": "Cosmetic assessment only. Whether the rim is true, and "
                     "whether the inner sidewall survived, cannot be "
                     "established from photographs.",
        },
    },

    # THE SURPRISE. Rear bumper scuff on a sensor-equipped sedan.
    # Looks trivially automatable. The parking sensors change the answer.
    "CLM-1003": {
        "coverage": {
            "panels_visible": ["rear_bumper"],
            "missing": [],
            "unfixable": "",
            "coverage_score": 0.92,
            "notes": "Rear bumper captured from three angles, damage fully visible.",
        },
        "damage": {
            "line_items": [
                {
                    "operation": "replace", "part": "rear bumper cover",
                    "panel": "rear_bumper", "damage_type": "scuff and gouge",
                    "severity": "moderate",
                    "reasoning": "Gouging penetrates the substrate below the "
                                 "clear coat across roughly 40cm. Refinish "
                                 "alone will not restore the surface.",
                    "confidence": 0.92,
                },
                {
                    "operation": "refinish", "part": "rear bumper cover",
                    "panel": "rear_bumper", "damage_type": "paint",
                    "severity": "moderate",
                    "reasoning": "Replacement cover supplied in primer; "
                                 "refinish to match.",
                    "confidence": 0.90,
                },
                {
                    "operation": "R&I", "part": "rear parking sensors",
                    "panel": "rear_bumper", "damage_type": "n/a",
                    "severity": "light",
                    "reasoning": "Sensors are mounted through the bumper cover "
                                 "and must be transferred to the replacement. "
                                 "Whether recalibration is required cannot be "
                                 "determined from photographs.",
                    "confidence": 0.71,
                },
            ],
            "damage_panels": ["rear_bumper"],
            "notes": "Single rear impact, cosmetically contained — but the "
                     "panel carries sensors.",
        },
    },

    # Authenticity flag: capture time predates the loss.
    "CLM-1004": {
        "coverage": {
            "panels_visible": ["right_front_fender", "right_front_door"],
            "missing": [],
            "unfixable": "",
            "coverage_score": 0.88,
            "notes": "Adequate coverage of the impact area.",
        },
        "damage": {
            "line_items": [
                {
                    "operation": "repair", "part": "right front fender",
                    "panel": "right_front_fender", "damage_type": "crease",
                    "severity": "moderate",
                    "reasoning": "Horizontal crease along the upper fender "
                                 "line, metal stretched but not torn.",
                    "confidence": 0.84,
                },
                {
                    "operation": "refinish", "part": "right front fender",
                    "panel": "right_front_fender", "damage_type": "paint",
                    "severity": "moderate",
                    "reasoning": "Paint fractured along the crease.",
                    "confidence": 0.88,
                },
            ],
            "damage_panels": ["right_front_fender", "right_front_door"],
            "notes": "Assessment proceeds; authenticity concerns are handled "
                     "separately and do not alter the damage judgement.",
        },
    },
}


_GENERIC_COVERAGE = {
    "panels_visible": ["front_bumper"],
    "missing": [],
    "unfixable": "",
    "coverage_score": 0.75,
    "notes": "MOCK MODE: generic coverage response for an unscripted claim.",
}

# Coverage to assume in mock mode when a real upload arrives against a claim
# whose evidence request is already on record.
#
# The generic 0.75 above is a "we have no idea what you sent" number, right for
# a claim that never asked for anything specific. CLM-1002 did ask: attempt 1
# named three angles (the rim face square on, the inner sidewall, and the wheel
# in context on the vehicle). A resubmission of three files that pass the
# deterministic checks answers that request, so coverage is higher than generic.
#
# 0.88 is a placeholder in exactly the same sense as every other number in this
# module. It is set to the same value as the weakest line item so the happy path
# reads identically whether confidence is combined by weighted sum or anchored
# on the weakest signal, which keeps the demo honest under either formula.
_UPLOAD_COVERAGE: dict[str, float] = {
    "CLM-1002": 0.88,
}

_GENERIC_DAMAGE = {
    "line_items": [
        {
            "operation": "repair", "part": "front bumper cover",
            "panel": "front_bumper", "damage_type": "scuff",
            "severity": "light",
            "reasoning": "MOCK MODE: generic line item. Run with "
                         "VLM_PROVIDER=anthropic for a real assessment.",
            "confidence": 0.80,
        },
        {
            "operation": "refinish", "part": "front bumper cover",
            "panel": "front_bumper", "damage_type": "paint",
            "severity": "light",
            "reasoning": "MOCK MODE: generic line item.",
            "confidence": 0.82,
        },
    ],
    "damage_panels": ["front_bumper"],
    "notes": "MOCK MODE: unscripted claim.",
}


class MockVLM(VLMProvider):
    name = "mock"
    is_live = False

    def _script_for(self, ctx: ClaimContext, stage: str):
        """The demo script for this claim, where it can honestly be applied.

        The two stages differ for uploaded photographs.

        Coverage is a judgement about whether the evidence is adequate, and the
        deterministic checks have already measured the reviewer's actual files.
        A script saying "insufficient" about a photograph it never saw would
        contradict a real measurement, so uploads always take the generic path
        here and the real sharpness, brightness and resolution decide it.

        Damage is different. Mock mode cannot see any photograph, scripted or
        uploaded, so there is nothing to contradict. Returning this claim's
        assessment gives a demo something coherent to show without a key, and
        the screen says plainly that the line items are scripted rather than
        read from the file.
        """
        if stage == "coverage" and getattr(ctx, "user_supplied_photos", False):
            return None
        return _SCRIPTS.get(ctx.claim_id)

    def assess_coverage(self, photos, ctx: ClaimContext, panel_vocabulary):
        script = self._script_for(ctx, "coverage")
        base = dict(script["coverage"]) if script else dict(_GENERIC_COVERAGE)

        # An upload against a claim with a known evidence request scores
        # against that request rather than against nothing. See _UPLOAD_COVERAGE.
        if getattr(ctx, "user_supplied_photos", False):
            expected = _UPLOAD_COVERAGE.get(ctx.claim_id)
            if expected is not None:
                base["coverage_score"] = expected
                base["notes"] = (
                    "MOCK MODE: uploaded files scored against the evidence "
                    "request already issued on this claim."
                )

        # Honour reality: if the actual files fail the deterministic quality
        # checks, the mock must not pretend coverage is fine. This keeps the
        # refusal path genuine even in mock mode.
        unusable = [p for p in photos if not p.quality_ok]
        if unusable and not base["missing"]:
            base = dict(base)
            base["missing"] = [
                "A replacement for each unusable photo listed below, "
                "retaken with the whole damaged panel in frame"
            ]
            base["coverage_score"] = min(base["coverage_score"], 0.4)
            base["notes"] = "Deterministic quality checks failed on submitted files."

        return base

    def assess_damage(self, photos, ctx: ClaimContext, panel_vocabulary):
        script = self._script_for(ctx, "damage")
        return dict(script["damage"]) if script else dict(_GENERIC_DAMAGE)
