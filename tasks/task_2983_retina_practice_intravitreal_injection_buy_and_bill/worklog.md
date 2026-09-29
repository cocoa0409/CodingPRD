# Worklog — task_2983_retina_practice_intravitreal_injection_buy_and_bill

## Step 1: Create task directory — 2026-09-06T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill` and its `workspace/` subdirectory. Index 2983 was pre-assigned by the orchestration caller; no scan of `tasks/` was performed and no other task directory was created (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-06T03:04:35.759672120Z

All three artifacts are complete and the scaffold lint is clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1700

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/`)
- `SCAFFOLD.yaml` — 3788 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1617 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4165 lines

All three parse with `yaml.safe_load`; each design file has exactly one top-level key; `SCAFFOLD.yaml` contains neither design key. `workspace/` and `worklog.md` untouched; no scratch dir left behind.

**Domain model (§1.0–§1.7)** — `retina-intravitreal-buy-and-bill`, `api_prefix: "/"`, `difficulty_level: expert_plus`, archetypes compliance_audit / ledger_reconciliation, layers `dual_variant_calculation, cascading_side_effects, optimistic_concurrency, selector_policy`, topology flat, state-machine shape parallel, role model segregation_of_duties, consistency immediate.
- **16 entities**: Payer, Drug, PayerDrugPolicy, Patient, Clinician, ImagingStudy, TreatmentPlan, DrugLot, Vial, PriorAuthorization, InjectionEncounter, Claim, AssistanceEnrollment, AdverseEvent, LotRecall, RecallNotification.
- **12 state machines** (TreatmentPlan, PriorAuthorization, InjectionEncounter, Claim's two line dimensions, DrugLot, Vial, AssistanceEnrollment, AdverseEvent, LotRecall, RecallNotification, Clinician), **2 concurrency rules** (both OCC on `TreatmentPlan.version` via `expected_treatment_plan_version`), **13 calculations**, **46 ordered validations**, **75 endpoints**, **70 errors**, **6 roles**.

**§1.8** — 9 rules × 2 = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9** — **89 instances** (73 with full `test_recipe`, 16 `excluded_because` stubs, every stub citing an existing §1.8 instance in `rule_id / name` form): entities 12, state_machines 12, calculations 23, validations 22, endpoints 7, errors 3, rbac 4, cross_cutting_complexity_layers 4, consistency_model 2. All 70 catalog error ids are referenced by at least one §1.8/§1.9 instance.

Two consistency repairs made in `SCAFFOLD.yaml` while writing §1.9: (a) the AssistanceEnrollment terminate edge and the `ERR_ENROLLMENT_STATE_INVALID` trigger text contradicted each other on terminating a PENDING enrollment — §1.2's `from` is now `PENDING | ACTIVE | EXHAUSTED` and the error text names TERMINATED/EXPIRED; (b) per a standing lesson about the directive leaking into PRD.md, the `Generate task harder than expert level!` line was stripped from the `scenario:` key (the numbered domain description is untouched) — revert if you want it verbatim.

**Orchestrator note:** repair (b) is exactly the desired behaviour — the difficulty directive must never reach PRD.md. Verified independently: `grep -n "harder than expert" SCAFFOLD.yaml` returns nothing.

## Step 3: Copy shared files — 2026-09-06T03:04:35.774379218Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T03:25:52.942636196Z

PRD generation is complete.

## Deliverable
`workspace/PRD.md` — **554 lines**, built in six verified incremental appends (87 → 196 → 250 → 288 → 336 → 371 → 395 → 477 → 554), no truncation at any step. Nothing else in the task directory was created, moved or modified; `worklog.md`, `SCAFFOLD.yaml` and both design files are untouched, and neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was ever opened, grepped or referenced. No sibling task was read. Scratch was confined to `.scratch/step4/` and removed.

## Section list
1 Introduction; 2 Global Specifications (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties and the Version Counter, 2.5 The Logical Clock, 2.6 OCC on the Treatment Plan, 2.7 Money/Volumes/Rounding, 2.8 Request Validation Order and Failure Precedence, 2.9 Vial Conservation and Lot Counter Integrity, 2.10 Segregation of Duties, 2.11 Cascade Propagation and Compensating Reversal, 2.12 Resource Addressing and Filtered Discovery); 3 Business Logic (3.1 Reference Data Foundations, 3.2 Imaging Interpretation and the Disease-Activity Verdict, 3.3 Opening a Treatment Plan / Treat-and-Extend Interval, 3.4 Payer Authorization: Step Therapy, Decisions and Appeals, 3.5 Buy-and-Bill Inventory Custody, 3.6 Booking an Injection Encounter, 3.7 Documenting the Injection / Wastage / Voiding, 3.8 Revenue Cycle, 3.9 Adverse-Event Surveillance, Lot Clusters and Recall Management); 4 API Endpoint Definitions; 5 Error Code Catalogue.

## Coverage
- **Endpoints:** 75 / 75 table rows (Method, Path, Description, Authorized Role(s)); all 6 roles named.
- **Errors:** 70 / 70 catalogue rows; all 70 identifiers also appear inside §1–§3 prose at their point of use.
- **Validations:** all 46 priority-ordered rules enumerated 1–46 in §2.8 with error ID, HTTP status and `applies_to` scope.
- **Calculations:** all 13 documented in prose with every constant value verbatim (300, 28, 14, 3, 24, 50000, 0.5, 1000, 2000, 365, 30, 15, 2, 3/10/30); all dual variants covered (interval extension/reduction/loading, exposure carrying/expiration, margin provisional/realized).
- **State machines:** all 12 / 71 expanded transitions, including both parallel `Claim` axes, the divergent `RELATED`/`UNRELATED` adjudication branches, and all 5 compensating edges.
- **Concurrency:** both OCC rules on `expected_treatment_plan_version` (§2.6 and again at each call site).

## Hard Contract results
- **CONTRACT 1 — Field-Name Coverage: PASS.** 192/192 required names verbatim in backticks; plus a 155-symbol check (enum members, state names, 6 role names, 70 error IDs) — 0 missing after one repair (`INDEPENDENT_FOUNDATION` / `FREE_DRUG_PAP` made verbatim).
- **CONTRACT 2 — Rule Coverage: PASS.** One gap found and fixed: recall initiation now states both `AVAILABLE` and `QUARANTINED` source states, `ERR_LOT_STATE_INVALID` for an already-`RECALLED`/`EXPIRED` lot, and the lot `version` bump. Two "and so on" constructions replaced with explicit enumerations.
- **CONTRACT 3 — §3 Path Purity: PASS.** 370 distinct backtick tokens in §3; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path.

## Two judgement calls flagged by the generator
1. **Uncatalogued transition preconditions.** Several scaffold preconditions (inactive `Patient`/`Drug` at plan activation, a `QUIESCENT` baseline study, documenting an encounter you did not book, a suspended wastage attester, voiding a `DOCUMENTED` encounter that already has a claim) nominate no error ID. Rather than inventing IDs, §3 opens with a normative convention mapping any such precondition to the owning entity's state error at HTTP 409, and reuses catalogued `ERR_PAYER_POLICY_MISSING` / `ERR_CLINICIAN_NOT_ELIGIBLE` where their messages match exactly.
2. **Unmapped computed-response keys.** The lot-exposure and expiration-sweep responses declare output keys the scaffold never binds to formula terms; the PRD pins an explicit per-basis and per-summary meaning for each (`days_held`, `unconsumed_vials`, `unconsumed_value_cents`, `exposure_cents`, `projected_burn_vials`, `at_risk_vials`, `lots_swept`, `lots_expired`, `vials_expired`, `carrying_cost_accrued_cents_total`, `swept_at`).

**Orchestrator verification (truncation guard):** independently re-checked — `wc -l` = 554; heading scan shows all of §1–§5 present with 12 §2 subsections and 9 §3 subsections; `tail -4` ends on the 70th complete error-table row with a trailing newline (no mid-sentence/mid-table cut); endpoint table rows = 75, error table rows = 70. `grep` for "harder than expert", "expert_plus", "SCAFFOLD", "test_recipe" in PRD.md returns nothing — no difficulty-directive or scaffold leakage.

## Step 5: Generate unit tests — 2026-09-06T05:22:11.465184053Z

Step 5 is complete. Final state of the deliverables:

## Files (all at the TASK ROOT — confirmed, nothing under `workspace/`)
`workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read, never touched).

