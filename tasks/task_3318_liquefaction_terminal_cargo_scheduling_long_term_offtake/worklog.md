# Worklog — task_3318_liquefaction_terminal_cargo_scheduling_long_term_offtake

## Step 1: Create task directory — 2026-09-30T20:04:00.000Z

Task directory `./tasks/task_3318_liquefaction_terminal_cargo_scheduling_long_term_offtake/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and no new index was computed.

## Step 2: Generate scaffold — 2026-09-30T20:35:00.000Z

All checks pass. Final state:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3318_liquefaction_terminal_cargo_scheduling_long_term_offtake/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 14 (Customer, SalesPurchaseAgreement, LiquefactionTrain, AnnualDeliveryProgram, CargoSlot, Berth, VesselCall, LaytimeStatement, Pipeline, PipelineDaySchedule, FeedGasNomination, CargoCancellation, FeedGasResale, MaintenanceTurnaround)
- Endpoints: 63 (38 mutations + 24 GETs + clock) — deliberately pushed past the Expert band per the max-difficulty instruction
- Difficulty instances (§1.8): 18 (exactly 2 per each of the 9 rules)
- Corner instances (§1.9): 47 scanned (44 active + 3 `excluded_because:` stubs); 71 unique instance names across both files, no collisions

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (725 calls scanned)

**Difficulty envelope highlights:**
- Dual-variant calcs in two domains (provisional/final cargo invoice: 24,399,000.00 vs 25,434,000.00; SOF vs pump-log laytime: 40,375.00 vs 33,645.83)
- Combinatorial modes (a)+(b): largest-remainder proration with floor caps (46,154/38,461/15,385) and pinned per-segment rounding order (3,435.42 vs the 3,470.83 wrong-order result)
- Non-linear machines: Train cycle COMMERCIAL_OPERATION↔TURNAROUND; CargoSlot parallel lift×billing dimensions
- Depth-3 cascades from two triggers (turnaround begin → train → slot shift → ADP recompute; cancellation → slot → nomination cut → schedule re-proration)
- Validation priority conflicts on two category pairs (state vs fiscal; safety vs temporal); boundary checks on laytime equality (used==allowed → 0.00) and 30-day notice threshold (allowed at exactly 30, rejected 1s later)
- Two OCC rules (vessel nomination on CargoSlot.version; ADP revision supersede on SPA.version), segregation-of-duties on turnaround approve, berth half-open+2h-buffer vs turnaround closed-interval overlap semantics, and two compensating invariants (pipeline gas balance; ACQ quantity conservation)

All pinned numeric literals were recomputed by executing the formulas (one arithmetic slip caught and fixed: reconciliation deficiency 25,434,000.00, not 17,094,600). Logical clock default 2026-09-01T00:00:00Z is declared, and every fixture date sits after it.

**Orchestrator verification:** all three files exist on disk; SCAFFOLD.yaml has 63 `path:` entries (endpoint count at the high end — flagged risk for Step 6, mitigations applied in the Step 6 prompt).

## Step 3: Copy shared files — 2026-09-30T20:36:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:42:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3318_liquefaction_terminal_cargo_scheduling_long_term_offtake/workspace/PRD.md` — 299 lines.

**Sections:**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC (5 roles, CustomerRep entity-backed identity translated; opaque identities for the four operator roles), 2.2 API Response Structure (byte-identical to the fixed block), 2.3 Pagination, 2.4 The Logical Clock (startup default `2026-09-01T00:00:00Z`, `to_iso8601` setter), 2.5 Common Resource Properties, 2.6 Nested Resource Retrieval, 2.7 Monetary/Quantities/Precision, 2.8 OCC (both `expected_cargo_slot_version` and `expected_spa_version` rules with `ERR_STALE_VERSION`/412), 2.9 Validation Order (priority sequence in prose), 2.10 Terminal-Wide Integrity and Cascades
- §3 Business Logic: 3.1 Buyers & SPAs, 3.2 Trains/Commissioning/COD, 3.3 Annual Delivery Program, 3.4 Vessel Nomination & Berth Assignment, 3.5 Invoicing & Laytime (both SOF and pump-log variants, pinned rounding order, constants 240,000 MMBTU/hr, 4h berth allowance, 6h NOR grace, 2h connection allowance), 3.6 Feed Gas & Proration (floor 5,000 MMBTU, largest-remainder, conservation invariant), 3.7 Cancellation & Resale (pinned 6-step settlement, 2% handling fee on gross, 0.35 USD/MMBTU tariff), 3.8 Turnarounds & Terminal-Wide Impact (SoD, closed-interval overlap, slot shifting), 3.9 Annual Reconciliation (inclusive lower bound)
- §4 Endpoint table (63 rows, 4 columns)
- §5 Error catalogue (31 rows, 2 columns)

