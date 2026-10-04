## Step 1: Create task directory — 2026-09-30T08:12:00.000Z

Pre-allocated directory tasks/task_3184_vehicle_allocation_turn_earn_distribution_order_management with workspace/ verified to exist; used as-is per instructions.

## Step 2: Generate scaffold — 2026-09-30T08:29:30.000Z

Scaffold generation complete. `VERDICT: clean lint` (verbatim lint output above).

## What was built

Task directory: `/home/ubuntu/github/CodingPRD/tasks/task_3184_vehicle_allocation_turn_earn_distribution_order_management/`

**SCAFFOLD.yaml** — Ford vehicle allocation / turn-and-earn domain, deliberately pushed past the Expert band:
- **14 entities**: Region, Dealer, ModelLine, Commodity, CommodityRestriction, AllocationRun, DealerAllocation, DealerModelLine, VehicleOrder, DealerTrade, Appeal, IncentiveProgram, Carrier, Shipment
- **9 state machines**, including a branching/cyclic DealerTrade (PROPOSED↔COUNTERED counter loop, four terminal branches), parallel state dimensions on VehicleOrder (lifecycle × build_state/retrofit), and a compound gate (AllocationRun lock requires all DealerAllocation children LOCKED + no open appeals)
- **8 calculations**: turn-and-earn `allocation_share` (weighted sales/turn score + floor-then-waterfall + earned-credit carryover, provisional/final variants), `new_point_floor` (strict 6-month boundary), `commodity_cap` (circular-looking pre-accept evaluation order pinned), `retail_reserve_split` (round-half-up once + retail spillover), `trade_earn_penalty`, `incentive_accrual` (marginal age/volume tiers, provisional/final freeze), `carrier_capacity` (discrete ISO-week bucket), `inventory_turn` (point-in-time pinned)
- **66 endpoints**, 26 error codes, 17 ordered validations, 6 roles (Anonymous + 5), 3 OCC concurrency rules (order entry / trade execute / appeal grant), logical clock with fixed default 2026-09-01T00:00:00Z and one `/_seed/order-at-week` test-driving endpoint for aged-inventory fixtures

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, 2 per rule across all 9 difficulty rules, each with structured `setup_api_calls`/`trigger`/`assert` chains; all formula-derived assert values were pre-computed as literals (e.g., raw share 0.578182 → base 6, marginal volume bonus 1900, aged credit 20000, trade penalty 1.0).

**SCAFFOLD_CORNER_DESIGN.yaml** — 23 instances across 8 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross-cutting layers), covering defaults/system fields, invalid/terminal transitions, cascade side effects, end-exclusive lookback boundaries, RBAC denials including entity-backed identity mismatch, and OCC version monotonicity.

Key design couplings for difficulty: order entry consumes DealerAllocation pool under OCC; trades move pool pairwise (conserved) while decaying earned credit (not conserved); cancel-from-ACCEPTED restores pool exactly; commodity resolve cascades restriction expiry which unblocks retrofits; delivery cascades order→sales-credit→incentive accrual (depth-3 chain).

## Step 3: Copy shared files — 2026-09-30T08:29:50.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T08:39:00.000Z

File complete: 359 lines, ends at §5 Error Code Catalogue with no audit footer.

## Report

**PRD generated** at `/home/ubuntu/github/CodingPRD/tasks/task_3184_vehicle_allocation_turn_earn_distribution_order_management/workspace/PRD.md` (359 lines).

