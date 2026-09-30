"""Claims agent review screen.

This is the human control surface, and it is the most important non-AI
component in the product. It is also the one that gets removed first, so it
has to earn that by proving itself.

Two things it must do:
  1. Show the reviewer everything the system used: photos, line items,
     reasoning, confidence arithmetic, flags. Nothing hidden.
  2. Capture overrides WITH A REASON CODE. Free text cannot be aggregated,
     and aggregation is the entire point — override reasons are the training
     signal and the evidence base for eventually removing this gate.

In the MVP every claim that clears the Tier 1 gate lands here. Nothing is
auto-approved.
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import (
    MAX_REQUEST_ATTEMPTS,
    OVERRIDE_LOG,
    RUNTIME_DIR,
    TIER_STARTING_POINT_MIN,
    TIER_VERIFY_MIN,
    VLM_PROVIDER,
)
from pipeline import adas, comparables, gate, pricing, routing, run

st.set_page_config(
    page_title="AI Assisted Damage Assessment and Claim Triage",
    page_icon="🚗",
    layout="wide",
)

# Layout values the theme keys cannot reach. Kept deliberately small: these
# selectors are Streamlit internals and are the first thing to break on a
# version bump, so anything that can be done with a theme key is done there.
st.html(
    """<style>
      [data-testid="stSidebar"] { width: 296px !important; }
      .block-container { padding: 2rem 2.5rem 4rem; max-width: 1240px; }
    </style>"""
)

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

# Short, specific, mutually exclusive. Free text is optional and secondary.
REASON_CODES = [
    "wrong part",
    "wrong operation",
    "missed damage",
    "over-scoped",
    "wrong severity",
    "pricing wrong",
    "not repairable as written",
]

SCENARIO_PHOTOS = {
    "CLM-1001": ["good_a.jpg", "good_b.jpg", "good_c.jpg"],
    "CLM-1002": ["bad_blurry.jpg", "bad_dark.jpg", "bad_lowres.jpg"],
    "CLM-1003": ["bumper_a.jpg", "bumper_b.jpg", "bumper_c.jpg"],
    "CLM-1004": ["stale_timestamp.jpg", "stale_timestamp_2.jpg"],
    "CLM-1005": ["good_a.jpg"],
    "CLM-1006": ["good_a.jpg"],
}

# (accent, tint) per routing tier. The dot and the rule carry the colour; the
# pill carries the tint; badge text stays ink so the tier reads as a label
# rather than as an alarm.
TIER_STYLE = {
    "verify":         ("#2E8B6F", "#E3F1EC"),
    "starting_point": ("#C98A1A", "#F7ECD6"),
    "low_confidence": ("#B33A3A", "#F5E1E1"),
    "re_request":     ("#4A6580", "#ECF1F6"),
    "escalated":      ("#1B3247", "#DEE5EE"),
    "not_processed":  ("#B33A3A", "#F5E1E1"),
}

INK, MUTED, BORDER = "#0D1B2A", "#4A6580", "#DEE5EE"
CONFIDENCE_BAR = "#4A6580"   # magnitude, never judgement. Not the orange accent.


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------

with st.sidebar:
    st.title("Damage Assessment and Claim Triage")
    st.caption("AI assisted assessment and routing, between damage "
               "documentation and estimate approval.")

    claims = gate.list_claims()
    labels = {cid: f"{cid}" for cid, _ in claims}
    claim_id = st.selectbox(
        "Claim", [c for c, _ in claims], format_func=lambda c: labels[c]
    )
    scenario = dict(claims).get(claim_id, "")
    if scenario:
        st.info(scenario, icon="🎬")

    attempt = st.radio(
        "Submission attempt", [1, 2], horizontal=True,
        help="Attempt 2 on CLM-1002 demonstrates the re-request cap and the "
             "bail-out to a human.",
    )

    uploaded = st.file_uploader(
        "Or upload your own photos",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        help="Uploaded photos run through the real quality and authenticity "
             "checks. In mock mode the damage assessment stays scripted.",
    )

    st.divider()
    live = VLM_PROVIDER == "anthropic"
    st.metric("Vision provider", VLM_PROVIDER.upper())
    if live:
        st.success("Live model calls", icon="🟢")
    else:
        st.warning(
            "Mock mode. Image quality, EXIF, C2PA and perceptual hashing are "
            "REAL in every mode. Damage line items are scripted. Set "
            "`VLM_PROVIDER=anthropic` with an API key for live assessment.",
            icon="🟡",
        )

    st.divider()
    with st.expander("Stubbed components"):
        st.caption(f"**Pricing** — {pricing.STUB_NOTE}")
        st.caption(f"**Comparables** — {comparables.STUB_NOTE}")
        st.caption("**Policy system** — read from a local JSON fixture.")

    SHOW_RATIONALE = st.toggle(
        "Show design rationale",
        value=False,
        help="Explains why each part of this screen works the way it does. Off "
             "by default: a claims agent needs the decision, not the argument "
             "behind it.",
    )


def rationale(text):
    """Design commentary, shown only when the reviewer asks for it.

    The working surface carries what a claims agent needs to act. Why it is
    built this way belongs in the PRD, and here behind a toggle. Mixing the
    two is how a product screen turns into a pitch deck.
    """
    if SHOW_RATIONALE:
        st.caption(text)


# --------------------------------------------------------------------------
# Run the pipeline
# --------------------------------------------------------------------------

if uploaded:
    os.makedirs(os.path.join(RUNTIME_DIR, "uploads"), exist_ok=True)
    paths = []
    for f in uploaded:
        dest = os.path.join(RUNTIME_DIR, "uploads", f.name)
        with open(dest, "wb") as fh:
            fh.write(f.getbuffer())
        paths.append(dest)
else:
    paths = [os.path.join(SAMPLES, n) for n in SCENARIO_PHOTOS.get(claim_id, [])]
    if attempt == 2 and claim_id == "CLM-1002":
        paths = paths[:2]

if not paths:
    st.warning("No photos for this claim. Upload some in the sidebar.")
    st.stop()

result = run.run(claim_id, paths, attempt=attempt, record_hashes=False)
ctx = result.context


# --------------------------------------------------------------------------
# Header and decision
# --------------------------------------------------------------------------

st.markdown(f"### {claim_id} · {ctx.vehicle_label}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Loss date", ctx.loss_date.strftime("%d %b %Y"))
c2.metric("Deductible", f"${ctx.deductible:,.0f}")
c3.metric("Photos", len(result.photos))
c4.metric("ADAS data", "on file" if adas.is_known_vehicle(ctx) else "unknown vehicle")

decision = result.decision
tier = decision.tier
accent, tint = TIER_STYLE.get(tier, (MUTED, "#ECF1F6"))

st.html(
    f"""<div style="background:#FFFFFF;border:1px solid {BORDER};
    border-left:4px solid {accent};border-radius:10px;padding:20px 24px;
    margin:16px 0 4px 0;">
      <span style="display:inline-flex;align-items:center;gap:8px;
      background:{tint};border-radius:999px;padding:4px 12px 4px 10px;">
        <span style="width:8px;height:8px;border-radius:50%;
        background:{accent};display:inline-block;"></span>
        <span style="font-size:11px;font-weight:600;letter-spacing:0.12em;
        color:{INK};">{routing.TIER_LABELS.get(tier, tier.upper())}</span>
      </span>
      <div style="font-family:'Saira',system-ui,sans-serif;font-size:24px;
      font-weight:600;line-height:1.2;color:{INK};margin-top:12px;">
      {decision.headline}</div>
      <div style="font-size:13.5px;color:{MUTED};margin-top:6px;">
      {routing.TIER_GUIDANCE.get(tier, "")}</div>
    </div>"""
)

for reason in decision.reasons:
    st.markdown(f"- {reason}")


# --------------------------------------------------------------------------
# Tier 1 gate rejection: stop here
# --------------------------------------------------------------------------

if not result.gate_passed:
    st.divider()
    st.subheader("Why this claim was not processed")
    rationale(
        "Every Tier 1 exclusion is a legal or wasted-spend reason. None of them "
        "are 'the model might do badly' — those are handled downstream by "
        "confidence and routing. A narrow processing gate is self-confirming: "
        "if the system only ever sees easy claims it can never learn where the "
        "real boundary sits."
    )
    for r in result.gate_reasons:
        st.error(r, icon="⛔")
    st.stop()


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

st.divider()
st.subheader("Evidence")

cols = st.columns(min(len(result.photos), 4))
for i, photo in enumerate(result.photos):
    with cols[i % len(cols)]:
        st.image(photo.path, width='stretch')
        st.caption(f"**{photo.filename}** · {photo.width}×{photo.height}")
        st.caption(
            f"sharpness {photo.sharpness:.0f} · brightness {photo.brightness:.0f}"
        )
        if photo.quality_issues:
            for issue in photo.quality_issues:
                st.error(issue, icon="📷")
        else:
            st.success("Quality checks passed", icon="✅")

        meta = []
        meta.append("EXIF present" if photo.exif_present else "no EXIF")
        if photo.capture_time:
            meta.append(f"captured {photo.capture_time:%d %b %Y %H:%M}")
        if photo.device:
            meta.append(photo.device)
        meta.append("C2PA present" if photo.c2pa_present else "no C2PA")
        st.caption(" · ".join(meta))

        for flag in photo.authenticity_flags:
            st.warning(flag, icon="🔍")

if result.evidence and result.evidence.status == "re_request":
    st.divider()
    st.subheader("Message sent to the policyholder")
    st.caption(f"Attempt {attempt} of {MAX_REQUEST_ATTEMPTS}. After that a person takes over.")
    rationale(
        "Specific and actionable, never 'send better photos'. J.D. Power 2025: "
        "customers rating a claims experience poor or just OK carry a 52% "
        "likelihood of switching carriers, against 4% for excellent. A vague "
        "repeated ask is where an efficiency feature destroys more value than "
        "it creates."
    )
    st.code(result.evidence.instruction, language=None)
    st.info(
        "Damage assessment was NOT run. Assessing from photos already judged "
        "inadequate would produce a confident answer built on bad evidence, "
        "which is the exact failure this product exists to prevent.",
        icon="🛑",
    )
    st.stop()

if result.evidence and result.evidence.status == "escalate":
    st.divider()
    st.subheader("Handed to a claims agent")
    st.caption(
        f"The re-request cap of {MAX_REQUEST_ATTEMPTS} was reached. A person "
        "takes over from here, with the photographs and the reason each one "
        "could not be used."
    )
    st.error(result.evidence.escalation_reason, icon="👤")
    st.info(
        "No damage assessment was produced. The system stops rather than "
        "guessing from evidence it has already judged inadequate.",
        icon="🛑",
    )
    rationale(
        "Two attempts, then stop asking. A third request is where an "
        "efficiency feature starts damaging the relationship it was meant to "
        "protect, and the claim still needs handling either way. Knowing when "
        "to give up is a product decision, not a failure mode."
    )
    st.stop()


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

st.divider()
st.subheader("Confidence")

conf = result.confidence
cc1, cc2 = st.columns([1, 2])
with cc1:
    st.metric("Claim confidence", f"{conf.claim_confidence:.2f}")
    st.caption(
        f"verify ≥ {TIER_VERIFY_MIN:.2f} · starting point ≥ "
        f"{TIER_STARTING_POINT_MIN:.2f}"
    )
    st.caption("⚠️ Thresholds are placeholders, not calibrated.")
    rationale(
        "In production they are set by retrospective calibration against "
        "historical claims whose final cost, including any supplement, is "
        "already known. Naming a number before that data exists would be "
        "inventing a fact."
    )
with cc2:
    st.dataframe(
        pd.DataFrame(
            [
                {"signal": "weakest line item", "value": conf.line_item_floor},
                {"signal": "evidence coverage", "value": conf.evidence_coverage},
                {"signal": "retrieval density", "value": conf.retrieval_density},
                {"signal": "cross-stage agreement", "value": conf.cross_stage_agreement},
            ]
        ),
        hide_index=True,
        width='stretch',
        column_config={
            "value": st.column_config.NumberColumn("value", format="%.2f"),
        },
    )
    # A penalty is subtracted from the weighted sum, not averaged in with it,
    # so showing it as a fifth signal would misdescribe the arithmetic.
    if conf.adas_penalty:
        st.caption(
            f"Less a fixed **{conf.adas_penalty:.2f}** ADAS calibration penalty."
        )

with st.expander("Show the arithmetic"):
    for line in conf.explanation:
        st.markdown(f"- {line}")
    st.caption(
        "Anchored on the weakest line item rather than the mean. Ten items at "
        "0.90 and one at 0.60 is not a 0.87 claim — one badly wrong line ruins "
        "an estimate, and averaging buries exactly the item that matters."
    )


# --------------------------------------------------------------------------
# Risks
# --------------------------------------------------------------------------

assessment = result.assessment
adas_hits = adas.involved_zones(ctx, assessment.damage_panels)

if adas_hits or assessment.hidden_damage:
    st.divider()
    st.subheader("Risks the photos cannot resolve")

if adas_hits:
    st.markdown("**Calibration risk**")
    for line in adas.describe(adas_hits):
        st.warning(line, icon="📡")
    st.caption("No calibration line item is priced. This is a routing signal, not a charge.")
    rationale(
        "A photo cannot establish that calibration is required — the damage may "
        "be a scuff nowhere near the sensor bracket. Charging on suspicion "
        "overstates the estimate and starts disputes with shops. CCC Q3 2025: "
        "calibrations appear on 35.6% of DRP estimates, up from 26.9% year over "
        "year, and 51.5% of them show up on supplements rather than initial "
        "estimates."
    )

if assessment.hidden_damage:
    st.markdown("**Possible damage behind the visible panels**")
    for cand in assessment.hidden_damage:
        rate = (
            f"{cand.observed_rate:.0%} of comparable claims"
            if cand.observed_rate is not None
            else "rate unavailable (stubbed corpus)"
        )
        st.info(f"**{cand.part}** — {cand.rationale} _({rate})_", icon="🔧")
    st.caption("Informational. No confidence penalty is applied in the MVP.")
    rationale(
        "Without observed rates from a real claims corpus any weight would be "
        "arbitrary, and the signal fires on nearly every claim — a signal that "
        "fires on everything carries no information. Becomes rate-weighted once "
        "comparables are connected."
    )


# --------------------------------------------------------------------------
# Line items and override capture
# --------------------------------------------------------------------------

st.divider()
st.subheader("Draft estimate")
st.caption(
    f"Total \\${assessment.estimate_total:,.2f} before deductible "
    f"(\\${ctx.deductible:,.0f}). Pricing is stubbed — treat totals as illustrative."
)

original = pd.DataFrame(
    [
        {
            "operation": li.operation,
            "part": li.part,
            "panel": li.panel,
            "severity": li.severity,
            "price": li.price if li.price is not None else 0.0,
            "confidence": li.confidence,
            "priced": li.priced,
        }
        for li in assessment.line_items
    ]
)

if original.empty:
    st.warning("No line items were produced.")
    st.stop()

state_key = f"edit::{claim_id}::{attempt}"
edited = st.data_editor(
    original,
    key=state_key,
    width='stretch',
    hide_index=True,
    column_config={
        "price": st.column_config.NumberColumn("price", format="$%.2f"),
        "confidence": st.column_config.ProgressColumn(
            "confidence", min_value=0.0, max_value=1.0, format="%.2f",
            color=CONFIDENCE_BAR,
        ),
        "priced": st.column_config.CheckboxColumn(
            "priced", disabled=True,
            help="Whether the costing stage could price this line. Items it "
                 "cannot price feed the cross-stage agreement signal.",
        ),
        "panel": st.column_config.TextColumn("panel", disabled=True),
    },
    num_rows="fixed",
)

with st.expander("Why the model proposed each line"):
    for li in assessment.line_items:
        st.markdown(
            f"**{li.operation} — {li.part}** _(confidence {li.confidence:.2f})_  \n"
            f"{li.reasoning}"
        )
    rationale(
        "Reasoning is what makes an override meaningful. A reviewer cannot "
        "sensibly disagree with a number that carries no explanation."
    )

# --- Detect changes ------------------------------------------------------
changes = []
for idx in range(len(original)):
    for col in ("operation", "part", "severity", "price"):
        before, after = original.at[idx, col], edited.at[idx, col]
        if isinstance(before, float) or isinstance(after, float):
            differs = abs(float(before) - float(after)) > 0.005
        else:
            differs = str(before) != str(after)
        if differs:
            changes.append(
                {
                    "row": idx,
                    "line": f"{original.at[idx, 'operation']} {original.at[idx, 'part']}",
                    "field": col,
                    "before": before,
                    "after": after,
                }
            )

st.markdown("#### Reviewer decision")

if changes:
    st.markdown(f"**{len(changes)} change(s) pending. Each needs a reason code.**")
    rationale(
        "Reason codes are mandatory and are the point of this screen. Free text "
        "cannot be aggregated, and aggregation is what turns overrides into the "
        "evidence base for removing this gate later."
    )

with st.form("override_form"):
    reasons = {}
    for i, ch in enumerate(changes):
        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.markdown(
                f"`{ch['line']}` · **{ch['field']}** "
                f"`{ch['before']}` → `{ch['after']}`"
            )
        with col_b:
            reasons[i] = st.selectbox(
                "reason", REASON_CODES, key=f"reason_{state_key}_{i}",
                label_visibility="collapsed",
            )

    note = st.text_area(
        "Optional note", placeholder="Anything the reason codes do not capture",
        height=68,
    )
    action = st.radio(
        "Outcome", ["Approve as reviewed", "Approve with changes", "Reject and rebuild"],
        horizontal=True,
    )
    submitted = st.form_submit_button("Record decision", type="primary")

if submitted:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "claim_id": claim_id,
        "attempt": attempt,
        "vehicle": ctx.vehicle_label,
        "provider": VLM_PROVIDER,
        "claim_confidence": conf.claim_confidence,
        "routing_tier": tier,
        "adas_involved": assessment.adas_zones_involved,
        "action": action,
        "note": note,
        "overrides": [
            {**ch, "before": str(ch["before"]), "after": str(ch["after"]),
             "reason_code": reasons[i]}
            for i, ch in enumerate(changes)
        ],
    }
    with open(OVERRIDE_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    st.success(
        f"Recorded. {len(changes)} override(s) written to "
        f"`runtime/overrides.jsonl`.",
        icon="✅",
    )
    rationale(
        "This record is the audit trail and the calibration input. Linking "
        "predicted confidence to realized override rate is how thresholds get "
        "set, and it is also what the NAIC model bulletin's documentation "
        "requirements are asking for — adopted in 11 states as of 2024."
    )
    st.json(record, expanded=False)

# --- Accumulated override log -------------------------------------------
if os.path.exists(OVERRIDE_LOG):
    with st.expander("Override log"):
        with open(OVERRIDE_LOG, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        st.caption(f"{len(rows)} decision(s) recorded across this session.")
        flat = []
        for r in rows:
            if r["overrides"]:
                for o in r["overrides"]:
                    flat.append({
                        "claim": r["claim_id"], "confidence": r["claim_confidence"],
                        "tier": r["routing_tier"], "line": o["line"],
                        "field": o["field"], "reason": o["reason_code"],
                    })
            else:
                flat.append({
                    "claim": r["claim_id"], "confidence": r["claim_confidence"],
                    "tier": r["routing_tier"], "line": "—", "field": "—",
                    "reason": "no change",
                })
        st.dataframe(pd.DataFrame(flat), hide_index=True, width='stretch')
