## Step 1: Create task directory — 2026-09-05T13:04:31.933609162Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2896_guest_ranch_all_inclusive_resort_operations and its workspace/ subdirectory. Index 2896 pre-assigned by the orchestrator prompt; no scan of ./tasks/ performed.

## Step 2: Generate scaffold (subagent) — 2026-09-05T14:38:14.126193957Z

All three scaffold artifacts for task 2896 are complete, YAML-valid, and lint-clean.

**Files** — `/home/ubuntu/github/CodingPRD/tasks/task_2896_guest_ranch_all_inclusive_resort_operations/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3520 | 168,553 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1844 | 118,763 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4818 | 301,859 |

**SCAFFOLD.yaml (§1.0–§1.7)** — top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`; neither design key is present (verified programmatically).
- 12 entities, 14 state-machine dimensions, 13 calculations, 68 validations, 68 endpoints, 77 error ids, 6 roles (RanchManager, ReservationsAgent, HorseProgramDirector, ActivityGuide, SafetyOfficer, Guest).
- `complexity_profile`: primary `temporal_windowing`, secondary `quota_allocation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, topology `graph`, SM shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, difficulty `expert_plus`.
- Domain model spans Season/Booking/Cabin folio math (all-inclusive package + buyout premium + gratuity + no-show penalties), the horse program (ability assessment → mount assignment with duty/rest/daily-hour ceilings), ActivitySlot readiness posture with guide-ratio staffing, waivers/equine-statute acks and incident disposition, and seasonal staff retention-bonus vesting.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key `scaffold_difficulty_design`; 9 rules / 19 instances, every instance with full `test_recipe`.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key `scaffold_corner_design`; 76 instances = 66 active (with `test_recipe`) + 10 `excluded_because` stubs. Section coverage hits all nine claim-extraction-guide sections:

`entities 11 · state_machines 16 · calculations 14 · validations 14 · endpoints 4 · errors 4 · rbac 5 · cross_cutting_complexity_layers 7 · consistency_model 1`

**Audit results**
- No duplicate instance names across the two design files (95 names total, all unique).
- All 10 stubs cite an existing §1.8 instance name; no stub carries a `test_recipe`.
- Every `${var}` in every call is bound by an earlier `captures:` (no unbound references).
- All four OCC instances use `${var}` for `expected_*_version`, never literals.
- Formula asserts are pre-computed literals (package totals, deposits, folio balance 1107648, retention bonus 80377 from `round_half_up(120000*71/106)`, bed-nights aggregation and its reversal).
- `selector_policy` — a layer absent from the guide's table — is covered by an active instance rather than a stub, since `excluded_because` may only cite §1.8 names.

**Lint verdict** (verbatim):
```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1240

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read at any point; the scaffold was generated from the scenario plus the generator skill's spec alone. Scratch dir `/tmp/task_2896_scratch/` has been removed.

Orchestrator verification: grep for "harder than expert level" across the task dir returns nothing — the difficulty directive did not leak into any scaffold file. workspace/ still present.

## Step 3: Copy shared files — 2026-09-05T14:38:14.141186526Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-05T14:57:57.337543080Z

PRD complete and audited.

