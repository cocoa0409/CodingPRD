# Worklog — task_2132_grief_bereavement_support

## Step 1: Create task directory — 2026-08-22T10:30:09.232Z

Created `./tasks/task_2132_grief_bereavement_support/` and `./tasks/task_2132_grief_bereavement_support/workspace/` (index 2132 = max existing 2131 + 1).

## Step 2: Generate scaffold — 2026-08-22T11:22:30.000Z

Done. All three scaffold artifacts are written and lint-clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3479 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1290 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4154 |

## Inventory

- **Entities** 16 (Referral, Participant, Assessment, MeetingSpace, Cohort, Enrollment, Counselor, CounselingReferral, VolunteerCompanion, CompanionMatch, RemembranceEvent, Invitation, GrantAward, FundingAllocation, GrantReport, AnniversaryOutreach)
- **State machines** 15 / **80 transitions**; **concurrency rules** 3 (OCC on Cohort, Counselor, GrantAward `version`)
- **Calculations** 11 · **Validations** 15 priority bands · **Endpoints** 79 · **Errors** 62 · **Roles** 7
- **§1.8** 9 rule blocks × 2 = **18 instances**; **§1.9** 9 sections, **100 instances** (94 with full recipes + 6 `excluded_because` stubs)

## Difficulty design (beyond Expert)

- Profile: `workflow_orchestration` × `quota_allocation`, **graph** topology, **cyclic** state-machine shape, **segregation_of_duties** role model.
- Five non-linear machines: Cohort (branch on the viability boundary + `UNDERSUBSCRIBED→OPEN_ENROLLMENT` and `RUNNING<->SUSPENDED` cycles), Participant (two independent dimensions `service_status x outreach_status`), CounselingReferral (`WAITLISTED→ASSIGNED→WAITLISTED`), VolunteerCompanion (re-certification loop), GrantReport (`DRAFT→SUBMITTED→RETURNED→DRAFT`).
- Two depth-5 cascades from different triggers: participant withdrawal → enrollment → cohort seats/suspend → allocation release → grant ledger; counselor deactivation → referral re-queue → re-entry count → one-level risk-tier escalation → cadence + outreach re-channelling (leaves `risk_tier HIGH` while `composite_need_index` stays 45.00 — catches implementations that re-derive the tier).
- Dual-variant money (provisional 134400 vs settled 50400 on one cohort) and dual-variant clinical scoring (raw -25.00 vs attendance-adjusted -16.80).
- Combinatorial modes (b) and (c): pinned per-line-then-sum indirect rounding (4122, not 4121 → total 38460) and a circular-looking indirect tier pinned to `direct_cost_cents` alone (28800/268800, not 26880/266880).
- Two overlap geometries on different resources: MeetingSpace closed-interval + buffer over a recurring weekday window (gap of exactly 30 min collides, 31 does not) vs Counselor aggregate weekly-minute capacity (equality passes at 120, 121 fails).
- Two conserved quantities: grant cents (`awarded == available + committed + spent`) and cohort seats (`seats_total == open + held + filled`).

Every numeric literal in the design files was computed in Python against the pinned formulas. Verdict: **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** Independent checks also confirmed all 118 instance names unique, every `grounds:` reference resolving into §1.1–§1.7, all 62 error codes referenced by at least one design instance, endpoint roles ⊆ RBAC, all roles carrying `identity:`, each OCC endpoint declaring its `expected_*_version` input and version-bump side effect, and no forbidden concurrency vocabulary. No sibling task directory was read.

## Step 3: Copy shared files — 2026-08-22T10:30:29.237Z

Copied `./INSTRUCTION.md` → `tasks/task_2132_grief_bereavement_support/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-22T11:35:20.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 464 lines, ~13,900 words. Built incrementally across 7 append operations (no truncation).

**Section inventory**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 RBAC · 2.2 API Response Structure (verbatim, byte-verified against `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Logical Clock · 2.5 The Rejection Ladder · 2.6 Stale-Parent Protection on Contended Writes · 2.7 Conserved Pools, Money and Rounding · 2.8 Nested Paths and Not-Found Reporting · 2.9 Cascade Discipline · 2.10 The Operational Sweep
- §3 Business Logic — 9 subsections: Intake · Assessment/Risk Tiering/Outcome Measurement · Meeting Spaces & Occupation Calendar · Seats & Cohort Lifecycle · Counselling Waitlist · Volunteer Companions · Remembrance Events & Invitations · Outreach Cadence/Holds/Withdrawal · Grant Money
- §4 Endpoint table (4 columns) · §5 Error table (2 columns). Document ends at §5 — no audit footer.

