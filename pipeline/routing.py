"""Routing: what the reviewer is shown, and how it is framed.

In the MVP, EVERY claim that clears the Tier 1 gate is reviewed by a human.
Nothing is auto-approved, in this build or in either phase of the PRD.
Routing therefore does not decide whether a person is involved. It decides
how the draft is PRESENTED, so the reviewer knows how much to trust it.

That framing matters. A low-confidence draft is still worth showing, because
even a partial line item list saves typing. What destroys reviewer trust is a
bad draft presented as a good one.

The PRD has two phases, and they differ in who reviews the draft, not in
whether anyone does. In Phase 1 every draft goes to a claims agent. In Phase 2
a draft inside a proven confidence band, with no ADAS involvement and below
an authority ceiling, goes straight to the senior claims adjuster, who
approves or rejects it. This build is Phase 1. The band cannot be drawn
until the thresholds are calibrated against real override and supplement
outcomes.
"""

from config import TIER_STARTING_POINT_MIN, TIER_VERIFY_MIN, VERIFY_MIN_LINE_FLOOR
from pipeline.models import Assessment, ConfidenceBreakdown, Decision

# Stands for the Phase 2 route: inside the proven band, the draft skips the
# claims agent and goes to the senior claims adjuster. A person still approves
# every claim. Deliberately off, and the route is not built. Turning it on
# without calibration evidence would be the most dangerous change anyone could
# make to this system.
AUTOMATION_ENABLED = False


def decide(
    confidence: ConfidenceBreakdown,
    assessment: Assessment,
    adas_hits: list[dict],
    authenticity_flags: list[str],
) -> Decision:
    reasons: list[str] = []
    score = confidence.claim_confidence

    if adas_hits:
        reasons.append(
            f"Calibration risk on {len(adas_hits)} panel(s) carrying sensors."
        )
    from pipeline.authenticity import STRONG, flag_strength
    strong_flags = [f for f in authenticity_flags if flag_strength(f) == STRONG]
    if strong_flags:
        reasons.append(
            f"{len(strong_flags)} strong media authenticity concern(s). Routed "
            f"for review, not denied."
        )
    elif authenticity_flags:
        reasons.append(
            f"{len(authenticity_flags)} minor media authenticity note(s), such "
            f"as missing photo metadata. Shown to the reviewer; not a bar to "
            f"verification."
        )
    if assessment.hidden_damage:
        reasons.append(
            f"{len(assessment.hidden_damage)} hidden damage candidate(s) that "
            f"cannot be confirmed before teardown."
        )
    unpriced = [li for li in assessment.line_items if not li.priced]
    if unpriced:
        # Two causes produce an unpriced line, and the reviewer should not be
        # told it is always the first. Either the assessment named an
        # operation the costing stage does not recognize, or the catalog has
        # a gap. Against a complete production catalog the first dominates;
        # against this stub the second is more likely (CLM-1007's rocker panel
        # is a catalog gap, not a model error). Both leave the total
        # incomplete, which is what the reviewer needs to act on.
        reasons.append(
            f"{len(unpriced)} line item(s) could not be priced, so the total is "
            f"incomplete. Either the assessment named something the costing "
            f"stage does not recognize, or the price catalog has a gap."
        )

    # Verify needs three things: the score, no strong authenticity signal (see
    # authenticity.py), and a weakest line that clears its own minimum. The
    # score is a weighted sum, so good photos and dense comparables could carry
    # a claim past the threshold with one shaky line in it; the floor stops
    # that line being outvoted.
    floor = confidence.line_item_floor
    floor_ok = floor >= VERIFY_MIN_LINE_FLOOR
    if score >= TIER_VERIFY_MIN and not strong_flags and floor_ok:
        tier = "verify"
        headline = "Draft estimate ready for verification"
        reasons.insert(
            0,
            f"Confidence {score:.2f} at or above the verify threshold "
            f"({TIER_VERIFY_MIN:.2f}).",
        )
    elif score >= TIER_STARTING_POINT_MIN:
        tier = "starting_point"
        headline = "Use as a starting point: specific risks identified"
        if score >= TIER_VERIFY_MIN:
            # The score cleared verify, so "sits between the thresholds" would
            # be untrue. Say what held it back instead.
            blockers = (["a strong media authenticity flag"] if strong_flags
                        else []) + ([] if floor_ok else ["the weakest line item"])
            reasons.insert(
                0,
                f"Confidence {score:.2f} is at or above the verify threshold "
                f"({TIER_VERIFY_MIN:.2f}), but {' and '.join(blockers)} "
                f"{'keeps' if len(blockers) == 1 else 'keep'} the claim out of "
                f"verify.",
            )
            if not floor_ok:
                reasons.insert(
                    1,
                    f"Weakest line item {floor:.2f} is below the verify minimum "
                    f"({VERIFY_MIN_LINE_FLOOR:.2f}), so the claim cannot be "
                    f"marked verify.",
                )
        else:
            reasons.insert(
                0,
                f"Confidence {score:.2f} sits between the starting-point "
                f"threshold ({TIER_STARTING_POINT_MIN:.2f}) and the verify "
                f"threshold ({TIER_VERIFY_MIN:.2f}).",
            )
    else:
        tier = "low_confidence"
        headline = "Low confidence: do not anchor on these figures"
        reasons.insert(
            0,
            f"Confidence {score:.2f} is below the starting-point threshold "
            f"({TIER_STARTING_POINT_MIN:.2f}).",
        )

    if AUTOMATION_ENABLED:
        reasons.append(
            "NOTE: Phase 2 routing is enabled. It should not be without "
            "calibration evidence."
        )

    return Decision(tier=tier, headline=headline, reasons=reasons)


TIER_LABELS = {
    "verify": "VERIFY",
    "starting_point": "STARTING POINT",
    "low_confidence": "LOW CONFIDENCE",
    "re_request": "MORE PHOTOS NEEDED",
    "escalated": "ESCALATED TO AGENT",
    "not_processed": "NOT PROCESSED",
}

TIER_GUIDANCE = {
    "verify": "Line items look well supported. Check them rather than rebuilding.",
    "starting_point": "Usable as a base, but the risks below need your judgment.",
    "low_confidence": "Treat the figures as unreliable. The line item list may "
                      "still save you typing.",
    "re_request": "A specific, actionable request has been issued to the "
                  "policyholder. No assessment was run on inadequate evidence.",
    "escalated": "The re-request loop is exhausted or the problem cannot be "
                 "fixed by resubmission. A person takes it from here.",
    "not_processed": "Excluded before any assessment ran. See reasons.",
}


def label(decision: Decision) -> str:
    """The banner label: the decision's own wording if it has one."""
    return decision.label or TIER_LABELS.get(decision.tier, decision.tier.upper())


def guidance(decision: Decision) -> str:
    """The line under the headline: the decision's own wording if it has one."""
    return decision.guidance or TIER_GUIDANCE.get(decision.tier, "")