**Output:** `workspace/PRD.md` — **548 lines / 121 KB**, built in 17 verified chunked appends (no single large write), ending cleanly on the last row of the §5 table.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Ranch Personnel, Guests and RBAC / 2.2 API Response Structure (fixed block, verbatim) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Version Counters / 2.5 The Logical Ranch Clock / 2.6 Money, Hours and Rounding Discipline / 2.7 OCC on Contended Writes / 2.8 Path Resolution and Referential Integrity / 2.9 The Order in Which the Ranch Says No / 2.10 Cascade Discipline and the Conservation Rule / 2.11 Season Gating
- §3 Business Logic & Workflows — 3.1 The Operating Season and Its Package Terms / 3.2 Cabins, Housekeeping Turnover and Off-Season Capital Projects / 3.3 Guest Records, Liability Waivers and Guest Standing / 3.4 Rider Ability Assessment and the Rank Ladder / 3.5 Holding, Pricing and Confirming a Weekly Package / 3.6 Arrival, the Single Seating, and Settling the Folio / 3.7 Scheduling Activities and Staffing Guides / 3.8 Seats, Mounts and Riding the Programme / 3.9 The Herd, Its Health Record and Its Duty Days / 3.10 Seasonal Contracts, Bunkhouse Space and the Retention Bonus / 3.11 Incidents: Filing, Disposition and Closure
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage audit (mechanically verified with a script over SCAFFOLD.yaml)**
- Endpoints: **68/68** rows in §4 (`| METHOD |` row count = 68), every one also reachable from §3 narrative via state-transition / role+verb / capability framing.
- Calculations: **13/13** rendered as prose (package_charge_total both variants, folio_settlement_amount's 10 ordered steps, horse_load_index scheduled vs realized, guide_staffing_requirement, cancellation_refund_split, retention_bonus projected vs settled with the 50 % cliff, season_financial_rollup, mount_selection_ranking, rider_ability_rank_resolution, guest_waiver_status_resolution, slot_readiness_posture, horse_duty_day_run, cabin_bed_night_occupancy). No pseudocode operators remain anywhere (`==`, `:=`, `>=`, `+=`, `ceil(`, `round_half_up` all absent from §1–§3).
- Errors: **77/77** in §5 and **77/77** also named in §1–§3 prose next to the rule they guard.
- Contract 1 (Field-Name Coverage): **PASS** — 153/153 entity field names and 110/110 endpoint request-body/query/path identifiers appear verbatim inside backticks; all enum literals across every enum field present; nested object contents of `package_tiers` and `party_members` present down to `code`, `adult_nightly_rate_cents`, `child_discount_pct`, `included_activity_credit_cents`, `guest_id`, `member_type`, `dietary_restrictions`.
- Contract 2 (Rule Coverage): **PASS** — 71 transitions over 14 dimensions with every from/to state value in prose, all 68 validations enumerated in strict priority order in §2.9 (including the four normative inversions at priorities 18, 30, 57, 66), all 4 OCC rules with their pinned parent row and 412 semantics, and every multi-link cascade written out link-by-link.
- Contract 3 (§3 Path Purity): **PASS** — zero backtick tokens in §3 start with `/`, are a bare HTTP method, or combine method+path. The only method+path tokens in the document outside §4 are the four concurrency-rule anchors in §2.7, which the contract scopes as permitted.

Scaffold contradictions resolved and recorded in prose as the authoritative reading: payment `kind` is `DEPOSIT` | `SETTLEMENT`; `mount_required` is derived from `activity_type` even though it appears in the creation payload; slot completion takes `actual_duration_hours` and records `actual_ended_at` from it; folio step 2's surcharge set is `CHECKED_IN`/`COMPLETED`/`NO_SHOW` less `CANCELLED` reversals; `net_surplus_cents` subtracts retention liability and `capital_committed_cents`. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read. Task-scoped scratch dir `/tmp/task_2896_prd_scratch/` was used for the table generation and has been removed.

Orchestrator truncation check: `tail -12 PRD.md` ends on a complete §5 error-table row (`| ERR_CAPITAL_RESERVE_INSUFFICIENT | 409 |`), and the heading scan shows all five top-level sections plus every §2.x/§3.x subsection present. Not truncated — no regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-05T15:37:53.166218365Z

_(Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator never saw test_suite/. Step 6 returned first; the Step 5 entry follows below.)_

Implementation complete and smoke-verified.

## Module inventory (`workspace/implementation/`, 4023 lines total)

| file | lines | role |
|---|---|---|
| `store.py` | 118 | in-memory `Store` (12 dict collections), logical clock (default `2026-08-01T00:00:00Z`), id/`created_at`/`version` minting, `touch()` |
| `errors.py` | 94 | `ApiError` + full 77-entry error→HTTP status map |
| `envelope.py` | 90 | success/error envelope, `req_`+20-char ids, pagination (`limit` 1–100 default 10, `offset`), list `meta` |
| `auth.py` | 42 | header auth, 6 roles, ordered `MISSING_AUTH_HEADERS → UNKNOWN_ROLE → UNAUTHORIZED` |
| `fields.py` | 188 | typed body/query coercion, all `ERR_MISSING_REQUIRED_FIELD` / `ERR_INVALID_FIELD_VALUE` |
| `lookup.py` | 41 | 11 not-found codes, path and body FK resolution |
| `calc.py` | 242 | Decimal/ROUND_HALF_UP money+hours primitives and every named constant |
| `derive.py` | 654 | derived fields, cascades (`Touch`), mount selection, 12 serialisers |
| `routes_seasons.py` | 335 | clock + seasons + cabins (11 endpoints) |
| `routes_guests.py` | 283 | guests, waivers, standing, rider assessments (13) |
| `routes_bookings.py` | 577 | bookings, payments, folio, 10-step settlement (9) |
| `routes_horses.py` | 150 | herd + immutable health events (6) |
| `routes_slots.py` | 395 | slots lifecycle + guide assignments (11) |
| `routes_reservations.py` | 349 | seats, mounts, rider check-in, cancel (8) |
| `routes_staff.py` | 206 | seasonal contracts, bunks, retention bonus (6) |
| `routes_incidents.py` | 177 | incident filing, disposition, closure (4) |
| `app.py` / `requirements.txt` / `start.sh` | 75 / 1 / 7 | blueprint registration, error handlers, `$PORT` + 0.0.0.0 foreground launcher |

## Coverage
- **68/68 endpoints** of PRD §4 registered (verified by dumping `app.url_map` — exact count, no extras).
- **All 77 error ids** in the catalogue are reachable; a static scan confirms zero unknown and zero unused ids.
- **13 calculations**: `package_charge_total`, `guide_staffing_requirement`, `cancellation_refund_split`, `retention_bonus` (pro-rated/projected/settled), `season_financial_rollup`, `horse_duty_day_run` live in `calc.py`; `horse_load_index`, `mount_selection_ranking`, `rider_ability_rank_resolution`, `guest_waiver_status_resolution`, `slot_readiness_posture`, `cabin_bed_night_occupancy` live in `derive.py` as derive-on-read; `folio_settlement_amount` is the literal ten-step sequence in `routes_bookings.check_out_booking`.
- **68 validation priorities**: rules 1–3 in `auth.py`, 4–6 inline at the top of each handler, 7–8 in `lookup.py`, 9–10 in `fields.py`, 11–68 as an explicit top-to-bottom gate chain inside each handler ordered by §2.9 priority number (which I treated as normative over §3 prose wherever they differ, e.g. payments' amount check before the booking-state gate, seat creation's safety gates before capacity/duplicate).

## Smoke test
Launched `PORT=28963 bash start.sh` (recorded PID, killed only that PID and its child; no broad `pkill`), restarted from scratch 5 times to mimic `--isolation per-test-server`. A full lifecycle script passed: clock set → season → cabin → advance → 2 guests → waiver → assessment/evaluate → booking (`provisional 1008000`, `deposit 302400`) → payment → confirm → horse → staff hire/onboard → slot → guide assignment (`STAFFED_READY`) → open → seat (slot correctly self-demoted to `HOLD`/`MOUNT_SHORT`) → auto-assign mount → re-open → advance IN_SEASON → run → rider check-in → incident file (horse → `REVIEW_HOLD`) → dispose (`CLEARED`, horse back `IN_SERVICE`) → self-close rejected 403 `ERR_SEGREGATION_OF_DUTIES` → close by second officer → slot complete (`scheduled 0.0`, `realized 2.5`, `consecutive_duty_days 1`) → booking check-in → check-out refused 402 with balance `887040`, then settled exactly to zero (`final_folio_total 1189440`, gratuity `181440`) → cabin `TURNOVER`→`READY` → staff complete-season (bonus `120000` in full) → season CLOSED rollup (`gross 1189440`, `liability 120000`, `net 1069440`, `reserve 267360`, `bed_nights 14`) → OFF_SEASON → maintenance hold + return-to-ready. Negative paths verified: 412 stale slot version, 403 unauthorized role, 404 unknown horse, list filters + pagination.

Two smoke assertions of mine were wrong, not the implementation: an empty slot legitimately requires 0 guides (§3.13 "a slot with no confirmed riders at all requires exactly 0 guides, not the terrain floor"), and a mounted seat legitimately knocks an `OPEN` slot to `HOLD` until re-opened. Storage stayed purely in-memory, nothing is seeded, and `worklog.md` was not touched.

## Step 5: Generate unit tests (subagent) — 2026-09-05T15:47:44.781858039Z

Generation is complete. All 19 queue-A difficulty instances and all 66 non-stub queue-B corner instances are translated.

## Output

Both directories sit at the task root; nothing test-related was written under `workspace/`, `workspace/implementation/` was never read or written, and `worklog.md` was not touched.

**`test_helpers/` (Stage 1, 2770 lines)** — `__init__.py` 60, `api_client.py` 391, `api_errors.py` 193, `assertions.py` 385, `constants.py` 131, `factories.py` 369, `fixtures.py` 627, `test_users.py` 120, `types.py` 494.

**`test_suite/` — 108 test functions across 18 modules (6470 lines incl. `conftest.py` 31)**

Queue A (mine, 41 tests): `test_01_dual_variant_money.py` 199/4, `test_02_combinatorial_formulas.py` 205/4, `test_03_parallel_and_cyclic_states.py` 190/4, `test_04_transitive_cascades.py` 366/6, `test_05_validation_precedence.py` 180/4, `test_06_boundary_precision.py` 241/5, `test_07_cross_entity_state_gates.py` 317/6, `test_08_resource_temporal_overlap.py` 299/4, `test_09_compensating_invariants.py` 275/4.

Queue B (three subagents, 67 tests): `test_20` 433/12, `test_21` 737/13, `test_22` 885/11, `test_23` 848/12, `test_24` 257/4, `test_25` 248/4 (one parametrized 3x -> 6 collected), `test_26` 308/5, `test_27` 373/5, `test_28` 78/1.

## Coverage and skips

- Queue A: 19/19 instances, every one with >=2 tests (no instance under 2).
- Queue B: 66/66 non-stub instances with >=1 test; the 10 `excluded_because:` stubs were correctly left untranslated.
- **Zero instances skipped** — every one passed both the verbatim-coverage and unique-derivability filters. Assertion-level drops were made where a design claim was not PRD-pinned (never the distinguishing assertion): `credited_hours` at creation (PRD pins 0, not 2.0), `payments_applied_cents` after a DEPOSIT (PRD routes deposits to `deposit_paid_cents`), guest-role booking ownership, `retention_bonus_settled_cents` on an ACTIVE staff member, `updated_at` tied to the logical clock, and `scheduled_guide_hours` on slot cancel/complete.

## Verification (programmatic, all green)

`ast.parse` on all 18 modules; `PYTHONPATH=. import test_helpers` ok; pyflakes clean apart from two unused constant imports in `fixtures.py`; no `pytest.mark.skip/skipif/xfail`, `unittest`, `mock`, `print(`, `time.sleep`, `datetime.now`, or scaffold references anywhere; 108/108 tests carry exactly one `PRD:` citation that is verbatim in `PRD.md` (>=8 words) and exactly one `Design:` line as the final docstring line, each naming a real instance; no duplicate test names; no stub translated.

## Two real defects fixed in Stage 1

1. `fixtures.assess_guest_ability` opened rider assessments as `ReservationsAgent`, but PRD §4 restricts `POST /guests/{guestId}/rider-assessments` to `HorseProgramDirector` — this would have 403'd `build_ready_rider`, `build_ride_scenario` and the `adult_rider` fixture across most of the suite. Now posted as `HORSE_PROGRAM_DIRECTOR`. (Flagged by the entities/state-machines subagent, which had worked around it with module-local helpers in `test_21`; that workaround is now redundant but harmless.)
2. `fixtures.build_filed_incident` filed reports as `SafetyOfficer`; PRD §3.11 requires the assigned `ActivityGuide`. It now takes an optional `guide_staff_member_id` routed through `make_activity_guide_headers`.

I also audited every `client.*` call in `fixtures.py` against the §4 role table — no remaining role mismatches.

One deliberate judgement call worth knowing for Step 7: PRD §4 does not unambiguously pin whether `POST /activity-reservations/{id}/mount-assignments` answers 200 or 201 (it transitions the seat but is spelled as a sub-collection create), so successful mount assignments use the lenient `get_success_data` rather than asserting a status; every mount-assignment *error* path still asserts the exact id and status.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-05T16:09:37.46458323Z

All 8 rounds green at 110/110. Exiting.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one fix batch, one verification sweep).

