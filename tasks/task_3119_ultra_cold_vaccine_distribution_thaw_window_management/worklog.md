# Worklog — task_3119_ultra_cold_vaccine_distribution_thaw_window_management

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3119_ultra_cold_vaccine_distribution_thaw_window_management/` was pre-allocated by the operator with an empty `workspace/` inside. No index computation or directory creation was performed; the pre-allocated path was used exactly as instructed. Verified: task dir exists, `workspace/` exists and is empty, `./INSTRUCTION.md` exists at project root (1424 bytes).

## Step 2: Generate scaffold — 2026-09-30T01:00:00.000Z

All three artifacts are generated and the linter is clean.

### Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3689 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1232 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2515 |

### Counts

- **Entities:** 26 (§1.1)
- **State machines:** 15 (§1.2) + 2 concurrency rules (§1.2.1)
- **Endpoints:** 132 (§1.5)
- **Error catalog:** 78 (§1.6), every code referenced at least once by a validation or transition
- **Calculations:** 11 (§1.3, 9 dual-variant) · **Validations:** 32 ordered priorities (§1.4) · **Roles:** 8 (§1.7)
- **§1.8 queue A:** 18 instances across all 9 Difficulty Rules (§0.5 minimum is 2 per rule → 18 total)
- **§1.9 queue B:** 42 active instances + 2 `excluded_because:` stubs, spanning all nine claim-extraction-guide sections

### Design note

The scenario is pinned to archetype `quota_allocation` blended with `temporal_windowing`, on a **flat** topology (peer entities with FK links, no nesting) — a configuration the skill flags as 0% in prior examples. Six §0.2 complexity layers are active (OCC, cascading side effects, dual-variant calculation, derived-field reconciliation, scheduled/deferred actions, selector policy), and the role model is `segregation_of_duties` with a mandatory reviewer ≠ adjudicator rule. The difficulty core is a cluster of genuinely ambiguous arithmetic: an additive seven-bucket carton waterfall whose minimum-order uplift is applied *before* prior rejections are netted; a hold-back rule that rounds an exact-integer product down but a fractional one up; a capped piecewise thaw function whose cap sits on the first branch; slice caps on integer dose multiples; an inclusive-at-the-ceiling capacity boundary, an exclusive-at-the-start half-open interval rule, and a tier-1 score gate that is inclusive exactly at 21. All formula-derived `assert:` values were computed by hand and written as literals (e.g. the waterfall slicing 1000 doses into 1 carton, a 2-carton acceptance yielding 2340 doses and a variance of 1340, a 2×1170-dose carton pair giving 4680 usable doses).

Corner-design instances that the difficulty index already covers are emitted as `excluded_because:` stubs (2 of them, no `test_recipe`) rather than duplicated. §1.5 was iterated under the priority ladder while writing the setup chains — three gaps surfaced and closed by adding business endpoints (`POST /allocation-batches/{id}/cartons`, `POST /logger-readings/{id}` read, `POST /cartons/{id}/destroy`), plus pagination inputs added to all 44 list endpoints so the listing claims in §1.9 are drivable.

`scaffold_lint.py` verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    132
  §1.1 entities declared:     26
  §1.8 instances scanned:     18
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  1162

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two caveats worth flagging to the downstream generators: the file-split was verified programmatically (`scaffold_difficulty_design` / `scaffold_corner_design` appear only as single top-level keys in their own files, never in `SCAFFOLD.yaml`), and a grep sweep confirms zero forbidden concurrency vocabulary and zero use of UUID/random `id` as a decision input anywhere — all tie-breaks use `created_at ASC`, as the checklist requires.

### Orchestrator verification

Confirmed all three files exist on disk. `wc -l`: SCAFFOLD.yaml 3689, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1232, SCAFFOLD_CORNER_DESIGN.yaml 2515. `grep -c 'scaffold_difficulty_design\|scaffold_corner_design' SCAFFOLD.yaml` → 0, confirming the design indices were correctly split out of SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-30T01:01:00.000Z

Copied `./INSTRUCTION.md` (project root, 1424 bytes) to `./tasks/task_3119_ultra_cold_vaccine_distribution_thaw_window_management/workspace/INSTRUCTION.md`. This is the build contract handed to the Step 6 implementation generator.

## Step 4: Generate PRD — 2026-09-30T01:11:00.000Z

All checks pass. The PRD is complete.

### Summary

**Output:** `workspace/PRD.md` — 504 lines (orchestrator `wc -l` confirms 503), ~15.5k words (120,263 bytes), ending exactly at §5 with no audit footer. Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were withheld and never opened; no sibling task directory was read.

**Hard Contract reports (verified mechanically against SCAFFOLD.yaml):**

```
Contract 1 — Field-Name Coverage:
- entities[].fields:        215 required, 215 present, 0 missing
- endpoints[].input:        133 required, 133 present, 0 missing
- endpoints[].query_params:   0 declared,  0 missing
Status: PASS

