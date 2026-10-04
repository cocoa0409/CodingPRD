# Worklog — task_3167_host_railroad_track_access_time_performance_dispatch

## Step 1: Create task directory — 2026-09-30T06:41:00.000Z

Verified pre-allocated task directory `./tasks/task_3167_host_railroad_track_access_time_performance_dispatch/` with `workspace/` inside (bash-only; no index computation per command args).

## Step 2: Generate scaffold — 2026-09-30T07:16:00.000Z

Done. All three scaffold artifacts generated for the Amtrak host-railroad scenario, with a clean lint verdict.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3167_host_railroad_track_access_time_performance_dispatch/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 14 (HostRailroad, Corridor, TrackSegment, OperatingAgreement, Timetable, TrainRun, SegmentPassage, DelayIncident, DispatchPriorityDispute, CapitalProject, MaintenanceWindow, ServiceDisruption, FundingAgreement, SettlementStatement)
- State machines: 11 (incl. cyclic Timetable review loop, fork-join dispute machine, parallel cascades from OA suspend and disruption bridge)
- Calculations: 6 (otp_measurement with endpoint_only/all_stations variants, host_delay_attribution gross/net, tiered incentive-penalty, rounding-order-pinned funding allocation, ceil-based schedule feasibility, 40h equipment threshold)
- Endpoints: 69 (incl. `POST /rail/_clock/set_current_utc` with the pinned 2026-09-01T00:00:00Z default)
- Errors: 17; Roles: 4 (SystemAdmin/PassengerOperator/StateSponsor opaque, HostRailroadRep entity_backed:HostRailroad); OCC concurrency rules: 2 (both pinned to OperatingAgreement.version)
- Difficulty instances: 18 (9 rules × 2, all §0.5 differentiation clauses honored — different entity domains, formula modes (a) vs (b), category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities, cascade triggers)
- Corner instances: 38 active + 4 `excluded_because` stubs (42 `- name:` entries total), across sections entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting/consistency

**Key design decisions:** temporal-windowing primary archetype with pricing-engine secondary; two disjoint interval semantics (half-open single-track occupancy vs clearance-buffered maintenance windows); cascades of depth 3 (bridge → run → passages → auto DelayIncident) and depth 2 (OA suspend → timetable → runs); all formula-derived asserts pre-computed to literals (e.g. penalty 3000/1950/1500, funding lines 205480/616439 summing to 821919 vs period cost 821918, OTP 50.0000, disruption auto-incident 77 minutes).

Lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (708 calls scanned). No sibling task directories were inspected.

## Step 3: Copy shared files — 2026-09-30T07:18:00.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3167_host_railroad_track_access_time_performance_dispatch/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T07:23:00.000Z

All key rules verified present. One subtle detail to double-check: the tier rule — scaffold says tier 1 if `otp >= target - 0.05`, tier 2 if `otp >= target - 0.15`, else 3. My prose says "one when ... at least target minus 0.05, two when at least target minus 0.15, and three when it falls below that". Correct (the tier-2 branch is only reached when tier 1 fails, i.e., below target−0.05 but at least target−0.15).

Also check the host_delay_attribution NET clamp and the train-run/dispute details. Everything is in place. Final summary.

