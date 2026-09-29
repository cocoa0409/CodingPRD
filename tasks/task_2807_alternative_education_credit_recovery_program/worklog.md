## Step 1: Create task directory — 2026-09-05T00:12:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2807_alternative_education_credit_recovery_program and its workspace/ subdirectory. Index 2807 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T01:52:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2807_alternative_education_credit_recovery_program/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2802 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1974 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4007 |

`scaffold_lint.py` verdict: **clean lint** — 66 endpoints / 14 entities declared, 18 §1.8 + 63 §1.9 instances scanned, 947 calls checked, all FKs reverse-reachable.

## Domain model
14 entities (Center, HomeSchool, Student, Course, PriorCourseRecord, Referral, Placement, CourseEnrollment, CreditAward, GraduationPlan, ProctorStation, ProctorSession, SupportProvider, SupportSession); 8 state machines; 4 `concurrency_rules`; 12 calculations; 20 ordered validation rungs; **66 endpoints**; 59 error codes; 6 roles (DistrictAdmin, PlacementCoordinator, HomeSchoolCounselor, AltEdTeacher, Registrar, SupportProviderStaff). Profile: `api_prefix: "/"`, flat topology, cyclic state-machine shape, `segregation_of_duties` role model, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers, conditional_feature_flags]`, `consistency_model: immediate`.

## §1.8 depth probe — 9 rule ids × 2 instances = 18
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant` — 2 each.

## §1.9 breadth probe — 87 instances (63 full + 24 `excluded_because` stubs)
entities 12 (12 full) · state_machines 13 (9) · calculations 12 (7) · validations 9 (6) · endpoints 5 (4) · errors 19 (10) · rbac 6 (6) · cross-cutting complexity layers 9 (7) · consistency model 2 (2).

## Verification done beyond lint
- All 59 error codes are reachable from the two design files (0 unmentioned); `ERR_PRIOR_RECORD_ALREADY_REPLACED` required narrowing §1.4 rung 11 to in-flight enrollments so it stopped being masked.
- Every instance name is globally unique across both design files; every stub's `difficulty_instance` resolves by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (fixed 4 stubs that cited `rule_id / name`), and 9 stubs that were missing `grounds:` now have them.
- Grounds style normalised to one dotted form (29 bracket-form entries converted); every ground resolves to a declared entity/state machine/calculation/validation rung/endpoint/error/role/concurrency rule.
- No forbidden concurrency vocabulary in any file; the "harder than expert level" directive does not appear in `SCAFFOLD.yaml`, whose `scenario:` holds the domain prose verbatim; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- Every formula-derived assert is a pre-computed literal (e.g. mastery `0.60*85.00 + 0.40*95.00 = 89.00`, readiness `0.4500 + 0.3000 + 0.0000 -> 0.7500 + 0.0300 = 0.7800`, headroom walk `3 -> 2 OPEN -> 1 RESTRICTED -> 0 FROZEN -> 1 RESTRICTED`, staffing `floor(0.20*12) - 1 = 1` with ratio `5.00`, GPA `1.50 / 3.00 / 0.00`).

Orchestrator verification: all three files parse as YAML; top-level keys correct (SCAFFOLD.yaml has neither design key); difficulty-directive leak check on SCAFFOLD.yaml returned no match; workspace/ intact.

## Step 3: Copy shared files — 2026-09-05T01:53:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2807_alternative_education_credit_recovery_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T02:08:00.000Z

All verification passes are complete. PRD is written and clean.

## Output
`workspace/PRD.md` — **442 lines**

Ends at a real section boundary: the final line is the last row of the §5 table, `| ERR_CLOCK_BACKWARD | 409 Conflict |`. No mid-sentence truncation, no audit footer, no content after §5.

## Section list
- `# Alternative Education Credit Recovery API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Precision, Rounding and Credit Granularity · 2.6 Stale-Version Guards on Seat, Placement and Plan Writes · 2.7 Funded Seats, Staffing Ratio and the Intake Posture Gate · 2.8 Derived Values, Cascade Depth and Hierarchical Consistency · 2.9 Segregation of Duties · 2.10 The Order in Which a Request Is Judged · 2.11 Path Identifier Resolution
- `## 3. Business Logic & Workflows` — 3.1 Standing Up the District · 3.2 Graduation Plans, the Credit Ledger and "On Track" · 3.3 Referral Intake, Pathways and Priority Scoring · 3.4 Seating Decisions: Offers, Waitlist, Withdrawal, Acceptance · 3.5 Coursework at the Center · 3.6 Proctored Examinations and the Academic-Integrity Axis · 3.7 On-Site Support Services · 3.8 Awarding Credit and the Void That Reverses It · 3.9 Returning to the Home School, or Exiting Without Re-Entry
- `## 4. Endpoint Definitions` — 4-column table, 66 rows
- `## 5. Error Code Catalogue` — 2-column table, 59 rows

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 160 checked, 0 missing
- `endpoints[].request_body`: 85 checked, 0 missing
- `endpoints[].query_params`: 27 checked, 0 missing
- `endpoints[].path_params`: 14 checked, 0 missing
- error IDs: 59 checked, 0 missing · roles: 6 checked, 0 missing

