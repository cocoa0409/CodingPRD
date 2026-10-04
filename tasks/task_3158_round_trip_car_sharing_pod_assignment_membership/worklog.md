# Worklog — task_3158_round_trip_car_sharing_pod_assignment_membership

Scenario: Round-Trip Car Sharing Pod Assignment & Membership Operations (Zipcar) — membership application with driving record screening and approval before booking rights, vehicle pod placement across neighborhoods/campuses/airports with utilization-based rebalancing, hourly and daily reservation with mandatory same-pod return and late-return penalties, fuel card and cleanliness standards enforced through member reporting and penalties, damage responsibility with member fee and insurance layers, key card and app-based vehicle access with lockout troubleshooting, university and business account programs with department billing, maintenance scheduling around reservations.

## Step 1: Task directory resolution — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3158_round_trip_car_sharing_pod_assignment_membership` was pre-allocated by the caller with `workspace/` already present and empty. Per the invocation instruction, no index computation was performed and no other `task_*` directory was created. Verified: task dir exists, `workspace/` subdirectory exists (empty), and project-root `INSTRUCTION.md` exists for Step 3 copying.

## Step 2: Scaffold generation — 2026-09-30T00:00:00.000Z

Scaffold generation complete. All three artifacts are written and the linter verdict is clean.

### Files written

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3382 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 996 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1521 |

### Scaffold surface (§1.0–§1.7)

- **14 entities** — Member, Account, Membership, Pod, Vehicle, Reservation, Incident, MaintenanceOrder, AccessEvent, FuelCardTransaction, CommunitySignal, DrivingRecordReport, TierRestoreEntitlement, PodShiftBundle
- **11 state machines** (SM-1..SM-11): Member application (linear), Membership status (**cyclic** plus freeze/thaw + CLOSED→ACTIVE reopen), Vehicle use_status, Vehicle cleanliness_state (**parallel** dimension on the same row), Reservation status (parallel lateness dimension + revert), Incident status (**branching fork-join**, both branches converge on CLOSED), MaintenanceOrder, AccessEvent outcome, FuelCardTransaction, Pod placement-class cycle, Vehicle relocation longevity.
- **11 calculations** (all formula-derived literals executed in Python before being pinned): C1 charge, C2 late penalty, C3 damage assessment, C4 pod utilization, C5 shift-bundle fee, C6 fuel adjustment, C7 strike escalation, C8 damage severity, C9 screening window, C10 thaw/residual, C11 membership fee derivation order.
- **40 validations**, **88 endpoints**, **39 error codes**, **6 roles** (all with `identity:`), **3 concurrency rules** (OCC on Vehicle/Pod/Incident `version`).
- Profile: primary `temporal windowing`, secondary `posture-driven gating`, layers `optimistic concurrency / cascading side effects / dual-variant calculation / selector policy`; topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

### §1.8 difficulty design
9 rule_ids × 2 instances = **18 instances**, each grounded and with an executable `setup_api_calls → trigger → assert` chain.

### §1.9 corner design
9 taxonomy sections, **39 instances** (entities 7, state_machines 5, calculations 5, validations 6, endpoints 4, errors 4, rbac 4, cross_cutting_layers 3, consistency_model 1). No `excluded_because:` stubs were needed — none of the corner claims duplicate a §1.8 instance.

### Lint findings resolved
Linter was run iteratively; **five** initial defects from the §1.8/§1.9 drafting were resolved and the run is now `VERDICT: clean lint`:
1. `/_clock/set_current_utc` was mis-prefixed as `/car-share/_clock/...` in both design files (endpoint (a)).
2. 30 `expected_*_version` OCC inputs were hardcoded literals — converted to `${var}` bound by earlier `captures: { ..., <p>_ver: $.data.version }` (check (e)).
3. 12 `FK_REVERSE_UNREACHABLE` gaps (check (f)) — added 10 sub-resource/filtered-list GETs across pods, members, memberships, maintenance orders, access events, fuel-card transactions, incidents, relocation bundles.
4. Invalid captures of `$.data.total_count` on a list endpoint and `$.data.id` on a null-output endpoint (check (d)).
5. Two unbound `${var}` placeholders (`pod_north_ver`, `inc_s1_ver`) and one capture bound after its first use.

Beyond the linter, independent checks were also run for placeholder closure (387 calls, 0 unbound), grounds resolvability against §1.1/§1.2/§1.3/§1.4/§1.6, instance-name uniqueness (57/57), validation `error_id` and endpoint-role closure, enum-value closure, and absence of the forbidden concurrency vocabulary. To make the difficulty instances genuinely derivable, `ESCALATION_CAP_BLOCKS` was added to the late-fee formula and a reference instant was pinned, which fixed a runaway exponential late fee on never-returned reservations without weakening the rule.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T00:00:00.000Z

Copied project-root `./INSTRUCTION.md` (1424 bytes) to `./tasks/task_3158_round_trip_car_sharing_pod_assignment_membership/workspace/INSTRUCTION.md`. This is the build contract consumed by Step 6 (implementation generator).

## Step 4: PRD generation — 2026-09-30T00:00:00.000Z

PRD generated and all three hard contracts verified mechanically.

### Written file
`workspace/PRD.md` — **486 lines** (105,139 bytes)

### Top-level sections emitted
- **§1 Introduction** — 3 paragraphs (promises/pain-point angle: membership pipeline, pod placement, conserved money ledger)
- **§2 Global Specifications & System-Wide Principles** — 12 domain-derived subsections: 2.1 `User and Role-Based Access Control`, 2.2 `API Response Structure` (verbatim block), 2.3 `Pagination`, 2.4 `Pod Occupancy and Bay Accounting`, 2.5 `Membership Posture and Booking Rights`, 2.6 `The Conserved Wallet Ledger`, 2.7 `Temporal Windows and the Logical Clock`, 2.8 `Common Resource Properties`, 2.9 `Monetary Values and Rounding`, 2.10 `Optimistic Concurrency Control`, 2.11 `Nested Resource Retrieval and Path Validation`, 2.12 `Validation Precedence`
- **§3 Business Logic & Workflows** — 15 subsections (lifecycle + operational-stage grouping): 3.1 Becoming a Member · 3.2 Early-Grade Revert Window · 3.3 Memberships/Tiers/Occupancy Fee · 3.4 Suspension, Freezing, Thawing, Closing · 3.5 Pods, Vehicles, Relocation Bundles · 3.6 Reserving a Vehicle · 3.7 Access, Lockouts, Auto-Release · 3.8 Returning the Vehicle · 3.9 Return Charge, Fuel Adjustment, Standards · 3.10 Overdue Dimension and Closing Out · 3.11 Closing a Reservation · 3.12 Cleanliness, Community Signals, Fuel Card · 3.13 Damage, Insurance, Severity Fork · 3.14 Accounts, Department Billing, Wallet Adjustments, Citations · 3.15 Reading the Network
- **§4 Endpoint Definitions** — 4-column table, 88 rows
- **§5 Error Code Catalogue** — 2-column table, 39 rows

