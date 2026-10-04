# Worklog — task_3401_seasonal_confection_production_planning_retail_sell_through

## Step 1: Create task directory — 2026-10-01T18:17:00.000Z

Task directory `./tasks/task_3401_seasonal_confection_production_planning_retail_sell_through/` was pre-allocated by the invoker (index fixed, not computed); verified it exists with `workspace/` inside. No other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T18:30:00.000Z

Both flags are false positives — `&offset` and `*max`/`*250` appear only inside quoted prose strings (query text and formulas), not as YAML anchors. The parsers already validated all three files.

All checks pass. Final state of the delivered scaffold package:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3401_seasonal_confection_production_planning_retail_sell_through/`):

| File | Lines | `yaml.safe_load` |
|---|---|---|
| `SCAFFOLD.yaml` | 1438 | parses OK |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1170 | parses OK (18 instances, 2 per rule × 9 rules) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2200 | parses OK (45 active instances + 5 `excluded_because` stubs) |

**SCAFFOLD.yaml contents:** 12 entities (SeasonalProgram, Product, ProductionRun, RetailerAccount, RetailerCommitment, Shipment, HeatClaim, Warehouse, InventoryLot, DispositionOrder, CommodityContract, SellThroughReport), **51 endpoints**, 47 error codes, 8 state machines (cyclic: program reopen budget, claim MORE_INFO loop, lot quarantine/release, commitment FULFILLED→FULFILLING reorder), 8 calculations, 11 ordered validation priorities, 2 OCC concurrency rules (program advance, commitment revise-supersede), 6 roles (segregation_of_duties model). Archetype: temporal_windowing + quota_allocation; flat topology; beyond-expert calibration per the task instruction.

**Difficulty differentiation highlights:** dual-variant calcs on two domains (hedged landed cost provisional-vs-final on CommodityContract; raw-vs-lift-adjusted cannibalization on SellThroughReport); combinatorial modes (a) tier/created_at waterfall allocation and (b) pinned per-unit-first markdown rounding (4240 vs 4242); depth-3 pull cascade (quarantine→cancel→restore) vs depth-3 complete cascade (lot→load→posture); priority conflicts (state vs temporal; safety vs constraint); boundary checks at 850/1000 congestion and pool-drain-to-zero; overlap rules with buffered (8h changeover, inclusive) vs aggregate-capacity semantics; compensating invariants on physical units and line-hours.

**Verification evidence:**
- `scaffold_lint.py` verdict block (verbatim):

```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     37
  Calls scanned (§1.8+§1.9):  1041

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(The "37" figure predates the final errors-section additions; the corner file now carries 45 active instances and the lint remained clean after each addition — the last full-file parse plus per-instance audits were re-run after every chunk.)

- Placeholder-closure audit across both design files: CLEAN (every `${var}` bound by an earlier `captures:`; one real hole found and fixed — missing product-create in the pagination corner chain).
- Forbidden concurrency vocabulary scan: CLEAN.
- Error-catalog coverage: all 47 error codes are exercised by at least one §1.8/§1.9 instance (16 gaps found by audit and closed with a dedicated `errors` corner section).
- Two YAML issues fixed en route: unquoted trailing-`?` flow entries (quoted via script) and two stray alias references (removed).

## Step 3: Copy shared files — 2026-10-01T19:20:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T19:40:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_3401_seasonal_confection_production_planning_retail_sell_through/workspace/PRD.md`.

## Summary

**PRD.md line count:** 337 lines (long-paragraph prose style; ~11,000 words equivalent), ending at §5 Error Code Catalogue with no audit footer.

**Document skeleton (domain-derived, not template-copied):** §1 Introduction (3 paragraphs from business-context angle); §2 with 10 subsections (RBAC, verbatim response structure, pagination, common resource properties, logical clock & window architecture, monetary precision, OCC, validation priority order, warehouse posture, line scheduling discipline); §3 with 9 subsections organized chronologically by season lifecycle (standing up a season → production → procurement → commitment window → allocation day → shipping/reorder → sell-through → heat claims → pull/quarantine/disposition); §4 with all 51 endpoints in a 4-column table; §5 with all 47 errors in a 2-column table.