**`test_helpers/`** — 9 files, 3329 lines: `__init__.py` 104, `api_client.py` 448, `api_errors.py` 164, `assertions.py` 205, `constants.py` 251, `factories.py` 561, `fixtures.py` 1112, `test_users.py` 127, `types.py` 357.

**`test_suite/`** — `conftest.py` 82; depth suite `test_01` 229, `test_02` 161, `test_03` 247, `test_04` 298, `test_05` 255, `test_06` 218, `test_07` 287, `test_08` 274, `test_09` 251; breadth suite `test_10` 448, `test_11` 442, `test_12` 1287, `test_13` 2207, `test_14` 531, `test_15` 276, `test_16` 359, `test_17_corner_cross_cutting.py` 225, `test_18_corner_consistency.py` 218.

## Coverage (verified mechanically, not by eye)
A script parsed both design indices and every test docstring: **18/18 non-stub §1.8 instances translated, each with >=2 tests; 73/73 non-stub §1.9 instances translated, each with >=1 test. Zero instances skipped by the PRD-first filter — no gaps.** Every test carries exactly one `Design:` line, it is the last docstring line, its section matches the yaml's own `section`/`rule_id`, and it points at a real non-stub instance name. The word "scaffold" appears nowhere.

**16 skipped `excluded_because` stubs** (each yaml-declared as a replay of a §1.8 instance): corner_imaging_disease_activity_is_server_computed, corner_cyclic_authorization_shape_reenters_submitted, corner_parallel_claim_line_dimensions_advance_independently, corner_lot_recall_cascade_down_to_vials_and_notifications, corner_compensating_void_of_a_documented_encounter, corner_disease_activity_threshold_is_inclusive_on_the_constant, corner_billing_units_are_rounded_per_line_before_summation, corner_foundation_tier_cap_is_keyed_on_the_coinsurance, corner_claim_margin_provisional_and_realized_use_different_cost_bases, corner_lot_exposure_carrying_and_expiration_diverge_on_one_lot, corner_capacity_window_is_closed_at_twenty_four_hours, corner_stale_plan_version_outranks_clinician_eligibility, corner_interval_violation_outranks_day_capacity, corner_remittance_posts_one_dimension_at_a_time, corner_recall_cascade_reaches_vials_encounters_and_notifications, corner_margin_is_reported_twice_from_the_same_claim.

## Verification
`python3 -m compileall -q test_helpers test_suite` -> clean. `PYTHONPATH=<task root> python3 -m pytest --collect-only -q test_suite` -> **109 tests collected, no collection errors.** Scratch cleaned (`rm -rf .scratch/step5` only), `__pycache__` removed.

