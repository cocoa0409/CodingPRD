# Worklog — task_2969_nitrogen_fertilizer_production

## Step 1: Create task directory — 2026-09-05T23:15:03.687Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production` and `workspace/` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-06T00:35:30.625531220Z

All three Step-2 deliverables are complete, valid YAML, and the scaffold lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production/`)
- `SCAFFOLD.yaml` — 2836 lines. Top-level keys only `scenario … roles`; neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1871 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3186 lines, single key `scaffold_corner_design`.

**SCAFFOLD.yaml inventory** — 13 entities, 71 endpoints, 10 state machines, 2 concurrency rules, 10 calculations, 28 prioritised validations, 43 error codes, 6 roles. `api_prefix: /nitrogen-ops`; archetypes `quota_allocation` / `compliance_audit`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; topology `flat`; shape `branching`; `role_model: segregation_of_duties`; consistency `immediate`; logical clock defaults to `2026-08-01T00:00:00Z`.

**§1.8 — 9 rule ids / 24 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.

**§1.9 — 9 sections / 78 instances** (56 live test recipes + 22 `excluded_because` stubs): entities 12, state_machines 13, calculations 15, validations 11, endpoints 6, errors 9, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. All 78 names are unique across the union of both design files, every stub cites a difficulty instance that exists by name, and every one of the 43 error codes is triggerable somewhere (the eleven remaining `*_NOT_FOUND` codes are covered by one sweep instance that hits eleven collections with the same unknown UUID).

**Lint verdict** (`scaffold_lint.py`, pasted verbatim):
```
Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  639

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Adjudications**
1. `ERR_TASK_PREDECESSOR_NOT_DONE` (priority 24) was unreachable: priority 9 `ERR_INVALID_STATE` applies to all action endpoints and a PENDING task has no declared PENDING→DONE edge. Added a scope note to validation 9's `check:` making priority 24 the sole reporter for a PENDING task inside an IN_PROGRESS turnaround.
2. `ERR_PLANT_FROZEN` is priority **10**, not 12 (12 is `ERR_SEGREGATION_OF_DUTIES`) — corrected a §1.9 `grounds` citation after auditing every `validations[priority=N]` reference in the corner file against §1.4.
3. `psm_program_status: DUE` does **not** degrade the posture (only `OVERDUE` does, per `plant_operating_posture`); the RBAC exclusive-write fixture was changed to `OVERDUE` so its RESTRICTED assertion holds.
4. Dropped a `grounds` reference to a non-existent `calculations.order_ammonia_requirement` (the reserve ammonia math lives in the endpoint's side effects) in favour of `entities.ProductionOrder.fields.allocated_ammonia_tons`.
5. Removed the phrase "run in parallel" from `turnaround_task_schedule.input_set` — it described graph slack, not request concurrency, but the wording is on the forbidden-vocabulary list and could mislead the test generator. Re-ran the lint after the edit; still clean.
6. Where a §1.9 corner was already asserted by a §1.8 instance I emitted a stub rather than a duplicate recipe; the two priority-pair errors (`ERR_RUN_NOT_COMPLETED`/`ERR_PRODUCED_EXCEEDS_RESERVED`, `ERR_SECURITY_CLASS_INSUFFICIENT`/`ERR_PRODUCT_MISMATCH`) are documented once, in `validations`, rather than repeated in `errors`.

Scratch dir `.scratch/step2` was removed (parent `.scratch` left in place); `worklog.md` was not touched.

Orchestrator verification: all three files present and non-empty; `grep "harder than expert"` over all three returned no hits, so the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-06T00:35:35.643450066Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T00:49:02.545609529Z

Step 4 complete. `workspace/PRD.md` — **533 lines / 108,212 bytes**, ends at a real section boundary (final row of the §5 error table). No `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` and no sibling task dir was opened. `worklog.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/` untouched; `.scratch/step4` removed.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
```
entities[].fields: 116 required, 116 present, 0 missing
request_body:       76 required,  76 present, 0 missing
query_params:       22 required,  22 present, 0 missing
```

**Contract 2 — Rule Coverage: PASS**
```
error ids not mentioned in §1-§3: []   (43/43)
state values missing from PRD:    []   (all 10 machines, 58 transitions)
enum values missing:              []
```

**Contract 3 — §3 Path Purity: PASS**
```
§3 backtick tokens scanned: 1010; violations: []
(no `/`-leading tokens, no bare HTTP methods, no method+path combos)
```

## Section headings (ordered)

`# Nitrogen Fertilizer Production API — Product Requirements Document` · `## 1. Introduction` · `## 2. Global Specifications & System-Wide Principles` · `### 2.1. User and Role-Based Access Control` · `### 2.2. API Response Structure` (`#### Standard Success Response Format`, `#### Standard Error Response Format`) · `### 2.3. Pagination` · `### 2.4. Resource Identity, Version Semantics and the Logical Clock` · `### 2.5. Flat Topology, Path Resolution and List Filters` · `### 2.6. Rounding, Precision and Tonnage Discipline` · `### 2.7. Stale-Version Guards on Allocation and Booking` · `### 2.8. Operating Posture: The Site-Level Gate` · `### 2.9. Segregation of Duties Across the Signature Chain` · `### 2.10. Business Code Uniqueness Scopes` · `### 2.11. The Order of Rejection` · `### 2.12. Cascade Discipline and Deterministic Sweep Order` · `## 3. Business Logic & Workflows` · `### 3.1. Commissioning the Site: Plants, Trains and Catalyst Charges` · `### 3.2. Catalyst Activity, Regeneration and the Derate Cascade` · `### 3.3. The Gas Hedge Book and the Feedstock Blend` · `### 3.4. Ammonia Campaigns: Schedule, Approve, Run, Settle, Restate` (`#### Feedstock unit cost: one waterfall, two variants`, `#### Settlement`, `#### The ammonia pool and its shifting basis`, `#### Aborting and reopening`) · `### 3.5. The Product Slate and the Order Book` · `### 3.6. Storage Assets, Production into Storage, and the Seasonal Set-Aside` · `### 3.7. Moving Product by Rail, Barge and Truck` · `### 3.8. Customer Quoting on a Hedged or Spot Basis` · `### 3.9. Turnaround Planning, Safety Review and the Outage Cascade` (`#### The outage cascade`) · `### 3.10. Emissions Monitoring, Permit Standing and Posture Re-Derivation` · `## 4. Endpoint Definitions` · `## 5. Error Code Catalogue`

## Coverage

13 entities · **71 endpoint rows** in §4 (verified count) · 10 state machines / 58 transitions · 10 calculations (incl. both dual-variant pairs: `run_ammonia_unit_cost` PROVISIONAL/FINAL, `catalyst_activity_pct` CALENDAR/SEVERITY_ADJUSTED) · 28 priority-ordered validations rendered as an explicit rejection ladder in §2.11 · **43 error rows** in §5 (verified count) · 6 roles (5 opaque + `TerminalOperator` entity-backed to `StorageAsset`) · 2 OCC rules (`expected_run_version`, `expected_origin_asset_version`) · §2.2 emitted byte-verbatim from the fixed template.

## Adjudications (scaffold self-contradictions resolved)

1. **Posture-driven quote withdrawal reason.** `state_machines[Plant]` names `POSTURE_RESTRICTED` (regulated lines only, `issued_at` ASC then `created_at` ASC) and `POSTURE_FROZEN`; three endpoint definitions (permit-status, psm-program-status, emissions-readings) instead all name `PLANT_POSTURE_DEGRADED` for **every** ISSUED quote in `created_at` ASC. Resolved to the endpoint-level rule (3 consistent mentions vs 2, and it leaves the psm-program-status→RESTRICTED path unambiguous). FROZEN-only extra hops retained: revert APPROVED runs → PLANNED clearing `provisional_unit_cost_usd_per_ton`; release RESERVED orders with `release_reason` = `PLANT_FROZEN`.
2. **Train availability for campaign operations.** Validation priority 14 references a `DOWN` state absent from the `ReformerTrain` enum `{IDLE, RUNNING, DERATED, DOWN_FOR_TURNAROUND}`, while both approve and start preconditions say `{IDLE, RUNNING}`. Resolved to `{IDLE, RUNNING}` for create/approve/start; `DERATED` and `DOWN_FOR_TURNAROUND` rejected with `ERR_TRAIN_UNAVAILABLE`. (Corroborated: no `DERATED → RUNNING` arc exists for a run start, and a DERATED train's charge is SPENT so priority 13 would reject anyway.)
3. **Destination-capacity check at reserve time.** The `UNALLOCATED → RESERVED` precondition includes a destination capacity ceiling but validation priority 26's `applies_to` omits reserve, nominating no error. Assigned `ERR_STORAGE_CAPACITY_EXCEEDED` (409).
4. **Business-code uniqueness scopes.** For `run_code`, `order_code`, `shipment_code` and `quote_code` the entity field constraints say per-`train_id` / per-`run_id` / per-`origin_asset_id` / per-`plant_id`, while validation priority 8 and `ERR_DUPLICATE_CODE` say per-plant (`run_code`) and global (the other three). Resolved uniformly to the validation-table + error-catalogue side: `run_code` unique per plant; `product_code`, `order_code`, `shipment_code`, `quote_code` globally unique.

Also noted: `ERR_EMISSIONS_READING_NOT_FOUND` exists in `errors[]` but is missing from validation priority 5/6's error lists; it is carried in §2.5's 404-family list and used in §3.10.

Orchestrator verification (truncation guard): `wc -l` = 533; `grep -n '^#'` shows all 31 headings through `## 5. Error Code Catalogue`; `tail` ends on the last of 43 error rows (`ERR_PRODUCED_EXCEEDS_RESERVED | 409`), i.e. a real section boundary, not mid-sentence. No regeneration needed. Leak check for "harder than expert"/"scaffold"/"test_recipe" over PRD.md: no hits.

## Step 5: Generate unit tests — 2026-09-06T01:50:42.78400004Z

Step 5 is complete. Both directories are at the task root; nothing was written under `workspace/`.

## Deliverables

`test_helpers/` — 9 files, 2379 lines
`__init__.py` 23 · `api_client.py` 658 · `api_errors.py` 137 · `assertions.py` 249 · `constants.py` 135 · `factories.py` 360 · `fixtures.py` 607 · `test_users.py` 132 · `types.py` 78

`test_suite/` — 16 files, 6386 lines
`conftest.py` 23 · `test_01_run_costing_and_hedge_waterfall.py` 256 (8 tests) · `test_02_catalyst_activity_and_approval_gate.py` 345 (10) · `test_03_commercial_pricing_composition.py` 307 (9) · `test_04_turnaround_lifecycle_and_scheduling.py` 393 (12) · `test_05_order_allocation_and_clearance.py` 390 (9) · `test_06_outage_cascade_and_frozen_posture.py` 323 (8) · `test_07_boundaries_and_temporal_overlap.py` 375 (10) · `test_08_entity_representations.py` 455 (17) · `test_09_state_transitions.py` 593 (16) · `test_10_derived_calculations.py` 536 (15) · `test_11_input_validation.py` 501 (12) · `test_12_endpoint_contracts.py` 463 (11) · `test_13_error_contracts.py` 441 (13) · `test_14_role_access.py` 531 (10) · `test_15_concurrency_and_consistency.py` 454 (10)

## Coverage and verification

- **170 tests**, **170 `Design:` lines** — a machine check confirmed every test function carries exactly one tag; zero untagged, zero dual-tagged, zero tags pointing at an unknown instance or a stub.
- **Queue A (difficulty): 24 / 24 instances** translated across 9 rule_ids (test_01–test_07).
- **Queue B (corner): 56 / 56 non-stub instances** translated; the 22 stubs carrying `excluded_because:` were correctly left alone. Sections: entities 12 (test_08), state_machines 10 (test_09), calculations 7 (test_10), validations 6 (test_11), endpoints 4 (test_12), errors 7 (test_13), rbac 5 (test_14), cross_cutting_complexity_layers 4 + consistency_model 1 (test_15).
- `python3 -m compileall -q` clean over both dirs; `pytest --collect-only` collects **170 tests, 0 collection errors**.
- Audits: no reference to the scaffold or its section numbering anywhere in `test_suite/`; no `skip`/`xfail`/`TODO`/placeholder; all 43 distinct `ERR_*` ids used appear verbatim in `workspace/PRD.md`; no money/tonnage emitted as a JSON string; no date-only literal where the PRD declares an instant.
- `ls -d .../workspace/test_*` prints nothing. `.scratch/step5` removed; the sibling's `.scratch/step6` left intact. `worklog.md` untouched.

## Skipped instances

None on PRD-silence grounds. Every non-stub instance in both indices passed the two-condition filter and was translated; only individual sub-assertions were dropped (see adjudications b and f).

## Adjudications (6)

a. **`run_code` uniqueness** — PRD §2.10 says "unique per plant"; SCAFFOLD.yaml's entity table says per `train_id`. The PRD is the contract and governs.
b. **`hedge_lot_crud_triple...` asserts `data.limit == 50`** — PRD §2.3 fixes the default `limit` at 10. Not uniquely derivable; that one sub-assertion dropped (test_12). The rest of the instance is asserted.
c. **List-envelope shape** — the corner yaml writes `data.items[0]` / `data.total_count` / `data.limit` / `data.offset` / `data.has_more`; PRD §2.2–§2.3 put the array in `data` and pagination in `meta`. All list assertions go through `validate_paginated`.
d. **`product_line_is_immutable_with_no_version_and_no_updated_at`** carried a scaffold-meta assertion (§1.5 declares no PATCH/PUT/DELETE). Emitted as the observable absence of `version`/`updated_at` only, via `assert_immutable_entity`.
e. **`site_code: "VDG-1"` / `"YZC-1"` in the recipes is not PRD-legal** — §2.10 restricts `site_code` to 3–12 chars of uppercase A–Z and digits. Tests use hyphen-free codes from `unique_site_code()`; other business codes carry no charset rule.
f. **`run_reopen_is_rejected_once_one_of_its_orders_is_consumed`** asserts, after reopening PR-2, `allocation_status == RESERVED` and `unallocated_ammonia_tons == 4420.000`. PRD §3.5 states reopen releases every `RESERVED` order to `RELEASED` with `release_reason = RUN_REOPENED`, and the pool "returns to the full `target_ammonia_tons`". test_12 asserts the PRD values (RELEASED / `RUN_REOPENED` / 5000.000); the instance's primary claim is unaffected.

One precision note worth flagging to Step 7: `permit_limit_tons_30d` is not listed in any §2.6 precision class, so test_14 compares its value numerically rather than asserting a decimal width.

## Step 6: Generate implementation — 2026-09-06T01:50:42.90227413Z

Teardown, inventory and verification are complete. Final report:

## Files written (all under `workspace/implementation/`)

Foundation (12 modules, 1,509 lines):
`calc.py` 493 · `serialize.py` 292 · `cascade.py` 202 · `validate.py` 181 · `errors.py` 106 · `util.py` 105 · `app.py` 77 · `store.py` 75 · `envelope.py` 75 · `guards.py` 65 · `auth.py` 38 · `mutate.py` 22

Routes (14 modules + package init, 1,894 lines):
`turnarounds.py` 262 · `runs.py` 269 · `shipments.py` 184 · `orders.py` 177 · `quotes.py` 145 · `charges.py` 114 · `tasks.py` 99 · `plants.py` 91 · `assets.py` 77 · `emissions.py` 67 · `hedge_lots.py` 59 · `product_lines.py` 53 · `trains.py` 50 · `clock.py` 24 · `routes/__init__.py` 1

Plus `start.sh` (8 lines, chmod +x, reads `$PORT`, binds 0.0.0.0, `exec python3 app.py` in the foreground) and `requirements.txt` (`flask`). **3,412 lines total.** No `__pycache__` shipped; `.scratch/step6` removed (its empty parent left in place).

## Endpoint count: 71 / 71, exact

I diffed Flask's `url_map` against the PRD's endpoint table (rows parsed from PRD.md) by (method, path): **0 missing, 0 extra**. I also machine-diffed the authorized-role set of every route (static AST parse of each view's `actor([...])` call) against the table's Authorized Role(s) column: **0 mismatches across all 71**. Family tallies: plants 6, trains 3, charges 5, hedge lots 3, product lines 3, runs 7, orders 7, assets 4, shipments 7, quotes 7, turnarounds 10, tasks 4, emissions 3, clock 1.

## What is implemented

- **State machines**: run PLANNED→APPROVED→RUNNING→COMPLETED / ABORTED plus COMPLETED→RUNNING reopen; order DRAFT→RESERVED→CONSUMED / RELEASED with the EXEMPT/PENDING/CLEARED security arc; shipment DRAFT→BOOKED→IN_TRANSIT→DELIVERED / CANCELLED; quote DRAFT→ISSUED→WITHDRAWN/EXPIRED plus revise; turnaround DRAFT→SUBMITTED→(PSM)→APPROVED→IN_PROGRESS→COMPLETED / REJECTED / revise; task PENDING→READY→DONE; charge ACTIVE→SPENT→ACTIVE (regeneration) →RETIRED; train IDLE/RUNNING/DERATED/DOWN_FOR_TURNAROUND; plant posture NORMAL/RESTRICTED/FROZEN.
- **Calculations** (all `Decimal` + ROUND_HALF_UP at the PRD's per-class precision): hedged blend, provisional/final campaign unit cost with the hedge-lot waterfall draw, catalyst calendar and severity-adjusted activity with hour accrual, ammonia allocation and unallocated balance, landed cost, freight (base + fuel surcharge + per-ton), quoted price by pass-through basis, storage position (on-hand/reserved/seasonal/available), emissions tons and the rolling 30-day window, CPM earliest-start-day and critical path, turnaround counters.
- **Validations**: 28-rung deterministic rejection ladder with the PRD's fixed sweep orders, 43 error ids with their declared HTTP statuses, role auth plus entity-backed TerminalOperator, segregation of duties on run approval and turnaround approval, OCC on the two declared writes (`expected_run_version`, `expected_origin_asset_version`), pagination bounds (out-of-range → ERR_INVALID_REQUEST 422), the FROZEN-posture gate, and all cascades (derate, recover, freeze/degrade, outage start, order release, shipment cancellation, quote withdrawal, expire-due sweep).
- Version discipline is exactly +1 per mutated row per request, enforced by request-scoped dedup, so multi-hop cascades that revisit a row still bump once.

## Boot smoke test

Cold-booted the shipped tree from a fresh process with `PORT=51942 bash start.sh` after deleting all bytecode. Server came up, and **every one of the 13 collections returned `total_count=0`** — confirming no seeded or preloaded data, and the clock defaulted to `2026-08-01T00:00:00.000Z`. Ran a 40-step end-to-end scenario (plant → train → charge → hedge lot → product line → assets → campaign approve/start/complete/settle → order reserve/produce → shipment book/depart/deliver → quote issue → turnaround submit/PSM/approve/start/tasks/complete → emissions exceedance): no 500s, no unexpected error ids, and the cascades landed correctly — hedge waterfall drew 158,400 MMBtu and closed out at 41,600 remaining, catalyst hours accrued 1,000→1,336 with activity 97.57%, freight priced to 20,115.90 USD, delivery moved 990 t between assets, turnaround completion retired CH1 and installed CH2 leaving the train IDLE, two exceeding pollutants drove the plant to FROZEN and withdrew the ISSUED quote with `PLANT_POSTURE_DEGRADED`. Negative paths returned ERR_INVALID_REQUEST 422 (bad limit), ERR_UNKNOWN_ROLE 401, ERR_PLANT_NOT_FOUND 404. **Kill-and-relaunch on the same port within one second worked and came back to empty state**, which is the exact pattern `--isolation per-test-server` uses. Torn down by specific listener PID only (verified port free and zero orphan processes with a cwd under the task dir); no broad pkill was ever issued.

## Adjudications where the PRD was ambiguous

1. **`run_code` uniqueness scope** — declared unique per plant, but a run references a train, not a plant. Resolved by scoping the duplicate check to the set of trains belonging to the run's train's plant.
2. **Abort clearing the provisional price** — the PRD lists that effect only under the APPROVED arm, so aborting a RUNNING campaign keeps `provisional_unit_cost_usd_per_ton` and only the APPROVED arm nulls it.
3. **No ACTIVE charge at approve/start** — the PRD names no distinct error for a train carrying no charge at all; folded into `ERR_CATALYST_ACTIVITY_TOO_LOW`.
4. **Clock advance** — §3.10's "so does advancing the logical clock" is implemented as a sweep re-deriving every plant's posture (a sliding 30-day window can degrade a plant with no write to it); versions bump only on plants whose posture actually changed.
5. **Rung-order ties** — security class (rung 16) evaluated before product mismatch (rung 18) on order create; destination capacity (rung 26) before origin seasonal reserve (rung 27) on booking; duplicate (rung 8) before state (rung 9), which makes turnaround completion validate `new_charge_code` uniqueness before the IN_PROGRESS gate.
6. **`window_days` under one day** — floored at 1 whole day.
7. **Which charge a turnaround retires** — the train's ACTIVE charge if there is one, else its earliest SPENT charge.
8. **Regeneration refusal** — rejected when the post-regeneration figure would still be below the minimum, or when the train already carries another ACTIVE charge.
9. **Immutable families** — product lines and emissions readings emit no `updated_at`/`version` (a create-only `_immutable` flag), since the PRD's field lists omit them.
10. **Unhandled/framework errors** — routing and unexpected exceptions still return the standard envelope; the catch-all maps to ERR_INVALID_REQUEST 422 rather than a bare 500, and `strict_slashes` is off so trailing-slash variants resolve.

Orchestrator verification after Steps 5+6: no `workspace/test_*` strays; 170 `Design:` tags across `test_suite/`; `compileall` clean over test_helpers/, test_suite/ and implementation/; no seed/preload symbols in implementation/.

## Step 7: Run tests and iterate — 2026-09-06T02:11:54.601359711Z

Done — all 8 rounds green.

## Summary

**Iterations run:** 2 sweeps (baseline + 1 fix batch).

**Final sweep (all 8 parallel rounds):**

| Round | Passed/Total |
|---|---|
| 1 | 170/170 |
| 2 | 170/170 |
| 3 | 170/170 |
| 4 | 170/170 |
| 5 | 170/170 |
| 6 | 170/170 |
| 7 | 170/170 |
| 8 | 170/170 |

Cross-checked: union of failing tests = 0, and `sum(total - passed)` = 0 across all rounds. Round durations were tight (297–299 s), no load-induced or connection-reset noise.

**Tests deleted:** none. Both failure clusters were test-artifact bugs that were fixable in a PRD-more-faithful direction, so no test failed the STEP 1 coverage or unique-derivability checks.

**Fixes applied to `test_suite/`** (both in `test_suite/test_09_state_transitions.py`):

1. `TestShipmentDelivery._departed_movement` — added `fx.set_clock(api, "2026-08-05T00:00:00Z")` between booking and departing. The helper drafted a movement with `window_start` of 2026-08-05 but left the logical clock at its 2026-08-01 epoch, so PRD §3.7 ("Departure … requires only that the logical clock has reached or passed `window_start`") made the PRD-faithful implementation correctly refuse with `ERR_INVALID_STATE`, surfacing as a shared setup error across 4 tests. The sibling helper in `test_14_role_access.py:394` already used exactly this clock-move pattern, confirming the majority convention.
2. `TestOverduePsmProgramWithdrawsIssuedQuotes.test_the_restriction_withdraws_the_quote_it_had_already_issued` — corrected the expected `withdraw_reason` literal from `"POSTURE_RESTRICTED"` to `"PLANT_POSTURE_DEGRADED"`. PRD §3.10 states verbatim: "every quote on that plant whose `status` is `ISSUED` transitions to `WITHDRAWN` with `withdraw_reason` set to `PLANT_POSTURE_DEGRADED`". The suite's own `test_helpers/constants.py` already defines `WITHDRAW_REASON_POSTURE_DEGRADED = "PLANT_POSTURE_DEGRADED"`; this one test hardcoded a divergent string instead of using it.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories, role-header builders and assertion library all traced cleanly to PRD (money/tonnage as JSON numbers, full ISO-8601 instants with three fractional digits, truly-empty `""` headers, entity-backed `TerminalOperator` identity).

**Fixes applied to `implementation/`:** none. Neither failure was an implementation defect — in cluster 1 the implementation was enforcing a PRD-required precondition that the test setup could not satisfy (STEP 2 territory, not STEP 3), and in cluster 2 the implementation already wrote the exact cascade reason the PRD names. No PRD-required check was removed or weakened, and storage remains in-memory-only with no seeded data.

### Orchestrator independent verification of the Step 7 claim

Re-read all 8 `workspace/implementation/results.$i.json` directly (keyed on `status`, not `outcome`): every round `passed=170 total=170`, durations 296.8–298.7 s, `sum(total-passed) = 0`, union of failing tests = 0. `grep -c "def test_"` over `test_suite/` still totals **170** test functions, so nothing was deleted to reach green. `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/`: no hits.

### Orchestrator decision on Step 8

Step 7 reports **0 `implementation/` fixes and 0 deletions**, but it is **not** a zero-iteration exit — it ran 2 sweeps and applied 2 `test_suite/` fixes. The skip condition in the skill requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes, so it is not met. Step 8 therefore runs, with the two `test_suite/` fixes as its `<step_7_diff>` focus list. Expectation recorded up front: because no implementation code changed, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome here — both fixes were the test disagreeing with prose the PRD already states verbatim (the §3.7 departure precondition and the §3.10 `PLANT_POSTURE_DEGRADED` reason), i.e. no PRD silence to pin. Step 9 must still not be identical.

## Step 8: Finalize PRD — 2026-09-06T02:22:33.510741399Z

`workspace/PRD_FINALIZED.md` is written and is byte-identical to PRD.md.

## Line counts
- PRD.md: 533 lines
- PRD_FINALIZED.md: 533 lines
- Delta: 0 lines, 0.0%

## Changes
None. Both `<step_7_diff>` items were the test artifact disagreeing with prose PRD.md already states verbatim, and Step 7 applied zero implementation fixes and zero test deletions, so there was no PRD-silence or PRD-mismatch to pin.

## Verification log (per Step 7 item)

**Item 1 — `TestShipmentDelivery._departed_movement` clock move before departure**
- (a) Subject: the precondition set for the `BOOKED → IN_TRANSIT` departure transition, and the error code raised when the logical clock has not reached `window_start`.
- (b) Impl paths enumerated: `implementation/routes/shipments.py:133-145` (`depart_shipment` — asserts only `status == "BOOKED"` and `db.clock >= ship["window_start"]`, touches only the shipment, moves no inventory); `routes/shipments.py:98-131` (`book_shipment` — confirmed it has **no** clock gate, so the fixture's booking at the 2026-08-01 epoch was legitimately accepted); `routes/shipments.py:147-169` (`deliver_shipment`) and `:171+` (`cancel_shipment`) as the parallel transitions; `guards.py:46` (`state()` default `error_id="ERR_INVALID_STATE"`); `errors.py:24,70`; and every sibling clock gate in the codebase via `grep "db.clock >=|db.clock <"` → `routes/runs.py:149,174`, `routes/turnarounds.py:198`, `routes/quotes.py:94`. All four `>=`-style gates use the `state()` default `ERR_INVALID_STATE` (409); only the quote-issue gate names a specific code, `ERR_QUOTE_EXPIRED`, which PRD §3.8 line 336 already states. PRD §3.7 line 326 ("requires **only** that the logical clock has reached or passed `window_start`… no inventory moves yet, and the movement's `version` advances by 1") describes `depart_shipment` exactly, and PRD §3.2 rung 9 (line 168) already generically pins unnamed state-transition refusals to `ERR_INVALID_STATE` at 409. PRD determines the behavior uniquely; the fixture simply failed to satisfy a PRD-required precondition.
- (c) No wording adjustment — no edit made.

**Item 2 — corrected `withdraw_reason` literal in the posture-degradation cascade test**
- (a) Subject: the `withdraw_reason` value written when a posture re-derivation withdraws `ISSUED` quotes.
- (b) Impl paths enumerated: `implementation/cascade.py:138-146` (`withdraw_issued_quotes` — writes the literal `"PLANT_POSTURE_DEGRADED"`, filters `status == "ISSUED"`, orders by `created_at`, bumps `version`); `cascade.py:155-172` (`rederive_posture` — invokes the withdraw sweep on **both** `RESTRICTED` and `FROZEN` landings, and additionally `freeze_production` only on `FROZEN`); `cascade.py:148-153` (`freeze_production` → reverted campaigns + `release_order(order, "PLANT_FROZEN")`); plus every other `withdraw_reason` writer via grep — `routes/quotes.py:113,117` (manual withdrawal takes the reason from the request body), `routes/quotes.py:142` (revision clears it to null), `routes/quotes.py:47` (initial null), `serialize.py:205`. PRD §3.10 line 401 already states the `PLANT_POSTURE_DEGRADED` literal, the `RESTRICTED`-or-`FROZEN` trigger, the `created_at` ascending order, the `version` bump, and the `FROZEN`-only extra hops with `release_reason` `PLANT_FROZEN` — all matching the impl; and PRD §3.8 line 342 already covers the manual and revision arms. The suite's own `test_helpers/constants.py` already carried the correct constant; one test hardcoded a divergent string.
- (c) No wording adjustment — no edit made.

Scratch dir `.scratch/step8` was created and removed; PRD.md, `implementation/`, `test_suite/`, `test_helpers/` and worklog.md were not modified.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is the correct outcome for Step 8 when Step 7 made no `implementation/` fixes — both Step 7 fixes corrected the test against prose the PRD already stated. Confirmed by `md5sum` on both files. Step 9, by contrast, must NOT be identical: it runs a full impl-vs-PRD scan and will be partitioned by implementation module into sequential passes plus a reconciliation pass.

## Step 9: Complete PRD — 2026-09-06T02:57:10.122895849Z

Orchestrator decision: Step 9 was run as **four sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, because a single-agent full-impl scan reliably under-covers a 3,400-line implementation and can return a byte-identical file. Pass A performed the `cp` from `PRD_FINALIZED.md`; passes B, C and D were explicitly forbidden from copying. Pass D was a reconciliation pass whose only job was to close the cross-partition contradictions the earlier passes deferred.

**Partition map**
- Pass A — `app.py`, `store.py`, `envelope.py`, `auth.py`, `guards.py`, `mutate.py`, `util.py`, `errors.py`, `validate.py`, `serialize.py`, `routes/{plants,trains,charges,hedge_lots,product_lines,clock}.py`
- Pass B — `calc.py`, `routes/{runs,orders,quotes}.py`
- Pass C — `cascade.py`, `routes/{assets,shipments,turnarounds,tasks,emissions}.py`
- Pass D — reconciliation only (no new partition)

**Totals: 69 edits.** Pass A 20 (18 ambiguity-pins, 2 mismatch-revisions) · Pass B 16 (14 pins, 2 mismatches) · Pass C 17 (14 pins, 3 mismatches) · Pass D 16 (8 worklist items + 4 consistency-sweep contradictions).

### Pass A (20 edits) — plumbing + registries

- §2.1 — revise — ambiguity — whitespace-only header counts as empty for `ERR_UNAUTHENTICATED`; role match is exact/case-sensitive — `auth.py:30,34`
- §2.1 — revise — mismatch — TerminalOperator identity is compared as an opaque string on exactly one check (delivery ack); it is never resolved to a `StorageAsset`, so an unknown id yields `ERR_TERMINAL_NOT_OWNER`, not a 404 — `auth.py:26-38`, `routes/shipments.py:149-154`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase A–Z/0–9; `api_request_timestamp` reads the logical clock — `envelope.py:11-22`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is 422; explicitly empty value takes the default; `offset` has no upper bound and past-the-end pages return empty data with `has_more` false — `envelope.py:51-75,30-39`
- §2.3 — revise — ambiguity — `created_at` ties (common under a stationary logical clock) break by insertion order, for lists and for every `created_at ASC` sweep — `store.py:47-56`
- §2.4 — revise — ambiguity — one canonical emitted instant form `YYYY-MM-DDTHH:MM:SS.mmmZ`; input accepts `T`/space, optional seconds/fraction, bare date as midnight UTC, `Z` or `±HH:MM` offset; sub-ms remainder dropped on emission — `util.py:46-87`
- §2.4 — revise — ambiguity — `version` advances once per row per request even when two hops touch it; `updated_at` refreshed from the logical clock — `mutate.py:12-21`, `store.py:71-75`
- §2.4 — revise — ambiguity — clock response is `data.current_utc`; the instant may move backwards (no monotonicity check); plants re-derived in `created_at` ascending order — `routes/clock.py:15-24`
- §2.5 — revise — ambiguity — out-of-vocabulary enum filters and non-existent id filters match nothing (200 + empty array, never 422/404); empty filter value is absent; undeclared query params ignored — `validate.py:167-182`, `guards.py:58-65`
- §2.6 — revise — ambiguity — `permit_limit_tons_30d` and `rated_ammonia_tpd` carry 2 decimal places (previously unlisted) — `routes/plants.py:23`, `routes/trains.py:22`
- §2.6 — insert — ambiguity — over-precise input literals are rounded half up at validation, not rejected; integer fields accept a zero-fraction number; figures emit as JSON numbers with no forced trailing zeros — `validate.py:84-123`, `serialize.py:9-14`
- §2.10 — revise — ambiguity — codes compared case-sensitively; a uniqueness scope covers rows in every status, including terminal ones — `guards.py:30-43`
- §2.10 — revise — ambiguity — length bounds measured on the value as supplied and stored untrimmed; blankness judged after trimming — `validate.py:48-70`
- §2.11 rung 4 — revise — ambiguity — absent/empty body reads as `{}`; non-JSON or non-object body is 422; explicit null counts as absent — `validate.py:24-45`
- §3.1 — revise — ambiguity — `gas_index_updated_at` is stamped at registration, so it opens equal to `created_at` — `routes/plants.py:31`
- §3.1 — revise — mismatch — the incumbent charge retired by a new install has its own `version` advanced too, alongside the train's — `routes/charges.py:48-52`
- §3.2 — revise — ambiguity — a poisoning revision is accepted on any charge status (only `ACTIVE` can derate) and never restores a `SPENT` charge — `routes/charges.py:75-85`, `cascade.py:102-106`
- §3.2 — revise — ambiguity — the three-regeneration ceiling binds only the `ACTIVE` self-transition; the recovery arm is uncapped and rolls the increment back on failure — `routes/charges.py:88-107`
- §3.3 — revise — ambiguity — the blend is derived, not stored; booking a lot is the one blend-moving event that does not advance the plant's `version` — `routes/hedge_lots.py:17-41`, `serialize.py:35`
- §3.10 — revise — ambiguity — permit-status and PSM-status writes are not gated on the value changing; a no-op re-post still advances `version` by 1 — `routes/plants.py:70-90`

### Pass B (16 edits) — calculations, campaigns, orders, quotes

- §3.4 (schedule) — insert — ambiguity — a new campaign's `actual_ammonia_tons`, `actual_operating_hours`, both unit-cost fields, `abort_reason` and `reopen_reason` all open null — `routes/runs.py:77-95`
- §3.4 (approve) — insert — ambiguity — a train carrying **no** `ACTIVE` charge answers `ERR_CATALYST_ACTIVITY_TOO_LOW`, not a distinct code, at approve and start alike — `routes/runs.py:44-52`
- §3.4 (start) — insert — ambiguity — a clock short of `window_start` is `ERR_INVALID_STATE` — `routes/runs.py:149-150`
- §3.4 (start) — insert — ambiguity — a train already `RUNNING` keeps its status but its `version` still advances (`touch(train)` is unconditional) — `routes/runs.py:160-162`
- §3.4 (settle) — insert — ambiguity — clock shortfall is `ERR_INVALID_STATE`, and settlement is **not** posture-gated, so it succeeds at a `FROZEN` plant — `routes/runs.py:166-179`
- §3.4 (pool basis) — revise — mismatch — pinned the `PLANNED` exception: the pool reads exactly `0.000` regardless of `target_ammonia_tons` and of tonnage already promised; it exists only from `APPROVED` onward, and a cascade-reverted campaign collapses to `0.000` with its reservations intact, so §2.12's conservation identity holds from `APPROVED` on — `calc.py:483-493`
- §3.4 (abort) — insert — ambiguity — the `RUNNING` arm leaves `provisional_unit_cost_usd_per_ton` as it stands; only the `APPROVED` arm clears it — `routes/runs.py:217-219`
- §3.4 (reopen) — insert — ambiguity — the train's `version` advances only when the reopen actually moves its `status` — `routes/runs.py:266-268`
- §3.5 (order creation) — insert — ambiguity — `produced_tons`, `landed_cost_usd`, `release_reason`, `security_checked_by_user_id` open null — `routes/orders.py:55-62`
- §3.5 (order creation) — insert — ambiguity — the three creation tests run in §2.11 ladder order, so `ERR_SECURITY_CLASS_INSUFFICIENT` outranks either `ERR_PRODUCT_MISMATCH` — `routes/orders.py:42-47`
- §3.5 (reserve) — insert — ambiguity — `reserve_tons` is bounded only by the pool and asset capacity, never by `requested_tons`, and each reservation overwrites `reserved_tons` — `routes/orders.py:93-111`
- §3.5 (release) — insert — ambiguity — only the origin asset of a cancelled **`BOOKED`** movement is touched; a `DRAFT` cancellation bumps no asset — `cascade.py:40-48`
- §3.5 (security check) — insert — ambiguity — a decision aimed at a non-regulated line answers `ERR_INVALID_STATE` — `routes/orders.py:138`
- §3.6 (produce) — revise — mismatch — "Five conditions" → "Six conditions", plus the pin that they are evaluated in §2.11 ladder order, making `ERR_PRODUCED_EXCEEDS_RESERVED` the last reached — `routes/orders.py:156-170`
- §3.8 (issue) — insert — ambiguity — `ERR_QUOTE_EXPIRED` (rung 9) precedes `ERR_PLANT_FROZEN` (rung 10) — `routes/quotes.py:93-96`
- §3.8 (revise) — insert — ambiguity — a supplied `expires_at` is tested against the quote's **original `created_at`**, not the clock, so a revision may install an already-past expiry — `routes/quotes.py:130-131`

Two of pass A's three flagged observations did **not** hold and were correctly left alone: §3.8 already says the seasonal multiplier keys off "the UTC month of `expires_at`", and §3.6 already says `landed_cost_usd` "is the exact sum of those four rounded values and is never re-rounded". The `PLANNED` pool observation did hold.

### Pass C (17 edits) — cascades, storage, logistics, turnarounds, emissions

- §2.12 — insert — ambiguity — movement-cancellation sweep driven by an order release processes that order's `DRAFT`/`BOOKED` movements in `created_at` ascending — `cascade.py:36-39`
- §3.2 hop 3 — revise — mismatch — hops 3 and 4 are skipped when the train already sits `DOWN_FOR_TURNAROUND`: charge still goes `SPENT` and bumps, train status/`version` untouched, no `APPROVED` campaign reverted — `cascade.py:111-114`
- §3.2 (recovery arm) — insert — ambiguity — the reopen-driven `SPENT → ACTIVE` arm carries the same no-other-`ACTIVE`-charge condition as regeneration; train status then left alone too — `cascade.py:122-132`
- §3.6 — insert — ambiguity — opening-balance accepts exactly 0 (`ge=0`), negative is `ERR_INVALID_REQUEST` — `routes/assets.py:72`
- §3.7 (draft) — insert — ambiguity — `distance_miles` carries one decimal place — `routes/shipments.py:41`
- §3.7 (book) — insert — ambiguity — the six booking conditions are evaluated in §2.11 ladder order, not as narrated (security outranks product-mismatch; dest capacity outranks origin availability); a released/never-reserved order fails at rung 9 with `ERR_INVALID_STATE` — `routes/shipments.py:103-125`
- §3.7 (depart) — insert — ambiguity — clock short of `window_start` → `ERR_INVALID_STATE` — `routes/shipments.py:140-141`
- §3.7 (deliver) — insert — ambiguity — `received_tons > tons` is `ERR_INVALID_REQUEST` (422) reached only after rung 7 ownership and rung 9 `IN_TRANSIT` — `routes/shipments.py:156-157`
- §3.9 (author) — insert — ambiguity — `plant_id` and `train_id` are never cross-checked; an outage may name a train belonging to another plant — `routes/turnarounds.py:59-60`
- §3.9 (submit) — insert — ambiguity — an outage with no steps is refused at rung 9 with `ERR_INVALID_STATE` — `routes/turnarounds.py:109-110`
- §3.9 (approve) — insert — ambiguity — ladder order applies (SoD rung 12 before PSM rung 15), and the 14-day separation is whole days truncated toward zero between the earlier `window_end` and the later `window_start` — `routes/turnarounds.py:31-38, 137-143`
- §3.9 (start) — insert — ambiguity — clock short of `window_start` → `ERR_INVALID_STATE` — `routes/turnarounds.py:198-199`
- §3.9 (complete) — insert — ambiguity — unfinished step → rung 9 `ERR_INVALID_STATE` — `routes/turnarounds.py:224`
- §3.9 (complete, charge swap) — insert — ambiguity — retires the `ACTIVE` charge if any, else the earliest-created `SPENT` charge, else nothing — `routes/turnarounds.py:229-236`
- §3.9 (complete, versions) — revise — mismatch — retired charge bumps only when the scope swapped the catalyst; replacement is minted at `version` 1; a `VESSEL_INSPECTION`-only close-out touches no charge — `routes/turnarounds.py:228-261`
- §3.10 (ingestion) — insert — ambiguity — the reading is stored before `rolling_30d_tons` is taken, so its own `tons` counts toward the figure it reports — `routes/emissions.py:44-46`
- §3.10 (re-derivation) — revise — mismatch — version discipline: the three write events bump the plant regardless of posture movement, while a re-derivation landing on the same posture is not a write, so a clock move leaves unchanged plants' `version`/`updated_at` alone — `cascade.py:156-170`, `routes/emissions.py:48`, `routes/plants.py:77,89`, `routes/clock.py:22-23`

### Pass D (16 edits) — reconciliation

All 8 deferred worklist items were VERIFIED-AND-FIXED (none turned out not to hold):

1. **Posture-gate count.** `grep -rn not_frozen` returns exactly 8 callsites: `routes/runs.py:73,127,153,242` (create/approve/start/**reopen**), `routes/orders.py:100,160` (reserve/produce), `routes/quotes.py:96` (issue), `routes/shipments.py:109` (book). Settlement and abort carry no gate. Fixed §2.8 ("eight commercial and production writes", reopen inserted, plus an explicit note that settle and abort are *not* gated), §2.11 rung 10 ("exactly eight operations"), and §3.10's closing ("the eight writes listed in §2.8").
2. **Rung 14.** `_train_available` (`runs.py:39-41`) refuses `DERATED`+`DOWN_FOR_TURNAROUND` at create/approve/start; reopen (`runs.py:243`) tests only `!= "DOWN_FOR_TURNAROUND"`. Widened rung 14 to four operations, spelling out the two widths.
3. **Rung 19.** `CREATE_LIVE = ("PLANNED","APPROVED","RUNNING","COMPLETED")` (`runs.py:19`) vs `APPROVE_LIVE = ("APPROVED","RUNNING","COMPLETED")` (`:20`), used at `:132-134` with `exclude_id`. Widened rung 19 to both operations, both live sets, and the self-exclusion.
4. **Version-expectation schema bound.** `orders.py:94` / `shipments.py:101` are `s_int(..., ge=0)`. Pinned in both homes compatibly: rung 4 lists them among the at-least-zero fields and states a negative value is its 422 rather than rung 11's 412; §2.7 gained one paragraph cross-referencing rung 4 and noting `version` starts at 1, so `0` is a 412 not a 422.
5. **Rung 4's "tonnages strictly positive".** Full `ge=`/`gt=` sweep found exactly six at-least-zero numeric inputs: `opening_balance_tons` (`assets.py:72`), `rate_lb_per_hour` (`emissions.py:26`), `baseline_operating_hours` (`charges.py:32-33`), `findings_count` (`turnarounds.py:122`), and the two version-expectation fields. Softened rung 4 and enumerated all six.
6. **`received_tons ≤ tons`.** `shipments.py:156-157` calls `v.bad(...)` after `load` and the `IN_TRANSIT` check. Rung 4 now carries the carve-out (schema-shaped code, reached only after rungs 7 and 9), matching §3.7.
7. **§2.6 precision.** Added `distance_miles` (1 dp). The cross-check of every rounded field caught three further silences, all fixed: `new_charge_design_life_hours` (1 dp, `turnarounds.py:212`), the input `reserve_tons` (3 dp, `orders.py:93` — only the stored `reserved_tons` was listed), and `conversion_cost_usd_per_ton`, which is **3** places (`product_lines.py:23`) yet fell inside §2.6's blanket 2-dp currency class — the currency bullet now names it and `ammonia_tons_per_product_ton` as 3-place exceptions. All `rhu()` sites in `calc.py` map to an already-stated class.
8. **Rung 20.** `NEIGHBOUR_STATUSES = ("APPROVED","IN_PROGRESS","COMPLETED")` (`turnarounds.py:20`), filtered at `:29`. Rung 20 rewritten to name the set and state that `DRAFT`/`SUBMITTED`/`REJECTED` neighbours are invisible, matching §3.9.

Additional contradictions found in the consistency sweep and resolved:

- **§3.10 quote withdrawal vs §3.10 version bookkeeping.** §3.10 said quotes withdraw "*whenever* a re-derivation **lands** the plant at `RESTRICTED` or `FROZEN`", while the same section said a re-derivation onto the posture already held is not a mutation. `cascade.rederive_posture` returns early on `posture == previous`, *before* the withdraw/freeze hops. Reworded to arc-driven ("actually moves the plant to…", plus "a re-derivation that merely confirms the posture the plant already holds cascades nothing at all").
- **Rung 16 vs §3.6.** `ERR_SECURITY_CLASS_INSUFFICIENT` fires at three sites — `orders.py:42` (create), `orders.py:163` (**produce**), `shipments.py:111` (book) — but rung 16 listed two while §3.6 states the production test. Widened rung 16.
- **Rung 26 vs §3.5.** `ERR_STORAGE_CAPACITY_EXCEEDED` fires at five sites — `assets.py:74`, `orders.py:109` (**reserve**), `orders.py:169`, `shipments.py:119`, `shipments.py:162` — but rung 26 listed four while §3.5 states the reservation ceiling. Widened rung 26 and summarised the five distinct sums.
- Added a carve-out clause to §2.11's closing "schema precedes existence" sentence so it no longer contradicts rung 4's new `received_tons` note.

### Orchestrator final verification

- `md5sum`: `PRD.md` = `PRD_FINALIZED.md` = `c66dc5b4184538643e13138aefe40766`; `PRD_COMPLETED.md` = `abef818969acaf138beadb03635fa4e4` — **PRD_COMPLETED.md is NOT identical to its source**, as required for Step 9.
- Sizes: PRD.md 533 lines / 108,212 chars → PRD_COMPLETED.md 537 lines / 126,191 chars (**+4 lines, +17,979 chars**). 128 changed lines by `diff`.
- `diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` is empty — 35 headings, no section added or removed, exactly as the "no new sections" rule requires.
- Tail ends at the last row of the §5 error table (`ERR_PRODUCED_EXCEEDS_RESERVED | 409`) — not truncated.
- Leak scan of PRD_COMPLETED.md for `SCAFFOLD` / `harder than expert` / `test_recipe` / `§1.8`-`§1.9`: no hits.
- No file under `implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json`, so the 8/8 × 170/170 sweep remains valid for the shipped tree — Step 9 changed documentation only.
- Cleanup: `sweep.log` (spliced 8-writer garbage) and the `SWEEP_DONE` sentinel removed; `sweep.sh` retained as the reproducible sweep entry point; all `__pycache__` and the empty `.scratch/` removed.

**PIPELINE COMPLETE** — `workspace/PRD_COMPLETED.md` written.
