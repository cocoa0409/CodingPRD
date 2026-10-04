## Step 1: Create Task Directory — 2026-10-01T10:39:00.000Z

Task directory `tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and used it as-is. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T11:41:00.000Z

All three artifacts are complete and pass every check. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys) — 1,334 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 18 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 35 active instances + 3 `excluded_because` stubs

**Counts:**
- Entities: **11** (University, Student, Employer, EmployerApproval, JobPosting, CareerEvent, EventSession, EventSignup, Application, Interview, OutreachMessage)
- State machines: **10** (every entity except OutreachMessage), incl. cycles on Employer (APPROVED↔UNDER_REVIEW), JobPosting (PUBLISHED↔PAUSED), University (ACTIVE↔SUSPENDED)
- Endpoints: **40** (deliberately held at the ≤40 ceiling; per-test-server impl-gen degrades beyond it)
- Validations: **11** ordered priority rows; Errors: **56** (all referenced by at least one validation/transition — audited); Roles: **5**
- Calculations: **10**, including dual-variant fraud scoring (auto_screen vs analyst_screen) and dual-denominator outcome rates with pinned nested-rounding order
- OCC concurrency rules: **2** (`expected_employer_version` on approval decide; `expected_career_event_version` on session create)
- Difficulty design: **18 instances** (2 per §0.5 rule × 9 rules), all differentiation clauses honored; Corner design: **35 + 3 stubs**
- Lint: 560 recipe calls scanned, zero violations on checks (a)–(f)

**Difficulty gearing beyond Expert:** flat FK-in-body topology with entity-backed RBAC (CareerCenterAdmin ↔ University.id, EmployerRecruiter ↔ Employer.id), a depth-4 cascade (approval BLOCK → posting blocked → application AUTO_WITHDRAWN → interview CANCELLED, with OFFER_EXTENDED conditionally spared), a second depth-2 cascade on student withdrawal that also fires waitlist promotion, two interval-conflict semantics (half-open room adjacency vs 15-minute buffered interviewer calendar), priority-conflict pairs (state vs safety; safety vs capacity), and two compensating invariants (occupied_seats under cancel+promote; active_application_count under submit+withdraw).

**Notable design decisions:**
- Posting EXPIRED is a **read-time projection**, not a clock sweep — a sweep on clock-set would convert the inclusive-deadline boundary into a state error and make ERR_APPLICATION_DEADLINE_PASSED unreachable; the projection keeps the temporal error testable while proving (via a post-deadline PAUSED transition) the stored status is never rewritten.
- Employer re-approval uses supersede semantics (old BLOCKED/REVOKED row → SUPERSEDED with `supersedes_approval_id`), keeping the approval machine branching without a revive path.
- Logical clock pinned to the mandatory default 2026-09-01T00:00:00Z; all fixture dates sit at/after it.
- Every formula-derived assert literal was executed in Python before being pinned (fraud scores 25/55, tier boundary 20 vs 21, caps 2/3/10, outcome rates 0.6666 vs the 0.6667 raw-rounding trap and 0.5455 cohort).
- All recipes replayed call-by-call against §1.2/§1.4/§1.6 (e.g., OCC versions re-captured after every parent mutation; the 11-alumni CS/BIO fixture reproduces exactly the asserted report numbers).

## Step 3: Copy Shared Files — 2026-10-01T11:42:00.000Z

Copied ./INSTRUCTION.md to tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T12:05:00.000Z

All checks pass. The earlier "missing" report was a checker artifact (unstripped code fences shifted backtick parity); with fences stripped, every required identifier is present.

**Task complete.** Generated `/home/ubuntu/github/CodingPRD/tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/workspace/PRD.md` from the scaffold (the two forbidden design-index files were never opened).

## Summary

**PRD line count:** 377 lines

**Section list:**
- §1 Introduction (2 paragraphs — federated-trust angle, logical-clock framing)
- §2 Global Specifications: 2.1 RBAC (all 5 roles with identity translations), 2.2 API Response Structure (verbatim block, verified byte-present), 2.3 Pagination, 2.4 Common Resource Properties and Mutation Semantics, 2.5 The Logical Clock, 2.6 Numeric Precision and Rounding Conventions, 2.7 Nested Resource Retrieval and Existence Order, 2.8 Optimistic Concurrency Control, 2.9 Order of Evaluation for Rejections, 2.10 Read-Time Expiry Projection for Job Postings
- §3 Business Logic (9 subsections, timeline + cross-cutting grouping): 3.1 University Onboarding & Roster Provisioning, 3.2 Employer Registration/Domain Verification/Fraud Screening, 3.3 Employer Approvals, 3.4 Job Postings & Clearance, 3.5 Career Events & Sessions, 3.6 Sign-Ups/Waitlists/Attendance, 3.7 Applications & Interviews, 3.8 Outreach & Messaging Allowance, 3.9 Outcome Report
- §4 Endpoint Definitions (40 rows, 4 columns)
- §5 Error Code Catalogue (56 rows, 2 columns)

**Hard contract reports (mechanically verified):**
- Contract 1 (Field-Name Coverage): 83 required names (all entity fields, request-body keys, query params, output fields) — 83 present, 0 missing. **PASS**
- Contract 2 (Rule Coverage): 11 validation priorities with first-failure-wins ordering expressed (§2.9 + concrete instantiations in §3.5/§3.7); both OCC rules with `expected_employer_version`/`expected_career_event_version` + exact 412 error ids; all 10 state machines' transitions with preconditions and side effects; all 9 calculations in precise prose (fraud auto/analyst variants with all constants and 0–100 clamp, tiered messaging cap with floor division, pinned nested round-half-up outcome rates, half-open room conflict vs 15-minute buffered interview conflict with exact-adjacency asymmetry, inclusive deadline vs exclusive signup deadline, 5-step pinned eligibility order, both conserved-count invariants); all cascades (withdrawal 2-hop, BLOCK/REVOKE 3-hop with `OFFER_EXTENDED` exemption, clearance, event-cancel with no-promotion note); all field defaults/nullability/computed semantics; sibling-branch symmetry (ACCEPTED/DECLINED, ATTENDED/NO_SHOW, CLEAR/FLAG/REJECT with the REJECT-from-PENDING asymmetry, cohort vs respondent denominators). **PASS** — no silence gaps I am aware of.
- Contract 3 (§3 Path Purity): 624 backticked §3 tokens scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**
- Aux scans: 0 fuzzy/approximating words; 0 pseudocode operators (`==`, `>=`, `min()`, etc.) in prose; all 56 error ids and all 68 enum/state values present with exact scaffold spelling.

## Step 5: Generate Unit Tests — 2026-10-01T12:55:00.000Z

Generation complete. Final state verified end to end.

## Summary

**Task**: task_3375_campus_recruiting_marketplace_employer_approval_student_access — full test infrastructure generated from the two design indices under the design-index-only contract.

**Totals**: 69 tests, each carrying exactly one `Design:` tag (verified 1:1 per file).

**Queue A (Difficulty)** — 36 tests covering all 18/18 instances with ≥2 tests each, e.g. the fraud-score auto-vs-analyst variant pair, the APPROVED↔UNDER_REVIEW employer cycle, the depth-4 BLOCK cascade (postings → AUTO_WITHDRAWN applications → CANCELLED interviews, with the OFFER_EXTENDED exclusion), the withdrawal cascade with waitlist promotion, both priority-pair conflicts (state-beats-safety, visibility-beats-capacity — both backed by PRD §2.9's explicit evaluation order), both boundary probes (inclusive deadline ±1s; message cap at exactly effective_cap), both overlap semantics (half-open room vs 15-minute buffered interviews), and both conserved quantities (occupied_seats, active_application_count).

**Queue B (Corner)** — 33 tests covering 33/35 non-stub instances; the 3 `excluded_because:` stubs were cross-reference-verified (all resolve to real difficulty instances) and not translated.

**Skipped (2 instances, both on the two-reader unique-derivability rule)**:
- `Corner/entities/job_posting_create_active_count_extra_field_is_ignored_input` — asserts a smuggled computed field is silently ignored (201 + count 0), but the PRD never states whether undeclared payload fields are ignored or rejected; a strict-schema implementation is PRD-faithful and would fail.
- `Corner/entities/employer_create_system_fields_input_ignored` — same reasoning for `status`/`version` smuggled into employer registration.

**Helper files** (`test_helpers/`): `__init__.py` (barrel), `types.py` (11 TypedDicts + 16 enums; all entities carry id/created_at/updated_at/version), `api_client.py` (all 40 endpoints), `api_errors.py` (56 errors registered with `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (values verified against PRD: tiers 20/50/79, base 5, multipliers 200/100/40/0, buffer 15, cap default 10), `test_users.py` (per-instance `make_*_headers` builders for the three entity-backed roles), `fixtures.py` (8 tiers incl. `setup_base_marketplace`, `setup_messaging_marketplace` ELEVATED, `setup_low_risk_marketplace` cap-3, `setup_eleven_alumni_university`; all creates pinned to 201 / actions to 200 per PRD §4, OCC versions auto re-observed).

