# Worklog — task_3358_residential_workforce_training_center_enrollment_placement

## Step 1: Create task directory — 2026-10-01T08:27:46.384Z

Task directory `./tasks/task_3358_residential_workforce_training_center_enrollment_placement/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and is empty. No new index computed, no other task_* directory created, per caller instruction.

## Step 2: Generate scaffold — 2026-10-01T09:53:03.220Z

All artifacts are complete, parse cleanly, and pass `scaffold_lint.py` with a clean verdict. Final report:

## Scaffold generated — task_3358_residential_workforce_training_center_enrollment_placement

**Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3358_residential_workforce_training_center_enrollment_placement/`):**
- `SCAFFOLD.yaml` — 1003 lines (§1.0–§1.7, no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 749 lines (single top key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1148 lines (single top key `scaffold_corner_design`, §1.9)

**Lint verdict (verbatim tail):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (789 calls scanned across §1.8+§1.9)

**Counts:**
- Entities: 13 (Applicant, Application, Center, TradeProgram, Enrollment, DormitoryAssignment, ConductIncident, Credential, EmployerAgreement, WBLPlacement, TransitionPlan, OperatorContract, PerformanceSnapshot)
- Endpoints: **41** — one over the ~40 aim: `GET /jc/applicants` was added during lint repair because `Applicant.assigned_center_id -> Center.id` failed FK reverse-reachability, and every other endpoint was load-bearing (each anchors an FK reverse-lookup, an OCC capture, a terminal-state reachability path, or a rule instance). Depth was kept in the mechanics rather than the surface.
- State machines: 11 entries over 10 entities — including a cyclic Application review/appeal loop, parallel training×residential dimensions on Enrollment, branching board adjudication on ConductIncident, and OPEN↔FULL auto-cycling on TradeProgram
- Calculations: 8 (income/age/barrier threshold, gated weighted center ranking with `created_at` tie-break, rolling 90-day conduct points, bed/seat ledger reconciles, dual-variant WBL hours, tiered transport allowance, dual-variant performance rates, per-graduate-then-sum payment)
- Validations: 25 ordered priorities; Errors: 24 (every one triggerable and referenced); Roles: 7 (all `identity: opaque`, segregation-of-duties between intake counselor and reviewer); Concurrency rules: 2 (both OCC on `Applicant.version` over supersede-style creates, 412 `ERR_STALE_VERSION`)
- §1.8: 18 instances — 2 per rule × 9 rules, all non-stub, all asserts precomputed as literals (verified by executing the formulas: e.g. payment 399998 vs 399997 under the wrong rounding order; PROVISIONAL 0.6667 vs FINAL 0.5000 graduation rates on identical data; ranking scores 4.70/8.00/9.00)
- §1.9: 56 instances across all nine claim-extraction sections — 46 full + 10 `excluded_because` stubs pointing at §1.8 instances

**Harder-than-expert drivers:** dual-variant math on two entity domains, combinatorial formulas in modes (a) and (b), a depth-3 separation cascade (incident→enrollment→dorm→center occupancy) plus a depth-2 checkout cascade, priority conflicts on two distinct error-category pairs (state>fiscal, safety>referential), half-open bed intervals vs aggregate WBL slot ceilings, OCC-vs-duplicate priority interplay, clock-driven window/expiry semantics (default clock pinned at 2026-09-01T00:00:00Z), and conditional plan inheritance of WBL hire conversions.

**Consistency sweeps run (beyond lint):** placeholder closure (no unbound `${var}`), grounds resolution, error-catalog usage, endpoint exercise coverage (all 41 exercised after fixes), enum-value closure (added the explicit `null -> REMEDIATION` create transition after the sweep flagged it), forbidden concurrency vocabulary (one "simultaneously" reworded), and a p7/p8/p16 precedence repair so `ERR_ALREADY_TERMINAL`, `ERR_INVALID_STATE`, and `ERR_TRANSITION_WINDOW_EXPIRED` each have a reachable, non-shadowed trigger.

Orchestrator verification: all three files confirmed on disk with the reported line counts; all parse as valid YAML; SCAFFOLD.yaml top-level keys = scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors (no difficulty/corner keys); the two design files each carry exactly their single required top-level key; endpoint count grep = 41.

## Step 3: Copy shared files — 2026-10-01T09:53:39.620Z

Copied `./INSTRUCTION.md` → `./tasks/task_3358_residential_workforce_training_center_enrollment_placement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T10:12:27.169Z

RECOVERY NOTE: the Step 4 subagent was mid-flight when the prior host session ended; its final report was never recorded. Per recovery protocol (lost report ≠ lost artifact), the orchestrator verified the artifact directly instead of re-running:

- `workspace/PRD.md` exists: 271 lines, 48246 bytes, ends cleanly on a complete error-catalogue table row (no mid-sentence/mid-table truncation).
- Structure matches the doc-generator template: §1 Introduction, §2 Global Specifications & System-Wide Principles (9 subsections incl. verbatim §2.2), §3 Business Logic & Workflows (8 subsections), §4 Endpoint Definitions, §5 Error Code Catalogue.
- Coverage cross-check vs SCAFFOLD.yaml (scripted): all 41 endpoint paths present in PRD §4 (43 table rows = 41 + header + separator); all 24 scaffold error ids present; all 13 entities present in natural-language form (WBLPlacement found as "work-based learning placement"); the fixed §2.2 verbatim block marker `req_RANDOMALPHANUM123456` present; the pinned logical-clock literal `2026-09-01` present.

Verdict: Step 4 is COMPLETE — the subagent finished writing PRD.md before the interruption; only its summary message was lost.

## Step 5: Generate unit tests — 2026-10-01T10:12:27.169Z

Done. Test infrastructure for task 3358 is generated and verified.

## Test counts per design source

**Queue A (§1.8 difficulty) — 18/18 instances emitted, 0 skipped.** Each instance got exactly 2 tests (36 total, tagged `Design: Difficulty/<rule_id>/<name>`). All passed the PRD-first filter; PRD §3.1–3.8 + §2.7 cover every asserted rule verbatim.

**Queue B (§1.9 corner) — 46/46 non-stub instances emitted (57 tests), 0 skipped.** All 10 `excluded_because:` stubs verified against queue A and not translated (all cross-references resolve to real difficulty instances). No freelance tests were invented.

Notable adjudications:
- `created_entities_apply_declared_defaults` and `reviewer_cannot_file_application`: dropped the design's literal `version == 1` assertion — PRD §2.5 says only "starts low at creation", which doesn't uniquely derive 1. Tests capture the created version and assert increment/unchanged-ness instead.
- `center_ranking_tie_break_created_at`: added a 1-second clock nudge between the two center creates so the created_at tie-break is deterministic under either a wall-clock or logical-clock `created_at` implementation; asserted outcome unchanged (both still score 4.70/4 beds).
- All other literals (0.6667 vs 0.5 rates, 399998 payment, 25/100/101-mile tiers, 119-vs-120-hour gate, 2026-06-03 window edge, 2027-09-01 plan expiry) re-derived against the PRD clock 2026-09-01T00:00:00Z and match the design recipes.

## Files

`test_helpers/` (9 files, 1580 lines): types.py (13 TypedDicts, 20 enums; PerformanceSnapshot correctly omits `updated_at`/`version` per PRD §2.5), constants.py (41 constants, all PRD-verbatim values), api_errors.py (24 error IDs + framework status-map registration), api_client.py (all 41 endpoints; close-period posts no body), assertions.py, factories.py, test_users.py (7 opaque roles + counselor/reviewer identity builders for segregation), fixtures.py (7 tiers of composite chains), `__init__.py` barrel.

`test_suite/` (11 files, 2510 lines): conftest.py + 10 domain-clustered test files (eligibility, assignment, enrollment gates, seats/credentials, dormitory, conduct, WBL, transition plans, operator performance, platform/RBAC).

## Verification results

- `pytest --collect-only test_suite/ -q` → **93 tests collected, 0 errors** (with `PYTHONPATH=.`).
- AST parse over all 20 generated .py files → **clean**.
- Design-tag audit → all 18 difficulty instances have ≥2 tags, all 46 corner instances ≥1, no dangling tags, exactly one tag per test, tag is the last docstring line, no `skip`/`xfail`/`skipif` anywhere.
- PRD-citation audit → all 109 quoted spans (≥8 words) survive literal whitespace-normalized grep of PRD.md.
- Constant-closure scan → no referenced UPPER_CASE name lacks a definition.
- pyflakes on test_suite → clean (caught and fixed one real `undefined name: transition_placement` in test_08 and one missing barrel export `create_dormitory_assignment_payload`).
- HTTP status fidelity → creates asserted with explicit 201 (applicant/application/center/program/close-period), transitions/checkouts with 200, errors auto-checked via the registered status map. No live server was started, per instructions.

Orchestrator verification: re-ran `pytest --collect-only` independently → 93 tests, 0 errors; grep confirms 0 skip/xfail/skipif markers; 93 `Design:` docstring tags = exactly one per collected test; test_helpers/ + test_suite/ total 4090 lines on disk.

## Step 6: Generate implementation — 2026-10-01T11:21:20.840Z

Done. The implementation is complete, compiles, and boots cleanly.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_3358_residential_workforce_training_center_enrollment_placement/workspace/implementation/`

**Files (20 Python modules + start.sh + requirements.txt, 2830 lines total):**
- `app.py` (90) — Flask factory, blueprint registration, global store lock, envelope error handlers
- `db.py` (98) — in-memory dict store, logical clock (default `2026-09-01T00:00:00Z`, never wall-clock), monotonic 3-fractional-digit timestamps, `version` starting at 1
- `errors.py` (41), `envelope.py` (42), `auth.py` (51), `helpers.py` (196 — body-shape validation, pagination `limit`/`offset`, date/age/month math)
- `domain.py` (356) — all derived state + calculations + cascades
- `serializers.py` (78) — per-entity views with read-time derivation
- 12 route modules: clock, applicants, applications, centers, programs, enrollments, dorm, conduct, credentials, wbl, transition, contracts
- `start.sh` (10, guarded `pip install`, `exec python3 app.py`, `$PORT`/0.0.0.0), `requirements.txt` (flask)

**Endpoints: 41/41** — verified by route-decorator count against the scaffold table (39 unique paths + GET/POST pairs on `/jc/applicants` and `/jc/enrollments`).

**State machines implemented (11):** Applicant assignment (NONE/ASSIGNED/ENROLLED/RELEASED with supersede + re-arm), Application eligibility (SUBMITTED→UNDER_REVIEW↔INFO_REQUESTED→ELIGIBLE/INELIGIBLE, appeal cycle, ELIGIBLE-only terminal), Enrollment training axis (TRAINING/REMEDIATION→COMPLETED/UNENROLLED/SEPARATED), Enrollment residential axis, DormitoryAssignment, ConductIncident (incl. zero-tolerance board routing and the depth-3 separation cascade), Credential (with REMEDIATION→TRAINING auto-advance on verify), WBLPlacement (incl. system termination on enrollment exit), TransitionPlan (read-time COMPLETED/EXPIRED/ACTIVE, COMPLETED wins), OperatorContract (ACTIVE↔PROBATION→TERMINATED + floor-driven auto-transitions), TradeProgram (OPEN↔FULL derived, CLOSED via PATCH only).

**Calculations implemented (8):** eligibility_determination (inclusive age bounds 16–24, income == limit passes, fixed reason order), center_assignment_ranking (capped weighted score, Decimal round-half-up 2dp, tie → beds_available DESC → created_at ASC), conduct_rolling_points (90-day window inclusive both ends, ≥10 hold), dorm_occupancy_reconcile (half-open [move_in, move_out) intervals, adjacency allowed, label-ASC auto-select), wbl_hours_credit (ACTUAL vs PROVISIONAL totals), transition_support_allowance (25/100-mile tiers lower-inclusive, 50000-cent housing stipend, 12-month window), performance_rate (FINAL vs PROVISIONAL with projected actives, 4dp round-half-up), operator_performance_payment (pinned round-per-graduate-then-sum order).

**Verification:**
- `py_compile`: all 20 .py files pass
- Boot smoke test: `PORT=17331 bash start.sh` — GET `/jc/applicants` with auth → 200 (correct envelope + pagination meta); without auth → 401 `ERR_UNAUTHENTICATED`; POST `/_clock/set_current_utc` → 200 echoing `current_utc`. Killed exactly the saved PID; no test suite was run, and no design/test files were read.
- No seeding: store initializes to empty dicts only.

**Notable fidelity decisions (PRD-first):** eligibility gate precedes empty-pool error on center-assignment (PRD §3.2 ordering over scaffold priority numbering); validation pipeline otherwise follows scaffold priority numbers exactly (incl. prerequisite check 12 before applicant-eligible 17 on enrollment create, SoD at priority 3 via raw-action peek, terminal lockdown before state analysis on `*/transition` paths, services endpoint's window-check outranking the generic state rule while a fully-resolved plan still surfaces `ERR_INVALID_STATE`); board-ordered separation creates the plan with all tracks PENDING while manager-initiated complete/separate applies WBL hire-inheritance (PRD §3.4 vs §3.3); PerformanceSnapshot carries only `id`/`created_at` (no `updated_at`/`version`); body-referenced FK misses resolve as `ERR_NOT_FOUND`.

Orchestrator verification: all 22 files present on disk; independent `py_compile` over all 20 .py files passes; independent route-decorator grep = 41; seeding scan shows only a benign "nothing is seeded" comment in db.py; Step 5↔6 literal spot-check aligns (50000-cent stipend, 90-day window, age 16/24, 120-hour gate, `DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"` present in both trees).

## Step 7: Test/fix iteration loop — 2026-10-01T11:21:20.840Z

**CLEAN SWEEP ACHIEVED — all 8 parallel rounds pass 93/93.**

## Summary

**Iterations run:** 2 (initial sweep surfaced 4 deterministic failures; post-fix sweep is clean across all 8 rounds).

**Tests deleted:** none — every failing test traced to a PRD-verbatim rule (§2.5 id format, §3.2 pool filter + §2.7 state-beats-capacity priority, §3.7 transport tiers, §3.8 FINAL variant/floor). No PRD-silence or unique-derivability collapses found.

**Fixes applied to `test_suite/`** (2 files, both test-setup bugs — fixtures constructed preconditions a PRD-faithful implementation must reject):

- `test_suite/test_05_dormitory.py` — `TestStateBeatsCapacity._setup`: moved e2's resident enrollment BEFORE `assign_bed(e1)`. Previously the setup created e1, exhausted the only bed, then attempted e2's residential-track center-assignment — which PRD §3.2 requires to fail with `ERR_NO_ELIGIBLE_CENTER` (pool excludes centers with `beds_available < 1`). The reorder preserves the design recipe's dual-failure intent (e2 terminal AND bed pool exhausted at trigger time, asserting `ERR_INVALID_STATE` wins per §2.7).
- `test_suite/test_08_transition_plans.py` — `TestTransportTiers`: replaced per-plan `setup_enrolled_student` (3 centers) with one center + one program + three applicants, matching the design recipe's "three COMPLETED graduates at one center". With three identical centers, all candidates tie at score 7.6 (completion releases the seat per §3.3, restoring `open_seats`), so the §3.2 `created_at ASC` tie-break assigned later applicants to the oldest center → `ERR_CENTER_MISMATCH` on enrollment.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`** (1 file):

- `workspace/implementation/db.py` — `Store.new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5's "server-minted UUID" is the canonical dashed 8-4-4-4-12 form (the harness-wide `is_valid_uuid` validator and sibling-task convention); only `assert_performance_snapshot` exercises the check, which is why just one of 93 tests tripped on it.

**Artifacts:** `results.{1..8}.json` (all 93/93) retained in `workspace/implementation/` per the output contract.

Orchestrator verification: independently parsed all 8 `results.{i}.json` — every round passed=93 failed=0 total=93 errors=0; confirmed `str(uuid.uuid4())` shipped at db.py:60 and the test_05 setup reorder is on disk.

## Step 8: Finalize PRD — 2026-10-01T11:21:20.840Z

Done. `workspace/PRD_FINALIZED.md` written — exactly one revised sentence; everything else verbatim.

## Summary

**Line counts / delta:** PRD.md 271 lines vs PRD_FINALIZED.md 271 lines; +136 chars (+0.28%), +0 lines.

**Changes (1 edit):**
- §2.5 — revise — pinned the server-minted resource `id` to the canonical dashed 8-4-4-4-12 string form (36 chars, hyphens included, example given), keeping "no type prefix" and the rest of the sentence verbatim — `implementation/db.py:57-60` (`Store.new_id()` returns `str(uuid.uuid4())`; the Step 7 fix changed `uuid.uuid4().hex` → `str(uuid.uuid4())`, and the harness `is_valid_uuid` regex `^[0-9a-f]{8}-[0-9a-f]{4}-...{12}$` rejects the dashless hex form).

**No-edit determinations for the two test-side fixes (PRD already verbatim; sibling-path audit per orchestrator caution):**
- *test_05_dormitory.py (pool filter + state-beats-capacity)*: §3.2's pool filter (`beds_available ≥ 1` under `residential_track`, else `ERR_NO_ELIGIBLE_CENTER`) matches `domain.rank_centers` (domain.py:197-235), its only caller being `center_assignment` (routes_applicants.py:140). §2.7's state-before-business priority matches `create_dormitory_assignment` (routes_dorm.py:72-106: `ERR_INVALID_STATE` for non-`AWAITING_BED` — terminal enrollments read `RELEASED` — before `ERR_CONDUCT_HOLD`, `ERR_BED_OVERLAP`, `ERR_NO_BED_AVAILABLE`) and the terminal→state→business order in `enrollment_transition` (routes_enrollments.py:148-190). No looseness on any sibling path.
- *test_08_transition_plans.py (seat release + tie-break)*: seat restoration is derived (`program_enrolled_count` counts only `REMEDIATION`/`TRAINING`, domain.py:56-66), so all four terminal transitions — complete/unenroll/separate (routes_enrollments.py:182-190) and board-ordered separation (routes_conduct.py:159, same `finalize_enrollment_terminal`) — release the seat exactly as §3.3/§3.4/§2.9 describe. The ranking tie-break (domain.py:232-234 sorts `-score, -beds_available, _seq`; `_seq` is a strictly monotonic creation counter ≡ `created_at` ASC) matches §3.2 verbatim. Transport tiers (domain.py:137-148) match §3.7 verbatim. No edit warranted.

**Per-edit pre-edit search log:**
- Edit 1 (§2.5 UUID form):
  - (a) Subject: string representation of server-minted persisted-resource `id`s.
  - (b) Impl paths enumerated and read/grepped: `db.py:57-60` (`new_id`, sole minting function); `db.py:84-94` (`new_record`, used by all 10 route modules for every resource create); `routes_contracts.py:152` (performance snapshot id, also via `STORE.new_id()`); `envelope.py:12` (`api_request_id` = `"req_" + uuid4().hex[:24]` — not a persisted resource id, governed by §2.2); `test_helpers/assertions.py` (`is_valid_uuid` on all resource ids); runner regex probed directly (dashed passes, dashless hex fails, case-insensitive). Grep confirmed no other uuid/id-minting sites.
  - (c) Wording adjustment: scoped the pin to "persisted resource ... id" (§2.5's existing scope) so `api_request_id` under §2.2 is untouched; phrased as a uniform property of all resource ids so both minting paths (`new_record` and the snapshot literal) are covered; kept "with no type prefix" verbatim. No narrowing of any enumerated path.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the one reported §2.5 sentence revision and nothing else (1 hunk, +136 chars, 0 net lines); mtime ordering confirms Step 8 did not touch implementation/ — newest source file (db.py, the Step 7 fix) predates all 8 sweep results files, so the clean sweep remains valid.

## Step 9: Complete PRD — 2026-10-01T11:21:20.840Z

All edits are in place and verified. Here is the final report.

## Summary

**Files**
- Source: `workspace/PRD_FINALIZED.md` (271 lines, 48,382 chars)
- Produced: `workspace/PRD_COMPLETED.md` (271 lines, 52,863 chars; **+4,481 chars, +0 lines** — all changes are in-paragraph inserts/revisions; section headers byte-identical; 22 paragraphs touched)

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions.

### Changes (one bullet each)

- §2.3 — insert — ambiguity — pinned `offset >= 0` and that non-integer/out-of-range `limit`/`offset` are `ERR_INVALID_REQUEST` — implementation/helpers.py:133-155
- §2.4 — revise — ambiguity — clock endpoint accepts any parseable instant (not constrained to be later), unparseable → `ERR_INVALID_REQUEST`, and `current_utc` echoes the supplied `to_iso8601` text verbatim — routes_clock.py:13-29
- §2.5 — revise — ambiguity — `version` "starts low" pinned to starts at 1 — db.py:84-94
- §2.6 — revise — ambiguity — OCC token must equal the applicant's current `version` exactly (impl uses `!=`, rejecting in both directions) — routes_applications.py:71-76, routes_applicants.py:116-121
- §2.7 — revise — **mismatch** — segregation-of-duties now runs *after* the case identifier resolves (it reads stored `intake_counselor_id`) and before body validation; PRD had it before id resolution, impl does 404 → segregation — routes_applications.py:135-144
- §2.7 — insert — ambiguity — per-action role restriction sits at the priority-2 tier ahead of id resolution; body-carried identifiers resolve after body-shape validation in payload-field order; entity-dependent field-domain checks (bed-label range reads the center's `total_beds`) run right after that entity resolves — routes_applications.py:124-134, routes_dorm.py:55-70
- §2.7 — revise — **mismatch** — removed "assignment in `CHECKED_OUT`/`TERMINATED`" from the terminal-lockdown list and carved out checkout (impl reports `ERR_INVALID_STATE` there) — routes_dorm.py:149-154
- §2.7 — revise — **mismatch** — carved period close-out out of terminal lockdown: a `TERMINATED` contract close reports `ERR_PERIOD_NOT_CLOSABLE`, not `ERR_ALREADY_TERMINAL` — routes_contracts.py:143-149
- §2.7 — revise — ambiguity — terminal list now includes terminal enrollments; cross-entity state precondition clause qualified to "no more specific error named in §3" (so `ERR_PROGRAM_NOT_OPEN` stands) — routes_enrollments.py:148-153, 78-83
- §3.1 — insert — ambiguity — per-action role split pinned (`begin_review`/`request_info`/`determine` = EligibilityReviewer only; `provide_info`/`appeal` = AdmissionsCounselor only; mismatch → `ERR_FORBIDDEN_ROLE` before id resolution/segregation) — routes_applications.py:124-134
- §3.2 — insert — ambiguity — `ranked_candidates` entry shape pinned: `center_id`, `score`, `trade_points`, `capacity_points`, `geo_points`, `beds_available` — routes_applicants.py:155-165
- §3.2 — insert — ambiguity — program PATCH may set only `CLOSED`; `OPEN`/`FULL` or re-`CLOSED` → `ERR_INVALID_STATE` — routes_programs.py:76-83
- §3.3 — insert — ambiguity — prerequisite screen runs *ahead of* the three enrollment gates (`ERR_PREREQUISITE_NOT_MET` first) — routes_enrollments.py:59-65
- §3.3 — insert — ambiguity — hire-inheritance takes the earliest-created qualifying placement's `hire_wage_cents` — domain.py:254-265
- §3.4 — revise — ambiguity — bed-label form pinned: `B-` + zero-padded number of at least two digits, value in 1..`total_beds` — routes_dorm.py:24, 60-70
- §3.4 — revise — ambiguity — checkout date rule named `ERR_INVALID_REQUEST`, evaluated after the state check; checkout of non-`ACTIVE` → `ERR_INVALID_STATE` — routes_dorm.py:149-160
- §3.4 — revise — ambiguity — board-separation cascade suppressed when the owning enrollment's training axis is already terminal (incident still lands `SEPARATION_ORDERED`) — routes_conduct.py:157-161
- §3.6 — insert — ambiguity — `hourly_wage_cents` is a non-negative integer of cents; completion hours shortfall → `ERR_INVALID_STATE`; missing `hire_wage_cents` on claimed conversion → `ERR_INVALID_REQUEST` — routes_wbl.py:118, 227-232, 301-309
- §3.7 — revise — ambiguity — `expires_at` = twelve calendar months with day-of-month clamping — helpers.py:170-182, domain.py:246
- §3.7 — revise — ambiguity — `starting_wage_cents` (non-negative integer) / `distance_miles` (non-negative number) required when completing their tracks (`ERR_INVALID_REQUEST`); stipend/allowance read 0 while `PENDING` or `WAIVED` — routes_transition.py:63-80, domain.py:133-148
- §3.8 — insert — ambiguity — duplicate `contract_code` → `ERR_INVALID_REQUEST`; preview response field list pinned; close accepts no payload fields — routes_contracts.py:54-59, 119-131, 139-141
- §5 — insert — ambiguity — `ERR_INTERNAL` (HTTP 500) for unexpected server failures — errors.py:37, app.py:72-76

### Dead-code audit

**No PRD-required check-helper with zero callsites found.** Every guard/validation helper is called: all 17 `domain.py` functions (incl. `recompute_conduct_hold`, `prereqs_met_for_applicant`, `prereqs_met_for_enrollment`, `agreement_status`, `plan_status`, `rank_centers`, `performance_calc`), all `helpers.py` validators, `auth.authenticate`/`require_role`, and route-local guards (`_bed_conflicts`, `_center_of_enrollment`, `_active_count_for_agreement`, `_active_count_for_supervisor`, `_overwrite_snapshot`, `request_body_present`, per-module `_invalid_state`). Two non-check dead spots noted for completeness: `errors.raise_err` (errors.py:40 — generic raise-wrapper utility, zero callsites, no PRD sentence requires it) and an unused `invalid` import in routes_applications.py:26 (the helper itself is used throughout helpers.py). Neither is a PRD-mandated check shipped as dead code.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md is a real patch (271 lines, 52,863 chars = +4,481 over PRD_FINALIZED.md, matching the report); section headers byte-identical between PRD_FINALIZED.md and PRD_COMPLETED.md; no .py file under implementation/, test_suite/, or test_helpers/ is newer than the sweep results files — Step 9 touched nothing executable and the clean 8-round sweep remains valid; all 8 `results.{i}.json` still present; PRD_COMPLETED.md ends cleanly on the complete error catalogue.

## Pipeline complete — 2026-10-01T12:05:00.000Z

Final output-contract verification passed: all required artifacts present (3 scaffold YAMLs, worklog.md, test_helpers/ 9 files, test_suite/ conftest + 10 test files, workspace/ INSTRUCTION.md + PRD.md + PRD_FINALIZED.md + PRD_COMPLETED.md, implementation/ with start.sh + requirements.txt + app.py + 19 more modules + results.1–8.json). Final sweep state re-verified: 8/8 rounds at 93/93 passed, 0 failed.