**Coverage audit (mechanically verified against SCAFFOLD.yaml)**

| Category | Scaffold | Covered | Gaps |
|---|---|---|---|
| Entities | 16 | 16 | 0 |
| Entity field names (backticked) | 129 | 129 | 0 |
| Endpoint input/output identifiers | 91 | 91 | 0 |
| State machines | 15 | 15 | 0 |
| State transitions | 80 | 80 | 0 |
| State enumeration values | 35 distinct | 35 | 0 |
| Enum-field values | 97 | 97 | 0 |
| Calculations | 11 | 11 | 0 |
| Validation priority bands | 15 | 15 (ordered ladder in §2.5) | 0 |
| Concurrency (OCC) rules | 3 | 3 (field + error + 412 each) | 0 |
| Endpoints | 79 | 79 | 0 |
| Error codes | 62 | 62 in table, 62 also referenced in §2/§3 prose | 0 |
| Roles | 7 | 7, each `identity:` translated | 0 |

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 129 required, 129 present, 0 missing
- endpoints[].input/request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params (limit/offset/filters): included above, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed as an explicit ordered ladder, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write op + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: 80 checked, 80 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (pinned orders, constants, precision), 0 missing
- validations[] conditions: 62 error paths checked, 62 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 79 checked, all expressed, 0 missing
- entities[].fields[] structured content: 129 checked, defaults/initials/nullability reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (launch RUNNING vs UNDERSUBSCRIBED; provisional vs settled x GROUP_PROGRAM vs REMEMBRANCE_EVENT; ACCEPT vs DECLINE on matches and RSVPs; cohort-vs-event / cohort-vs-cohort / event-vs-event conflict shapes; DECLINE/VOID/EXPIRE invitation exits; SETTLED vs RELEASED allocation exits), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1048
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notable rules given explicit prose treatment (the ones most likely to be silently lost): the pinned single-pass admin-fee tier order with the 240,000-cent divergence example; the pinned round-per-line-then-sum grant-report order with the 11,446 x 3 example; the closed-interval buffer collision with the minute-720/721 boundary; the suicidality floor applied *after* rounding; the RTM-correction-before-attendance-weighting order; the disjoint status sets between `provisional_projected` and `settled_actual`; the 5-step counsellor-deactivation cascade into risk-tier escalation and outreach re-channelling; and the two-dimension Participant state machine. The design-index files were never opened.

## Step 6: Generate implementation — 2026-08-22T11:58:40.000Z

All four smoke suites pass and the server boots clean from a fresh process. Implementation is complete.

**Location:** `workspace/implementation/`

### File tree (3,182 Python lines)
```
  68  app.py                    (entry, error handlers, request-serializing middleware)
   8  start.sh                  (guarded pip install, exec python3 app.py)
   1  requirements.txt
 core/  errors.py 98 · store.py 145 · envelope.py 82 · auth.py 97 · shape.py 167 · calc.py 210
 services/ derive.py 145 · cascade.py 172 · occupation.py 69 · reporting.py 59 · state.py 55
 routes/ __init__.py 27 · ops.py 107 · referrals.py 153 · participants.py 189 · outreach.py 48
         spaces.py 49 · cohorts.py 190 · enrollments.py 154 · counselors.py 178 · volunteers.py 208
         events.py 213 · grants.py 299
```

### Coverage
- **Endpoints: 79/79** — verified programmatically against `SCAFFOLD.yaml` (`missing: []`, `extra: []`).
- **Errors: 62/62** wired (every id in the catalogue is raised somewhere or reachable via the per-entity NOT_FOUND map).
- **Boot:** `bash start.sh` on `$PORT`/`0.0.0.0` answers in <4s; fresh store, logical clock at `2026-08-01T00:00:00Z`, sweep returns all-zero counters, no seeded data anywhere.
- Storage is in-memory dicts only; counters (`seats_*`, `committed/spent/available_cents`, `active_caseload`, `committed_minutes`, `active_match_count`, `has_active_companion`) are recomputed from child rows inside the same write, so the conserved-pool identities hold in the causing response. All requests are serialized by a WSGI lock so cascades are atomic.
- Verified by smoke tests: tier selection from `direct_cost_cents` alone (240000 → 28800/268800; 750000 → 60000/810000), provisional vs settled allocation (405000 vs 33600 on disjoint status sets), event settlement capped headcount ratio, report round-per-line-then-sum, RTM-before-attendance pinned order (-33.38), closed-interval buffer boundary (720 collides / 721 legal), OCC 412s, ladder precedence (shape > OCC > state > safety > agreement > capacity), all five sweep steps, counselor-deactivate re-entry chain, participant-withdrawal 5-entity unwind, withdraw→suspend→release money chain.