**Coverage self-audit (machine-verified against the scaffold):**
- Contract 1 (Field-Name Coverage): 98 required identifiers (84 entity fields, endpoint inputs incl. `decision`/`to_state`/`expected_program_version`/`expected_commitment_version`/`to_iso8601`, common fields, supply-summary-only outputs `allocated_units_total` and `remaining_supply_pool_units`, clock output `current_utc`) — 0 missing. **PASS**
- Contract 2 (Rule Coverage): all 8 state machines' transitions expressed with from/to states, preconditions paired to error IDs, and side-effect cascades (pull cascade LINK 1–3 with reverse-FEFO restore, allocation waterfall, run-complete lot creation); all 8 calculations in precise prose (waterfall tier order GOLD=0/SILVER=1/BRONZE=2 with `SHORTFALL_CREDIT_PCT` 0.10; provisional-vs-final landed cost; both cannibalization variants with lifts 1.10/1.15/1.25/1.20 and floor 0.85; per-unit-first markdown with the pinned 4240-not-4242 example; 4-branch heat settlement 1.00/0.50/1.00/0.25 with `SUMMER_MONTHS` 6/7/8; reorder pool; posture thresholds at floor(0.85×capacity) inclusive; half-open overlap + 8h inclusive changeover, overlap before changeover); both OCC rules in pure stale-version framing with `ERR_STALE_VERSION` 412; all 11 validation priorities in explicit ordered prose; 47/47 error IDs appear in §1–§3 narrative and in §5. **PASS**
- Contract 3 (§3 Path Purity): 538 backtick tokens scanned in §3 — 0 path tokens, 0 bare-method tokens, 0 method+path tokens. **PASS**
- §2.2 emitted verbatim (all four anchors confirmed: `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`).

**Named-constant pinning:** every scaffold constant carries its exact value in prose. One scaffold gap handled per Zero-Silence: `SECONDARY_RECOVERY_PCT` is referenced twice in the scaffold but never valued; the PRD pins it explicitly at 0.25 (25%) in §3.9 so test and implementation generators cannot drift on it.

**Deliberately underdetermined behaviors:** none.

Orchestrator spot-check: PRD.md is 337 lines; the secondary-channel recovery fraction is pinned in prose at PRD.md:221 ("a system constant fixed at 0.25 (25%)") — value pinned as claimed, though the constant NAME `SECONDARY_RECOVERY_PCT` itself does not appear in the prose. No design-index leakage tokens found.

## Step 5a: Generate test_helpers/ (Stage 1 of split Step 5) — 2026-10-01T20:05:00.000Z

All checks pass. Step 5a is complete.

## Files written (all under `test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 197 | Barrel export: framework generics + all PRD-specific names |
| `types.py` | 357 | 19 enums (roles, all entity statuses, channel/decision/kind enums) + 13 TypedDicts (12 entities + SupplySummary; all carry the full PRD §2.4 common set — this PRD has no append-only entities) |
| `api_client.py` | 257 | `ApiClient(GenericApiClient)` with 45 methods covering all 51 PRD §4 endpoints + `api_client` singleton |
| `api_errors.py` | 120 | `ApiErrorId` (all 47 PRD §5 codes) + `HTTP_STATUS_CODES` map, registered with the framework at import |
| `assertions.py` | 427 | `assert_<entity>()` × 12, `assert_warehouse_posture_consistent`, `assert_cannibalization_guard_inputs`, and Decimal-half-up re-derivations of every PRD calculation |
| `factories.py` | 245 | Payload factories × 15, `unique_sku_code`/`unique_retailer_name`, `DEFAULT_PROGRAM_WINDOWS` |
| `constants.py` | 84 | PRD-verbatim values only (see below) |
| `test_users.py` | 70 | `TEST_USERS` (7 header entries) + 6 `make_<role>_headers()` builders |
| `fixtures.py` | 771 | Clock waypoints, primitives, per-entity chains, `drive_program_to` engine, 13 named stage wrappers |

## Frozen constants (constants.py — every value pinned by PRD.md prose)
`CLOCK_START_DEFAULT_ISO="2026-09-01T00:00:00Z"` (§2.5), `MAX_REOPEN=1` (§3.4), `SHORTFALL_CREDIT_PCT=0.10` (§3.5), `TIER_RANK` GOLD0/SILVER1/BRONZE2 (§3.5), `SEASONAL_LIFT` 1.10/1.15/1.25/1.20 (§3.7), `CANNIBALIZATION_FLOOR=0.85` (§3.9), `MIN/MAX_MARKDOWN_PCT=0.10/0.70` (§3.9), `SECONDARY_RECOVERY_PCT=0.25` (§3.9 prose-fixed), `SUMMER_MONTHS=(6,7,8)` (§3.8), four `HEAT_CLAIM_PCT_*` branch fractions (§3.8), `CONGESTED_PCT=0.85` (§2.9), `CHANGEOVER_HOURS=8` (§2.10), pagination 10/1/100/0 (§2.3). No scaffold-only or dead constants.

