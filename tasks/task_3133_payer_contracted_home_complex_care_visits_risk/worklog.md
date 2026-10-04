# Worklog — task_3133_payer_contracted_home_complex_care_visits_risk

## Step 1: Create Task Directory — 2026-09-30T01:59:00.000Z

Task directory `tasks/task_3133_payer_contracted_home_complex_care_visits_risk/` was pre-allocated (per command args) with `workspace/` inside; verified it exists. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T04:18:30.169Z

(Resume note: the first two Step 2 subagents were killed mid-flight when the host session ended. The second left a complete valid SCAFFOLD.yaml (85,701 bytes; sections scenario/complexity_profile/response_envelope/entities/state_machines/concurrency_rules/calculations/validations/endpoints/errors/roles — parses cleanly) and a SCAFFOLD_DIFFICULTY_DESIGN.yaml (117,022 bytes) that contained a YAML syntax defect: 3 `captures:` flow mappings with unquoted `$.data[0]...` JSONPath values (lines 481, 1856, 1863). Orchestrator repaired the quoting in place; file now parses. §1.8 = 9 rules × 2 instances = 18 instances, all named, no stubs. SCAFFOLD_CORNER_DESIGN.yaml was never written, so a fresh subagent generated it from the skill spec + existing SCAFFOLD.yaml.)

Corner-design subagent summary (verbatim):
**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3133_payer_contracted_home_complex_care_visits_risk/SCAFFOLD_CORNER_DESIGN.yaml`
**Verification:** parses cleanly with `scaffold_corner_design` as the single top-level key.
**Structure:** 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), 135 total instances: entities 16, state_machines 18, calculations 11, validations 18, endpoints 8, errors 32, rbac 19, cross_cutting_complexity_layers 11 (incl. 3 excluded_because stubs referencing §1.8), consistency_model 2.
**Coverage:** all 32 error codes exercised; all 6 roles tested allowed+denied (segregation_of_duties); both OCC concurrency rules covered; all 5 complexity layers exercised; structured setup_api_calls/trigger/assert with ${var} placeholders.

## Step 3: Copy Shared Files — 2026-09-30T04:18:49.108Z

Copied ./INSTRUCTION.md → tasks/task_3133_payer_contracted_home_complex_care_visits_risk/workspace/INSTRUCTION.md (1,424 bytes).

## Step 4: Generate PRD — 2026-09-30T04:26:00.000Z

All checks pass. PRD complete.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3133_payer_contracted_home_complex_care_visits_risk/workspace/PRD.md` — 360 lines.

**Section list**:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 10 subsections (2.1 RBAC, 2.2 Response Envelope [verbatim], 2.3 Pagination, 2.4 Common Properties & Logical Clock, 2.5 OCC, 2.6 Validation Ordering, 2.7 Precision & Rounding, 2.8 Payment-Model Consistency, 2.9 Geography/Capacity/Selector, 2.10 Visit-Window Overlap)
- §3 Business Logic & Workflows — 7 subsections organized by lifecycle stage (program setup, member identification, enrollment funnel, care team, visit lifecycle, urgent response, performance & settlement)
- §4 Endpoint Definitions (60-row method/path/description/roles table)
- §5 Error Code Catalogue (55-row id/status table)

