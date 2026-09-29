# Worklog — task_2971_cement_plant_kiln_operations

## Step 1: Create task directory — 2026-09-05T23:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2971_cement_plant_kiln_operations` and `.../workspace`. Index 2971 was pre-assigned by the orchestrating invocation (no scan of ./tasks/, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-06T01:13:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output files

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2493 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (contains neither design key) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1082 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2388 | `scaffold_corner_design` only |

`workspace/`, `worklog.md` and the `.scratch` parent are intact; only `.scratch/step2` was removed.

## SCAFFOLD.yaml counts
15 entities, 9 state machines, 3 concurrency rules (OCC only), 9 calculations, 50 ordered validations, 73 endpoints, 74 errors, 8 roles. `api_prefix: /cement-ops`, difficulty `expert_plus`, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

## §1.8 — 9 rule ids / 20 instances
`dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## §1.9 — 9 sections / 126 instances (84 real + 42 `excluded_because` stubs)
entities 11 (11/0), state_machines 23 (16/7), calculations 16 (9/7), validations 15 (9/6), endpoints 6 (6/0), errors 28 (12/16), rbac 13 (13/0), cross-cutting complexity layers 12 (6/6), consistency model 2 (2/0).

## Verification
- All 146 instance names unique across the union of both design files; all 42 `excluded_because` citations resolve to a real §1.8 instance (normalized to the spec's `rule_id / instance_name` composite form — 22 bare-name citations were rewritten).
- Error-triggerability audit: 0 of 74 declared error ids uncovered.
- Forbidden concurrency vocabulary: zero hits (two innocuous uses of "simultaneously" were reworded).
- SCAFFOLD §1.8/§1.9 -> §1.5 lint: VERDICT clean — 73 endpoints, 15 entities, 20 §1.8 instances, 84 §1.9 instances, 2767 calls scanned; all calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

## Design adjudications
1. `_refuses_` is not a lint negative-name pattern, so the three OCC instances are fully role-legal and payload-complete; every `expected_*_version` value carries a `${...}` placeholder.
2. The DRAFT-certificate path to `ERR_CERTIFICATE_NOT_ISSUED` cannot be produced by revoking a certificate (revocation blocks the cement silo and rule 62 then outranks rule 105), so a second DRAFT certificate is minted instead.
3. An alternative fuel with no burn test is refused outright with `ERR_BURN_TEST_NOT_AUTHORIZED`; the test charges only 5.00 t so the assertion holds under either reading of the TSR ordering.
4. `ERR_SILO_CAPACITY_EXCEEDED` is asserted on `POST /kiln-runs/{id}/complete` — clinker is credited at complete, not at release.
5. Peak-season override is a role-conditioned *payload* privilege: a ProcessEngineer sending `peak_season_override: true` gets 422 `ERR_PEAK_SEASON_OUTAGE`, not 403.
6. Rule 87 (outage conflict, 409) outranks rule 108, so an August outage colliding with a run answers `ERR_OUTAGE_WINDOW_CONFLICT`.
7. Customer scope splits three ways: single foreign read → 403 `ERR_CUSTOMER_SCOPE_VIOLATION`; list read → 200 filtered to `total_count 0`; endpoint without the Customer role → 403 `ERR_UNAUTHORIZED`.
8. Design SoD compares `X-User-ID` with `created_by_user_id` (explicit `as_user_id` literals); burn-test SoD bars only the result recorder, not the requester.
9. OCC guards precede capacity/availability rules, so a stale version beats `ERR_INSUFFICIENT_CLINKER`; conversely rule 104 (`ERR_INSUFFICIENT_CEMENT`) precedes rule 107 (`ERR_DRAW_RATE_EXCEEDED`), asserted in the rate-threshold instance.
10. Chain reuse is via flat YAML alias lists (9 chain anchors, 37 call anchors); extra per-instance setup is placed at the head of `trigger`, which the linter walks as calls.

Orchestrator verification: grep for the difficulty directive ("harder than expert") across the whole task dir returned no hits — the directive did not leak into any scaffold artifact.

## Step 3: Copy INSTRUCTION.md — 2026-09-06T01:14:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T01:33:00.000Z

PRD generation is complete.

**Deliverable:** `workspace/PRD.md` — **539 lines / 115,002 bytes**, built incrementally (1 `Write` + 7 appends), so nothing was lost to the output cap. `worklog.md`, `workspace/INSTRUCTION.md` and all three `SCAFFOLD*.yaml` files are untouched; the two `SCAFFOLD_*_DESIGN.yaml` files were never opened or grepped, and no sibling task directory was read. `.scratch/step4` removed; the `.scratch` parent left in place.

**Ends at a real section boundary:** the last line is the complete table row `| ERR_DRAW_RATE_EXCEEDED | 422 |`, the 74th and final row of §5. No mid-sentence or mid-row truncation, and no audit footer inside the document.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Identity & RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination & List Ordering, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Measurement Precision & Rounding, 2.6 Stale-Read Protection, 2.7 Two-Person Controls, 2.8 The Validation Ladder, 2.9 Silo Inventory Accounting, 2.10 The Air Permit Envelope, 2.11 Cement Type Specifications, 2.12 Cascade Propagation/Compensation/Plant Posture
- §3 Business Logic & Workflows: 3.1 Designing the Raw Mix, 3.2 Blending the Pile, 3.3 Qualifying Fuels, 3.4 Kiln Assets/Firing Windows/Outages, 3.5 Pyroprocessing, 3.6 Laboratory/Clinker Release/Availability Cascade, 3.7 Finish Milling & Cement Qualification, 3.8 Silo Blocking & Feed Reconciliation, 3.9 Customers/Certification/Loadout/Distribution Planning
- §4 API Endpoint Definitions
- §5 Error Code Catalogue

**Completeness self-audit (documented vs scaffold)**

| Item | Scaffold | Documented |
|---|---|---|
| Entities | 15 | 15 |
| State machines / transitions | 9 / 43 | 9 / 43 |
| Calculations | 9 | 9 |
| Validations (priority rungs) | 50 | 50 (all 50 priority numbers, plus the 3 deliberate collisions) |
| Concurrency rules | 3 | 3 |
| Endpoints | 73 | 73 table rows, 4 columns |
| Errors | 74 | 74 table rows, 2 columns; all 74 also referenced in §1–§4 prose |
| Roles | 8 | 8 |

**Hard Contract audits (mechanically verified, report kept out of the document)**
- **Contract 1 — Field-Name Coverage: PASS.** All 185 deduplicated required identifiers (entity fields + request bodies + query/path params) appear verbatim in backticks; 0 missing. A broader sweep of all 256 snake_case identifiers in the calculations and state-machine sections left only scaffold-internal artefacts unmentioned (rule names like `silo_not_blocked`, calculation names, `algorithm_type` labels, and math index variables such as `dry_tonnes_i`) — no API-visible name. Every declared calculation output field is present.
- **Contract 2 — Rule Coverage: PASS.** All 43 transitions now appear in explicit `FROM -> TO` arrow form (arrows added for `BURNING -> ABORTED`, the three void transitions and the two `CANCELLED_BY_QUALITY` transitions, which had been prose-only); all 50 ladder priorities, all 3 OCC rules, all 3 segregation pairs, both cascades (3-hop availability, 4-hop decertification), both compensations, all field defaults and both fork branches with their join are documented. Constants including `KILN_FEED_FACTOR` 1.55, `MAX_DESIGN_REVISIONS` 3 and the four-row `CEMENT_TYPE_SPECS` table are given as numbers.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path. The only `/`-prefixed backtick token in the whole document is `/cement-ops` in §1 and the §4 preamble.

Also verified: no pseudocode operators (`==`, `<=`, `+=`, `min(`, `round(`, `IN {`) and no fuzzy words ("approximately", "roughly", "and so on", "etc.") anywhere in the file.

Three scaffold preconditions carry no `error_id`; resolved without inventing identifiers — the burn-test authorization ceiling checks and the loadout `loaded_tonnes` bound map to `ERR_INVALID_REQUEST` (consistent with the priority-40 shape rung, which already covers numeric-range cases), and the "no fuel charged" completion check maps to `ERR_INVALID_RUN_STATE`.

Orchestrator verification (truncation guard): `wc -l` = 539; `tail` confirms the file ends on the complete final row of the §5 error table, a real section boundary — not mid-sentence. Section headings present: §1 (line 3), §2 (11), §3 (218), §4 (380), §5 (460). Leak scan for "harder than expert" / "scaffold_difficulty" / "scaffold_corner" / "test_recipe" in PRD.md: 0 hits.

## Step 5: Generate unit tests — 2026-09-06T03:50:00.000Z

Step 5 is complete. Final state of the deliverables:

## Files written (all at the task root, none under `workspace/`)

`test_helpers/` — 2130 lines total: `__init__.py` 11, `api_client.py` 451, `api_errors.py` 169, `assertions.py` 159, `constants.py` 230, `factories.py` 416, `fixtures.py` 586, `test_users.py` 96, `types.py` 12.

`test_suite/` — 9799 lines total, 167 tests: `conftest.py` 82; queue A `test_11_depth_calculations.py` 370/6, `test_12_depth_state_and_cascade.py` 375/5, `test_13_depth_priority_and_boundaries.py` 495/8, `test_14_depth_dependencies_overlap_and_compensation.py` 577/8; queue B `test_21_entities.py` 808/18, `test_22_state_machines_design_pile_and_burn.py` 406/7, `test_23_state_machines_kiln_runs_and_outages.py` 340/6, `test_24_state_machines_cement_and_certificates.py` 348/7, `test_25_calculations_kiln_and_permit.py` 393/8, `test_26_calculations_blending_and_cement.py` 350/8, `test_27_calculations_distribution_plan.py` 327/6, `test_28_validations_priority_ladder.py` 305/7, `test_29_validations_chemistry_and_windows.py` 436/9, `test_30_endpoints_customers_and_loadout.py` 343/8, `test_31_endpoints_silos_lab_and_lists.py` 404/7, `test_32_errors_not_found_and_state_gates.py` 569/10, `test_33_errors_kiln_and_permit_gates.py` 618/10, `test_34_errors_cement_and_commercial_gates.py` 628/8, `test_35_rbac_role_matrix.py` 533/7, `test_36_rbac_scoping_and_segregation.py` 459/6, `test_37_cross_cutting_layers.py` 456/6, `test_38_consistency_model.py` 177/2.

## Design-index coverage

- **Queue A (§1.8): 20 of 20 non-stub instances emitted**, across 27 tests.
- **Queue B (§1.9): 84 of 84 non-stub instances emitted**, across 140 tests — entities 11, state_machines 16, calculations 9, validations 9, endpoints 6, errors 12, rbac 13, `cross-cutting complexity layers` 6, `consistency model` 2.
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first two-condition filter, so no gaps were left and nothing was weakened, xfailed or stubbed. The 42 `excluded_because` stubs were not emitted (verified programmatically: zero tags intersect the stub name set).
- Where an individual yaml sub-assertion was not PRD-derivable the sub-assertion was dropped rather than the instance, and the intent re-realised from PRD text (e.g. the 90-minute draw-rate ceiling became a 375.01 t/1.5 h refusal ordered ahead of any reservation so the availability rung could not preempt it; two yaml slips were corrected against the PRD — outage `scope` `BURNER`/`COOLER` -> `MECHANICAL`/`COMBINED`, and a pile born `BLENDING` -> `OPEN`).

## Verification run

- Every test has **exactly one** `Design:` line (167 tests / 167 tags, checked per-test by splitting on `def test_`); no dangling tags, no dual tags, no stub tags.
- Every `PRD: "..."` citation normalises to a string occurring **exactly once** in `workspace/PRD.md` — 0 problems after fixing one truncated quote in `test_12_depth_state_and_cascade.py` (the "Hop two ... genuine availability" excerpt ended with a period where the PRD has an em dash, so it matched zero times; extended to the full sentence).
- Also fixed earlier: three `quality_state == "PENDING"` literals -> `"PENDING_LAB"` (PRD lines 272/286) in `test_32`, `test_33`, `test_35`; batch branch states legitimately remain `"PENDING"`.
- `python3 -m py_compile` clean on all files; `python3 -m pytest --collect-only -q test_suite` -> **167 tests collected, no errors**. No server started, no tests executed, no process killed.

## Misplacement check

`ls -d workspace/test_helpers workspace/test_suite` -> nothing (exit 2); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` (never read or touched). `worklog.md`, `PRD.md`, `INSTRUCTION.md` and all `SCAFFOLD*.yaml` are untouched. `.scratch/step5` removed (parent `.scratch` left in place); `__pycache__`/`.pytest_cache` byproducts cleaned.

## Step 6: Generate implementation — 2026-09-06T03:50:00.000Z

Implementation complete and verified. (Launched in the SAME assistant message as Step 5, so the impl generator started before `test_suite/` existed on disk — physical isolation, not just an instruction.)

## Modules (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `core.py` | 634 | error catalogue (74 ids -> HTTP status), `ApiError`/`fail`, Decimal + ROUND_HALF_UP helpers, logical clock, `fmt_ts`, in-memory `Store`, row lifecycle (`new_row`/`touch`/`path_row`), envelope builders, `authenticate` (rungs 10/20), `pagination` (rung 42), rung-40 field coercers, `fk_ref` (rung 35), `guard` (RLock + auth), `filtered_list` |
| `calc.py` | 606 | all constants (`CEMENT_TYPE_SPECS`, LSF coeffs, SHC tiers, `KILN_FEED_FACTOR`, seasonal factors) + the 9 calculations and every derived field |
| `serial.py` | 354 | 15 per-entity serializers; live-computed fields; `lab_test_out` is the one immutable shape (no `version`/`updated_at`) |
| `cascades.py` | 203 | 3-hop release, 3-hop re-quarantine, 4-hop certificate revocation, silo block/unblock, feed reconciliation, lab-driven quality transitions |
| `routes_master.py` | 331 | 22 endpoints — plants (+distribution-plan), raw-materials, fuels, customers, kilns, silos, clock |
| `routes_design.py` | 448 | 18 endpoints — designs, blended piles, burn tests |
| `routes_kiln.py` | 400 | 14 endpoints — kiln runs, kiln outages; window geometry helpers |
| `routes_cement.py` | 217 | 8 endpoints — cement batches, lab tests |
| `routes_commercial.py` | 332 | 11 endpoints — mill certificates, loadout orders, rung-45 Customer scoping |
| `app.py` | 64 | blueprint registration, `ApiError`/HTTPException handlers, `threaded=True`, `use_reloader=False` |
| `start.sh` | 17 | `set -euo pipefail`, `PORT` default 10000, guarded flask install, `exec python3 app.py` |

**3607 lines total.** Every module compiles.

## Coverage
- **Endpoints: 73 / 73** — counted programmatically off `app.url_map` (excluding `static`).
- **Error ids: 74 / 74** — every catalogued id is raised somewhere outside the catalogue itself (verified by script; zero unreachable).
- **Calculations: 9 / 9**; **validation rungs: 50 / 50**, first-violation-wins, with the three stated collisions honoured (62 before 103, 70 before 80, 96 before 103).
- Storage is pure in-memory dicts; no file/SQLite/`/tmp` persistence. All timestamps are `...THH:MM:SS.mmmZ` (3 fractional digits) everywhere — spot-checked across entity, list-meta and computed stamps: zero nonconforming.

## Smoke verification
Cold boot on self-chosen free port 45211 (checked free with `ss -ltn` first): **ready in 0.69 s**, `GET /cement-ops/plants` returns the empty-array envelope, state fully wiped on relaunch. Killed by listener PID only; port released. A full happy-path script (plant -> materials -> design approve -> pile seal -> kiln run light/charge/complete -> free-lime test -> clinker release -> batch grind -> Blaine + 28-day strength -> QUALIFIED -> certificate issue -> loadout order reserve/load/complete -> distribution plan -> certificate revoke cascade) passed end to end, plus negative probes for all four pagination faults, 6 not-found ids, unknown path, missing/wrong-role headers, and the Customer scope violation. Notable computed values all matched hand arithmetic (effective SHC tiered once to 3.45, clinker 6782.61 t, NOx intensity 1.035, batch cement 215.05 t / SO3 2.42, plant cement balance conserved at 215.05 across a completed loadout, revoke cascade -> batch `DECERTIFIED` + silo `BLOCKED/DECERTIFIED_CEMENT`).

Scratch (`.scratch/step6`) and its `/tmp` files removed; `.scratch/step5` and all task-root files (`worklog.md`, `SCAFFOLD*.yaml`, `workspace/PRD.md`) untouched. `test_helpers/` and `test_suite/` were never read, listed or grepped.

## PRD-silence judgement calls
1. `created_at`/`updated_at` come from a monotonic wall clock, not the logical clock — PRD 2.3 ordering, every cascade walk and the distribution tie-break need `created_at` ASC to be a total insertion order; PRD 2.4 scopes the logical clock to *computed* stamps.
2. Certificate-issue tonnage gate (rung 106) excludes the certificate being issued; the literal reading double-counts a DRAFT and makes "with equality allowed" unreachable. `certified_tonnes_allocated` is still reported as the live DRAFT+ISSUED sum, forced to 0.00 when the batch is DECERTIFIED.
3. Silo PATCH to its current status (blocking a BLOCKED silo, unblocking an OPEN one) -> `ERR_INVALID_REQUEST` 400; the catalogue has no silo-state error.
4. Outage start/complete with the clock before `window_start` -> `ERR_INVALID_WINDOW` 422; a run BURNING on the kiln at outage start -> `ERR_KILN_UNAVAILABLE` 409, checked after rung 60 and before the window check (409s precede 422s).
5. Rung 72 (TSR) is skipped when the charged alternative fuel is not currently authorized — the effective ceiling is not computable — so rung 80 reports instead: "an AUTHORIZED row exists but its window misses the clock" -> `ERR_BURN_TEST_EXPIRED`; "no AUTHORIZED row at all" -> `ERR_BURN_TEST_NOT_AUTHORIZED`.
6. Burn-test adjudicate `ERR_INVALID_REQUEST` branch checks (`stack_compliant` true, granted <= requested, granted <= `permit_max_tsr_pct`) run after the rung-60 state check; `authorized_max_tsr_pct` defaults to 0 when omitted; `adjudicated_by_user_id` is recorded on both decision branches.
7. Uniqueness of `code` / `pile_code` is **not** enforced — the complete catalogue has no duplicate error.
8. Zero-denominator / no-data cases: run `nox_intensity_kg_per_tonne` = 0.000 when `clinker_tonnes` is 0; a charge-free run reports gross 0.00 / provisional 0.00 / effective SHC 4.00 / clinker 0.00 / TSR 0.00; an addition-free pile reports as-received/dry/alt-share 0.00 and null `as_blended_*` and `lsf_deviation`.
9. Numeric inputs are echoed as supplied (not quantized); only computed values are quantized; all arithmetic goes through `Decimal(str(x))`.
10. Whitespace-only auth headers count as **present**; only the literal empty string is absent.
11. Plant `version` is never bumped by a cascade — all four plant aggregates are derived and PRD never states a plant version bump.
12. Design submit with an uncomputable `as_designed_lsf` (null / zero denominator) -> `ERR_MODULE_TARGET_DEVIATION`.
13. The ">=2 components summing to 100.00" gate is applied at design create, amend **and** submit.
14. Silo `unreleased_tonnes` / `reserved_tonnes` / `tonnes_on_hand` are stored counters mutated by PRD's explicit hop arithmetic; only `available_tonnes` is derived.
15. `nominal_shc_gj_per_tonne` must be > 0 (`ERR_INVALID_REQUEST`) to keep the provisional-clinker division defined.
16. Unmatched paths -> `ERR_INVALID_REQUEST` at HTTP 404, and disallowed methods -> `ERR_INVALID_REQUEST` at 405 (the catalogue has no routing error); the response envelope shape is unchanged.
17. Void from COMPLETED with a missing silo row -> `ERR_SILO_NOT_FOUND`; the capacity re-check (rung 102) precedes the state mutation so a refused void leaves the order COMPLETED.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`, `sweep.sh`. No stray `workspace/test_*` dirs. Orchestrator pre-wrote `workspace/sweep.sh` (setsid-launched, `SWEEP_DONE` sentinel after `wait`, per-round `round.$i.log`) so Step 7 never has to hand-quote the sweep one-liner.

## Step 7: Test-and-fix iteration loop — 2026-09-06T04:30:00.000Z

Clean sweep achieved: **8/8 rounds, 167/167 passing**.

## Summary

**Iterations run:** 3 full 8-round sweeps (iteration 1: 113/167; iteration 2: 166/167; iteration 3: 167/167 in every round).

**Fixes to `implementation/`** (1 defect, 2 call sites) — `workspace/implementation/routes_commercial.py`:
- `core.r2()` returns a **float**, so `r2(x) > D(y)` is an exact-binary comparison and `574.72 > Decimal("574.72")` is `True`. Both "with equality allowed" gates were therefore rejecting exactly-equal tonnages. Changed to stay in `Decimal`:
  - line 102 (`ERR_CERTIFIED_TONNES_EXCEED_BATCH`): `r2(others + D(cert["certified_tonnes"]))` -> `rnd(others + D(cert["certified_tonnes"]), 2)`
  - line 194 (`ERR_CERTIFICATE_ALLOCATION_EXCEEDED`): `r2(allocated + D(tonnes))` -> `rnd(allocated + D(tonnes), 2)`
  - added `rnd` to the `core` import.
- This single defect accounted for ~33 of the 54 iteration-1 failures (mostly "Setup step failed with HTTP 422"). No other implementation change was needed; the remaining 21 were all test-artifact defects.

**Fixes to `test_helpers/`:** none — no bug was found in that layer.

**Fixes to `test_suite/`** (assertion/fixture mistranslations of the PRD; all made the test *more* faithful, none weakened):
- `test_13`: 4x `charge_fuel` expected 201 -> **200** (PRD §4: every append to a collection of charges returns 200); 2x `ERR_INSUFFICIENT_CLINKER` expected 409 -> **422** (PRD §5 catalogue); `test_free_lime_exactly_at_the_plant_ceiling_is_in_spec` expected `ERR_FREE_LIME_OUT_OF_SPEC` on a `QUARANTINED` run -> **`ERR_INVALID_RUN_STATE`/409** (PRD §3.6 subject-state rung 60 precedes free-lime rung 74).
- `test_21`: dropped `assert_instant_equals(created_at, "2026-08-01T12:00:00Z")`, replaced with `assert_three_fractional_digits` — PRD §2.4's enumeration of clock-sourced timestamps pointedly omits `created_at`, and list ordering/cascade walks depend on `created_at` ascending being insertion order, so logical-clock stamping is **not uniquely derivable**.
- `test_23`: `clinker_tonnes` on a BURNING run expected 0.00 -> **583.78** (PRD §3.5: each charge recomputes the whole thermal picture; completion merely *freezes* it).
- `test_24`: a strength test recorded on a terminally `REJECTED` batch was a fixture call that violates PRD §3.7 ("must have `status` exactly `GROUND`"); replaced with an explicit `validate_error(..., ERR_LAB_SUBJECT_STATE_INVALID, 409)`.
- `test_32`: removed 2 assertions on a persisted `decision` field — PRD names `decision` only as a request input and enumerates exactly which fields each adjudication branch persists (COMPUTED/PERSISTED-FIELD SILENCE).
- `test_33`: removed 4 `alternative_energy_gj` assertions (token appears nowhere in PRD; only an unnamed intermediate of `tsr_pct` — COMPUTED-FIELD SILENCE); gave the queued run its own sealed pile (lighting *consumes* the pile and aborting never returns it, so rung 67 legitimately preceded rung 82); 3x `scope="BURNER"` -> **`MECHANICAL`** (PRD enumerates `REFRACTORY`/`MECHANICAL`/`COMBINED`); the NOx-budget test's 220000 t **coal** charge -> 500000 t **natural gas** (coal's chlorine made rung 70 fire first; gas has `chlorine_pct` 0.00 and is conventional, isolating rung 100).
- `test_34`: 3 expectations corrected — `certified_tonnes_allocated` 0.00 -> **100.00** and 0.00 -> **200.00**, plus **200.00** for the two lingering drafts (PRD §3.7 defines the field as the sum over certificates whose status is **`DRAFT` or `ISSUED`**); clinker-silo `reserved_tonnes` 500.00 -> **0.00** (PRD §3.8: starting grinding shrinks `reserved_tonnes` by `clinker_tonnes_drawn`).
- `test_36`: removed the `request_design_revision` segregation-of-duties expectation — PRD §2.8 rung 55 scopes the two-person control to "design approval, burn-test adjudication and certificate issue" only.
- `test_37`: `fx.record_strength()` returns the lab-test row, not the batch; re-read the batch via `get_cement_batch` before asserting `status == "QUALIFIED"`.

**Tests deleted:** none. Nine assertions were removed or corrected in place; every affected test kept an exact `error_id`/value assertion, and no `skip`/`xfail`/status-only downgrade was introduced.

**Notable adjudications:** PRD §3.7's definitional "Throughout, `certified_tonnes_allocated` is the sum ... whose `status` is `DRAFT` or `ISSUED`" was taken as authoritative over §3.9's looser "simply grows by the newly issued tonnage"; the implementation's self-exclusion in the exceed gate is the necessary reconciliation (otherwise a full-batch certificate could never issue). `created_at` was left on the wall clock as the implementation's documented choice, since the PRD does not uniquely determine it.

**Per-round results (iteration 3):** rounds 1-8 all `passed 167 / total 167`, union of failures empty.

`.scratch/step7/` removed; the dev server on port 21971 was killed by PID and the port is free. `worklog.md`, `PRD.md` and `sweep.sh` untouched.

Orchestrator verification (independent of the subagent's claim): all 8 `implementation/results.$i.json` files exist on disk, written 2026-09-06T04:28Z, each reporting `passed 167 / total 167` with zero non-`passed` entries when the per-test array is walked on the `"status"` key. Step 7 made 1 implementation fix, so Step 8 does NOT meet the skip condition.

## Step 8: Finalize PRD — 2026-09-06T04:36:00.000Z

Done. `PRD_FINALIZED.md` written with four targeted edits. (Step 8 was NOT skipped: Step 7 applied 1 implementation fix, so the skip condition — zero deletions and zero fixes in all four layers — did not hold.)

## Line counts
- `PRD.md`: 539 lines / 115,002 bytes
- `PRD_FINALIZED.md`: 541 lines / 116,551 bytes
- Delta: +2 lines (+0.37%), +1,549 bytes (+1.35%)

## Changes
- **§2.4 — insert** — new paragraph pinning `created_at`/`updated_at` as wall-clock-minted (truncated to ms, forced strictly increasing so `created_at` ASC == insertion order), explicitly exempted from the logical clock — `implementation/core.py:232-246` (`sys_now`), used at `core.py:303-306` (`new_row`) and `core.py:316` (`touch`).
- **§3.7 — revise** — `certified_tonnes_allocated` is a live recomputation, not a stored counter (a `DRAFT` certificate raises it immediately), and reads 0.00 on a `DECERTIFIED` batch — `implementation/calc.py:564-573`, `implementation/serial.py:276`.
- **§3.9 — revise** — `ERR_CERTIFIED_TONNES_EXCEED_BATCH` gate now sums the batch's **other** `DRAFT`/`ISSUED` certificates plus this one's tonnage, rounded to 2 dp; self-exclusion stated with its rationale — `implementation/routes_commercial.py:96-103` (the Step 7 `rnd(...)` fix at line 102).
- **§3.9 — revise** — issuing bumps only a `QUALIFIED` batch (`-> CERTIFIED`, version+1) and leaves an already-`CERTIFIED` batch untouched; issuing does **not** grow `certified_tonnes_allocated` (the cert was already counted while `DRAFT`) — `implementation/routes_commercial.py:104-112`.

## Per-edit pre-edit search log
1. **§2.4 timestamps.** (a) Subject: source of `created_at`/`updated_at` and their ordering role. (b) Enumerated: `core.sys_now`, `core.new_row`, `core.touch`, `core.now`/`now_iso`/`fmt_ts`, `core.sort_key`/`ordered`, `serial._common` + `serial.lab_test_out`, `calc.newest_lab_test`, `calc.newest_in_spec_lab_test`, `calc.applicable_authorization` (created_at tie-break), `calc.distribution_plan` ranking, `cascades._planned_batches_on`, `cascades.cancel_orders_on_silo`; grepped all `created_at|updated_at|sys_now` across every module. Confirmed no logical-clock-sourced `created_at` anywhere, and every §2.4-enumerated stamp (`sealed_at`, `lit_at`, `valid_from`, `qualified_at`, ...) still comes from `now()`. (c) Wording adjusted to name only `created_at`/`updated_at` as the exception and to leave `api_request_timestamp` (also wall-clock, but PRD §2.2 is already under-determined) untouched, avoiding a universal claim about "all timestamps".
2. **§3.7 field definition.** (a) Subject: `certified_tonnes_allocated`. (b) Enumerated every producer/consumer: `calc.batch_certified_allocated` (sole computation, incl. the `DECERTIFIED -> 0.0` branch), `serial.batch_out:276`, `routes_commercial.create_certificate` (DRAFT rows count), `routes_commercial.issue_certificate` gate, `cascades.revoke_cascade` hop one, `routes_cement` batch creation (starts at 0 with no certificates); grepped `certified_tonnes` repo-wide. (c) Added the `DECERTIFIED` carve-out so the sentence does not contradict §3.9 hop one's "drops to 0.00", and said "recomputed on every read" rather than "never changes on issue" to stay compatible with the revoke path.
3. **§3.9 exceed gate.** (a) Subject: the rung-106 comparison. (b) Enumerated: `routes_commercial.py:96-103`; the parallel rung-105 gate at `:193-195` (`calc.certificate_allocated`, which needs no self-exclusion because the order does not yet exist); `calc.batch_certified_allocated`; `routes_commercial.create_certificate` (no gate at draft time). (c) Scoped the exclusion to the certificate being issued only, and did not touch the `ERR_CERTIFICATE_ALLOCATION_EXCEEDED` sentence, whose existing wording already matches `:194`.
4. **§3.9 issue side-effects.** (a) Subject: what issuing mutates on the batch. (b) Enumerated: `routes_commercial.issue_certificate:104-112` (cert touched always, batch touched only from `QUALIFIED`), `serial.batch_out`, `calc.batch_certified_allocated`, `cascades.revoke_cascade` (the only other batch-status writer in the commercial chain), `cascades._qualify_join`/`_reject_batch`. (c) Wrote "left entirely untouched by the issue" rather than "no version bump" so the claim covers status, timestamps and version together, and cross-referenced §3.7 instead of restating the sum.

Orchestrator verification: `PRD_FINALIZED.md` is 541 lines / 116,551 bytes and is NOT byte-identical to `PRD.md` (+2 lines). `PRD.md`, `implementation/`, `test_suite/` and `test_helpers/` were left untouched.

## Step 9: Complete PRD — 2026-09-06T05:12:00.000Z

Run as FOUR sequential passes over one shared `workspace/PRD_COMPLETED.md`: three module-partitioned scan passes (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2-4 were forbidden to copy) plus a fourth reconciliation pass to close the cross-pass contradictions the partitioned passes reported but could not fix inside their own partition. Total 68 in-paragraph edits; `PRD_FINALIZED.md` 541 lines / 116,551 chars -> `PRD_COMPLETED.md` 545 lines / 137,540 chars (+4 lines, +20,989 chars, +18.0%). No new sections were added by any pass.

### Pass 1 — `core.py` + `app.py` + `calc.py` (11 ambiguity-pins, 4 mismatch-revisions)
- Verified `core.ERROR_STATUS` and the §5 catalogue agree exactly: same 74 identifiers, same statuses, same order — no edit needed there.
- §2.2 revise (ambiguity) — `api_request_id` is `req_` + twenty upper-case alnum chars — `core.py:351-355`
- §2.2 revise (mismatch) — `api_request_timestamp` comes from real wall-clock, not the logical clock — `core.py:361`
- §2.3 insert (ambiguity) — pagination values parsed as signed integers after whitespace trim; present-but-empty / fractional / non-numeric all rejected as non-integer — `core.py:415-436`
- §2.3 insert (ambiguity) — filter query params: exact case-sensitive string match, booleans as `true`/`false`, conjunctive, filter values never validated, undeclared params ignored — `core.py:595-623`
- §2.3 revise (ambiguity) — `total_count` includes the Customer ownership narrowing, applied before the endpoint's own filters — `core.py:609-623`
- §2.5 insert (mismatch) — the stated decimal widths govern computed figures only; caller-supplied numbers are stored/echoed verbatim, unrounded — `serial.py:53`, `core.py:482-492`
- §2.5 insert (ambiguity) — rounded figures are JSON numbers in shortest form (`0.0`, not `0.00`) — `core.py:145-154`
- §2.8 rung 35 insert (ambiguity) — an absent/null/non-string FK is not evaluated at rung 35 and never yields a not-found error — `core.py:552-565`
- §2.8 rung 40 revise (mismatch) — non-negativity applies to every fractional numeric field and every integer field except `contract_priority` — `core.py:482-505`, `routes_master.py:171`
- §2.8 rung 40 insert (ambiguity) — non-JSON / non-object body is itself `ERR_INVALID_REQUEST`; absent body = `{}`; explicit `null` counts as absent; empty strings rejected; booleans never accepted as number/int/string; integer fields reject `5.0`; the accepted ISO-8601 forms — `core.py:446-538`, `core.py:195-225`
- §3.1 insert (ambiguity) — each chemical module is null on its own zero denominator; a null `as_designed_lsf` fails submission with `ERR_MODULE_TARGET_DEVIATION` — `calc.py:73-83`, `routes_design.py:156`
- §3.2 revise (ambiguity) — `alt_raw_share_pct` divides by the rounded `as_received_tonnes` and reads 0.00 (not null) on an empty pile — `calc.py:140-146`
- §3.2 insert (ambiguity) — all seven as-blended figures are null while rounded `dry_tonnes` is 0.00; `lsf_deviation` is null whenever `as_blended_lsf` is — `calc.py:147-184`
- §3.2 revise (ambiguity) — a null `lsf_deviation` fails the seal gate with `ERR_PILE_LSF_OFF_TARGET` — `routes_design.py:312-314`
- §3.5 insert (ambiguity) — `nox_intensity_breach` compares the already-rounded 3-decimal figure; a run with no clinker reads 0.000, flag false — `calc.py:244-254`
- §3.7 insert (ambiguity) — `so3_pct` is 0.00 when the batch would carry no cement mass — `calc.py:353-355`

### Pass 2 — `serial.py` + `routes_master.py` + `routes_design.py` (13 ambiguity-pins, 8 mismatch-revisions)
- §2.8 rung 91 revise (mismatch) — scope was "creation and amendment"; `_component_sum_gate` also runs at submit — `routes_design.py:154`
- §2.9 / §3.1 x2 / §3.2 / §3.3 / §3.4 revise x6 (mismatch) — PRD claimed globally/plant-unique `code` and `pile_code`. **No uniqueness check exists anywhere in the implementation** and the catalogue has no duplicate-code error; all six reworded to "unique by convention rather than by enforcement" — `routes_master.py:89,131,232,272`, `routes_design.py:79,232`
- §3.2 seal revise (mismatch) — PRD listed `ERR_PILE_EMPTY` before `ERR_DESIGN_NOT_APPROVED`, contradicting rung 64<65 and the code; reordered and marked ladder-ordered — `routes_design.py:306-314`
- §2.9 — `loadout_spouts` is a non-negative JSON integer — `routes_master.py:269,276`
- §2.10 — `peak_season_months` required; non-integer / out-of-1..12 entry -> `ERR_INVALID_REQUEST`; empty array accepted; echoed verbatim incl. order and duplicates — `routes_master.py:34-37,47`
- §3.1 — each `components[].raw_material_id` is a rung-35 FK resolved after body `plant_id`, in array order, at create/amend as well as submit; entry shape rules; extra entry keys dropped — `routes_design.py:26-54,77`, `serial.py:98-102`
- §3.1 — design born with `revision_reason`/`approved_by_user_id`/`approved_at`/`superseded_by_design_id` null — `routes_design.py:99-103`
- §3.1 — all six amendable fields optional (empty amendment still succeeds, recomputes, bumps `version`); `revision_count`/`revision_reason` never cleared by amendment or approval — `routes_design.py:116-141`
- §3.2 — `expected_raw_mix_design_version` is a JSON integer; the pile's `plant_id` is not cross-checked against the design's; `sealed_at` null at birth — `routes_design.py:228-257`
- §3.3 — `valid_days` non-negative integer; no `is_alternative` check at request time; the eight other burn-test fields null at birth — `routes_design.py:348-365`
- §3.3 — `decision_reason` recorded in both adjudication branches, null when omitted — `routes_design.py:414`
- §3.3 — omitting `authorized_max_tsr_pct` authorises at a ceiling of 0 rather than being refused — `routes_design.py:420`
- §3.3 — a refused `AUTHORIZED` adjudication leaves status/ceiling/version unmoved but retains the `adjudicated_by_user_id` and `decision_reason` already written (no rollback) — `routes_design.py:413-426`
- §3.4 — `nominal_shc_gj_per_tonne` must be strictly > 0 (`ERR_INVALID_REQUEST`); both hour counts non-negative integers — `routes_master.py:234-239`
- §3.8 — `block_reason` optional on the PlantAdmin path, stored null when omitted — `routes_master.py:294,300`
- §3.8 — a no-op `status` (block a BLOCKED, unblock an OPEN) is refused with `ERR_INVALID_REQUEST` (400), not a state error — `routes_master.py:295-298`
- §3.9 — customer amendment: all five fields optional, no state gate, `name`/`region_code` ignored, `version` bumps even on a no-change amendment — `routes_master.py:184-203`
- §3.9 — `as_of_month` is a query parameter; absent/empty/non-integer/out-of-range -> `ERR_INVALID_REQUEST` — `routes_master.py:70-73`, `core.py:626`
- Handed-back items resolved: **rung 35 multi-FK ordering verified, no divergence** (designs `plant_id` -> `components[].raw_material_id`; piles `plant_id` -> `raw_mix_design_id`; burn tests `plant_id` -> `fuel_id`; all top-to-bottom as PRD claims). **`serial.py` field inventory clean** — all 15 serializers diffed against the PRD inventories: no undeclared field exposed, no declared field omitted; `lab_test_out` is the only shape without `updated_at`/`version`, already pinned at §2.4.

### Pass 3 — `routes_kiln.py` + `routes_cement.py` + `routes_commercial.py` + `cascades.py` (14 ambiguity-pins, 11 mismatch-revisions)
- §2.12 ¶2 insert — a hop that revisits one row advances that row's `version` once per visit, not once per hop — `cascades.py:23-48`
- §2.12 ¶3 insert — no cascade ever writes the plant row; posture/permit/balance figures move without the plant's `version` or `updated_at` — `calc.production_posture:576`
- §2.8 rung 66 insert (mismatch) — starting an outage sits at this rung too (`ERR_KILN_UNAVAILABLE` for a BURNING run) and does not consult `availability_state` — `routes_kiln.py:353-355`
- §2.8 rung 81 revise (mismatch) — retitled "window ordering and window arrival"; outage start/complete clock-not-reached also yields `ERR_INVALID_WINDOW` (PRD previously named no error) — `routes_kiln.py:356-357,373-374`
- §2.8 rung 105 insert (mismatch) — on start-loading the certificate-still-ISSUED test is evaluated out of position, right after rung 60 and ahead of silo/window/spout — `routes_commercial.py:231-233`
- §2.8 rung 107 insert — start-loading also raises `ERR_SILO_SPOUT_CAPACITY` at this rung, as its last check — `routes_commercial.py:239-246`
- §3.4 ¶7 insert — run birth values pinned (`lit_at`/`completed_at`/`abort_reason` null; thermal figures 0.00 but `effective_shc_gj_per_tonne` 4.00 from the 0.00 provisional tier); scheduling tests nothing about the pile — `routes_kiln.py:79-96`, `calc.py:206`
- §3.4 ¶15 revise (mismatch) — start-outage gates reordered to ladder order (rung 66 before rung 81) — `routes_kiln.py:352-357`
- §3.4 ¶17 revise — complete-outage clock failure is `ERR_INVALID_WINDOW`, bound is `window_start` not `window_end` (early close-out legal), `refractory_replaced` required boolean — `routes_kiln.py:370-374`
- §3.5 ¶37 revise (mismatch) — authorisation test looks only at this charge's fuel; a not-yet-valid AUTHORIZED row also yields `ERR_BURN_TEST_EXPIRED`; rung 72 skipped as uncomputable when the charged alt fuel is unauthorised/lapsed so the rung-80 error surfaces despite 72 < 80; a previously charged lapsed alt fuel stops tightening the ceiling but keeps counting toward `tsr_pct` — `routes_kiln.py:153-165`, `calc.py:294,321`
- §3.5 ¶39 revise (mismatch) — completion gates in ladder order: state AND "at least one charge" fused at rung 60, silo-OPEN at 62, `window_end` at 83, then feed and capacity — `routes_kiln.py:186-199`
- §3.5 ¶43 insert — abort rewrites only two figures; charges, gross energy, provisional clinker, effective SHC, `tsr_pct` and chlorine input all survive — `routes_kiln.py:224-228`
- §3.6 ¶51 insert x2 — `free_lime_pct` null with no test; a reading naming no movement is a pure no-op leaving `quality_state`/`version`/`updated_at` untouched and never re-running the cascade — `cascades.py:141`, `calc.py:533`
- §3.7 ¶73 revise (mismatch) — start-grinding checks both silos at rung 62 before the FEED_READY test at 68 — `routes_cement.py:95-101`
- §3.7 ¶77 insert — a branch only leaves PENDING; a repeat same-type test on a still-GROUND batch is stored but changes nothing — `cascades.py:183`
- §3.8 ¶2 revise (mismatch) — blocking a CLINKER silo runs the same conditional withdrawal walk as a re-quarantine, not an unconditional demotion; blocking moves no tonnage; an amply-stocked silo can be blocked with no `feed_state` change; posture turns CONSTRAINED only if the walk leaves a batch short; cancellation walk is `created_at` ASC; each customer's version advances once — `cascades.py:97,37,77`
- §3.8 ¶3 revise — reconciliation on unblock runs only for a CLINKER silo and only over PLANNED FEED_SHORT batches; unblocking a CEMENT silo runs no downstream hop — `cascades.py:107`
- §3.9 ¶97 insert — `certified_blaine_m2_per_kg`/`certified_strength_mpa` null when no in-spec test of that type; an out-of-spec reading is never snapshotted even when newest; five other fields null at birth; drafting ungated beyond FK/shape — `routes_commercial.py:56-71`, `calc.py:521`
- §3.9 ¶99 revise (mismatch) — SoD at priority 55 precedes the DRAFT state test at 60; comparison uses the newest strength test in-spec or not; no strength test => control does not apply — `routes_commercial.py:81-87`
- §3.9 ¶101 insert — revoke hops one and two are each conditional and neither short-circuits; the chain follows the silo, so unrelated certificates' orders on it are cancelled while the revoked certificate's orders on another silo are not; walk is `created_at` ASC — `cascades.py:118`
- §3.9 ¶103 insert — the customer row is not written at reservation (`open_reserved_tonnes` rises with no version bump); complete and void both write it; start-loading writes nothing but the order — `routes_commercial.py:218-221,249,266-274,297-312`
- §3.9 ¶105 revise (mismatch) — silo-OPEN at 62 precedes window ordering at 81; the silo-kind test checks kind only — a reservation carries no `plant_id` — `routes_commercial.py:180-186`
- §3.9 ¶107 revise — the LOADING count on start-loading ignores windows entirely, and the five gates run in the stated order — `routes_commercial.py:239-246`
- §4 `POST /kiln-runs` row revise (mismatch) — "against a sealed pile" -> "against a blended pile"; no pile-state gate exists at scheduling — `routes_kiln.py:49-96`
- Handed-back item 2 (`calc.proportion_batch` returning `None`) left deliberately silent: with `gypsum_pct` bounded 2-7 at rung 40 and `limestone_pct` capped at the cement type's maximum at rung 96 before the call, `gypsum + limestone <= 22`, so the `denom <= 0` branch is unreachable and documenting it would add PRD surface for behaviour no request can produce.

### Pass 4 — reconciliation (7 edits; adjudicated every cross-pass item from source)
- **A. §2.8 same-priority totality — CONFIRMED overstated, edited.** Rung-40 coercers all route through `_bad` (`core.py:457-549`) and `create_customer` evaluates `contract_state`/`credit_hold` before `name`/`region_code`/`contract_priority`/`max_so3_pct` (`routes_master.py:166-177`) — not declaration order. Key finding the reporting pass missed: every co-located rung-40 rule reports the SAME `error_id` and status, so determinism survives and only the non-contractual `message` varies. Same collapse at priority 62 (`routes_cement.py:47-48`) and 81 (`routes_kiln.py:38-41`); rungs with distinct ids at one priority (35, 80, 105, 107) already prescribe their own order and the code matches. Line 118 rewritten to drop the false "can never both be violated" claim and declare within-rung-40 field order explicitly under-determined.
- **B. §3.4 ¶17 `refractory_replaced` -> AVAILABLE — CONFIRMED false, edited.** `calc.py:494-501` re-derives from `refractory_hours_since_reline >= reline_due_hours`; `routes_kiln.py:381-382` resets the count to 0 only. With `reline_due_hours` 0, `0 >= 0` -> RELINE_DUE. §3.4 ¶5 (the normative derivation) is correct and untouched; ¶17 now says the state is re-derived, reads AVAILABLE for any strictly-positive `reline_due_hours`, and reads RELINE_DUE even after a completed reline when `reline_due_hours` is 0.
- **C. §2.9 ¶4 same-plant universal — CONFIRMED false, edited.** Enforced for cement batches (`routes_cement.py:49-53`) and kiln runs (`routes_kiln.py:77-78`); not for loadout orders (`routes_commercial.py:185-186` tests `material_kind` only, request carries no plant). §2.9 qualified to name the two plant-carrying operations, matching pass 3's local §3.9 wording.
- **D. §2.8 rung 62 start-of-loading — CONFIRMED unreachable; NO edit (rung left declared, because the implementation genuinely carries the check).** Audited every writer of silo `status`: only `cascades.block_silo:97-104` and `cascades.revoke_cascade:130-135`, and both call `cancel_orders_on_silo` (revoke unconditionally, even on an already-BLOCKED silo), moving every RESERVED/LOADING order to CANCELLED_BY_QUALITY. Orders can only name CEMENT silos, `material_kind` is immutable, the cascade runs under one RLock (`core.py:588`), and CANCELLED_BY_QUALITY is terminal — so `start_loading`'s rung-60 test always fires first. The `silo is None` branch is also dead (no deletes).
- **E. §3.1 "before it checks anything" — CONFIRMED imprecise, edited.** `routes_design.py:147-160`: state gate (148) -> per-component FK resolution (150-152) -> recompute (153) -> component-sum gate (154) -> module-deviation gate (155-160). Reworded to "before either of its two substantive gates runs", naming the two things that legitimately precede the recompute.
- **F. §2.4 clock direction — CONFIRMED backward-settable, edited.** `core.py:164-169` — `_Clock.set` is a bare assignment with no comparison against `self.current`; `routes_master.py:325-331` only validates that the instant parses. Pinned: the clock is a settable register accepting any parseable instant, including one earlier than its current value or the startup instant, with no error for rewinding.
- **G. Pass 1 vs pass 2 on `nominal_shc_gj_per_tonne` = 0 — pass 2 is right, pass 1 was wrong; no edit needed.** `routes_master.py:238-239` refuses `<= 0` with `ERR_INVALID_REQUEST` before the row is stored, and there is no kiln PATCH endpoint anywhere, so the divisor at `calc.py:228` can never see 0. Pass 2's existing sentence verified accurate as written.
- **Consistency sweep — 2 genuine internal contradictions found and fixed.** (1) §3.9 reservation contradicted §2.8 rung 50: the paragraph claimed to walk the ladder and named priority 62 as the first rung reached, but `routes_commercial.py:179-183` tests `expected_mill_certificate_version` (-> `ERR_STALE_CERTIFICATE_VERSION`, 412) first; the priority-50 step was inserted ahead of it. (2) §2.8 rung 40's range list read as closed but omitted rules §3 states (`nominal_shc_gj_per_tonne`, `loaded_tonnes` at `routes_commercial.py:261-262`, the no-op silo transition at `routes_master.py:295-298`, the burn-test adjudication ceilings at `routes_design.py:421-426`, the limestone/clinker headroom at `routes_cement.py:57-58`); `nominal_shc_gj_per_tonne` was added and the list marked illustrative rather than exhaustive.
- The other nine cross-section ordering claims (§3.2 seal, §3.4 outage start, §3.5 light/charge/complete, §3.6 release, §3.7 start-grinding, §3.8, §3.9 certificate issue and start-loading) were each re-verified against handler source and already matched — no edit.

Orchestrator verification: `workspace/PRD_COMPLETED.md` exists at 545 lines / 137,540 bytes and is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran); it ends on the complete final row of the §5 error table. `PRD.md` (539/115,002) and `PRD_FINALIZED.md` (541/116,551) are unchanged. All 8 `implementation/results.$i.json` remain on disk at 167/167. `__pycache__` byproducts and the now-empty `.scratch` parent removed.

## Pipeline complete — 2026-09-06T05:15:00.000Z

All nine steps finished. Deliverables: three SCAFFOLD artifacts, `test_helpers/` (9 files / 2130 lines), `test_suite/` (23 files / 167 tests), `workspace/implementation/` (11 files / 3607 lines) passing 167/167 in all 8 rounds of the final stability sweep, and the PRD chain `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`.