## Frozen helper API surface (key names Stage 2 will import)
- **Client:** `api_client` / `ApiClient` — `create_seasonal_program`, `get_seasonal_program`, `get_supply_summary`, `advance_program`, `create/get/list_products`, `create/get/list_production_runs` + `start/complete/cancel_production_run`, `create/get_retailer_account`, commitment `create/get/list/submit/confirm/revise/reorder/cancel`, shipment `create/get/list/deliver`, heat-claim `create/get/list/decide/provide_heat_claim_info`, `create/get_warehouse`, lot `get/list/quarantine/release_inventory_lot_quarantine`, disposition `create/get/list/approve/execute`, contract `create/get/list/settle`, report `create/get/list`, `set_logical_clock`.
- **Fixtures:** primitives `set_clock`, `advance_program_to` (OCC-safe, re-reads version), `get_*` readers, `get_lot_for_run`; chains `create_draft/submitted/confirmed_commitment`, `create_scheduled_run`/`start_run`/`complete_run`/`cancel_run`, `create_planned_shipment`/`deliver_shipment`, `file_heat_claim`/`decide_claim`/`provide_claim_info`, `file_sell_through_report`, `propose_disposition`/`decide_disposition`/`execute_disposition`/`create_approved_disposition`/`create_executed_disposition`, `create_contract`/`settle_contract`; the `drive_program_to(stage, commitment_specs=, produced_units=, run_stage=, shipment_specs=, ...)` engine returning a refreshed world dict (`program, retailer, warehouse, product, everyday_product, commitments, commitment_retailers, commitment, run, lot, shipments, shipment`).
- **Header builders:** `TEST_USERS` (platform_admin, production_planner, category_manager=cm-alice, category_manager_b=cm-bob, logistics_coordinator, claims_adjuster, retailer fallback) + `make_retailer_headers(account_id)` (mandatory identity-threading for the entity-backed role) + 5 other `make_*_headers`.

## Deep-precondition chains vs. design indices
- `setup_ready_for_allocation(specs, produced_units)` → IN_PRODUCTION, clock parked at ship-open: serves Difficulty/allocation_waterfall_tier_then_created_at_partial_fill and Corner/allocation_same_tier_tie_break_by_created_at.
- `setup_allocated_program(...)` → SHIPPING post-waterfall: serves inventory_lot_quarantine_release_cycle, reorder_drains_pool_to_exactly_zero_then_exhausted, heat_claim_requires_shipment_delivered (with `shipment_specs=[{deliver:False}]`), shipment window/allocation-cap, supply-summary.
- `setup_delivered_shipment(...)` / `setup_heat_claim_under_review(...)` → serve heat_claim_more_info_review_cycle, declined-50% credit, auto-approve-cannot-reject, claim aggregate cap.
- `setup_on_shelf_program` → cannibalization_raw_vs_seasonally_adjusted, report-week window, disposition-propose-too-early, cannibalization_guard (report filed first).
- `setup_disposition_program` → markdown_recovery_rounds_per_unit (4240-vs-4242), brand_protection_beats_quarantine, lot_release_after_pull, markdown bounds, disposition-exceeds-quarantine, segregation_of_duties, destroy-by gate, close_blocked.
- `drive_program_to("DISPOSITION", shipment_specs=[...])` → program_pull cascade and shipment_create_then_pull_cancel conservation.
- `setup_locked_with_in_progress_run` / `setup_warehouse_with_load(units, capacity)` → run_complete posture flip (850), 849/850 inclusive boundary, 950 overflow, congested-seasonal-vs-everyday.
- `setup_open_program(with_everyday_product=True)` → changeover 8h boundary, line create/cancel conservation, run-start gate, DRAFT-commitment scenarios (submit-on-locked priority, reopen loop, pagination, revise OCC).
- `setup_program`/`setup_cancelled_program`/`setup_closed_program` → creation-shape, contract variants, terminal lockdowns, CLOSED lifecycle.

## Verification
- `ast.parse` passes on all 9 files; `import test_helpers` succeeds from the task directory (184 exported names, no dangling imports).
- Error map registered: 47 codes, string-keyed lookup confirmed working through the framework's `validate_error` (so HTTP statuses auto-check; `validate_success(expected_status=200)` default with explicit 201 for creates is re-exported as required).
- All calculation helpers were executed against the PRD's own pinned arithmetic: markdown 4240 (not 4242), shortfall credits 998/499, heat-claim 1746.5→1747 half-up, cannibalization 0.88/0.704, contract 2000000/2260000/475000, posture 849→OPEN / 850→CONGESTED / 1000→FULL.
- Logical clock: fixture waypoints (2027-01-05 → 01-20 → 02-15 → 07-15 → 08-02 → 09-20 → 11-15) are monotone, postdate the PRD startup default, and align with the default program window chain in factories (commit [01-10,02-15) ≤ deadline 06-30 ≤ ship [07-15,09-15] ≤ on-shelf 09-20 < pull 11-15 < destroy 12-31).
- No `test_*.py` / `test_suite/` generated; no scaffold references in any file.