**Contract 2 — Rule Coverage: PASS**
- `validations`: 20/20 rungs enumerated in §2.10 in strict priority order (verified items 1-20 contiguous); every `error_id` alternative across all `|`-joined rungs present, 0 missing; `applies_to` scopes and rung 18's internal sub-order stated
- `concurrency_rules`: 4/4 in §2.6 with write endpoint, OCC field, error ID and 412 status
- `state_machines`: 8 machines / 35 transitions; every `from` and `to` state literal present; `CourseEnrollment`'s two independent axes (`progress_state`, `integrity_state`) documented separately
- `calculations`: 12/12 translated to prose with reconstructible formulas; both dual-variant pairs given equal density (`SEAT_TIME` vs `COMPETENCY`; `REPLACE_ON_RECOVERY` vs `AVERAGE_ON_RECOVERY`)
- cross-entity side effects: 4-hop award posting and its compensating void, exit cascade, acceptance seat conversion, waitlist promotion, seat-conservation and credit-ledger invariants all documented
- sibling-branch symmetry checked on 8 branch pairs (resolve-integrity, exit source states, award/deny-award, complete/no-show, approve/deny re-entry, both calc variants)
- fuzzy-word scan: 4 raw hits, all false positives ("reports **about** that cohort", "nothing **about** the center's capacity", "turn**around** buffer" x2). Zero numeric hedging.

**Contract 3 — §3 Path Purity: PASS**
- 853 backtick tokens scanned in §3; tokens beginning `/` = 0; bare HTTP-method tokens = 0; method+path combinations = 0

## Other verification
- §2.2 matches `section-2.2-response-structure.md` byte-for-byte
- §4 table rows match the scaffold's 66 endpoint paths exactly (no missing, no extras); §5 has exactly 59 rows
- Isolation constraint honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling task directory was read.

Two scaffold ambiguities resolved and documented conservatively: (1) re-entry gate order written as posture -> attendance -> readiness -> integrity, following rungs 15/16/17 plus the Placement machine's trailing integrity precondition, since rung 12's `applies_to` omits `request-re-entry`; (2) the void endpoint's "zeroes `awarded_credits`" written as "clears back to null - the value an enrollment reports whenever it has no `POSTED` award", reconciling it with the entity definition.

Orchestrator truncation check (per the known doc-generator failure mode): PRD.md tail inspected — document terminates at the last row of the §5 error table, a real section boundary. §4 table holds 66 endpoint rows, §5 holds 59 error rows. No difficulty-directive leak (grep for "expert level" returns 0 hits). No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T04:12:00.000Z

Generation is complete. Final state of the two output directories.

## Files written (all at the TASK ROOT — nothing under `workspace/`)

`test_helpers/` — 9 files, 3,457 lines
`__init__.py` 150 · `api_client.py` 417 · `api_errors.py` 183 · `assertions.py` 426 · `constants.py` 359 · `factories.py` 426 · `fixtures.py` 945 · `test_users.py` 96 · `types.py` 455

`test_suite/` — 23 files, 9,056 lines
`conftest.py` 63 · `test_01` 390 · `test_02` 309 · `test_03` 328 · `test_04` 348 · `test_05` 310 · `test_06` 265 · `test_07` 417 · `test_08` 353 · `test_09` 408 · `test_10` 377 · `test_11` 471 · `test_12` 612 · `test_13` 397 · `test_14` 296 · `test_15` 554 · `test_16` 405 · `test_17` 473 · `test_18` 477 · `test_19` 558 · `test_20_optimistic_concurrency_layers.py` 521 · `test_21_posture_ladder_and_proctoring_flags.py` 438 · `test_22_immediate_consistency_of_derived_figures.py` 286

**148 tests** collected (`pytest --collect-only -q`), every file >=5 tests, queue A in `test_01`-`test_09`, queue B in `test_10`-`test_22`.

## Coverage
Queue A (§1.8): all 9 rule ids x 2 instances = **18/18 translated**, >=3 tests each, 57 tests — `boundary_precision_check` 6, `combinatorial_formula` 6, `compensating_invariant` 8, `cross_entity_state_dependency` 6, `dual_variant_calc` 6, `non_linear_state_machine` 6, `priority_pair_validation_conflict` 6, `resource_temporal_overlap` 6, `transitive_cascade` 7.

Queue B (§1.9): **60 of 63 non-stub instances translated**, 91 tests; all 24 `excluded_because:` stubs untranslated. entities 11/12 (11 tests) · state_machines 9/9 (9) · calculations 7/7 (10) · validations 5/6 (6) · endpoints 4/4 (5) · errors 9/10 (21) · rbac 6/6 (13) · cross-cutting complexity layers 7/7 (11) · consistency model 2/2 (5).

## Instances SKIPPED (3, gaps left as gaps)
- `entities/create_support_provider_applies_max_concurrent_default` — asserts default 1; PRD says the default is 4, so the asserted outcome is not PRD-derivable.
- `validations/station_from_another_center_rejects_proctor_booking` — asserts 409 `ERR_STATION_CENTER_MISMATCH`, but §2.10 rung 4 makes the reached station's `center_id` a 403 `ERR_FORBIDDEN_CENTER_SCOPE`, a lower rung; outcome not uniquely derivable.
- `errors/enrollment_and_prior_record_reuse_rejected` — asserts rung-13 `ERR_PRIOR_RECORD_MISMATCH` where rung 11's `ERR_PRIOR_RECORD_ALREADY_ENROLLED` answers first.

