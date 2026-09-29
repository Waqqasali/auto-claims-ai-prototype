"""Media authenticity screening.

Why this is in the MVP rather than the roadmap:

The primary reason is calibration integrity. Phase 1 exists to collect the
evidence that justifies removing human review gates later. If some of those
claims carried manipulated images and nobody knew, the calibration curve is
built on contaminated data and thresholds get set using cases that should
never have been in the sample.

The supporting reason is that a human reviewer is not an effective control
here. Verisk found only 32% of insurers feel confident identifying deepfakes
and 66% believe media fraud often goes undetected, against 36% of consumers
who would consider altering a claim image (55% of Gen Z).

DESIGN RULE, and the thing that keeps this defensible:
Absence of provenance is NOT evidence of fraud. Most phones emit no C2PA
Content Credentials, and ordinary messaging apps strip EXIF in transit.
C2PA itself states it shows provenance history rather than proving
authenticity. So missing metadata produces a CONFIDENCE REDUCTION, never a
rejection. This module flags and routes to SIU. It never denies a claim.
Denial is a human decision with consequences under state unfair claims
settlement practices statutes.

Mostly not AI. Metadata consistency, cryptographic presence checks and
perceptual hashing are all deterministic.
"""

import json
import os
from datetime import timedelta

from config import (
    CAPTURE_WINDOW_DAYS_AFTER,
    CAPTURE_WINDOW_DAYS_BEFORE,
    PHASH_DUPLICATE_DISTANCE,
    PHASH_LEDGER,
    RUNTIME_DIR,
)
from pipeline import imaging
from pipeline.models import ClaimContext, Photo

# Software strings that indicate the file passed through an editor.
# Presence is a signal to weigh, not proof of anything: plenty of people
# crop a photo innocently, and 52% of consumers consider brightness
# adjustment acceptable.
_EDITOR_SIGNATURES = (
    "photoshop", "gimp", "lightroom", "affinity", "pixelmator",
    "snapseed", "picsart", "canva", "midjourney", "dall-e", "stable diffusion",
    "firefly", "generative",
)


def _c2pa_present(path: str) -> bool:
    """Check whether the file carries a C2PA manifest.

    HONEST LIMIT: this detects the presence of a JUMBF/C2PA box. It does NOT
    cryptographically validate the manifest or check it against a trust list.
    Full validation needs the c2pa library and a trust anchor, which is a
    production concern. Presence alone is what we weigh here, and we weigh it
    only positively — its absence costs nothing beyond a smaller bonus.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(2_000_000)   # manifests sit near the front
    except OSError:
        return False
    return b"c2pa" in head.lower() or b"jumbf" in head.lower()


def _load_ledger() -> dict:
    if not os.path.exists(PHASH_LEDGER):
        return {}
    try:
        with open(PHASH_LEDGER) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_ledger(ledger: dict) -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(PHASH_LEDGER, "w") as fh:
        json.dump(ledger, fh, indent=2)


def screen(photo: Photo, ctx: ClaimContext, record_hash: bool = True) -> Photo:
    """Annotate one photo with authenticity flags. Mutates and returns it."""
    flags: list[str] = []

    # --- 1. Metadata presence -------------------------------------------
    if not photo.exif_present:
        flags.append(
            "No EXIF metadata. Common and innocent — messaging apps strip it — "
            "but it removes our ability to corroborate capture time or device."
        )

    # --- 2. Capture time against the reported loss date -----------------
    if photo.capture_time:
        earliest = ctx.loss_date - timedelta(days=CAPTURE_WINDOW_DAYS_BEFORE)
        latest = ctx.loss_date + timedelta(days=CAPTURE_WINDOW_DAYS_AFTER)

        if photo.capture_time < earliest:
            delta = (ctx.loss_date - photo.capture_time).days
            flags.append(
                f"Capture time predates the reported loss by {delta} days "
                f"({photo.capture_time:%Y-%m-%d} vs loss {ctx.loss_date:%Y-%m-%d}). "
                "Damage cannot be photographed before it occurs."
            )
        elif photo.capture_time > latest:
            delta = (photo.capture_time - ctx.loss_date).days
            flags.append(
                f"Capture time is {delta} days after the reported loss, outside "
                f"the {CAPTURE_WINDOW_DAYS_AFTER}-day window. Not suspicious on "
                "its own; worth an adjuster's eye alongside the other signals."
            )

    # --- 3. Editing software signature -----------------------------------
    if photo.editing_software:
        low = photo.editing_software.lower()
        if any(sig in low for sig in _EDITOR_SIGNATURES):
            flags.append(
                f"Metadata names editing software ({photo.editing_software}). "
                "Not conclusive — cropping and brightness adjustment are common "
                "and widely considered acceptable — but it is a weighed signal."
            )

    # --- 4. Reuse across claims -------------------------------------------
    ledger = _load_ledger()
    if photo.perceptual_hash:
        for prior_hash, meta in ledger.items():
            if meta.get("claim_id") == ctx.claim_id:
                continue
            if imaging.hamming(photo.perceptual_hash, prior_hash) <= PHASH_DUPLICATE_DISTANCE:
                flags.append(
                    f"Visually near-identical to an image previously submitted "
                    f"on claim {meta.get('claim_id')}. Strongest single signal "
                    "in this screen."
                )
                break

        if record_hash:
            ledger[photo.perceptual_hash] = {
                "claim_id": ctx.claim_id,
                "filename": photo.filename,
            }
            _save_ledger(ledger)

    photo.c2pa_present = _c2pa_present(photo.path)
    photo.authenticity_flags = flags
    return photo


def summarise(photos: list[Photo]) -> list[str]:
    """Distinct flags across the submission, for the review screen."""
    seen: list[str] = []
    for p in photos:
        for f in p.authenticity_flags:
            if f not in seen:
                seen.append(f)
    return seen