Orchestrator note: Step 5 was split into 5a (helpers) / 5b (tests) per the oversized-generation-step rule. Orchestrator spot-check: `import test_helpers` OK (193 names); `CLOCK_START_DEFAULT_ISO` matches PRD §2.5's startup clock verbatim.

## Step 5b: Generate test_suite/ (Stage 2 of split Step 5) — 2026-10-01T20:45:00.000Z

Stage 2 complete. All artifacts verified.

## Summary

**Test files written** (13 files, 2837 lines, in `test_suite/`):

| file | lines | tests |
|---|---|---|
| conftest.py | 52 | — |
| test_01_program_lifecycle.py | 243 | 8 |
| test_02_products_and_contracts.py | 233 | 6 |
| test_03_production_runs.py | 308 | 9 |
| test_04_warehouse_capacity.py | 161 | 5 |
| test_05_commitments.py | 343 | 11 |
| test_06_allocation.py | 239 | 6 |
| test_07_shipments.py | 137 | 4 |
| test_08_heat_claims.py | 283 | 8 |
| test_09_disposition.py | 388 | 11 |
| test_10_pull_cascade.py | 264 | 7 |
| test_11_sell_through_reports.py | 116 | 3 |
| test_12_not_found_and_auth.py | 70 | 2 |

**Total tests emitted: 80** (36 queue-A + 44 queue-B).

**AST tag audit** (real `ast` docstring walk vs `yaml.safe_load` indices):
- 80 tagged tests, 0 untagged, 0 dual-tagged, 0 tags pointing to non-existent instances, 0 stub instances translated (5 `excluded_because` stubs correctly left bare).
- Queue A (Difficulty): **18/18 instances with ≥2 tests each**.
- Queue B (Corner): **44/45 active instances covered**; the one gap is a deliberate skip (below).

**Skipped instance (1):**
- `Corner/entities/run_create_body_foreign_keys_checked_in_declared_input_order` — fails unique derivability. The instance asserts that with *both* body FKs unknown, run-create returns `ERR_PROGRAM_NOT_FOUND` (program checked before product). PRD §2.8 priority 5 defers to "the endpoint's declared input order," but PRD §4 never restates payloads and §3.2's prose names `product_id` first — a faithful PRD-only implementer could legitimately check product first and return `ERR_PRODUCT_NOT_FOUND`. Skipped, not weakened.

**pytest --collect-only: 80 collected, 0 errors** (run with `PYTHONPATH=<task_dir>` so `test_helpers` resolves).

**Citation pass:** 59 distinctive ≥8-word probes drawn from every test file's docstring citations all survive literal grep of PRD.md (whitespace-normalized) — C1/C2/C3 hold; every asserted `error_id` is named in PRD prose; the two priority-pair tests (submit-on-locked, brand-protection-vs-quantity) cite the explicit §2.8 priority ordering, which PRD does state.

**Interpretation decisions (PRD vs design instance):**
- `heat_claim_more_info_review_cycle` asserts claim `version == 6`: derivable — PRD §3.8 states claims persist at `version` 1 after the automatic FILED→UNDER_REVIEW hop and that "every decide and provide-info increments the claim's `version` by 1" (1 + 4 cycle hops + 1 approval = 6). Kept as written.
- All design `flow:` dates were consistent with the frozen default window chain (commit [2027-01-10, 2027-02-15) ≤ ship [2027-07-15, 2027-09-15] ≤ on-shelf 2027-09-20 < pull 2027-11-15 < destroy 2027-12-31), so no date re-derivation was needed; every window test sets the clock explicitly via `set_clock`.
- OCC tests assert `ERR_STALE_VERSION` with HTTP 412 on stale (auto-checked via the registered error map) and 200/201 on match; creates throughout use `validate_success(..., 201)` explicitly.

Orchestrator independent re-audit (AST docstring walk vs yaml.safe_load of both indices, with correct `rule_id`/`section` path reconstruction): 80 tests, 0 invalid tags, 0 stub translations, 62/63 active instances covered, sole uncovered = `Corner/entities/run_create_body_foreign_keys_checked_in_declared_input_order` (the declared skip). Matches the subagent's report exactly.

## Step 6: Generate Implementation — 2026-10-01T21:20:00.000Z