**Done.**

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3167_host_railroad_track_access_time_performance_dispatch/workspace/PRD.md` — 290 lines.

**Structure:**
- §1 Introduction (3 paragraphs: business context, workflow scope, `/rail` mount + consistency model)
- §2 Global Specifications (9 subsections, domain-derived titles): RBAC with per-role `identity:` translation; verbatim §2.2 response envelope block; pagination (limit default 10/min 1/max 100, offset 0, `created_at` asc); common resource properties + logical clock (startup default 2026-09-01T00:00:00Z, `to_iso8601`, auto-expiry on `effective_to`); single-track half-open occupancy + capacity discipline; maintenance windows, clearance buffer (default 15, both sides, boundary equality not a conflict), and the 40.00-hour ISO-week (Monday 00:00Z) equipment budget; full 16-step validation priority order as an ordered list; OCC on the two guarded endpoints (`expected_operating_agreement_version`, `ERR_STALE_VERSION` 412); monetary/measurement precision (integer cents, round half-up, 4-decimal OTP, truncated minutes, ceil pad).
- §3 Business Logic (11 subsections, chronological/lifecycle grouping): network build-out, agreement lifecycle (activate/amend/suspend with both cascade links and timetable→DRAFT reset), timetable feasibility walk and review loop (including publish-time re-checks and `SUPERSEDED`), run/passage actualization, delay coding with `host_attributable` derivation and per-run recompute, disruption bridging three-link cascade with auto-incident creation, dispute fork-join (UPHELD-only from `UNDER_REVIEW`), capital projects (OCC-pin on approve, capacity add exactly once), maintenance window lifecycle, funding waterfall (two rounding steps, remainder not redistributed), and settlement (GROSS/NET variants, tier multipliers, null-OTP rule).

**Hard-contract reports:**
- Field coverage: 92 required (entity fields + endpoint inputs + path params), 92 present, 0 missing — PASS
- Rule coverage: all 16 validations with priority order and error IDs; both OCC rules with write endpoint + occ field + error id + 412; all 36 state-machine transitions with preconditions and side effects; all 6 calculations (otp_measurement dual-variant, host_delay_attribution GROSS/NET, tiered incentive/penalty with 0.05/0.15 bands, funding waterfall with pinned rounding order, schedule_feasibility with half-open rules, equipment_hours_budget) in precise prose without pseudocode; all endpoint side effects expressed — PASS
- §3 path purity: 384 backticked tokens scanned, 0 path/method violations — PASS

§4 endpoint table has 4 columns (69 rows); §5 error table has 2 columns (16 rows). The two withheld difficulty/corner YAML files were never opened or referenced.

## Step 5: Generate unit tests — 2026-09-30T07:49:00.000Z

All counts reconcile (I mis-enumerated errors earlier — the audit itself confirms 38 non-stub corner instances). Cleanup done. Final state:

## Summary

Generated complete test infrastructure for `task_3167_host_railroad_track_access_time_performance_dispatch`.

**test_helpers/ (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_3167_host_railroad_track_access_time_performance_dispatch/test_helpers/`
- `types.py` — 14 entity TypedDicts + 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (55 methods, `/rail` prefix), plus `canonical_instant` normalizer
- `api_errors.py` — 16 error ids + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, envelope/meta/pagination/instant/cents helpers
- `factories.py` — payload factories (input fields only)
- `constants.py` — 40.00h weekly equipment allowance, 15-min default buffer, tier bands, canonical corridor geometry
- `test_users.py` — opaque role header constants + `make_host_rep_headers(host_id)` for the entity-backed HostRailroadRep role
- `fixtures.py` — composite world builders: `setup_network`, `setup_draft_agreement`, `setup_active_agreement`, `setup_published_timetable`, `run_0902_completed_20_late`, `runs_0903_one_ontime_one_late`, plus incident/dispute/statement/project/window/disruption/funding helpers
- `__init__.py` — barrel export

**test_suite/ (16 test files + conftest.py)** — 75 test functions, all compile-clean, no skip/xfail markers, no scaffold references.

**Coverage audit (automated):**
- Queue A (Difficulty): 18/18 instances covered, 36 tests (exactly 2 each) — PASS
- Queue B (Corner): 38/38 non-stub instances covered, 39 tests (≥1 each) — PASS; 4 `excluded_because` stubs correctly not translated, cross-references verified
- Tag audit: every test has exactly one `Design:` tag; every tag resolves to a real instance
- Citation audit: all 105 `PRD:` quotes verified verbatim against PRD.md (whitespace/markdown-bold normalized) — 0 failures

**Skipped instances:** none. Every instance in both indices had verbatim PRD coverage with uniquely derivable outcomes, so no PRD-first filter skips were needed.

Notable design decisions: `maint_eff` tests use `assert_instant` for planned-time comparisons (fractional-digit rendering tolerance); the OCC stale-amend test derives the observed version from the activate response rather than hard-coding it; pagination assertions use `validate_paginated` + `assert_list_page`.

