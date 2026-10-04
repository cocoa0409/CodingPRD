# Worklog — task_3399_teacher_portfolio_submission_assessment_center_scoring

## Step 1: Create Task Directory — 2026-10-01T16:35:00.000Z

Task directory was pre-allocated by the caller (`./tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring` with `workspace/` inside); verified it exists and no new task_* directory was created. Scenario: Teacher Portfolio Submission & Assessment Center Scoring (NBPTS). Difficulty instruction for scaffold-generator only: "Generate task much harder than expert level!" Orchestrator runs Steps 5 and 6 SEQUENTIALLY (model endpoint duplicates parallel tool calls — one tool call per message maximum).

## Step 2: Generate Scaffold — 2026-10-01T17:15:00.000Z

All checks pass. Final state verification is complete. Here is the summary.

## Summary

**Task**: `task_3399_teacher_portfolio_submission_assessment_center_scoring` — Teacher Portfolio Submission & Assessment Center Scoring (NBPTS-style), generated at "much harder than expert" difficulty purely from the scenario + skill spec (no sibling tasks consulted).

**Files** (all parse cleanly with `yaml.safe_load`):
- `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/SCAFFOLD.yaml` — 1445 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2428 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/SCAFFOLD_CORNER_DESIGN.yaml` — 3410 lines, single top-level key `scaffold_corner_design`

**§1.0–§1.7 counts**: 13 entities, 10 state machines (cyclic: Candidate eligibility-resubmit, ComponentSubmission revision/retake self-chain, Assessor retraining, Certification deny-reopen, Program exhaust-reopen; branching: Booking, Assignment, Renewal, Stipend), 11 calculations, 10 validation priority groups, **40 endpoints**, 58 error codes, 6 roles (Anonymous + Candidate/Assessor entity-backed + 3 opaque admin roles; segregation-of-duties role model). Profile: workflow_orchestration × temporal_windowing, graph topology (cross-aggregate + polymorphic assignment target + self-referential retake), layers: selector_policy / cascading_side_effects / rate_threshold_triggers / scheduled_actions. `concurrency_rules` deliberately empty per the §1.2.1 serial-observability filter (every apparent race reduces to a state precondition here).

**§1.8**: 18 instances (9 rules × 2), all with fully-executed literal arithmetic — e.g. provisional 2.35 vs final 2.40 dual-variant totals; exact 0.50 vs adjacent 1.00 IRR rates over the same 10 reads (auto-suspend); stipend `min(round(300000×0.8×1.10), 200000)=200000`; rounding-order divergence proven by code (pinned per-component round3 yields 0.45 → CERTIFIED at threshold 0.45, sum-then-round would give 0.44 → DENIED); threshold equality 1.75 certifies; capacity == 2 blocks the 3rd booking; depth-3 cascade (submit-score → FINALIZED → SCORED → CERTIFIED → stipend PROPOSED 330000); depth-2 suspension → REASSIGNED → read slot reopens; half-open cycle adjacency vs exact-instant slot pooling; budget-cents and slot-seat conservation invariants.

**§1.9**: 79 instances (67 active + 12 `excluded_because` stubs resolving to §1.8 names) across all 9 guide sections — including a 15-id 404 sweep, 4 RBAC denials + 2 ownership denials, selector ranking/tie-break/empty-pool, clock-default 2026-09-01T00:00:00Z, renewal 44-vs-45-hour boundary with RETURN/resubmit loop, certification expiry sweep at 2032-05-31, DENIED-at-1.74 reopen, district-vs-statewide stipend matching.

**Verification**: `scaffold_lint.py` → **VERDICT: clean lint** (1821 calls scanned). Additional self-audits (all clean): placeholder closure per instance, grounds resolvability against §1.1–§1.7, stub references, error-code triggerability (every one of the 58 ids exercised), instance-name uniqueness, forbidden-vocabulary grep, file-split rule. Two authoring bugs found and fixed en route: an unbound-anchor chain (`*r2_cal_asg2` missing in 7 chains) and a late program creation that would have broken the fiscal corner's cascade ordering.

Orchestrator spot-check: wc -l confirms 1445/2428/3410; all three parse with yaml.safe_load; SCAFFOLD.yaml top-level keys contain neither design key; endpoint count = 40.

## Step 3: Copy Shared Files — 2026-10-01T18:12:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes, verified present).

## Step 4: Generate PRD — 2026-10-01T18:25:00.000Z

The file is complete and verified end-to-end — no truncation, no duplicated sections, all five top-level sections present. Final report:

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/workspace/PRD.md` — **318 lines**

**Structure:** §1 Introduction (2 paragraphs, goals + design commitments angle); §2.1–2.9 (roles/identity prose, verbatim §2.2 envelope, pagination, logical clock + sweeps, resource identity incl. the Artifact `common_fields: false` exception, score grid/rounding, window boundary semantics, 10-gate validation priority with 3 pinned intra-endpoint orderings, no-OCC concurrency); §3.1–3.8 (cycle config, eligibility loop, attempts/artifacts/retakes, assessment-center sessions, assessor pipeline, double-blind scoring/adjudication, certification/renewal/expiry, incentive programs/stipends); §4 endpoint table (4 columns); §5 error catalogue (2 columns).

**Coverage counts:**
- Endpoints: **40/40** rows in §4 (36 unique paths, all verified present)
- Error IDs: **58/58** in §5 table and 58/58 named in §2/§3 prose with trigger conditions and HTTP statuses
- State machines: **10/10** covered (CertificationCycle, Candidate, ComponentSubmission, AssessmentBooking, Assessor, ScoringAssignment, Certification, RenewalApplication, IncentiveProgram, StipendPayment) — every transition named with source/target states, trigger actor, preconditions paired to error IDs, and side effects including all cascades (booking-completion 3-hop, suspension → REASSIGNED, cycle-expiry sweeps, CERTIFIED → stipend auto-proposal)
- Calculations: **11/11** covered — weighted score with pinned round-3dp-then-sum-2dp order plus the 0.45-vs-0.44 worked example; stipend amount pinned multiplier→tentative→cap order with the 264000/330000/200000 worked example; counted_score max-over-SCORED; IRR window; calibration outcome (inclusive boundary); slot capacity (exact-instant pools); renewal hours; validity arithmetic; selector policy with total deterministic ranking