Implementation complete and verified. Final summary:

## Files written (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install; `exec python3 app.py` on `$PORT` (default 10000), 0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 56 | App factory, blueprint registration, error handlers, clock endpoint |
| `db.py` | 126 | In-memory dict store (empty at boot, no seeding), logical clock starting exactly `2026-09-01T00:00:00Z`, id/timestamp helpers, `touch()` |
| `errors.py` | 91 | `ApiError` + all 47 catalog error IDs |
| `respond.py` | 117 | §2.2 envelope (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1..100/0) |
| `validate.py` | 97 | Syntactic field validators (400s) |
| `middleware.py` | 52 | `X-User-ID`/`X-User-Role` auth (401/403), six roles |
| `domain.py` | 379 | Constants (0.85 congestion floor, tier ranks, lifts, 0.10 shortfall, 0.25 secondary, 8h changeover, MAX_REOPEN 1), getters-404, computed totals/posture (recomputed on read), serializers |
| `programs.py` | 289 | Program CRUD-read + supply-summary + advance state machine, allocation waterfall, pull cascade |
| `products.py` | 80, `runs.py` | 202, `retailers.py` 40, `commitments.py` 271, `shipments.py` 141, `claims.py` 182, `warehouses.py` 96, `dispositions.py` 206, `contracts.py` 114, `reports.py` 99 — per-domain route modules |

Total: 20 files, 2,649 lines.

## Endpoint table
Flask `url_map` shows 52 rules − 1 built-in `/static` = **51 endpoints**, exactly the scaffold's §1.5 table (4 programs, 3 products, 6 runs, 2 retailer-accounts, 8 commitments, 4 shipments, 5 heat-claims, 2 warehouses, 4 lots, 5 dispositions, 4 contracts, 3 reports, 1 clock).

## Verification
- `python3 -m compileall -q .` → **COMPILE_OK** (all modules).
- Booted on dynamic ports (never hardcoded), ran two self-authored smoke scripts:
  - Happy path (42 checks): program→product→warehouse→retailer→commitment create/submit/confirm→clock advance→LOCKED→run schedule/start/complete→IN_PRODUCTION→SHIPPING (allocation: ALLOCATED, totals correct)→shipment→deliver→FULFILLED→reorder (+ERR_REORDER_NOT_ALLOWED on second)→contract provisional `1000*300−400*50` / settle `1000*350−400*100`→ON_SHELF→report (raw 0.95, adjusted 0.76)→claim approve 49,900¢→DISPOSITION (lot QUARANTINED 2500)→markdown execute `424×2500=1,060,000`¢→CLOSED; plus 401/403/412 envelope checks.
  - Edge path (55 checks): half-open overlap 409, changeover 4h→422 / exactly-8h→allowed / same-kind no gap / cancelled run drops out, deadline 422, posture CONGESTED at exactly `floor(0.85×100)=85`, CONGESTED seasonal block + everyday accepted + overflow FULL, reopen once then `ERR_PROGRAM_REOPEN_EXHAUSTED`, `ERR_PROGRAM_ADVANCE_TOO_EARLY`, revise OCC 412→201 successor revision 2, tier-major allocation (GOLD 60 ALLOCATED, BRONZE SHORTED 40/70, credit `round_half_up(30×499×0.10)=1497`), ship-window 422, allocation cap 422, FEFO draw 100−60=40, claim aggregate 422, goodwill pct 0.25 (4990¢), MORE_INFO cycle + ownership 403, auto-approve reject ban 422 + approve at 100%, pull cascade cancelled PLANNED shipment and restored its 40 units to the DEPLETED lot as QUARANTINED, `ERR_UNDISPOSED_STOCK_REMAINS`, brand protection, markdown band, destroy-by gate, DESTRUCTION recovery 0.
- **All 97 checks passed.**
- Smoke server PIDs killed individually by exact PID (2643816 confirmed dead; two earlier strays 2641098/2641674 also killed; ports verified free via `ss`). No broad kill patterns used.

## Interpretation decisions (where PRD prose admitted >1 reading)

