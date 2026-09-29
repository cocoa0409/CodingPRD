# Worklog — task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty

## Step 1: Create task directory — 2026-09-06T04:01:25.830Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty` and its `workspace/` subdirectory. Index 2999 was pre-assigned by the invoking harness; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-06T05:59:00.000Z

Step 2 scaffold generation for **task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty** is complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3399 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1780 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3736 |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, validation_priority_conflicts, endpoints, errors, roles, segregation_of_duties` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. Each design file has exactly one top-level key. `worklog.md` (5 lines) and `workspace/` are untouched; `.scratch/step2` was removed after use.

## Domain coverage (§1.0–§1.7)

13 entities: PayerPolicy, Patient, AllergyTestOrder, ImmunotherapyVial, ImmunotherapyDose, ReactionEvent, SinuplastyCase, ProcedureBooking, EndoscopeAsset, DiagnosticStudy, DeviceDispense, SupplyLot, SurgeryCenterBlock. 65 endpoints, 73 errors, 12 calculations, 14 validation priorities, 6 roles, 2 OCC rules (`vial-create-stale-patient`, `dispense-create-stale-study`), logical clock at `2026-08-01T00:00:00Z`. complexity_profile: primary `compliance_audit`, secondary `temporal_windowing`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval]`, flat topology, cyclic state machine, `segregation_of_duties`, `immediate` consistency. Signature mechanics: per-unit allergy billing with tiered panel discounts, risk-score/observation-minute threshold ladders, escalation-step advance-on-clearance with gap rollback (band from pre-rollback step, volume from post-rollback step), dual candidacy variants (POLICY_STRICT contiguous-day merge vs CLINICAL_BROAD cumulative), payer authorization with device-count capping and policy-version pinning, HLD 168-hour scope shelf life with reprocessing cycle, block utilization in bps, dual refund variants, and millilitre/unit ledger invariants.

## §1.8 — difficulty design

9 rule_ids × 2 instances = **18 instances**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 — corner design

**9 sections, 79 instances (57 with full `test_recipe`, 22 `excluded_because` stubs)**: entities 11, state_machines 18, calculations 10, validations 9, endpoints 5, errors 18, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1. All claim_types are drawn from the closed claim-extraction-guide taxonomy; every stub's `difficulty_instance` resolves to a real §1.8 instance name; all 79 + 18 names are unique across the union. All **73 declared error ids** are exercised. Forbidden concurrency vocabulary: none. The "harder than expert level" directive line is excluded from `scenario:` and honored only as Expert-plus calibration.

## Lint

```
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  763

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two fixes were needed to reach it, both in the rbac probe instance: its `POST /immunotherapy-vials` and `POST /device-dispenses` triggers carried literal `expected_patient_version: 1` / `expected_study_version: 1` (rule (e) forbids literal OCC versions), so they were swapped for two OCC-free exclusive operations (`POST /immunotherapy-doses/{id}/void` as Audiologist, `POST /sinuplasty-cases/{id}/payer-decisions` as Otolaryngologist) which preserve the 403-before-404 ordering claim. A `bubble_up` cascade instance (`cleared_doses_advance_the_parent_patient_schedule`) was also added to close the last uncovered state-machine taxonomy row.

Orchestrator verification: all three files present (3399 / 1780 / 3736 lines). Grepped `SCAFFOLD.yaml` for the difficulty-directive line ("harder than expert", "expert level") — zero hits, so the Step 2 directive did not leak into the file the doc generator reads.

## Step 3: Copy shared files — 2026-09-06T06:00:12.934Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T06:24:28.927Z

PRD generation for task 2999 is complete.

**Output:** `workspace/PRD.md` — **541 lines / 138,125 bytes**. Final section heading: `## 5. Error Code Catalogue`; the document ends on the last error row (`| ERR_BLOCK_NOT_OPEN | 409 |`), not mid-sentence. Built in 10 chunked appends (heredoc), `wc -l` verified after each: 127 → 189 → 221 → 249 → 273 → 301 → 331 → 361 → 389 → 461 → 541.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Roles/RBAC · 2.2 Response Structure (verbatim block, diff-verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Identity/Timestamps/Version · 2.5 Logical Clock · 2.6 Cents, Millilitres, Basis Points, Rounding · 2.7 Version Pinning · 2.8 Fourteen-Rung Rejection Ladder · 2.9 Segregation of Duties · 2.10 Conserved Ledgers · 2.11 Cascade Discipline
- §3 Business Logic (9 subsections): 3.1 Payer Plans & Patient Chart · 3.2 Allergy Panel Fork · 3.3 Reading/Billing/Dermatographism Abort · 3.4 Reactions & Four-Hop Cascade · 3.5 Immunotherapy · 3.6 Sinuplasty Candidacy & Two Revision Loops · 3.7 Audiology/Sleep/Device Trial Economy · 3.8 Endoscopy Reprocessing & Supply Inventory · 3.9 Surgical Schedule
- §4 Endpoint Definitions (4-column table, **65 rows**)
- §5 Error Code Catalogue (2-column table, **73 rows**)

**Coverage:** 65/65 endpoints · 73/73 error ids (all 73 also stated with their trigger condition in §2/§3, none only in the table) · 13/13 entities · 12/12 calculations translated to prose with worked examples · 52/52 state-machine transitions written as explicit `FROM → TO` arrows · 14/14 validation rungs + both declared precedence conflicts · 2/2 OCC rules with occ field, error id and 412 · 6/6 roles.

**Hard Contracts**
- **Contract 1 (field-name coverage): PASS** — 199/199 required identifiers present verbatim in backticks; 0 missing, verified mechanically against `.scratch/step4/required_fields.json`.
- **Contract 2 (rule coverage): PASS** — all transitions, preconditions↔error-id pairings, side effects on both branches, cascade hop ordering, formulas, ledger invariants and list filters stated; no fuzzy quantifiers anywhere.
- **Contract 3 (§3 path purity): PASS** — 1,318 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations.

**Scaffold ambiguities resolved (each stated explicitly in PRD prose)**
1. `ImmunotherapyVial.label_text` composition (`mrn|dilution_code|YYYY-MM-DD`) has no dedicated error id → documented as a rung-3 shape failure returning `ERR_INVALID_REQUEST`.
2. `discard_reason` `SUPERSEDED` is system-only (set by the supersession cascade); only `BEYOND_USE_DATE` and `CONTAMINATION` are accepted from a body.
3. Authorization submission on a case whose plan has `requires_prior_auth` false has no declared error → `ERR_CASE_STATE_INVALID`. Symmetrically, a `DOCUMENTED` case under a plan that *does* require prior auth is refused the same way at booking creation.
4. Dispense adjustment attempted at/after `trial_end_at` has no declared error → `ERR_DISPENSE_STATE_INVALID` (`ERR_TRIAL_NOT_COMPLETE` is the opposite condition, reserved for finalize).
5. `devices_used_count` exceeding `planned_device_count` at completion → `ERR_BOOKING_STATE_INVALID` (rung 7), not rung 3.
6. A `WRITE_OFF` adjustment exceeding the lot's `available_quantity` → `ERR_SUPPLY_EXHAUSTED`.
7. `SupplyLot.expires_at` ("may not be reserved or consumed at or after") has no declared error → `ERR_LOT_STATE_INVALID`, same as a `QUARANTINED` lot.
8. Ordering inside rung 14 on booking creation is unspecified → documented in the catalogue's own declared order: supply → device-count authorization → block capacity → block posture.
9. CT recency for `POLICY_STRICT` is stated against the logical-clock date rather than the authorization-submission instant, and `requires_ct_within_months` is converted at 30 days per month.
10. Scaffold's `SupplyLot.quantity_wasted` description names a `WASTE` reason that the adjustment enum does not declare → PRD uses the endpoint's enum (`RECEIVE` / `WRITE_OFF` / `QUARANTINE`).

Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced.

Orchestrator truncation check (the known doc-generator failure mode): `tail -20 PRD.md` ends on a complete markdown table row `| \`ERR_BLOCK_NOT_OPEN\` | 409 |`, i.e. a real document boundary, not mid-sentence. Independently recounted from the file: 73 `ERR_*` rows in §5 and 65 method rows in §4 — matching the scaffold's 73 errors / 65 endpoints. Grep for "scaffold" and "harder than expert" in PRD.md: 0 hits, so neither the withheld indices nor the difficulty directive leaked. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T07:12:00.000Z

Implementation complete and smoke-verified.

