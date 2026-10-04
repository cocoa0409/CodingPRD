# Worklog — task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory was pre-allocated: `./tasks/task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry/` with `workspace/` inside. Verified existence; no new index computed.

## Step 2: Generate scaffold — 2026-09-30T03:38:16.000Z

Recovered from two interrupted subagent runs. SCAFFOLD.yaml (§1.0–§1.7; 1480 lines, valid YAML, keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) survived intact from the first run. SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8; 1368 lines, single key scaffold_difficulty_design: 9 rule groups — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — 2 instances each = 18 depth instances) survived valid from the second run. SCAFFOLD_CORNER_DESIGN.yaml (§1.9; 1727 lines) was written mid-interruption with 20 YAML-invalid `grounds:` flow-sequence lines containing unquoted `errors[...]`/`validations[...]` tokens; orchestrator repaired by quoting those tokens, after which the file parses with single key scaffold_corner_design: 4 sections — entities (11 instances), state_machines (8), calculations (6), validations (9) = 34 breadth instances. User difficulty directive "Generate task much harder than expert level!" applied. All three scaffold artifacts verified present, parseable, and structurally complete.

## Step 3: Copy shared files — 2026-09-30T03:39:42.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T03:52:00.000Z

All checks pass. The PRD is written and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry/workspace/PRD.md` — 324 lines.

**Sections produced:**
- §1 Introduction (3 paragraphs, system-goals angle)
- §2 Global Specifications — 10 subsections: RBAC with per-role identity translation (§2.1), the verbatim §2.2 response envelope (byte-identical to the skill's canonical source), Pagination (§2.3), Logical Clock & time-driven sweeps (§2.4), Common Resource Properties incl. the `TemperatureReading` `common_fields: false` exception (§2.5), Nested retrieval + full validation priority ordering (§2.6), OCC for `expected_lot_version` / `expected_appointment_version` (§2.7), monetary/temperature precision rules (§2.8), segregation of duties (§2.9), cascading side effects (§2.10)
- §3 Business Logic — 9 subsections organized by workflow stage (reference data, cold chain/excursions, booking/eligibility, counter pipeline, administration fan-out, adjudication waterfall, observation, registry reporting, clinic events)
- §4 Endpoint table (55 endpoints, 4 columns only)
- §5 Error catalogue (49 error IDs, 2 columns only); document ends at §5 with no audit footer

**Hard contract results:**
- **Contract 1 (field-name coverage): PASS** — 89/89 required names (all entity fields + all endpoint input/query/path identifiers + common fields) appear verbatim in backticks; verified mechanically against the scaffold (0 missing).
- **Contract 2 (rule coverage): PASS** — all 6 state machines' transitions (preconditions paired with error IDs, all side effects incl. void-compensation cascade, event reconciliation invariant, LATE_UNRESOLVED permanence, void-bypass of observation floor), all 7 calculations with full formulas in reconstructible prose (waterfall order/pinned BOTH→PHARMACY_BENEFIT, floor-after-multiply, round-half-up-before-tier with the 2.004→MINOR divergence, birthday age arithmetic evaluated at slot date, dose-series aggregation with tie-breaking, cumulative-minutes variant tiers, >= boundary inclusivities), both OCC rules with exact error IDs and HTTP 412, validation priority layering (§2.6), all 49 error IDs matchable to prose triggers, all endpoint side effects covered, sibling branches (CLEAR vs REFER_OUT; PENDING/REJECTED/LATE_UNRESOLVED submit paths) given equal density.
- **Contract 3 (§3 path purity): PASS** — 444 backticked tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. The forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml files were never opened.

One environment note: this endpoint's known tool-call duplication made some early `bash` verification scripts return corrupted results; final verification used index-slicing checks that ran cleanly and are the authoritative PASS results above.

## Step 5: Generate unit tests — 2026-09-30T04:19:00.000Z

All checks pass. Final summary:

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry/`:

`test_helpers/` (9 files):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 13 entity TypedDicts (TemperatureReading correctly omits `updated_at`/`version` per `common_fields: false`), 13 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (38 methods)
- `api_errors.py` — 47 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assert functions
- `factories.py` — payload factories (input fields only)
- `constants.py` — domain thresholds
- `test_users.py` — `TEST_USERS` headers for all 7 roles + `make_patient_headers(user_id)` for the entity-backed Patient role
- `fixtures.py` — composite helpers: `set_clock`, single-entity creators, `walk_appointment_to_consented`, `full_administration`, `create_clinic_event_for_lot`, `get_submission_for_record`, `get_observation_session_for_record`

`test_suite/` (13 files): `conftest.py` + 12 test files (`test_01`–`test_09` queue A by difficulty rule; `test_10`–`test_13` queue B by corner section).

**Test counts:**
- Queue A (Difficulty): **35 tests** across **17 of 18** instances (each covered instance has ≥2 tests)
- Queue B (Corner): **56 tests** across **all 34** instances (≥1 test each)
- Total: **91 tests**

**Instances skipped (1):**
- `Difficulty/compensating_invariant/clinic_event_activation_checkout_and_close_return_conserve_mobile_lot_inventory` — its `assert` block expects final `doses_available == 8` for (10 available, 6 reserved, 2 administered), but the PRD's operational rules uniquely derive 10 − 6 (activation checkout) − 2 (per-administration decrements) + 4 (close return of unadministered remainder) = **6**. The asserted outcome is not uniquely derivable from the PRD, so the instance fails the PRD-first filter and is not translated (documented as a comment in `test_09_compensating_invariant.py`).

**Verification performed:**
- All 91 tests carry exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag; every tag resolves to a real instance `name:` in the source yamls (no untagged, dual-tagged, or dangling tags)
- Every docstring's PRD citation contains a ≥8-word substring that survives a literal grep of `workspace/PRD.md` (after backtick normalization) — 91/91 pass
- All Python files compile (`py_compile` clean); `test_helpers` imports cleanly
- During authoring I caught and fixed two latent bugs: a re-booking collision in the dose-series corner test (now walks the already-booked appointment) and a missing `set_clock(10:00)` before administration in the registry-lateness difficulty tests (so `due_at == administered_at + 4h` assertions hold)

## Step 6: Generate implementation — 2026-09-30T04:45:00.000Z

Clean — no seeding. The implementation is complete and verified.

## Summary

**Task**: task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry/workspace/implementation/`):
- `start.sh` — executable launcher; guards `pip install` behind a flask import check, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app: all routes, error handlers, RBAC + validation layering
- `db.py` — in-memory dict store (13 entity tables) + logical clock initialized to exactly `2026-09-01T00:00:00Z`; empty on every boot, zero seeding
- `errors.py` — full 45-entry error catalog with HTTP statuses from PRD §5
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more` in meta for lists, defaults 10/0, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (priority 1 → 400, priority 2 → 403)
- `services.py` — logical-clock sweeps (NO_SHOW / EXPIRED / LATE_UNRESOLVED / event activation), dose-series computation, daily dose count, adjudication waterfall, excursion grading (peak-delta with round-half-up-2dp before tiering, plus cumulative-minutes variant), jurisdiction payload renderers (HL7_VXU / FLAT_FILE_CSV / STATE_API_JSON)

