## Step 1: Create task directory — 2026-09-05T19:36:20.195908310Z

Created tasks/task_2943_rental_car_fleet_planning_remarketing/ and tasks/task_2943_rental_car_fleet_planning_remarketing/workspace/ (index pre-assigned by orchestrator input; no auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-05T21:56:10.135316253Z

All three scaffold artifacts for task 2943 are complete and lint-clean.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_2943_rental_car_fleet_planning_remarketing/`)

| File | Lines | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 3181 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2758 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3820 | single key `scaffold_corner_design` |

## Counts
- **§1.1–§1.7**: 13 entities, 12 state machines, 2 concurrency rules (`allocation-create-stale-plan`, `consignment-create-stale-vehicle`), 6 calculations, 51 validation rules on a 27-level priority ladder, **71 endpoints**, **67 error codes**, 5 roles (`MarketOperator` is `entity_backed:Market`), `api_prefix: /fleet`.
- **§1.8**: 9 difficulty rules x 2 instances = **18 instances**.
- **§1.9**: all nine `section:` blocks present — entities 13, state_machines 14, calculations 14, validations 8, endpoints 5, errors 10, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1 = **74 instances** (50 full test recipes + 24 `excluded_because` stubs).

## Verification
- `scaffold_lint.py`: 1043 calls scanned across §1.8+§1.9 — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- Error-code sweep: **all 67 codes have a real trigger/assert** (not just a prose mention). The last two gaps found in the final sweep, `ERR_PLAN_POSTURE_RESTRICTED` and `ERR_TRANSPORT_COST_EXCEEDS_BENEFIT`, were closed with two added `errors` instances: a 9-then-2-vs-1 unit allocation pair at fill_ratio_bp exactly 9000, and a 915-km-vs-914-km haul against the MIDSIZE payback ceiling `round_half_up(5500*45) == 247500` (247688 refused / 247425 accepted, the refusing side landing the fuel surcharge on an exact .5 cent).
- Name uniqueness across both design files: no collisions; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; every stub has no `test_recipe` and every non-stub has all four recipe keys.

## Design adjudications
1. **71 endpoints / 67 errors vs the Expert band's 20–32 / 18–30** — justified by the verbatim "harder than expert level" directive plus 13 entities each needing single-GET + filtered-list reverse-reachability and a per-entity NOT_FOUND code.
2. `GET /fleet/ledger-entries/{ledger_entry_id}`, `GET /fleet/ledger-entries` and `ERR_LEDGER_ENTRY_NOT_FOUND` were added because lint check (f)'s sub-resource form requires a literal `{id}` segment.
3. **Three §1.5↔§1.2 self-contradictions repaired**: withdraw-from-`SOLD_PENDING_SETTLEMENT`, missing census restore on withdraw, missing `Market.in_service_unit_count` decrement on consignment create.
4. **One priority-shadowing defect repaired**: p18 `ERR_CHANNEL_NOT_ELIGIBLE` had swallowed the RETAIL_LOT mileage clause owned by p20 `ERR_MILEAGE_BAND_EXCLUDES_CHANNEL`; the p18 `check:` now carves it out and both codes are separately triggerable.
5. **One undeclared constant repaired**: `FLOOR_PRICE_PCT: 0.75` added to `consignment_net_proceeds.constants` (back-derived from §1.8's own 1677000/2236000 literals).
6. **RBAC denial code substitution**: the claim-extraction guide names `ERR_UNAUTHORIZED`, which this §1.6 does not declare; denial instances are written against the declared p3 `ERR_ROLE_NOT_PERMITTED` (403) and p4 `ERR_MARKET_SCOPE_VIOLATION`, recorded in an in-file comment.
7. **Rows deliberately left uninstantiated**, each with an in-file comment: the guide's `Bulk action` endpoint row (§1.5 declares no bulk endpoint), the `approval_chain` / `hierarchical_override` / `delegated_authority` role models (§1.3 declares `segregation_of_duties`), and the `selector_policy` complexity layer (no row in the guide's layer table — covered instead by the `remarketing_channel_selection` calculation instances).
8. All VINs re-minted to the declared 16-character width; `.scratch/step2` removed, `workspace/` and `worklog.md` untouched.

**Orchestrator note (post-subagent):** the difficulty directive line "Generate task harder than expert level!" had leaked into `SCAFFOLD.yaml`'s `scenario:` block (a known scaffold-generator failure mode). The orchestrator stripped that line plus its trailing blank line from `SCAFFOLD.yaml` before Step 4, so the doc generator cannot see it and it cannot reach PRD.md. All three YAMLs re-validated as parseable afterwards; top-level keys confirmed correct (`SCAFFOLD.yaml` has neither design key).

## Step 3: Copy shared files — 2026-09-05T21:56:15.174517676Z

Copied ./INSTRUCTION.md to tasks/task_2943_rental_car_fleet_planning_remarketing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T22:14:32.548112744Z

PRD generation for task 2943 is complete.

**Output:** `workspace/PRD.md` — 505 lines, 113 KB, built incrementally (1 `Write` + 8 heredoc appends, no truncation). Ends cleanly at the final row of the §5 error table; no audit footer in the file. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened; no sibling task dir and no `worklog.md` was read or written. Scratch dir `.scratch/step4/` removed (parent `.scratch/` left intact).

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Operator Identity and RBAC · 2.2 API Response Structure (byte-verbatim from the skill file) · 2.3 Pagination · 2.4 The Logical Fleet Clock · 2.5 Resource Identity, Timestamps and Version Semantics · 2.6 Money, Percentages and Rounding Discipline · 2.7 Optimistic Concurrency on Parent Rows · 2.8 Segregation of Duties in Two-Man Controls · 2.9 Path Resolution and Validation Precedence · 2.10 The Per-Vehicle Fleet Cost Ledger · 2.11 Parallel Lifecycle Dimensions and Cascade Propagation · 2.12 Derived Census and Roll-up Counters
- §3 Business Logic & Workflows: 3.1 Reference Configuration · 3.2 Depreciation Policy (draft, two-man activation, supersession) · 3.3 Sizing the Fleet (plans, postures, allocations) · 3.4 From Purchase Order to First Rent · 3.5 Life in Service (usage, residual valuation) · 3.6 Inter-City Redistribution · 3.7 Damage, Recovery and Total Loss · 3.8 Remarketing · 3.9 Plan Performance Reporting
- §4 Endpoint Definitions (4-column table, 71 rows)
- §5 Error Code Catalogue (2-column table, 67 rows)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_plan_version / expected_vehicle_version + ERR_STALE_PLAN_VERSION / ERR_STALE_VEHICLE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 71 endpoints (40 with side_effects) checked, all expressed, 0 missing
- entities[].fields[] structured content: 122 checked, 122 reconstructible from prose, 0 missing
- sibling-branch symmetry: 21 groups checked, 21 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1072
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage counts:** 13 entities, 12 state machines / 63 transitions, 6 calculations (both variants each for `vehicle_residual_valuation` and `fleet_plan_utilization_and_rpu`), 51 validations across priority bands 1–27, 71 endpoints, 67 error codes, 5 roles. Mechanical extras verified: all 79 scaffold enum values, all 39 state names and all 4 calculation variant names appear verbatim in backticks; every one of the 67 error ids appears in §2/§3 prose, not only in the §5 table; no fuzzy/approximating words.

**Three scaffold ambiguities resolved determinately** (consistent throughout, in case Step 5/7 needs the rationale): allocation create against a non-`LOCKED` plan → `ERR_PLAN_NOT_LOCKED` 409 while lock-time non-`DRAFT` → `ERR_PLAN_NOT_DRAFT` 409; activate with `effective_from` after the logical clock → `ERR_INVALID_REQUEST` 422 and activate-time supersession mismatch → `ERR_SUPERSEDE_TARGET_MISMATCH` 422; publishing straight from `DRAFT` on a channel whose `recondition_required` is true → `ERR_CONSIGNMENT_INVALID_STATE` 409.

**Orchestrator verification (post-subagent, truncation guard):** `wc -l` = 505; tail inspected — file ends mid-table? no: it ends at the last complete row of the §5 error table, a real section boundary. Independent cross-check against SCAFFOLD.yaml confirms all 67 declared error ids and all 71 declared endpoint paths appear in PRD.md; zero occurrences of the words "expert level" or "scaffold". No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T22:55:02.492044217Z

Implementation complete and smoke-verified.

## Deliverable

`workspace/implementation/`

| module | lines | contents |
|---|---|---|
| `app.py` | 74 | app factory, 9 blueprints, `ApiError`/HTTPException/catch-all handlers, `PORT` env |
| `store.py` | 172 | in-memory dicts, logical clock (`2026-08-01T00:00:00Z`), id/seq/rounding/instant helpers |
| `errors.py` | 105 | all 67 catalogue codes + statuses, `ApiError` |
| `envelope.py` | 105 | success/list/error envelopes, `req_`+20-char ids, pagination parsing |
| `auth.py` | 54 | ranks 1-3, MarketOperator entity-backed scope (rank 4) |
| `validate.py` | 180 | rank-7 schema helpers, per-entity 404 loads, rank-6 body FK resolution |
| `calc.py` | 449 | all 6 calculations + every derived counter |
| `serialize.py` | 148 | 13 entity representations, read-time computed fields, ledger without `updated_at`/`version` |
| `cascade.py` | 141 | ledger posting, 4-hop in-fleeting chain, 3-hop total-loss chain, damage/withdraw compensations |
| `filters.py` | 46 | list filters + pagination-before-filter ordering |
| `routes_config.py` | 303 | clock, markets, segments, programs, channels |
| `routes_policy.py` | 124 | policy draft / activate / supersede |
| `routes_plan.py` | 213 | plans, postures, allocations, performance |
| `routes_vehicle.py` | 198 | mint, in-fleet, usage, valuation, recommendation, vehicle ledger |
| `routes_task.py` | 204 | task scheduling, bay collision, daily capacity, complete/waive |
| `routes_order.py` | 283 | 9 redistribution endpoints incl. revision cycle |
| `routes_damage.py` | 264 | report, revise, recovery waterfall, write-off, total loss |
| `routes_consignment.py` | 363 | consign, both recondition/publish branches, sale, settle, withdraw |
| `routes_ledger.py` | 34 | ledger read/list |

Total 3460 lines of Python, plus `requirements.txt` (`flask>=2.0`) and executable `start.sh` (fresh `python3 app.py` each boot, no seeded data, all state lost on restart).

## Coverage

- **Endpoints: 71/71.** Diffed Flask's `url_map` against the PRD §4 table programmatically — zero missing, zero extra.
- **Errors: 67/67.** Every catalogue code is raised somewhere in the route/calc modules, and every HTTP status matches the §5 table (verified by script).
- **Validations:** all 51 scaffold priorities implemented in ladder order (1-27 → PRD §2.9's 17 ranks); precedence spot-checked live (stale version before uniqueness/state, state before SoD, open-damage before eligibility, `ERR_MILEAGE_BAND_EXCLUDES_CHANNEL` vs `ERR_CHANNEL_NOT_ELIGIBLE`).
- **Smoke:** two end-to-end scripts in `.scratch/step6/` (config → policy activation → plan/lock/allocation → mint → in-fleet → 3 tasks → promotion → 4-hop cascade to plan CLOSED → usage → valuation → recommendation → performance → redistribution → damage recovery → consignment → sale → settle → ledger; and recondition branch → withdraw reversal → mileage exclusion → total-loss cascade → suspension gating). Final run: **0 failures**, all hand-checked money figures matched (e.g. loaded recondition 86000 = rhu(80000×1.075); transport 171300 = 156000 + rhu(5%) + 7500; net proceeds 1759040 with independently rounded lines). Server bound to port 33825 and killed by that port only; no broad pkill used.

## PRD ambiguities resolved

1. **Pagination ceiling.** §2.3 says "at most 100" then refuses only values "outside the accepted range of 1 through 200"; I enforce **1-200** (matching the scaffold check and the sentence that carries the error code). Non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; bounds fire before filtering.
2. **Clock representation.** `GET /fleet/_clock` and the setter both return `{"current_utc": <raw string supplied>}`; stored instants are canonicalised to exactly 3 fractional digits; `api_request_timestamp` reads the logical clock.
3. **Derived counters are read-time.** Market census, plan/allocation counters, vehicle `total_recondition_cents`/`net_book_value_cents` are computed on read; markets never version-bump for census movement (only the entities §2.11 names as bubble-up targets bump).
4. **Version bumps.** Allocation bumps on the vehicle-enters-service recompute but not at vehicle mint (scaffold omits it); milestone stamping refreshes `updated_at` only and just the promotion bumps `Vehicle.version`.
5. **`unit_count`.** Absent → `ERR_INVALID_REQUEST`; present but non-integer or < 1 → `ERR_INVALID_UNIT_COUNT`.
6. **Policy activation order** follows §3.2's prose: `ERR_POLICY_NOT_DRAFT` → future `effective_from` (`ERR_INVALID_REQUEST`) → SoD → `ERR_SUPERSEDE_TARGET_MISMATCH`.
7. **Vehicle mint** is not one of §2.9's five body-FK operations, so `current_market_id` existence is checked after schema, and no `ERR_MARKET_SUSPENDED` applies at mint.
8. **Redistribution draft** uses the ladder rather than §3.6's prose order: vehicle state → `ERR_TRANSFER_WINDOW_INVALID` → `ERR_VEHICLE_TRANSFER_OVERLAP` → `ERR_SAME_MARKET_TRANSFER` → `ERR_TRANSPORT_COST_EXCEEDS_BENEFIT`.
9. **Consignment create ordering.** Fleet state (10) → open damage (13) → condition guard → min-holding (16, guarded to ACTIVE `PROGRAM_REPURCHASE` channels on `PROGRAM` vehicles so a SUSPENDED or RISK case reports `ERR_CHANNEL_NOT_ELIGIBLE`) → eligibility (18) → `ERR_NO_ACTIVE_DEPRECIATION_POLICY` → `ERR_MILEAGE_BAND_EXCLUDES_CHANNEL` (the last two share priority 20; I fire them in the order both PRD and scaffold list them). The saleable-condition gate is placed *after* the open-damage check deliberately: the scaffold's condition rule omits this endpoint, and a damaged car is always `DAMAGE_REPORTED`, so a rank-10 condition check would make `ERR_OPEN_DAMAGE_BLOCKS_LISTING` unreachable.
10. **Publish (`/list`).** From `DRAFT` a `recondition_required` channel is refused with `ERR_CONSIGNMENT_INVALID_STATE` (409); the condition check applies only on the DRAFT branch and runs after the open-damage check, for the same reachability reason. From `RECONDITION_PENDING` no condition check applies.
11. **`complete-recondition`** leaves the status at `RECONDITION_PENDING`; a second call is naturally refused by the `RECONDITIONING`-condition guard.
12. **Damage:** `revise-estimate` accepted from `REPORTED` and `RECOVERY_PENDING`, recomputing `total_loss_required` against the *frozen* `net_book_value_at_report_cents`; `write-off` applies the total-loss refusal from both origin states; `settle-recovery` memo is `recovery waterfall recondition N / depreciation N / income N`.
13. **Total-loss cascade:** hop 3 runs for `IN_SERVICE`/`IN_TRANSIT`/`HELD_FOR_SALE` origins; an `IN_FLEETING` origin waives PENDING tasks with no `PREP_COST` and no promotion; `ON_ORDER` retires only. Withdrawals forced by a total loss post **no** `RECONDITION_REVERSAL` (money sunk into a destroyed unit stays in the basis the loss is measured against).
14. **Re-suspend / re-close:** market → `ERR_MARKET_SUSPENDED` (422), program → `ERR_PROGRAM_CLOSED` (409), channel → `ERR_INVALID_REQUEST` (422; the catalogue has no channel-state code).
15. **Plain vehicle read** returns `net_book_value_cents` computed without a policy for PROGRAM units and `null` for RISK units with no ACTIVE policy (that read is not in the `ERR_NO_ACTIVE_DEPRECIATION_POLICY` list).
16. **Intervals:** prep-bay conflict expands only the new closed window by 60 min at both ends (touching = conflict); transfer overlap is half-open `[depart, receive)`.
17. **Task scheduling on a non-`IN_FLEETING` vehicle** → `ERR_VEHICLE_INVALID_FLEET_STATE` (409) at rank 10 (scaffold `applies_to` omits it; PRD §3.4 requires the gate). All three prep fields are required for `PREPARATION` and must be omitted otherwise (PRD wins over the scaffold's `bay_code?`).
18. **Ordering/ties:** lists order `created_at` then insertion sequence (the clock is frozen, so pure `created_at` would be non-deterministic); ledger lists order `posted_at`, `created_at`, sequence; `excluded_channel_codes` includes SUSPENDED channels in `created_at` order; channel ranking never consults `id`.
19. **Cross-field `ERR_INVALID_REQUEST` constraints:** segment `code` must be uppercase and `hard > soft` limit; market `code` matches `^[A-Z]{3,5}$`; program `max_holding_days > min_holding_days` and RISK ⇒ `repurchase_guarantee_pct == 0`.

## Step 5: Generate unit tests — 2026-09-06T00:03:34.170787142Z

Step 5 is complete. Final verification: `pyflakes` clean across all 26 files, `compileall` clean, citation audit 0 problems (321 verbatim PRD quotes checked), design-tag audit 0 problems.

## Deliverable summary

**Stage 1 — `test_helpers/` (task root, 3746 lines)**
| file | lines |
|---|---|
| `__init__.py` | 238 |
| `api_client.py` | 693 |
| `api_errors.py` | 197 |
| `assertions.py` | 498 |
| `constants.py` | 179 |
| `factories.py` | 437 |
| `fixtures.py` | 1055 |
| `test_users.py` | 99 |
| `types.py` | 449 |

**Stage 2 — `test_suite/` (7239 lines, 133 tests)**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 50 | — |
| `test_01_valuation_variants.py` | 359 | 6 |
| `test_02_money_formulas.py` | 287 | 6 |
| `test_03_state_machine_shapes.py` | 290 | 7 |
| `test_04_transitive_cascades.py` | 365 | 7 |
| `test_05_validation_precedence.py` | 315 | 6 |
| `test_06_boundaries.py` | 327 | 8 |
| `test_07_cross_entity_gates.py` | 366 | 6 |
| `test_08_interval_collisions.py` | 377 | 6 |
| `test_09_compensating_actions.py` | 370 | 8 |
| `test_10_entities.py` | 638 | 13 |
| `test_11_state_machines.py` | 386 | 8 |
| `test_12_calculations.py` | 389 | 8 |
| `test_13_validations.py` | 243 | 5 |
| `test_14_endpoints.py` | 276 | 5 |
| `test_15_errors.py` | 1330 | 22 |
| `test_16_rbac.py` | 473 | 7 |
| `test_17_concurrency_and_consistency.py` | 299 | 5 |

**Instances translated: 68 of 68 non-stub instances. Skipped: none.**
- Queue A (§1.8 Difficulty): 18 of 18 instances → 60 tests (every instance ≥ 2 tests, per the coverage floor).
- Queue B (§1.9 Corner): 50 of 50 non-stub instances → 73 tests. By section: entities 13/13 → 13, state_machines 8/8 → 8, calculations 4/4 → 8, validations 4/4 → 5, endpoints 4/4 → 5, errors 10/10 → 22, rbac 5/5 → 7, cross_cutting_complexity_layers 1/1 → 3, consistency_model 1/1 → 2.
- The 24 `excluded_because:` stub entries were deliberately not translated; the tag audit verifies no test names one.

**Audit results**
- Every test carries exactly one `Design:` line as the last line of its docstring; every tag resolves to a real non-stub instance.
- 321 PRD citations, all verified verbatim against `workspace/PRD.md` with the cited section number matching the section the text actually lives in.
- No occurrence of the word "scaffold" in `test_helpers/` or `test_suite/`; `pyflakes` reports no unused imports or undefined names.

**Where the PRD overruled the design index** (PRD treated as authoritative; nothing was weakened):
1. corner/errors instance 4 sends `window_start`/`window_end` on REGISTRATION and LICENSING tasks, which PRD §3.4 makes an `ERR_INVALID_REQUEST` schema violation — the zero-length-window probe was moved onto a PREPARATION task after completing REGISTRATION and LICENSING.
2. corner/errors instance 8's asserted `net_proceeds_cents` only reconciles once the reconditioning branch has run, so the floor-price test authorizes and completes reconditioning before recording the sale.
3. corner/consistency_model asserts one `PREP_COST` ledger row, but PRD §3.4 posts a `PREP_COST` line on every task completion — the test asserts all three rows (14000, 9000, 21000) and pins the 21000 row by `source_entity_id`.

Both output directories are at the task root (nothing under `workspace/`); `workspace/implementation/` and `worklog.md` were never read or written. Scratch artifacts (`cite_audit.py`, `tag_audit.py`, `corner2.txt`) remain in `.scratch/step5/` for Step 7.

## Step 7: Run tests and iterate — 2026-09-06T00:25:05.718120374Z

All 8 rounds pass. Done.

## Summary

**Iterations run:** 2 (iteration 1 sweep: 130/133 in all 8 rounds, 3 deterministic failures; iteration 2 sweep after fixes: 131/131 in all 8 rounds).

The whole failure set was one cluster in `test_suite/test_08_interval_collisions.py::TestPrepBayBufferedAdjacency`, all three failing identically in all 8 rounds with `Expected response_type 'error', got 'object'` — i.e. the server accepted a prep-bay window the tests expected to be refused with `ERR_PREP_BAY_CONFLICT`.

**Root cause (STEP 1b, unique-derivability collapse).** PRD §3.4 states the bay rule as: *"**Bay collision** works on the closed interval from `window_start` to `window_end`, expanded outward by sixty minutes at each end to allow for turnaround; if that expanded interval shares any instant with the interval of any other `PENDING` or `COMPLETED` `PREPARATION` task on the same `market_id` and the same `bay_code`, the request is refused with `ERR_PREP_BAY_CONFLICT` (HTTP 409)."* That sentence admits two PRD-faithful implementations, and the three tests sat exactly on the instant where they diverge (incumbent 08:00–10:00, newcomer 12:00–14:00, a 120-minute gap):
- Reader A (what `routes_task.py::_check_bay_conflict` does): expand the **new** task's interval by 60 min per side and compare it to each other task's own interval — *"that expanded interval"* vs *"the interval of any other ... task"* is read as a deliberate contrast. Required separation > 60 min, so the 120-minute gap is accepted. §3.6's cross-reference (*"a closed interval plus a buffer makes touching endpoints a conflict"*) still holds, since a newcomer starting at 11:00 would collide.
- Reader B (what the tests assert): expand **both** intervals, so the buffered halos meet at 11:00 and collide. Required separation > 120 min.

PRD never states an outcome for the 120-minute-gap case, and notably uses *"the **corresponding** interval"* in the analogous transfer-overlap rule (§3.6) where it wants symmetric construction — a word it omits here. Both readings are defensible, so the boundary is not uniquely derivable. Per the cardinal rule the tests go rather than the implementation changing.

**Tests deleted (2):**
- `test_buffered_intervals_that_meet_at_one_instant_are_a_conflict` — UNIQUE-DERIVABILITY COLLAPSE (boundary not determined by PRD prose: the sentence does not say the *other* task's interval is also expanded). Generated from scaffold rule `Difficulty/resource_temporal_overlap/prep_bay_buffered_closed_interval_adjacency_forbidden`, whose `distinguishing_aspect` asserts the double-expansion reading that only `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, not PRD.md, states.
- `test_one_minute_of_separation_is_the_whole_difference` — same collapse; the entire 12:00-vs-12:01 distinction exists only under the double-expansion reading. Same scaffold rule.

**Fixes applied to `test_suite/` (1):** `test_08_interval_collisions.py::TestPrepBayBufferedAdjacency::test_the_collision_is_per_bay_and_the_daily_count_is_not_the_cause` — this test's asserted rule (bay collision is scoped *"on the same `market_id` and the same `bay_code`"*, and daily capacity is a separate aggregate check) **is** PRD-verbatim and uniquely derivable; only its chosen request window landed in the ambiguous region. Moved the colliding attempt from 12:00–14:00 to 09:00–11:00, which genuinely overlaps the incumbent's raw 08:00–10:00 occupation and is therefore a conflict under either reading of the buffer clause. All assertions kept at full strength — the exact `ERR_PREP_BAY_CONFLICT` check, the `!= ERR_PREP_CAPACITY_EXCEEDED` check, the B2-accepted check and the market-wide count of 2 are unchanged; no skip, no xfail, no downgrade to an HTTP-status assertion.

**Fixes applied to `test_helpers/`:** none — no fixture, factory or role-header bug was implicated.

**Fixes applied to `implementation/`:** none. All implementation files retain their pre-existing mtimes (22:22–22:46); the PRD-faithful bay-collision check was left intact rather than widened to satisfy a non-derivable assertion.

**Final sweep evidence** (test count 131 after the 2 deletions):

| round | passed / total |
|---|---|
| 1 | 131 / 131 |
| 2 | 131 / 131 |
| 3 | 131 / 131 |
| 4 | 131 / 131 |
| 5 | 131 / 131 |
| 6 | 131 / 131 |
| 7 | 131 / 131 |
| 8 | 131 / 131 |

Zero failures in the union across all 8 parallel rounds, so no flakiness escaped. `worklog.md` was not touched (mtime 00:03, predating this step) and no scratch files were left behind.

**Orchestrator verification (post-subagent):** independently read all 8 `workspace/implementation/results.$i.json` — every round reports `passed == total == 131`, and `workspace/SWEEP_DONE` is present, so the sweep genuinely ran to completion rather than being reported clean without artifacts. Step 8 is therefore NOT skipped: the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes, and this run had 2 deletions plus 1 `test_suite/` fix.

## Step 8: Finalize PRD — 2026-09-06T00:34:13.835951780Z

Done. One edit, in §3.4.

## Line counts
- PRD.md: 505 lines / 113,134 bytes
- PRD_FINALIZED.md: 505 lines / 113,753 bytes
- Line delta: 0 (0.0%); byte delta +619 (+0.55%). Verified lines 1–250 and 252–505 are byte-identical to PRD.md, and PRD_FINALIZED.md ends on `| ERR_PROCEEDS_BELOW_FLOOR | 422 |`, the last row of the §5 error table.

## Change
- **§3.4 (Task scheduling rules, PRD line 251) — revise — pinned the prep-bay buffer as one-sided**: the new task's closed `window_start`–`window_end` interval is the only one expanded by sixty minutes per end; each already-stored `PENDING`/`COMPLETED` `PREPARATION` task is compared on its own **unexpanded** interval. Added the derived boundary: a nearer-edge separation of exactly sixty minutes still collides, a gap strictly greater than sixty minutes clears the check. Kept the existing "adjacency is a conflict" sentence verbatim. — `implementation/routes_task.py:100-117` (`_check_bay_conflict`, buffer applied at lines 102–103 only, compared at line 113 against raw `other_start`/`other_end` from lines 109–110).

This is the exact PRD-silence Step 7 identified: the old wording ("that expanded interval" vs "the interval of any other ... task") admitted both the single- and double-expansion readings, and the two deleted tests plus the retimed third all sat on the 120-minute-gap instant where the readings diverge. Implementation is single-expansion, so PRD_FINALIZED now says so.

## Pre-edit search log

**Edit 1 — §3.4 bay-collision buffer**
- (a) Subject: construction of the prep-bay collision intervals — which side(s) the 60-minute turnaround buffer is applied to, and the resulting minimum-separation boundary.
- (b) Impl paths enumerated (grepped `PREP_BAY_BUFFER|BUFFER|window_start|window_end|_check_bay_conflict` across all non-`__pycache__` `.py`, then read each hit):
  - `implementation/calc.py:40` — `PREP_BAY_BUFFER_MINUTES = 60`, the sole definition; no other consumer.
  - `implementation/routes_task.py:21` — the only `timedelta` built from it.
  - `implementation/routes_task.py:100-117` `_check_bay_conflict` — the only collision comparison; single callsite at line 81. Confirmed the scope filter (line 107) is `market_id` + `bay_code`, matching PRD verbatim, and the status/type filter (line 105) is `PREPARATION` × `PENDING|COMPLETED`. Verified algebraically that the two-sided test at line 113 yields "conflict iff gap ≤ 60 min" for both orderings (new window before or after the stored one), so the boundary sentence is symmetric and universally true, and that touching raw endpoints (gap = 0) still conflicts, preserving the pre-existing adjacency sentence and the §3.6 cross-reference at PRD line 279 ("a closed interval plus a buffer makes touching endpoints a conflict") without editing either.
  - `implementation/routes_task.py:120-138` `_check_daily_capacity` — reads only `window_start.date()`, no buffer; left undescribed by the edit so the aggregate rule's prose stays untouched.
  - `implementation/routes_task.py:41-50, 84-97` — window fields are set once at creation; `_resolve`/`complete`/`waive` (lines 162-204) never mutate `window_start`/`window_end`, and there is **no** reschedule/update endpoint, so no second path constructs a bay interval.
  - `implementation/serialize.py:48` — windows are echoed verbatim in the task projection; no normalization that the wording could contradict.
  - `implementation/routes_order.py` transfer-overlap rule was left alone: it is a half-open interval with no buffer, described separately in §3.6.
- (c) Wording adjustments made to stay consistent with all enumerated paths: (i) scoped the expansion to "the new task's" interval and stored ones to "already-stored", so the sentence describes the single creation-time callsite rather than implying a stored task's persisted window is rewritten; (ii) phrased the boundary as "nearer edge ... exactly sixty minutes away" instead of naming a start-side or end-side gap, since the impl's condition is direction-symmetric; (iii) said "the effective separation the rule demands is sixty minutes" as a consequence clause rather than restating the rule as a separation threshold, so the primitive definition (interval intersection) remains the normative one for nested and overlapping windows, which a bare gap-threshold phrasing would not cover.

**Orchestrator verification (post-subagent):** `cmp` confirms PRD_FINALIZED.md is NOT byte-identical to PRD.md; the diff is exactly one revised paragraph at line 251 (§3.4) and nothing else; the file still ends on the last row of the §5 error table.

## Step 9: Complete PRD — 2026-09-06T01:11:14.30160573Z

Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy, so no pass could clobber an earlier pass's edits). Partition: pass 1 = `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `filters.py`, `serialize.py`, `routes_config.py`, `routes_ledger.py`; pass 2 = `routes_policy.py`, `routes_plan.py`, `routes_vehicle.py`, `routes_task.py`, `calc.py`; pass 3 = `routes_order.py`, `routes_damage.py`, `routes_consignment.py`, `cascade.py`. All 19 implementation modules were covered exactly once.

**Totals: 46 edits — 40 ambiguity-pins, 6 mismatch-revisions.** `PRD_FINALIZED.md` 113,624 chars → `PRD_COMPLETED.md` 126,149 chars (+12,525 chars, +11.0%); line count unchanged at 505 (all edits are in-paragraph inserts/revisions, no new sections, no new lines).

### PASS 1 — global semantics, config, ledger (20 edits: 19 ambiguity-pins, 1 mismatch-revision; 118,941 chars at exit)

- §2.1 — revise — ambiguity — a whitespace-only header counts as absent, not merely an empty one — `auth.py:29`
- §2.1 — insert — ambiguity — MarketOperator scope is plain string equality; the server never checks the quoted id names an existing Market, so an unknown id yields the 403 not a 404 — `auth.py:44-50` (`acting_market` is dead code)
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-alphanumeric characters — `store.py:71-73`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, so it is constant until the clock moves — `envelope.py:15-19`
- §2.2 — insert — ambiguity — every declared field is always present; unassigned fields are null rather than omitted — `serialize.py:77-83`
- §2.3 — revise — **mismatch** — supplied `limit` ceiling is 200, not 100 (the paragraph contradicted itself); plus non-integer values are `ERR_INVALID_PAGINATION`, an empty value equals omission, and an over-long offset yields an empty page — `envelope.py:72-101`
- §2.3 — insert — ambiguity — every ordering falls back to server insertion sequence as final tie-break (the frozen clock makes `created_at` ties routine); ledger listings add it after `posted_at`, `created_at` — `store.py:168-172`, `routes_ledger.py:33`
- §2.3 — insert — ambiguity — filters are exact-match, applied before ordering and paging; an unmatched/unparseable filter value yields an empty page rather than an error; undeclared query params are ignored — `filters.py:9-46`
- §2.4 — insert — ambiguity — both clock endpoints answer with a single `current_utc` field echoing the supplied instant **verbatim** (not normalised to three fractional digits) — `routes_config.py:26-38`
- §2.6 — insert — ambiguity — percentages with more than four decimals are neither rejected nor rounded; stored, echoed and computed at full supplied precision — `validate.py:70-86`, `store.py:116-124`
- §2.9 (body FK ¶) — insert — ambiguity — a body FK that is null/blank/non-string is not a rank-6 404; it falls to rank 7 — `validate.py:171-180`
- §2.9 (item 7) — revise — ambiguity — integer fields must be JSON integers (whole-valued float / numeric string / bool refused), percentages accept any number; instants accept 0-9 fractional digits and `Z` or `±hh:mm` (normalised for comparison, echoed verbatim); explicit null counts as absent; missing/unparseable body treated as `{}`, non-object body is `ERR_INVALID_REQUEST` — `validate.py:13-121`, `store.py:20-110`
- §2.12 — insert — ambiguity — market census is derived at read time, and a census change is not a market mutation: a Market's `updated_at`/`version` move only on suspend — `serialize.py:86-89`, `routes_config.py:95-103`
- §2.12 — insert — ambiguity — an ordinary vehicle read never fails for want of a policy: `net_book_value_cents` is null for a RISK unit whose segment has no ACTIVE policy; PROGRAM units still report the guarantee — `serialize.py:124-128`, `calc.py:239-242`
- §3.1 — insert — ambiguity — re-suspending a SUSPENDED market → `ERR_MARKET_SUSPENDED` (422) — `routes_config.py:99-100`
- §3.1 — revise — ambiguity — `program_year` is an integer greater than zero, otherwise unconstrained (no 2020 floor, unlike `plan_year`) — `routes_config.py:171`
- §3.1 — insert — ambiguity — re-closing a CLOSED program → `ERR_PROGRAM_CLOSED` (409) — `routes_config.py:231-232`
- §3.1 — insert — ambiguity — re-suspending a SUSPENDED channel → `ERR_INVALID_REQUEST` (422), as no channel-state code exists — `routes_config.py:298-300`
- §3.4 — insert — ambiguity — the omit-for-wrong-type rule governs the request only; a task representation always carries all three prep keys, null on REGISTRATION/LICENSING — `serialize.py:46-49`, `routes_task.py:45-50`
- §4 / §5 — insert — ambiguity — trailing slash equivalence; and the three non-catalogue codes `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), ungated on auth headers — `app.py:28,52-64`, `errors.py:86-89`

Pass 1 found already fully pinned: `errors.py` (all 67 catalogue codes and statuses match §5 exactly, verified programmatically) and `routes_ledger.py`. Deliberately not edited: §2.6's "truncated toward zero" wording, although `store.floor_div` floors toward negative infinity — both call sites divide non-negative revenue sums (`revenue_cents_delta` is validated `>= 0`), so the difference is unobservable and revising it would have risked a false universal.

### PASS 2 — policy, plan, vehicle, task, calculations (11 edits: 9 ambiguity-pins, 2 mismatch-revisions; 121,626 chars at exit)

- §2.9 (body-FK fall-through) — revise — **mismatch** — PASS 1's sentence claimed an optional body FK like `supersedes_policy_id` is "treated exactly as if omitted" for null/number/blank-string alike; impl only does that for JSON null and re-runs `s_id` on anything else, yielding `ERR_INVALID_REQUEST`. Narrowed (refines, does not contradict, PASS 1's clause) — `routes_policy.py:33-34` + `validate.py:177-180`
- §3.3 (allocation payload) — insert — ambiguity — an omitted or null `unit_count` also reports `ERR_INVALID_UNIT_COUNT`, not the generic schema code — `routes_plan.py:123-125`, `validate.py:50-51`
- §3.3 (posture gate) — insert — ambiguity — the gating posture is derived *before* the new allocation is applied, and `OPEN` is not size-gated at all, so one allocation can vault a plan straight into `FROZEN` — `routes_plan.py:146-158`, `calc.py:132-138`
- §3.3 (allocation cancel) — insert — ambiguity — cancellability is tested before the plan's `LOCKED` state, so `ERR_ALLOCATION_NOT_CANCELLABLE` outranks `ERR_PLAN_NOT_LOCKED` — `routes_plan.py:200-207`
- §3.4 (vehicle mint) — insert — ambiguity — `current_market_id` is not a §2.9 rank-6 body FK: it resolves after the `vin` schema check, an unknown id gives `ERR_MARKET_NOT_FOUND`, and the market's `status` is not examined at minting — `routes_vehicle.py:26-28`
- §3.4 (vehicle mint) — revise — **mismatch** — the unit ceiling counted "the allocation's non-cancelled vehicles"; impl counts **every** vehicle ever minted regardless of `fleet_status`, `TOTAL_LOSS` included, so a destroyed car never frees its slot — `routes_vehicle.py:40`, `calc.py:52-53`
- §3.4 (vehicle mint) — insert — ambiguity — `created_vehicle_count` is derived at read time, so minting neither refreshes the allocation's `updated_at` nor bumps its `version`, and leaves the plan untouched — `routes_vehicle.py:46-77`, `serialize.py:117-121`
- §3.4 (task completion) — insert — ambiguity — the milestone stamp refreshes the vehicle's `updated_at` but does **not** increment the vehicle's `version`; only promotion does — `cascade.py:35-40`
- §3.5 (usage posting) — insert — ambiguity — all four payload fields are required JSON integers of zero or more; a negative delta is `ERR_INVALID_REQUEST`, a zero delta is accepted — `routes_vehicle.py:148-151`
- §3.5 (holding clock) — insert — ambiguity — `holding_days` is floored at zero, so a clock repositioned back before `in_service_at` reports 0, not a negative count — `calc.py:174-176`
- §3.8 (channel ranking) — insert — ambiguity — `excluded_channel_codes` is unranked: rejects come back in ascending `created_at` with the §2.3 insertion sequence as tie-break — `calc.py:417-419, 448`

Pass 2 found already fully pinned: `routes_policy.py` (draft bounds, the five activation conditions in impl order, the `ACTIVE → SUPERSEDED` double version bump), `routes_plan.py` (the `expected_plan_version` → `PLAN_NOT_LOCKED` → `PROGRAM_CLOSED` → posture ladder, compound status transitions, all four list filter sets), `routes_vehicle.py` (vin rules, the four in-fleet gates and their order, odometer regression, ledger sort key), `routes_task.py` (conditional prep-field requirement, the one-sided 60-minute bay buffer incl. the "exactly 60 minutes still collides" consequence, the fiscal asymmetry, three-type promotion), and `calc.py` — all six calculations verified formula-by-formula including every rounding site, the surcharge-tier boundaries, the integer cross-multiplication total-loss test, the recovery waterfall and the full recommendation scoring; **§3.9 plan performance needed no edit at all.**

### PASS 3 — redistribution, damage, remarketing, cascades (15 edits: 12 ambiguity-pins, 3 mismatch-revisions; 126,149 chars at exit)

- §3.6 (draft) — revise — **mismatch** — the four draft checks were narrated in an order that is not the firing order; now pinned as fleet state → window shape → transfer overlap → same market → payback gate — `routes_order.py:34-73`
- §3.6 (draft) — insert — ambiguity — neither origin nor destination market `status` is examined at draft time; the destination-suspension refusal first bites at authorize and again at depart — `routes_order.py:34-73` vs `:179,203`
- §3.6 (reject) — insert — ambiguity — `rejection_reason` is a required non-empty string (whitespace-only rejected), validated ahead of the order's state check — `routes_order.py:155` / `validate.py:30-44`
- §3.6 (receive) — insert — ambiguity — `actual_transport_cost_cents` and `odometer_km` are required integers ≥ 0, and the anti-regression check follows both state gates — `routes_order.py:222-236`
- §3.7 (report damage) — insert — ambiguity — fleet-status gate precedes the condition gate, and both precede the missing-policy refusal raised while freezing the baseline — `routes_damage.py:32-43`
- §3.7 (settle-recovery) — insert — ambiguity — `recovered_cents` is a required integer ≥ 0; 0 is legal and runs the waterfall over zero — `routes_damage.py:151`
- §3.7 (write-off) — revise — **mismatch** — PRD required `total_loss_required` false only on the `REPORTED` path; impl requires it on both, matching §3.7's earlier universal claim — `routes_damage.py:194-203`
- §3.7 (declare-total-loss) — insert — ambiguity — `salvage_proceeds_cents` required integer ≥ 0, and gate order pinned: event status → vehicle fleet status → ratio-test requirement — `routes_damage.py:222-238`
- §3.7 (total-loss cascade) — insert — ambiguity — the downstream order/consignment hop is reached from `IN_SERVICE`, `IN_TRANSIT`, `HELD_FOR_SALE` only, never from `IN_FLEETING` (which returns after waiving tasks) or `ON_ORDER` — `cascade.py:121-130`
- §3.8 (consign) — insert — **mismatch** — the five gates' evaluation order pinned (fleet → open damage → condition → min-holding → eligibility → ACTIVE-policy → mileage band), including the deliberate one-place departure from §2.9: open damage outranks the condition guard — `routes_consignment.py:46-86`
- §3.8 (consign) — revise — ambiguity — corrected a bogus "priority 16" reference and pinned that the min-holding gate is reached only for an `ACTIVE` channel on a `PROGRAM`-type program; otherwise `ERR_CHANNEL_NOT_ELIGIBLE` — `routes_consignment.py:66-78`
- §3.8 (authorize-recondition) — insert — ambiguity — `recondition_authorized_cents` required integer ≥ 0; condition gate sits after the `DRAFT` check and before the cap check — `routes_consignment.py:144-162`
- §3.8 (complete-recondition) — insert — ambiguity — `recondition_actual_cents` required integer ≥ 0; consignment `RECONDITION_PENDING` and vehicle condition `RECONDITIONING` both outrank the overrun test, making the booking single-shot — `routes_consignment.py:179-195`
- §3.8 (publish from RECONDITION_PENDING) — insert — ambiguity — the open-damage rule guards both publish branches; no condition gate on this branch — `routes_consignment.py:223-245`
- §3.8 (publish from DRAFT) — revise — ambiguity — open-damage check precedes the condition check on this branch too — `routes_consignment.py:235-245`
- §3.8 (record-sale) — insert — ambiguity — `gross_proceeds_cents` required integer ≥ 0 — `routes_consignment.py:261`

Pass 3 found already fully pinned: `routes_order.py` (propose/re-propose with `revision_count` ≤ 3, authorize's state → SoD → destination-`ACTIVE` order, depart/receive side effects and ledger line, cancel from all five non-terminal states with the IN_TRANSIT compensation, the frozen estimate, the 45-day payback ceiling, the half-open `[depart, receive)` overlap interval), `routes_damage.py` (report-time freeze of `net_book_value_at_report_cents`, the integer ratio test, `revise-estimate` recomputing against the unchanged baseline, branch A/B mutual exclusion, the three-bucket waterfall, write-off zeroing, the two total-loss ledger lines), `routes_consignment.py` (`floor_price_cents` freeze, hold-time census decrement, the 7.5% loading, `complete-recondition` leaving status at `RECONDITION_PENDING`, publish-from-DRAFT on a `recondition_required` channel refused with `ERR_CONSIGNMENT_INVALID_STATE`, the three independently rounded sale lines, the four settlement ledger rows plus SoD, withdrawal's `RECONDITION_REVERSAL` and condition reset) and `cascade.py` (`post_ledger` shape, the four-hop in-fleeting chain, total-loss withdrawal posting no `RECONDITION_REVERSAL`).

### Orchestrator verification (post-passes)

- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (nor to `PRD.md`) — the "scan never ran" failure mode is excluded. 41 lines differ from `PRD_FINALIZED.md`; 505 lines and all 5 `##` sections retained; file still ends on the last row of the §5 error table.
- Independent re-check against `SCAFFOLD.yaml`: all 67 declared error ids and all 71 declared endpoint paths are still present in `PRD_COMPLETED.md` — no section was dropped by the three-pass editing.
- Step 7's green sweep remains valid: neither Step 8 nor any Step 9 pass wrote to `implementation/`, `test_suite/` or `test_helpers/`; the 8 `results.$i.json` files in `workspace/implementation/` all record 131/131.

Pipeline complete.

