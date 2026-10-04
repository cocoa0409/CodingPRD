# Worklog — task_3413_category_leadership_joint_business_planning_innovation_launch

## Step 1: Create task directory — 2026-10-01T20:49:59.771Z

Task directory was pre-allocated by the caller: `tasks/task_3413_category_leadership_joint_business_planning_innovation_launch/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created. Difficulty instruction "Generate task much harder than expert level!" applies to Step 2 (scaffold generator) only.
## Step 2: Generate scaffold (subagent) — 2026-10-01T21:52:21.731073354Z

All checks green. Final report:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3413_category_leadership_joint_business_planning_innovation_launch/SCAFFOLD.yaml` — 92,778 bytes (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3413_category_leadership_joint_business_planning_innovation_launch/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 67,392 bytes (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3413_category_leadership_joint_business_planning_innovation_launch/SCAFFOLD_CORNER_DESIGN.yaml` — 161,991 bytes (single key `scaffold_corner_design`)

## Counts
- 13 entities, 42 endpoints, 10 state machines, 34 validation rules, 5 calculations, 39 error codes, 6 roles, 1 OCC concurrency rule, 33 pinned constants
- §1.8: 18 instances, all non-stub (2 per rule × 9 rules)
- §1.9: 84 instances — entities 11 (10 full + 1 stub), state_machines 13, calculations 7, validations 24, endpoints 7, errors 8 (3 full + 5 stubs), rbac 7, cross_cutting_complexity_layers 6 (3 full + 3 stubs), consistency_model 1 → 75 non-stub, 9 stubs, every stub's `difficulty_instance` ref verified to exist in §1.8
- api_prefix: `/jbp`; entities: Retailer, Category, JointBusinessPlan, PromotionalEvent, CategoryAnalysis, ShelfRecommendation, InnovationLaunch, LaunchPhase, TradeFund, Deduction, Forecast, PricePackDecision, PerformanceReview
- Instance names unique across the union of both design files (18 + 84)

## Verification
- YAML parsed after **every** append (caught and fixed three flow-context bugs — `$.data[0].id` / `validations[priority=N]` / `errors[...]` / `concurrency_rules[...]` inside flow collections needed quoting — plus a `yaml.safe_dump` restyle that re-indented the top-level list, which mangled a later append until dedented)
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (816 calls scanned, 0 violations)
- Every referenced constant resolves to the single top-level `constants:` block; no constant defined-but-unreferenced; no forbidden concurrency vocabulary (one "in parallel" found and reworded)
- All formula-derived asserts were pre-computed by hand (e.g. risk scores 52/25/24→26, fund split 601/400, rounding-order divergence 42788 vs 42787, distribution variants 53.75 vs 50.0)

## Design decisions worth flagging downstream
- **Endpoint count is 42** — two above the remembered Step-6 danger threshold of 40. Deliberate trade for "much harder than expert"; every endpoint is load-bearing (FK reverse-reachability or a mechanic). If impl-gen struggles, the merge candidates are already exhausted — do not cut GET singles (FK segment derivation + OCC version capture depend on them).
- **Error-with-side-effect pattern used twice**: negotiate at round 6 fails AND auto-EXPIRES the plan; verify past the 90-day SLA fails AND auto-STALLS the rec. Tests must assert both the error and the state change.
- **OCC only where a true race exists**: shelf-recommendation create (create-with-supersede against `JointBusinessPlan.version`). All other apparent races were classified as state preconditions per §1.2.1.
- **No clamp on `distribution_projection`** — the phase-write sum cap (≤100) makes a clamp unreachable dead code, so the formula was written without one.
- **No circular preconditions**: chain is plan → (analysis → shelf), (phases → launch → review), (activate → fund → accrual → event lock/deduction); verified acyclic.
- **Logical clock**: `POST /jbp/_clock/set_current_utc`, default `2026-09-01T00:00:00Z`, monotonic non-decreasing; all review/SLA fixtures were checked against this default (review recipes advance the clock before creating windowed entities so `created_at` lands inside review periods).
- Settlement **short-pays at the bucket floor** (`min(amount, available)`) instead of erroring — this is what powers the depth-3 cascade instance (settle → fund → review friction → posture flip HEALTHY→WATCH).

Orchestrator verification: all three files YAML-parse; SCAFFOLD.yaml top-level keys exclude both design keys; design files each have exactly their single required top-level key; 130 occurrences of `/jbp` and all 13 claimed entity names present in SCAFFOLD.yaml (domain-fidelity spot-check passed).

## Step 3: Copy shared files — 2026-10-01T21:52:36.953219653Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD (subagent) — 2026-10-01T22:15:15.378307566Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3413_category_leadership_joint_business_planning_innovation_launch/workspace/PRD.md` — 332 lines, 61,686 bytes. (The withheld design-index files were never opened.)

**Section list:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-for-byte verbatim from the canonical block, diff-verified); 2.3 Pagination; 2.4 The Shared Logical Clock; 2.5 Common Resource Properties; 2.6 Nested Resource Retrieval and Path Validation; 2.7 Money, Percentages, and Rounding Discipline; 2.8 Optimistic Concurrency Control; 2.9 The Validation Pipeline and Its Priority Order; 2.10 Plan Lifecycle Discipline and Terminal States; 2.11 Trade Fund Ledger Principles
- §3 Business Logic: 3.1 Reference Data, Plan Negotiation, and Activation; 3.2 The Promotional Calendar and Event Funding; 3.3 Category Advisory and Data Governance; 3.4 Shelf Assortment Recommendations and Implementation Tracking; 3.5 Innovation Launch Planning and Phase Gates; 3.6 Fund Accruals and Deduction Resolution; 3.7 Weekly Forecasts and Retailer Commitments; 3.8 Price-Pack Architecture and Channel Conflict; 3.9 Post-Launch Performance Review and Delisting Risk
- §4 Endpoint Definitions (42 rows, 4 columns); §5 Error Code Catalogue (39 rows, 2 columns). File ends at §5, no audit footer.

**Completeness-spotlight checklist:**
1. **Constants** — the scaffold block actually defines 34 entries (not 33): all 34 appear with exact value, unit, and governing rule. Clock default `2026-09-01T00:00:00Z` in §2.4; rounds 6, growth −20..50, fiscal 2026–2030, accrual (0,5], split floor 20 (§3.1); depth 40 (§3.2); space ±30, stores 1–10000, SLA 90d (§3.4); gap 84d, 4 phases, sum cap 100, phase weights 1.0/0.25/0.0 (§3.5); factor 0.92 (§3.6); club 12, gap 15, undercut 10 (§3.8); review 84d, weights 0.40/0.30/0.20/0.10, bias cap 25 ×4, friction cap 5 ×20, posture 25/50/75 (§3.9). Machine-verified: 34/34 values present.
2. **Logical clock** — §2.4: default instant verbatim, monotonic non-decreasing, regression rejected `ERR_VALIDATION`, `PlatformAdmin`-only, `to_iso8601` in / `current_utc` out, all time-gated preconditions read it.
3. **Error+state couplings** — both halves in one breath: §2.10 (dedicated) plus in-workflow at §3.1 (`ERR_NEGOTIATION_ROUNDS_EXHAUSTED` + auto-`EXPIRED` from both `PROPOSED` and `COUNTERED`) and §3.4 (`ERR_IMPLEMENTATION_STALLED` + auto-`STALLED`; contrasted with `ERR_IMPLEMENTATION_INCOMPLETE` making NO state change).
4. **OCC** — §2.8 and §3.4: `expected_plan_version` required on shelf-recommendation create only, mismatch → `ERR_STALE_VERSION` (412), rationale (supersede incumbent), plus the create's plan-`version` bump; explicitly stated no other endpoint takes a version field.
5. **Calculations** — operand order and rounding points pinned: fund waterfall with per-period round-half-up before accumulation and remainder-to-EVENT (§3.6); event-cost selector (latest containing week, fallback to `weekly_baseline_cases`) with single terminal rounding (§3.2); attainment/bias/friction/risk with clamps, weights, and inclusive posture thresholds (§3.9); dual distribution projections (§3.5); `price_per_unit_cents` rounds UP (§2.7/§3.8); boundary inclusivity stated ("exactly 15 passes", "exactly 84 days passes").
6. **Validations** — all 34 priorities: §2.9 numbered pipeline (1–13 explicit, 14–34 grouped enumeration with pointer to per-workflow homes) plus emphasized orderings (phase gates before date; pairwise gap before undercut; verify's 3-step order; OCC → plan-status → analysis on shelf-rec create). All 39 error ids appear in §2/§3 prose with HTTP statuses (machine-verified 39/39); §5 carries no conditions column.
7. **RBAC** — §2.1 names all six roles with exact spelling, translates each `identity:` (entity-backed `RetailerBuyer` with plan-chain ownership comparison + read scope-limitation; five opaque roles individually named); §3 assigns every action to its role; §4 lists roles per endpoint.

**Hard-contract reports:** Contract 1 — 100 required identifiers (entity fields, endpoint inputs, query params, common fields), 100 present, 0 missing, PASS. Contract 2 — 34/34 validations, 1/1 OCC rules, 37/37 transitions, 5/5 calculations, 39/39 error ids, all endpoint side effects, field defaults/nulls, symmetric sibling branches, PASS. Contract 3 — §3 scanned 491 backticked tokens, 0 path/method violations, PASS. (Note: the token extractor must strip §2.2's fenced JSON first — fence markers otherwise flip backtick parity and false-positive the scan.)

**Ambiguity calls made:** (a) treated the "33 constants" instruction as approximate — the block has 34, all rendered; (b) priority-4 generic body shape vs priority-5 growth-target range rendered as "shape first, then the growth-specific range error"; (c) scaffold names no launch-state precondition for review creation, so the PRD says "opens on a launched product" without inventing one; (d) event-create plan states rendered as the four listed non-terminal states with terminal rejection via `ERR_ALREADY_TERMINAL`; (e) §4 read-endpoint role cells say "All six roles" per the scaffold's own shorthand note, exact spellings anchored in §2.1. Final full-file re-read confirmed no truncated paragraphs.

Orchestrator spot-check: PRD.md is 61,686 bytes; tokens 2026-09-01T00:00:00Z / ERR_STALE_VERSION / ERR_NEGOTIATION_ROUNDS_EXHAUSTED / ERR_IMPLEMENTATION_STALLED / expected_plan_version / 0.92 / ERR_ALREADY_TERMINAL / PlatformAdmin all present; design-index worked-example numbers 42788 / 42787 / 53.75 / 52/25 / 601/400 all absent (no leakage).

## Step 5a: Generate test helpers (subagent, Stage 1 of split Step 5) — 2026-10-01T22:37:12.535255166Z

Stage 1 complete for task_3413. All helpers are written, byte-compiled, and import-verified.

### File list (bytes)
- `test_helpers/__init__.py` — 945
- `test_helpers/types.py` — 9 328
- `test_helpers/api_client.py` — 10 609
- `test_helpers/api_errors.py` — 4 409
- `test_helpers/assertions.py` — 16 424
- `test_helpers/factories.py` — 10 510
- `test_helpers/constants.py` — 3 643
- `test_helpers/test_users.py` — 2 494
- `test_helpers/fixtures.py` — 25 702
- `test_suite/conftest.py` — 1 650 (infrastructure only; no test functions)

### py_compile results
All 10 files: OK. Additionally `import test_helpers` executed cleanly (error map registered, no star-import collisions); spot-checked 50 export names — none missing. `ApiClient` exposes 46 public methods (42 endpoint methods + inherited base), `HTTP_STATUS_CODES` covers all 39 PRD §5 error ids.

### Exported helper API (the contract Stage 2 codes against)

**types.py** — enums (all `str, Enum`): `UserRole` (6 roles), `Channel`, `RetailerStatus`, `AdvisoryScope`, `PlanStatus`, `PlanDecision(ACCEPT/REJECT)`, `EventType`, `EventStatus`, `AnalysisStatus`, `AnalysisDecision(ACCEPT/RETURN)`, `ShelfRecStatus`, `ShelfRecDecision(ACCEPT/REJECT)`, `LaunchStatus`, `PhaseType`, `PhaseStatus`, `DeductionBucket(EDLP/EVENT)`, `DeductionStatus`, `DeductionAction(DISPUTE/SETTLE/REJECT/WRITE_OFF)`, `ForecastPubStatus`, `ForecastCommitStatus`, `PricePackStatus`, `PricePackDecision(APPROVE/REJECT)`, `ReviewStatus`, `ReviewDecision(CONTINUE/DELIST)`, `RiskPosture`. Constants: `ALL_ROLE_NAMES`, `CHANNEL_NAMES`, `PLAN_TERMINAL_STATES`, `DEDUCTION_TERMINAL_STATES`, `PHASE_TYPE_BY_INDEX` ({1:CAPACITY_BUILD, 2:DISTRIBUTION_BUILD, 3:TRADE_SPEND, 4:SUSTAIN}). TypedDicts for all 13 entities (all carry id/created_at/updated_at/version per PRD §2.5); note the PPD record TypedDict is named `PricePackDecisionRecord` to avoid colliding with the `PricePackDecision` payload enum.

**api_client.py** — `api_client` singleton + `ApiClient(GenericApiClient)`. All methods take `headers=None` (sends no auth headers → the 401 probe path). 46 public methods covering all 42 endpoints: set_clock, create_retailer, create_category, create_plan, get_plan, list_plans, negotiate_plan, decide_plan, activate_plan, create_event, list_events, lock_event, cancel_event, create_category_analysis, list_category_analyses, decide_category_analysis, create_shelf_recommendation, list_shelf_recommendations, decide_shelf_recommendation, verify_shelf_recommendation, create_launch, list_launches, get_launch, execute_launch, list_launch_phases, patch_launch_phase, evaluate_launch_phase, get_fund, list_funds, post_fund_accrual, create_deduction, list_deductions, resolve_deduction, create_forecast, list_forecasts, commit_forecast, create_price_pack_decision, list_price_pack_decisions, decide_price_pack_decision, create_performance_review, list_performance_reviews, finalize_performance_review. Base URL comes from `API_BASE_URL` env via the framework; no port hardcoded.

**api_errors.py** — `ApiErrorId` (39 members), `HTTP_STATUS_CODES` map, registered at import via `set_error_http_status_map` so `validate_error(resp, ApiErrorId.X)` auto-checks the HTTP status.

**assertions.py** — per-entity assert helpers for all 13 entities. Domain invariants: `assert_fund_invariants` (both derived-availability identities, PRD §2.11), `assert_launch_budget_invariant` (total == remaining + Σspend), `assert_distribution_projections` (recomputes committed/weighted with Decimal round-half-up 2dp, weights 1.0/0.25/0.0), `expected_risk_posture`, `assert_risk_posture_matches_score`. `assert_price_pack_decision` pins `price_per_unit_cents == ceil(list_price_cents/unit_count)`; `assert_category_analysis` pins `competitor_share_pct == 100 - manufacturer_share_pct`.

**factories.py** — `DEFAULTS` dict + payload factories for every endpoint body (plan, negotiate, decide, activate, event, analysis, analysis-decide, shelf-rec w/ expected_plan_version, shelf-decide, verify, launch, phase-patch, accrual, deduction, deduction-resolve, forecast, forecast-commit, ppd, ppd-decide, review, review-finalize, clock). All accept `**overrides`. Server-side defaults under test (retailer `status`, category `advisory_scope`, analysis `includes_competitor_data`, shelf `sku_adds`/`sku_drops`) are deliberately NOT defaulted.

**test_users.py** — `TEST_USERS` with per-role header builders; `make_retailer_buyer_headers(user_id)` (entity-backed — pass the real `Retailer.id`); `make_headers(user_id, role)` for unknown-role 401 probes.

**fixtures.py** — clock: `set_clock`, `ensure_clock_at_least`, `add_days_iso`. Plan chain: `setup_proposed_plan/setup_accepted_plan/setup_activated_plan` (return retailer/category/plan/(fund)/buyer_headers), `negotiate_rounds`, `drive_plan_to_exhaustion`, `get_plan_version`. Events: `create_penciled_event`, `create_locked_event`. Analyses: `create_submitted_analysis`, `create_accepted_analysis`. Shelf: `create_proposed_shelf_rec` (None → live GET version capture), `create_implementing_shelf_rec`. Launches: `create_launch_with_phases`, `gate_all_phases`, `execute_launch`, `create_launched_launch` (default launch_date 2027-01-15). Funds: `get_fund`, `get_fund_for_plan`, `post_accrual`. Deductions: `file_deduction`, `resolve_deduction`, `create_disputed_deductions`. Forecasts: `create_published_forecast`, `create_committed_forecast`. PPDs: `create_price_pack`, `create_approved_price_pack`. Reviews: `create_open_review` (auto-advances clock to launch_date+84d). Composite: `setup_review_scenario(...)` (clock-ordered so friction inputs land inside the review window).

### constants.py — every value annotated with the PRD § where it appears verbatim
DEFAULT_CLOCK_START_ISO="2026-09-01T00:00:00Z" (§2.4); MAX_NEGOTIATION_ROUNDS=6, GROWTH_TARGET_MIN_PCT=-20, GROWTH_TARGET_MAX_PCT=50, FISCAL_YEAR_MIN=2026, FISCAL_YEAR_MAX=2030, FUND_ACCRUAL_RATE_MAX_PCT=5, EVENT_SPLIT_MIN_PCT=20, EDLP_SPLIT_MAX_PCT=80 (§3.1); CASH_COLLECTION_FACTOR=0.92 (§3.6); PROMO_DISCOUNT_DEPTH_MAX_PCT=40 (§3.2); SHELF_SPACE_CHANGE_MAX_PCT=30, SHELF_TARGET_STORE_COUNT_MAX=10000, IMPLEMENTATION_SLA_DAYS=90 (§3.4); CHANNEL_PRICE_GAP_MAX_PCT=15, ECOMMERCE_UNDERCUT_MAX_PCT=10, CLUB_PACK_MIN_UNITS=12 (§3.8); LAUNCH_MIN_GAP_DAYS=84 (§3.5); REVIEW_MIN_DAYS_AFTER_LAUNCH=84, RISK_WEIGHT_SALES=0.40, RISK_WEIGHT_DISTRIBUTION=0.30, RISK_WEIGHT_FORECAST=0.20, RISK_WEIGHT_FRICTION=0.10, FORECAST_BIAS_CAP_PCT=25, FORECAST_BIAS_NORMALIZER=4, FRICTION_COUNT_CAP=5, FRICTION_UNIT_SCORE=20, RISK_WATCH_MIN_SCORE=25, RISK_AT_RISK_MIN_SCORE=50, RISK_DELIST_MIN_SCORE=75 (§3.9); PHASE_COUNT=4, DISTRIBUTION_SUM_MAX_PCT=100, PHASE_WEIGHT_GATE_PASSED=1.0, PHASE_WEIGHT_PENDING=0.25, PHASE_WEIGHT_GATE_FAILED=0.0 (§3.5); PAGINATION_DEFAULT_LIMIT=10, PAGINATION_MAX_LIMIT=100 (§2.3).

### Design decisions Stage 2 must know
1. Clock advancement only via `POST /jbp/_clock/set_current_utc` (PlatformAdmin); `ensure_clock_at_least` treats 400/ERR_VALIDATION as "clock already later" (monotonic).
2. RetailerBuyer identity is entity-backed: ownership-gated calls use `make_retailer_buyer_headers(retailer["id"])`; scenario dicts carry `buyer_headers`. Never use the fallback `retailer_buyer_headers` for an ownership-gated call.
3. OCC version capture: `create_proposed_shelf_rec(plan_id, expected_plan_version=None)` GETs the plan live; a successful shelf-rec create bumps plan version by 1 (re-GET before a second create).
4. No 200 default anywhere: fixtures use `get_success_data` (any 2xx); Stage 2 passes explicit statuses — `validate_success(resp, 201)` for creates, 200 for actions/reads.
5. `setup_review_scenario` advances the clock to `activity_clock` BEFORE filing deductions/committing forecasts so friction inputs land inside the review window.
6. `create_launched_launch` defaults launch_date=2027-01-15; `create_open_review` advances to launch_date+84d = 2027-04-09.
7. No-auth probes: pass `headers=None` to any ApiClient method.
8. conftest.py exposes `api` (session-scoped), one header fixture per role, and `buyer_headers_factory`. Stage 2 must not modify `test_helpers/`.

Orchestrator spot-check: all 10 files exist with matching sizes; `python3 -m py_compile` clean on all; constants values 0.92 / 0.40 / -20 / 10000 / 2026-09-01T00:00:00Z / 90 days / 84 days / 0.25 present in both PRD.md and constants.py.

## Step 5b: Generate difficulty-queue tests (subagent, Stage 2 queue A) — 2026-10-01T23:11:46.265298258Z

Stage 2 (Queue A) is complete. All verification gates pass.

**Files written** (all under test_suite/, one per rule_id, 4 tests each, 36 total): test_difficulty_dual_variant_calc.py (8818), test_difficulty_combinatorial_formula.py (7477), test_difficulty_non_linear_state_machine.py (8046), test_difficulty_transitive_cascade.py (10012), test_difficulty_priority_pair_validation_conflict.py (7304), test_difficulty_boundary_precision_check.py (8540), test_difficulty_cross_entity_state_dependency.py (7503), test_difficulty_resource_temporal_overlap.py (7108), test_difficulty_compensating_invariant.py (9463).

**Instance-to-test mapping — all 18 §1.8 instances EMITTED, zero SKIPPED:**
- fund_accrual_basis_vs_cash_basis -> test_difficulty_dual_variant_calc.py (2 tests)
- launch_distribution_weighted_vs_committed -> same file (2 tests)
- risk_score_multi_input_threshold -> test_difficulty_combinatorial_formula.py (2)
- fund_credit_rounding_per_period_then_sum -> same file (2)
- plan_negotiation_cycle_rounds -> test_difficulty_non_linear_state_machine.py (2)
- forecast_parallel_dimensions -> same file (2)
- deduction_settle_cascade_to_review_posture -> test_difficulty_transitive_cascade.py (2)
- delist_finalize_cascade_retires_price_packs -> same file (2)
- lock_event_state_beats_fiscal -> test_difficulty_priority_pair_validation_conflict.py (2)
- launch_state_beats_temporal -> same file (2)
- risk_posture_boundary_at_25 -> test_difficulty_boundary_precision_check.py (2)
- negotiation_round_exhaustion_at_six -> same file (2)
- shelf_rec_requires_accepted_analysis -> test_difficulty_cross_entity_state_dependency.py (2)
- forecast_create_requires_activated_plan -> same file (2)
- promo_overlap_half_open_adjacency -> test_difficulty_resource_temporal_overlap.py (2)
- launch_min_gap_buffer_semantics -> same file (2)
- event_lock_cancel_conserves_event_funding -> test_difficulty_compensating_invariant.py (2)
- phase_budget_patch_conserves_total -> same file (2)

**Verification:** py_compile PASS on all 9 files; collect-only: 36 tests collected == emitted; AST tag audit 36/36 single terminal Design: Difficulty/<rule_id>/<instance.name> lines, tag set == 18 instances exactly (2 tests each); all 81 PRD § citation lines survive whitespace-normalized literal match against workspace/PRD.md; frozen Stage-1 tree untouched (mtimes 22:24–22:33 vs test files 22:56–23:08).

**Helper-contract compliance:** creates via validate_success(resp, 201), reads/actions via validate_success(resp, 200) or validate_error with the registered status map; RetailerBuyer identity via scenario["buyer_headers"] / make_retailer_buyer_headers; clock only via set_clock/ensure_clock_at_least; OCC version captured live via get_plan_version; no double clock advancement around setup_review_scenario.

**Interpretation choices:**
1. Version assertions are delta-pinned, not absolute (PRD pins +1 per mutation but not the initial value); negotiation_round absolutes (1-born, 5, 6) ARE PRD-pinned and asserted absolutely.
2. Priority-pair second tests exercise the unmasked loser (lock -> ERR_INSUFFICIENT_FUNDS after activation; launch -> ERR_LAUNCH_DATE_NOT_REACHED after gating, then success after clock advance).
3. Rounding-order test asserts == 42788 (derived from test-chosen inputs + PRD formula); the forbidden 42787 named in prose but not asserted as inequality.
4. Superseded-forecast test asserts committed_cases survives but only checks committed_at presence — PRD names only commit_status as preserved.
5. Distribution-projection setup zeroes phase 3 target before evaluation; asserted totals 50.0/53.75 unaffected.
6. Review-scenario tests file windowed inputs at review period start (2027-01-01) rather than the recipe's 2027-03-01 — both inside the closed window, computed values identical.

## Step 5c1: Generate corner tests group 1 (subagent; entities/endpoints/errors/rbac/cross_cutting/consistency) — 2026-10-01T23:36:47.520887725Z

**Files written** (one per message, no truncation): test_corner_entities.py (12869, 10 tests), test_corner_endpoints.py (9120, 7), test_corner_errors.py (5224, 3), test_corner_rbac.py (8164, 7), test_corner_cross_cutting.py (6647, 3), test_corner_consistency.py (2839, 1).

**Instance disposition — 31/31 non-stub EMITTED, 0 SKIPPED:**
- entities: retailer_create_defaults_active; retailer_create_explicit_suspended_accepted; category_create_defaults_full_category_scope; plan_create_initial_computed_fields; plan_create_extra_computed_field_rejected; plan_create_with_missing_retailer_returns_404; launch_create_autocreates_four_phases; ppd_price_per_unit_ceil_rounding; deduction_create_defaults; analysis_competitor_share_computed (all -> test_corner_entities.py)
- endpoints: response_envelope_success_shape; error_envelope_shape; pagination_defaults_limit_10; pagination_limit_out_of_range_returns_400; list_filter_by_status; nested_child_not_found_under_wrong_parent; funds_filter_by_plan_id_returns_single_fund (all -> test_corner_endpoints.py)
- errors: err_insufficient_funds_triggerable; err_launch_date_not_reached_triggerable; err_review_already_exists_triggerable (all -> test_corner_errors.py)
- rbac: retailer_buyer_cannot_create_plan; manufacturer_cannot_commit_forecast; advisor_cannot_post_accrual; retailer_scope_mismatch_on_counter; platform_admin_cannot_negotiate; clock_set_requires_platform_admin; retailer_buyer_read_other_retailer_plan_returns_scope_mismatch (all -> test_corner_rbac.py)
- cross_cutting_complexity_layers: occ_stale_expected_plan_version_returns_412; occ_fresh_version_succeeds_and_bumps_plan_version; version_increments_on_each_plan_mutation (all -> test_corner_cross_cutting.py)
- consistency_model: mutation_visible_immediately_in_read (-> test_corner_consistency.py)

**Stubs (9) not translated; difficulty_instance refs all verified resolvable:** entities/forecast_created_published_supersedes_prior; errors/err_analysis_not_accepted_triggerable, err_negotiation_rounds_exhausted_triggerable, err_phase_gates_incomplete_triggerable, err_promo_overlap_triggerable, err_plan_not_activated_triggerable; cross_cutting/cascading_side_effects_covered, dual_variant_calculation_covered, derived_field_reconciliation_covered.

**Verification gates:** py_compile PASS on all six; collect-only on the six: 31 collected, zero errors, no server contact; AST tag audit 31/31 exactly one terminal Design: Corner/<section>/<name> line, tag set == assigned non-stub set exactly (0 missing/extra/stubs/malformed/non-terminal); every PRD § citation line survives whitespace-normalized verbatim match against workspace/PRD.md (0 failures); frozen tree untouched (test_helpers mtimes 22:24–22:33, conftest 22:33, all predate corner writes).

**Interpretation choices:**
1. Version values delta-pinned, never absolute (PRD pins only +1-per-mutation, no initial value; consistent with queue A adjudication).
2. Failed event lock: no estimated_cost_cents-is-None assertion (PRD admits rollback and persist-on-failure readings); asserts PENCILED + event_reserved_cents == 0.
3. Stale-OCC test asserts activated.version == stale + 1, pinning the 412 to the trigger condition.
4. Envelope tests assert meta.api_request_id startswith req_ and exact error-meta key set — both verbatim PRD §2.2.

**Helper-contract compliance:** creates validate_success(resp, 201); reads/actions 200; errors validate_error with registered status map; RetailerBuyer via scenario["buyer_headers"]/make_retailer_buyer_headers(retailer["id"]); OCC via get_plan_version/response capture; launch-date error test leaves clock at PRD §2.4 default; setup_review_scenario used once, no double advance.

## Step 5c2: Generate corner tests group 2 (subagent; state_machines/calculations) — 2026-10-01T23:54:10.94945301Z

**Files written:** test_corner_state_machines.py (20,798 bytes, 13 tests), test_corner_calculations.py (16,395 bytes, 7 tests). Frozen Stage-1 tree untouched.

**Per-section instance disposition — 20 EMITTED, 0 SKIPPED:**

state_machines -> test_corner_state_machines.py: plan_negotiate_from_accepted_returns_invalid_state; plan_decide_wrong_actor_returns_not_your_move; plan_expired_rejects_further_negotiate_returns_already_terminal; analysis_decide_twice_returns_already_terminal; shelf_superseded_on_new_create; shelf_verify_from_proposed_returns_invalid_state; launch_launch_twice_returns_invalid_state; phase_patch_after_gate_passed_returns_phase_locked; phase_evaluate_out_of_order_fails_gate; forecast_commit_on_superseded_returns_not_published; deduction_reject_from_received_returns_invalid_state; event_cancel_twice_returns_already_terminal; suspended_retailer_blocks_activation.

calculations -> test_corner_calculations.py: event_cost_estimate_uses_latest_published_forecast; event_cost_estimate_falls_back_to_plan_baseline; fund_split_remainder_routes_to_event_bucket; forecast_bias_excludes_uncommitted; forecast_bias_empty_set_zero; sales_attainment_two_decimal_rounding; phase_revise_recomputes_projections.

**Verification:** py_compile OK both files; collect-only on the two files: exactly 20 tests, no server contact, no errors; AST tag audit 20/20 exactly one terminal Design: line, 0 missing / 0 extra; all 43 PRD § citations survive whitespace-normalized literal substring check (0 failures).

**Interpretation choices:**
- plan_expired_rejects_further_negotiate_returns_already_terminal: recipe trigger is a post-expiry DECIDE (not negotiate); asserted only status == EXPIRED on re-read, deliberately NOT negotiation_round post-exhaustion (PRD pins version increment on failed move, silent on round counter — two-reader failure otherwise). Setup uses frozen drive_plan_to_exhaustion (5-success-then-failure alternation, matches recipe).
- launch_launch_twice_returns_invalid_state: LAUNCHED is not terminal per PRD §2.10 (only REVIEWED/DELISTED are), so unique outcome is ERR_INVALID_STATE; docstring says so explicitly to pre-empt an ERR_ALREADY_TERMINAL misreading.
- suspended_retailer_blocks_activation: empty-fund-list assertion derived from PRD §2.11 ("created at the moment of activation") — failed activation materializes no fund; asserted via list_funds?plan_id= returning [].
- Calculation literal values (22500, 16875, 601/400/553/368, 10.0/12/HEALTHY, 0/0/HEALTHY, 33.33/27/WATCH, 70.0/77.5) copied from the design index and independently re-derived against PRD formulas — all agree.

## Step 5c3: Generate corner tests group 3 (subagent; validations) — 2026-10-02T00:12:51.727076241Z

**Files written (one per message, no truncation):** test_corner_validations_a.py (12,145 bytes, 8 tests), test_corner_validations_b.py (14,068, 8), test_corner_validations_c.py (13,602, 8).

**Instance disposition (24/24 EMITTED, 0 SKIPPED):**
- -> test_corner_validations_a.py: missing_auth_headers_returns_401; unknown_role_returns_401; negotiate_missing_field_beats_not_found; governance_boundary_competitor_data_rejected; growth_target_above_range_returns_400; discount_depth_above_max_returns_400; accrual_rate_above_max_returns_400; event_split_below_min_returns_422
- -> test_corner_validations_b.py: channel_gap_at_exactly_max_approved; channel_gap_above_max_rejected; ecommerce_undercut_boundary; club_pack_min_units_boundary; week_not_aligned_returns_422; launch_outside_fiscal_year_returns_422; review_too_early_returns_422; duplicate_claim_reference_returns_409
- -> test_corner_validations_c.py: duplicate_accrual_period_returns_409; shelf_space_change_out_of_range_returns_400; sku_lists_overlap_returns_400; plan_create_duplicate_active_triple_returns_409; plan_create_duplicate_triple_allowed_after_rejection; verify_after_sla_stalls_recommendation; verify_with_insufficient_stores_returns_incomplete; verify_success_boundary_at_target

**Verification:** py_compile OK on all three; collect-only 24 tests, zero errors, no server contact; AST tag audit: exactly one terminal Design: line per test, emitted set == 24 non-stub validations instance names exactly; all 47 PRD § quotations survive whitespace-normalized literal grep of workspace/PRD.md.

**Interpretation choices:**
1. event_split_below_min_returns_422 (edlp_split_pct=85): asserted ERR_EVENT_SPLIT_TOO_LOW (422) per PRD §3.1's explicit sentence over the generic shape mapping; §2.9's domain-rule bucket names "the activation split floor"; scaffold priority-34 agrees.
2. Boundary inclusivity asserted only where the recipe dictates both sides: pass-at-boundary for channel-gap-15, e-commerce floor 90, club-pack 12, Monday week_start, review launch+84 (2027-04-09), verify +90d/100 stores; one-past-fail for gap-17, floor-89, club-11, Tuesday, launch+83, +91d. For growth_target_above_range and discount_depth_above_max only the fail side is asserted (pass phrasing lives in distinguishing_aspect, not the assert list).
3. Side-effect pins: plan stays ACCEPTED after rejected activation; no fund materializes after ERR_EVENT_SPLIT_TOO_LOW; rejected approval leaves price-pack PROPOSED; total_invoiced_cents unchanged after duplicate accrual; verify-after-SLA leaves rec STALLED (error-with-side-effect §2.10); incomplete verify leaves status and version untouched.
4. Date arithmetic independently verified: 2027-03-01 is Monday, 2027-03-02 Tuesday; launch 2027-01-15 +83/84d = 2027-04-08/09; accept 2027-01-01 +90/91d = 2027-04-01/02.

**Frozen-contract compliance:** nothing in test_helpers/ or conftest.py modified; explicit statuses everywhere; baselines built from factories with single-field overrides; no skip/xfail markers; no other subagents' files touched.

## Step 5 audit: full-suite measurable completeness (orchestrator) — 2026-10-02T00:14:30.610536641Z

Full-suite verification after Stage-2 slices 5b/5c1/5c2/5c3:
- pytest --collect-only: 111 tests collected, 0 collection errors (dangling-import check passed).
- AST walk of every test docstring: 111 tests, 93 unique terminal `Design:` tags, 0 untagged, 0 dual-tagged.
- Diff against both indices: index non-stub = 18 difficulty + 75 corner = 93; MISSING: none; EXTRA: none.
- Shape check: every difficulty tag has exactly 2 tests (18/18); every corner tag has exactly 1 (75/75).
- (First audit pass mis-parsed the corner yaml — its top level is a list of {section, instances} objects, not a dict; corrected walker confirms exact coverage. The earlier MISSING/EXTRA lists were walker artifacts, not test gaps.)

## Step 6: Generate implementation (subagent) — 2026-10-02T00:55:10.148444154Z

### File list (all under workspace/implementation/)
start.sh (396; guarded flask install, `exec python3 app.py` foreground), requirements.txt (14), app.py (1785; factory + envelope error handlers, 0.0.0.0:$PORT default 10000 under __main__), constants.py (3506; 38 PRD-pinned constants + enum alphabets + terminal sets), errors.py (1847; ApiError + 39-id catalog + err()), envelope.py (1338), timeutil.py (1567; fmt_logical vs fmt_stamp 3-fractional-digit stamps per PRD §2.5), clock.py (1109; default 2026-09-01T00:00:00Z, monotonic, PlatformAdmin endpoint), validation.py (3427; priority-4 body-shape + pagination), auth.py (2018; priorities 1–3, RetailerBuyer scope + list-visibility), storage.py (1582; in-memory dicts, UUID ids, version/timestamp stamping), calc.py (10222; all 5 calculations with Decimal discipline), reference.py (2037), plans.py (~9.9K; uniqueness, negotiate w/ round-6 exhaustion + auto-EXPIRE, decide, activate w/ fund creation), events.py (5221; half-open overlap per plan+type, lock estimate+reservation+ERR_INSUFFICIENT_FUNDS, cancel release), analyses.py (3913; governance boundary, competitor_share = 100 − share), shelf.py (6759; OCC create 412 + incumbent auto-WITHDRAWN + plan version bump, verify ordered state→SLA-auto-STALL→store count), launches.py (5634; 4 auto phases, fiscal-year + 84-day separation, gates-before-date execute), phases.py (5088; PATCH PENDING/GATE_FAILED only, evaluate gate), funds.py (2362; derived availabilities, accrual YYYY-MM dup 409), deductions.py (5138; claim unique per fund, resolve DISPUTE/SETTLE/REJECT/WRITE_OFF with min(amount, bucket-available) settlement + 3-hop review cascade), forecasts.py (4532; Monday 00:00:00Z, ACTIVATED plan, supersession preserves commit_status), pricepacks.py (5409; channel membership, CLUB ≥ 12, ppu ceil, gap rule before undercut), reviews.py (6555; LAUNCHED gate, one-per-launch, 84-day timing, 5 computed fields, finalize cascade retires pack family).

### Route table
42 routes registered, diffed programmatically against PRD §4 after normalizing <param>→{id}: 0 missing, 0 extra (43rd rule is Flask /static, excluded).

### Boot smoke transcript
- Port 53037 (dynamic): poll GET /jbp/plans until 401 ERR_UNAUTHENTICATED → READY. 50-behavior end-to-end run #1: ALL PASS. Run #2 (exhaustion, supersede, caps, scoping, pagination): 30/30 PASS. Zero 500s. Killed via port-bound PID.
- Port 53319 (fresh process): unauth list 401, create retailer 201, create category 201, unknown route 404 envelope, clock set 200. Killed exact PID 3262698.
- Port 42101 (fresh process): verify 91 days after accepted_at → 409 ERR_IMPLEMENTATION_STALLED AND rec STALLED version 3 in the same failed request; re-verify → 409 ERR_ALREADY_TERMINAL. PASS. Killed exact PID.
- Numeric checks live: accrual waterfall (100000 @3% → 3000; split 60 → 1800/1200; cash 1656/1104), event estimate 1000 vs fund availability (422 then reserve/release), risk 23 HEALTHY → dispute cascade → 25 WATCH, short-paid settlement (min(5000,1200)=1200, short_paid true), gap-rule precedence (|85−100|/85=17.6% → ERR_CHANNEL_CONFLICT, never UNDERCUT), undercut floor ceil(100×0.9)=90 rejects 89, exactly-84-day launch separation passes.

### Constants grep
38/38 match PRD verbatim (clock default, rounds 6, growth [-20,50], FY 2026–2030, accrual (0,5], split floor 20, factor 0.92, depth 40, space ±30, stores 10000, SLA 90, gap 15, undercut 10, club 12, gaps 84/84, phases 4, dist sum 100, weights 0.40/0.30/0.20/0.10, bias 25×4, friction 5×20, posture 25/50/75, phase weights 1.0/0.25/0.0, pagination 10/1/100/0).

### Dead-check scan
39/39 catalog error ids raised at least once outside errors.py; 0 raised-but-uncatalogued; all 30 domain checks wired in their endpoint's module; recompute_open_reviews called from deduction resolve; recompute_launch called from phase patch and evaluate.

### Interpretations chosen (candidate over-guards reviewed)
1. Priorities 7 vs 8 disjoint: terminal → ERR_ALREADY_TERMINAL; non-terminal wrong state → ERR_INVALID_STATE (otherwise ALREADY_TERMINAL could never fire; §2.10 absorbing).
2. Review create gated on launch.status == LAUNCHED (ERR_INVALID_STATE; REVIEWED/DELISTED → ERR_ALREADY_TERMINAL). Rests on §3.9 "opens the PerformanceReview on a launched product". Sits at priority 7, before uniqueness (20) and timing (32).
3. No plan-state gate on analysis create or price-pack create — PRD/scaffold state none; only forecast/launch create (ACTIVATED), shelf-rec create (ACCEPTED/ACTIVATED), event lock (ACTIVATED) gated; event create gated non-terminal per §3.2's explicit ALREADY_TERMINAL sentence.
4. pack_code uniqueness NOT enforced — PRD says "unique within the plan" but the 39-error catalog has no duplicate-pack-code id and validations table omits it; no check invented.
5. Terminality applies to the action's target entity; child creates on terminal plans use their specific gates (ERR_PLAN_NOT_ACTIVATED), except event create (explicit ERR_ALREADY_TERMINAL).
6. created_at/updated_at stamped from logical clock with exactly 3 fractional digits (§2.5); other instants canonical. Required because friction windows compare deduction creation instants (§2.4).
7. Friction window uses deduction's logical-clock creation instant, closed interval both ends (§3.6/§3.9).
8. Version bumps on cascade-touched entities (fund on lock/cancel/resolve, launch on phase patch/evaluate, OPEN reviews on deduction cascade) per §2.5. Versions start at 1.
9. RetailerBuyer reads: detail/nested on another retailer's plan → 403 ERR_RETAILER_SCOPE_MISMATCH (priority 3, only when chain resolves); top-level lists auto-filter to own retailer's data (§2.1) rather than 403.
10. invoiced_sales_cents type-checked integer only — no range guard stated; none invented. Unknown query params ignored; unmatchable filter → empty list.
11. No-input action endpoints accept any/absent body (lenient); input-taking endpoints reject undeclared fields.
12. edlp_split_pct > 80 (any magnitude) → ERR_EVENT_SPLIT_TOO_LOW; < 0 or non-integer → ERR_VALIDATION. accrual_rate_pct outside (0,5] → ERR_VALIDATION (no dedicated id).

### Deliberately not implemented (PRD does not require)
No GET for retailers/categories (not in the 42-row table); no seeding/preloading; no persistence, no threading locks; no pack_code uniqueness / country_code format / name non-emptiness enforcement.

Orchestrator spot-check: 23 .py files + start.sh + requirements.txt present; py_compile clean on all; start.sh foreground with $PORT via app.py and guarded dependency install; sampled constants (0.92, clock default, 10000, 84, 90, 0.40, 0.25, 75, 15, 12) present in both PRD.md and implementation; test_suite/ and test_helpers/ mtimes predate Step 6 (isolation held).

## Step 7: 8-round parallel stability sweep — 2026-10-02T01:00Z

Ran 8 concurrent rounds of `prd-bench-local-run --isolation per-test-server` (111 tests each, per-test server restart). Result: **8/8 rounds CLEAN, 111/111 passed, 0 failed, 0 errors** on the first sweep — no fixes, no deletions required. All 8 results.{1..8}.json artifacts retained in workspace/implementation/ (~33.9 KB each). Per-round durations ~190 s. Diagnostic protocol STEPs 0-3 not engaged (empty failure union).

## Step 7: Run tests and iterate (long-lived subagent) — verbatim summary — 2026-10-02T01:01:57.910430709Z

(Note: the Step 7 subagent also appended its own abbreviated entry directly above; this is the verbatim hand-back per the orchestration contract.)

- **Iterations run:** 1 (clean 8-round parallel sweep, no fixes needed).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.
- **Final sweep evidence** (all from workspace/implementation/): results.1.json through results.8.json each passed=111/111, failed=0, errors=0. All 8 results.{1..8}.json files confirmed on disk (~33.9 KB each, written 2026-10-02 01:00). The diagnostic protocol (STEPs 0–3) was never engaged because the failure union across all 8 rounds was empty.

Orchestrator verification: independently parsed all 8 results files — passed=111, total=111, failed=0, errors=0 in every round (ALL_8_CLEAN: True).

## Step 8: Finalize PRD — SKIPPED — same timestamp

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD (subagent) — 2026-10-02T01:21:25.592872837Z

**Source vs output:** workspace/PRD.md 332 lines / 61,686 chars → workspace/PRD_COMPLETED.md 332 lines / 63,941 chars (char-delta +2,255; 12 hunks, all in-paragraph inserts/revisions, no lines added or removed, no new sections).

**Counts:** 14 ambiguity-pins (PRD edits, across 12 hunks) · 0 mismatch-revisions · 0 implementation fixes.

### Change bullets
1. §2.3 — insert — ambiguity — negative offset and non-integer limit/offset pinned as ERR_VALIDATION body-shape violations — validation.py:90-113
2. §2.5 — revise — ambiguity — version pinned as "set to 1 at creation" — storage.py:41
3. §2.5 — revise — ambiguity — created_at/updated_at pinned as stamped from the server's logical clock, not wall-clock — storage.py:39-50
4. §2.8 — revise — ambiguity — OCC pinned as exact-equality: any expected_plan_version mismatch rejects ERR_STALE_VERSION — shelf.py:64
5. §2.9 item 8 — insert — ambiguity (internal tension vs §2.10) — terminality pinned as pre-empting state fit: terminal entities always report ERR_ALREADY_TERMINAL — plans.py:167-170, shelf.py:157-160, reviews.py:142-143, pricepacks.py:107-110, deductions.py:93-94
6. §2.10 — insert — ambiguity — price-pack decisions added to the terminal-state enumeration (REJECTED, RETIRED) — constants.py:65, pricepacks.py:107-108
7. §3.1 — insert — ambiguity — country_code pinned as opaque string, no alpha-2 re-validation — reference.py:22
8. §3.1 — insert — ambiguity — activation parameter breaches other than split floor (accrual_rate_pct outside (0,5], edlp_split_pct below 0) pinned as ERR_VALIDATION 400 — plans.py:218-223 vs 232-233
9. §3.2 — insert — ambiguity — event start_date/end_date accepted as any ISO 8601 instant; "midnight UTC" is convention, no alignment check — events.py:37-38
10. §3.3 — insert — ambiguity — analysis submission pinned as not gated on plan lifecycle status — analyses.py:24-70
11. §3.4 — insert — ambiguity — verify payload body-shape pinned: implemented_store_count non-negative integer else ERR_VALIDATION — shelf.py:150-152
12. §3.4 — revise — ambiguity (internal tension vs §2.10) — pinned: PROPOSED → ERR_INVALID_STATE; terminal → ERR_ALREADY_TERMINAL — shelf.py:157-160
13. §3.5 — insert — ambiguity — launch_date accepted as any ISO 8601 instant, no alignment enforcement — launches.py:52
14. §3.6 — insert — ambiguity — invoiced_sales_cents pinned as integer with no positivity constraint; successful posting pinned as 201 returning updated fund with derived availabilities — funds.py:71, funds.py:78
15. §3.8 — revise — ambiguity — pack_code re-pinned as "unique within the plan by naming convention — the server performs no duplicate check"; proposals not gated on plan lifecycle — pricepacks.py:33-68
16. §5 — insert — ambiguity — framework rejections pinned: unmatched route → ERR_RESOURCE_NOT_FOUND (404), wrong method → ERR_METHOD_NOT_ALLOWED (405), unexpected fault → ERR_INTERNAL (500) — app.py:55-69

### Mismatch-policy adjudications (3 candidate mismatches; all adjudicated ambiguous → PRD-pin, none an impl bug)
- pack_code uniqueness (§3.8): "a pack_code unique within the plan" is a field descriptor, not a full rule sentence; §2.9's domain-rule inventory lists exactly four uniqueness rules (plans, reviews, claims, accrual periods) excluding pack_code, and §5 has no error id a duplicate could map to — enforcing would require inventing an error path. → ambiguous, pinned impl's reading.
- Verify-on-terminal error id (§3.4): §3.4 "anything else fails with ERR_INVALID_STATE" conflicts with §2.10's explicit terminal-absorbing rule (and §2.9 #8); impl honors the more specific structural rule. → internal tension = ambiguity, pinned §2.10's reading.
- Terminality vs state-fit ordering (§2.9 #7/#8): strict 7-before-8 would make #8 dead code and contradict §2.10; impl evaluates terminality first at every transition endpoint (verified across plans/events/analyses/shelf/launches/deductions/pricepacks/reviews). → ambiguity, pinned impl's reading.

### Per-module walk evidence
All 22 modules read in full; behaviors not listed in the change bullets verified already uniquely pinned by PRD. Highlights: calc.py (accrual waterfall rhu-per-period + EVENT remainder + 0.92 cash shadow; event estimate latest-containing-week selector + single end rounding; projections 1.0/0.25/0.0 rhu-2dp; bias mean closed-window empty→0; friction DISPUTED/WRITTEN_OFF + short-paid SETTLED in logical window; risk clamps + 0.40/0.30/0.20/0.10 + one final rhu + 75/50/25 posture); clock.py (default, PlatformAdmin-only, monotonic, equal passes); envelope.py (req_+24hex, 3-digit meta ts, has_more=(offset+len)<total); errors.py (39 ids match §5 one-for-one); storage.py (uuid4, version=1/touch+1, logical stamps, creation-sequence ordering, _-prefixed keys stripped); validation.py (absent body → {}, bools rejected as numbers, non-finite floats rejected); plans.py (create priority chain, negotiate mover mapping + round-6 error+EXPIRED coupling, activate chain + zeroed fund + committed_growth_pct snapshot); events.py (half-open overlap per plan+type among PENCILED/LOCKED, lock order state→ACTIVATED→estimate→funds, reservation add/release with fund version bumps); analyses.py (share [0,100], governance 422, competitor_share=100−share, decide both terminal); shelf.py (guard order shape→existence→OCC→plan-status→accepted-analysis, incumbent WITHDRAWN + plan version +1, verify 3-check order with inseparable STALLED coupling, no-op INCOMPLETE); launches.py (ACTIVATED gate, UTC-year fiscal fit, strict-84-day separation with equality passing, 4 auto PENDING phases, execute gates(409)→date(422)); phases.py (phase_index asc, patch PENDING/GATE_FAILED-on-PLANNING else ERR_PHASE_LOCKED, post-write caps, GATE_FAILED→PENDING loop, evaluate pass rule, projection recompute with version bumps); funds.py (all-role reads RB-scoped, YYYY-MM regex, duplicate period 409); deductions.py (claim unique-per-fund 409, amount>0, resolve legality matrix, min(amount, availability) settlement with short_paid/absorbed flags, write-off into settled ledger, 3-hop cascade into OPEN reviews); forecasts.py (Monday-midnight 422, supersession preserves commit_status, commit requires PUBLISHED∧UNCOMMITTED else 409); pricepacks.py (channel alphabet + retailer-membership, CLUB ≥ 12 → 422, ceil per-unit, conflict pair pinned order pairwise-gap-then-undercut-floor, RETIRED cascade targets); reviews.py (window/target/dist validations, LAUNCHED→uniqueness(409)→timing(422) gates, creation-time computation of all five metrics, finalize CONTINUE→REVIEWED / DELIST→DELISTED + pack-family RETIRE cascade with version bumps).

**Impl edits:** none — no py_compile or boot smoke required; workspace/implementation/ byte-untouched.

Orchestrator verification: PRD_COMPLETED.md exists at 63,941 chars (+2,255 exactly as claimed) and differs from PRD.md (not a mid-flight no-op); zero implementation/ source files newer than results.1.json (Step 9 made no impl edits — the Step 7 sweep remains the valid final evidence, no re-run needed); pin spot-checks ("set to 1 at creation", req_) present in PRD_COMPLETED.md.

## Pipeline complete — same timestamp

Final tree: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (13 entities, 42 endpoints, 10 state machines, 34 validations, 5 calcs, 39 errors, 6 roles, 1 OCC rule; 18 difficulty + 84 corner instances) · test_helpers/ (9 modules + conftest) · test_suite/ (111 tests, 93 unique Design tags == 93 non-stub index instances exactly) · workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md} (no PRD_FINALIZED.md — Step 8 skipped on clean Step 7) · workspace/implementation/ (23 Flask modules + start.sh + results.1..8.json all 111/111).
