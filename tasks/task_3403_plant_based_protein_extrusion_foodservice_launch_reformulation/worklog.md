## Step 1: Create task directory — 2026-10-01T18:42:52.000Z

Pre-allocated task directory confirmed at tasks/task_3403_plant_based_protein_extrusion_foodservice_launch_reformulation/ with workspace/ inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-01T20:26:09.000Z

Scaffold generation complete and verified. All work was done without reading any sibling task.

## Files written

- `SCAFFOLD.yaml` (§1.0–§1.7, 94 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 85 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 143 KB)

## Verification results

1. All three files exist and are non-empty. 2. `yaml.safe_load` succeeds on all three (parse-checked after every append; two `?`-suffix/`[`-in-flow-sequence YAML traps found and fixed en route). 3. Key split honored: SCAFFOLD.yaml has neither design key; each design file has exactly its own single top-level key. 4. Domain check: `api_prefix: /protein-ops`, all entity/field/constant names are protein-extrusion domain (148 domain-term hits); no foreign-domain leftovers. 5. `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1016 calls scanned across 91 active instances). Additionally: placeholder-closure audit shows zero unbound `${var}` and zero instance-name collisions across both files; no forbidden race vocabulary anywhere.

## Counts

- **Endpoints: 39** (kept under the >40 impl-gen overshoot threshold) | **Entities: 10** | **State machines: 9** (incl. Supplier and ProductionLine as parallel two-dimension machines) | **Calculations: 9** | **Validation priority rows: 11** | **Errors: 43** | **Roles: 8** (all opaque) | **OCC rules: 2** (line version on run create; product version on label approve)
- **Difficulty instances (§1.8): 20** — 9 rules × ≥2 (non_linear_state_machine and cross_entity_state_dependency carry a 3rd)
- **Corner entries (§1.9): 75** — 71 active + 4 `excluded_because` stubs
- Entities: Supplier, IngredientLot, ProductionLine, Product, LabelVersion, ProductionRun, GrowthProgram, FinishedGoodsBatch, DemandForecast, InventoryWriteDown

## Design decisions worth flagging downstream

- **Deliberate co-manifold folds**: co-man capacity contract fields live on ProductionLine (no separate agreement entity); sampling vs foodservice launch are one GrowthProgram entity with type-conditional required fields (conditional validation difficulty); supplier holds two parallel state dimensions (qualification cycle × agreement lifecycle) driven through one `dimension`-parameterized transitions endpoint.
- **Validation priority is explicitly ordered 1–11 with request-shape (400) checks LAST** — state/existence errors beat missing-field errors; intra-row order pinned where two errors could co-fire (e.g., ERR_BATCH_NOT_WRITABLE precedes ERR_WRITEDOWN_EXCEEDS_AVAILABLE).
- **Boundary pins**: attainment 85.00 inclusive; audit texture ≥80 and moisture ≤3.0; capacity ≤ monthly cap inclusive; over-receipt ≤110% inclusive; forecast miss at variance ≤ −20.00 inclusive; program gap ≥14 days inclusive vs half-open adjacency for line run windows (the two Rule-8 interval semantics).
- **Rounding pins**: lot cost rounds indexed base before clamp; batch cost = per-lot round → sum → divide → round_half_up (4440.5→4441 corner); delivered_cases = per-run floor then sum (20 not 21).
- **Derived, not stored, batch status** (WRITTEN_OFF > EXPIRED > DEPLETED > RESERVED > AVAILABLE) evaluated against the logical clock; the only clock sweep that mutates stored state is supplier agreement expiry. Clock default pinned to 2026-09-01T00:00:00Z.
- **Segregation of duties** is identity-based (decision X-User-ID ≠ proposed_by_user_id), distinct from role-based 403 — both are corner-tested.
- Every constant referenced anywhere (thresholds, shelf lives, NRV per channel, freight estimate, markup, parity reference) is valued once in the top-level `constants:` registry and mirrored in each calculation's own `constants:` block.

Orchestrator verification: re-parsed all three files with yaml.safe_load — PASS; key split confirmed; api_prefix=/protein-ops; 10 domain entities; 39 endpoints; 28 pinned constants. Claims match source.

## Step 3: Copy shared files — 2026-10-01T20:26:16.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T20:55:06.000Z

All verifications pass. Final summary:

## PRD Generation Complete

**Output:** `workspace/PRD.md` — 303 lines, 52,812 bytes, ends with the §5 error catalogue (last row `ERR_INSUFFICIENT_ISOLATE`), no truncation. Built in 9 sequential appends, each tail-verified. The `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened.