**Zero-Silence / Hard-Contract confirmation:**
- Contract 1 (Field-Name Coverage): 120 required identifiers (entity fields + endpoint inputs/query/path params + envelope fields) — all 120 present in backticks, 0 missing. PASS.
- Contract 2 (Rule Coverage): all 31 error IDs appear in §2/§3 prose with their trigger conditions; all state-enum values (12 state machines), all enum values (`AAA/AA/A/BBB`, `HENRY_HUB/TTF/JKM`, `FOB/DES`, `LOADING_FLANGE/DISCHARGE_PORT`, `SOF_BASIS/PUMP_LOG_BASIS`), both OCC rules with write endpoint + occ field + error id, validation priority ordering, cross-entity cascades (cancellation → nomination CUT → schedule re-proration; turnaround begin → berth OUT_OF_SERVICE + pipeline OUTAGE + slot shift → ADP recompute), and all seven calculation formulas expressed in prose without pseudocode or fuzzy words. PASS.
- Contract 3 (§3 Path Purity): 417 backticked tokens scanned in §3 — 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS.

No forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were read.

## Step 5: Generate unit tests — 2026-09-30T20:58:00.000Z

All 89 tests collect cleanly. Done.

**Files written**

`test_helpers/` (8 files): `__init__.py` (barrel export), `types.py` (13 status enums + 14 entity TypedDicts), `api_client.py` (all PRD endpoints), `api_errors.py` (30 error IDs + HTTP status map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared opaque-role headers + `make_customer_rep_headers(customer_id)` for the entity_backed role), `fixtures.py` (commercial-train / commenced-SPA / confirmed+locked ADP / departed vessel-call / proration-schedule / settled-cancellation / turnaround composite fixtures).

`test_suite/` (8 files + `conftest.py`): 89 tests across buyers/SPAs/trains, ADP lifecycle, vessels/berths, invoicing/laytime, feed-gas proration, cancellation/settlement/reconciliation, turnarounds, pagination.

**Coverage**
- Queue A (Difficulty): all 18 instances (9 rules × 2) have exactly 2 tests each → 36 tests.
- Queue B (Corner): all 47 non-stub instances have ≥1 test → 53 tests (5 instances covered twice for paired branches). The 6 `excluded_because` stubs were not translated; their `difficulty_instance` cross-references all resolve.

**Skips**: none — every instance passed the PRD-first filter. Two judgment calls worth noting: the two priority-pair instances cite PRD §2.9's flat validation *sequence* (state legality before ACQ cap; physical-safety compatibility before berth-window overlap) rather than numeric priorities, with docstring annotations explaining the translation; and every fixture event timestamp in the recipes is ≥ the `2026-09-01T00:00:00Z` clock start (earliest is `2026-12-11`), so no clock-contradiction re-derivation was needed.

**Stage 2 self-check**: PASS — 89/89 tests carry exactly one `Design:` tag as the final docstring line, every tag resolves to a real instance in the correct rule/section, every difficulty instance has ≥2 tests, every non-stub corner instance has ≥1, and every docstring contains a ≥8-word substring that survives a literal normalized grep of `workspace/PRD.md`. `pytest --collect-only` imports the full suite without errors.