### PRD ambiguities resolved by implementation choice (relevant to Steps 8/9)
1. **Seats on cohort completion** — §2.7 + scaffold field definitions say `seats_filled` counts only CONFIRMED/ATTENDING, so COMPLETED enrollments release seats back to `seats_open`; §3.4's completion paragraph never mentions seat movement. Chose the compartment definition (counters derived from enrollment status).
2. **Undeclared error ids → `ERR_INVALID_STATE` (409)**: room not AVAILABLE on cohort open-enrollment / event confirm; confirm after `held_until` lapsed; reinstate after certification expiry; `mark-held` before `event_date`; closing an award with `committed_cents != 0`.
3. **Repeat withdraw** of a WITHDRAWN participant → `ERR_PARTICIPANT_WITHDRAWN` (not `ERR_ALREADY_TERMINAL`); withdraw of a DISCHARGED participant → `ERR_INVALID_STATE`.
4. **Counselor ownership on `GET /counseling-referrals/{id}`** — PRD compares against `counselor_id`, scaffold's role matrix annotates ownership only on `close`. Chose: 403 only when `counselor_id` is non-null and differs (a WAITLISTED referral stays readable); `close` is strict.
5. **VolunteerCompanion on `GET /participants/{id}/anniversary-outreaches`** — none of §2.1's three comparisons apply, so no ownership check; `send`/`acknowledge` do require an ACTIVE match with that participant.
6. **`GET /counseling-referrals` ordering** — §3.5 queue order (`queue_priority` DESC, `waitlisted_at` ASC, `created_at` ASC) applied instead of the §2.3 `created_at` default.
7. **Assign precondition order** — PRD prose puts caseload before minute capacity; the scaffold's code snippet has them reversed. Followed the PRD.
8. **Attendance logging** has no declared state precondition → allowed from any enrollment status, clamped to `[0, sessions_total]`.
9. **NEEDS assessment on a DISCHARGED participant** — undeclared; recorded and re-tiered with `service_status` unchanged.
10. **`endorsed_loss_types`** treated as optional (default `[]`) per PRD prose, though the scaffold endpoint input lists it as required; training-record `hours` required numeric >= 0 (no declared range).
11. **Event counters increment-only** — VOIDing a SENT invitation does not decrement `invitations_sent`.
12. **All timestamps** come from the logical clock, never the wall clock.
13. **`ERR_ALLOCATION_SUBJECT_MISMATCH` reachability** — rung 6 handles subject presence for GROUP_PROGRAM/REMEMBRANCE_EVENT (422 `ERR_INVALID_REQUEST`), so rung 11(e) fires for COUNSELING/VOLUNTEER_TRAINING categories.
14. **Intra-rung-9 order**: enrollment create checks cohort-not-enrolling before participant-withdrawn; match create checks companion-not-certified before participant-withdrawn.
15. Unmatched route/method returns the standard error envelope with `ERR_INVALID_REQUEST` at 404/405.

## Step 5: Generate unit tests — 2026-08-22T12:10:05.000Z

Test infrastructure and suite are complete for `task_2132_grief_bereavement_support`.

## Files written

**`test_helpers/`** (2,439 lines)

| file | lines |
|---|---|
| `types.py` | 563 |
| `fixtures.py` | 609 |
| `api_client.py` | 338 |
| `assertions.py` | 265 |
| `factories.py` | 251 |
| `api_errors.py` | 157 |
| `constants.py` | 139 |
| `test_users.py` | 73 |
| `__init__.py` | 44 |

**`test_suite/`** (4,663 lines, 12 domain-grouped modules + `conftest.py`)

`test_01_intake` (19) · `test_02_assessments_outcomes` (11) · `test_03_spaces_and_cohort_formation` (13) · `test_04_enrollment_seats` (16) · `test_05_cohort_lifecycle` (10) · `test_06_counseling_waitlist` (12) · `test_07_volunteer_companions` (11) · `test_08_events_invitations` (8) · `test_09_outreach_cadence` (5) · `test_10_grant_money` (13) · `test_11_grant_reporting` (8) · `test_12_concurrency_and_consistency` (5)