1. **Timestamps from the logical clock** — `created_at`/`updated_at`/meta timestamps read the logical clock, resting on "The server does not consult wall-clock time for any business rule" (§2.5) and lot_code as "the deterministic tie-break after created_at" (§3.2) — ties only occur under a settable clock.
2. **Syntactic 400 before auth 401** — rests on "Syntactic request validation comes before all numbered priorities" (§2.8). Program-relative window bounds (also `ERR_INVALID_REQUEST` per §3.4 "with violations rejected as `ERR_INVALID_REQUEST`") are checked immediately after body-FK existence since they require the program row.
3. **`claimed_units < 1` → `ERR_CLAIM_EXCEEDS_SHIPMENT` (422), not 400** — the catalog condition explicitly includes "claimed_units < 1", which beats the generic §2.8 wording.
4. **Heat-claim filing carries no ownership check** — §2.1: "This ownership rule guards commitment submission, revision, reorder, and cancellation, the provision of additional heat-claim evidence, and sell-through report creation" — filing is deliberately absent.
5. **Reorder restricted to `{ALLOCATED, SHORTED, FULFILLING, FULFILLED}`**, others → `ERR_REORDER_NOT_ALLOWED` ("commitment/program state forbids reorder"); a single version increment covers the reorder including the FULFILLED→FULFILLING reopen, per the endpoint's single "increments RetailerCommitment.version by 1".
6. **Pull-cascade restore flips a DEPLETED source lot to QUARANTINED** — LINK 1 quarantines only AVAILABLE lots; restored post-pull seasonal stock must remain dispositionable (the CLOSED gate counts only QUARANTINED lots), so units restored "to the exact lots they were drawn from" land as QUARANTINED.
7. **+1 version per entity per mutation event** (a draw that zeroes a lot changes units+status as one mutation), per §2.4 "incremented by exactly 1 on every mutation, including … cascades".
8. **Revise temporal gate is only `clock < commitment_close_on`** (no lower bound) — §3.4: revision requires "the logical clock to be strictly before commitment_close_on", asymmetric to submit's half-open interval.
9. **Confirm has no program-state gate** — only the SUBMITTED from-state plus the shelf cap, per the stated preconditions.
10. **`lot_code` rendered `LOT-%06d`** — "LOT-<zero-padded monotone sequence>" leaves the width free; fixed width makes the string-ascending tie-break equal numeric order.
11. **`produced_units >= 0` accepted at complete** — no positivity constraint is stated for it (only `planned_units` is "> 0").
12. **Disposition execute re-verifies quarantined sufficiency** (defensive `ERR_DISPOSITION_EXCEEDS_QUARANTINE`) — PRD names only the destroy-by gate at execute; draining two approved orders must not drive a lot negative.
13. **Allocation intra-tier tie-break: `created_at` then insertion sequence** — PRD pins only "ties within a tier break by the commitment's `created_at`, earliest first"; identical logical-clock instants need a stable secondary.
14. **Window dates echo normalized UTC without fractional digits when whole-second** (e.g. `2027-01-05T00:00:00Z`), matching the PRD's own rendering of the startup clock; `created_at`/`updated_at`/meta always carry three fractional digits per §2.2/§2.4.

Orchestrator spot-check: `compileall` clean; no references to test_helpers/test_suite/design YAMLs anywhere in implementation/; route decorators present across all per-domain modules.

## Step 7: Test/fix iteration loop — 2026-10-01T21:50:00.000Z

All 8 rounds pass cleanly — 80/80 in every round, with all `results.1.json` … `results.8.json` preserved in `workspace/implementation/` per the output contract.

## Summary

