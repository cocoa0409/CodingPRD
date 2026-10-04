# Worklog — task_3381_charter_candidate_progression_exam_windows_experience_verification

## Step 1: Create Task Directory — 2026-10-01T12:05:00.000Z

Task directory `./tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/` was pre-allocated by the invoker (index 3381 pinned; no index computation performed). Verified it exists with an empty `workspace/` subdirectory. No other `task_*` directory created.

## Step 2: Generate Scaffold — 2026-10-01T13:41:00.000Z

All three artifacts are complete, lint-clean, and self-consistent. Final summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rules × 2 instances = 18
- `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 70 real instances + 15 `excluded_because` stubs across all 9 guide sections

## Counts

- **13 entities** (Candidate, ProgramEnrollment, ExamLevel, CurriculumCycle, ExamWindow, TestCenter, ExamAppointment, ExamAttempt, WorkExperienceSubmission, ReferenceContact, MisconductCase, Society, SocietyMembership)
- **48 endpoints** (incl. `POST /_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default), **65 errors**, **7 roles**, **9 state machines**, **11 calculations**, **13 ordered validation priorities**, **3 OCC concurrency rules**
- Lint: `VERDICT: clean lint` — 1109 setup/trigger calls across both design files verified against §1.5 (endpoint/role/payload/capture/OCC/FK-reverse-reachability)
- Additional mechanical checks passed: no forbidden race vocabulary, all `grounds:` resolve, 103 unique instance names, enum closure, every error referenced, every role declares `identity:`

## Notable design decisions

- **Archetypes**: temporal windowing (primary) + compliance/audit (secondary), with layers optimistic-concurrency, cascading-side-effects, dual-variant-calculation, rate-threshold-triggers; graph topology; segregation-of-duties role model (case investigator ≠ adjudicator by X-User-ID; references are entity-backed `ReferenceProvider` acting as their own `ReferenceContact` id so candidates can never self-verify).
- **Dual-variant calcs on three domains**: experience months (cumulative 47 vs interval-merged contiguous 41 on overlapping segments), CE standing (calendar-year 21 vs rolling-365-day 26), eligibility pathways (education 23-month window vs work 36-month/4000-hour conjunction).
- **Combinatorial calcs in distinct modes**: reschedule fee (branch + `min(count,2)` + 60000 cap; worked 50000/60000/60000 fixture), scholarship per-line round-half-up vs sum-then-round (121499 vs 121498 — differ by exactly one cent), plus a pinned evaluation-order retake rule (passed-set → cap → strict retake gap).
- **Cascades**: EXAM_INVALIDATION sanction → attempt invalidation → progression downgrade → curriculum access shrink (depth 3); window cancel → appointment cancel → ledger credit → auto-drawn rebook (depth 2).
- **Key boundary pins**: MPS `>=` (700 passes, 699 fails), seat exactly-full, early-fee deadline inclusive, retake requires target window open *strictly after* the failed window's close (adjacent windows legal to create but too soon for retakers), appeal window inclusive at +30 days, reference lazy expiry at +30 days.
- **Endpoint budget management**: the lint's FK reverse-reachability check (f) derives collection segments only from `GET /<prefix>/<segment>/{id}` single-resource endpoints, so I added 9 GET-single endpoints and offset the count by embedding the append-only professional-conduct statement into `Candidate.conduct_statements` (dropping a separate entity + its list endpoint). 48 endpoints is above the Expert guideline band but each FK relation is provably reachable.
- **Bug caught in self-review**: fixed an arithmetic slip (lifetime charges 309003 → 299003) in the reschedule-fee instance and a window-deadline ordering constraint that would have made `ERR_RETAKE_WINDOW_TOO_SOON` unreachable (scheduling deadline is `<= window_closes_at`, not `<= window_opens_at`, so post-failure bookings into a later window can pass the temporal gate and reach the retake check).

Orchestrator verification: all three files exist on disk, parse as YAML, top-level keys as specified, `api_prefix: /charter`, 400 domain-token matches (cfa/charter/candidate/exam/curriculum/work experience/society) — no foreign-domain bleed.

## Step 3: Copy Shared Files — 2026-10-01T13:42:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T13:55:00.000Z