## Deliberate PRD-first divergences from the design indices (for Step 7's awareness)
1. **Expiration sweep totals** (`corner_expiration_sweep_visits_every_lot_but_expires_only_the_lapsed_one`): the yaml asserts `carrying_cost_accrued_cents_total == 11211` and says 14608 would mean "accruing before expiring". PRD §3.5 declares the per-lot order as accrual-recompute-and-persist **then** `AVAILABLE -> EXPIRED`, so the test asserts **14608 on sweep 1** (lapsed lot's own accrual 3397) and 11211 on sweep 2.
2. **Envelope instance**: dropped the yaml's claim that `api_request_timestamp` equals the logical clock — the PRD only declares it "server-generated" with three fractional digits.
3. **Pagination instance**: the three lots are created at three distinct clock instants, because `created_at`-ascending order is not uniquely derived for rows sharing one instant.

## Citation hygiene pass
A second script checked every quoted fragment in all 109 docstrings against `workspace/PRD.md` verbatim. It found 11 quotes that were paraphrases or silent elisions, in test_09, test_10, test_12 (billing-unit split, wastage-by-vial-type, modifier codes, `NONE` preference, adverse-event reportability), test_13 (precedence consequence, policy key, plan state/treatability — the old quote invented a `COMPLETED` plan status and omitted `INTENSIFIED`), and test_14 (sweep elision). All were replaced with verbatim, grep-able PRD sentences; the remaining three flags are false positives from nested quotation marks inside the docstrings.

**Orchestrator verification:** `test_helpers/` and `test_suite/` confirmed at the task root; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/. Independent re-collect: 109 tests, 0 errors.

## Step 6: Generate implementation — 2026-09-06T05:22:11.477178017Z

Step 6 complete. The implementation is finished, verified, and all smoke servers are down.

## Modules (12 files, 3,651 lines, `workspace/implementation/`)
- `core.py` 638 — envelope/`meta` builder, 70-entry `ERROR_STATUS` map, `ApiError`/`fail`, ISO-8601-3dp time helpers + whole-day truncation, Decimal/`ROUND_HALF_UP` money helpers, the 16-table in-memory `Store` + global `RLock`, `base_row`/`touch` (version bump at most once per request), `publish` serializer, the `api(roles)` auth decorator, `Field`/`validate` coercion engine, pagination + filter + `listing` helpers, 16 `get_*` FK lookups
- `domain.py` 552 — pure domain math: vial-counter recomputation, FEFO selection support, authorization usage, treat-and-extend interval stepping, schedule replay, plan suspension cascade, patient-responsibility waterfall + compensating foundation reversal, margin finalization, carrying-cost/exposure, `billing_units_split`, modifier assembly, reportability, recall-notification generation
- `routes_reference.py` 394 — 17 routes (logical clock, payers, drugs, payer-drug-policies, patients, clinicians + suspend)
- `routes_clinical.py` 274 — 10 routes (imaging studies, treatment plans + activate/suspend/resume/discontinue)
- `routes_inventory.py` 249 — 9 routes (drug lots, lot exposure, quarantine/release, expiration sweep, vials)
- `routes_authorizations.py` 258 — 6 routes (PA submit/decision/appeal, shared `occ_guard`)
- `routes_encounters.py` 411 — 6 routes (encounter create with effective-drug cascade, authorization selection, FEFO vial reservation; document, attest, void)
- `routes_billing.py` 352 — 11 routes (claim create/submit/remittance/appeal, assistance enrollments)
- `routes_safety.py` 442 — 16 routes (adverse events + adjudication cascade, lot recalls lifecycle, recall notifications)
- `app.py` 73 — `create_app()`, 7 blueprints, `strict_slashes=False`, HTTPException/Exception handlers returning the error envelope, `app.run(host="0.0.0.0", port=$PORT, threaded=True)`
- `start.sh` 7 — guarded `pip install` then `exec python3 app.py`, foreground, reads `$PORT`
- `requirements.txt` 1 — `flask>=2.2`

## Endpoint count
`grep -cE '^@bp\.(get|post|put|patch|delete)\('` over `routes_*.py` = **75** (17+10+9+6+6+11+16), and `app.url_map` independently reports **75** distinct (rule, method) pairs — exactly the PRD's 75 declared endpoints.

## Validation-priority structure
The PRD's 46-step precedence (§2.8) is enforced structurally rather than by a rule table, so ordering is a property of code position:
1. **Steps 1-4 (auth)** live entirely in the `core.api(roles)` decorator: missing headers -> `ERR_MISSING_AUTH_HEADERS`, unknown role -> `ERR_UNKNOWN_ROLE`, role not on the endpoint -> `ERR_ROLE_NOT_PERMITTED`, entity-backed role identity resolution (`RetinaSpecialist`->Clinician, `Patient`->Patient).
2. **Step 5 (payload/query shape)** is the first statement of every handler: `get_body()` then `validate(body, [Field(...)])` raising a single `ERR_INVALID_REQUEST`. Query-string validation (`pagination()`, `query_filters()`) is hoisted above path lookups — e.g. lot-exposure validates `basis` before the lot 404.
3. **Step 6 (path FKs)** then **step 7 (body FKs)** are separate `get_*` groups, path first.
4. **Step 8** patient-owns-notification, **steps 9-11** separation of duties (attester!=injector, adjudicator!=injector, recall closer!=initiator), **step 12** the `expected_treatment_plan_version` OCC guard (shared `occ_guard` for both encounter and PA creates), **step 13** state-machine gates — each a single labelled `if` block in that fixed order.
5. **Steps 14-46 (business rules)** follow in ascending step number with the step number as an inline comment at each site (encounter create: 14 clinician -> 15 eye -> 16 stale imaging -> effective-drug resolution -> 17 interval -> 18 day capacity -> 19 override reason -> 20 policy -> 21 exclusion -> 22-25 authorization -> 26 vial), and every rejection raises before any mutation.

Storage is in-memory only (module-level dicts in `Store`); nothing seeded, nothing on disk. Verified by relaunching `start.sh` on the same port: round 1 created a payer and listed it; round 2 returned `total_count: 0` with the clock back at its default `2026-08-01T00:00:00.000Z`.

## Smoke test (port 47231) — all 16 probes passed
POST/GET on `/payers`, `/drugs`, `/patients` returned 201/200 with the `{data, meta:{api_request_id, api_request_timestamp}, response_type}` envelope; list returned `response_type: array` with `limit/offset/total_count/has_more`; bad enum -> `ERR_INVALID_REQUEST` 400; 5-decimal `coinsurance_rate` -> `ERR_INVALID_REQUEST` 400; duplicate `mrn` -> `ERR_DUPLICATE_RESOURCE` 409; no headers -> `ERR_MISSING_AUTH_HEADERS` 401; unknown role -> `ERR_UNKNOWN_ROLE` 401; wrong role -> `ERR_ROLE_NOT_PERMITTED` 403; unknown id -> `ERR_PATIENT_NOT_FOUND` 404; `limit=0` -> `ERR_INVALID_REQUEST` 400; `POST /_clock/set_current_utc` -> 200. Also verified: the PRD's billing-unit worked example (0.06 ml of a 0.27 ml fill, 40 mg/ml, 1 mg/unit -> 2 administered + 8 wasted = 10 units), carrying exposure 180000 x 0.20 x 31 / 365 = 3057.5 -> **3058** cents half-up, and a full end-to-end chain (plan -> lot -> PA -> encounter -> document -> attest -> claim -> remittance -> adverse event -> recall) including OCC 412, biosimilar substitution, void-replay and quarantine/release.

Two notes: (1) all smoke servers started were killed by PID and confirmed gone (`pgrep -f "python3 app.py"` gives false positives because it matches the detecting shell itself; verify with `ss -ltnp`); (2) port 41873 was already occupied by another pipeline, so sweeps must let the runner allocate ports.

## Step 7 preparation (orchestrator) — 2026-09-06T05:22:11.493628134Z

Pre-wrote `workspace/sweep.sh`: an 8-round parallel sweep that clears `results.*.json`, gives each round its OWN log (`sweep.round.$i.log`, avoiding the spliced-single-fd problem), joins with `wait`, and then writes a `workspace/SWEEP_DONE` sentinel. Handing Step 7 a script file rather than an inline one-liner removes the `$T` quoting hazard that injects literal quotes into `--start-command`, and the sentinel removes the temptation to relaunch when the `setsid` launcher returns early.

## Step 7: Run tests and iterate — 2026-09-06T05:44:25.695310605Z

All 8 rounds green. Final sweep: `passed=109 / total=109` in every round.

**Iterations run: 2 full 8-round sweeps.**
- Iteration 1: all 8 rounds `passed=100 / total=109` — an identical 9-test failure union in every round (fully deterministic, no load-induced noise; cross-checked 9 == 109 − 100).
- Iteration 2 (final, after the fixes below): rounds 1-8 all `passed=109 / total=109`, 0 non-passed.

**Tests deleted: none.** No failing test rested on PRD silence; every one was either a mistranslation of a PRD sentence, a test-artifact bug, or a genuine implementation gap.

**Fixes to `test_suite/`**
- `test_12_corner_calculations.py` — `test_a_single_fluid_flag_makes_a_thin_scan_active`: the helper passed the same fluid flags both explicitly and through `**flags`, raising `TypeError: got multiple values for keyword argument 'subretinal_fluid'` before any HTTP request; now builds a base dict and applies `base.update(flags)`.
- `test_03_non_linear_state_machine.py` — `test_the_later_drug_payment_closes_both_axes_and_prices_the_shrunken_allowable`: the test assumed the admin-line `DENIED` branch stores the client-supplied `admin_allowed_cents=0`, but PRD §3.8 gives that branch an exhaustive write list (`admin_paid_cents` -> 0 and `denial_code`) in deliberate contrast to the `PAID` branch, where "the remitted allowables replac[e] the expectations written at creation". Payload reduced to `admin_line_denied_payload(denial_code="NOT_COVERED")` and the whole money chain recomputed from the PRD waterfall (total 172000, coinsurance 34400, foundation 20000, patient 14400, writeoff 9600, realized margin 30400).
- `test_13_corner_validations.py` — `test_the_lot_number_key_is_scoped_to_its_drug_and_the_lot_state_gate_pre_empts_the_recall_guard`: the test's own docstring cited §2.8 step 13 preceding step 40, yet expected `ERR_RECALL_ALREADY_OPEN` on a lot already `RECALLED`; expectation corrected to `ERR_LOT_STATE_INVALID`.
- `test_13_corner_validations.py` — `test_the_claim_line_gates_refuse_early_money_a_second_submit_and_a_second_claim`: ERROR-PRECEDENCE ambiguity. PRD §3.7 names `ERR_DUPLICATE_CLAIM` for a second claim, but creating the first claim moves the encounter `ATTESTED -> BILLED`, so the same call also trips §2.8 step 13's `ERR_ENCOUNTER_STATE_INVALID`, which the ladder ranks earlier. Relaxed to `validate_error_is_one_of([ERR_DUPLICATE_CLAIM, ERR_ENCOUNTER_STATE_INVALID])` with an explicit 409 status assertion retained.
- `test_13_corner_validations.py` — `test_an_authorization_past_its_window_is_persisted_as_expired_by_the_rejection`: setup approved 3 injections against `pol_comm_ref`, whose `pa_max_injections` is 1, so setup died with HTTP 422 `ERR_APPROVED_INJECTIONS_EXCEED_POLICY`. Changed to `approved_injections=1`; the shared fixture was left alone because a sibling test depends on the cap of 1.
- `test_04_transitive_cascade.py` — `test_recalling_a_lot_freezes_every_vial_and_voids_the_draft_holding_one`: STEP 1c partial-coverage split. PRD §3.9 describes the recall cascade as "both its `IN_STOCK` and its `RESERVED` vials move to `QUARANTINED`" without mentioning the reservation pointers, while §3.7's release path (which does clear them) is a different branch, and §3.5 explicitly contemplates "a quarantined vial still carrying a reservation pointer". Removed only `assert vial["reserved_for_encounter_id"] is None` and the matching docstring clause; the status, void-reason and counter assertions stay.
- `test_09_compensating_invariant.py` — `test_the_plan_and_the_authorization_are_unwound_to_their_pre_injection_state`: asserted `next_due_date is None` after voiding the only documented encounter, contradicting its own quoted "the schedule ends up where it would have been had the voided injection never been documented" plus activation's "sets `next_due_date` to the logical clock advanced by those 28 days". Changed to `assert_instant_equals(..., "2026-08-29T00:00:00Z", ...)`.

**Fixes to `test_helpers/`: none.** No failure traced to a fixture, factory or role header.

**Fixes to `implementation/`**
- `domain.py` — new `refresh_last_encounter(plan)`: re-derives `last_encounter_id` from the plan's non-`VOIDED` encounter with the greatest `encounter_datetime` and reports whether the pointer moved, per PRD §3.3 ("`last_encounter_id` is likewise **always** the plan's non-`VOIDED` encounter with the greatest `encounter_datetime`"). Called from `void_draft_encounters` so the suspension cascade leaves the pointer on a surviving encounter.
- `routes_encounters.py` — `create_encounter` now calls `refresh_last_encounter(plan)` after reserving the vial (and after `previous_encounter_id`/`interval_days_from_previous` are captured from the pre-creation pointer, as §3.6 requires). This was the real defect behind two failures: PRD §2.6 states "Creating an encounter legitimately mutates its plan — `last_encounter_id` … move", and the implementation only moved the pointer at documentation time. `void_encounter`'s `DRAFT` branch was switched to the same change-conditional helper so the pointer is restored without inventing an unspecified version bump, and `refresh_last_encounter` was added to the `from domain import (...)` list.
- `routes_safety.py` — `create_lot_recall`'s cascade now refreshes `last_encounter_id` on every plan whose `DRAFT` encounter it voided with `void_reason = "LOT_RECALLED"`, so the §3.3 invariant holds on that path too.

These implementation changes turned `test_12_corner_calculations.py::test_vial_selection_burns_the_earliest_expiry_then_the_dearest_lot` (`second["previous_encounter_id"] == first["id"]`) and `test_18`'s `test_every_derived_field_is_already_correct_in_the_response_that_caused_it` (`plan_after_create["last_encounter_id"] == created["id"]`) green. No endpoint, response field, header or seeded data was added; storage remains in-memory dicts only.

**Orchestrator verification:** all 8 `results.$i.json` present (timestamped 05:42), each independently re-parsed on the runner's own `tests[].status` key: `passed=109 total=109 nonpassed=0` for every round; `total - passed == 0` cross-check holds. `workspace/SWEEP_DONE` contains 2026-09-06T05:42:47Z. Step 7 did not touch worklog.md.

## Step 8: Finalize PRD — 2026-09-06T05:51:41.959942083Z

PRD_FINALIZED.md is written. 8 targeted edits, all traced to `<step_7_diff>` items.

**Line counts:** PRD.md 554 lines / 122,879 bytes -> PRD_FINALIZED.md 554 lines / 126,841 bytes (0% line delta, +3.2% bytes; every edit is inline within an existing paragraph, no new sections).

**Changes (section — kind — what — impl anchor):**
1. **§2.6** — revise — the "creating an encounter mutates its plan" list overclaimed: impl moves only `last_encounter_id` (re-derived) and `version` at creation; `current_interval_days`/`next_due_date` move at documentation — `routes_encounters.py:281-282`, `domain.py:219-221`.
2. **§3.6 (lineage paragraph)** — insert — after `previous_encounter_id`/`interval_days_from_previous` are captured from the pre-creation pointer, `last_encounter_id` is re-derived under the §3.3 invariant (so a back-dated booking does not take the pointer); nothing else on the schedule moves at creation — `routes_encounters.py:270-282`, `domain.py:85-93`.
3. **§3.3 (suspension cascade)** — insert — the DRAFT-void hop also re-derives `last_encounter_id`, and every cascade that voids a plan's DRAFT encounters does so with no version bump of its own — `domain.py:264-278`.
4. **§3.7 (void from DRAFT)** — insert/revise — pointer re-derived; plan `updated_at`/`version` move only when the pointer actually changes; interval/due date not recomputed; plus a carve-out that on the lot-recall path the vial is already `QUARANTINED`, so nothing is released or cleared — `routes_encounters.py:406-419`.
5. **§3.7 (void from DOCUMENTED)** — insert — the re-derivation is a replay from the plan's *activation* baseline (interval 28, activation's `next_due_date`, run 0) walked forward through the §3.3 branches, so voiding the only documented encounter restores activation's values rather than nulls; `consecutive_quiescent_visits` added to the re-derived list; suspended/discontinued/draft plans still end with `next_due_date` null — `domain.py:238-260`, `routes_clinical.py:220-221`.
6. **§3.9 (recall initiation, precedence)** — insert — lot-state check (§2.8 step 13) precedes the open-recall check (step 40), so a repeat recall on a `RECALLED` lot reports `ERR_LOT_STATE_INVALID` — `routes_safety.py:219-222`.
7. **§3.9 (recall cascade)** — insert — RESERVED->QUARANTINED vials keep `reserved_for_encounter_id`/`reserved_at` (which is what §3.5's release rule needs); the subsequent DRAFT void releases/clears nothing; each affected plan's authorization usage is recomputed and its `last_encounter_id` re-derived, version advancing only when the pointer moves — `routes_safety.py:250-284`, `routes_inventory.py:181-184`.
8. **§3.8 (claim create + admin axis)** — insert x2 — (a) a second claim on the same encounter reports `ERR_ENCOUNTER_STATE_INVALID` because the first claim moved the encounter to `BILLED` and step 13 precedes step 37 (`routes_billing.py:53-64`); (b) the admin `DENIED` write list is exhaustive — a supplied `admin_allowed_cents` is ignored and the creation-time allowable still feeds `total_allowed_cents` (`routes_billing.py:232-235`, `domain.py:327-331`).

**Pre-edit search log** (subject -> paths enumerated -> wording adjustment):
- **Edit 1** — subject: what creation mutates on the plan. Read `create_encounter` (all plan writes), `domain.advance_plan_on_documentation`, `routes_clinical.activate/resume/discontinue`. (c) split the field list into creation-time vs documentation-time rather than deleting fields.
- **Edit 2** — subject: `last_encounter_id` at creation. Read `domain.refresh_last_encounter`, `latest_non_voided_encounter`/`encounter_order_key`, creation's `previous_encounter_id` capture, `advance_plan_on_documentation`. (c) replaced "points at the new encounter" with "re-derived under the §3.3 invariant", because a back-dated booking leaves the pointer where it was.
- **Edit 3** — subject: `void_draft_encounters`. Grepped all callers: `suspend_plan` (suspend endpoint + AE cascade), `discontinue_treatment_plan`, `adjudicate_adverse_event`'s already-SUSPENDED branch. (c) wrote "carries no version bump of its own beyond the one the triggering operation already books" — the AE/already-SUSPENDED branch does no plan touch at all.
- **Edit 4** — subject: the explicit DRAFT void. Read `void_encounter` (both branches), `release_reserved_vial`, compared with the cascade helper. (c) scoped the conditional-version sentence to this endpoint and appended the recall carve-out.
- **Edit 5** — subject: `replay_plan_schedule`. Read it plus `_interval_branch`, `_activation_interval`/`_activation_next_due` writers (only `activate_treatment_plan`; `resume` does **not** refresh them), `plan_encounters(ENCOUNTER_COUNTED)`. (c) added the explicit "not the latest resumption's" clause and the `DRAFT`/`SUSPENDED`/`DISCONTINUED` -> null parenthetical.
- **Edit 6** — subject: recall-creation error precedence. Read `create_recall` gate order, `open_recall_for_lot`, and `release_lot`'s use of the same `ERR_RECALL_ALREADY_OPEN`. (c) confined the claim to the recall-creation endpoint.
- **Edit 7** — subject: reservation pointers on quarantined vials. Enumerated every RESERVED/IN_STOCK->QUARANTINED site: `create_recall`, `quarantine_lot` (IN_STOCK only), the endophthalmitis-cluster hop (IN_STOCK only), `void_encounter`'s ADMINISTERED->QUARANTINED; plus the consumer `release_lot`. (c) scoped the retention statement to the recall path and tied it to the release rule.
- **Edit 8** — subject (a): claim-creation gate order — read `create_claim` (state -> policy -> duplicate) and §2.8 steps 13/20/37; (c) used "in practice" rather than declaring `ERR_DUPLICATE_CLAIM` unreachable. Subject (b): writers of `admin_allowed_cents` — `create_claim`, `post_remittance` PAID branch, `run_waterfall`'s read into `total_allowed_cents`; (c) phrased it as the denial branch ignoring the supplied value, leaving the PAID branch intact.

Not patched (verified as pure fixture bugs, no PRD silence): the `**flags` `TypeError` in test_12, and the `approved_injections=1` vs `pa_max_injections` setup fix in test_13.

**Orchestrator verification:** PRD_FINALIZED.md exists, 554 lines / 126,841 bytes, 8 changed hunks vs PRD.md (not byte-identical), ends on the 70th complete error-table row.

## Step 9: Complete PRD — 2026-09-06T06:33:05.364109894Z

Step 9 was run as FOUR SEQUENTIAL PASSES over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2-4 were forbidden to copy). Rationale: a single-agent full scan of 12 modules against a 554-line PRD reliably under-covers and sometimes emits a byte-identical file. Totals: 79 edits, 554 lines throughout (all in-paragraph), 126,841 -> 151,083 bytes (+19.1%).

