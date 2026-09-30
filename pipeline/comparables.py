"""Hidden damage flagging, from historical comparables.

STUBBED. This is one of two components that depend on data existing only
inside a carrier.

WHAT THIS SHOULD DO IN PRODUCTION
    Query the carrier's historical claims corpus:
        "find claims with a similar damage pattern on a similar vehicle, and
         report what the repair actually involved after teardown"
    returning observed rates, e.g. "across 340 comparable claims, 38%
    involved radiator support damage, average supplement $1,240."

WHAT IT DOES HERE
    Reads a small hand-written rules table with NO observed rates. Inventing
    rates would be fabricating evidence, so the field is left None and the
    UI shows it as unavailable.

WHY THE STUB IS SHAPED THIS WAY
    Everything about lookup() is final: its inputs, its output type, and every
    consumer of its output (confidence scoring, routing, the review screen).
    Only the body changes when a real corpus is connected. A bad stub hardcodes
    a value in the middle of the logic and has to be unpicked from five places.

WHY THE FEATURE EARNS ITS PLACE
    Pre-teardown blindness is the hard information limit in this domain.
    Tractable concedes its AI has not reduced supplement amounts precisely
    because it only assesses visually before teardown. We cannot see behind
    the panel — but history can say what is usually back there.

DESIGN RULE
    The flag must be CONSUMED, never generated and ignored. In the MVP it is
    consumed by the reviewer: every candidate is named on the review screen
    and counted in the routing reasons. It does NOT reduce confidence yet,
    because a candidate fires on nearly every claim and weighting it without
    observed rates would be inventing evidence (see confidence.py). The
    penalty switches on, rate-weighted, once a real corpus supplies rates.
"""

import json
import os

from config import DATA_DIR
from pipeline.models import HiddenDamageCandidate

_CACHE: dict | None = None


def _rules() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(os.path.join(DATA_DIR, "hidden_damage_rules.json"), encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def lookup(damaged_panels: list[str], vehicle_label: str) -> list[HiddenDamageCandidate]:
    """STUB BOUNDARY. Replace this body with a retrieval query; change nothing else.

    `vehicle_label` is unused by the stub but is part of the production
    signature, because real comparables are vehicle-specific.
    """
    patterns = _rules()["patterns"]
    out: list[HiddenDamageCandidate] = []
    seen: set[str] = set()

    for panel in damaged_panels:
        for entry in patterns.get(panel, []):
            if entry["part"] in seen:
                continue
            seen.add(entry["part"])
            out.append(
                HiddenDamageCandidate(
                    part=entry["part"],
                    rationale=entry["rationale"],
                    observed_rate=None,   # stub: no real corpus to measure
                )
            )
    return out


def retrieval_density(damaged_panels: list[str]) -> float:
    """How well-covered is this damage pattern by comparable history?

    A real implementation returns a function of how many close comparables
    exist. The stub approximates it by how many of the damaged panels appear
    in the rules table at all, which at least makes the signal move.
    """
    if not damaged_panels:
        return 0.0
    patterns = _rules()["patterns"]
    known = sum(1 for p in damaged_panels if p in patterns)
    return round(known / len(damaged_panels), 3)


IS_STUBBED = True
STUB_NOTE = (
    "Hidden damage candidates come from a hand-written rules table, not from "
    "a claims corpus. Observed rates are unavailable. This is the highest "
    "delivery-risk component in the MVP: if a carrier's historical data is "
    "poorly structured, it degrades to generic rules by damage type."
)