**Constant-pinning self-check:** 37/37 pinned-value checks pass — MIN_TEACHING_YEARS 3, SESSION 120 min, 500/50 MB, 15 min video, calibration 2/3, divergence 0.50 (inclusive), grid [0.00, 4.00] step 0.25, IRR window 10 / floor 0.70 (equality does not suspend) / band 0.25, early-bird 1.10, renewal 45 h (inclusive), validity 1825 days, renewal window 90/30 days inclusive, max_attempts default 2, fte default 1.0 in [0.5, 1.0], tolerance default 0.25, startup clock 2026-09-01T00:00:00Z, weights sum exactly 1.000, pagination 10/1/100/0.

**Hard contracts:** Contract 1 PASS (89/89 field/input tokens in backticks; two passes — first pass was a false alarm caused by code-fence backtick parity, fixed by stripping fences). Contract 2 PASS (priorities, no-OCC statement, side-effect cascades, applies-to scopes, field defaults, sibling-branch symmetry all expressed). Contract 3 PASS (439 §3 backtick tokens scanned, 0 paths/methods).

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. One tool call per message throughout; heredocs all quoted so no backtick execution.

Orchestrator spot-check: PRD.md = 318 lines; 40/40 endpoint paths and 58/58 error_ids from SCAFFOLD.yaml appear in PRD; `certification_threshold` is a scaffold input field (not a fixed constant) and PRD pins the equality semantics; clock default 2026-09-01T00:00:00Z present; design worked-example values (1.75, 2.35) correctly absent from PRD.

## Step 5a: Generate test_helpers (frozen infrastructure) — 2026-10-01T18:50:00.000Z

Step 5a complete. Summary for worklog:

## Files delivered (all under `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/`)

| File | Lines |
|---|---|
| test_helpers/__init__.py | 59 |
| test_helpers/types.py | 316 |
| test_helpers/api_client.py | 179 (40 endpoint methods — full PRD §4 inventory) |
| test_helpers/api_errors.py | 143 (58 error IDs, all registered with the framework) |
| test_helpers/assertions.py | 282 |
| test_helpers/factories.py | 347 |
| test_helpers/constants.py | 115 |
| test_helpers/test_users.py | 69 |
| test_helpers/fixtures.py | 505 |
| test_suite/conftest.py | 68 (no test_*.py files — verified zero exist) |

## Constant cross-check (constant → PRD quote location)

- CLOCK_STARTUP_DEFAULT_ISO = "2026-09-01T00:00:00Z" → §2.4 "At startup the clock reads exactly 2026-09-01T00:00:00Z"
- SCORE_MIN/MAX/STEP = 0.00/4.00/0.25 → §2.6 "at least 0.00, at most 4.00, and an exact multiple of 0.25"
- VIDEO_MAX_MB 500, DOC_MAX_MB 50, VIDEO_MAX_MINUTES 15, VIDEO_FORMATS mp4/mov, DOCUMENT_FORMATS pdf/docx → §3.3
- MIN_TEACHING_YEARS 3 → §3.2 "years_experience must be at least 3"; fte default 1.0, range [0.5, 1.0] → §3.2
- REQUIRED_WEIGHT_SUM 1.000, DEFAULT_MAX_ATTEMPTS 2 → §3.1
- SESSION_DURATION_MINUTES 120 → §3.4 "slot_start_at plus 120 minutes"
- REQUIRED_CALIBRATION_PASSES 2, MAX_CALIBRATION_FAILURES 3 → §3.5
- IRR_WINDOW 10, IRR_EXACT_FLOOR 0.70, ADJACENT_BAND 0.25 → §3.5
- DIVERGENCE_TOLERANCE 0.50, DEFAULT_BENCHMARK_TOLERANCE 0.25 → §3.6
- MIN_RENEWAL_HOURS 45, VALIDITY_DAYS 1825, RENEWAL_LOOKBACK_DAYS 90, RENEWAL_GRACE_DAYS 30 → §3.7/§2.7
- DEFAULT_EARLY_BIRD_MULTIPLIER 1.10 → §3.8
- Pagination 10/1/100/0 → §2.3

No dead scaffold-only constants. All 58 ApiErrorId members machine-verified against the PRD §5 table (zero mismatches, zero missing). Standard-fixture dates (window 2027-01-01/03-01, retake 2027-04-15, threshold 1.75) live in factories.py as test-construction defaults, not constants.py.

## Ownership model in test_users.py

- Candidate/Assessor are entity-backed: `make_candidate_headers(candidate["id"])` / `make_assessor_headers(assessor["id"])` are the canonical builders; fixtures thread real entity ids everywhere (submit, retake, artifacts, bookings, renewals, submit-score). Distinct builders per owner — never a shared constant across distinct owners.
- Anonymous/ScoringAdministrator/BoardAdministrator/IncentiveAdministrator are opaque: shared TEST_USERS constants are canonical.
- Shared candidate_headers/assessor_headers constants kept only as non-ownership fallbacks, documented as such; conftest exposes `candidate_headers_for` / `assessor_headers_for` factory fixtures.

## Verification results

- `python3 -m py_compile` on all 10 files: COMPILE_OK.
- Import smoke (`import test_helpers.factories, fixtures, assertions, api_client, test_users, constants, types, api_errors` + barrel): IMPORT_OK; only third-party deps are `requests` and the framework `prd_bench_local_runner.testing`.
- `expected_weighted_total` reproduces PRD §2.6's pinned worked example exactly (0.45 for weights [0.325,0.275,0.225,0.175] × scores [0.00,0.25,0.50,1.50]; standard pipeline yields 2.40).
- `assertions.validate_created` wraps `validate_success(response, 201)` for the 12 creation endpoints; `validate_error_is_one_of` re-exported. `assert_artifact` enforces absence of `updated_at`/`version` per PRD §2.5.

