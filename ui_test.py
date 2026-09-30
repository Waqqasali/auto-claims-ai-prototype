"""Exercise the Streamlit script itself for every demo scenario.

An HTTP health check only proves the server started. This runs the actual
script and inspects what it rendered, which is how a bad emoji argument and a
deprecated parameter were both caught.

Every scenario runs twice, once with the design rationale toggle off and once
with it on, because the toggle changes which branches execute.
"""
import re
import sys

from streamlit.testing.v1 import AppTest

# CLM-1002 attempt 2 is deliberately absent: it is a claim awaiting evidence,
# so it has no routing tier. It has its own assertion further down.
CASES = [("CLM-1001", 1), ("CLM-1002", 1), ("CLM-1003", 1),
         ("CLM-1004", 1), ("CLM-1005", 1), ("CLM-1006", 1)]
TIERS = ["VERIFY", "STARTING POINT", "LOW CONFIDENCE", "MORE PHOTOS NEEDED",
         "ESCALATED TO AGENT", "NOT PROCESSED"]

fails = 0
for claim_id, attempt in CASES:
    at = AppTest.from_file("app.py", default_timeout=120)
    at.run()
    if at.exception:
        print(f"[FAIL] boot: {[e.message for e in at.exception]}")
        fails += 1
        continue

    at.sidebar.selectbox[0].set_value(claim_id).run()
    at.sidebar.radio[0].set_value(attempt).run()
    if at.exception:
        print(f"[FAIL] {claim_id}/{attempt}: {[e.message for e in at.exception]}")
        fails += 1
        continue

    # The routing banner is st.html, not st.markdown, so both have to be
    # searched. Looking in only one is how this check silently degraded to "?"
    # while still reporting a pass.
    rendered = " ".join(
        str(getattr(e, "value", "") or getattr(e, "body", ""))
        for e in list(at.markdown) + list(at.get("html"))
    )
    tier = next((t for t in TIERS if t in rendered), None)
    if tier is None:
        print(f"[FAIL] {claim_id}/{attempt}: no routing tier rendered")
        fails += 1
        continue
    quiet = len(at.caption)

    # Rationale on: the commentary branches must render without error, and
    # must actually add something, or the toggle is wired to nothing.
    at.sidebar.toggle[0].set_value(True).run()
    if at.exception:
        print(f"[FAIL] {claim_id}/{attempt} rationale: "
              f"{[e.message for e in at.exception]}")
        fails += 1
        continue
    loud = len(at.caption)
    if loud <= quiet:
        print(f"[FAIL] {claim_id}/{attempt}: rationale toggle added nothing "
              f"({quiet} -> {loud} captions)")
        fails += 1
        continue

    print(f"[ OK ] {claim_id} att{attempt}  tier={tier:<22} "
          f"blocks={len(at.markdown) + len(at.get('html')):<3} "
          f"err={len(at.error)} warn={len(at.warning)} captions {quiet}->{loud}")


# --------------------------------------------------------------------------
# A claim awaiting a resubmission renders a waiting state, not an assessment
# and not an error. Nothing should be assessed before evidence arrives.
# --------------------------------------------------------------------------

at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1002").run()
at.sidebar.radio[0].set_value(2).run()
if at.exception:
    print(f"[FAIL] awaiting: {[e.message for e in at.exception]}")
    fails += 1
else:
    shown = " ".join(
        str(getattr(e, "value", "") or getattr(e, "body", ""))
        for e in list(at.markdown) + list(at.get("html")) + list(at.caption)
    )
    if "AWAITING RESUBMISSION" not in shown:
        print("[FAIL] awaiting: CLM-1002 attempt 2 did not render the waiting state")
        fails += 1
    elif any(t in shown for t in ("VERIFY", "STARTING POINT", "LOW CONFIDENCE")):
        print("[FAIL] awaiting: assessed a claim with no evidence")
        fails += 1
    else:
        print("[ OK ] awaiting resubmission     no assessment without evidence")


# --------------------------------------------------------------------------
# Override capture. This is the product's core claim — no change without a
# reason code — and it had no coverage at all until an add/delete bug in the
# estimate table went unnoticed.
# --------------------------------------------------------------------------

