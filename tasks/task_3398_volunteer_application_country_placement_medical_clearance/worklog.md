## Step 1: Create Task Directory — 2026-10-01T16:31:00.000Z

Task directory `./tasks/task_3398_volunteer_application_country_placement_medical_clearance/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and no other task_* directory was created.

## Step 2: Generate Scaffold — 2026-10-01T18:31:00.000Z

Done. All three scaffold artifacts are generated, lint-clean, and cross-audited.

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/SCAFFOLD.yaml` (§1.0–§1.7 only, 1698 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 1781 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 2885 lines)

**Counts**
- Entities: 14 (Applicant, CountryProgram, AssignmentOpening, Application, Interview, Invitation, MedicalClearance, LegalClearance, TrainingCohort, TrainingEnrollment, VolunteerService, SitePlacement, ServiceEvent, CompletionRecord)
- State machines: 11 (incl. cyclic medical-deferral loop, parallel-dimension legal clearance, FILLED↔OPEN seat churn, placement re-review loop)
- Calculations: 8 (weighted match with strict/preference variants, capped interview score, dual-variant readjustment with pinned per-month rounding, pinned-tier medical gap, cohort aggregate-overlap, half-open interview overlap, service duration, ordered clock sweep)
- Endpoints: 52 · Errors: 41 · Validation priority rows: 10 · Roles: 7 (segregation-of-duties on legal review) · OCC concurrency rules: 1 (invitation issuance on opening version)
- **§1.8 difficulty instances: 20** across all 9 rules (≥2 each; combinatorial_formula covers all three modes; boundary_precision_check has 3)
- **§1.9 corner entries: 51** (43 full instances + 8 excluded_because stubs), across all 9 taxonomy sections
- `scaffold_lint.py`: **VERDICT: clean lint** — 927 setup/trigger calls scanned, zero violations; all 12 FKs reverse-reachable

**Hardness drivers**: dual-variant divergence on two entity domains (fiscal allowance vs skill matching), a 4-deep medical-denial cascade (denial→rescission→application revert→seat release/reopen + legal void), invitation issuance-time snapshot pinning vs live program tier, seat-conservation and paid+forfeited==gross invariants, NCE boundary at day 344/345, half-open vs aggregate-capacity overlap semantics, OCC with stale-retry flow, and a deterministic logical clock (default 2026-09-01T00:00:00Z) driving expiry/close/session sweeps. All formula-derived assertion literals were pre-computed in Python (e.g. penalized 6-month payout 190002 = 6×31667, not the 190000 a wrong rounding order yields).

**Corrections made during self-audit**: removed two temporal error codes the deterministic sweep made unreachable and reworked the affected priority-conflict instance to an auth-vs-state pair; quoted `?`-suffixed flow scalars; normalized path placeholders to `{id}` for the FK reverse-reachability heuristic; made `sector_preferences` draft-optional so the submit gate is a live check rather than dead code. No sibling task directories were inspected at any point.

Orchestrator verification: all three files exist, parse as YAML with the required top-level keys, and grep confirms the volunteer-portal domain (no foreign-domain content).

## Step 3: Copy Shared Files — 2026-10-01T18:32:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T18:36:00.000Z