## Verification run over all 148 tests
Every `PRD:` quote machine-checked verbatim against `workspace/PRD.md` (0 misses); exactly one `Design:` line, at the very end of each docstring, one per test; every tag resolves to a real §1.8/§1.9 instance (0 dangling, 0 dual tags); the word "scaffold" appears nowhere; no skip/xfail/mocking; `pyflakes` clean on `test_suite/*.py`. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no `test_helpers/` or `test_suite/` anywhere beneath it, and neither worklog was touched.

## Design-index data defects found (repaired locally, not propagated)
New this session: (1) `consistency model/attendance_response_...` states `attendance_component 0.4500`/`0.3375` — those are the *weighted* terms; PRD §3.9 defines `attendance_component` as the rate itself (0.9000 / 0.6750), so the components were asserted per the PRD while the base/bonus/score figures it quotes (0.7500/0.0300/0.7800 and 0.6375/0.0000/0.6375) verified exactly. (2) The same instance asserts `re_entry_eligible == true` with no graduation plan in setup; PRD makes that flag depend on plan posture, so the sub-assertion was omitted. (3) `complexity layers/proctoring_and_ncaa_flags...` publishes `OPEN1` as an **ONLINE** course with `proctoring_required: false`, which the catalog forbids; it was published as `PACKET` (transcript code asserted `OPEN1-PK-AE`), and the same instance's invalid `subject_area: "PE_HEALTH"` -> `ELECTIVE` and field name `mastery_percent` -> `mastery_pct`.

Carried from earlier sessions: `COUNSEL_INDIV` not an enum; support-provider default 1 vs 4; bogus `SupportProvider.scheduled_session_count`; clock echo not envelope-pinned; `awarded_credits == 0.00` after a void where the PRD clears it to null; a re-referral bump instance colliding with rung 11; and both `rbac` segregation-of-duties instances asserting HTTP 409 where PRD line 150, rung 8 and the error catalogue all say **403**.

Orchestrator verification: test_helpers/ (9 .py files) and test_suite/ (23 .py files) both at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing, so no stray copies drifted under workspace/. Only one worklog.md exists (task root).

## Step 6: Generate implementation — 2026-09-05T04:12:30.000Z

The implementation is complete and verified.

## Modules (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 58 | Flask app factory, 7 blueprint registrations, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` |
| `store.py` | 142 | 14 in-memory dicts, logical clock (startup `2026-08-01T00:00:00Z`), `new_row`/`touch`/`ordered`, Decimal + ROUND_HALF_UP helpers, floor/quarter-floor |
| `errors.py` | 84 | all 59 error ids -> HTTP status, `ApiError` |
| `envelope.py` | 91 | `meta`/`response_type`/`data` envelope, `req_` id, pagination meta |
| `validate.py` | 187 | rung-5 body well-formedness (strings, ints, Decimals with dp/step, bools, enums, dates, UTC instants) |
| `auth.py` | 77 | 6-role RBAC decorator (rungs 1-2) + the 3 scope guards (rung 4) |
| `helpers.py` | 88 | 14 path/body id resolvers with their own 404s, query helpers |
| `derive.py` | 764 | every derived value: center posture/seat ledger/staffing, cohort figures, student status, GPA, pacing, mastery, credit bands, attendance, the 8 readiness figures, plan ledger/posture, priority score, and all 14 serializers |
| `services.py` | 163 | waitlist promotion, posture re-derivation, 4-hop award cascade, zero-drift compensating void, exit cascade |
| `routes_setup.py` | 325 | home schools, centers + staffing PATCH, courses, students, prior records, graduation plans, clock |
| `routes_referral.py` | 259 | referral CRUD + screen/request-info/resubmit/offer/waitlist/deny/withdraw-offer/accept-offer |
| `routes_placement.py` | 155 | placement reads + attendance/re-entry request/approve/deny/exit |
| `routes_enrollment.py` | 265 | enrollments + progress/submit/award-credit/deny-award/flag- and resolve-integrity |
| `routes_award.py` | 53 | credit-award reads + void |
| `routes_proctor.py` | 158 | stations, sessions, complete, no-show |
| `routes_support.py` | 135 | providers, sessions, complete |
| `start.sh` | 9 | guarded `pip install flask`, `exec python3 app.py`, honours `$PORT` (default 10000) |

Total 3004 lines of Python. Every file `ast.parse`s clean.

## Verification