PRD generation complete. All three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/workspace/PRD.md` — 378 lines.

**Section list:**
- §1 Introduction (2 paragraphs: gate-credibility framing + logical-clock/recompute/segregation commitments; `/charter` mount)
- §2 Global Specifications — 2.1 RBAC (7 roles, per-role identity prose: `Candidate`→entity-backed `Candidate`, `ReferenceProvider`→entity-backed `ReferenceContact`, five opaque roles with recorded-field notes); 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified by substring check); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, four `meta` fields); 2.4 The Program's Logical Clock (starts `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`, lazy-expiry semantics); 2.5 Common Resource Properties; 2.6 The Validation Pipeline (all 13 scaffold priority stages in order with every error ID mapped to its stage); 2.7 OCC (all 3 rules: `expected_appointment_version` / `expected_submission_version` / `expected_case_version` → `ERR_STALE_VERSION` 412, checked after ownership before business rules); 2.8 Enrollment Ledger (per-line half-up rounding before summing, credit auto-apply both directions, seven ledger fields, money gates 402/422); 2.9 Precision & Calendar Conventions (integer cents, whole-calendar-months formula in prose, 1-decimal credit hours, half-open windows); 2.10 Progression, Curriculum Access & Cascade Discipline
- §3 Business Logic — 9 subsections grouped by candidate lifecycle: 3.1 registration/eligibility/enrollment/payments, 3.2 levels/cycles/windows/centers, 3.3 booking (pinned 5-step retake chain, seat accounting, fee-tier boundary), 3.4 reschedule (OCC, tiered fee with all 6 constants + worked examples) & cancel & window-cancel cascade, 3.5 check-in/scoring/publication (identity-before-calculator, MPS boundary, no-show sweep ordering reconciled across scaffold statements), 3.6 experience (cumulative vs interval-merged variants + 47/41 worked example, reference lazy expiry), 3.7 conduct/misconduct (origins, SoD, 4 sanction cascades, appeal, dismissal compensation incl. non-restored memberships), 3.8 charter award (6 gates in order), 3.9 societies/membership/CE (calendar vs rolling variants + 21/26 worked example)
- §4 Endpoint table: 48 rows, 4 columns (Method/Path/Description/Authorized Roles), 201-vs-200 rule paragraph
- §5 Error catalogue: 65 rows, 2 columns; normative statuses from the scaffold catalog preserved (notably `ERR_WINDOW_NOT_CONCLUDED` 409, `ERR_OPEN_MISCONDUCT_CASE` 409, `ERR_OUTSTANDING_BALANCE` 402, `ERR_INCORRECT_DUES_AMOUNT` 422)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 115 required field/input/query names — 115 present, 0 missing; 12/12 path params present. PASS (verified mechanically against parsed SCAFFOLD.yaml)
- Contract 2 (Rule Coverage): validations priority (13 stages) expressed; 3/3 OCC rules with write-capability + field + error id + 412; all 30+ state transitions with preconditions/side-effects; 11/11 calculations in precise prose with all 15 constants embedded (fixed two word-form numbers to digits); 65/65 error IDs and 36/36 state values present in narrative; sibling branches (pathways, months variants, CE variants, sanction types, decisions) at equal density. PASS
- Contract 3 (§3 Path Purity): 476 backtick tokens scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS

**Coverage notes:** scaffold sections map as §1.1 entities → §2.5 + §3 narratives; §1.2 state machines → §3 (workflow-framed, no paths); §1.2.1 concurrency → §2.7 + endpoint subsections; §1.3 calculations → §2.8/2.9/2.10 + §3 worked examples; §1.4 validations → §2.6 pipeline + per-workflow triggers; §1.0 envelope → §2.2/2.3; §1.5 endpoints → §4; §1.6 errors → §5; §1.7 roles → §2.1. No fuzzy/approximating words or operator syntax in §2/§3 prose (mechanically verified). The difficulty/corner design files were not opened.

Orchestrator verification: PRD.md exists on disk, 378 lines, 27 headings.

## Step 5a: Generate Test Helpers (Phase A of split Step 5) — 2026-10-01T14:10:00.000Z

The `find` match on `test_users.py` is just the name pattern — it is a mandated helper module, not a pytest file. No `test_suite/` directory exists. Phase A is complete and verified.

---

## Phase A complete — test_helpers/ frozen for task_3381

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/test_helpers/`)