OVERRIDE_CASES = [
    ("no change",    {}, 0),
    ("edited price", {"edited_rows": {0: {"price": 500.0}}}, 1),
    ("added line",   {"added_rows": [{"operation": "replace",
                                      "part": "headlamp assembly"}]}, 1),
    ("deleted line", {"deleted_rows": [2]}, 1),
    ("all three",    {"edited_rows": {0: {"price": 500.0}},
                      "added_rows": [{"operation": "replace",
                                      "part": "headlamp assembly"}],
                      "deleted_rows": [2]}, 3),
]

for label, delta, expected in OVERRIDE_CASES:
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.sidebar.selectbox[0].set_value("CLM-1001").run()
    at.session_state["edit::CLM-1001::1"] = {
        "edited_rows": delta.get("edited_rows", {}),
        "added_rows": delta.get("added_rows", []),
        "deleted_rows": delta.get("deleted_rows", []),
    }
    at.run()

    if at.exception:
        print(f"[FAIL] override/{label}: {[e.message for e in at.exception]}")
        fails += 1
        continue

    text = " ".join(
        str(getattr(e, "value", "") or getattr(e, "body", ""))
        for e in list(at.markdown) + list(at.caption)
    )
    m = re.search(r"\*\*(\d+) change\(s\) pending", text)
    found = int(m.group(1)) if m else 0

    if found != expected:
        print(f"[FAIL] override/{label}: expected {expected} pending change(s), "
              f"found {found}")
        fails += 1
        continue

    # A change must never be recordable without somewhere to justify it.
    if expected and len(at.selectbox) < expected:
        print(f"[FAIL] override/{label}: {expected} change(s) but only "
              f"{len(at.selectbox)} reason selector(s)")
        fails += 1
        continue

    print(f"[ OK ] override {label:14} pending={found} "
          f"reason selectors={len(at.selectbox)}")


# --------------------------------------------------------------------------
# Decision gating. A reviewer must never be able to record a decision without
# saying why: no outcome, no rejection reason, or an unjustified change all
# hold the button. This is the product's central claim, so it is asserted.
# --------------------------------------------------------------------------

KEY = "edit::CLM-1001::1"

GATING = [
    # label,                       delta,                          outcome,                reject reason,  codes,  should enable
    ("nothing chosen",             {},                             None,                   None,           [],     False),
    ("approve, no changes",        {},                             "Approve as reviewed",  None,           [],     True),
    ("reject without a reason",    {},                             "Reject and rebuild",   None,           [],     False),
    ("reject with a reason",       {},                             "Reject and rebuild",
                                   "evidence inadequate for assessment",                                   [],     True),
    ("change without a code",      {"edited_rows": {0: {"price": 500.0}}},
                                   "Approve with changes",         None,                   [],             False),
    ("change with a code",         {"edited_rows": {0: {"price": 500.0}}},
                                   "Approve with changes",         None,     ["pricing wrong"],            True),
]

for label, delta, outcome, reject_reason, codes, should_enable in GATING:
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.sidebar.selectbox[0].set_value("CLM-1001").run()
    at.session_state[KEY] = {
        "edited_rows": delta.get("edited_rows", {}),
        "added_rows": delta.get("added_rows", []),
        "deleted_rows": delta.get("deleted_rows", []),
    }
    if outcome is not None:
        at.session_state[f"outcome_{KEY}"] = outcome
    if reject_reason is not None:
        at.session_state[f"reject_{KEY}"] = reject_reason
    for i, code in enumerate(codes):
        at.session_state[f"reason_{KEY}_{i}"] = code
    at.run()

    if at.exception:
        print(f"[FAIL] gating/{label}: {[e.message for e in at.exception]}")
        fails += 1
        continue

    buttons = [b for b in at.button if "Record decision" in b.label]
    if not buttons:
        print(f"[FAIL] gating/{label}: no Record decision button rendered")
        fails += 1
        continue

    enabled = not buttons[0].disabled
    if enabled != should_enable:
        want = "enabled" if should_enable else "disabled"
        print(f"[FAIL] gating/{label}: button should be {want}")
        fails += 1
        continue

    # Rejecting must always offer somewhere to say why.
    if outcome == "Reject and rebuild":
        offered = any("rejecting" in str(getattr(sb, "label", "")).lower()
                      for sb in at.selectbox)
        if not offered:
            print(f"[FAIL] gating/{label}: rejection reason field missing")
            fails += 1
            continue

    print(f"[ OK ] gating {label:26} "
          f"button={'enabled' if enabled else 'disabled'}")