## PRD gaps / design-index hazards flagged for Step 5b

1. **Off-grid literal in a design recipe**: corner instance `certification_denied_at_1_74_reopens_on_retake` uses CKA 2.85 — not a multiple of 0.25, so PRD §2.6 requires ERR_SCORE_INVALID at booking completion. 5b must re-derive a grid-legal score set summing below 1.75 (e.g. CKA 2.75 → 1.70) instead of copying the literal.
2. **Drifted date literals**: difficulty instances assert `valid_until == 2032-05-30T00:00:00Z` for certified_at 2027-01-20T15:00:00Z, but PRD §3.7's "certified_at plus 1825 days" yields 2032-01-19T15:00:00Z (and the renewal instance's 2037-05-29 is derived from the same drifted base). Helpers avoid hardcoding either value — `assert_certification_validity_window(cert, certified_at, days)` computes the expectation dynamically from PRD's rule.
3. factories omit optional fields (fte_fraction, tolerance, early_bird_multiplier, sponsor_district_code, max_attempts_per_component when forced via `None`) so server-side defaults are exercised as the PRD declares, matching the design recipes' payloads verbatim.

Orchestrator spot-check: all 10 files compile (py_compile clean); import smoke IMPORT_OK; constants.py carries the PRD clock value; grep confirms no drifted literals (2032-05-30 / 2037-05-29 / 2.85) in test_helpers/; line counts match; zero test_*.py in test_suite/.

## Step 5b: Generate test_suite (102 tests) — 2026-10-01T19:45:00.000Z

Step 5b complete. Summary for worklog.md:

## Step 5b — test suite generated (task_3399)

**Test files (12 files, 3814 lines, 102 tests, all py_compile-clean, `pytest --collect-only` collects 102 with zero errors):**

| File | Lines | Tests |
|---|---|---|
| test_01_cycles.py | 218 | 9 |
| test_02_candidates_eligibility.py | 270 | 9 |
| test_03_submission_lifecycle.py | 512 | 17 |
| test_04_artifacts.py | 208 | 7 |
| test_05_assessment_center_bookings.py | 465 | 14 |
| test_06_assessor_pipeline.py | 286 | 8 |
| test_07_scoring_assignments.py | 478 | 13 |
| test_08_assessor_reliability.py | 98 | 2 |
| test_09_certification.py | 512 | 11 |
| test_10_certification_renewal.py | 202 | 3 |
| test_11_incentives_stipends.py | 433 | 7 |
| test_12_errors_auth.py | 132 | 2 |

**AST tag audit** (ast-parsed docstrings, tags verified as the docstring's last line; indices parsed with yaml):
- Queue A (difficulty): 18/18 instances emitted at exactly 2 tests each (36 tests). 0 missing, 0 thin, 0 skipped.
- Queue B (corner): 67 non-stub instances; 66 emitted, 1 documented skip (below). 12 `excluded_because` stubs correctly untranslated (cross-references all resolve).
- Orphan tags (resolving to no index instance): 0. Untagged/multi-tagged tests: 0. Stub-tag violations: 0.
- Separate citation audit: 160 quoted docstring segments; all survive whitespace-normalized literal grep of PRD.md.

**Skipped instance (PRD-first filter):**
- `Corner/entities/cycle_create_invalid_component_kind_returns_invalid_request` — SKIP: PRD does not uniquely derive the outcome. A `kind: "QUIZ"` component both (a) is a malformed enum value → plausibly 400 ERR_INVALID_REQUEST, and (b) leaves the cycle with zero ASSESSMENT components, violating §3.1's "Exactly one component of the cycle may be of `ASSESSMENT` kind" → plausibly 422 ERR_WEIGHT_SUM_INVALID. Two faithful PRD-only readers diverge; the recipe hardcodes reading (a).

**Literal re-derivations (all three hazard flags applied):**
1. `Corner/state_machines/certification_denied_at_1_74_reopens_on_retake` — recipe's CKA earned_score 2.85 is off the 0.25 grid (PRD §2.6 → ERR_SCORE_INVALID at booking completion). Substituted grid-legal CKA 2.75 with P1 1.50 / P2 1.00 / P3 0.50 → weighted_total_final 1.70 < 1.75 → DENIED (same branch). Substitution documented in the docstring.
2. `Corner/state_machines/certification_expires_after_valid_until` — recipe's valid_until 2032-05-30T00:00:00Z and 2032-05-31 sweep were drifted. Test asserts via frozen `assert_certification_validity_window(cert, certified_at, VALIDITY_DAYS)` (2032-01-19T15:00:00Z) and sweeps at valid_until + 1 day computed from the cert's own field.
3. `Corner/calculations/renewal_total_hours_boundary_and_validity_extension` — recipe's window-open clock 2032-03-01T00:00:00Z and post-renewal valid_until 2037-05-29 descend from the same drift; under the PRD rule the window opens at valid_until − 90d = 2031-10-21T15:00:00Z (the recipe's clock would land past the window's far edge, 2032-02-18). The test derives both the filing clock and the post-renewal window from the certification's own valid_until at runtime. Also used the validity helper in `Difficulty/transitive_cascade/read_finalization_cascades_to_certification_and_stipend` instead of its drifted 2032-05-30 literal.

**Other adjudication choices:** timestamp equality assertions (created_at/certified_at/calibrated_at) compare parsed instants, since PRD §2.5 renders timestamps with three fractional digits while §2.4 writes the clock without — the instant is uniquely derivable, the string is not. `version == 1` recipe literals were relaxed to POST/GET version agreement (immediate consistency); PRD pins that version increments on mutation, not the start value.

**Frozen-helper defects:** none found. All helpers behaved as documented (fixtures, factories, assertions, error map).

Orchestrator spot-check: `pytest --collect-only` independently re-run → 102 collected, 0 errors; independent AST re-audit → 102/102 valid Design tags, 0 orphans, and the only missing active instance is exactly the documented skip (`cycle_create_invalid_component_kind_returns_invalid_request`); apparent extra "missing" names from the crude walk (`Center Five`, `Center Cap2`, `NM Program`, ...) verified as payload `name:` field values inside recipe grounds, not instance names.

## Step 6: Generate Implementation — 2026-10-01T20:35:00.000Z

All done. Final summary for the worklog follows.

---

## Step 6 implementation summary — task_3399_teacher_portfolio_submission_assessment_center_scoring

### Files written (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Guarded pip install (import-check), `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| requirements.txt | 1 | flask>=3.0 |
| app.py | 59 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| constants.py | 80 | Every PRD constant, defined exactly once |
| errors.py | 82 | ApiError + all 56 catalog error ids |
| store.py | 88 | In-memory dict store (starts empty), logical clock at 2026-09-01T00:00:00Z, timestamp helpers, stamp/touch |
| response.py | 51 | Success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination in meta) |
| validation.py | 109 | Gates 1-2 (headers, role), body/field/datetime/number parsing, 0.25-grid score check, pagination (10/1/100/0) |
| domain.py | 340 | Weighted aggregation (round-3dp-then-sum, half-up), counted_score/superseded derivation, certification decision, stipend auto-proposal, selector policy, suspension cascade, IRR window, booking cascade, clock sweeps |
| serializers.py | 212 | Per-entity serializers; computed fields derived on read |
| routes_clock.py | 20 | clock endpoint |
| routes_cycles.py | 143 | cycle CRUD/transition with expiry sweeps |
| routes_candidates.py | 121 | registration + eligibility loop |
| routes_submissions.py | 228 | attempts, submit, tech-review, retake, list |
| routes_artifacts.py | 99 | artifact upload/list with format/size/duration gates |
| routes_centers.py | 43 | assessment centers |
| routes_bookings.py | 164 | booking create/read/list/transition + completion cascade |
| routes_assessors.py | 112 | assessor ladder + benchmarks |
| routes_scoring.py | 238 | assignments, selector, submit-score, agreement/adjudication resolution |
| routes_certifications.py | 175 | certifications + renewal lifecycle |
| routes_incentives.py | 140 | programs + stipend lifecycle |