- **Endpoints: 66/66, exact match.** Diffed the live `app.url_map` against the 66 rows extracted from PRD §4 (method + path, `{x}` -> `<x>`): `IDENTICAL`, no extras, no misses.
- **Error codes: 59/59.** Every `ERR_*` id in PRD.md is raised somewhere in the implementation, and `ERROR_STATUS` matches the PRD status table row-for-row with zero mismatches. The only non-PRD ids are three framework fallbacks in `app.py` (unknown route, wrong method, unexpected exception) that never collide with spec codes.
- **Smoke test passed.** On a random high port, a 30-call end-to-end flow: home school -> center -> student -> course -> prior record -> plan -> activate -> referral -> screen -> offer (OCC) -> accept-offer (201 Placement) -> enrollment (OCC) -> clock advance -> progress -> attendance -> submit-for-award -> award-credit (201 CreditAward) -> reads of every derived entity -> provider -> support session -> complete -> station -> proctor-session correctly refused `ERR_PROCTORING_POLICY_VIOLATION` (409) -> void (200). All statuses as expected in the PRD envelope shape. The one non-2xx at the end (`request-re-entry` -> 409 `ERR_PLAN_POSTURE_BLOCKS_RE_ENTRY`) is correct business logic for that fixture — the student had 1 of 24 credits and the award had just been voided.
- **Fresh-process cleanliness.** A second cold boot returned empty collections for `/students` and `/referrals`, and a grep audit confirms no sqlite, no `json.dump`, no file writes, no `/tmp` use anywhere — state exists only in process memory.
- Both smoke servers were killed by exact PID (no `pkill -f`); ports confirmed free, `__pycache__` removed.

## Two judgement calls worth flagging to review

1. **Exit cancels sessions without a CANCELLED status.** PRD §3.9 says exit "cancels every SCHEDULED ProctorSession and SCHEDULED SupportSession ... releasing their reserved intervals", but neither status enum has a `CANCELLED` value, no such transition is defined, and §3.9's version-bump enumeration lists only enrollments, the center and the placement. Implemented as a hidden `_released` flag (no status change, no version bump), with released sessions excluded from station-conflict and provider-capacity tests only — so the interval is genuinely released while the serialized row stays exactly as the PRD's field list describes.
2. **`created_at`/`updated_at` use wall-clock, not the logical clock.** PRD §2.4 ties the logical clock explicitly to `enrolled_on`, `posted_on`, `offer_expires_on` and pacing arithmetic, and describes `created_at` only as "when the row was first created", so system timestamps come from a strictly-increasing wall clock while every date stamp and pacing figure reads the logical clock.

Note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator could not read `test_suite/` — the directory did not exist when it started.

## Step 7: Run tests and iterate — 2026-09-05T04:08:00.000Z

Clean sweep achieved. Final state confirmed on disk.

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep under `setsid nohup`).

- Iteration 1: 148 tests, 143 passed / 5 failed — identical failure set in all 8 rounds (no flakiness; every failure was deterministic).
- Iteration 2: **147 tests, 147 passed / 0 failed in all 8 rounds** (`results.1.json` ... `results.8.json` present in `workspace/implementation/`, ~269 s each).

**Tests deleted (1)**

- `test_05_validation_priority_conflicts.py::TestPlacementStateOutranksRecoveryEligibility::test_the_exited_placement_reports_only_the_state_error` — **PRD silence / non-unique derivability**. It asserted that `POST /course-enrollments` against an `EXITED_UNSUCCESSFUL` placement returns `ERR_PLACEMENT_STATE_INVALID` (rung 10) ahead of `ERR_COURSE_NOT_PREVIOUSLY_FAILED` (rung 13). No PRD sentence makes placement status a precondition of enrollment *creation*: §3.5 enumerates that create's refusals as `ERR_INTAKE_FROZEN`, `ERR_DUPLICATE_ENROLLMENT` and the recovery-eligibility codes only, and rung 10 is scoped to "every **action** endpoint" while an enrollment create is a 201 create (contrast §3.8, which *does* say submit-for-award "is legal only while the owning placement's `status` is `ACTIVE`"). Two PRD-faithful implementations exist — one that never emits this error here, one that does — so unique derivability is broken. The two sibling tests in the class (rung-13 refusal, and the inertness of both refusals) are PRD-covered and were kept; the class docstring now records the removal and its reason.

**Fixes applied to `test_suite/` (test bugs, both in the setup layer)**

- `test_04_award_and_exit_cascades.py`, `_single_seat_world()` — the fixture opened a `seat_capacity=1` centre, placed one student, then tried to create a course enrollment. Accepting the only seat drives `seats_available` to 0, so per §2.7 the posture is `FROZEN`, and per §3.5 "A center whose `intake_posture` is `FROZEN` accepts no new enrollment at all and refuses it with `ERR_INTAKE_FROZEN`" — the PRD-faithful implementation correctly rejected the setup, killing all 3 tests in the class. Rebuilt the world with `seat_capacity=2`: student A's enrollment is created while the centre is still `OPEN`, then a second student fills the remaining seat to reach `FROZEN`, then student B is waitlisted. The transition under test is unchanged (`FROZEN` -> seat released -> `OPEN` -> promotion -> back to `FROZEN`, five-day promotion expiry). The derived seat picture in `test_the_posture_is_re_derived_twice_and_lands_back_on_frozen` was updated to follow the new capacity (`active=1, reserved=1, available=0, committed=2`, still `FROZEN`); no assertion was weakened.
- `test_15_not_found_and_reuse_rungs.py::TestTheUniquenessRungSpeaksFourDifferentCodes::test_four_duplicate_attempts_return_four_distinct_conflicts` — the duplicate-course-code payload overrode `modality` to `ONLINE` while leaving `proctoring_required: False`. §3.1 requires `proctoring_required` to "be true for `ONLINE` and `BLENDED` courses", so the request legitimately failed body validation at rung 5 with `ERR_INVALID_REQUEST` and never reached rung 11. Added `proctoring_required=True` to the override so the payload is PRD-valid and the `ERR_DUPLICATE_COURSE_CODE` assertion under test is actually exercised.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. All three root causes were test-artifact defects; in every case the implementation's behaviour was the PRD-required one (frozen-centre enrollment refusal, ONLINE-course proctoring validation, and the §3.5 refusal set for enrollment creation), so no PRD-required check was removed or weakened.