## Coverage tally — 131 tests

- **Queue A (Difficulty):** 18/18 instances translated, >=2 tests each (36 tests). **0 skipped.**
- **Queue B (Corner):** 94/94 non-stub instances translated, >=1 test each (95 tests). **0 skipped.** All 6 `excluded_because` stubs left untranslated; every `difficulty_instance` cross-reference verified to resolve.

## Verification performed

- Every docstring carries exactly one `Design:` line, as the final line, resolving to a real instance (no tag points at a stub).
- Every PRD citation was machine-checked: each quoted string, whitespace-normalized, is a literal substring of `workspace/PRD.md`; every docstring carries at least one >=8-word rule-bearing quote.
- All 22 files pass `python3 -m py_compile`; `pytest --collect-only` collects **131 tests, 0 import errors**.
- No `skip` / `skipif` / `xfail` anywhere; no "scaffold" or index-section references leak into generated comments.

## PRD-vs-index conflicts found

1. **`allocation_subject_mismatch_when_category_and_subject_disagree` (Corner/errors)** — the PRD states the category/subject agreement rule twice at different ladder rungs: §2.5 rung 6 makes it a *request-shape* rule (`ERR_INVALID_REQUEST`, 422), while §2.5 rung 11 and §3.9 make it a *matching* rule (`ERR_ALLOCATION_SUBJECT_MISMATCH`, 422). Rung 6 precedes rung 11, so two faithful PRD-only readers diverge on the `error_id`. Per the `error-precedence` silence pattern the test asserts HTTP 422 exactly and uses `validate_error_is_one_of([ERR_ALLOCATION_SUBJECT_MISMATCH, ERR_INVALID_REQUEST])` rather than pinning the index's single value. This is the only relaxed assertion in the suite.
2. **`event_cancel_voids_draft_and_sent_invitations` (Corner/state_machines)** — the index asserts `invitations_sent == 2` after cancellation, but §3.7 defines that counter as reflecting invitations "in `SENT`, `ACCEPTED`, `DECLINED` or `EXPIRED`" (VOID absent), while also saying voiding "changes no headcount". Two readers diverge (1 vs 2), so that single assertion was dropped; the instance's actual subject is kept — `VOID`/`VOID`/`ACCEPTED` statuses plus `invitations_accepted == 1` and `confirmed_headcount == 3`, both of which the PRD uniquely determines.

No literal disagreements (thresholds, error names, state names, defaults) were found between the PRD and either index — the pre-computed values in both design files (134400/50400, 4122 vs 4121, 28800/268800, 68.50, 85.00, 74.75, 50.75, 2862, 0.3750, 11446/488554) all reconcile with the PRD formulas.

## Step 7: Run tests and iterate — 2026-08-22T12:16:00.000Z

The sweep came back clean on the first iteration, verified not a false green before exiting.

**Iterations run:** 1 (single 8-round parallel sweep — all rounds green, so no fix/rerun cycles were needed).

**Result:** 8/8 rounds at `131 / 131`. Aggregate across the sweep: 1048 passed, 0 failed, 0 errors, 0 skipped. Round wall time ~175s each; the 8 rounds claimed 8 distinct ports (38487, 39335, 41269, 42199, 48825, 53083, 54781, 60071), so no port collision masked a run.

**Tests deleted:** none. No test failed in any round, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Green-sweep validation

A clean first sweep is exactly the shape a broken harness makes, so the failure modes that would produce one were checked:

- **Tests genuinely ran.** Each `results.${i}.json` carries 131 individual test entries with per-test durations (`duration_seconds` 174–175s per round), not an empty or short collection. All 8 rounds report the identical set of 131 test names — no round silently collected a subset.
- **No hidden passes.** `skipped == 0` in every round, and there is no `pytest.mark.skip` or `xfail` anywhere in `test_suite/` or `test_helpers/`.
- **No data-seeding or persistence shortcut.** `implementation/core/store.py` is plain in-memory dicts keyed by id; a grep for `sqlite`, `open(`, `json.dump`, `pickle`, `/tmp`, `shelve`, and external DB drivers across the implementation returns nothing. State is fully wiped by each `start.sh` reboot under `per-test-server` isolation.

### One thing worth flagging