Contract 2 — Rule Coverage:
- validations[] priority ordering:      32 checked, 32 expressed, 0 missing
- concurrency_rules[] OCC rejections:    2 checked,  2 expressed, 0 missing
- state_machines[].transitions:         77 checked, 77 fully expressed, 0 missing
- calculations[]:                       11 checked, 11 fully expressed, 0 missing
- validations[] conditions → error_id:  32 checked, 32 matchable, 0 missing
- endpoints[].side_effects / applies_to:132 checked,132 expressed, 0 missing
- entities[].fields[] structured content:215 checked,215 reconstructible, 0 missing
- error IDs mentioned in §2/§3:         78 checked, 78 present, 0 missing
- sibling-branch symmetry:              all parallel branches rendered at equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned (§3): 1131
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scattering / Zero-Silence note.** Entity families are distributed by workflow rather than by schema. §2 carries the contract-level spine: role identity translation for all eight roles in 2.1, byte-verbatim §2.2, pagination in 2.3, and ten domain-derived cross-cutting subsections (2.4 logical-clock discipline, 2.5 common properties + precision + "never order by a surrogate id", 2.6 OCC on the acceptance/seal/window-open trio, 2.7 left-to-right retrieval, 2.8 equipment/capability/standing gates, 2.9 validation ordering with the adjudication sub-ordering, 2.10 the full enum vocabulary, 2.11 deferred actions). §3 scatters the nine lifecycle stages: product config + batch + carton + auto transit/expiry in 3.1; allocation waterfall + hold-back rounding trap + lapse in 3.2; site registry + order submission + the seven-bucket dose waterfall in 3.3; shipper packing, ice hairpin and seal OCC in 3.4; dispatch/dock in 3.5; thaw window and beyond-use cascade in 3.6; transfers + reservation interval merge in 3.7; excursions, adjudication bands, appeals and the two audit orderings in 3.8; ledger, wastage, dual-variant accountability and standing escalation in 3.9. Endpoint input parameters are split across §2 (the two `expected_*_version` fields, 2.6) and multiple §3 subsections; no §3 table or field list exists. **The Zero-Silence Rule is honored:** every scaffold calculation formula, transition precondition plus its error_id, side-effect cascade, validation condition/priority/applies_to scope, OCC rejection, and structured field default is reconstructed in precise prose — no operator syntax and no fuzzy hedging survived the translation, and the reconstruction test was applied to all 11 calculations (including the logarithmic cure-phase and the sign-symmetric decay hairpin, both added explicitly after a coverage gap surfaced).

**Orchestrator verification:** `workspace/PRD.md` exists, 503 lines, 120,263 bytes. `workspace/` now holds `INSTRUCTION.md` + `PRD.md`.

## Step 5: Generate unit tests — 2026-09-30T01:34:00.000Z

Generation is complete and fully audited.

### Files generated

**`test_helpers/`** (9 files, 2477 lines)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 24 entity TypedDicts (append-only `TemperatureLoggerReading` / `DoseLedgerEntry` correctly omit `updated_at`/`version`), 30 status enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 138 endpoint methods
- `api_errors.py` — 78 error IDs registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_entitlement_carton_invariant`, `assert_release_conservation`, `assert_program_invariants`
- `factories.py` — 18 payload factories (input fields only)
- `constants.py` — PRD thresholds and literal expected values
- `test_users.py` — shared constants for the 8 roles plus `make_site_coordinator_headers(site_id)` (the only `entity_backed` role)
- `fixtures.py` — 30 composite helpers across all 5 tiers, including `anchor_delivered_carton`, `anchor_thawed_carton`, `setup_entitled_site`, `setup_reservation_pair`, `setup_lapsed_program`, `setup_adjudicated_excursion`

**`test_suite/`** (9 files, 3026 lines): `conftest.py` + `test_01_domain_and_pagination` … `test_08_corner_breadth_gaps`

### Counts

- **80 tests total** (all collected by pytest, no import or name errors)
- **Queue A (Difficulty): 38 tests** — every one of the 18 instances has ≥2 tests
- **Queue B (Corner): 42 tests** — every one of the 40 active instances has ≥1 test (the 2 `excluded_because:` stubs emitted nothing)
- Every docstring ends with exactly one resolving `Design:` line; 0 unresolved tags; every quoted PRD citation verified verbatim against `PRD.md`; no `skip`/`skipif`/`xfail`; no scaffold vocabulary in generated code

### Instances skipped by the PRD-first two-condition filter

**None.** All 18 queue-A instances and all 40 active queue-B instances passed both conditions (verbatim PRD coverage + unique derivability) and were translated.

Two notes worth surfacing:

1. The PRD is unusually complete for these rules — including the cases the generator expected to drop, such as the second carton-only bind (`min_order_shortfall_cartons == 2` at the exact-value boundary, §3.3), the OCC "no other endpoint takes a version field" rule (§2.6), and the selector determinism/tie-break rules (§3.4/§2.5).
2. One downstream correction: the corner instance `holdback_rounding_and_pack_ceiling_on_rejection` asserts the OH entitlement's `computed_cartons == 3`, but the PRD's own rule ("a rate of five gives two and a half, which rounds up to three" for the *reservable* amount, then "`computed_cartons` is the rate minus the reservable amount") yields 5 − 3 = **2**. The tests assert 2 — this is a PRD-scaffold disagreement, resolved in favour of the PRD per Key Principle 1, and flagged upstream rather than treated as a test gap. Step 7 will confirm the implementation matches the PRD reading.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both exist with the reported file counts.

## Step 6: Generate implementation — 2026-09-30T02:31:28.117Z

**NOTE: this entry is a reconstruction.** The Step 6 subagent was in flight when the host session that launched it was stopped (the process died mid-pipeline; not an error in the work). Its returned summary was never captured, so there is no verbatim subagent report for this step. The orchestrator therefore verified the Step 6 artifacts directly on disk rather than trusting a lost report.

**Artifact inventory** (`workspace/implementation/`):

```
app.py                54      routes/__init__.py      0
helpers.py            64      routes/allocation.py  838
response.py           72      routes/common.py      229
db.py                105      routes/custody.py     658
errors.py            117      routes/ops.py         245
clockutil.py         134      routes/reference.py   347
middleware.py        449      routes/review.py      593
services/derive.py   449      routes/supply.py      693
services/calc.py     590      services/__init__.py    0
                                            total 5637
