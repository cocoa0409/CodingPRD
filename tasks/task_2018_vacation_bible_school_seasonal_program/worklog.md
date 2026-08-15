# Worklog — task_2018_vacation_bible_school_seasonal_program

## Step 1: Create Task Directory — 2026-08-15T07:09:00.000Z

Pre-existing per pipeline invocation: `tasks/task_2018_vacation_bible_school_seasonal_program/` and its `workspace/` were created by the caller; orchestrator did not scan or create any other task directory.

## Step 2: Generate Scaffold — 2026-08-15T08:17:00.000Z

All three scaffold artifacts are written, lint-clean, and self-audited. Summary of what was generated for task_2018 (Vacation Bible School & Seasonal Program Registration):

### SCAFFOLD.yaml (1356 lines) — `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/SCAFFOLD.yaml`

**Complexity profile**: quota_allocation (primary) + compliance_audit (secondary); layers: optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation; flat topology with FK references; segregation_of_duties role model; immediate consistency. Logical clock endpoint with the mandated default `2026-08-01T00:00:00Z`.

**17 entities**: Program, Classroom, Family, Child, Registration, Volunteer, ScreeningCheck, RoleAssignment, AccommodationPlan, SupplyOrder, SupplyItem, SupplyDistribution, ProgramDay, SecurityTag, AttendanceRecord, FamilyMessage, RetentionEntry — all FKs carry canonical `FK -> X.id` descriptions and every FK has a reverse-reachability GET.

**15 state machines**, including: Registration with creation fork (ENROLLED|WAITLISTED) + OFFERED fan-out to ENROLLED/DECLINED/EXPIRED; ScreeningCheck cycle (SUBMITTED→INFO_REQUESTED→SUBMITTED); Classroom ACCEPTING⇄FULL auto-cycle; SupplyOrder SUBMITTED→DRAFT revision loop; AccommodationPlan supersede; Program 6-state lifecycle.

**3 OCC concurrency rules** (all pass the serial-observability filter): classroom config PATCH, plan approve-with-supersede (Child.version), waitlist sweep (Program.version).

**13 calculations** with pinned constants/rounding: age-at-registration (birthday-on-start-date rule), required_adults (max(2, ceil) staffing), open_seats pool, waitlist promotion loop, dual-variant kit recommendation (provisional vs final), per-classroom-then-sum craft pack rounding, budget remaining (APPROVED-only input set), dual-variant attendance rate (provisional/final denominators), priority tiers with inclusive 0.80/0.60 boundaries, allergen set-intersection safety check, family-dedup recipient counts, strict-> late pickup, FCFS waitlist ordering (created_at only, never id).

**11 ordered validation priority rows** (P0 request → P10 fiscal, with child-safety deliberately outranking state), **88 endpoints**, **40 error codes** (every one triggerable and exercised by a design instance), **8 roles** (Anonymous, Parent `entity_backed:Family`, Volunteer `entity_backed:Volunteer`, CheckInStaff, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, ProgramDirector) with two-way segregation of duties (screener ≠ assigner, parent ≠ check-in staff, self-review forbidden).

### SCAFFOLD_DIFFICULTY_DESIGN.yaml (1035 lines) — 24 instances across all 9 rules
dual_variant_calc (2: SupplyOrder kits vs attendance rate), combinatorial_formula (3: modes a/b/c — max/ceil staffing, per-classroom rounding order, promotion evaluation-order loop), non_linear_state_machine (2: ScreeningCheck cycle, Registration branching), transitive_cascade (3: cancel→flip→promote depth-3, clearance→auto-confirm→staffing depth-4, family-archive cascade), priority_pair_validation_conflict (3 distinct category pairs), boundary_precision_check (3: seats / strict offer-expiry time / retention ratio), cross_entity_state_dependency (3 entity pairs), resource_temporal_overlap (3: closed-interval program overlap, aggregate capacity pool, strict day adjacency), compensating_invariant (2: seat conservation, stock conservation).

### SCAFFOLD_CORNER_DESIGN.yaml (1633 lines) — 72 entries (67 active + 5 excluded_because stubs)
Sections per the claim-extraction guide: entities (7), state_machines (10), calculations (5), validations (27), endpoints (4), errors (5 stubs), rbac (6), cross_cutting_layers (7 incl. all 3 OCC stale-version tests), consistency_model (1).