**Coverage confirmation**:
- Contract 1 (Field-Name Coverage): **PASS** — 242/242 required identifiers present (entities fields, endpoint inputs/query/path params, common fields, envelope tokens, role names, state values, enum values, error IDs, OCC fields, calculation names).
- Contract 2 (Rule Coverage): **PASS** — all 15 validation priorities expressed as ordered ladder in §2.6; both OCC rules (enrollment-create + visit-reschedule) explicitly named with `expected_member_version`/`expected_visit_version` + `ERR_STALE_VERSION` + 412; all 8 calculations expressed in precise prose (provisional burden with all 7 condition weights and ED/IP weights; final burden with all 4 med-rec/safety/social sub-weights; composite score with 0.40/0.30/0.20/0.10 weights, 1.0 empty-denominator fallbacks, and two-stage round-half-up at 4 decimals; capitated settlement with withhold on gross; shared-savings with pinned per-member-delta → pool → floor-at-zero → split → withhold → release order and explicit no-clawback; both selectors with capacity/zip/discipline filters and `active_daily_visit_count`-then-`created_at` ranking, id never tie-break; `enrolled_member_months` distinct-member counting); all state machine transitions with their preconditions, side-effects, and exact error IDs; sibling-branch symmetry preserved (CAPITATED vs SHARED_SAVINGS, IDENTIFIED vs DECLINED begin-outreach, ACTIVE vs CONSENTED disenrollment, TRIGGERED vs DISPATCHED lapsed cascade).
- Contract 3 (§3 Path Purity): **PASS** — 575 backticked tokens in §3 scanned; 0 violations (no paths, no bare HTTP methods, no method+path tokens).

**Scaffold totals covered in prose**: 13 entities, 6 state machines (34 transitions), 8 calculations, 15 validation rules, 2 OCC rules, 60 endpoints, 55 error IDs, 6 roles (5 opaque + 1 entity-backed `Clinician` explicitly identity-bound).

## Step 5: Generate Unit Tests — 2026-09-30T04:55:25.817Z

156 tests collected cleanly. One final check on a subtle risk: in `test_02` the composite setup uses a SHARED_SAVINGS contract — irrelevant to the measurement math, fine. In `_setup_composite_counters`, episode 2 resolution (REFERRED_TO_ED) cascades a POST_ED_FOLLOWUP visit — that consumes clinician capacity but max_daily_visits=10, fine. Also in test_02 the REFERRED_TO_ED cascade creates a visit assigned to primary_np with window [now, now+72h] — no overlap issue since NP1's capacity is 10.

One more check: `test_visit_arrive_sets_actual_start` uses `startswith("2026-09-02T09:30:00")` — tolerant of millisecond formatting. Good.

Done. Summary:

## Generation complete

**Output locations**
- `test_helpers/` — 9 files: `__init__.py`, `types.py`, `api_client.py` (55 endpoint methods), `api_errors.py` (52 error ids registered with the framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with `make_clinician_headers` for the identity-bound Clinician role), `fixtures.py` (composite funnel/visit/episode/settlement setup helpers).
- `test_suite/` — `conftest.py` + 15 test files.

**Counts**
- Test files: 15 (plus conftest).
- Total tests emitted: 156 (verified via `pytest --collect-only`).
- §1.8 difficulty queue: 18/18 instances translated, each with ≥2 tests (36 tests). None skipped.
- §1.9 corner queue: 132 non-stub instances; 120 translated, 12 skipped. The 3 `excluded_because` stubs were not translated (cross-references verified to resolve).

**Skipped corner instances (PRD-first two-condition filter failures)**
- `entities/member_creation_ignores_input_burden_score_provisional` — unknown-field handling not pinned by PRD.
- `entities/medical_cost_amount_negative_rejected` — rejection error_id not named in PRD prose.
- `endpoints/post_visits_rejects_urgent_visit_type` — error_id not named in PRD prose.
- `endpoints/get_care_team_for_enrollment_returns_array`, `endpoints/get_assessment_for_visit_returns_array` — PRD never pins the array-vs-object shape for the 1:1 sub-resource GETs.
- `endpoints/get_enrollments_filtered_by_member_id`, `endpoints/get_visits_filtered_by_enrollment_id`, `cross_cutting/pagination_with_filtering_list_members_by_risk_tier`, `cross_cutting/pagination_with_filtering_list_visits_by_status` — PRD never documents list filter parameters.
- `errors/error_care_team_not_found`, `errors/error_assessment_not_found` — PRD names no trigger condition for these codes on empty 1:1 lookups.
- `errors/error_primary_np_invalid_wrong_discipline` — PRD pins `ERR_PRIMARY_NP_INVALID` to care-team activation only, not to PUT care-team.

