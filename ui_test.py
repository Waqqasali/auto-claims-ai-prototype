"""Exercise the Streamlit script itself for every demo scenario."""
from streamlit.testing.v1 import AppTest
import sys

CASES = [("CLM-1001",1),("CLM-1002",1),("CLM-1002",2),("CLM-1003",1),
         ("CLM-1004",1),("CLM-1005",1),("CLM-1006",1)]
TIERS = ["VERIFY","STARTING POINT","LOW CONFIDENCE","MORE PHOTOS NEEDED",
         "ESCALATED TO AGENT","NOT PROCESSED"]
fails = 0
for claim_id, attempt in CASES:
    at = AppTest.from_file("app.py", default_timeout=120)
    at.run()
    if at.exception:
        print(f"[FAIL] boot: {[e.message for e in at.exception]}"); fails += 1; continue
    at.sidebar.selectbox[0].set_value(claim_id).run()
    at.sidebar.radio[0].set_value(attempt).run()
    if at.exception:
        print(f"[FAIL] {claim_id}/{attempt}: {[e.message for e in at.exception]}"); fails += 1; continue
    md = " ".join(m.value for m in at.markdown)
    tier = next((t for t in TIERS if t in md), "?")
    print(f"[ OK ] {claim_id} att{attempt}  tier={tier:<22} md={len(at.markdown):<3} "
          f"err={len(at.error)} warn={len(at.warning)} imgs={len(at.get('imageContainer'))}")
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