The concurrency tests (`test_12_concurrency_and_consistency.py`) pass, but note *how*: `app.py` wraps the WSGI app in a `SerializingMiddleware` holding a process-wide `threading.RLock`, so every request is serialized. This is a legitimate PRD-faithful way to make cascades atomic, and it is not a test weakening — but it does mean the race-semantics tests are exercising a serialization in which the loser of a race always lands deterministically. If a future change removes or narrows that lock, those tests are the first place flakiness would reappear.

### Orchestrator independent verification

Re-read all 8 `results.*.json` directly: every round `passed=131 failed=0 total=131 skipped=0 errors=0`. `grep -rn "mark.skip\|mark.xfail" test_suite/ test_helpers/` → 0 hits. `grep -rniE "sqlite|json\.dump|pickle|shelve|/tmp" implementation --include=*.py` → 0 hits.

## Step 8: Finalize PRD — SKIPPED — 2026-08-22T12:17:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-22T12:26:00.000Z

`PRD_COMPLETED.md` is written. Structure verified intact: 464 lines, §1–§5 headings all present, both tables unchanged at 145 rows.

- **Source vs output**: `PRD.md` 464 lines / 99,609 chars → `PRD_COMPLETED.md` 464 lines / 108,561 chars (**+8,952 chars**). 38 lines revised, zero lines added or removed, no new sections.
- **Counts**: 40 changes — **32 ambiguity-pins**, **8 mismatch-revisions**.

### Changes