**Notable adjudication**: dispatch-after-SLA-deadline tests (difficulty `business_temporal_sla_check_beats_business_referential_occ_check` temporal half, boundary `urgent_episode_sla_deadline_uses_closed_interval_temporal_semantics` past-deadline half, corner `error_sla_already_lapsed`) use `validate_error_is_one_of([ERR_SLA_ALREADY_LAPSED, ERR_EPISODE_NOT_TRIGGERED])` per the error-precedence silence pattern, because the auto-lapse sweep on clock advance makes the strict single-error outcome ambiguous to a PRD-only reader.

**Verification**: every emitted test carries exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` tag resolving to a real instance (automated audit, 0 errors); all 193 quoted PRD citations survive a whitespace-normalized literal grep of PRD.md; all modules import and pytest collects 156 tests cleanly.

## Step 6: Generate Implementation — 2026-09-30T05:10:29.669Z

All verified. The implementation is complete and the workspace is clean (no leftover processes, no pycache).

## Summary

**Task**: `task_3133_payer_contracted_home_complex_care_visits_risk` — Payer-Contracted In-Home Complex Care Visits & Risk Stratification.

**File list** (all under `workspace/implementation/`):

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=2.0`
- `app.py` — Flask entry point, blueprint registration, error handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (dicts keyed by id) + logical clock init `2026-09-01T00:00:00Z`
- `errors.py` — full error catalog with exact error IDs and HTTP statuses
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/0, min 1, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, six roles, RBAC
- `routes/` — `programs.py`, `contracts.py`, `pcp_providers.py`, `clinicians.py`, `members.py`, `enrollments.py`, `care_teams.py`, `visits.py`, `episodes.py`, `measurements.py` (measurements + settlements + medical costs + clock)
- `services/` — `clock.py` (logical clock + LAPSED sweep), `resources.py` (UUID, common fields, touch), `calculations.py` (burden provisional/final, risk tiers, two-stage round-half-up composite via `Decimal`, half-open overlap), `measurements.py`, `selectors.py` (routine NP-only + urgent-qualified selectors, ranked by `active_daily_visit_count` then `created_at`, never id), `settlements.py` (capitated + shared-savings with pinned delta→pool→split→withhold→release order), `serializers.py`, `validation.py`

**Endpoint count**: 47 routes implemented — all 45 from the PRD §4 table, with the two `/visits/{id}/assessment` (POST + GET) and `/enrollments/{id}/care-team` (GET + PUT) method pairs counted separately in the table.

**start.sh** (in brief): `set -euo pipefail`; `cd` to script dir; guarded install (`if ! python3 -c "import flask"` then `pip install -q -r requirements.txt`); `exec python3 app.py` in foreground.

**Storage / seeding**: In-memory only — module-level Python dicts in `db.py`; no SQLite, no file or /tmp persistence. Zero seeding: fresh boot verified by querying all ten list endpoints and confirming every store returns `data: []` / `total_count: 0`.