**Final sweep evidence** (`workspace/implementation/results.1.json` .. `results.8.json`):

| round | passed/total |
|---|---|
| 1 | 110/110 |
| 2 | 110/110 |
| 3 | 110/110 |
| 4 | 110/110 |
| 5 | 110/110 |
| 6 | 110/110 |
| 7 | 110/110 |
| 8 | 110/110 |

failed=0, errors=0, skipped=0 in every round. Iteration 1 was 103/110 in all 8 rounds with an identical 7-test failure set — fully deterministic, no flakiness and no load-induced failures observed at any point.

**Tests deleted:** none. All 7 failures passed STEP 1a coverage; each resolved to either an implementation defect or a test-layer defect under STEP 2/3.

**Fixes applied to `implementation/`**

- `workspace/implementation/routes_bookings.py`, `cancel_booking()` — added the unpaid-hold special case before the refund-band-to-`payment_status` mapping: when `deposit_paid_cents == 0` and `payment_status == "AWAITING_DEPOSIT"`, `payment_status` becomes `FORFEITED`. PRD §3.6 states verbatim: *"A booking cancelled while nothing had yet been collected — `deposit_paid_cents` at 0, `payment_status` still `AWAITING_DEPOSIT` — moves to `FORFEITED` with both `refunded_cents` and `forfeited_cents` at 0, since the conserved total is itself 0."* The impl was applying only the band mapping, and the band mapping's own wording (*"moves `payment_status` **from `DEPOSIT_PAID`** to `REFUNDED`"*) scopes it to a booking that had actually paid. The canonical fixtures cancel at clock 2026-08-01 against arrival 2026-10-11 = 71 days out, which selects the 0.50 band, so an unpaid hold was reporting `PARTIALLY_REFUNDED`. This was the single root cause of 2 failures (`test_the_refused_confirmation_leaves_the_unpaid_deposit_untouched`, `test_second_cancel_on_a_cancelled_booking_is_rejected`). **Step 8 note: this is the only implementation-side PRD site touched this step.**

**Fixes applied to `test_suite/`**