## Module layout (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
`app.py` | 63 | `create_app()`, 7 blueprints, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT`
`store.py` | 156 | logical clock (default `2026-08-01T00:00:00Z`), 13 in-memory dicts, ISO parse/format, whole-day/minute math
`errors.py` | 106 | `ApiError` + the 73-entry `ERROR_STATUS` map
`envelope.py` | 52 | `meta`/`response_type`/`data` envelope, `req_`+20-char request ids, pagination meta
`shape.py` | 305 | auth (6 roles), rung-3 validators, strict unknown-key/unknown-query rejection, `pagination()`
`calc.py` | 480 | enums, constant tables, all 12 calculations
`common.py` | 159 | `begin/new_row/touch/find/find_ref/public/paginate`, cascade fragments
`r_registry.py` | 177 | payer policies, patients, `POST /_clock/set_current_utc`
`r_allergy.py` | 308 | panels (skin + serum arms), readings, reaction events + both cascades
`r_immuno.py` | 348 | vial compounding/verification/discard, dose sizing/administration/clearance/void
`r_sinuplasty.py` | 213 | cases, documentation, candidacy read, submissions, payer decisions
`r_audiology.py` | 312 | studies, results, interpretation, dispenses, adjustments, return, finalize, settlement
`r_assets.py` | 219 | endoscopes + reprocessing, supply lots + adjustments
`r_schedule.py` | 476 | blocks, bookings, start/complete/cancel
`start.sh` | 10 | `set -euo pipefail`, `cd $(dirname $0)`, guarded pip install, `exec python3 app.py` (foreground)
`requirements.txt` | 1 | `flask==3.1.3`

3385 lines total. Storage is in-memory dicts only; nothing is seeded — a fresh boot returns `total_count: 0` for every collection and the clock back at the default.

## Coverage (machine-verified, not eyeballed)
- **Endpoints 65/65** — extracted the PRD §4 table and the `@bp.<verb>` decorators and set-differenced them: zero missing, zero extra.
- **Error ids 73/73** — set-differenced `ERROR_STATUS` against every `ERR_*` token in the PRD: exact match. The 13 never appearing in a literal `raise` are the per-entity 404s, emitted from `store.NOT_FOUND` via `common.find/find_ref`.
- 13 entities, 6 roles, 12 calculations, 14-rung ladder, 2 OCC rules (`ERR_STALE_PATIENT_VERSION`, `ERR_STALE_STUDY_VERSION`, both 412), 4 cascades (4-hop reaction, 3-hop reprocessing failure, 3-hop supply write-off, vial supersession).

## Smoke test
Booted `bash start.sh` on port 18299, drove **235 assertions** in four scripted passes (~410 requests): **zero 500s, zero tracebacks** in the server log. Passes 2–4 (175 assertions) were fully green. Pass 1 had 9 red assertions that were all the smoke script's own wrong expectations, each then confirmed correct against PRD prose: billing (the impl reproduces the PRD's own worked example 1509/54324/302/10872 exactly), the order-parent cascade (requires the order to be `ADMINISTERED`, not `READ`), the epinephrine gate (only bites at score >= 45), and dose observation sizing (30, not 90).

Verified end-to-end: all four PRD-worked billing examples, `age_months` borrow, both risk variants, the dermatographism abort and its permanent block, serum conversion with no wait, the four-hop dose cascade in full (dose→patient→ORDERED-order resize→vial+booking flags), vial supersession and the ledger identity, gap rollback and the 6/7 seam, all three refund arcs, `superseded_dispense_count`, the consumed→wasted bucket move on settlement, both scope-failure hops plus `mec_test_due` across a 10-cycle loop, the write-off/replenish shortfall-flag loop, block concurrency and `FULL` flip, the lazy `AUTH_EXPIRED` write-before-refuse, `ERR_POLICY_VERSION_DRIFT`, the revision-limit loop, and all 13 404 ids. Server reaped by `/proc/<pid>/cwd` match (both the wrapper and the `python3 app.py` child); no survivors, ports 18299/18300 free, `__pycache__` and `.scratch/step6` removed, sibling scratch dirs and `worklog.md` untouched.

## PRD ambiguities resolved (Step 9 should align the PRD to these)
1. **Rung-10 order at panel administration** — §2.8 lists epinephrine first, §3.2 lists dermatographism first. Chose **§3.2's order**: dermatographism → epinephrine → washout.
2. **Rung-10 order at dose administration** — chose §3.5's operational sequence: `VIAL_EXPIRED` → `EPINEPHRINE_NOT_ON_FILE` → `DILUTION_MISMATCH` → `SUPERVISION_REQUIRED` → `INSUFFICIENT_VIAL_VOLUME`.
3. **Order-parent cascade is 3 hops, not 4** — §3.2 promises `observation_required_minutes` is re-derived "whenever the reaction cascade of §3.4 moves the patient's risk", but §3.4 puts the ORDERED-order resize inside the *dose* chain's hop 3 and ends the *order* chain at the tier flip. Took the literal hop enumeration: an order-parent grade->=2 reaction flips the tier but does **not** resize sibling `ORDERED` orders and does **not** touch vials or bookings. This is the single most likely divergence point.
4. **One version bump per row per request** — §2.11 says "every row a cascade touches is a mutation *of that row*", so hop 2 and hop 3 both landing on the patient produce one `version` increment, not two.
5. **Unknown query parameters and unknown body keys** → `ERR_INVALID_REQUEST` (rung 3). Additionally accepted `systemic_grade` on `GET /reaction-events` and `patient_id` on `GET /immunotherapy-doses` (joined via the vial, since a dose row carries no `patient_id`) because §4 names them although the scaffold input lists omit them.
6. **Parent-dependent rung-3 checks** run after resolving the parent but before the state gate: `positive_antigen_count <= antigen_count`, `label_text` composition (needs the patient's `mrn`, so checked after patient resolution but before lot resolution and before OCC), and the study-type metric set.
7. **`expires_at` window on compounding** (strictly after clock, <= +365 d) is a rung-3 `ERR_INVALID_REQUEST` — the PRD assigns it no error id.
8. **Lot expiry** blocks device dispensing and booking creation with `ERR_LOT_STATE_INVALID` but **not** vial compounding, where §3.5's gate list names only `QUARANTINED` and the item type.
9. **Label verification sets `immunotherapy_status` unconditionally** from the escalation step, which also lifts a `HELD` patient.
10. **Cascade rescore never downgrades a tier** — hop 2 recomputes `risk_score` and the variant only; the tier can fall only through the explicit `PATCH /patients/{id}` re-derivation of §3.1.
11. **Booking lot item-type check** applies only to `BALLOON_SINUPLASTY`→`BALLOON_DEVICE` and `TYMPANOSTOMY_TUBES`→`TYMPANOSTOMY_TUBE`; other procedure types get no mismatch check.
12. **Completion** may fire `EXHAUSTED→ACTIVE` and clear shortfall flags but never originates `ACTIVE→EXHAUSTED`.
13. **Booking cancel** restores the case via an internal `_pre_schedule_status` recorded at scheduling, falling back to `AUTHORIZED`/`DOCUMENTED` by `requires_prior_auth`.
14. **Booking start** puts `ERR_HLD_EXPIRED` before `ERR_SCOPE_NOT_READY`, and deliberately excludes `RETIRED` from `ERR_SCOPE_NOT_READY` so it falls through to `ERR_SCOPE_REASSIGNMENT_REQUIRED`.
15. **Dispense adjustment** also refuses with `ERR_DISPENSE_STATE_INVALID` once `clock >= trial_end_at`.
16. **Scaffold field lists treated as authoritative** over incidental PRD prose: `SurgeryCenterBlock` stores no `duration_minutes`, `ImmunotherapyDose` has no `patient_id`, and there is no `GET /payer-policies` collection endpoint. Inputs accepted but not persisted/returned because no entity field exists for them: `max_wheal_mm`, `adjustment_note`, `void_reason`, `return_reason`, `decision`, `leak_test_passed`/`mec_test_passed`, lot-adjustment `reason`/`quantity`, `label_text_confirmation`, and both `expected_*_version` fields.
17. **Instant formatting** — client-supplied instants are stored verbatim (`/_clock/set_current_utc` echoes the caller's exact string); every server-stamped instant uses exactly 3 fractional digits + `Z`. `api_request_timestamp` reads the logical clock, not wall time.

Orchestrator verification: 16 files in `workspace/implementation/`, `start.sh` present and foreground (`exec python3 app.py`, guarded pip install, `cd "$(dirname "$0")"`). Confirmed no stray `workspace/test_helpers/` or `workspace/test_suite/` were created.

## Step 5: Generate unit tests — 2026-09-06T07:33:00.000Z

Stage 2 complete and fully verified.

### Files written

**`test_helpers/` (task root, 3930 lines)** — Stage 1, frozen before Stage 2 began:
```
 146 __init__.py      631 api_client.py    195 api_errors.py
 625 assertions.py    452 constants.py     388 factories.py
1096 fixtures.py      113 test_users.py    284 types.py
```

**`test_suite/` (task root, 10188 lines, 166 test functions)**:
```
  65 conftest.py                                       -
 395 test_01_allergy_panel_billing_and_readings.py      8
 553 test_02_immunotherapy_dosing_and_ledger.py         9
 539 test_03_sinuplasty_authorization_lifecycle.py      7
 496 test_04_device_dispense_and_refunds.py             7
 728 test_05_endoscope_and_scheduling_resources.py      9
 357 test_06_supply_inventory_conservation.py           5
 869 test_07_entities_and_field_contracts.py           19
1205 test_08_state_machine_transitions.py              23
 695 test_09_calculation_semantics.py                    8
 590 test_10_validation_priority_ladder.py              7
 446 test_11_endpoint_behaviours.py                     5
 846 test_12_error_catalogue_core.py                   22
 979 test_13_error_catalogue_scheduling.py             14
 766 test_14_rbac_and_segregation_of_duties.py         14
 659 test_15_concurrency_and_consistency.py             9
