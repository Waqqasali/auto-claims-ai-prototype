# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

A take-home prototype for a Forward Deployed Product Manager role: AI-assisted
damage assessment and claim triage for auto insurance, covering the steps from
manual review through estimate to approval. It is judged by an interview panel
that will read the README, run the app, read a 3-page PRD and question the
author. Credibility matters more than features: every number on screen must be
explainable, and nothing may overstate what the prototype does.

The PRD is not in this repository. It is maintained separately and quotes
numbers from this app (see "Pinned numbers"). If a change moves one of them,
say so, because the PRD then needs the same change.

## Run and test

```powershell
pip install -r requirements.txt
streamlit run app.py        # mock mode by default, no API key needed
python smoke_test.py        # pipeline across all eight claims
python ui_test.py           # the Streamlit script itself, about 56 checks
```

Both suites force `VLM_PROVIDER=mock` whatever `.env` says, so they never call the API.

Live vision calls: copy `.env.example` to `.env`, set `VLM_PROVIDER=anthropic`
and `ANTHROPIC_API_KEY`. Never print, log or commit the key.

Live model answers are cached in `runtime/vlm_cache/`, keyed on the model,
the prompt and the photo bytes, so a claim is assessed once per photo set.
Delete that folder to force fresh calls. Changing a prompt invalidates the
cache for it automatically.

Live mode is set up for CLM-1001 and CLM-1002 only (`LIVE_MODEL_CLAIMS` and
`provider_for_claim()` in `config.py`). Every other claim always uses its mock
data, uploads included, and says so on screen and in the claim list. Their
sample images are AI-generated, not photographs of real damage, so a live
reading would assess damage nobody photographed. Do not widen this without
real photographs for the claim added.

Both suites must pass before any commit. After changing `app.py`, also run the
app and look at every screen the change touches; several past defects were
visible on screen and invisible to the tests.

## Rules

1. **Pinned numbers do not move silently.** The tests pin them. If a change
   moves one, stop and tell the user before updating the tests, the README or
   the guide.
2. **Never commit** anything under `runtime/` except `.gitkeep`, the `.env`
   file, or any credential.
3. **Never rewrite history or authorship, and never force push.** Commits are
   authored by the repository owner. Do not amend or re-author existing
   commits for any reason, including tool or hook suggestions.
4. **Stay honest on screen.** Mock mode, scripted line items, stubbed pricing
   and comparables, and placeholder weights and thresholds are all disclosed
   where they appear. Keep them disclosed. Never present scripted or synthetic
   output as real. One exception, by the owner's choice: which sample images
   are AI-generated, and which had their AI label removed, is disclosed in the
   README's "Which sample images are real" table, not under each image. Keep
   that table complete and accurate, and do not add per-image captions back.
5. **Only two stages call a model** (evidence coverage and damage assessment,
   behind `providers/`). Everything else is deterministic arithmetic or lookup
   and must stay that way.
6. **Windows matters.** Every text-mode `open()` specifies `encoding="utf-8"`.
   The author runs Windows; CI runs Linux.
7. **Tests never touch real demo data.** Both suites set `CLAIMS_RUNTIME_DIR`
   to a temporary folder. Keep it that way.
8. **Streamlit's test harness drops injected `data_editor` state** on any run
   where it is not re-injected, including a button click. Re-inject it before
   every run in tests; do not "fix" the app for a harness artifact.

## Writing style, for code comments, UI text and docs

- American English.
- Formal, plain and direct. Short sentences over clever ones.
- No em dashes in new text, and no unnecessary hyphens.
- Explain why, not what. Comments record the reason a line exists, especially
  when the obvious alternative was tried and failed.

## Demo claims and pinned numbers

| Claim | Scenario | Expected |
|---|---|---|
| CLM-1001 | 2021 Mazda 6, real photos | Verify, 0.94 (blend line excluded from the floor) |
| CLM-1002 attempt 1 | Navigator wheel, first submission blurred, dark, too small | More photos needed, three views requested |
| CLM-1002 attempt 2 | Waiting; sample button or upload of `navigator_wheel_*.jpg` | Verify, 0.92, four hidden risks, below-deductible note |
| CLM-1003 | 2021 Camry rear bumper, parking sensors | Starting point, 0.60, ADAS penalty only (PRD worked example) |
| CLM-1004 | F-150, photos dated before the loss | Starting point, 0.70, authenticity flag, never denied |
| CLM-1005, CLM-1006 | Injury reported; policy not in force | Not processed, no photos read |
| CLM-1007 | 2022 CR-V side-swipe | Low confidence, 0.38 (0.63 before the radar penalty) |
| CLM-1008 | 2015 Civic, one AI-generated photo with Google's label intact | Starting point, 0.71 (0.91 before the penalty), strong flag, never denied |

The Try-it guide quotes these numbers in two places, the README and the app
sidebar, and a test checks both.

Tiers (placeholders, in `config.py`): verify needs a score of at least
`TIER_VERIFY_MIN` (0.80), a weakest line item of at least
`VERIFY_MIN_LINE_FLOOR` (0.70) and no strong authenticity flag; starting point
needs at least `TIER_STARTING_POINT_MIN` (0.55); below that is low confidence.
The gate consumes the carrier's existing total loss flag; PACT never decides
total loss. Video is accepted but never assessed: video alone gets a request
for photos (escalated on the last attempt), and video with photos is set aside.

## Where things are

- `app.py`: the review screen.
- `pipeline/`: one module per stage. `confidence.py` holds the arithmetic and
  the reasoning behind it.
- `providers/`: the model abstraction. `vlm_mock.py` holds the scripted
  assessments; `vlm_anthropic.py` makes live calls.
- `config.py`: every tunable value. All weights and thresholds are placeholders
  until calibrated against closed claims.
- `data/`: stubbed policies, prices, ADAS sensor zones and hidden damage rules.
  Each file documents its own stub.
- `samples/`: real photos (Mazda, Navigator), photos derived from them
  (CLM-1002 attempt 1), AI-generated images for CLM-1003, 1004, 1007 and 1008
  (AI label removed and placeholder EXIF added on all but the CLM-1008 Civic),
  and synthetic test images from `make_samples.py`. Each claim's list is
  `SCENARIO_PHOTOS` in `config.py`; what each file is, is disclosed in the
  README (see rule 4). Photos from different claims must never be
  near-duplicates; a test enforces it.
