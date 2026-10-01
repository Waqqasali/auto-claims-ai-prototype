"""ADAS zone flagging.

Why this exists: CCC Crash Course data shows calibrations now appear on
35.6% of DRP estimates (Q3 2025), up from 26.9% a year earlier, and 51.5% of
those calibrations appear on SUPPLEMENTS rather than initial estimates. Half
the time this work is missed at estimate time, and it is invisible to a
photograph.

What this module does NOT do, and why:
It does not add a priced calibration line item. A photo cannot establish that
calibration is actually required — the damage might be a scuff on the bumper
skin nowhere near the radar bracket. Charging on suspicion would overstate
the estimate, which is a different error and one that starts disputes with
shops. So the honest output is a risk flag that reduces confidence and
changes routing, not a number.

Not AI. The VLM identifies which panels are damaged; this module intersects
that against a reference table. Deterministic.
"""

import json
import os

from config import DATA_DIR
from pipeline.models import ClaimContext

_CACHE: dict | None = None


def _table() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(os.path.join(DATA_DIR, "adas_zones.json"), encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def panel_vocabulary() -> list[str]:
    """The canonical panel names. The VLM is constrained to these so its
    output can be intersected with the reference tables without fuzzy matching.
    """
    return _table()["_panel_vocabulary"]


def vehicle_key(ctx: ClaimContext) -> str:
    return f"{ctx.vehicle_year}|{ctx.vehicle_make.lower()}|{ctx.vehicle_model.lower()}"


def sensors_for_vehicle(ctx: ClaimContext) -> dict:
    """Panel -> list of sensors, for this vehicle. Empty dict if unknown."""
    entry = _table()["vehicles"].get(vehicle_key(ctx), {})
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def is_known_vehicle(ctx: ClaimContext) -> bool:
    return vehicle_key(ctx) in _table()["vehicles"]


def involved_zones(ctx: ClaimContext, damaged_panels: list[str]) -> list[dict]:
    """Intersect damaged panels against this vehicle's sensor map.

    Returns one entry per affected panel:
        {"panel": ..., "sensors": [...]}
    """
    sensors = sensors_for_vehicle(ctx)
    hits = []
    for panel in damaged_panels:
        if panel in sensors:
            hits.append({"panel": panel, "sensors": sensors[panel]})
    return hits


def describe(hits: list[dict]) -> list[str]:
    """Human-readable lines for the review screen."""
    out = []
    for hit in hits:
        sensor_list = ", ".join(hit["sensors"])
        out.append(
            f"{hit['panel'].replace('_', ' ')} carries: {sensor_list}. "
            "Repair here will likely require recalibration, which cannot be "
            "confirmed from photographs."
        )
    return out