| File | Contents |
|---|---|
| `__init__.py` | Barrel export: framework generics + full PRD-specific surface |
| `types.py` | 23 str-enums (7 roles, all status/vocabulary sets), 13 entity TypedDicts (all entities carry id/created_at/updated_at/version per PRD §2.5), 4 sub-structure TypedDicts |
| `api_client.py` | `ApiClient(GenericApiClient)` with 48 endpoint methods (one per PRD §4 row) + module-level `api_client` |
| `api_errors.py` | `ApiErrorId` with all 65 error IDs; `HTTP_STATUS_CODES` per PRD §5; registered via `set_error_http_status_map` at import |
| `assertions.py` | 13 `assert_<entity>()` shape checks, `assert_experience_segment_shape`, `assert_enrollment_ledger_invariants` (net_billed identity exact, outstanding = max(0, charges−payments−credits_applied)), plus 5 PRD-formula oracles: `months_between`, `compute_provisional_months`, `compute_committee_months`, `compute_reschedule_fee_cents`, `compute_ce_credit_totals` — all validated against the PRD's own worked examples (47/41, 21/26, 50000/60000/60000/25000, 31503/89996) |
| `factories.py` | `DEFAULTS` (canonical scenario values) + 25 payload factories, input fields only; enrollment factory fills pathway-conditional fields per branch |
| `constants.py` | 27 PRD-prose-derived constants, each with a §-citation (clock start 2026-09-01T00:00:00Z, program fee 35003, 23/36/4000 eligibility, reschedule card 25000/14/25000/10000/2/60000, pct 50, refs 2, 30-day expiry/appeal, 365-day suspension/rolling, 36 charter months, CE default 20, pagination 10/1/100/0, calculator pair, level order) |
| `test_users.py` | `TEST_USERS` (7 shared header sets) + `make_<role>_headers(user_id)` builders for all 7 roles — entity-backed builders for Candidate/ReferenceProvider are mandatory-path, opaque builders exist so SoD tests can mint distinct inv-1/adj-2 IDs |
| `fixtures.py` | 50 helpers: clock, single-entity creators, readers/listers, `setup_bookable_context`, `book_appointment`, `check_in_appointment`, `score_attempt`, `book_checkin_score`, `setup_scored_appointment`, submission/reference chain (`setup_approved_submission` defaults to the 41-committee-month segment pair), `setup_charterholder` (full 3-level pass → APPROVED experience → PCS → award), `setup_active_membership`, misconduct chain (`open_external_case`, `open_incident_case`, `adjudicate_case`, `appeal_case`), `expected_charge_cents` (Decimal half-up per-line) |