### 40-endpoint → handler mapping

POST /_clock/set_current_utc → routes_clock.py:set_current_utc · POST /cycles → routes_cycles.py:create_cycle · GET /cycles/{id} → routes_cycles.py:get_cycle · POST /cycles/{id}/transition → routes_cycles.py:transition_cycle · POST /benchmarks → routes_assessors.py:create_benchmark · POST /candidates → routes_candidates.py:create_candidate · GET /candidates/{id} → routes_candidates.py:get_candidate · POST /candidates/{id}/submit-eligibility → routes_candidates.py:submit_eligibility · POST /candidates/{id}/verify-eligibility → routes_candidates.py:verify_eligibility · POST /cycles/{id}/submissions → routes_submissions.py:create_submission · GET /submissions/{id} → routes_submissions.py:get_submission · GET /submissions → routes_submissions.py:list_submissions · POST /submissions/{id}/submit → routes_submissions.py:submit_submission · POST /submissions/{id}/tech-review → routes_submissions.py:tech_review · POST /submissions/{id}/retake → routes_submissions.py:retake_submission · POST /submissions/{id}/artifacts → routes_artifacts.py:upload_artifact · GET /submissions/{id}/artifacts → routes_artifacts.py:list_artifacts · POST /assessment-centers → routes_centers.py:create_center · GET /assessment-centers/{id} → routes_centers.py:get_center · POST /bookings → routes_bookings.py:create_booking · GET /bookings/{id} → routes_bookings.py:get_booking · GET /bookings → routes_bookings.py:list_bookings · POST /bookings/{id}/transition → routes_bookings.py:transition_booking · POST /assessors → routes_assessors.py:create_assessor · GET /assessors/{id} → routes_assessors.py:get_assessor · POST /assessors/{id}/transition → routes_assessors.py:transition_assessor · POST /assignments → routes_scoring.py:create_assignment · GET /assignments/{id} → routes_scoring.py:get_assignment · GET /assignments → routes_scoring.py:list_assignments · POST /assignments/{id}/submit-score → routes_scoring.py:submit_score · GET /certifications/{id} → routes_certifications.py:get_certification · GET /certifications → routes_certifications.py:list_certifications · POST /certifications/{id}/renewals → routes_certifications.py:create_renewal · GET /certifications/{id}/renewals → routes_certifications.py:list_renewals · POST /renewals/{id}/review → routes_certifications.py:review_renewal · POST /incentive-programs → routes_incentives.py:create_program · GET /incentive-programs/{id} → routes_incentives.py:get_program · GET /incentive-programs/{id}/stipends → routes_incentives.py:list_program_stipends · GET /certifications/{id}/stipends → routes_incentives.py:list_certification_stipends · POST /stipends/{id}/transition → routes_incentives.py:transition_stipend

### Constant-definition grep

All 33 named constants (clock default, 0.00-4.00/0.25 grid, 3dp-then-2dp quants, weight sum 1.000, 1825 validity days, 45 renewal hours, 90/30 renewal window, IRR 10/0.70/0.25, calibration 2/3, divergence 0.50, defaults max_attempts 2 / fte 1.0 / tolerance 0.25 / early-bird 1.10, 500MB/50MB/15min, 120-minute session, MIN_TEACHING_YEARS 3, FTE [0.5,1.0], pagination 10/1/100/0) — exactly one definition each, all in constants.py.

### Interpretations chosen (PRD citations)

