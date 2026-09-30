"""Tunable parameters, all in one place.

Every threshold here is a PLACEHOLDER. None of them are calibrated.

In production these are set by retrospective calibration: the system is run
against a recent historical sample where the final cost including any
supplement is already known, and predicted confidence is plotted against
those realized outcomes. Naming a calibrated number before that data exists
would be inventing a fact, so these values exist only to make the prototype
run and to make the routing behavior visible.
"""

import os

# Load a local .env file when one exists and python-dotenv is installed. Both
# are optional. Every value below falls back to a working default and the
# default provider needs no credentials, so a missing .env changes nothing.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- Provider selection -----------------------------------------------------
# "mock" runs with no API key and returns deterministic canned assessments.
# "anthropic" makes real vision calls. Set VLM_PROVIDER=anthropic and
# ANTHROPIC_API_KEY to use it.
VLM_PROVIDER = os.environ.get("VLM_PROVIDER", "mock")
# Sonnet is a sensible default for running the prototype, not a production
# recommendation.
#
# Inference cost does NOT decide this. At 500,000 claims a year and two vision
# calls each, Sonnet runs about $20k a year and Opus about $41k, against a
# $14M annual cost for the agent step the product is trying to shorten. The
# difference between the two is 0.7% of the Phase 1 saving, and it pays for
# itself if the stronger model widens the automatable band by ~1,900 claims,
# which is 0.4% of volume.
#
# So the deciding measure is band width, not price: a model that identifies
# panels more reliably earns higher per-item confidence, which widens the band
# that Phase 2 can handle without an agent. That is measurable only against
# calibration data which does not exist before deployment, which is why the PRD
# declines to name a model. The abstraction in providers/ is what keeps this a
# configuration decision rather than a rewrite.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# --- Stage 1: image quality -------------------------------------------------
MIN_SHARPNESS = 60.0        # variance of Laplacian below this reads as blurry
MIN_BRIGHTNESS = 45.0       # mean luminance; below this is too dark to assess
MAX_BRIGHTNESS = 225.0      # above this is blown out
MIN_LONG_EDGE_PX = 800      # smaller than this loses the detail we need

# --- Stage 1: re-request loop ----------------------------------------------
MAX_REQUEST_ATTEMPTS = 2    # after this, a human takes over

# --- Stage 1: authenticity --------------------------------------------------
# How far a photo's capture time may sit from the reported loss date before
# it is flagged. Generous on purpose: people photograph damage days later.
CAPTURE_WINDOW_DAYS_BEFORE = 0      # a photo taken BEFORE the loss is a flag
CAPTURE_WINDOW_DAYS_AFTER = 14
PHASH_DUPLICATE_DISTANCE = 8        # Hamming distance below this = likely reuse

# --- Stage 4: confidence ----------------------------------------------------
# Weighting is anchored to the weakest line item, not the mean. One badly
# wrong line ruins an estimate, and averaging hides exactly that item.
W_LINE_ITEM_FLOOR = 0.45
W_EVIDENCE_COVERAGE = 0.25
W_RETRIEVAL_DENSITY = 0.15
W_CROSS_STAGE_AGREEMENT = 0.15

ADAS_CONFIDENCE_PENALTY = 0.25      # flat subtraction when a sensor zone is hit
# Reserved, and deliberately unused in the MVP: hidden damage candidates are
# shown to the reviewer but not penalized until observed rates exist. See the
# note in pipeline/confidence.py.
HIDDEN_DAMAGE_PENALTY_EACH = 0.05   # per candidate, capped below
HIDDEN_DAMAGE_PENALTY_CAP = 0.15
AUTHENTICITY_FLAG_PENALTY = 0.20

# --- Stage 5: routing tiers -------------------------------------------------
TIER_VERIFY_MIN = 0.80              # >= this: present as a draft to verify
TIER_STARTING_POINT_MIN = 0.55      # >= this: present as a starting point
# below TIER_STARTING_POINT_MIN: present as low confidence, do not anchor

# --- Paths ------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
# Overridable so the test suites write to a temporary folder instead of the
# presenter's real ledger and override log.
RUNTIME_DIR = (os.environ.get("CLAIMS_RUNTIME_DIR")
               or os.path.join(os.path.dirname(__file__), "runtime"))
OVERRIDE_LOG = os.path.join(RUNTIME_DIR, "overrides.jsonl")
PHASH_LEDGER = os.path.join(RUNTIME_DIR, "phash_ledger.json")
