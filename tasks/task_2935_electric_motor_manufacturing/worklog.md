# Worklog — task_2935_electric_motor_manufacturing

## Step 1: Create task directory — 2026-09-05T18:44:29.379Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/` and `.../workspace/` using the pre-assigned path from the orchestrator invocation (index fixed by scenario number 2935; no auto-allocation scan performed, since up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold (subagent prd-bench-scaffold-generator) — 2026-09-05T20:39:23.127Z

Verified by orchestrator: all three files present; SCAFFOLD.yaml 3427 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2564 lines, SCAFFOLD_CORNER_DESIGN.yaml 4567 lines. Difficulty-directive leak check (`grep -in "harder than expert|expert level" SCAFFOLD.yaml`) returned no hits.

Subagent summary (verbatim):

Step 2 scaffold generation is complete and lint-clean.

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3427 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2564 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4567 |

Structure verified: `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the two design files each have exactly one top-level key. All three parse under `yaml.safe_load` and end at real YAML boundaries (last lines are a complete `note:` string and complete `assert:` list items respectively). The difficulty directive did not leak — no occurrence of "harder"/"expert level" anywhere in `SCAFFOLD.yaml` prose; `scenario:` holds only the `2935. Electric Motor Manufacturing (...)` domain text.

**Linter verdict** (`skills/prd-bench-scaffold-generator/scaffold_lint.py`):
```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  1029

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Domain model:** 13 entities (MotorDesign, StatorBuild, RotorBuild, AssemblyRecord, WorkOrder, PerformanceTest, Nameplate, CustomerOrder, Distributor, WarrantyClaim, RegulatoryStandard, CuringOven, TestCell), 9 state machines, 2 concurrency rules, 17 calculations, 46 ordered validations, 58 endpoints, 56 error codes, 9 roles (DesignEngineer, DesignReviewer, ProductionPlanner, BuildTechnician, TestEngineer, QualityCertifier, ComplianceOfficer, Distributor, PlantAdmin) with `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: expert`, `api_prefix: ""`.

**§1.8:** 9 rule_ids / 22 instances — dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9:** all 9 claim-extraction-guide sections / 78 instances (45 with full `test_recipe`, 33 `excluded_because` stubs): entities 12 (11+1), state_machines 20 (10+10), calculations 13 (7+6), validations 16 (11+5), endpoints 3 (1+2), errors 6 (1+5), rbac 2 (2+0), cross_cutting_complexity_layers 5 (1+4), consistency_model 1. Every stub cites a difficulty instance that exists by name, and no stub carries a `test_recipe`; all 100 instance names are unique across both design files.

**Design adjudications**
- No supersede endpoint for performance tests as a mutation — superseding is a side effect of scheduling a newer test, asserted in the cross-cutting OCC instance.
- `MIN_LEAD_DAYS` clamp is never binding for realistic order shapes, so it is exercised only through the STOCK_REPLENISH/PLATINUM path rather than given its own boundary instance.
- Closed a priority-3 ownership gap in §1.4 by adding `ERR_NOT_OWNER` coverage for submit-review/open-revision authorship plus four missing priority-20 not-found ids, then proved the ladder in `only_the_owning_distributor_and_the_authoring_engineer_may_act_on_a_row`.
- Corrected three invented `claim_type` values (`range_validation`, `state_validation`, `uniqueness`) to guide-legal names (`violation_to_error`, `cross_entity_validation`, `satisfaction_to_pass`) and audited every other section's claim types.
- Fixed a wrong pinned literal: `review_round == 0` after `submit-review` (only `review-decision` increments the round).
- Final lint fix: `GET /work-orders/{id}/cost-summary` declared its inline `output:` as bare comma-separated field names, which the linter parses as an entity name. Rewrote it as `field: type` pairs; this resolved all 6 "(d) capture JSONPath unresolvable" violations (3 in §1.8, 3 in §1.9) with no edits to either design file.
- Error coverage: all 56 codes are triggerable. `ERR_UNAUTHENTICATED`, `ERR_SEGREGATION_OF_DUTIES` and `ERR_STALE_WORK_ORDER_VERSION` had zero coverage after §1.8 and were given real §1.9 instances (errors, rbac, cross-cutting respectively).

All pinned numeric literals come from `.scratch/step2/calc.py` (175 lines), which recomputes the loss model, cost bands, performance/surge/air-gap/balance checks, lead times, warranty indices and the credit waterfall. `worklog.md` and `workspace/` were not touched.

## Step 3: Copy shared files — 2026-09-05T20:39:50.731806586Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD (subagent prd-bench-doc-generator) — 2026-09-05T20:55:39.267332276Z

Orchestrator truncation check (the known doc-generator failure mode): `wc -l` = 486 lines / 101754 bytes; all 28 planned headings present in order (§1 Introduction → §5 Error Code Catalogue); tail is the complete final row of the §5 error table (`| \`ERR_STOCK_ALLOWANCE_EXCEEDED\` | 422 |`), a real section boundary, not mid-sentence. No regeneration needed.

Subagent summary (verbatim):

PRD.md is complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/workspace/PRD.md` — **486 lines, 101,754 bytes**

## Section headings, in order

```
# Electric Motor Manufacturing API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
### 2.1. User and Role-Based Access Control
### 2.2. API Response Structure
#### Standard Success Response Format
#### Standard Error Response Format
### 2.3. Pagination
### 2.4. Resource Identity, Audit Fields and Reference-Data Immutability
### 2.5. The Logical Plant Clock
### 2.6. Flat Collections and Left-to-Right Reference Resolution
### 2.7. Metrology, Rounding and Boundary Discipline
### 2.8. Design Pinning and Optimistic Concurrency Control
### 2.9. Segregation of Duties
### 2.10. Cascades and Compensating Ledgers
### 2.11. Rejection Order
## 3. Business Logic & Workflows
### 3.1. Plant Reference Data and the Logical Clock
### 3.2. Motor Design: Geometry, Materials and the Predicted Loss Model
### 3.3. Design Review, Release and the Revision Cycle
### 3.4. Distributor Programs, Lead Times and the Commercial Order Book
### 3.5. Work Orders: Pinning a Revision and Costing the Build
### 3.6. Stator Winding, Varnish Impregnation and Surge Qualification
### 3.7. Rotor Cage Routes, Air Gap and Balance
### 3.8. Assembly, Dynamometer Scheduling and Efficiency Verification
### 3.9. Nameplate Certification, Revocation and the Regulatory Standard Selector
### 3.10. Warranty Claims: Adjudication, the Credit Waterfall and the Dispute Cycle
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