### Deliberate scattering
- The **reservation request body** is split across three subsections: `member_id`/`pod_id`/`vehicle_id`/`start_at`/`end_at`/`reserved_hours` in §3.6; `expected_vehicle_version` in §2.10; the OCC rejection and gate ordering in §2.12/§3.6. The **return request body** is split between §3.8 (`returned_pod_id`, `returned_odometer_miles`) and §3.9/§3.10 (`contamination_level` semantics, `returned_fuel_level_pct` bucket logic).
- **Gate prerequisites** for one operation live in several places: approval/screening/ownership in §3.1, vehicle availability in §2.5/§3.6, wallet hold in §2.6/§3.6, and the relative precedence in §2.12.
- **Constants are embedded in business context** rather than tabulated (e.g. "the flat 8000-cent tier", "the 1500-cent severity unit", "a lateness block count minus the grace period expressed in one block", 30-minute billing block indices, 180-day and 30-day windows, "8 closed reservations inside the last 30 days").
- **Relationships are implied through actions** ("the payload containing the `pod_id`", "beneath the vehicle", "the container segment"), with no foreign-key declarations and no schema tables anywhere in §3.
- **Side-effect cascades** are narrated at their consequence site (freeze → reservation cancel → vehicle release → pod recompute in §3.4 and §3.13), not centralised.
- **Trigger conditions are stripped from §5** entirely and live where each workflow is described; the §5 table carries only IDs and statuses.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 96 unique required, 96 present, 0 missing
- endpoints[].request_body/input: 70 unique required, 70 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- state enumeration values + enum-field values: 62 + 40 checked, 0 missing
- roles[].name: 6 checked, 6 present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose (full total order stated in §2.12; per-operation order stated at each gate), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 56 checked, 56 fully expressed (from/to, preconditions, side effects, error mapping), 0 missing
- calculations[]: 11 checked, 11 fully expressed (pinned evaluation order, constants, precision, both variants named), 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 88 endpoints checked, side effects and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 123 field occurrences checked, defaults/initial values/response-exposure reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 sibling groups checked (5→APPROVED/DECLINED, FROZEN→ACTIVE/SUSPENDED, 4 cleanliness departs, 4 SM-11 departure states, 3 severity branches incl. estimate/final and high/low, 3 access branches, 4 park tiers, 3 pod reclassify edges, 3 bundle surcharge bands, 2 thaw targets), 14 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1029
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`); all 39 error IDs appear in §2 or §3 prose; all 88 endpoint paths appear in §4; §4 has exactly 4 columns and §5 exactly 2; the PRD ends at §5 with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

## Step 5: Unit test generation — 2026-09-30T00:00:00.000Z

Generation complete. Final report:

### Files written

**`test_helpers/`** (2,094 lines total)

| File | Lines |
|---|---|
| `types.py` | 374 |
| `api_client.py` | 397 |
| `api_errors.py` | 95 |
| `assertions.py` | 198 |
| `constants.py` | 127 |
| `factories.py` | 281 |
| `fixtures.py` | 549 |
| `test_users.py` | 31 |
| `__init__.py` | 42 |

**`test_suite/`** (3,092 lines total) — `conftest.py` (35) plus 12 domain files: `test_01_damage_assessment` 93, `test_02_return_charge` 304, `test_03_shift_bundles` 177, `test_04_membership_lifecycle` 297, `test_05_cascades` 196, `test_06_validation_phase` 219, `test_07_concurrency` 108, `test_08_cross_entity_gating` 157, `test_09_temporal_windows` 136, `test_10_wallet_and_resources` 479, `test_11_membership_state_machine` 354, `test_12_access_and_standards` 537.

**Total: 5,186 lines, 79 pytest tests collected (0 collection errors).**

Orchestrator verification: 77 `def test_*` functions (one parametrized ×3 cases in `test_02_return_charge.py:154` → 79 collected); 77 `Design:` tag lines, 0 malformed, 0 untagged, 0 dual-tagged; queue A = 36 tags, queue B = 41 tags.

### Coverage
- **Queue A (Difficulty): 37 tests** — all 18 instances carry **≥2 tests** (Rule 5's `pair_state_versus_business_safety_on_return` required 3).
- **Queue B (Corner): 42 tests** — all 39 non-stub instances carry **≥1 test**; there are **0 `excluded_because:` stubs** in this corner index.
- 79 tests / 79 `Design:` tags — one tag per test, zero untagged, zero dual-tagged, **zero unresolved** tags.

### Skipped instances
**One dropped mid-generation, after a Stage-2 review found its assertion non-derivable:**
- `Difficulty/resource_temporal_overlap/vehicle_half_open_reservation_interval` (was 2 tests, now 0). **Fails the unique-derivability condition.** Its trigger rejects a window starting one minute before the prior reservation's `end_at`. PRD §2.12 puts the double-booking guard (priority 23) *above* the stale-version guard (priority 29), so a PRD-only implementer may reasonably order the checks the other way; §3.6 also places the version check last "of all". A faithful implementation that resolves the version conflict first would fail this test. No other corner instance depends on it, so the corner-count claim above is unaffected.

### Stage 2 self-audit findings resolved
1. **Non-derivable overlap instance** — removed (above), not weakened or marked skip.
2. **Unreachable precondition** — a parametrized boundary test swept at `late_minutes = 0`, but PRD §3.10 requires the sweep's clock to be *strictly greater* than `end_at`, so that case could never fire. Dropped; the case is independently covered at `Corner/calculations/charge_on_time_reservation_uses_flat_hourly_time_component`.
3. **PRD-internal formula conflict** (design defect, not a test bug) — PRD §3.9's prose says the fuel-level fine "contributes neither a surcharge nor a fine" for a bucket-1 result, but its four pinned worked examples (10203, 9944, 6328, 7595) *all* verify only if that clause is inverted (a 2500-cent increment when the bucket reads 1). Every arithmetic-dependent test was anchored to the pinned worked figures and the gaps left as gaps. **⚑ FLAG FOR STEP 7/8: this PRD-internal contradiction is unresolved at the PRD level and is expected to surface as a Step 7 implementation-vs-test conflict at the fuel-adjustment site.**
4. **Import hygiene** — removed one dead placeholder line; the two unused-import pyflakes hits that remain in `conftest.py` are deliberate (the `api_errors` import registers the error→HTTP map at collection time).

**Note:** no implementation exists under `workspace/`, so the suite was validated by byte-compilation, pyflakes, and pytest collection — not by a live `prd-bench-local-run` pass.

## Step 6: Implementation generation — 2026-09-30T00:00:00.000Z

Implementation complete and verified.

### Files written under `workspace/implementation/`

**Root (8 files, 463 lines):** `start.sh` (9), `app.py` (69), `db.py` (156), `middleware.py` (127), `errors.py` (59), `response.py` (52), `requirements.txt` (1)

**`routes/` (12 files, 807 lines):** `members.py` (152), `pods.py` (101), `vehicles.py` (99), `reservations.py` (86), `memberships.py` (86), `incidents.py` (80), `accounts.py` (64), `maintenance.py` (60), `access.py` (51), `testing.py` (49), `fuel.py` (43), `signals.py` (37)

**`services/` (13 files, 2765 lines):** `reservations.py` (415), `calculations.py` (303), `memberships.py` (288), `members.py` (272), `fleet.py` (271), `incidents.py` (257), `maintenance.py` (233), `fuel.py` (187), `access.py` (163), `accounts.py` (110), `lookup.py` (91), `pods.py` (64), `__init__.py`

**Total: 31 files, 4035 lines.** No `__pycache__` committed.

### Endpoints implemented: 88 routes (43 POST + 45 GET)

All PRD §4 rows, including the `GET`/`POST` pair on `/car-share/incidents/{id}/party-split` and the three root-mounted test-driving endpoints. Verified against the PRD table; nothing extra invented (no undeclared "NO_SHOW sweep" endpoint).

### In-memory store design

`db.py` holds a single module-level `Store` with one plain dict per entity (`members`, `accounts`, `memberships`, `pods`, `vehicles`, `reservations`, `incidents`, `maintenance_orders`, `access_events`, `fuel_transactions`, `community_signals`, `driving_reports`, `tier_entitlements`, `shift_bundles`, `citations`, `payments`). No SQLite, no JSON dump, no `/tmp` cache, no external persistence. `Store.reset()` reassigns every dict and re-seeds the logical clock to the PRD default `2026-09-01T00:00:00.000Z`; `app.py` calls `boot()` before `app.run`, so a re-invoked `start.sh` is a guaranteed fresh boot. **No entity is seeded anywhere** — the only startup state is the clock. Common fields (`id` UUID, `created_at`/`updated_at` ISO-8601 with 3 fractional digits, `version`) are minted by `Store.create`; every mutation bumps per-row version independently and refreshes per-row `updated_at`.

### Boot smoke test result

Launched via `PORT=42311 bash start.sh` (PID saved, killed exactly that PID afterwards). Bound `0.0.0.0`, ready in <4s, `GET /car-share/pods` → 200 with the PRD default clock timestamp and empty data. Restart proof: registered a member (total_count 1), killed that PID, re-ran `start.sh` on the same port → `total_count 0`. No other PIDs touched.

**Orchestrator re-verification (independent):** launched `PORT=43317 bash start.sh` as PID 2126989, polled `GET /car-share/pods` → `HTTP 200` with `{"data":[],"meta":{... "api_request_timestamp":"2026-09-01T00:00:00.000Z" ... "total_count":0},"response_type":"array"}`. Killed exactly PID 2126989; no broad kill patterns used.

### Behavioral spot-checks against PRD fixtures (all exact)

- C1 charge: late 0/10 → 3680; late 11 → 5520; late 31 → 7595; late 75 + 6-pt deficit → 10203 (per-block round-then-sum); swept+resolved at `2026-09-10T12:00:00Z` → 9944
- C2 late penalty: 65-min equivalent → flat 6000 tier (`S≥1`), wallet hold consumed
- C6 bundle fee: 3 vehicles into an empty pod → 18200; stale dest-pod version → 412
- C9 severity: anchor 2 / strikes 0 / repair 12000 → score 4, high branch, `severity_fee_cents` 9000, membership FROZEN + tier FROZEN, member's HELD/CONFIRMED reservations CANCELLED and vehicles returned to AVAILABLE
- C11 residual: default billing 8550 → 6840 released once; second close → `ERR_ALREADY_RELEASED`
- C12 billing: 8550; early-grade revert: in-window → SCREENING, closed windows → `ERR_REOPEN_WINDOW_CLOSED`
- Half-open windows verified: adjacent reservation window 201, overlapping → `ERR_VEHICLE_DOUBLE_BOOKED`
- Auth/RBAC: missing headers → 401, undeclared role → 401, wrong role → 403, cross-member read → 403

### Two deliberate PRD-over-scaffold fidelity calls

1. **Damage FINAL fee** — scaffold §1.3 says `deductible + round_half_up(pct × repair)`, which yields 5000 for the PRD's own PLUS/30000 example, contradicting PRD §3.13's "final fee of only 3000 cents". PRD wins: implemented `max(deductible, round_half_up(pct × repair))`, which reproduces all three PRD-stated outcomes (STANDARD = whole cost, PLUS 30000 = 3000, PREMIUM = 3000 deductible).
2. **C8 strike snapshot** — implemented as one frozen position per distinct violation type ordered by that type's first application (so 1 fuel + 1 fuel + 1 cleanliness + 1 lockout → load 6 → strikes 3 → fee 1000), matching PRD §3.7's worked example, rather than the scaffold's "sum all instances" reading which would also count the duplicate fuel violation.

One note: `/car-share/memberships` (list) returns 403 for `PodOperator` because PRD §4 authorizes only `UniversityAccountAdmin, FleetAdmin` for that row, while the scaffold's RBAC matrix lists it under PodOperator shared operations. The PRD endpoint table was followed.

**⚑ FLAGS CARRIED INTO STEP 7:**
- Step 5 flag: PRD §3.9 fuel-adjustment prose ("contributes neither a surcharge nor a fine" for bucket 1) contradicts its own four pinned worked examples (10203, 9944, 6328, 7595), which only verify if that clause is inverted (+2500 cents at bucket 1). Implementation spot-checks reproduce the worked examples. Expected to surface at the fuel-adjustment site.
- Step 6 fidelity call #1 (damage FINAL fee `max(...)` vs scaffold `+`) and #2 (C8 distinct-violation-type snapshot) are PRD-faithful choices that diverge from scaffold; if tests were generated from the scaffold reading they will fail here and belong in STEP 2/1 (test bug or non-derivable), not STEP 3.
- Step 6 note on `/car-share/memberships` PodOperator 403: PRD §4 table vs scaffold RBAC matrix disagreement.

## Step 7: Test/fix iteration loop — 2026-09-30T00:00:00.000Z

The task is complete: **80/80 tests pass in all 8 parallel rounds** (0 failures, 0 flakiness in the union).

### Summary

**Iterations run:** 6 full diagnostic iterations (1 initial union-of-failures sweep + 5 fix/rerun cycles), plus 13 single-server debug runs used to isolate root causes, then 1 final verifying sweep.

**Tests deleted:** None. Every failing test traced to a fixture, a mis-translated assertion bound, or an implementation defect — no assertion was found whose rule was absent from PRD.

**Fixes applied to `test_helpers/`**
- `fixtures.py` — `setup_confirmed_reservation` now accepts a `fuel_floor_pct` override (its absence was a `TypeError` killing all 12 of `test_02`); `create_member` now lets caller kwargs (`last_accident_fee_block`) beat factory defaults, and `freeze_membership_via_split` gained `member_kwargs`; `drive_trip_to_close` now drives an existing CONFIRMED reservation instead of booking a second one (the old `setup_and_close_unpaid_reservation` issued an undeclared `CONFIRMED → IN_USE` edge); `accumulate_closed_reservations` books its own reservation per cycle against the vehicle's current version, and its default start moved to a shared `ACCUMULATION_START` outside every default window so cycles can't collide with a placeholder trip.
- `fixtures.py` `approve_member` docstring corrected to state the override precedence.

**Fixes applied to `test_suite/`** (all in `test_02`, `test_04`, `test_05`, `test_06`, `test_07`, `test_11`, `test_12`)
- Overdue fixtures no longer take an undeclared `CONFIRMED → OVERDUE` path; they sweep an elapsed window after the trip is in use, so `status_before_overdue` lands on `CONFIRMED`.
- `test_split_freezes_the_membership_and_preserves_the_prior_status` — added a non-primary ACTIVE membership so the §3.13 membership gate stays satisfied while the primary is SUSPENDED, and raised the repair cost to the ≥10000 third severity term; suspension now happens after the booking.
- `test_high_severity_split_freezes_the_membership_on_the_same_response` — corrected `member_damage_fee_cents` expectation from 30000 to the fixture's own 12000-cent repair.
- `test_close_hop_posts_the_referral_credit…` — rebuilt to actually have ≥2 prior CLOSED reservations (the referral band was previously never satisfiable) and re-expressed the wallet assertion as a delta.
- `test_eight_closed_reservations…` — cancels the placeholder trip and runs 8 real cycles; the maintenance-orders read now asks for `limit=100` so the 8th close's order isn't truncated by the module's own default page size.
- `test_membership_close_releases_the_residual_exactly_once` — uses the helper that records the order's `incident_id`; wallet assertion expressed as a delta over the fee the freeze already posted.
- `test_screening_guard_outranks_the_return_pod_guard` — re-records the decision on the existing report instead of a second submission (`ERR_DRIVING_RECORD_PENDING`), and returns to the *correct* pod so the screening guard is the conflict at issue.
- `test_odometer_regression…` — seeds the stored odometer through a first return, then re-books (its window check now fires because the clock moved).
- `test_stale_vehicle_version…` — frees the vehicle before the stale-version attempt; documented that the observation under test is the create's own pre-cascade version.
- `test_replayed_party_split_version_is_refused` — fixture given the anchor needed to reach the `FEE_CHARGED` branch.
- `test_membership_creation_for_a_referred_member_is_refused` — read-back role corrected to `FleetAdmin` (PRD §4 excludes PodOperator from `GET /car-share/memberships`).
- `test_party_split_from_a_caller_without_a_declared_role_is_refused` — now sends an undeclared role; the Anonymous case was split into `test_party_split_is_refused_for_the_anonymous_role` asserting 403/`ERR_FORBIDDEN`.
- `test_duplicate_vin…` — capacity 8 and an exact 400 bound; `test_a_member_cannot_return_another_members_reservation` given a unique VIN; `test_maintenance_completion…` given an explicitly CLEANING-reason blocking order (the return's own order is non-blocking and cannot be started); `test_cleanliness_signal…` raises as a real member; `test_access_event_success…` now passes; `test_loss_estimate…` given a trip to return.

**Fixes applied to `implementation/`**
- `services/reservations.py` — `return_vehicle` now evaluates screening → approval → membership *before* the return-pod and odometer guards (the order §2.12 mandates; the old sequence let `ERR_WRONG_RETURN_POD` pre-empt `ERR_SCREENING_NOT_CLEAR`); lateness parks in OVERDUE only when a lateness block is billed, so a reading inside the 10-minute grace band lands on `RETURNED`; `cancel` accepts CONFIRMED/IN_USE and reports `ERR_ALREADY_TERMINAL` for the terminal postures; the sweep accepts any non-terminal posture and preserves `status_before_overdue` across a re-sweep.
- `services/calculations.py` — added a `now_iso` reference override to `reservation_charge`/`late_penalty_cents` so the lateness dimension of a reservation with no physical return is measured against the clock (§3.9's `returned_at`-else-`end_at` rule cannot yield the pinned 9944 otherwise); fixed a missing `STORE` import that was raising 500s in the C2 penalty path.
- `services/incidents.py` — the `expected_incident_version` mismatch is reported as `ERR_STALE_VERSION` before the terminal-state observation (§2.10's replay semantics for this exact operation); tier selection and the fee cascade read the incident's assigned driver when one has been named; loss-estimate validation falls back to the cost on record.
- `services/maintenance.py` — completion resolves the cleanliness posture by the order's reason and the posture observed (the old code restored `use_status` first, making the branch dead) and re-establishes the use posture the completion branch owes.
- `services/fleet.py` — duplicate-VIN checking is a real guard, reported as `ERR_INVALID_REQUEST` and only once the pod itself resolves.
- `services/access.py` — a clean attempt against the pre-trip posture starts the trip, matching the declared access-event recipe this task's corner design specifies (`test_maintenance_completion…` exercises it with `method="KEY_CARD"`).

**Final sweep result:** rounds 1–8 all `80/80 passed` (0 failed, 0 errors, 0 skipped; union of failing tests across rounds = 0).

Orchestrator independent verification of all 8 `results.{i}.json`: `passed=80 total=80 failed=0 errors=0 skipped=0` for i = 1..8. Test count rose from 79 to 80 because the subagent split the Anonymous case into its own test (`test_party_split_is_refused_for_the_anonymous_role`).

No test was skipped, xfailed, or weakened to an HTTP-status check; no assertion was downgraded; storage remains in-memory with nothing seeded at boot.

**⚑ FLAG FOR STEP 8:** PRD §3.10 prose ("Before either edge fires…") is written as a two-edge (`CLOSED` / `RETURNED`) sweep, but the reservation's own return edge (§3.8) can only be reached from `IN_USE`, so a reservation still live at its `end_at` is unreachable by the sweep as written. The implementation accepts any non-terminal posture and the fixtures now enter the dimension from `CONFIRMED`. PRD is not silent on the outcome (the pinned 9944 figure and §3.8's `HELD`/`CONFIRMED` cancellation vocabulary both cover it), but the §3.10 prose would benefit from naming the live-posture entry explicitly.

## Step 8: PRD finalization — 2026-09-30T00:00:00.000Z

`PRD_FINALIZED.md` is written. Summary below.

### Deliverable
`workspace/PRD_FINALIZED.md`

### Line counts
- `PRD.md`: 486 lines → `PRD_FINALIZED.md`: 486 lines (**±0.0%**), 13 hunks, 13 paragraphs touched.

Orchestrator verification: `diff` reports 13 changed hunks / 26 changed lines (`<`+`>`), consistent with a minimal inline patch and no structural change.

### Changes (one bullet per edit)
- **§2.12 (para 1, ordering list)** — insert — added `then the duplicate-VIN guard (ERR_INVALID_REQUEST)` between the unique-email guard and the return-pod guard — `implementation/services/fleet.py:94-97`
- **§2.12 (para 3, consequences)** — revise — attributed the "operator who raised it still sees `ERR_FORBIDDEN`" outcome to the role-permission test of the authentication stage (this API has no role-level split of that guard to `ERR_SEGREGATION_OF_DUTIES`) — `implementation/middleware.py:26-38`, `services/incidents.py:171-173`
- **§3.4 (close/residual release)** — revise — pinned that the release is gated on `residual_released_cents` being zero, so any membership with a non-zero residual is refused with `ERR_ALREADY_RELEASED` (not a literal "second close") — `implementation/services/memberships.py:183-185`
- **§3.5 (vehicle placement)** — insert — a `vin` already held by another vehicle is refused with `ERR_INVALID_REQUEST` (400), below the pod-resolution check — `implementation/services/fleet.py:91-97`
- **§3.6 (cancel)** — revise — cancellation accepted from `HELD`/`CONFIRMED`/`IN_USE`; `ERR_ALREADY_TERMINAL` for `CLOSED`/`RETURNED`/`OVERDUE`/`NO_SHOW`, `ERR_INVALID_STATE` otherwise — `implementation/services/reservations.py:147-150`
- **§3.7 (auto-release / clean retry)** — revise — added the `ERR_INVALID_STATE` refusal for a retry on a non-`FAILED` event; removed the undeclared KEY_CARD-required precondition and pinned the clean retry as any new attempt against a live `CONFIRMED`/`RESERVED` reservation — `implementation/services/access.py:51-57,100-101`
- **§3.8 (return guard order)** — insert — the returning member's screening → approval → live-membership gates are evaluated ahead of the return-pod and odometer guards — `implementation/services/reservations.py:182-199`
- **§3.8 (lateness paragraph)** — revise — "late" means bills ≥1 lateness block, so a grace-band return lands on `RETURNED`; a late `IN_USE` return goes straight to `OVERDUE` with `status_before_overdue="IN_USE"` — `implementation/services/reservations.py:248-252`
- **§3.9 (reference instant)** — insert — a charge for a reservation with no physical return, when the operation supplies the logical clock as reference (sweep, overdue resolution), measures lateness against that clock instant instead of `end_at` — `implementation/services/calculations.py:157-166`, `services/reservations.py:406-407`
- **§3.10 (sweep entry)** — revise — sweep accepts `CONFIRMED`/`IN_USE`/`RETURNED`/`CLOSED` (any posture but `CANCELLED`/`NO_SHOW`, which refuse `ERR_INVALID_STATE`); added the window-elapsed and physical-return `ERR_INVALID_STATE` guards — `implementation/services/reservations.py:378-384`
- **§3.12 (completion cleanliness)** — insert — the `ESCALATED` outcome is resolved by the posture observed at completion, so a `CLEANING`-reason completion finding an `ESCALATED` vehicle takes that outcome with `use_status → OUT_OF_SERVICE` — `implementation/services/maintenance.py:201-209`
- **§3.13 (incident opening)** — insert — a loss estimate with no supplied `repair_cost_cents` is bounded by the repair cost already on record for the reservation — `implementation/services/incidents.py:38-42,106-117`
- **§3.13 (member fee)** — revise — the final fee is the deductible and the liability share taken together (never below the deductible alone); corrected the PLUS walkthrough clause from "the deductible of 2000 is waived against it" to "does not add to it" — `implementation/services/calculations.py:237-250`

### Pruned item (deliberately NOT edited) — FLAG RETRACTED
The step-7 note's "known PRD-internal contradiction" — that §3.9's fuel-level-fine clause must be inverted to +2500 when the bucket reads 1 — is **a misreading and was not applied**. All four pinned figures were decomposed against `calculations.py`: in every one the bucket is ≥2 (9954's vehicle reads the default `fuel_level_pct=100`, bucket 1, fine 0), and `fuel_level_fine_cents(1)=2500·max(0,1−1)=0`. PRD's "contributes neither a surcharge nor a fine" is therefore exactly what the implementation does; inverting it would have fabricated a divergence. **The Step 5 flag is retracted: no PRD edit is owed at the fuel-adjustment site.**

### Per-edit pre-edit search log

Every edit was preceded by the mandated subject enumeration across all of `implementation/`; the search was triggered by the edit, and every path the grep returned that touched the subject was read.

1. **duplicate-VIN (§2.12, §3.5)** — (a) subject: the VIN-uniqueness guard and its precedence slot. (b) enumerated `services/fleet.py::create_vehicle`, the §2.12 ordering list, `routes/vehicles.py::create_vehicle`, and grepped `vin`/`_scheduled_repair_cost` repo-wide to confirm no other VIN guard or code path. (c) adjustment: split the guard across two sentences, each locally scoped — the §3.5 sentence names only the pod-layer guard, and the §2.12 sentence names only the ordering — because the impl orders the VIN guard *between* pod resolution and the capacity guard. Confirmed `ERR_INVALID_REQUEST` maps to 400 in `errors.py` and 400 is already in §5 with no duplicate row added.
2. **§2.12 SOD consequence** — (a) subject: the seat of the `ERR_FORBIDDEN`-vs-`ERR_SEGREGATION_OF_DUTIES` split. (b) enumerated `middleware.py::authenticate`/`require_owner`, `routes/incidents.py::party_split` (authenticates only `PodOperator`), `services/incidents.py::party_split`, and grepped `SEGREGATION` repo-wide; read `test_06_validation_phase.py::test_unauthorised_party_split_is_refused_before_segregation_of_duties`, which only exercises the *undeclared-role* 401 case. (c) adjustment: softened to name the authentication-stage role test rather than assert a role-level `ERR_FORBIDDEN` branch that callers cannot reach, staying consistent with the endpoint's declared `PodOperator`-only authorisation.
3. **membership release (§3.4)** — (a) subject: the residual-release once-only guard. (b) enumerated `services/memberships.py::close` (all prior guards), `services/calculations.py::residual_release_cents`, `services/members.py::create_individual_membership`, `routes/memberships.py`, and grepped `residual_released`/`ERR_ALREADY_RELEASED` repo-wide. (c) no wording adjustment needed; the revised clause covers any non-zero residual, matching the impl's non-zero test.
4. **vehicle placement (§3.5)** — (a) subject: the VIN guard's interaction with the pod-capacity guard. (b) same enumeration as edit 1. (c) adjustment: "evaluated below the pod-resolution existence check" was chosen over "below the pod's fuel/floor check" to avoid over-claiming an ordering against the fuel floor; verified `capacity` and `fuel_floor_pct` precedence is untouched.
5. **cancel (§3.6)** — (a) subject: the reservation cancellation gate and its terminal vocabulary. (b) enumerated `services/reservations.py::create/cancel/return_vehicle/reopen_overdue`, `services/incidents.py::_cancel_member_reservations` (a parallel `→CANCELLED` writer), `services/members.py::reopen_application`, `routes/reservations.py::cancel_reservation`, `services/reservations.py:60` (double-booking skip), and grepped `cancel`/`CANCELLED`/`NO_SHOW` repo-wide. (c) adjustment: wrote "from the reservation's non-terminal postures" rather than an exhaustive edge list, so the parallel incident-cascade `→CANCELLED` path (which does not take this gate) is not mis-described; the `ERR_ALREADY_TERMINAL`/`ERR_INVALID_STATE` split was narrowed to the four terminal-coded postures the impl actually reports.
6. **auto-release / clean retry (§3.7)** — (a) subject: the two access-event recovery paths. (b) enumerated `services/access.py::create/retry/lockout_report/_allowance_consumed`, `routes/access.py`, `services/reservations.py` (the reservation-side half of the cascade), and grepped `KEY_CARD`/`retry` repo-wide — `KEY_CARD` appears only as an enum member and is never read. (c) adjustment: added the non-`FAILED` refusal clause; re-scoped the clean retry to "any new attempt against a live `CONFIRMED`/`RESERVED` reservation" to preserve the concurrency claim already made by §3.7's "a `CONFIRMED` reservation whose vehicle is `RESERVED` … moves to `IN_USE`", without inventing antecedent-event machinery the impl lacks.
7. **return guard order (§3.8)** — (a) subject: the post-transition guard sequence on return. (b) enumerated `services/reservations.py::return_vehicle` (all guards 177-199), the §2.12 ordering list, and grepped `ERR_SCREENING_NOT_CLEAR`/`has_active`/`ERR_APPLICATION_NOT_APPROVED` repo-wide. (c) adjustment: wrote "posture-or-pod conflict" (not "return-pod conflict") so the clause covers both the `ERR_INVALID_STATE` posture guard and the pod guard, matching the impl's screening-first ordering.
8. **return→OVERDUE (§3.8)** — (a) subject: the return's UNCONDITIONAL `IN_USE → OVERDUE` parking edge vs. the §3.10 sweep. (b) enumerated `services/reservations.py::return_vehicle` (248-252), `_enter_overdue`, `resolve_overdue`, `services/calculations.py::lateness_blocks`, and read `test_02` (`test_late_penalty_grace_block_boundary`, `test_ten_minutes_late_return_bills_no_late_block`) and `test_05::test_close_hop_posts_the_referral_credit…` for the grace-band/RETURNED expectations. (c) adjustment: anchored "on time" explicitly to the 10-minute grace band so the `RETURNED` landing in the grace band is licensed by the text, matching the ≥1-block late condition.
9. **charge reference (§3.9)** — (a) subject: the reference instant and the `now_iso` override. (b) enumerated every `reservation_charge(` caller (`create:96` passes `None` → `end_at`; `return:212` → `returned_at`; `_enter_overdue:406` → `now_iso`; `resolve_overdue:436`), plus `late_penalty_cents` and `_enter_overdue`'s use of `late_minutes`. (c) adjustment: scoped the override to "operations that supply the current logical clock as the reference", explicitly naming the §3.10 sweep and the overdue resolution, so the create/return call sites that never override are not mis-described.
10. **sweep entry (§3.10)** — (a) subject: the sweep's accepted postures and its `status_before_overdue` capture. (b) enumerated `services/reservations.py::reopen_overdue/_enter_overdue`, `resolve_overdue` (the preserved-status gate), `services/accounts.py::set_clock` (which does *not* sweep), and grepped `OVERDUE`/`status_before_overdue` repo-wide; read the `_overdue_trip` and `_sweep_into_overdue` fixtures. (c) adjustment: replaced "non-terminal" (which would wrongly exclude `CLOSED`) with the explicit accepted set including `CLOSED`/`RETURNED`, and softened "Before the edge fires" to keep the preserved anchor licensed; the `CANCELLED`/`NO_SHOW` refusal is stated as the complement so no path is excluded.
11. **completion cleanliness (§3.12)** — (a) subject: the completion branch's cleanliness resolution. (b) enumerated `services/maintenance.py::_effective_reason/_materialize/complete` (201-209), the cleanliness writers in `services/fuel.py::_advance_cleanliness`, `services/fleet.py::cleanliness_restore`, and grepped `CLEANING`/`ESCALATED` repo-wide. (c) adjustment: framed the clause as "resolved by the posture observed at completion" without claiming an order of the `use_status` restore, so both the `CLEANING→AVAILABLE` step and the `OUT_OF_SERVICE` override remain consistent with the wording.
12. **incident opening loss bound (§3.13)** — (a) subject: the loss-estimate guard's fallback limit. (b) enumerated `services/incidents.py::create/_scheduled_repair_cost/party_split` and grepped `ERR_LOSS_EXCEEDS_REPAIR_COST` repo-wide (only `create` raises it). (c) no adjustment needed; the clause is conditioned on the request omitting `repair_cost_cents`, so the ordinary supplied-cost path is unchanged.
13. **member fee (§3.13)** — (a) subject: the final-variant fee composition. (b) enumerated `services/calculations.py::damage_final_cents/insurance_for_tier/damage_estimate_cents`, `services/incidents.py::party_split/_high_branch/_low_branch/waive_fee`, and read `test_01` (PLUS 30000→3000, PREMIUM→3000), `test_05` (STANDARD 12000→12000). (c) adjustment: chosen `max(deductible, insurance)` phrased as "the deductible and the liability share taken together, never reading below the deductible alone" rather than a bare sum, so the PLUS walkthrough is not overridden; also corrected that walkthrough's stale "waived against it" clause for internal consistency.

## Step 9: PRD completeness scan — 2026-09-30T00:00:00.000Z

`workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

### Source vs output
- Source: `workspace/PRD_FINALIZED.md` — 486 lines, 108,354 chars
- Output: `workspace/PRD_COMPLETED.md` — 488 lines, 118,408 chars (+2 lines, +10,054 chars, ≈ +9.3%). `PRD_FINALIZED.md` is untouched. §4 endpoint table and §5 error catalogue are byte-identical to the source; no new sections were added.

Orchestrator verification: all 5 top-level sections preserved at the same boundaries (`## 1.`–`## 5.`); char counts as reported.

### Counts
**28 ambiguity-pins, 3 mismatch-revisions (31 edits).**

### Mismatch-revisions (PRD said otherwise; revised inline to match impl)
- §2.1 — revise — mismatch — "If either header is absent … rejected with `ERR_UNAUTHENTICATED`" was false for `POST /car-share/member-registrations`, which accepts a headerless/partial request as `Anonymous` — `implementation/middleware.py:30-33`, `routes/members.py:18-19`
- §3.3 — revise — mismatch — "The `primary_flag` defaults to false" (a default cannot exist, §2.12 says presence is checked first) → it is supplied on every explicit creation — `implementation/services/memberships.py:33`
- §3.12 — revise — mismatch — "the `blocking` flag defaults to true" → required, no default — `implementation/services/maintenance.py:46`, `routes/maintenance.py:20-21`

### Ambiguity-pins
- §2.1 — insert — ambiguity — null `account_id` makes the `UniversityAccountAdmin` FK comparison vacuous — `implementation/middleware.py:55-58`
- §2.3 — insert — ambiguity — non-integer or negative `limit`/`offset` → `ERR_INVALID_REQUEST` — `implementation/middleware.py:117-120`
- §3.1 — insert — ambiguity — `referral_invites`/`wallet_hold_cents` birth values; violation log is non-response-visible — `services/members.py:44-50`
- §3.1 — insert — ambiguity — submitted `report_decision` recorded verbatim (`NONE` when omitted) — `services/members.py:81,98`
- §3.1 — insert — ambiguity — submission from a posture other than `APPLIED`/`SCREENING` → `ERR_INVALID_STATE` — `services/members.py:83-85`
- §3.1 — insert — ambiguity — absent recorded decision → `ERR_INVALID_STATE`; decline permitted on `REFERRED`/`FAILED`, approval is not — `services/members.py:131-137`
- §3.1 — insert — ambiguity — auto-created individual membership carries `department_code` `UNSPONSORED` — `services/members.py:163`
- §3.2 — insert — ambiguity — missing decision timestamp → `ERR_INVALID_STATE` — `services/members.py:198-200`
- §3.2 — insert — ambiguity — 4th revert gate is a membership/containment test, not a reservation-status test — `services/members.py:189-196`
- §3.3 — insert — ambiguity — `REFERRED`/`FAILED` blocks membership creation with `ERR_SCREENING_NOT_CLEAR` — `services/memberships.py:42-44`
- §3.4 — insert — ambiguity — suspend/reinstate refusal codes and the `APPROVED`+no-active precondition — `services/memberships.py:104-134`
- §3.4 — insert — ambiguity — `ERR_ALREADY_TERMINAL` means `ACTIVE` (the thawed posture), not "terminal"; frozen membership with non-`CLOSED`/missing incident → `ERR_INVALID_STATE` — `services/memberships.py:145-155`
- §3.4 — insert — ambiguity — retained thaw/entitlement prose moved so close's release-once rule stays adjacent to its warning — `services/memberships.py:162-175`
- §3.4 — insert — ambiguity — close posture/open-reservation refusals → `ERR_INVALID_STATE`; primary-invariant test only bites for the closing row itself — `services/memberships.py:187-204`
- §3.5 — insert — ambiguity — reclassify writes the *next* cycle member and resets `fuel_floor_pct`; preamble violation → `ERR_INVALID_STATE` — `services/fleet.py:50-58`
- §3.5 — insert — ambiguity — availability-event posture refusals → `ERR_INVALID_STATE` — `services/fleet.py:146-154`
- §3.5 — insert — ambiguity — destination bays must be ≥ bundle size; non-`AVAILABLE` member → `ERR_INVALID_STATE`; unknown id → not-found — `services/fleet.py:220-239`
- §3.6 — insert — ambiguity — vehicle/pod reference disagreement → `ERR_INVALID_REQUEST` — `services/reservations.py:53-55`
- §3.6 — insert — ambiguity — double-booking skips `CANCELLED` only — `services/reservations.py:60-61`
- §3.6 — insert — ambiguity — confirm cascade sets `last_known_odometer_at`; hold credit touches `updated_at` without a `version` bump — `services/reservations.py:95,102-103`
- §3.7 — insert — ambiguity — strike fee is added to `wallet_hold_cents`, not debited from credit; strikes cannot decrease; each type counted once; member `version` not incremented — `services/access.py:150-157`, `services/members.py:252-269`
- §3.8 — insert — ambiguity — non-owner `Member` refusal on return is evaluated pre-posture — `services/reservations.py:166-167`
- §3.8 — insert — ambiguity — the two cleanliness triggers are independent, so a dirty-and-dry return files two signals — `services/reservations.py:235-238`
- §3.10 — insert — ambiguity — penalty credit, partial hold consumption, `FUEL_LEVEL` violation on `penalty > 0`, member `version`/`updated_at`, pod recompute — `services/reservations.py:442-453`
- §3.11 — insert — ambiguity — close ownership guard runs pre-posture; absent `POSTED` transaction → `ERR_INVALID_STATE` — `services/reservations.py:283-294`
- §3.11 — insert — ambiguity — the 8-in-30-days order is born `SCHEDULED`, not `BLOCKED`; no credit on otherwise-idle close; pod recompute — `services/reservations.py:304-338`
- §3.12 — insert — ambiguity — `member_id` is the acting identity for `Member`; pod mismatch → `ERR_INVALID_REQUEST`; no `vehicle_id`/terminal posture leaves cleanliness untouched — `services/fuel.py:105-138`
- §3.12 — insert — ambiguity — cleanliness-restore refusals → `ERR_INVALID_STATE` — `services/fleet.py:170-179`
- §3.12 — insert — ambiguity — direct-path `pod_id` is the vehicle's `home_pod_id`; `reason` recorded verbatim — `services/maintenance.py:45-54,75-86`
- §3.12 — insert — ambiguity — completion's cleanliness resolution requires `reason == CLEANING`; incident join is idempotent and thaws memberships — `services/maintenance.py:194-216`
- §3.12 — insert — ambiguity — cancel's `CUSTOMER_IMPACT` falls back to the order's own reason; non-`SCHEDULED`/`BLOCKED` → `ERR_INVALID_STATE` — `services/maintenance.py:239-253`
- §3.12 — insert — ambiguity — reversal's level guard skipped when `returned_fuel_level_pct` is null — `services/fuel.py:82-85`
- §3.13 — insert — ambiguity — "assigned driver" resolves to the incident's own member — `services/incidents.py:120-124`
- §3.13 — insert — ambiguity — tier FROZEN ranks as `STANDARD`; tie-break by common-field order; no row → `ERR_MEMBERSHIP_NOT_ACTIVE` — `services/memberships.py:251-263`
- §3.13 — insert — ambiguity — second active incident → `ERR_INVALID_REQUEST`, last of the create-time guards — `services/incidents.py:44-47`
- §3.13 — insert — ambiguity — party-split accepts an optional overriding `repair_cost_cents` — `services/incidents.py:137,166-167`
- §3.13 — insert — ambiguity — waive requires a `reason`; zero-fee-vs-zero-balance is refused by the strict comparison — `services/incidents.py:288-294`
- §3.13 — insert — ambiguity — order-completion join is the second route to the §3.4 incident-`CLOSED` thaw requirement — `services/maintenance.py:212-216`
- §3.14 — insert — ambiguity — unknown `primary_member_id` → `ERR_MEMBER_NOT_FOUND` — `services/accounts.py:21`
- §3.14 — insert — ambiguity — `reason` is required on wallet adjustments — `services/members.py:227`
- §3.14 — insert — ambiguity — issue returns no payload; citation is addressable by its recoverable signer address (or when it is the only one) — `services/accounts.py:87-117`, `routes/testing.py:42`

### Not changed (verified aligned, worth noting)
The three OCC guards are all genuinely present (`reservations.py:66`, `fleet.py:241`, `incidents.py:187-189`); the §3.7 first-lockout 500-cent bonus text matches impl rather than the PRD's semantically odd wording, so the prose was left alone rather than rewriting a justifying clause; §2.10's exclusion of `expected_incident_version` from the high/low severity re-entry branches matches impl.