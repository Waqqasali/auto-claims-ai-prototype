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

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
