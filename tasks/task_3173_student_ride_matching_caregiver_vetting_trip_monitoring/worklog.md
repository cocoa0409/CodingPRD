# Worklog — task_3173_student_ride_matching_caregiver_vetting_trip_monitoring

## Step 1: Create task directory — 2026-09-30T07:10:00.000Z

Task directory `./tasks/task_3173_student_ride_matching_caregiver_vetting_trip_monitoring/` was pre-allocated by the caller with an empty `workspace/` inside; verified present and empty. No index computation, no other `task_*` directory created.
## Step 2: Generate scaffold — 2026-09-30T08:10:00.000Z

All three artifacts are generated and the lint is clean. Final summary:

**Files (task dir `/home/ubuntu/github/CodingPRD/tasks/task_3173_student_ride_matching_caregiver_vetting_trip_monitoring/`)**
- `SCAFFOLD.yaml` — 2,899 lines (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,489 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2,711 lines (single top-level key `scaffold_corner_design`)

**Counts**
- Entities: 14 — District, Rider, Driver, BackgroundCheck, VehicleInspection, Contract, RideRequest, Trip, HandoffVerification, SafetyIncident, TripAlert, BillingStatement, Geofence, GeofenceCheck
- State machines: 9 — Driver, BackgroundCheck, VehicleInspection, Contract, RideRequest, Trip, SafetyIncident, TripAlert, BillingStatement
- Calculations: 19 | Endpoints: 83 | Errors: 46 | Validations: 12 | Concurrency rules: 2 | Roles: 5
- Difficulty design: 9 rule blocks × 2 instances = 18 (all rules at minimum)
- Corner design: 13 groups over the guide's 9 sections (plus 4 stub-only groups); 30 active instances + 11 `excluded_because:` stubs

**Lint verdict** (`scaffold_lint.py`, verbatim from last run): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 718 calls scanned, zero violations across checks (a)–(f).

**Coverage decisions**
- Profile: `temporal_windowing` + `compliance_audit`, layers = selector_policy, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; flat topology, compound state machine, peer_roles, immediate consistency. Advanced band (leans Expert: 14 entities / 83 endpoints).
- Restructured §1.5 so `api_prefix /student-rides` is a single scope root with every collection at `/student-rides/<collection>/{id}` — required because lint check (f) matches on two-segment collections and literal template segments. Driver is a platform-global roster, so its reverse reads hang off the flat side; the test-driving endpoints (`/_clock`, `/_support-center`, `/_events`) sit outside the root.
- Added `Geofence`/`GeofenceCheck` (+ `geofence_containment`, `POST /trips/{id}/geofence-checks`) purely so Rule 8's second overlap rule differs in *interval geometry* (half-open driver availability vs closed rider-trip windows), not just arithmetic — the same touching pair is accepted on one resource and rejected on the other. That also gave a distinct boundary metric for Rule 6.
- Added `POST /districts/{id}/credit-adjustments` (business endpoint, not `/_seed`) so the credit-pool setups are reachable; added `planned_miles` to Trip/RideRequest and `billable_miles` to the handoff input so the quote-vs-settlement dual variant is measurable on identical data.
- `BillingStatement.contract_id` is deliberately documented as a rate-provenance stamp, not an FK, since a statement outlives its contract; the filtered-list form still resolves it.
- Rule 5 uses two different error-category pairs: auth-vs-existence (403 beats 404) and state-vs-business_constraint (409 beats 422). Rule 9 uses two conserved quantities of different type: a count (district scheduled load) and a capacity (fleet seat pool).
- No `/_clock` call relies on the startup default; the fixed default `2026-09-01T00:00:00Z` is stated in the endpoint description and every recipe pins the clock explicitly.
- All formula-derived asserts are pre-computed literals (e.g. final charge 29300, statement total 26300, absence points 11.25 → HIGH, impact score 180 → clamped 100).

Note: `worklog.md` and `workspace/` already existed in the task dir; I did not touch them.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T08:15:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`. Build contract: produce `./implementation/start.sh` + source; listen on `$PORT` (default 10000), bind `0.0.0.0`, run in foreground; evaluator runs `bash start.sh` from `./implementation/`.

## Step 4: Generate PRD — 2026-09-30T08:40:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3173_student_ride_matching_caregiver_vetting_trip_monitoring/workspace/PRD.md` — 1,219 lines / ~14,250 words.

**Structure:** 5 top-level sections. §2 has 11 subsections (2.1 RBAC, 2.2 response structure [verbatim], 2.3 pagination, 2.4 Driver Qualification Integrity, 2.5 Safety Posture Governance, 2.6 Trip Window Geometry and Booking Collisions, 2.7 Common Resource Properties, 2.8 Monetary Precision and Rate Provenance, 2.9 Optimistic Concurrency Control, 2.10 The Logical Clock, 2.11 Nested Resource Retrieval). §3 has 12 subsections (3.1 district/contract/credit, 3.2 student placement, 3.3 driver qualification incl. 3.3.1 clearance revocation, 3.4 intake/approval, 3.5 scheduling/recurring series/calendars, 3.6 selection & dispatch, 3.7 supply planning, 3.8 trip execution/handoffs/absence, 3.9 monitoring/alerts/incidents, 3.10 pricing & statements, 3.11 counting discipline), plus an unnumbered guard-priority preamble and §4/§5.

**State machines documented:** Driver, BackgroundCheck, VehicleInspection, Contract, RideRequest, Trip (both `trip_state` and `safety_state` dimensions plus the CANCELLED→SCHEDULED revert cycle), SafetyIncident, TripAlert, BillingStatement — all 57 transitions covered.

**Calculations:** all 19 prose-rendered precisely with constants embedded in narrative (12-month experience minimum, 2026-08-15 term open, 0.25/0.5/0.8/1.1/1.2 factors, 3-strike threshold, 12-minute wait blocks, $800 floor), handling both base rules and the documented variant readings (provisional-vs-final, declared-class-cap, on-road-only, credit-against-net, vetted fallback, weighted score, coverage-only, proximity, resolved-only, flat program weight, seated-demand-only).

**Endpoint groups:** all 83 endpoints (District, Rider, Driver, BackgroundCheck, VehicleInspection, Contract, RideRequest, Trip, SafetyIncident, TripAlert, Geofence/GeofenceCheck, BillingStatement, plus `_clock`, `_support-center`, `_events`) with role columns matching the scaffold exactly.

**Errors/RBAC:** all 46 error IDs in the §5 two-column table and each mentioned in §2/§3 prose; all 5 roles (`Anonymous`, `DistrictAdmin`, `Driver`, `SupportCenterAgent`, `PlatformAdmin`) with identity forms translated in §2.1.

**Scattering:** request-body parameters split across subsections (e.g. `window_start_at`/`max_window_minutes` in 3.4, `billable_miles` in 3.8, `note`/`issue` in 3.8, `candidate_driver_id` in 3.6); OCC `expected_district_version` deliberately placed in §2.9 as a system-wide contract and *not* repeated in §3; foreign keys implied through action ("payload containing the `ride_request_id`"); no field lists or schema tables in §3; no HTTP methods or paths in §3.

**Ambiguities resolved:** (1) variants treated as alternative documented readings — I specified each contrastively but did not add endpoints for them (they are consumed by whichever call site the scaffold names). (2) Validation priority expressed as a category ladder plus within-gate ordering, since §1.4 mixes single-check rows with multi-clause rows. (3) The `HandoffVerification.result` vs §1.2 `handoff.result == PASSED` tension resolved by rendering `authorized` as the computed verdict gating the transition, with `ERR_HANDOFF_NOT_AUTHORIZED`/`ERR_DUPLICATE_HANDOFF`/`ERR_HANDOFF_ALREADY_ATTEMPTED` all surfaced. (4) §2.11 covers RBAC's unlisted `GET /student-rides/drivers` and `GET /student-rides/riders` as generic nested-retrieval endpoints.

**Hard Contract reports:**
```
Field coverage check:
- entities[].fields: 123 required, 123 present, 0 missing
- endpoints[].request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing (pagination limit/offset + filters covered)
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_district_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed, 0 missing
- calculations[]: 19 checked, 19 fully expressed (variants included), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 83 / 12 checked, all expressed, 0 missing
- entities[].fields[] structured content: 123 checked, 123 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 706
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraints honored:** neither design file was read, grepped, or referenced; no sibling task directory was touched; no processes were killed.

## Step 5: Generate unit tests — 2026-09-30T09:15:00.000Z

Test infrastructure and suite are generated and audited. Summary:

**Files written (18 files, 5,518 lines)**
`test_helpers/` (2,468 lines): `__init__.py` 27, `types.py` 480, `api_client.py` 481, `api_errors.py` 111, `assertions.py` 215, `constants.py` 255, `test_users.py` 31, `fixtures.py` 868.
`test_suite/` (3,050 lines): `conftest.py` 40, `test_01_driver_qualification_pipeline.py` 161, `test_02_ride_request_intake.py` 149, `test_03_window_geometry.py` 153, `test_04_trip_pricing.py` 254, `test_05_absence_grading.py` 206, `test_06_cascades.py` 182, `test_07_trip_lifecycle_gates.py` 110, `test_08_safety_posture.py` 140, `test_09_guard_ordering.py` 124, `test_10_compensating_invariants.py` 164, `test_11_district_and_rider_surface.py` 298, `test_12_driver_roster_surface.py` 217, `test_13_trip_cancellation_and_counts.py` 203, `test_15_endpoint_surface.py` 124, `test_16_terminal_states.py` 140, `test_17_auth_and_concurrency.py` 238, `test_18_geofence_and_limits.py` 155. Nothing was written to `workspace/implementation/`; no sibling task was touched.

**Counts** — 74 tests collected (0 collection errors). Queue A: 18/18 instances translated, each with ≥2 tests. Queue B: 30/30 non-stub instances translated with ≥1 test; all 11 `excluded_because:` stubs correctly not translated and their `difficulty_instance` pointers verified to resolve.

**Skipped instances (7), with reason**
- Queue A `dual_variant_calc/opening_rate_under_combined_and_contract_invoice_variants` — the discriminating assertion needs `district.contract_rate_per_mile_cents`; the PRD never says a trip charge is ever computed from the district's default rate (only the contract's), so not-uniquely-derivable. Coverage re-anchored to the thought-exact observable: quote uses `planned_miles`, settlement uses odometer `billable_miles` (PRD `"The settlement is priced from the actual odometer distance recorded at completion rather than the planned distance."`).
- Queue B `calculations/rider_active_request_count_excludes_scheduled_requests` — no PRD sentence assigns a numeric `transitions` value, so `== 1.0` / `== 2.0` are not uniquely derivable; the count-shaped corners are asserted instead.
- Queue B `calculations/compliance_expiry_takes_the_earliest_clearance_and_the_latest_inspection` — recipe preconditions are unsatisfiable/ambiguous (the attestation gate needs the roster in `INSPECTION`, which is only entered before the first attest, so a second attestation cannot succeed as scripted); the derivable subset (earliest CLEARED governs, `PASSED` inspection expiring before it) is asserted.
- Queue B `cross_cutting_layers/school_closure_event_fans_out_to_every_active_series_in_the_district` — required the recipe's weekday/weekend test setup, which the PRD leaves open (whether a Saturday produces a trip is not derivable); event fan-out semantics are asserted without that dependency.
- Queue B `entities/driver_create_out_of_enum_vehicle_class_returns_invalid_request` and `entities/rider_create_missing_the_school_of_record_returns_invalid_request` — PRD never states that an unknown enum member or a missing field yields `ERR_INVALID_REQUEST` (the identifier appears only for empty `days_of_week` and a bad absence `issue`), so the asserted `error_id` is not uniquely derivable; the positive halves (all three classes accepted; `spi_level` defaulting) are asserted.
- Queue B `entities/district_list_paginates_with_total_count_and_has_more` — asserted verbatim, but tagged to the underlying rules; see note below.

**Tag lines used (41 distinct)** — 18 `Design: Difficulty/<rule_id>/<instance.name>` (rule_ids: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) and 23 `Design: Corner/<section>/<instance.name>` (sections: `entities`, `state_machines`, `validations`, `calculations`, `endpoints`, `errors`, `rbac`, `cross_cutting_layers`, `consistency_model`).

**Coverage decisions** — every docstring carries one verbatim PRD quote (all 74 pass a literal normalized-`grep` check against `PRD.md`) plus exactly one resolvable `Design:` line. Guard-ordering instances were constrained to rule pairs the PRD actually names (e.g. `ERR_FORBIDDEN` before `ERR_NOT_FOUND` via `"Authorisation is evaluated before any business rule"`); the `absence_wait_boundary` instance's `3.0 * 2.0 * 1.5 == 9.0` literal and the `branch-asymmetry`/`computed-field`/`default-value` recipes were dropped as not PRD-uniquely-derivable. The pagination test is counted against its section's remaining instance so no instance is dual-tagged. No `pytest.mark.skip`/`skipif`/`xfail` appears anywhere; no generated file mentions the scaffold.

## Step 6: Generate implementation — 2026-09-30T10:15:00.000Z

The implementation is complete and verified. Final report:

## What was built

**16 files in `workspace/implementation/` (4,906 lines):**

| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | launcher: guarded dep install, `exec python3 app.py`, `0.0.0.0:$PORT` |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 21 | entry point (pristine clock, empty store) |
| `app_factory.py` | 67 | Flask app, blueprint registration, error handlers |
| `clock.py` | 88 | logical clock (fixed `2026-09-01T00:00:00Z`), ISO formatting |
| `db.py` | 103 | in-memory store + common-field helpers |
| `errors.py` | 141 | 50 error IDs and statuses |
| `response.py` | 88 | envelope, pagination |
| `middleware.py` | 100 | auth/role/permission gate, phone masking |
| `validators.py` | 168 | body/enum/field validation |
| `models.py` | 300 | 14 entity serialisers |
| `services.py` | 306 | posture, alert synthesis, trip creation |
| `calculations.py` | 827 | all scoring/pricing/window rules |
| `routes/` (10 modules) | 2,680 | endpoint handlers |

**Coverage:** 86 endpoints (1 health + 85 spec), 13 state machines, 14 calculation rules, 12 validation priorities, RBAC from the §1.7 matrix. Auth uses `X-User-ID`/`X-User-Role`; envelope uses `meta`/`response_type`/`data`; pagination uses `limit`/`offset`/`total_count`/`has_more`; OCC uses `expected_district_version` → `ERR_STALE_VERSION` (412).

**Persistence:** in-memory dicts only — verified by scan for `sqlite3`/`open()`/`pickle`/`json.dump`/`/tmp`. A fresh boot returns `total_count = 0` for every collection and the clock reads the default instant. No seed/preload/register code exists anywhere; `.gitkeep`-style scrubbing confirmed by grep for `seed|preload|fixture|bootstrap`.

## Ambiguities resolved

1. **`cleared_after_months`** — undefined derivation. Used whole calendar months between the check's creation date and the clear instant.
2. **Compliance expiry for a non-fingerprint-only packet** — the rule says "min of CLEARED FINGERPRINT_* rows" but the pipeline admits a `COUNTY_COURT`-only packet, which would make expiry null and drop a valid driver from dispatch. Fell back to the min across all CLEARED rows.
3. **Auto-posture from a HIGH alert vs. the absence grade** — a HIGH dispute/absence both implies LOCKED. Made alert-driven posture the final write so `safety_state` and the alert severity agree.
4. **`ERR_ALREADY_TERMINAL` scope** — reserved for final states (`CANCELLED` trips, `VOIDED` incidents, `PAID`/`VOIDED` statements, `EXPIRED` contracts), not `COMPLETED` trips.
5. **Gate ordering** — driver-scoped identity (`ERR_DRIVER_NOT_SELECTED`, `ERR_NOT_TRIP_DRIVER`) runs as authorisation *before* posture/state, since PRD §3 puts authorisation second.
6. **`trip_alert_severity` contract** — returned severity, `notify_caregiver`, `notify_school` and `notify_support_center` together, since the notification flags are the alert's substance.
7. **`issuance` check order** — followed the PRD's stated sequence (state → period → empty → over-limit).
8. **Status codes** — `201` wherever an operation adds a new distinct resource to a collection (including `schedule`, `resume-series`, `geofence-checks`); `200` for in-place mutation.

A note on the final verification: three independent probe suites were run through `bash start.sh` (readiness 0.67 s), all passing. Several apparent failures during testing turned out to be incorrect expectations rather than defects — notably the dispatcher tie-break (`created_at` ascending, never `id`), the global driver roster, and `round_half_up` where half-cent ties cost a cent.

## Step 7: Run tests and iterate — 2026-09-30T12:30:00.000Z

All 8 parallel rounds pass 72/72 with zero flakiness. Done.

## Summary

**Iterations run:** 5 diagnostic harness rounds + 2 full 8-round parallel sweeps (the final sweep is clean).

**Final result:** 72/72 tests pass in all 8 concurrent rounds; zero flakiness (no test failed in any round).

### Tests deleted (2)
- `test_12_driver_roster_surface.py::test_a_newly_onboarded_driver_ignores_client_supplied_qualification_fields` — **PRD IS SILENT**. PRD §3.3's sentence only states the *initial values* of status/seat count/expiry/strike count for a new driver; it never says the create operation tolerates or rejects client-supplied server-managed fields. The driving scaffold rule is SCAFFOLD §1.6 ("malformed body, unknown field, … is ERR_INVALID_REQUEST"), which is exactly the scaffold-only rule the test asserted against — a PRD-only implementer rejects the payload. (doc-generator: Zero-Silence Rule violation; unit-test-generator: rule not derivable from PRD.)
- `test_18_geofence_and_limits.py::test_a_district_over_its_issuance_limit_is_refused_the_next_issue` — **PRD IS SILENT on the value**. PRD names `ERR_DISTRICT_OVER_LIMIT` and says the trigger is "strictly greater than the district's overdue threshold" but never states the threshold, so a threshold-crossing fixture cannot be derived (a PRD-faithful implementation may pick any value). The PRD-verbatim portion (`issue` adds to `outstanding_balance_cents`) is preserved elsewhere. (unit-test-generator: unique-derivability miss.)

### Fixes applied to `test_helpers/`
- `fixtures.py` — added the missing `get_success_data` import (a `NameError` that faked **62** independent implementation failures; the single highest-leverage fix).
- `fixtures.py::vet_driver` — accepts and forwards extra onboarding kwargs (`full_name`, `phone`), so distinct drivers can coexist (a `TypeError` in 5 tests).
- `fixtures.py::record_inspection` — new `expect_success=False` path returning the raw response, so a test can assert a *refusal* (the old always-`get_success_data` turned a legitimate 422 into a fake "Setup failed").
- `fixtures.py::create_request` — approval is now skipped when `submit=False` (previously approved a DRAFT, which PRD §3.4 forbids → `ERR_INVALID_STATE`).
- `fixtures.py::setup_absence_scenario` — pins the clock to the arrival instant *before* arrival, because PRD computes wait blocks as elapsed-minutes-since-arrival; the old ordering measured 20 hours of wait.
- `fixtures.py::setup_rider_overlap_scenario` / `setup_driver_overlap_scenario` — a vetted driver is required for the first trip to be schedulable; the rider-scenario's first trip was failing `ERR_NO_ELIGIBLE_DRIVER`. The driver-overlap scenario now uses an exclusive `WHEELCHAIR` specialty so the global dispatch ranking cannot steal its date.
- `fixtures.py::setup_strike_cascade_scenario` — restructured: the LOW-graded absence is built first (accumulating its `pre_strikes` HIGH absences in-place on the *same* driver, not a fresh district), and `scoped_trip` is `None` when the driver is already suspended — matching how PRD's threshold interacts with dispatch eligibility.
- `constants.py::pickup_handoff_payload` — was `AUTHORIZED_ADULT`/`PHOTO_ID`, which PRD §3.8 renders a **failed** handoff unless the name is on the student's roster; switched to `PLACEMENT_WORKER`/`PHYSICAL_SIGNATURE`, the neutral always-valid release. This one fixture bug caused ~15 "Setup failed" errors.
- `constants.py::dropoff_handoff_payload` — drops `billable_miles` when re-tagged to another leg (the field belongs to DROPOFF alone).

### Fixes applied to `implementation/`
- `routes/ride_requests.py` (resume-series, one-off schedule) — return 200/201 per PRD §4's create-vs-modify rule (`suspend`/`resume` are state transitions of an existing request).
- `routes/trips.py::cancel_trip` — PRD §3.8 compresses *both* terminal states into `ERR_INVALID_STATE` ("a trip in any other movement state is refused with ERR_INVALID_STATE"); the code was reporting `ERR_ALREADY_TERMINAL` for COMPLETED.
- `routes/trips.py::restore_trip` — the parent-request gate ("only while the parent request is still SCHEDULED — otherwise … ERR_REQUEST_NOT_SCHEDULED") now runs ahead of the terminal probe.
- `routes/trips.py::resolve_discrepancy` — the exception record is cleared only on the DISCREPANCY→NORMAL hop; PRD §3.8's restore rule requires the exception to survive the LOCKED→DISCREPANCY hop so a MEDIUM/HIGH grade keeps blocking restoration.
- `routes/trips.py::release_lock` — accepts `DISCREPANCY` as well as `LOCKED`, so PRD §2.5's two-hop reverse loop completes.
- `routes/trips.py::report_exception` + `services.create_trip_alert` — a reported absence's alert takes the **grade** as its severity (PRD §3.8: "A `LOW` grade leaves the safety posture `NORMAL`"), instead of the generic base-HIGH alert rule re-escalating it and spuriously locking the trip and consuming a strike.
- `routes/drivers.py::create_background_check` — the opening step tolerates `PENDING` **or** `BACKGROUND_CHECK` (PRD §3.3.1: a failure "is not erased by a later clearance, and the driver's covering paperwork must be rebuilt from a fresh check"), with the per-check-type `ERR_DUPLICATE_CLEARANCE` rule preserved.
- `routes/districts.py` (availability block) — removed the 20-minute buffer that was being applied to the *trip-overlap* check; PRD §2.6 requires "a window that begins exactly at another window's close is accepted and a gap of zero minutes is permitted."

### Tests rewritten to stay PRD-faithful (no weakening)
- `test_13`'s multi-clearance compliance test (the original asserted a `PASSED`-plus-`COUNTY_COURT` state no declared transition can produce) was replaced with two constructible scenarios that cover the same verifiable clause.
- `test_01`, `test_07`, `test_10`, `test_12` were re-expressed against reachable states; `test_05`'s flat-absence half now uses an on-time dispatch so the grade boundary is observable as PRD specifies.
- `test_04`'s hardcoded credit-cap expectation was corrected (9810 → 7320) to match PRD's "floor of one half of the gross total".

No `skip`/`xfail` was added, no assertion was downgraded, and no PRD-required implementation check was removed.

## Step 8: Finalize PRD — 2026-09-30T13:20:00.000Z

PRD_FINALIZED.md is complete. Final verification: the full benchmark suite (72 tests) passes against `implementation/`, and I ran in-process probes confirming each concrete claim (driver-create field rejection; schedule 201 / resume 200 / suspend 200; restore of a COMPLETED trip under a suspended parent returns `ERR_ALREADY_TERMINAL`).

## Output

- **`PRD.md`: 1218 lines → `PRD_FINALIZED.md`: 1253 lines** (+35 lines, **+2.9%**; 54 added / 19 removed lines).

## Changes (one bullet per edit)

- **§3.3 (driver onboarding)** — insert — the create body admits only declared onboarding fields; a server-managed field (`status`, `approved_seat_count`, `compliance_expires_at`, `incident_strike_count`) is refused with `ERR_INVALID_REQUEST` — `implementation/routes/drivers.py:78-96`, `validators.py:48-51`
- **§3.3 (background-check opening)** — revise — the first pipeline step is legal from `PENDING` **or** `BACKGROUND_CHECK` (the failure-returned state), and the duplicate guard reads only `FINGERPRINT_FBI` rows so other check types may still be opened — `implementation/routes/drivers.py:129-142`, `calculations.py:152-181`
- **§2.6 (window geometry)** — revise — the platform applies no twenty-minute buffer; the availability-block overlap test and series-to-series comparison both evaluate at second precision — `implementation/routes/districts.py:243-262`, `calculations.py:684-691`, `services.py:246-262`
- **§3.6 (availability block)** — revise — removes the applied buffer from the trip-overlap check (keeps it as a separate clause from the block-vs-trip wording) — `implementation/routes/districts.py:229-272`
- **§3.8 (planned cancellation)** — revise — both terminal movement states (`CANCELLED`, `COMPLETED`) are compressed into the ordinary `ERR_INVALID_STATE`, not the terminal-lockdown error — `implementation/routes/trips.py:484-510`, `55-72`
- **§3.8 (restoration)** — revise — `CANCELLED` is the only legal source and is never itself a terminal probe (a cancelled trip whose parent is not `SCHEDULED` reports `ERR_REQUEST_NOT_SCHEDULED`); a non-`CANCELLED` trip is refused that way (`COMPLETED` → `ERR_ALREADY_TERMINAL`, other states → `ERR_INVALID_STATE`) — `implementation/routes/trips.py:513-551`
- **§3.9 (posture recovery)** — revise — the exception record is cleared only on the `DISCREPANCY`→`NORMAL` hop and survives `LOCKED`→`DISCREPANCY` (the `ERR_OPEN_ALERTS` half was already PRD-verbatim) — `implementation/routes/trips.py:556-591`
- **§3.9 (release-lock)** — revise — the release also accepts a `DISCREPANCY` trip and carries it to `NORMAL`; a trip already `NORMAL` is refused with `ERR_INVALID_STATE` — `implementation/routes/trips.py:594-615`
- **§2.5 (safety posture)** — revise — same release-lock acceptance stated for the global principle — same path
- **§3.8 (absence reporting)** — revise — the student-absent alert takes the absence grade as its severity instead of re-running the generic base-severity rule, so a `LOW` grade stays `LOW` and `NORMAL` — `implementation/services.py:77-136`, `routes/trips.py:463-471`
- **§3.5 (scheduling)** — insert — one-off and recurring scheduling both answer `201 Created` — `implementation/routes/ride_requests.py:333`, `377`
- **§3.5 (resume-series)** — insert — resume answers `200 OK` (suspension too), being a state transition of an existing request — `implementation/routes/ride_requests.py:472-473`
- **§3.10 (billing run / issue)** — insert — the overdue threshold is the fixed account-level figure `500000` cents, the same for every district — `implementation/calculations.py:24`, `routes/billing.py:66-76`

## Per-edit pre-edit search log

1. **§3.3 onboarding field rejection** — (a) subject: create-driver body field set. (b) enumerated: `routes/drivers.py::create_driver` (`DRIVER_INPUT` + `reject_unknown`); `validators.reject_unknown`; all 30 `reject_unknown` call sites (confirmed 30 sites/85 handlers, all body-reading POST/PUT covered). (c) wording used "such as" and "in particular" rather than an exhaustive enumerated list, so it stays true for all other unknown fields.
2. **§3.3 background-check opening** — (a) subject: source-state gate for opening a background check. (b) enumerated: `create_background_check`; `fail_background_check` (PENDING-fail sets status `PENDING`; CLEARED-revocation sets `SUSPENDED`); `clear_background_check` (failure-not-erased → `BACKGROUND_CHECK`); `attest_inspection`/`create_inspection` (require `INSPECTION`/`BACKGROUND_CHECK`); `driver_approved_seat_count` status list; `test_12` (`COUNTY_COURT` accepted; `FINGERPRINT_FBI` duplicate refused). (c) **adjusted**: original draft said "per check type" — false, since the guard only inspects `FINGERPRINT_FBI`; reworded to "the guard reads only the driver's `FINGERPRINT_FBI` rows".
3. **§2.6 buffer** — (a) subject: the twenty-minute availability buffer. (b) enumerated: `calculations.AVAILABILITY_BUFFER_MINUTES`/`SERIES_OVERLAP_BUFFER_MINUTES` (referenced nowhere), `create_availability_block` (uses `half_open_overlap`), `services.driver_series_overlap`, `test_03` (zero-minute gap accepted). (c) rewrote so the mismatch is visible and PRD-consistent without inventing an "applies buffer" claim the impl lacks.
4. **§3.6 availability block** — (a) as #3. (b) as #3 + `services.rider_window_collision` and `recalculate` call chain. (c) none. (An intermediate draft claiming the affected-request set is always empty was **reverted** — that is behaviour outside the step_7 item and the impl only reaches that state via unrelated bugs.)
5. **§3.8 cancel** — (a) subject: `cancel_trip` source-state gate/error id. (b) enumerated: `cancel_trip`, `_state_gate`/`_terminal_gate`, `services.refresh_trip_relations`, `district_trips_scheduled_total`, `test_13::test_cancelling_a_completed_trip_is_refused_as_a_wrong_state`. (c) none.
6. **§3.8 restore** — (a) subject: `restore_trip` guard order and terminal probe. (b) enumerated: `restore_trip` (inline `!= CANCELLED` probe, parent gate, past-date, posture), `_state_gate`, `_terminal_gate`, `test_07`, and an in-process probe of a `COMPLETED` trip under a suspended parent. (c) **adjusted twice**: removed the initial draft's "parent gate runs ahead of the terminal probe" (false for a `COMPLETED` trip → `ERR_ALREADY_TERMINAL`); removed the "pinned candidate" addition to the cleared-field list (outside scope, and `candidate_driver_id` isn't in the step_7 diff description).
7. **§3.9 resolve-discrepancy** — (a) subject: exception clearing across the two recovery hops. (b) enumerated: `resolve_discrepancy` (DISCREPANCY→NORMAL clears; LOCKED→DISCREPANCY does not), `restore_trip` posture gate, `driver_strike_count` LOCKED term, `release_lock`, `test_08` (discrepancy-hop trip asserts `LOCKED`). (c) none.
8. **§3.9 release-lock** — (a) subject: `release_lock` accepted postures. (b) enumerated: `release_lock` (`LOCKED`/`DISCREPANCY`, else `ERR_INVALID_STATE`), `resolve_discrepancy`, `test_08`/`test_09`. (c) kept "LOCKED in that dimension" so the terminal-lockdown framing isn't re-applied to `NORMAL`.
9. **§2.5 release-lock** — (a)/(b) as #8. (c) none.
10. **§3.8 absence alert** — (a) subject: severity of the alert a reported absence raises. (b) enumerated: `report_exception` (`severity_override=grade`), `services.create_trip_alert` (override recomputes routing), `calculations.trip_alert_severity`, other `create_trip_alert` sites (depart/geofence/handoff/sweep — no override). (c) none.
11. **§3.5 schedule status** — (a) subject: HTTP status of scheduling. (b) enumerated: `schedule` (201 both branches), `create_trip` route (201), create-vs-modify rule (PRD §4), `test_13`/`test_03` accepting 201. (c) none.
12. **§3.5 resume status** — (a) subject: status of resume/suspend. (b) enumerated: `resume_series` (200), `suspend_series` (200), `test_07` (no status assertion). (c) none.
13. **§3.10 threshold** — (a) subject: the overdue threshold value. (b) enumerated: `OVERDUE_THRESHOLD_CENTS` (only use), `_assert_issuable`, `issue_statement` (sets `SUSPENDED`), `create_district` (no threshold field), `create_billing_run`, `expire_overdue_contracts`. (c) worded as "an account-level figure … the same value for every district rather than a per-district setting" to match the constant.

## Notable judgment calls

- The two **deleted tests** are PRD silences the impl pins: onboarding field rejection and the `500000` threshold — both added.
- I **did not** pin the fixture-only items (`get_success_data` import, handoff payloads, clock pinning, cascade restructuring, credit-cap 9810→7320, provider-side `PENDING`/`BACKGROUND_CHECK` widening, generic cascades) — per the method, impl already matches PRD there.
- Three exploratory edits were **reverted after the mandatory enumeration** (background-check `FAILED`-terminal probe, restore "pinned candidate", availability "empty affected set") because they either exceeded `<step_7_diff>` scope or would have created new mismatches.

## Step 9: Complete PRD — 2026-09-30T14:35:00.000Z

`PRD_COMPLETED.md` is written. Final report:

## Source and size
- Source file: **PRD_FINALIZED.md** (present, so it was copied); `PRD.md` was not used.
- PRD_FINALIZED.md: 1,253 lines / 100,614 bytes → PRD_COMPLETED.md: 1,556 lines / 129,946 bytes. **Line delta +303, char delta +29,279.**
- 76 diff hunks; endpoint table gained exactly 2 rows (`GET /student-rides/riders`, `GET /student-rides/drivers`); the §5 error table is byte-identical; no sections added.

## Counts
- **ambiguity-pins: 62**
- **mismatch-revisions: 16**

## Changes (one bullet per change; `insert` = pin a silence, `revise` = correct prose)

**§2 — global**
- §2.2 Success envelope — insert — ambiguity — pinned that unpaged list answers still report all four pagination fields; non-paged `limit` = set size (or 10 when empty); `response_type` is `"array"` for collections — `response.py:31-49`
- §2.3 Pagination — insert — ambiguity — `limit`/`offset` parse fallbacks, clamping to [1,100], negative offset; named the three operations that ignore paging; computed objects carry no pagination — `response.py:66-88`
- §2.4 Compliance expiry — insert — ambiguity — fingerprint-less fallback to the full cleared set; null when no `PASSED` inspection; rendered as `YYYY-MM-DD` — `calculations.py:184-211`
- §2.5 Safety posture — insert — ambiguity — posture is committed inside the same response that implies it (no separate write) — `services.py:44-59,130-135`
- §2.7 `updated_at`/`version` — insert — ambiguity — state transitions advance `version` without re-stamping `updated_at`; `version` is an integer — `db.py:58-72`
- §2.11 Nested retrieval — insert — ambiguity — a resolving path id need not match the actor outside `Driver`; child collection reads answer the whole filtered set — `middleware.py:51-66`

**§3.1 District/contract/credit**
- §3.1 registration — insert — ambiguity — unknown members (incl. server-managed fields) → `ERR_INVALID_REQUEST` — `routes/districts.py:60-67`
- §3.1 contract transitions — insert — ambiguity — drafting rejects unknown members; contract transitions carry no version check and advance the district's version via `account_status` — `routes/contracts.py:57-74`
- §3.1 credit pool — insert — ambiguity — `reason` optional, negative amounts applied, `expected_district_version` refused as unknown — `routes/districts.py:308-320`

**§3.2 Riders**
- §3.2 `spi_level` — insert — ambiguity — band is a ranking convention, not a validated range — `routes/riders.py:63`
- §3.2 update surface — insert — ambiguity — only seven members editable; others → `ERR_INVALID_REQUEST`; `authorized_adults` replaced wholesale — `routes/riders.py:20-23,93-115`
- §3.2 driver masking — revise — ambiguity — driver read replaces `emergency_contact_phone` with the masked digest rather than omitting it — `models.py:39-58`

**§3.3 Driver pipeline**
- §3.3 onboarding — insert — ambiguity — declared quantities (short experience, non-positive capacity) accepted at onboarding, disqualify later — `routes/drivers.py:76-96`
- §3.3 inspection step — insert — ambiguity — `INACTIVE` driver → `ERR_ALREADY_TERMINAL` on that step — `routes/drivers.py:175-179`
- §3.3 deactivate/reactivate — revise — ambiguity — source states `ACTIVE`/`SUSPENDED` only; others `ERR_INVALID_STATE`; `INACTIVE` terminal for reactivation; unset expiry refused — `routes/drivers.py:242-283`

**§3.3.1 Checks and inspections**
- §3.3.1 clear — insert — ambiguity — whole-month count (never negative); re-clear → `ERR_ALREADY_TERMINAL` — `routes/drivers.py:295-319`
- §3.3.1 revocation — insert — ambiguity — `SUSPENDED` still qualifies for the seat rule, so the count stays at its covered value; re-fail → `ERR_ALREADY_TERMINAL` — `routes/drivers.py:322-386`
- §3.3.1 rejection — insert — ambiguity — `FAILED` terminal for reject/attest; `INACTIVE` driver terminal too — `routes/drivers.py:432-467`

**§3.4 Intake**
- §3.4 create — insert — ambiguity — unknown members refused; creation advances the district version; stale-version guard precedes rider resolution; inverted series dates → `ERR_INVALID_REQUEST` — `routes/ride_requests.py:85-139`
- §3.4 terminal/refusal split — insert — ambiguity — `REJECTED`/`CANCELLED` → `ERR_ALREADY_TERMINAL`, otherwise `ERR_INVALID_STATE`; `reason`/`revision_note` not persisted; cancel source states `DRAFT`/`SERIES_SUSPENDED` — `routes/ride_requests.py:55-65,171-265`

**§3.5 Scheduling**
- §3.5 scheduling — insert — ambiguity — scheduling pins a candidate per date; body admits `scheduled_date` alone; rider collision checked before the driver search — `routes/ride_requests.py:270-377`
- §3.5 suspend/resume — insert — ambiguity — both answer with the request object; suspension does not rewrite posture; resume regenerates released dates; `ERR_SERIES_ENDED` before `ERR_NO_SCHOOL_DAYS_IN_RANGE`; rider collision rolled back — `routes/ride_requests.py:380-473`
- §3.5 events — insert — ambiguity — body enum; duplicates not re-appended; answer is the district; fan-out cancels only `SCHEDULED`/`DRIVER_EN_ROUTE` and leaves posture — `routes/monitoring.py:83-122`

**§3.6 Dispatch**
- §3.6 dispatch/accept — insert — ambiguity — selection excludes the dispatched trip from its own occupancy test; `DistrictAdmin` skips both candidate checks and pins the rule's choice — `routes/trips.py:220-282`
- §3.6 availability block — insert — ambiguity — 20-minute buffer not applied; `reason` optional and block not addressable; named the three unpaged list answers; supply-run body and ordering — `routes/districts.py:226-305`

**§3.7 Supply plan**
- §3.7 — insert — ambiguity — demand filter is a query parameter; plan is a computed object with no pagination/common fields; date-keyed maps repeat under `per_date`; empty-coverage dates still reported — `calculations.py:696-764`, `routes/districts.py:207-223`

**§3.8 Trip execution**
- §3.8 direct creation — insert — ambiguity — requires `SCHEDULED` parent (`ERR_INVALID_STATE`, not `ERR_ALREADY_SCHEDULED`); window order → `ERR_INVALID_REQUEST` — `routes/trips.py:126-173`
- §3.8 handoff fields — insert — ambiguity — `verification_code` read on the rule's leg only; `billable_miles` read on `DROPOFF` only — `routes/trips.py:378-379`
- §3.8 handoff verdicts — insert — ambiguity — refused handoffs still recorded; pickup leaves state, dropoff still completes; attempt cap outranks posture/state gates; dropoff re-attemptable after a pass — `routes/trips.py:327-339,416-435`
- §3.8 failed dropoff — insert — ambiguity — dispute alert anchored to the incident and searched via the shared severity rule (so it can read `HIGH` while the incident reads `MEDIUM`); receiving party not recorded — `routes/trips.py:389-409`
- §3.8 absence report — insert — ambiguity — already-reported guard precedes body checks — `routes/trips.py:425-431`
- §3.8 grade multipliers — insert — ambiguity — exclusive branches, no-driver always halves; grade fixed at report time — `calculations.py:556-566`
- §3.8 absence alert routing — insert — ambiguity — overridden alert's routing follows the grade — `services.py:111-120`
- §3.8 cancel/restore — insert — ambiguity — cancellable only from `SCHEDULED`, any other state (incl. cancelled) → `ERR_INVALID_STATE`; state gate before posture gate — `routes/trips.py:496-505`
- §3.8 restoration — revise — insert — mismatch/ambiguity — parent-state gate is first, ahead of date and posture; restoration also clears the pinned candidate and arrival instant — `routes/trips.py:513-551`

**§3.9 Monitoring**
- §3.9 geofence registration — insert — ambiguity — signed centre, unvalidated radius, `registered_on` is a bare date — `routes/geofences.py:33-41`
- §3.9 geofence recording — revise — insert — mismatch/ambiguity — one check per fence in fence order (not one check total); an unpaged whole-set answer; per-fence alerts escalate within the same observation; recordings allowed in any state — `routes/trips.py:620-650`
- §3.9 monitor sweep — insert — ambiguity — body admits `trip_id` alone; answers the trip; finished trip → `ERR_INVALID_STATE` — `routes/monitoring.py:42-80`
- §3.9 severity rule — insert — ambiguity — breach escalation applied then strike escalation reads its result; coordination cap applied last to the escalated severity — `calculations.py:590-630`
- §3.9 routing — insert — ambiguity — flags read the final (post-cap) severity — `calculations.py:623-629`
- §3.9 `released_by_resolution` — insert — ambiguity — direct resolve always leaves it false; true only via incident review/void; alert creation writes posture in the same request — `routes/incidents.py:196-205`, `services.py:139-146`
- §3.9 alert resolution — insert — ambiguity — re-resolving a closed alert → `ERR_INVALID_STATE`, not terminal — `routes/incidents.py:200`
- §3.9 incident shape — insert — ambiguity — no stored strike tally; incidents open `REPORTED` — `calculations.py:125-139`
- §3.9 resolution — insert — ambiguity — body enum; note rule precedes adjudication rule; no-driver skips the fault pre-check; answer carries the resolved score; note stored — `routes/incidents.py:90-144`
- §3.9 reopen/void — insert — ambiguity — `RESOLVED` → `ERR_INVALID_STATE` for review/void; `VOIDED` → `ERR_ALREADY_TERMINAL` for all four; `reason` optional and unstored — `routes/incidents.py:47-58,147-193`
- §3.9 impact score — insert — ambiguity — strike input excludes the trip's own lock strike; recomputed on read and for sibling incidents — `calculations.py:635-646`, `services.py:180-184`
- §3.9 discrepancy clearing — insert — ambiguity — already-`NORMAL` → `ERR_INVALID_STATE` — `routes/trips.py:556-591`
- §3.9 lock release — insert — ambiguity — accepts `LOCKED` or `DISCREPANCY`, writes `NORMAL` without touching the exception record — `routes/trips.py:594-615`

**§3.10 Billing**
- §3.10 billing run — insert — ambiguity — body enum; stale guard first; no `ACTIVE` contract → `ERR_FORBIDDEN` with the sweep's artefacts already written; `201 Created`; version advances on the reservation even at zero credit — `routes/districts.py:142-202`
- §3.10 credit term — insert — ambiguity — cap is half the gross rounded half-up; `total_miles` keeps fractions — `routes/districts.py:171-182`
- §3.10 issue/pay — insert — ambiguity — period-key check spans all completed trips in the window; strict `>` on the threshold; issue gate ordered after empty and period checks; payment amount recorded but not used; `OPEN` payment → `ERR_INVALID_STATE` — `routes/billing.py:66-139`
- §3.10 provenance — insert — ambiguity — stamp captured at installation and never rewritten; filters applied together — `routes/billing.py:49-63`
- §3.10 contract suspend — insert — ambiguity — auto-void touches neither the outstanding balance nor an instant; statements read `VOIDED` afterwards — `routes/contracts.py:118-143`
- §3.10 contract expiry — insert — ambiguity — the sweep spans every contract and is not reported through an error identifier — `calculations.py:816-828`

**§4 and §5**
- §4 intro — insert — ambiguity — surface is closed (`405`/unknown path → `ERR_INVALID_REQUEST`/`ERR_NOT_FOUND`); `PlatformAdmin` superset behaviour; only `Driver` is entity-backed — `app_factory.py:50-62`, `middleware.py:43-66`
- §4 table — insert — ambiguity — added the two unlisted collection reads (`GET /student-rides/riders`, `GET /student-rides/drivers`) and the `GET /` health path — `routes/riders.py:78`, `routes/drivers.py:99`, `app_factory.py:64-66`
- §5 intro — insert — ambiguity — the `409` identifiers are told apart by workflow, not status; only `ERR_STALE_VERSION` is `412` — `errors.py:79-126`

## Notable impl-only behaviours surfaced (previously PRD-silent or contradicted)
- Failing dropoff sets `DISCREPANCY` and opens a `MEDIUM` incident, yet the dispute alert is computed by the generic rule and reads `HIGH` on a two-breach trip (probe: alert `HIGH`, incident `MEDIUM`). PRD previously said only "DISCREPANCY".
- A `DistrictAdmin` may `accept` a trip with no pinned candidate and the platform pins its own choice — a path PRD never mentioned (`routes/trips.py:247-275`).
- Scheduling *does* pin a per-date candidate, contradicting the README claim in `services.py` that "no candidate is pinned until dispatch".
- Driver supply run and availability block are unpaged and `GET /student-rides/riders`/`drivers` were undocumented.
- `INACTIVE` is terminal for the driver dimension, so `deactivate → reactivate` cannot round-trip (probe returned `ERR_ALREADY_TERMINAL`, not the seat restoration the seam name implies).

A server started for probing (PID 3575001, listener PID 3575003 on port 18973) was left running by the subagent; the orchestrator verified both PIDs' identity (cwd = this task's `workspace/implementation`, listener bound to exactly `:18973`) and killed exactly those two PIDs. Port 18973 is free again. No broad kill patterns were used.

## Final verification — 2026-09-30T14:45:00.000Z

- All three scaffold artifacts present with the correct single top-level design key each.
- `workspace/` holds `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/`.
- Implementation is unchanged since the passing sweep: newest source file mtime 11:36:08, `results.8.json` mtime 11:46:22. Steps 8 and 9 wrote only `PRD_FINALIZED.md` / `PRD_COMPLETED.md`, so the 8×72/72 result remains valid against the current `implementation/`.
- `results.{1..8}.json` all report `passed=72 total=72 failed=0 errors=0`.
- Removed `__pycache__` directories from `implementation/` and `test_helpers/`/`test_suite/`.
- Probe server left by the Step 9 subagent (bash PID 3575001, listener PID 3575003 bound to `:18973`, cwd = this task's `workspace/implementation`) was identified by PID+cwd+port and killed by exact PID only. Port 18973 confirmed free. No broad kill pattern used.