PRD generation complete. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/workspace/PRD.md` — 324 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context + design-pressure angle)
- §2 Global Specifications: 2.1 RBAC (7 roles, identity prose for entity-backed `Applicant` vs 6 opaque roles), 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Deterministic Sweep (default 2026-09-01T00:00:00Z, pinned 4-step sweep order), 2.5 Common Resource Properties (incl. ServiceEvent `id`/`created_at`-only exception), 2.6 Immutable Issuance Snapshots, 2.7 Seat Accounting & Opening Churn, 2.8 OCC at Issuance, 2.9 Validation Discipline & Error Precedence, 2.10 Precision/Rounding/Time Units, 2.11 Cascades & Cross-Aggregate Consistency
- §3 Business Logic: 3.1 Applicants/Programs/Openings, 3.2 Application lifecycle (submit/withdraw/reject with per-state withdrawal cascades), 3.3 Interviews (half-open overlap rule, 30/25/25/20 scoring, min-dimension cap), 3.4 Matching & Invitations (strict vs preference-weighted score variants, 5 issuance gates, OCC), 3.5 Medical Clearance (pinned-tier gap, admissibility matrix, dental, deferral cap 2, denial cascade), 3.6 Legal Clearance (parallel dimensions, segregation of duties), 3.7 Training (aggregate cohort overlap cap, 2.5 technical/cultural floors, second-fail separation, swear-in → VolunteerService), 3.8 Service (placement review loop, event log, suspension, completion vs early termination), 3.9 Readjustment Allowance & NCE (47,500¢/mo, penalized 31,667¢/mo rounding pinned, 18-month standard threshold, 12-month NCE)
- §4 Endpoint Definitions — 52 rows, 4 columns only
- §5 Error Code Catalogue — 41 rows, 2 columns only

**Zero-Silence self-audit (all three hard contracts PASS, verified by script):**
- Contract 1 Field-Name Coverage: 88/88 entity fields, 60/60 endpoint input identifiers, plus all nested/output identifiers (`condition_code`, `strict_score`, `weighted_score`, `matches`, `to_iso8601`, `current_utc`, etc.) present in backticks — 0 missing. All 41 error IDs and all state/enum literals (13 Application states, 10 skill codes, 6 sectors, etc.) present.
- Contract 2 Rule Coverage: all 75 state-machine transitions across 12 machines expressed (from/to pairs, preconditions paired with error IDs, every cascade side-effect including seat release + FILLED→OPEN reopen + clearance voiding); all 8 calculations rendered as reconstruction-test prose (no pseudocode, no fuzzy words — grep-verified zero `>=`/`==`/`~`/"approximately"/"conservatively"); 10 validation priorities stated as an explicit evaluation order in §2.9; 1 OCC rule fully expressed (endpoint, `expected_assignment_opening_version`, `ERR_STALE_OPENING_VERSION`/412, no race framing); `applies_to` scopes enumerated (7 ownership endpoints, 3 compliance-gate endpoints); sibling branches (withdrawal×9 states, review loop×4, determinations×4) at equal density.
- Contract 3 §3 Path Purity: 545 backticked tokens in §3 scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

Orchestrator verification: PRD.md exists (324 lines) and opens with the volunteer/medical-clearance domain content under `/volunteer-portal`.

## Step 5a: Generate Test Helpers — 2026-10-01T18:50:00.000Z

Step 5a complete. All checks pass; no `test_suite/` files were created.

## Files written (9), under `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/test_helpers/`

**Compile check:** `ast.parse` over all 9 files — zero syntax errors; full package import smoke test passed (41 error ids registered, 56 `ApiClient` methods, all fixture/assertion/factory names resolve); date arithmetic verified against the logical clock start `2026-09-01T00:00:00Z` (2027-01-01 + 810d = 2029-03-21, leap-2028 included; all fixture instants ≥ clock start; interview 2026-09-05, issue deadline 2026-12-01, cohort 2027-01-01..2027-03-31, acceptance deadline 2026-09-11 all reachable). No design-index literal needed re-derivation.

## Frozen public interface (Step 5b imports against this verbatim)

- **types.py** — `UserRole`, `SkillCode`, `Sector`, `CountryProgramStatus`, `AssignmentOpeningStatus`, `ApplicationStatus`, `InterviewStatus`, `InterviewRecommendation`, `InvitationStatus`, `DentalStatus`, `MedicalClearanceStatus`, `BackgroundCheckStatus`, `SuitabilityStatus`, `LegalOverallStatus`, `LegalLifecycle`, `TrainingCohortStatus`, `TrainingEnrollmentStatus`, `VolunteerServiceStatus`, `SitePlacementStatus`, `ServiceEventType`, `ServiceEventSeverity`, `CompletionType`, `EtReason`; TypedDicts `MedicalCondition`, `Applicant`, `CountryProgram`, `AssignmentOpening`, `Application`, `Interview`, `Invitation`, `MedicalClearance`, `LegalClearance`, `TrainingCohort`, `TrainingEnrollment`, `VolunteerService`, `SitePlacement`, `ServiceEvent` (append-only: id+created_at, no updated_at/version), `CompletionRecord`.
- **api_client.py** — `ApiClient(GenericApiClient)`, module singleton `api_client`, `PORTAL` prefix constant. 52 methods: `set_clock`, `create_applicant`, `create/get/update_country_program`, `create/get/list_assignment_opening(s)`, `cancel_assignment_opening`, `create/get/list_application(s)`, `submit_application`, `withdraw_application`, `begin_review_application`, `reject_application`, `get_application_matches`, `create/list_interview(s)`, `complete_interview`, `cancel_interview`, `create/get/list_invitation(s)`, `accept_invitation`, `decline_invitation`, `create_medical_clearance`, `list_medical_clearances`, `determine_medical_clearance`, `resubmit_medical_clearance`, `list_legal_clearances`, `adjudicate_background`, `determine_suitability`, `create/get/list_training_cohort(s)`, `create/get/list_training_enrollment(s)`, `assess_training_enrollment`, `remediate_training_enrollment`, `swear_in_training_enrollment`, `get/list_volunteer_service(s)`, `create/list_service_event(s)`, `early_terminate_service`, `complete_service`, `get_completion_record`, `create/list_site_placement(s)`, `review_site_placement`.
- **api_errors.py** — `ApiErrorId` (41 members), `HTTP_STATUS_CODES` (registered with the framework at import).
- **constants.py** — clock (`DEFAULT_CLOCK_START`, `INVITATION_ACCEPTANCE_WINDOW_DAYS`), pagination (10/1/100/0), enum literal lists (`SKILL_CATALOG`, `SECTORS`, `EVENT_TYPES`, `EVENT_SEVERITIES`, `ET_REASONS`, `DENTAL_STATUSES`, `MEDICAL_DETERMINATIONS`, `BACKGROUND_OUTCOMES`, `SUITABILITY_OUTCOMES`, `PLACEMENT_DECISIONS`), bounds (`SCORE_MIN/MAX`, tiers, seats/capacity mins), match weights (0.7/0.2/0.1/0.25/0.5), interview weights and tiers (2.0/4.0/3.0/2.5), `MAX_MEDICAL_DEFERRALS=2`, `TECHNICAL_PASS_MIN=CULTURAL_PASS_MIN=2.5`, readjustment set (`READJUSTMENT_MONTHLY_RATE_CENTS=47500`, `PENALIZED_MONTHLY_CENTS=31667`, `DAYS_PER_MONTH=30`, `HALF_MONTH_DAYS=15`, `SERVICE_TERM_DAYS=810`, `ET_SHORT_SERVICE_THRESHOLD_MONTHS=18`, `NCE_MIN_MONTHS_SERVED=12`, `NCE_DURATION_MONTHS=12`), canonical instants (`INTERVIEW_START/END`, `*_ALT`, `OPENING_DEPARTURE_DATE`, `OPENING_ISSUE_DEADLINE`, `COHORT_START/END_DATE`, `COHORT_NAME`, `SERVICE_START_CLOCK`, `EXPECTED_COMPLETION_DATE`, `INVITATION_DEADLINE_AT_CLOCK_START`, `CLOCK_AFTER_INVITATION_EXPIRY`, `CLOCK_AFTER_ISSUE_DEADLINE`), canonical ET/FULL expected records (0/3/6/11/12/27-month gross/paid/forfeited), `BOGUS_UUID`.
- **test_users.py** — `TEST_USERS` (9 header entries incl. `legal_reviewer_background_headers`/`legal_reviewer_suitability_headers`), id constants (`LEGAL_REVIEWER_BACKGROUND_ID="legal-1"`, `LEGAL_REVIEWER_SUITABILITY_ID="legal-2"`, `MEDICAL_OFFICER_ID`, `PLACEMENT_OFFICER_ID`, `TRAINING_DIRECTOR_ID`, `COUNTRY_DIRECTOR_ID`, `SYSTEM_ADMIN_ID`), `make_applicant_headers(user_id)` (entity-backed, mandatory for ownership-gated calls), `make_legal_reviewer_headers(user_id)`.
- **factories.py** — `create_applicant_payload`, `create_country_program_payload`, `create_assignment_opening_payload`, `create_application_payload`, `create_interview_payload`, `complete_interview_payload` (default 4/3/3/3 → 3.30 RECOMMEND), `create_invitation_payload`, `create/resubmit_medical_clearance_payload`, `determine_medical_payload`, `adjudicate_background_payload`, `determine_suitability_payload`, `create_training_cohort_payload`, `create_training_enrollment_payload`, `assess_enrollment_payload` (default 3.0/3.0/3.0 pass), `create_service_event_payload`, `early_terminate_payload`, `create_site_placement_payload`, `review_site_placement_payload` (emails/country codes auto-unique via counters).
- **assertions.py** — `assert_<entity>` for all 14 entities + invariant checkers `assert_seat_accounting_invariants`, `assert_completion_record_invariants` (paid+forfeited==gross, NCE duration), `assert_legal_overall_consistency` (derived overall_status), `assert_inspection_conjunction`.
- **fixtures.py** — clock `set_clock`; Tier 1: `create_country_program`, `create_assignment_opening`, `create_program_with_opening`, `create_applicant`, `create_training_cohort`, `create_application`, `submit_application`, `begin_review`, `schedule_interview`, `complete_interview`, `get_application`, `get_opening`, `get_cohort`, `get_service`; Tier 3 runners: `run_applicant_to_evaluated`, `issue_invitation` (OCC-safe, fresh-reads version), `accept_invitation`, `get_legal_clearance`, `run_applicant_to_accepted`, `create/determine/resubmit_medical_clearance`, `clear_medical`, `adjudicate_background`, `determine_suitability`, `clear_legal`, `run_applicant_to_fully_cleared`, `enroll_in_cohort`, `run_applicant_to_enrolled`, `ensure_cohort_in_session`, `assess_enrollment`, `swear_in`, `get_service_for_application`, `assess_and_swear_in`, `run_applicant_to_sworn_in`; Tier 2/5 scenarios: `create_accepted_scenario`, `create_fully_cleared_scenario`, `create_enrolled_scenario`, `create_sworn_in_scenario` (dict bundles keyed by entity name); service close: `log_service_event`, `suspend_service_with_security_alert`, `return_service_to_active`, `create_site_placement`, `review_site_placement`, `get_completion_record` (0/1 array → record-or-None), `early_terminate_service_at(service_id, reason, at)`, `complete_service_at(service_id, at)`.
- **__init__.py** — re-exports the framework generics plus all of the above.

Key interface decisions for Step 5b: fixture bundles are plain dicts; all applicant-owned calls inside fixtures already thread `make_applicant_headers(applicant["id"])`; `issue_invitation` always re-reads the opening version so OCC never goes stale inside a fixture; multi-applicant flows compose the per-applicant `run_applicant_to_*` runners against shared program/opening/cohort created by the test.

## Step 5b: Generate Test Suite — 2026-10-01T20:05:00.000Z

Step 5b complete. test_helpers/ untouched (frozen); only test_suite/ was created.

**Files written (14):** test_suite/conftest.py plus test_01_resource_creation.py, test_02_application_workflow.py, test_03_interviews.py, test_04_matching.py, test_05_invitation_issuance.py, test_06_invitation_lifecycle.py, test_07_medical_clearance.py, test_08_legal_clearance.py, test_09_training_cohorts.py, test_10_training_enrollment.py, test_11_service.py, test_12_readjustment.py, test_13_placements.py.

**AST tag audit (real ast.parse + yaml diff):** 82 test functions, 62 distinct Design tags. Queue A: 20/20 difficulty instances at exactly 2 tests each. Queue B: 42/43 non-stub corner instances covered; 8 excluded_because stubs not translated (all cross-references resolve). 0 dangling tags, 0 stub-tagged tests, 0 dual/untagged tests.

**Skipped (1):** Corner/calculations/matches_selector_tiebreak_departure_then_created_at — fails unique derivability: the created_at tiebreak between O2 and O3 is unobservable because the logical clock stamps identical created_at values for both openings (PRD §2.4 "does not consult the wall clock"; §2.10 second-precision comparison), so their relative order is implementation-defined. Not weakened; recorded as a gap.

**Deliberate literal relaxations (two-reader rule, assertion-level):** creation-shape tests omit version==1 (PRD §2.5 says version "increments on every mutation" but never pins the initial value); the OCC test asserts strict monotonic increase instead of exact version numbers; timestamp equalities are compared as parsed datetimes (PRD pins values, not the fractional-digit string format of every field).

**Re-derived literals:** none from the design recipes (all verified against the 2026-09-01T00:00:00Z clock start: 2027-01-01+810d=2029-03-21, day 344/345 -> 11/12 months, 95001 vs 95000 rounding split all confirmed numerically). One new literal introduced by a second test, not a recipe: ET FAMILY at 2028-06-24 (day 540 -> 18 months, STANDARD variant, gross=paid=855000, NCE false) for readjustment_penalized_vs_standard_divergence.

**Verification:** all 145 PRD citation spans grep-verified verbatim against workspace/PRD.md (0 ellipses); pyflakes clean; python3 -m pytest --collect-only -q test_suite/ (PYTHONPATH=task dir) collects 82 tests with 0 errors.

## Step 6: Generate Implementation — 2026-10-01T20:25:00.000Z

Implementation complete and verified. Final report:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (no-op when flask importable), `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| `requirements.txt` | 1 | flask>=3.0,<4 |
| `db.py` | 119 | In-memory STORE (14 empty dicts, zero seeding), logical clock (default exactly 2026-09-01T00:00:00Z), all pinned constants, ISO8601 parse/format, `touch()` (updated_at + version++) |
| `errors.py` | 92 | ApiError, exact envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields in meta for lists), limit/offset validation, 404/405/500 handlers |
| `validate.py` | 121 | Field-shape helpers, all raising ERR_VALIDATION 400 (priority 10) |
| `authz.py` | 32 | X-User-ID/X-User-Role checks → ERR_UNAUTHENTICATED/ERR_FORBIDDEN/ERR_NOT_OWNER |
| `calc.py` | 87 | Decimal/ROUND_HALF_UP: interview overall (round → min-dimension cap 2.0 → tiers 4.0/3.0/2.5), match score (0.7/0.2/0.1, country bonus 0.5 empty / 1.0−0.25·rank), months=(days+15)//30, penalized month=round(47500·2/3)=31667 before multiplying |
| `cascade.py` | 226 | Seat release (provisional/committed + FILLED→OPEN churn), denial cascade, opening-cancel cascade, per-state withdrawal cascade, trainee separation, 4-step pinned clock sweep (strict `<` for invitation/opening deadlines, `<=` for cohort start/conclude, second-precision comparisons) |
| `routes_stage.py` | 215 | applicants, country-programs (POST/GET/PATCH with OPEN↔SUSPENDED→CLOSED machine), assignment-openings (+cancel cascade) |
| `routes_applications.py` | 182 | applications CRUD, submit/withdraw/begin-review/reject, matches selector (OPEN + deadline + seats + strict==1.0 + preference filter; ranked weighted DESC, departure ASC, created_at ASC; 200 empty array when no candidates) |
| `routes_interviews.py` | 132 | per-interviewer half-open overlap (adjacency allowed) → ERR_INTERVIEW_OVERLAP; complete (scores → overall/recommendation → EVALUATED); cancel (last SCHEDULED → UNDER_REVIEW) |
| `routes_invitations.py` | 189 | issuance: OCC `expected_assignment_opening_version` → 412, then EVALUATED/OPEN guards, then skill/recommendation/preference/seats gates in PRD order; pins program/tier/departure, deadline = issued_at + 10d; accept (seat conversion, FILLED at full, LegalClearance auto-created); decline |
| `routes_medical.py` | 186 | create (ACCEPTED + no active duplicate, gap vs pinned tier, clamped ≥0), determine (gap-admissibility → grant flag → dental → deferral cap ≤2, DENIED fires cascade), resubmit (DEFERRED + app ACCEPTED, wholesale replace, deferral_count++) |
| `routes_legal.py` | 91 | adjudicate-background, determine-suitability (background-first, segregation-of-duties → ERR_SUITABILITY_SELF_APPROVAL), derived overall_status (VOID > DENIED > CLEARED > PENDING) |
| `routes_training.py` | 288 | cohorts (aggregate overlap capacity vs training_capacity; adjacency doesn't overlap), enrollment (ACCEPTED → clearances → pinned-program → capacity), assess (cohort IN_SESSION; language ≥ program threshold, technical/cultural ≥ 2.5; REMEDIATION fail → separation cascade), remediate, swear-in (creates ACTIVE VolunteerService, +810 days) |
| `routes_service.py` | 269 | services, append-only events (no updated_at/version; SECURITY_ALERT+CRITICAL suspends, ALL_CLEAR reactivates; MedicalOfficer MEDICAL_CARE-only), complete (term gate 422) / early-terminate with full CompletionRecord ledger, site placements + review loop |
| `routes_clock.py` | 25 | `POST /_clock/set_current_utc`, no-backwards guard, runs sweep |
| `app.py` | 49 | App factory, global RLock per request, blueprint registration, `0.0.0.0:$PORT` (default 10000) |

## Smoke-test transcript
- Booted via `bash start.sh` on dynamic ports 59471 and 41841 (never a hardcoded common port); each run killed by exact listener PID verified via `/proc/<pid>/cwd` (PIDs 2470801, 2471907, 2472868; port confirmed free after each kill).
- Two scripted end-to-end passes, all assertions green: full pipeline (applicant → program → opening → application → submit → review → interview → complete → invitation with 412-then-success OCC → accept → medical gap-1 accommodation flow → legal two-reviewer flow → cohort → enroll → clock sweep starts cohort → assess PASS → swear-in → service → suspend/ALL_CLEAR → placement confirm → early-terminate at day 100 → CompletionRecord paid=95001=3×31667, forfeited=47499, NCE false, placements ENDED).
- Error paths verified: 401, 403 (role + MedicalOfficer event-type + ERR_NOT_OWNER), 404, 409 (overlap, state guards, opening cancel on CLOSED, cohort capacity), 412 stale version, 422 (accommodation, self-approval, housing), 400 backwards clock. Boundary checks: invitation still ISSUED exactly at deadline, EXPIRED one second past; interview/cohort adjacency allowed; expected_completion_date = 2028-11-23 (810 days from 2026-09-05, verified arithmetic).

## Isolation compliance
Zero reads of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`; test suite never executed. Built solely from INSTRUCTION.md, SCAFFOLD.yaml, PRD.md.

## PRD interpretation decisions (candidate over-guards for the fix loop)
1. **Domain timestamps (created_at/updated_at/issued_at/service dates) read the logical clock** ("the system does not consult the wall clock"); `meta.api_request_timestamp` uses the wall clock (transport metadata). Sort ties → insertion order (stable sort).
2. Duplicate email / country_code → **ERR_VALIDATION 400** (no dedicated catalog error).
3. GET matches on a DRAFT application → **ERR_INVALID_APPLICATION_STATE 409** (scaffold names the guard, not the error).
4. PATCH program with status equal to current (e.g. OPEN→OPEN) → **ERR_INVALID_STATE 409** (no self-loop in the machine); field-only edits on a CLOSED program allowed; no-op PATCH returns 200 unbumped.
5. Backwards clock set → **ERR_VALIDATION 400**; equal re-set allowed (sweep idempotent).
6. Missing body FK → ERR_VALIDATION (shape, last); present-but-unknown FK → 404 at existence stage; ownership on create paths applies only when the FK is present.
7. MedicalOfficer with missing/non-MEDICAL_CARE event_type → **ERR_FORBIDDEN at role stage** (before existence).
8. Events append on services in any state; suspend/reactivate transitions fire only from their machine-listed source states.
9. Cohort creation does **not** require the program OPEN (PRD gates only opening creation on program status).
10. Enrollment cohort-not-SCHEDULED → **ERR_INVALID_STATE 409** at state-guard priority (after the app-ACCEPTED check), though PRD §3.7 lists it last in prose.
11. **Legal denial voids the clearance's own lifecycle** (PRD §3.6 "…or a denial"), so overall_status reads VOID after ADVERSE/UNFAVORABLE with dimensions frozen.
12. Country bonus formula literal (1.0 − 0.25·i, unclamped — negative only at rank ≥ 5).
13. Out-of-range/non-integer `limit`/`offset` → ERR_VALIDATION 400 (min 1 / max 100 / offset ≥ 0).
14. Version increments per individual mutation, including each seat-counter change inside cascades (PRD §2.7); PATCH bumps once per call.
15. `determine` with an unknown determination enum skips admissibility gates → ERR_VALIDATION (priority 10); `accommodation_granted` must be JSON `true`.
16. Resubmit from non-DEFERRED → **ERR_INVALID_STATE** (ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE reserved for determine).

Orchestrator verification: all 18 source files + start.sh present; start.sh parses (`bash -n`); literal drift spot-check (clock start, 10-day window, 810 days, 47500/31667, 2.5 floors, 0.7/0.25 weights, 18/12 thresholds) shows test_helpers/constants.py and implementation agree.

## Step 7: Run Tests and Iterate — 2026-10-01T20:35:00.000Z

Clean sweep confirmed. The newest implementation source file (routes_service.py, 20:22) predates the sweep start (20:28), so no post-sweep edits invalidate the results. All 8 `results.*.json` files persist in `workspace/implementation/` per the output contract.

**Summary**

- **Iterations run:** 1 — clean 8-round parallel sweep on the first attempt.
- **Sweep outcome:** All 8 rounds report `passed=82, failed=0, errors=0, skipped=0` out of `total=82`. No flakiness surfaced across the 8 concurrent rounds (union of failing tests is empty).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

The Step 6 implementation (18 source files under `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/workspace/implementation/`, built solely from PRD.md + INSTRUCTION.md) passes the full 82-test suite (14 test modules: resource creation, application workflow, interviews, matching, invitation issuance/lifecycle, medical/legal clearance, training cohorts/enrollment, service, readjustment, placements) under `--isolation per-test-server` with zero failures. The one known coverage gap remains the deliberately skipped scaffold corner `matches_selector_tiebreak_departure_then_created_at`, which Step 5b already adjudicated as failing unique derivability (logical clock stamps identical `created_at` for both openings, so the tiebreak is unobservable) — no test exists for it, so nothing to delete or fix.

Orchestrator verification: all 8 `results.{1..8}.json` files read directly — each shows passed=82 total=82 failed=0 errors=0.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T20:36:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-10-01T20:50:00.000Z

All verification is complete. The mtimes confirm every implementation/test/results file predates this session (pipeline writes 19:48–20:31; my only write is PRD_COMPLETED.md at 20:45), and results.*.json (20:30) postdate the last implementation write (20:22), so the sweep evidence stands untouched.

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_3398_volunteer_application_country_placement_medical_clearance/workspace/PRD_COMPLETED.md` as a minimal inline patch over `PRD.md` (no `PRD_FINALIZED.md` existed — Step 8 was skipped).

**Size:** PRD.md 324 lines / 56,238 chars → PRD_COMPLETED.md 324 lines / 57,858 chars. Char delta: **+1,620**, line count unchanged (all edits are in-paragraph; no new sections or paragraphs).

**Counts:** 16 ambiguity-pins, **0 mismatch-revisions** — the implementation matched every pinned PRD behavior audited (all 53 endpoints, both state machines, sweep order, seat accounting, OCC, denial/withdrawal/cancellation cascades, interview/match/readjustment arithmetic, error catalog statuses).

One bullet per change:

- §2.3 — insert — ambiguity — multiple filter params on one list endpoint combine conjunctively — routes_stage.py:193-199 (pattern repeated in all list endpoints)
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset` + returned items < `total_count` — errors.py:45
- §2.4 — revise — ambiguity — setting the clock strictly backwards fails with `ERR_VALIDATION` (HTTP 400); re-setting the same instant is allowed and re-runs the idempotent sweep — routes_clock.py:21-24
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — db.py:113
- §3.1 — insert — ambiguity — duplicate applicant `email` fails with `ERR_VALIDATION` (HTTP 400) — routes_stage.py:34-36
- §3.1 — insert — ambiguity — duplicate `country_code` fails with `ERR_VALIDATION` (HTTP 400) — routes_stage.py:62-64
- §3.1 — revise — ambiguity — a program status transition outside the declared set, including re-entering the current status, is rejected with `ERR_INVALID_STATE` (HTTP 409) — routes_stage.py:99-104
- §3.1 — revise — ambiguity — `CLOSED` is terminal for the status machine only; `medical_support_tier`/`training_capacity`/`language_threshold_score` remain patchable afterwards — routes_stage.py:108-124
- §3.1 — revise — ambiguity — a PATCH that changes no field performs no mutation and does not increment `version` — routes_stage.py:112-126
- §3.2 — insert — ambiguity — a repeated entry in `country_preference_ids` fails with `ERR_VALIDATION` (HTTP 400) — routes_applications.py:46-47
- §3.4 — insert — ambiguity — reading the match list of a `DRAFT` application fails with `ERR_INVALID_APPLICATION_STATE` (HTTP 409) — routes_applications.py:145-147
- §3.4 — insert — ambiguity — the match list is returned in full, non-paginated, in a single object envelope whose `data` carries the `matches` array — routes_applications.py:180-182
- §3.4 — insert — ambiguity — the reported `strict_score` is the exact unrounded fraction (the §2.10 two-decimal rule applies to `weighted_score`, not to it) — routes_applications.py:174, calc.py:51-55
- §3.5 — revise — ambiguity — resubmitting from a non-`DEFERRED` clearance state fails with `ERR_INVALID_STATE` (HTTP 409) — routes_medical.py:167-169
- §3.7 — insert — ambiguity — cohort creation does not consult the program's `status` (cohorts may be stood up under `SUSPENDED`/`CLOSED` programs, unlike opening creation) — routes_training.py:38-43
- §3.7 — revise — ambiguity — enrollment into a non-`SCHEDULED` cohort fails with `ERR_INVALID_STATE` (HTTP 409) — routes_training.py:128-130
- §3.7 — revise — ambiguity — swear-in advances the enrollment itself to `SWORN_IN` (not just the application) — routes_training.py:265, 285-287

**Scope confirmation:** No file other than `workspace/PRD_COMPLETED.md` was created or modified. `workspace/PRD.md`, `workspace/implementation/`, `test_helpers/`, and `test_suite/` are byte-untouched.

Orchestrator verification: `diff -q PRD.md PRD_COMPLETED.md` confirms a real edit (not a byte-identical no-op); all 8 `results.{1..8}.json` persist; zero implementation `.py` files are newer than the sweep results, so the clean sweep remains valid.
