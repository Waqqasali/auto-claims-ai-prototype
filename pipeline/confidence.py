"""Composite confidence.

THE PROBLEM THIS SOLVES
Ask a model how confident it is and it will give you a number. That number is
not a calibrated probability — models routinely report high confidence on
wrong answers. Since the entire plan to remove human review gates depends on
this score, it has to be built from things that can be measured.

FOUR SIGNALS
  evidence_coverage       did we get adequate angles for every damaged zone
  retrieval_density       how many close historical comparables exist
  cross_stage_agreement   do identified line items map to priceable operations
  adas_penalty            does damage touch a calibration-dependent zone

AGGREGATION
Anchored to the WEAKEST line item, not the mean. Ten items at 0.90 and one at
0.60 is not a 0.87 claim. One badly wrong line ruins an estimate, and
averaging buries exactly the item that matters — which is usually the sensor
or structural item, i.e. the one that generates the supplement.

NOT AI
The per-item confidences come from the model. Everything here is deterministic
arithmetic over measurable inputs, so it is auditable, repeatable and tunable
by the carrier. A model deciding how much to trust another model is not
something you can explain to a regulator.

NOT CALIBRATED
Every weight and threshold in config.py is a placeholder. In production they
are set from shadow-mode data by plotting predicted confidence against two
realized outcomes: adjuster override rate, and supplement occurrence. This
module deliberately does not pretend otherwise.
"""

from config import (
    ADAS_CONFIDENCE_PENALTY,
    AUTHENTICITY_FLAG_PENALTY,
    W_CROSS_STAGE_AGREEMENT,
    W_EVIDENCE_COVERAGE,
    W_LINE_ITEM_FLOOR,
    W_RETRIEVAL_DENSITY,
)
from pipeline.models import Assessment, ConfidenceBreakdown


def compute(
    assessment: Assessment,
    evidence_coverage: float,
    retrieval_density: float,
    cross_stage_agreement: float,
    adas_hits: list[dict],
    authenticity_flags: list[str],
) -> ConfidenceBreakdown:
    explanation: list[str] = []

    # --- Base: weighted blend, anchored on the weakest line -------------
    if assessment.line_items:
        floor = min(li.confidence for li in assessment.line_items)
        weakest = min(assessment.line_items, key=lambda li: li.confidence)
        explanation.append(
            f"Weakest line item is '{weakest.operation} {weakest.part}' at "
            f"{floor:.2f}. Claim confidence is anchored here rather than on the "
            f"average, because one wrong line ruins an estimate."
        )
    else:
        floor = 0.0
        explanation.append("No line items produced; confidence floor is 0.")

    base = (
        W_LINE_ITEM_FLOOR * floor
        + W_EVIDENCE_COVERAGE * evidence_coverage
        + W_RETRIEVAL_DENSITY * retrieval_density
        + W_CROSS_STAGE_AGREEMENT * cross_stage_agreement
    )
    explanation.append(
        f"Base = {W_LINE_ITEM_FLOOR}x floor({floor:.2f}) + "
        f"{W_EVIDENCE_COVERAGE}x coverage({evidence_coverage:.2f}) + "
        f"{W_RETRIEVAL_DENSITY}x retrieval({retrieval_density:.2f}) + "
        f"{W_CROSS_STAGE_AGREEMENT}x agreement({cross_stage_agreement:.2f}) "
        f"= {base:.3f}"
    )

    score = base

    # --- ADAS penalty ----------------------------------------------------
    adas_penalty = 0.0
    if adas_hits:
        adas_penalty = ADAS_CONFIDENCE_PENALTY
        score -= adas_penalty
        panels = ", ".join(h["panel"].replace("_", " ") for h in adas_hits)
        explanation.append(
            f"ADAS penalty -{adas_penalty:.2f}: damage touches {panels}, which "
            f"carries sensors on this vehicle. Calibration need cannot be "
            f"confirmed from photographs, and 51.5% of calibrations industry-wide "
            f"appear on supplements rather than initial estimates."
        )

    # --- Hidden damage candidates ----------------------------------------
    # DELIBERATELY NOT PENALISED IN THE MVP.
    #
    # Nearly every damage pattern has candidates behind it, so a flat penalty
    # fires on almost every claim — and a signal that fires on everything
    # carries no information. It simply shifts the whole distribution down and
    # collapses the routing tiers.
    #
    # Weighting it properly requires OBSERVED RATES from a real claims corpus
    # ("38% of 340 comparable claims involved radiator support damage"). The
    # stub has no rates, and inventing weights would be fabricating evidence.
    #
    # So in the MVP these are surfaced to the adjuster as information, and the
    # penalty is switched on — rate-weighted — once comparables are real.
    if assessment.hidden_damage:
        explanation.append(
            f"{len(assessment.hidden_damage)} hidden damage candidate(s) shown "
            f"to the adjuster for information. No confidence penalty applied: "
            f"without observed rates from a real claims corpus any weight would "
            f"be arbitrary, and the signal fires on nearly every claim. Becomes "
            f"rate-weighted when comparables are connected."
        )

    # --- Authenticity -----------------------------------------------------
    if authenticity_flags:
        score -= AUTHENTICITY_FLAG_PENALTY
        explanation.append(
            f"Authenticity penalty -{AUTHENTICITY_FLAG_PENALTY:.2f}: "
            f"{len(authenticity_flags)} media flag(s) raised. This reduces "
            f"confidence and routes for review. It never denies a claim."
        )

    score = max(0.0, min(1.0, score))
    explanation.append(f"Claim confidence = {score:.3f}")

    return ConfidenceBreakdown(
        evidence_coverage=round(evidence_coverage, 3),
        retrieval_density=round(retrieval_density, 3),
        cross_stage_agreement=round(cross_stage_agreement, 3),
        adas_penalty=round(adas_penalty, 3),
        line_item_floor=round(floor, 3),
        claim_confidence=round(score, 3),
        explanation=explanation,
    )