Every module opens with a frozen API manifest comment block. Identity threading is enforced inside fixtures (candidate calls use `make_candidate_headers(candidate["id"])`, reference responds use the reference's own id).

### Verification
- `python3 -m py_compile` on all 9 modules: OK
- `python3 -c "import test_helpers"` from task dir and from foreign cwd with sys.path: OK (no import-time HTTP; error map registered)
- No `test_suite/` or `test_*.py` files created (Phase A only)
- Oracle functions reproduce every PRD worked example exactly

### Instance counts Phase B must cover
- **Queue A (difficulty, §1.8): 18 instances** — 9 rules × 2; each needs ≥2 tests → **≥36 tests**
- **Queue B (corner, §1.9): 85 instances total, 70 non-stub** needing ≥1 test each; **15 `excluded_because:` stubs** — all 15 stub cross-references verified to resolve to real difficulty instance names (broken-pointer count: 0)
- Non-stub breakdown: entities 10, state_machines 9, calculations 4, validations 4, endpoints 1, errors 30, rbac 6, cross_cutting_layers 6, consistency_model 0

### PRD/scaffold discrepancies resolved in favor of PRD
1. **`ERR_WINDOW_NOT_CONCLUDED` → 409.** The scaffold validations table (§1.4 priority-9 group) displays 422, but PRD §5's normative catalogue says 409 (scaffold §1.6 errors table agrees). Frozen as 409.
2. **`ERR_OPEN_MISCONDUCT_CASE` → 409** (PRD §5; the scaffold's priority-12 group header shows 422 but §1.6 agrees with PRD).
3. **`ERR_INCORRECT_DUES_AMOUNT` → 422** despite living under the fiscal group whose header says 402 (PRD §5 and the scaffold's own note agree).

All other 62 error statuses agree across PRD §5 and scaffold §1.6. Clock-start consistency: both pin 2026-09-01T00:00:00Z, and every fixture chain begins by setting the clock forward to 2027-01-05 — no clock-unreachable setup. No numeric literal in `constants.py` comes from the design indices; each was diffed against PRD prose.

Orchestrator verification: all 9 modules on disk, `import test_helpers` succeeds, no test_suite/ directory yet (Phase A purity confirmed).

## Step 5b: Generate Test Suite (Phase B of split Step 5) — 2026-10-01T14:55:00.000Z

Phase B is complete. All verification passes.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/test_suite/`):

| File | Tests | Content |
|---|---|---|
| `conftest.py` | — | session `api` fixture + 7 role-header fixtures |
| `test_01_candidate_registration.py` | 5 | creation defaults, read round-trip, 404, system-field rejection, duplicate email |
| `test_02_enrollment_and_eligibility.py` | 10 | request shape, pathway eligibility (23-month boundary, work months×hours), initial state, payments, ownership, curriculum access |
| `test_03_levels_windows_centers.py` | 5 | level uniqueness, cycle supersede+duplicate year, role-before-shape, proctor denial, cancelled-window booking |
| `test_04_booking_and_rescheduling.py` | 10 | retake chain (prerequisite/cap/gap/already-passed), double booking, scheduling deadline, pagination, level-mismatch retarget, day-14 fee boundary, OCC reschedule |
| `test_05_exam_day_scoring_and_cancellation.py` | 11 | check-in date/identity/calculator, attempt side effect, scoring guards, no-show sweep, window publish, cancel semantics |
| `test_06_experience_and_references.py` | 12 | months precision, sub-50% exclusion, revision cycle, state gates, reference gates, lazy expiry, reference identity, OCC amend |
| `test_07_conduct_cases.py` | 8 | PCS uniqueness + auto-open, incident origin forcing, one-case-per-appointment, role denial, SoD, appeal window, OCC adjudicate |
| `test_08_award_and_membership.py` | 9 | all five award gates + dues/duplicate/CE-renewal/revocation-cascade |
| `test_20`–`test_28_difficulty_*.py` | 36 | 9 files, one per difficulty rule, 2 tests per instance |

**Coverage:** queue A 18/18 instances × ≥2 tests (36); queue B 70/70 non-stub instances × ≥1 test (70). **Skipped instances: none** — every non-stub instance passed the PRD-first filter.

**Notable translation decisions:**
- `misconduct_case_sanction_appeal_cycle`: `suspended_until` asserted by parsed-instant comparison (== 2028-03-19T00:00Z, the sanction instant + 365 days spanning the 2028 leap day) rather than raw string equality — PRD pins the instant, not the serialization format.
- `c_candidate_create_with_system_fields_rejected`: the instance's "no candidate with that email exists" sub-assertion is unobservable (PRD §4 has no list-candidates endpoint); the primary 400 `ERR_INVALID_REQUEST` claim is emitted.
- Both priority-pair difficulty instances got complementary-leg second tests (e.g. capacity error reachable once the temporal gate passes), same tag.
- Frozen helper gaps composed inline, per instructions: `get_exam_attempt` (no fixture reader exists — composed via `api.get_exam_attempt` + `validate_success`), and the charter-ready-but-unawarded chain (composed from `book_checkin_score`/`setup_approved_submission`/`file_conduct_statement` in test_08 and test_26).

**AST tag audit** (real `ast` parse of every test function, diffed against both parsed YAML indices): 106 tests emitted; orphan tags 0; untagged/multi-tagged 0; every `PRD §x.y: "..."` quotation survives whitespace-normalized containment in PRD.md (0 citation failures).

**`pytest --collect-only -q`: 106 collected, 0 errors.** pyflakes clean. `test_helpers/` untouched (all module mtimes still Phase A's 14:19–14:35).

Orchestrator verification: 19 files in test_suite/ (conftest + 9 corner + 9 difficulty), `pytest --collect-only` from repo root collects 106 tests, 0 errors.

## Step 6: Generate Implementation — 2026-10-01T16:10:00.000Z

Done. Implementation complete and smoke-tested.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/workspace/implementation/`):
- `start.sh` (executable, guarded pip install, `exec python3 app.py`, PORT/0.0.0.0/foreground)
- `requirements.txt`, `app.py` (Flask app + error handlers), `store.py` (in-memory dicts + logical clock defaulting to 2026-09-01T00:00:00Z), `errors.py` (full PRD §5 catalog with normative statuses: ERR_WINDOW_NOT_CONCLUDED/ERR_OPEN_MISCONDUCT_CASE → 409, ERR_INCORRECT_DUES_AMOUNT → 422), `util.py` (envelope, auth, shape validation, pagination), `domain.py` (ledger, progression/curriculum recompute, retake chain, fees, seats, blackouts, months variants, serializers), `routes_a.py` (clock, candidates, enrollments, levels, cycles), `routes_b.py` (windows, centers, appointments, attempts), `routes_c.py` (submissions, references, conduct statements, cases, societies, memberships)

**Endpoints:** all 48 from PRD §4 implemented; validation pipeline stages 1–13 per PRD §2.6 (headers → role → path ids → shape → body FKs → ownership → OCC → state → clock → safety → capacity/uniqueness → referential → money). In-memory only, zero seeding; verified fresh state across reboots.

**Boot smoke-test:** 3 fresh boots on self-chosen ports (18371/18372/18374), each killed by its exact saved PID. Verified: envelope shape, auth 400/404s, full lifecycle (enroll → pay → ENROLLED → book EARLY tier → check-in → score-gate 409 before close → boundary PASS at MPS → window auto-publish → COMPLETED → progression LEVEL_I), per-line half-up rounding (99995×0.9→89996), OCC 412, reschedule fee cap (25000 then 60000), window-cancel credit cascade (credit 89996, applied 60000, remainder to credit_balance, reschedule fees never credited).

**Interpretations chosen:**
- `created_at`/`updated_at` read the logical clock (fee-tier and deadline rules depend on them); `meta.api_request_timestamp` uses wall clock.
- `version` starts at 1; cascaded/derived-field changes bump version only when the value actually changes; side-effect transitions (check-in, no-show, sanction cascades) always bump.
- Ledger kept as running balances: overpayments raise `credit_balance_cents` (PRD "overpayments land here as well" — literal scaffold formula `posted − applied` doesn't cover overpayment); reduces to the scaffold formulas when no overpayment exists.
- `GET /charter/curriculum-cycles/{id}` 404 maps to `ERR_EXAM_LEVEL_NOT_FOUND` — the catalog defines no cycle-specific NOT_FOUND id and cycles live under levels.
- Appointments list `status` filter treated as alias for `booking_status` (the entity has no literal `status` field).
- Auto-opened conduct-statement case uses `disclosure_text` (or `""`) as `allegation`; `reviewer_notes`/`attestation_text` accepted but not stored (no entity field).
- Reference lazy expiry: computed on reads/gates; the stored status flips (with version bump) only on a late respond, per the state machine.
- Dismissal compensation reverses only what *that case* caused (tracked per-case: invalidated attempt ids, suspension, revocation) rather than unconditionally clearing candidate flags.
- Out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (PRD declares min 1 / max 100 but no dedicated error).
- Cross-pathway enrollment fields (e.g. `declared_work_months` on EDUCATION) are type-validated and stored but ignored for eligibility.
- New case on an appointment whose compliance is `CLEARED` (post-dismissal) re-flags to `POLICY_FLAGGED`; window overlap checked against all windows of the level regardless of status (no PRD carve-out).
- Clock setter accepts any instant (PRD says "advances" but states no monotonicity guard); CE-record append not gated on ACTIVE (no PRD gate stated); ENROLLED-with-all-levels-passed (pre-award) sees all PUBLISHED cycles (no unpassed level exists).

Orchestrator verification: 48 unique `@bp.{get,post}` routes on disk (19 GET + 29 POST) matching PRD §4; independent boot on port 19871 — candidate create 201 with envelope, clock set 200; killed exact saved PID. NOTE for Step 7: this scaffold has 48 endpoints (>40 overshoot band) — treat the subagent report as claims, verify fixes on disk.

## Step 7: Run Tests and Iterate — 2026-10-01T16:25:00.000Z

Clean 8-round parallel sweep: **106/106 passing in every round**, all 8 `results.*.json` artifacts left in `workspace/implementation/`.

## Summary

**Iterations run:** 2 (sweep 1: 104/106 ×8 rounds, identical 2 failures everywhere — deterministic, not flaky; sweep 2 after fix: 106/106 ×8 rounds).

**Tests deleted:** none. Both failing tests assert PRD-verbatim rules (PRD §3.3 retake-eligibility chain steps 4 and 5, quoted in their docstrings) with unique derivability — coverage and derivability both held, so they stayed.

**Fixes applied to `test_suite/`** (test bug, STEP 2 — fixture inconsistent with PRD):
- `/home/ubuntu/github/CodingPRD/tasks/task_3381_charter_candidate_progression_exam_windows_experience_verification/test_suite/test_04_booking_and_rescheduling.py` — module-level window fixtures `LATER_WINDOW_N` and `LATER_WINDOW_L` violated PRD §3.2 verbatim: *"`scheduling_deadline_at`, which must fall no later than the window's opening … `early_fee_deadline_at`, which must fall no later than the scheduling deadline"* (WN had scheduling 2027-03-20 > opens 2027-03-15; WL had scheduling 2027-04-01 > opens 2027-03-29). The implementation correctly rejected both windows with 400 `ERR_INVALID_REQUEST` at creation, so setup died before either test reached its asserted gate. Fixed `scheduling_deadline_at` to equal each window's opening (WN 03-15, WL 03-29), keeping early ≤ scheduling ≤ opens < closes and reschedule ≤ closes. The boundary instants are pinned, not chosen: WN's opening must equal the failed attempt's window close (non-overlap forces ≥, the "not strictly later" retake assertion forces ≤), which in turn forced the retake test's `score_clock` from `2027-03-16` to `2027-03-15` — scoring requires clock ≥ window close while the booking must occur ≤ WN's scheduling deadline, and 03-15 is the unique instant satisfying both. The EARLY-fee assertion on the successful WL booking is preserved (booking clock 03-15 ≤ WL early_fee_deadline 03-20).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation's window-invariant checks (`sched ≤ opens`, `early ≤ sched`, `resched ≤ closes`, `opens < closes` in `routes_b.py:create_window`) are the PRD-faithful behavior that exposed the fixture bug, and were left untouched per the cardinal rules.

Orchestrator verification: all 8 results.*.json on disk, each passed=106 total=106 failed=0. Step 8 NOT skipped (1 test_suite fix occurred; 0 implementation fixes).

## Step 8: Finalize PRD — 2026-10-01T16:28:00.000Z

**Done. PRD_FINALIZED.md is byte-identical to PRD.md — zero edits owed.**

**Line counts / delta:** PRD.md 378 lines; PRD_FINALIZED.md 378 lines; 0% delta (verified with `diff -q` → BYTE-IDENTICAL).

**Changes:** none.

**Why no edits — verification log for the single `<step_7_diff>` item** (test_04 fixture fix; no impl fixes, no deletions, no helper fixes):

- **(a) Subject:** window deadline invariants — `scheduling_deadline_at ≤ window_opens_at`, `early_fee_deadline_at ≤ scheduling_deadline_at`, `reschedule_deadline_at ≤ window_closes_at` — plus the retake-gap interaction that forced the `score_clock` move (2027-03-16 → 2027-03-15).
- **(b) Impl paths enumerated and read:**
  - `workspace/implementation/routes_b.py` — `create_window` lines 20-54 (invariant checks at 33-40: `opens < closes`, `sched <= opens`, `resched <= closes`, `early <= sched`, each `fail('ERR_INVALID_REQUEST')`); `create_appointment` lines 150-200 (scheduling-deadline gate at 168, exam-date half-open gate at 171, retake chain call at 186, fee-tier `now() <= early_fee_deadline_at` at 189); reschedule gates 273-279; cancellation credit 324-326; results-publish gate 406.
  - `workspace/implementation/domain.py` — `window_view` 93-97; `_retake_gap` 330-339 (`not (target_opens > failed_closes)` → `ERR_RETAKE_WINDOW_TOO_SOON`, i.e. "strictly after", matching PRD §3.3 verbatim).
  - PRD §3.2 line 169 states all three deadline invariants **verbatim** ("must fall no later than the window's opening" / "no later than the window's close" / "no later than the scheduling deadline"); PRD §2.6 stage 4 (line 100) pins `ERR_INVALID_REQUEST` for request-shape violations; PRD lines 177/183/191/197 pin every downstream use of these deadlines (booking gate, fee tier with equality-books-early, reschedule gates, cancellation credit timing).
  - Test file `test_suite/test_04_booking_and_rescheduling.py` lines 41-59 (fixed fixtures now carry a comment citing PRD §3.2) and 167-201 (retake test; comment explains the score_clock must satisfy the scheduling-deadline gate to reach the retake gate).
- **(c) Wording adjustment:** none. The PRD already determines every behavior the fix touched: the invariants are verbatim, the equality boundary ("no later than" = `<=`) matches the impl operators and is exactly what the corrected fixtures exercise (deadline == opening accepted), the error code is pinned by §2.6 stage 4, and the `score_clock` move is pure test sequencing (stage-9 clock gate must pass before the stage-12 retake gate fires — pipeline order already fixed by PRD §2.6/§3.3). Step 7's own note concurs: "Pure fixture bug — the implementation's ERR_INVALID_REQUEST rejection was PRD-faithful." Any added wording would only risk a NO-NEW-MISMATCH violation, so PRD prose was kept verbatim throughout.

**File written:** `workspace/PRD_FINALIZED.md` (copy of PRD.md, unmodified). No other files touched.

Orchestrator verification: `diff -q` confirms BYTE-IDENTICAL; implementation/*.py mtimes all ≤16:05 (pre-sweep 16:24) — implementation untouched by Step 8.

## Step 9: Complete PRD — 2026-10-01T16:45:00.000Z

All edits verified in the diff — exactly the intended 17 line-level changes plus one added catalog row. Final report:

## Summary

**Source vs output**: `PRD_FINALIZED.md` (378 lines / 61,321 chars) → `workspace/PRD_COMPLETED.md` (379 lines / 63,620 chars), char-delta **+2,299**. Only `PRD_COMPLETED.md` was written; `implementation/`, `test_helpers/`, `test_suite/` untouched.

**Counts**: 16 ambiguity/omission pins, 4 mismatch revisions (20 change-points, applied as 17 in-line edits).

### Changes (one bullet each)

- §1 — revise — mismatch — "same response envelope as the write that triggered it" replaced with: envelope carries the operation's primary resource with its figures recomputed; figures on other affected resources commit in the same operation and show on their next read — impl returns only the primary resource on every cascade (routes_b.py:97 window-cancel returns window only; routes_b.py:432 scoring returns attempt only; routes_c.py:433 adjudication returns case only).
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit` (outside 1..100) and non-integer/negative `offset` are malformed (`ERR_INVALID_REQUEST`) — util.py:132-148.
- §2.3 — insert — ambiguity — list sort ties on equal `created_at` broken by creation order — util.py:125-126 (`_seq` tie-break; the logical clock makes equal `created_at` common).
- §2.4 — insert — ambiguity — clock setter moves directly to any supplied instant, no monotonicity check (may move backward) — routes_a.py:19 (`DB.clock = as_dt(...)` unconditionally).
- §2.5 — insert — ambiguity — `version` begins at 1 at creation, when `created_at` == `updated_at` — store.py:92-95.
- §2.6 stage 11 — revise — omission — added `ERR_DUPLICATE_SOCIETY_CODE` to the uniqueness family (§3.9 already references it; the family list was incomplete) — routes_c.py:477-479.
- §2.8 — revise — ambiguity — `outstanding_balance_cents` never below zero: payment/credit excess routes to `credit_balance_cents` — domain.py:235-238, 244-246 (min()-clamped absorption).
- §2.8 — insert — ambiguity — charge draw-down counts toward `lifetime_credits_applied_cents` whatever the balance's origin (posted credits or overpayments) — domain.py:223-226.
- §2.10 — revise — mismatch — cascade clause "every affected entity reflects the change in the same response envelope" replaced with commit-in-same-operation + primary-resource-in-envelope semantics (same rationale as §1).
- §3.2 (cycles) — insert — ambiguity — a read naming a nonexistent `{cycleId}` fails with `ERR_EXAM_LEVEL_NOT_FOUND` (no cycle-specific id in the catalogue) — routes_a.py:283.
- §3.2 (windows) — insert — ambiguity — `window_closes_at` must lie strictly after `window_opens_at` (`ERR_INVALID_REQUEST`) — routes_b.py:33-34.
- §3.2 (windows) — insert — ambiguity — overlap check counts every existing window of the level whatever its status (incl. `CANCELLED`) — routes_b.py:44-47 (no status filter).
- §3.2 (centers) — insert — ambiguity — blackout `blackout_end_date` must be no earlier than the start date — routes_b.py:128-129.
- §3.4 — insert — ambiguity — resupplying the appointment's current window id is not a window change and binds no retarget checks — routes_b.py:268 (`tw['id'] != orig_w['id']`).
- §3.5 — revise — mismatch — an unapproved `actual_calculator_model` value is malformed (`ERR_INVALID_REQUEST` at shape stage); only an approved-but-undeclared model yields `ERR_CALCULATOR_POLICY_VIOLATION` — routes_b.py:339 (`as_enum` before state checks) vs 349-350.
- §3.5 — insert — ambiguity — `scaled_score` must be an integer; non-integer → `ERR_INVALID_REQUEST`, out-of-range integer → `ERR_SCORE_OUT_OF_RANGE`, both at shape stage — routes_b.py:398-401 + util.py:87-90.
- §3.7 — insert — ambiguity — auto-opened conduct-statement case's `allegation` carries the `disclosure_text` (empty when absent); filing returns `201 Created` with the candidate record — routes_c.py:262, 269.
- §3.7 — insert — ambiguity — explicit `origin` is an enum of `EXAM_INCIDENT`/`CONDUCT_STATEMENT`/`EXTERNAL_REPORT` — routes_c.py:287-289.
- §3.7 — insert — ambiguity — case-opening flags compliance from `CLEAR` **or** `CLEARED` (re-flag); already `POLICY_FLAGGED`/`CONFIRMED_VIOLATION` left untouched — routes_c.py:314-316.
- §3.7 — revise — mismatch — dismissal compensation scoped per-case: each item reverses only what this case's own sanctions applied (tracked attempts reinstated, own suspension lifted, own revocation reversed); standing imposed by other cases untouched — routes_c.py:374-390 (`_ever_sanctioned`/`_suspension_applied`/`_revocation_applied`/`_invalidated_attempt_ids` flags). PRD's unqualified "suspended_until is cleared to null; conduct_revoked returns to false" would have one case's dismissal wipe another case's sanction.
- §5 — insert row — omission — added `| ERR_DUPLICATE_SOCIETY_CODE | 409 Conflict |` (referenced by §3.9 and the impl callsite but missing from the normative table) — routes_c.py:479.

### Per-file walk evidence

- **app.py** (41 lines): 4 behaviors examined (ApiError handler, HTTPException→`ERR_INVALID_REQUEST`/`<500` vs `ERR_INTERNAL`/`500` fallback, blueprint mounts, PORT/0.0.0.0/foreground). All already-pinned or outside the PRD's explicitly 4xx-scoped contract. 0 changes.
- **errors.py** (87): 50 catalog entries diffed against §5 — all statuses match; the one anomaly is the *missing* `ERR_DUPLICATE_SOCIETY_CODE` entry (see dead-code findings).
- **store.py** (101): 8 behaviors (default clock `2026-09-01T00:00:00Z`, `base_fields` version-1/equal-timestamps, `touch` +1, `months_between` formula == §2.9, ms-precision `iso`, parsers). 1 pin.
- **util.py** (151): 10 behaviors (envelope/`req_` id/wall-clock timestamp, `has_more` formula, `ctx` stages 1-2, empty/non-dict body handling, unknown-field rejection, type guards, pagination validation + sort tie-break). 2 pins.
- **domain.py** (430): ~25 behaviors (conduct_standing precedence, 14 serializers' field shapes, lazy `ref_status`, `ce_totals` calendar + trailing-365-day variants, ledger post_charge/credit/payment mechanics, per-line ROUND_HALF_UP, progression + curriculum recompute incl. lowest-unpassed rule, 5-step retake chain, reschedule fee 25000/25000/10000×min(priors,2)/60000-cap, seat-consuming states, inclusive+1-day-buffer blackout, provisional-cumulative vs committee-merged months). 2 pins.
- **routes_a.py** (284): all 12 routes walked (clock, candidates, enrollments, payments, award six-gate order, levels, cycles incl. newer-year-only auto-archive, cycle not-found). 2 pins.
- **routes_b.py** (432): all 13 routes walked (window create deadline chain + overlap, window-cancel cascade creation-order/full-fee/CHECKED_IN-untouched, center validation, full booking pipeline incl. body-FK order enrollment→window→center and money-last, reschedule OCC + original-window deadline + retarget chain + own-seat exclusion + fee-vs-current-date, appointment cancel deadline-gated credit, check-in identity-before-calculator + attempt_sequence counting all attempts, scoring shape-stage range check + NO_SHOW sweep + all-SCORED auto-publish + CHECKED_IN→COMPLETED). 5 pins.
- **routes_c.py** (572): all 17 routes walked (segment validation, amend OCC/DRAFT-reset/months-null, submit ≥2-non-EXPIRED lazy, review ≥2-VERIFIED gate + committee only on APPROVED/REJECTED, reference 30-day expiry + late-respond transitions-then-fails + uid==referenceId, statement dup-year + auto-case, case create origin forcing/defaulting + one-open-case, adjudicate shape→OCC→state→segregation order + all four sanction cascades, dismissal compensation, appeal ≤30-days-after-`sanctioned_at` inclusive, society create, join dup→charter→exact-dues order, renew calendar-year-variant-only +1 year, CE append). 6 pins.

**Totals**: ~93 behaviors examined; ~70 already uniquely pinned; 16 ambiguity/omission pins; 4 mismatch revisions.

### Dead-code findings

1. **Inverse dead-code (invoked but undefined) — flagged, not edited**: `fail('ERR_DUPLICATE_SOCIETY_CODE')` at `routes_c.py:479` references an id **absent from `errors.py` CATALOG**, so the guard raises `KeyError`, which `app.py`'s fallback converts to HTTP 500 `ERR_INTERNAL` — not the PRD-named 409. No test in `test_suite/` exercises duplicate society codes (grep-confirmed), so the 8-round sweep never sees it. Per the task's dead-code clause I did not touch `implementation/`; PRD_COMPLETED keeps the §3.9 contract self-consistent by adding the missing §5 row at 409 (matching every sibling duplicate error and the callsite's evident intent), and the defect is flagged here.
2. No classic "defined but never called" PRD-required check found: every guard/helper relied on above (`retake_check`, `retake_gap_check`, `recompute_candidate`, `recompute_all_curriculum`, `post_charge`/`post_credit`/`post_payment`, `line_cents`, `seats_consumed`, `blackout_blocked`, `provisional_months`, `committee_months`, `ref_status`, `conduct_standing`, `ce_totals`, `months_between`, `ctx`, `list_response`) has at least one live callsite, verified by reading all 42 route handlers.

Orchestrator verification: PRD_COMPLETED.md on disk (379 lines, +2299 chars, 35 diff lines vs PRD_FINALIZED.md); §5 row present at line 336; defect claim CONFIRMED against source (routes_c.py:479 invokes it, errors.py CATALOG lacks it, fail() does `CATALOG[error_id]` → KeyError → 500). Implementation/test mtimes unchanged by Step 9 (impl ≤16:05, latest test file 16:21 from Step 7's fixture fix).

## Post-Step-9 Defect Repair + Sweep Re-verification (orchestrator) — 2026-10-01T17:05:00.000Z

Step 9's dead-code scan surfaced a genuine implementation defect that the test suite never exercised (grep-confirmed: no test duplicates a society code): `fail('ERR_DUPLICATE_SOCIETY_CODE')` at `implementation/routes_c.py:479` referenced an id absent from `errors.py` CATALOG, so the PRD-named guard (`PRD.md §3.9` line 245; `PRD_COMPLETED.md §5` row) would have surfaced as HTTP 500 `ERR_INTERNAL` via the `app.py` fallback instead of 409.

- **Fix (orchestrator-applied, implementation/):** added `'ERR_DUPLICATE_SOCIETY_CODE': (409, 'society_code already exists')` to `errors.py` CATALOG, adjacent to its sibling duplicate entries (all 409). One-line additive change tracing to a verbatim PRD sentence; no guard logic altered.
- **Targeted smoke test:** boot on port 19872 (exact saved PID, killed after): first `POST /charter/societies` → 201; duplicate `society_code` → error envelope with `error_id: ERR_DUPLICATE_SOCIETY_CODE` (previously KeyError → 500).
- **Sweep re-run (mandatory — implementation/ bytes changed after Step 7's clean sweep):** full 8-round parallel sweep re-run by the orchestrator, `results.{1..8}.json` regenerated. Result: **106/106 passed in all 8 rounds (ALL_PASS)**, ~182s per round. The 8 passing results files remain in `workspace/implementation/` per the output contract.