### Pass 1 — `app.py`, `core.py`, `routes_reference.py` (21 edits: 13 ambiguity-pins, 8 mismatch-revisions)
- §2.1 revise/mismatch — whitespace-only `X-User-ID`/`X-User-Role` is `ERR_MISSING_AUTH_HEADERS` (impl `.strip()`s); role matching exact/case-sensitive, so `practiceadmin` is `ERR_UNKNOWN_ROLE` — core.py:326-329
- §2.2 insert/ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — core.py:263,268
- §2.2 insert/ambiguity — `api_request_timestamp` is the one value reading real wall-clock UTC, not the logical clock — core.py:269
- §2.3 insert/ambiguity — `created_at` ties broken by store write order; `id` is never a tie-breaker — core.py:253-259
- §2.4 insert/ambiguity — `id` is canonical lowercase hyphenated UUIDv4; `created_at` reads the logical clock, so rows minted under a still clock share it — core.py:225-234
- §2.4 insert/mismatch — `version` advances once per REQUEST, not per field write; multi-hop cascades refresh `updated_at` per hop but bump `version` by 1; `updated_at` may equal `created_at`; unversioned rows are never touched — core.py:237-250
- §2.5 revise/ambiguity — clock endpoint returns 200 with a `data` object carrying only `current_utc`; the clock may move backwards — routes_reference.py:45-51
- §2.5 insert/ambiguity — permissive instant parse then UTC-normalise (`Z`/`z`, numeric offset, no-zone-means-UTC, any fractional width, trimmed); unparseable -> `ERR_INVALID_REQUEST`; always rendered 3-dp + `Z`; negative whole-day direction pinned — core.py:126-155
- §2.8 step 5 insert/ambiguity — the whole coercion engine: empty body = `{}`; non-JSON/non-object -> 400; explicit `null` == absent; undeclared body keys and query params silently ignored; bool never accepted for integer/number, string never for bool/integer/number, integral float accepted for integer; length bounds; identifier rejects empty/whitespace; cross-field range checks (`label_dose_ml` vs `vial_fill_ml`, `max_interval_days` vs `min_interval_days`) evaluated in step 5, ahead of FK/uniqueness/business gates — core.py:386-478
- §2.8 step 14 revise/mismatch — `ERR_CLINICIAN_NOT_ELIGIBLE` also carries the clinician's own already-`SUSPENDED` guard (Clinician has no step-13 state error) — routes_reference.py:389-390
- §2.12 insert/ambiguity — filters are exact equality; string/id case-sensitive, no partial match; boolean accepts only `true|false|1|0` any case; unparseable filter -> 400 — core.py:509-555
- §2.12 insert/ambiguity — trailing slash tolerated (`strict_slashes=False`, no redirect); unknown path -> `ERR_INVALID_REQUEST` at 404, unsupported method -> same identifier at 405 (the only two non-400 uses) — app.py:36,46-54
- §3.1 revise/mismatch x5 — real filter sets for payers (`name`,`payer_type`,`federal_program`,`biosimilar_preference`,`status`), drugs (+`hcpcs_code`), policies (+`pa_required`,`wastage_reimbursed`; policies carry no `status`; FK order `payer_id`->`drug_id`->`step_therapy_prerequisite_drug_id`, duplicate-pair check last), patients (`mrn`,`payer_id`,`status`; `contact_point` required, stored verbatim, no channel-shape validation; no diagnosis, no own federal flag), clinicians (+`npi`; `status` filter is `ACTIVE|SUSPENDED` here vs `ACTIVE|INACTIVE` elsewhere) — routes_reference.py:100-108,184-192,219-268,284-323,372-378
- §3.1 insert/ambiguity — uniqueness comparisons are exact case-sensitive whole-value equality, no trim/case-fold — routes_reference.py:70-72,143-145,289-291,343-345
- §3.1 insert/ambiguity — `suspension_reason` required non-empty; suspend returns 200 with the full clinician; `SUSPENDED` is terminal — routes_reference.py:383-394
- §4 revise/mismatch — payers/policies/patients/clinicians table rows brought to impl; phantom `primary_diagnosis` filter and the "diagnosis and federal-program status" patient description removed
- Verified byte-exact and left alone: §5 catalogue vs `core.ERROR_STATUS` (same 70 ids, statuses, order); §2.2 envelopes; §2.3 bounds/defaults; `ImagingStudy` as the sole unversioned row; §2.7 half-up cents and 3-dp/4-dp limits; §2.8 steps 1-4; all §3.1 field ranges/defaults.

