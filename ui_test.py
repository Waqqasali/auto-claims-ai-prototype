"""Exercise the Streamlit script itself for every demo scenario.

An HTTP health check only proves the server started. This runs the actual
script and inspects what it rendered, which is how a bad emoji argument and a
deprecated parameter were both caught.

Every scenario runs twice, once with the design rationale toggle off and once
with it on, because the toggle changes which branches execute.
"""
# Run against a throwaway runtime folder. These tests delete and plant ledger
# and log entries, and must never touch a presenter's real demo data.
import os as _os
import tempfile as _tempfile
_os.environ["CLAIMS_RUNTIME_DIR"] = _tempfile.mkdtemp(prefix="claims-test-")
import re
import sys

from streamlit.testing.v1 import AppTest

# CLM-1002 attempt 2 is deliberately absent: it is a claim awaiting evidence,
# so it has no routing tier. It has its own assertion further down.
CASES = [("CLM-1001", 1), ("CLM-1002", 1), ("CLM-1003", 1),
         ("CLM-1004", 1), ("CLM-1005", 1), ("CLM-1006", 1),
         ("CLM-1007", 1)]
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

PRICE_EDIT = {"edited_rows": {0: {"price": 500.0}}}
GATING = [
    # label, delta, outcome, reject reason, codes as (change id, code), should enable
    ("nothing chosen",               {}, None, None, [], False),
    ("approve, no changes",          {}, "Approve as reviewed", None, [], True),
    ("reject without a reason",      {}, "Reject and rebuild", None, [], False),
    ("reject with a reason",         {}, "Reject and rebuild",
                                     "evidence inadequate for assessment", [], True),
    ("change without a code",        PRICE_EDIT, "Approve with changes", None, [], False),
    ("change with a code",           PRICE_EDIT, "Approve with changes", None,
                                     [("edited:0:price", "pricing wrong")], True),
    # The outcome must agree with the table.
    ("approve as reviewed, but edited", PRICE_EDIT, "Approve as reviewed", None,
                                     [("edited:0:price", "pricing wrong")], False),
    ("approve with changes, none made", {}, "Approve with changes", None, [], False),
    ("negative price",               {"edited_rows": {0: {"price": -5000.0}}},
                                     "Approve with changes", None,
                                     [("edited:0:price", "pricing wrong")], False),
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
    for change_id, code in codes:
        at.session_state[f"reason_{KEY}_{change_id}"] = code
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

# --------------------------------------------------------------------------
# A blend is paint on an UNDAMAGED adjacent panel for color match, so it must
# never set the claim's confidence. CLM-1001 is the case that proves it: its
# blend line is the lowest-confidence line in the estimate and the cheapest.
# --------------------------------------------------------------------------

_m = _run.run("CLM-1001",
              ["samples/mazda6_front.jpg", "samples/mazda6_corner.jpg",
               "samples/mazda6_damage.jpg"], attempt=1, user_photos=False)
_items = _m.assessment.line_items
_blends = [li for li in _items if li.operation.lower() == "blend"]
_real = [li for li in _items if li.operation.lower() != "blend"]

if not _blends:
    print("[FAIL] blend: CLM-1001 has no blend line, so this proves nothing")
    fails += 1
elif min(li.confidence for li in _blends) >= min(li.confidence for li in _real):
    print("[FAIL] blend: the blend is no longer the weakest line, so this "
          "test has stopped testing anything")
    fails += 1
elif _m.confidence.line_item_floor != min(li.confidence for li in _real):
    print(f"[FAIL] blend: floor is {_m.confidence.line_item_floor}, expected "
          f"{min(li.confidence for li in _real)} (blend excluded)")
    fails += 1
else:
    print(f"[ OK ] blend    floor {_m.confidence.line_item_floor:.2f} from "
          f"damage lines, not the {min(li.confidence for li in _blends):.2f} blend")

# A blend-only estimate must not score 1.00 by scoring nothing at all.
from pipeline import confidence as _conf  # noqa: E402
from pipeline.models import Assessment, LineItem  # noqa: E402

_only = Assessment(line_items=[
    LineItem(operation="blend", part="left front fender",
             panel="left_front_fender", damage_type="", severity="",
             reasoning="", confidence=0.55),
])
_b2 = _conf.compute(_only, 1.0, 1.0, 1.0, [], [])
if _b2.line_item_floor != 0.55:
    print(f"[FAIL] blend: blend-only estimate scored floor "
          f"{_b2.line_item_floor}, expected the 0.55 fallback")
    fails += 1
else:
    print("[ OK ] blend    blend-only estimate falls back to the full set")


# --------------------------------------------------------------------------
# Sample photographs belonging to DIFFERENT claims must not be near-identical.
#
# A perceptual hash reads only an image's coarse luminance layout, so synthetic
# samples that share a composition hash alike no matter how much fine detail
# differs. When that happened, the authenticity screen flagged whichever
# scripted claim was opened second as a reused photograph, purely as a function
# of click order, and it dropped the Camry from 0.60 to 0.40 against the worked
# example in the PRD.
#
# This is invisible in ordinary use and only shows up on stage, so it is
# asserted rather than trusted.
# --------------------------------------------------------------------------

import itertools  # noqa: E402
import os  # noqa: E402

from pipeline import imaging as _img  # noqa: E402
from config import PHASH_DUPLICATE_DISTANCE  # noqa: E402

_CLAIM_OF = {
    **{f"mazda6_{n}.jpg": "CLM-1001" for n in ("front", "corner", "damage")},
    **{f"bad_{n}.jpg": "CLM-1002" for n in ("blurry", "dark", "lowres")},
    **{f"navigator_wheel_{n}.jpg": "CLM-1002" for n in
       ("closeup", "angle", "context")},
    **{f"bumper_{a}.jpg": "CLM-1003" for a in "abc"},
    "stale_timestamp.jpg": "CLM-1004",
    "stale_timestamp_2.jpg": "CLM-1004",
    **{f"good_{a}.jpg": "shared" for a in "abc"},
    **{f"sideswipe_{a}.jpg": "CLM-1007" for a in "abc"},
}

_samples = sorted(f for f in os.listdir("samples") if f.endswith(".jpg"))
_hashes = {f: _img.measure(os.path.join("samples", f))["perceptual_hash"]
           for f in _samples}

_unowned = [f for f in _samples if f not in _CLAIM_OF]
_clashes = []
_closest = 999
for _a, _b in itertools.combinations(_samples, 2):
    if _CLAIM_OF.get(_a, _a) == _CLAIM_OF.get(_b, _b):
        continue                      # same claim: three angles should look alike
    _d = _img.hamming(_hashes[_a], _hashes[_b])
    _closest = min(_closest, _d)
    if _d <= PHASH_DUPLICATE_DISTANCE:
        _clashes.append((_d, _a, _b))

if _unowned:
    print(f"[FAIL] samples: {_unowned} are not assigned to a claim in this "
          f"test, so they are not being checked")
    fails += 1
elif _clashes:
    print(f"[FAIL] samples: {len(_clashes)} cross-claim pair(s) within the "
          f"duplicate threshold of {PHASH_DUPLICATE_DISTANCE}:")
    for _d, _a, _b in _clashes[:5]:
        print(f"         {_d:2d}  {_a} / {_b}")
    fails += 1
else:
    print(f"[ OK ] samples  no cross-claim collisions, closest pair "
          f"{_closest} vs threshold {PHASH_DUPLICATE_DISTANCE}")


# --------------------------------------------------------------------------
# The Camry is the PRD's worked example, so its numbers are pinned to the
# document: three line items, the sensor line weakest at 0.71, the ADAS penalty
# applied, and nothing else. It must resolve to 0.60 and route as a starting
# point, from a clean ledger.
# --------------------------------------------------------------------------

import config as _cfg  # noqa: E402

if os.path.exists(_cfg.PHASH_LEDGER):
    os.remove(_cfg.PHASH_LEDGER)

_c = _run.run("CLM-1003", [f"samples/bumper_{a}.jpg" for a in "abc"],
              attempt=1, user_photos=False)
_cb = _c.confidence
if round(_cb.claim_confidence, 2) != 0.60:
    print(f"[FAIL] camry: confidence {_cb.claim_confidence:.2f}, PRD says 0.60")
    fails += 1
elif _c.decision.tier != "starting_point":
    print(f"[FAIL] camry: tier {_c.decision.tier}, PRD says starting point")
    fails += 1
elif _cb.authenticity_penalty:
    print(f"[FAIL] camry: an authenticity penalty of "
          f"{_cb.authenticity_penalty:.2f} was applied; the worked example "
          f"has only the ADAS penalty")
    fails += 1
else:
    print(f"[ OK ] camry    {_cb.claim_confidence:.2f} starting point, "
          f"ADAS penalty only, matching the PRD")


# --------------------------------------------------------------------------
# CLM-1007 is the only claim that demonstrates the low confidence tier, and
# the only one where retrieval density and cross-stage agreement fall below
# 1.00. Each of those is pinned, because the claim exists to show them.
# It must also get there honestly: no authenticity penalty, and a base score
# that is already only a starting point before the ADAS penalty applies.
# --------------------------------------------------------------------------

if os.path.exists(_cfg.PHASH_LEDGER):
    os.remove(_cfg.PHASH_LEDGER)

_s = _run.run("CLM-1007", [f"samples/sideswipe_{a}.jpg" for a in "abc"],
              attempt=1, user_photos=False)
_sb = _s.confidence
_unpriced = [li for li in _s.assessment.line_items if not li.priced]
_base = round(_sb.claim_confidence + _sb.adas_penalty + _sb.authenticity_penalty, 3)

_problems = []
if _s.decision.tier != "low_confidence":
    _problems.append(f"tier {_s.decision.tier}, expected low_confidence")
if _sb.authenticity_penalty:
    _problems.append("authenticity penalty applied; this claim has no flag")
if not _sb.adas_penalty:
    _problems.append("no ADAS penalty; the blind spot radar was not hit")
if not (_cfg.TIER_STARTING_POINT_MIN <= _base < _cfg.TIER_VERIFY_MIN):
    _problems.append(f"base {_base:.2f} is not a starting point on its own")
if _sb.retrieval_density >= 1.0:
    _problems.append("retrieval density did not drop below 1.00")
if _sb.cross_stage_agreement >= 1.0:
    _problems.append("cross-stage agreement did not drop below 1.00")
if [li.panel for li in _unpriced] != ["left_rocker_panel"]:
    _problems.append(f"unpriced lines are {[li.part for li in _unpriced]}, "
                     f"expected only the rocker")

if _problems:
    print("[FAIL] sideswipe: " + "; ".join(_problems))
    fails += 1
else:
    print(f"[ OK ] sideswipe base {_base:.2f} -> {_sb.claim_confidence:.2f} low "
          f"confidence, retrieval {_sb.retrieval_density:.2f}, agreement "
          f"{_sb.cross_stage_agreement:.2f}, rocker unpriced")


# --------------------------------------------------------------------------
# Reset demo data. runtime/ is gitignored, so it survives an unzip over an
# existing folder. A ledger left from earlier testing, in which the Navigator
# photos were once uploaded against a different claim, flags them as reused
# when they are uploaded to CLM-1002 in the demo and knocks the happy path out
# of verify. This plants exactly that state, proves it does the damage, then
# proves the Reset button removes it.
# --------------------------------------------------------------------------

import json as _json  # noqa: E402

_nav = [f"samples/navigator_wheel_{n}.jpg" for n in ("closeup", "angle", "context")]
_stale = {_img.measure(p)["perceptual_hash"]: {"claim_id": "CLM-1001",
                                               "filename": os.path.basename(p)}
          for p in _nav}
os.makedirs(_cfg.RUNTIME_DIR, exist_ok=True)
with open(_cfg.PHASH_LEDGER, "w", encoding="utf-8") as _fh:
    _json.dump(_stale, _fh)
with open(_cfg.OVERRIDE_LOG, "w", encoding="utf-8") as _fh:
    _fh.write('{"claim_id": "CLM-9999", "note": "left over from testing"}\n')

_before = _run.run("CLM-1002", _nav, attempt=2, user_photos=True, record_hashes=False)
if _before.decision.tier == "verify":
    print("[FAIL] reset: stale ledger did not affect the Navigator claim, so "
          "this test no longer demonstrates anything")
    fails += 1
else:
    at = AppTest.from_file("app.py", default_timeout=120).run()
    _btn = [b for b in at.sidebar.button if "Reset demo data" in b.label]
    if at.exception:
        # The planted log line deliberately lacks the current fields. The
        # review screen must survive an old or damaged log, not crash on it.
        print(f"[FAIL] reset: app crashed reading an old-format override log: "
              f"{[e.message for e in at.exception]}")
        fails += 1
    elif not _btn:
        print("[FAIL] reset: no Reset demo data button in the sidebar")
        fails += 1
    else:
        _btn[0].click().run()
        _led = {}
        if os.path.exists(_cfg.PHASH_LEDGER):
            with open(_cfg.PHASH_LEDGER, encoding="utf-8") as _fh:
                _led = _json.load(_fh)
        _planted = [h for h in _stale if _led.get(h, {}).get("claim_id") == "CLM-1001"]
        _after = _run.run("CLM-1002", _nav, attempt=2, user_photos=True,
                          record_hashes=False)
        if at.exception:
            print(f"[FAIL] reset: {[e.message for e in at.exception]}")
            fails += 1
        elif _planted:
            print("[FAIL] reset: stale ledger entries survived the reset")
            fails += 1
        elif os.path.exists(_cfg.OVERRIDE_LOG):
            print("[FAIL] reset: override log survived the reset")
            fails += 1
        elif _after.decision.tier != "verify":
            print(f"[FAIL] reset: Navigator still {_after.decision.tier} after reset")
            fails += 1
        else:
            print(f"[ OK ] reset    stale ledger took Navigator to "
                  f"{_before.decision.tier}; after reset it verifies again")


# --------------------------------------------------------------------------
# Defects found by the independent pre-submission review. Each is reproduced
# the way the reviewer reproduced it, so the fix is proven, not assumed.
# --------------------------------------------------------------------------

import tempfile as _tf  # noqa: E402
from PIL import Image as _Image  # noqa: E402

_tmp = _tf.mkdtemp(prefix="claims-review-")

# 1. Reason codes stay attached to the change they were given for.
#    Two sequences, both reproduced from the review:
#    (a) code an added line, THEN edit a price, which sorts ahead of it;
#    (b) code two added lines, THEN delete the first, which shifts the second.
#    Streamlit's test harness discards injected table edits on a button
#    click (a browser does not), so the recorded line cannot be produced here.
#    The log writes reasons[i] for changes[i], and each reason is read from
#    the selector keyed on that change's identity, so the bindings are the
#    thing to check.
for _p in (_cfg.OVERRIDE_LOG,):
    if os.path.exists(_p):
        os.remove(_p)

_A = {"operation": "replace", "part": "headlamp assembly"}
_B = {"operation": "repair", "part": "grille"}


def _codes(at):
    return {str(sb.key): sb.value for sb in at.selectbox
            if str(sb.key).startswith(f"reason_{KEY}_")}


# The harness also drops injected table state on any run where it is not
# re-injected, which would clear a selector for one run and lose its value.
# So every run below re-injects the table, as a browser would keep it.
def _run_with(at, added, edited=None, **codes):
    at.session_state[KEY] = {"edited_rows": edited or {}, "deleted_rows": [],
                             "added_rows": added}
    for k, v in codes.items():
        at.session_state[k] = v
    return at.run()


# (a) code an added line, then insert a price edit ahead of it
at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1001").run()
_run_with(at, [_A])
_ka = [k for k in _codes(at) if "_added:" in k][0]
_run_with(at, [_A], **{_ka: "missed damage"})
_run_with(at, [_A], edited={0: {"price": 500.0}},
          **{f"reason_{KEY}_edited:0:price": "pricing wrong"})
_a = _codes(at)
_ok_a = (_a.get(f"reason_{KEY}_edited:0:price") == "pricing wrong"
         and _a.get(_ka) == "missed damage" and len(_a) == 2)

# (b) code two added lines, then delete the first
at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1001").run()
_run_with(at, [_A, _B])
_kab = list(_codes(at))
_run_with(at, [_A, _B], **{_kab[0]: "missed damage", _kab[1]: "wrong part"})
_run_with(at, [_B])
_b = _codes(at)
_ok_b = list(_b.values()) == ["wrong part"]

if at.exception:
    print(f"[FAIL] codes: {[e.message for e in at.exception]}")
    fails += 1
elif not _ok_a:
    print(f"[FAIL] codes: after a price edit sorted ahead, bound as {_a}")
    fails += 1
elif not _ok_b:
    print(f"[FAIL] codes: after deleting the first added line, the grille "
          f"shows {_b}")
    fails += 1
else:
    print("[ OK ] codes    each reason code stays on its own change, when "
          "another sorts ahead and when an earlier added line is deleted")

# One record per decision: once recorded, the button stays disabled, and
# "Record another decision" unlocks this claim without touching the log.
at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1001").run()
at.session_state[f"outcome_{KEY}"] = "Approve as reviewed"
at.session_state[f"recorded_{KEY}"] = True
at.run()
_again = [b for b in at.button if b.label == "Record decision"]
_unlock = [b for b in at.button if b.label == "Record another decision"]
if not _again or not _again[0].disabled:
    print("[FAIL] once: Record decision still enabled after recording")
    fails += 1
elif not _unlock:
    print("[FAIL] once: no way to record another decision on this claim")
    fails += 1
else:
    _unlock[0].click().run()
    _after = [b for b in at.button if b.label == "Record decision"]
    if at.exception or not _after or _after[0].disabled:
        print("[FAIL] once: Record another decision did not unlock the claim")
        fails += 1
    else:
        print("[ OK ] once     a recorded decision cannot be written twice; "
              "Record another decision unlocks the claim")

# 2. The app records what it has seen, so reuse across claims is caught, and
#    the flag holds on every rerun rather than vanishing after one view.
if os.path.exists(_cfg.PHASH_LEDGER):
    os.remove(_cfg.PHASH_LEDGER)
at = AppTest.from_file("app.py", default_timeout=120).run()
at.sidebar.selectbox[0].set_value("CLM-1003").run()
_views = []
for _ in range(3):
    _reuse = _run.run("CLM-1001", ["samples/bumper_a.jpg"], attempt=1,
                      user_photos=True, record_hashes=True)
    _views.append(any("CLM-1003" in f for p in _reuse.photos
                      for f in p.authenticity_flags))
_own = [_run.run("CLM-1003", [f"samples/bumper_{a}.jpg" for a in "bc"],
                 attempt=1, user_photos=True, record_hashes=True)
        for _ in range(2)]
_self = any("previously submitted" in f for r in _own for p in r.photos
            for f in p.authenticity_flags)
if not all(_views):
    print(f"[FAIL] reuse: flag on successive views of CLM-1001: {_views}")
    fails += 1
elif _self:
    print("[FAIL] reuse: a claim flagged its own photographs")
    fails += 1
else:
    print("[ OK ] reuse    reuse flagged on every view, never on a claim's "
          "own photos")

# 3. Capture time comes from the Exif sub-IFD, where cameras write it. Taken
#    before the CLM-1003 loss (2026-09-18), edited after it.
_img_path = os.path.join(_tmp, "edited_after_capture.jpg")
_im = _Image.new("RGB", (1600, 1200), (118, 122, 128))
_ex = _Image.Exif()
_ex[271], _ex[272] = "Apple", "iPhone 15"
_ex[306] = "2026:09:19 10:00:00"                      # main block: last modified
_ex.get_ifd(0x8769)[36867] = "2026:08:19 09:00:00"     # sub-IFD: captured
_im.save(_img_path, exif=_ex, quality=90)
_e = _run.run("CLM-1003", [_img_path], attempt=1, user_photos=True,
              record_hashes=False)
if not any("predates" in f for p in _e.photos for f in p.authenticity_flags):
    print("[FAIL] exif: a photo captured a month before the loss was not flagged")
    fails += 1
else:
    print("[ OK ] exif     capture time read from the sub-IFD, pre-loss photo "
          "flagged")

# 4. Files that are not readable images are refused with a reason.
_bad = {"fake.jpg": b"not an image", "empty.jpg": b""}
with open("samples/good_a.jpg", "rb") as _fh:
    _raw = _fh.read()
_bad["truncated.jpg"] = _raw[: len(_raw) // 3]
_unread = []
for _name, _data in _bad.items():
    _bp = os.path.join(_tmp, _name)
    with open(_bp, "wb") as _fh:
        _fh.write(_data)
    if not _img.unreadable_reason(_bp):
        _unread.append(_name)
if _unread or _img.unreadable_reason("samples/good_a.jpg"):
    print(f"[FAIL] unreadable: not refused {_unread}, or a good file refused")
    fails += 1
else:
    print("[ OK ] unreadable fake, empty and truncated files refused; a real "
          "photo accepted")

# 5. One photo cannot answer a request for three views.
_one = _run.run("CLM-1002", ["samples/navigator_wheel_closeup.jpg"], attempt=2,
                user_photos=True, record_hashes=False)
_copies = _run.run("CLM-1002", ["samples/navigator_wheel_closeup.jpg"] * 3,
                   attempt=2, user_photos=True, record_hashes=False)
if _one.decision.tier == "verify":
    print("[FAIL] views: a single photo verified a three-view request")
    fails += 1
elif _copies.decision.tier == "verify":
    print("[FAIL] views: three copies of one photo verified a three-view request")
    fails += 1
else:
    print(f"[ OK ] views    one of three requested views at the attempt cap -> "
          f"{_one.decision.tier}")


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
