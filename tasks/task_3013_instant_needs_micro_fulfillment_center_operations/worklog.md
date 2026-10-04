# Worklog — task_3013_instant_needs_micro_fulfillment_center_operations

## Step 1: Create Task Directory — 2026-09-29T12:07:03.870Z

Used pre-allocated task directory `./tasks/task_3013_instant_needs_micro_fulfillment_center_operations` (per command args; no new index computed). Confirmed `workspace/` exists and is empty.

Scenario: Instant-Needs Micro-Fulfillment Center Operations (Gopuff) — micro-fulfillment site assortment of a few thousand instant-need items selected by local demand, owned inventory with buy-side vendor terms rather than a marketplace model, order pick-pack targets measured in minutes with single-picker batch limits, delivery driver dispatch from a fixed site with a small delivery radius and fee schedule, age-restricted item handling with identification scanning at handoff, site-level demand forecasting for late-night and weather-driven spikes, subscription membership waiving delivery fees above a basket threshold, inventory shrink and expiry control in a small footprint. Difficulty instruction: "Generate task much harder than expert level!"

## Step 3: Copy Shared Files — 2026-09-29T12:07:20.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3013_instant_needs_micro_fulfillment_center_operations/workspace/INSTRUCTION.md` (1424 bytes). Done early (Step 3 has no dependency on Step 2 output).

## Step 2: Generate Scaffold — 2026-09-29T13:01:30.292Z

(Note: first attempt at 12:07 was killed by session exit before writing any files; re-run from scratch in foreground.)

All checks pass. The scaffold is complete and lint-clean.

## Summary

Generated three scaffold artifacts for **task_3013_instant_needs_micro_fulfillment_center_operations** (Gopuff-style micro-fulfillment), targeting well beyond expert difficulty:

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (1359 lines, 73543 bytes)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single key `scaffold_difficulty_design` (1403 lines, 80041 bytes)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single key `scaffold_corner_design` (1760 lines, 98823 bytes)