### Verification
- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1137 calls scanned, 24 + 67 instances, 0 violations)
- Additional self-audits passed: zero unbound `${var}` placeholders; all 211 grounds references resolve; instance names unique across both files; no forbidden race vocabulary; all 40 error codes referenced and triggered; all status-enum values reachable; file split honored (neither design key appears in SCAFFOLD.yaml); scenario text verbatim.
- All formula-derived asserts are pre-computed literals (e.g., kit 6 vs 8, craft packs 4, offer expiry 2026-08-03T00:00:00Z, rates 1.0000/0.4000/0.8000/0.6667, budget 94000/75000/30000, tag codes 000001/000002).

One design note: the entity/endpoint counts exceed the Expert band deliberately, per the task's harder-than-expert instruction — the depth is carried by the coupled mechanics (safety-gated check-in, OFFERED seat reservation pool, TTL promotion sweep, screening cascade into staffing posture) rather than by CRUD volume.

## Step 3: Copy Shared Files — 2026-08-15T07:10:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2018_vacation_bible_school_seasonal_program/workspace/INSTRUCTION.md` (1424 bytes). Executed while Step 2 subagent runs (no mutual dependency).

## Step 4: Generate PRD — 2026-08-15T08:39:00.000Z

Done. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/workspace/PRD.md`.

### Summary

**Section structure** (378 lines):
- §1 Introduction — 2 paragraphs (business context, then system scope + logical-clock framing)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 8 roles with identity prose per role), 2.2 API Response Structure (byte-identical verbatim block), 2.3 Pagination and List Ordering, 2.4 Logical Clock and Calendar Semantics, 2.5 Resource Identity, Versioning, and OCC (all 3 concurrency rules with endpoint, `expected_*_version` field, error id, and 412 status), 2.6 Numeric Precision and Rounding, 2.7 Seat Reservation and Waitlist Allocation, 2.8 Child-Safety Gates and Segregation of Duties, 2.9 Validation Pipeline (all 11 priorities with P7's six-rule internal order and the (v)-outranks-(vi) note), 2.10 Derived Fields and Immediate Consistency
- §3 Business Logic — 8 subsections organized by season timeline: 3.1 Program Setup/Calendar/Classrooms, 3.2 Household Intake/Registration fork, 3.3 Waitlist Offers/Expiry/Waterfall, 3.4 Volunteers/Screening/Staffing, 3.5 Accommodation Plans/Allergen Safety, 3.6 Kits/Stock/Distribution, 3.7 Program Days/Check-In/Tags/Pickup, 3.8 Messaging/Retention/Archive
- §4 Endpoint table — 88 rows, 4 columns only (Method, Path, Description, Authorized Role(s)); exact (method, path) diff vs scaffold: 0 missing, 0 extra
- §5 Error catalogue — all 40 error ids, 2 columns only; document ends at §5 with no audit footer

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].input (request bodies + query filters): 70 required, 70 present, 0 missing
- path_params: 17 required, 17 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.9 incl. P7 intra-tier order i–vi), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 52 checked across 15 machines, 52 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 13 checked, 13 fully expressed (incl. per-classroom-then-sum craft rounding with the 4-pack vs 3-pack divergence, 1.10 kit buffer, half-up 4dp rates, tier thresholds 0.80/0.60/0.50 inclusive), 0 missing
- validations[] conditions: 40 error conditions matchable to error_id in §2/§3 prose (verified: 0 error ids absent from §2/§3), 0 missing
- endpoints[].side_effects / applies_to: 88 checked, 88 expressed (all cascades: seat flips, promotion loop, family-archive cascade, auto-confirm exceptions, supersede + Child.version bump, reserve/issue/cancel arithmetic), 0 missing
- entities[].fields[] structured content: 103 checked, 103 reconstructible (defaults 8/48/12:00/EMAIL/false/empty/null/0, enum value sets, conditional allergens and classroom_id rules, system vs input vs computed sources), 0 missing
- sibling-branch symmetry: 9 groups checked (3 offer exits, 3 decide outcomes, 5 lifecycle steps, 3 classroom-close from-states, 4 message audiences, 2 rate variants, 2 kit variants, 3 cancel sources, 2 retention responses), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 626
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional precision checks (all pass):** §2.2 block byte-identical to `section-2.2-response-structure.md`; no fuzzy words ("approximately"/"roughly"/etc.), no race-framing in OCC text, no pseudocode operators (`==`, `>=`, `+=`, …) in §2/§3 prose; all 8 role names and all 44 state values appear verbatim; the SecurityTag day-close void branch is rendered as nominally declared but unreachable by construction, keeping `void_reason` faithful to its `REPRINT`-only enum.

## Step 6: Generate Implementation — 2026-08-15T09:20:00.000Z

Implementation complete and verified. All smoke suites pass and reboots yield pristine state.

### Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/workspace/implementation/`):