# --------------------------------------------------------------------------
# Section order and tooltips. Confidence must render AFTER the estimate: the
# score is only defensible once the reviewer has seen the line items and the
# coverage score it was computed from. Ordering is easy to undo by accident in
# a single-file Streamlit script, so it is asserted rather than assumed.
# --------------------------------------------------------------------------

at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1001").run()

if at.exception:
    print(f"[FAIL] order: {[e.message for e in at.exception]}")
    fails += 1
else:
    heads = [str(getattr(h, "value", "") or getattr(h, "body", ""))
             for h in at.subheader]

    def idx(needle):
        return next((i for i, h in enumerate(heads) if needle in h), None)

    i_ev, i_est, i_conf = idx("Evidence"), idx("Draft estimate"), idx("Confidence")
    if None in (i_ev, i_est, i_conf):
        print(f"[FAIL] order: a section is missing. Found: {heads}")
        fails += 1
    elif not i_ev < i_est < i_conf:
        print(f"[FAIL] order: expected Evidence < Draft estimate < Confidence, "
              f"got {i_ev} < {i_est} < {i_conf}")
        fails += 1
    else:
        print(f"[ OK ] order  Evidence({i_ev}) -> estimate({i_est}) "
              f"-> confidence({i_conf})")

    # Every score on the page must carry an explanation of what produced it.
    labels = {str(getattr(m, "label", "")): getattr(m, "help", None)
              for m in at.metric}
    want = ["Claim confidence", "Weakest line item", "Evidence coverage",
            "Retrieval density", "Cross-stage agreement"]
    missing = [w for w in want if not labels.get(w)]
    if missing:
        print(f"[FAIL] tooltips: no help text on {missing}")
        fails += 1
    else:
        print(f"[ OK ] tooltips  {len(want)} scores carry help text")

    # Coverage is shown twice by design: under the photographs it measured,
    # and again as a confidence signal. Both must be present.
    if sum(1 for m in at.metric
           if "Evidence coverage" in str(getattr(m, "label", ""))) < 2:
        print("[FAIL] coverage: not shown both under Evidence and in Confidence")
        fails += 1
    else:
        print("[ OK ] coverage  shown under the evidence and as a signal")


# --------------------------------------------------------------------------
# The Navigator resubmission is the happy path in the demo, so the numbers it
# produces are pinned. 0.88 coverage is set deliberately to match the weakest
# line item; if either drifts the demo silently changes tier.
# --------------------------------------------------------------------------

from pipeline import run as _run  # noqa: E402

_paths = [f"samples/navigator_wheel_{n}.jpg"
          for n in ("closeup", "angle", "context")]
_r = _run.run("CLM-1002", _paths, attempt=2, user_photos=True)
_b = _r.confidence
_sig = (_b.line_item_floor, _b.evidence_coverage,
        _b.retrieval_density, _b.cross_stage_agreement)

if _r.decision.tier != "verify":
    print(f"[FAIL] navigator: tier is {_r.decision.tier}, expected verify")
    fails += 1
elif (_b.evidence_coverage, _b.line_item_floor) != (0.88, 0.88):
    print(f"[FAIL] navigator: coverage/floor are "
          f"{_b.evidence_coverage}/{_b.line_item_floor}, expected 0.88/0.88")
    fails += 1
elif min(_sig) < 0.80:
    # Anchoring on the weakest signal must reach the same tier as the weighted
    # sum, or the demo depends on which formula is in force.
    print(f"[FAIL] navigator: weakest signal {min(_sig):.2f} would not verify")
    fails += 1
else:
    print(f"[ OK ] navigator  weighted {_b.claim_confidence:.2f} / "
          f"anchored {min(_sig):.2f}, both verify")

# A good score must not be unconditional: bad files still fail the checks.
_bad = _run.run("CLM-1002", ["samples/bad_blurry.jpg", "samples/bad_dark.jpg"],
                attempt=2, user_photos=True)
if _bad.evidence.coverage_score > 0.40:
    print(f"[FAIL] navigator: blurry upload scored "
          f"{_bad.evidence.coverage_score:.2f}; the quality clamp did not hold")
    fails += 1
else:
    print("[ OK ] navigator  blurry upload still clamped to 0.40")


print("FAILURES:", fails)
sys.exit(1 if fails else 0)