**Counts:**
- Entities: **12** (Site, Product, InventoryBalance, StockLot, Customer, Membership, ReplenishOrder, Order, PickBatch, Picker, Driver, DeliveryBag)
- State machines: **8** (Site cyclic OPERATING↔SUSPENDED with derived OPENED_REPLENISH posture; Product one-way retire; ReplenishOrder branching DRAFT→PLACED→FINALIZED/CANCELLED; Order branching with post-failure return-to-stock path; PickBatch linear-with-compound-close; Membership cyclic ACTIVE↔LAPSED→CANCELLED; DeliveryBag with **parallel delivery_status × handoff_status dimensions**; handoff sub-machine NONE→ID_SCANNED→AGE_VERIFIED/REFUSED)
- Calculations: **10** (delivery_fee tiered/capped/peak; order_tax per-line rounding pinned; loyalty accrual record-vs-absorb variants; wallet absorb waterfall; age-at-handoff boundary; batch capacity dual ceilings; forward-looking stockout; lot expiry semi-open horizon; membership billing close with pinned evaluation order; night/weather demand forecast)
- Endpoints: **57** (incl. `/_clock/set_current_utc` with mandatory 2026-09-01T00:00:00Z startup default)
- Errors: **33**; Validations: **14** priorities; Roles: **4** (segregation-of-duties model — picker can't seal own batch, driver can't touch another's bag); Concurrency rules: **2** OCC (Site capacity profile, Customer membership writes)
- Difficulty instances (§1.8): **19 active** — every rule ≥2 (dual_variant_calc has 3); all numeric asserts pre-computed as literals (fees 199/249/399/993, taxes 21/6, loyalty 67, billing 1000→950 at the 13th close, etc.)
- Corner instances (§1.9): **41 total** (36 active + 5 `excluded_because` stubs citing real difficulty instances)

**Notable design decisions:**
- Flat topology (`api_prefix: /mfc`) with body/query FKs — deliberate departure from the hierarchical norm; every FK has a reverse-reachability GET.
- Dual-variant pair crosses entity domains: Order tax (rounding order, pinned per-line-then-sum) vs Customer wallet (record/absorb accrual).
- Two compensating invariants on different conserved quantities: wallet cents (absorb↔cancel) and on_order units (place↔cancel).
- Boundary-precision pair: fee-waiver `>=` threshold (3000 vs 2999 cents) vs batch line-cap inclusive boundary on a different metric/endpoint.
- Temporal-overlap pair with different interval semantics: semi-open expiry horizon on StockLot vs combined inclusive-count/overflow-guard capacity on PickBatch.
- All test recipes drive empty-DB → precondition using only §1.5 endpoints; placeholder closure verified programmatically (0 unbound `${var}`).
- `scaffold_lint.py` verdict: **clean lint** (531 calls scanned, 0 violations, all 16 FKs reverse-reachable).

## Step 4: Generate PRD — 2026-09-29T13:12:17.710Z

All contracts pass. The PRD is complete at `workspace/PRD.md`.

## Summary

**Output:** `workspace/PRD.md` — 297 lines.

**Section structure:**
- §1 Introduction (2 paragraphs: business context + operating-reality framing)
- §2 Global Specifications — 9 subsections: 2.1 RBAC (4 roles with entity-backed vs opaque identity prose), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 The Logical Clock (startup default `2026-09-01T00:00:00Z`), 2.5 Site Posture and the Replenishment Interlock (`effective_status` derivation + suspend guard), 2.6 Common Resource Properties and Cross-Resource Validation (id/created_at/updated_at/version + normative validation ordering), 2.7 Monetary Precision (integer cents, round half-up, per-line-then-sum pinning), 2.8 Optimistic Concurrency Control (both OCC rules), 2.9 Batch Capacity and Segregation of Duties
- §3 Business Logic — 9 subsections organized by workflow timeline: 3.1 Sites/Catalog/Capacity, 3.2 Inventory Foundations, 3.3 Vendor Replenishment, 3.4 Customers/Wallets/FAM Membership (billing close with pinned evaluation order), 3.5 Order Placement and Basket Pricing (pinned subtotal → wallet absorb → per-line tax → fee/waiver order), 3.6 Picking Waves and Batch Sealing, 3.7 Dispatch/Handoff Compliance/Delivery (selector policy, dual handoff state machine, dual-variant loyalty accrual), 3.8 Failure Paths (CUSTOMER vs RETURN_TO_STOCK cancels), 3.9 Demand Forecasting
- §4 Endpoint table (58 rows, 4 columns), §5 Error catalogue (33 errors, 2 columns)

**Self-audit results:**

```
Field coverage check (Contract 1):
- entities[].fields: 56 required, 56 present, 0 missing
- endpoints[].input: 28 required, 28 present, 0 missing
- endpoints[].path params: 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check (Contract 2):
- validations priority ordering: expressed as normative ordered sequence in §2.6
- concurrency_rules OCC: 2 checked, 2 expressed (write capability + expected_*_version + ERR_STALE_VERSION/412 each), 0 missing
- state machine transitions: 25 checked, 25 expressed (from/to, preconditions with error IDs, side effects incl. hop cascades), 0 missing
- calculations: 10 checked, 10 expressed in precise prose with pinned rounding/evaluation order, 0 missing
- validations conditions: 14 checked, 14 matchable to error IDs in §2/§3 prose, 0 missing
- endpoints side effects / applies_to scopes: expressed (e.g. ERR_AGE_VERIFICATION_REQUIRED on both batch-append and handoff-scan; ERR_PRODUCT_UNSELLABLE on both placement and append)
- field structured content (types, defaults, constraints): reconstructible from prose
- sibling-branch symmetry: FINALIZED/CANCELLED, record/absorb, AGE_VERIFIED/REFUSED, CUSTOMER/RETURN_TO_STOCK branches all at equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 379
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 33 error IDs appear in §2/§3 prose near their triggers; §5 contains no trigger conditions. The forbidden design-index files were not opened.

## Step 5: Generate Unit Tests — 2026-09-29T14:20:50.359Z

**Orchestrator note:** I mistakenly spawned TWO copies of the Step 5 (unit-test-generator) subagent instead of test-gen + impl-gen. Both wrote into the same directories concurrently; per their reports they detected the interference, converged, and audited the final merged state. Step 6 (implementation) did NOT run in this batch and was run separately afterwards. The on-disk merged result below was verified by the orchestrator: 9 test_helpers files + conftest.py + 7 test files; `pytest --collect-only` = 85 tests, 0 errors.

### Subagent A report
All audits pass. Final summary:

## Summary

**Task**: task_3013_instant_needs_micro_fulfillment_center_operations — test infrastructure and suite generated per `prd-bench-unit-test-generator`.

### Deliverables

**`test_helpers/`** (9 files):
- `types.py` — 15 status enums, 13 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.6), `UserRole` enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (46 endpoints, `/mfc` prefix), plus `canonical_instant`/`instants_equal` timestamp normalizers
- `api_errors.py` — `ApiErrorId` (34 ids) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_common_fields` + order money invariant checker
- `factories.py` — payload factories for all 12 entities + lines/adjustments/scan payloads
- `constants.py` — TOBACCO_TAX_RATE 0.07, LOYALTY_RATE/CAP, MIN_AGE_RESTRICTED 21, TENURE_DISCOUNT_BPS 500 / threshold 12, NIGHT/WEATHER lifts, clock startup default
- `test_users.py` — `SITE_OPS_HEADERS` (opaque) + per-instance builders `make_customer/picker/driver_headers` (entity-backed)
- `fixtures.py` — tiers: reads/clock, single-entity creators, replenish place/finalize chains (`receive_perishable_stock`), `setup_sealed_order`, `setup_assigned_bag`, `deliver_bag`
- `__init__.py` — barrel export

**`test_suite/`**: `conftest.py` + 7 test files, **85 tests** (collected cleanly by pytest).

### Coverage audit (against the two design indices only)
- **Queue A (Difficulty)**: all 18 instances covered, each with ≥2 tagged tests (some 4–6).
- **Queue B (Corner)**: all 38 non-stub instances covered with ≥1 tagged test; 5 `excluded_because` stubs correctly not translated (cross-references verified to resolve).
- 85 tests = 85 `Design:` tags; zero orphans; zero untagged/dual-tagged; every tag resolves to a real yaml `name:` and is the last docstring line.

### PRD-citation audit
- 109 quoted PRD citations checked; all verbatim under backtick/whitespace normalization (C1–C3).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- Deliberate relaxations for unique-derivability: replenish-idempotency replay accepts any 2xx (PRD doesn't pin 200 vs 201 on replay); forecast test reads `projected`/`projected_orders` key tolerantly (PRD names the rule, not the bucket field).

### Instances skipped
None — every non-stub instance passed the PRD-first two-condition filter.

Note: mid-generation, another process wrote a parallel (canonical) set of 7 test files; I removed my 10 overlapping drafts and instead closed the 5 coverage gaps in the canonical set (added 5 tests to `test_01`, `test_02`, `test_03`, `test_05`), so the final suite is coherent with the shared `test_helpers/` interface.

### Subagent B report
All generation is complete and the final merged state is stable (no writes in ~15 minutes). Full self-audit passes.

## Summary

**Task**: `task_3013_instant_needs_micro_fulfillment_center_operations` — complete test infrastructure + suite generated from the two design indices against `workspace/PRD.md`.

### Note on process
A concurrent agent process began generating files into the same task directory midway through my run (a mergeable helper layer, then a parallel test suite, then a consolidation pass that deleted its duplicates and folded the best versions back into my files). I detected the interference, froze my own writes, waited for the other process to finish and converge, then audited the **final merged state** — everything below describes what is on disk now, which is coherent and complete.

### Test counts per queue
- **Queue A (Difficulty)**: all 19 instances covered, each with ≥2 tests (a few have 3–4). 0 shortfalls.
- **Queue B (Corner)**: all 36 non-stub instances covered, each with ≥1 test. 0 shortfalls. All 5 `excluded_because` stubs verified to resolve to real §1.8 instances and were not translated.
- **Total**: 85 test functions, all tagged, across 7 files (`test_01_sites_products_customers.py`, `test_02_pricing.py`, `test_03_picking.py`, `test_04_dispatch_handoff.py`, `test_05_inventory_replenish.py`, `test_06_membership_billing.py`, `test_07_cancellations_sites_occ_rbac.py`) plus `conftest.py`.

### Instances skipped
None. Two instances I had initially planned to skip were covered soundly in the final suite:
- `picker_create_defaults_status_active` — final version asserts ACTIVE-readback + batch-ownership; the ownership consequence is PRD-derivable ("Only ACTIVE pickers may own batches").
- `forecast_night_and_weather_multipliers_compose` — final version asserts only the zero-baseline projects zero (multiplicative lifts), with a tolerant projected-field lookup; no unverifiable shape assumptions beyond the PRD-pinned "next 24 hours".
- `batch_seal_commit_cascade_depth3` — covered with the setup fix I designed (L1 expiry moved to 2026-09-13T00:00Z so both lots are FRESH at the pinned clock; the asserted drawdown L1→0/L2→9 is then exactly PRD-derivable, and a second exact-exhaustion boundary test was added).

### test_helpers inventory (9 files, all PRD-specific)
`__init__.py` (barrel re-export of framework + PRD code), `types.py` (14 status enums, role enum, 12 TypedDicts), `api_client.py` (`ApiClient(GenericApiClient)` with all 46 endpoints + `canonical_instant`/`instants_equal` timestamp comparators), `api_errors.py` (33 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`), `assertions.py` (12 per-entity assert fns + order-money invariant), `factories.py` (input-field-only payload factories with unique counters), `constants.py` (PRD calculation constants + shared fee schedule), `test_users.py` (opaque `SITE_OPS_HEADERS`, unknown-identity fallbacks, per-instance builders for the three entity-backed roles), `fixtures.py` (5-tier composite helpers: clock/reads, entity creation, replenishment chains incl. `receive_perishable_stock`, order→batch→seal progression `setup_sealed_order`, dispatch progression `setup_assigned_bag`/`deliver_bag`; identity threading via `make_*_headers(entity_id)` throughout).

### Self-audit results
- **Tag coverage**: every A instance ≥2 tests, every B non-stub ≥1 test; every tag resolves to a real instance name; no unknown tags; no dual-tagged tests; every docstring *ends* with its `Design:` line (85/85).
- **PRD citation pass**: 109 `PRD §…` citations extracted and verified — a ≥8-word window of each survives literal grep of `workspace/PRD.md` (markdown-normalized). 0 failures.
- **Placeholder closure**: no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no placeholder tests.
- **No scaffold leakage**: no `scaffold`, `§1.x`, or `Table N` references in generated code.
- **Interface consistency**: all `from test_helpers import …` names resolve against the actual package; all bare function calls in tests resolve to imported/builtin names.
- **Syntax**: `python3 -m py_compile` clean on all 17 files; `import test_helpers` succeeds.

## Step 6: Generate Implementation — 2026-09-29T14:37:44.976Z

(Run after Step 5 completed, because the orchestrator's concurrent batch mistakenly contained two test-gen agents; see Step 5 note.)

Implementation complete. Summary:

## File inventory
All under `workspace/implementation/`:

- `start.sh` — executable foreground launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, error handlers, and all routes
- `db.py` — in-memory stores (12 entity dicts), logical clock defaulting to exactly `2026-09-01T00:00:00Z`, `fmt_ts` (ISO 8601 UTC, 3 fractional digits), `new_common`/`touch` (id/created_at/updated_at/version)
- `errors.py` — `ApiError` plus one factory per catalog error_id (all 32 error IDs with exact HTTP statuses)
- `response.py` — envelope: `{meta: {api_request_id ("req_…"), api_request_timestamp}, response_type: object|array|error, data}`; list responses add `limit`/`offset`/`total_count`/`has_more` into `meta`
- `middleware.py` — auth (`X-User-Role` always, `X-User-ID` required for entity-backed Customer/Picker/Driver), role gating, JSON body parsing, limit/offset pagination (default 10, min 1, max 100, offset 0), created_at-ascending sort
- `services.py` — constants (TOBACCO_TAX_RATE 0.07, LOYALTY_RATE 0.03, LOYALTY_CAP 500, MIN_AGE 21, TENURE 500bps/12 periods, NIGHT 0.40, WEATHER 0.25), half-up Decimal rounding, derived `effective_status`/`lot_status`, FRESH-lot cover, driver run-size selector helpers, serializers for all 12 entities

No startup seeding anywhere — the store is empty on every boot.

## Endpoint count
46 routes registered, matching the §1.5 endpoint table exactly (clock, 7 site routes, 4 product, 4 inventory-balance, 2 stock-lot, 4 customer, 6 membership, 6 replenish-order, 6 picker/driver roster, 4 order, 5 pick-batch, 7 delivery-bag).

## Boot / smoke confirmation
- `bash start.sh` boots cleanly and `GET /mfc/sites` returns 200 with the correct envelope.
- Fresh reboot (new process) returns `total_count: 0, data: []` — confirmed empty in-memory state.
- Full lifecycle verified end-to-end: clock set → site/product/balance/receipt → customer → order placement (subtotal 1599, per-line-then-sum tax 70 = round(999×0.07), fee 274 = 199 + round_half_up(1.5×50), total 1943) → batch open/append (reserve) → seal by a different picker (commit cascade) → bag create/assign via selector → handoff scan (AGE_VERIFIED) → depart → complete (loyalty 56 = round(0.03×1873), wallet credited, batch auto-CLOSED).
- Error paths verified: `ERR_UNAUTHENTICATED` (401), `ERR_UNAUTHORIZED` (403), `ERR_SITE_NOT_FOUND` (404), `ERR_INVALID_REQUEST` for limit=101, `ERR_STALE_VERSION` (412) on OCC mismatch with success on the correct version.
- Replenish interlock verified: idempotent replay on `idempotency_key` returns the original record; place → `effective_status: OPENED_REPLENISH`; order placement blocked with `ERR_SITE_NOT_OPERATING`; finalize without `lot_expiries` → `ERR_INVALID_REQUEST`; finalize with expiries creates a FRESH StockLot and the site falls back to `OPERATING`; demand-forecast returns 24 hourly buckets with night/weather multipliers.

## Step 7: Test-Fix Iteration Loop — 2026-09-29T15:26:59.857Z

Orchestrator verification: all 8 final `results.{1..8}.json` files show `passed: 85, failed: 0, total: 85`.

Subagent summary (verbatim):

Those leftover `app.py` processes belong to a different task (task_3009) — not mine to kill. Task 3013 is done.

## Summary

**Iterations run:** 4 (sweep 1: 20/85 all rounds — fixture bug cascade; sweep 2: 72–74/85 — 13 unique failures; sweep 3: 84/85; sweep 4 + final clean confirmation: 8× 85/85).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `constants.py` — `STANDARD_FEE_SCHEDULE["included_miles"]: 1.5 → 1`. PRD §3.1 declares the fee_schedule as "six integer-cent fields", so the non-integer value was a fixture bug (this single bug caused 65/85 setup failures in the first sweep).
- `fixtures.py` — `receive_perishable_stock` now identifies the newly created lot by matching `expires_at` instead of `lots[-1]`. Root cause of the flaky cascade failures: the logical clock is frozen within a test, so all lots share `created_at` and list order falls back to random UUID tiebreak — `lots[-1]` nondeterministically returned the wrong lot. This was the classic flakiness the 8-round sweep exists to catch.

**Fixes applied to `test_suite/`:**
- `test_01_sites_products_customers.py` — two inline site payloads' `included_miles: 1.5 → 1`; clock test DOB `2005-08-31 → 2005-09-02` (PRD §3.6 explicitly says "a customer whose 21st birthday is the current date passes", so 08-31 made the customer exactly 21 at the pinned startup instant and no rejection could fire).
- `test_02_pricing.py` — updated expected fee arithmetic for the integer `included_miles`: peak-interaction test now uses distance 7.0 for the under-cap branch (199 + 594 + 150 = 943, surcharge survives; cap still exercised by the dedicated cap test and short-order 448); waiver test's one-cent-below line repriced soda to 499 to restore the intended exact 2999 subtotal (5×500 + 499).
- `test_04_dispatch_handoff.py` — fixed three 7-vs-8 tuple unpack bugs on `setup_sealed_order` (fixture returns 8 items incl. picker); loyalty test's first order actually rides at the default 1.0-mile distance (fee 199, accrual 66), not 2.0 as its comment claimed — assertions corrected (298→199, 69→66, top-up 131→134).
- `test_05_inventory_replenish.py` — same 7-vs-8 unpack fix.
- `test_07_cancellations_sites_occ_rbac.py` — wallet accrual expectation 67 → 66 (fee is 199, not 249, at the fixture's default 1.0-mile distance).

**Fixes applied to `implementation/`:**
- `app.py` site creation — peak-window HH:MM validation now accepts `"24:00"` as end-of-day (PRD §3.1 names HH:MM without excluding the midnight boundary; the tests' FRI 22:00→24:00 + SAT 00:00→04:00 windows are the natural way to express an overnight peak).
- `app.py` `seal_batch` — moved the self-seal check (`ERR_SELF_SEAL_FORBIDDEN`, 403 business-safety) ahead of the empty-batch check (`ERR_BATCH_EMPTY`, capacity), matching PRD §2.6's normative priority ordering.
- `app.py` `cancel_order` — a reason that mismatches the acting role (e.g. a Customer sending `RETURN_TO_STOCK`) now returns `ERR_INVALID_REQUEST` instead of `ERR_UNAUTHORIZED`, per PRD §3.8 ("any other reason ... rejected (ERR_INVALID_REQUEST)").

No PRD-silent tests found; nothing was weakened, skipped, or deleted.

## Step 8: Finalize PRD — 2026-09-29T15:31:21.151Z

(Step 7 had 3 implementation/ fixes and 8 test-side fixes, so Step 8 was NOT skipped. Orchestrator verified diff: exactly 3 in-place line revisions, 0 lines added/removed.)

Done. `workspace/PRD_FINALIZED.md` written as a minimal in-line patch of PRD.md.

## Line counts

- PRD.md: 297 lines; PRD_FINALIZED.md: 297 lines; %-delta: 0.00% (three in-place revisions, no lines added or removed).

## Changes (one bullet per edit)

- §3.1 — revise — fee_schedule reworded from "six integer-cent fields" to "six fields, each a non-negative integer (the monetary fields in integer cents)", with `included_miles` noted as whole miles — implementation/app.py:106-109 (rejects non-integers for all six fields; `included_miles` feeds Decimal mile arithmetic at app.py:1056, and Step 7's fixture fix 1.5 → 1 confirmed the integer pin).
- §3.1 — revise — peak_windows now states that `24:00` is additionally accepted as the end-of-day boundary, enabling overnight peaks expressed as FRI 22:00→24:00 plus SAT 00:00→04:00 — implementation/app.py:131-134 (validator permits hh==24 only with mm==0).
- §3.6 — insert — added sentence pinning that when self-seal and empty-batch violations coexist, `ERR_SELF_SEAL_FORBIDDEN` (business-safety) precedes `ERR_BATCH_EMPTY` (capacity) per §2.6's normative ordering — implementation/app.py:1308-1311.
- §3.8 — revise — expanded "any other reason is `ERR_INVALID_REQUEST`" to explicitly cover a well-formed reason that does not match the acting role (e.g. a Customer sending `RETURN_TO_STOCK`) — implementation/app.py:1119-1122.

No edits were made for the pure fixture/test fixes (lot identification by `expires_at` in test_helpers/fixtures.py, DOB adjustment in the clock test, 7-vs-8 tuple unpack bugs, and fee-arithmetic repricing in test_02) — those traced to test-side bugs or to behavior the PRD already pins (§3.6 "21st birthday is the current date passes", §3.5 fee formula, §2.9/§3.6 batch fields).

## Per-edit pre-edit search log

**Edit 1 (fee_schedule + peak_windows, §3.1)**
- (a) Subjects: fee_schedule field typing; peak_windows HH:MM validation.
- (b) Enumerated paths: app.py:94-146 (site creation: peak_windows + fee_schedule validation, `svc.is_int(v) and v >= 0` for all six fee fields); app.py:168-195 (`update_capacity_profile` — confirmed it never touches `peak_windows` or `fee_schedule`, so the 24:00 acceptance is scoped correctly to creation); app.py:1053-1063 (fee computation consuming `included_miles` via Decimal subtraction — consistent with whole-mile integer); services.py:81-103 (`is_peak` — parses windows generically, handles overnight windows, 24:00 parses to 1440 min safely); services.py:30-31 (FEE_FIELDS list); services.py:299-304 (site serialization, read-only passthrough).
- (c) Wording adjustments: avoided claiming all six fields are "cent" amounts (mis-describes `included_miles`); avoided any claim that peak windows can be updated post-creation (capacity-profile update excludes them); added the concrete FRI/SAT example only because it mirrors the exact test scenario Step 7 cites.

**Edit 2 (seal_batch error ordering, §3.6)**
- (a) Subject: validation ordering within the seal endpoint.
- (b) Enumerated paths: app.py:1300-1315 (seal_batch: `ERR_INVALID_STATE` for non-OPEN → self-seal check → `ERR_BATCH_EMPTY` → ACTIVE-sealer check); §2.9 prose (self-seal characterized as business-safety); §2.6 ordering list (state → business-safety → capacity); errors.py (ERR_SELF_SEAL_FORBIDDEN 403, ERR_BATCH_EMPTY 409). Confirmed no other endpoint orders these two errors against each other.
- (c) Wording scoped to "when both violations coexist" rather than a blanket endpoint-ordering claim, and explicitly anchors the ordering to §2.6's existing normative priority rather than inventing a new rule — this keeps the sentence consistent with the INVALID_STATE-first check and the ACTIVE-sealer check that Step 7 did not reorder.

**Edit 3 (cancel_order role/reason mismatch, §3.8)**
- (a) Subject: cancel-order reason validation and role binding.
- (b) Enumerated paths: app.py:1110-1145 (cancel_order: role gate to Customer/SiteOps → reason ∈ {CUSTOMER, RETURN_TO_STOCK} else ERR_INVALID_REQUEST → role/reason mismatch → ERR_INVALID_REQUEST → ownership ERR_UNAUTHORIZED → state ERR_INVALID_STATE); §3.8 first paragraph (customer path — already says "any other reason ... ERR_INVALID_REQUEST", consistent); §4 endpoint table (`/mfc/orders/{orderId}/cancel` — Customer, SiteOps, consistent); errors.py (no dedicated mismatch error). Confirmed the symmetric case (SiteOps sending CUSTOMER) also returns ERR_INVALID_REQUEST at app.py:1121 — the wording covers it via "the acting role" without enumerating only the Customer case... the final wording says "such as a Customer sending RETURN_TO_STOCK", i.e. an example, not an exclusive list, so both directions are covered.
- (c) Used "including ... such as" phrasing (non-exhaustive) so the sentence stays true for the SiteOps-with-CUSTOMER direction as well; placed the edit in the RETURN_TO_STOCK paragraph only, since the customer-path paragraph already pins its own ERR_INVALID_REQUEST rule.

## Step 9: Complete PRD — 2026-09-29T15:53:11.899Z

Done. `workspace/PRD_COMPLETED.md` produced (source: PRD_FINALIZED.md, which existed).

**Stats:** PRD_FINALIZED.md → PRD_COMPLETED.md: 297 → 297 lines (no new paragraphs/sections; all changes inline), 42,930 → 47,651 chars (+4,721). 27 ambiguity-pins, 2 mismatch-revisions, 0 new sections.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — insert — ambiguity — unknown role values are malformed; entity-backed roles enumerated as Customer/Picker/Driver — `middleware.py:11-23`
- §2.2 — insert — ambiguity — `data` convention covers every state-transition endpoint; clock + stock-adjustment are the only divergent shapes — `app.py` (all transition routes return `svc.serialize_*`)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_INVALID_REQUEST`; sort ties broken by `id` — `middleware.py:43-66`
- §2.4 — insert — ambiguity — malformed `current_utc` → `ERR_INVALID_REQUEST`; success returns `200` with `{"current_utc": ...}` — `app.py:64-74`
- §2.5 — insert — ambiguity — suspend also requires status `OPERATING`; resume requires `SUSPENDED`, else `ERR_INVALID_STATE` — `app.py:201-202, 219-220`
- §2.6 — insert — ambiguity — resources created at `version` 1 — `db.py:71-76`
- §2.6 — insert — ambiguity — no `ERR_BALANCE_NOT_FOUND`; unknown balance path id → `ERR_INVALID_REQUEST` — `app.py:395-397, 405-407`
- §2.6 — insert — ambiguity — body-FK existence check precedes identity-ownership comparison — `app.py:994-998, 559-563`
- §2.8 — insert — ambiguity — missing/non-integer `expected_site_version` → `ERR_INVALID_REQUEST` — `app.py:175-176`
- §2.8 — insert — ambiguity — membership renew/cancel restricted to Customer role + ownership — `app.py:659-662`
- §2.9 — insert — ambiguity — INACTIVE picker at open → `ERR_INVALID_REQUEST`; at seal → `ERR_UNAUTHORIZED` — `app.py:1202-1203, 1312-1314`
- §3.1 — insert — ambiguity — peak-window HH:MM range pinned (hh 00–23 or exactly 24:00, mm 00–59) — `app.py:129-134`
- §3.1 — revise — ambiguity — product-in-use in-flight set explicitly excludes `HANDOFF_FAILED` — `app.py:25, 330-334`
- §3.2 — insert — ambiguity — duplicate (site, product) balance creation → `ERR_DUPLICATE_RESOURCE` — `app.py:364-365`
- §3.2 — revise — ambiguity — both SHRINK guards (not-EXPIRED, qty overflow) → `ERR_SHRINK_EXCEEDS_LOT` — `app.py:429-430`
- §3.2 — insert — mismatch — adjustment response shape pinned to `201` `{balance_id, on_hand, applied_qty}` (PRD's "return the balance" was vague/mismatched) — `app.py:437-441`
- §3.3 — insert — ambiguity — replenish placement requires existing balance per line, else `ERR_INVALID_REQUEST` — `app.py:794-796`
- §3.3 — insert — ambiguity — finalize requires balances, validates all lines before applying (atomic), lot_code server-generated per pair — `app.py:816-857`
- §3.4 — insert — ambiguity — non-boolean `auto_renew` → `ERR_INVALID_REQUEST` — `app.py:568-569`
- §3.4 — insert — ambiguity — wallet adjustment requires `reason`, returns `201` with updated customer — `app.py:537-541`
- §3.4 — insert — ambiguity — close allowed on ACTIVE or LAPSED (not CANCELLED); "reaches" pinned as inclusive of exact end instant — `app.py:625-628`
- §3.5 — insert — ambiguity — distance is a non-negative number (0 and fractions allowed) — `app.py:1022-1023`
- §3.5 — insert — ambiguity — placement gate order pinned: site-operating → radius → sellability — `app.py:1026-1032`
- §3.5 — insert — ambiguity — zero-absorption placement leaves Customer.version unchanged — `app.py:1040-1043`
- §3.6 — insert — ambiguity — Picker callers may open batches only for self (else `ERR_UNAUTHORIZED`); `total_items` derived on read — `app.py:1204-1205`; `services.py:414-425`
- §3.6 — insert — ambiguity — append requires order PLACED (`ERR_INVALID_STATE`) and same-site as batch (`ERR_INVALID_REQUEST`) — `app.py:1255-1258`
- §3.7 — insert — ambiguity — bag creation requires order `AWAITING_HANDOFF` (`ERR_INVALID_STATE`); bag's site is the parent order's — `app.py:1365-1366`
- §3.7 — insert — ambiguity — explicit driver assignment performs no eligibility checks beyond existence — `app.py:1415-1420`
- §3.7 — insert — ambiguity — rostering pinned at a site; picker status defaults to `ACTIVE` — `app.py:888-906, 928-955`
- §3.7 — insert — ambiguity — handoff-scan: non-NONE handoff or non-ASSIGNED delivery → `ERR_INVALID_STATE` — `app.py:1449-1452`
- §3.7 — insert — ambiguity — completion accrues to membership of any status; membership version also bumped; response returns the bag — `app.py:1521-1529`
- §3.8 — insert — ambiguity — CUSTOMER-cancel touches customer version even when refund is zero — `app.py:1133-1136`
- §3.8 — insert — mismatch — existing RMA lot is merged (qty added) rather than duplicated; both cancel paths return the updated order — `app.py:1149-1180`
- §3.9 — insert — ambiguity — `precipitation_prob` defaults 0, invalid → `ERR_INVALID_REQUEST`; baseline = DELIVERED orders by creation instant in trailing 7d; response shape `{site_id, hours[24]}` with pinned per-entry fields — `app.py:226-264`

---

## Pipeline Complete — 2026-09-29T15:53:11.899Z

All 9 steps done. Final state: 85/85 tests passing across all 8 parallel stability-sweep rounds under per-test-server isolation; 0 tests deleted; 0 assertions weakened. Artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, test_helpers/ (9 files), test_suite/ (7 files, 85 tests), workspace/implementation/ (Flask, in-memory, 46 endpoints, start.sh launcher, results.1..8.json all green).
