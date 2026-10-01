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
rejection. This module flags; referral to the Special Investigation Unit is
the reviewer's decision, recorded as a rejection reason. It never denies a claim.
Denial is a human decision with consequences under state unfair claims
settlement practices statutes.

Not AI. Metadata consistency, the C2PA presence check and perceptual hashing
are all deterministic, and no model is called.
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
    production concern. The result is shown to the reviewer and does not move
    the score either way: most phones write no manifest, so its absence is
    normal, and a manifest nobody has validated proves nothing.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(2_000_000)   # manifests sit near the front
    except OSError:
        return False
    return b"c2pa" in head.lower() or b"jumbf" in head.lower()


def _load_ledger() -> dict:
    """Perceptual hash -> the claims that submitted it, and in what order.

    Each entry's "seen" maps a claim to its place in the order of submissions
    across the whole ledger, so two entries can be compared. Ledgers written
    before the order was kept are numbered in file order, which is the order
    their photos were first recorded in.
    """
    if not os.path.exists(PHASH_LEDGER):
        return {}
    try:
        with open(PHASH_LEDGER, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(ledger, dict):
        return {}
    ledger = {h: m for h, m in ledger.items() if isinstance(m, dict)}
    n = _last_seen(ledger)
    for meta in ledger.values():
        if not isinstance(meta.get("seen"), dict):
            meta["seen"] = {}
            for claim in meta.pop("claims", None) or [meta.get("claim_id")]:
                if claim and claim not in meta["seen"]:
                    n += 1
                    meta["seen"][claim] = n
    return ledger


def _last_seen(ledger: dict) -> int:
    return max((n for meta in ledger.values()
                for n in (meta.get("seen") or {}).values()), default=0)


def _save_ledger(ledger: dict) -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(PHASH_LEDGER, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2)


# How much each signal should move the score. Only a STRONG signal (the same
# photo on another claim, or a photo taken before the loss) bars the verify
# tier. Missing EXIF is WEAK: it is the ordinary state of a photo that went
# through a messaging app, and treating it as suspicious would make most real
# claims unverifiable. Anything not listed here is MODERATE by default, and a
# test checks that every message this module writes is classified on purpose.
STRONG, MODERATE, WEAK = "strong", "moderate", "weak"
_STRENGTH_BY_PREFIX = (
    ("Visually near-identical", STRONG),
    ("Capture time predates", STRONG),
    ("Metadata names editing software", MODERATE),
    ("Capture time is", MODERATE),
    ("No EXIF metadata", WEAK),
)


def flag_strength(flag: str) -> str:
    for prefix, strength in _STRENGTH_BY_PREFIX:
        if flag.startswith(prefix):
            return strength
    return MODERATE


def screen(photo: Photo, ctx: ClaimContext, record_hash: bool = True) -> Photo:
    """Annotate one photo with authenticity flags. Mutates and returns it."""
    flags: list[str] = []

    # --- 1. Metadata presence -------------------------------------------
    if not photo.exif_present:
        flags.append(
            "No EXIF metadata. Common and innocent, since messaging apps strip "
            "it, but it removes our ability to corroborate capture time or "
            "device."
        )

    # --- 2. Capture time against the reported loss date -----------------
    if photo.capture_time:
        # Compared by calendar date. Comparing a timestamp against midnight on
        # the loss date produced "14 days after the loss, outside the 14-day
        # window" for a photo taken on day 14, and "by 0 days" for the evening
        # before.
        days_after = (photo.capture_time.date() - ctx.loss_date.date()).days

        def _days(n):
            return f"{n} day" + ("" if n == 1 else "s")

        if days_after < -CAPTURE_WINDOW_DAYS_BEFORE:
            delta = -days_after
            flags.append(
                f"Capture time predates the reported loss by {_days(delta)} "
                f"({photo.capture_time:%Y-%m-%d} vs loss {ctx.loss_date:%Y-%m-%d}). "
                "Damage cannot be photographed before it occurs."
            )
        elif days_after > CAPTURE_WINDOW_DAYS_AFTER:
            delta = days_after
            flags.append(
                f"Capture time is {_days(delta)} after the reported loss, outside "
                f"the {CAPTURE_WINDOW_DAYS_AFTER}-day window. Not suspicious on "
                "its own; worth a reviewer's eye alongside the other signals."
            )

    # --- 3. Editing software signature -----------------------------------
    if photo.editing_software:
        low = photo.editing_software.lower()
        if any(sig in low for sig in _EDITOR_SIGNATURES):
            flags.append(
                f"Metadata names editing software ({photo.editing_software}). "
                "Not conclusive: cropping and brightness adjustment are common "
                "and widely considered acceptable. It is still a weighed signal."
            )

    # --- 4. Reuse across claims -------------------------------------------
    #
    # Every claim a photo has appeared on is kept, with the order it arrived
    # in. The first version stored a single owner and overwrote it on each
    # view, so the claim that looked last took the photo over: the reuse flag
    # showed once, then vanished on the next rerun and the tier flipped back.
    # A submission is a fact about the past and is never reassigned.
    #
    # Only the later submission is flagged. Flagging every claim a photo
    # appears on let one upload to another claim knock the original claim out
    # of verify, for every visitor to a shared copy of the app, with a flag
    # naming the copy as the original. A claim is flagged when the ledger shows
    # the photo on a different claim before this one; a claim that has not
    # submitted it yet is submitting it now, after everything on record.
    ledger = _load_ledger()
    if photo.perceptual_hash:
        matches = [meta["seen"] for prior_hash, meta in ledger.items()
                   if imaging.hamming(photo.perceptual_hash, prior_hash)
                   <= PHASH_DUPLICATE_DISTANCE]
        mine = min((seen[ctx.claim_id] for seen in matches
                    if ctx.claim_id in seen), default=float("inf"))
        earlier = sorted((n, claim) for seen in matches
                         for claim, n in seen.items()
                         if claim != ctx.claim_id and n < mine)
        if earlier:
            flags.append(
                f"Visually near-identical to an image previously submitted "
                f"on claim {earlier[0][1]}. Strongest single signal in this "
                "screen."
            )

        if record_hash:
            entry = ledger.get(photo.perceptual_hash)
            if entry is None or ctx.claim_id not in entry["seen"]:
                n = _last_seen(ledger) + 1
                if entry is None:
                    ledger[photo.perceptual_hash] = {
                        "claim_id": ctx.claim_id,        # first submitter
                        "filename": photo.filename,
                        "seen": {ctx.claim_id: n},
                    }
                else:
                    entry["seen"][ctx.claim_id] = n
                _save_ledger(ledger)

    photo.c2pa_present = _c2pa_present(photo.path)
    photo.authenticity_flags = flags
    return photo


def summarize(photos: list[Photo]) -> list[str]:
    """Distinct flags across the submission, for the review screen."""
    seen: list[str] = []
    for p in photos:
        for f in p.authenticity_flags:
            if f not in seen:
                seen.append(f)
    return seen