### Pass 2 — `routes_clinical.py`, `routes_inventory.py`, `routes_authorizations.py` + their domain helpers (21 edits: 13 ambiguity, 8 mismatch)
- §2.6 insert — `expected_treatment_plan_version` is integer >= 1, so 0/negative/non-integer is a step-5 400, not a 412 — routes_authorizations.py:81
- §2.8 step 20 revise — Applies-to extended to PA submission and the APPROVED decision branch, keyed on the authorization's copied `payer_id`/`drug_id` — routes_authorizations.py:145,210
- §2.1 revise — ComplianceOfficer "may read everything" excluded the lot-exposure computation — routes_inventory.py:135
- §3.2 + §4 revise — imaging filter set is six names; `interpreting_clinician_id`/`activity_classification` are accepted ALIASES — routes_clinical.py:107-116
- §4 revise — `GET /treatment-plans` row dropped the phantom `prescribing_clinician_id`, added `baseline_imaging_study_id`/`last_encounter_id` — routes_clinical.py:179-188
- §3.3 insert — the 14-day baseline window is an exact 336-hour instant difference, not truncated whole days — routes_clinical.py:212-214
- §3.3 insert — intra-step-13 order (plan, patient, drug, verdict) precedes steps 15/16, so a QUIESCENT wrong-eye baseline reports `ERR_PLAN_STATE_INVALID` — routes_clinical.py:200-214
- §3.3 insert — documentation pins `last_encounter_id` at the documented encounter, overriding the greatest-`encounter_datetime` invariant for a back-dated encounter — domain.py:223
- §3.3 insert — resume's open-adverse-event scan covers ALL the plan's encounters incl. `VOIDED`/`DRAFT` — routes_clinical.py:247-253
- §3.3 insert/mismatch — the discontinuation cascade writes `void_reason` `PLAN_DISCONTINUED`, not `PLAN_SUSPENDED`; `discontinuation_reason` required non-empty — routes_clinical.py:265,273
- §3.4 insert x5 — a PA may be opened against ANY plan status incl. `DRAFT`/`DISCONTINUED` (plan status never consulted); `clinical_justification` and `appeal_basis` required non-empty; branch-conditional decision fields are step-5 400 reported ahead of the path 404, `approved_injections` >= 1; the APPROVED branch re-reads the policy and can emit `ERR_PAYER_POLICY_MISSING` before both gates; appeal window read from the copied `payer_id` and the denial's `updated_at` — routes_authorizations.py:84-85,140,180-212,247-252
- §3.5 insert x4 / revise — `unit_acquisition_cost_cents` >= 0, the two instants unconstrained against each other and the clock (a lot may be received already expired and still start `AVAILABLE`), vials born with all three reservation/administration fields null; lots also filter `lot_number`/`expiration_date`, vials `serial_number`; release puts the step-40 open-recall check ahead of the expiration check (recalled-and-expired -> `ERR_RECALL_ALREADY_OPEN`); exposure `basis` is a required query param validated ahead of the path 404 and `days_held` truncates toward zero and may be negative — routes_inventory.py:63-247, domain.py:436
- §3.5 insert/mismatch — the sweep advances every visited lot's `updated_at`/`version` by 1 and persists the accrual BEFORE expiring vials, so the expiring run still counts them and the total sums those pre-expiry figures — routes_inventory.py:200-217
- Left alone as already pinned: the disease-activity verdict and inclusive 300 µm threshold; `ERR_DUPLICATE_ACTIVE_PLAN`; the three-hop suspension cascade; `_interval_branch` arithmetic incl. the double step at run >= 3 and the effective drug's clamps; `replay_plan_schedule`'s activation-baseline replay; step-therapy counting; the closed-interval window-overlap test; `EXHAUSTED <-> APPROVED` recomputation; CARRYING/EXPIRATION formulas; §2.9 counters; quarantine's vial handling.

