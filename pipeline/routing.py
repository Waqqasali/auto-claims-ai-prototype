"""Routing: what the reviewer is shown, and how it is framed.

In the MVP, EVERY claim that clears the Tier 1 gate is reviewed by a human.
Nothing is auto-approved. Routing therefore does not decide whether a person
is involved — it decides how the draft is PRESENTED, so the reviewer knows
how much to trust it.

That framing matters. A low-confidence draft is still worth showing, because
even a partial line item list saves typing. What destroys reviewer trust is a
bad draft presented as a good one.

Automated authority is a Phase 3 concept and lives behind AUTOMATION_ENABLED,
which is False. When it is eventually switched on, it opens only for claims
inside a proven confidence band with no ADAS involvement and no flags — and
only once the thresholds have been calibrated against real override and
supplement outcomes.
"""

from config import TIER_STARTING_POINT_MIN, TIER_VERIFY_MIN
from pipeline.models import Assessment, ConfidenceBreakdown, Decision

# Phase 3. Deliberately off. Flipping this without calibration evidence would
# be the single most dangerous change anyone could make to this system.
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
    if authenticity_flags:
        reasons.append(
            f"{len(authenticity_flags)} media authenticity flag(s) — routed for "
            f"review, not denied."
        )
    if assessment.hidden_damage:
        reasons.append(
            f"{len(assessment.hidden_damage)} hidden damage candidate(s) that "
            f"cannot be confirmed before teardown."
        )
    unpriced = [li for li in assessment.line_items if not li.priced]
    if unpriced:
        reasons.append(
            f"{len(unpriced)} line item(s) could not be priced, which suggests "
            f"the assessment produced something outside the expected vocabulary."
        )

    if score >= TIER_VERIFY_MIN and not authenticity_flags:
        tier = "verify"
        headline = "Draft estimate ready for verification"
        reasons.insert(
            0,
            f"Confidence {score:.2f} at or above the verify threshold "
            f"({TIER_VERIFY_MIN:.2f}).",
        )
    elif score >= TIER_STARTING_POINT_MIN:
        tier = "starting_point"
        headline = "Use as a starting point — specific risks identified"
        reasons.insert(
            0,
            f"Confidence {score:.2f} sits between the starting-point threshold "
            f"({TIER_STARTING_POINT_MIN:.2f}) and the verify threshold "
            f"({TIER_VERIFY_MIN:.2f}).",
        )
    else:
        tier = "low_confidence"
        headline = "Low confidence — do not anchor on these figures"
        reasons.insert(
            0,
            f"Confidence {score:.2f} is below the starting-point threshold "
            f"({TIER_STARTING_POINT_MIN:.2f}).",
        )

    if AUTOMATION_ENABLED:
        reasons.append(
            "NOTE: automated authority is enabled. It should not be without "
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
    "starting_point": "Usable as a base, but the risks below need your judgement.",
    "low_confidence": "Treat the figures as unreliable. The line item list may "
                      "still save you typing.",
    "re_request": "A specific, actionable request has been issued to the "
                  "policyholder. No assessment was run on inadequate evidence.",
    "escalated": "The re-request loop is exhausted or the problem cannot be "
                 "fixed by resubmission. A person takes it from here.",
    "not_processed": "Excluded before any assessment ran. See reasons.",
}
