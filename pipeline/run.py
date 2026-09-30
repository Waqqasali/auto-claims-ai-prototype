"""Orchestrator. Runs one claim through the pipeline.

Stage order matters and is deliberate:

  0  gate          Tier 1 exclusions. Legal / wasted-spend only. No AI.
  1a imaging       Deterministic quality measurement. No AI.
  1b authenticity  Metadata, provenance, reuse. Mostly no AI.
  1c coverage      VLM judges sufficiency. STOPS HERE if inadequate.
  2  assessment    VLM produces line items. Only runs on adequate evidence.
  3  costing       Price lookup (stubbed). No AI.
  3b adas          Panel/sensor intersection. No AI.
  3c comparables   Hidden damage candidates (stubbed). No AI.
  4  confidence    Deterministic arithmetic over the above.
  5  routing       Deterministic tier decision.

Note stage 1c gates stage 2. Assessing damage from photos already judged
inadequate would produce a confident answer built on bad evidence, which is
the exact failure this product exists to prevent.
"""

import os

from config import VLM_PROVIDER
from pipeline import adas, authenticity, comparables, confidence, evidence, gate, imaging, pricing, routing
from pipeline.models import Assessment, ClaimResult, LineItem, Photo
from providers.vlm_base import get_provider


def _build_photo(path: str) -> Photo:
    photo = Photo(filename=os.path.basename(path), path=path)
    m = imaging.measure(path)
    photo.width = m["width"]
    photo.height = m["height"]
    photo.sharpness = m["sharpness"]
    photo.brightness = m["brightness"]
    photo.exif_present = m["exif_present"]
    photo.capture_time = m["capture_time"]
    photo.device = m["device"]
    photo.editing_software = m["editing_software"]
    photo.perceptual_hash = m["perceptual_hash"]
    return photo


def run(
    claim_id: str,
    photo_paths: list[str],
    attempt: int = 1,
    provider_name: str | None = None,
    record_hashes: bool = True,
    user_photos: bool = False,
) -> ClaimResult:
    ctx = gate.load_claim_context(claim_id)
    ctx.user_supplied_photos = user_photos
    result = ClaimResult(context=ctx, attempt=attempt)

    # --- Stage 0: processing gate ----------------------------------------
    may_process, reasons = gate.evaluate(ctx)
    result.gate_passed = may_process
    result.gate_reasons = reasons
    if not may_process:
        result.decision = routing.Decision(
            tier="not_processed",
            headline="Claim excluded from automated assessment",
            reasons=reasons,
        )
        return result

    provider = get_provider(provider_name or VLM_PROVIDER)
    vocabulary = adas.panel_vocabulary()

    # --- Stage 1a/1b: evidence measurement and authenticity ---------------
    photos: list[Photo] = []
    for path in photo_paths:
        p = _build_photo(path)
        p = evidence.check_quality(p)
        p = authenticity.screen(p, ctx, record_hash=record_hashes)
        photos.append(p)
    result.photos = photos

    auth_flags = authenticity.summarize(photos)

    # --- Stage 1c: coverage judgement (VLM) -------------------------------
    coverage = provider.assess_coverage(photos, ctx, vocabulary)
    verdict = evidence.evaluate(photos, coverage, attempt)
    result.evidence = verdict

    if verdict.status != "sufficient":
        # Deliberately do NOT assess damage on inadequate evidence.
        result.decision = routing.Decision(
            tier="escalated" if verdict.status == "escalate" else "re_request",
            headline=(
                "Escalated to a claims agent"
                if verdict.status == "escalate"
                else f"Additional photos requested (attempt {attempt} of "
                     f"{evidence.MAX_REQUEST_ATTEMPTS})"
            ),
            reasons=(
                [verdict.escalation_reason]
                if verdict.status == "escalate"
                else ["Evidence insufficient; specific re-request issued."]
            ),
        )
        return result

    # --- Stage 2: damage assessment (VLM) ---------------------------------
    raw = provider.assess_damage(photos, ctx, vocabulary)
    items = [
        LineItem(
            operation=li.get("operation", ""),
            part=li.get("part", ""),
            panel=li.get("panel", ""),
            damage_type=li.get("damage_type", ""),
            severity=li.get("severity", ""),
            reasoning=li.get("reasoning", ""),
            confidence=float(li.get("confidence", 0.0)),
        )
        for li in raw.get("line_items", [])
    ]

    assessment = Assessment(
        line_items=items,
        damage_panels=raw.get("damage_panels", []),
        model_notes=raw.get("notes", ""),
    )

    # --- Stage 3: costing, ADAS, comparables ------------------------------
    assessment.line_items = pricing.price_all(assessment.line_items)
    adas_hits = adas.involved_zones(ctx, assessment.damage_panels)
    assessment.adas_zones_involved = [h["panel"] for h in adas_hits]
    assessment.hidden_damage = comparables.lookup(
        assessment.damage_panels, ctx.vehicle_label
    )
    result.assessment = assessment

    # --- Stage 4: confidence ----------------------------------------------
    # Retrieval density is measured over panels that actually carry damage.
    # A 'blend' line item names an ADJACENT undamaged panel painted for colour
    # match, so including it would understate how well the real damage pattern
    # is covered by history.
    damaged_panels = sorted({
        li.panel for li in assessment.line_items
        if li.panel and li.operation.lower() != "blend"
    })

    result.confidence = confidence.compute(
        assessment=assessment,
        evidence_coverage=verdict.coverage_score,
        retrieval_density=comparables.retrieval_density(damaged_panels),
        cross_stage_agreement=pricing.agreement_score(assessment.line_items),
        adas_hits=adas_hits,
        authenticity_flags=auth_flags,
    )

    # --- Stage 5: routing ---------------------------------------------------
    result.decision = routing.decide(
        result.confidence, assessment, adas_hits, auth_flags
    )
    return result