```

Plus `requirements.txt` and `start.sh`.

**Completeness verification (orchestrator-run, not subagent-reported):**

- `python3 -m py_compile` over every `.py` file → **SYNTAX OK, zero failures**. No file is truncated mid-token.
- Route declaration count: `grep -rhoE "@bp\.route|@app\.route"` → **132 `@bp.route` + 2 `@app.route`**, matching the scaffold's 132 declared §1.5 endpoints (the 2 extra app routes are infrastructure).
- Runtime route count from `app.app.url_map` → **135 rules registered** (132 business + infrastructure), confirming the blueprints actually attach.
- Boot smoke test: `PORT=8731 bash start.sh` → Flask serves on `0.0.0.0:8731`, `curl http://127.0.0.1:8731/` returns **HTTP 200**. Boot completes in well under 60 s. `start.sh` uses `exec python3 app.py` (foreground, correct per INSTRUCTION.md) and guards `pip install` behind an `import flask` check so that `--isolation per-test-server` reboots do not contend on pip.
- Persistence check: `grep -rnE "sqlite|\.db'|json\.dump|pickle|shelve|/tmp/"` → **no matches**. Storage is in-memory only.
- Seeding check: `grep -rnE "seed|preload|hardcod|DEMO_|SAMPLE_"` → **3 matches, all in module docstrings** stating the opposite ("no entity is ever seeded, preloaded or hardcoded here -- every record is produced by a test calling a declared endpoint"). No seeded data.

**Conclusion:** Step 6's artifacts are complete, syntactically whole, contract-compliant, and boot-capable. The step is accepted as complete on the strength of direct verification. Its narrative summary (which PRD rules were hardest to encode) is unrecoverable and is not reconstructed here.

An initial `prd-bench-local-run` sweep left `workspace/results.json` at 02:02 UTC with **44/80 passing**; that run is superseded by the fresh Step 7 sweep below.

## Step 7: Run tests and iterate — started 2026-09-30T02:31:28.117Z

Launched ONE long-lived fix subagent to own the run → diagnose → fix → rerun loop until an 8-round parallel stability sweep reports `passed == total` in all 8 rounds. Baseline entering the loop: 44/80 passing (stale `results.json` from the interrupted process).

### Step 7 attempt history (this step was killed twice by host-session restarts)

Two prior Step 7 attempts were launched and killed mid-flight when the host session that owned them stopped. Neither had applied any fix: a full 8-round sweep at 02:37 UTC plus a mini sweep at 02:46 UTC both reported the identical deterministic baseline **total=80 passed=44 failed=36 errors=0**, and no file under `implementation/` had been modified. The orchestrator therefore triaged the 36-failure set directly (grouping by failure signature — 4 `NameError`s in `test_suite/`, 2 shared-`ERR_CARTON_DESTROYED` setup failures, 1 missing-`logger_serial` factory bug, 2 order-status precondition mismatches, 2 error-precedence disputes, and a cluster of numeric/state-enum assertion mismatches) and passed that triage into the retry as a head start, along with an instruction to append durable per-batch notes to `step7_progress.md` so a further restart could resume rather than re-derive.

### Step 7 final summary (third attempt — completed)

Step 7 is complete — all 8 rounds pass 80/80.

**Iterations run:** 3 full 8-round parallel sweeps (44/80 → 51/80 → 68/80 → **80/80**), plus many single-test verify loops.

**Tests deleted: 0.** No test was deleted, skipped, or xfailed. Every failing test was traced to either a test-side defect (fixed faithfully to PRD) or an implementation gap (fixed in `implementation/`). Durable notes are appended in `step7_progress.md` (249 lines, 14 fix batches).

**Notable PRD adjudications** (PRD wins over scaffold in each):
- The scaffold's `holdback_rounding_and_pack_ceiling_on_rejection` asserted `computed_cartons == 3` for a rate of 5; PRD §3.2 gives 5 − 3 = **2**, which is what the tests assert. The scaffold's assertion was wrong; tests were left alone.
- `test_02::carton_puncture_axis...` expected `15:00:00Z` (09:00 + 6 h) but the test never advances the clock to 09:00 — corrected the literal to `14:00:00Z`.
- `test_04::wastage_rate_and_standing_tier_precision` asserted tier 2 off a lone lapse; PRD §3.9's ladder makes that tier 0 (score 3 ≤ 20). Split into a tier-0 assertion plus a tier-2 assertion once four lapsed periods raise the score past twenty.
- Both supersession tests appealed a `NOT_USABLE` adjudication, but PRD §3.8 refuses an appeal with `ERR_CARTON_DESTROYED` once the carton is destroyed — reworked over a live carton.
- Two scaffold-only assertions relaxed to sets PRD actually admits: site `inventory_status == RESTRICTED` after a `NOT_USABLE` site-wide cascade (PRD derives that field from non-adjudicated excursions only), and the disputed-order re-dispatch error precedence (PRD does not order `ERR_PAYMENT_HOLD` against `ERR_INVALID_STATE`).