Orchestrator verification (per the known "Step 7 claims a clean sweep with no artifacts" hazard): re-read all 8 `results.*.json` myself — every round reports passed 147 / total 147 / failed 0, all eight written at the same wall-clock minute (04:04:23), so the final sweep genuinely ran to completion. Step 7 did not touch worklog.md.

Step 8 decision: NOT skipped. The skip condition requires 0 deletions and 0 fixes of every kind; this run had 1 deletion and 2 `test_suite/` setup fixes. Although `implementation/` was untouched, the deletion marks a genuine PRD silence (enrollment-create refusal set vs rung 10's action-endpoint scope) and both test_suite fixes mark places where the PRD's frozen-posture and proctoring rules bound behaviour the tests had mis-set-up — all three are legitimate Step 8 focus items.

## Step 8: Finalize PRD — 2026-09-05T04:11:00.000Z

`PRD_FINALIZED.md` is written. Two minimal patches; the third Step 7 item was a pure fixture bug and needed none.

**Line counts:** PRD.md 442 lines / 100,711 bytes -> PRD_FINALIZED.md 442 lines / 101,402 bytes. Line delta 0 (0.0%); byte delta +691 (+0.69%). Both edits are in-paragraph insertions, so no line-count change.

**Changes**

- §3.5 (course-enrollment creation) — insert — pins that the owning placement's `status` is **not** a precondition of `POST /course-enrollments`: rung 10 of §2.10 does not reach that endpoint, an enrollment may be created against a placement in `RE_ENTRY_PENDING`/`RE_ENTERED`/`EXITED_UNSUCCESSFUL`, and the endpoint never answers `ERR_PLACEMENT_STATE_INVALID`; a pointer contrasts §3.8's `ACTIVE`-placement requirement for submit-for-award — `implementation/routes_enrollment.py:29-86` (no placement-status branch anywhere in `create_enrollment`).
- §3.1 (catalog publish) — revise — pins that an `ONLINE`/`BLENDED` course published with `proctoring_required` false is a malformed body refused at rung 5 with `ERR_INVALID_REQUEST`, ahead of the `code` uniqueness check — `implementation/routes_setup.py:138-143` (`v.bad(...)` -> `ERR_INVALID_REQUEST`, evaluated before the duplicate-code loop).

**Per-edit pre-edit search log**

Edit 1 — §3.5 placement-status precondition
- (a) Subject: whether a placement's `status` gates creation of child rows, and which endpoints legitimately emit `ERR_PLACEMENT_STATE_INVALID`.
- (b) Enumerated: `grep -rn ERR_PLACEMENT_STATE_INVALID` across all of `implementation/` -> only `routes_enrollment.py:147` (submit-for-award) and `routes_placement.py:59,76,111,130,148` (attendance, request-re-entry, approve, deny, exit). Read `routes_enrollment.py` in full (create, progress, submit, award, deny, flag, resolve), `routes_proctor.py` in full (station create, session create/complete/no-show — session create reads only interval, `proctoring_required`, station centre and station occupancy; never placement status), `routes_setup.py` in full, and grepped `routes_support.py`/`routes_placement.py` for `placement["status"]` reads. Confirmed all three sibling creates (`/course-enrollments`, `/proctor-sessions`, `/support-sessions`) are placement-status-blind.
- (c) Adjustment: scoped the sentence to `POST /course-enrollments` alone rather than writing a general "creates never read parent state" claim. Although the impl happens to be blind for proctor and support session creates too, a universal statement would have been a new, unverified-in-full universal; the narrow form covers the Step 7 site without asserting anything about the other two endpoints. Also added the §3.8 contrast so the negative claim cannot be over-read into submit-for-award, which does require `ACTIVE`.

Edit 2 — §3.1 modality/proctoring cross-field constraint
- (a) Subject: the `ONLINE`/`BLENDED` => `proctoring_required` constraint, and its rung/error-code placement relative to `ERR_DUPLICATE_COURSE_CODE`.
- (b) Enumerated: `routes_setup.py:121-152` (the only writer of `modality` and `proctoring_required`; no `PATCH /courses` exists — verified by reading every route in `routes_setup.py` and the blueprint list in `app.py`'s siblings), `validate.py:14-15` (`bad()` raises `ERR_INVALID_REQUEST`) plus `grep 'v.bad|bad('` showing `routes_setup.py:139` is the only non-generic body-validation callsite in the whole codebase, and every reader of the two fields: `routes_proctor.py:75` (`ERR_PROCTORING_POLICY_VIOLATION`), `routes_enrollment.py:152` (`ERR_PROCTORED_EXAM_MISSING`), plus `derive.py`'s `mastery_pct`, `modality_code`/`transcript_code` and `ncaa_acceptable` uses.
- (c) Adjustment: worded as a constraint on the *publish request* only, and deliberately did not say anything about `PACKET` courses — the impl forces `proctoring_required` true only for `ONLINE`/`BLENDED` and freely accepts a `PACKET` course with it true, so a symmetric "must be false for `PACKET`" phrasing would have been a new mismatch. Named rung 5 and the relative order versus the uniqueness check (impl order: field validation -> cross-field check -> duplicate-code loop) without touching §2.10's rung-5 text, to avoid a broad claim about cross-field validation in general.

Orchestrator verification: diffed PRD.md against PRD_FINALIZED.md — exactly two changed lines (189 and 233), matching the two reported edits, so the finalizer genuinely edited rather than merely copying.

## Step 9: Complete PRD — 2026-09-05T04:35:00.000Z

Orchestrator decision: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single subagent. Rationale: a 442-line PRD against a 3,004-line 16-module implementation is more than one context can scan exhaustively, and a single-pass Step 9 characteristically returns a byte-identical file (the scan never really ran). Pass 1 owned the `cp` and the cross-cutting modules; passes 2 and 3 were explicitly forbidden to copy or revert, and each spot-checked the prior passes' edits before starting.

### Pass 1 — cross-cutting modules (`app.py`, `store.py`, `errors.py`, `envelope.py`, `validate.py`, `auth.py`, `helpers.py`) + `routes_setup.py`

`cp PRD_FINALIZED.md PRD_COMPLETED.md` ran as the first action. PRD_FINALIZED.md 442 lines / 101,402 chars -> PRD_COMPLETED.md 450 lines / 109,739 chars (+8 lines, +8,337 chars, 17 diff hunks). All headings and both tables verified byte-identical; every edit in-paragraph. **18 ambiguity-pins, 1 mismatch-revision.**

- §2.1 role bullets — insert — ambiguity — when the acted-on row *is* the scoping entity (`Center`/`HomeSchool`/`SupportProvider`) the comparand is its own `id`; each scope check inspects only its own role — auth.py:56-77, routes_setup.py:40,76
- §2.1 collection reads — revise — mismatch — the blanket "listing returns only rows inside the caller's scope" was untrue for rows carrying no scoping reference; narrowed with the concrete unnarrowed cases (`GET /centers`, `GET /courses`, `GET /prior-course-records`) — routes_setup.py:46,82,163,245
- §2.2 envelope bullets — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` comes from real wall clock, not the logical clock — envelope.py:19-27
- §2.3 pagination — insert — ambiguity — empty-string params treated as omitted; non-integer / out-of-range `limit` / negative `offset` -> `ERR_INVALID_REQUEST` 422; over-large offset legal and empty; `created_at` ties broken by creation order — envelope.py:48-73, store.py:98-100
- §2.3 — insert — ambiguity — filters are query params named exactly after the response field (including derived ones), exact-equality, conjunctive, empty ignored, unknown params ignored, bool filter accepts true/false/1/0 any case, scope narrowing precedes filters — helpers.py:56-88
- §2.3 meta fields — insert — ambiguity — `total_count` counted after scope+filter before windowing; `has_more` = offset + returned < total; object/action responses omit all four — envelope.py:76-91
- §2.4 `created_at`/`updated_at` — insert — ambiguity — sourced from real wall clock and forced strictly increasing so no two rows share a stamp — store.py:59-72
- §2.4 logical clock — insert — ambiguity — `current_utc` ISO parsing leniency (Z / offset / optional fraction / naive read as UTC) and the clock endpoint's response shape (`data` = `{current_utc}` only, 200, no id/version) — validate.py:170-181, routes_setup.py:317-325
- §2.5 precision — insert — ambiguity — figures emitted as bare JSON numbers with no trailing zeros (0.5, 88.0, 60.0), uncomputable figures as `null` — store.py:128-134
- §2.6 version guards — insert — ambiguity — absent/`null`/non-integer version field is rung-5 `ERR_INVALID_REQUEST` 422, not 412; no range imposed — routes_setup.py:98, validate.py:67
- §2.10 rung 5 — insert — ambiguity — absent/unparseable body = `{}`, non-object body refused, explicit `null` == absent, strict int/float/bool/string typing, excess decimal places and off-step values refused not rounded, strict `YYYY-MM-DD` — validate.py:18-167
- §2.10 rung 6 — insert — ambiguity — multiple body identifiers resolve in narrative order, first failure wins (`student_id` before `course_id`); absent/null nullable ids not resolved — routes_setup.py:228-229
- §2.10 rung 11 — insert — ambiguity — uniqueness comparisons are exact equality, case-sensitive, no trimming — routes_setup.py:141,184
- §2.11 path resolution — insert — ambiguity — trailing slash ignored in routing; identifiers matched as opaque strings so a non-UUID fails as a 404 — app.py:24, helpers.py:25-29
- §3.1 centers/staffing — insert — ambiguity — headroom test uses would-be values against the live active count before any write; a revision supplying none of the three still succeeds and still bumps `version`; `support_staff_fte` feeds no derivation — routes_setup.py:95-117
- §3.1 students — insert — ambiguity — `status` derived on read; a `COMPLETED` plan reports `GRADUATED` ahead of the placement chain; "latest placement" = most recently created — derive.py:149-164
- §3.1 prior course records — insert — ambiguity — historical rows carry no uniqueness constraint (same student/course/term may repeat) — routes_setup.py:217-235
- §3.2 plan activation — insert — ambiguity — `projected_completion_term` overwritten only when supplied and never clearable to null — routes_setup.py:306-311
- §5 preamble — insert — ambiguity — unrouted path -> `ERR_NOT_FOUND` 404, unsupported method -> `ERR_METHOD_NOT_ALLOWED` 405, both pre-auth, standard envelope — app.py:36-43

### Pass 2 — `routes_referral.py`, `routes_placement.py`, `services.py`

No `cp` run; only `Edit`. Pass 1's edits spot-checked intact (§5 preamble paragraph, §3.1 `support_staff_fte` clause, §2.2 20-character pin, §2.11 trailing-slash sentence), 28 headings / 129 table rows unchanged. 450 lines / 109,739 chars -> 450 lines / 114,415 chars. **12 ambiguity-pins, 3 mismatch-revisions** (15 edits).

- §3.3 — insert — mismatch — POST /referrals resolves body ids and validates body *before* the school-scope check, so out-of-scope student + bad `center_id` yields `ERR_CENTER_NOT_FOUND`, not `ERR_FORBIDDEN_SCHOOL_SCOPE`; `narrative` optional/null; `prior_referral_id` checked for existence only — routes_referral.py:39-45
- §3.3 — insert — ambiguity — duplicate-active-referral scan spans every center; `screening_note`/`missing_items`/`waitlist_reason`/`denial_reason`/`offer_expires_on` start null and `promoted_from_waitlist` starts false — routes_referral.py:46-62
- §3.3 — insert — ambiguity — every free-text note/reason on referral and placement transitions is min length 1 with no upper bound — routes_referral.py:106,121,193,207, routes_placement.py:128,146
- §3.3 — revise — mismatch — resubmission's `narrative` is optional (omitted leaves the stored account untouched); resubmit body carries no identifier — routes_referral.py:135-147
- §3.4 — insert — ambiguity — `offer_valid_days` must be an integer >= 1, no upper bound — routes_referral.py:164
- §3.4 — insert — ambiguity — a waitlist promotion adds no second center `version` bump; `waitlist_reason` is retained and never cleared, including by a later withdrawal — services.py:23-35, routes_referral.py:225-232
- §3.4 — insert — ambiguity — placement created by acceptance starts with days at 0 and the five re-entry/exit fields null; the `201` response `data` is the placement, not the referral; the referral keeps `offer_expires_on` and `promoted_from_waitlist` — routes_referral.py:247-259
- §3.4 — insert — ambiguity — acceptance is ungated on `intake_posture` and `staffing_headroom`, so successive acceptances may drive headroom <= 0 and the posture to `FROZEN` and still succeed — routes_referral.py:244-258
- §3.5 — insert — ambiguity — both attendance deltas are required non-negative integers with no upper bound, and nothing requires `days_present <= days_enrolled`, so `attendance_rate` above 1.0000 is reachable — routes_placement.py:56-63
- §3.8 — insert — ambiguity — the void also increments the enrollment's `version` by 1, and the integrity-driven void shares that single bump with the resolution (total +1, not +2) — services.py:112-126, routes_enrollment.py:255-258
- §3.9 — insert — ambiguity — a student with no graduation plan is refused with `ERR_PLAN_POSTURE_BLOCKS_RE_ENTRY` (not `ERR_PLAN_NOT_FOUND`), and a `DRAFT` plan clears the gate when its posture is not `OFF_TRACK` — routes_placement.py:78-81
- §3.9 — insert — ambiguity — approval clears nothing: `target_re_entry_date`, `re_entry_requested_by_user_id` and any earlier `re_entry_denial_reason` all stand — routes_placement.py:106-119
- §3.9 — insert — ambiguity — a repeat approval by the original requester is refused at rung 8 with `ERR_SEGREGATION_OF_DUTIES` ahead of the terminal-state 409 — routes_placement.py:106-112
- §3.9 — revise — mismatch — the exit releases scheduled sessions of **any** enrollment of the placement (not only the just-denied ones), and the release is capacity-only: session keeps `SCHEDULED`, keeps its `version`, keeps its place in `scheduled_session_count`, stays completable — services.py:153-163, routes_proctor.py:87, routes_support.py:80, derive.py:482-485
- §3.9 — insert — ambiguity — an exit out of `RE_ENTRY_PENDING` leaves `target_re_entry_date` and `re_entry_requested_by_user_id` standing — services.py:149-152

### Pass 3 — `routes_enrollment.py`, `routes_award.py`, `routes_proctor.py`, `routes_support.py`, `derive.py`

No `cp` run; 15 `Edit` calls, no whole-file writes. Pass 1 and pass 2 edits spot-checked intact (six samples). 450 lines / 114,415 chars -> 450 lines / 120,872 chars (+6,457 chars, all in-paragraph). **12 ambiguity-pins, 3 mismatch-revisions.**

- §3.1 (stations) — insert — ambiguity — coordinator's center scope on `POST /proctor-stations` is checked only after body validation and `center_id` resolution; station `label` carries no uniqueness constraint — routes_proctor.py:27-37
- §3.5 (new enrollment) — insert — ambiguity — `submitted_by_user_id`, `integrity_incident_code`, `integrity_resolution_note`, `denial_reason` all begin null — routes_enrollment.py:75-83
- §3.5 (recovery eligibility) — revise — mismatch — `ERR_PRIOR_RECORD_ALREADY_ENROLLED` is keyed on the *citation*, not on `enrollment_type` (a `NEW_CREDIT` create citing a record is guarded too), and sits at rung 11 ahead of the rung-13 eligibility checks — routes_enrollment.py:50-55
- §3.5 (progress) — revise — ambiguity — delta bounds pinned (`modules_passed_delta` int >=0 unbounded; `seat_hours_delta` >=0, no upper bound, no decimal-place cap; `module_avg_percent` any JSON number, no 0-100 range, no dp cap); an all-omitted report is legal and still bumps `version` by 1; rung-10 state check precedes the rung-12 integrity hold — routes_enrollment.py:116-132
- §3.6 (session booking) — insert — ambiguity — interval instants parsed with optional zone/fraction and echoed normalized to UTC at 3 fractional digits; rung-6 order gives `ERR_ENROLLMENT_NOT_FOUND` before `proctor_station_id`, scope after both; neither `progress_state` nor placement `status` is a precondition; any number of sessions per enrollment — routes_proctor.py:64-70
- §3.6 (booking result) — insert — ambiguity — `score_percent`, `integrity_incident`, `no_show_note` all start null (`integrity_incident` null, not false) — routes_proctor.py:92-94
- §3.6 (completion) — insert — ambiguity — omitted `integrity_incident` is recorded as false, not null — routes_proctor.py:127
- §3.6 (completion) — insert — ambiguity — the system flag fires only out of `CLEAR`; against a `FLAGGED`/`CLEARED`/`VOIDED_FOR_INTEGRITY` enrollment it leaves state, code and `version` untouched and the completion still succeeds; the enrollment's `version` bumps only on the firing branch — routes_proctor.py:135-140
- §3.6 (flag-integrity) — insert — ambiguity — `integrity_incident_code` is >=1 char with no upper bound; flagging a non-`CLEAR` enrollment is `ERR_ENROLLMENT_STATE_INVALID` — routes_enrollment.py:237-240
- §3.7 (support booking) — insert — ambiguity — same timestamp normalization; rung-6 order gives `ERR_PROVIDER_NOT_FOUND` before `placement_id`, both scopes after; placement `status` is not a precondition — routes_support.py:60-68
- §3.7 (booking result) — insert — ambiguity — `minutes_delivered` and `completion_note` both start null — routes_support.py:88-90
- §3.8 (submit-for-award) — revise — ambiguity + mismatch — `final_percent` accepts any JSON number (no range, no dp cap); non-`ACTIVE` placement is `ERR_PLACEMENT_STATE_INVALID` with the enrollment's own state judged first inside rung 10; inside rung 12 the integrity gate precedes the proctored-exam requirement (PRD prose had implied the reverse) — routes_enrollment.py:141-155
- §3.8 (award-credit) — revise — mismatch — the precondition list is explicitly *not* evaluation order; pinned actual order: SoD -> plan lookup (`ERR_PLAN_NOT_FOUND` sits between rungs 8 and 9) -> stale plan version -> enrollment state -> plan state -> integrity -> recovery replacement check -> rung-18 academic gates. PRD's "Finally..." had put `ERR_PRIOR_RECORD_ALREADY_REPLACED` last, behind `ERR_FINAL_PERCENT_BELOW_PASSING`; impl raises it first — routes_enrollment.py:169-207
- §3.8 (credit computation) — insert — ambiguity — `projected_credits` is never null: under `COMPETENCY` a null `mastery_pct` projects `0.0` — derive.py:319-326
- §3.9 (readiness) — revise — ambiguity — `attendance_component` alone is uncapped, so a >1.0000 attendance rate can push `readiness_base_score` above 1.0000, trimmed only by the final `readiness_score` cap — derive.py:358-359, 375-377

Pass 3 deliberate non-patch: the award/void cascade's hop-2 `version` bump on the backing prior course record (services.py:96-100, 129-134) is unenumerated in §3.8's bump lists, but §2.4's general cascade rule already covers it and `services.py` was pass 2's subject.

### Step 9 totals and orchestrator verification

Cumulative: PRD_FINALIZED.md 442 lines / 101,402 chars -> PRD_COMPLETED.md 450 lines / 120,872 chars (+8 lines, +19,470 chars, +19.2%). 42 ambiguity-pins and 7 mismatch-revisions across the three passes.

Orchestrator checks: `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (the known "Step 9 never ran" failure signature is absent); `diff` shows 42 changed lines; 28 headings preserved; the file still ends at the last row of the §5 error table (`| ERR_CLOCK_BACKWARD | 409 Conflict |`), so no truncation. `find implementation -name "*.py" -newer results.1.json` returns nothing — no Step 8/9 pass touched the implementation, so the Step 7 result of 147/147 in all 8 rounds still holds for the code on disk.

PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
