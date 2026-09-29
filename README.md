# Claims Triage

An assessment and routing layer that sits between damage documentation and
estimate approval in an auto physical damage claim.

**It is not an estimating engine.** CCC's straight-through-processing product
is already deployed by 15 insurers including seven of the top ten US carriers
by direct written premium, covering roughly half of US auto claims volume.
Building another estimator would be competing where the market is settled.

What this does instead is decide **how much to trust an assessment, and what
should happen as a result.** The differentiated parts are evidence refusal,
media authenticity screening, calibration-risk flagging and a derived
confidence score that drives routing.

---

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

**No API key needed.** The default provider is a deterministic mock, so a
reviewer can clone this and see it work in one command. Any friction between
you and a running demo is friction I chose to create.

### Run with live vision calls

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export VLM_PROVIDER=anthropic
streamlit run app.py
```

### Run the tests

```bash
python smoke_test.py    # pipeline, all six claims, no UI
python ui_test.py       # exercises the Streamlit script for every scenario
```

---

## What to look at

Six claims are pre-loaded. Pick them from the sidebar.

| Claim | Scenario | Expected outcome |
|---|---|---|
| **CLM-1001** | 2015 Honda Civic, door dent. Pre-ADAS vehicle, non-sensor panel | `VERIFY` at 0.93 |
| **CLM-1002** attempt 1 | Blurry, dark and low-resolution photos | `MORE PHOTOS NEEDED` — specific re-request issued |
| **CLM-1002** attempt 2 | Still inadequate | `ESCALATED TO ADJUSTER` — attempt cap reached |
| **CLM-1003** | 2021 Toyota Camry, rear bumper scuff | `STARTING POINT` at 0.60 |
| **CLM-1004** | Photo EXIF timestamp predates the reported loss | `STARTING POINT`, authenticity flag raised, **not denied** |
| **CLM-1005** | Bodily injury reported | `NOT PROCESSED` |
| **CLM-1006** | Policy not in force at loss date | `NOT PROCESSED` |

### Start with CLM-1003

A rear bumper scuff on a common sedan is the claim everyone assumes is
trivially automatable. The system declines to treat it that way, because the
rear bumper on that vehicle carries parking sensors and rear cross-traffic
radar. Whether recalibration is required **cannot be established from a
photograph**, so confidence takes a 0.25 penalty and the claim routes for
human judgement.

The R&I line for the parking sensors carries 0.71 confidence, the lowest in
the claim. Because claim confidence is anchored on the weakest line rather
than the mean, that single item drives the outcome. Averaging would have
buried it at 0.84 and sent the claim through.

That is the whole product in one screen.

---

## What is real and what is stubbed

Honesty here matters more than coverage. Seven of nine MVP features run for
real; two depend on data that exists only inside a carrier.

| Component | Status | Detail |
|---|---|---|
| Image quality measurement | **Real** | Variance of Laplacian for sharpness, mean luminance, resolution. Runs on the actual files in every mode, including mock. |
| EXIF extraction and consistency | **Real** | Capture time against loss date, device, editing-software signatures. |
| C2PA presence check | **Real, limited** | Detects a JUMBF/C2PA box. Does **not** cryptographically validate the manifest against a trust list — that needs the `c2pa` library and a trust anchor. |
| Perceptual hashing | **Real** | Catches the same image reused across claims. |
| Evidence sufficiency logic | **Real** | Attempt cap, bail-out conditions, instruction generation. |
| ADAS zone intersection | **Real logic, thin data** | Five vehicles hand-entered. Production uses licensed reference data. |
| Confidence arithmetic | **Real** | Deterministic, auditable, in `pipeline/confidence.py`. |
| Routing and tiering | **Real** | Deterministic. |
| Override capture | **Real** | Writes to `runtime/overrides.jsonl` with mandatory reason codes. |
| Damage line items | **Real with a key, scripted without** | Mock mode returns scripted assessments so the decision architecture is observable without an API key. |
| Pricing | **Stubbed** | Flat rates from a local table. No regional variation, no vehicle-specific parts, no DRP-negotiated rates. Isolated behind `pricing.price_line()`. |
| Historical comparables | **Stubbed** | Hand-written rules table with **no observed rates**. Inventing rates would be fabricating evidence. Isolated behind `comparables.lookup()`. |
| Policy system | **Stubbed** | Local JSON fixture. Assumes real-time programmatic access in production. |

### How the stubs are shaped, and why it matters

Every stub is isolated behind a function whose signature, output type and
every consumer are final. Connecting real data means rewriting **one function
body** and changing nothing else.

A bad stub hardcodes a value in the middle of the logic and has to be unpicked
from five places. The difference is whether a prototype is throwaway or is
genuinely the first version of the production system.

### Sample images are synthetic

`samples/*.jpg` are generated by `samples/make_samples.py`. They are not car
damage photographs. They exist so the pipeline runs end to end with zero setup
and so the quality gate can be seen failing for **real measured reasons** —
sharpness 0.6 on the blurred file, brightness 6.2 on the dark one — rather
than simulated ones. Upload real photos in the sidebar to exercise the same
checks against genuine files.

---

## Architecture

```
Stage 0   gate.py          Tier 1 exclusions               deterministic
Stage 1a  imaging.py       quality measurement             deterministic
Stage 1b  authenticity.py  EXIF, C2PA, reuse               mostly deterministic
Stage 1c  evidence.py      sufficiency + re-request        VLM for coverage
          ── STOPS HERE if evidence is inadequate ──
Stage 2   assessment       line items with reasoning       VLM
Stage 3   pricing.py       cost lookup                     deterministic (stub)
Stage 3b  adas.py          panel/sensor intersection       deterministic
Stage 3c  comparables.py   hidden damage candidates        deterministic (stub)
Stage 4   confidence.py    composite score                 deterministic
Stage 5   routing.py       tier decision                   deterministic
```

**Two of ten stages use a model.** The rest is deterministic on purpose.
The eligibility gate and the confidence arithmetic are the auditable safety
boundary — a model deciding how much to trust another model is not something
you can explain to a regulator, and the NAIC model bulletin (adopted in 11
states as of 2024) requires third-party AI to carry contractual audit rights
and regulatory cooperation.

### The sovereignty answer

`providers/vlm_base.py` is the abstraction. Every vision call goes through it.
Swapping to a locally hosted open-weight model for an air-gapped or
data-residency-constrained deployment means adding one implementation and
changing one environment variable.

What degrades, stated honestly: fine-grained part identification. A smaller
local model will confuse adjacent panels and trim parts more often. That shows
up as lower per-item confidence, which the composite score already consumes,
which narrows the band handled without an adjuster. **The system degrades into
more human review rather than into wrong answers.**

Everything downstream of that interface — costing, ADAS intersection,
confidence, routing, the audit trail — is already deterministic and local.

---

## What this prototype does not prove

As important as what it does.

- **Not estimate accuracy.** It cannot. Ground truth in this domain only
  exists after teardown, as the supplement. There are no supplements here to
  compare against.
- **Not scale or performance.**
- **Not interface quality.** Functional, not designed.
- **Not model selection.** An off-the-shelf VLM behind an abstraction. Which
  model is a production decision requiring evaluation data that does not exist
  yet.
- **Not calibrated confidence.** Every threshold in `config.py` is a
  placeholder. In production they are set from shadow-mode data by plotting
  predicted confidence against realized override rate and realized supplement
  occurrence. Naming a calibrated number before that data exists would be
  inventing a fact.

---

## Layout

```
app.py                  adjuster review screen
config.py               every tunable parameter, all placeholders
pipeline/               stages, one module each
providers/              VLM abstraction + mock + Anthropic
data/                   stubbed reference data, each file documents its stub
samples/                synthetic test images + generator
runtime/                override log, perceptual-hash ledger
smoke_test.py           pipeline test, all scenarios
ui_test.py              Streamlit script test, all scenarios
```
