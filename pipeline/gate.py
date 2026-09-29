"""Tier 1: the processing gate.

This is NOT a capability gate. Every exclusion here is a legal, regulatory
or wasted-spend reason. None of them are "the model might do a bad job" —
those are handled downstream by confidence and routing.

Why the distinction matters: a narrow processing gate is self-confirming.
If the system only ever sees claims inside a band someone guessed at, it can
never generate the evidence needed to discover where the real boundary is.
Process broadly, automate narrowly.

No AI here, deliberately. This is the safety boundary, so it must be
deterministic, repeatable and inspectable.
"""

import json
import os
from datetime import datetime

from config import DATA_DIR
from pipeline.models import ClaimContext


def load_claim_context(claim_id: str) -> ClaimContext:
    """Read claim data from the stubbed policy system."""
    with open(os.path.join(DATA_DIR, "policies.json"), encoding="utf-8") as fh:
        payload = json.load(fh)

    record = payload["claims"].get(claim_id)
    if record is None:
        raise KeyError(f"No claim record for {claim_id}")

    return ClaimContext(
        claim_id=claim_id,
        loss_date=datetime.fromisoformat(record["loss_date"]),
        policy_in_force=record["policy_in_force"],
        coverage_applies=record["coverage_applies"],
        deductible=record["deductible"],
        injury_reported=record["injury_reported"],
        vehicle_count=record["vehicle_count"],
        liability_disputed=record["liability_disputed"],
        open_siu_flag=record["open_siu_flag"],
        obvious_total_loss=record["obvious_total_loss"],
        vehicle_year=record["vehicle_year"],
        vehicle_make=record["vehicle_make"],
        vehicle_model=record["vehicle_model"],
    )


def list_claims() -> list[tuple[str, str]]:
    """(claim_id, scenario description) for the UI picker."""
    with open(os.path.join(DATA_DIR, "policies.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    return [
        (cid, rec.get("_scenario", ""))
        for cid, rec in payload["claims"].items()
    ]


def evaluate(ctx: ClaimContext) -> tuple[bool, list[str]]:
    """Return (may_process, reasons_not_to).

    Five exclusions. Each one is here because processing would create legal
    exposure or waste spend, never because the assessment would be difficult.
    """
    reasons: list[str] = []

    if ctx.injury_reported:
        reasons.append(
            "Bodily injury reported. A damage assessment on an injury claim "
            "creates a document that can be drawn into litigation for a purpose "
            "it was not built for. Different workflow, different exposure."
        )

    if not ctx.policy_in_force or not ctx.coverage_applies:
        reasons.append(
            "Policy not in force or applicable coverage not carried at the loss "
            "date. No compute is spent assessing a claim that will not be paid."
        )

    if ctx.open_siu_flag:
        reasons.append(
            "Open Special Investigation Unit case. An automated assessment "
            "should not produce a document that interferes with an active "
            "fraud investigation."
        )

    if ctx.vehicle_count > 1 and ctx.liability_disputed:
        reasons.append(
            "Multi-vehicle loss with disputed liability. Same litigation "
            "exposure concern as an injury claim."
        )

    if ctx.obvious_total_loss:
        reasons.append(
            "Vehicle is an evident total loss. Repair line items serve no "
            "purpose. Note this is deliberately narrow: many carriers determine "
            "total loss BY comparing a repair estimate against actual cash "
            "value, so only already-evident total losses are excluded here."
        )

    return (len(reasons) == 0), reasons