- `test_suite/test_21_lifecycle_transitions.py`, `TestAbilityAssessmentCycle::test_rider_assessment_loops_evaluated_to_re_evaluation_and_back` — the assertion `capped["effective_ability_rank"] == "NOVICE"` after flagging mis-translated PRD §3.4. The normative derivation reads *"among the guest's assessments whose `assessment_status` is `EVALUATED`, the one with the greatest `evaluated_at` is selected … If the guest has no `EVALUATED` assessment at all, `current_ability_rank` is `UNASSESSED`"*, and the cap is *"lowered to `NOVICE` if it stands above `NOVICE`"* — a cap can only lower. Flagging moved the guest's only assessment out of `EVALUATED`, so the verdict is withdrawn and the rank is `UNASSESSED`; the prose *"Flagging caps the guest's effective ability at `NOVICE`"* asserts `<= NOVICE`, not `== NOVICE`. Replaced with `current_ability_rank == "UNASSESSED"` plus a `<= RE_EVALUATION_CAP` ladder assertion. (Provenance cross-check only: `SCAFFOLD.yaml` formula `rider_ability_rank_resolution` reads `assessment_status == EVALUATED` and `base_rank := min(base_rank, rank_of[NOVICE])`, confirming the impl's reading.) The rest of the test — the `EVALUATED -> RE_EVALUATION_REQUESTED -> EVALUATED` cycle, `re_evaluation_reason` clearing, and the restored `INTERMEDIATE` — is unchanged and passes.
- `test_suite/test_26_role_permissions.py`, `TestSegregationOfDuties::test_one_officer_cannot_both_dispose_and_close_the_same_report` — setup bug: taking a seat on an OPEN mounted slot leaves it `MOUNT_SHORT`, and PRD §3.8 requires *"an `OPEN` slot whose posture degraded moves to `HOLD`"*, so `run_slot` correctly answered `ERR_SLOT_STATE_INVALID`. Naming the mount only restores *"a re-openable state"* (§3.8), not `OPEN`. Added the explicit `HOLD -> OPEN` re-open (`open_slot`, already imported) after `attach_mount`, asserting `slot_status == "OPEN"`, per PRD §3.7 *"The same capability re-opens a slot from `HOLD -> OPEN` … the slot's `readiness_posture` must read `STAFFED_READY`."*
- `test_suite/test_27_concurrency_and_layering.py`, `TestSlotVersionPin::test_stale_slot_version_is_refused_on_the_second_seat` — same MOUNT_SHORT->HOLD root cause: the first seat dropped the OPEN `TRAIL_RIDE` slot to `HOLD`, so the second (correctly-pinned) seat was refused `ERR_SLOT_ON_HOLD` (§2.9 rule 56). Switched the slot to `activity_type="HIKE", mount_required=False` — PRD §3.7: *"`mount_required` … is true exactly when `activity_type` is `TRAIL_RIDE` or `ARENA_LESSON`, and false for `FLY_FISHING`, `HIKE` and `KIDS_PROGRAM`"* — so no seat can leave it mount-short and the slot stays `OPEN`. The default guide certifications include `WILDERNESS_FIRST_AID`, which the hike demands. The version-pin assertions the test exists for are untouched.
- `test_suite/test_27_concurrency_and_layering.py`, `TestGuestVersionPin::test_stale_guest_version_is_refused_on_a_second_assessment` — the three `create_rider_assessment` calls used `RESERVATIONS_AGENT`, so the impl correctly answered `ERR_UNAUTHORIZED`. PRD §4 authorises `POST /guests/{guestId}/rider-assessments` for `HorseProgramDirector` only (and §2.1 gives the director *"rider ability assessment"*). Switched all three to `HORSE_PROGRAM_DIRECTOR`; the reads/list stay on `RESERVATIONS_AGENT`, which §4 does authorise.
- `test_suite/test_27_concurrency_and_layering.py`, `TestBookingVersionPin::test_stale_booking_version_is_refused_on_the_second_folio_adjustment` — dropped `assert_folio_waterfall_consistent` / `assert_folio_balance_consistent` on a `CHECKED_IN` booking. PRD §3.6 recomputes `final_folio_total_cents` and `folio_balance_cents` from an adjustment only *"when the booking has already reached `CHECKED_OUT`"*, so both stand at 0 pre-departure and the waterfall identity is not a PRD-required invariant there (STEP 1c partial coverage: the covered effect is *"Each accepted adjustment adds its amount to `folio_adjustment_total_cents` and increments the booking's `version` by 1"*). Replaced with `booking_status == "CHECKED_IN"` and `version == bv_fresh + 1`, keeping the `folio_adjustment_total_cents == 7500` and stale-pin assertions.

**Fixes applied to `test_helpers/`:** none — no shared fixture, factory, or role-header defect surfaced. (Noted but not triggered by any test: `fixtures.build_filed_incident` falls back to `SAFETY_OFFICER` headers when `guide_staff_member_id` is omitted, which would draw `ERR_UNAUTHORIZED` since PRD §4 restricts incident filing to `ActivityGuide`; every current caller passes the guide id, so it is latent only.)

**Suite size unchanged at 110 tests** before and after, confirming no test was dropped or skipped. `worklog.md` was not touched.

_Orchestrator verification: independently read all 8 `results.$i.json` — every one reports 110/110. Sweep artifacts are present on disk, so the clean sweep is evidenced, not merely claimed._

## Step 8: Finalize PRD (subagent) — 2026-09-05T16:19:03.666137715Z

PRD_FINALIZED.md is written: 548 lines / 121,272 bytes vs PRD.md's 548 lines / 120,997 bytes — line count unchanged (0.0% delta), +275 bytes, exactly one line (§3.6, line 305) rewritten.

## Change

- **§3.6 "Cancelling a stay"** — revise — reordered the `payment_status` terminal-value sentence so the unpaid-hold case is decided *ahead* of the refund-band mapping (previously the two sentences both matched a `deposit_paid_cents == 0` / `AWAITING_DEPOSIT` booking whose arrival date selected a non-zero band, and the band mapping read as the operative rule); added that the outcome holds "whichever band the arrival date selected" and that `cancellation_refund_pct` still records the band's fraction; and dropped the "from `DEPOSIT_PAID`" qualifier from the 1.00 arm, replacing it with "whatever `payment_status` the booking was carrying". — `implementation/routes_bookings.py:361-383`

## Pre-edit search log

**Edit 1 — subject: the `payment_status` value a cancellation lands on, and `cancellation_refund_pct`.**