**Fixes to `test_helpers/`:** new `current_window_version_for_order` (PRD §2.6's "recompute your view before retrying") wired through every accept; new `add_lapsed_periods`; `setup_lapsed_program` default holding 20/`clock_after` 2026-09-03T12:00:00Z.

**Fixes to `test_suite/`:** 3 missing imports/fixture wiring (`make_product`, `anchor_thawed_carton`, and `_prepared_dispatch` using the `api` pytest fixture from module scope); nested-ledger list filters moved client-side (that route declares only `limit`/`offset`); dock-refusal fixtures now build PRD §3.5's declared basis; literals corrected against PRD where the scaffold had invented them.

**Fixes to `implementation/`:** the largest were `services/derive.py`'s dose accounting rewritten to PRD §3.9 (`remaining_doses`, `administrative_remaining_doses`, `cumulative_released_doses`, `dose_shortfall_doses` — which fixed the fulfillment-reversal family) and `held_cartons` derived from the orders per PRD §3.2 (which reproduced both 10→7→2 and 2→10 from one rule); plus acceptance semantics (`pack_ceiling`, `occupied_cartons` capacity gate ordered after the fiscal check), window-version bumping on accept/reject, expiry/lapse sweeps, adjudication supersession, and one-family-row membership.

**Final sweep:** rounds 1–8 each `total=80 passed=80 failed=0 errors=0 skipped=0`, identical, 155 s wall each.

**Orchestrator verification (on disk):** all eight `workspace/implementation/results.{1..8}.json` report `total=80 passed=80 failed=0 errors=0 skipped=0`. `grep -rh "^def test_" test_suite/ | wc -l` → **80**, confirming zero test deletions. `grep -rnE "pytest.mark.skip|pytest.mark.xfail|@pytest.mark.skipif" test_suite/ test_helpers/` → **0 matches**, confirming no skips or xfails were introduced. `step7_progress.md` present at 249 lines.

## Step 8: Finalize PRD — 2026-09-30T05:24:00.580Z

Step 8 ran (not skipped — Step 7 applied implementation fixes, so `PRD.md` did not already determine every behavior the implementation exhibits). `PRD_FINALIZED.md` is written.

### Counts

- `PRD.md`: 503 lines / 120,146 chars
- `PRD_FINALIZED.md`: 504 lines / 125,136 chars (orchestrator `ls` reports 125,381 bytes on disk)
- Delta: **+1 line, +4.15% chars** (33 edits: 32 single-line replacements + 1 inserted catalogue row)

### Changes (PRD section — insert/revise — what changed — impl anchor)

- §3.2 — revise — window `requested_cartons` aggregates `requested_cartons_snapshot` (fallback `requested_cartons`), **not** "the requested_cartons" verbatim — `implementation/services/derive.py:260`
- §3.2 — insert — `held_cartons` is a derived view (sum of `requested_cartons_snapshot` over ACCEPTED/PARTIALLY_ACCEPTED/FULFILLED orders); a LAPSED entitlement pins `held_cartons` and `available_cartons` to 0 — `implementation/services/derive.py:214-248`
- §3.3 — insert — submission materialises `rounded_from_doses`/`min_order_shortfall_cartons`, which stay order-field properties — `implementation/routes/allocation.py:392-394, 505-512`
- §3.3 — revise — governing minimum floors an unset program minimum at its default `2` — `implementation/services/calc.py:51`
- §3.3 — insert — `ERR_PROGRAM_NOT_OPEN` evaluated **after** the five submission conditions — `implementation/routes/allocation.py:382`
- §3.3 — revise — accepted count is the caller's `accepted_cartons` (no truncation); the computed ceiling feeds only the preconditions and the pack-ceiling field; over-available is refused not trimmed — `implementation/routes/allocation.py:424, 430, 449-450, 498`
- §3.3 — revise — min-order precondition applies to the order's **first** decision only — `implementation/routes/allocation.py:446`
- §3.3 — insert — acceptance admitted from SUBMITTED/ACCEPTED/PARTIALLY_ACCEPTED; FULFILLED also when `accepted >= snapshot > available`; removed the `ERR_INVALID_REQUEST` full-snapshot branch; capacity check ordered after entitlement and inclusive — `implementation/routes/allocation.py:407, 455-460, 474-482`
- §3.3 — revise — entitlement moves by the **delta**; no EntitlementRelease is ever booked; reversal recomputes rather than adding — `implementation/routes/allocation.py:523, 542-561; 662-665` (dead `entitlement_releases` collection)
- §3.3 — revise — DRAFT rejection branch (was "THAWED") — `implementation/routes/allocation.py:599`
- §3.4 — revise/insert — hub resolved at dispatch creation (`ERR_NO_ELIGIBLE_SITE` there); `freeze_required` keys on `reported_entry_type` alone; `route_cartons` == non-destroyed attached cartons — `implementation/routes/supply.py:119-123, 223-225; services/derive.py:503-506`
- §3.4 — revise — seal failure `ERR_SHIPPER_HOLD` is 409 (added to §5 catalogue); seal advances version exactly once — `implementation/errors.py:59; routes/supply.py:584-593`
- §3.4 — revise — logger reading breach is a literal **15 minutes** — `implementation/routes/supply.py:677-678`
- §3.4 — revise — hold requires RECEIVED (both orderings → `ERR_INVALID_REQUEST`; bad enum → `ERR_REJECTION_REASON_INVALID`); hold persisted; release from RECEIVED-or-HELD, `ERR_HOLD_NOT_CLEARED` on both, cleared on success — `implementation/routes/supply.py:601-611, 614-653`
- §3.5 — revise — arrival refuses with `ERR_SHIPPER_NOT_RELEASED` (HELD) / `ERR_REFREEZE_FORBIDDEN` (DIRECT + thawed); THAW_AT_HUB expiry anchored on the thaw instant; `thaw_window_expires_at` recomputed staged; park test uses ultra-cold capacity vs already-ultra-cold+incoming — `implementation/routes/supply.py:321-323, 358-383`
- §3.5 — revise — dock refusal basis reaches the cert at `eta_at` (fallback clock) + HELD shipper + carried-forward DISPUTED — `implementation/routes/supply.py:443-466`
- §3.6 — insert — `DESTROYED` carton thaw → `ERR_CARTON_DESTROYED` — `implementation/routes/custody.py:42-43`
- §3.6 — revise — recovery hours truncate via `min(minutes // 60, 48)` — `implementation/services/calc.py:192`
- §3.6 — revise — carton/vial/dose limits all carry the recovered hours — `implementation/services/calc.py:225-227`
- §3.6 — revise — THAWED puncture **replaces** the expiry; already-PUNCTURED always refused — `implementation/routes/custody.py:98-101, 81-82`
- §3.6 — revise — second destruction → `ERR_ALREADY_TERMINAL` — `implementation/routes/custody.py:161`
- §3.7 — revise — `hours_remaining_at_request` measured to the logical clock, not `requested_at` — `implementation/routes/custody.py:359-362`
- §3.7 — revise — approval takes **no** min-order test — `implementation/routes/custody.py:422-424`
- §3.7 — revise — receipt parks only when the destination still reports the other type with the arriving carton counted in — `implementation/routes/custody.py:517-528; services/derive.py:354-370`
- §3.7 — revise — cancel's CONFIRMED precondition checked before state/terminal; removed the stale `ERR_RESERVATION_ALREADY_CONFIRMED` clause — `implementation/routes/custody.py:606-611`
- §3.7 — revise — elapsed-HELD lapse is unconditional, applies even with no attached transfer — `implementation/routes/ops.py:180-193`
- §3.8 — revise — NOT_USABLE sets `quarantine_status` directly to `DESTROYED` — `implementation/routes/review.py:333`
- §3.8 — revise — appeal filing points the trace at the appeal; accepting restores a DESTROYED carton to THAWED — `implementation/routes/review.py:404, 479-480`
- §3.8 — revise — supersession needs no second SOD check and is reachable via accept→review→re-adjudicate — `implementation/routes/review.py:252-254, 286-294`
- §3.8 — revise — in-band always USABLE + category restructure — `implementation/services/calc.py:273-290`
- §3.8 — revise — audit view exposes `deficits_by_depth` and `total_hours` (naming) — `implementation/services/calc.py:639-644`
- §3.9 — insert — family list `site_id` filter matches either endpoint — `implementation/routes/ops.py:55-58`
- §3.9 — revise — tier computed for any assessment mode; rate count clamped to `released_cartons_to_date` — `implementation/routes/allocation.py:756-757; services/calc.py:356-360`
- §5 — insert — `ERR_SHIPPER_HOLD | 409 Conflict` — `implementation/errors.py:59`

### Pre-edit search log (a: subject / b: impl paths enumerated / c: adjustment)

All 33 edits followed the same procedure; the five with real adjustments are marked ⚠.

1. **subject:** window `requested_cartons` source. **b:** `derive.recompute_window` (only writer); all callers (`submit_order`, `accept_order`, `reject_order`); `order_status`/`requested_cartons_snapshot` writers (`submit_order`, `reject_order`). **c:** none.
2. **subject:** entitlement held/available derivation. **b:** `recompute_entitlement`; every caller (`open_window` init, `accept_order`, `reject_order`, `reverse_fulfillment`, `close_window`, `run_cycle::_close_window_side_effects`, `recall_batch`); the LAPSED branches in `close_window`/`recall_batch`; `available_cartons` readers (`submit_order`, `accept_order`, `close_window`). **c:** added the LAPSED clause after confirming recall lapses via the direct branch (no shipping-window lapse).
3. **subject:** order need materialisation timing. **b:** `submit_order`, `accept_order`, `carton_rounding_waterfall`, `order_carton_need`, `governing_minimum`; order-field readers in tests. **c:** none.
4. **subject:** governing minimum default. **b:** `governing_minimum` alone (single source); both caller families (`carton_rounding_waterfall`, `pack_ceiling`). **c:** none.
5. **subject:** program-standing gate position on submit. **b:** `submit_order` only; compared against `pack_dispatch`, `accept_order`, `open_window` standing gates. **c:** none.
6. **subject:** accepted-count semantics. **b:** `pack_ceiling`, `accept_order`, `occupied_cartons`; all `accepted_cartons` readers (entitlement delta, window aggregate, delivery `FULFILLED`, `occupied_cartons`). **c:** none.
7. **subject:** min-order precondition scope. **b:** `accept_order` only; `governing_minimum`/`pack_ceiling`. **c:** none.
8. **subject:** acceptance admitted states / FULFILLED handles. **b:** `accept_order`; `TERMINAL_STATES["site_orders"]`; order-state checks in `pack_dispatch`, `dispatch_order`, `deliver_dispatch`. **c:** re-scoped the prose to *"one of two states"* (`FULFILLED`/`ACCEPTED`) rather than contradicting it with the third `PARTIALLY_ACCEPTED` branch the impl also has.
9. **subject:** entitlement move + release booking + reversal. **b:** `accept_order`, `reject_order`, `reverse_fulfillment`, `_record_rejection`, `_maybe_allocate_batch`; `entitlement_releases` writers (none — confirmed dead collection) and readers. **c:** kept the release contract prose but removed the CLAIM that it is filed; stated outright that no release is booked.
10. **subject:** DRAFT rejection branch. **b:** `reject_order` only. **c:** none.
11. **subject:** hub resolution timing / freeze_required / route_cartons. **b:** `create_dispatch`, `_select_staging_site`, `pack_dispatch`, `recompute_dispatch`; `freeze_required` writers and readers (none). **c:** ⚠ dropped the invented "after the route is applied" phrasing (the impl reads only `reported_entry_type`) to avoid a false universal claim.
12. **subject:** seal failure code/status and version. **b:** `seal_shipper`, `errors.HTTP_BY_ERROR`, §5 table. **c:** none (added the missing catalogue row).
13. **subject:** logger breach minutes. **b:** `create_reading` only. **c:** none.
14. **subject:** shipper hold/release. **b:** `hold_shipper`, `release_shipper`, `deliver_dispatch` (HELD reader); the audit comment explicitly calling the old "cleared by a reviewer decision" clause dead. **c:** none.
15. **subject:** arrival branch semantics. **b:** `deliver_dispatch`, `_park_with_excursion`, `thaw_window_expiry`, `beyond_use_for_carton`, `cartons_at_site`. **c:** ⚠ replaced "arrival instant plus …" with "its thaw instant plus …" (`thawed_at`, which is arrival only when it was null).
16. **subject:** dock refusal basis. **b:** `_dock_inspection_failed`, `reject_at_dock`, `deliver_dispatch` (cert semantics). **c:** none (documented the carried-forward DISPUTED term).
17. **subject:** thaw preconditions. **b:** `thaw_carton`; carton-state readers elsewhere. **c:** none.
18. **subject:** recovered-hours flooring. **b:** `recovered_hours`; `readiness_view.restored` (uses the minute path, not the floored one). **c:** none.
19. **subject:** carton/vial/dose limit identity. **b:** `beyond_use_for_carton`; `advance_logical_state`, `adjudicate` USABLE branch, `deliver_dispatch` (recompute `current_expires_at`). **c:** added a sentence rather than re-tightening the (implemented) level-aware prose.
20. **subject:** puncture from THAWED vs REFRIGERATED. **b:** `puncture_carton`; `beyond_use_for_carton` puncture limit; `refreeze_carton` resets `_puncture_at`. **c:** none.
21. **subject:** double-destroy. **b:** `destroy_carton`, `ensure_not_terminal`/`TERMINAL_STATES`, `_maybe_deplete_batch`. **c:** scope-checked `ERR_ALREADY_TERMINAL` to the carton only (not generalised to other entities).
22. **subject:** `hours_remaining_at_request` instant. **b:** `create_transfer`; `dispatch_transfer` (thaw-window gate); `report_excursion` (breach-based remaining, a different site). **c:** none.
23. **subject:** approval min-order. **b:** `approve_transfer`, `shipper_payload_shortfall` (dead), `recompute_dispatch` (the live charge), `_maybe_allocate_batch`. **c:** none.
24. **subject:** receipt parked-destination branch. **b:** `receive_transfer`, `prospective_entry_type`, `_mode_entry_type`, `recompute_site`; the §2.8 contract `ERR_DEST_RESTRICTED`. **c:** restructured the clause so it no longer asserts the destination is refused with an error the impl does not emit.
25. **subject:** cancel-transfer precondition order. **b:** `cancel_transfer` only; `TERMINAL_STATES["site_transfers"]`. **c:** ⚠ switched from an example ("a transfer that has already moved past APPROVED") to a general ordering statement to avoid a false universal claim over the CANCELLED path; also deleted the now-contradictory reservation sentence.
26. **subject:** reservation lapse. **b:** `run_cycle`; the dead `_sweep_reservations` (deliberately unwired); `receive_transfer` reservation branch; `reject_transfer`. **c:** none.
27. **subject:** quarantine ride-through. **b:** `adjudicate` (both outcome branches); quarantine writers (`report_excursion`, `review_excursion`, `accept_appeal`); quarantine readers. **c:** none.
28. **subject:** appeal trace + carton revival. **b:** `file_appeal`, `accept_appeal`, `deny_appeal`, `_newest_adjudication`. **c:** none.
29. **subject:** second adjudication. **b:** `adjudicate`; `accept_appeal` (sets UNDER_REVIEW) → the reachable cycle; the withdrawn-adjudication gate. **c:** none.
30. **subject:** dose-impact category. **b:** `dose_impact_category`, `band_outcome`, `breach_band`; the in-band adjudication path end to end. **c:** none.
31. **subject:** audit view field names. **b:** `audit_view`, `_wallclock_total`, `_consistent_total`. **c:** none.
32. **subject:** family list filter. **b:** `create_family`, `list_families`, `family_neighbours`, `family_closure`; `shared_dose_count` writer. **c:** none.
33. **subject:** standing tier + rate clamp. **b:** `standing_assessment`, `_recompute_standing`, `assess_standing`, `run_cycle`, `submit_period`; `recompute_program` (dead). **c:** ⚠ deliberately did NOT document the clamp formula (a clawback the PRD never contemplates); replaced it with the PRD-silent ordering fact actually needed.

### Notes

- Deliberately **not** patched (impl behaviour that is dead/unobservable or out of `step_7_diff` scope): `shipper_payload_shortfall`, `order_carton_need`, `recompute_program`, `_sweep_reservations`, `_staged_hop` (dead), `_ready_at_first_phase` (always 0), `reason_code` accepted on accept/reject payloads (never validated on accept, unused on reject), `assigned_user_id`/`assigned_site_id` echoes.
- Inherently-unpinned figures (rate=500, zero-quantity DESTROY …) were already marked in the source PRD as hand-computed literals; left verbatim.

**Orchestrator verification:** `workspace/PRD_FINALIZED.md` exists on disk, 504 lines / 125,381 bytes, alongside the untouched `PRD.md` (503 lines / 120,263 bytes).

## Step 9: Complete PRD — 2026-09-30T05:46:48.218Z

All 36 edits verified as in-place prose revisions — no new sections, no changes to §4/§5 tables, identical heading structure and identical 504-line count.

### Counts

- Source `PRD_FINALIZED.md`: 504 lines / 125,381 chars. `PRD_COMPLETED.md`: 504 lines / 129,930 chars. Δ = same line count, **+4,549 chars**. Heading set, §4 endpoint table (132 rows) and §5 error catalogue (79 rows) byte-identical; every change is an inline in-paragraph insert/revise.
- **23 ambiguity-pins**, **13 mismatch-revisions** (36 total edit sites; several paragraphs carry a jump that spans two classifications and is logged once under its dominant class).

### Change log (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`)

- §2.3 — insert — ambiguity — list sort gains `id` ascending as tie-break — `routes/common.py:185`
- §2.4 — revise — mismatch — clock advance *is* the sweep (EXPIRED + `expired_at` + `EXPIRE` + `administrative_expired`, plus batch/site sweeps); reservation/window/standing deferrals happen only in the cycle — `routes/ops.py:81-113`, `ops.py:147-165` (unreached)
- §2.5 — insert — ambiguity — `version` initialised to 1 on creation — `db.py:104`
- §2.5 — insert — ambiguity — `hours_remaining_at_request` floored at zero — `routes/custody.py:359-362`
- §2.5 — insert — ambiguity — `site_wastage_rate_ppm` whole-number floor; `required_dry_ice_kg` whole-number ceiling — `routes/review.py:522-524`, `services/derive.py:454`
- §2.5 — revise — mismatch — `id` is the final tie-break, so "never orders by `id`" is moderated — `routes/common.py:185`
- §2.9 — insert — ambiguity — `ERR_ALREADY_TERMINAL` examined before `ERR_INVALID_STATE`; terminal sets are per-resource — `routes/common.py:140-166`, `routes/reference.py:256`, `routes/supply.py:199`, `routes/custody.py:161`
- §3.1 — insert — ambiguity — `standing_status` is the latest standing assessment's tier — `routes/allocation.py:268-277`, `564-580`
- §3.1 — insert — ambiguity — recall zeroes `remaining_doses`/`administrative_remaining_doses`, clears expiry stamps, resets `cumulative_released_doses` — `routes/reference.py:291-304`
- §3.1 — insert — ambiguity — `logger_serial` optional at creation (seal needs it) — `routes/supply.py:509`, `580-581`
- §3.2 — insert — ambiguity — the "group" is every registered program — `services/calc.py:147-154`
- §3.2 — insert — ambiguity — window materialises exactly one entitlement; its program always takes the segment-0 treatment, so `segment_rule`'s segment-1 branches never arise — `services/calc.py:128-142`
- §3.2 — insert — ambiguity — rejection leaves the release listing always empty (no release row is ever materialised) — `routes/reference.py:291-309` + no `entitlement_releases` write
- §3.3 — insert — ambiguity — order tie-break gains `id` only when declared instants are equal — `routes/common.py:185`
- §3.4 — revise — mismatch — attach is gated on `packing_status == PREPARING`; `payload_locked_at` is a stamp, not a gate — `routes/supply.py:548-556`
- §3.4 — revise — mismatch — the decay factor does not enter `required_dry_ice_kg`; the exact integer ceiling division does — `services/derive.py:451-455`
- §3.4 — insert — ambiguity — the four-hundred-dose base governs; the rounded pack size is not used — `services/derive.py:453`
- §3.4 — revise — mismatch — half weight is keyed on having left ultra-cold (`THAWED`/`REFRIGERATED`/`PUNCTURED`), not on a staging hop — `services/derive.py:436-439`
- §3.4 — revise — mismatch — arrival leaves the shipper `IN_TRANSIT` when no in-grace reading exists; `ERR_LOGGER_READING_LATE` declared but never surfaced — `errors.py:75` only
- §3.5 — revise — mismatch — `eta_at` is `dispatched_at` + a flat 24 h on either route — `routes/supply.py:23`, `280`
- §3.5 — insert — ambiguity — arrival capacity counts `IN_TRANSIT` cartons among the already-attributed — `routes/supply.py:350-356`
- §3.5 — revise — mismatch — the post-thaw-into-ultra-cold delivery is refused via `ERR_REFREEZE_FORBIDDEN`; `ERR_CARTON_POST_THAW` declared but never surfaced — `services/derive.py:83` table only
- §3.6 — insert — ambiguity — thaw requires `ULTRA_COLD` (else `ERR_INVALID_STATE`) — `routes/custody.py:83-84`
- §3.6 — insert — ambiguity — thaw never applies the 48 h staged ceiling — `routes/custody.py:62-63`, `services/calc.py:170-175`
- §3.6 — revise — mismatch — `advance-logical-state` accepts any of five targets, needs no state precondition, re-stamps `thawed_at` at the clock and re-dates both stamps — `routes/custody.py:130-147`
- §3.7 — insert — ambiguity — `reservation_expires_at` cleared on both rejection branches — `routes/custody.py:590`
- §3.8 — revise — mismatch — review does not park family cartons; only `quarantine_status`/site recompute move — `routes/review.py:109-129`
- §3.8 — revise — mismatch — slice close cites no reference (only the bound check) — `routes/review.py:189-204`
- §3.8 — revise — mismatch — a `USABLE` adjudication re-derives the beyond-use date through the recovery cascade; `thaw_window_expires_at` is untouched — `routes/review.py:336-342`
- §3.9 — revise — mismatch — `administrative_remaining_doses` = `doses_per_carton` − losses + restored − administered — `services/derive.py:168-195`
- §3.9 — insert — ambiguity — `cumulative_released_doses` includes `REVERSE` entries and is reset to zero on expiry/destruction — `services/derive.py:196-199`, `routes/ops.py:107`
- §3.9 — insert — ambiguity — `diluent_doses` = released − `THAW`/`ADMINISTER` quantities, floored — `routes/review.py:544-552`
- §3.9 — insert — ambiguity — `site_wastage_rate_ppm` uses the signed variance — `routes/review.py:519-524`
- §3.9 — revise — mismatch — `wastage_rate_basis_points` is rounded half up (not truncated) — `services/calc.py:436-437`
- §3.9 — insert — ambiguity — the threshold test uses the magnitude of the variance; `dose_accountability_status` is the field that moves — `routes/review.py:590-593`

**Not changed (checked and already uniquely pinned):** §2.1 role list and SiteCoordinator entity-binding vs `middleware.py:18-29`; §2.6's exact OCC endpoint/version-absence list vs `supply.py:198`, `allocation.py:418`; every field default in §3.1 vs `routes/reference.py:41-64`, `92-120`; §3.3's seven-bucket waterfall, pad-ceiling algebra and zero-dose variant vs `services/calc.py:28-122`; the §3.4 reference-presentation rule and projective `punctured_ice_slots`/`dry_ice_deficit_kg` formulas; §3.6's beyond-use cascade; §3.7's `RESERVATION_BOUNDARY`/`CAPACITY_POOLED` interval merge; §3.9's tier arithmetic. RBAC was verified mechanically — the §4 role table and `OPS_BY_ROLE` agree on all 132 operations with zero divergence.

**Known approximation, called out rather than papered over:** `path-segment endpoint ids` (e.g. a transfer's `from_site_id` versus resources carrying `site_id`; the dose-position read's `site_id`) and `dose_ledger_entries.status` transitions beyond reversal. The former has no draftable artifact made by our implementation at generation time; the latter is described at §3.9/§3.8 and was not cleanly separable into a single pin without inventing behaviour.

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` exists on disk — 504 lines / 129,930 bytes. Full artifact chain intact: `PRD.md` 503/120,263 · `PRD_FINALIZED.md` 504/125,381 · `PRD_COMPLETED.md` 504/129,930.

## Final verification — 2026-09-30T05:49:53.513Z

Steps 8 and 9 wrote only PRD documents, so the Step 7 green state was expected to hold. The orchestrator verified this two ways rather than assuming it:

1. **mtime audit.** `find workspace/implementation test_suite test_helpers -name '*.py' -newermt '2026-09-30 04:50'` returned **nothing** — no source or test file changed after the final Step 7 sweep at 04:51:12 UTC. Steps 8–9 touched only `workspace/PRD_*.md`.
2. **Independent 8-round confirmation sweep.** A fresh full sweep (8 concurrent rounds, `--isolation per-test-server`, 80 tests each) returned **80/80 passed, 0 failed, 0 errors, 0 skipped in all 8 rounds** — reproducing Step 7's result from a clean process.

Scratch artifacts from the interrupted attempts and the confirmation run (`results.mini.json`, `results.confirm.*.json`, `workspace/results.json`, `__pycache__`) were removed. `workspace/implementation/results.{1..8}.json` — the eight all-passing rounds of the final stability sweep — are retained as the step's evidence.

**Pipeline complete. All 9 steps done; 80/80 tests passing across 8 concurrent rounds.**

### Final task directory

```
tasks/task_3119_ultra_cold_vaccine_distribution_thaw_window_management/
├── SCAFFOLD.yaml                          3689 lines
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml        1232 lines
├── SCAFFOLD_CORNER_DESIGN.yaml            2515 lines
├── worklog.md
├── step7_progress.md                      249 lines (durable Step 7 fix log)
├── test_helpers/                          9 files, 2477 lines
├── test_suite/                            9 files, 3026 lines, 80 tests
└── workspace/
    ├── INSTRUCTION.md
    ├── PRD.md                             503 lines
    ├── PRD_FINALIZED.md                   504 lines
    ├── PRD_COMPLETED.md                   504 lines
    └── implementation/                    ~5,640 lines, 132 business endpoints
        ├── start.sh
        ├── requirements.txt
        ├── app.py, db.py, errors.py, helpers.py, middleware.py,
        │   response.py, clockutil.py
        ├── services/{calc,derive}.py
        ├── routes/{allocation,common,custody,ops,reference,review,supply}.py
        └── results.{1..8}.json            (all 8 rounds: 80/80 passing)
```