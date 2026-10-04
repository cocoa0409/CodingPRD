# Worklog — task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply

## Step 1: Create task directory — 2026-10-01T21:38:20.000Z

Task directory was pre-allocated by the orchestrator invocation: `tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/` with `workspace/` inside. Verified it exists and is empty except for `workspace/`; no new index computed and no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-01T23:20:00.000Z

All checks pass. The flagged grounds were checker artifacts (roles and concurrency-rule ids both resolve). Final report:

## Scaffold generation complete — task_3416

**Files written (all three parse cleanly with `yaml.safe_load`):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 10 (Plant, Customer, SupplyAgreement, MetalPriceIndex, ProductionLine, CanFormat, ProductionRun, CustomerForecast, ScrapReturn, QualityIncident)
- Endpoints: 41 (at the ~40 cap; includes `POST /_clock/set_current_utc` with the mandated `2026-09-01T00:00:00Z` default stated in its description)
- State machines: 6 (agreement with ACTIVE↔RENEGOTIATING cycle; run with IN_PROGRESS↔HELD cycle; incident fork-join OPEN→{ESCALATED,RESOLVED} with divergent side effects; format/scrap/forecast)
- Calculations: 9 (incl. provisional-vs-final pricing, per-run-round-then-sum invoicing, capped multi-factor spoilage, rolling-vs-lifetime forecast accuracy, tier true-up, termination exposure)
- Validations: 9 ordered priorities; Errors: 24; Roles: 5 (CustomerPlanner is `entity_backed:Customer`, others opaque); OCC concurrency rules: 2 (amend + run-create on `SupplyAgreement.version`)
- §1.8 difficulty instances: 18 (9 rules × 2, all with structured `setup_api_calls`, placeholder-closed, precomputed literal asserts — e.g. 5032.80 vs 5226.00 pricing variants, rolling 90.00 vs lifetime 94.29, tier true-up −24000.00, capacity == allowed / +1 rejected)
- §1.9 corner instances: 43 (42 active + 1 `excluded_because` stub) across all nine guide sections
- Constants: every `CONST.*` referenced anywhere is defined in a top-level `constants:` map (14 entries, all concrete)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (625 calls scanned.)