## Tail confirmation

Last non-empty line is the final row of the §5 table. No audit footer, no contract-report block, no truncated sentence. `PRDEOF` sentinel does not appear anywhere in the file.

## Coverage notes (scaffold → PRD)

- **§1.0 domain/prefix/envelope/pagination** → §1, §2.2 (verbatim from the skill's fixed block), §2.3
- **§1.1 entities (13)** → RegulatoryStandard / Distributor / CuringOven / TestCell → §3.1; MotorDesign → §3.2–3.3; CustomerOrder → §3.4; WorkOrder → §3.5; StatorBuild → §3.6; RotorBuild → §3.7; AssemblyRecord + PerformanceTest → §3.8; Nameplate → §3.9; WarrantyClaim → §3.10. `common_fields: false` on RegulatoryStandard is stated in §2.4.
- **§1.2 state machines** → transitions narrated in the owning §3 subsection; the WorkOrder dual dimension (`build_status` × `certification_status`) is introduced in §3.5, the rotor fork-join in §3.7, the design revision cycle in §3.3, the warranty dispute cycle in §3.10.
- **§1.2.1 concurrency_rules (2)** → §2.8 (both write endpoints, both `expected_*` fields, `ERR_STALE_DESIGN_VERSION` / `ERR_STALE_WORK_ORDER_VERSION`, both 412), restated at the point of use in §3.5 and §3.8.
- **§1.3 calculations (17)** → all constants, rounding widths and inclusive/exclusive boundaries in prose; all four variant pairs given equal-density treatment (design-estimate vs guaranteed-declared in §3.2, DIE_CAST vs BRAZED_BAR in §3.7, summation vs direct in §3.8, FIELD_DATA vs TEARDOWN in §3.10).
- **§1.4 validations (46 priorities)** → conditions distributed into §3; the full priority ordering is expressed as narrative in §2.11.
- **§1.5 endpoints (58)** → §4 four-column table generated directly from the scaffold; 201-vs-200 rule in the intro paragraph.
- **§1.6 errors (56)** → §5 two-column table generated directly from the scaffold.
- **§1.7 roles (9) + 3 SoD separations** → §2.1 and §2.9.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Two independent extractions run against the finished file. Pass 1: 191 required identifiers (175 entity field names, 124 request-body keys, 32 query params, deduped) — 0 missing. Pass 2: an independently re-derived set of 195 (adding path params and common fields) — 0 missing. The PRD's inline backticked tokens yield 440 distinct identifier words, a superset of both. Note: an initial run reported 167 false-positive misses because triple-backtick fences in §2.2 broke naive inline-code pairing; fenced blocks are stripped before matching.

**Contract 2 — Rule Coverage: PASS.** All 56 `error_id`s appear by name in §1–§3 prose (not merely in the §5 table). All entity enum values appear verbatim (0 missing). All state names appear (the one flagged item was the composite initial-state string `build_status=RELEASED, certification_status=PENDING`; both symbols are present). All numeric calculation constants appear (one genuine defect was found and fixed: the `j6` shaft-fit lower bound had been written with a Unicode minus, so `-5` was not literally present; it is now ASCII). All non-null field defaults appear (the one flagged item, `special_requirements` default `{}`, is expressed as "defaulting to empty" with all four recognised keys named). Both OCC rules, all `applies_to` scopes, all cross-entity cascades, all four compensating ledgers, and both sides of every sibling branch are covered.

**Contract 3 — §3 Path Purity: PASS.** 1,033 inline backticked tokens between `## 3.` and `## 4.`: 0 leading-slash tokens, 0 bare HTTP methods, 0 method+path combinations, 0 path-shaped tokens. §1–§2 are also path-free. All operations in §3 are framed as state transitions, role + action verb, or capability descriptions.

**Structure:** §4 table is exactly 4 columns across all 58 endpoint rows; §5 table is exactly 2 columns across all 56 error rows. Nothing was written outside PRD.md; `worklog.md` was not touched; scratch work lives in `.scratch/step4/`.

## Step 6: Generate implementation (subagent prd-bench-implementation-generator) — 2026-09-05T21:25:48.642675760Z

Subagent summary (verbatim):

Step 6 complete. The implementation is written, compiles, and passed an end-to-end smoke test on the first run.

## Files (`workspace/implementation/`)

| lines | file | role |
|---|---|---|
| 71 | `app.py` | app factory, blueprint registration, ApiError/HTTPException/Exception → JSON error envelope, `$PORT`, `0.0.0.0`, `threaded=False` |
| 82 | `errors.py` | all 57 error ids → HTTP status + default messages, `fail()` |
| 122 | `store.py` | 13 in-memory dicts + logical clock, `base_row/touch/now/new_id/iso3`, JSON coercion |
| 120 | `envelope.py` | `meta`/`response_type`/`data` envelope, request id, strict pagination |
| 242 | `validate.py` | shape validation (all → `ERR_INVALID_REQUEST`), `json.loads(parse_float=Decimal)` |
| 378 | `calc.py` | every pinned calculation (loss model, lead time, cost bands, surge, air gap, unbalance, shaft fit, dual-variant efficiency, misuse index, credit waterfall) |
| 98 | `ledgers.py` | the 4 compensating ledgers, all by full recomputation |
| 52 | `auth.py` | 9 roles, `ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`, distributor identity |
| 70 | `helpers.py` | 404 map, row loading, filters |
| 240 | `routes_reference.py` | clock, standards, distributors, ovens, cells |
| 235 | `routes_design.py` | designs, review cycle, design-revision cascade |
| 303 | `routes_orders.py` | customer orders (+3-hop cancel cascade), work orders, cost summary, ship |
| 540 | `routes_builds.py` | stator (impregnate/surge/disposition), rotor (fork/join), assembly |
| 335 | `routes_tests.py` | performance tests, standard selector, nameplates, 3-hop revocation cascade |
| 213 | `routes_warranty.py` | claims, analyze, dispute, close |
| **3101** | 15 modules | + `requirements.txt`, `start.sh` (mode 755) |

**Endpoints: 58/58.** Flask's `url_map` enumerates exactly 58 non-static routes (27 GET, 31 POST), one-for-one with the PRD §4 table. `python3 -m py_compile` clean on all 15 modules; `__pycache__` removed afterwards, no stray files.

## Notable PRD-interpretation decisions
- **Rejection order** implemented as one uniform 13-band pipeline (auth → endpoint role → body-derived ownership → path 404 → path-row ownership/SoD → payload shape → body-FK 404 → uniqueness/maintenance → state machines → requalification → cross-entity referential → OCC → acceptance/duplication → evidence → window start → safety/metrology/compliance → capacity/quota). Where §3 narrative and §2.11 disagree (e.g. `ERR_RESOURCE_IN_MAINTENANCE` vs. state), §2.11 wins.
- Body-FK resolution follows §2.6's global list, so `design_id` before `order_id`, and `distributor_id` before `work_order_id`.
- Ownership/SoD checks that logically precede shape validation peek the raw body field opportunistically (distributor claims/orders, nameplate certifier vs. test engineer), then re-check after resolution.
- `created_at`/`updated_at` and every system instant read the logical clock; only `api_request_timestamp` uses wall clock.
- Ranges owned by a dedicated 422 error (slot fill, cure temp, grease fill, teardown evidence, unbalance, shaft fit, air gap) are excluded from shape validation — shape only checks type and decimal width.
- `oven_code`/`cell_code` uniqueness is **not** enforced: no error id exists for it. Filter enums are likewise unvalidated (empty page), since only pagination bounds are named as `ERR_INVALID_REQUEST`.
- Accepted stator/rotor disposition bumps the work order `version` once for the disposition and again when the fork-join fires (+2 total).
- An `_seq` insertion counter gives the stable registration-order tiebreak needed because many rows share the same logical-clock `created_at`.

## Smoke test
Port `26639` (random high port), server PID `1575807`. Script at `.scratch/step6/smoke.py` walked: auth failures (401/403) → pagination bound (400) → empty list envelope → standard → distributor → oven → cell → design (verified `total_predicted_loss_w` 439.2, `predicted_efficiency_pct` 94.47, `guaranteed_efficiency_pct` 93.64, both classes IE4) → duplicate model code (409) → submit-review (incl. `ERR_NOT_OWNER`) → review-decision (incl. `ERR_SEGREGATION_OF_DUTIES`) → order (lead 27 d, ship 2026-08-28) → confirm (allowance 1000→990) → stale-design 412 → work order (direct 2 025 000, COMPLEX, overhead 627 750, standard 2 652 750, unit 265 275) → cost-summary → stator (insulation mismatch, slot fill, required 2.07 kV) → impregnate (60 min, capability 2.68 kV, oven ledger) → surge (overstress, negative margin, margin 0.43/PASS) → disposition → rotor (construction mismatch, bar-count mismatch, air gap, permissible unbalance 318.3) → fork-join to SUBASSEMBLIES_DONE → assembly (shaft fit, grease, deviation 10 µm) → performance test (stale WO 412, cell peak 10.0) → window-not-started → clock advance → record (total loss 500.0, stray 40.0, efficiency 93.75, IE4) → nameplate (SoD, jurisdiction mismatch, not-certified ship block, standard selection, stamp) → ship (order FULFILLED, allowance credited back) → warranty claim → teardown-evidence 422 → analyze FIELD_DATA (index 0.0, DEFECT_CONFIRMED, waterfall credit 222 165 = 159 165 parts + 45 000 labour + 18 000 freight) → distributor credit balance → dispute (credit reversed to 0) → analyze TEARDOWN (index 0.076) → close → nameplate revoke (WO → SUSPENDED) → all 13 list endpoints → 404. Result: `SMOKE OK`, zero failures.

Teardown: located the listener with `ss -lptnH "sport = :26639"` and ran `kill 1575807` on that single PID only. No `pkill`, no pattern match, no other process touched; post-kill the port is refused and only my PID is gone.

## Step 5: Generate unit tests (subagent prd-bench-unit-test-generator) — 2026-09-05T22:32:04.387569439Z

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root (no copy under `workspace/`); 95 `def test_` functions and 95 `Design:` tags.

Subagent summary (verbatim):

Step 5 is complete. All 67 non-stub design instances are now translated into tests.

## Output locations (correct — task root, not `workspace/`)
`test_helpers/` and `test_suite/`. Nothing named `test_helpers`/`test_suite` exists anywhere under `workspace/`.

### test_helpers/ (2787 lines)
`__init__.py` 18 · `api_client.py` 314 · `api_errors.py` 161 · `assertions.py` 667 · `constants.py` 269 · `factories.py` 503 · `fixtures.py` 650 · `test_users.py` 122 · `types.py` 83

### test_suite/ (4978 lines, 95 tests)
`conftest.py` 27 · `test_01` 209 (6) · `test_02` 151 (5) · `test_03` 228 (6) · `test_04` 269 (6) · `test_05` 271 (5) · `test_06` 310 (6) · `test_07` 171 (4) · `test_08` 137 (4) · `test_09` 164 (4) · `test_10` 175 (4) · `test_11` 487 (11) · `test_12` 567 (10) · `test_13` 422 (7) · `test_14` 896 (11) · `test_15_cost_read_out_authentication_and_authority.py` 319 (4) · `test_16_concurrency_guard_and_read_your_writes.py` 175 (2)

## Coverage
- **Queue A (Difficulty §1.8): 50 tests** over all 22 non-stub instances (several tests per instance, since those instances are multi-branch).
- **Queue B (Corner §1.9): 45 tests**, exactly 1:1 with the 45 non-stub instances — entities 11, state_machines 10, calculations 7, validations 11, endpoints 1, errors 1, rbac 2, cross_cutting_complexity_layers 1, consistency_model 1.
- **Instances SKIPPED: 0.** Every non-stub instance passed the PRD-first filter. The 33 stub instances were not emitted.

## Verification
An audit script (`.scratch/step5/audit_tags.py`) parses both design yamls and every test file: 95 `def test_` functions, 95 `Design:` tags, per-file counts match exactly, **zero** tags failing to resolve to a non-stub instance, **zero** stub tags used, **zero** uncovered non-stub instances. `python3 -m py_compile` passes on all 9 helper files and all 17 suite files; `pyflakes` is clean (no undefined names, no unused imports). No `skip`/`xfail`/placeholder markers, no mention of "scaffold" in generated code.

## Two fixture bugs found and fixed this pass
1. **`assert_cost_rollup` asserted a field the work-order row does not carry.** `per_unit_direct_cost_cents` and `unit_standard_cost_cents` are read-out-only per PRD §3.5 ("computed on read rather than stored on the work order"), but the helper checked `per_unit_direct_cost_cents` against work-order rows in 5 call sites — a deterministic `KeyError` in test_02/04/13/14. `assert_cost_rollup` now checks only the stored roll-up (plus `unit_count`), and a new `assert_cost_summary_figures()` checks all eleven declared read-out fields; test_15 uses the latter.
2. **The corner brief's duplicate-model-code trigger used `rated_output_kw: 3.0`**, below the PRD's 4.0–15.0 band, which would have returned `ERR_INVALID_REQUEST` (priority 10) instead of `ERR_DUPLICATE_MODEL_CODE` (priority 24). Rebuilt from a valid payload driven to `OBSOLETE`.

## One brief assertion deliberately not emitted
The `consistency_model` instance's last ASSERT line claims the customer order is still `CONFIRMED` after the work order is created. PRD §3.5 states "If the customer order was still `CONFIRMED` it moves to `IN_PRODUCTION`". test_16 asserts `CONFIRMED` + non-null `confirmed_at` immediately after confirm, and `IN_PRODUCTION` after work-order creation — following the PRD, not the brief.

## Step 7: Run tests and iterate (long-lived diagnostic subagent) — 2026-09-05T22:58:05.470620748Z

Orchestrator verification: the Step 7 subagent deleted its own sweep artifacts on exit, so the orchestrator re-ran the full 8-round sweep independently under `setsid` via `workspace/sweep.sh`. Result: `results.1..8.json` all report `passed 95 / total 95 / failed 0`. Artifacts are left in place in `workspace/implementation/` per the skill output contract.

Subagent summary (verbatim):

Clean. worklog.md untouched (mtime unchanged from before I started).

## Summary

**Iterations run: 2.** Iteration 1 found 6 deterministic failures (identical in all 8 rounds — no flakiness anywhere in this task). Iteration 2: **all 8 parallel rounds 95/95 passed.**

**Tests deleted: none.** One test was partially trimmed under STEP 1c:

- `test_13_calculation_constants_and_precision.py::test_a_second_design_point_reproduces_every_loss_component_and_both_verdicts` — removed the five assertions on `core_loss_w` / `copper_loss_w` / `rotor_loss_w` / `friction_windage_loss_w` / `stray_loss_w` as **COMPUTED-FIELD SILENCE**. PRD §3.2 names the components only in loss-model prose ("Core loss is the base loss multiplied by…") and backticks only `total_predicted_loss_w`; those field names appear in the PRD *solely* as `POST /performance-tests/{id}/record` payload fields (§3.8), never as motor-design response attributes. A faithful reader can omit them from the design serializer. The covered assertions (`total_predicted_loss_w == 388.8`, both efficiencies, both class verdicts, status, version) were kept — and 388.8 is reachable only by rounding each component before summing, so the docstring's PRD rule is still exercised. Drove from Corner/calculations/`premium_design_variant_reproduces_every_loss_component_and_both_classes`.

**Fixes applied to `test_helpers/` (1 file):**
- `factories.py` — `premium_motor_design_payload()` and `economy_motor_design_payload()` passed their variant defaults as literal keywords plus `**overrides`, so any caller overriding a key the variant itself sets crashed with `TypeError: motor_design_payload() got multiple values for keyword argument 'model_code'`. Both now merge overrides into the variant dict via `_merge` before delegating. (Fixed `test_14::test_model_codes_are_case_sensitive_and_a_rejected_build_frees_its_slot`.)

**Fixes applied to `test_suite/` (3 files, all STEP 2 test-vs-PRD faithfulness):**
- `test_11::test_system_fields_are_server_minted_and_the_version_advances_once_per_write` — asserted `updated_at > created_at`, but §2.5 fixes the logical clock at `2026-08-01T00:00:00Z` until a `PlantAdmin` advances it and §2.4 mints both instants from that clock, so a PRD-faithful server *must* return them equal. Rather than relax the assertion, the test now advances the clock between the create and the two mutations (§2.5: "Advancing the clock changes no stored row"), keeping the strict `>` and genuinely proving `updated_at` is refreshed.
- `test_13::test_the_governing_standard_is_the_latest_effective_row_registered_earliest` — asserted `winner["created_at"] < tie["created_at"]` on two standards registered without advancing the clock, so both carried the same instant. The clock is now advanced one minute between the two registrations, which makes §3.9's "`created_at` ascending" tiebreak the actual discriminator instead of relying on an insertion-order fallback the PRD never names.
- `test_12::test_a_superseded_test_can_neither_be_recorded_nor_stamped` — setup died on `ERR_TEST_CELL_CAPACITY_EXCEEDED` (two overlapping 12.0 kW schedules against the 20.0 kW default cell). The implementation is right: §2.11 evaluates the capacity ceiling last, and §3.8 releases draw only for tests already in `SUPERSEDED`, so the test being superseded is still `SCHEDULED` when the aggregate is summed. (`test_06`'s passing reschedule test corroborates this by using a non-overlapping window.) The fixture now registers the cell with `max_concurrent_kw: 40.0` so the test exercises the supersession state machine, not the ceiling. No implementation check was weakened.

**Fixes applied to `implementation/` (1 file):**
- `routes_builds.py::impregnate` — real rejection-order bug. It resolved the path stator with `load()` (hard 404) *before* validating the body, so an inverted `impregnation_window_end` on a non-existent stator returned `ERR_SUBASSEMBLY_NOT_FOUND` instead of `ERR_INVALID_REQUEST`. §2.11 is explicit: "Only then is the payload itself examined for shape … every interval pair satisfying end strictly after start (both `impregnation_window_end` after `impregnation_window_start` …) — all failures reported as `ERR_INVALID_REQUEST`. Existence checks follow: path identifiers first." The path row is now resolved softly and reported missing only after shape validation. (Fixed `test_14::test_the_path_identifier_is_reported_before_the_body_foreign_key`; the other five cases in that test — clean path 404, both-unknown 404, body-FK 404, wrong-role 403 — are unaffected.)

No assertion was weakened to an HTTP-status check, no `skip`/`xfail` was added, no endpoint/field/side-effect was added to the implementation, and storage remains in-memory dicts with no seeded data. `worklog.md` was not touched. Sweep artifacts (`results.*.json`, `SWEEP_DONE`, `sweep.log`, `__pycache__`) were cleaned up; `workspace/sweep.sh` is left in place.

## Step 8: Finalize PRD (subagent) — 2026-09-05T23:06:18.654445920Z

Orchestrator verification: PRD_FINALIZED.md is 486 lines / 102978 B vs PRD.md 486 lines / 101754 B; `diff` shows 4 changed lines (8 diff lines), so the file is NOT byte-identical and the pass genuinely ran. Tail is the same real section boundary (final §5 error-table row).

Subagent summary (verbatim):

PRD_FINALIZED.md is produced. 4 lines revised out of 486; both files end at the same final §5 error-table row (`| ERR_STOCK_ALLOWANCE_EXCEEDED | 422 |`).

**Line counts:** PRD.md 486 lines / 101,754 B; PRD_FINALIZED.md 486 lines / 102,978 B — 0% line delta, +1.2% bytes (4 lines revised, 0 inserted, 0 deleted, no new sections).

**Changes (3 edits, 4 revised lines):**
- §2.3 — revise — pinned the tiebreak for rows sharing an identical `created_at` (frozen clock makes this common): ties keep server-acceptance order, earlier-accepted first, never reordered by `id`; scoped to "wherever this document orders rows by `created_at` ascending" so it covers list results, cascade hops and the §3.9 selector — `store.py:96-104` (`sort_key`/`by_created_at`), `routes_tests.py:208`, `routes_reference.py:103`. Traces to the Step 7 test_13 governing-standard fix ("insertion-order fallback the PRD never names").
- §2.4 — revise — `created_at` (and every server-written row instant) is read from the logical plant clock, never the host wall clock — `store.py:69-79` (`base_row`).
- §2.4 — revise — `updated_at` is refreshed *from that same clock*, so create-then-mutate with no intervening clock advance leaves `updated_at == created_at`; only a clock advance makes it later — `store.py:85-92` (`touch`). Traces to the Step 7 test_11 fix.
- §3.2 — insert — the five predicted-loss components are intermediate figures: only `total_predicted_loss_w` is stored on / returned by the motor-design resource; parenthetical keeps §3.8's measured per-component fields as performance-test fields — `calc.py:71-93` (`design_predicted_efficiency` writes only total + 2 efficiencies + 2 verdicts), `routes_design.py:83-120`. Traces to the Step 7 COMPUTED-FIELD-SILENCE trim in test_13.

**Per-edit pre-edit search log:**
1. **§2.3 ordering tiebreak.** (a) Subject: row ordering when `created_at` ties. (b) Enumerated: `store.py` `sort_key`/`by_created_at` (`(created_at, _seq)`); every list endpoint via `helpers.rows()`; `routes_reference.py:103-104` standards list (stable `(created_at,_seq)` then `effective_from` desc); `routes_tests.py:208-209` `select_standard`; all cascade iterations `routes_design.py:220,228`, `routes_orders.py:164,173,178,182,188`, `routes_builds.py:171`, `routes_tests.py:73,108,321,331`; `ledgers.py` (unordered, sum/count only — order-insensitive). (c) Wording widened from a list-only statement to "wherever this document orders rows by `created_at` ascending — list results, cascade hops and the certification selector's tiebreak alike", and left the standards' `effective_from`-descending exception sentence verbatim so the two do not conflict; added "never reordered by `id`" consistent with §3.9's existing claim.
2. **§2.4 `created_at` source.** (a) Subject: which clock server-written row instants come from. (b) Enumerated: `store.base_row` and all 11 call sites (`routes_design.py:83`, `routes_orders.py:54,222`, `routes_builds.py:97,289,509`, `routes_tests.py:80,260`, `routes_warranty.py:59`, `routes_reference.py:68,127,176,216`); `store.wall_iso3` — used only for `meta.api_request_timestamp` in `envelope.py:22` and `app.py:31`; `routes_reference.py:68` `base_row(mutable=False)` for immutable standards. (c) First draft said "Like every other instant stored on a row" — that would have falsely claimed client-supplied row instants (`window_start`/`window_end`, `impregnation_window_*`, `effective_from`) come from the clock; revised to "every other instant **the server itself writes onto** a row", which also leaves the wall-clock `meta.api_request_timestamp` of §2.2 untouched.
3. **§2.4 `updated_at` refresh / §3.2 loss components.** (a) Subjects: `updated_at` refresh source; per-component loss fields on resources. (b) Enumerated for `updated_at`: `store.touch` (single writer, `now()`), `ledgers.py` all four recompute functions (all call `touch`), grep confirmed no direct `updated_at =` outside `store.py`, and standards correctly have no `updated_at`. Enumerated for loss components: `calc.py:71-93` design model (locals only, no component keys written), `calc.py:268` + `routes_tests.py:95-96,142-143,165-166` performance-test measured components, `routes_design.py:83-120` create serializer and `routes_design.py:141-147` submit-review recompute, §3.3's existing enumeration of the five recomputed outputs, plus grep for `*_loss_w` across all impl modules (hits only `routes_tests.py` and `calc.py`). (c) `updated_at` sentence phrased as "no intervening clock advance" rather than "always equal", so the clock-advance path stays correct; §3.2 sentence scoped to "the design row / the motor-design endpoints" with an explicit parenthetical carving out §3.8's performance-test fields, so the negative claim cannot be read as denying `rotor_loss_w`/`core_loss_w` on tests.

No PRD edit was made for the three Step 7 items that were already PRD-determined or pure fixture bugs: the `factories.py` `**overrides` TypeError (fixture bug), the test_12 test-cell capacity fixture (§2.11 already orders `ERR_TEST_CELL_CAPACITY_EXCEEDED` last and §3.8 already limits released draw to `SUPERSEDED`), and the `routes_builds.py::impregnate` rejection-order fix (§2.11 already mandates shape-before-existence, so the implementation moved toward the PRD).

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 sequential partitioned subagents) — 2026-09-05T23:34:44.929632927Z

Orchestrator decision (recorded per the autonomy directive): Step 9 was run as **three sequential passes partitioned by implementation module**, sharing one `PRD_COMPLETED.md`. A single agent cannot exhaustively walk 15 modules / 3101 lines of implementation against a 486-line PRD within one context, and the known failure mode is a pass that returns a byte-identical PRD_COMPLETED.md because the scan never really happened. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to copy, and each verified the previous pass's edits survived. Partition: pass 1 = app/errors/store/envelope/validate/auth/helpers + routes_reference + routes_design + the design loss model; pass 2 = routes_orders + routes_builds + ledgers (oven/allowance) + lead-time/cost/surge/air-gap/balance/metrology calcs; pass 3 = routes_tests + routes_warranty + measured-efficiency/misuse-index/credit-waterfall calcs + the cell-draw ledger.

Orchestrator verification: PRD_FINALIZED.md 486 lines / 102978 B → PRD_COMPLETED.md 487 lines / 120309 B (+17331 B, NOT byte-identical, so the scan genuinely ran). Heading list is identical to PRD_FINALIZED.md (`diff` of all heading lines is empty — no new sections). §4 endpoint table 58 rows, §5 catalogue complete, tail is the real final section boundary. `find workspace/implementation -name '*.py' -newer results.1.json` returns nothing, confirming Steps 8 and 9 changed no implementation code, so the verified 8×95/95 sweep still holds.

Totals across the three passes: 18 + 24 + 27 = **69 changes (53 ambiguity-pins, 16 mismatch-revisions)**.

### Pass 1 summary (verbatim)
Pass 1 complete.

## Setup
`cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` done (PRD_FINALIZED.md verified present first).

| file | lines | chars |
| --- | --- | --- |
| PRD_FINALIZED.md | 486 | 102,978 |
| PRD_COMPLETED.md | 487 | 108,078 |

Char delta **+5,100**; line delta **+1** (a single new bullet in §2.2's error-format list; every other change is in-paragraph). Heading count and markdown table-row count are byte-for-byte unchanged, and the file still ends at `| ERR_STOCK_ALLOWANCE_EXCEEDED | 422 |`. 19 lines touched: 54, 55, 81, 85, 93, 115, 154, 156, 162, 170, 172, 174, 176, 178, 182, 192, 212, 218, 363.

## Counts
- ambiguity-pins: **12**
- mismatch-revisions: **6**

## Changes
- `§2.2 success format` — revise — ambiguity — `api_request_id` pinned to `req_` + 20 chars from uppercase letters/digits — `envelope.py:12,16`
- `§2.2 success format` — revise — ambiguity — `api_request_timestamp` pinned as the one instant read from host real time, not the logical clock; never written to a row or compared — `envelope.py:22`, `store.py:65`
- `§2.2 error format` — insert — ambiguity — new bullet pinning the global handler: unknown path → 404, unsupported method → 405, server fault → 500, all with `ERR_INVALID_REQUEST`; trailing slash treated as the path itself — `app.py:41,53-61`
- `§2.3` — insert — ambiguity — non-integer-literal `limit`/`offset` rejected (whitespace tolerated); unnamed query params ignored; boolean filters accept only true/false/1/0 any case, `poles` filter integers-only, string filters never reject — `envelope.py:82,92`, `helpers.py:49-70`
- `§2.4` — revise — ambiguity — unrecognised body fields dropped, not rejected (extends the existing "client-supplied `id` is ignored") — `validate.py:40-46` + all route modules' explicit getters
- `§2.7` — insert — ambiguity — decimal width fixes arithmetic precision, not textual form: numbers emitted as bare JSON numbers, `91.40` → `91.4`, whole decimals → `360.0`, compare numerically — `store.py:120-121`
- `§2.11 payload band` — revise — **mismatch** — instants no longer required to carry exactly three fractional digits: fraction is optional, 1–9 digits, `T`/`Z` in either case — `validate.py:19-21`
- `§2.11 payload band` — insert — ambiguity — integer fields refuse booleans and zero-fraction floats; decimal fields accept integers and trailing zeros within width; absent/empty body read as `{}`; non-object JSON rejected — `validate.py:27-37,112-119,153-157`
- `§2.11 existence band` — insert — **mismatch** — path identifiers are resolved *ahead of* the payload-shape band (because ownership/SoD compare against the stored row), so an unknown path id reports 404 even with a malformed body; body FKs still resolved after the shape band. Scoped with "unless that endpoint's own narrative in §3 says otherwise" so pass 2/3 can pin `/stator-builds/{id}/impregnate`, the only endpoint that soft-loads (`routes_builds.py:148`) — `routes_design.py:143,160,206`, `routes_orders.py:102,140,285`, `routes_tests.py:137,303`, `routes_warranty.py:118,175,201`
- `§2.11 closing paragraph` — revise — **mismatch** — "class shortfall only after the review-round ceiling has been confirmed to be intact" contradicted its own next clause and the impl; now "without regard to the state of the review-round ceiling" — `routes_design.py:174-183`
- `§3.1 standards` — revise — ambiguity — `tolerance_pct` pinned to two decimal places with no range of its own — `routes_reference.py:66`
- `§3.1 curing ovens` — revise — **mismatch** — dropped the false "unique across all ovens" claim; `oven_code` recorded as supplied, no uniqueness check, no duplicate-code rejection for equipment — `routes_reference.py:167-185`
- `§3.1 test cells` — revise — **mismatch** — same for `cell_code` — `routes_reference.py:208-224`
- `§3.1 distributors` — revise — ambiguity — `stock_buffer_units` pinned as zero-or-greater with no upper bound — `routes_reference.py:125`
- `§3.1 clock` — insert — ambiguity — returns HTTP 200 with empty data, no read-back; any instant accepted including one earlier than the present reading — `routes_reference.py:36-42`
- `§4 preamble` — revise — **mismatch** — "the clock-setting endpoint returns the clock state" → returns an empty `data` object rather than any read-back — `routes_reference.py:42`
- `§3.2 initial row` — insert — ambiguity — `released_at`, `released_by_user_id`, `review_notes` and (when unsupplied) `supersedes_design_id` are all present-and-null on a fresh DRAFT — `routes_design.py:109-116`
- `§3.2 loss model` — insert — ambiguity — the base loss figure is a full-precision intermediate, never rounded, never stored, never returned — `calc.py:75-85`
- `§3.3 review-decision` — revise — ambiguity — `review_notes` may be the empty string and only overwrites on rounds that carry it; an omitted value leaves the prior round's note standing — `routes_design.py:168,186-187`
- `§3.3 open-revision` — insert — ambiguity — reopening rewrites neither `review_round` nor the release fields, so a design that consumed all three rounds can be reopened and resubmitted but never clears the round-limit check again — `routes_design.py:203-235`

## Modules scanned
`app.py`, `errors.py`, `store.py`, `envelope.py`, `validate.py`, `auth.py`, `helpers.py`, `routes_reference.py`, `routes_design.py`, and `calc.py` lines 16–93 (`rhu`, `rhu_int`, loss-model constants, `class_ordinal`, `classify`, `design_predicted_efficiency`).

Verified as already uniquely pinned, no change made: the nine role names and their exact-match semantics (§2.1); all five reference/design role sets against the §4 table; `has_more`/`total_count` semantics; the standards collection's `effective_from` DESC / `created_at` ASC exception and the global `_seq` accept-order tiebreak; the standards-are-immutable audit-field exception; the five-component round-then-sum order, the 1.15 derate applied to the *rounded* `predicted_efficiency_pct`, the floor table, the `BELOW_IE2..IE5` ordinal ordering, and the guaranteed-verdict release gate; `ERR_DUPLICATE_MODEL_CODE` case-sensitivity and its evaluation after `supersedes_design_id` existence; the two-hop revision cascade with its stale-status set and `SCHEDULED`-only second hop; the full §5 error-id → status table (all 57 rows match `errors.py:13-70` exactly).

## Deliberately left to pass 2/3
The `/stator-builds/{id}/impregnate` soft-load exception to my §2.11 path-before-payload pin (`routes_builds.py:143-148`) — my wording leaves an explicit opening for it in §3.6. Also untouched: everything in §3.4–§3.10 and the §4 rows for orders, work orders, builds, tests, nameplates and warranty; `ledgers.py`; and `calc.py` lines 96–378.

### Pass 2 summary (verbatim)

PASS 2 complete. `workspace/PRD_COMPLETED.md` edited in place only.

## Size
- Before: 487 lines / 108,078 bytes
- After: 487 lines / 113,459 bytes (no new sections, no new paragraphs — all in-paragraph inserts/revisions)

## Counts
- Ambiguity-pins: 19
- Mismatch-revisions: 5

## Changes

**§3.4 (orders / lead times / cancellation)**
- §3.4 — revise — mismatch — `special_requirements`: "an unrecognised key contributes nothing at all" narrowed to "nothing *to the lead time*"; every value in the object must be a boolean regardless of whether its key is recognised — `routes_orders.py:44-48`
- §3.4 — insert — ambiguity — a `Distributor` naming a foreign `distributor_id` is `ERR_NOT_OWNER` ahead of the shape band, but only when the value is a string; missing/null/other-typed gives `ERR_INVALID_REQUEST` — `routes_orders.py:33-38`
- §3.4 — insert — ambiguity — order row minted with `confirmed_at` and `cancellation_reason` present and null — `routes_orders.py:64-65`
- §3.4 — insert — ambiguity — Distributor read of a foreign order is `ERR_NOT_OWNER` (not 404); list is narrowed to own rows, and a foreign `distributor_id` filter is `ERR_NOT_OWNER`, not an empty page — `routes_orders.py:78, 86-91`
- §3.4 — insert — ambiguity — `cancellation_reason` must be at least one character — `routes_orders.py:142`
- §3.4 — insert — ambiguity — the *first* work order to ship fulfils the order; a later shipment finds it `FULFILLED` and leaves the order and the allowance ledger untouched (no double credit-back) — `routes_orders.py:297-301`
- §3.4 — insert — ambiguity — cascade hop 3 recomputes each affected oven once however many of its bookings were scrapped, so its `version` advances by exactly 1 — `routes_orders.py:187-190`

**§3.5 / §4 (work orders, costing)**
- §3.5 — insert — ambiguity — a `design_id` naming some other design draws `ERR_DESIGN_NOT_RELEASED` even when that design is itself `RELEASED` — `routes_orders.py:213-215`
- §3.5 — insert — ambiguity — `shipped_at` present and null at creation — `routes_orders.py:232`
- §3.5 — insert — ambiguity — all seven costing figures are stored on the work-order row and appear on every work-order read, not only on the cost read-out — `calc.py:166-172`, `routes_orders.py:234`
- §4 (`POST /work-orders` row) — revise — mismatch — "against a CONFIRMED order" → "CONFIRMED or already IN_PRODUCTION", matching §3.5 and impl — `routes_orders.py:209-211`

**§3.6 (stator builds)**
- §3.6 — revise — mismatch — "`achieved_capability_kv` is absent" → present and null, plus the full set of eleven other keys minted null on a stator build — `routes_builds.py:106-118`
- §3.6 — insert — ambiguity — **the pass-1 hand-off**: pinned the impregnation endpoint as the one documented exception to §2.11's path-first rule — the path stator is resolved *after* the shape band, so a malformed body reports `ERR_INVALID_REQUEST` even on an unknown stator id, and `ERR_SUBASSEMBLY_NOT_FOUND` only once the body is well-formed; `oven_id` still resolves after the stator — `routes_builds.py:145-161`
- §3.6 — insert — ambiguity — `cure_temp_c` to one decimal place with no range of its own; the oven ceiling is its only bound — `routes_builds.py:157`
- §3.6 — revise — ambiguity — `impregnation_minutes` is *complete* minutes, part-minute remainder discarded not rounded — `routes_builds.py:190-191`
- §3.6 — insert — ambiguity — `disposition_notes` may be empty and is written only when supplied; omission leaves the field as it stood — `routes_builds.py:237, 249-250`
- §3.6 — revise — mismatch — the acceptance that completes the pair advances the work order's `version` twice (disposition touch + fork-join touch), not once — `routes_builds.py:255-256, 58-59`

**§3.7 (rotor builds)**
- §3.7 — insert — ambiguity — the sixteen fields minted null on a rotor build — `routes_builds.py:290-312`
- §3.7 — insert — ambiguity — `melt_temp_c` / `die_preheat_c` to one decimal place, no range — `routes_builds.py:357-358`
- §3.7 — insert — ambiguity — `braze_alloy` at least one character; `bar_count` a whole number bounded only by the design match — `routes_builds.py:371-372`
- §3.7 — insert — ambiguity — only `cage_method` is shape-checked in the payload band; the fork match is settled (after the `PLANNED` check) before the fork's own fields, so a missing/null or wrong-fork field is the construction mismatch while a wrongly typed field on the right fork is `ERR_INVALID_REQUEST` reported after it — `routes_builds.py:348-372`
- §3.7 — insert — ambiguity — `measured_rotor_od_mm` and `rotor_mass_kg` each to three decimal places, no range — `routes_builds.py:393-394`
- §3.7 — revise — mismatch — rotor disposition: notes written only when supplied, and an acceptance firing the fork-join advances the work order's `version` once more — `routes_builds.py:444-451`

**§3.8 (assembly-record portion only)**
- §3.8 — insert — ambiguity — `grease_fill_pct` is stored exactly as submitted at two decimals; only the range comparison uses the one-decimal rounding — `routes_builds.py:504-519`

## Verification
- Pass 1's edits all survived: confirmed the `api_request_id` twenty-character pin, the §2.11 "unless a specific endpoint's own narrative in §3 says otherwise" clause, the equipment no-uniqueness pin, the "full-precision intermediate" base-loss pin, and the global-handler envelope pin.
- File still 487 lines, still ends at `| ERR_STOCK_ALLOWANCE_EXCEEDED | 422 |`; 23 `###` subsections and 58 endpoint rows intact. §5 catalogue verified line-for-line against `errors.py`.

## Left to pass 3 (deliberately untouched)
Everything from "**Scheduling a dynamometer test**" onward in §3.8, all of §3.9 and §3.10, and the `routes_tests.py` / `routes_warranty.py` §4 rows. §2.9/§2.10/§2.11's general framing left alone — impl matches it everywhere in my partition except the impregnation endpoint, pinned locally in §3.6 through pass 1's escape clause rather than by widening §2.11.

### Pass 3 summary (verbatim)

Pass 3 complete. Verification and summary below.

## Structure verification
- **Before:** 487 lines / 113,459 bytes. **After:** 487 lines / 120,309 bytes (+6,850 chars, no line-count change — all edits are in-paragraph).
- §4 endpoint table: **58 rows** intact. §5 catalogue: **56 rows**, and a programmatic diff confirms the §5 `error_id → status` set is byte-identical to `errors.py`'s `ERROR_STATUS`.
- Tail still ends `| ERR_STOCK_ALLOWANCE_EXCEEDED | 422 |`. All 21 `###` sections and 10 `### 3.x` subsections present.
- **Pass 1 survived** (`api_request_id` x4; the §3.4 "ERR_NOT_OWNER ahead of the payload-shape band" pin). **Pass 2 survived** (§3.6 "the one documented exception to the path-identifier ordering of §2.11" impregnation pin).
- Only `workspace/PRD_COMPLETED.md` was touched; git shows no tracked-file changes.

## Counts
27 substantive changes: **22 ambiguity-pins, 5 mismatch-revisions**.

## Changes
- §3.8 capacity — insert — ambiguity — aggregate is taken *before* supersession, so a still-`SCHEDULED` test on the same cell+work order counts against the ceiling — routes_tests.py:60-79
- §3.8 supersession — revise — ambiguity — supersedes on any cell, in `created_at` order; recompute reaches every touched cell incl. the newly reserved one (so a first schedule re-versions its cell) — routes_tests.py:72-110
- §3.8 supersession — insert — ambiguity — the 14 null result fields at creation; `requires_requalification` false even when `design_pin_stale` is true — routes_tests.py:80-104
- §3.8 record payload — insert — ambiguity — 3dp kW / 1dp W / 1dp °C widths, all seven required under either method, `input_power_kw > 0` in the shape band — routes_tests.py:139-147
- §3.8 IEEE bullet — revise — ambiguity — loss/ambient/stray still computed and stored on a dynamometer test, just not used in the efficiency — calc.py:261-278
- §3.9 payload — insert — ambiguity — no rule links `performance_test_id` to `work_order_id`; standard and jurisdiction come from the work order's design/order — routes_tests.py:226-250
- §3.9 gates — insert — **mismatch** — gates evaluate in §2.11 order (SoD, work-order state, test state, jurisdiction), not the narrated order; SoD resolves the cited test opportunistically ahead of the shape band — routes_tests.py:217-247
- §3.9 `issued_at` — revise — **mismatch** — it is not the warranty pro-rata origin; the origin is the work order's `shipped_at` — calc.py:362-366
- §3.9 `certification_status` — revise — **mismatch** — also legitimately from `CERTIFIED`; duplicate nameplates per work order / per test are allowed and the earlier `ISSUED` row is untouched — routes_tests.py:237-277
- §3.9 revoke — insert — ambiguity — `revocation_reason` >= 1 character — routes_tests.py:305
- §3.9 revoke hop 1 — insert — ambiguity — `SUSPENDED` assigned unconditionally whatever the field reads — routes_tests.py:315-318
- §2.10 ledger bullet — insert — ambiguity — "still open" means any `status` other than `CLOSED` — ledgers.py:90-97
- §3.10 filing — insert — ambiguity + mismatch — both ownership mismatches are `ERR_NOT_OWNER`; self-check precedes the shape band (string-only), order-ownership follows the existence band; **no shipment/build-status gate** — routes_warranty.py:33-57
- §3.10 filing — insert — ambiguity — the three measured decimals carry no range of their own — routes_warranty.py:41-44
- §3.10 `reported_at` — revise — **mismatch** — not the pro-rata endpoint; the endpoint is the clock at analysis time — routes_warranty.py:158-161
- §3.10 list/read — insert — ambiguity — foreign `distributor_id` filter and foreign single read both `ERR_NOT_OWNER` — routes_warranty.py:92-106
- §3.10 teardown conditions — insert — ambiguity — JSON null counts as absent; wrong type/>1dp is `ERR_INVALID_REQUEST` first — routes_warranty.py:120-138
- §3.10 adjudication storage — insert — ambiguity — `teardown_defect_evidence_pct` written back null on a `FIELD_DATA` re-analysis — routes_warranty.py:150
- §3.10 waterfall — insert — ambiguity — `claim_unit_standard_cost_cents` written only on the defect branch; misuse leaves the prior value — routes_warranty.py:155-157
- §3.10 service age — insert — ambiguity — end-of-month clamping in the month advance — calc.py:336-345
- §3.10 dispute — insert — ambiguity — `analysis_basis`, evidence, unit cost and `defect_presumption_applied` survive a dispute; `dispute_reason` is never cleared — routes_warranty.py:186-192
- §3.10 dispute — insert — ambiguity — `dispute_reason` >= 1 character — routes_warranty.py:178
- §3.10 close — insert — ambiguity — `closure_notes` may be empty; omitted/null leaves the stored value unchanged — routes_warranty.py:203-209
- §4 `GET /performance-tests` / `GET /nameplates` / `GET /warranty-claims` — revise x3 — ambiguity — full filter lists — routes_tests.py:122-131,288-297; routes_warranty.py:98-112
- §4 `POST /warranty-claims` — revise — **mismatch** — "against a shipped motor" → a motor in the field, no shipment gate — routes_warranty.py:29-57

Nothing in the partition remains unpinned: `select_standard`'s ranking/tiebreak, the capacity/peak ledger arithmetic, both efficiency variants, the misuse index, the credit waterfall, and the credit/presumed-defect ledgers were each already uniquely determined by existing prose (§2.3's `created_at`+acceptance-order tiebreak covers the selector's `_seq`).

---

## Pipeline complete

Step 9 has written `workspace/PRD_COMPLETED.md`. Final state: 95 tests, 8/8 sweep rounds at 95/95, `results.1..8.json` retained in `workspace/implementation/`, and the PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md all present and non-identical.