- `start.sh` — guarded pip install (no-op once Flask is importable), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0`, foreground
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/500 handlers, global request lock (RLock) for serialized mutations
- `errors.py` — `ApiError` + full 38-entry error catalog with HTTP statuses
- `clock.py` — logical clock, starts at exactly `2026-08-01T00:00:00Z`, never wall-clock
- `store.py` — in-memory dicts keyed by UUID for all 17 entities; monotonic `created_at`/`updated_at`; hidden `_seq` creation order key (drives created_at-ASC list sort and waitlist ranking); `touch()` bumps `version`+`updated_at` on every stored-field mutation
- `envelope.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data`; pagination fields `limit/offset/total_count/has_more` in meta for lists
- `auth.py` — `X-User-ID`/`X-User-Role` extraction, 8 declared roles, 401/403 helpers
- `validate.py` — P0 well-formedness DSL: required/undeclared-field rejection, strict types (bool≠int), enum/date/datetime/HH:MM parsing, allergen arrays
- `derived.py` — all computed fields recomputed from source rows at read time + per-entity serializers
- `cascade.py` — seat flips (each +1 classroom version), waitlist promotion waterfall (one-at-a-time, recompute after each promotion), enrollment side effects (mid-session NOT_ARRIVED spawn), cancellation cascade (record deletion on SCHEDULED/OPEN days), volunteer status rollup and auto-confirm-with-skip
- `routes/` — 17 modules: `programs` (lifecycle, OCC sweep, supply-plan, attendance-summaries), `classrooms` (OCC patch, close cascade), `families` (archive cascade), `children`, `registrations` (ENROLLED/WAITLISTED fork, accept/decline/cancel), `volunteers`, `screening`, `assignments`, `plans` (OCC approve + supersede bumps Child.version), `orders`, `items`, `distributions`, `days` (open/close gates), `attendance` (check-in 201, check-out, reprint, security tags), `messages`, `retention`, `clock_route`, plus `common.py` (pagination clamp 1–100, empty-body guard, archived-program read-only guard)

**Key design points:**
- **Validation pipeline** follows PRD §2.9 strictly per endpoint: P0 body → P1 auth → P2 role/ownership → P3 existence (program → classroom/day/item → child/volunteer/…) → P4 OCC (`expected_classroom_version`/`expected_child_version`/`expected_program_version`, required, 412) → P5 safety gates (self-review 403, accommodation, allergen, staffing, children-on-site) → P6 state + ARCHIVED read-only → P7 temporal (window, offer-expiry, day-today, overlap, out-of-range **before** not-sequential) → P8 constraints (age 422 before duplicate-registration, per §2.9 list order) → P9 referential → P10 fiscal (budget 402).
- **Calculations** use exact integer math (`ceil(n*11/10)` for the 1.10 kit buffer, per-classroom ceil-then-sum craft packs) and `Decimal` ROUND_HALF_UP at 4dp for rates/tier thresholds (0.8000 inclusive).
- **OCC** is enforced on exactly the three guarded endpoints; all other endpoints reject version fields as undeclared (400).
- **Timestamps**: business instants (offer_expires_at, enrolled_at, checked_out_at, sent_at, …) read the logical clock; entity `created_at`/`updated_at` use monotonic wall time. Tag codes are per-day zero-padded sequences (000001…), reprints consume the next value.
- **No seeding**: store starts empty every boot; verified pristine after kill+restart.

**Verification**: booted via `bash start.sh` on multiple ports; 5 smoke suites passed covering the full lifecycle (program→classroom→family→registration→waitlist waterfall→offer accept/expire/sweep→screening/auto-confirm→day open/staffing gate→check-in/out/tag reprint/late-pickup→orders/budget/kit-quantity→allergen gate→messages→retention generate/force→archive read-only), plus pipeline-ordering cases (400-before-401, 403-before-404 ownership, 412 OCC precedence, safety-outranks-state). `compileall` and `pyflakes` are clean (unused imports removed).

## Step 5: Generate Unit Tests — 2026-08-15T09:27:00.000Z

Generation complete and fully audited. Final summary:

### Generated files

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/test_helpers/`:
- `types.py` — 17 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.5), 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~70 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum + full §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_instant_equals` (format-tolerant ISO instant comparison used for `offer_expires_at` claims)
- `factories.py` — 14 payload factories (input fields only, unique emails/names via counter)
- `constants.py` — domain thresholds (two-adult minimum, 1.10 kit buffer, 3-units/10-pack craft constants, tier rates 0.80/0.60/0.50, default clock `2026-08-01T00:00:00Z`)
- `test_users.py` — opaque-role shared constants + mandatory per-instance builders `make_parent_headers(family_id)` / `make_volunteer_headers(volunteer_id)` for the two entity-backed roles
- `fixtures.py` — ~50 lenient builders across all five tiers, including `setup_classroom_with_queue` (N enrolled + M waitlisted), `create_volunteer_with_assignment(..., decide_count=k)` (partial-clearance control), `clear_volunteer`, `setup_in_session_program` (full DRAFT→IN_SESSION flow with ADEQUATE two-adult staffing), `run_session_days` (per-day open/check-in/check-out/close driving the logical clock), `generate_retention`
- `__init__.py` — barrel export

**`test_suite/`** — `conftest.py` + 11 test files organized by concern (envelope/access, program lifecycle, classrooms/capacity, families, registrations/waitlist, offers/expiry, volunteers/screening, accommodation/allergens, supply logistics, days/attendance, messaging/retention).

### Test counts

- **Queue A (Difficulty): 48 tests** covering all **24/24 instances** with exactly 2 tests each
- **Queue B (Corner): 67 tests** covering all **67/67 non-stub instances** with 1 test each
- **Total: 115 tests** (pytest-collected cleanly)

### Instances skipped

None. Every non-stub instance passed the PRD-first two-condition filter. The priority-pair instances (`checkin_safety_beats_state`, `order_approve_state_beats_fiscal`, `registration_constraint_beats_referential`) were kept because PRD §2.9 explicitly pins the ordering ("Tiers run in ascending priority number, and when several checks fail at once the lowest-numbered failure wins and produces the response"). The 5 `excluded_because:` stubs (queue B, errors section) were not translated; all 5 cross-references resolve to real difficulty instances.

### Audit results (all green)

- Every test docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line; all 115 tags resolve to real instances (no untagged, dual-tagged, dangling, or stub-pointing tags)
- Verbatim sweep: all 166 rule-bearing quoted spans (≥3 words) across all docstrings survive a literal whitespace-normalized grep of `PRD.md`; ellipsized citations were rewritten to full clauses during the pass
- No `skip`/`skipif`/`xfail` markers; no "scaffold"/table references in generated code
- pyflakes clean (suite); all modules import with only `PYTHONPATH=.`; `pytest --collect-only` collects 115 tests

Two derivability judgments worth noting: `offer_expires_at` values are compared as parsed instants (PRD pins the instant via the default clock + TTL, not the serialization string), and the `craft_packs_per_classroom` breakdown assertion accepts list or mapping shape (PRD §3.6 names "per-classroom breakdown" without pinning the container type) while still asserting the pinned per-classroom-rounded values `[2, 2]`.

## Step 7: Run Tests and Iterate — 2026-08-15T09:48:00.000Z

All 8 rounds pass 115/115 — clean sweep.

### Summary

**Iterations run**: 2 (round 1: 5 consistent failures across all 8 sweeps; round 2: all clean).

**Tests deleted**: none. All 5 failures traced to test bugs (assertions inconsistent with PRD-derived state or over-narrow shape acceptance), not PRD-silence or unique-derivability collapse.

**Fixes applied to `test_helpers/`**: none.

**Fixes applied to `test_suite/`** (5 tests, all setup/arithmetic bugs where the test author mis-computed the post-setup state):
- `test_suite/test_03_classrooms_and_capacity.py::test_close_with_enrolled_rejected` — with capacity=2 + waitlisted=0 the fixture creates 2 children, both ENROLLED → classroom flips FULL on the 2nd enrollment per PRD §3.2. Fixed assertion `ACCEPTING` → `FULL` (PRD §3.1: failed close leaves state untouched).
- `test_suite/test_03_classrooms_and_capacity.py::test_enrolled_count_reconciles_after_cancel` — same setup bug. Switched to capacity=1, waitlisted=0 (single enrollee) and corrected open_seats assertions to match: before 0, after 1.
- `test_suite/test_05_registration_and_waitlist.py::test_accept_from_enrolled_returns_invalid_state` — same setup bug; capacity=2 gives enrolled_count=2, not 1. Switched to capacity=1, waitlisted=0 so the "no double-enroll side effect" assertion (enrolled_count stays 1) is faithful.
- `test_suite/test_05_registration_and_waitlist.py::test_second_cancel_returns_invalid_state` — same setup bug; capacity=2 leaves a second enrollee at 1 after one cancel. Switched to capacity=1, waitlisted=0 so enrolled_count is 0 after the first cancel as the test asserts.
- `test_suite/test_09_supply_logistics.py::test_per_classroom_breakdown_reports_two_each` — PRD §3.6 names "per-classroom breakdown `craft_packs_per_classroom`" without pinning container shape. Test previously accepted only dict or list-of-ints; implementation returns list-of-rows (`[{"classroom_id":..., "packs":N}]`) — a third faithful reading. Extended the shape handler to also unpack `row["packs"]` from list-of-rows; per-classroom `[2, 2]` assertion unchanged.

**Fixes applied to `implementation/`**: none. Implementation was already PRD-faithful on all 5 paths.

## Step 8: Finalize PRD — 2026-08-15T09:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/workspace/PRD_FINALIZED.md` written with exactly one inline edit.

