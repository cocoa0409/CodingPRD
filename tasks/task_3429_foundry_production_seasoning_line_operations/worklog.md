# Worklog — task_3429_foundry_production_seasoning_line_operations

## Step 1: Create Task Directory — 2026-10-02T00:53:00.000Z

Used pre-allocated task directory `./tasks/task_3429_foundry_production_seasoning_line_operations/` (per command args); verified it exists with an empty `workspace/` inside. No new index computed, no other task directory created.

## Step 2: Generate Scaffold — 2026-10-02T02:10:00.000Z

All checks pass. The scaffold package is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3429_foundry_production_seasoning_line_operations/`):

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 1213 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys, per spec) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1707 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2613 | `scaffold_corner_design` only |

**Scaffold dimensions** (Expert-plus, per the "much harder than expert" brief):
- **12 entities**: Product, ProductionOrder, MeltBatch, Mold, CastingUnit, DefectReport, SeasoningBatch, EnvironmentalPermit, EmissionsReading, InventoryRecord, RetailAllocation, OutletSale
- **53 endpoints**, including a `/_clock/set_current_utc` test-driving endpoint with pinned default `2026-09-01T00:00:00Z`
- **8 state machines** — three cyclic (melt chemistry adjustment loop, casting-unit rework loop with cap 2, permit ACTIVE→WARNING→BREACH→REMEDIATION→ACTIVE), plus a derived posture gate (OPEN/RESTRICTED/FROZEN) on ProductionOrder
- **10 calculations** with all formula-derived assert literals pre-computed in the design files (e.g. planned vs actual charge cost 56300 vs 55230 cents; provisional vs final unit cost 6973 vs 19678 cents; cure score 87 pass / 51 fail; CE 4.30 inclusive pass / 4.305→4.31 half-up reject; channel split of 37 → {1,3,6,27})
- **32 validation rows** (total priority order across auth→SoD→schema→existence→state→OCC→posture→safety→constraint→temporal→referential→fiscal), **32 error codes** (all referenced by at least one design instance), **7 roles** (all `opaque`, segregation-of-duties enforced via X-User-ID comparisons), **2 OCC concurrency rules** (melt-create on ProductionOrder.version, allocation-create on InventoryRecord.version)
- **§1.8**: 18 instances, exactly 2 per Difficulty Rule, each with structured `setup_api_calls`/`trigger` chains
- **§1.9**: 64 instances (49 active + 15 `excluded_because` stubs) across all nine claim-extraction-guide sections

**Verification evidence**:
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (768 calls scanned, 0 violations)
- Placeholder closure: zero unbound `${var}` across both design files; all OCC `expected_*_version` payloads are `${var}` references/expressions
- Instance names unique across both files (82 total); all `excluded_because.difficulty_instance` references resolve; every `grounds` entry resolves to a declared §1.1–§1.7 element
- No forbidden concurrency vocabulary anywhere

**Two authoring-time defects found and fixed**: (1) a heredoc marker leaked into the corner file mid-write, corrupting one section header — repaired surgically and re-verified; (2) a genuine reachability bug I caught while drafting corners: the original SAND_RECLAMATION breach band (0.70/0.20 margin) was unreachable because the 12% per-mold loss cap floors the monthly rate at ~0.88 — re-derived the constants (limit 0.90, breach margin 0.05) and added DUST→shakeout and SAND→mold-create breach gates so every permit type's BREACH has observable teeth.

Orchestrator verification (independent): all three files parse as valid YAML; top-level keys match the required shapes; foundry/casting/melt/seasoning/mold domain terms present at high density (323 / 589 / 967 hits); api_prefix is `/foundry`.

## Step 3: Copy Shared Files — 2026-10-02T02:11:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T02:25:00.000Z

All checks pass. The PRD is complete and verified.

**Summary on exit**

- **Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3429_foundry_production_seasoning_line_operations/workspace/PRD.md` — 313 lines, ends cleanly at the §5 error table (verified tail).
- **Structure**: §1 introduction (2 paragraphs); §2 with 10 subsections (roles/auth, verbatim §2.2 envelope, pagination, logical clock, resource identity, OCC, precision, derived posture/scrap tiering, validation ordering, nested-resource existence); §3 with 8 lifecycle-grouped subsections (products/pricing, orders, melting, molding/pouring/shakeout/reclaim, inspection/defects/rework, seasoning, environmental permits, inventory/allocations/outlet); §4 endpoint table (4 columns); §5 error catalogue (2 columns).
- **Coverage counts**: 12/12 entities, 8/8 state machines with every transition (including the 5 HELD-entry and 5 HELD-resume edges, the adjustment loop, and all cascade edges), 10/10 calculations with every constant at exact value (38/12/6/145 cents-per-lb, CE band [3.90, 4.30], 0.060/0.080/2650 gates, 1450/3200/14/185/0.30 cost constants, 0.04/0.08 scrap tiers, 1.5x breach multiplier, 0.05 sand margin, 12% sand loss, 3% slag, 0.02/0.08/0.15 channel waterfall, all three oil cure profiles, 70 release threshold, 42-day freeze, 0.55/1.00 outlet floors, 0.85 yield gate, OVEN_1 capacity 12, pour 1..48, clock start 2026-09-01T00:00:00Z), 30/30 validations in explicit priority order (§2.9), 43/43 endpoints with exact role lists, 32/32 error codes each raised in prose sentences, 7/7 roles with individual opaque-identity prose, 2/2 OCC rules.
- **Hard contracts**: Contract 1 PASS (135 required field/input/query/path identifiers, 0 missing — verified mechanically; `casting_unit_id` and `oven_id` were initially missed and added). Contract 2 PASS (all six high-risk categories walked, including applies_to scopes for every multi-endpoint validation and all cross-entity cascades). Contract 3 PASS (713 backtick tokens scanned in §3, zero paths/methods).
- **Not translatable**: none — every scaffold element was expressible in prose.
- **Process notes**: the two withheld design files were never opened; part-file assembly avoided heredoc backtick hazards; one misdirected write to a truncated directory name was corrected immediately.