(b) Paths enumerated and read/grepped:
- `grep -n "FORFEITED\|PARTIALLY_REFUNDED\|cancellation_refund_pct\|AWAITING_DEPOSIT" implementation/*.py` — every writer of these fields.
- `routes_bookings.py:347-401` `cancel_booking()` — the only site that assigns `REFUNDED` / `PARTIALLY_REFUNDED` / `FORFEITED`; the special case is keyed on `deposit_paid_cents == 0 and payment_status == "AWAITING_DEPOSIT"`, is not keyed on `booking_status`, and `cancellation_refund_pct` is written from the band unconditionally at line 365 before the mapping.
- `calc.py:170-184` `cancellation_refund_pct` / `cancellation_refund_split` — band thresholds and the remainder-based forfeit; confirms the fraction is computed and returned even when the deposit is 0.
- `routes_bookings.py:296-310` (payment posting: `AWAITING_DEPOSIT -> DEPOSIT_PAID` only once `deposit_paid_cents >= deposit_required_cents`, and only from a positive amount, so `deposit_paid_cents == 0` with `DEPOSIT_PAID` is unreachable) and `routes_bookings.py:210-255` (creation defaults `payment_status: AWAITING_DEPOSIT`, `deposit_paid_cents: 0`).
- `routes_bookings.py:320-344` `confirm_booking()` — a zero `deposit_required_cents` lets a booking reach `CONFIRMED` while still `AWAITING_DEPOSIT` with `deposit_paid_cents == 0`; the impl's unpaid-hold branch fires for that booking too, so the new wording deliberately carries no `booking_status`/`HELD` qualifier.
- `routes_bookings.py:500-530` (check-out `PAID_IN_FULL`) and `derive.py:508` (`cancellation_refund_pct` exposure) — confirm no other transition into a terminal money status and no second reader that would be mis-described.

(c) Wording adjustments made to keep all paths consistent: (1) kept the override keyed on *both* field conditions joined by an explicit **and**, so a partially-deposited booking (`deposit_paid_cents > 0`, still `AWAITING_DEPOSIT`) continues to take the band mapping as the impl does; (2) added no `booking_status` qualifier, since the impl's branch also covers a `CONFIRMED` zero-deposit booking; (3) removed "from `DEPOSIT_PAID`" and substituted "whatever `payment_status` the booking was carrying", because the impl applies the band mapping from `AWAITING_DEPOSIT` as well — leaving the original phrase after promoting the special case would have implied the mapping fires only out of `DEPOSIT_PAID`, a brand-new mismatch; (4) stated explicitly that `cancellation_refund_pct` still holds the band fraction in the unpaid case, matching line 365, so the promoted special case cannot be read as zeroing it.

## Items that needed no PRD edit

- **test_21 ability cap** — §3.4's "How the two rank fields are derived" already pins `current_ability_rank = UNASSESSED` when no `EVALUATED` assessment remains and that caps "can only ever lower the rank"; `derive.py:68-90` matches verbatim, and `routes_guests.py:278-280` cascades on the literal `NOVICE` threshold as §3.4 states. Test-translation bug only.
- **test_26 / test_27 slot fixes** — §3.8 ("an `OPEN` slot whose posture degraded moves to `HOLD`") and §3.7 (manual `HOLD -> OPEN` requiring `STAFFED_READY`) already determine this; `derive.py:234-246` and `routes_slots.py:127-150` match. Test setup bugs.
- **test_27 guest version pin** — §4 line 415 already restricts `POST /guests/{guestId}/rider-assessments` to `HorseProgramDirector`; `routes_guests.py:166` matches. Fixture role bug.
- **test_27 booking folio pin** — §3.5 ("every money counter at 0" at creation) plus §3.6 ("when the booking has already reached `CHECKED_OUT`, `final_folio_total_cents` and `folio_balance_cents` are recomputed") already determine that both stand at 0 for a `CHECKED_IN` adjustment; `routes_bookings.py:575-585` matches. The deleted assertions were a test over-assertion, not a PRD silence.

_Orchestrator verification: `wc -l` = 548 (unchanged), `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (305c305), and the tail ends on the complete `| ERR_CAPITAL_RESERVE_INSUFFICIENT | 409 |` row — not truncated._

## Step 9: Complete PRD (three sequential module-partitioned subagent passes) — 2026-09-05T16:58:56.503068435Z

Step 9 was split into three strictly sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were forbidden to copy and edited in place. Each pass received the previous passes' out-of-partition observations.

**Net result: `PRD_FINALIZED.md` 548 lines / 121,272 chars -> `PRD_COMPLETED.md` 549 lines / 142,269 chars (+1 line, +20,997 chars, 165 changed lines). 82 edits total: 63 ambiguity-pins, 31 mismatch-revisions (some edits carry both classifications).**

---

### PASS 1 — cross-cutting infrastructure + seasons/cabins
Owned `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `fields.py`, `lookup.py`, `routes_seasons.py`; patched §2.1-§2.11, §3.1, §3.2, clock/season/cabin §4 rows, §5.

Source 548 lines / 121,272 chars -> 549 lines / 127,372 chars (+1 line, +6,100 chars). **21 ambiguity-pins, 6 mismatch-revisions** (27 edits, 25 lines, nothing at or after line 234).

