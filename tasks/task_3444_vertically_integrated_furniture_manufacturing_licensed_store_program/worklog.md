# Worklog — task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program

## Step 1: Create task directory — 2026-10-02T04:02:00.000Z

Pre-allocated task directory confirmed: `tasks/task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program/` with `workspace/` inside (no new index computed, per entrance args). Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-02T05:29:00.000Z

All three artifacts are complete and verified. (Note: the task directory already contained a small pre-existing `worklog.md` and empty `workspace/` from an earlier process at 04:02 — not created by me; I left them untouched.)

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**: 11 entities · 11 state machines (incl. SupplyOrder's parallel `allocation_state × fulfillment_state` axes and cyclic Licensee/WarrantyClaim/Territory machines) · 8 calculations · 10 ordered validation priorities · 41 endpoints (40 business under `/api` + unprefixed `POST /_clock/set_current_utc`, default clock `2026-09-01T00:00:00Z`) · 43 errors · 6 roles (LicenseeManager/WholesaleBuyer entity-backed; rest opaque) · 2 OCC concurrency rules · 18 difficulty instances (9 rules × 2) · 61 corner instances (54 real + 7 `excluded_because` stubs).

**Lint**: `VERDICT: clean lint` — 864 §1.8/§1.9 calls conform to §1.5; all 13 FKs reverse-reachable. Zero violations on first run.

**Design decisions worth noting**:
- Archetype: quota/allocation (weekly `AllocationCycle` per factory with a licensee-cap/wholesale-floor waterfall, waitlist demotion *and* best-fit backfill) blended with temporal windowing — two deliberately different interval semantics (aggregate crew-capacity overlap on DCs vs strict half-open week exclusion per factory).
- Termination cascade pinned with **snapshot semantics** (drop set evaluated at terminate-time, before territory-revocation appointment cancels revert SHIPPED→PICKED) — this keeps the depth-3 cascade deterministic instead of deadlocking.
- Both Rule-1 dual variants are fully computed: delivery fee estimate 19900 vs final 30900; licensee score instantaneous 35.00 vs seasoned 62.86 (weight-renormalized over ≤4 closed cycles).
- Every constant is pinned (price ladder, tier qtys 10/25/50, 30% licensee discount, 75% clearance keep, 25% wholesale floor, 50% constrained capacity, 48h lead, 120–360min windows, 120min missed grace, 365d/30d warranty windows, 60/40/75 score thresholds, 0.15 chargeback, max 3 territories).
- One arithmetic bug caught and fixed during self-verification: a pinned literal `3855700` corrected to `3865700` (77314 × 50) in the hold-vs-credit priority instance; all other assert literals re-executed from the formulas and confirmed.

Orchestrator verification: all three files exist and parse as valid YAML with correct top-level keys (SCAFFOLD.yaml keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, ...). Sizes: SCAFFOLD.yaml 81879 B, SCAFFOLD_CORNER_DESIGN.yaml 96389 B, SCAFFOLD_DIFFICULTY_DESIGN.yaml 73342 B.

## Step 3: Copy shared files — 2026-10-02T05:31:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-10-02T05:55:00.000Z

PRD generation is complete and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program/workspace/PRD.md` — 335 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (6 roles with identity semantics), 2.2 API Response Structure (verbatim canonical block, byte-identical confirmed), 2.3 Pagination, 2.4 Common Resource Properties & Mutation Semantics, 2.5 The Logical Clock, 2.6 Money/Rounding/Precision, 2.7 Optimistic Concurrency Control, 2.8 Validation Pipeline & Error Precedence (all 10 priorities in order), 2.9 Nested Resource Retrieval & Existence Ordering
- §3 Business Logic & Workflows: 3.1 Manufacturing Footprint & Product Catalog, 3.2 Licensees & Territories, 3.3 Wholesale Accounts & Open Credit, 3.4 Production Weeks & the Capacity Waterfall, 3.5 Supply Orders Dual-Axis Lifecycle, 3.6 Home Delivery Operations, 3.7 Warranty/Chargebacks/Parts, 3.8 Performance Standards & the Seasoned Score
- §4 Endpoint Definitions (41 rows, 4 columns, all scaffold paths present)
- §5 Error Code Catalogue (43 rows, 2 columns, all scaffold errors present)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 83 required identifiers (87 entity-field slots + request-body + query-param identifiers deduplicated), 0 missing — PASS
- Contract 2 (Rule Coverage): all 34 state values and all 53 transition pairs expressed; all 43 error IDs appear in §2/§3 prose; both OCC rules complete (endpoint + `expected_<parent>_version` + error id + 412); all calculation constant names and values present; all 10 validation priorities stated in explicit order — PASS
- Contract 3 (§3 Path Purity): 560 backticked tokens scanned, 0 path/method violations — PASS

**Constants confirmed verbatim in prose (name + value):** price ladder 39900/59900/89900/129900/189900 (`PRICE_LADDER_CENTS`), `LICENSEE_DISCOUNT_RATE` 0.30, `CLEARANCE_MARKDOWN_KEEP` 0.75, tiers `TIER1_QTY` 10 / `TIER2_QTY` 25 / `TIER3_QTY` 50 with rates 0.05/0.09/0.14, `WHOLESALE_FLOOR_PCT` 0.25, `LICENSEE_GUARANTEE_PCT` 0.60, 50% CONSTRAINED capacity floor, `MISSED_GRACE_MINUTES` 120, `DELIVERY_MIN_LEAD_HOURS` 48, `WINDOW_MIN_MINUTES` 120 / `WINDOW_MAX_MINUTES` 360, 365d/30d warranty windows (boundary day passes), `PERF_PROBATION_THRESHOLD` 60.00 / `PERF_SUSPENSION_THRESHOLD` 40.00 / `PERF_RECOVERY_THRESHOLD` 75.00, `SEASONED_WEIGHTS` 0.4/0.3/0.2/0.1 with renormalization, `CHARGEBACK_RATE` 0.15, `MAX_TERRITORIES_PER_LICENSEE` 3, `INFO_REQUEST_MAX` 2, fee constants (`CALL_OUT_CENTS` 14900, `ZONE_CENTS` 0/5000/12000, `CREW_CENTS` 2500, `OVERAGE_BLOCK_MINUTES` 30, `OVERAGE_CENTS` 4000, `STAIRS_FREE_FLIGHTS` 1, `STAIRS_CENTS` 1500), clock start 2026-09-01T00:00:00Z, unprefixed `POST /_clock/set_current_utc`.

**Deliberate subtleties stated explicitly:** termination-cascade snapshot semantics (drop set fixed from fulfillment state at terminate time, before appointment cancellations; SHIPPED orders stay ALLOCATED/PICKED), the two contrasting interval semantics (strict half-open week exclusion with adjacency allowed per factory vs aggregate instant-wise crew overlap on DCs where touching windows do not overlap), waterfall ordering (licensee pass against K − floor(0.25K), then wholesale pass with best-fit backfill, demotion possible), promotion sweep (single rank-ordered scan; RESERVED while OPEN, ALLOCATED with final-price lock once ALLOCATED), round-unit-first-then-multiply and round-per-line-then-sum pinned, credit equality passes, score boundary equalities (60.00/40.00) do not trigger, and retirement drops leaving fulfillment PENDING vs cancel/termination/close drops setting CANCELLED.

The two withheld design-index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate unit tests — 2026-10-02T06:20:00.000Z

Generation complete. Final summary:

## Files written

**`test_helpers/` (9 files, frozen first):** `constants.py` (31 constants, each with its PRD citation comment), `types.py` (17 enums + 11 TypedDicts; all entities carry the four common fields), `api_errors.py` (all 44 error ids + HTTP map registered with the framework), `test_users.py` (opaque-role constants + mandatory `make_licensee_manager_headers`/`make_wholesale_buyer_headers` entity-backed builders), `factories.py`, `api_client.py` (all 35 endpoints; `set_clock` targets the **unprefixed** `/_clock/set_current_utc` per PRD §2.5), `assertions.py`, `fixtures.py` (6 tiers incl. `setup_hd_picked_order`, `setup_delivered_freight_order`, `play_scored_cycle`), `__init__.py` barrel — self-checked: imports cleanly, all exports resolve.

**`test_suite/` (17 files, 90 tests):** `conftest.py` + `test_01`…`test_16` clustered by concern (catalog, orders, pricing, credit, cycles/waterfall, conservation, order machine, territories, cascades, appointment guards, fees/capacity, warranty, performance, priorities, RBAC, OCC/reads).

## Coverage (AST tag audit, real parse)

- Queue A (Difficulty): **18/18 instances, each with exactly 2 tests**
- Queue B (Corner): **54/54 non-stub instances, 1 test each; 7 `excluded_because` stubs skipped** — all cross-references verified to resolve, none emitted as tests
- 0 orphan tags, 0 untagged/dual-tagged tests, 0 skip/xfail markers
- `pytest --collect-only -q`: **90 tests collected, 0 errors** (one dangling import — missing `get_product_line` fixture — was caught by collection and fixed)

## Constants diff

31/31 constants mechanically verified against verbatim PRD sentences (ladder, tiers 10/25/50 + rates 0.05/0.09/0.14, 0.30/0.75/0.25/0.60/0.5, 120min grace, 48h lead, 120/360 window, 365d/30d, 60/40/75, weights 0.4–0.1, 0.15 chargeback, 3 territories, info-max 2, all fee constants, clock start). No dead constants carried.

## Clock reachability

All `set_clock` targets ≥ 2026-09-01T00:00:00Z and forward-only within every test (multi-cycle tests step 09-07T08:00 → 09-14T08:00 → 09-21T08:00). The only pre-start dates (2026-08-30) are the deliberately-rejected `window_in_past` trigger payloads, never clock targets.

## Adjudications / re-derivations (design index vs PRD)

1. **`product_line_retirement_cascades`**: the design's assert ("DROPPED + CANCELLED") contradicts PRD §3.1's explicit "retirement does not mark them `CANCELLED`" — tests assert DROPPED + **PENDING** per PRD.
2. **Both performance instances (`performance_score_instantaneous_vs_seasoned_diverge`, `seasoned_score_exactly_sixty_stays_active`)**: the design's `setup_api_calls` under-submit orders (2-of-5 and 3-of-5) while its own literals require all five submitted (sell-through 40 and 60); fixtures submit all five per each instance's natural-language setup. Asserted literals (35.00/62.86, 60.00) verified by re-derivation.
3. **Warranty windows**: fail legs re-derived from "+1 second" to "+1 full day" (2027-09-06 / 2026-10-06). PRD's "filing exactly on the boundary day still passes" makes the +1s case fail the two-reader test (a day-granular reader accepts it); both readings agree on the day-after.
4. **`window_in_past_rejected`**: a past window necessarily violates both stage-8 guards and PRD pins no intra-stage order — per the error-precedence silence pattern, the test asserts HTTP 422 + `validate_error_is_one_of([ERR_WINDOW_IN_PAST, ERR_LEAD_TIME_TOO_SHORT])`.
5. **Absolute `version == 1` dropped** (factory-create, order-version-ignored corners): PRD §2.4 pins only "increments by exactly 1", never the initial value; tests assert int presence, `!= 99` for the ignored-input case, and exact `v+1` relative increments in the OCC tests (which is verbatim).
6. **`updated_at` "advanced" dropped** (terms-consistency corner): with all timestamps on the logical clock (PRD §2.5), a faithful impl re-stamps the same value when the clock hasn't moved; asserted presence + new field values + version increment instead.
7. **"No line persisted" dropped** (wholesale-buyer role denial): no product-line list endpoint exists, so non-persistence is unobservable; the 403 is asserted.

## Step 6: Generate implementation — 2026-10-02T07:05:00.000Z

That PID also exited on its own — the successive PIDs (462976 → 463225 → 463409) are short-lived external processes churning through the shared task directory, not servers from my runs (my `start.sh` sets cwd to `implementation/`; these have the task root). My one true orphan (433763) was found and killed; every smoke server was killed by its saved PID.

The implementation is complete and verified.

## Summary

**Files written** — all under `/home/ubuntu/github/CodingPRD/tasks/task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program/workspace/implementation/` (2389 lines total):

| File | Lines | Role |
|---|---|---|
| `constants.py` | 105 | every PRD constant exactly once (ladder, tiers, 0.30/0.75/0.25/0.60, fees, windows, perf thresholds/weights, clock start 2026-09-01T00:00:00Z, enums, roles) |
| `errors.py` | 61 | ApiError + full 43-entry error catalog with HTTP statuses |
| `db.py` | 34 | in-memory dict store, logical clock, creation seq; zero seeding |
| `util.py` | 260 | envelope/pagination (limit/offset/total_count/has_more, defaults 10/1..100/0), ISO ms timestamps, shape validators, serialize |
| `middleware.py` | 36 | auth (stage 1), role (3), ownership (4) |
| `services/calc.py` | 214 | pricing (round-unit-first), royalty/chargeback (round-per-line), credit, cycle counters, standing tier, delivery fees, aggregate capacity check |
| `services/engine.py` | 320 | waterfall, promotion sweep, close+scoring, retire cascade, terminate cascade (snapshot semantics), missed sweep |
| `routes/*.py` | ~1270 | clock (29), factories (75), product_lines (92), licensees (117), territories (88), retail_accounts (68), dcs (54), cycles (114), orders (235), appointments (175), claims (168), parts (63) |
| `app.py` / `start.sh` / `requirements.txt` | 61 | factory + lock + error handlers; guarded-install `exec` launcher reading `$PORT`, binding 0.0.0.0 |

**Verification**
- `python3 -m py_compile` on every file; `python3 -m pyflakes .` clean; `import app` succeeds (no dangling imports).
- Route count: exactly **41** (40 under `/api` + unprefixed `POST /_clock/set_current_utc`); Flask's `/static` disabled.
- Smoke: 79 functional assertions passed across two fresh `bash start.sh` boots on self-allocated ports (unit pricing 27930/34314/62930, waterfall demotion + waitlist promotion on OPEN and ALLOCATED cycles, credit equality passes / over-limit 422, OCC 412s, appointment fee 24900→31900, royalty 2234 / chargeback 8379 / net -6145, parts bubble-up, cycle close scoring 94.00 with seasoned==instantaneous, MISSED sweep strict boundary, termination snapshot leaving SHIPPED order ALLOCATED/PICKED). All servers killed by their own PIDs.

**Key interpretations chosen (Step 8/9 candidates)**
1. Entity timestamps read the **logical clock** (required for warranty windows and claims-in-cycle); `meta.api_request_timestamp` uses wall clock.
2. Rank tie-break: internal monotonic creation seq after `created_at` (PRD bans id-based ranking; logical clock ties are common).
3. Claim on non-DELIVERED order and PUT price on CLEARANCE/RETIRED line → `ERR_INVALID_TRANSITION` (409) — no dedicated catalog errors exist.
4. `code`/`region_code` uniqueness → `ERR_VALIDATION` (400) — scaffold says "unique" but maps no error.
5. Appointment CONFIRM with elapsed `window_start` → `ERR_WINDOW_IN_PAST` (422).
6. Body-FK ownership (appointment/claim create) evaluated after existence of the referenced order.
7. Invalid `to_state`/`action` enum values → `ERR_VALIDATION` (400); valid-but-no-edge → `ERR_INVALID_TRANSITION` (409).
8. Waterfall RETIRED-line drop leaves fulfillment unchanged (mirrors the retirement cascade).
9. Pagination out-of-range → `ERR_VALIDATION` (400).
10. `version` starts at 1; recomputed aggregates bump only on actual change; direct mutations bump exactly once per event per entity.
11. `info_note` / DENIED `decision_note` accepted as optional (scaffold marks them optional); `info_note` has no entity field and is not persisted.
12. Seasoned score blends the **rounded** stored instantaneous scores with renormalized weights; scoring counts orders that reached ALLOCATED and are not DROPPED at close.

## Step 7: Run tests and iterate — 2026-10-02T07:35:00.000Z

All 8 rounds pass 90/90. The final `results.1.json` … `results.8.json` artifacts remain in `workspace/implementation/` as required.

## Summary

**Iterations run:** 2 (initial sweep → fix → verification sweep, all 8 parallel rounds clean)

**Failure union (initial sweep):** 2 tests, failing deterministically in all 8 rounds — both in `TestProductLineRetirementCascade` in `test_suite/test_09_cascades.py`:
- `test_clearance_advance_fires_no_cascade`
- `test_retirement_drops_orders_and_releases_credit`

Both failed with `NameError: name 'setup_open_cycle' is not defined` at the shared `_setup()` helper (line 154).

**Diagnosis:** Pure test-file defect — a missing import, not a semantic mismatch. The helper `setup_open_cycle` is defined in `test_helpers/fixtures.py` and exported via the package's `from .fixtures import *` barrel (no `__all__` restricting it; its sibling `setup_hd_context` was already imported from the same module and worked). The tests' assertions themselves trace to PRD §3.1 verbatim (DROPPED + deliberately-unchanged PENDING fulfillment, credit release, capacity recompute) per the Step 5 worklog adjudication that overrode the design index's contradicting CANCELLED claim. STEP 1 coverage/derivability: satisfied. STEP 2: the expressed logic was faithful; the file simply failed to name a symbol it used.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3444_vertically_integrated_furniture_manufacturing_licensed_store_program/test_suite/test_09_cascades.py` — added `setup_open_cycle` to the `from test_helpers import (...)` block; one-line why: `_setup()` referenced it but the import list omitted it.

**Fixes applied to `implementation/`:** none — the implementation was already correct.

Orchestrator verification: all 8 `results.${i}.json` files present and show passed=90, failed=0, total=90, errors=0. `setup_open_cycle` import confirmed at test_09_cascades.py:25 (used at :155, defined at test_helpers/fixtures.py:271).

## Step 8: Finalize PRD — 2026-10-02T07:50:00.000Z

Step 8 complete. Zero edits — byte-identical copy, as the hard scope anticipated.

**Summary on exit**

- **Line counts:** PRD.md 334 lines, PRD_FINALIZED.md 334 lines — 0% delta. `diff -q` confirms byte-identical.
- **Changes:** zero edits — byte-identical copy. Justification via the evidence reads below: the single Step 7 item is a pure mechanical import fix revealing no PRD silence and no PRD/impl mismatch.

**Evidence-read log (Step 7 site: test_suite/test_09_cascades.py)**

- **(a) Test assertions read** (`test_suite/test_09_cascades.py`):
  - Lines 4-29: the fixed import block — `setup_open_cycle` added at line 25; `_setup()` at line 154-164 calls it. Pure NameError fix, no assertion touched.
  - `test_clearance_advance_fires_no_cascade` (lines 166-181): after ACTIVE→CLEARANCE, credit_used_cents stays 179800 and both orders stay RESERVED — no cascade on CLEARANCE entry.
  - `test_retirement_drops_orders_and_releases_credit` (lines 183-215): after CLEARANCE→RETIRED, both orders flip to DROPPED with fulfillment left PENDING (explicitly not CANCELLED), credit_used_cents recomputes to 0, and cycle counters recompute (licensee_reserved_units=0, wholesale_reserved_units=0, available_units=100, conservation check).
- **(b) PRD sentences covering them** (`workspace/PRD.md` §3.1, line 140 — verbatim match to the test docstrings' quotes):
  - "Entering `CLEARANCE` needs no recomputation — `clearance_price_cents` already reflects the 75-percent keep — but from that moment on, orders created or submitted price off the clearance base."
  - "Entering `RETIRED` fires a three-hop cascade. Hop 1: every supply order on this line whose allocation state is `RESERVED` or `WAITLISTED` flips to `DROPPED`, while its fulfillment state is deliberately left unchanged — such orders are still `PENDING` by construction, and retirement does not mark them `CANCELLED`... Hop 2: each dropped order's allocation cycle recomputes `licensee_reserved_units`, `wholesale_reserved_units`, and `available_units`... and each affected retail account recomputes `credit_used_cents`... Hop 3: per affected cycle, the waitlist promotion sweep of §3.4 runs."
- **(c) Impl code paths read confirming the behavior:**
  - `workspace/implementation/routes/product_lines.py:56-70` (`advance_line`) — one step per call; CLEARANCE entry performs only the lifecycle flip (no cascade); RETIRED entry calls `retire_line`.
  - `workspace/implementation/services/engine.py:226-243` (`retire_line`) — drops RESERVED/WAITLISTED orders via `drop_order(o, cancel_fulfillment=False, ...)`, recomputes affected cycles (`calc.recompute_cycle`) and retail accounts (`_recompute_accounts`), then runs `promotion_sweep` on OPEN/ALLOCATED cycles.
  - `workspace/implementation/services/engine.py:35-40` (`drop_order`) — with `cancel_fulfillment=False`, allocation → DROPPED and fulfillment deliberately untouched (stays PENDING).
- **(d) Conclusion:** implementation/ exhibits exactly the behavior PRD.md §3.1 already states verbatim, and the tests assert exactly that behavior. The Step 7 fix was a missing-import NameError repair with zero semantic content. No PRD silence, no PRD/impl mismatch → no edits. PRD_FINALIZED.md ships as a byte-identical copy.

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed independently. All 8 `results.*.json` still present. No implementation/*.py or *.sh file newer than the sweep results (no post-sweep impl writes).

## Step 9: Complete PRD — 2026-10-02T08:20:00.000Z

All verification complete. The file is coherent, no truncation, and the diff is exactly 23 in-place revisions plus 1 pure insertion.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` 334 lines / 56,460 chars → `workspace/PRD_COMPLETED.md` 335 lines / 60,464 chars (Δ +1 line, +4,004 chars). Only `workspace/PRD_COMPLETED.md` was edited; implementation/, test_suite/, test_helpers/ untouched.

**Counts:** 24 changes total — all 24 are **ambiguity-pins**; **0 mismatch-revisions** (0 IMPL-GAP, 0 PRD-DEFECT). No PRD claim had to be stripped: every impl behavior I found was either already pinned or fell in PRD silence/ambiguity. The two nearest-to-contradiction cases (§2.4 "aggregates increment version on every resource they touch" vs bump-only-on-change; §3.7 "Denial moves the claim to DENIED with a decision_note" vs optional note) both admit the impl's reading and were pinned, not revised away.

**Change log (section — kind — class — what — evidence):**
1. §2.2 — insert — ambiguity — framework errors `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) / `ERR_INTERNAL` (500) in the standard envelope — `implementation/app.py:29-40`
2. §2.3 — revise — ambiguity — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_VALIDATION` (400) — `implementation/util.py:233-250`
3. §2.3 — revise — ambiguity — list ordering tie on equal `created_at` broken by creation sequence; filter params match exactly, no-match yields empty page not error — `implementation/util.py:251`, e.g. `routes/cycles.py:77-85`
4. §2.4 — revise — ambiguity — `version` starts at 1 at creation — `implementation/util.py:195-203`
5. §2.4 — revise — ambiguity — recomputed aggregates (cycle counters, `credit_used_cents`, licensee ledger) bump only when a stored value actually changes; one bump per resource per request max — `implementation/util.py:206-211`; `services/calc.py:84-148`; `services/engine.py:27-32,82-84,147-149,165-166,237-239,297-299`
6. §2.5 — revise — ambiguity — all entity/business timestamps read the logical clock; `meta.api_request_timestamp` is the sole wall-clock exception; backward clock sets permitted, sweep nothing — `implementation/util.py:15-29,52-53`; `routes/clock.py:25-28`
7. §2.8 stage 2 — revise — ambiguity — malformed/non-object JSON body is `ERR_VALIDATION`; `to_state`/`action` enum defects explicitly stage 2 — `implementation/util.py:81-90,160-164`
8. §2.8 stage 4 — revise — ambiguity — ownership read from a stored resource resolves that resource's existence (stage 5) first; only order create checks ownership from body FKs ahead of existence — `routes/appointments.py:46-49,130-132`; `routes/claims.py:35-36,113-114`; `routes/orders.py:54-57,133-135`
9. §2.8 closing — revise — ambiguity — within a stage, guards evaluate in that stage's enumeration order — verified at `routes/orders.py:152-177,193-235`; `routes/appointments.py:51-79`; `routes/territories.py:66-75`; `routes/retail_accounts.py:59-64`; `routes/product_lines.py:81-87`
10. §3.1 — revise — ambiguity — duplicate factory `code` → `ERR_VALIDATION` (400), evaluated after role authorization — `routes/factories.py:43-44`
11. §3.1 — revise — ambiguity — price PUT on `CLEARANCE`/`RETIRED` line → `ERR_INVALID_TRANSITION` (409) — `routes/product_lines.py:84-85`
12. §3.2 — revise — ambiguity — terms update accepts any subset including empty (version still bumps) — `routes/licensees.py:84-90`
13. §3.2 — revise — ambiguity — duplicate `region_code` → `ERR_VALIDATION` (400) after role authorization — `routes/territories.py:32-33`
14. §3.4 — revise — ambiguity — rank tie on equal `created_at` broken by creation sequence — `services/calc.py:168-169`; `db.py:21-30`
15. §3.4 — revise — ambiguity — waterfall `RETIRED`-line drop leaves fulfillment unchanged (mirrors §3.1 cascade) — `services/engine.py:132-134`
16. §3.5 — revise — ambiguity — submit provisional re-price applies on every submit (both `RESERVED` and `WAITLISTED` landings) and before the credit gate, which measures the re-priced total — `routes/orders.py:170-177`
17. §3.6 — revise — ambiguity — negative `stairs_flights` → `ERR_VALIDATION` (400) — `routes/appointments.py:43`
18. §3.6 — revise — ambiguity — duplicate DC `code` → `ERR_VALIDATION` (400) after role authorization — `routes/dcs.py:38-39`
19. §3.6 — revise — ambiguity — confirmation with elapsed `window_start` → `ERR_WINDOW_IN_PAST` (422); confirmation ships the order only if still `PICKED` — `routes/appointments.py:138-139,146-149`
20. §3.6 — revise — ambiguity — `actual_duration_minutes` must be a non-negative integer; completion delivers the order only if still `SHIPPED` — `routes/appointments.py:124-126,158-160`
21. §3.7 — revise — ambiguity — filing against a non-`DELIVERED` order → `ERR_INVALID_TRANSITION` (409); new claim carries `decision_note` null — `routes/claims.py:37-39,53`
22. §3.7 — revise — ambiguity — `info_note` accepted but never persisted — `routes/claims.py:98`
23. §3.7 — revise — ambiguity — `decision_note` optional on every adjudication transition including `DENIED`, stored when supplied — `routes/claims.py:97,124-125,137-138,147-148,165-166`
24. §3.8 — revise — ambiguity — seasoned blend inputs are the stored (already-rounded) instantaneous scores — `services/engine.py:197-209`

**12-interpretation checklist verdicts:**
1. Logical clock entities / wall clock meta — **pinned** (change 6)
2. Rank tie-break by internal creation sequence — **pinned** (changes 3, 14)
3. Claim on non-DELIVERED order → 409; price PUT on CLEARANCE/RETIRED → 409 — **pinned** (changes 11, 21)
4. `code`/`region_code` uniqueness → `ERR_VALIDATION` (400) — **pinned** all three sites (changes 10, 13, 18)
5. CONFIRM with elapsed `window_start` → `ERR_WINDOW_IN_PAST` (422) — **pinned** (change 19)
6. Body-FK ownership evaluated after referenced-order existence — **pinned** (change 8)
7. Invalid `to_state`/`action` enum → 400; valid-but-no-edge → 409 — **already-pinned** by §2.8 stage 2 ("enum values in range"); reinforced by explicitly naming `to_state`/`action` (change 7)
8. Waterfall RETIRED-line drop leaves fulfillment unchanged — **pinned** (change 15)
9. Pagination out-of-range → `ERR_VALIDATION` (400) — **pinned** (change 2)
10. `version` starts at 1; aggregates bump only on change; one bump per event per entity — **pinned** (changes 4, 5)
11. `info_note` not persisted; DENIED `decision_note` optional — **pinned** (changes 22, 23)
12. Seasoned blends rounded stored scores; scoring counts reached-ALLOCATED-and-not-DROPPED — **already-pinned** for the counting half (§3.8 "reached ALLOCATED at any point — orders that ended DROPPED, do not count", matching `engine.py:184`); the rounded-inputs half **pinned** (change 24)

**Impl observations reported, not fixed (edit boundary respected):**
- `routes/orders.py:175` and `routes/retail_accounts.py:62` recompute `credit_used_cents` in memory before the credit gate / zero-exposure check; on rejection the recomputed value persists without a version bump. Unobservable in practice since credit is recomputed on every order event, but it is a latent write-before-reject.
- `routes/claims.py:38`: the `buyer_type != "LICENSEE"` half of the claim-create guard is unreachable — a retail-account order has `licensee_id` None, so the ownership check (403) always fires first. Dead but harmless.
- `routes/appointments.py:147-149,159-160`: the conditional order ship/deliver on confirm/complete is the behavior pinned in changes 19-20; reachable only via cancelling an order while its appointment is still `REQUESTED`.

Orchestrator verification: `wc -l -c` confirms 334/56,460 → 335/60,464 exactly as reported. `diff -q` PRD_FINALIZED vs PRD_COMPLETED → differ (real edits, not a silent no-op); unified diff +31/−30 lines consistent with 23 in-place revisions + 1 insertion. `find implementation -name '*.py' -newer results.1.json` (excluding `__pycache__`) → 0 files: implementation untouched since the clean sweep. All 8 `results.*.json` present and passing (90/90 × 8 rounds).
