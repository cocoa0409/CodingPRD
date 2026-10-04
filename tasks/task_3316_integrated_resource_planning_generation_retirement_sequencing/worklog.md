# Worklog — task_3316_integrated_resource_planning_generation_retirement_sequencing

## Step 1: Create Task Directory — 2026-09-30T19:56:00.000Z

Pre-allocated task directory `tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/` verified to exist with `workspace/` inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T20:28:00.000Z

  No forbidden vocabulary; all three files written and lint-clean.

  ## Summary

  **Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/`):
  - `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
  - `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
  - `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

  **Counts:**
  - 15 entities, 8 state machines, 9 calculations, 9 ordered validations, 78 endpoints, 47 error codes, 5 roles, 2 OCC concurrency rules
  - 18 difficulty instances (9 rules × 2), 50 corner instances (all with full test_recipes; no excluded stubs needed), 603 calls scanned by the linter

  **Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

  **Design notes (hardest-end choices):**
  - Archetype: compliance/audit + workflow orchestration; approval-chain RBAC with entity-backed Intervener ownership and a segregation-of-duties rule on commitment award (issuer's `created_by_user_id` vs awarding Commissioner's X-User-ID).
  - Logical clock (`/_clock/set_current_utc`, fixed default `2026-09-01T00:00:00Z`) drives comment-window date arithmetic, retirement lead-time, auto RETIRED transition, and the cycle-year Sept-1 statutory deadline.
  - Dual-variant pairs sit in different domains: load (COINCIDENT vs NET_PEAK electrification weighting) and sensitivity (COST_PLUS vs MARKET fuel pass-through), plus an accreditation-mode variant (DECIDED_EXCLUSIVE vs DECIDED_INCLUSIVE).
  - Combinatorial modes split across (a) multi-input non-linear accreditation (nameplate × factor × state eligibility × bracketed age-ramp derate) and (b) pinned round-per-component-then-sum retirement economics.
  - Boundary instances computed exactly in Python: zero-margin pass (460.00 vs 460.00 required), comment-window `closes_on` inclusive, recommendation strict `> 0`, deviation `> 0.05` strict (0.0525 breaches), CRF-based levelized costs pinned to the dollar.
  - Cascades are genuinely transitive: retire → snapshot retire-flag (portfolio version bump) → recompute flips `meets_requirement` → commission-review blocked; award → condition discharge → later deviation report's `required_procurement_mw` shrinks.
  - Cycle-bounded plan machine (REOPEN_LIMIT = 2), supersede-on-same-cycle_year auto-transition, testimony FILED↔WITHDRAWN cycle preserving `volume_no`.
  - All OCC version inputs in recipes reference `${var}` captures (a flat `GET /portfolios/{id}` was added so post-cascade versions are observable); `api_prefix` is `""` (root-mounted hybrid topology) after discovering the linter's FK derivation only recognizes prefix-nested single-GETs.

