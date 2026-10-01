"""End-to-end smoke test across all eight demo claims. Mock provider, no key."""
# Run against a throwaway runtime folder. These tests delete and plant ledger
# and log entries, and must never touch a presenter's real demo data.
import os as _os
import tempfile as _tempfile
_os.environ["CLAIMS_RUNTIME_DIR"] = _tempfile.mkdtemp(prefix="claims-test-")
# Tests always run in mock mode. A .env set up for live mode would otherwise
# make real API calls and break the pinned numbers. load_dotenv() never
# overrides a variable that is already set.
_os.environ["VLM_PROVIDER"] = "mock"
import glob, os, sys
from config import SCENARIO_PHOTOS
from pipeline import run, routing

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
def s(*names): return [os.path.join(S, n) for n in names]
# Each claim's own demo photos, from the one list the app uses.
def demo(claim_id): return s(*SCENARIO_PHOTOS[(claim_id, 1)])

CASES = [
    ("CLM-1001", demo("CLM-1001"), 1),
    ("CLM-1002", demo("CLM-1002"), 1),
    ("CLM-1002", s("bad_blurry.jpg", "bad_dark.jpg"), 2),   # attempt cap
    ("CLM-1003", demo("CLM-1003"), 1),
    ("CLM-1004", demo("CLM-1004"), 1),
    ("CLM-1005", demo("CLM-1005"), 1),
    ("CLM-1006", demo("CLM-1006"), 1),
    ("CLM-1007", demo("CLM-1007"), 1),
    ("CLM-1008", demo("CLM-1008"), 1),
]

fails = 0
for claim_id, paths, attempt in CASES:
    print("=" * 74)
    try:
        r = run.run(claim_id, paths, attempt=attempt, record_hashes=False)
    except Exception as e:
        print(f"{claim_id} attempt {attempt}: EXCEPTION {type(e).__name__}: {e}")
        fails += 1
        continue
    print(f"{claim_id}  attempt {attempt}  |  {r.context.vehicle_label}")
    print(f"  gate passed : {r.gate_passed}")
    if r.gate_reasons:
        for g in r.gate_reasons: print(f"    - {g[:88]}")
    if r.evidence:
        print(f"  evidence    : {r.evidence.status}  coverage={r.evidence.coverage_score}")
    for p in r.photos:
        bits = []
        if p.quality_issues: bits.append("QUALITY:" + "|".join(i.split("(")[0].strip() for i in p.quality_issues))
        if p.authenticity_flags: bits.append(f"AUTH:{len(p.authenticity_flags)}")
        print(f"    {p.filename:24s} {p.width}x{p.height} sharp={p.sharpness:8.1f} bright={p.brightness:6.1f} {' '.join(bits)}")
    if r.assessment:
        print(f"  line items  : {len(r.assessment.line_items)}  total=${r.assessment.estimate_total:,.2f}")
        for li in r.assessment.line_items:
            print(f"    {li.operation:9s} {li.panel:20s} conf={li.confidence:.2f} priced={li.priced} ${li.price or 0:,.2f}")
        if r.assessment.adas_zones_involved:
            print(f"  ADAS zones  : {r.assessment.adas_zones_involved}")
        if r.assessment.hidden_damage:
            print(f"  hidden dmg  : {[h.part for h in r.assessment.hidden_damage]}")
    if r.confidence:
        c = r.confidence
        print(f"  confidence  : {c.claim_confidence}  (floor={c.line_item_floor} cov={c.evidence_coverage} ret={c.retrieval_density} agree={c.cross_stage_agreement} adas=-{c.adas_penalty})")
    if r.decision:
        print(f"  DECISION    : [{routing.TIER_LABELS.get(r.decision.tier, r.decision.tier)}] {r.decision.headline}")
        for rs in r.decision.reasons: print(f"    * {rs[:92]}")

print("=" * 74)
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