**Verification performed**: full end-to-end smoke run covering the enrollment funnel (begin-outreach / record-attempt cap of 3 with auto-DECLINED + `NON_ENGAGEMENT` / re-engagement reset / consent / care-team activation gating / enrollment activation), CREATE-with-supersede + `ERR_STALE_VERSION` OCC on both member-version and visit-version, visit lifecycle (depart/arrive/assessment/submit/complete with final-burden recompute 22 → 40 and tier HIGH → VERY_HIGH, PCP opt-in notification), overlap arithmetic (overlap rejected, back-to-back allowed), cancel/reschedule/no-show with window check, urgent episodes (dispatch selector, SLA met, AVOIDED_ED, REFERRED_TO_ED cascade creating a POST_ED_FOLLOWUP visit assigned to the team's primary NP, clock-advance LAPSED sweep), CAPITATED settlement (gross 50000, withhold 5000, finalize/mark-paid) and SHARED_SAVINGS settlement (pooled 60000 → 0.5 split → 30000, withhold 3000, full release → net 30000), validation-ladder ordering (404 before 412), RBAC 403s, and error-envelope shape.

## Step 7: Run Tests and Iterate — 2026-09-30T05:26:11.767Z

All 8 rounds pass 156/156. Clean sweep.

Summary:

- **Iterations run**: 2 (initial sweep: 151/156 in all 8 rounds with a stable set of 5 failures; post-fix sweep: 156/156 in all 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`** (1 file):
  - `/home/ubuntu/github/CodingPRD/tasks/task_3133_payer_contracted_home_complex_care_visits_risk/test_suite/test_02_combinatorial_formulas.py` — `_setup_composite_counters()` (used by `test_composite_score_counters_after_mixed_activity` and `test_composite_score_weighted_sum_two_stage_rounding`): the setup resolved an episode with `REFERRED_TO_ED`, which per PRD §3.6 cascades a SCHEDULED `POST_ED_FOLLOWUP` visit on the primary NP spanning `[clock, clock+72h)` (2026-09-01T00:00 → 2026-09-04T00:00). The setup then tried to schedule visits on 09-02/03/04 for the same clinician, which the PRD §2.10 half-open overlap rule correctly rejects with `ERR_VISIT_TIME_OVERLAP`. Shifted the three completed visits to 09-04/05/06 and the no-show visit (plus its `set_clock`) to 09-07, outside the cascade window. The asserted counters and composite math are unchanged.

- **Fixes applied to `implementation/`** (2 files):
  - `/home/ubuntu/github/CodingPRD/tasks/task_3133_payer_contracted_home_complex_care_visits_risk/workspace/implementation/routes/measurements.py` — `set_current_utc()`: removed the `sweep_episode_lapses()` call. PRD §3.6 states verbatim "Both the program's period-advance capability and the operator's clock-advance-hours capability trigger this sweep" — the set-to-arbitrary-timestamp capability is not a sweep trigger, so setting the clock past an SLA deadline must leave a DISPATCHED episode arriavable (with `sla_met=false` computed at arrival). This was blocking `test_sla_met_false_one_second_past_deadline`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_3133_payer_contracted_home_complex_care_visits_risk/workspace/implementation/routes/enrollments.py` — `record_attempt()`: moved the `outreach_attempts >= 3` exhaustion check ahead of the `status != OUTREACH` check. PRD §3.3 states verbatim that after the cap-3 auto-transition to DECLINED, "the same `ERR_OUTREACH_ATTEMPTS_EXHAUSTED` rejection surfaces on any subsequent record-attempt call", so exhaustion pre-empts the state error for this endpoint. This fixes `test_error_outreach_attempts_exhausted` and `test_outreach_attempts_max_cap`.

Final state: 156/156 passing in all 8 parallel rounds. (Orchestrator verified all 8 results.*.json files: passed=156, total=156, failed=0.)

## Step 8: Finalize PRD — 2026-09-30T05:30:36.866Z

The diff is clean: 4 lines changed (all inline revisions, no new sections), same line count (360 → 360, 0% delta). The test-suite fix (`_setup_composite_counters`) was a pure fixture bug against already-correct PRD rules — no PRD edit needed for it.

## Summary

**Line counts**: PRD.md = 360 lines, PRD_FINALIZED.md = 360 lines (0% delta; 4 lines revised in place).

**Changes** (one bullet per edit):
- §2.4 — revise — replaced "Whenever the logical clock advances past … automatically lapses" with wording pinning the LAPSED sweep as a discrete event fired only by the period-advance capability and the clock-advance-hours capability; explicitly states set-to-arbitrary-timestamp does NOT sweep, leaving a past-decline DISPATCHED episode arriavable with `sla_met=false` computed at arrival — `implementation/routes/measurements.py:242-251` (set_current_utc, no sweep) vs `:254-261` (advance_hours, sweeps) and `implementation/routes/programs.py:62-74` (period advance, sweeps).
- §3.6 — revise — aligned the "Whenever the logical clock advances past…" lapse sentence with the sweep-trigger model and appended that the set-clock capability does not trigger the sweep — `implementation/services/clock.py:63-93`, callers at `routes/measurements.py:260` and `routes/programs.py:73`.
- §3.3 — revise — pinned that on record-attempt the cap check is evaluated first: once `outreach_attempts` reaches 3 the endpoint always reports `ERR_OUTREACH_ATTEMPTS_EXHAUSTED`, pre-empting the state precondition and the `is_current` invariant — `implementation/routes/enrollments.py:165-186`.
- §2.6 — revise — appended a carve-out to the validation-ladder paragraph noting the record-attempt exception so §2.6's "every endpoint applies the same ladder" doesn't contradict §3.3 — `implementation/routes/enrollments.py:173-179`.

**Test-suite fix item** (`test_02_combinatorial_formulas.py::_setup_composite_counters`): pure fixture bug — the setup double-booked the primary NP inside the §3.6 72-hour POST_ED_FOLLOWUP cascade window, which the §2.10 half-open overlap rule correctly rejects. PRD already fully determines both behaviors; no PRD edit.

**Per-edit pre-edit search log**:

1. **§2.4 sweep-trigger edit**
   - (a) Subject: when the LAPSED sweep runs relative to the three clock/period capabilities.
   - (b) Enumerated paths: `grep -rn "sweep_episode_lapses"` → `routes/measurements.py:260` (advance_hours sweeps), `routes/programs.py:73` (period-advance sweeps), `services/clock.py:63` (definition); `grep -rn "db.clock|set_clock|advance_clock_hours"` → only `measurements.py:250` (set, no sweep) and `:259` (advance, sweep); also read `routes/episodes.py:117-157` to confirm `arrive` has no deadline gate (so "DISPATCHED episode may still be arrived with sla_met=false" is accurate) and `dispatch` retains its `ERR_SLA_ALREADY_LAPSED` gate (so my wording does not imply dispatch becomes possible past deadline).
   - (c) Wording adjustment: scoped the "may still be arrived" parenthetical to DISPATCHED episodes only, since a TRIGGERED episode past deadline is still blocked at dispatch; used "has passed"/"crossed" phrasing matching the sweep's strict `now > deadline` comparison.

2. **§3.6 sweep-trigger alignment edit**
   - (a) Subject: same sweep-trigger semantics, second PRD site making the broad "whenever the clock advances" claim.
   - (b) Enumerated paths: same set as edit 1 plus the verbatim §3.6 final sentence already naming the two triggers — confirmed my revision keeps that sentence and appends the set-clock exclusion with a §2.4 cross-reference.
   - (c) Changed "Whenever the logical clock advances past" to "When the lapse sweep runs and finds that the logical clock has advanced past" to avoid implying continuous reaction while keeping the rest verbatim.

3. **§3.3 record-attempt ordering edit**
   - (a) Subject: check ordering on the record-attempt endpoint (cap vs state vs is_current).
   - (b) Enumerated paths: `grep -rn "ERR_OUTREACH_ATTEMPTS_EXHAUSTED|outreach_attempts"` across impl → only `routes/enrollments.py` (init at :82, reset at :160, checks at :173/:176/:179/:181) and serializer exposure; read `enrollments.py:145-186` confirming order exhaustion → state → `_check_is_current`; confirmed no other endpoint rejects on `outreach_attempts`, so wording scoped to record-attempt cannot mis-describe begin-outreach/record-consent/record-decline.
   - (c) Added "(while the counter is still below the cap)" qualifier to the existing NOT_IN_OUTREACH sentence so the two sentences no longer conflict after auto-decline; explicitly named the is_current invariant as also pre-empted, matching impl line order.

4. **§2.6 ladder carve-out edit**
   - (a) Subject: global validation ladder's "every endpoint applies the same ladder" claim vs the record-attempt exception.
   - (b) Enumerated paths: re-checked that record-attempt is the only endpoint where a non-ladder check (cap exhaustion) precedes rung 5 — grep over all routes for raises before state checks; record-attempt is the sole case. Other rung-5 endpoints (`record_consent`, `begin_outreach`, `record_decline`, `disenroll`, `activate` in `enrollments.py`) all check state before is_current, consistent with the ladder.
   - (c) Kept the carve-out to a single appended sentence naming record-attempt and deferring to §3.3, leaving the 15-rung ladder itself untouched.

No tests were deleted by Step 7 and no other Step 7 items required PRD changes.

## Step 9: Complete PRD — 2026-09-30T05:48:01.146Z

A few remaining cross-checks against the impl before closing out. Let me verify two subtle points I pinned: (1) record-decline order (state before is_current — impl line 227-230 confirms), (2) `GET /members/{memberId}/enrollments` when member missing → 404 (already consistent with ladder rung 3). Also confirm my claim that `GET /enrollments/{enrollmentId}/care-team` never 404s on missing team but PUT/activate/suspend/reinstate do — confirmed via care_teams.py lines 56-62 vs 42-46. And the settle-generate duplicate-allowance and frozen amounts — confirmed via measurements.py create_settlement and settlements.py.

One more check: the §3.5 reschedule precondition order in the PRD (cap listed before overlap, enrollment-ACTIVE, OCC last) matches impl — yes (visits.py:433-463).

Done. Summary:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (360 lines) → `workspace/PRD_COMPLETED.md` (359 lines; +5,541 chars).

**Counts:** 19 ambiguity-pins (inserts), 9 mismatch-revisions (including 2 catalogue row deletions).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — revise — mismatch — unrecognized non-empty `X-User-Role` is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400), not 403 — implementation/middleware.py:29-31
- §2.1 — revise — mismatch — clinician `X-User-ID` existence is never validated; identity only exercised through FK ownership comparison — implementation/middleware.py:16-32
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase alphanumerics; envelope timestamps use real wall clock, logical clock governs business timestamps only — implementation/response.py:11-19
- §2.2 — insert — ambiguity — undefined paths/unsupported methods → `ERR_NOT_FOUND` (404); uncaught failures → `ERR_INVALID_REQUEST` (400) — implementation/app.py:36-51
- §2.3 — insert — ambiguity — invalid limit/offset → `ERR_INVALID_REQUEST`; sort ties broken by `id` ascending; `has_more` formula; optional conjunctive equality filters incl. `is_current` true/1/yes parsing — implementation/response.py:66-99, all list endpoints
- §2.4 — insert — ambiguity — lapse sweep is global across all programs; `by_hours`/`by_days` integers with no positivity constraint; `/_clock/*` return 200 with empty `data`, period-advance returns the program — implementation/services/clock.py:63-93, routes/measurements.py:242-261
- §2.6 — revise — mismatch — rung 5: only resource-specific state errors (dropped `ERR_INVALID_STATE`, which impl never raises) — implementation/routes/*.py (no usage)
- §2.6 — revise — mismatch — ladder rungs 9-11 reordered to SLA-temporal → selector-emptiness → overlap, matching dispatch (SLA before selector) and visit-create (selector before overlap) — implementation/routes/episodes.py:121-131, routes/visits.py:138-144
- §2.6 — insert — ambiguity — body field validation (presence/type/enum, incl. window validity) → `ERR_INVALID_REQUEST`, evaluated between rungs 3 and 5 except where §3 pins otherwise — implementation/services/validation.py
- §2.8 — insert — ambiguity — rate fields of the non-chosen payment model are stored as supplied (null when omitted), not rejected — implementation/routes/contracts.py:51-63
- §2.9 — insert — ambiguity — `active_daily_visit_count` decrements floor at 0 — implementation/routes/visits.py:366-367 et al.
- §3.1 — revise — mismatch — `program_code`, `npi`, `member_external_id` uniqueness claims removed (impl enforces none); contract dates stored as strings, expiration parsed only at finalize — implementation/routes/programs.py, pcp_providers.py, members.py, measurements.py:144
- §3.2 — insert — ambiguity — invalid chronic condition code → `ERR_INVALID_REQUEST`; dropped "address_zip drives routing eligibility" (impl never reads it) — implementation/routes/members.py:48-51
- §3.3 — revise — mismatch — begin-outreach from any non-IDENTIFIED/non-DECLINED status → `ERR_ENROLLMENT_NOT_IDENTIFIED` (impl never raises `ERR_ENROLLMENT_NOT_DECLINED`) — implementation/routes/enrollments.py:149-155
- §3.3 — insert — ambiguity — disenroll: invalid reason value → `ERR_INVALID_REQUEST`; state and `is_current` checked before the reason — implementation/routes/enrollments.py:271-282
- §3.4 — insert — ambiguity — care-team PUT: no status precondition, omitted slots unchanged, explicit null clears; nonexistent clinician → `ERR_CLINICIAN_NOT_FOUND`, wrong status/discipline → `ERR_INVALID_REQUEST`; GET returns list envelope with 0/1 items (empty array, never 404) — implementation/routes/care_teams.py:56-95
- §3.5 — insert — ambiguity — `URGENT` visit_type rejected with `ERR_INVALID_REQUEST` right after enrollment FK resolves — implementation/routes/visits.py:110-112
- §3.5 — insert — ambiguity — assessment upsert requires only assigned-clinician (and DRAFT if existing); no visit-status check; supplied structured objects must be fully populated, omitted ones unchanged; GET assessment returns 0/1-item list envelope; submit with no assessment → `ERR_ASSESSMENT_NOT_FOUND` — implementation/routes/visits.py:261-339
- §3.5 — revise — mismatch — `pcp_coordination_rate` computed across all of the member's COMPLETED visits, not period-scoped — implementation/services/measurements.py:39-58
- §3.5 — insert — ambiguity — `burden_score_final` left unchanged when no completed INITIAL_ASSESSMENT exists; cancel: state check before reason, invalid reason → `ERR_INVALID_REQUEST` — implementation/services/calculations.py:73-118, routes/visits.py:400-411
- §3.6 — insert — ambiguity — trigger against non-ACTIVE enrollment → `ERR_ENROLLMENT_NOT_ACTIVE`; resolve checks state → outcome presence/validity → ownership, invalid outcome → `ERR_INVALID_REQUEST` — implementation/routes/episodes.py:57-59, 163-177
- §3.6 — insert — ambiguity — REFERRED_TO_ED cascade visit bypasses selector/capacity/overlap; increments primary NP's count when assigned, else null `clinician_id` — implementation/routes/episodes.py:200-231
- §3.7 — revise — mismatch — settlement period lower bound is per-contract (max prior `period_index` of that contract's settlements, any status incl. VOIDED), not "first settlement of a program"; duplicate generation for a period permitted, amounts frozen at creation; `period_index` must be integer ≥ 0 on medical costs — implementation/services/settlements.py:13-41, routes/measurements.py:83-106, 195
- §4 — insert — ambiguity — list endpoints honour the §2.3 equality filters for fields their resource carries — implementation/routes/*.py list handlers
- §5 — revise — mismatch — removed orphan catalogue rows `ERR_INVALID_STATE` and `ERR_ENROLLMENT_NOT_DECLINED` (never raised) — grep over implementation/ confirms zero raise sites

**Post-Step-9 confirmation sweep** (orchestrator-run, 2026-09-30T05:48–05:53Z): 8 parallel rounds of `prd-bench-local-run --isolation per-test-server` against the unchanged implementation + test suite — all 8 rounds 156/156 passed, 0 failed. ALL PASS.