## Step 3: Copy Shared Files — 2026-09-30T20:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:42:00.000Z

  PRD generation complete.

  **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/workspace/PRD.md` — 363 lines.

  **Section list:** §1 Introduction (3 paragraphs); §2 Global Specifications with 9 subsections (2.1 RBAC with per-role identity prose, 2.2 Response Structure emitted verbatim from the canonical block, 2.3 Pagination, 2.4 Logical Clock & Statutory Calendar, 2.5 Common Resource Properties incl. the three thin entities Position/ReliabilitySnapshot/PlanDeviationReport, 2.6 OCC, 2.7 Precision & Rounding, 2.8 Cascades & left-to-right path validation, 2.9 nine-layer validation priority ordering); §3 Business Logic in 11 subsections (plan/forecast, fleet & candidates, portfolios & positions, retirement decisions & retire-flag cascade, snapshots/accreditation/derating/capacity margin, screening-levelized-cost & retirement analysis, sensitivity scoring with COST_PLUS/MARKET variants, plan lifecycle incl. supersede/reopen, procurement commitments & condition discharge & segregation of duties, comments/intervenors/testimony, deviation reports); §4 endpoint table (72 endpoints, 4 columns); §5 error catalogue (47 errors, 2 columns).

  **Hard-contract audit results (all PASS):**
  - Contract 1 Field-Name Coverage: entity fields 77/77, request-body identifiers 41/41, query params 17/17, path params 15/15 (added a §4 naming-conventions sentence covering all 15 camelCase path params). 0 missing.
  - Contract 3 §3 Path Purity: 420 backtick tokens scanned in §3 (heading-anchored extraction after stripping the §2.2 code fences — the fences shift naive backtick pairing), 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos.
  - Error IDs: all 47 scaffold error ids appear in backticks in §2/§3 narrative (and §5).

  **Zero-Silence coverage audit (scaffold rule → PRD section):**
  - All 7 ResourcePlan transitions incl. supersede cascade and reopen cap 2 → §3.8; preconditions paired with `ERR_PLAN_MISSING_BASE_FORECAST`/`ERR_PLAN_MISSING_PORTFOLIO`/`ERR_CYCLE_DEADLINE_MISSED`/`ERR_COMMENT_WINDOW_OPEN`/`ERR_NO_PREFERRED_PORTFOLIO`/`ERR_RELIABILITY_NOT_MET`/`ERR_PLAN_REOPEN_LIMIT`.
  - Portfolio DRAFT↔FROZEN system transitions → §3.8, §3.3; Resource ACTIVE→DECIDED→RETIRED/MOTHBALLED/cancel incl. retire-flag semantics (flagged snapshot excluded from review precondition, uniqueness slot freed) and clock auto-retire → §3.4, §2.4.
  - RetirementAnalysis DRAFT↔FINAL with recompute-on-reopen and plan-DRAFT gate → §3.6; PublicComment RECEIVED→ACKNOWLEDGED window gates → §3.10; Testimony FILED↔WITHDRAWN with ownership, `volume_no` preservation, standing → §3.10; Commitment ISSUED→AWARDED (condition discharge cascade, SoD via `created_by_user_id`) and ISSUED→CANCELLED (`ERR_CONDITION_ALREADY_DISCHARGED` guard, MW freeing) → §3.9; PlanCondition OPEN→DISCHARGED bubble-up → §3.9.
  - All 9 calculations expressed in prose with constants embedded: load forecasting (0.95 industrial coincidence, 1.00/0.60 electrification variants) §3.1; accreditation factors (all 9 types) + DECIDED_EXCLUSIVE/INCLUSIVE modes §3.5; derating (coal 40/50/0.90 linear, storage 20/0.75, DR 2030/0.85) §3.5; capacity margin (15% reserve, exactly-zero passes) §3.5; screening levelized cost (7% discount, 25-yr life, 4-step pinned allocation, `global_sequence_index` tie-break) §3.6; retirement analysis (10-yr window, coal 42000+8000 schedule, GAS_CT 6000, fixed O&M 38000/14000/9000, round-per-component, exactly-zero→KEEP) §3.6; sensitivity scoring (0.35 fuel share, 0.5 policy factor, 10% inclusive robust tolerance) §3.7; deviation measurement (0.05 strict threshold, zero-baseline rejection) §3.11; accreditation waterfall (auto_select eligibility, ranking, partial allocation) §3.9.
  - Both OCC rules with exact field names, error ids, HTTP 412, stale-version framing → §2.6; validation priority layers 1–9 → §2.9; all `applies_to` scopes and cross-entity referential rules (`ERR_SNAPSHOT_PLAN_MISMATCH`, `ERR_INTERVENOR_NO_STANDING`, `ERR_REFERENTIAL_INTEGRITY`, `ERR_CONDITION_NOT_FOUND` for cross-plan condition ids) → §3.4/§3.6/§3.7/§3.9/§3.10.
  - Role identity translations for all 5 roles (Intervener entity_backed; others opaque) → §2.1; statutory constants (MIN_RETIREMENT_LEAD_YEARS 2, REOPEN_LIMIT 2, COMMENT_WINDOW_DAYS 30, CYCLE_DEADLINE 09-01, clock default 2026-09-01T00:00:00Z) → §2.4/§3.4/§3.8.

  No invented rules; SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not opened.

## Step 5: Generate Unit Tests — 2026-09-30T21:10:00.000Z

  All verification sweeps pass on disk. Final summary:

  ## Files written

  **test_helpers/** (8 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/test_helpers/`):
  - `types.py` — status enums, role enum, TypedDicts for all 16 entities; Position / ReliabilitySnapshot / PlanDeviationReport correctly omit `version`/`updated_at` (append-only per PRD §2.5)
  - `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all root-mounted)
  - `api_errors.py` — full 46-error `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`
  - `assertions.py` — per-entity `assert_*` validators and a snapshot invariant checker
  - `factories.py` — payload factories (input fields only) with unique-name counter
  - `constants.py` — all PRD calculation/statutory constants + clock instants
  - `test_users.py` — shared role headers + per-instance builders incl. `make_intervener_headers(intervenor_id)` for the entity-backed Intervener role
  - `fixtures.py` — composite helpers: clock driving, plan lifecycle (`create_draft_plan_with_basics`, `setup_plan_under_review`, `setup_plan_rejected`, `setup_approved_plan`), OCC-aware `compute_snapshot` (reads current portfolio version), stakeholder and procurement helpers
  - `__init__.py` — barrel export

  **test_suite/** (8 files: `conftest.py` + `test_01`…`test_16`, same parent dir) — 86 tests total.

  ## Coverage

  - **Queue A (Difficulty): 18/18 instances, 36 tests** (exactly 2 per instance).
  - **Queue B (Corner): 50/50 non-stub instances, 50 tests** (exactly 1 per instance). No `excluded_because:` stubs exist in this corner index.

  ## Skipped-instance report

  No instance was skipped wholesale; two instances had specific drifted literals that were not asserted (PRD wins over design index, per the two-condition filter):

  1. `Difficulty/combinatorial_formula/retirement_analysis_mode_b_round_per_component` — covered by 2 tests asserting the PRD-verbatim compliance/fixed-OM literals (258,000,000 and 114,000,000), the net-benefit identity, and RETIRE. The design's replacement_cost 299,414,511 / net 72,585,489 are **not** asserted: the PRD's "each per-year or per-position component rounded to whole dollars before summing, not after (round-per-component-then-sum)" uniquely derives 299,414,510 (per-year 29,941,451.12 → round → ×10); 299,414,511 requires the PRD-forbidden sum-then-round order (verified numerically with Decimal CRF).
  2. `Corner/calculations/retirement_recommendation_zero_boundary_keep` — covered by 1 test asserting compliance 60,000, fixed_om 140,000, the net identity, negative net, and KEEP. The design's replacement 612,573 / net −412,573 are not asserted (same rounding contradiction: 61,257.26 → round → ×10 = 612,570).
  3. `Difficulty/dual_variant_calc/sensitivity_fuel_cost_plus_vs_market` — covered; design's COST_PLUS `robust_flag == true` literal not asserted because the PRD's inclusive 10% tolerance (|3,261.9k| = 10.89% > 10%) uniquely derives `false`; the MARKET literal (`false`) and all four score literals verified exact.

  ## On-disk verification (run from disk, not write history)

  - All 23 files compile (`compileall` clean); package imports cleanly.
  - Tag audit: 86/86 tests carry exactly one `Design:` tag as the final docstring line; 0 untagged, 0 dual-tagged, 0 unresolved pointers; queue A shortfall = none, queue B shortfall = none.
  - Verbatim-citation sweep: 125 quoted rule-bearing segments (≥8 words) all survive whitespace-normalized grep of `workspace/PRD.md`.
  - No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in generated code.
  - `pytest --collect-only` (with `PYTHONPATH=.`, which the runner supplies): **86 tests collected** without import errors.

  Orchestrator note: independently re-verified on disk — 9 test_helpers files + conftest.py + 16 test files present; `grep -c "def test_"` totals exactly 86 tests.

## Step 6: Generate Implementation — 2026-09-30T21:32:00.000Z

  Implementation complete. Summary:

  ## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/workspace/implementation/`)

  - **start.sh** — guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground, `$PORT` (default 10000), binds 0.0.0.0
  - **requirements.txt** — flask>=3.0,<4.0
  - **app.py** — Flask entry point, blueprint registration, `ApiError`/404/405/500 handlers producing the scaffold envelope
  - **db.py** — empty-on-boot in-memory store (no seeding), logical clock fixed at 2026-09-01T00:00:00Z, global candidate sequence counter
  - **errors.py** — all 40 scaffold error ids with exact HTTP statuses
  - **response.py** — envelope helpers: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list `meta` adds `limit/offset/total_count/has_more`
  - **middleware.py** — X-User-ID/X-User-Role auth (401), per-endpoint RBAC (403) via decorator
  - **helpers.py** — UUID/timestamp minting, `touch()` version bumps, Decimal round-half-up utilities, pagination (limit 1–100 default 10, offset 0), payload validators
  - **serializers.py** — wire views; Position/ReliabilitySnapshot/PlanDeviationReport carry only id+created_at per PRD §2.5
  - **calculations.py** — load forecasting (COINCIDENT/NET_PEAK variants), capacity accreditation with per-unit 2dp pre-sum rounding, coal/storage/DR derating, capacity margin (×1.15 reserve), CRF levelized-cost engine with full-precision ranking + global_sequence_index tie-break, retirement analysis (10-yr window, round-per-year-then-sum), sensitivity scoring (COST_PLUS/MARKET, POLICY fossil-only, TECHNOLOGY_COST capex-only), deviation measurement (4dp, strict >0.05), accreditation waterfall
  - **routes_clock.py, routes_plans.py, routes_forecasts.py, routes_resources.py, routes_candidates.py, routes_portfolios.py, routes_positions.py, routes_snapshots.py, routes_retirement.py, routes_comments.py, routes_intervenors.py, routes_sensitivities.py, routes_commitments.py, routes_deviations.py** — per-domain route modules implementing all state machines, cascades (retire-flag, freeze/unfreeze, lock/unlock, supersede, condition discharge), and both OCC guards (ERR_STALE_PLAN_VERSION / ERR_STALE_PORTFOLIO_VERSION, 412)

  ## Endpoint coverage check

  Programmatic diff of `app.url_map` against SCAFFOLD.yaml §1.5: **scaffold 78 endpoints, registered 78, missing 0, extra 0** (normalized path params).

  ## Fresh-boot smoke test

  `PORT=29931 bash start.sh` booted cleanly and served a full lifecycle: plan create (201) → forecast create (total 200.0, effective 198.0 = 100+50+40×0.95+10) → preferred portfolio → candidate + position → snapshot with OCC (`expected_portfolio_version: 2`, accredited 352.0 = 400×0.88, margin 124.3, meets_requirement true) → open-comment (window closes 2026-10-01 = +30 days) → clock advance → submit-for-review (UNDER_REVIEW, preferred pinned) → commission-review APPROVE with `expected_plan_version: 3` → APPROVED with approved_snapshot_id set. Own smoke-server PID killed afterward; no other processes touched.

  One note: the scaffold defines no dedicated not-found ids for Position, SensitivityAnalysis, or PlanDeviationReport flat GETs; those fall back to the nearest catalog family (ERR_PORTFOLIO_NOT_FOUND, ERR_ANALYSIS_NOT_FOUND, ERR_PLAN_NOT_FOUND respectively) — flagged as a potential scaffold gap if tests expect otherwise.

  Orchestrator note: independently re-verified on disk — 23 .py files + start.sh + requirements.txt present, 3220 total lines; start.sh is foreground `exec python3 app.py` with guarded pip install.