Orchestrator verification (independent): scaffold declares **53** endpoints and PRD §4 table contains **53** method rows — full coverage; the "43/43" figure in the subagent's summary is a self-miscount, the artifact itself is complete. PRD.md is 313 lines.

## Step 5a: Generate Test Helpers — 2026-10-02T02:45:00.000Z

Stage 1 complete. All nine helper files are written, compile, and import cleanly.

## Files written (task dir `test_helpers/`, 2,196 lines total)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 53 | Barrel: framework generics + all PRD-specific exports |
| `constants.py` | 129 | All PRD literals + `round_half_up`/`round_half_up_int` (Decimal, ROUND_HALF_UP) |
| `types.py` | 419 | 7-role `UserRole`, 16 domain enums, 12 entity TypedDicts (EmissionsReading/OutletSale carry only `id`+`created_at` per PRD §2.5) |
| `api_client.py` | 207 | `ApiClient(GenericApiClient)` — 53 methods, exactly the 53 PRD §4 endpoints; base URL via `API_BASE_URL` env var (framework default) |
| `api_errors.py` | 82 | 32 `ApiErrorId` members + full HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 365 | 12 `assert_{entity}` + invariant checkers + 15 `expected_*` calculators |
| `factories.py` | 275 | 20 payload factories (input fields only, None-dropped, unique default `sku_code`) |
| `test_users.py` | 73 | `TEST_USERS` (8 header sets), per-role `make_*_headers(user_id)`, generic `make_headers` |
| `fixtures.py` | 593 | `SetupFailedError`, granular step helpers, composite chains |

## Exported helper API (highlights)

- **Fixtures**: `advance_clock`, `create_product`, `create_order`, `release_order`, `create_melt` (auto OCC version fetch), `charge_melt`, `record_chemistry`, `certify_melt`, `tap_melt`, `create_mold_for_order`, `get_mold` (via order mold list — no single-mold GET exists in PRD), `pour_units`, `shakeout`, `inspect_unit_pass`, `inspect_unit_defect` (returns `(unit, report_id)`), `disposition_report`, `scrap_unit_via_defect`, `rework_unit_via_defect`, `create_seasoning_batch`, `start_bake`, `qa_release`, `create_permit`, `record_reading`, `warn_permit`, `breach_permit_with_readings`, `breach_permit_immediately`, `remediate_permit` (fm acknowledge + eo-2 certify), `reclaim_mold`, `get_inventory_record_for_product`, `create_allocation` (auto OCC), `confirm/cancel/ship_allocation`, `record_outlet_sale`; composites: `setup_released_order`, `setup_charging_melt`, `setup_certified_melt`, `setup_tapped_melt`, `setup_poured_units`, `setup_shaken_units`, `setup_finished_units`, `setup_seasoning_batch_ctx`, `setup_baking_batch`, `setup_seasoned_units`, `setup_completed_order`, `setup_restricted_order` (2/25 → scrap_index exactly 0.0800), `setup_frozen_order`, `setup_inventory_with_stock`, `setup_confirmed_allocation`.
- **Calculators** (verified): planned charge 56300, actual charge 55230, CE 4.30 boundary, slag 60.30, cure 87 (SOYBEAN 475F/60min), channel split 20/80/150/750 for 1000, brand floor 2300, outlet floors 2200/4000, provisional cost 6973.