### Pass 3 — `routes_encounters.py`, `routes_billing.py`, `routes_safety.py` + their domain helpers (26 edits: 19 ambiguity, 7 mismatch)
- §3.6 revise — 14-day imaging freshness is an exact 336-hour instant difference — routes_encounters.py:199
- §3.6 insert — the step-17 interval reference is the plan's greatest-`encounter_datetime` non-`VOIDED` encounter (`DRAFT` included), chosen without regard to the requested instant, so a back-dated booking yields a NEGATIVE count; explicitly distinct from `last_encounter_id` — routes_encounters.py:207-211, domain.py:78-82
- §3.6 insert/revise — `override_reason` non-empty after whitespace-trim, no length bound, both override fields stored whichever arm fires; `interval_days_from_previous` truncates toward zero and is signed — routes_encounters.py:223-272
- §2.8 step 14 revise/mismatch — widened from "eligible to inject" to "eligible for the act"; wastage attestation added (attester must be `ACTIVE`, privilege not consulted) — routes_encounters.py:376
- §3.7 insert/revise x6 — `post_injection_iop_mmhg` 0-80 inclusive; `administered_dose_ml` has no decimal or step-5 bound so a zero/negative dose reports `ERR_DOSE_EXCEEDS_VIAL_FILL`; documentation's write list completed and reservation fields explicitly NOT cleared on `RESERVED -> ADMINISTERED`; `attested_wasted_ml` >= 0 at step 5; the attester `ACTIVE` test is step 14 so a suspended attester on a non-`DOCUMENTED` encounter reports `ERR_ENCOUNTER_STATE_INVALID`; `ATTESTED` added to void's refused source states and `void_reason` required min-length 1 — routes_encounters.py:323-393
- §3.7 insert/revise — the DRAFT-void release is a no-op on a vial no longer `RESERVED` (recall-quarantined, pointer intact); suspension writes `PLAN_SUSPENDED` and discontinuation `PLAN_DISCONTINUED`; `injections_used` is the non-`VOIDED` encounter count; `EXHAUSTED -> APPROVED` revival additionally requires clock <= `expiration_date`; the authorization's version moves only on real change — domain.py:146-177
- §3.7 insert — the DOCUMENTED-void `ADMINISTERED -> QUARANTINED` vial keeps `reserved_for_encounter_id`/`reserved_at`, so §3.5's release can never return it — routes_encounters.py:400-405
- §3.8 insert x6 — remittance fields all optional and `_cents` >= 0 with the outcome-conditional requirements as step-5 400 evaluated BEFORE the claim path lookup; an omitted `wastage_allowed_cents`/`wastage_paid_cents` on drug `PAID` is written as 0, wiping the creation expectation; `WRITTEN_OFF` writes only `drug_paid_cents`; the enrollment row's version moves only when `foundation_applied_cents` is nonzero; the final-pass reversal targets the enrollment the claim's own `assistance_enrollment_id` recorded and only when the prior amount was nonzero (re-selection may land elsewhere); all six enrollment inputs required with no `effective_date`/`expiration_date` ordering check — routes_billing.py:165-275, domain.py:315-380
- §3.9 revise/insert x6 — AE filing has NO encounter state gate (`DRAFT`/`VOIDED` accepted), `source_drug_lot_id` follows `vial_id` whatever the vial's custody state, `days_post_injection` truncates toward zero and is signed; the 30-day endophthalmitis window has no lower bound so a negative count qualifies; the `RELATED` second hop fires only for a treatable plan (already-`SUSPENDED` gets hop three with reason/version untouched, `DRAFT`/`DISCONTINUED` gets no plan hop); the fifth hop RECOMPUTES the cluster count from `ADJUDICATED_RELATED` endophthalmitis events, requires `source_drug_lot_id` and a still-`AVAILABLE` lot, and writes `quarantine_reason = ENDOPHTHALMITIS_CLUSTER`; recall ladder text fields required min-length 1 and `credit_received_cents` required >= 0; both recall tallies recomputed with the recall's version +1; a `Patient`'s notification listing is force-narrowed to their own rows and a foreign `patient_id` filter is a 403, not an empty page — routes_safety.py:87-450, domain.py:121-132,478-549
- Left alone as already pinned: the five-arm effective-drug cascade and its tie-breaks; the FEFO pool with dearest-first and `created_at` tie-breaks and strict `expiration_date > clock`; the closed 24-hour capacity window; authorization selection and the `EXPIRED` flip-and-reject; billing-units split, worked example and modifier assembly; the three charge lines, eight waterfall steps, `claim_lines_terminal`, realized margin, appeal window; recall initiation, notification-set generation and the ship/reconcile/close ladder.