## Step 7: Run Tests and Iterate — 2026-09-30T21:47:00.000Z

  Clean 8-round sweep achieved. Summary:

  ## Summary

  - **Iterations run:** 3 (initial 8-round sweep: 18 deterministic failures in all rounds → fixes → probe 74/86 → more fixes → probe 86/86 → final 8-round sweep: **86/86 in all 8 rounds**).

  - **Tests deleted:** none.

  - **Fixes applied to `test_helpers/`:**
    - `fixtures.py` — `setup_approved_plan` gained `extra_forecast_years` param so callers can pre-register BASE forecast rows for years later used by snapshot compute (snapshot load must come from a stored forecast row).
    - `fixtures.py` — `set_clock` now tracks the logical-clock date in module state (`_current_clock_date`) so multi-plan fixtures keep the clock moving forward lawfully.

  - **Fixes applied to `test_suite/`:**
    - `test_01_dual_variant_calculations.py::test_load_forecasting_coincident_vs_net_peak_margins` — PRD §3.5 keys snapshot uniqueness on `(portfolio_id, forecast_year)` only, so the NET_PEAK comparison snapshot moved to a sibling portfolio (was colliding with ERR_DUPLICATE_SNAPSHOT).
    - `test_12_calculation_corners.py::test_accreditation_decided_inclusive_variant` — same slot fix (sibling portfolio, same scenario so the expected 450.00 holds).
    - `test_12_calculation_corners.py::test_storage_cycle_and_dr_step_derates` — candidate `online_year=2010` violated PRD §3.2's "must be 2026 or later"; reworked to exercise the 20-cycle storage cliff at 2045/2046 (online 2026) and the DR step at 2029/2030 with corrected expected values (134.50 / 145.00 / 145.00 / 126.25).
    - `test_04_transitive_cascades.py` — `_setup_cascade_plan_under_review` renamed to `_setup_cascade_plan_with_flagged_snapshot`: retire now happens while the plan is DRAFT (PRD §3.4: retire against a non-DRAFT plan is ERR_PLAN_NOT_DRAFT — the old test violated it), and the coal unit was resized 500→550 MW / in-service 2010→2020 so the baseline snapshot actually passes (500 MW coal at any age accredits 450 < 460 needed).
    - `test_04_transitive_cascades.py::_setup_condition_plan` and `test_08_slot_occupancy.py::test_deviation_report_for_other_year_accepted` — pass `extra_forecast_years=(2032,)` so the 2032 snapshot compute has a forecast row.
    - `test_05_validation_priority.py` — `_approve_plan` now schedules open/submit on a lawful calendar (open ≥ Jan 1 of cycle_year per the PRD §2.4 Sept-1 deadline, submit = open + 30 days, clock never rewound); the two `test_nameplate_breach_beats_cross_plan_condition_reference*` tests now expect `ERR_CONDITION_NOT_FOUND` (PRD §2.9 puts the 404 existence family — explicitly including body-referenced condition ids — before structural uniqueness, and PRD §3.9 maps a cross-plan condition to ERR_CONDITION_NOT_FOUND), replacing the scaffold-priority-driven ERR_NAMEPLATE_EXCEEDED expectation.
    - `test_16_cross_cutting_and_consistency.py::test_approval_of_same_cycle_supersedes_prior_plan` — same lawful-calendar fix via new `_open_and_submit` helper (plan C, cycle 2027, previously opened at 2026-08-31 and submitted 2026-10-01 while its window closed 2026-09-30).
    - `test_16_cross_cutting_and_consistency.py::test_mutations_visible_immediately_in_same_response` — `get_success_data` already returns the `data` payload; removed the erroneous extra `["data"]` index.

  - **Fixes applied to `implementation/`:**
    - `response.py` — added `_json_safe` (recursive Decimal→float) applied in `success_object`/`success_list`.
    - `routes_candidates.py`, `routes_positions.py`, `routes_commitments.py`, `routes_sensitivities.py`, `routes_snapshots.py`, `routes_deviations.py`, `routes_resources.py`, `routes_forecasts.py` — numeric entity fields now stored as Decimal (not float) so arithmetic like `candidate["nameplate_mw"] - committed_aggregate(...)` no longer raises `float - Decimal` TypeError; JSON conversion happens at the envelope boundary.
    - `routes_comments.py::acknowledge_comment` — added the missing state gate: only a `RECEIVED` comment may be acknowledged; a second ack is `ERR_INVALID_STATE` (409), per PRD §3.10 ("A comment is born `RECEIVED`; a planner may acknowledge it (`RECEIVED → ACKNOWLEDGED`...)").

  Orchestrator note: independently re-verified all 8 `results.${i}.json` on disk — every round reports total=86 passed=86 failed=0 errors=0 skipped=0.