**Structure:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC, 2.2 Response envelope (verbatim), 2.3 Pagination, 2.4 Resource identity/versioning, 2.5 Validation pipeline (17 priorities), 2.6 OCC, 2.7 Nested paths, 2.8 Precision/rounding, 2.9 Logical clock, 2.10 Cascades
- §3 Business Logic: 14 subsections covering catalog, commodities/restrictions, allocation runs, turn-and-earn waterfall, new-point floor + retail reserve, order entry, scheduling/build/retrofit, shipments/carrier capacity, dealer trades, appeals, run lock, incentives, DealerModelLine aggregates, test-driving hooks
- §4 Endpoint table (66 endpoints, 4 columns)
- §5 Error catalogue (26 errors, 2 columns)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints inputs/query/path + occ fields + common fields: 72 required, 72 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 17 checks expressed in §2.5 numbered pipeline
- concurrency_rules[] OCC: 3/3 expressed (order-entry, trade-execute, appeal-grant) with write_endpoint + expected_*_version + error_id + 412
- state_machines[].transitions: all 9 machines expressed with from/to states, preconditions, side effects
- calculations[]: 8/8 expressed (allocation_share, new_point_floor, inventory_turn, commodity_cap, retail_reserve_split, trade_earn_penalty, incentive_accrual, carrier_capacity) as precise business narrative
- validations[] conditions: all 17 matchable to error_id in prose
- endpoints[].side_effects: expressed in workflow narrative
- entities[].fields[] structured content: defaults, types, and sentinel values reconstructible
- sibling-branch symmetry: parallel cancel branches, PROPOSED↔COUNTERED loop, hard_split vs spillover, AGED_INVENTORY_CREDIT vs VOLUME_BONUS all given equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 527
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Key features:**
- All 26 error IDs referenced in §2/§3 narrative
- §2.2 verbatim block byte-identical to source (verified via `src in prd`)
- All 39 state/enum values present (initial run caught missing `SUSPENDED`/`DISCONTINUED`, fixed)
- No pseudocode or mathematical notation in calculation narratives — `F + 1 ≤ floor((A+1) * install_rate_pct / 100)` is rendered as precise prose
- Trade earn penalty 0.5/unit, new-point floor 2 units / 6 months, weights 0.6/0.4 all embedded in business context

## Step 5: Generate unit tests — 2026-09-30T09:12:00.000Z

All complete. Final state verified.

## Report

Generated the complete test infrastructure for `task_3184_vehicle_allocation_turn_earn_distribution_order_management`:

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 14 status enums + 14 entity TypedDicts (all `common_fields: true` per PRD §2.4)
- `api_errors.py` — all 26 error IDs with HTTP map, registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per all 66 `/wholesale` endpoints (incl. `_clock/set_current_utc` and `_seed/order-at-week`)
- `factories.py`, `constants.py`, `assertions.py` (per-entity + pool invariant checker), `test_users.py` (opaque role constants + mandatory `make_dealer_headers(dealer_id)` builder for the entity-backed Dealer role)
- `fixtures.py` — composite helpers: `setup_dealer_run` (region+dealers+line+published run), `submit_order` (re-reads DealerAllocation version for OCC), `create_accepted/scheduled/built/delivered_order`, `seed_built_order`, `setup_restricted_line`, trade/appeal/program helpers, `get_accrual`, `lock_all_children`
- `__init__.py` barrel re-exporting framework + PRD-specific names

**Stage 2 — `test_suite/` (conftest + 8 files, 62 tests):**
- `test_01_access_catalog_pipeline.py` (RBAC, auth, validation pipeline order)
- `test_02_allocation_runs_turn_earn.py` (waterfall, new-point floor boundary, publish-vs-lock carryover, lock gates, supersede, lookback end-exclusivity)
- `test_03_order_entry_commodity_caps.py` (pre-accept cap evaluation, partial-build gate, accept/cancel pool conservation)
- `test_04_production_shipments_retrofit.py` (shipment gating, carrier capacity strict-< and week buckets, deliver cascade, parallel build_state, resolve cascade)
- `test_05_dealer_trades.py` (counter loop, cross-region rejection, execute conservation + earn penalty)
- `test_06_appeals.py`, `test_07_incentives.py` (provisional/final freeze, marginal tier straddle = 1900), `test_08_restrictions_concurrency_lists.py` (window overlap/adjacency, stale version 412, pagination)

**Final audit (all green):** 62 tests collected; every test has exactly one `Design:` tag resolving to a real instance; all 18 difficulty instances have ≥2 tests; all 23 non-stub corner instances have ≥1; every quoted PRD sentence is a verbatim substring of PRD.md; no skip/xfail markers; pyflakes clean.