**Structure:** §1 (2-paragraph intro) → §2 (10 subsections: RBAC, verbatim §2.2 block, pagination, logical clock + expiry sweep, common properties, rounding discipline, OCC, 11-tier validation cascade, nested retrieval, stored-vs-derived state) → §3 (8 workflow subsections: suppliers, lots, lines, products/labels, runs, programs, batches, forecasts/write-downs) → §4 (4-column endpoint table) → §5 (2-column error table).

**Verification results:**
1. **Truncation check** — final line is the intended last catalogue row; markdown structure intact.
2. **10+ constant greps — all hit:** `2026-09-01T00:00:00Z`, `1.05`, `85.00`, `12.00`, `-20.00`, `920 cents`, `270 days`, `40 cents per kilogram`, `3.0 percent`, `15 days` (plus 85/35/110 percent, 110 cents packaging, 14 days, 70/80 audit thresholds, 45/60/30 shelf lives, 20g/3g claim gates, NRV 1000/1200/1500/0, 10 kg/case — all present exactly once with correct context).
3. **Error IDs — all 43 present** in prose with trigger conditions near their workflows; the 5 sampled (`ERR_STALE_LINE_VERSION`, `ERR_FEFO_VIOLATION`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PROGRAM_WINDOW_OVERLAP`, `ERR_INSUFFICIENT_ISOLATE`) each hit 3–4 times; §5 table has exactly 43 rows.
4. **Clock default** `2026-09-01T00:00:00Z` present.
5. **§3 path purity** — mechanical scan of §3 backticks: zero paths, zero bare HTTP methods (PASS).
6. **Field-name sweep** — all ~100 entity fields plus request-body-only names (`to_iso8601`, `dimension`, `target_status`, `decision`, `target_state`, OCC fields, etc.) and query params present in backticks (Contract 1 PASS).
7. **§4 table** — exactly 39 rows matching the 39 scaffold endpoints, roles verbatim.

**Contract 2 highlights:** the 11-priority validation cascade is rendered as a numbered §2.8 list including the tier-8 sub-order (uniqueness → batch-writable → quantity → …) and tier-11 "state errors win"; both OCC rules expressed in stale-version terms with exact error IDs and 412 status; all formulas translated to operator-free prose with pinned rounding order (per-lot round → sum → divide for batch costing; weighted average → 35% markup → 110 cents packaging → 920 reference for parity); the disqualify → terminate → reject cascade, completion FIFO/depletion/agreement cascade, dedicated-run full-reservation, and program-termination compensating release are all spelled out; boundary inclusivity pinned everywhere (exactly 1.05 meets goal, exactly -20.00 is a miss, 80/3.0 audit boundaries pass, half-open run windows).

**Deliberately left unpinned (scaffold is silent, so I did not invent):**
- The error ID for drafting a label on a `SUNSET`/`DISCONTINUED` product (gate stated, no code nominated).
- The error ID for `agreement_end_date ≤ agreement_start_date` at supplier creation (constraint stated, no code nominated).
- Whether the clock capability can move backward ("advances" mirrored).
- Failing audit outcome from `SUSPENDED` (only the four scaffold-specified audit combos stated); version bumps on cascade-touched resources beyond the two scaffold-declared ones (line on run create, product on label approve).

Orchestrator verification: PRD.md is 303 lines ending at the ERR_INSUFFICIENT_ISOLATE catalogue row; spot greps (clock default, 85.00, -20.00, ERR_FEFO_VIOLATION, ERR_SEGREGATION_OF_DUTIES, ERR_INSUFFICIENT_ISOLATE, rounding) all hit. Claims match source.

## Step 5a: Generate test helpers (Stage 1) — 2026-10-01T21:19:44.000Z

Stage 1 is complete and verified. Summary follows.

## Files written (all under `test_helpers/`)

`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` — each passed `python3 -m py_compile` immediately after writing. Nothing written to `test_suite/` (confirmed absent).

## Verification results

1. **Import check**: `import test_helpers` succeeds from the task dir — 220 exported names, no dangling cross-imports. Surface sanity asserted for all key exports.
2. **Error catalog**: 43 `ApiErrorId` members; the id→HTTP-status map diffs **exactly** against the PRD §5 table (programmatic regex diff, not eyeball).
3. **Constants spot-check**: 28 flat constants in `constants.py`, each value asserted equal to its PRD expectation and grep-traced to the pinning sentence — clock default `2026-09-01T00:00:00Z` (§2.4), 70/80 audit gates (§3.1), 110% over-receipt + 40-cent freight (§3.2), 80/3.0 audit bounds (§3.3), 35%/110/920/1.05 parity (§3.4), 10 kg/case + 85% isolate (§3.5), 85.00/12.00/14-day (§3.6), 45/60/270/30 shelf lives (§3.7), −20.00 miss, 15-day expiry window, NRV 1000/1200/1500/0 (§3.8). Derived lookup dicts (`SHELF_LIFE_DAYS_BY_CHANNEL`, `NRV_CENTS_PER_CASE_BY_CHANNEL`, `CHANNEL_FOR_PROGRAM_TYPE`) are computed from the flat names — no duplicated literals — and are referenced by `assertions.py` (`assert_batch_expiry_matches_shelf_life`, `assert_write_down_amounts`) and `fixtures.py` (dedicated-run channel mapping), so no dead constants.
4. **Offline composition smoke** (transport stubbed, no server): walked `setup_production_scenario`, `setup_completed_batch`, `setup_lto_program_with_deliveries(20, [100, 75])`, `setup_posted_recall_write_down`, `setup_expired_agreement_supplier`. Confirmed: clock pinned first; label approval re-reads and carries the fresh product version (OCC threading); run creation re-reads line version per attempt; non-dedicated runs **omit** `program_id`; dedicated runs carry `program_id` + channel mapped from program type; RECALL write-downs omit `demand_forecast_id`; the expiry composite advances the clock past `agreement_end_date`.
5. **Create-status rule**: no helper calls `validate_success` with a default status — fixtures use `get_success_data` (lenient 2xx, loud "Setup step failed" on error) per the skill; Stage 2 asserts 201 on creates explicitly. `api_client.py` reads the base URL solely via the framework's `API_BASE_URL` env handling.

## Composite-fixture inventory (exported from `fixtures.py`)

- **Supplier chain**: `create_bare_supplier` / `create_qualified_supplier` / `create_qualified_active_supplier` (+ `qualify/suspend/disqualify/activate_agreement/terminate_agreement` steps) — serves all supplier-standalone instances, `nsm_supplier_requalification_cycle`, `tc_supplier_disqualify_depth2`, tolerance/qualification corners.
- **Lots**: `create_received_lot`, `release_lot`, `reject_lot`, `create_released_lot` — `dvc_lot_landed_cost_provisional_vs_final`, release-twice, wrong-role QC corners.
- **Lines**: `create_owned_line`, `create_coman_line`, `certify_coman_line`, `move_line_operational`, `reset_line_to_idle` — `nsm_line_parallel_dimensions`, `bpc_texture_80_moisture_30_passes`, `pvc_certification_beats_window_overlap`, `cesd_run_create_requires_line_certified`, capacity-month corner.
- **Product/label (OCC-aware)**: `create_product_with_approved_label`, `create_pilot_product_with_label`, `create_active_product_with_label` — label revision loop, supersede cascade, stale-product-version OCC, claim-gate corners.
- **`setup_production_scenario`** — the canonical chain (supplier QUALIFIED/ACTIVE + released 500 kg lot at final 535 + OWNED CERTIFIED line + ACTIVE product with APPROVED label) shared by ~40 instances.
- **Run lifecycle**: `schedule_run` (fresh line OCC token every call), `start_run`, `complete_run`, `abort_run`, `release_run`, `recall_run`, `get_run_batch`; composites `setup_run_in_progress`, `setup_completed_batch`, `setup_recalled_batch`.
- **Programs**: `create_lto_program` / `create_sampling_program`, `setup_lto_program(_in_window)`, `setup_sampling_program_in_window`.
- **Tier-4 threshold targeting**: `setup_lto_program_with_deliveries(committed_cases, run_kg_list)` — serves `cf_delivered_cases_per_run_floor` (24, [105,105]), `bpc_attainment_85_exact_converts` (20, [100,75]), `cn_calc_attainment_below_boundary_converted_fails` (20, [100,65]); `setup_two_batches_staggered_expiry` (FEFO corner); `setup_expired_agreement_supplier` (clock-sweep instance).
- **Forecasts/write-downs**: `create_locked_forecast`, `create_actualized_forecast`; `propose_write_down` / `decide_write_down` / `post_write_down` / `reject_write_down` / `setup_proposed_recall_write_down` / `setup_posted_recall_write_down` — segregation-aware: proposer defaults to `planner-1`, decider to `fin-1`, both via `make_demand_planner_headers(user_id)` / `make_finance_controller_headers(user_id)` so the forbidden self-decision is constructible.

## PRD gaps routed around (no values invented)

1. **No GET-by-id for Supplier or ProductionLine** in PRD §4 — `fetch_supplier`/`fetch_line`/`current_line_version` re-read through the list endpoints, mirroring the design recipes' own `GET .../production-lines` + `$.data[0].version` capture pattern.
2. **All eight roles are `opaque`** (PRD §2.1 explicitly: no ownership check compares `X-User-ID` to a resource id) — so no entity-backed identity threading exists here; the only identity-sensitive rule is write-down segregation of duties, handled by the per-call header builders above.
3. **Conditionally-null payload pairings** (`supersedes_product_id`, LTO-vs-sampling field exclusion): `supersedes_product_id` is sent as explicit null for first generations (PRD §3.4: "the first generation carries null"); forbidden counterpart fields (budget on LTO, partner on sampling, co-man fields on OWNED) are **omitted entirely**, matching every happy-path recipe in both design indices rather than guessing an explicit-null semantics.

Orchestrator verification: 9 helper files present, `import test_helpers` OK (229 names), test_suite/ absent as expected at this stage. Claims match source.

## Step 5b: Generate test suite (Stage 2) — 2026-10-01T21:52:20.000Z

Stage 2 is complete and both final audits pass. Summary:

## Files written (13, all under `test_suite/`)
`conftest.py` + 12 test files: `test_01_suppliers.py` (12 tests), `test_02_lots_and_costing.py` (10), `test_03_production_lines.py` (9), `test_04_products_and_labels.py` (9), `test_05_run_scheduling.py` (16), `test_06_run_execution.py` (13), `test_07_programs.py` (13), `test_08_batch_reservations.py` (7), `test_09_demand_forecasts.py` (3), `test_10_write_down_proposals.py` (8), `test_11_write_down_decisions.py` (7), `test_12_security_baseline.py` (3). Every file py_compiled clean right after writing; creates assert 201 explicitly.

## Collect-only
`python3 -m pytest test_suite --collect-only -q` → **110 tests collected, 0 errors** (run with the task dir on PYTHONPATH, as the runner provides).

## AST tag audit (real `ast` parse + yaml cross-reference)
- 110/110 tests carry exactly one `Design:` tag as the final docstring line; all tags resolve to real instances.
- **Queue A (Difficulty): 20/20 instances, 40 tests** (each ≥2). Per rule: 9 rules each fully covered (boundary_precision_check 4, combinatorial_formula 4, compensating_invariant 4, cross_entity_state_dependency 6, dual_variant_calc 4, non_linear_state_machine 6, priority_pair_validation_conflict 4, resource_temporal_overlap 4, transitive_cascade 4).
- **Queue B (Corner): 70/71 active instances, 70 tests** — calculations 8, consistency_model 1, cross_cutting_layers 3, endpoints 2, entities 10/11, rbac 3, state_machines 11, validations 32.
- All 4 `excluded_because` stubs emit nothing; cross-references verified (`cesd_lot_release_requires_agreement_active`, `ci_batch_reserve_terminate_release`, `dvc_lot_landed_cost_provisional_vs_final`, `cesd_forecast_miss_writedown_requires_actualized` all exist).
- Verbatim-citation sweep: 124 quoted fragments (≥8 words) all grep-verbatim in PRD.md (6 initially non-verbatim citations were fixed, mostly `§` vs "section" and missing backticks).

## Skip list (1, PRD-silence)
- `Corner/entities/cn_ent_computed_status_input_ignored` — PRD §3.1 pins the initial `qualification_status` and §4 omits the field from the create input list, but never says whether a client-smuggled system field is ignored or rejected; §2.8 tier 11 ("unknown ... inputs" → `ERR_INVALID_REQUEST`) makes a 400 equally faithful, so no unique observable outcome exists.

## Helper-name mismatches
**None** — every fixture/factory/assertion was used exactly as exported from the frozen `test_helpers/`. Three recipe-level adaptations were made in test code only (helpers untouched):
1. `cn_occ_label_approve_stale_product_version`'s label-v2 payload (`fat_g: 4` + `LOW_SATURATED_FAT`) would fail the §3.4 claim gate at SUBMITTED; used `claims: ["HIGH_PROTEIN"]` (protein_g 24 ≥ 20) so the OCC rule is what's exercised.
2. Recipes asserting `version == 1/2/3` literals were translated to the PRD-pinned relative form (`version` advances by exactly one, §2.7/§3.4) since §2.5 never pins the initial value.
3. `produced_at`/`expiry_date` are compared as parsed datetimes rather than string equality (fractional-digit formatting for clock-derived fields is not uniquely pinned), and write-down tests needing the 4250-cents/case batch pass `invoiced_unit_cost_cents=465` through the scenario fixtures' `**scenario_kwargs`.

Orchestrator verification: independent `pytest --collect-only` run collected 110 tests, 0 errors. Claims match source.

## Step 6: Generate implementation — 2026-10-01T22:31:52.000Z

All verification complete. Here is the summary.

## Files written (23) — `workspace/implementation/`

- **Foundation**: `constants.py` (full named-constant registry, PRD-exact), `errors.py` (43-id catalog with HTTP statuses), `clock.py` (logical clock, default 2026-09-01T00:00:00Z, ISO parse/format helpers), `store.py` (in-memory dicts, dirty-tracking flush giving +1 version per modified entity per request), `response.py` (exact `meta`/`response_type`/`data` envelope, pagination), `middleware.py` (X-User-ID/X-User-Role auth), `validation.py` (tier-11 deferred shape-error collector)
- **Routes** (10 modules): `routes_clock.py`, `routes_suppliers.py`, `routes_lots.py`, `routes_lines.py`, `routes_products.py`, `routes_labels.py`, `routes_runs.py`, `routes_programs.py`, `routes_batches.py`, `routes_forecasts.py`, `routes_writedowns.py`
- **Logic**: `services.py` (landed cost clamp calcs, FIFO consumption, parity trio, batch derived_status, attainment/redemption/variance/NRV), `app.py` (factory + error handlers), `start.sh` (exec, $PORT default 10000, 0.0.0.0, guarded pip install), `requirements.txt`

## Verification results

- **py_compile**: all 21 .py files pass.
- **Smoke 1** (port 35237, 23/23 PASS): 401/403 envelope shapes, supplier CRUD+qualify+activate, duplicate 409, weak-audit 422, provisional cost 590 (round(500×1.1)=550+40), release-missing-inputs 400, final cost 555 (clamp(520)+35), supplier aggregates, OWNED-line CERTIFIED, OWNED+coman-fields 400, claim gate 422, clock RBAC + expiry sweep → EXPIRED.
- **Smoke 2** (port 52745, 49/49 PASS): full chain — clamped costs (640/610), label OCC (stale 412) + supersede cascade, activation parity (871 / 0.9467 / true), program 14-day-gap 409, run OCC 412, half-open window legality, per-target RBAC 403, completion FIFO (consumed=[lot1], 85 kg, 10 cases, 4590¢/case), exact produced_at/expiry strings, dedicated-batch full reservation, attainment 66.67→93.33, conversion gate 422 then success, EXPIRY_RISK proximity 422, write-down post (provisional 13770 / final 10770 after NRV), segregation-of-duties 403, forecast variance −30.0/is_miss, RECALL cascade, FIFO residue (lot1 remaining 796).
- **Fresh-boot emptiness**: all 10 list endpoints return total_count=0 — nothing seeded.
- **Endpoint audit**: 39 expected vs 39 registered; zero missing/extra after `<param>`↔`{param}` normalization.
- **Constant fidelity**: all 30 referenced CONST names defined; all registry values diffed against PRD literals — no mismatch; error catalog 43/43 with exact statuses. All smoke servers were killed by saved PID; no stray processes.

## Interpretations chosen (candidate over-guards for the fix loop)

1. `created_at`/`updated_at` read the **logical clock** (3-fractional-digit format per §2.5); `produced_at`/`expiry_date` use canonical format (no fraction on whole seconds, matching the PRD's clock literal); client-supplied datetimes echoed verbatim.
2. Run completion with 0 < actual < 10 kg (cases_produced == 0) → **400 ERR_INVALID_REQUEST** (PRD: "a division that requires at least one full case" names no error id).
3. System-only/backward transition targets (DRAFT, PENDING_AUDIT, PROPOSED, DEVELOPMENT, SUPERSEDED, EXPIRED, COMPLETED) → **409**; unrecognized strings / wrong-dimension targets → **400**.
4. Label draft under SUNSET/DISCONTINUED product → **409 ERR_INVALID_STATE** (PRD states the allowed set but no error id).
5. Supplier create with agreement_end_date ≤ start → **400** (scaffold tier-7 applies_to excludes POST /suppliers).
6. DISQUALIFIED lockdown fires **before** body/shape evaluation (409 even for malformed bodies).
7. `redemption_rate_pct` initialized to 0.0 at creation for SAMPLING_DEMO with coupons_issued > 0 (scaffold field def); `attainment_pct` stays null until first recompute trigger (PRD §3.6 explicit).
8. Pagination: non-integer / limit < 1 / offset < 0 → 400; limit > 100 **clamped** ("capped").
9. audit_score enforced integer 0..100 ("a score from 0 to 100").
10. FEFO read literally: an earlier-expiry same-product+channel batch with available_cases > 0 blocks even if itself EXPIRED/recall-flagged.
11. Re-reserving additional cases to the **same** program is allowed (only "a different program" triggers ERR_BATCH_ALREADY_RESERVED).
12. ERR_PROGRAM_TARGET_NOT_MET checked immediately after the state gate (the scaffold's validations table never assigns it a tier).

**Guards deliberately NOT added** (unstated in PRD): no product-match gate between a dedicated run and its program's product; no `dedicated_run_required` enforcement on reservations; no positivity constraints on budget_cents / monthly_reserved_capacity_kg / label version_number beyond integer typing; no clock-monotonicity guard; no moisture/protein thresholds at lot release.

Orchestrator verification: all 21 .py files compile; url_map registers 39 rules; constants.py spot-check (clock default, 920, 85.00, −20.00) matches PRD literals. Claims match source.

## Step 7: Run tests and iterate — 2026-10-01T22:37:46.000Z

Clean sweep on the first iteration: all 8 parallel rounds report 110/110 passed, confirmed at both the aggregate and per-test level. No fixes were needed.

## Summary

- **Iterations run**: 1 (initial sweep passed; no further iterations required).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.
- **Sibling unasserted implementation paths**: not applicable (no test-side fixes were made, so no rules lost coverage).
- **Results artifacts**: all 8 `results.${i}.json` files from the final passing sweep are present in `workspace/implementation/` (results.1.json through results.8.json, each showing total=110, passed=110, failed=0, per-test `status` all "passed").

Orchestrator verification: independently read all 8 results files — each total=110, passed=110, failed=0. Claims match source.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T22:37:46.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. Per the skip condition, PRD.md already determined every behavior the implementation exhibits; PRD_FINALIZED.md is not produced.

## Step 9: Complete PRD — 2026-10-01T22:58:26.000Z

The diff is verified: exactly 23 hunks, each matching one intended edit, nothing else. Line counts: PRD.md 303 lines / 52,812 chars → PRD_COMPLETED.md 309 lines / 56,881 chars (+6 lines, +4,069 chars).

## Summary

**Source vs output:** `workspace/PRD.md` (303 lines, 52,812 chars) → `workspace/PRD_COMPLETED.md` (309 lines, 56,881 chars; +4,069 chars). Diff verified by hand: 23 hunks, all and only the intended edits.

**Counts:** 23 ambiguity-pins, 0 mismatch-revisions, 0 impl-defect-candidates.

All 22 implementation files walked (every route, service function, middleware, response/pagination helper, error catalogue, constants registry) and checked each behavior against the PRD: endpoint inventory, roles, per-target run-lifecycle RBAC, all state machines, every gate in the §2.8 cascade (order verified per route), all formulas (provisional/final lot costing, parity trio, required-isolate ceiling, per-lot-then-sum batch costing, attainment/redemption/variance, NRV write-down), all defaults and null-until semantics, response envelopes, and pagination. Every concrete rule the PRD states is matched by the implementation; all remaining gaps were PRD silences, pinned as follows:

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as wall-clock (the logical clock governs domain data only) — implementation/response.py:16-17
- §2.2 — insert — ambiguity — unmatched path or unsupported method → `ERR_NOT_FOUND` (404); internal failure → `ERR_INVALID_REQUEST` (400) — implementation/app.py:43-53
- §2.3 — revise — ambiguity — non-integer `limit`/`offset`, `limit`<1, negative `offset` → `ERR_INVALID_REQUEST`; `limit`>100 clamped; `created_at` ties ordered by creation sequence — implementation/response.py:37-76, routes_*list* sort keys
- §2.4 — revise — ambiguity — clock may be set to any instant (earlier or later); missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/routes_clock.py:23-26
- §2.5 — revise — ambiguity — `version` starts at 1; `created_at`/`updated_at` stamped from the logical clock; client-supplied timestamps stored/echoed verbatim and compared as instants; batch `produced_at`/`expiry_date` omit the fractional part on whole seconds — implementation/store.py:34-46, implementation/routes_runs.py:320-321, implementation/clock.py:31-36
- §2.8 — insert — ambiguity — `supplier_code`/`line_code`/`product_code`/`program_code` must be non-empty; unused body fields ignored — implementation/routes_suppliers.py:27, routes_lines.py:41, routes_products.py:32, routes_programs.py:42, implementation/validation.py
- §2.10 — revise — ambiguity — one `version` increment and one `updated_at` refresh per resource per request — implementation/store.py:49-61
- §3.1 — revise — ambiguity — supplier registration rail/date-order violations → `ERR_INVALID_REQUEST` — implementation/routes_suppliers.py:43-49
- §3.1 — revise — ambiguity — requesting unreachable targets (`PENDING_AUDIT`; `DRAFT`/`EXPIRED`/`COMPLETED`) → `ERR_INVALID_STATE`; `audit_score` outside 0–100 → `ERR_INVALID_REQUEST` — implementation/routes_suppliers.py:109,160-161,183-185
- §3.1 — revise — ambiguity — disqualification cascade fires only while the agreement is `ACTIVE`; `DRAFT`/`TERMINATED`/`EXPIRED`/`COMPLETED` agreements and their lots untouched — implementation/routes_suppliers.py:154-159
- §3.2 — revise — ambiguity — QC `decision` values spelled `RELEASED`/`REJECTED` — implementation/routes_lots.py:126
- §3.2 — revise — ambiguity — FIFO consumption: further ties after `received_at`/`created_at` fall to receipt-recording order — implementation/services.py:65
- §3.3 — revise — ambiguity — failing audit on a `SUSPENDED` line leaves it `SUSPENDED` — implementation/routes_lines.py:156-158
- §3.4 — revise — ambiguity — `supersedes_product_id` optional on any generation; only existence enforced (`ERR_NOT_FOUND`); pairing never policed — implementation/routes_products.py:35-39
- §3.4 — revise — ambiguity — label submit/return/approve gated only on the label's own status; product lifecycle state constrains drafting only — implementation/routes_labels.py:39-40 vs 122-123
- §3.5 — revise — ambiguity — dedicated-run containment in the program window is inclusive of both bounds — implementation/routes_runs.py:103
- §3.5 — revise — ambiguity — completion with `actual_quantity_kg` under 10 kg (zero full cases) → `ERR_INVALID_REQUEST` — implementation/routes_runs.py:250-251
- §3.6 — revise — ambiguity — sampling `redemption_rate_pct` opens at 0.0 when `coupons_issued`>0, null when 0; LTO always null; `dedicated_run_required` accepted on either type, default true — implementation/routes_programs.py:49,86-87,105-109
- §3.6 — revise — ambiguity — termination touches reservations only; `SCHEDULED`/`IN_PROGRESS` dedicated runs are unaffected and still credit the program and reserve their batch on completion — implementation/routes_programs.py:241-252, implementation/routes_runs.py:329-333
- §3.7 — revise — ambiguity — reservation `quantity_cases` must be ≥1 (`ERR_INVALID_REQUEST`) — implementation/routes_batches.py:59
- §3.8 — revise — ambiguity — `week_start` accepted as any ISO-8601 instant (midnight not validated); triple uniqueness compares instants, not strings — implementation/routes_forecasts.py:33,42-49
- §3.8 — revise — ambiguity — write-down `decision` values spelled `POSTED`/`REJECTED` — implementation/routes_writedowns.py:133
- §4 — revise — ambiguity — transition endpoints take `target_status` (product lifecycle: `target_state`; supplier adds `dimension`; the two decision endpoints take `decision`) — implementation/routes_labels.py:112, routes_runs.py:204, routes_programs.py:156, routes_forecasts.py:106, routes_suppliers.py:105, routes_products.py:101

**Impl-defect candidates:** none. No PRD-stated concrete rule was found omitted or violated in the implementation, so no PRD text was left unchanged on mismatch grounds.

**Confirmation:** ran `diff PRD.md PRD_COMPLETED.md` and read the full output — it shows exactly the 23 intended edits and nothing else. Only `workspace/PRD_COMPLETED.md` was written; no files under `implementation/`, `test_suite/`, or `test_helpers/` were touched.

Orchestrator verification: PRD_COMPLETED.md exists at 309 lines and differs from PRD.md (not a killed-mid-flight no-op); all 8 results.*.json present; no .py source under test_suite/, test_helpers/, or implementation/ is newer than the final sweep's results.1.json — the clean sweep remains valid. Claims match source.