**Verification**:
- `pytest --collect-only` → **69 tests collected, 0 collection errors** (run with the runner's PYTHONPATH layout; no server needed).
- All 120 quoted PRD citations match PRD.md verbatim (whitespace-normalized grep); the one abbreviated quote found was rewritten in full.
- No `skip`/`skipif`/`xfail` markers; zero "scaffold" references in generated code.

One caveat worth flagging to downstream steps: waitlist FIFO assertions rely on `created_at` being wall-clock-stamped with 3 fractional digits (PRD §2.4), since the logical clock freezes business timestamps at 2026-09-01 — PRD §2.5's business-timestamp list excludes `created_at`, so this is the uniquely derivable reading.

Orchestrator verification: 69 `def test_` functions and 69 `Design:` tags confirmed on disk via grep.

## Step 6: Generate Implementation — 2026-10-01T13:37:00.000Z

Done. The implementation is complete and verified.

## Deliverables — `workspace/implementation/` (18 files)

- `start.sh` (executable, guarded `pip install` on `import flask`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000)
- `requirements.txt`, `app.py` (Flask app factory, per-request global lock, envelope error handlers), `db.py` (empty in-memory stores + logical clock defaulting to `2026-09-01T00:00:00Z`, never wall-clock), `errors.py` (all 58 error IDs with catalog statuses), `util.py` (envelope, auth context, deferred-shape `Body` so `ERR_INVALID_REQUEST` stays the last-priority residual, pagination), `services.py` (fraud scoring variants, trust tiers, cascades, waitlist promotion, conflict detection, outcome report, serializers)
- `routes/`: `clock`, `universities`, `students`, `employers`, `approvals`, `postings`, `events`, `signups`, `applications`, `outreach`

## Endpoint count: 40/40

All endpoints from the scaffold §1.5 table implemented, including the two OCC-gated writes (`decide` → 412 `ERR_STALE_EMPLOYER_VERSION`, session create → 412 `ERR_STALE_CAREER_EVENT_VERSION`).

## Verification (self-run smoke tests, ~90 assertions, two rounds on fresh boots)

Server booted cleanly via `bash start.sh` on a self-allocated port (58743), ready in <1s, store empty at boot, and was killed by exactly the PID bound to that port afterward — no broad kill patterns used. The test suite was never read or run.

Verified behaviors: full auth/role/ownership gate order; fraud auto vs analyst variants (incl. `ERR_FRAUD_RISK_TOO_HIGH`, `REJECT`-from-PENDING with no score recompute, ±40 adjustment bound); approval supersede chain; posting platform-publish gate (recruiter `to=PUBLISHED` on SUBMITTED → 403 `ERR_UNAUTHORIZED_ROLE`, on DRAFT → 409 state error); inclusive application deadline + read-time EXPIRED projection; full application gate chain in pinned eligibility order; buffered interview conflict (exactly-15-min gap passes); half-open room conflict (adjacency passes); session OCC invalidating pre-add versions; exclusive signup deadline; waitlist promotion with email tie-break under a frozen clock; no promotion on event-cancel cascade; student-withdrawal cascade (applications→WITHDRAWN, interviews→CANCELLED, signups→CANCELLED with promotion); employer BLOCK/REVOKE cascade leaving OFFER_EXTENDED untouched; suspension gates on all six operation kinds; messaging allowance floor math with university cap min() → 429; outcome report nested round-half-up ordering (respondent rate 0.3334 vs the rejected raw-order 0.3333, verified with a discriminating 9-alumni dataset).

Notable design decisions (ambiguities resolved against PRD prose): all business/system timestamps read the logical clock; computed counters (`active_application_count`, `occupied_seats`, `enrolled_student_count`, `approved_employer_count`) are derived at read time so cascades self-balance; version bumps only where a stored field mutates (including `last_session_added_at` and `last_trust_decision_at` stamps, per spec); `trust_tier_at_decision` pinned on all three decision directions per PRD §3.3.

Orchestrator verification: 18 files on disk (7 root + 11 routes/), all Python files parse via ast, start.sh executable with $PORT/exec-python3 contract.

## Step 7: Run Tests and Iterate — 2026-10-01T13:57:00.000Z

Clean 8-round sweep achieved. All verification gates pass.

## Summary

**Iterations run:** 2 (sweep 1: 3 tests failing deterministically in all 8 rounds; sweep 2 after fixes: 69/69 passed in all 8 rounds, zero flaky signals).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`** — `/home/ubuntu/github/CodingPRD/tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/test_suite/test_05_employer_approvals.py`:
- `test_block_cascades_to_posting_application_and_interview` and `test_block_leaves_offer_extended_applications_untouched` — STEP 2 test bug (PRD-illegal request). Both tests built an APPROVED approval (mandatory: applications require it per PRD §3.7) and then issued `decision: BLOCK`, which PRD §3.3 verbatim forbids: "From `PENDING`, the administrator may decide `APPROVE` or `BLOCK`; from `APPROVED`, the administrator may decide `REVOKE`." The implementation's `ERR_INVALID_APPROVAL_TRANSITION` rejection was PRD-required. Fixed by deciding `REVOKE` — PRD §3.3 states "`BLOCK` and `REVOKE` additionally fire the same three-hop cascade", so every cascade assertion (posting block-list, AUTO_WITHDRAWN, CANCELLED, OFFER_EXTENDED survival, count conservation) is exercised unchanged; the one status assertion updated `BLOCKED` → `REVOKED`. (A PENDING-with-footprint setup is unreachable: re-request after REVOKE supersedes to PENDING, but the REVOKE itself pre-fires the cascade.)

**Fixes applied to `implementation/`** — wall-clock system timestamps:
- `/home/ubuntu/github/CodingPRD/tasks/task_3375_campus_recruiting_marketplace_employer_approval_student_access/workspace/implementation/db.py` — added `wall_now()` (real UTC); `touch()` now stamps `updated_at` from it.
- 9 route files (`applications, approvals, employers, events, outreach, postings, signups, students, universities`) — all 11 record-creation sites now stamp `created_at`/`updated_at` from `wall_now()` instead of the logical clock; business timestamps (`submitted_at`, `decided_at`, `registered_at`, `outcome_recorded_at`, `sent_day`, all deadline/window comparisons) remain on the logical clock per PRD §2.5's enumeration.
- Why (STEP 3, implementation bug): `test_promotion_is_fifo_by_created_at` failed because the frozen default clock (2026-09-01T00:00:00Z) gave every signup an identical `created_at`, so the §3.6 email tie-break decided every promotion and Bo (`bo@` < `wei@`) was promoted over the earlier-waitlisted Wei. PRD §2.4 classes `created_at`/`updated_at` as system-managed properties; §2.5's logical-clock list enumerates only business timestamps (each of which has its own dedicated field in this implementation); and the frozen reading would render §2.3's creation-order default sort and §3.6's primary sort key inert. No test asserts a concrete `created_at` value, so the change is safe everywhere.

**Artifact check:** all 8 `results.${i}.json` regenerated on disk post-fix; no source file newer than the sweep.

Orchestrator verification: all 8 results.${i}.json show 69/69 passed, 0 failed; newest results (13:56) post-date newest implementation source edit (13:52) and newest test_suite edit (test_05 at 13:53); REVOKE fix spot-checked present in test_05 lines 95–100.

## Step 8: Finalize PRD — 2026-10-01T14:05:00.000Z

Done. The diff is exactly two inline revisions, both tracing to the single `implementation/` fix in the step_7_diff. Line counts: PRD.md 377, PRD_FINALIZED.md 377 (0% delta — revisions are in-place, no lines added or removed).

**Changes**

- §2.4 — revise — the `created_at` and `updated_at` property definitions now state they are "stamped from the server's real wall clock (UTC), not from the logical clock of §2.5" — implementation/db.py:40-44 (`wall_now()`), db.py:76-79 (`touch()`), and the 11 creation sites (routes/universities.py:42-43, students.py:62-63, employers.py:41-42, approvals.py:63-64, postings.py:64-65, events.py:61-62 and 184-185, signups.py:83-84, applications.py:138-139 and 258-259, outreach.py:75-76).
- §2.5 — revise — the universal opening "All temporal evaluation in the system reads a single logical clock" gains the exception sentence: "The sole exceptions are the system-managed `created_at` and `updated_at` properties of §2.4, which are stamped from the server's real wall clock (UTC) and never read this clock." — same impl sites.

The `test_suite/test_05_employer_approvals.py` fix needed no PRD edit: PRD §3.3 already verbatim pins the legal decision transitions and the `ERR_INVALID_APPROVAL_TRANSITION` rejection; the implementation was PRD-conformant and the test was issuing a PRD-illegal `BLOCK` from `APPROVED`.

**Per-edit pre-edit search log**

Edit 1 (§2.4 bullets):
- (a) Subject: clock source for the system-managed `created_at`/`updated_at` stamps.
- (b) Enumerated and read/grepped: `datetime.now`/`utcnow` sweep across all of implementation/ (sole wall-clock read is db.py:44); all `wall_now()` creation sites listed above; all `touch()` callsites (services.py:135/145/170/186/211/228/232, routes employers.py:82/139, postings.py:152/183, students.py:174, applications.py:218, events.py:113/192, universities.py:64, approvals.py:53/146/148, signups.py:166); every `created_at` consumer (util.py:126 list-sort key, services.py:164 waitlist-promotion key, approvals.py:49 supersede "latest" pick) — all three are ordering-only and clock-agnostic, so wall-clock stamps keep §2.3's creation-order sort and §3.6's FIFO promotion accurate.
- (c) Wording adjustment: phrased as "stamped from the server's real wall clock (UTC)" with no claimed relationship to business timestamps or ordering guarantees, so no enumerated path is mis-described.

Edit 2 (§2.5 exception sentence):
- (a) Subject: scope of the logical clock's universality claim.
- (b) Enumerated and read/grepped: every `now()` logical-clock callsite (students.py:163 `outcome_recorded_at`, approvals.py:141 `decided_at`/`last_trust_decision_at`, applications.py:107/136 deadline check + `submitted_at`, signups.py:58/81 window check + `registered_at`, outreach.py:74 `sent_day`, services.py:77/108/144/168 day bucket + expiry projection + `decided_at` + promotion `registered_at`, events.py:191 `last_session_added_at`, clock.py:19 readback, **util.py:59 `api_request_timestamp`** — the envelope timestamp reads the logical clock, so the exception had to name only the two §2.4 properties and nothing broader).
- (c) Wording adjustment: exception is exhaustive ("sole exceptions ... `created_at` and `updated_at`") precisely because util.py:59's envelope timestamp stays on the logical clock; a broader "system timestamps" carve-out would have falsified that path. §1's "every deadline ... never against wall-clock time" was left verbatim — it enumerates only deadline/window/bucket evaluations, all still logical.

Orchestrator verification: diff PRD.md → PRD_FINALIZED.md is exactly the two revisions above (lines 87-88 §2.4, line 95 §2.5); 377 → 377 lines.

## Step 9: Complete PRD — 2026-10-01T14:30:00.000Z

All edits are in place. The work is complete. Here is the summary.

## Summary

**Source:** `PRD_FINALIZED.md` (377 lines, 59,258 chars) → **`workspace/PRD_COMPLETED.md`** (379 lines, 64,567 chars; +2 lines, +5,309 chars).

**Counts:** 19 ambiguity-pins, 3 mismatch-revisions (22 edited paragraphs total, all in-paragraph inserts/revisions; no new sections). All 8 prior sweep results files show 69/69 passing, and the dead-code scan found every helper in `services.py` called (nothing to resolve there).

### Mismatch revisions (PRD contradicted impl)
- **§3.2 screening** — revise — PRD said "every screening call" recomputes the analyst-variant score and re-derives the tier; impl recomputes only on `CLEAR`/`FLAG`, and `REJECT` leaves the stored `fraud_risk_score`/`trust_tier` untouched (null when `REJECT` issues from `PENDING`) — `implementation/routes/employers.py:101-137` (`# REJECT does not recompute the score`).
- **§3.1 outcome window** — revise — PRD restricted writable `outcome_status` to the four non-`UNREPORTED` values; impl's enum accepts `UNREPORTED` too (a write that never stamps/re-stamps `outcome_recorded_at`) — `implementation/routes/students.py:20,137,161-165`.
- **§3.5 session-creation check order** — revise — PRD said "first the event state gate"; impl runs the university-`ACTIVE` gate (`ERR_UNIVERSITY_NOT_ACTIVE`) before the event-open gate — `implementation/routes/events.py:142-147`.

### Ambiguity pins (PRD silent; pinned to impl)
- **§2.2** — insert — `api_request_timestamp` is stamped from the logical clock, not the wall clock — `implementation/util.py:56-60`.
- **§2.2** — insert — undeclared route/unsupported method returns the error envelope with `ERR_INVALID_REQUEST` at routing status 404/405 — `implementation/app.py:40-46`.
- **§2.3** — insert — out-of-range `limit`/`offset` are clamped (to 1/100/0), non-integer is `ERR_INVALID_REQUEST` — `implementation/util.py:104-121`.
- **§2.4** — insert — computed readouts (`enrolled_student_count`, `approved_employer_count`, `active_application_count`, `occupied_seats`, `documents_status`) are derived at read time; underlying-row movement does not mutate the carrier or advance its `version` — `implementation/services.py:316-520`, `implementation/db.py:76-79`.
- **§3.1** — insert — negative `employer_daily_message_cap` is a shape error `ERR_INVALID_REQUEST` — `implementation/routes/universities.py:32`.
- **§3.1** — insert — a `CareerCenterAdmin` may also write `profile_visibility`; outcome-write legality is evaluated against the pre-update status (combined graduate+outcome PATCH fails `ERR_OUTCOME_NOT_RECORDABLE`); a no-op self-update does not increment `version` — `implementation/routes/students.py:117-177`.
- **§3.1** — insert — `PlatformAdmin` student listing is unscoped — `implementation/routes/students.py:73`.
- **§3.2** — insert — `fraud_risk_score`/`trust_tier` are null until domain verification; verification requires status `PENDING` (state check before token check, else `ERR_INVALID_EMPLOYER_TRANSITION`) — `implementation/routes/employers.py:38-39,73-81`.
- **§3.2** — insert — out-of-range `analyst_signal_adjustment` is a shape error `ERR_INVALID_REQUEST` — `implementation/routes/employers.py:95`.
- **§3.2** — insert — employer reads also expose `domain_verification_token`; `CareerCenterAdmin`/`PlatformAdmin` may read any employer — `implementation/services.py:366`, `implementation/routes/employers.py:52-58`.
- **§3.3** — insert — university-`ACTIVE` check precedes transition legality on decide; `decision_reason` is overwritten every decision (omitted → null) — `implementation/routes/approvals.py:122-134,143`.
- **§3.4** — insert — `min_graduation_year`/`max_graduation_year` are required fields — `implementation/routes/postings.py:35-36`.
- **§3.4** — insert — `PlatformAdmin` may target only `PUBLISHED` (any other target → `ERR_UNAUTHORIZED_ROLE`); resumption from `PAUSED` is recruiter-only — `implementation/routes/postings.py:117-128`.
- **§3.4** — insert — `EXPIRED` is never a transition target (`ERR_INVALID_POSTING_TRANSITION`, or `ERR_POSTING_TERMINAL` out of `CLOSED`) — `implementation/routes/postings.py:133-145`.
- **§3.4** — insert — student posting list uses the reported (post-projection) status; `status`/`university_id` filter semantics; recruiter list scoped to own employer; single-posting read visibility-ungated except recruiter ownership — `implementation/routes/postings.py:72-107`, `implementation/services.py:113-124`.
- **§3.4** — insert — clearance error pinning: `CLOSED` → `ERR_POSTING_TERMINAL`; `DRAFT`/`SUBMITTED` → `ERR_INVALID_POSTING_TRANSITION` — `implementation/routes/postings.py:171-176`.
- **§3.5** — insert — event list scoping/filters (`university_id`, `status`; CCA scoped, others unscoped) and single-event/session-list CCA restriction — `implementation/routes/events.py:69-94,196-206`.
- **§3.5** — insert — suspension gate applies to every event transition and is evaluated before transition legality — `implementation/routes/events.py:104-110`.
- **§3.6** — insert — sign-up transition role partition (Student → only `CANCELLED`; CCA → only `ATTENDED`/`NO_SHOW`; else `ERR_UNAUTHORIZED_ROLE`) — `implementation/routes/signups.py:140-144`.
- **§3.6** — insert — sign-up listing scoped for CCA to own university's events, unscoped for `PlatformAdmin` — `implementation/routes/signups.py:91-104`.
- **§3.7** — insert — application transition role partition (recruiter vs student target sets; wrong-role target → `ERR_UNAUTHORIZED_ROLE`) — `implementation/routes/applications.py:196-201`.
- **§3.9** — insert — `per_major` entry shape (`major`, `respondents_count`, `placed_count`, `placement_rate`) and the alumni-but-zero-respondents case (cohort rate computed, respondent rate null, empty `per_major`) — `implementation/services.py:281-301`.

Orchestrator verification: PRD_COMPLETED.md exists (379 lines, differs from PRD_FINALIZED.md per `diff -q`); no implementation source file is newer than the Step 7 sweep results (13:52 < 13:56); results.1.json confirmed 69/69.