```

### Coverage — zero skips

- **Queue A (Difficulty): 18/18 instances translated**, every one with >=2 tests (range 2-3). No instance failed the two-condition filter.
- **Queue B (Corner): 57/57 non-stub instances translated**, >=1 test each (range 1-5). All 22 `excluded_because:` stubs correctly untested — grep confirms zero references.
- 75 distinct `Design:` tags = 18 + 57. All 166 docstrings carry exactly one tag, as the last docstring line, resolving to a real non-stub instance.

### Verification performed

`compileall` clean. Static AST audit across all 15 files: **0 unresolved** `C.*`/`F.*`/`SETUP.*`/`USERS.*`/`check.*`/`ApiErrorId.*`/`api.*` symbols; all 166 tests take exactly `(api)`; every quoted PRD citation survives a whitespace-normalised literal grep of `workspace/PRD.md`; no `skip`/`skipif`/`xfail`/`pytest.raises`, no `["data"]` double-unwrap, no TODO/FIXME, no duplicate test names, no money-as-string, no whitespace-only header literal, no forbidden prose words. Nothing landed under `workspace/`; `worklog.md` untouched.

### Fixture-design decisions the fix loop must know

1. **Envelope**: `api.*` returns the raw `Response`; only validators unwrap, returning inner `data` once. `check.validate_unpaginated` for single reads/actions/projections, `validate_paginated` for lists. `validate_error` is never passed an expected status (the 73-entry catalogue is pre-registered).
2. **Every vial `label_text`** goes through `C.make_label_text` (PRD's `mrn|dilution_code|YYYY-MM-DD`); the design yaml's space form would 400 at the shape gate. Deliberate mismatches are produced by feeding a wrong MRN/dilution through the same builder.
3. **Corrections applied against the design yaml, PRD followed**: `DISCOMFORT` -> `C.RETURN_REASON_POOR_FIT`; `SETTLED` -> `C.BILLING_REFUNDED`; whitespace-only `X-User-ID` -> empty-string builders (sub-assertion dropped); "`updated_at` moved" claim dropped in favour of the version bump + unchanged `created_at`.
4. **`payer_approval_authorizes_case_with_capped_device_count`** required `requires_prior_auth: true` (the recipe's `false` makes its own `AUTH_SUBMITTED` unreachable per PRD 3.6), which forces `POLICY_STRICT` and therefore adjacent 28-day courses plus strictly admissible criteria. All original claims preserved.
5. **`endoscope_asset_id` added** to every `BALLOON_SINUPLASTY` booking body in two instances where the recipe omitted a PRD 3.9 shape requirement — without it the tests would 400 before reaching the precedence rung under test.
6. **Rung-masking avoided** in `policy_version_drift_blocks_booking_start`: two scopes are registered so an `IN_USE` scope cannot answer at rung 12 and hide the rung-13 `ERR_POLICY_VERSION_DRIFT`.
7. **Array ordering** (`admissible_criteria_codes`) is compared sorted — the PRD never fixes it. Pagination tie-breaks are likewise not asserted (all rows share one `created_at` because the clock does not move).
8. **Two items worth a second look if they fail in isolation**: `risk_decay_factor_at_sixty_one_days_with_fresh_event` reaches its claim through a `patch_patient` recompute trigger because PRD 3.4 vs 2.11 leaves the grade-1 recompute path underdetermined; and `overnight_capability_required_for_a_pediatric_tonsillectomy` deliberately omits the recipe's trailing `ERR_PEDIATRIC_VENUE_REQUIRED` aside (different rule, different rung).
9. Instants are compared with `check.assert_instant_equals` (moments, not spellings) and volumes with `check.assert_volume_ml` — sub-second width and float noise cannot fake a failure. Distinct actors always use the two-per-role identities in `test_users`.

Orchestrator verification: Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator could not see `test_suite/` (the directory did not exist at its spawn). Independently recounted from disk after a 45s stability re-check (line totals unchanged): `test_helpers/` 3930 lines, `test_suite/` 10188 lines, 166 test functions, 166 `Design:` tags — one tag per test. Both directories are at the task root, not under `workspace/`. `__pycache__` trees cleared before the sweep. The orchestrator also pre-wrote `workspace/sweep.sh` (setsid-safe 8-round sweep with a `SWEEP_DONE` sentinel written only after `wait`) and `workspace/summarize.py` (keys on `tests[].status`/`error_message`, cross-checks the failure list against `total - passed`) for Step 7 to use, avoiding the inline-quoting and early-return sweep hazards.

## Step 7: Run tests and iterate — 2026-09-06T07:57:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run: 2.** Final sweep: `166/166` in every one of rounds 1-8 (union of failures across all rounds = 0). The 8 `results.{1..8}.json` files are left in `workspace/implementation/`; `SWEEP_DONE`, `round.$i.log` and all `__pycache__` removed.

Iteration 1 was already at `163/166` in all 8 rounds with three fully deterministic failures (8/8 rounds each) and zero flakiness — no load-induced or connection-level failures at any point, and no implementation defects found.

### Tests deleted
None. One *assertion* was dropped under STEP 1c (partial coverage):

- `test_suite/test_12_error_catalogue_core.py::test_void_at_exactly_fifteen_minutes_restores_the_vial_ledger` — removed `assert voided["void_reason"] == C.VOID_REASON_WRONG_VIAL` (was `KeyError: 'void_reason'`). Category: **DEFAULT/FIELD SILENCE on a response-visible attribute.** PRD §3.5 names `void_reason` only as a request input ("The nurse supplies a `void_reason` of `DRAWN_IN_ERROR`, `WRONG_VIAL` or `PATIENT_DEFERRED`"); it is absent from the dose's created-with field list and from §2.11's computed-field enumeration. Contrast the two sibling reason fields PRD *does* declare as stored: a booking's `cancel_reason` and a vial's `discard_reason` (§3.9 / §3.5). Accept-and-discard is therefore an equally faithful reading. The rest of the test — `status == VOIDED`, the 5.00/0.00/0.00 volume restoration, the ledger identity, and `last_dose_administered_at is None` — is verbatim-covered and was kept intact.

### Fixes applied to `test_helpers/`
- `fixtures.py`, `immunotherapy_ready_patient` — the fixture returned the patient snapshot minted at registration, but its own docstring (and `verified_vial`'s) promised a chart already moved to `BUILD_UP`. Label verification mutates the patient row (PRD §3.5: "the patient's `immunotherapy_status` leaves `NONE` for the first time: it becomes `BUILD_UP` when the patient's `immunotherapy_escalation_step` is 6 or lower"), so the snapshot was stale by two mutations. Added a `read_patient` refresh of `base["patient"]` after `verified_vial`. This fixed `test_08_state_machine_transitions.py::test_clearing_a_dose_advances_the_parent_chart_one_escalation_step` (`immunotherapy_status: expected 'BUILD_UP', got 'NONE'`). Reach checked: 15 call sites across test_02/08/12; `mix_vial` already re-reads the version at call time and only consumes the immutable `id`/`mrn` from the dict, so no downstream `expected_patient_version` behaviour changes, and the three other `base["patient"]` assertion sites (risk score / variant / tier) are untouched by vial operations.

### Fixes applied to `test_suite/`
- `test_10_validation_priority_ladder.py::test_a_plan_amended_after_authorization_blocks_the_balloon_start` — the test called `SETUP.start_booking(...)` with no `attending_physician_user_id` yet asserted the field came back as the acting identifier `u_ent_1`. PRD §3.9 creates a booking with `attending_physician_user_id` null and, when `requires_physician_presence` is false, says only that "the field may be supplied and is simply recorded"; §2.9 adds that it "is a *different* person's identifier and is never compared with `physician_user_id`". Nothing licenses populating it from the acting user, so the implementation's `None` was correct. Fixed by supplying `attending_physician_user_id=C.USER_ENT_1` on the start call, which keeps the author's intent and now exercises the "simply recorded" rule directly rather than an inference PRD never states. (The `requires_physician_presence`-false recording path is also independently covered by `test_12_error_catalogue_core.py:456-460`, which was already passing.)

### Fixes applied to `implementation/`
**None.** No file under `workspace/implementation/` was modified. All three deterministic failures traced to the test artifact. In particular, the two divergence points the generators flagged for a second look both held up against PRD without any change: the ORDER-parent grade>=2 cascade scope (§3.4 hop enumeration) and `overnight_capability_required_for_a_pediatric_tonsillectomy` passed in all 8 rounds of both sweeps, as did `risk_decay_factor_at_sixty_one_days_with_fresh_event`.

### PRD defects found but not acted on
1. **§3.5 does not declare `void_reason` as a field of the `ImmunotherapyDose` entity** — the sole cause of the deleted assertion. PRD declares the request input and the parallel fields on two sibling entities (`cancel_reason`, `discard_reason`) but never says whether a dose stores or exposes the void reason. Adding "the dose is created … with `void_reason` null" to the dose's created-with list and "`void_reason` is stored" to the void paragraph would close it symmetrically with §3.9's cancellation prose.
2. **§3.7's `return_reason` has the identical silence** (not exercised by any current test): "supplying a `return_reason` of `DISSATISFIED`, `POOR_FIT` or `MEDICAL_CHANGE`" never states whether the value is persisted on the dispense row. Worth fixing in the same pass as (1) so the four reason fields are uniform.
3. **§3.9's optional `attending_physician_user_id` on start is underdetermined in one direction only** — PRD says it "may be supplied and is simply recorded" but never states what the field holds when it is *omitted* on a successful start. "Null" is the only reading consistent with §2.9's "different person" framing plus the created-with null, and the implementation chose it, but one explicit sentence ("an omitted `attending_physician_user_id` leaves the field null") would remove the ambiguity that produced this failure.

Orchestrator verification: re-ran `workspace/summarize.py` against the on-disk artifacts rather than trusting the subagent's claim. All 8 `results.$i.json` are present (same 07:51 mtime batch, ~54 KB each) and each reports `passed 166/166` with zero non-passed entries and a zero-size union — the `total - passed` cross-check agrees, so this is not a key-schema false clean. Also grepped `implementation/*.py` for `sqlite`, write-mode `open(...)`, and `/tmp/` paths: zero hits, confirming storage stayed in-memory only. Step 8 is NOT skipped: Step 7 ran 2 iterations with 1 dropped assertion, 1 `test_helpers/` fix and 1 `test_suite/` fix (0 implementation fixes).

## Step 8: Finalize PRD — 2026-09-06T08:01:00.000Z

All three edits are applied and verified. PRD_FINALIZED.md is intact (541 lines, ends on the §5 error-catalogue table).

**Line counts:** PRD.md 541 lines / 138,125 bytes -> PRD_FINALIZED.md 541 lines / 139,202 bytes. Line delta 0 (+0.00%); byte delta +1,077 (+0.78%). All three edits are in-paragraph insertions/revisions, so no line count changes. Tail verified at `| ERR_BLOCK_NOT_OPEN | 409 |`.

**Changes made (3):**

- **§3.5 (Verifying the label)** — *revise* — replaced "the patient's `immunotherapy_status` leaves `NONE` for the first time" with an unconditional re-derivation from `immunotherapy_escalation_step`, stated that the previous status is not consulted so a `HELD` patient's hold is lifted, that the escalation step is never moved by a verification, and that the patient row is mutated in the full §2.11 sense on every successful verification — `implementation/r_immuno.py:153-160`, `implementation/common.py:158-159`.
- **§3.5 (Voiding a dose)** — *revise* — `void_reason` is now stated as mandatory, enum-validated against the three members and then **discarded**: a dose carries no `void_reason` field, so the reason is neither stored nor present in any dose representation (contrasted with `cancel_reason` / `discard_reason`, which are stored) — `implementation/r_immuno.py:317-319` (value bound to `_values`, never written), `implementation/r_immuno.py:215-229` (created-with list has no such key), `implementation/common.py:52-57` (`public()` is a whole-row projection, so absent field = absent response key).
- **§3.9 (Starting)** — *insert* — an omitted `attending_physician_user_id` leaves the field at the null it was created with, and start never populates it from the acting identifier (which rung 9 has already required to equal `physician_user_id`) — `implementation/r_schedule.py:366,375,400-402` and `r_schedule.py:310`.

**Per-edit pre-edit search log:**

1. **`immunotherapy_status` on label verification**
   (a) Subject: every write to a patient's `immunotherapy_status`, and whether verification's write is conditional.
   (b) Enumerated: `grep -n immunotherapy_status *.py` -> exactly four writers — `r_registry.py:118` (created `NONE`), `r_immuno.py:157` (verify, unconditional derive), `r_immuno.py:301` (clear-observation, unconditional derive), `r_allergy.py:270` (grade>=2 dose reaction -> `HELD`). Read `common.derive_immunotherapy_status` (pure `step<=6`). Cross-checked all writers of `immunotherapy_escalation_step` (`r_registry.py:117` = 1, `r_immuno.py:298` clear, `r_allergy.py:267` rollback) to confirm no path can leave `BUILD_UP`/`MAINTENANCE` inconsistent with the step. Confirmed `common.touch(patient)` at `r_immuno.py:160` is unconditional on success.
   (c) Adjustment: dropped a first draft that said the hold is lifted "in the same way clearing a dose does" — clear-observation *also* advances the step, so the analogy would have implied a step move that verification does not perform. Replaced with a bare "lifts that hold" plus an explicit "the escalation step itself is never moved by a verification". Kept "*normally* where the status leaves `NONE` for the first time" rather than deleting that clause, so the sentence stays true for the ordinary registration->verify path.

2. **`void_reason`**
   (a) Subject: persistence and response-visibility of a dose's void reason.
   (b) Enumerated: `grep -rn void_reason` across all impl modules -> single hit, the `read_body` spec at `r_immuno.py:318`; the handler binds it to `_values` and never writes it. Read the full `void_dose` body (`r_immuno.py:314-348`), the dose `new_row` field list (`215-229`), and every other dose-row writer (`clear_observation` 293-294, `r_allergy.py` `_rollup_dose` / `REACTION_HELD` 265-269) — none introduces the key. Read `common.public()` to confirm the projection is "all non-underscore keys", making absence-from-row equal absence-from-response. Read `shape.read_body` to confirm `(True, …, False)` = required, non-nullable. Read the two sibling reason fields to confirm the contrast is true: `discard_reason` stored at `r_immuno.py:177`, `cancel_reason` stored at `r_schedule.py:457`.
   (c) Adjustment: deliberately did **not** extend the contrast to §3.7's `return_reason`, which `r_audiology.py:257` also discards — an "unlike … `return_reason`" phrasing would have been a false claim about a path Step 7 never touched.

3. **`attending_physician_user_id` on start**
   (a) Subject: the field's value after a successful start, across supplied / omitted / explicit-null.
   (b) Enumerated: `grep -n attending_physician_user_id r_schedule.py` -> only `310` (created `None`), `366` (optional, nullable spec), `375`, `401-402` (written only when truthy). Read `start_booking` in full (`362-407`) plus `complete_booking` and the cancel path to confirm neither touches the field, and `common.flag_supervision_targets` to confirm the §3.4 cascade sets `requires_physician_presence` only. Read `r_schedule.py:181,304` to establish that `physician_user_id` comes from the *request body* at creation, not from the acting identifier.
   (c) Adjustment: two. First, an early draft described `physician_user_id` as "recorded" from the acting identifier — false at creation time, so it was rewritten as a reference to the §2.9 equality rung. Second, the sentence is phrased as "leaves the field at the null it was created with" rather than "the server sets it to null", which keeps it equally true of the explicit-`null` body (nullable spec -> `attending is None` -> no write) without making a separate claim about that path.

**Step 7 diff items concluded to need NO PRD edit:**

- **Deleted/dropped assertion itself** — no edit beyond the `void_reason` pin above. The rest of that test (`VOIDED` status, 5.00/0.00/0.00 restoration, ledger identity, `last_dose_administered_at` null) is already verbatim in §3.5's void paragraph; that prose was left byte-identical.
- **`test_helpers/fixtures.py` `immunotherapy_ready_patient` refresh** — the fixture bug itself (a stale local snapshot) needs no PRD text. But per the diff's explicit instruction I checked the adjacent question and *did* find a real mismatch: PRD's "leaves `NONE` for the first time" reads as a from-`NONE` precondition, while `r_immuno.py:157` re-derives unconditionally and so lifts a `HELD` patient. That is edit 1 above.
- **`test_suite/test_10` `attending_physician_user_id` fix** — a test-artifact bug; PRD arguably already determined `null` via the created-with list. Added only the one-sentence clarification the diff recommended, since the omission case was genuinely unstated.
- **PRD defect #2, §3.7 `return_reason`** — **deliberately not edited.** It traces to no `implementation/`, `test_suite/`, `test_helpers/` fix or test deletion in `<step_7_diff>` (the diff itself notes it is "not exercised by any current test"), so it falls outside the HARD SCOPE. **Flagged for Step 9:** `r_audiology.py:257` validates `return_reason` against `("DISSATISFIED","POOR_FIT","MEDICAL_CHANGE")` and discards it — the dispense row never stores it (`return_dispense` writes only `fit_status`, `days_used`, `refund_variant`, `restock_fee_cents`, `refund_cents`, `billing_status`) — and §3.7 is silent on persistence. Step 9's audiology pass should close it symmetrically with the §3.5 `void_reason` wording now in place.
- **The two impl divergence points the diff flagged for a second look** (ORDER-parent grade>=2 cascade scope, `overnight_capability_required_for_a_pediatric_tonsillectomy`, and `risk_decay_factor_at_sixty_one_days_with_fresh_event`) — Step 7 reports these held up against PRD with no code change and no test change, so there is no fix behind them and nothing in scope to pin.

Orchestrator verification: `PRD_FINALIZED.md` is 541 lines / 139,202 bytes vs PRD.md's 541 / 138,125 — NOT byte-identical (`cmp` differs), and `diff` shows exactly 6 changed lines, consistent with the 3 reported in-paragraph revisions. `tail -3` ends on `| \`ERR_BLOCK_NOT_OPEN\` | 409 |`, a real document boundary, so the file is not truncated. `PRD.md` is unchanged at its original 138,125 bytes.

## Step 9: Complete PRD — 2026-09-06T08:14:00.000Z (pass 1 of 4: cross-cutting layer + registry + allergy)

Orchestrator note on method: Step 9 was deliberately partitioned into FOUR sequential passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module, because a single-agent full-PRD scan reliably under-covers a 3385-line implementation. Pass 1 owned `app.py`/`envelope.py`/`errors.py`/`store.py`/`shape.py`/`common.py`/`r_registry.py`/`r_allergy.py`; pass 2 owned `r_immuno.py`/`r_sinuplasty.py`; pass 3 owned `r_audiology.py`/`r_assets.py`/`r_schedule.py`; pass 4 was a reconciliation pass closing the cross-pass contradictions and out-of-partition referrals the first three could only report. Only pass 1 ran the `cp` from `PRD_FINALIZED.md`; passes 2-4 were explicitly forbidden from copying over the shared file.

Ran `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` as the only pass to do so. Source: 541 lines / 139,202 chars. Current `PRD_COMPLETED.md`: **542 lines / 150,117 chars** (+1 line, +10,915 chars). The extra line is one new bullet inside the existing §2.2 error-format list; no new sections, no whole-file writes (targeted Edits only). `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/`, `test_helpers/` untouched; §3.5-§3.9 verified byte-identical to PRD_FINALIZED, so Step 8's three edits are intact.

Counts: **23 ambiguity-pins, 6 mismatch-revisions** (29 changes).

- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-alnum characters — envelope.py:9-13
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, so it repeats until the clock moves — envelope.py:16-21
- §2.2 — insert — ambiguity — an unroutable request (unknown path / unsupported method) returns the error envelope with `ERR_INVALID_REQUEST` and the router's 404 or 405, not 400 — app.py:41-47
- §2.3 — revise — ambiguity — `created_at` ties broken by creation order (rows created later never sort ahead) — common.py:64-69
- §2.3 — insert — ambiguity — `limit`/`offset` accepted-and-ignored on every single-resource read (still bare two-field `meta`); `offset` past the end is an empty page, not an error — shape.py:243-253, shape.py:297-305
- §2.3 — insert — ambiguity — filters match by exact equality; an unresolvable identifier filter matches nothing rather than 404; identifier filters are free strings while enum/integer filters fail the shape gate — shape.py:270-294, common.py:76-80
- §2.4 — insert — ambiguity — client-supplied instants and dates are stored and echoed verbatim; only server-stamped instants carry exactly three fractional digits — shape.py:129-148, r_registry.py:177
- §2.5 — insert — ambiguity — the clock response carries only the caller's own spelling of `current_utc` (no `id`/`created_at`/`version`), and the clock may be moved backwards — r_registry.py:170-177, store.py:21-23
- §2.8 rung 3 — insert — ambiguity — exact accepted instant spellings (upper/lower `T`, optional fractional part, `Z` or an explicitly zero offset in four forms, surrounding whitespace trimmed) — store.py:80-83, store.py:104-120
- §2.8 rung 3 — insert — ambiguity — body must parse to a JSON object; no-body endpoints treat absent/empty/`{}` alike; query-string policing exists only on `GET` (writes ignore the query string entirely) — shape.py:195-239, shape.py:243-253
- §2.8 rung 5 — insert — ambiguity — a blank identifier string is a rung-3 400, not a 404; identifiers are never pattern-checked as UUIDs — shape.py:62-68
- §2.11 — revise — **mismatch** — there are two read-time recomputes, not one: a supply lot's `quantity_reserved`/`available_quantity` refresh on every read as well — common.py:52-57 (calls calc.refresh_lot)
- §3.1 — insert — ambiguity — an amendment supplying no terms is accepted and still advances the plan's `version` — r_registry.py:68-77
- §3.1 — insert — ambiguity — a future `date_of_birth` is `ERR_INVALID_REQUEST` judged before `payer_policy_id` resolves — r_registry.py:93-97
- §3.1 — revise — **mismatch** — `risk_score_variant` flips to `POST_REACTION` only when the named parent is in the arming state (order `ADMINISTERED` / dose `ADMINISTERED`); a grade-2+ event on any other parent state leaves variant, score and tier untouched — r_allergy.py:249, r_allergy.py:264
- §3.1 — insert — ambiguity — explicit null accepted only for `antihistamine_last_dose_at`; an empty patient update still re-derives `age_months`/score/tier and bumps `version` — shape.py:220-232, r_registry.py:152-166
- §3.2 — revise — **mismatch** — an `ORDERED` order's `observation_required_minutes` is re-derived only by dose-branch hop three; chart revisions and the order-branch cascade leave it stale — common.py:94-104, r_allergy.py:275
- §3.2 — insert — ambiguity — inside rung 10, dermatographism is evaluated before the epinephrine gate — r_allergy.py:93-98
- §3.2 — insert — ambiguity — an order opened with `method` `SERUM_IGE` is a permanent dead end (no administer, no convert, never readable) — r_allergy.py:90, 123, 149
- §3.3 — revise — **mismatch** — `max_wheal_mm` is validated then discarded, never persisted — r_allergy.py:140-143
- §3.3 — insert — ambiguity — the `positive_antigen_count > antigen_count` 400 is evaluated after the order resolves and outranks the lifecycle gate — r_allergy.py:144-150
- §3.3 — insert — ambiguity — an aborted order keeps `positive_antigen_count`, leaves `billed_units` as-is (0 on the skin arm), and neither recomputes `sensitized_antigen_count` nor rescores — r_allergy.py:162-171
- §3.4 — insert — ambiguity — a reaction event's representation carries both parent identifier fields, the unused one null — r_allergy.py:235-244
- §3.4 — insert — ambiguity — the roll-up versions the parent even when the figure does not change, and likewise when the parent is not in the arming state — r_allergy.py:246-278
- §3.4 — insert — **mismatch** — the order-branch third hop stops at the tier flip: no `ORDERED`-order resize, no vial/booking flags (those are dose-branch only) — r_allergy.py:255-260
- §3.4 — insert — ambiguity — the patient's `version` advances exactly once per cascade, one bump not one per hop — r_allergy.py:256, 272
- §4 — insert — ambiguity — trailing slash is insignificant — app.py:26
- §4 — revise — **mismatch** — `/patients` also filters by `supervision_tier` — r_registry.py:138-142
- §5 — insert — ambiguity — `ERR_INVALID_REQUEST` carries the router's 404/405 on a routing failure, the one exception to the tabulated statuses — app.py:41-47

**Referred to later passes** (spotted outside pass 1's modules, not edited):
- calc.py:110-112 `vol_out` renders volumes via `float(Decimal.quantize(0.01))`, so a two-decimal millilitre is emitted as a JSON number (e.g. `0.05`, `5.0` for 5.00). §2.6 says "carried to exactly two decimal places" without pinning the JSON rendering — pass 2 (immunotherapy) should pin.
- calc.py:213-219 `rescore_patient` re-derives `supervision_tier` purely from the score, so a `PHYSICIAN_PRESENT` patient can be demoted to `STANDARD` by any later rescore once the decayed event term shrinks, whereas the reaction cascade (r_allergy.py:257, 273) only ever promotes. §3.1/§3.5 prose does not call the asymmetry out; pass 2/4 may want it pinned where doses rescore.
- calc.py:229-230 the immunotherapy observation bump ("effective schedule step >= 9") uses the *effective* (post-gap-rollback) step from `next_dose_plan`, not the patient's stored step — pass 2 (§3.5) territory.
- Verified independently and needing no change: `ERROR_STATUS` has exactly 73 entries with the §5 breakdown (1x401, 1x403, 1x400, 13x404, 2x412, 55x409), and the router exposes exactly 65 endpoints with 13 creations returning 201.

Final verification: `wc -l` = 542; `tail -3` still ends on `| \`ERR_BLOCK_NOT_OPEN\` | 409 |`; all five `## ` headings present (§1 line 3, §2 line 11, §3 line 192, §4 line 392, §5 line 464). Scratch dir `.scratch/step9_pass1/` was created, left empty and removed; sibling `.scratch/step4`, `step5`, `step8` untouched.

## Step 9: Complete PRD — 2026-09-06T08:26:00.000Z (pass 2 of 4: immunotherapy + sinuplasty)

**No `cp` was run.** Edited `workspace/PRD_COMPLETED.md` in place with 24 targeted `Edit` calls only.
- Before: **542 lines / 150,117 chars**
- After: **542 lines / 161,301 chars**

**Counts: 23 ambiguity-pins, 8 mismatch-revisions** (some Edit calls carry more than one pin in one paragraph).

### Changes
- §3.5 compounding — insert — ambiguity — `volume_ml_initial` defaults to 5.00 only when the key is *omitted*; an explicit null is a shape failure — `r_immuno.py:44` + `shape.py:227-231`
- §3.5 compounding — revise — mismatch — the `label_text` composition check is the one rung-3 check judged *after* `patient_id` resolves but *before* `supply_lot_id` does (bad label + bad patient => `ERR_PATIENT_NOT_FOUND`; bad label + bad lot => `ERR_INVALID_REQUEST`) — `r_immuno.py:54-62`
- §3.5 compounding — insert — ambiguity — both `expires_at` window checks precede every reference resolution and report `ERR_INVALID_REQUEST`, never `ERR_VIAL_EXPIRED`; the label's date portion comes from the *trimmed* spelling — `r_immuno.py:16-17,47-52`
- §3.5 vial creation — insert — ambiguity — **[referral 1]** all four volume buckets and a dose's `volume_ml` are JSON *numbers* quantized to two places, so 5.00->`5.0`, 0.00->`0.0`, 0.30->`0.3`, 0.05->`0.05` — `calc.py:110-112`
- §3.5 supersession — revise — ambiguity — sweeps *every* `LABEL_VERIFIED`/`IN_USE` vial of the patient, leaves `MIXED`/`EXHAUSTED`/`DISCARDED` alone, never supersedes itself — `r_immuno.py:92-102`
- §3.5 discard — insert — ambiguity — a discard touches the vial only; the patient row is not mutated and its `version` does not advance — `r_immuno.py:164-180`
- §3.5 administering — revise — ambiguity — an explicitly null `supervising_user_id` counts as *not supplied*; the stored value is an opaque 1-120-char string, never trimmed, resolved or role-checked — `r_immuno.py:189,205-207`
- §3.5 administering — insert — ambiguity — three non-gates: `immunotherapy_status` (a `HELD` patient may still be dosed), no bar on concurrent uncleared doses, no version field accepted — `r_immuno.py:184-211`
- §3.5 administering — insert — ambiguity — **[referral 3]** the 45-minute bump reads the **post-rollback** effective step (= `escalation_step_at_dose`), with worked cases 10->7 (no bump) and 12->9 (bump) — `r_immuno.py:219-221`, `calc.py:229-230`
- §3.5 administering — revise — ambiguity — the `last_dose_administered_at` write is a full §2.11 mutation of the patient (version +1); `immunotherapy_status`/`_escalation_step` untouched — `r_immuno.py:235-236`
- §3.5 dose listing — revise — mismatch — adds the `patient_id` filter, resolved *through* the dose's vial (a dose carries no patient field) — `r_immuno.py:252-268`
- §3.5 clearing — revise — mismatch — the `reaction_grade <= 1` test is judged at rung 7 **ahead of** the window, and emits `ERR_DOSE_STATE_INVALID` (PRD had window first) — `r_immuno.py:283-291`
- §3.5 clearing — insert — ambiguity — the vial is versioned only if the `IN_USE -> EXHAUSTED` arc actually fires; a clearance moves no volume and normally leaves the vial untouched — `r_immuno.py:306-310`
- §3.5 void — revise — mismatch — the state failure is `ERR_DOSE_STATE_INVALID` at rung 7, measured before the window (prose previously read as if both gave `ERR_VOID_WINDOW_CLOSED`) — `r_immuno.py:321-327`
- §3.5 void — insert — ambiguity — the elapsed figure is whole minutes taken downward, so 15 min 59 s is inside and 16 min flat is not — `r_immuno.py:323-326`, `calc.py:93`
- §3.5 void — insert — ambiguity — the vial is versioned on *every* void whether or not its status moved — `r_immuno.py:332-334`
- §3.5 void — insert — ambiguity — `immunotherapy_status` is never re-derived by a void, so a `HELD` posture survives it — `r_immuno.py:314-348`
- §3.6 case creation — insert — ambiguity — `sinuses` stored and echoed in submitted order, never sorted — `r_sinuplasty.py:36-47`
- §3.6 case creation — insert — ambiguity — `evaluation_variant` is never recomputed after creation (a later `requires_prior_auth` flip or plan change does not move it) while the plan's *numeric* thresholds are read live; case creation does not touch the patient row — `r_sinuplasty.py:51-52`, `calc.py:304`
- §3.6 documentation — revise — mismatch — `documented_criteria_codes` may be **empty** and its members need **not** be distinct; duplicates clear the shape gate and collapse only in the evaluation (PRD said "distinct members") — `r_sinuplasty.py:103-104`
- §3.6 documentation — insert — ambiguity — the `ct_study_date` *key* is mandatory though its value may be null; nothing constrains it to the past — `r_sinuplasty.py:101`
- §3.6 documentation — insert — ambiguity — both arrays stored verbatim (duplicates intact); only four derived figures written back; the admissible-code list is never stored on the case; the patient row is untouched — `r_sinuplasty.py:112-122`
- §3.6 evaluation — revise — ambiguity — dedup keeps each code at its **first** appearance and that order is what `admissible_criteria_codes` returns — `calc.py:300-303,338`
- §3.6 POLICY_STRICT / CLINICAL_BROAD headers — revise x2 — mismatch — "governs whenever `requires_prior_auth` **is** true/false" -> "**was** true/false when the case was opened", reconciling with the pinned-at-creation variant — `r_sinuplasty.py:51`, `calc.py:304`
- §3.6 CT recency — insert — ambiguity — inclusive whole-day age; a *future* `ct_study_date` is trivially inside the allowance; a null date strikes the code out; `requires_ct_within_months` read live; therapy cross-checks look only at `therapy_code` presence, ignoring dates — `calc.py:320-326`
- §3.6 candidacy read — insert — ambiguity — takes `evaluation_variant` from the case rather than re-deriving it; a `DRAFT` case is run through the same arithmetic and returns zeros + empty admissible list + the plan's live thresholds, with `candidacy_status` forced to `UNDETERMINED` — `r_sinuplasty.py:131-136`
- §3.6 submission — insert — ambiguity — neither `INFO_REQUESTED` nor `AUTH_EXPIRED` re-tests `requires_prior_auth` or `candidacy_status`; no submission re-runs the evaluation; `payer_reference` survives a resubmission — `r_sinuplasty.py:158-173`
- §3.6 submission — insert — ambiguity — every submission **re-stamps** `pinned_policy_version` (overwriting the earlier pin) and nothing ever returns it to null, not a decision and not the `AUTH_EXPIRED` reset — `r_sinuplasty.py:169-177`
- §3.6 decision — insert — ambiguity — `payer_reference` is a 1-60-char string stored verbatim, never trimmed, patterned or uniqueness-checked — `r_sinuplasty.py:187`
- §3.6 decision — insert — ambiguity — `max_balloon_devices` and `auth_validity_days` are read from the plan **live at decision time**, not from the pinned revision; an approval does not reset `revision_round`; `DENIED` leaves `auth_expires_at` as it stood; `INFO_REQUESTED` leaves `authorized_device_count`, `auth_expires_at` and `pinned_policy_version` alone — `r_sinuplasty.py:196-212`
- §4 endpoint table — revise — mismatch — `GET /immunotherapy-vials` filter list gains **supply lot** (impl accepts `supply_lot_id`; §3.5 prose already listed it) — `r_immuno.py:120-125`

### Disposition of the three items pass 1 referred to pass 2
1. **`calc.py:110-112` `vol_out` rendering — PINNED** in the §3.5 vial-creation paragraph, covering all four buckets and a dose's `volume_ml`. §2.6 was **not** touched.
2. **`calc.py:213-219` `rescore_patient` demotion asymmetry — NO EDIT, and it is not pass 2's territory.** Neither `r_immuno.py` nor `r_sinuplasty.py` ever calls `calc.rescore_patient`; its only call sites are `r_registry.py:122`, `r_registry.py:164` and `r_allergy.py:186`. Doses never rescore — administration, clearance and void all leave `risk_score` and `supervision_tier` alone. Pass 1's premise ("pin the asymmetry where doses rescore") does not hold against the implementation, so the silence belongs to §3.1/§3.4. Referred to pass 4.
3. **`calc.py:229-230` effective-step observation bump — PINNED** in §3.5 with explicit "post-rollback" wording and two worked steps.

### Referred to later passes
- `calc.py:213-219` + `r_registry.py:122,164` + `r_allergy.py:186` — `rescore_patient` re-derives `supervision_tier` purely from the score, so a plain chart revision or an order-branch reaction can **demote** a `PHYSICIAN_PRESENT` patient to `STANDARD`, while §3.4's cascade only ever promotes. Pass 1's territory (§3.1/§3.4); unresolved.
- `common.py:96-101` — `resize_ordered_orders` passes `order["method"]` as the observation context with no step argument, so hop three re-derives a still-`ORDERED` `SERUM_IGE` order to 0. §3.2/§3.4 (pass 1).
- `calc.py:349-374` `trial_refund` — `days_used` is whole days + 1; the `POST_TRIAL` branch zeroes both `restock_fee_cents` and `refund_cents`. §3.7 (pass 3).
- `calc.py:402-420` `recompute_block` — bidirectional `FULL <-> OPEN` arc on the 10000-bps boundary, and `utilization_bps` forced to 0 when `capacity_minutes` is 0. §3.9 (pass 3).
- `calc.py:470-480` — `mec_test_due` is `(cycle_count + 1) % 10 == 0`, and `scope_shelf_valid` returns true when `hld_expires_at` is null. §3.8 (pass 3).
- `calc.py:435-442` — `refresh_lot` writes `quantity_reserved`/`available_quantity` onto the row while `common.public("supply_lots", …)` recomputes them on every read, so a lot's buckets are always live on read. §3.8 (pass 3/4).

### Possible cross-pass wording tensions (reported, NOT fixed)
- **§2.6 line 114** (pass 1) says the five volume fields "are all two-decimal quantities", which a reader can take as a two-decimal *rendering* guarantee. The §3.5 pin says the JSON number drops trailing zeros (`5.0`, `0.0`, `0.3`). Pass 4 should confirm §2.6 does not read as promising `5.00` on the wire.
- **§2.8 rung 3** (pass 1) states "shape before existence" universally. The §3.5 pin documents the single implementation exception (label composition evaluated after the `patient_id` 404). Pass 4 may want a pointer in §2.8.
- **§2.8 rung 7** enumerates the dose-state gates for clearance and void but does not mention the `reaction_grade` sub-check that also emits `ERR_DOSE_STATE_INVALID` at that rung. Pinned in §3.5 only.

### Final verification
`wc -l` = **542** · `wc -c` = 161,301 · `tail -3` still ends on `| \`ERR_BLOCK_NOT_OPEN\` | 409 |` · all **5** `## ` headings present · §5 table still has **73** `ERR_` rows. Scratch dir `.scratch/step9_pass2/` left empty and removed; sibling `.scratch/step4`, `step5`, `step8` untouched. No implementation, test, `PRD.md`, `PRD_FINALIZED.md` or `worklog.md` file was modified.

## Step 9: Complete PRD — 2026-09-06T08:42:00.000Z (pass 3 of 4: audiology + assets + scheduling)

No `cp` was run. Every change was a targeted `Edit` on `workspace/PRD_COMPLETED.md`; no whole-file `Write`. Nothing under `implementation/`, `test_suite/`, `test_helpers/`, `PRD.md`, `PRD_FINALIZED.md`, or `worklog.md` was touched. Scratch confined to `.scratch/step9_pass3/` (now removed; siblings `step4`, `step5`, `step8` untouched).

Counts: before 542 lines / 161,301 chars -> after 542 lines / 172,319 chars (+11,018 chars, zero net lines). 28 changes: 5 mismatch-revisions, 23 ambiguity-pins. Partition honored — all edits fall between lines 308 and 388 (§3.7/§3.8/§3.9); nothing below 388, so §4/§5 are exactly as pass 1/pass 2 left them.

### Changes

§3.7
- insert — ambiguity — metric-set check cannot be judged before the path id resolves, so the 404 beats it while other rung-3 errors beat the 404; metrics echoed in submitted numeric form; explicit null is a shape failure; forbidden metrics stay null — r_audiology.py:82-98
- insert — ambiguity — `ear` never cross-checked against `device_type` — r_audiology.py:137
- revise — ambiguity — dispense lot gate covers QUARANTINED *or* expired; EXHAUSTED falls through to rung 14 — r_audiology.py:18-22,149
- insert — ambiguity — dispense's ACTIVE->EXHAUSTED flip carries the §3.8 shortfall-flag hop; any earlier dispense row counts for `superseded_dispense_count` whatever its status — r_audiology.py:196-200
- insert — ambiguity — `adjustment_note` not persisted, explicit null is a shape failure; adjustment window closes at `trial_end_at` inclusively, tested after `fit_status` — r_audiology.py:238-244
- insert — ambiguity — `return_reason` validated then discarded (mirrors §3.5 `void_reason`); a return is accepted on either side of `trial_end_at`; the return leaves all four lot buckets alone — r_audiology.py:256-274
- revise — mismatch — worked-example `days_used` arithmetic corrected; `days_used` stored under both variants — calc.py:353

§3.8
- insert — ambiguity — boolean filter spelled exactly `true`/`false` — shape.py:279-287, r_assets.py:57
- revise — mismatch — shelf-valid is three-limbed (null `last_reprocessed_at`, null `hld_expires_at`, or clock strictly before) with the SOILED->`ERR_SCOPE_NOT_READY` consequence — calc.py:474-480, r_schedule.py:436
- insert — ambiguity — `leak_test_passed`/`mec_test_passed` not persisted; explicit null `mec_test_passed` is a shape failure — r_assets.py:88-91
- insert — ambiguity — `mec_test_passed` not consulted when `mec_test_due` is false — r_assets.py:98-99
- insert — ambiguity — a failed run rewrites neither `last_reprocessed_at`, `hld_expires_at` nor `mec_test_due` — r_assets.py:116-119
- insert — ambiguity — a failing completion advances `version` once (quarantine) or twice (retire) — r_assets.py:119-123
- insert — ambiguity — a lot's `expires_at` need not be in the future — r_assets.py:137
- revise — ambiguity — `quantity_reserved`/`available_quantity` are fields but always re-derived on read and write, floored at zero — calc.py:435-442, common.py:52-57
- insert — ambiguity — required-`quantity` shape failure precedes path-lot resolution; explicit null `quantity` fails; neither `reason` nor `quantity` persisted — r_assets.py:187-195
- insert — ambiguity — QUARANTINE raises no `supply_shortfall_flag` and clears none — r_assets.py:211-216

§3.9
- insert — ambiguity — blocks never checked against one another; `center_name` has no uniqueness rule; boolean filter spelling — r_schedule.py:23-50,62-68
- revise — mismatch — a block stores no `duration_minutes`; `capacity_minutes` computed once at publication — r_schedule.py:38-49
- revise — mismatch — utilization/posture re-evaluated only on booking creation and cancellation, never on completion — r_schedule.py:321,466 vs 410-443
- revise — mismatch — worked example now says "a duration of 240 minutes" rather than naming a nonexistent field — r_schedule.py:46
- insert — ambiguity — `physician_user_id` opaque, stored verbatim, never resolved or role-checked — r_schedule.py:181
- insert — ambiguity — `start_at`/`end_at` never compared with the clock at creation, start or completion — r_schedule.py:188-191
- insert — ambiguity — the four conditional references treat explicit null as omission (null-where-required still fails); `planned_device_count`, `max_concurrent_cases`, `overnight_capable` reject explicit null — shape.py:220-232, r_schedule.py:182-212
- insert — ambiguity — reference resolution order patient -> case -> scope -> block -> lot — r_schedule.py:215-227
- insert — ambiguity — RETIRED is the only scope posture blocking creation; shelf life not consulted at creation — r_schedule.py:239-240
- insert — ambiguity — overlap and buffer tests consider only SCHEDULED/IN_PROGRESS bookings, and only the nearest live booking on each side — r_schedule.py:93-127
- insert — ambiguity — lot item-type check knows only the two mapped procedure types — r_schedule.py:13-16,266-269
- insert — ambiguity — concurrency counted over SCHEDULED/IN_PROGRESS/COMPLETED — r_schedule.py:137, calc.py:393
- insert — ambiguity — explicit null `attending_physician_user_id` counts as not supplied for both the gate and the write — r_schedule.py:366-401
- revise — ambiguity — start's shelf-life parenthetical expanded to the three-limb test — calc.py:474-480
- insert — ambiguity — completion can fire EXHAUSTED->ACTIVE and clear shortfall flags; the case hop is conditioned on the case still being SCHEDULED — r_schedule.py:431,438-442
- insert — ambiguity — cancel restores the case from the private pre-schedule status with the `requires_prior_auth` fallback, only while the case is still SCHEDULED — r_schedule.py:324,468-475

### Five referred items — disposition
1. `return_reason` discarded (r_audiology.py:257) — PINNED in §3.7 "Returning a device", worded to mirror §3.5's `void_reason`.
2. `calc.trial_refund` (calc.py:349-374) — "+1" day rule and the POST_TRIAL double-zero were already pinned; the *worked example* was arithmetically wrong, so REVISED as a mismatch.
3. `calc.recompute_block` (calc.py:402-420) — bidirectional FULL<->OPEN and `utilization_bps = 0` at zero capacity were ALREADY pinned (§3.9 line 368); no edit needed. Adjacent false claim that utilization is re-evaluated on completion was revised instead.
4. `calc.py:470-480` — `mec_test_due = (cycle_count + 1) % 10 == 0` already pinned; the null-`hld_expires_at` limb was a MISMATCH, revised in both §3.8 and §3.9 Starting.
5. `calc.refresh_lot` (calc.py:435-442) — PINNED as a §3.8-local consequence in "What the buckets mean"; §2.11 deliberately not re-edited (pass-1 territory).

### Suspected cross-pass contradictions — reported only, not fixed (for pass 4)
- §2.11 (pass 1) lists `duration_minutes` among stored computed fields, but only bookings have it; a `SurgeryCenterBlock` does not — r_schedule.py:38-49 vs :303.
- §3.5 line 256 (pass 2) calls the vial `label_text` check "the one rung-3 check in the service that cannot be judged before a reference has been resolved"; the study metric-set check has the same property against the path row — r_audiology.py:87-98. Possibly compatible (body ref vs path id) but worth adjudicating.
- §2.3 (pass 1) is silent on boolean-filter spelling while `shape.q_bool` accepts only exactly `true`/`false` — shape.py:279-287. Pinned locally in §3.8/§3.9 instead of touching §2.3.

### Remaining unclosed silence in pass 3's partition
- `expected_study_version` has no integer bounds (`shape.v_int()` at r_audiology.py:139), consistent with §2.7's plain "an integer" — left as is.
- §2.11's `duration_minutes` listing (above) is pass-1 territory and left for pass 4.

Verification: 542 lines / 172,319 chars; 5 `## ` headings; 73 `| \`ERR_` rows; tail ends on `| \`ERR_BLOCK_NOT_OPEN\` | 409 |`; Step 8's §3.9 sentence about the omitted `attending_physician_user_id` staying at the null it was created with is intact. A `difflib` opcode diff against `PRD_FINALIZED.md` shows 40 changed hunks; note that a naive line-by-line zip diff misreports everything from line 301 onward, because pass 1 inserted one line at 78 (`PRD_FINALIZED.md` is 541 lines, `PRD_COMPLETED.md` is 542); that offset is an artifact, not evidence of §4/§5 edits.

## Step 9: Complete PRD — 2026-09-06T09:09:00.000Z (pass 4 of 4: reconciliation)

Purpose of this pass: partitioned passes report cross-pass contradictions instead of fixing them, and an out-of-partition silence gets referred rather than closed. Pass 4's worklist was exactly those eight leftovers (A-H) plus a targeted self-consistency read for §2 universals that a §3 pin had since contradicted. No fresh exhaustive PRD-vs-impl scan was attempted — by design.

**No `cp` was run.** 13 targeted `Edit` calls, never a whole-file `Write`.
- Before: **542 lines / 172,319 chars**
- After: **546 lines / 178,067 chars** (+4 lines = two paragraph breaks for the two inserted paragraphs; +5,748 chars)

### Worklist verdicts A-H

**A — FIXED.** `r_schedule.py:38-49` creates a `SurgeryCenterBlock` with `booked_case_count`/`booked_minutes`/`capacity_minutes`/`utilization_bps` and no `duration_minutes`; `r_schedule.py:303` is the only writer of the field, on a booking.
- §2.11 — revise — scoped `duration_minutes` in the computed-field list to a booking, and stated that a block carries none, its window length surviving only inside `capacity_minutes` — r_schedule.py:37,46,303

**B — FIXED (softened; the distinction is real but the qualifier was implicit).** `r_immuno.py:54-62`: the label check sits between `find_ref("patients")` and `find_ref("supply_lots")` — it genuinely waits on a *body* reference (behind rung 5). `r_audiology.py:87-98`: the metric set waits only on the *path* id `study_id` (rung 4). So the claim is true of body references only, and as written ("a reference") it was a false universal — `r_allergy.py:144-148` is a third counterexample on a path id.
- §3.5 — revise — "cannot be judged before a **body** reference has been resolved", naming the §3.7 metric set and §3.3 reading count as path-identifier cousins, so the claim reads as "the only place rung 3 sits behind rung 5" — r_immuno.py:54-62, r_audiology.py:87-98, r_allergy.py:144-148

**C — FIXED.** `calc.py:110-112` `vol_out` returns `float(Decimal.quantize(0.01))`, and `envelope`/Flask emit it as a JSON number, so 5.00 -> `5.0`. §2.6 did read as a wire guarantee.
- §2.6 — insert — "Two decimal places is a statement about the *value* and not about its spelling on the wire", with the `5.0`/`0.0`/`0.3`/`0.05` renderings and a note that `5.00`-style literals elsewhere in the doc name the quantised value; worded to match pass 2's §3.5 pin — calc.py:110-112

**D — FIXED.** Full enumeration from source: exactly three rung-3 checks are judged after a row is fetched — `r_immuno.py:59-60` (body ref), `r_audiology.py:89-98` (path id), `r_allergy.py:147-148` (path id). Everything else that calls `shape.bad` does so before any resolution, including `r_assets.py:193` (before the `find` on line 195).
- §2.8 rung 3 — insert — one paragraph after rung 3 naming the three exceptions and their respective waiting-points, without restating the individual rules — r_immuno.py:59, r_audiology.py:89-98, r_allergy.py:147

**E — FIXED.** `r_immuno.py:283-291` clearance gates on three things at rung 7 (`status != ADMINISTERED`, `observation_cleared_at is not None`, `reaction_grade > 1`); `r_immuno.py:321-322` void gates on the first two. §2.8 rung 7 named only the first, and its enumeration reads exhaustive.
- §2.8 rung 7 — revise — the dose clause now names all three sub-checks and notes the grade is judged at rung 7 ahead of the window — r_immuno.py:283-291, r_immuno.py:321-322

**F — FIXED (as a self-consistency repair, not a new rule).** `shape.q_bool` (`shape.py:279-287`) has exactly two call sites service-wide: `r_assets.py:57` (`mec_test_due`, §3.8) and `r_schedule.py:67` (`overnight_capable`, §3.9). Both already pinned by pass 3. However §2.3 enumerated only identifier/enum/numeric filter kinds while §3.9's pin back-references "like every boolean filter in the service" — a dangling reference to a general rule that did not exist.
- §2.3 — insert — added the boolean kind to the filter-kind enumeration with the exact `true`/`false` spelling and the rejected variants, plus a note that the service declares boolean filters on those two endpoints only — shape.py:279-287, r_assets.py:57, r_schedule.py:67

**G — FIXED.** Pass 1's premise was partly wrong and pass 2's refusal was right for the wrong reason. The *order-branch* reaction does **not** demote: `r_allergy.py:204-207` `_cascade_rescore` writes `risk_score` directly and never touches the tier, with promotion-only at `r_allergy.py:257-258`/`273-274`. `rescore_patient` (`calc.py:217-219`, symmetric via `tier_for_score`) has exactly three call sites: `r_registry.py:122` (registration, no prior tier), `r_registry.py:164` (chart revision) and `r_allergy.py:186` (readings roll-up). The latter two can genuinely demote — and neither reverses hop three or hop four, since nothing in the service ever writes `requires_supervised_administration` or `requires_physician_presence` back to false.
- §3.1 — insert — a paragraph after "Supervision follows the score" stating the tier is re-derived not latched, naming the three re-deriving operations and the four ways a score can fall, marking §3.4 as the promotion-only exception (so pass 1's §3.4 pin is not contradicted), and pinning that a demotion unwinds none of the cascade's flags — calc.py:213-219, r_registry.py:164, r_allergy.py:186, common.py:106-117

**H — FIXED.** `common.py:96-103` passes `order["method"]` with no `step`, so `calc.observation_minutes` short-circuits to 0 at `calc.py:224-225` for a `SERUM_IGE` order. Pass 1's §3.4 hop-three sentence claimed the hop "raises each of them to at least 90 minutes" — false for the §3.2 dead-end order, which sits in `ORDERED` for ever. `common.py:103` touches unconditionally, so the row is still versioned.
- §3.4 — insert — hop three now states the re-derivation reads each order's own `method` with no step in play, that a `SERUM_IGE` order comes back to exactly 0, and that the hop reaches every `ORDERED` order but raises only the skin-method ones — common.py:96-103, calc.py:223-234

### Additional self-consistency contradictions found and fixed

- §2.8 rung 12 / §3.9 — revise — §2.8 said a `RETIRED` scope "is reported one rung higher"; §3.9's start narrative says "the next rung", i.e. lower. Source: `r_schedule.py:387` lets `RETIRED` through the rung-12 check and it lands on rung 13's `ERR_SCOPE_REASSIGNMENT_REQUIRED` (`r_schedule.py:390-391`, flag raised by `common.py:149-155` via `r_assets.py:121-125`), while a *creation* stops it at rung 7 (`r_schedule.py:239-240`). Rewrote §2.8 to say rung 13, one rung lower, and to separate start from creation.
- §2.11 — revise — `available_quantity` was named as one of the "two deliberate exceptions" refreshed on read and then listed again among "every other computed field ... written at the moment the operation runs". Removed the duplicate from the enumeration; the exception sentence already covers its write-on-mutation behaviour (common.py:52-57, calc.py:435-438).
- §3.8 — revise — "Only two can raise `available_quantity`" contradicted §3.9's completion paragraph, which correctly says a completion can lift availability. Source: `r_schedule.py:427-431` releases a reservation of `planned_device_count` while consuming only `devices_used_count` and calls `lot_replenish_check`. Changed to three raisers and added that a refund settlement raises nothing (r_audiology.py:308-309, matching §3.7's own wording).
- §2.6 — revise — "Two clinical measures carry a single decimal place" read as *exactly* one, contradicting §3.7's "an integral `40` is never re-rendered as `40.0`". `shape.v_number` (`shape.py:118`) rejects only *more* than `places`, so one place is a ceiling. Changed to "at most a single decimal place".
- §2.8 rung 10 — revise — "must be venued at a block whose `overnight_capable` is true" implied a block is mandatory, which §3.9's precise pin contradicts. `r_schedule.py:245` guards on `block is not None`; an office-suite booking is stopped by rung 13's `ERR_PEDIATRIC_VENUE_REQUIRED` (`r_schedule.py:276-279`) instead. Added the scoping clause.

### Deliberately left unpinned

- §2.8 rung 10's *enumeration order* (epinephrine listed before dermatographism) versus §3.2's explicit "dermatographism first" (`r_allergy.py:93-98`). Not a contradiction: §3.2 opens by deferring intra-rung order to itself ("where two of them share rung 10, in the order stated here"), and §2.8 rung 10 makes no ordering claim. §3.5 likewise states its own dose-gate order, which matches `r_immuno.py:197-207`.
- §3.7's "That one check is the exception to this rung's usual precedence over rung 4" — scoped to that endpoint by the following clause ("every other rung-3 violation on this endpoint"), and now safely anchored by the new §2.8 rung-3 paragraph, so no local edit was needed.
- `volume_ml_initial`'s "between 1.00 and 10.00 millilitres to two decimal places" in §3.5 — also a ceiling rather than an exact width (`shape.py:118` with `places=2`), but §3.5 already states the explicit-null and default behaviour precisely and the new §2.6 sentence establishes the general ceiling reading. Left alone under the minimal-change rule.
- No fresh exhaustive PRD-vs-impl scan was attempted, per instructions; all edits trace to a worklist item or to a sentence-vs-sentence contradiction inside PRD_COMPLETED.md.

### Final verification (pass 4's own)

`wc -l` = **546** (>= 542) · `wc -c` = 178,067 · `tail -3` ends on `| \`ERR_BLOCK_CAPACITY_EXCEEDED\` | 409 |` / `| \`ERR_BLOCK_NOT_OPEN\` | 409 |` · all five `## ` headings present · 20 `### ` sub-headings, unchanged — no new sections · §5 table **73** `ERR_` rows · §4 table **65** method rows · Step 8's three pins all still present and unique.

### Step 9 aggregate

Four passes, **101 changes** total over `PRD_COMPLETED.md` (pass 1: 29 · pass 2: 31 · pass 3: 28 · pass 4: 13). 541 lines / 139,202 chars in -> 546 lines / 178,067 chars out (+38,865 chars, +28%). Only pass 1 ran the `cp`; no pass ever used a whole-file `Write`.

## Pipeline complete — 2026-09-06T09:12:00.000Z

Orchestrator-run final verification, independent of every subagent's own claim:

- `workspace/PRD_COMPLETED.md` — **546 lines / 178,067 bytes**. `cmp` against `PRD_FINALIZED.md` differs at byte 6,099 / line 51, and against `PRD.md` differs too, so the Step 9 scan demonstrably ran (a byte-identical PRD_COMPLETED.md would mean it did not).
- Structure intact: **5** `## ` headings (§1 line 3, §2 line 11, §3 line 194, §4 line 396, §5 line 468), **20** `### ` sub-headings, **73** `ERR_` rows in §5, **65** endpoint method rows in §4 — matching the scaffold's 73 errors / 65 endpoints. Tail ends on `| \`ERR_BLOCK_NOT_OPEN\` | 409 |`, a real table boundary.
- Sweep re-summarised from the 8 surviving `results.$i.json` with `workspace/summarize.py` (which keys on `tests[].status`, the runner's actual schema, and cross-checks `total - passed` against the failure list): **rounds 1-8 all 166/166, union of failing tests across all rounds = 0.** 8/8 result files present as deliverables.
- Test artifact: 16 files / 10,196 lines in `test_suite/` with **166 test functions and 166 `Design:` tags** (1:1, no untagged tests); 9 files / 3,935 lines in `test_helpers/`. No stray `test_suite/` or `test_helpers/` under `workspace/`.
- Difficulty-directive containment re-verified across every deliverable (`*.md`, `*.yaml`, `*.py`): the only hits for "harder than expert"/"expert level" are inside this worklog's own audit notes. `SCAFFOLD.yaml`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, the tests and the implementation are all clean.
- Exactly one task directory was created, the pre-assigned `task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty`; no index was auto-allocated and no sibling was touched.
- Housekeeping: `.scratch/` removed (17 scratch files across step4/step5/step8/step9_pass4), all `__pycache__`/`*.pyc` swept, one `worklog.md` at the task root and no cwd-drift strays.

All nine steps complete.