- §2 intro — insert — ambiguity — trailing slash accepted as the same endpoint — `app.py:38`
- §2.1 — insert — ambiguity — both header values are whitespace-stripped before interpretation — `auth.py:31-42`
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:12,21`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real UTC time, not the logical clock — `envelope.py:27-29`
- §2.2 — insert — ambiguity — `message` non-contractual; unrouted path -> `ERR_INVALID_FIELD_VALUE`/404 and bad method -> `ERR_INVALID_FIELD_VALUE`/405, outside the §5 status table — `app.py:47-59`
- §2.3 — revise — ambiguity — `offset` has no upper bound; non-canonical integer text (fraction, sign, leading zeros) rejected `ERR_INVALID_FIELD_VALUE`; empty value = absent — `envelope.py:51-72`
- §2.3 — insert — ambiguity — empty filter = absent; enum filter out of range -> `ERR_INVALID_FIELD_VALUE`; id filters exact-match, unknown id -> empty page not 404 — `fields.py:172-188`, `derive.py:20-33`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read real server UTC time (strictly increasing), so `created_at` ASC == creation order — `store.py:68-77,112-115`
- §2.4 — insert — ambiguity — at creation `updated_at` equals `created_at` — `store.py:93-101`
- §2.5 — insert — ambiguity — `current_utc` required; offsets normalised to UTC and naive instants read as UTC; response is 200 with `data.current_utc` at 3 fractional digits — `routes_seasons.py:38-45`, `fields.py:125-146`
- §2.7 — insert — ambiguity — pins are plain integers; wrong type settles as invalid field value before comparison — `routes_reservations.py:36`
- §2.8 — insert — ambiguity — a payload id is FK-resolved only when present and string-shaped, otherwise falls through to shape checks — `lookup.py:29-34`, `routes_seasons.py:254,302`
- §2.8 — insert — ambiguity — JSON `null` counts as absent; missing/invalid/non-object body read as `{}` (so `ERR_MISSING_REQUIRED_FIELD`, not a parse error); undeclared fields ignored; strict typing (no string/number coercion, no boolean-as-number, no `4.0` for an integer) — `fields.py:14-18,25-97`
- §2.9 rule 8 — revise — **mismatch** — added creating a seat, cabin maintenance-hold and cabin return-to-ready to the body-FK list — `routes_reservations.py:31-32`, `routes_seasons.py:254,302`
- §2.9 rule 17 — revise — **mismatch** — `ERR_SEASON_NOT_OPEN` also on completing a slot, rider check-in, and placing a maintenance hold — `routes_slots.py:198`, `routes_reservations.py:289`, `routes_seasons.py:265`
- §2.9 rule 21 — revise — **mismatch** — `ERR_CABIN_NOT_READY` is per-operation state (`READY`; `TURNOVER`/`OUT_OF_SERVICE` on return-to-ready; `TURNOVER` on turnover-complete) — `routes_seasons.py:269,311,331`
- §2.10 — insert — ambiguity — a row reached by several cascade paths is versioned exactly once per request — `derive.py:250-280`
- §2.11 — revise — **mismatch** — dropped "new seats" from the CLOSED refusal; seat creation has no season gate and is governed by the parent slot's status — `routes_reservations.py:26-57`
- §3.1 — insert — ambiguity — `season_start_date`/`season_end_date` are not cross-checked at registration — `routes_seasons.py:103-104`
- §3.1 — insert — ambiguity — all four tier sub-fields required (`ERR_MISSING_REQUIRED_FIELD`); non-object element / non-string or duplicate `code` / bad rate-credit-discount -> `ERR_INVALID_FIELD_VALUE`; extra tier keys discarded — `routes_seasons.py:49-85`
- §3.1 — insert — ambiguity — empty tier table on the `OPEN` step -> `ERR_INVALID_SEASON_TRANSITION` — `routes_seasons.py:171-175`
- §3.1 — revise — **mismatch** — `CLOSED` (not `OFF_SEASON`) is what unlocks maintenance holds and capital commitments — `routes_seasons.py:263-267`
- §3.2 — insert — ambiguity — duplicate cabin `name` -> `ERR_INVALID_FIELD_VALUE` — `routes_seasons.py:218-220`
- §3.2 — insert — ambiguity — turnover-complete takes no body fields and demands `TURNOVER` — `routes_seasons.py:326-334`
- §3.2 — insert — ambiguity — maintenance-hold's four conditions are tested in §2.9 order (season -> cabin -> booking conflict -> reserve); response is the cabin — `routes_seasons.py:263-293`
- §3.2 — insert — ambiguity/mismatch — return-to-ready: `season_id` required and resolved in both branches, season status not examined, and the `TURNOVER` branch leaves the season and its `version` untouched — `routes_seasons.py:296-323`
- §4 return-to-ready row — revise — **mismatch** — row said `OUT_OF_SERVICE` only; impl also accepts `TURNOVER` — `routes_seasons.py:309-313`

§5 error table verified byte-equivalent to `errors.py` (77 id->status pairs, machine-diffed IDENTICAL) — no change needed. §4 role lists for all clock/season/cabin rows verified against `auth()` calls — all already correct.

Out-of-partition observations handed forward: seat accepted on a `DRAFT` slot vs the §4/§3.8 `OPEN`-only narrative; `/open` apparently not writing `slot_status = OPEN`; `ERR_SLOT_OUTSIDE_SEASON` vs `ERR_INVALID_FIELD_VALUE` for the slot geometry conditions.

---

### PASS 2 — guests, rider assessments, bookings, money
Owned `calc.py`, `routes_guests.py`, `routes_bookings.py` plus derive.py's guest/assessment/booking serialisers; patched §3.3-§3.6, §2.6, and guest/booking §4 rows. **No `cp` run.**

549 lines / 127,372 chars -> 549 lines / 135,924 chars. **20 ambiguity-pins, 8 mismatch-revisions** (28 edits).

- §2.6 — insert — ambiguity — every percentage/fraction is taken at its exact decimal value as written in the request, never at the nearest binary floating-point approximation — `calc.py:73-76`
- §3.3 — insert — ambiguity — `full_name`, `birth_date` and `weight_lb` are all required; `weight_lb` is a plain positive number that accepts fractional values — `routes_guests.py:33-36`
- §3.3 — insert — ambiguity — all three waiver timestamps (`waiver_signed_on`, `waiver_expires_on`, `waiver_revoked_at`) are null at creation and `equine_statute_ack` false — `routes_guests.py:44-48`
- §3.3 — insert — ambiguity — the guardian id is a body FK resolved before anything else about the payload, so an unknown guardian yields `ERR_GUEST_NOT_FOUND` even when `signed_on`/`equine_statute_ack` are absent — `routes_guests.py:85-87`
- §3.3 — insert — ambiguity — signing overwrites `waiver_signed_by_guardian_guest_id` (writing null when no guardian is named), `signed_on` is unconstrained relative to the clock, and there is no posture gate so re-signing a `SIGNED` guest is accepted — `routes_guests.py:108-117`
- §3.3 — insert — ambiguity — revocation is ungated on current waiver posture, and a never-signed guest's `waiver_status` stays `NONE` after revocation — `routes_guests.py:129`, `derive.py:62`
- §3.3 — insert — ambiguity — the revocation cascade raises each affected guest's `mount_release_count` by 1 — `derive.py:289`
- §3.3 — revise — **mismatch** — `target_standing` admits only `SUSPENDED` and `RESTRICTED` (`GOOD` is `ERR_INVALID_FIELD_VALUE`), there is no gate on the standing currently held, and the incident cross-reference was corrected from §3.10 to §3.11 — `routes_guests.py:143-147`
- §3.3 — insert — ambiguity — the standing cascade also raises `mount_release_count` — `derive.py:289`
- §3.3 — insert — ambiguity — reinstatement is ungated and is accepted on a guest already in `GOOD` standing — `routes_guests.py:152-162`
- §3.4 — revise — **mismatch** — a new assessment supersedes only prior `EVALUATED`/`RE_EVALUATION_REQUESTED` rows, leaving prior `PENDING` rows untouched so several `PENDING` assessments may coexist; each superseded row's `version` increments — `routes_guests.py:182-185`
- §3.4 — insert — ambiguity — `assessed_ability` is restricted to the four rider ranks (`UNASSESSED` refused), and all three evaluate fields are required — `routes_guests.py:235-236`
- §3.4 — insert — ambiguity — the re-evaluation flag cascade raises `mount_release_count` — `derive.py:289`
- §3.5 — insert — ambiguity — roster element shape: only `guest_id` and `member_type` are required, the missing-field error names the offender positionally (`party_members[0].member_type`), `dietary_restrictions` is optional/nullable and stored as `[]`, and extra keys are silently dropped — `routes_bookings.py:48-85`
- §3.5 — insert — ambiguity — booking creation defaults, including `cancellation_refund_pct` at 0 and every money counter at 0 except the two the pricing step writes — `routes_bookings.py:236-253`
- §3.5 — insert — ambiguity — only the occupancy interval is tested at hold time; the cabin's own `cabin_status` is not, so a hold may be placed against an `OCCUPIED`/`TURNOVER`/`OUT_OF_SERVICE` cabin — `routes_bookings.py:150-215`
- §3.5 — revise — **mismatch** — the vacuous "Whenever the roster changes..." sentence replaced: no capability edits a roster, window, tier or buyout flag, so `provisional_package_total_cents` and `deposit_required_cents` are written once and never revised — `routes_bookings.py` (no such endpoint exists)
- §3.5 — insert — ambiguity — payment refusals are layered (`ERR_INVALID_FIELD_VALUE` for bad JSON types, then `ERR_INVALID_PAYMENT_AMOUNT` for unknown kind or non-positive integer), deposits have no ceiling, and the payment-validity check precedes the booking-state gate on this one endpoint — `routes_bookings.py:287-300`
- §3.5 — revise — **mismatch** — confirmation's three gates reordered to season -> state -> deposit, with the consequences of each outranking spelled out — `routes_bookings.py:321-336`
- §3.6 — revise — **mismatch** — `dietary_briefing_ack` is required on every arrival (only the demand that it be *true* is conditional), and the five check-in gates reordered to season -> booking -> cabin -> dietary -> capacity — `routes_bookings.py:413-443`
- §3.6 — insert — ambiguity — `settle_payment_cents` is a required non-negative integer; zero is valid and a negative amount is `ERR_INVALID_FIELD_VALUE`, not a refund — `routes_bookings.py:462`
- §3.6 — insert — ambiguity — `realized_nights` has no floor at zero, so a same-day check-out measures 0 nights and `realized_subtotal_cents` re-prices to 0 — `routes_bookings.py:490`
- §3.6 — insert — ambiguity — step 2 is a fresh signed recomputation from the seats, not a read of the running counter, and can overwrite the 0 that a conserving reversal restored with a negative figure — `routes_bookings.py:494-500`
- §3.6 — insert — ambiguity — step 4's minimum has no floor at zero, so a negative surcharge total makes the credit equally negative and the two cancel exactly in step 9 — `routes_bookings.py:503`
- §3.6 — insert — ambiguity — step 8 reads the accumulated counter rather than re-deriving, because no per-adjustment row is stored — `routes_bookings.py:296` / `553-587`
- §3.6 — insert — ambiguity — `payment_status` becomes `PAID_IN_FULL` from whatever value it held, `AWAITING_DEPOSIT` included, for a booking whose `deposit_required_cents` rounded to 0 — `routes_bookings.py:537`
- §3.6 — insert — ambiguity — a post-check-out adjustment leaves `payment_status` at `PAID_IN_FULL` with a non-zero balance; `memo` is validated then discarded and no per-adjustment resource is readable anywhere — `routes_bookings.py:553-587`
- §4 — revise — **mismatch** — `POST /guests/{guestId}/rider-assessments` row: supersedes any prior EVALUATED **or RE_EVALUATION_REQUESTED** assessment while leaving a prior PENDING one untouched — `routes_guests.py:183`
- §4 — revise — **mismatch** — `POST /rider-assessments/{id}/evaluate` row: accepts a **PENDING or RE_EVALUATION_REQUESTED** assessment — `routes_guests.py:240`

Out-of-partition observations handed forward: §2.7's over-general "a new assessment supersedes the prior one"; §2.9 rule 8 missing `waiver_signed_by_guardian_guest_id`; §3.11's "only route out of suspension" claim contradicted by ungated reinstatement; four §3.10 retention/rollup items to confirm; the no-show penalty timing in `routes_slots.py:230-233`.

---

### PASS 3 — horses, slots, reservations, staff, incidents (+ two handed-down reconciliations)
Owned `routes_horses.py`, `routes_slots.py`, `routes_reservations.py`, `routes_staff.py`, `routes_incidents.py` plus derive.py's horse/slot/staff/incident portions; patched §3.7-§3.11 and their §4 rows, plus the two handed-down items. **No `cp` run.** 39 surgical Edit calls.

549 lines / 135,924 chars -> 549 lines / 142,269 chars (all edits in-paragraph; no lines added or removed). **22 ambiguity-pins, 17 mismatch-revisions.**

Handed-down reconciliations:
1. **§2.7 — FIXED.** "A new assessment supersedes the prior one" -> "supersedes the guest's prior `EVALUATED` and `RE_EVALUATION_REQUESTED` assessments". OCC rationale left intact; §3.4's rule not restated.
2. **§2.9 rule 8 — FIXED.** Added recording a waiver signature (`waiver_signed_by_guardian_guest_id`, `routes_guests.py:85-86`). Grepped every `find_body_ref` callsite across the five owned modules: seat creation (`routes_reservations.py:31-32`), named mount (`:175`), guide assignment (`routes_slots.py:295`), incident filing (`routes_incidents.py:33`) — all four already listed. `routes_horses.py` and `routes_staff.py` resolve no body FKs. No further additions needed.

Cross-partition leads, disposition:
- **`/open` not writing `slot_status = OPEN` — FALSE ALARM.** `routes_slots.py:147` does set it; nothing to fix.
- **Seat on a `DRAFT` slot — §3.8 was already correct** ("not `DRAFT`, `OPEN` or `HOLD`"); the **§4 row was the mismatch** and is fixed.
- **`ERR_SLOT_OUTSIDE_SEASON` for the geometric conditions — already pinned** in §3.7 para 1 and §2.9 rule 48. No change.
- **No-show penalty timing — MOOT.** `no_show_penalty_cents` is written only at season creation (`routes_seasons.py:111`); no endpoint mutates it, so retro-application is unreachable. No change.
- **§3.11 "only route out of suspension" — FIXED** (now names §3.3 reinstatement as an ungated second route).
- **Pass 2's four §3.10 items — all already pinned:** `staff_days_worked` clamping (§3.10 para 1), `pro_rated_bonus` single rounding and the `days_worked * 2 < contract_days` cliff (§3.10 para 3). `capital_reserve` flooring **belongs to §3.1 and is already pinned there** ("a negative net surplus is first floored at zero") — left alone as instructed.

Changes:
- §2.9 r19 — revise — mismatch — `ERR_SLOT_STATE_INVALID` also answers guide-assignment release, incl. a non-`SCHEDULED` assignment — `routes_slots.py:379-388`
- §2.9 r25 — revise — mismatch — `ERR_HORSE_NOT_IN_SERVICE` is unreachable on auto-assign (filtered, not raised) — `derive.py:345`
- §3.7 — insert — ambiguity — `mount_required` optional, boolean-checked, value discarded — `routes_slots.py:63,97`
- §3.7 — insert — ambiguity — `UNASSESSED` riders have no per-guide allowance — `calc.py:36-41,157`
- §3.7 — insert — ambiguity — `minor_rider_count` uses age at read, not frozen — `derive.py:199`
- §3.7 — insert — ambiguity — staffing has no slot-status/season gate — `routes_slots.py:290-334`
- §3.7 — insert — ambiguity — staff `version` unmoved by an assignment (derived hours) — `derive.py:158,346-348`
- §3.7 — insert — ambiguity — non-`SCHEDULED` release -> `ERR_SLOT_STATE_INVALID` — `routes_slots.py:384`
- §3.7 — revise — mismatch — open requires `STAFFED_READY` on `DRAFT` too; `MOUNT_SHORT` also answers `ERR_GUIDE_RATIO_UNMET` — `routes_slots.py:140-145`
- §3.7 — insert — ambiguity — cancel clears `hold_reason` — `routes_slots.py:283`
- §3.8 — revise — ambiguity — mount write needs a live (`CONFIRMED`/`CHECKED_IN`) seat — `routes_reservations.py:158-167`
- §3.8 x3 — revise — mismatch — version enumerations omitted the seat (attach/release) and the booking+horse (cancel) — `derive.py:382-387,282-307`
- §3.8 — revise — mismatch — mount cycle runs until `COMPLETED`, incl. `RUNNING` — `routes_reservations.py:260-262`
- §3.8 — insert — ambiguity — non-`RUNNING` slot at check-in -> `ERR_RESERVATION_STATE_INVALID` — `routes_reservations.py:296-300`
- §3.8 — insert — ambiguity — no-show release raises `mount_release_count` — `routes_slots.py:235`
- §3.9 — insert — ambiguity — duplicate horse name -> `ERR_INVALID_FIELD_VALUE` — `routes_horses.py:52-54`
- §3.9 — revise — mismatch — `resulting_horse_status` can be `REVIEW_HOLD` — `routes_horses.py:95-99`
- §3.9 — revise — mismatch — unknown health-event id -> `ERR_HORSE_NOT_FOUND`; no cascade ever files a health event — `lookup.py:37-41`
- §3.9 — revise+insert — mismatch+ambiguity — bad §3.10 cross-ref -> §3.11; a non-matching `event_type` is accepted and moves nothing — `routes_horses.py:97-99`
- §3.9 x2 — insert — ambiguity — the out-of-service cascade, the duty-run reset and `last_rest_started_on` all fire on `event_type` alone — `routes_horses.py:103-118`
- §3.10 — insert — ambiguity — `contract_end_date` violation is `ERR_INVALID_FIELD_VALUE`; hiring has no season gate — `routes_staff.py:40-41`
- §3.10 — insert — ambiguity — `housing_bunk_number` >= 1 — `routes_staff.py:89`
- §3.10 — insert — ambiguity — `COMPLETED_SEASON` projects the full bonus — `derive.py:179-187`
- §3.10 — insert — ambiguity — completion freezes `days_worked` — `routes_staff.py:196`
- §3.10 — insert — ambiguity — separation keeps the housing fields yet frees the bunk — `routes_staff.py:146-149,104`
- §3.11 — revise — mismatch — filing needs a live `SCHEDULED` assignment, so a completed/cancelled slot yields `ERR_NOT_ASSIGNED_GUIDE` — `routes_slots.py:28-39,248-252`
- §3.11 — insert — ambiguity — a horseless report filed with the notice false can never leave `FILED` — `routes_incidents.py:113-117`
- §3.11 — revise — mismatch — only an `IN_SERVICE` horse moves to `REVIEW_HOLD`, and filing releases no existing mounts — `routes_incidents.py:67-69`
- §3.11 — revise — mismatch — `CRITICAL` suspends from any non-`SUSPENDED` standing — `routes_incidents.py:70-73`
- §3.11 — insert — ambiguity — `CLEARED` branch sets `incident_status` — `routes_incidents.py:121`
- §3.11 — insert — ambiguity — remediation flag failure is `ERR_INCIDENT_STATE_INVALID`; report `version` +1 — `routes_incidents.py:159-163`
- §4 x3 — revise/insert — reservations row `DRAFT or OPEN`; mount-assignments answers 200 with the seat; health-event list drops the false cascade claim — `routes_reservations.py:53,232`, `routes_horses.py:142`

---

### Orchestrator final verification

- `PRD_COMPLETED.md` is **549 lines / 142,269 chars** and is **NOT** byte-identical to `PRD_FINALIZED.md` (165 changed lines) — the scan demonstrably ran.
- The file ends on the complete final §5 row `| ERR_CAPITAL_RESERVE_INSUFFICIENT | 409 |` — not truncated.
- Pass 2's summary contained an `EVATED` typo in its own prose; grepped `PRD_COMPLETED.md` for `EVATED` — absent, so the typo never reached the document.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for `*.py` newer than `results.1.json` returns **nothing**: no Step 8/9 pass touched code, so the Step 7 evidence (8/8 rounds at 110/110, all 8 `results.$i.json` present on disk) still holds for the delivered implementation.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; Steps 1-9 all done.

