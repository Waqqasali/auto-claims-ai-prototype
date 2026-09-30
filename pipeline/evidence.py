"""Stage 1: evidence sufficiency, and the guided re-request loop.

The assignment places photo capture BEFORE our boundary, so we cannot
redesign how people photograph damage. The only lever available is the right
to refuse to proceed on inadequate input.

The loop is bounded at two attempts because it is a retention surface, not
just a data quality gate. J.D. Power's 2025 study of 5,958 claims found
customers rating their claims experience "poor" or "just OK" have a 52%
likelihood of switching carriers, against 4% for "excellent". Someone who
has just had an accident and receives three vague resubmission requests is
exactly that cohort. Vague, repeated asks are where an efficiency feature
destroys more value than it creates.

Split by design:
  - quality checks are deterministic arithmetic (see imaging.py)
  - coverage judgment needs a VLM, because deciding "the damage runs off
    the frame edge" requires understanding what is in the picture
"""

from config import (
    MAX_REQUEST_ATTEMPTS,
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    MIN_LONG_EDGE_PX,
    MIN_SHARPNESS,
)
from pipeline.models import EvidenceVerdict, Photo

# Re-exported so callers can reference the cap without importing config too.
MAX_REQUEST_ATTEMPTS = MAX_REQUEST_ATTEMPTS

# Conditions no amount of resubmission can fix. Asking someone to retake a
# photo they cannot possibly take is the worst version of this feature.
UNFIXABLE = {
    "wrong_vehicle": "The vehicle shown does not match the policy vehicle.",
    "occluded_by_object": "Damage is obscured by another vehicle or object that "
                          "cannot be moved from the claimant's position.",
    "no_light_available": "Scene is unlit and cannot be re-shot usefully without "
                          "daylight or equipment the claimant will not have.",
    "vehicle_not_present": "The vehicle is no longer accessible to the claimant.",
}


def check_quality(photo: Photo) -> Photo:
    """Deterministic pass. Populates photo.quality_issues."""
    issues: list[str] = []

    if photo.sharpness < MIN_SHARPNESS:
        issues.append(
            f"Out of focus (sharpness {photo.sharpness:.0f}, need {MIN_SHARPNESS:.0f})"
        )
    if photo.brightness < MIN_BRIGHTNESS:
        issues.append(
            f"Too dark (brightness {photo.brightness:.0f}, need {MIN_BRIGHTNESS:.0f})"
        )
    elif photo.brightness > MAX_BRIGHTNESS:
        issues.append(
            f"Overexposed (brightness {photo.brightness:.0f}, max {MAX_BRIGHTNESS:.0f})"
        )
    if max(photo.width, photo.height) < MIN_LONG_EDGE_PX:
        issues.append(
            f"Resolution too low ({photo.width}x{photo.height}, "
            f"need {MIN_LONG_EDGE_PX}px on the long edge)"
        )

    photo.quality_issues = issues
    return photo


def evaluate(
    photos: list[Photo],
    coverage: dict,
    attempt: int,
) -> EvidenceVerdict:
    """Combine deterministic quality with the VLM's coverage judgment.

    `coverage` comes from the assessment provider and carries:
        panels_visible : list[str]
        missing        : list[str]   what still needs photographing
        unfixable      : str | ""    key from UNFIXABLE, if applicable
        coverage_score : float       0-1
    """
    unusable = [p for p in photos if not p.quality_ok]
    missing = list(coverage.get("missing", []))
    unfixable_key = coverage.get("unfixable") or ""
    score = float(coverage.get("coverage_score", 0.0))

    # --- Bail immediately on conditions resubmission cannot fix ----------
    if unfixable_key:
        return EvidenceVerdict(
            status="escalate",
            missing=missing,
            escalation_reason=UNFIXABLE.get(
                unfixable_key, "Condition cannot be resolved by resubmission."
            ),
            coverage_score=score,
        )

    problems: list[str] = []
    for p in unusable:
        problems.append(f"{p.filename}: {'; '.join(p.quality_issues)}")

    if not problems and not missing:
        return EvidenceVerdict(status="sufficient", coverage_score=score)

    # --- Out of attempts: hand to a human --------------------------------
    if attempt >= MAX_REQUEST_ATTEMPTS:
        return EvidenceVerdict(
            status="escalate",
            missing=missing,
            escalation_reason=(
                f"Evidence still insufficient after {attempt} attempts. "
                "Routed to a claims agent rather than asking the claimant again."
            ),
            coverage_score=score,
        )

    return EvidenceVerdict(
        status="re_request",
        missing=missing,
        instruction=build_instruction(problems, missing),
        coverage_score=score,
    )


def build_instruction(problems: list[str], missing: list[str]) -> str:
    """Customer-facing text. Specific and actionable, never 'send better photos'."""
    lines = ["To finish assessing your claim we need a little more from you."]

    if missing:
        lines.append("\nPlease take these photos:")
        for m in missing:
            lines.append(f"  - {m}")

    if problems:
        lines.append("\nThese photos could not be used:")
        for p in problems:
            lines.append(f"  - {p}")

    lines.append(
        "\nTips: stand about 6 feet back so the whole damaged panel is in frame, "
        "shoot in daylight or a well-lit area, and hold still until the camera "
        "focuses. If you are unable to take these, reply and a claims specialist "
        "will call you."
    )
    return "\n".join(lines)
