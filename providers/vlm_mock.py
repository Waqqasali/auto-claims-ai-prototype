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
    # Clean path: pre-ADAS vehicle, non-sensor panel.
    "CLM-1001": {
        "coverage": {
            "panels_visible": ["left_front_door", "left_front_fender"],
            "missing": [],
            "unfixable": "",
            "coverage_score": 0.95,
            "notes": "Damage fully in frame across three angles.",
        },
        "damage": {
            "line_items": [
                {
                    "operation": "repair", "part": "left front door shell",
                    "panel": "left_front_door", "damage_type": "dent",
                    "severity": "moderate",
                    "reasoning": "Single impact dent approximately 20cm across, "
                                 "no crease crossing a body line, paint intact "
                                 "at the perimeter. Repairable rather than "
                                 "replacement.",
                    "confidence": 0.91,
                },
                {
                    "operation": "refinish", "part": "left front door",
                    "panel": "left_front_door", "damage_type": "paint damage",
                    "severity": "moderate",
                    "reasoning": "Clear coat scuffed across the impact area; "
                                 "refinish required after repair.",
                    "confidence": 0.93,
                },
                {
                    "operation": "blend", "part": "left rear door",
                    "panel": "left_rear_door", "damage_type": "n/a",
                    "severity": "light",
                    "reasoning": "Adjacent panel blend for colour match on a "
                                 "metallic finish.",
                    "confidence": 0.86,
                },
            ],
            "damage_panels": ["left_front_door", "left_rear_door"],
            "notes": "Contained single-panel impact.",
        },
    },

    # Insufficient evidence: triggers the re-request loop.
    "CLM-1002": {
        "coverage": {
            "panels_visible": ["front_bumper"],
            "missing": [
                "A photo of the front bumper from about 6 feet back, with the "
                "entire bumper in frame",
                "A photo of the left front corner showing where the bumper "
                "meets the fender",
                "A straight-on photo of the front of the vehicle",
            ],
            "unfixable": "",
            "coverage_score": 0.3,
            "notes": "Only one usable angle; damage runs off the frame edge.",
        },
        "damage": {
            "line_items": [],
            "damage_panels": ["front_bumper"],
            "notes": "Not assessed — evidence insufficient.",
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

    def _script_for(self, ctx: ClaimContext):
        """The demo script, unless the reviewer supplied their own photographs.

        A script written for CLM-1002 says the evidence is insufficient. Applied
        to a photograph the reviewer just took, that is the mock asserting
        something about an image it never saw. Their files get the generic path,
        so the deterministic stages still judge the real file and the scripted
        verdict does not override them.
        """
        if getattr(ctx, "user_supplied_photos", False):
            return None
        return _SCRIPTS.get(ctx.claim_id)

    def assess_coverage(self, photos, ctx: ClaimContext, panel_vocabulary):
        script = self._script_for(ctx)
        base = dict(script["coverage"]) if script else dict(_GENERIC_COVERAGE)

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
        script = self._script_for(ctx)
        return dict(script["damage"]) if script else dict(_GENERIC_DAMAGE)
