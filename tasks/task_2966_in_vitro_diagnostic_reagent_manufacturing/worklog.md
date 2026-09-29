# Worklog — task_2966_in_vitro_diagnostic_reagent_manufacturing

## Step 1: Create task directory — 2026-09-05T23:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2966_in_vitro_diagnostic_reagent_manufacturing` and `.../workspace`. Index 2966 was pre-assigned by the invoking command; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold (subagent, prd-bench-scaffold-generator) — 2026-09-06T01:19:00.000Z

Verified after exit: all three YAML files present; `workspace/` and `worklog.md` survived untouched; grep for the difficulty directive string "harder than expert level" across the task dir returns nothing, so the Step-2-only difficulty instruction did NOT leak into `SCAFFOLD.yaml`'s `scenario:` key (it carries the scenario text verbatim and nothing more). No strip needed.

Subagent summary (verbatim):

All three scaffold artifacts for task 2966 are complete and lint-clean.

## Files

| File | Lines | Top-level key(s) | YAML parse |
|---|---|---|---|
| `.../SCAFFOLD.yaml` | 2384 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (13 — no design keys) | `dict`, OK |
| `…/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2567 | `scaffold_difficulty_design` (single) | `dict`, OK |
| `…/SCAFFOLD_CORNER_DESIGN.yaml` | 5786 | `scaffold_corner_design` (single) | `dict`, OK |

All three end at real structural boundaries (`shared_operations` list / final `assert:` lists). `workspace/` and `worklog.md` untouched; `.scratch/step2` left empty, `.scratch` parent never touched.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1444

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Domain model

`domain_name: ivd-reagent-manufacturing`, `api_prefix: ""`, difficulty **expert_plus**, topology graph, state-machine shape parallel, role_model segregation_of_duties, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

- **14 entities**: MaterialSpecification, MaterialLot, ProductSpecification, DesignControlRecord, ReagentLot, LotComponent, FillRun, MonitoringSample, TestResult, StabilityStudy, BridgingStudy, Complaint, DistributionOrder, Allocation.
- **10 state machines** (MaterialLot cyclic OOS_INVESTIGATION loop; ReagentLot two independent axes disposition × distribution; Complaint fork-join; plus ProductSpecification, DesignControlRecord, FillRun, StabilityStudy, BridgingStudy, DistributionOrder, Allocation).
- **15 calculations**, incl. dual-variant `material_lot_acceptance_decision` (ALL_PASS vs WEIGHTED_SCORE) and `stability_shelf_life` (REAL_TIME vs ACCELERATED), weighted `material_lot_acceptance_score` with a present-set denominator, `lot_release_reference_bias` with a pinned per-test-then-aggregate rounding order, four-phase `fefo_allocation` waterfall, two conservation invariants, `cold_chain_verdict`.
- **37 validations** on a single priority ladder 10 → 140 (401 → 403 → 400 → 400 shape → 404 path → 404 body-FK → 403 SoD → 409 state → 412 OCC → 409 duplicates → the business-safety block 75–140).
- **61 endpoints**, **61 error codes** (401×1, 403×2, 400×2, 404×12, 409×37, 412×2, 422×5), **6 roles** (QCAnalyst, ProductionOperator, QAReleaser, RegulatoryAffairs, DistributionPlanner, PlatformAdmin — the last with an empty `exclusive_operations`), **2 OCC rules** (`component-add-stale-reagent-lot`, `design-record-add-stale-product-spec`).

## §1.8 — 20 instances over all 9 rules
`dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## §1.9 — 104 instances (72 with `test_recipe`, 32 `excluded_because` stubs)
entities 22 · state_machines 20 · calculations 16 · validations 19 · endpoints 5 · errors 10 · rbac 5 · cross_cutting_complexity_layers 6 · consistency_model 1.