**Line counts / delta:** PRD.md 377 lines, PRD_FINALIZED.md 377 lines (0% line-count delta; one sentence inserted into an existing line at §3.6).

**Changes:**
- §3.6 (supply-plan paragraph) — insert — pinned the container shape of `craft_packs_per_classroom`: "a list with one row per non-`CLOSED` classroom in classroom creation order, each row carrying that classroom's `classroom_id` and its rounded pack count under `packs`" — `implementation/routes/programs.py:219-228` (rows built as `{"classroom_id": c["id"], "packs": craft_packs_for_classroom(c)}`, sorted by `_seq`), with per-row value from `implementation/derived.py:108-110`.

**Per-edit pre-edit search log:**
1. Edit: `craft_packs_per_classroom` shape.
   - (a) Subject: container shape and row ordering of the `craft_packs_per_classroom` breakdown in the supply-plan response.
   - (b) Paths enumerated: `implementation/routes/programs.py:213-231` (`supply_plan` — verified via repo-wide grep for `craft_packs`/`packs` that this is the sole producer); `implementation/derived.py:108-110` (`craft_packs_for_classroom`, sole caller is `supply_plan`); `implementation/derived.py:100-105` (`non_closed_classrooms`, shared with `kit_required_final` — already described in PRD as "status is not `CLOSED`", so wording reuses that exact phrase); `implementation/store.py:91-93` (`_seq` = monotonic creation-order key). Also confirmed the supply-plan response key set matches the PRD-named fields exactly (`enrolled_total`, `classroom_count`, `kit_quantity_provisional`, `kit_quantity_final`, `craft_packs_required`, `craft_packs_per_classroom`, `budget_remaining_cents`), so no other sentence needed touching.
   - (c) Wording adjustment: ordered rows described as "in classroom creation order" rather than "`created_at` ascending" to match `_seq` semantics exactly without inventing a tie-break claim; "rounded pack count under `packs`" (not "the count") to pin the key name as impl emits it; scoped strictly to non-`CLOSED` classrooms, consistent with both the impl filter and the existing kit-final wording in the same section.