**Issues hit and fixed during generation:**
- Twice, a shell heredoc spliced the literal `EOF`+command line into the YAML mid-file (the known incremental-append corruption); detected by re-parsing after every append, repaired by deleting the stray lines; later chunks were staged via a temp part-file + `cat >>` to avoid recurrence.
- One unbound `${plantId}` placeholder (case typo) fixed to `${plant_id}`.
- One unquoted `$.data[0]...` capture inside a flow mapping quoted.
- One arithmetic error in a corner assert corrected (5340.00 unit → 1335000.00 amount).
- Lint initially failed FK reverse-reachability: the checker requires the literal `{id}` parent path segment, so all path placeholders were normalized to `{id}`; `CanFormat.customer_id` then needed a top-level channel, so the formats list became `GET /formats` (plant_id?/customer_id?) plus `GET /formats/{id}` (41st endpoint).
- Caught and rewrote an unsatisfiable corner setup (start-on-held-line originally created the target run *after* the hold was active — reordered so R1 is scheduled while healthy, then the sibling's incident escalates).
- Verified post-hoc: no forbidden concurrency vocabulary, all 24 error codes referenced with trigger sites, instance names unique across both design files, no circular preconditions in the state machines.

Orchestrator verification (post-hand-back): all three YAMLs re-parsed cleanly; `api_prefix` is the empty string (root-relative paths — valid); endpoint prefixes all in-domain (plants, customers, supply-agreements, metal-price-indices, production-runs, forecasts, formats, scrap-returns, quality-incidents, _clock); 84 domain-vocabulary hits; 41 endpoints; 14 constants; 10 entities confirmed.

## Step 3: Copy shared files — 2026-10-01T23:19:56.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T23:45:00.000Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/workspace/PRD.md` (310 lines). The withheld design-index files were never opened.

## Section outline

- **§1 Introduction** — 2 paragraphs (freight/siting economics + operational texture: tooling, changeovers, quality holds, forecasts, scrap, logical clock)
- **§2 Global Specifications** — 2.1 Roles & RBAC (5 roles, `CustomerPlanner` entity-backed by `Customer`, 4 opaque; ownership scopes enumerated), 2.2 API Response Structure (**byte-identical** to canonical source — verified by diff), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` asc, all list filters), 2.4 Logical Clock & Operations Checkpoint (`2026-09-01T00:00:00Z` default, `ops_run_index`, both expiry sweeps, year-matching), 2.5 Common Resource Properties (MetalPriceIndex exception: no `updated_at`/`version`), 2.6 Nested Paths & FK existence order, 2.7 Validation Priority Order (all 9 gates, with inner orderings), 2.8 Units/Precision/Rounding (per-run round-then-sum pinned, sum-then-round forbidden), 2.9 OCC (both rules, `expected_agreement_version`, `ERR_STALE_VERSION`/412), 2.10 Warehouse Projection & Posture (gate with equality allowed, LOCKDOWN/CONGESTED/OPEN thresholds with integer floor)
- **§3 Business Logic** — 9 subsections: network foundations, agreement lifecycle (sign window, renegotiation cycle, termination exposure waterfall), lines & formats (tooling terms, amortization), run scheduling gauntlet, execution/completion/void (spoilage cap 0.15 with +0.03/+0.02 factor stacking, provisional pricing at prior-month index), settlement & tier true-up (sign conventions both flip directions, triggering run excluded), forecasts (rolling mean-of-ratios vs lifetime ratio-of-aggregates), scrap & recycled content (closed-interval conflicts, 2/day cap), quality incidents (escalate/resolve fork, line-hold cascades)
- **§4 Endpoint Definitions** — 41 rows, 4 columns only, root-relative paths
- **§5 Error Code Catalogue** — 24 rows, 2 columns only

## Hard-contract reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 76 required, 76 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priorities: 9/9 expressed with explicit ordering (incl. quality-hold before lockdown, overlap before buffer, conflict before daily limit, state-check inner order)
- concurrency_rules[]: 2/2 expressed (write_endpoint + expected_agreement_version + ERR_STALE_VERSION/412)
- state_machines[].transitions: 26/26 expressed across all 6 machines (preconditions paired with error_ids, all side effects incl. cascades)
- calculations[]: 9/9 expressed (per-run round-then-sum, provisional-vs-final index variants, capped spoilage, rolling-vs-lifetime accuracy, tier true-up signs, termination waterfall)
- validations[] conditions: 9/9 matchable to error_ids in prose; all 24 error_ids appear in §2/§3
- endpoints[].side_effects / applies_to: all expressed
- entities[].fields[] structured content (defaults, null-until-settled, computed formulas): reconstructible
- sibling-branch symmetry: resolve OPEN/ESCALATED, void COMPLETED/SETTLED, cancel SCHEDULED/HELD, retire TOOLED/QUALIFIED, terminate/expire ACTIVE/RENEGOTIATING all symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 354; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

Also verified mechanically: all 42 enum/state values, all 5 role names, all 41 endpoint paths in §4, all 24 errors in §5, and all 14 constant literals (0.04, 0.12, 400, 0.15, 0.03, 0.02, 240, 2/day, 3, 0.20, 5,000, 1,000,000, 1-month lag, default clock) appear in the prose. File ends at §5 with no audit footer.

Orchestrator spot-check: PRD.md is 310 lines, 50 `ERR_` mentions, opens with the aluminum-can freight/siting framing, and pins the logical clock default `2026-09-01T00:00:00Z`.

## Step 5: Generate unit tests — 2026-10-02T00:10:00.000Z

Generation complete. Final report:

## Files written

**test_helpers/ (9 files):** `types.py` (10 entity TypedDicts — MetalPriceIndex correctly omits `version`/`updated_at` per common_fields:false — 15 status/role enums), `constants.py` (14 PRD-pinned literals, all diffed against PRD prose), `api_errors.py` (24 error IDs + HTTP map registered with the framework), `api_client.py` (35 endpoint methods, root-relative paths since `api_prefix` is `""`), `factories.py`, `test_users.py` (shared constants + mandatory `make_customer_planner_headers(customer_id)` builder for the entity-backed CustomerPlanner role — never shares one X-User-ID across distinct customers), `assertions.py`, `fixtures.py` (composite setup tiers: clock, network, active agreement, run env, scheduled/in-progress/completed runs, forecasts, scrap, incidents — all with identity threading and auto OCC version re-reads), `__init__.py` barrel.

**test_suite/ (24 files):** `conftest.py` + 23 test modules (`test_01`…`test_23`).

## Coverage audit (AST-parse evidence)

- **78 test functions**, 60 distinct `Design:` tags, exactly 1 tag per test, zero orphan tags, zero tests with 0 or 2+ tags.
- **Queue A: 18/18 difficulty instances** carry ≥2 tests each (36 tests).
- **Queue B: 42/42 active corner instances** carry ≥1 test each (42 tests). The 1 excluded stub (`cross_cutting_layers/dual_variant_calculation_layer`) was not translated; its `difficulty_instance` cross-reference resolves to a real §1.8 instance.
- **PRD-citation pass: 93/93** quoted chunks (≥8 words) survive a literal normalized grep of PRD.md.
- **No skipped instances** — every non-stub instance passed the PRD-first two-condition filter.
- `pytest --collect-only -q`: **78 tests collected, 0 errors** — package graph intact.

## Re-derivations (design literals that contradicted PRD + inputs)

1. **`invoice_round_per_run_then_sum_beats_sum_then_round`** — the design's literals (unit 3189.74, per-run 24806.61, revenue 49613.22/49613.19) are arithmetically inconsistent with the PRD formula on the recipe's own inputs. Exact-decimal and IEEE-float re-derivation both give: unit = round_half_up(13.5×101.3×0.87+2000, 2) = **3189.77**, per-run = **24806.84**, revenue = **49613.68**, forbidden sum-then-round = **49613.66**. The tests assert the re-derived values (and still pin the forbidden-order divergence, now 2 cents).
2. **`run_ops_expires_past_end_agreements_and_stale_pickups`** — the recipe's clock sequence (set 2026-08-01 from the 2026-09-01 default) requires moving the clock backward, which "advances the clock" in PRD §2.4 does not license. Re-derived forward-only: sign at the 2026-09-01 default with end_date 2026-09-30 and pickup window 2026-09-10, advance to 2026-10-02, then run-ops. Same rule asserted (agreement EXPIRED, pickup EXPIRED, ops_run_index 1 → 2 idempotent re-sweep).

All fixture dates are reachable from the 2026-09-01T00:00:Z clock start (forward-only). All create calls assert 201 explicitly via `validate_success(resp, 201)` / `get_success_data(..., expected_status=201)`. No skip/xfail markers anywhere; no scaffold references in comments or docstrings.

Orchestrator verification (independent AST re-audit): rebuilt the expected instance set from both design YAMLs (18 difficulty + 42 active corner = 60) and diffed against the AST-extracted `Design:` tags — 78 tests, 60 distinct tags, 0 missing, 0 orphans. Hand-back claims confirmed against source.

## Step 6: Generate implementation — 2026-10-02T00:29:27.000Z

Done. The implementation is complete, boots cleanly from a fresh process, and passed two smoke passes covering the main workflow and the corner paths.

## File tree — `workspace/implementation/` (2095 total lines)

```
implementation/
├── start.sh                 (10 lines, executable, guarded pip install + exec)
├── requirements.txt         (flask>=2.2,<4)
├── app.py                   (45)   entry point, blueprints, error handlers
├── db.py                    (97)   in-memory store, logical clock, monotonic ISO ts, touch()
├── errors.py                (39)   ApiError + all 24 catalog error ids/statuses
├── response.py              (38)   meta/response_type/data envelope, pagination meta
├── middleware.py            (41)   X-User-ID/X-User-Role auth, role + ownership gates
├── validation.py            (157)  body shape, types, ranges, ISO date/dt/period, pagination
├── services/
│   ├── __init__.py          (0)
│   ├── calc.py              (263)  all 9 calculations + 14 constants verbatim
│   └── serialize.py         (162)  public projections + read-time computed fields
└── routes/
    ├── __init__.py          (0)
    ├── clock.py             (20)   POST /_clock/set_current_utc
    ├── plants.py            (74)   create/get/run-ops with both expiry sweeps
    ├── customers.py         (33)
    ├── agreements.py        (189)  create/list/get/sign/open-renegotiation/amend/terminate
    ├── indices.py           (32)   metal price index publish + duplicate period
    ├── lines.py             (51)
    ├── formats.py           (137)  propose/get/list/tool/qualify/retire
    ├── runs.py              (155)  run create (full 9-gate gauntlet) + list/get
    ├── run_actions.py       (203)  start/complete/settle/cancel/void with cascades
    ├── forecasts.py         (91)
    ├── scrap.py             (128)  closed-interval conflict + daily cap + credit
    └── incidents.py         (129)  open/escalate/resolve fork-join
```

## Checks

- **Syntax/import**: `py_compile` over all 22 files → OK; `import app` → OK; route map shows all **41 declared endpoints** (42 rules incl. Flask's `/static` helper).
- **Smoke test 1** (main flow, port 48731, PID 3170953): 401 `ERR_UNAUTHENTICATED` without headers; plant 201 (posture OPEN); customer 201; agreement 201 (DRAFT, freight_zone NEAR); sign 200 → ACTIVE; re-sign 409 `ERR_INVALID_STATE`; indices 201/201; duplicate 409 `ERR_DUPLICATE_PERIOD`; stale OCC 412 `ERR_STALE_VERSION`; run create 201 (correct version) → start → complete (provisional 910.0 from prior-month index, effective_spoilage 0.0526, flag true) → settle (final 977.5 from delivery-month index, settled 8797.5); agreement ledger ytd=9000, revenue=8797.5; plant on_hand=9000, metal_ytd=128.25; list envelope `array/total_count/has_more`; 404 `ERR_NOT_FOUND`. `KILLED_OK`.
- **Smoke test 2** (corners, port 58911, PID 3177322): freight MID for US-SW vs US-NE; escalate → run HELD + line QUALITY_HOLD; create blocked 409 `ERR_LINE_QUALITY_HOLD`; resolve → IN_PROGRESS/RUNNING; scrap touching windows 409 `ERR_PICKUP_WINDOW_CONFLICT`, 3rd same-day 409 `ERR_PICKUP_DAILY_LIMIT`, wrong owner 403 `ERR_UNAUTHORIZED`; forecasts close 100/90/50 → rolling 80.0 / lifetime 80.0, duplicate 409; terminate exposure {shortfall 400000 + tooling 100000 = 500000}; clock set 2027-06-01 + run-ops → agreement EXPIRED, both scrap returns EXPIRED, ops_run_index=1. `KILLED_OK`.

## Key design decisions

- **Constants**: all 14 transcribed exactly in `services/calc.py` (0.04, 0.12, 400, 0.15, 0.03, 0.02, 240, 2, 3, 0.20, 5000, 1000000, lag 1, clock default `2026-09-01T00:00:00Z`).
- **Derived vs locked fields**: `posture`, `projected_warehouse_units`, `volume_tier`, rolling/lifetime accuracy, `unamortized_exposure_cents`, `recycled_content_pct` are pure functions computed at read time; prices/spoilage/settled amounts are locked at their transition (provisional at complete, final at settle).
- **YTD accumulators are event-sourced**, tagged with the clock year of the completion/credit (voids append a compensating event tagged with the original completion year), so `scrap_credit_lbs_ytd`/`metal_consumed_lbs_ytd`/`recycled_content_pct` always reflect the current clock year per PRD §2.4, even across clock sets.
- **Validation order** follows PRD §2.7 exactly: auth → authz/ownership → body shape → existence (path L-to-R, then body FKs in declared input order) → OCC 412 → state (target, then path-parent, then body-FK) → safety (quality-hold before lockdown) → temporal (overlap before buffer; pickup conflict before daily cap) → business.
- **Money math** is `Decimal` + `ROUND_HALF_UP`; per-run/per-component rounding pinned before summation; tier true-up prices the triggering run at the pre-flip tier and credits only sibling SETTLED runs.
- **No seeding**; storage is dicts only; `start.sh` guards the pip install and `exec`s the server on `$PORT`/`0.0.0.0` in the foreground.

Orchestrator verification: `bash -n start.sh` OK; `py_compile` over all modules OK; grep of implementation tree for `test_suite`/`test_helpers`/`SCAFFOLD_DIFFICULTY`/`SCAFFOLD_CORNER` returned nothing — isolation rule held.

## Step 7: Run tests and iterate — 2026-10-02T00:45:00.000Z

Clean exit — all 8 rounds pass.

## Summary

**Iterations run:** 2 (initial sweep surfaced 1 consistent failure; fix verified on re-sweep).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/test_suite/test_11_run_execution.py` — `TestSettlementIndexGate.test_settle_without_delivery_month_index_returns_index_not_published`: changed `setup_run_env()` to `setup_run_env(pass_through_pct=1.0)`.

**Why (STEP 2 — test bug, not impl bug):** The test's assertion `settled_amount_cents == 1335000.00` derives from "30.0 lbs × 128.0 × 1.0 + 1500" per its own comment, i.e., pass_through_pct = 1.0. But the setup called `setup_run_env()` with no overrides, so the agreement inherited the `test_helpers/factories.py` default `PASS_THROUGH_PCT = 0.9`. PRD §3.5/§3.6 verbatim requires the metal component to be multiplied "by the agreement's `pass_through_pct`", which with 0.9 uniquely yields (30×128×0.9 + 1500) × 250 = 1,239,000 — exactly what the implementation returned on all 8 rounds. Every other exact-amount pricing test in the suite (test_12, test_13:53, test_14:88/153, test_15:16) passes `pass_through_pct` explicitly; this test simply omitted the override. The primary assertion (ERR_INDEX_NOT_PUBLISHED gate) was already passing; the fix aligns the fixture with the test's documented derivation.

**Fixes applied to `test_helpers/`:** None — the factory default 0.9 is PRD-legitimate and used consistently elsewhere.

**Fixes applied to `implementation/`:** None — the implementation's settlement formula was PRD-faithful.

**Results artifacts:** All 8 `results.${i}.json` files remain in `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/workspace/implementation/`, each showing `passed == total == 78`, `failed == 0`.

Orchestrator verification: all 8 results files independently re-read — 78/78 passed, 0 failed in every round; no `.py` source file in test_suite/, test_helpers/, or implementation/ is newer than the oldest results file, so the clean sweep reflects current code; the claimed test_11 fix (`setup_run_env(pass_through_pct=1.0)` at line 41) spot-checked present.

## Step 8: Finalize PRD — 2026-10-02T00:42:27.000Z

**Step 8 complete — zero-edit outcome, confirmed by evidence.**

**File status:** PRD.md: 310 lines; PRD_FINALIZED.md: 310 lines; 0% delta. `diff -q` confirms the two files are **byte-identical**. The file was produced via `cp` as instructed:
`/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/workspace/PRD_FINALIZED.md`

**Changes:** None.

**Why zero edits is correct here:** the sole `<step_7_diff>` item was adjudicated as a pure test-fixture bug, and my investigation confirms that adjudication on all three legs:

1. **PRD already uniquely pins the behavior** (no silence to patch):
   - PRD.md:197 (§3.5): "the metal component is the format's `metal_lbs_per_1000_units` multiplied by the aluminum index in `index_cents_per_lb` and by the agreement's `pass_through_pct`"
   - PRD.md:203 (§3.6): "the system computes `final_unit_price_cents_per_1000` with **exactly the same formula as §3.5** but on the final variant of the index"
   Together these leave zero degrees of freedom on whether settlement multiplies by `pass_through_pct`.

2. **Implementation is PRD-faithful.** Formula site read: `implementation/services/calc.py:55-60` — `can_unit_price` computes `metal = metal_lbs_per_1000_units × index_cents_per_lb × agreement["pass_through_pct"]`, and both callsites were enumerated and read: `implementation/routes/run_actions.py:68` (completion, provisional index = month before delivery) and `run_actions.py:104` (settlement, delivery-month index with `ERR_INDEX_NOT_PUBLISHED` gate at lines 95-99) — both matching §3.5/§3.6 verbatim, including the shared formula.

3. **Test fix inspected and arithmetic reproduced.** `test_suite/test_11_run_execution.py:41` now passes `pass_through_pct=1.0`, matching the test's own derivation comment (line 55: "30.0 lbs x 128.0 x 1.0 + 1500 = 5340.00; x 250000 / 1000" = 1,335,000.00 = the assertion at line 56). The pre-fix call inherited `PASS_THROUGH_PCT = 0.9` (`test_helpers/factories.py:11`, applied at line 57), under which the PRD-pinned formula uniquely yields (30×128×0.9 + 1500)×250 = 1,239,000 — exactly what the implementation returned on all 8 sweep rounds. `setup_run_env(**agreement_overrides)` forwards overrides to the agreement factory (`test_helpers/fixtures.py:169-181`), so the fix mechanism is sound.

Per the task's own guidance, a fixture-only Step 7 diff means the PRD needs no patch, and manufacturing an edit would risk violating the no-new-mismatch rule against the many other paths touching `pass_through_pct` (agreement create at `routes/agreements.py:38`, amend at `agreements.py:151/168`, serialization at `services/serialize.py:45`). No edits were committed.

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed independently (310 lines each).

## Step 9: Complete PRD — 2026-10-02T01:05:00.000Z

All 8 rounds pass 78/78. The work is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 310 lines / 45,772 chars → `PRD_COMPLETED.md` 314 lines / 49,880 chars (+4 lines, +4,108 chars). Not byte-identical (edits made); the pre-edit `cp` was verified identical via `diff -q`. `PRD_COMPLETED.md` is at `/home/ubuntu/github/CodingPRD/tasks/task_3416_aluminum_can_manufacturing_plant_proximity_sheet_supply/workspace/PRD_COMPLETED.md`.

**Counts:** 14 ambiguity-pins, 3 mismatch-revisions, 1 impl-bug-fix. Full 41-endpoint / 6-state-machine / 9-calculation / 9-gate walk done; dead-code check in both directions found no uncalled checks, no calls to undefined checks, and all 24 catalog errors are raised somewhere with every raised id in the catalog.

**Ambiguity-pins (PRD section — what changed — impl ref):**
- §2.1 — insert — pins ownership-vs-existence ordering: path-customer ownership (scrap) precedes existence (403 before 404); FK-based ownership (agreement/forecast) requires the resource, so missing resource → 404 — `implementation/routes/scrap.py:31-32`, `implementation/routes/agreements.py:111-115`
- §2.2 — insert — undefined path/unsupported method → `ERR_NOT_FOUND` 404 envelope; unexpected failure → 500 `ERR_INTERNAL` — `implementation/app.py:29-41`
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; `has_more` = offset + returned < total_count; filter values never validated — `implementation/validation.py:140-157`, `implementation/response.py:23-30`
- §2.4 — insert — clock-set accepts any ISO-8601 instant (earlier or later), echoes verbatim, naive timestamps read as UTC — `implementation/routes/clock.py:12-20`, `implementation/db.py:32-40`
- §2.4 — insert — event-sourced YTD: completion/credit events tagged with clock year at occurrence, void posts negative event tagged with the completion's year, accumulators = sum of current-year events — `implementation/services/calc.py:250-256`, `implementation/routes/run_actions.py:81,172`
- §2.5 — insert — `version` starts at 1 — `implementation/db.py:70-73` and all create routes
- §2.5 — insert — `created_at`/`updated_at` are wall-clock; the logical clock governs only business temporal rules — `implementation/db.py:50-57`
- §2.7 gate 3 — insert — fixes the exact integer-typed fields vs any-number fields — `implementation/validation.py:60-95`
- §2.10 — insert — a run's plant attribution flows through its line (projection, lockdown, capacity gate, on-hand cascade) — `implementation/services/calc.py:170-178`, `implementation/routes/runs.py:72-78,94`, `implementation/routes/run_actions.py:79`
- §3.4 — insert — `line_id`/`format_id` are not cross-checked against the agreement's plant/customer — `implementation/routes/runs.py:48-59`
- §3.5 — insert — `sheet_lbs_consumed` carried without rounding — `implementation/routes/run_actions.py:63`
- §3.7 — insert — lifetime accuracy defined as 100 when all closed forecasts are zero on both sides (div-by-zero case) — `implementation/services/calc.py:158-159`
- §3.8 — revise — daily pickup cap keys on the UTC calendar date of `pickup_window_start` — `implementation/routes/scrap.py:58-60`
- §3.9 — revise — incident `note` must be non-empty — `implementation/routes/incidents.py:39` (`req_str`)

**Mismatch-revisions (legitimate interpretations pinned):**
- §2.9 — revise — OCC rejects any `expected_agreement_version` not equal to the current version (lagging or ahead), not only "advanced past" — `implementation/routes/agreements.py:159`, `implementation/routes/runs.py:61`
- §3.3 — revise — the specialty tooling-terms pairing is enforced at tooling time, not at proposal; creation accepts any integer ≥ 0 regardless of `is_specialty` (PRD's creation sentence contradicted its own gate-9 tooling check; tests confirm creation accepts zero terms) — `implementation/routes/formats.py:38-39,99-104`
- §3.5 — revise — only voiding a `SETTLED` run increments the agreement's `version`; voiding a `COMPLETED` run touches no agreement ledger — `implementation/routes/run_actions.py:174-202`

**Impl-bug-fix (rule b — PRD unambiguous, impl violated):**
- `implementation/services/calc.py:214-225` — `format_unamortized_exposure` computed the full `tooling_investment_cents` even for `PROPOSED` formats; PRD §3.3 pins "A proposed format starts in `PROPOSED` with … `unamortized_exposure_cents` at 0" and "upon tooling … initializes … to the full `tooling_investment_cents`". Fixed to return 0 while `PROPOSED`. PRD §3.3 amortization paragraph also gained the "once it has been tooled" qualifier to match. Termination exposure unaffected (only sums TOOLED/QUALIFIED).

**Sweep:** because implementation/ was edited, the full 8-round sweep was re-run afterwards — all 8 fresh `results.{1..8}.json` files show passed == total == 78, failed == errors == 0.

Orchestrator verification: PRD_COMPLETED.md is 314 lines (310 + 4, matching the claim); all 8 results files independently re-read — 78/78 passed in every round; results files (01:00:22) post-date the calc.py impl fix (00:57:24) and no `.py` source is newer than the sweep; the impl fix is present at calc.py:214-217 (returns 0 while PROPOSED).