## Constants fidelity
Every literal cross-checked against PRD: clock start `2026-09-01T00:00:00Z` (§2.4); component prices 38/12/6/145 (§3.3); CE band [3.90, 4.30], S 0.060, P 0.080, 2650F (§3.3); slag 0.03 (§3.3); conversion 1450, labor 3200, energy 14, overhead 185, margin 0.30, yield 0.85 (§3.2); scrap 0.04/0.08, weight 1.5, rework max 2 (§2.8/§3.5); pour 1..48, sand 85%/3.0–4.5/8.0–12.0/loss 12%, breach margin 0.05 (§3.4); breach multiplier 1.5 (§3.7); oven capacity 12, cure threshold 70, profiles (450/500/60, 425/475/75, 400/450/90) (§3.6); channel pcts 0.02/0.08/0.15, brand 1.15, outlet 0.55/1.00, freeze 42 days (§3.1/§3.8); pagination 10/1/100/0 (§2.3). No dead constants.

## Flag for Step 7 (pre-existing drift, not mine)
Difficulty instance `unit_cost_provisional_vs_final_at_completion` asserts `unit_cost_final_cents == 19678`, but the PRD §3.2 formula on its own inputs yields **19768**: (55230 + 128000 + 12600 + 1850)/10. The helper calculator follows the PRD; the design YAML's precomputed literal is wrong (dropped 900).

## Checks
- `python3 -m py_compile` — all 9 files OK
- `python3 -c "import test_helpers.fixtures"` from the task dir — OK (full barrel also imports)
- No `scaffold` references or TODOs anywhere in the package