**Notable adjudications (PRD-first):** literal allocation-share numeric outcomes (A=6/B=1 etc.) were not tested because PRD omits inventory seeding (the recipe's numbers are unreachable from PRD alone) — replaced with uniquely-derivable boundary tests (sole-dealer full pool, exact 6-month floor boundary at 1-second resolution). Also note: no `excluded_because` stubs exist in this task's corner index; the trade-expiry `ERR_TRADE_EXPIRED` path is untestable via API since `expires_at` is a system-minted TTL the PRD never quantifies, so no freelance test was invented for it.

## Step 6: Generate implementation — 2026-09-30T10:05:00.000Z

Done. All 62 tests pass, three consecutive runs under `prd-bench-local-run --isolation per-test-server` (fresh server boot per test, ~115s per run).

## What was built

Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_3184_vehicle_allocation_turn_earn_distribution_order_management/workspace/implementation/`:

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded dependency install (no-op once Flask is present)
- `app.py` — blueprint registration, ApiError/404/500 handlers producing the PRD §2.2 envelope
- `db.py` — empty in-memory stores + logical clock (default exactly `2026-09-01T00:00:00Z`, never wall-clock)
- `errors.py` — all 26 error IDs with correct HTTP statuses
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, created_at-ascending sort)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, entity-backed Dealer ownership
- `util.py` — UUID/timestamps, version bumps, field validators (ERR_VALIDATION), ISO-week helpers, lazy sweeps (trade expiry, restriction expiry)
- `services/core.py` — turn-and-earn waterfall (6dp round-half-up raw scores, floor-then-waterfall, deterministic tie-breaks), new-point floor (strict 6-month boundary), DealerModelLine aggregates (days_supply with −1 sentinel), commodity cap (pre-accept `F+1 <= floor((A+1)*rate/100)`), retail/stock pool split with spillover, marginal-tier incentive accrual
- `routes/` — catalog, commodities/restrictions, runs/dealer-allocations, orders, trades, appeals, incentives, shipments; all 66 endpoints, OCC (`expected_dealer_allocation_version` / `expected_run_version` → 412), validation pipeline ordering per PRD §2.5

## Key decisions where tests pinned behavior beyond the prose

- **Waterfall eligibility**: dealers within or exactly at the 6-month new-point window at publish draw no waterfall share (base 0); new points get the 2-unit floor only. This is the unique reading consistent with `test_dealer_at_exactly_six_months_gets_no_floor` (final < 2 with a sole dealer and pool 2) versus `test_single_eligible_dealer_gets_full_pool` (base == 12) and `test_commodity_cap_beats_allocation_exhausted` (final == 2 with old dealer, pool 2).
- **Build gate**: rejects only a scheduled week strictly earlier than the current week — two tests build a W37 order while the clock sits in W36 and expect success; only pickup is week-gated in those fixtures.
- **`reported_sales_units`**: counts all DELIVERED orders for the line (chronological inclusion); the end-exclusive lookback window applies only to the `allocation_share` sales input.
- **Week comparisons**: ISO weeks compare by week-start date (string comparison already zero-padded; week-start math is the safe form).
- **Incentive close**: closing sets a stored CLOSED flag + freezes `_final_accruals`; accrual rows are emitted per dealer with a DealerModelLine on the program's line (provisional/final variants).
- **Constants not in the spec** (never exercised by the suite): `TRADE_TTL_DAYS=7`, `FILING_WINDOW_DAYS=14`, six months = 184 days.

Results: `62 passed / 0 failed` on three consecutive full-suite runs (each with per-test server restarts).

## Step 7: Run tests and iterate — 2026-09-30T10:10:00.000Z

All 8 rounds passed: 62/62 tests in each round. All 8 rounds have `passed == total` (62 == 62).

Summary:
- Iterations run: 1 (clean 8-round parallel sweep on first pass)
- Tests deleted: none
- Fixes applied to `test_helpers/`: none
- Fixes applied to `implementation/`: none

All 62 tests pass consistently across all 8 parallel rounds under `per-test-server` isolation. The task is stable and complete — no diagnostic intervention was needed.

## Step 8: Finalize PRD — SKIPPED — 2026-09-30T10:10:30.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, and 0 implementation fixes. Per the skip condition, PRD_FINALIZED.md is not produced.

## Step 9: Complete PRD — 2026-09-30T10:25:00.000Z

Done. PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** PRD.md 359 lines / 52,200 chars → PRD_COMPLETED.md 361 lines / 57,307 chars (+5,107 chars). 26 source paragraphs touched.

**Counts:** 21 ambiguity-pins, 7 mismatch-revisions (some hunks contain both).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.3 — insert — ambiguity — non-integer limit/offset falls back to default; out-of-range clamped; sort ties broken by `id` — response.py:27-46, all `rows.sort(key=(created_at, id))`.
- §2.5 item 4 — insert — ambiguity — lazily-materialized `DealerAllocation`/`DealerModelLine` rows: reference to existing entities without a materialized child is `ERR_NOT_FOUND` — orders.py:73-75, trades.py:180-181, catalog.py:88 (seed tolerates missing DA).
- §2.5 item 15 — revise — ambiguity — MARKET_GAP metric pinned to own `base_units` < mean `base_units` of ACTIVE same-region dealers on the run — appeals.py:32-52.
- §2.6 — revise — ambiguity — exact per-write version deltas: order accept/cancel +1; trade execute and appeal grant bump each affected DA by 2 when recomputed pool fields change else 1; run +1 — orders.py:141, trades.py:188-191/207, appeals.py:162-165, core.py:166-169.
- §2.9 — insert — ambiguity — clock-set response shape `{"current_utc": to_iso8601}` (HTTP 200) and immediate sweep of restrictions/trades on clock-set; week comparisons by Monday week-start date — catalog.py:30-37, util.py:46-55.
- §3.1 — revise — mismatch — `carryover_credit_units` = current sum over all DML rows rounded to 2dp (was "against the latest closed run") — catalog.py:142-149. Also commodity list `status` filter — commodities.py:47.
- §3.2 — revise — mismatch — overlap/supersede rule pinned: rejection only when windows overlap and new `effective_from` strictly later than old; non-overlapping later windows still supersede — commodities.py:111-130.
- §3.3 — revise — mismatch — supersede freezes only still-`OPEN` children at `LOCKED` — runs.py:67-70.
- §3.3 — revise — mismatch — publishing a childless run is `ERR_INVALID_STATE`; run list filters `model_line_id`/`status`, DA listings `dealer_id`/`run_id` — runs.py:119, 91-94, 161-173.
- §3.4 — insert — ambiguity — new-point dealers (opened_on within or exactly at the 6-month window at `published_at`) are excluded from the waterfall (base 0, floor only) — core.py:196-203.
- §3.4 — insert — ambiguity — lookback window applies only to the waterfall sales input; retrofit children excluded from all sales/inventory/incentive tallies; publish materializes DML rows for all allocated dealers — core.py:71-107, 209-213.
- §3.4 — insert — ambiguity — waterfall take floored at zero — core.py:254-255.
- §3.5 — insert — ambiguity — "six months" = exactly 184 days — core.py:23-26.
- §3.6 — insert — ambiguity — STOCK order rejected only for non-null `customer_ref`; accept refreshes the DML row (avg inventory unchanged since ACCEPTED not counted) — orders.py:90, 142, core.py:93.
- §3.7 — insert — ambiguity — `build_week` strictly earlier than current week rejected; equal allowed — orders.py:215.
- §3.7 — revise — ambiguity — build gate rejects only a current week strictly earlier than `scheduled_week` (same-week build allowed) — orders.py:231.
- §3.8 — revise — mismatch — ISO weeks compared by week-start dates, not lexicographically; shipment list filters `order_id`/`carrier_id`/`state`/`pickup_week`; carrier list `status` filter — shipments.py:96-99, 132, 53.
- §3.9 — revise — ambiguity — trade TTL pinned to 7 days; run state not checked at proposal; trade list filters — trades.py:65, 85.
- §3.9 — revise — ambiguity — execution moves pool via `adjustment_units` with floor re-applied; expired ACCEPTED trade fails execute with `ERR_INVALID_STATE` after sweep; `ERR_TRADE_EXPIRED` only on accept/counter — trades.py:169-170, 186-189.
- §3.10 — revise — ambiguity — filing window pinned: 14 days after `published_at`, inclusive boundary; MARKET_GAP metric pinned; appeal list filters — appeals.py:78, 32-52, 106.
- §3.12 — revise — ambiguity — close rejected when already closed/closed-by-call/clock outside window; final accruals frozen at close and served thereafter; accrual listing covers dealers with DML rows on the line and accepts `dealer_id`; program listing filters — incentives.py:96-99, 105, 111-116, 126-144, 73-76.
- §3.13 — revise — mismatch — `reported_sales_units` counts ALL DELIVERED orders chronologically with no window; `days_supply` rate uses reference run (latest LOCKED else latest) lookback length — core.py:60-68, 110-129.
- §3.13 — insert — ambiguity — orders listing accepts `dealer_id` filter — orders.py:156.
- §3.14 — revise — ambiguity — seed defaults: `order_kind` defaults STOCK, RETAIL `customer_ref` defaults "SEED", `scheduled_at`/`built_at` set to week Monday, bypasses PUBLISHED/ACTIVE gates, consumes pool only when DA exists — catalog.py:47-95.