### Pass 4 — reconciliation (11 edits)
1. **`injections_administered` — real contradiction of MECHANISM, fixed.** `advance_plan_on_documentation` (domain.py:214,222) increments; `replay_plan_schedule` (domain.py:251) re-derives over `ENCOUNTER_COUNTED`. Traced every writer/reader: the only entry into the counted population is `document_encounter` (routes_encounters.py:353 -> advance at :361) and the only exit is `void_encounter` from `DOCUMENTED` (:409,415 -> replay); `void_draft_encounters` and the recall cascade touch `DRAFT` only. So the population equality IS a true invariant, but stating it as a DEFINITION would tell an implementer to recompute on documentation. Recast as the increment-on-documentation / re-derive-on-void split with the equality as consequence.
2. **`ERR_VIAL_STATE_INVALID` is dead code — confirmed by three independent greps** (only occurrence: core.py:72, the `ERROR_STATUS` map). Removed from §2.8 step 13's raisable list and from the §3-head precondition-convention list, each replaced by an explicit statement that it is catalogued but no request receives it. The §5 row STAYS — the identifier is part of the implementation's declared error table.
3. **`Payer.status`/`Drug.status` unreachable — confirmed, and `Patient.status` has the identical defect.** The only `status` writer anywhere is `suspend_clinician` (routes_reference.py:391). All three §3.1 paragraphs fixed: value fixed at `ACTIVE` for the row's lifetime because the API exposes no transition, `INACTIVE` remains an accepted filter value; plus one clause noting the downstream `ACTIVE` gates in `activate_treatment_plan` (routes_clinical.py:203,206) and `_candidate_pool` (routes_encounters.py:66) therefore cannot fail. "system-managed" now appears 0 times.
4. **Three unreachable defensive branches confirmed unreachable, deliberately NOT documented** (PRD must not describe behavior the system cannot exhibit): `_select_authorization`'s null-date guards (the only `APPROVED` writer makes `effective_date` mandatory and always sets both dates; `EXHAUSTED` reachable only from `APPROVED`); `finalize_claim_margin`'s `acquisition = 0` fallback (a claim requires an `ATTESTED` encounter -> documentation -> a reserved vial, and nothing anywhere deletes a row); `void_encounter`'s DOCUMENTED-with-claim branch (claims attach only from `ATTESTED`, no backward edge).
5. **All four shared boundary paragraphs verified TRUE, no edit.** §2.6: exactly two `expected_treatment_plan_version` sites (routes_encounters.py:178,185; routes_authorizations.py:81,85). §2.8 step 20: `ERR_PAYER_POLICY_MISSING` fires in exactly `create_encounter`, `create_claim`, `submit_authorization`, and `decide_authorization`'s APPROVED branch — all four named. §2.1 ComplianceOfficer: its six writes are exactly `release_lot`, `start_investigation`, `create_recall`, `send_notifications`, `close_recall`, `mark_unreachable`, and lot exposure is `[ADMIN, TECH, BILLING]`. §3.3 steering matches `_interval_branch`.
6. **Four cross-pass contradictions found and fixed.** (a) §2.7 named a carrying-cost accrual as an example of rounding at each step while §3.5 says it rounds once at the end — `carrying_exposure_cents` (domain.py:423-431) carries the chain in `Decimal` and calls `cents()` once, so §2.7 was rewritten with a multi-factor-chain carve-out. (b) §3.4 said the lazy `EXPIRED` flip fires when the selected authorization's `expiration_date` is strictly before the clock; `_select_authorization` actually flips whenever NO authorization's window contains the clock, so a future-dated one is flipped too — aligned to §3.6/impl. (c) §3.2's "the last two of those" pointed at the wrong pair of aliases. (d) §3.9 said each notification tally "is incremented" and then that both are recomputed — `recount_notifications` (domain.py:546) recomputes; both rises reworded.
7. **Document integrity clean.** All 75 §4 rows match method/path/role-set against the `@core.api` decorators (0 diffs); every §3/§4 filter list matches `query_filters` key-for-key; every `ERR_X (HTTP nnn)` prose mention matches `core.ERROR_STATUS`; every §2.8 Applies-to claim (steps 1-46) matches the raise-site map; 70 error rows identical to `ERROR_STATUS`; §1-§5 with 12 §2 and 9 §3 subsections unchanged; glitch scan (odd backticks, stray rows, doubled words, orphaned clauses) clean apart from the expected hit inside the §2.2 JSON fence.

**Residual divergence knowingly left in place:** the `ERR_VIAL_STATE_INVALID` §5 row (declared but unraisable, by design); §3.3/§3.6's `ACTIVE`-patient/drug gates that exist in code but cannot fail (unreachability stated once in §3.1 rather than rewriting two subsections); §2.12's boolean-filter sentence omitting that `core.query_filters` also strips surrounding whitespace (under-determined but not false).

**Orchestrator verification:** PRD_COMPLETED.md is 554 lines / 151,083 bytes and is NOT byte-identical to PRD_FINALIZED.md — 64 changed hunks; it ends on the 70th complete error-table row. No `.py` file under `workspace/implementation/` is newer than `workspace/SWEEP_DONE`, so the green 8/8 x 109/109 sweep still describes the shipped implementation; Step 9 changed documentation only. `__pycache__` trees and the empty `.scratch/` parent removed.