Orchestrator adjudication of the flagged drift (verified independently against PRD §3.2 and the design instance's `setup_api_calls`/`trigger`): material sum 55230 (810×38 + 790×12 + 320×6 + 90×145), labor 40×3200 = 128000, energy 900×14 = 12600, overhead 185×10 poured = 1850 → total 197680; ÷ good_units 10 = **19768** (exact, half-up no-op). The design YAML's own `distinguishing_aspect` writes the correct inputs and a mis-added result ("= 19678", a digit transposition). PRD is the contract and uniquely derives 19768 — **Step 5b is instructed to translate this instance asserting 19768, overriding the design literal 19678, with a note in the test docstring.** Provisional figure 6973 (55230/10 + 1450) confirmed correct on both sides.

## Step 5b: Generate Test Suite — 2026-10-02T03:20:00.000Z

Stage 2 complete. All three mandatory audits pass.

## Files written (18 files, 2521 lines) under `/home/ubuntu/github/CodingPRD/tasks/task_3429_foundry_production_seasoning_line_operations/test_suite/`

- `conftest.py` (54) — `api` session fixture + 8 role-header fixtures
- Difficulty queue (9 files, one per rule): `test_difficulty_dual_variant_calc.py` (107), `test_difficulty_combinatorial_formula.py` (116), `test_difficulty_non_linear_state_machine.py` (130), `test_difficulty_transitive_cascade.py` (152), `test_difficulty_priority_pair.py` (116), `test_difficulty_boundary_precision.py` (96), `test_difficulty_cross_entity.py` (123), `test_difficulty_resource_overlap.py` (138), `test_difficulty_compensating_invariant.py` (115) — 2 tests per instance, 36 total
- Corner queue (8 files by section): `test_corner_entities.py` (163, 6 tests), `test_corner_state_machines.py` (268, 9), `test_corner_calculations.py` (270, 10), `test_corner_validations.py` (222, 9), `test_corner_validations_line.py` (278, 9), `test_corner_rbac.py` (72, 3), `test_corner_complexity_layers.py` (60, 2), `test_corner_consistency_model.py` (41, 1) — 49 tests total

## Instance accounting (audit c, AST + yaml-parsed indices)

- **82 instances total** in the two indices: 18 difficulty, 64 corner (of which 15 are `excluded_because:` stubs, all with cross-references resolving to real difficulty instances — not translated, per spec).
- **67 non-stub instances, all emitted** — 36 difficulty tests (2 per instance) + 49 corner tests = 85 test functions; **zero instances skipped** on the two-condition filter (every asserted rule has verbatim PRD coverage and unique derivability).
- Audit output: `AUDIT PASS (0 problems)` — no missing, unknown, dual, or untagged tests.

## Design-literal re-derivations (2)

1. **Pre-adjudicated**: `Difficulty/dual_variant_calc/unit_cost_provisional_vs_final_at_completion` asserts `unit_cost_final_cents == 19768` (55230+128000+12600+1850)/10 and provisional 6973, with the docstring noting the design's 19678 is a transposition error.
2. **Found by recompute**: `Corner/calculations/sand_reclamation_rate_warning_band` — the design claims 380/500 lbs → rate 0.7600 lands in the WARNING band, but 0.7600 < 0.90−0.05 = 0.85, so PRD §3.4 ("a rate more than 0.05 below `limit_value` drives the permit to `BREACH`") uniquely derives **BREACH**. Emitted asserting `status == BREACH`, `current_sand_rate == 0.7600`, `last_breach_reading_recorded_by == "eo-1"`, with a docstring re-derivation note. The 12%-loss-inclusivity half of the recipe (loss 60.0 on 500 allowed) is retained.

## Other derivation note

`Corner/state_machines/allocation_lifecycle_confirm_ship_and_terminal_lockdown`: `confirmed_at` is asserted by prefix (`"2026-09-01T00:00:00"`) — PRD pins the logical-clock instant but not the fractional-second rendering of `confirmed_at`; noted in the docstring.

## Audits

- (a) `py_compile` all 18 files: OK
- (b) `pytest --collect-only` (PYTHONPATH=task dir): **91 tests collected, 0 errors** (85 functions; the shared-GET RBAC test parametrizes ×7 roles)
- (c) AST tag audit: PASS (above)
- C1 verbatim sweep: 112 quoted spans extracted from docstrings, all survive whitespace-normalized substring match against PRD.md; 3 nested/multi-line quotes confirmed by direct grep

## Helper gaps

None. Every construction used the frozen `test_helpers/` API (composite fixtures, factories, `make_*_headers` for segregation identity control, `advance_clock`, expected-value calculators); `test_helpers/` was not modified. No inline workarounds were needed.

Orchestrator verification (independent): PRD §3.4 verbatim-confirms the band semantics ("a rate below `limit_value` but still within 0.05 of it moves an `ACTIVE` permit to `WARNING`; a rate more than 0.05 below `limit_value` drives the permit to `BREACH` from any non-terminal status") — 0.7600 vs limit 0.90 is 0.14 below → BREACH derivation correct. Re-ran `pytest --collect-only` myself: **91 tests collected, 0 errors** — matches the subagent's claim.

## Step 6: Generate Implementation — 2026-10-02T04:15:00.000Z

All done. Both servers killed, temp files cleaned. Final report:

## Implementation complete

**File tree** (`tasks/task_3429_foundry_production_seasoning_line_operations/workspace/implementation/`, 2736 lines total):

| file | lines | purpose |
|---|---|---|
| start.sh | 10 | guarded pip install, `exec python3 app.py`, PORT/0.0.0.0 |
| requirements.txt | 1 | flask |
| app.py | 65 | blueprint registration, ApiError/404/405/500 envelope handlers |
| store.py | 75 | in-memory dicts, logical clock (default 2026-09-01T00:00:00Z), seq, touch() |
| errors.py | 50 | ApiError + all 32 catalog IDs with statuses |
| envelope.py | 50 | `meta`/`response_type`/`data` envelope, pagination in meta |
| validate.py | 177 | body well-formedness engine (types, enums, bounds, undeclared-field rejection), pagination/query parsing |
| authz.py | 38 | X-User-ID/X-User-Role auth, role authorize, SoD check |
| calc.py | 206 | all 10 calculations, exact constants, Decimal round-half-up |
| domain.py | 191 | derived posture/tier/index, closure/hold/resume cascades, defect-scrap accounting, sand rate |
| serialize.py | 285 | per-entity serializers (computed fields derived on read) |
| routes_products.py | 117 | 5 endpoints |
| routes_orders.py | 159 | 7 endpoints incl. complete/cancel cascades |
| routes_melts.py | 327 | 8 endpoints (create/charge/chemistry/certify/tap/pour) |
| routes_molds.py | 126 | create/shakeout/reclaim |
| routes_units.py | 127 | units list/get/inspect/complete-rework/per-unit reports |
| routes_defects.py | 68 | report list + disposition |
| routes_seasoning.py | 212 | create/start-bake/qa-release + oven capacity |
| routes_env.py | 162 | permits, readings rollup, acknowledge/certify-remediation |
| routes_inventory.py | 41 | list/get/allocation-plan waterfall |
| routes_allocations.py | 158 | create/confirm/cancel(peak freeze)/ship |
| routes_outlet.py | 56 | outlet sale with channel price floor |
| routes_clock.py | 35 | clock set + month-rollover processing |

**Compile/import**: all 22 .py files pass `py_compile`; `import app` succeeds.

**Smoke transcript** (dynamic ports 32981, then 53795 after kill+relaunch):
- (a) `POST /foundry/_clock/set_current_utc {"to_iso8601":"2026-09-02T00:00:00Z"}` (FoundryManager) → 200 `{"current_utc":"2026-09-02T00:00:00.000Z"}`
- (b) `POST /foundry/products` (full valid body) → 201, product with `created_at` from logical clock, auto-created InventoryRecord (verified via `?product_id=`)
- (c) `POST /foundry/products` with wholesale 3000 vs floor round(3000×1.15)=3450 → 422 `ERR_PRICE_BELOW_BRAND_FLOOR`
- (d) same create as MeltOperator → 403 `ERR_UNAUTHORIZED_ROLE`; GET with no headers → 401 `ERR_UNAUTHENTICATED`

**Extended e2e (70+ assertions, all PASS)**: melt OCC 412, furnace overlap 409 + adjacency allowed, planned/actual charge rounding (28150 both variants), CE rounding 4.00/5.19, SoD 403 on certify, out-of-spec 422, adjustment loop, supplemental-charge line-rounding (6709), tap ledger (slag 15.00/remaining 485.00), pour → units + MOLDING→POURING, exact-pour → EXHAUSTED, tolerance 422, DEFECT→report→USE_AS_IS/REWORK/complete-rework loop, critical-must-scrap 422, SCRAP accounting (index 0.25 → RED → RESTRICTED, returns_credit 100.0), RESTRICTED blocks seasoning 409, start-bake well-formedness 400, qa SoD/food-safety/cure 422s, RELEASE cure 87 → inventory +2, complete final cost 21575 + margin_flag, terminal-cancel 409, allocation reserve/confirm/ship conservation, outlet floor equality-allowed, allocation waterfall 50→(1,4,8,37), emissions WARNING→BREACH counting + 1.5× immediate breach, melt create blocked 409 during breach, HELD hold + resume with state_before_hold, FROZEN posture, rollover clears WARNING/counters but not BREACH, ship_week 422, sand WARNING at rate 0.85 vs limit 0.90, sand loss 422, peak-freeze cancel 409 ERR_ALLOCATION_FROZEN, stale inventory 412. Fresh reboot verified: empty store, clock back at 2026-09-01T00:00:00Z.

**Interpretations chosen** (PRD-ambiguous points):
1. **GET role lists** — PRD §2.1 narrative + scaffold `roles[].shared_operations` ("all GET endpoints") both override the narrower §4 table column; all 7 roles authorized on every read endpoint.
2. **Release of a discontinued product's PLANNED order** → 422 ERR_PRODUCT_DISCONTINUED (state machine has the precondition; validation-25 applies_to omits release; chose the semantically matching error over generic 409).
3. **Hold cascade scope** — fires on AIR_EMISSIONS and SAND_RECLAMATION breach (§3.7 + §3.4's explicit "triggering the hold cascade"); DUST_CONTROL breach does not hold melts (PRD silent; melt HELD transitions name only AIR).
4. **Reading-driven breach** only from ACTIVE/WARNING (PRD enumerates); **sand-rate breach** from any non-terminal status (§3.4 wording). Readings during BREACH/REMEDIATION increment the counter, no status change.
5. **Seasoning create, non-FINISHED unit** → 409 ERR_INVALID_STATE_TRANSITION (ERR_UNITS_NOT_SAME_ORDER reserved by PRD wording for empty/oversized/foreign lists).
6. **Duplicate sku_code, msrp < wholesale, peak_start > peak_end** → 400 ERR_INVALID_REQUEST (no dedicated catalog entries).
7. **Version bumps follow the stated side-effect lists literally** — qa-release does not bump the order version, defect-scrap does not bump the melt version, closure cascade bumps the order once; rollover bumps a permit's version only on WARNING→ACTIVE.
8. **Out-of-range limit/offset** → 400; `api_request_timestamp` uses wall-clock UTC (request metadata), entity timestamps use the logical clock.
9. **Rejected requests mutate nothing** (e.g. failed-PASS measurements not persisted); charge lbs must be ≥ 0, tapped_lbs > 0 (400).

**PRD internal contradictions found**: §2.1 vs §4 table on GET roles (resolved to narratives per the PRD's own precedence note); scaffold's generic permit BREACH cascade vs melt machine's AIR-only HELD trigger (resolved per PRD §3.4/§3.7: AIR+SAND hold, DUST doesn't); §3.1's "four operations" discontinuation list vs the release transition's product-ACTIVE precondition (both enforced, release via ERR_PRODUCT_DISCONTINUED). Nothing was unimplementable.

Orchestrator verification (independent): all 22 .py files re-compiled OK; `start.sh` + `requirements.txt` present; newest test_suite/test_helpers source mtime (03:09) strictly predates newest implementation mtime (03:38) — Step 6 honored the isolation rule and did not touch the test tree.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T04:35:00.000Z

All 8 rounds pass 91/91. The sweep was the final write event — no edits after it. Done.

## Summary

**Iterations run:** 2 (initial sweep → fix batch → final clean sweep).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3429_foundry_production_seasoning_line_operations/test_helpers/fixtures.py` — `setup_seasoned_units` consumed `num_units` as a named parameter but called `setup_baking_batch(**kwargs)` without forwarding it, so the whole downstream chain (`setup_seasoning_batch_ctx` → `setup_finished_units` → `setup_shaken_units` → `setup_poured_units`) silently fell back to the default `num_units=3`. Callers requesting 10 units got an order with `planned_quantity=10` but only 3 castings — breaking the PRD §3.2 yield gate at completion (`good_units 3 < ceil(0.85*10)=9`) and leaving `on_hand_units=3` for tests that allocate 10. One-line fix: `setup_baking_batch(num_units=num_units, **kwargs)`. This healed 7 failing tests (boundary-precision ×2, compensating-invariant ×2, cross-entity allocation ×2, dual-variant completion ×1). The fixture's own docstring ("on_hand_units == num_units") confirms forwarding was the intent.

**Fixes applied to `test_suite/`:**
- `test_corner_validations_line.py` — `test_mold_order_mismatch_rejected` and `test_seasoning_units_from_two_orders_rejected`: `release_order(create_order(...))` passed the full order dict where the fixture expects an id string; the dict repr landed in the URL path and the impl correctly returned 404 `ERR_RESOURCE_NOT_FOUND`. Fixed to `release_order(create_order(...)["id"])` (4 call sites).
- `test_difficulty_cross_entity.py` — `_air_breach_with_second_order` (shared by 2 tests): same dict-instead-of-id bug for `o2`; fixed identically.
- `test_corner_state_machines.py` — `test_order_cancel_cascades_units_melts_seasoning`: asserted the mold stays `POURED` after cancel, but the fixture's own `setup_shaken_units` moves the mold to `SHAKEOUT_DONE` (PRD §3.4) and PRD §3.2 cancels only molds "still in `PREPARED`". Assertion corrected to `SHAKEOUT_DONE` (unchanged-by-cascade), docstring updated to match. The design YAML's "POURED mold" prose contradicted its own recipe.

**Fixes applied to `implementation/`:** none — every failure traced to the test tree; the implementation was PRD-faithful on all 12 (yield gate, inventory sufficiency bound, mold cascade scope, and 404 behavior all match PRD verbatim).

**Final sweep evidence (passed/total per round):** 91/91, 91/91, 91/91, 91/91, 91/91, 91/91, 91/91, 91/91 — all 8 `results.{1..8}.json` retained in `workspace/implementation/`.

Orchestrator verification (independent): parsed all 8 `results.{1..8}.json` — every round `passed: 91, total: 91, failed: 0`. Oldest results file mtime (04:01) is strictly newer than the newest source file across `test_suite/`, `test_helpers/`, and `workspace/implementation/` (03:58) — the clean sweep was the last write event, no post-sweep edits. Spot-checked the headline fixture fix: `setup_baking_batch(num_units=num_units, **kwargs)` present at fixtures.py:376 with forwarding consistent through the whole chain.

## Step 8: Finalize PRD — 2026-10-02T04:50:00.000Z

All verification is complete. The zero-edit outcome is confirmed: every Step 7 fix traces to a pure test-side bug, and the PRD already uniquely determines every behavior involved.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 313 lines vs 313 lines, 0% delta — **byte-identical** (verified with `diff -q`). This is the verified-correct outcome: the Step 7 diff contains only test-side bugs and zero `implementation/` fixes, and my per-item investigation confirmed each one reveals no PRD silence and no PRD/impl mismatch.

**Changes:** none (empty list).

**Per-item investigation log:**

1. **`test_helpers/fixtures.py` — `setup_seasoned_units` not forwarding `num_units`** — Checked the impl yield gate: `routes_orders.py:115-119` rejects completion with `ERR_YIELD_BELOW_MINIMUM` when `good_units < calc.min_good_units(planned_quantity)`, and `calc.py:161-162` computes `math.ceil(COMPLETE_YIELD_MIN * planned_quantity)`. PRD §3.2 (line 136) already pins this verbatim: "the yield gate requires `good_units` to be at least the ceiling of 0.85 times `planned_quantity`". Also confirmed the fix landed (`fixtures.py:376`: `setup_baking_batch(num_units=num_units, **kwargs)`). **Verdict: pure test-helper bug — parameter never reached the downstream chain; impl behavior was PRD-determined. No edit.**

2. **`test_corner_validations_line.py` — dict-instead-of-id at 4 call sites** — `release_order(order_id)` at `fixtures.py:110` takes an id string; passing a dict put its repr in the URL path. Impl `domain.py:24-28` (`get_or_404`) raises `ERR_RESOURCE_NOT_FOUND` (404) for any unresolvable path identifier — exactly what PRD §2.10 (lines 112–114) mandates: "every identifier — path or body — must resolve to an existing resource; the first identifier that does not resolve rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)." **Verdict: pure test call-site bug; impl 404 was PRD-correct. No edit.**

3. **`test_difficulty_cross_entity.py` — same dict-instead-of-id bug for `o2`** — Identical mechanism via the same `get_or_404` path; same PRD §2.10 pinning. **Verdict: pure test call-site bug. No edit.**

4. **`test_corner_state_machines.py` — assertion corrected from POURED to SHAKEOUT_DONE** — Impl shakeout sets `mold["state"] = "SHAKEOUT_DONE"` (`routes_molds.py:80`), matching PRD §3.4 (line 162): "shakes out a mold in `POURED`, moving it to `SHAKEOUT_DONE`". The cancel cascade cancels only molds with `state == "PREPARED"` (`domain.py:124-126`), matching PRD §3.2 (line 138): "Every mold still in `PREPARED` is moved to `CANCELLED`." A SHAKEOUT_DONE mold is therefore correctly unchanged by cancel. The original assertion contradicted both its own fixture (`setup_shaken_units`) and the PRD. **Verdict: pure test assertion bug; PRD determined both halves. No edit.**

**Per-edit pre-edit search log:** empty (zero edits committed, so no NO-NEW-MISMATCH enumeration was triggered beyond the per-item investigations above).

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3429_foundry_production_seasoning_line_operations/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

Orchestrator verification (independent): `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed (313 lines each). The zero-edit outcome is consistent with a Step 7 diff containing only test-side bugs and zero implementation fixes; the subagent's per-item investigation cites specific impl files/lines and PRD line numbers, so this is a reasoned zero-edit, not a killed-mid-flight no-op.

## Step 9: Complete PRD — 2026-10-02T05:15:00.000Z

Done. Summary:

**Files**: `workspace/PRD_FINALIZED.md` 313 lines / 61,062 chars → `workspace/PRD_COMPLETED.md` 313 lines / 65,276 chars (+4,214 chars, +0 lines; all in-paragraph inserts/revisions, no new sections). Not byte-identical.

**Counts**: 13 ambiguity-pins, 0 mismatch revisions of either case, 0 implementation fixes. No sweep re-run (zero `implementation/` edits; existing `results.1..8.json` = 91/91 × 8 rounds remain in place and valid).

**Exhaustive-walk coverage**: read all 21 impl modules — `app.py`, `authz.py`, `calc.py`, `domain.py`, `envelope.py`, `errors.py`, `serialize.py`, `store.py`, `validate.py`, and all 12 route modules (products, orders, melts, molds, units, defects, seasoning, env, inventory, allocations, outlet, clock). Walked every endpoint's gates against the §2.9 precedence ladder (auth → role → SoD → well-formedness → existence → state → OCC → posture → chemistry/emissions/food-safety/cure → business constraints → temporal → activeness → fiscal) and found impl ordering consistent everywhere; verified every PRD-named check is actually wired into its request path (melt-create/tap AIR gate, mold-create SAND gate, shakeout DUST gate, posture gates, OCC pins, cure/food-safety, floors, freeze, yield — all called, none dead). Cross-checked ambiguous points against `test_suite/` (auxiliary only): e.g. `test_corner_rbac.py` confirms the all-roles read rule; `test_difficulty_resource_overlap.py` exercises only multi-batch oven overlap, leaving single-oversized-batch behavior genuinely unpinned.

**Changes** (all `ambiguity` pins):

- §2.1 — insert — ambiguity — all-roles read rule governs every list/get even where the §4 table lists narrower roles; table is authoritative for writes/actions and for the allocation-plan read (FoundryManager, RetailPlanner) — `authz.py:16`, `routes_inventory.py:38` vs. table rows.
- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as wall-clock UTC, the one timestamp not drawn from the logical clock — `envelope.py:17` (`datetime.now`).
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by insertion sequence — `validate.py:143-162`, `store.py:74`.
- §2.4 — insert — ambiguity — non-advancing `to_iso8601` → `ERR_INVALID_REQUEST` (400); rollover counter resets don't bump permit `version`, only WARNING→ACTIVE does — `routes_clock.py:20-34`.
- §3.1 — insert — ambiguity — negative `wholesale_price_cents`/`msrp_cents`, duplicate `sku_code`, `msrp < wholesale`, and start-week > end-week all → `ERR_INVALID_REQUEST` (400) — `routes_products.py:33-47`.
- §3.2 — revise — ambiguity — release's product-activeness gate pinned to `ERR_PRODUCT_DISCONTINUED` (422); §3.1's four-operation list never named release's error — `routes_orders.py:89-91`.
- §3.3 — insert — ambiguity — charge components may be 0 (negative → 400); `tapped_lbs` must be > 0 (else 400) — `routes_melts.py:151-155, 242`.
- §3.4 — insert — ambiguity — `pour_weight_per_unit_oz` > 0 (else 400); pour responds 201 with `data` as the array of created casting units; reclaim values may be 0 (negative → 400) — `routes_melts.py:270, 325-327`, `routes_molds.py:96-97`.
- §3.5 — insert — ambiguity — PASS ignores supplied `defect_type`/`severity`/`notes`; inspect returns 200 with the casting unit, disposition returns 200 with the defect report; the `returns_credit_lbs` ledger credit does not bump the melt batch's `version`/`updated_at` (the act's version increments are exactly unit+order+report) — `routes_units.py:52-56, 83, 104`, `routes_defects.py:54, 64, 68`, `domain.py:187-191` (no `store.touch(melt)`).
- §3.6 — revise — ambiguity (PRD self-contradiction: "an empty list, an oversized batch, or a foreign unit is rejected with `ERR_UNITS_NOT_SAME_ORDER` (HTTP 422)" vs. §2.9 precedence listing oven capacity *before* unit composition plus the capacity formula that counts the new batch's own `unit_count`) — pinned the impl's §2.9-consistent reading: empty list / foreign unit → `ERR_UNITS_NOT_SAME_ORDER` (422); non-FINISHED unit → `ERR_INVALID_STATE_TRANSITION` (409); own-size > 12 trips `ERR_OVEN_CAPACITY_EXCEEDED` (409) first — `routes_seasoning.py:41-66`. Also pinned: release's `good_units` increment does not bump the order's `version` — `routes_seasoning.py:197` (no touch).
- §3.7 — insert — ambiguity — multiple permits per `permit_type` allowed; type-keyed gates trip when *any* permit of the type is in BREACH; the sand-rate evaluation applies to every `SAND_RECLAMATION` permit; over-limit readings during BREACH/REMEDIATION still increment the counter without status change; an already-BREACH permit keeps its `last_breach_reading_recorded_by` — `routes_env.py:99-115`, `domain.py:60-61, 147-155`, `routes_molds.py:119-125`.
- §3.8 — insert — ambiguity — `ship_week` accepts any ISO date (no Monday validation; freeze reads the ISO week of the date as given); missing/non-integer/<1 `build_qty` → 400; `unit_price_cents` must be a non-negative integer (negative → 400) — `validate.py:44-50`, `routes_allocations.py:39, 122`, `routes_inventory.py:40`, `routes_outlet.py:28`.
- §4 — insert — ambiguity — undeclared paths and unsupported methods on declared paths → 404 `ERR_RESOURCE_NOT_FOUND`, pre-authentication for undeclared paths — `app.py:47-53`.

**Case-(b) scan result**: none found. Every clear PRD rule traced to wired impl behavior; the two apparent conflicts (§3.6 oversize error code, §2.5 "every mutation increments version" vs. §3.5/§3.6 enumerations) are PRD-internal contradictions, i.e. case (a), and were pinned to the impl's reading with the conflict noted in the PRD text itself.

Orchestrator verification (independent): `wc -lc` confirms 61,062 → 65,276 chars (+4,214) at constant 313 lines — matches the claim; 42 diff lines total. Implementation tree untouched (newest .py mtime still 03:38, pre-Step-7) and all 8 `results.*.json` intact, so the 91/91 × 8 sweep evidence remains valid. Spot-checked the §3.6 pin: the revised seasoning-create sentence now pins empty/foreign → `ERR_UNITS_NOT_SAME_ORDER` (422), non-FINISHED → `ERR_INVALID_STATE_TRANSITION` (409), own-size > 12 → `ERR_OVEN_CAPACITY_EXCEEDED` (409) first — consistent with the §2.9 precedence ladder as claimed.
