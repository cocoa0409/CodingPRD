# Worklog — task_3234_comedy_training_program_enrollment_ensemble_casting

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory verified on disk: ./tasks/task_3234_comedy_training_program_enrollment_ensemble_casting with workspace/ inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T13:03:00.000Z

All clean. The lint passes; counts look right.

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3234_comedy_training_program_enrollment_ensemble_casting/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3234_comedy_training_program_enrollment_ensemble_casting/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3234_comedy_training_program_enrollment_ensemble_casting/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: 15 (CurriculumLevel, Term, Instructor, CourseSection, Student, PlacementEvaluation, Enrollment, ShowcaseEvent, VenueSlot, CohortProgram, Audition, EnsembleCast, TouringAssignment, ScholarshipAward, TuitionInvoice)
- Endpoints: 84 (incl. one test-driving `POST /_clock/set_current_utc` with default clock pinned at 2026-09-01T00:00:00Z)
- Errors: 29
- Validations: 14
- State machines: 11
- Calculations: 8
- Roles: 6 (ProgramDirector, Registrar, PlacementOfficer, CastingDirector, FinanceOfficer, Student)
- §1.8 difficulty instances: 18 (9 rules × 2 instances each)
- §1.9 corner instances: 34 total (31 active + 3 `excluded_because:` stubs cross-referencing §1.8)

**Complexity profile:** graph constraint (curriculum prereq DAG) × quota/allocation (section capacity, cohort size, venue slots), with layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, scheduled_actions. Difficulty-rule differentiation is honored — dual variants on PlacementEvaluation vs TuitionInvoice; combinatorial modes (a) and (c); non-linear state machines on PlacementEvaluation (cycle) and Enrollment (branching with revert); cascades from Term-close vs Showcase-stage; priority conflicts state-vs-safety and safety-vs-fiscal; boundary on timestamp vs count; cross-entity gates Term×CourseSection and EnsembleCast×VenueSlot; temporal overlap half-open vs turnover-buffer; compensating invariants enrolled_count vs cash.

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

Orchestrator note: 84 endpoints exceeds the ~40 known-safe bound for Step 6 (memory: scaffold-endpoint-overshoot-breaks-impl-gen). Will verify implementation files on disk directly after Step 6 rather than trusting its summary.

## Step 3: Copy Shared Files — 2026-09-30T13:04:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T13:12:00.000Z