**Orchestrator spot-check:** 89 test functions / 89 `Design:` tags confirmed by grep; api_client.py `_request` calls enumerated — all 63 PRD-table endpoint paths present (the subagent's "44 endpoints" line was a misstatement; actual coverage is full).

## Step 6: Generate implementation — 2026-09-30T21:22:00.000Z

Implementation is complete.

**Files written** (all under `workspace/implementation/`):

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0 foreground |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 43 | Flask app, blueprint registration, ApiError + 404/405 handlers |
| `db.py` | 31 | In-memory stores (empty at boot), logical clock defaulting to 2026-09-01T00:00:00Z |
| `errors.py` | 130 | Full error catalog (31 error_ids), envelope helpers, pagination (limit/offset/total_count/has_more) |
| `util.py` | 163 | Auth headers (X-User-ID/X-User-Role), typed body validators, id/timestamp/touch helpers, `pub()` view |
| `services.py` | 202 | Decimal money/hours rounding, feed-gas ratio, invoice formula, ADP/schedule recompute, proration waterfall, berth overlap (2h buffer), lazy SPA expiry |
| `routes_commercial.py` | 151 | Customers, SPAs (+commence, lazy EXPIRED), logical clock endpoint |
| `routes_trains.py` | 273 | Trains, commissioning/COD gating, turnarounds (SoD, overlap, begin/complete cascades: berth OUT_OF_SERVICE, pipeline OUTAGE, slot shifts through RESCHEDULED→SCHEDULED) |
| `routes_adps.py` | 331 | ADP revisions/supersede with slot re-parenting + OCC on SPA version, propose/confirm(ACQ cap)/lock/reconcile, cargo slots, cancellations with nomination-cut + re-proration cascade |
| `routes_marine.py` | 391 | Berths, vessel nominations (supersede + OCC on slot version), call lifecycle accept/NOR/berth/depart with provisional invoice, laytime statements (pinned rounding order: per-period whole-minute rounding before summing; both SOF and pump-log variants) |
| `routes_gas.py` | 282 | Pipelines, day schedules (capacity + unique gas_day), nominations, close/proration, nomination reconcile, cancellation settle (pinned 6-step settlement, OFFERED→UNSOLD flip), resales |

**Coverage:** all 63 PRD §4 endpoints implemented; all 31 §5 error_ids implemented. In-memory dict storage only; no seeding at startup.

**Boot smoke test:** server booted via `bash start.sh` on a saved PID (three times, killed by exact PID each time). Verified GET (404 error envelope) and POST (customer create, correct envelope). Deeper end-to-end runs all passed: commissioning/COD gating, SPA commence, OCC 412 on stale versions, slot window validation, schedule capacity/duplicate-day 422s, proration conservation (16000 nominated → 10000 confirmed + 6000 cut, floor-min 5000 each), cancellation cutting CONFIRMED nominations to CUT with schedule re-proration, resale volume cap, settlement arithmetic (credit 3,530,000.0 / net 2,470,000.0 matching the pinned formula), turnaround SoD 403, overlap 409, begin cascade (train→TURNAROUND, pipeline→OUTAGE) and complete restore, auth 401/403, provisional/final invoice amounts exact.

**Orchestrator verification:** 11 files on disk, 2008 total lines; 56 unique route path templates (= 63 method-endpoints, GET/POST sharing paths).

## Step 7: Run tests and iterate — 2026-09-30T21:44:00.000Z

All 8 rounds pass 89/89. Clean exit.

**Summary**

- Iterations run: 2 full 8-round parallel sweeps (plus targeted single-file reproduction runs in between).

- Tests deleted: none. Every failing test traced to verbatim PRD prose; no PRD-silence or unique-derivability collapse was found.

- Fixes applied to `test_helpers/`: none.

- Fixes applied to `test_suite/`:
  - `test_02_annual_delivery_program.py` (`test_occ_stale_adp_revision_version`): the setup created a train in `CONSTRUCTION` but never walked it to `COMMERCIAL_OPERATION` before commencing the SPA, so the PRD-faithful implementation correctly rejected commence with `ERR_NO_COMMERCIAL_TRAIN` (PRD §3.1). Replaced the dead train-create + unused `create_commercial_train` import with an actual `create_commercial_train(commissioning_cargoes_required=0)` call — the helper's COD path is valid per PRD §3.2 (`completed >= required`, i.e. 0 >= 0, plus `performance_test_passed`).

- Fixes applied to `implementation/`:
  - `workspace/implementation/util.py` (`logical_now_iso`, `dt_to_iso`): PRD §2.4 pins the startup default clock to the exact string `2026-09-01T00:00:00Z`; the implementation unconditionally rendered `.000Z`, breaking `cancelled_at`, `departed_at`, `laytime_start_at`, and shifted `window_start` comparisons in 4 tests. Both formatters now omit fractional digits when the logical clock carries zero microseconds (3-digit fractions preserved when non-zero, per §2.5/§2.6).
  - `workspace/implementation/services.py` (`prorate`): two bugs against PRD §3.6. (1) The 5,000 MMBTU floor was applied as a cap on the pro-rata term (`min(nom, floor, floored)`), producing bases of 5,000/5,000/5,000; the PRD sentence ("the smallest of three quantities: its nominated volume, a floor of 5,000 MMBTU applied as the lesser of the nomination's volume and the floor itself, or its nominated volume times the factor rounded down") and the test's worked example (60,000/50,000/20,000 vs 100,000 → 46,154/38,461/15,385) only admit the floor-as-guaranteed-minimum reading `min(nom, max(min(nom, FLOOR), floored))`. (2) Fractional parts for remainder ranking are now computed from the raw nominated×factor product, not from the floored base.
  - `workspace/implementation/routes_adps.py` (`reconcile_adp`): PRD §3.9 gates reconciliation on the clock being "past the first instant of the year following the ADP's contract year"; the implementation used `clock <= year_end`, wrongly rejecting reconciliation at exactly `2028-01-01T00:00:00Z`. Changed to strict `<`.

Final state: 89/89 passing in all 8 concurrent rounds.

**Orchestrator verification:** all impl/test fix mtimes (≤21:41:10) precede the final sweep results (21:44:09), so no post-sweep edits invalidate the sweep; all 8 `results.${i}.json` read back as total=89, passed=89, failed=0, errors=0, skipped=0.

## Step 8: Finalize PRD — 2026-09-30T21:52:00.000Z

All three edits are in place. One more NO-NEW-MISMATCH verification for the proration wording against the worked example and edge cases in the impl:

- Nominations below the floor, e.g. nom=4,000 with factor 0.5: impl base = `min(4000, max(min(4000,5000), 2000))` = `min(4000, max(4000,2000))` = `min(4000, 4000)` = 4000 — the sub-floor nomination is confirmed in full, consistent with "a nomination smaller than the floor is guaranteed at most its own volume" and base = min(nom, raised term).
- nom=60,000, factor≈0.769: floor doesn't bind, base = 46153 = `min(60000, max(5000, 46153))` ✓.
- The "cycling back" clause matches `idx % len(fracs)` in services.py:183.

Also confirm the worked example in the test (46154/38461/15385) follows from the new wording: bases 46153/38461/15384, remainder 2, raw-product fractions 0.846/0.538/0.615 → A and C get +1 → 46154/38461/15385 ✓.

**Line counts:** PRD.md 299 lines, PRD_FINALIZED.md 301 lines (+2 lines, +0.67%).

**Changes:**

- §2.5 — revise — replaced the blanket "three fractional digits" claim on `created_at` with a timestamp-rendering rule: stored/echoed datetimes render with no fractional digits when the sub-second component is zero and with exactly three fractional digits otherwise; explicitly scopes the rule to `created_at`/`updated_at`, logical-clock stamps (`nor_tendered_at`, `berthed_at`, `departed_at`, `cancelled_at`, `laytime_start_at`), stored window bounds, and the `current_utc` echo, while preserving §2.2's three-fractional-digit `api_request_timestamp` — `implementation/util.py:18-31` (`logical_now_iso`), `util.py:159-162` (`dt_to_iso`).

- §3.6 — revise — rewrote the proration base-allocation sentence from the self-contradictory "smallest of three quantities" phrasing to the floor-as-guaranteed-minimum formula `min(nominated, max(min(nominated, 5000), floor(nominated × factor)))`; also pinned that remainder ranking uses the raw (un-floored) nominated×factor fractional part and that distribution cycles back to the head of the ranking while remainder persists — `implementation/services.py:155-187` (`prorate`).

- §3.9 — revise — changed the reconciliation gate from "past the first instant of the year following the ADP's contract year" to "reached or passed" (inclusive at exactly the first instant), matching the impl's strict `<` rejection — `implementation/routes_adps.py:144-146` (`reconcile_adp`).

- (No PRD change) — the test-suite fix in `test_02_annual_delivery_program.py` was a pure fixture bug (test never commissioned a train before commencing the SPA); the PRD already determined the behavior, so prose was kept verbatim.

**Per-edit pre-edit search log:**

1. **§2.5 timestamp rendering** — (a) subject: string rendering of all system-stored/echoed datetimes. (b) enumerated impl paths: `util.logical_now_iso` callers (`stamp_new`/`touch` → every resource's `created_at`/`updated_at`; `routes_marine.py:196,212,228` NOR/berthed/departed; `routes_adps.py:320` `cancelled_at`) and `util.dt_to_iso` callers (`routes_adps.py:186-187` slot windows; `routes_marine.py:173-174,282,312` call windows, excluded-period echo, `laytime_start_at`; `routes_trains.py:220-221` turnaround-shifted windows; `routes_commercial.py:151` clock echo). Also verified `errors.py:63-73` `api_request_timestamp` uses wall-clock with 3 fractional digits and §2.2 is untouched. (c) wording scoped to "stored or echoed" datetimes and explicitly excluded the envelope timestamp to avoid narrowing §2.2.

2. **§3.6 proration formula** — (a) subject: base allocation and remainder distribution in the proration waterfall. (b) enumerated impl paths: `services.prorate` (sole implementation, lines 133-196) and its only two call sites — `routes_gas.py:103` (schedule close) and `routes_adps.py:314` (cancellation cascade re-run); `routes_trains.py` imports but never calls it. Validated the rewritten formula against the test's worked example (46154/38461/15385) and the sub-floor nomination edge case. (c) initial draft had an awkward first clause; rewrote for clarity before committing, and added the raw-product fraction and ranking-cycle pins to match `exact - int(exact)` and `idx % len(fracs)`.

3. **§3.9 reconciliation gate** — (a) subject: temporal gate for ADP reconciliation. (b) enumerated impl paths: `routes_adps.reconcile_adp` lines 144-146 is the only gate of this kind (`if db.get_clock() < year_end: fail`); no other endpoint consumes this year-boundary check (the slot-window year check at `routes_adps.py:180-182` is a different half-open bound already correctly described in §3.3). Also confirmed consistency with §3.1's inclusive "reaches or passes" SPA-expiry phrasing. (c) none.

Output file: `workspace/PRD_FINALIZED.md` (299 → 301 lines).

## Step 9: Complete PRD — 2026-09-30T22:07:00.000Z

Done. `workspace/PRD_COMPLETED.md` written (copied from PRD_FINALIZED.md, then edited in place only).

**Counts:** PRD_FINALIZED.md 301 lines / 48,366 chars → PRD_COMPLETED.md 303 lines / 53,287 chars (+2 lines, +4,921 chars). Ambiguity-pins: 20. Mismatch-revisions: 1.

**Changes (one per bullet):**
- §2.1 — insert — ambiguity — pinned that GET endpoints do no CustomerRep ownership check and listed exactly which state-changing operations do — routes_adps.py:107, routes_marine.py:84/192, routes_gas.py:126-127, routes_marine.py:354/369
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` = offset + page-length < total_count — errors.py:100-122, errors.py:86
- §2.8 — insert — ambiguity — expected-version fields are optional; omission skips the check; present non-integer → 400 — routes_adps.py:29-38, routes_marine.py:79-82/101
- §2.10 — insert — ambiguity — pinned exact trigger set of lazy SPA expiry (SPA fetch, SPA ADP listing, customer SPA listing, commence-deliveries, ADP creation) — routes_commercial.py:52/106/116/129, routes_adps.py:36
- §3.1 — insert — ambiguity — lazy EXPIRED transition itself refreshes `updated_at` and increments `version` — services.py:83-91
- §3.3 — insert — ambiguity — re-parented slots on ADP supersession are themselves touched (version/updated_at) — routes_adps.py:63-66
- §3.4 — insert — ambiguity — nominating against BERTH_ASSIGNED/RESCHEDULED slot → `ERR_SLOT_INVALID_STATE`; supersede leaves slot in VESSEL_NOMINATED (never regresses to SCHEDULED) — routes_marine.py:93-98, 103-105, 127
- §3.4 — insert — ambiguity — accepted window bounds inclusive of slot window edges (ws ≥ slot start, we ≤ slot end) — routes_marine.py:168
- §3.4 — insert — ambiguity — accept window with ws ≥ we → `ERR_INVALID_REQUEST` — routes_marine.py:156-157
- §3.5 — insert — ambiguity — pinned the berth-window overlap rule: half-open intervals padded by a 2-hour changeover buffer; conflict iff `ws < ce+2h and we > cs−2h`; checked against ACCEPTED/NOR_TENDERED/BERTHED/DEPARTED calls — services.py:18, 201-216
- §3.5 — insert — ambiguity — `elapsed_hours` rounded half-up to 2dp before use; excluded-period minutes rounded half-up; excluded-sum hours and `used_laytime_hours_sof` each rounded half-up to 2dp — routes_marine.py:287-296
- §3.5 — insert — ambiguity — `used_laytime_hours_pumplog` rounded half-up to 2dp; demurrage amounts rounded half-up to 2dp; both SOF and pump-log figures computed and stored on every statement regardless of basis — routes_marine.py:297-305
- §3.5 — insert — ambiguity — statement born with `adjusted_demurrage_usd` null — routes_marine.py:320
- §3.5 — insert — ambiguity — missing pump_hours on PUMP_LOG_BASIS, non-numeric pump_hours, non-list excluded_periods, and period end-before-start all → `ERR_INVALID_REQUEST` — routes_marine.py:256-262, 278-279
- §3.6 — insert — ambiguity — RECONCILED nominations remain counted in `total_confirmed_mmbtu` and in the confirmed-cut component of `total_cut_mmbtu` — services.py:124-128
- §3.6 — insert — ambiguity — nomination born with `cut_mmbtu` zero; creating one increments the schedule's version — routes_gas.py:140, 144-145
- §3.6 — insert — ambiguity — every nomination touched by the proration waterfall (even confirmed-in-full) is touched per §2.5; cancellation re-run reallocates SUBMITTED+CONFIRMED+RECONCILED, demoting zero-confirmed ones to CUT — services.py:140-196
- §3.7 — insert — ambiguity — notice-days equality is sufficient; cancellation born with `resale_credit_usd` = 0 and `net_due_usd` = null — routes_adps.py:290-291, 323-324
- §3.7 — insert — ambiguity — RECONCILED nominations exempt from cancellation cut; proration re-run only on CLOSED schedules (OPEN ones just re-totalled); schedule version increments either way — routes_adps.py:305-316
- §3.7 — insert — ambiguity — non-positive resale offered volume → `ERR_RESALE_VOLUME_EXCEEDED` (not 400); sale_price must be > 0 — routes_gas.py:243-244, 275
- §3.7 — insert — ambiguity — pinned that the settle-time billing transition only ever encounters UNBILLED (impl's UNBILLED guard is a tautology) — routes_gas.py:222-225
- §3.8 — insert — ambiguity — begin pre-start-date → `ERR_TURNAROUND_INVALID_STATE`; begin against non-COMMERCIAL_OPERATION train → `ERR_TRAIN_INVALID_STATE`; complete non-IN_PROGRESS → TURNAROUND_INVALID_STATE; complete with train not in TURNAROUND → `ERR_TRAIN_INVALID_STATE` — routes_trains.py:194-201, 255-259
- §3.8 — revise — mismatch — PRD claimed a turnaround "may end as CANCELLED" but no cancel endpoint exists and none is implemented; revised to state CANCELLED never occurs in practice while preserving the overlap-check exemption wording — routes_trains.py (no cancel route), endpoint table §4
- §3.9 — insert — ambiguity — `reference_index_price_usd_per_mmbtu` must be > 0 (else `ERR_INVALID_REQUEST`) — routes_adps.py:141
- §3.9 — revise (grammar disambiguation) — ambiguity — clarified shortfall formula grouping: `max(0, floor(ACQ×(1−tol)) − delivered)` — routes_adps.py:150-151

No changes were needed for the endpoint table (§4), error catalogue (§5), timestamp rendering rule (§2.5), logical clock default (§2.4), feed-gas 1.10 ratio, proration floor/remainder algorithm, settlement six-step order, or ADP quantity formulas — impl matches PRD prose exactly there (verified against implementation and the 89/89 passing results.8.json).