- **Iterations run:** 2 (baseline sweep + verification sweep after the fix).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_05_commitments.py` — `test_shelf_cap_confirm_allows_exact_cap_and_rejects_one_over`: reordered setup so the 1-unit commitment (`c3`) is created *after* `c1` (60) and `c2` (40) are confirmed. PRD §3.4 counts `SUBMITTED` commitments in the shelf-cap sum ("…commitments in `SUBMITTED`, `CONFIRMED`, `ALLOCATED`, `SHORTED`, `FULFILLED`, or `FULFILLED` status — this commitment included —"), so with all three pre-created the first confirm already summed to 101 > 100 and was correctly rejected. The reorder preserves both intended assertions: exact cap 60+40=100 confirms (inclusive), and 100+1=101 is rejected with `ERR_SHELF_CAP_EXCEEDED` leaving `c3` SUBMITTED.

- **Fixes applied to `implementation/`:** none — the implementation's shelf-cap check (`commitments.py`, `SHELF_CAP_STATUSES` including `SUBMITTED`) was already PRD-faithful; the deterministic failure in all 8 baseline rounds was a test-setup bug, not an implementation bug.

Orchestrator verification: all 8 `results.${i}.json` show 80/80 passed, 0 failed; no `.py` source in implementation/, test_suite/, or test_helpers/ is newer than the final sweep's results files (no post-sweep edits); the shelf-cap fix was read at test_05_commitments.py:149-174 and matches the claim (c3 created after both confirms; inclusive cap; exact error_id asserted).

## Step 8: Finalize PRD — 2026-10-01T22:00:00.000Z

Done. PRD_FINALIZED.md is written and verified identical to PRD.md — zero edits is the correct outcome here.

## Summary

**Line counts / delta:** PRD.md = 337 lines, PRD_FINALIZED.md = 337 lines, 0.0% delta. `diff -q` confirms the two files are byte-identical.

**Changes:** none.

**Why zero edits is correct:** The `<step_7_diff>` contains exactly one item — a test_suite fix to `test_05_commitments.py::test_shelf_cap_confirm_allows_exact_cap_and_rejects_one_over`, explicitly a setup-order bug (the 1-unit commitment was created before confirming the 60/40-unit ones). No implementation files were touched and no tests were deleted. Per the method, a PRD patch is only warranted when the impl pinned a choice the PRD left open or diverged from the PRD; a pure fixture bug with a PRD-faithful impl warrants nothing.

**Candidate-edit evaluation log (the single Step 7 item):**
- (a) Subject: shelf-cap check on commitment confirm — which statuses count toward the retailer's `max_seasonal_units` sum, and cap inclusivity.
- (b) Paths enumerated and read:
  - `workspace/PRD.md:173` (§3.4) — already states verbatim: "the sum of `committed_units` over all of the retailer's commitments in `SUBMITTED`, `CONFIRMED`, `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status — this commitment included — must not exceed the account's `max_seasonal_units`, or the confirm is rejected with `ERR_SHELF_CAP_EXCEEDED` (HTTP 422)." Cross-checked against PRD.md:122 (structural-constraints catalog) and :149 (`max_seasonal_units` as an all-programs cap) — all consistent.
  - `workspace/implementation/commitments.py:24-25` — `SHELF_CAP_STATUSES = ("SUBMITTED", "CONFIRMED", "ALLOCATED", "SHORTED", "FULFILLING", "FULFILLED")`, exactly the PRD's six statuses.
  - `commitments.py:152-167` (`confirm_commitment`) — sums `committed_units` over all of the retailer's commitments in those statuses (the commitment being confirmed is SUBMITTED at check time, so "this commitment included" holds), rejects with `ERR_SHELF_CAP_EXCEEDED`/422 only when the sum strictly exceeds the cap ("must not exceed" → exact cap allowed). Also checked the only other cap-relevant path, `submit_commitment` (lines 132-149) — it applies no cap check, and the PRD places the cap on confirm only, so nothing off-site is mis-described.
  - `implementation/errors.py:70` — error-id/422 mapping matches the PRD error table (PRD.md:332).
- (c) Wording adjustment: none — the PRD prose already uniquely determines the implemented behavior at every enumerated path, so any edit would be pure churn with NO-NEW-MISMATCH risk and no traceability to a Step 7 item.

**Artifact:** `workspace/PRD_FINALIZED.md` (identical copy of PRD.md).

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → identical (337 lines each).

## Step 9: Complete PRD — 2026-10-01T22:40:00.000Z

Both passages are coherent. The task is complete. Here is the final report.

## Summary

**Produced** `workspace/PRD_COMPLETED.md` — a minimal in-place patch over `PRD_FINALIZED.md`.

**Size**: 337 → 337 lines (all edits are in-paragraph inserts/revisions; no new sections); 60,093 → 63,804 chars (**+3,711**).

**Counts**: 22 ambiguity-pins, 2 mismatch-revisions. Total 24 pins, applied in three scripted passes with per-edit occurrence-count assertions; the last two passes restructured six insertions so that **zero** test-docstring verbatim quotes broke (verified mechanically: 105 docstring quotes re-extracted and matched, same 3 pre-existing stylization failures as the unedited PRD_FINALIZED baseline, 0 new).

### Changes (section — kind — class — what — impl evidence)

- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, never wall-clock — implementation/respond.py:25, db.py:76-78
- §2.3 — insert — ambiguity — negative `offset` → ERR_INVALID_REQUEST; list ties on `created_at` break by creation order — respond.py:75-83, 96-98
- §2.4 — insert — ambiguity — `created_at`/`updated_at` derive from the logical clock; each cascade link touching an entity is its own mutation (+1 version per link); client-supplied instants are echoed verbatim — db.py:53,117-126; programs.py:191-210
- §2.5 — insert — ambiguity — clock endpoint accepts any instant (backwards allowed); `current_utc` renders whole-second instants without fractional digits — app.py:41-47, db.py:81-91
- §2.8 — insert — ambiguity — within priority 7, the target resource's own transition validity is evaluated before cross-entity state gates — commitments.py:137-143, runs.py:132-140
- §2.9 — insert — ambiguity — warehouse creation carries `name`, `temp_controlled`, `capacity_units` — warehouses.py:33-36
- §3.1 — insert — ambiguity — `brand_protected`/`requires_temp_control` are required booleans at creation — products.py:22-23
- §3.2 — revise — **mismatch** — body-FK resolution order for run creation is `program_id` (when supplied) then `product_id` (PRD prose names `product_id` first) — runs.py:46-55
- §3.2 — insert — ambiguity — `produced_units` at completion is non-negative; zero accepted — runs.py:149
- §3.2 — insert — ambiguity — `lot_code` is six-digit zero-padded from `LOT-000001` — db.py:42,61-63
- §3.3 — insert — ambiguity — negative `hedged_quantity_units`, non-positive strike when supplied, non-positive settlement spot are ERR_INVALID_REQUEST (400) — contracts.py:39-45,99
- §3.4 — insert — ambiguity — program-relative ship-window bounds at creation evaluated after body FKs, before the OPEN_FOR_COMMITMENTS gate — commitments.py:63-81
- §3.4 — insert — ambiguity — confirmation carries no program-state or clock gate — commitments.py:152-167
- §3.4 — insert — ambiguity — revision re-validates the successor's effective ship window (supplied sides replace, omitted carry over) after the clock gate — commitments.py:197-206
- §3.5 — insert — ambiguity — commitments created at the same logical-clock instant break allocation ties by creation sequence (load-bearing in passing test_06) — programs.py:156-160
- §3.6 — insert — ambiguity — `delivered_on` rendering: whole-second bare, else three fractional digits (test-asserted at test_07:58) — shipments.py:133
- §3.6 — insert — ambiguity — reorder is defined only for `ALLOCATED`/`SHORTED`/`FULFILLING`/`FULFILLED`; any other commitment status → ERR_REORDER_NOT_ALLOWED — commitments.py:26,240-244
- §3.7 — insert — ambiguity — report filing is gated by the week window alone; program status is not consulted — reports.py:51-54
- §3.9 — insert — ambiguity — pull-cascade restore flips a non-QUARANTINED (e.g. DEPLETED) source lot to QUARANTINED — programs.py:204-210
- §3.9 — insert — ambiguity — EVERYDAY-product lots have no program and are never blocked by the quarantine gate — warehouses.py:21-28
- §3.9 — insert — ambiguity — disposition execution re-verifies quarantined sufficiency → ERR_DISPOSITION_EXCEEDS_QUARANTINE — dispositions.py:169-172
- §4 — insert — ambiguity — undeclared request fields are ignored; client-supplied system-managed properties never take effect (test-asserted at test_05:35-57) — all handlers' `v_*` accessors
- §5 — revise — **mismatch** — catalogue's "complete set" claim qualified: off-route requests fail with framework-level ERR_NOT_FOUND (404) / ERR_METHOD_NOT_ALLOWED (405) — respond.py:107-117

Known-generation-time sites verified already pinned by the PRD (no edit needed): syntactic-400-before-auth (§2.8), claimed_units<1 → ERR_CLAIM_EXCEEDS_SHIPMENT (§3.8), no ownership check on claim filing (§2.1's exclusion), revise gate = clock < commitment_close_on only (§3.4), +1 version per mutation (§2.4).

### Implementation gaps NOT patched into PRD

None found — every PRD-stated rule has a live enforcement path in implementation/. One borderline observation, disclosed for transparency: §3.7 calls `week_of_on` "the Monday of the reported week", and the impl validates only the `[on_shelf_on, pull_on]` interval, never Monday-ness (reports.py:52). Read as descriptive rather than a stated rule — the PRD names a rejection only for out-of-window weeks — so neither edited nor classified as a gap.

### Verification

- `diff -q PRD_COMPLETED.md PRD_FINALIZED.md` → **files differ** (expected: edits were made; the zero-edit byte-identical fallback does not apply).
- File exists, non-empty: 337 lines / 63,804 chars.
- No file outside `workspace/PRD_COMPLETED.md` was created, modified, or deleted; implementation/ (including results.*.json showing 8× 80/80 green), test_suite/, and test_helpers/ were read-only throughout.

Orchestrator verification: PRD_COMPLETED.md present at 337 lines; both mismatch revisions confirmed in-place (§3.2 program_id-first FK resolution — which also resolves the ambiguity behind Step 5b's single skipped corner instance — and §5 framework-level 404/405 qualification); no `.py` source newer than the final sweep's results files; all 8 `results.${i}.json` still show 80/80. Neither mismatch revision strips a scaffold rule — both pin previously underdetermined behavior. Sweep evidence stands: **pipeline complete**.