## Verification performed beyond the lint
- **All 61 error codes are now triggerable** — closed the last two gaps this session: `ERR_BRIDGING_REQUIRED` (added a release attempt on the bridging-required lot inside the existing predicate-selection instance) and `ERR_STALE_PRODUCT_SPEC_VERSION` (new OCC instance covering both §1.2.1 rules, stale → 412 → refreshed → success, with the parent version and the source MaterialLot ledger proven untouched by the rejection).
- **Placeholder closure**: 0 unbound `${var}` across all 124 instances (found and fixed two — a forward-referenced `${admin_ps_v}` and a never-bound `${probe_rl_v}`, both in the new rbac section).
- **Grounds resolvability**: 0 unresolved (normalised 15 legacy `validations.priority_<N>_<lowercase>` grounds to the canonical `priority_<N>` / `priority_<N>_<ERR_ID>` form).
- **Name uniqueness** across the union of both design files: no duplicates; every stub cites an existing §1.8 instance; no stub carries a `test_recipe`; no instance lacks both.
- **Banned race vocabulary**: 3 residual uses of "simultaneous(ly)" rewritten; scan now clean across all three files.
- Fixed one capture against an undeclared field (`MaterialLot.status` → `qualification_status`) and re-derived the consistency-model score assertion as a computed literal (`acceptance_score 99.60`, which required switching that fixture's spec to `acceptance_mode: WEIGHTED_SCORE`).

## Step 3: Copy shared files — 2026-09-06T01:21:02.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes). No subagent.

## Step 4: Generate PRD (subagent, prd-bench-doc-generator) — 2026-09-06T01:38:00.000Z

Orchestrator truncation check (the known failure mode for this step): `wc -l -c workspace/PRD.md` = 465 lines / 112,584 bytes; `tail -12` ends on the final row of the §5 error-code table (`| ERR_ALLOCATION_SHORTFALL | 409 |`) with a trailing newline — a real section boundary, not mid-sentence/mid-table. `grep -n '^#'` shows all 5 top-level sections and all 23 subsections present in order (§1 … §5). No regeneration needed. Both design YAMLs and INSTRUCTION.md untouched; `.scratch/step2/` intact.

Subagent summary (verbatim):

PRD generation is complete and verified.

## Deliverable

`workspace/PRD.md` — **465 lines, 112,584 bytes**, ends with a trailing newline at a real section boundary (last row of the §5 error table), no audit footer.

## Three Hard Contracts

| Contract | Result | Evidence |
| --- | --- | --- |
| 1 — Field-Name Coverage | **PASS** | 163/163 required names (all `entities[].fields[].name`, all `endpoints[].input` with `?` stripped, both `concurrency_rules[].occ_field`) appear verbatim in backticks; 0 missing. One repair was needed: `fill_run_id` was absent and was added to §3.4. |
| 2 — Rule Coverage | **PASS** | 61/61 error IDs present; 10/10 state machines with all 50 transitions having their `from` and `to` states co-located in prose (0 uncolocated); all reachable state values present in backticks; 15/15 calculations with every declared output field present; 37/37 validation rungs enumerated in §2.6 with all their error IDs and all 37 `applies_to` scopes (0 paths missing); 2/2 OCC fields; 6/6 role names. |
| 3 — §3 Path Purity | **PASS** | 1,236 backtick tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path. |

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; the §4 table's 61 (Method, Path) pairs match the scaffold exactly with 0 extras, 0 missing, 0 duplicates, and all 61 role lists match `auth_roles` exactly (0 mismatches); §5 has 61 rows with scaffold HTTP statuses; scans for fuzzy words, operator/pseudocode leakage (`==`, `>=`, `min(`, `round_half_up`, …) and scaffold-internal references (`§1.x`, `state_machines.`, `test_recipe`) all return empty.

## Table of contents (line ranges)

| Lines | Section |
| --- | --- |
| 1–2 | Title |
| 3–10 | 1. Introduction |
| 11–12 | 2. Global Specifications & System-Wide Principles |
| 13–29 | 2.1 User and Role-Based Access Control |
| 30–78 | 2.2 API Response Structure (verbatim block) |
| 79–84 | 2.3 Pagination |
| 85–92 | 2.4 Common Resource Properties, Revision Counters and the Logical Clock |
| 93–102 | 2.5 Optimistic Concurrency Control on Parent Aggregates |
| 103–146 | 2.6 Path Resolution and the Validation Precedence Ladder (all 37 rungs) |
| 147–154 | 2.7 Precision, Rounding Order and Inclusive Boundaries |
| 155–162 | 2.8 The Two Conservation Invariants |
| 163–172 | 2.9 Segregation of Duties in the Quality System |
| 173–180 | 2.10 Cascade Discipline, Parallel State Dimensions and Version Propagation |
| 181–182 | 3. Business Logic & Workflows |
| 183–206 | 3.1 Raw Material Qualification |
| 207–220 | 3.2 Design Control, Traceability and Regulatory Clearance |
| 221–230 | 3.3 Opening a Finished Lot and Dispensing the BOM |
| 231–244 | 3.4 Filling Runs, Environmental Monitoring and the Compensating Abort |
| 245–262 | 3.5 Release Testing and the Two-Axis Release Decision |
| 263–278 | 3.6 The Stability Programme |
| 279–292 | 3.7 Lot-to-Lot Consistency |
| 293–306 | 3.8 Complaint Handling, Malfunction Reporting and Field Actions |
| 307–330 | 3.9 Distribution: Expiry-Ordered Allocation, Shipping and the Cold Chain |
| 331–398 | 4. Endpoint Definitions (4-column table, 61 rows) |
| 399–465 | 5. Error Code Catalogue (2-column table, 61 rows) |

## Grepped coverage counts

14 entities / 173 entity fields (163 unique required names) · 10 state machines / 50 transitions · 15 calculations · 37 validations · 61 endpoints · 61 errors · 6 roles · 2 concurrency rules — all covered.

## Notes for the orchestrator

- Two scaffold under-specifications were resolved by stating the only determinate reading explicitly in prose: (a) `shelf_life_basis` omitted on reagent-lot disposition means basis `CLAIM` (§3.5); (b) closing a complaint whose `field_action` is still null is refused with `ERR_COMPLAINT_STATE_INVALID`, since the scaffold defines no dedicated code (§3.8).
- The PRD deliberately refers to resources in domain language ("raw material lot", "reservation", "monitoring sample") rather than internal class names, but every field name of all 14 entities appears verbatim in backticks in the section that specifies that resource.
- `SCAFFOLD.yaml`, both design YAMLs, `worklog.md` and `workspace/INSTRUCTION.md` are untouched; `.scratch/step4/` was removed and the sibling `.scratch/step2/` is intact. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was accessed.

## Step 5: Generate unit tests (subagent, prd-bench-unit-test-generator) — 2026-09-06T02:35:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the implementation generator had physical isolation from `test_suite/` (the dir did not exist when it started). Orchestrator verification after exit: `test_helpers/` and `test_suite/` both exist at the TASK ROOT (not under `workspace/`); `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`; `python3 -m compileall -q` over both dirs plus the implementation returns clean.

Subagent summary (verbatim):

Step 5 complete. All eight Stage 2 writers finished; aggregate verification is clean.

## Deliverables (both at the TASK ROOT, not under `workspace/`)

`test_helpers/` — 2828 lines
| file | lines |
|---|---|
| `__init__.py` | 36 |
| `api_client.py` | 252 |
| `api_errors.py` | 140 |
| `assertions.py` | 407 |
| `constants.py` | 132 |
| `factories.py` | 381 |
| `fixtures.py` | 844 |
| `test_users.py` | 108 |
| `types.py` | 528 |

`test_suite/` — 11133 lines
| file | lines | tests |
|---|---|---|
| `conftest.py` | 60 | — |
| `test_01_acceptance_scoring_and_shelf_life_variants.py` | 1282 | 21 |
| `test_02_cascades_precedence_and_boundaries.py` | 1015 | 17 |
| `test_03_cross_entity_gating_overlap_and_conservation.py` | 1362 | 33 |
| `test_04_resource_shapes_and_lifecycle_fields.py` | 985 | 29 |
| `test_05_state_machine_transitions.py` | 1325 | 26 |
| `test_06_derived_calculations.py` | 1186 | 29 |
| `test_07_validation_precedence.py` | 1913 | 60 |
| `test_08_endpoints_errors_and_access_control.py` | 2005 | 65 |

**Total: 280 tests** (confirmed independently by `pytest --collect-only -q` → "280 tests collected").

## Per-queue instance accounting

**Queue A (Difficulty): 20/20 instances translated, 0 skipped, 71 tests.** Every instance carries >= 2 tests (verified minimum = 2). By rule: dual_variant_calc 2 inst/4 tests, combinatorial_formula 3/9, non_linear_state_machine 3/8, transitive_cascade 2/6, priority_pair_validation_conflict 2/4, boundary_precision_check 2/7, cross_entity_state_dependency 2/7, resource_temporal_overlap 2/15, compensating_invariant 2/11.

**Queue B (Corner): 72/72 non-stub instances translated, 0 skipped, 209 tests.** Every instance carries >= 1 test. By section: entities 22 inst/29 tests, state_machines 16/26, calculations 7/29, validations 14/60, endpoints 4/18, errors 1/9, rbac 5/21, cross_cutting_complexity_layers 2/11, consistency_model 1/6.

**32 corner stubs deliberately NOT translated** (state_machines 4, calculations 9, validations 5, endpoints 1, errors 9, cross_cutting 4). Every stub's `excluded_because.difficulty_instance` cross-reference was confirmed to resolve to a real instance in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and the verifier flags any tag that names a stub — none do.

**No instance was SKIPPED under the two-condition filter.** Where the PRD did not uniquely derive a claim, writers narrowed the assertion instead of dropping the instance: pre-measurement `release_bias_*` values, the error id for a non-reportable malfunction report, `created_at == clock` (§2.4 stamps only `performed_at`/`dispositioned_at`/`started_at`/`ended_at`), a "stored at exactly 2 decimals" claim on a JSON number, rung-30-vs-35 ordering, `version`-untouched claims on rejected calls, and the literal `quarantine_reason` string.

**Design-index defects corrected against the PRD** (PRD wins): non-enum test codes `STERILITY`/`SENSITIVITY` replaced with `ACTIVITY`/`PRECISION`; non-existent `FEFO_BEST_EFFORT` policy dropped; empty `required_material_codes: []` recipes replaced (rung 30 forbids empty); a recipe expecting `FILLED` corrected to `UNDER_RELEASE_TEST` (§3.5); a fresh order's `shortfall_units` 0 not 100 and `filled_units` null not 0 (§3.9/§3.4); a retest recipe missing the INVESTIGATE disposition (rung 60 would have pre-empted rung 104); a bridging 404 probe given a real `decision` so rung 30 does not pre-empt rung 40.

## Verification

- **`Design:` tags**: 280 test functions / 280 `Design:` lines. An AST check confirms every test has a docstring whose **last** non-empty line is exactly one `Design:` line. 92 distinct instances covered = 20 difficulty + 72 non-stub corner. No malformed tags, no dangling tags, no tag naming an excluded stub, no untranslated non-stub instance. No `skip`/`xfail`/placeholder anywhere; no duplicate test function names.
- **No forbidden vocabulary** (scaffold / yaml / instance / recipe / design-index words) anywhere outside the single `Design:` line per test; no test file mentions `workspace` or `implementation`.
- **`python3 -m compileall -q test_helpers test_suite` -> exit 0** (no output, no syntax errors). Each writer also reported clean `py_compile` + `pyflakes`.
- Writers verified all docstring PRD quotations byte-verbatim against `workspace/PRD.md` by script (A1 72 quotes, B4 150 quotes, B5 and B2 full sets); one line-wrap defect found and fixed in B5.

## Write-scope proof

Both dirs resolve at the task root. The three SCAFFOLD files and `worklog.md` all predate the Stage 1 (01:43-01:55) and Stage 2 (02:09+) writes, so none were touched. `.scratch/` still contains both `step2/` and `step5/`. `__pycache__` dirs from the import smoke test were removed.

**One flag for the orchestrator:** `workspace/` contains `INSTRUCTION.md`, `PRD.md` **and** `implementation/` (mtime 02:09). The `implementation/` directory is the concurrent Step 6 generator's output — never read, created, or modified by Step 5, and `INSTRUCTION.md` was never read.

## Step 6: Generate implementation (subagent, prd-bench-implementation-generator) — 2026-09-06T02:35:00.000Z

Launched concurrently with Step 5 in the same assistant message. Orchestrator verification after exit: `workspace/implementation/` exists with `start.sh`; `compileall` clean.

Subagent summary (verbatim):

Implementation complete.

## Modules (`workspace/implementation/`, 3933 lines total)

| File | Lines |
|---|---|
| `app.py` | 88 |
| `store.py` | 146 |
| `errors.py` | 111 |
| `response.py` | 59 |
| `validation.py` | 325 |
| `calc.py` | 418 |
| `recompute.py` | 165 |
| `serialize.py` | 285 |
| `lookup.py` | 76 |
| `cascades.py` | 100 |
| `routes/__init__.py` | 0 |
| `routes/clock.py` | 18 |
| `routes/material_specifications.py` | 79 |
| `routes/material_lots.py` | 147 |
| `routes/product_specifications.py` | 99 |
| `routes/design_control_records.py` | 150 |
| `routes/reagent_lots.py` | 323 |
| `routes/fill_runs.py` | 263 |
| `routes/test_results.py` | 259 |
| `routes/stability_studies.py` | 165 |
| `routes/bridging_studies.py` | 116 |
| `routes/complaints.py` | 200 |
| `routes/distribution.py` | 175 |
| `routes/allocations.py` | 157 |
| `start.sh` (chmod +x) | 8 |
| `requirements.txt` | 1 |

## Endpoints: 61/61 — none omitted
Verified mechanically: extracted the 61 method+path rows from the PRD §4 table, extracted `app.url_map` (61 method/rule pairs, excluding HEAD/OPTIONS/static), normalised path params, and `diff` reported **ENDPOINTS_MATCH** — an exact set equality with no extras and no gaps.

## compileall
`python3 -m compileall -q .` -> clean, exit 0 (`COMPILEALL_OK`). Every module also passed `py_compile` individually as it was finished.

## Smoke transcript (final run: "SMOKE OK — every assertion matched")
- **Ladder/auth:** no headers -> `401 ERR_UNAUTHENTICATED`; QCAnalyst POST spec -> `403 ERR_FORBIDDEN_ROLE`; unknown id -> `404 ERR_MATERIAL_SPECIFICATION_NOT_FOUND`; `?limit=0` -> `400 ERR_INVALID_REQUEST`; unrouted path -> `404 ERR_NOT_FOUND`; wrong method on a real route -> `405 ERR_METHOD_NOT_ALLOWED`; POST with no body -> `400 ERR_INVALID_REQUEST`.
- **Creates across distinct aggregates (all 201):** material-specification, material-lot, test-result x7, product-specification, design-control-record x4, reagent-lot x2, lot component, fill-run x2, monitoring sample, stability-study x3, bridging-study, complaint, distribution-order x5.
- **Full happy-path chain:** clock set -> spec -> lot -> 2 acceptance tests -> `QUALIFY` (QUALIFIED, avail 1000, v4) -> product spec -> DESIGN_INPUT->OUTPUT->VERIFICATION+VALIDATION all approved -> clearance `CLEARED` (`design_trace_complete` true) -> reagent lot -> component dispensed -> fill run scheduled/started/sampled/completed -> release test -> `RELEASE` (RELEASED/AVAILABLE, expiry 2028-08-01, 500 avail) -> order -> allocate (`ALLOCATED` 200/0, v2) -> ship (`SHIPPED`, `shipped_at` from logical clock, v2) -> cold-chain event (`EXCURSION_ACCEPTABLE`, 30.0 min / 12.5 C) -> delivery-confirmed event -> `DELIVERED` -> order cascades to `CLOSED`. Finished-goods ledger asserted balanced (filled 500 = avail 300 + shipped 200).
- **409 state conflicts:** `ERR_MATERIAL_LOT_STATE_INVALID`, `ERR_REAGENT_LOT_STATE_INVALID`, `ERR_ORDER_STATE_INVALID` (second allocate), `ERR_ALLOCATION_STATE_INVALID` (cold-chain on RESERVED, double ship), `ERR_COMPLAINT_STATE_INVALID` x2, `ERR_STABILITY_STUDY_STATE_INVALID`, `ERR_BRIDGING_STUDY_STATE_INVALID`, `ERR_DUPLICATE_MATERIAL_CODE`, `ERR_DUPLICATE_TIMEPOINT`, `ERR_FILL_LINE_CONFLICT`, `ERR_CHAMBER_CAPACITY_EXCEEDED`, `ERR_DESIGN_TRACE_INCOMPLETE`, `ERR_SHIP_BY_PASSED`, `ERR_SHELF_LIFE_TOO_SHORT`, `ERR_ALLOCATION_SHORTFALL`, `ERR_MALFUNCTION_REPORT_PENDING`.
- **412 OCC (both guarded endpoints):** `ERR_STALE_PRODUCT_SPEC_VERSION`, `ERR_STALE_REAGENT_LOT_VERSION`.
- **403 SoD:** analyst signing own release data, and the lot's releaser deciding its own field action.
- **400/422:** `ERR_SUBJECT_FIELD_MISMATCH`, `ERR_TIMEPOINT_NOT_PLANNED` (422), `ERR_PAIRED_DATA_MISSING` (422).
- **Paginated list:** `GET /distribution-orders/{id}/allocations?limit=1` -> `response_type: array`, meta `{limit:1, offset:0, total_count:1, has_more:false}`; `GET /reagent-lots?limit=1&offset=0` likewise.
- **FEFO policy gate:** `FEFO_STRICT` shortfall -> 409 and the order verified still `DRAFT`/0 units/`version` 1 (nothing persisted); `FEFO_WITH_SHORTFALL` -> `PARTIALLY_ALLOCATED` 300/99700; cancel -> exact compensation.
- **Recall cascade:** `REMOVAL` field action -> lot `RECALLED`/`BLOCKED` with 10 units quarantined (the SHIPPED reservation; the DELIVERED one untouched, per PRD), critical raw-material lot `QUARANTINED`, product `WITHDRAWN`, complaint closes only after the malfunction report.
- **Stability:** conclude -> `COMPLETE`, last conforming month 3, shelf life 3 months, method `REAL_TIME_LAST_CONFORMING`.

## State is in-memory only, no seeding
Grep across the implementation for `sqlite|shelve|pickle|json.dump(|open(` returns **nothing**; the only `seed` hits are two docstring sentences. Storage is plain dicts in `store.Store`, rebuilt by `reset()` at import.

**Re-boot check:** after killing the first server, a second `bash start.sh` on the same port returned `total_count 0, items 0` for all ten list collections, and the logical clock read the untouched default `2026-08-01T00:00:00.000Z`.

## Process hygiene
No `pkill`/`killall`/pattern kill was ever run. Each server was launched on an explicit high random port with its PID captured via `$!` and killed by that exact PID. Scratch dir `.scratch/step6` was used and removed (`rm -rf .scratch/step6` only — sibling `.scratch/step2` and `.scratch/step5` intact).

## Step 7: Run tests and iterate (long-lived fix subagent) — 2026-09-06T03:10:00.000Z

Orchestrator independently verified the sweep artifacts rather than trusting the report: all 8 `workspace/implementation/results.$i.json` exist (~95 KB each, mtime 03:05) and each parses to `passed=280 total=280 failed=0 errors=0`. The sweep was launched via the pre-written `workspace/sweep.sh` under `setsid nohup` with a `SWEEP_DONE` sentinel, per-round logs (`round.$i.log`), and the mandatory `cd $IMPL && bash start.sh` start-command — so neither the reaping failure mode nor the inline-quoting failure mode applied. Step 7 applied 1 `implementation/` fix, so Step 8 is NOT skipped.

Subagent summary (verbatim):

Step 7 complete — clean sweep on iteration 2.

## Summary

**Iterations run:** 2 (iteration 1: 276/280 in all 8 rounds, same 4 deterministic failures; iteration 2: clean).

**Tests deleted:** none. All four failures traced to rules PRD.md verbatim-covers and uniquely determines (STEP 1a and 1b both passed for each), so the fairness contract required fixing the artifacts, not deleting tests.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — `assert_order_shortfall_consistent` applied §3.9's post-allocation "ongoing rule" (`shortfall = requested - allocated`) to *every* order, including freshly created ones. §3.9 states explicitly "Orders are created in `status` `DRAFT` with `allocated_units` and `shortfall_units` both 0", and allocation always leaves `DRAFT`, so a `DRAFT` order has by definition never allocated. Added a `DRAFT` branch asserting both counters are 0; the derived rule now governs only post-allocation states. (Audited all 11 call sites; only `test_05:176` targets a never-allocated `DRAFT` order.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_cross_entity_gating_overlap_and_conservation.py` — `test_a_refused_protocol_leaves_two_live_studies_on_file` expected its second probe, mid-December `[12-05, 12-10)`, to be refused, but with only studies A `[09-01, 12-01)` and B `[10-01, 2027-01-01)` on file, A's *exclusive* `protocol_end` means mid-December overlaps B alone — the probe is the chamber's second occupant and §3.6 requires it to be **accepted**. The test contradicted the half-open rule it cites. Swapped the second probe for new `_LATE_NOVEMBER_*` constants `[11-20, 11-30)`, which genuinely share instants with both live studies, preserving the test's intent (two refusals, then the listing shows only the original two). `_MID_DECEMBER_*` is left in place for `test_the_saturating_pair_shifts_as_the_schedule_fills`, where three studies exist and the refusal is correct.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/complaints.py` — `decide_field_action` carried an extra gate raising `ERR_REAGENT_LOT_STATE_INVALID` when a `CORRECTION`/`REMOVAL` named a lot not in `disposition_status` `RELEASED`, placed *ahead* of rung 96, so it pre-empted `ERR_FIELD_ACTION_NOT_JUSTIFIED` (2 failing tests). §3.8 enumerates the field-action branch's gates exhaustively — complaint state, segregation of duties, and `REMOVAL` requires `HIGH` severity — and none is a lot-state gate; the "which must be in `disposition_status` `RELEASED`" phrase belongs to recall-cascade Hop 2, carries no error code, and has no rung on the §2.6 ladder (rung 60's target resource here is the complaint). Deleted the gate. Verified no test in the suite expects `ERR_REAGENT_LOT_STATE_INVALID` from this endpoint (all 8 occurrences are disposition/component/allocation flows), and `recall_lot` was left untouched since no PRD sentence conditions its hops.

**Judgement call recorded:** I deliberately did *not* add a compensating guard inside `cascades.recall_lot`. PRD says "every hop of it is mandatory", and inventing an unstated conditional would breach the "never add behavior that does not trace to a verbatim PRD sentence" rule; no test exercises a `CORRECTION`/`REMOVAL` on a non-`RELEASED` lot.

**Final per-round results (all 8 rounds, left in `workspace/implementation/`):** rounds 1-8 all 280/280. Zero failures, zero errors, zero skips in every round. `worklog.md`, `PRD.md`, the scaffolds, and sibling `.scratch/` step dirs were never touched; no pattern kills were issued.

## Step 8: Finalize PRD — align documentation to implementation (subagent) — 2026-09-06T03:16:00.000Z

Not skipped: Step 7 applied 1 `implementation/` fix (plus 1 `test_suite/` and 1 `test_helpers/` fix), so the skip condition (zero fixes of any kind) did not hold. Orchestrator verification: `PRD_FINALIZED.md` is 465 lines / 113,540 bytes vs `PRD.md` 465 lines / 112,584 bytes; `diff` shows 3 hunks / 6 changed lines — so it is NOT byte-identical, and it ends on the same real section boundary (final `ERR_ALLOCATION_SHORTFALL` row of the §5 table). All 8 `results.*.json` still present and `PRD.md` unmodified.

Subagent summary (verbatim):

Done.

## Result

`PRD_FINALIZED.md` created as a 3-hunk minimal patch of `PRD.md`. Both files are **465 lines** (0.0% line delta); byte size 112,584 -> 113,540 (+0.85%). Both end at the identical final §5 error-table row `| ERR_ALLOCATION_SHORTFALL | 409 |`. `diff` hunk count: **3**. No other file created or modified outside `.scratch/step8/`.

## Changes

- **§3.8 (field-action branch)** — *insert* — pinned the gate list as exhaustive: the implicated lot's `disposition_status`/`distribution_status` are never examined, `ERR_REAGENT_LOT_STATE_INVALID` is unreachable from this endpoint, and no lot-state check exists to pre-empt rung 96 — `implementation/routes/complaints.py:139-167`
- **§3.8 (recall cascade Hop 2)** — *revise* — replaced the gate-flavoured "which must be in `disposition_status` `RELEASED`" with an explicitly unconditional Hop 2 that recalls/blocks the lot "whatever those two dimensions held before" — `implementation/cascades.py:31-37`
- **§3.9 (Phase 4 ongoing rule)** — *revise* — scoped the derived-counter rule to orders that have **left** `DRAFT`, and stated that a `DRAFT` order keeps both counters at 0 (fresh booking and post-`FEFO_STRICT`-rejection alike) — `implementation/routes/distribution.py:42-43`, `implementation/recompute.py:69-75`

## Per-edit pre-edit search log

**Edit 1 — subject: gating of `POST /complaints/{id}/field-action`.**
(b) Read `routes/complaints.py` in full (all five complaint endpoints); grepped `ERR_REAGENT_LOT_STATE_INVALID` repo-wide (only `routes/reagent_lots.py:305-319` `move_distribution_status`, plus disposition/component/allocation flows — none in complaints); grepped `disposition_status` repo-wide (17 sites); re-read §2.6 rungs 50/60/96.
(c) Softened "nothing may pre-empt rung 96" to "no lot-state check exists to pre-empt rung 96" — the original phrasing was a false universal, since rungs 50 (SoD) and 60 (complaint state) legitimately do pre-empt rung 96 in the impl's own ordering.

**Edit 2 — subject: the transition of a finished lot into `disposition_status` `RECALLED` and `distribution_status` `BLOCKED`.**
(b) Read `cascades.py` in full; confirmed `cascades.py:34` is the **only** writer of `RECALLED` and that `recall_lot`'s sole caller is `decide_field_action`; confirmed `create_complaint` performs only an FK lookup on `reagent_lot_id` (no state gate); checked `bridging_failure`'s Hop 2b (`distribution_status` -> `BLOCKED` only from `AVAILABLE`) to be sure the "whatever those two dimensions held before" phrasing stayed scoped to the recall hop.
(c) Kept "in the ordinary course a lot in `disposition_status` `RELEASED`" as descriptive colour and confined the unconditional claim to Hop 2 — §3.7's Hop 2b genuinely *is* conditional on `AVAILABLE`.

**Edit 3 — subject: order `allocated_units` / `shortfall_units` derivation.**
(b) Enumerated every writer: `routes/distribution.py:42-43` (creation, both 0), `routes/distribution.py:156` (allocate Phase 4), `routes/allocations.py:99` (cancel), `routes/allocations.py:150` (cold-chain `EXCURSION_REJECTED`), `cascades.py:67` (recall Hop 4); read `recompute.order_rollup`. Also checked `ship_allocation` — it does not call `order_rollup`, but `RESERVED`->`SHIPPED` leaves the sum unchanged. Confirmed the `FEFO_STRICT` rejection path raises before any write.
(c) Wrote the scope as "every order that has left `DRAFT`" rather than naming specific statuses; added the explicit `FEFO_STRICT` clause because that is the one path where a `DRAFT` order has non-zero `requested_units` and an allocation attempt already behind it.

## Items requiring no PRD change

- **`test_helpers/assertions.py` DRAFT branch** — partially in scope: the helper bug itself was a fixture bug, but it exposed a real self-contradiction in §3.9. Edit 3 closes that; the creation sentence was already correct and is left verbatim.
- **`test_suite/test_03` mid-December probe** — **no PRD change**. §3.6 already pins the half-open interval and aggregate capacity 2 over "any single instant", verbatim and uniquely; `routes/stability_studies.py:22-47` `_peak_occupancy` implements exactly that. The test simply contradicted the rule it cited.
- **Step 7's judgement call not to add a guard inside `cascades.recall_lot`** — covered by Edit 2's "the hop is unconditional" wording.

## Step 9 plan (orchestrator decision) — 2026-09-06T03:16:00.000Z

Step 9 is run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, plus a fourth reconciliation pass. Rationale: a single agent asked to scan 24 modules / 61 endpoints against a 465-line PRD reliably under-scans and can return a byte-identical file (the tell that the scan never ran); partitioning by implementation module bounds each pass's reading load. Pass 1 alone performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; later passes must not, or they would discard their predecessors' edits. Shared base instructions live in `.scratch/step9/BASE.md`.

- Pass 1 — cross-cutting core: `app.py`, `store.py`, `errors.py`, `response.py`, `validation.py`, `lookup.py`, `serialize.py`, `routes/clock.py` -> PRD §2.1-§2.10.
- Pass 2 — materials, design control, lot build, release testing: `routes/material_specifications.py`, `material_lots.py`, `product_specifications.py`, `design_control_records.py`, `reagent_lots.py`, `fill_runs.py`, `test_results.py` and the `calc.py`/`recompute.py` functions serving them -> PRD §3.1-§3.5.
- Pass 3 — stability, bridging, complaints, distribution: `cascades.py`, `routes/stability_studies.py`, `bridging_studies.py`, `complaints.py`, `distribution.py`, `allocations.py` and the `calc.py`/`recompute.py` functions serving them -> PRD §3.6-§3.9.
- Pass 4 — reconciliation: resolve every `CROSS-PASS CONTRADICTION` the first three passes report, re-check §4/§5 tables against the implementation's route map and error catalogue, and verify no truncation.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (4 sequential subagent passes) — 2026-09-06T04:35:00.000Z

Executed as the four partitioned passes planned above. Pass 1 performed the single `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2, 3 and 4 were explicitly forbidden to copy and edited the shared file in place. Total 64 in-paragraph edits (14 + 22 + 20 + 8), no new sections.

Orchestrator's independent final verification:
- `wc -l -c`: PRD.md 465 / 112,584 · PRD_FINALIZED.md 465 / 113,540 · PRD_COMPLETED.md 470 / 143,315.
- NOT byte-identical to PRD_FINALIZED.md: md5 `dcf8e30b0639fa382c4777123c640136` vs `b0470986811ef0f365090a63832f33c3`; `diff` shows 133 changed lines. (Pass 4 reported the COMPLETED md5 as `ea6bba16…` at the same 143,315 bytes — it evidently hashed before its final equal-length edit. The line/byte counts and the structural checks below all reconcile, so this is a stale hash in its report, not a content problem.)
- Ends at the final §5 row `| ERR_ALLOCATION_SHORTFALL | 409 |` with a trailing `0x0a`; not truncated.
- `grep -n '^#'`: 27 headings — title, §1, §2, §2.1-§2.10, §3, §3.1-§3.9, §4, §5, plus the two `####` sub-headings in §2.2. All present, in order, none lost or duplicated across four in-place editing passes, no new section added.
- Table integrity: §4 has 63 pipe lines (header + separator + 61 endpoint rows), §5 likewise 63 (header + separator + 61 error rows). 4 code fences (balanced). No conflict/stray markers.
- All 8 `workspace/implementation/results.*.json` still present; `PRD.md` and `PRD_FINALIZED.md` unmodified.

### Pass 1 — cross-cutting core (`app.py`, `store.py`, `errors.py`, `response.py`, `validation.py`, `lookup.py`, `serialize.py`, `routes/clock.py`) -> §2.1-§2.10

14 edits: 13 ambiguity-pins, 1 mismatch-revision. Highlights: §2.1 whitespace-only header counts as empty (401) and 401 is the only such condition, role names matched case-sensitively so an unrecognised non-blank role is 403 never 401, routing-layer 404/405 bypass both header checks; §2.2 `api_request_id` = `req_` + exactly 20 chars of `A`-`Z`/`0`-`9` fresh per response, `api_request_timestamp` from real wall-clock not the logical clock, `data` a bare array for collections and `[]` when empty, pagination keys on list endpoints only; §2.2 error heading **mismatch** — PRD said "4xx status codes" but the same envelope carries 405 and 500; the three transport-level ids (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500) decided by routing ahead of authentication, unparseable/non-object body -> `ERR_INVALID_REQUEST` 400, 415 remapped to 400, absent body read as `{}`; §2.3 non-integer limit/offset -> 400, `offset >= total_count` legal, the paginated shape governs every list endpoint with no unpaginated variant anywhere; §2.4 `id` is a canonical lower-case v4 UUID, instants always carry the `.000`-style fraction and a literal `Z`, and the store boots completely empty; §2.4 `created_at`/`updated_at` are the deliberate wall-clock exception, clock may move backwards, a clock move versions nothing; §2.5 expected-version fields are integer-typed so a string/bool/`1.0` is 400 at rung 30 not 412, and a rejected OCC check is a complete no-op; §2.6 evaluation stops at the first failing rung and a failed request is a complete no-op, rung-30 presence->type->bound ordering, explicit `null` semantics, query values validated at rung 30 ahead of path resolution; §2.7 rounding governs the stored value not the JSON spelling; §2.9 the generic SoD mechanism is exact case-sensitive equality and a `null` stored id can never match; §2.10 one request bumps a row's `version` by exactly 1 and the two immutable event records carry no `version`.

Notable NO-NEW-MISMATCH corrections it made to its own drafts: dropped an unverifiable claim about padded header values (HTTP strips optional whitespace before the app sees it); carved zero-initialised counters out of the "nullable numeric serializes as `null`" rule; scoped "duplicate array elements are not rejected" to that rung so it cannot conflict with the strictly-increasing timepoint rule. It reordered no rung — the PRD's stated ladder matched the code everywhere it checked.

### Pass 2 — materials, design control, lot build, filling, release (7 route modules + serving `calc.py`/`recompute.py`/`serialize.py`) -> §3.1-§3.5

22 edits: 20 ambiguity-pins, 2 mismatch-revisions. §3.3 needed no edit. Mismatches: §3.4 "an aborted run keeps its samples on file, but they no longer feed any lot disposition decision" was false in both halves — aborted runs' samples still feed the lot's `em_excursion_count`/`bioburden_cfu_per_ml`, and abort never re-derives the run's `environmental_state`, so a run that was `DISQUALIFIED` when aborted still blocks release at rung 80 (with a fully reachable path given); §3.1 the purity sub-score is `min(1, v/100)` — capped above but never floored, so "between 0 and 1" over-claimed. Pins include: the latest-per-code tie-break's third key (insertion order), `reason` type-checked then discarded on all three disposition endpoints, `INVESTIGATE` with no failing measurement is `ERR_MATERIAL_LOT_STATE_INVALID` and stamps neither disposition field, the retest-window rung is skipped when `first_oos_at` is null, an unresolvable `traces_to_record_id` is 404 at rung 45 even on a `DESIGN_INPUT`, the supersede scan is exhaustive, the four `sample_type` enum members (`VIABLE_AIR`, `SURFACE`, `NONVIABLE_PARTICLE`, `BIOBURDEN_BULK`) which appeared nowhere in the PRD, the two parent-lot preconditions on fill start raise the lot's code not the run's, `shelf_life_basis` is written as the literal `CLAIM` when omitted, a rejection leaves the six release-evidence fields null, and `WITHHELD` is never a legal distribution target.

### Pass 3 — stability, bridging, complaints, distribution (`cascades.py` + 5 route modules + serving helpers) -> §3.6-§3.9

20 edits: 16 ambiguity-pins, 4 mismatch-revisions. Mismatches: `bridging_required` is recomputed at three moments not two (dispense, run completion, **and run abort**); bridging failure hop 2 is conditional on `QUALIFIED` with an exact reason string, and hop 2b widened to "not currently `AVAILABLE`"; recall hop 3's exact `quarantine_reason` string with `DELIVERED`/`CANCELLED` reservations left alone, hop 3b forcing `available_quantity_units` to 0, hop 4 visiting only orders that lost a reservation; rider 2 corrected from "the only RELEASED lot" to "**no other** lot is RELEASED". Pins include: chamber capacity is a peak-occupancy sweep over the clipped half-open window with close-before-open at equal instants (three mutually non-overlapping live studies do not block), the accelerated shelf-life floor carries a 1e-9 tolerance and a chamber colder than reference gives a factor < 1, `last_conforming_month` 0 is usable, the stability-abort hop is selective so a `PROTOCOL_DRAFT` study on a recalled lot keeps its status and still occupies its chamber, `report_due_at` uses plain 24-hour days, the three field-action gates answer in ladder order, a past `ship_by` is accepted at booking and only allocation refuses it, the non-`AVAILABLE` lot at shipment is `ERR_REAGENT_LOT_STATE_INVALID`, `delivery_confirmed` defaults to false, `INTACT` when cumulative excursion is "0 or below", and closure requires every reservation row of any status to be `DELIVERED` so one `CANCELLED`/`QUARANTINED` sibling blocks `CLOSED` permanently.

### Pass 4 — reconciliation -> §2.10, §3.1, §3.3, §3.4, §5

8 edits: 1 ambiguity-pin, 7 mismatch-revisions. This pass exists because a module-partitioned scan structurally cannot close cross-partition defects, and it earned its place:

- **TASK A settled the contradiction passes 2 and 3 both reported but neither was allowed to fix.** §2.10's universal claim that "a row a cascade reaches but does not in the end need to change is not touched" was false at three confirmed sites (`design_control_records._refresh_parent`, `fill_runs.record_sample`, `cascades.recall_lot` hop 2 on a reachable second recall) **plus a fourth that neither earlier pass found**: `fill_runs.py:201-207`'s abort ledger hop touches `material_lot` once per returned dispensing row with no dedup, and `dispense_component` has no uniqueness gate on (reagent_lot, material_lot) — so a raw lot dispensed twice into one finished lot has its `version` raised by 2 on abort, which also falsified §3.4's own "increased by 1". §2.10 now distinguishes state-conditional hops (skip non-qualifying rows, which keep `version` and `updated_at`) from unconditional hops, names the abort's per-row exception, and confines the change-gated behaviour to `recompute.bridging_study_figures` — verified to be the only change-gated touch in the entire codebase, and reached only from §3.5, not §3.7. Two further §2.10 internal errors fixed while there: the recall coupling was attributed to §3.5 instead of §3.8, and "the four multi-hop cascades" should be five.
- **TASK B verified §4 and §5 programmatically and needed no corrections to either table.** §4's 61 (method, path) pairs are exactly the 61 `@bp.*` routes after `{id}`/`<param>` normalisation — zero extra, zero missing — and all 61 role lists match `authenticate_and_authorize` including `ALL_ROLES` expansion. §5's 61 IDs and statuses are identical to `errors.ERROR_STATUS` with zero status mismatches and the same order. One real inconsistency fixed: §5's intro said "Every failure … carrying the `error_id` from the table below", a false universal contradicting pass 1's §2.2 prose about the three transport-level IDs. Explicit decision recorded: the three stay OUT of the table, and §5's intro now scopes itself to workflow failures and names them as deliberate non-rows.
- **TASK C found one genuine seam defect** in a shared helper: `calc._latest_key` ranks on stored microsecond-resolution values while `fmt_ts` renders three digits only at serialisation, so §3.1's "when both instants tie at the rendered millisecond" understated the tie condition. Fixed; the word "millisecond" now appears nowhere in the PRD. §3.7's parallel sentence was already correct. All 12 status enums checked for a value written by one section's cascade but omitted where the enum is declared — none found. §1 misstates nothing.
- **TASK C also pinned the fact §3.4's new wording depends on**: §3.3 declared "four safety gates guard every dispensing call" but never said a raw lot may be drawn into the same finished lot twice — now stated, with no fifth uniqueness gate and no deduplication of the pairing or `component_role`.
- **TASK D**: protected-file baselines verified with two md5 manifests (7 top-level files; 104 entries across `implementation/`, `test_suite/`, `test_helpers/`) — 0 failures, all 8 `results.*.json` present and unchanged. Whole-PRD editing-damage scan (duplicated sentences, broken clauses, malformed table rows, unbalanced code fences, stray markers) found nothing to fix.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; the implementation stands at 280/280 across all 8 sweep rounds and was not modified after Step 7.