## Step 6: Generate implementation — 2026-09-30T08:03:00.000Z

All files in place. Implementation is complete and verified.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3167_host_railroad_track_access_time_performance_dispatch/workspace/implementation/`:

- `start.sh` — foreground launcher; guards `pip install` with `python3 -c "import flask"` so per-test reboots skip the install; `exec python3 app.py`.
- `requirements.txt` — `Flask>=2.0.0`.
- `app.py` — Flask entry point; binds `0.0.0.0:$PORT` (default 10000); registers blueprints and error handlers that convert `ApiError` and Werkzeug HTTPException into the spec envelope.
- `core.py` — Logical clock (boots at exactly `2026-09-01T00:00:00Z`), in-memory store (empty on every boot, no seeding), response envelope (`meta.api_request_id` / `meta.api_request_timestamp` / `response_type` / `data`, plus `limit`/`offset`/`total_count`/`has_more` for lists), auth middleware reading `X-User-ID` / `X-User-Role` against the four declared roles, schema/query validators, pagination (10/0/1..100), ISO-8601 / YYYY-MM-DD / HH:MM parsers, Decimal helpers with `ROUND_HALF_UP`.
- `svc.py` — Entity enums, existence helpers, host-ownership chain helpers (HostRailroadRep `X-User-ID` compared against the owning railroad via corridor/agreement chain), schedule feasibility walk (padded run minutes ceil + dwell, half-open SINGLE overlap, per-segment-per-day capacity, LOCKED-window clearance buffer with strict-inequality boundary), TrainRun/SegmentPassage materialization, attributed-minutes recompute, disruption cascade with auto-incident (SYSTEM_DISRUPTION) creation, maintenance-window equipment budget (40.00 hr/week, ISO week via `isocalendar()`), funding allocation waterfall (round period cost then round each state line, no remainder redistribution), settlement computation (GROSS vs NET host minutes, tiered penalty, incentive, otp_pct 4-decimal round-half-up, null when 0 runs).
- `routes/` — one module per resource group: `network.py` (clock, host railroads, corridors, segments), `agreements.py`, `timetables.py`, `runs.py` (train runs + segment passages), `incidents.py` (delay incidents + disputes), `projects.py`, `windows.py`, `disruptions.py`, `funding.py`, `settlements.py`.

**Architecture notes / key design decisions:**
- All state in module-level dicts keyed by UUID; logical clock is the only time source — never wall-clock.
- Common fields `id`/`created_at`/`updated_at`/`version` set on every row; `touch()` bumps `version` and `updated_at` on every mutation, including cascaded children.
- Validation priority order (PRD §2.7) enforced structurally: format → auth → authz/ownership → existence → OCC → state → business. The two OCC endpoints (`amend`, `capital-projects approve`) compare `expected_operating_agreement_version` against `version` *before* the state check, returning `ERR_STALE_VERSION` (412).
- Schedule feasibility uses `Decimal` for the pad computation, ceils to whole minutes before adding dwell; overlap is half-open; maintenance conflicts use strict `<`/`>` so exact buffer-boundary equality is not a conflict.
- Settlement GROSS variant computed at create/issue; reissue flips to NET and recomputes against currently-CONFIRMED incidents.
- Funding allocation rounds the period cost first, then each state's line, per the PRD's "rounding step 2 applied per line, remainder not redistributed" rule.
- Disruption bridge cascade: SCHEDULED/EN_ROUTE runs with `scheduled_departure_at >= started_at` flip to DISRUPTED, their PLANNED passages flip to SKIPPED, and a `SYSTEM_DISRUPTION` incident is auto-created once per affected run when its passage set completes.

**Verified by smoke tests** (against fresh boots):
- Auth/authz: missing headers → 401 ERR_UNAUTHENTICATED; wrong role → 403 ERR_FORBIDDEN.
- Full pipeline: railroad → corridor → segments → agreement draft/activate → timetable draft/propose/review/ratify/publish → runs materialized with correct padded schedule (60 min pure × 1.10 pad = 66 min, plus dwell).
- Depart/actualize/complete: origin delay 5 min, destination delay 20 min, `on_time_endpoint=false`, `on_time_all_stations=false` (passage 2 exited 20 min late, over the 10-min threshold).
- Incident confirm → `attributed_host_delay_minutes=12`.
- Settlement create: `otp_pct=0.0`, tier-3 penalty `100 × 12 × 3 = 3600` cents, `net_cents=-3600`, `train_miles=100.0`.
- Funding allocation: 30-day period over 36500000 cents annual cost, CA share (60/100 miles) → `allocated_cost_cents=1800000`.
- Logical clock: `POST /rail/_clock/set_current_utc` returns the new instant; expiry sweep runs.

**Deviations:** none material. Small judgment calls:
- `train_number` is a sequence-based integer-as-string (`"1"`, `"2"`, …) — the PRD says only "sequence-based".
- Timetable serialization renders `departure_time_of_day` as `HH:MM` and `service_date_*` as `YYYY-MM-DD` strings (input form), and `window_hours`/`equipment_week_hours_available` as floats via `jsonable(Decimal)`.
- For the publish-time overlap guard against other published timetables, I compare against PLANNED or ACTUALIZED passages of the other timetable's runs (using actual interval if actualized) — PRD only names "passage of another PUBLISHED timetable" without specifying planned vs actual.
- Host-ownership on ServiceDisruption operations is enforced via the corridor's host railroad; on TrainRun operations via timetable → corridor → host.

## Step 7: Run tests and iterate — 2026-09-30T08:16:00.000Z

All 8 rounds pass, 74/74 (75 original minus 1 deleted test).

## Summary

**Iterations run:** 2 (first sweep: 66/75 failing in all 8 rounds, identical failure set — deterministic, not flaky; second sweep: 74/74 × 8 rounds, clean).

**Tests deleted (1):**
- `test_confirmed_host_minutes_return_to_zero_after_reversal_and_reissue` (test_difficulty_settlement_variants.py) — ENUM-MEMBERSHIP-ONLY / PRD-contradicted pathway: the test disputed an already-CONFIRMED incident, but PRD §3.5 states verbatim "disputing requires `OPEN` status" and the dispute state machine has no CONFIRMED → DISPUTED edge, so the confirm→reverse→reissue-at-zero scenario is unconstructible for any PRD-faithful implementation. The remaining covered claim (reissue recomputes from currently-CONFIRMED incidents) survives in the rewritten sibling test.

**Fixes applied to test artifacts:**
- `test_helpers/fixtures.py` — `create_agreement`: popped `host_railroad_id`/`corridor_id` from `**overrides` before passing positionally to `operating_agreement_payload` (TypeError collision when tests override `corridor_id`). Fixed 2 tests.
- `test_suite/test_difficulty_settlement_variants.py` — rewrote `test_reissued_statement_host_minutes_equal_live_confirmed_host_sum` → `test_reissued_statement_host_minutes_equal_live_confirmed_net_sum`: PRD-faithful NET clamp scenario (confirmed host 20 + confirmed WEATHER 25 → reissued host_delay_minutes 0, penalty 0, net 0) instead of the impossible confirm→dispute path.
- `test_suite/test_difficulty_state_machines.py` — `test_revision_loop_increments_revision_no_each_round` and `test_review_loop_is_cyclic_not_terminal`: removed the second `propose_timetable` call after `revise`; PRD says revise returns UNDER_REVIEW → PROPOSED and propose acts on a *draft*, so the cyclic loop is review→revise→review→ratify.
- `test_suite/test_difficulty_state_machines.py` — `test_escalated_overturn_reverses_incident_and_recomputes_attributed_minutes`: corrected `attributed_host_delay_minutes` assertion from 5 to 0; PRD counts CONFIRMED host incidents only, and the 5-minute incident is still DISPUTED at that point.
- `test_suite/test_difficulty_temporal_overlap.py` — `test_passage_one_minute_inside_clearance_is_infeasible`: corrected expected error from 422/`ERR_SCHEDULE_INFEASIBLE` to 409/`ERR_MAINTENANCE_CONFLICT`; PRD's clearance-buffer rule names `ERR_MAINTENANCE_CONFLICT` and the priority list places it (tier 9) ahead of schedule feasibility (tier 11).

**Fixes applied to implementation:**
- `workspace/implementation/core.py` — `endpoint` decorator now *defers* auth failures into `g.deferred_auth_error` instead of raising immediately, satisfying PRD §2.7's ordering (format → auth → authz → existence); added `raise_deferred_auth()`, invoked from `new_row`, `touch`, `forbid_unless_owner_host`, `svc.need()` (existence lookups), and after handler completion as a backstop so unauthenticated requests can never receive data. This fixed `test_format_failure_is_reported_before_auth` (400 ERR_VALIDATION now precedes 401 ERR_UNAUTHENTICATED).
- `workspace/implementation/svc.py` — added `import core`; `need()` calls `core.raise_deferred_auth()` before the lookup so auth (tier 2/3) still precedes existence (tier 4).

## Step 8: Finalize PRD — 2026-09-30T08:22:00.000Z

All edits are in place. Final verification: line counts identical (290 → 290, 0% delta), diff limited to exactly the four intended line-level revisions.

## Summary

**PRD.md vs PRD_FINALIZED.md:** both 290 lines (0% line-count delta; 4 lines revised in place).

### Changes

- **§2.7 — revise —** Appended clarification that the validation priority order governs *which error is reported* (not execution/short-circuit order), that later-tier checks may still run, and that tier-1 format failures are reported before tier-2 auth failures — `implementation/core.py:316-345` (`endpoint` decorator defers auth into `g.deferred_auth_error`), `implementation/core.py:301-313` (`raise_deferred_auth` invoked from `new_row` at core.py:203, `touch` at core.py:217, `forbid_unless_owner_host` at core.py:350, and the post-handler backstop at core.py:338), `implementation/svc.py:66-71` (`need()` raises deferred auth before existence lookup).
- **§3.3 — revise —** `propose` now documented as also rejecting with `ERR_MAINTENANCE_CONFLICT` when a planned passage conflicts with a LOCKED window under clearance-buffer semantics, with the §2.7 tier order (9 → 11 → 12) governing which error surfaces — `implementation/svc.py:261-318` (`check_schedule_feasibility` raises `ERR_MAINTENANCE_CONFLICT` at svc.py:289-292 before `ERR_SCHEDULE_INFEASIBLE` at svc.py:306-309).
- **§3.3 — revise —** Review loop explicitly pinned as cyclic with `revision_no` incrementing on each UNDER_REVIEW → PROPOSED return, and re-proposing requires DRAFT status — `implementation/routes/timetables.py:101-136` (`propose_timetable` rejects non-DRAFT at line 105-106; `revise_timetable` moves UNDER_REVIEW → PROPOSED and bumps `revision_no` at lines 131-135).
- **§3.7 — revise —** Clarified that post-resolution recompute of `attributed_host_delay_minutes` counts only currently-CONFIRMED incidents, so a still-DISPUTED incident contributes nothing — `implementation/svc.py:442-453` (`recompute_run_attributed_minutes` filters `status == "CONFIRMED"` at line 447), called from `implementation/routes/incidents.py:192-194` in `resolve_dispute`.

No edit for the settlement-variant step_7 item: §3.11 already states verbatim that reissue recomputes "from the currently CONFIRMED incidents" and the NET clamp — `implementation/svc.py:625-715` (`compute_statement_fields`) and `implementation/routes/settlements.py:133-144` match the PRD exactly. The fixture-override fix (`test_helpers/fixtures.py`) is a pure test bug with no PRD content.

### Per-edit pre-edit search log

**Edit 1 (§2.7 auth-ordering)**
- (a) Subject: evaluation order of format vs auth vs authz vs existence checks.
- (b) Enumerated: `core.py` `endpoint` (316-345), `raise_deferred_auth` (301-313), `new_row` (202-213), `touch` (216-221), `forbid_unless_owner_host` (348-356), `body()`/validators (369-475); `svc.py` `need()` (66-71); every handler's entry pattern across all ten route modules (grep for `body()`/validators/`need_*`/`forbid_unless_owner_host` in routes/*.py, plus the ordering grep showing existence-before-ownership on every ownership-gated path); read `windows.py` fully (create/lock/release) and `network.py` `set_clock` (30-38).
- (c) Yes: drafted strict sequencing ("authz applied before existence"), found ownership checks run after existence lookups in every ownership-gated handler (e.g. `runs.py:165-166`, `incidents.py:39-41`), so reworded to report-precedence language — the priority order decides *which error is reported*, tiers 2-3 still must precede tier 4+, and non-short-circuit of later tiers is permitted. This matches all enumerated paths, including non-ownership endpoints.

**Edit 2 (§3.3 propose maintenance check)**
- (a) Subject: which errors `propose` raises for window/overlap/capacity failures.
- (b) Enumerated: `svc.py` `check_schedule_feasibility` (261-318, the propose-time check), `check_publish_guards` (321-384, publish-time), `_passage_conflicts_window`/`_locked_window_expanded` (248-258), `runs.py` `actualize_passage` (159-205, actualization-time `ERR_MAINTENANCE_CONFLICT` at 178-183), `windows.py` `lock_window` (91-112, budget-first per §3.9), `timetables.py` `propose_timetable` (101-112).
- (c) Yes: scoped the new sentence explicitly to "The proposal is rejected…" and described the ordering as applying "when more than one of these rules fails" (tier 9 → 11 → 12), avoiding any claim about actualize/lock/publish paths; §3.4/§3.9 already describe those paths correctly.

**Edit 3 (§3.3 revise loop)**
- (a) Subject: revise transition target and revision_no semantics.
- (b) Enumerated: `timetables.py` `revise_timetable` (127-136), `propose_timetable` (101-112, DRAFT-only gate), `review_timetable` (115-124), `ratify_timetable` (139-151, also UNDER_REVIEW-only), `agreements.py` amend cascade (forces PROPOSED/UNDER_REVIEW → DRAFT, per §3.2), and the `revision_no` field (created 0 at timetables.py:61, only mutated in revise).
- (c) Yes: kept "the operator may return an under-review timetable to `PROPOSED`" verbatim (matches impl and §4 endpoint table), added only the cyclic-loop clarification, the "by one on each such return" increment pinning, and the "proposing again requires DRAFT" note — none of which touches ratify/amend-cascade paths.

**Edit 4 (§3.7 recompute semantics)**
- (a) Subject: what `attributed_host_delay_minutes` counts when recomputed after dispute resolution.
- (b) Enumerated: `svc.py` `recompute_run_attributed_minutes` (442-453, CONFIRMED-only, host-attributable-only); its two call sites — `incidents.py` `confirm_incident` (98-100) and `resolve_dispute` (192-194); incident status transitions in `incidents.py` (confirm 90-101, dispute 104-126, resolve 166-195); settlement recompute `svc.py:660-676` (also CONFIRMED-only, consistent).
- (c) No: appended sentence restates the CONFIRMED-only population already pinned in §3.5 with an explicit cross-reference; consistent with all enumerated call sites, no rewording needed.

## Step 9: Complete PRD — 2026-09-30T08:33:00.000Z

The diff is contained to the intended line-level edits (same 290 lines; +2561 chars). All edits are inline inserts/revisions.

## Summary

**Source file:** `PRD_FINALIZED.md` (290 lines, 43141 chars) → `PRD_COMPLETED.md` (290 lines, 45702 chars; +2561 chars, 0 line-count change).

**Counts:** 20 ambiguity-pins (inserts), 6 mismatch-revisions.

**Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION` — `implementation/core.py:499-523`
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence — `implementation/core.py:224-225`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `implementation/core.py:202-213`
- §2.7 — insert — ambiguity — request body must be a JSON object; absent/empty body treated as empty object — `implementation/core.py:369-381`
- §2.9 — revise — ambiguity — delay minutes pinned as max(0, floor((later − earlier) in whole minutes)) — `implementation/svc.py:434-439`
- §3.1 — insert — ambiguity — `annual_cost_cents` zero-or-more range — `implementation/routes/network.py:75`
- §3.1 — insert — ambiguity — `capacity_trains_per_day`, `pure_run_minutes`, `dwell_after_minutes` zero-or-more ranges — `implementation/routes/network.py:125-129`
- §3.2 — insert — ambiguity — `on_time_threshold_minutes`, `penalty_rate_cents_per_minute`, `incentive_rate_cents_per_train_mile` zero-or-more — `implementation/routes/agreements.py:36-40`
- §3.3 — insert — ambiguity — `service_date_end` on/after `service_date_start` else `ERR_VALIDATION` — `implementation/routes/timetables.py:47-50`
- §3.3 — insert — ambiguity — `trains_per_day` ≥ 1, `headway_minutes` ≥ 0 — `implementation/routes/timetables.py:36-38`
- §3.3 — insert — ambiguity — publish overlap guard counts only other timetable's `PLANNED`/`ACTUALIZED` passages, using actual interval when actualized — `implementation/svc.py:345-384`
- §3.3 — insert — ambiguity — `train_number` is a global cross-timetable counter rendered as decimal string; `scheduled_arrival_at` is final segment's planned exit — `implementation/svc.py:387-402`
- §3.4 — revise — mismatch — cancel's optional `reason` is accepted but not persisted (was "recording") — `implementation/routes/runs.py:118-128`
- §3.4 — insert — ambiguity — actualize requires owning run `EN_ROUTE`, else `ERR_INVALID_STATE` — `implementation/routes/runs.py:169-171`
- §3.6 — revise — mismatch — bridge cascade link one drops "whose service date overlaps the disruption" filter (impl applies only `scheduled_departure_at >= started_at`) — `implementation/svc.py:573-599`
- §3.6 — insert — ambiguity — auto-created disruption incident fires at most once per run — `implementation/svc.py:476-479`
- §3.8 — revise — mismatch — project suspend's optional `reason` accepted but not persisted — `implementation/routes/projects.py:121-132`
- §3.8 — insert — ambiguity — `funded_amount_cents`, `added_frequency_capacity` zero-or-more — `implementation/routes/projects.py:34-35`
- §3.9 — insert — ambiguity — `clearance_buffer_minutes` zero-or-more when supplied — `implementation/routes/windows.py:41-43`
- §3.10 — insert — ambiguity — funding draft born with `allocated_cost_cents` null; `period_end` on/after `period_start` else `ERR_VALIDATION`; state-code mismatch explicitly `ERR_REFERENTIAL_INTEGRITY` — `implementation/routes/funding.py:41-58`
- §3.11 — insert — ambiguity — statement period bounds pinned as date comparisons vs `effective_from`/`effective_to` dates; inclusive overlap; only `ISSUED`/`PAID` block — `implementation/routes/settlements.py:46-64`
- §3.11 — insert — ambiguity — run selection `service_date` inclusive on both ends — `implementation/svc.py:632-638`
- §3.11 — revise — mismatch — statement dispute's optional `reason` accepted but not persisted (was "recording") — `implementation/routes/settlements.py:118-128`
- §4 (13 table rows) — insert — ambiguity — each list endpoint's concrete query filters pinned (`host_railroad_id`/`status`; `corridor_id`/`state_code`/`status`; `corridor_id`/`operating_agreement_id`/`status`; `timetable_id`/`service_date`/`status`; `train_run_id`/`track_segment_id`/`status`; `train_run_id`/`segment_passage_id`/`status`/`cause_code`; `train_run_id`/`delay_incident_id`/`status`; `operating_agreement_id`/`track_segment_id`/`status`; `track_segment_id`/`equipment_unit_id`/`status`; `corridor_id`/`status`; `operating_agreement_id`/`status`) — `implementation/routes/*.py` list handlers

Notable behaviors verified as already pinned (no change needed): validation-order tiers, deferred-auth semantics, half-open occupancy and clearance-buffer conflict rules, equipment 40.00h weekly budget with ISO-week keying, funding two-step half-up rounding waterfall, settlement GROSS/NET variants and tier multipliers, agreement-expiry sweep at `clock >= effective_to`, and the full §5 error-code/HTTP-status table.