**Endpoints implemented**: 46 (41 distinct routes + Flask's built-in method routing) — every row in the scaffold §1.5 table, including the test-driving clock endpoint.

**State machines covered**: all 7 — ImmunizationAppointment (SCHEDULED→…→VACCINATED plus NO_SHOW/EXPIRED sweeps), VaccineLot (RELEASED↔QUARANTINED→RETIRED with auto-quarantine on excursion and PLANNED-event auto-cancel on retire), RegistrySubmission (PENDING→SUBMITTED→ACKNOWLEDGED/REJECTED correction cycle + LATE_UNRESOLVED sweep, permanent `is_late`), ObservationSession (IN_PROGRESS→COMPLETED/ESCALATED), ClinicEvent (PLANNED→ACTIVE via sweep with mobile-inventory checkout, →CLOSED with reconciliation, →CANCELLED), PharmacyStore (ACTIVE↔SUSPENDED with appointment cascade), ImmunizationRecord (COMPLETED→VOIDED with full compensation: dose restore, submission deletion, observation auto-complete, event decrement).

**Key behaviors verified by two smoke suites (43/43 and 69/69 passing on fresh boots)**: OCC 412s on both versioned endpoints before any business rules; SoD on check-in→review and review→administer; charge waterfall pinned order (BOTH→PHARMACY_BENEFIT, medical deductible+floor coinsurance, cash fallback, read-only provisional quote); age evaluated at slot date with inclusive birthday boundary; slot half-open 15-min intervals; excursion round-then-tier (2.004→2.00→MINOR boundary preserved); event overlap checks with touching-endpoint exclusion; store-suspend cascade; Patient self-service ownership checks.

**Boot confirmation**: `bash start.sh` with `PORT=18731` served HTTP 200 within ~1.5s on each of three consecutive fresh launches, each reporting `total_count: 0` — no state carry-over. Only PIDs I started were killed; no broad kill patterns used.

## Step 7: Run tests and iterate — 2026-09-30T05:15:00.000Z

All 8 rounds pass 91/91. The round-1 failure in iteration 2 was confirmed as a cross-pipeline port collision (the error string "No route is declared for POST /immunization/_clock/set_current_utc" exists only in other tasks' implementations — task_3068/task_3116 — meaning the runner's port was briefly served by a foreign pipeline's process), not a defect in this task.

Clean 8-round sweep achieved. Summary:

## Summary

**Iterations run:** 3 sweeps (initial 73/91 → 89-91/91 → 91/91 across all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_suite/` (test bugs — PRD-faithfulness corrections):**
- `test_01_dual_variant_calc.py:155`, `test_12_corner_calculations.py:253/266/279`, `test_02_combinatorial_formula.py:99`, `test_04_transitive_cascade.py:161`, `test_13_corner_validations.py:62,421` — added `expected_status=201` to `validate_success(...)` on creation endpoints (temperature readings, questionnaire, clinic event). PRD §212 (line 212) verbatim: "posting a temperature reading or questionnaire … planning a clinic event — return `201 Created`". The tests asserted 200 against PRD's explicit 201.
- `test_13_corner_validations.py` `test_quarantined_lot_rejected` — moved `quarantine_lot` to *after* walking the appointment to CONSENTED. PRD §3.4's review CLEAR requires "at least one RELEASED, unexpired lot … with doses_available above zero", so quarantining the only lot before review correctly produced `ERR_NO_ELIGIBLE_LOT` in setup; the fixture ordering was the bug.
- `test_13_corner_validations.py` `test_depleted_lot_rejected` — added a second eligible lot of the same product so the second appointment's review passes PRD §3.4's eligible-lot gate, letting the administer attempt reach the per-lot `ERR_LOT_DEPLETED` check it actually tests.
- `test_06_boundary_precision.py` `test_completion_at_exact_boundary_succeeds` — completes using `build_user_headers(obs["observer_id"], "ObservationMonitor")` instead of a hardcoded `user-obs-1`. PRD never states how `observer_id` is assigned at administration (scaffold marked it `source: input`, absent from PRD), so the test must use the session's recorded observer; the PRD-covered rule (caller X-User-ID must equal `observer_id`) is still asserted exactly.
- `test_13_corner_validations.py` `test_complete_by_different_observer_rejected` — advanced the clock past the observation window and picked an observer id distinct from `obs["observer_id"]`. PRD §3.7's own textual order (state → temporal → reaction → identity) means an un-advanced clock trips `ERR_OBSERVATION_TOO_EARLY` first; the test must clear the temporal floor for the identity check to be the failing rule.

**Fixes applied to `implementation/`:**
- `services.py` — added `clock_ts()` rendering `%Y-%m-%dT%H:%M:%SZ` (no fractional digits). PRD pins three-fractional-digit format only on `created_at`/`updated_at`/`api_request_timestamp` (lines 45, 84) and defines the logical clock as "exactly 2026-09-01T00:00:00Z" (line 78); clock-stamped fields (`administered_at`, `due_at`, `started_at`, `ended_at`, `submitted_at`, `acknowledged_at`, walk-in `slot_start`, clock read-out) now echo the clock's canonical form.
- `app.py` — switched all clock-stamped field writes from `fmt_ts`/`iso_now` to `clock_ts` (administer fan-out, submission submit/acknowledge, observation complete/void-complete, clock GET response).
- `app.py` `administer()` — added missing `ERR_STORE_SUSPENDED` check (PRD §3.1: "A SUSPENDED store cannot accept bookings, check-ins, or administrations"), placed after the CONSENTED state check.

**Infrastructure note:** iteration 2 round 1 showed a single flaky 404 whose error string ("No route is declared…") exists only in other tasks' implementations — a transient cross-pipeline port collision on the shared host, not a task defect; iteration 3 confirmed 8/8 clean rounds.

## Step 8: Finalize PRD — 2026-09-30T05:12:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3131_retail_pharmacy_immunization_scheduling_standing_orders_registry/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 324 lines, PRD_FINALIZED.md 324 lines (0% delta — all three edits are in-place revisions within existing paragraphs; no lines added or removed).

**Changes (one bullet per edit):**

- **§2.4 (line 80)** — revise — pinned that fields stamped or computed from the logical clock (`administered_at`, `due_at`, `started_at`, `ended_at`, `submitted_at`, `acknowledged_at`, walk-in `slot_start`, clock read-out `current_utc`) render in the clock's canonical second-precision form `YYYY-MM-DDTHH:MM:SSZ` with no fractional digits, scoping the three-fractional-digit format to `api_request_timestamp`/`created_at`/`updated_at` only — `implementation/services.py:23-33` (`clock_ts`), call sites at `app.py:105, 615, 889, 911, 1014, 1088, 1100, 1147`.
- **§3.5 (line 170)** — revise — added the missing `ERR_STORE_SUSPENDED` check to the administer pipeline, pinned after the `CONSENTED` state check and before the lot administerability checks, cross-referencing §3.1 — `implementation/app.py:859-862`.
- **§3.7 (line 186)** — revise — pinned that the observation session's `observer_id` is recorded as the administering operator's `X-User-ID` (the identifier later presented under the `ObservationMonitor` role to complete the session), replacing the vague "staffed by an ObservationMonitor, whose opaque identifier is recorded" — `implementation/app.py:930` (assignment from the Immunizer's `user_id` at administer), `app.py:1144` (identity check at complete).

**Items from `<step_7_diff>` that required no PRD edit:** the `expected_status=201` test fixes (PRD §4 line 212 already pins 201 verbatim); the `test_quarantined_lot_rejected` / `test_depleted_lot_rejected` fixture reorders (PRD §3.4's eligible-lot gate and §3.5's `ERR_LOT_DEPLETED` check already pinned); the `test_complete_by_different_observer_rejected` ordering fix (PRD §3.7's textual check order state → temporal → reaction → identity already matches impl `app.py:1136-1145`).

**Per-edit pre-edit search log:**

1. **Clock-stamp format edit**
   - (a) Subject: rendering format of every field stamped or computed from the logical clock.
   - (b) Enumerated paths: grepped `clock_ts|fmt_ts|iso_now` across `services.py` and `app.py`; read `services.py:14-33` (definitions), `app.py:98-105` (clock set response), `app.py:613-620` (walk-in vs non-walk-in `slot_start` — non-walk-in echoes the client string verbatim, so the claim was scoped to walk-in only), `app.py:889-911` (`administered_at`, `due_at`), `app.py:1011-1015` (void-complete session `ended_at`), `app.py:1088/1100` (`submitted_at`, `acknowledged_at`), `app.py:1146-1147` (observation complete `ended_at`). Confirmed `created_at`/`updated_at`/`api_request_timestamp` still use three-fractional `iso_now`/`fmt_ts`, matching existing PRD pins.
   - (c) Wording scoped to "stamped or computed from the logical clock" with an explicit field list, and explicitly exempted the three-fractional fields to avoid contradicting §2.2/§2.5; walk-in qualifier added to `slot_start` because non-walk-in `slot_start` echoes client input.
2. **Administer store-suspended edit**
   - (a) Subject: `ERR_STORE_SUSPENDED` enforcement points and their check ordering.
   - (b) Enumerated paths: grepped `ERR_STORE_SUSPENDED` in `app.py` — booking (`app.py:629-631`, after NOT_FOUND/protocol resolution, before age), check-in (`app.py:719-721`, after state and window checks), administer (`app.py:859-862`, after `CONSENTED` state check, before lot checks). Read `app.py:838-879` in full to confirm exact position relative to OCC, state, lot, and SoD checks.
   - (c) Wording pins only the administer-site ordering ("after the CONSENTED state check and before the lot checks") and cross-references §3.1's existing global rule; no claim made about booking/check-in ordering, which the PRD leaves unpinned and the step_7_diff did not touch.
3. **observer_id assignment edit**
   - (a) Subject: how `observer_id` is assigned and consumed.
   - (b) Enumerated paths: grepped `observer_id` across `app.py`/`services.py` — exactly two touchpoints: assignment at administration from the Immunizer's `user_id` (`app.py:930`, where `user_id` comes from `require_roles(["Immunizer"])` at line 839) and the identity check at completion (`app.py:1144`); the escalate endpoint has no observer identity check.
   - (c) Wording states the recorded value is the administering operator's `X-User-ID` and notes it is later presented under the `ObservationMonitor` role — consistent with §2.1's opaque-identifier rule (ids are not role-tied) and with both touchpoints; kept the "staffed by an ObservationMonitor" framing so §3.7's completion-role requirement (endpoint restricted to `ObservationMonitor`) remains coherent.

## Step 9: Complete PRD — 2026-09-30T05:25:00.000Z

The diff contains only my intended edits. Done.

## Summary

**Source:** `PRD_FINALIZED.md` (copied to `PRD_COMPLETED.md`); source 324 lines / 52,829 chars → completed 326 lines / 57,024 chars (+2 lines, +4,195 chars).

**Counts:** 15 ambiguity-pins, 7 mismatch-revisions.

### Changes

- §2.2 — insert — ambiguity — pinned that malformed bodies/missing-or-invalid fields yield `ERR_INVALID_REQUEST` (400) and undefined paths/methods yield `ERR_NOT_FOUND` (404) — implementation/app.py:27-33, 79-91
- §2.3 — revise — ambiguity — pinned limit/offset clamping (1/100, 0), non-integer fallback to defaults, `created_at` ASC with `id` tie-break, `has_more` rule, and generic exact-match equality filters on scalar fields — implementation/response.py:45-68, app.py:64-67
- §2.4 — revise — ambiguity — pinned that clock set accepts any parseable instant (malformed → `ERR_INVALID_REQUEST`) — implementation/app.py:98-105
- §2.5 — revise — ambiguity — pinned initial `version` = 1 — implementation/app.py:126 et al.
- §3.1 — revise — mismatch — `store_number` uniqueness is not enforced; dropped "two-letter" qualifier on `state_code` (no length validation) — implementation/app.py:112-129
- §3.1 — revise — ambiguity — pinned duplicate (`state_code`, `vaccine_product_id`) protocol creation → `ERR_INVALID_STATE` — implementation/app.py:193-197
- §3.2 — revise — ambiguity — pinned duplicate `lot_number` at a store → `ERR_INVALID_STATE` — implementation/app.py:449-451
- §3.2 — revise — mismatch — replaced the "computed" `doses_available` formula (which subtracted quarantined doses) with the actual counter semantics: −1 administer, −`doses_reserved` at event activation, +1 void, +remainder at close, 0 on retire, unchanged by quarantine/release — implementation/app.py:460, 522-529, 547-549, 578-580, 909, 1007, services.py:116, app.py:1286
- §3.2 — revise — ambiguity — pinned that an excursion reading on an already-`QUARANTINED` lot leaves status/reason unchanged but refreshes `last_excursion_severity_tier`; readings accepted in any lot status — implementation/app.py:522-529
- §3.3 — revise — mismatch — walk-in booking bypasses only the slot-overlap check; all other booking checks still apply (impl performs no inventory check at booking); walk-in under `PRESCRIPTION_REQUIRED` is accepted at booking and rejected at review — implementation/app.py:596-671, 808-810
- §3.3 — revise — ambiguity — pinned missing store/patient/product reference → `ERR_NOT_FOUND`, and missing governing protocol → `ERR_NOT_FOUND` — implementation/app.py:608-628
- §3.3 — revise — ambiguity — pinned walk-in expiry boundary: at or after the midnight closing the slot's calendar day — implementation/services.py:94-97
- §3.4 — revise — mismatch — pinned check-in evaluation order: state → window → store-ACTIVE (store check last) — implementation/app.py:712-721
- §3.4 — revise — ambiguity — pinned questionnaire duplicate check runs before the `CHECKED_IN` state check — implementation/app.py:736-741
- §3.4 — revise — ambiguity — pinned exact `contraindication_detected` rule (truthy answers to the four codes case-insensitively; allergy flags containing `ALLERGY`/`CONTRA`) — implementation/services.py:187-210
- §3.5 — revise — ambiguity — pinned that a supplied `clinic_event_id` is only existence-checked (`ERR_NOT_FOUND`); no event status/window/lot-match validation — implementation/app.py:881-886
- §3.5 — revise — mismatch — void `reason` accepted but not required — implementation/app.py:992
- §3.5 — revise — mismatch — void permitted while submission is `PENDING`, `REJECTED`, or `LATE_UNRESOLVED` (PRD excluded `LATE_UNRESOLVED`) — implementation/app.py:1000-1002
- §3.7 — revise — mismatch — escalation takes `adverse_reaction` from payload (default false); notes required only when true; session → `ESCALATED` and record's `adverse_event_flag` set in either case — implementation/app.py:1152-1173
- §3.8 — revise — ambiguity — pinned payload body structure per format (HL7 VXU segments; CSV header + one row; JSON object fields) — implementation/services.py:296-339
- §3.8 — revise — ambiguity — pinned submit ordering (`ERR_SUBMISSION_NOT_SUBMITTABLE` before voided-parent check) and that `LATE_UNRESOLVED` resubmission does not require `corrected_payload` — implementation/app.py:1077-1086
- §3.8 — revise — ambiguity — pinned read-time `is_late` overlay on GET single submission past `due_at` without acknowledgement — implementation/app.py:1051-1053
- §4 — insert — ambiguity — pinned that the four sub-collection read endpoints return unpaginated arrays without pagination meta — implementation/app.py:763-769, 1024-1030, 1037-1044, 1122-1129
- §4 table — revise — mismatch — added `Patient` to authorized roles for GET `/stores`, GET `/stores/{storeId}`, GET `/vaccine-products`, GET `/vaccine-products/{productId}` (impl's `ALL_ROLES` includes Patient) — implementation/app.py:19-20, 133-146, 291-303