Done. PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3234_comedy_training_program_enrollment_ensemble_casting/workspace/PRD.md` — 347 lines.

**Sections:**
- 1. Introduction
- 2. Global Specifications: 2.1 RBAC (headers, 6 roles, identity semantics), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending), 2.4 Common resource properties + logical clock (pinned `2026-09-01T00:00:00Z`), 2.5 OCC (`expected_section_version` on enrollment create, `expected_cast_version` on lock-cast, both `ERR_STALE_VERSION`/412), 2.6 Money/rounding (integer cents, round half-up, final-step only; composite score 2dp), 2.7 Validation priority order + nested path resolution, 2.8 Curriculum DAG integrity, 2.9 Venue calendar (half-open intervals, 30-minute turnover buffer)
- 3. Business Logic: 3.1 Curriculum & term lifecycle (DRAFT→SCHEDULING→ENROLLMENT_OPEN→IN_SESSION→CLOSED with all section/enrollment/showcase cascades), 3.2 Instructor staffing (`ERR_INSTRUCTOR_UNAVAILABLE`), 3.3 Placement petitions (AUDITION_BYPASS vs PORTFOLIO_REVIEW, threshold 70, recognized institutions), enrollment, confirm/drop/transfer, seat-allocation waterfall (RETURNING>NEW, `created_at` asc, id forbidden), crediting, 3.4 Tuition invoices (pinned evaluation order, FIFO scholarship application), tiered refund schedule (75/50/25/0 by elapsed quarter), scholarship lifecycle, 3.5 Showcases and venue slots (grading cascade, `ERR_GRADES_INCOMPLETE`), 3.6 Cohort programs (admit/finalize/graduate/dissolve), 3.7 Auditions and weighted composite score (40/25/20/15), 3.8 Ensemble casting selector (PIPELINE_ONLY/OPEN_CALL/MIXED with +0.5 pipeline bonus), 3.9 Touring assignments and understudy coverage
- 4. Endpoint Definitions: all 84 endpoints in a 4-column table (Method, Path, Description, Authorized Roles)
- 5. Error Code Catalogue: all 29 errors in a 2-column table

**Contract verification (scripted against SCAFFOLD.yaml):**
- Field-name coverage: 81/81 entity+common fields, 70/70 endpoint input/output keys, 15/15 path params present in backticks — PASS
- Rule coverage: all 29 error IDs with HTTP statuses in prose + §5, all 54 state values, both OCC rules (write endpoint + expected-version field + error id), all state-machine transitions with preconditions/side-effects, all 7 calculations (prerequisite topological check, placement variant, tuition balance order, tiered refund, waitlist waterfall, composite weights, casting selector, slot interval/turnover rules) expressed in prose — PASS
- §3 path purity: 401 backtick tokens scanned, 0 path/method violations — PASS

Note: one verification-script artifact worth knowing — the verbatim §2.2 JSON fences shift naive backtick-pairing, so fenced blocks must be stripped before token extraction; after that, all coverage checks are clean.

Orchestrator note: 347 lines for an 84-endpoint scaffold is compact (table-driven §4/§5). Risk of Step 7 deletions from PRD under-specification noted; will watch Step 7's deletion categories.

## Step 5: Generate Unit Tests — 2026-09-30T13:45:00.000Z

All done. Summary of the generation for task_3234:

**Files written**

- `test_helpers/` — `__init__.py` (barrel export), `types.py` (18 status/role enums), `api_client.py` (`ApiClient(GenericApiClient)` with one method per PRD endpoint, including the logical-clock endpoint), `api_errors.py` (29 `ApiErrorId`s + HTTP map registered via `set_error_http_status_map`), `assertions.py` (13 per-entity shape assertions), `factories.py` (14 payload factories, input fields only), `constants.py` (portfolio threshold 70, turnover buffer 30 min, composite weights, pipeline bonus 0.5, boot clock, shared term window), `test_users.py` (shared role headers + `make_student_headers` per-instance builder for the entity-backed Student role), `fixtures.py` (composite setups: open-term-with-section, fresh-version enroll, placement grant, staged showcase, term-to-close, cast-and-fill).
- `test_suite/` — `conftest.py` + 16 test files (`test_01`–`test_16`).

**Test counts**

- Total: **67 tests**, all byte-compiled and import-checked.
- Queue A (Difficulty): **36 tests** — every one of the 18 `scaffold_difficulty_design` instances has exactly ≥2 tests (9 rules × 2 instances × 2 tests).
- Queue B (Corner): **31 tests** — every one of the 31 non-stub `scaffold_corner_design` instances has exactly 1 test.

**Skipped instances**: none. The 3 `excluded_because:` stubs (`error_section_full_on_confirm_after_capacity_reached`, `error_prerequisite_not_met_on_enroll`, `error_venue_slot_conflict`) were verified to resolve to real difficulty instances and were not translated, per spec.

**Tag compliance**: every one of the 67 test docstrings carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real yaml instances (no extras, no shortfalls, no dual tags). Every docstring's quoted PRD citation was programmatically verified to survive a whitespace-normalized verbatim match against `workspace/PRD.md` (67/67 pass; initial backtick-style mismatches against PRD markdown were fixed by quoting the PRD's exact `` `X → Y` `` arrow-chain form). No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

**Notable design decisions under the PRD-first filter**

- `state_vs_prerequisite_enroll_into_terminal_section`: PRD §2.7's fixed validation order names `ERR_INVALID_STATE` (state) ahead of prerequisite checks, so the precedence assertion is uniquely derivable and was kept.
- `ensemble_lock_cast_gates_on_venue_slot_booked`: the instance's expected `error_id` was relaxed to a 409-status assertion plus unchanged-state checks, because PRD §3.8 names `ERR_CAST_INCOMPLETE` for roster failures but no specific error for the venue-slot gate — asserting the scaffold's `ERR_INVALID_STATE` would fail the two-reader test. The roster/venue gate itself is asserted.
- `venue_slot_turnover_buffer_gap_rule` third recipe leg (30-min slot overlapping a newly created slot) was replaced with clean 15-min-reject / 45-min-accept tests, since the yaml's third assertion conflated turnover with half-open overlap and is not uniquely derivable as written.

## Step 6: Generate Implementation — 2026-09-30T14:00:00.000Z

All done. The implementation boots clean with an empty store on a fresh process.

## Summary

**File tree** (`workspace/implementation/`, 2530 total lines):

| File | Lines | Responsibility |
|---|---|---|
| start.sh | 8 | Guarded pip install + `exec python3 app.py` |
| requirements.txt | 1 | flask |
| app.py | 44 | Blueprint registration, ApiError/404/500 handlers, 0.0.0.0:$PORT |
| store.py | 71 | In-memory dicts, UUID/timestamps, logical clock (boots pinned 2026-09-01T00:00:00Z) |
| errors.py | 57 | ApiError + all 29 error IDs from PRD §5 |
| response.py | 43 | Envelope per §2.2 (meta/api_request_id/api_request_timestamp, response_type, data; pagination fields in meta) |
| middleware.py | 74 | X-User-ID/X-User-Role auth, RBAC, ownership, limit/offset parsing |
| services.py | 326 | Prereq DAG + cycle check, seat-allocation waterfall, invoice/scholarship math (Decimal ROUND_HALF_UP), tiered refunds, venue conflict/turnover |
| clock.py, levels.py, terms.py, instructors.py, sections.py, students.py, placements.py, enrollments.py, venues.py, showcases.py, cohorts.py, auditions.py, casts.py, touring.py, scholarships.py, invoices.py | 21–213 each | One module per entity domain |

**start.sh boot confirmation:** verified — `bash start.sh` on a fresh process listens on `0.0.0.0:$PORT` in the foreground via `exec`, responds within 2 s, and the store is empty / clock reset on every boot (per-test-server isolation safe). No seeding anywhere.

**Endpoint checklist — all 84 rows of PRD §4 routed:**
- Clock: POST /_clock/set_current_utc (1)
- CurriculumLevel: POST, GET list, GET one (3)
- Term: POST, GET×2, open-scheduling, open-enrollment, start-session, close (7)
- Instructor: POST, GET×2 (3)
- Section: POST, GET×2, PATCH, cancel (5)
- Student: POST, GET×2 (3)
- PlacementEvaluation: POST, GET×2, begin-review, grant, deny, appeal (7)
- Enrollment: POST, GET×2, confirm, drop, transfer (6)
- VenueSlot: POST, GET×2 (3)
- ShowcaseEvent: POST, GET×2, schedule, stage, archive, cancel (7)
- CohortProgram: POST, GET×2, begin-auditions, admit, finalize-cohort, graduate, dissolve (8)
- Audition: POST, GET×2, evaluate, waitlist, reject (6)
- EnsembleCast: POST, GET×2, open-casting, cast, lock-cast, open-revue, close-revue (8)
- TouringAssignment: POST, GET×2, accept, decline, sync, replace (7)
- ScholarshipAward: POST, GET×2, award, deny, revoke (6)
- TuitionInvoice: POST, GET×2, pay (4)

**Smoke-tested flows (all correct):** cycle rejection (ERR_PREREQUISITE_CYCLE), term staffing audit + section cascades (DRAFT→OPEN, OPEN→LOCKED/RUNNING/CANCELLED, RUNNING→COMPLETED), waitlist waterfall promotion on drop, REGISTERED-drop voids invoice / CONFIRMED early-drop full refund / late-drop tiered refund (100000 → 75000 at <25% elapsed), scholarship award → auto-disburse on invoice (applied 10000, due 40000), OCC 412 on both `expected_section_version` and `expected_cast_version`, placement AUDITION_BYPASS grant with transitive `granted_level_codes` ['L2','L1'], PORTFOLIO_REVIEW threshold error, composite score 7.75 (weighted, half-up 2dp), casting selector ranking + ERR_CAST_INCOMPLETE + ERR_STALE_VERSION, understudy eligibility and tour-window validation, showcase schedule/stage/archive with slot RESERVED→BOOKED→RELEASED and COMPLETED→CREDITED + is_alumni cascade.

**One spec ambiguity resolved:** PRD defines `enrolled_count` as REGISTERED+CONFIRMED, yet confirm requires `enrolled_count < capacity` — taken literally no enrollment could ever confirm. Confirm instead checks seats occupied by *other* enrollments, which is the only reading under which both §3.3 confirm semantics and the ERR_SECTION_FULL test path are satisfiable.

**Orchestrator disk verification:** 2531 lines across 24 files confirmed via wc; 84 route decorators counted across 16 blueprint modules (matches PRD §4 exactly — no overshoot truncation); manual boot on alternate port succeeded (0.0.0.0:$PORT, unauthenticated /levels → 404 as RBAC requires). Step 6 report corroborated.

## Step 7: Run Tests and Iterate — 2026-09-30T14:25:00.000Z

All 8 parallel rounds pass 67/67. Summary:

## Summary

**Iterations run:** 3 sweeps (initial diagnosis → fixes → confirmation; final sweep clean 8/8 rounds × 67/67 tests).

**Tests deleted:** none — every failing test traced to a verbatim PRD sentence.

**Fixes applied to `test_helpers/`:**
- `factories.py::create_audition_payload` — ENSEMBLE/TOURING auditions were created without an `ensemble_cast_id`, violating PRD §3.7 ("the `ensemble_cast_id` when the target is an ensemble or a touring company"). The factory now materializes a fresh venue slot + ensemble cast via the declared endpoints when the caller doesn't supply one. This fixed 4 tests (composite-score tests and `test_registrar_cannot_evaluate_audition`) that died with `ERR_NOT_FOUND` before their assertions ran.

**Fixes applied to `test_suite/`:**
- 23 call sites across 13 files: `validate_success(api_client.create_*())` was asserting the helper's default 200 on POST create endpoints; PRD §4 states verbatim "Endpoints that create a new resource respond with 201". Added the explicit `, 201` expected status (several sites already had it, proving the pattern).
- `test_16_rbac_and_crosscutting.py::_touring_setup` — used `capacity=4`, which under the corrected seat semantics leaves the section LOCKED (not RUNNING) at start-session, so the understudy never became `is_alumni` and tour proposal failed with `ERR_UNDERSTUDY_INELIGIBLE`. Changed to `capacity=1` so the CONFIRMED enrollment fills the section per PRD §3.1 ("a section already LOCKED whose `enrolled_count` has reached `capacity` advances LOCKED → RUNNING").

**Fixes applied to `implementation/`:**
- `services.py::recompute_section_counts` — `enrolled_count` counted REGISTERED+CONFIRMED; PRD's event deltas (confirm +1, drop −1, waterfall leaves it unchanged until the promoted student confirms) uniquely require seats to be held only by CONFIRMED. Changed to count CONFIRMED only. This fixed the waterfall (`test_drop_promotes_waitlisted_back_to_registered`) and the capacity-boundary pair.
- `enrollments.py::confirm` — replaced the bespoke "others in REGISTERED/CONFIRMED" capacity check with the recomputed `enrolled_count >= capacity` (CONFIRMED-held seats), so a promoted student can confirm after a drop while a second confirm at capacity gets `ERR_SECTION_FULL`.
- `enrollments.py::drop` / `transfer` — recompute counters after `seat_allocation` so a promotion's waitlist_count decrement is persisted on the section.
- `enrollments.py::create_enrollment` — added the §2.7 state gate (section must be OPEN) before the OCC and prerequisite checks, so enrolling into a CANCELLED section surfaces `ERR_INVALID_STATE` rather than `ERR_PREREQUISITE_NOT_MET`.
- `scholarships.py::revoke` — a DISBURSED award with non-zero `disbursed_cents` now surfaces `ERR_SCHOLARSHIP_NOT_REVOCABLE` (the §3.4 sentence the revoke rule exists for) instead of `ERR_INVALID_STATE`.
- `cohorts.py::admit` — the min-track-level floor now also accepts `placement_credit_codes` (PRD §3.6 "must have completed"; placement credits are advanced standing for exactly the required level, consistent with §3.3 enrollment semantics).
- `cohorts.py::create_cohort` / `touring.py::_understudy_ok` — cohorts record their track (`_track`) so the cast's track can be resolved through cohort membership for the §3.9 understudy coverage predicate ("CREDITED enrollment in the cast's track"); falls back to any CREDITED enrollment when no cohort linkage exists.

**Orchestrator verification:** all 8 results.{1..8}.json read from disk: 67 passed / 0 failed / 67 total in every round. Step 8 is REQUIRED (implementation/ fixes were non-zero).

## Step 8: Finalize PRD — 2026-09-30T14:35:00.000Z

All 5 edits are in place. Done.

## Summary

**Line counts**: PRD.md 346 lines, PRD_FINALIZED.md 346 lines (0% delta — all edits are in-place sentence revisions/insertions within existing paragraphs; no new sections).

### Changes

- **§3.2** — revise — `enrolled_count` redefined from "enrollments in `REGISTERED` or `CONFIRMED`" to "enrollments in `CONFIRMED` — a seat is held only from confirmation onward" — impl: services.py:74-89 (`recompute_section_counts`).
- **§3.1** — revise — start-session sweep wording changed from "at least one enrolled student" / "zero enrolled students" to "`enrolled_count` at least 1" / "`enrolled_count` zero", tying the LOCKED/CANCELLED branch to the CONFIRMED-only counter — impl: terms.py:98-106.
- **§3.3 (Enrolling)** — insert — state gate: target section must be `OPEN`, else `ERR_INVALID_STATE`, running before the `expected_section_version` comparison and before prerequisite/capacity business rules — impl: enrollments.py:49-54.
- **§3.6 (admit)** — revise — min-track-level floor now reads "the union of the student's `completed_level_codes` and `placement_credit_codes` contains the cohort's `min_track_level_code`" — impl: cohorts.py:110-112.
- **§3.9 (understudy coverage)** — insert — defines the previously undefined "cast's track": casts carry no track field; the track is resolved through cohort membership (track of any cohort that admitted the understudy); with no cohort linkage, any `CREDITED` enrollment qualifies — impl: touring.py:23-47, cohorts.py:48-51 (`_track`).

### Step 7 items requiring no PRD edit (verified)

- Audition factory `ensemble_cast_id` — PRD §3.7 already pins it verbatim (fixture bug).
- 201 on create endpoints — PRD §4 already states it verbatim (test bug).
- `_touring_setup` capacity — PRD §3.1 already pins LOCKED→RUNNING at capacity (fixture bug).
- `scholarships.py::revoke` — PRD §3.4 already pins both the AWARDED→REVOKED state gate and `ERR_SCHOLARSHIP_NOT_REVOCABLE` for non-zero `disbursed_cents`; impl matches (impl-only fix).
- drop/transfer recompute ordering — internal persistence detail with no observable behavior beyond the counter semantics already pinned.

### Per-edit pre-edit search log

1. **§3.2 counter redefinition** — (a) subject: `enrolled_count` semantics; (b) enumerated: services.py:74-89 (recompute), enrollments.py:62/118/189 (create/confirm/transfer capacity checks), terms.py:100/111 (start-session), sections.py:57 (init), services.py:92-104 (seat_allocation), plus every PRD event-delta sentence (§3.3 confirm +1, drop −1, waterfall unchanged); (c) added the explicit "REGISTERED and WAITLISTED never occupy a seat" clause so §3.3's waterfall sentence ("`enrolled_count` does not change until the promoted student confirms") and the REGISTERED-drop path (no count change) stay consistent.
2. **§3.1 start-session** — (a) subject: OPEN-section branch predicate; (b) enumerated: terms.py:87-119 full sweep (both passes), cancel_section_cascade; (c) reworded to reference `enrolled_count` directly rather than "enrolled student" so the new counter definition binds unambiguously.
3. **§3.3 enrolling state gate** — (a) subject: create-enrollment check ordering; (b) enumerated: enrollments.py:33-78 (auth → fields → owner → not-found → esv type → state → OCC → priority → prereq → capacity); (c) scoped the ordering claim to "before the `expected_section_version` comparison and before the prerequisite and capacity business rules" — exactly what impl exhibits — without asserting anything about checks PRD leaves unordered (e.g. body validation).
4. **§3.6 admit floor** — (a) subject: `min_track_level_code` evaluation; (b) enumerated: cohorts.py:30/46/110-112 (only touchpoints of the field), cross-checked §3.3's prerequisite union semantics; (c) added the "placement credits count as advanced standing … exactly as they do for the §3.3 prerequisite check" clause to tie the two union-semantics sites together without redefining either.
5. **§3.9 cast-track resolution** — (a) subject: "CREDITED enrollment in the cast's track" predicate; (b) enumerated: touring.py:23-47 helper plus all three call sites (create:81, accept:128, replace:178), cohorts.py:48-51 `_track` recording; (c) worded the resolution as keyed on the *understudy's* cohort admissions (not the cast's members), with the no-linkage fallback to any CREDITED enrollment, matching the helper exactly.

## Step 9: Complete PRD — 2026-09-30T14:50:00.000Z

Diff is 80 lines (all in-paragraph edits, no sections added). Done.

## Summary

**Source vs completed:** `PRD_FINALIZED.md` 346 lines / 50,395 chars → `PRD_COMPLETED.md` 346 lines / 53,856 chars (+3,461 chars, +0 lines — every change is an in-paragraph insert/revision, no new sections).

**Counts:** 21 changes total — 20 ambiguity-pins, 1 mismatch-revision.

**Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.1 — insert — ambiguity — student cross-owner access = `ERR_UNAUTHORIZED_ROLE`; Student reading an unrelated touring assignment = `ERR_NOT_FOUND` — middleware.py:28-31, touring.py:114-115
- §2.7 — revise — ambiguity — OCC `expected_section_version` check on enrollment runs immediately after the section state gate, before prerequisite check — enrollments.py:51-54
- §2.9 — insert — ambiguity — `AVAILABLE`/`RELEASED` slots participate in neither overlap nor turnover checks — services.py:316
- §3.1 — insert — ambiguity — start-session also cascades cohorts `CASTED → ACTIVE`; auto-created showcase born with `venue_slot_id` null; non-showcase-required sections credit enrollments directly at term close — terms.py:114-118, 145, 153-156
- §3.2 — insert — ambiguity — instructor load excludes `CANCELLED`/`COMPLETED` sections and the section being patched — sections.py:22-25
- §3.3 (students) — insert — ambiguity — duplicate email rejected with `ERR_INVALID_REQUEST` 400 — students.py:20-22
- §3.3 (placement) — insert — ambiguity — four recognized institutions spelled exactly: `iO`, `UCB`, `Groundlings`, `Second City (other campus)` — placements.py:14
- §3.3 (dropping) — insert — ambiguity — early vs late is `now <= drop_deadline_utc` (deadline instant is early) — services.py:248-249
- §3.3 (transferring) — revise — mismatch — a full target section rejects the transfer with `ERR_SECTION_FULL`; no waitlist-on-transfer path exists — enrollments.py:189-190
- §3.3 (transferring) — insert — ambiguity — carried payments make the new invoice born `PAID`/`PARTIALLY_PAID`; source `priority_tier` carried over — services.py:168-171, enrollments.py:203
- §3.3 (crediting) — insert — ambiguity — `completed_level_codes`/`placement_credit_codes` are sorted, de-duplicated, recomputed on each mutation — services.py:263, placements.py:117
- §3.4 — insert — ambiguity — each award covers at most the invoice's uncovered base balance and its own remaining balance — services.py:137-140
- §3.4 — revise — ambiguity — refund sets `refunded_cents = paid_cents` exactly; clawback returns scholarship to awards newest-first — services.py:196, 206-224
- §3.4 — insert — ambiguity — award-time disbursement cascade to outstanding invoices; revoke checks non-zero `disbursed_cents` before the `AWARDED` state gate — scholarships.py:74-85, 107-110
- §3.5 — insert — ambiguity — showcase `venue_slot_id` nullable while `PLANNED` — showcases.py:37-39, terms.py:145
- §3.6 — insert — ambiguity — admit requires audition `target_kind=COHORT`, this cohort, outcome `EVALUATED`/`WAITLISTED` — cohorts.py:101-104
- §3.6 — insert — ambiguity — graduate requires the cohort's term `CLOSED` — cohorts.py:140-142
- §3.7 — revise — ambiguity — rubric dimension keys pinned exactly: `scene_work`, `characters`, `musicality`, `game` — auditions.py:11
- §3.8 — revise — ambiguity — pipeline student = has a `CREDITED` enrollment AND admitted to a `CONSERVATORY` cohort; `ERR_SOURCE_POLICY_VIOLATION` only when pool non-empty but all ineligible; empty pool = `ERR_NO_ELIGIBLE_AUDITIONS` — casts.py:23-39, 111-120
- §3.8 — revise — ambiguity — OCC check precedes roster/venue checks at lock; unbooked opening-night slot also fails with `ERR_CAST_INCOMPLETE` — casts.py:156-162
- §3.9 — insert — ambiguity — `DECLINED`/`REPLACED` tours impose no window exclusion — touring.py:56-57

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_3234_comedy_training_program_enrollment_ensemble_casting/workspace/PRD_COMPLETED.md`

## Pipeline complete — 2026-09-30T14:55:00.000Z

All 9 steps done. Final state: 67/67 tests passing across all 8 stability rounds; PRD_COMPLETED.md is the final contract document.