1. **Computed fields derived on read** (counted_score, superseded, budget_remaining_cents, program OPEN/EXHAUSTED, open_assignment_count, IRR rates, weighted_total_provisional) — PRD 3.8 "budget_remaining_cents is derived, never stored by hand"; PRD 3.7 provisional "recomputed on every score event". Makes the compensating invariant and EXHAUSTED↔OPEN flips structurally exact.
2. **0-budget program reads EXHAUSTED immediately** — PRD 3.8 "EXHAUSTED exactly when the remaining budget reaches 0" (overrides scaffold's initial_state OPEN).
3. **Artifact upload state gate** uses ERR_SUBMISSION_NOT_SUBMITTABLE (409) — PRD 3.3 restricts uploads to IN_PROGRESS/RETURNED without naming an error; this is the catalog entry whose condition matches. No kind gate (no error id exists for artifacts on ASSESSMENT attempts).
4. **POST /candidates with a non-Anonymous role header** → ERR_INSUFFICIENT_PERMISSIONS; header-presence gate still skipped (PRD 2.1).
5. **Unknown role strings** pass gate 1 (non-empty = well-formed), fail gate 2 (not in any role list).
6. **Unknown Candidate X-User-ID** on submission/booking create → ERR_CANDIDATE_NOT_FOUND (404) before the ELIGIBLE check.
7. **Booking transition dispatch**: per-action actor gate before the BOOKED state check — CANCELLED by anyone but the owning candidate → ERR_NOT_RESOURCE_OWNER (PRD 3.4 "anyone other than the owning candidate"); COMPLETED/NO_SHOW by a Candidate → ERR_INSUFFICIENT_PERMISSIONS; missing/unknown `to` → ERR_INVALID_REQUEST.
8. **Stipend unknown `to`** → ERR_STIPEND_NOT_TRANSITIONABLE (PRD 3.8 "any transition request outside these declared moves"); missing `to` → ERR_INVALID_REQUEST.
9. **Assessor system-only transitions requested directly** → ERR_INVALID_ASSESSOR_TRANSITION (PRD 3.5).
10. **Benchmark target without assessor_id** → ERR_INVALID_REQUEST (400); the selector's trigger is scoped to submission targets only (SCAFFOLD §1.3 assessor_selector).
11. **Assignment body-id existence (404) before target-ambiguity (422)** — gates 4 before 7; the pinned ordering (ambiguity before conflict-of-interest, PRD 2.8) is preserved.
12. **Score accepted on an ASSIGNED assignment whose submission EXPIRED mid-flight** records the score but never resurrects the submission — PRD 3.1 "expired attempts never score"; no error id exists for the corner, none invented.
13. **REASSIGNED reads don't count** for read_number or read segregation — PRD 3.5 "the submission's missing reads become re-assignable".
14. **Calibration counters increment past thresholds** but auto-transitions fire only from CALIBRATING (scaffold preconditions).
15. **Renewal resubmission reuses the most recent RETURNED application**, returned with 201 (the endpoint's declared code).
16. **review_note stored on both APPROVE and RETURN** (scaffold: "note from the latest renewal decision").
17. **Datetime rendering**: created_at/updated_at/meta always 3 fractional digits (PRD 2.5/2.2); clock/input datetimes render seconds+Z (ms only when sub-second), matching the PRD clock literal format.
18. **No backward-clock guard** — PRD 2.4 declares exactly two sweeps and no error for backwards moves.
19. **Pagination clamps** out-of-range limit/offset into bounds (PRD 2.3 "capped"); non-integer → ERR_INVALID_REQUEST.
20. **No uniqueness enforcement** on cycle.code / candidate.email / assessor.email — PRD §5's fixed catalog has no duplicate error id.

### Self-smoke-test transcript

- `python3 -m py_compile` on all 19 .py files → COMPILE OK.
- Booted once on dynamic port 36747 (`PORT=36747 bash start.sh &`, PID 2497765): Flask up on 0.0.0.0:36747 in <2s (install guard no-op).
- (i) POST /cycles without headers → 400 ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, correct error envelope.
- (ii) POST /candidates without headers → 201, status REGISTERED, envelope `{meta, response_type:"object", data}`.
- (iii) POST /cycles weights 0.4+0.6 (one ASSESSMENT) → 201 DRAFT; weights 0.5+0.4 → 422 ERR_WEIGHT_SUM_INVALID.
- POST /_clock/set_current_utc → 200 `{"current_utc":"2026-09-15T00:00:00Z"}`.
- Full E2E: cycle OPEN → candidate ELIGIBLE → CK+P1 attempts (certification auto-created) → artifacts → submit (SUBMITTED) → tech-review ACCEPT (SCORING) → center+booking (BOOKED) → clock to slot → COMPLETED 3.50 (CK SCORED via cascade) → benchmark + 2 assessors × 2 calibration passes → CALIBRATED → ACTIVE → reads 3.00/3.25 (|d|=0.25 ≤ 0.50, agree) → P1 SCORED final 3.13 → certification CERTIFIED with weighted_total_final **3.28** (1.400 + 1.878 → 3.278 → 3.28, pinned round-then-sum), valid_until 2034-01-31T10:00:00Z (certified_at + 1825d). Asserted — E2E OK.
- Negative paths observed working: duplicate-window cycle → 409 ERR_CYCLE_WINDOW_OVERLAP; submit before window → 422 ERR_SUBMISSION_WINDOW_CLOSED; tech-review on non-SUBMITTED → 409 ERR_SUBMISSION_NOT_SUBMITTABLE-family (ERR_SUBMISSION_NOT_REVIEWABLE).
- Cleanup: killed exactly PID 2497765 (verified via /proc cwd it was this task's app.py), port confirmed free, temp files removed. Note: an earlier launch of mine bound port 10000 because my own shell didn't export PORT — a smoke-script bug, not an app bug (app reads `os.environ["PORT"]`); that stray process was verified and killed by exact PID too.

### Isolation confirmation

Never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/; never ran the test suite. No seeding anywhere (grep-verified — only empty dicts at startup). All state is in-memory and vanishes on process exit.

Orchestrator spot-check: all 21 files present and py_compile-clean; app.py reads `$PORT` from env; pgrep found no surviving server processes for this task. The 20-item "interpretations chosen" list is carried forward as candidate over-guards for Step 7 adjudication.

## Step 7: Run Tests and Iterate — 2026-10-01T21:05:00.000Z

Clean sweep achieved. All work is complete — here is the summary.

## Summary

**Iterations run:** 3 sweeps (24 total round-executions). Baseline 45/102 → 101/102 → **102/102 in all 8 parallel rounds**, with zero flaky tests at every step (failing sets were identical across rounds in every sweep).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/test_suite/test_05_assessment_center_bookings.py` — `test_booking_completion_scores_assessment_submission`: replaced `create_eligible_candidate_with_assessment_submission()` with `create_eligible_candidate()`. The test pre-created a stray IN_PROGRESS assessment attempt, then `score_assessment_component` created a second one — which the impl correctly refused per PRD §3.1 ("While any earlier attempt ... still sits in IN_PROGRESS ... creating another is refused with ERR_ACTIVE_ATTEMPT_EXISTS"). The stray attempt was unused by the assertions.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `video_artifact_payload` / `minimal_portfolio_artifact_payloads`: default `subject_student_count` changed `0` → `None` (field omitted when None). PRD §3.3: the count "must be at least 1 when supplied", so the factory's "compliant" default payload was PRD-illegal; omission is the PRD-legal way to express the no-release-form baseline (the §3.3 gate fires only on a reported count ≥ 1). This single root cause accounted for 47 of the 57 failures.
- `fixtures.py` — `upload_minimal_portfolio_artifacts` / `create_portfolio_submission_in_state`: `student_count` default `0` → `None`, passed through to the fixed factory.
- `api_errors.py` — added missing `ApiErrorId.ERR_RENEWAL_HOURS_INSUFFICIENT` member + 422 mapping. PRD §3.9 names it verbatim ("fewer fails with `ERR_RENEWAL_HOURS_INSUFFICIENT` (HTTP 422)") even though the §5 catalog table omits it; the test cited it but the enum lacked it (AttributeError).

**Fixes applied to `implementation/`:**
- `store.py` — `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5 "server-minted UUID with no type prefix" means the canonical dashed form; the 32-char dash-less hex failed the framework's UUID validator for all 9 entity types.
- `errors.py` — added the missing constant `ERR_RENEWAL_HOURS_INSUFFICIENT = "ERR_RENEWAL_HOURS_INSUFFICIENT"`. `routes_certifications.py:159` referenced it but it was never defined — a latent AttributeError→500 on the PRD-required insufficient-hours path, shadowed until the test-side enum crashed first. Final audit confirms zero referenced-but-undefined and zero defined-but-unreferenced error constants.

**Sibling unasserted implementation paths for Step 8** (test-side fixes dominated):
- `routes_artifacts.py` `subject_student_count < 1` → ERR_INVALID_REQUEST guard: no remaining test ever sends 0 or a negative count, so this PRD-verbatim check is now unexercised; likewise no test sends `subject_student_count` on a STUDENT_WORK artifact, though PRD names both VIDEO and STUDENT_WORK.
- `routes_artifacts.py` "duration_minutes supplied for a non-video" → ERR_INVALID_REQUEST branch: asserted nowhere (only the missing-duration-on-video direction is tested).

**Final sweep evidence:** rounds 1–8 each report `passed == total == 102`, `failed == 0`; all eight `results.1.json` … `results.8.json` files remain on disk in `workspace/implementation/` as required by the output contract.

Orchestrator spot-check: all 8 results.*.json present on disk, each independently parsed → passed=102/total=102/failed=0; newest impl source mtime (errors.py 20:56:13) predates the results files (20:59:37) so the clean sweep covers the final code; `pytest --collect-only` still collects 102 (no silent test loss).

## Step 8: Finalize PRD — 2026-10-01T21:20:00.000Z

All edits verified. PRD_FINALIZED.md is complete at `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/workspace/PRD_FINALIZED.md`.

## Summary (for worklog.md)

**Line counts:** PRD.md 318 lines → PRD_FINALIZED.md 319 lines (+1 line, +0.31%). Diff is exactly 3 edits; everything else verbatim.

**Changes:**
- §2.5 — revise — pinned `id` to the canonical lowercase hyphenated UUID form (8-4-4-4-12 hex groups, example `550e8400-e29b-41d4-a716-446655440000`), replacing the bare "UUID with no type prefix" — implementation/store.py:66-67 (`new_id()` = `str(uuid.uuid4())`)
- §3.3 — revise — `subject_student_count` now declared optional on every artifact type, defaulting to null when omitted, an integer of at least 1 when supplied else `ERR_INVALID_REQUEST` (HTTP 400); the VIDEO/STUDENT_WORK mention re-scoped to its semantic role (only those two types feed the release-form check) — implementation/routes_artifacts.py:52-57,76; implementation/serializers.py:112; implementation/routes_submissions.py:155-159
- §5 — insert — added `| ERR_RENEWAL_HOURS_INSUFFICIENT | 422 |` row after ERR_NO_ELIGIBLE_ASSESSOR (mirrors impl errors.py grouping); §3.9 prose already named the id + 422, so this resolves the PRD-internal inconsistency — implementation/errors.py:75; implementation/routes_certifications.py:158-161

**Per-edit pre-edit search log:**
- Edit 1 (§2.5): (a) subject = server-minted resource id format. (b) enumerated: single minting site store.py:66-67, consumed by all 13 create sites (routes_cycles.py:84, routes_candidates.py:39, routes_centers.py:25, routes_bookings.py:76, routes_submissions.py:67/211, routes_artifacts.py:70, routes_assessors.py:27/104, routes_scoring.py:100, routes_certifications.py:117, routes_incentives.py:40, domain.py:103/196); `api_request_id` (response.py:17, `req_`-prefixed) confirmed not a persisted-resource id, so §2.5's scope does not collide with §2.2. (c) pinned lowercase hyphenated form — the only form any enumerated path emits.
- Edit 2 (§3.3): (a) subject = `subject_student_count` acceptance/default/validation/consumption. (b) enumerated: routes_artifacts.py:52-57 (no artifact-type gate; `as_int` in validation.py:57-60 rejects bool/non-int with ERR_INVALID_REQUEST 400; `<1` guard same error), routes_artifacts.py:76 + serializers.py:112 (stored/rendered null when omitted), routes_submissions.py:155-159 (release-form gate reads only VIDEO/STUDENT_WORK counts, fires on not-None-and-≥1). (c) widened wording from the original — the old sentence could be read as restricting the field to VIDEO/STUDENT_WORK, which would mis-describe the type-agnostic upload acceptance; VIDEO/STUDENT_WORK now scopes only the release-form gate.
- Edit 3 (§5): (a) subject = catalogue row for the renewal-hours gate. (b) enumerated: errors.py:75 (constant), routes_certifications.py:157-161 (sole raise site, APPROVE with total_hours < 45 → 422; MIN_RENEWAL_HOURS=45 at constants.py:25 matches §3.9 prose), test_helpers/api_errors.py:70,136 (auxiliary, 422). (c) none — pure row insertion consistent with §3.9 prose and §5's preamble.

**Step-7 items requiring no edit:** the test_05 booking fix was a pure fixture bug (PRD §3.3's ERR_ACTIVE_ATTEMPT_EXISTS sentence already pins the behavior verbatim); the `duration_minutes`-on-non-video sibling path is already pinned verbatim in §3.3 ("supplying it for a non-video, is `ERR_INVALID_REQUEST` (HTTP 400)") and matches routes_artifacts.py:49-51.

**Out-of-scope observation (not edited, per HARD SCOPE):** `ERR_ASSIGNMENT_NOT_SUBMITTABLE` (errors.py:52, raised at routes_scoring.py:222, named in §3.6 prose) is likewise absent from the §5 table — same class of omission, but not listed in `<step_7_diff>`, so left for a future pass.

Orchestrator spot-check: `diff PRD.md PRD_FINALIZED.md` shows exactly the 3 reported edits and nothing else (318 → 319 lines). The out-of-scope observation (ERR_ASSIGNMENT_NOT_SUBMITTABLE missing from §5) is handed to Step 9, whose full-scan scope covers it.

## Step 9: Complete PRD — 2026-10-01T21:55:00.000Z

All verification passed. Here is the completion report.

## Summary (for worklog.md)

**Source vs output:** `workspace/PRD_FINALIZED.md` (319 lines, 51,682 chars) → `workspace/PRD_COMPLETED.md` (320 lines, 55,587 chars; +3,905). `diff -q` from the task root: **"Files workspace/PRD_FINALIZED.md and workspace/PRD_COMPLETED.md differ"** — not a no-op; 25 edit operations applied. No file under `implementation/`, `test_suite/`, or `test_helpers/` was touched (mtime-verified).

**Counts:** 21 ambiguity-pins, 9 mismatch-revisions.

**Changes (one bullet per edit):**
- §2.1 — insert — ambiguity — "holding" for the assessor read gate means an assignment in ASSIGNED/SCORE_SUBMITTED/FINALIZED; REASSIGNED no longer grants access — routes_submissions.py:23-27,91-93; routes_artifacts.py:93-95
- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, not wall-clock — response.py:20-24, store.py:62-63
- §2.3 — insert — ambiguity — limit/offset out-of-range values are clamped (limit<1→1, >100→100, offset<0→0); non-integer → ERR_INVALID_REQUEST; created_at ties keep creation order — validation.py:84-109
- §2.4 — insert — ambiguity — clock may be set backward; no monotonicity guard; sweeps run on every set and never un-flip — routes_clock.py:18-19, domain.py:329-330
- §2.5 — insert — ambiguity — `version` starts at 1; non-system datetime fields render at seconds precision with 3 fractional digits only for sub-second values — store.py:30-37,75-81
- §2.6 — insert — ambiguity — a non-numeric score value is ERR_INVALID_REQUEST (400), not ERR_SCORE_INVALID — validation.py:68-81
- §2.7 — insert — ambiguity — retake_window_close before submission_window_close is ERR_INVALID_REQUEST (400) at cycle creation — routes_cycles.py:79-81
- §2.8 gate 4 — insert — ambiguity — a Candidate caller whose X-User-ID resolves to no record fails ERR_CANDIDATE_NOT_FOUND ahead of the eligibility gate — routes_bookings.py:41-48, routes_submissions.py:45-50
- §2.8 orderings — insert — ambiguity — booking transition resolves `to` and the actor for that target (unknown `to`→400, non-owner cancel→ERR_NOT_RESOURCE_OWNER, non-admin COMPLETED/NO_SHOW→ERR_INSUFFICIENT_PERMISSIONS) before the BOOKED state gate — routes_bookings.py:129-145
- §3.1 — revise — mismatch — "a unique `code`" → uniqueness descriptive, duplicates accepted (justification: catalogue defines no duplicate-code rejection, so "unique" was unenforceable prose; impl's non-enforcement is the defensible reading) — routes_cycles.py:60-99
- §3.2 — revise+insert — mismatch+ambiguity — "a unique `email`"/"two-letter `license_state`" → descriptive only (same justification); fte_fraction out of [0.5,1.0] pinned as ERR_INVALID_REQUEST (400) — routes_candidates.py:22-54
- §3.3 — revise — mismatch — "attempt_number 1" → one higher than the count of existing attempts of the triple (PRD's own active-attempt guard contemplates later creates, so the literal "1" could not hold universally) — routes_submissions.py:64-65
- §3.3 — revise+insert — mismatch+ambiguity — upload target is status-gated only ("portfolio attempt" was loose; no kind-rejection error exists in the catalogue), and a wrong-status upload is ERR_SUBMISSION_NOT_SUBMITTABLE (409) — routes_artifacts.py:32-34
- §3.4 — insert — ambiguity — slot_capacity below 1 is ERR_INVALID_REQUEST (400) — routes_centers.py:21-23
- §3.4 — revise — mismatch — capacity rejection "to equal" → "beyond" slot_capacity (the original sentence contradicted its own clarifying clause "a pool with exactly one seat free still accepts the booking"; impl matches the clause) — routes_bookings.py:68-74
- §3.5 — revise — mismatch — assessor "a unique `email`" → descriptive, not enforced (same uniqueness justification) — routes_assessors.py:24-25
- §3.5 — insert — ambiguity — a calibration read submitted after the assessor left CALIBRATING still finalizes and increments its counter past threshold, but fires no further transition — routes_scoring.py:149-167
- §3.5 — revise — mismatch — reliability window tie-break "created_at" → "the assignment created first" (created_at ties are common under the logical clock, so the stated tie-break was frequently indecisive; creation order is the deterministic realization) — domain.py:257-263
- §3.6 — insert — ambiguity — selector runs for live targets only; a calibration target must name `assessor_id`, else ERR_INVALID_REQUEST (400) — routes_scoring.py:71-73
- §3.6 — revise — mismatch — selector final tie-break "earlier created_at" → "assessor record created first" (same indecisive-tie justification) — domain.py:239-243
- §3.6 — insert — ambiguity — REASSIGNED assignments count toward neither live nor calibration read numbering — routes_scoring.py:18,93-98
- §3.6 — insert — ambiguity — omitting `score` is ERR_INVALID_REQUEST (400); a score is recorded on the assignment even when the target submission was meanwhile swept to EXPIRED (attempt still never scores) — routes_scoring.py:225-237
- §3.7 — insert — ambiguity — an evidence item missing a field or with negative hours is ERR_INVALID_REQUEST (400) — routes_certifications.py:58-80
- §3.7 — insert — ambiguity — refiling against a RETURNED application reuses it and answers 201 Created — routes_certifications.py:107-115
- §3.7 — revise — ambiguity — `review_note` is stored on either decision (null when omitted); PRD had only described the RETURN branch — routes_certifications.py:157-174
- §3.8 — revise+insert — mismatch+ambiguity — "two-letter `sponsor_state`" descriptive only; negative budget_total_cents pinned as ERR_INVALID_REQUEST (400) — routes_incentives.py:24-30
- §5 — insert — ambiguity — added the missing catalogue row `| ERR_ASSIGNMENT_NOT_SUBMITTABLE | 409 |` (the known lead; confirmed: defined errors.py:52, raised routes_scoring.py:222, named in §3.6 prose, absent from §5)

**Impl gaps NOT patched (PRD left intact):**
1. Renewal filing gate order — routes_certifications.py:96-104 evaluates the duplicate-active-application guard (`ERR_ACTIVE_RENEWAL_EXISTS`, a §2.8 gate-7 "duplicate-active-resource guard") *before* the renewal temporal window (gate 6), contradicting §2.8's fixed gate order and §3.7's narrative order (status → window → evidence → one-in-flight). Observable only when both violations coincide (e.g. after a backward clock set with a SUBMITTED application outstanding). Deliberate PRD rule → gap recorded, prose unchanged.
2. Exotic corner noted, not enshrined: while a submission is ADJUDICATION_REQUIRED the impl permits creating further adjudication reads (read_number 4+, routes_scoring.py:93) and the adjudication resolution finalizes *all* live reads including still-ASSIGNED ones (routes_scoring.py:180-183). PRD's singular "the adjudication read (read 3)" is satisfied by the state gate as written; this multiplicity corner is untestable-by-design and left unpinned rather than blessing a probable bug.

**20-interpretation audit table:**
| Interpretation | Status |
|---|---|
| derived-on-read computed fields | already-pinned (§3.8 budget "derived, never stored by hand"; counted_score/superseded/rates semantics pinned §3.3/§3.5/§3.7; mechanics invisible via API) |
| EXHAUSTED-at-0-budget | already-pinned (§3.8 "EXHAUSTED exactly when the remaining budget reaches 0") |
| artifact-upload gate error choice | newly pinned (§3.3 upload edit) |
| unknown-candidate 404 before ELIGIBLE check | newly pinned (§2.8 gate-4 edit) |
| booking transition actor-gate ordering | newly pinned (§2.8 orderings edit) |
| stipend unknown-`to` error | already-pinned (§3.8 "any transition request outside these declared moves → ERR_STIPEND_NOT_TRANSITIONABLE"; impl routes_incentives.py:137 confirms 409) |
| system-only assessor transitions | already-pinned (§3.5) |
| assignment 404-before-422 ordering | already-pinned (§2.8 gate 4 before gate 7; ambiguity-before-COI pin) |
| score-recorded-on-expired-submission | newly pinned (§3.6 edit) |
| REASSIGNED reads not counting | newly pinned (§3.6 numbering edit) |
| calibration counters past thresholds | newly pinned (§3.5 edit) |
| renewal resubmission 201 reuse | newly pinned (§3.7 edit) |
| review_note on both branches | newly pinned (§3.7 edit) |
| 3-fractional-digit rendering | already-pinned for created_at/updated_at/meta (§2.5/§2.2); newly pinned for all other datetime fields (§2.5 edit) |
| no backward-clock guard | newly pinned (§2.4 edit) |
| pagination clamping | newly pinned (§2.3 edit) |
| no uniqueness on code/email | newly pinned (§3.1, §3.2, §3.5 edits) |

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3399_teacher_portfolio_submission_assessment_center_scoring/workspace/PRD_COMPLETED.md`

Orchestrator spot-check: PRD_COMPLETED.md = 320 lines and differs from PRD_FINALIZED.md (not a no-op); `find ... -newer results.1.json` over implementation/ + test_suite/ + test_helpers/ returns zero source files, so the 102/102 × 8-round sweep evidence remains valid for the final code; all 8 results.*.json intact; ERR_ASSIGNMENT_NOT_SUBMITTABLE confirmed present in both §3.6 prose and the §5 table. The 2 flagged impl gaps are recorded above as known deviations (PRD requirement left intact deliberately).

## Pipeline Complete — 2026-10-01T21:55:00.000Z

All 9 steps done. Final state: 102/102 tests passing across all 8 parallel stability-sweep rounds; PRD_COMPLETED.md is the final contract.