**Items with no edit (justified):**
- Items 1–4 (test_03 ×2, test_05 ×2) are pure test-fixture arithmetic bugs: the PRD already uniquely determines each behavior — last-seat flip `ACCEPTING`→`FULL` (§3.2), `open_seats` recompute and waterfall on cancel (§2.7/§3.2), accept gated on `OFFERED` (§3.3), cancel from other states → `ERR_INVALID_STATE` (§3.2), failed close leaves state untouched (§3.1 `ERR_CLASSROOM_NOT_EMPTY`). Step 7's own note confirms "Implementation was already PRD-faithful on all 5 paths," so no PRD silence or mismatch exists to pin.

## Step 9: Complete PRD — 2026-08-15T10:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2018_vacation_bible_school_seasonal_program/workspace/PRD_COMPLETED.md` is written — a pure inline patch over `PRD_FINALIZED.md` (same line count, no new sections).

### Summary

- **Source**: `PRD_FINALIZED.md` (377 lines / 63,275 chars) → `PRD_COMPLETED.md` (377 lines / 64,704 chars); char-delta **+1,429**, 16 lines touched in place.
- **Counts**: 16 ambiguity-pins (inserts), 2 mismatch-revisions.

### Changes

- **§2.1 (Parent role)** — insert — ambiguity — pinned that list endpoints scope a Parent to their own household rows (foreign `family_id` filter yields an empty page, not 403) — implementation/routes/children.py:95-99, registrations.py:150-154, plans.py:163-167
- **§2.3 (Pagination)** — insert — ambiguity — pinned clamping of out-of-range `limit`/`offset`, default fallback for unparseable values, `has_more` = offset + returned rows < total_count, and that unknown query params are ignored — implementation/routes/common.py:11-28, envelope.py:33-43
- **§2.4 (Logical clock)** — insert — ambiguity — the set call accepts instants ahead of or behind the previous reading; naive datetimes are read as UTC — implementation/routes/clock_route.py:18-25, clock.py:24-29
- **§3.1 (Classroom PATCH)** — insert — ambiguity — age-band rules apply to the merged stored+supplied values; a `CLOSED` classroom rejects edits with `ERR_INVALID_STATE` — implementation/routes/classrooms.py:120-125, 133-134
- **§3.2 (Family list)** — insert — ambiguity — `include_archived` counts `true`/`1`/`yes` (case-insensitive) as true — implementation/routes/families.py:79-81
- **§3.2 (Family archive cascade)** — revise — mismatch — PRD named only `ENROLLED` cancellations as running the seat-flip/waterfall cascade; impl runs it for `OFFERED` cancellations too — now reads "each `ENROLLED` or `OFFERED` cancellation runs its normal cascade"; also pinned creation-order processing of children and registrations — implementation/routes/families.py:97-106, cascade.py:105-131
- **§3.4 (Volunteer create)** — insert — ambiguity — a `family_id` naming no existing family fails with `ERR_NOT_FOUND` — implementation/routes/volunteers.py:45-46
- **§3.4 (Screening decide)** — insert — ambiguity — `decision_notes` is optional, null when omitted — implementation/routes/screening.py:32-34
- **§3.4 (Screening resubmit)** — insert — ambiguity — `response_notes` is optional — implementation/routes/screening.py:37-39
- **§3.4 (Auto-confirm on CLEARED)** — insert — ambiguity — `PROPOSED` assignments auto-confirm in creation order — implementation/cascade.py:174-184
- **§3.5 (Request-revision)** — insert — ambiguity — `revision_notes` is a required field — implementation/routes/plans.py:35-37
- **§3.5 (Plan approval)** — revise — mismatch — PRD tied the child's version bump to a supersede occurring; impl increments the child's version on every approval, even with no prior `APPROVED` sibling — implementation/routes/plans.py:117-126
- **§3.6 (Supply items)** — insert — ambiguity — `restock_threshold` is zero-or-more; restock `additional_quantity` is at least 1 — implementation/routes/items.py:43-44, 89-90
- **§3.6 (Distribution creation)** — insert — ambiguity — body references validated in payload order: item, then classroom, then day, each missing reference → `ERR_NOT_FOUND` — implementation/routes/distributions.py:50-59
- **§3.7 (Check-in)** — insert — ambiguity — the 201 response carries the attendance record as `data` (not the minted tag) — implementation/routes/attendance.py:131-137
- **§3.7 (Reprint)** — insert — ambiguity — the response carries the updated attendance record — implementation/routes/attendance.py:186-189
- **§3.7 (late_pickup)** — insert — ambiguity — `late_pickup` reads false until a checkout computes it — implementation/routes/attendance.py:163-167

### Notable non-changes (verified already pinned or unreachable)

- All 60+ endpoint role lists, HTTP status codes, and 201/200 classifications in §4 match the implementation exactly.
- Validation pipeline ordering (P0–P10), including self-review-before-state on decide, allergen-gate-before-state on distributions, staffing-gate-first on day open, OCC-before-business on the three guarded endpoints — all match impl.
- The sweep's "no-op yet version still increments" pairing, tag-code sequence, kit/craft rounding, tier thresholds, and the archived-program read-only guard are all consistently pinned already.
- Framework fallbacks (unknown route → ERR_NOT_FOUND 404; 405 → ERR_NOT_FOUND/405; unhandled → ERR_INTERNAL 500 in app.py:38-51) were deliberately left unpinned as outside the declared endpoint contract of §4/§5.