## Step 8: Finalize PRD — 2026-09-30T21:55:00.000Z

  Both edits are in place. Final verification of the two edited sentences in context is complete via the diff above.

  ## Summary

  **Line counts:** PRD.md 363 lines; PRD_FINALIZED.md 363 lines (0% line-count delta — both edits are in-place sentence expansions within existing paragraphs; no sections added).

  **Changes (2 total):**

  - **§3.5 (Reliability Snapshots, demand side)** — revise — pinned how a snapshot's `load_mw` is sourced: exact `(scenario_tag, forecast_year)` forecast row; for non-`BASE` scenarios with no exact row, the `BASE` row for that year supplies the class contributions under the snapshot's variant; no usable row at all → `ERR_INVALID_REQUEST` (HTTP 400) — `implementation/calculations.py:190-213` (`find_forecast_load`), `implementation/routes_snapshots.py:70-73`.
  - **§3.10 (comment acknowledge)** — revise — named the two acknowledge rejection errors left unnamed by the PRD: plan not `OPEN_FOR_COMMENT` → `ERR_PLAN_NOT_OPEN_FOR_COMMENT` (409); comment not `RECEIVED` → `ERR_INVALID_STATE` (409) — `implementation/routes_comments.py:78-83`.

  **Step-7 diff items needing no PRD change (already pinned or test-side only):** sibling-portfolio moves in test_01/test_12 (PRD §3.5 already keys snapshot uniqueness on `(portfolio_id, forecast_year)`); storage/DR test rework (PRD §3.2 already pins `online_year >= 2026`; §3.5 derate wording matches impl, verified against expected values 134.50/145.00/145.00/126.25); test_04 retire-while-DRAFT fixture (PRD §3.4 already pins `ERR_PLAN_NOT_DRAFT`); test_05 `ERR_CONDITION_NOT_FOUND` expectations (PRD §2.9 + §3.9 already pin the 404 for missing/cross-plan condition ids, verified at `routes_commitments.py:70-75`); `extra_forecast_years`/`set_clock` fixture infrastructure and test_16 fixes (test-side only); Decimal storage + `_json_safe` (internal representation — the JSON surface §2.7 pins is unchanged).

  **Per-edit pre-edit search log:**

  1. **Edit 1 (§3.5 snapshot load sourcing).**
     - (a) Subject: where a snapshot's `load_mw` comes from and what happens when no forecast row exists.
     - (b) Enumerated paths: grepped `find_forecast_load`/`effective_load_for` across `implementation/` — only consumer is `routes_snapshots.py:70` (compute_snapshot); read `calculations.py:87-91, 190-213` (exact-row lookup, BASE fallback for non-BASE scenarios, `None` → `ERR_INVALID_REQUEST` 400) and `routes_deviations.py`/`compute_deviation_report` (consumes stored snapshot `load_mw`, unaffected). Confirmed the fallback evaluates class contributions under the requested variant (so a NET_PEAK snapshot falling back to a BASE row still applies the 0.60 electrification factor), consistent with §3.1's "stored `effective_load_mw` always reflects COINCIDENT" — my wording says the BASE row "supplies the class contributions… evaluated under the snapshot's variant" to avoid implying the stored COINCIDENT total is reused.
     - (c) Wording adjustment: phrased the fallback as "supplies the class contributions instead, still evaluated under the snapshot's variant" (not "the BASE row's effective load is used") to stay consistent with `effective_load_for(row..., variant)`.

  2. **Edit 2 (§3.10 comment acknowledge errors).**
     - (a) Subject: rejection errors for the acknowledge operation.
     - (b) Enumerated paths: grepped `ACKNOWLEDGED`/`RECEIVED` across `implementation/` — comment status is touched only at creation (`routes_comments.py:55`) and in `acknowledge_comment` (`routes_comments.py:73-86`); read the full function to confirm gate order (plan-status 409 first, then comment-state 409) and error ids. Checked the §5 catalog contains both `ERR_PLAN_NOT_OPEN_FOR_COMMENT` and `ERR_INVALID_STATE` at 409 (it does).
     - (c) Wording adjustment: named both errors in one clause without asserting a relative priority between them (both are in §2.9's 409 state-gate family, and the impl checks the plan gate first — left unpinned deliberately, per the under-determination preference).

  PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3316_integrated_resource_planning_generation_retirement_sequencing/workspace/PRD_FINALIZED.md`.

  Orchestrator note: independently verified on disk — PRD_FINALIZED.md exists, 363 lines, diff vs PRD.md shows exactly the 2 described in-place sentence expansions and nothing else.

## Step 9: Complete PRD — 2026-09-30T22:05:00.000Z

  All edits verified via the diff. Final stats and summary.

  **File stats**
  - Source `PRD_FINALIZED.md`: 363 lines / 63,863 chars
  - `PRD_COMPLETED.md`: 366 lines / 65,376 chars (+3 lines, +1,513 chars)

  **Counts: 6 ambiguity-pins, 6 mismatch-revisions (12 changes total)**

  Changes (PRD section — kind — class — what changed — impl reference):

  - §2.4 (logical clock) — insert — ambiguity — pinned `current_utc` response format as ISO 8601 UTC with no fractional digits — `implementation/routes_clock.py:32` + `db.py:36` (`now_iso()` uses `%Y-%m-%dT%H:%M:%SZ`).
  - §2.9 (validation ordering) — revise — mismatch — removed "forecast horizon" from the 422 temporal family (impl raises 400 for it) — `implementation/routes_forecasts.py:57-58`.
  - §3.1 (forecast creation) — insert — ambiguity — pinned horizon rule: `forecast_year > cycle_year + planning_horizon_years` → `ERR_INVALID_REQUEST` (400) — `routes_forecasts.py:57-58`.
  - §3.3 (portfolio creation) — revise — mismatch — `portfolio_name` is non-empty only; no uniqueness enforced — `routes_portfolios.py:31-53` (no name-uniqueness check; `helpers.get_str` enforces non-empty).
  - §3.4 (retire) — revise — ambiguity (ordering) — pinned concrete check order: resource existence/state (`ERR_INVALID_STATE`) → lead time (`ERR_RETIREMENT_TOO_EARLY`) → plan SUPERSEDED (`ERR_REFERENTIAL_INTEGRITY`) → plan not DRAFT (`ERR_PLAN_NOT_DRAFT`) — `routes_resources.py:98-114`.
  - §3.5 (snapshot compute) — insert — ambiguity — pinned stored field shape: `variant` stored verbatim (null when omitted), `accreditation_mode` stored resolved; response carries scenario/fuel price/computed fields/`retire_flagged` — `routes_snapshots.py:77-89`, `serializers.py:109-125`.
  - §3.5 (derating) — revise — mismatch — storage fleet units derate on `in_service_year` cycles (PRD said "online year" for all units) — `calculations.py:120-122, 159`.
  - §3.5 (load fallback) — insert — ambiguity — BASE-row fallback applies to both non-BASE scenarios (`HIGH_ELECTRIFICATION` and `LOW_GROWTH`) — `calculations.py:203-207`.
  - §3.5 (slot uniqueness) — insert — ambiguity — recompute into a retire-flagged slot creates a fresh row returned with HTTP 201 — `routes_snapshots.py:90-94`.
  - §3.6 (retirement analysis create) — insert — ambiguity — any resource status may anchor an analysis; missing `retirement_year` → `ERR_INVALID_REQUEST` (400) — `routes_retirement.py:31-54`, `calculations.py:321-323`.
  - §3.9 (commitment issue) — revise — ambiguity — pinned error split: zero remaining nameplate → `ERR_NO_ELIGIBLE_CANDIDATE` (422); partial remaining but over-cap → `ERR_NAMEPLATE_EXCEEDED` (409) — `routes_commitments.py:80-87`.
  - §3.9 (condition discharge ids) — insert — ambiguity — already-`DISCHARGED` listed conditions are validated but dropped from the stored `condition_discharge_ids` (only `OPEN` ones persisted) — `routes_commitments.py:88, 95`.
  - §3.10 (testimony filing) — insert — ambiguity — a non-string `intervenor_id` is rejected with `ERR_INTERVENOR_NO_STANDING` (422) — `routes_intervenors.py:87-88`.
  - §5 (error catalogue) — insert — ambiguity — added `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) for unmatched routes/methods and unexpected failures — `app.py:42-52`.

  Notable deliberately-unchanged areas (impl already matched PRD uniquely): all calculation constants/formulas in `calculations.py`, envelope shape and pagination, the full endpoint/role matrix, OCC guards, cascade semantics, reopen/supersede flows, deviation-report math, and the testimony volume_no semantics (impl assigns count-of-FILED + 1; tests do not distinguish this from max+1 and PRD prose covers it).

  Orchestrator note: independently verified on disk — PRD_COMPLETED.md exists, 366 lines, 29 diff lines vs PRD_FINALIZED.md with 13 ERR_ mentions in added lines, consistent with the reported 12 changes. Full task tree verified: SCAFFOLD*.yaml ×3, test_helpers ×9, test_suite ×17 (conftest + 16), worklog.md, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (23 .py + start.sh + requirements.txt + 8 passing results files)}.

## Pipeline Complete — 2026-09-30T22:05:00.000Z

All 9 steps done. Final state: 86/86 tests passing in all 8 rounds of the final stability sweep under per-test-server isolation; 0 test deletions; PRD aligned to implementation through PRD_FINALIZED.md (2 edits) and PRD_COMPLETED.md (12 edits).