- §2.1 — revise — ambiguity — an unassigned counselling referral (`counselor_id` null) is owned by nobody: readable by any `Counselor`, but closing demands strict equality — `core/auth.py:61-75`
- §2.1 — insert — ambiguity — the acting `X-User-ID` is never looked up; it is compared as an opaque string — `core/auth.py:49-58`
- §2.5 r3 — revise — **mismatch** — ownership is enforced only where §2.1 names a comparison, not on every endpoint admitting an entity-backed role — `routes/participants.py:180-189`, `routes/counselors.py:41-44,116-126`, `routes/volunteers.py:157-165`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics — `core/envelope.py:19-20`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, never wall time — `core/envelope.py:23-27`
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST`; omitted/empty falls back to the default — `core/envelope.py:61-68`
- §2.3 — insert — ambiguity — `created_at` ties break by creation order; undeclared query params ignored, filters exact-match — `core/store.py:106-120`
- §2.4 — insert — ambiguity — the clock may move backwards, and it is the sole source of every server-stamped timestamp — `core/store.py:72-99`
- §2.5 r6 — insert — ambiguity — undeclared body fields ignored; absent/unparseable body reads as `{}`; a non-object body is a violation — `core/shape.py:32-38`
- §2.5 r7 — insert — ambiguity — body-identifier resolution order pinned for the four multi-id creates — `routes/enrollments.py:35-36`, `routes/volunteers.py:114-115`, `routes/events.py:137-138`, `routes/grants.py:108-110`
- §2.5 r9 — insert — ambiguity — `ERR_ALREADY_TERMINAL` outranks endpoint-specific state errors (sole exception: outreach send → `ERR_OUTREACH_NOT_DUE`); nine undeclared state preconditions collapse to `ERR_INVALID_STATE` — `services/state.py:39-49`
- §2.8 — insert — ambiguity — unmatched route → `ERR_INVALID_REQUEST` 404, undeclared method → 405; trailing slash tolerated — `app.py:38-48,32`
- §2.9 — insert — ambiguity — requests are processed strictly one at a time (process-wide serialising lock) — `app.py:17-27,59`
- §3.1 — revise — **mismatch** — accept on a terminal referral yields `ERR_ALREADY_TERMINAL`, not `ERR_REFERRAL_NOT_SCREENED` — `routes/referrals.py:129` + `services/state.py:44-47`
- §3.2 — insert — ambiguity — assessments accepted in any `service_status` but `WITHDRAWN`; a `DISCHARGED` participant still accepts them and never moves off `DISCHARGED` — `routes/participants.py:52,76-90`
- §3.2 — insert — ambiguity — baseline/latest tie-break falls through to creation order — `routes/participants.py:107,117-124`
- §3.2 — revise — ambiguity — `attendance_ratio_capped` is rounded half up to 4 dp — `core/calc.py:109-113`
- §3.3 — insert — ambiguity — space unavailability and a no-op status toggle both report `ERR_INVALID_STATE` — `routes/spaces.py:46`, `routes/cohorts.py:99`, `routes/events.py:88`
- §3.4 — insert — ambiguity — intra-rung-9 order on enrollment create: cohort state before participant-withdrawn — `routes/enrollments.py:41-43`
- §3.4 — revise — ambiguity — confirm after `held_until` lapses → `ERR_INVALID_STATE`; check order enrollment → cohort → hold window — `routes/enrollments.py:107-113`
- §3.4 — insert — ambiguity — attendance logging has no state precondition and no withdrawn-participant guard — `routes/enrollments.py:138-153`
- §3.4 — insert — ambiguity — cohort completion returns all seats: `seats_open` = `seats_total`, other compartments zero — `routes/cohorts.py:169` + `services/derive.py:27-38`
- §3.5 — revise — ambiguity — `queue_priority` is stored, recomputed only at creation and waitlist fall-back, so it does not drift with the clock; ordering adds a creation-order tie-break — `routes/counselors.py:101,70,124-125`
- §3.5 — revise — ambiguity — the four assign preconditions are evaluated in the stated order, all after the referral's `WAITLISTED` check — `routes/counselors.py:141-151`
- §3.6 — revise — ambiguity — `endorsed_loss_types` members must be declared loss categories — `routes/volunteers.py:28`
- §3.6 — insert — ambiguity — training `hours` is a number >= 0; recording refused with `ERR_INVALID_STATE` against a `CERTIFIED`/`SUSPENDED` volunteer — `routes/volunteers.py:59-60`
- §3.6 — insert — ambiguity — reinstatement after certification expiry → `ERR_INVALID_STATE` — `routes/volunteers.py:99-101`
- §3.6 — insert — ambiguity — match create resolves companion before participant, and `ERR_COMPANION_NOT_CERTIFIED` precedes the participant-withdrawn check — `routes/volunteers.py:114-119`
- §3.7 — insert — ambiguity — mark-held before `event_date` → `ERR_INVALID_STATE` — `routes/events.py:116-117`
- §3.7 — insert — ambiguity — an invitation may be drafted whatever the event's status — `routes/events.py:137-150`
- §3.7 — revise — **mismatch** — the three event counters are increment-only; a `SENT`→`VOID` invitation stays counted in `invitations_sent` — `routes/events.py:100-107,187,207-208`
- §3.8 — revise — ambiguity — hold/unhold from the wrong `outreach_status` → `ERR_INVALID_STATE` — `routes/participants.py:168-175`
- §3.8 — revise — ambiguity — repeat withdrawal → `ERR_PARTICIPANT_WITHDRAWN`; withdrawal of a `DISCHARGED` participant → `ERR_INVALID_STATE` — `routes/participants.py:153-155`
- §3.8 — revise — **mismatch** — the withdrawn-participant guard is carried by exactly eight writes; elsewhere the refusal surfaces as `ERR_ALREADY_TERMINAL`, except attendance logging (ungated) and responding to an already-`SENT` invitation — `services/cascade.py:142-172`
- §3.9 — insert — ambiguity — no ordering constraint between `period_start` and `period_end` — `routes/grants.py:31-32`
- §3.9 — revise — ambiguity — non-zero `committed_cents` on close → `ERR_INVALID_STATE`; re-closing a `CLOSED` award → `ERR_ALREADY_TERMINAL` — `routes/grants.py:66-68`
- §3.9 — revise — **mismatch** — `ERR_ALLOCATION_SUBJECT_MISMATCH` is unreachable for `GROUP_PROGRAM`/`REMEMBRANCE_EVENT` (rung 6 catches those as `ERR_INVALID_REQUEST`); reserved for `COUNSELING`/`VOLUNTEER_TRAINING` — `routes/grants.py:92-106,124-129`
- §3.9 — revise — ambiguity — report line ordering adds a creation-order tie-break — `services/reporting.py:25`
- §3.9 — insert — ambiguity — totals recomputed only at creation, submission and reopening; return and acceptance freeze them — `routes/grants.py:222,252,283`
- §4 — revise — **mismatch** — an unauthenticated `GET /health` sits outside `/bereavement` and outside the §2.2 envelope — `app.py:51-53`

Notable non-findings verified against code (PRD already pins them uniquely, no edit made): all §2.7 rounding rules and every calculation formula in `core/calc.py`; the five-step sweep and its thresholds; occupation buffer arithmetic; the assign precondition set; `match_score` freezing; provisional/settlement formulas; `participants_served`; per-line indirect rounding.
