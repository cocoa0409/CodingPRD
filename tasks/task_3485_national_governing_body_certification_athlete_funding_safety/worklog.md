# Worklog — task_3485_national_governing_body_certification_athlete_funding_safety

## Step 1: Create Task Directory — 2026-10-02T15:25:00.000Z

Task directory pre-allocated by the caller: `tasks/task_3485_national_governing_body_certification_athlete_funding_safety/` with empty `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created. Scenario: National Governing Body Certification, Athlete Funding & Safety Compliance (USOPC). Difficulty instruction: "much harder than expert level" (applies to scaffold generation only).

## Step 2: Generate Scaffold — 2026-10-02T15:47:00.000Z

All three scaffold artifacts are generated, verified, and lint-clean. Summary:

## Files written
| File | Lines | Parse |
|---|---|---|
| `SCAFFOLD.yaml` | 1512 | OK (keys: scenario…roles; no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2179 | OK (single key `scaffold_difficulty_design`) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2544 | OK (single key `scaffold_corner_design`) |

**scaffold_lint.py verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (949 calls scanned, 0 violations)

## Counts
- **Endpoints: 40** (exactly at cap) · **Entities: 11** · **State machines: 11** · **Calculations: 9** · **Validations: 28** (priority-ordered) · **Error catalog: 27** · **Roles: 7** · **OCC concurrency rules: 2**
- **§1.8: 18 instances, 0 stubs** (all 9 rules × 2, each with fully structured replayable chains)
- **§1.9: 45 instances = 42 active + 3 excluded stubs** (8 taxonomy sections)

## Design decisions downstream steps must know
- **api_prefix: `/api`** for all business endpoints; **`POST /_clock/set_current_utc` is deliberately unprefixed** (platform/test-driving endpoint). Logical clock default is fixed at **`2026-09-01T00:00:00Z`**, never wall-clock; clock-set applies documented auto-transitions (screening expiry, deal expiry, remediation-deadline cycle failure, posture window re-evaluation).
- **Parallel state dimensions** on Athlete (eligibility × screening × training), FundingAgreement (status × insurance), SelectionProcedure (proc × trials) — one transitions endpoint per entity, `to_state` values are disjoint across dimensions so the server infers the dimension.
- **Embedded collections** instead of child entities: trials entries live in `SelectionProcedure.entries`, roster slots in `Roster.slots`; slot accept/decline is a `NOMINATED→NOMINATED` self-loop on `POST /api/rosters/{id}/transitions` with `slot_decisions`.
- **Two OCC rules** (`expected_roster_version` on nominations — including the NOMINATED→NOMINATED selector re-run self-loop added after replay showed the naive design deadlocked the OCC corner test; `expected_deal_version` on all deal transitions).
- **Segregation of duties** with opaque literal user ids: cycle issuer≠closer, complaint triager≠resolver, result submitter≠verifier.
- **`declined_athlete_ids` persists across appeal reverts** (slots are cleared on UPHELD; decliners stay excluded on re-nomination) — added after end-state replay caught the exclusion marker being erased.
- **Every constant is valued at its single definition** in §1.3/§1.4 (e.g., tier thresholds 100/60/30, stipends 300000/200000/100000, appeal window 72h inclusive, publish lead 90d, registration close 14d, posture threshold 3/365d, quota bonus 250→+1 slot, share pcts 30/40/30 with athlete-absorbs-remainder rounding, science caps 40/25/10, screening 730d, training 365d). §1.8/§1.9 reuse those literals; every formula-derived assert literal was independently recomputed in Python (e.g., trailing 128.25 vs season 60.0; compliance 71.5→74.0; NET split 270000/360000/269999; waterfall 40/25/15/0 of pool 80; tie at 78.0 broken by trials score).
- **Interval semantics deliberately split for Rule 8:** certification cycles half-open (adjacency allowed) vs deal exclusivity closed with mandatory 1-day gap (touching rejected).
- Two incidental issues found and fixed during authoring: bare `?`-suffixed flow tokens and `$.data[0]` JSONPaths need YAML quoting; `ERR_APPEAL_WINDOW_EXPIRED` initially existed in validations but not the catalog (added; catalog now 27).

Orchestrator verification: all three files exist on disk with the reported line counts, all three parse clean under yaml.safe_load with the reported top-level keys, and SCAFFOLD.yaml carries 429 domain-term matches (athlete/governing/certification/roster/safe-sport/stipend) plus the `/api` prefix and unprefixed `/_clock/set_current_utc` — confirmed authentic to the USOPC scenario.

## Step 3: Copy Shared Files — 2026-10-02T16:46:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T17:05:00.000Z

PRD generation complete and verified.

## Summary

**Output:** `workspace/PRD.md` — 316 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (7 roles, entity-backed identity prose for NGBAdmin/Athlete, opaque for the other five, interim-management submission restriction), 2.2 API Response Structure (verbatim block, byte-identical against `section-2.2-response-structure.md`), 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, created_at ascending), 2.4 Common Resource Properties, 2.5 Logical Clock, 2.6 Validation Pipeline (10-tier precedence ladder, first-failure-wins), 2.7 OCC (both rules), 2.8 Precision/Rounding, 2.9 Cascading Consistency, 2.10 Nested Resource Resolution
- §3 Business Logic: 3.1 Certification Cycles, 3.2 Complaints/Posture/Decertification, 3.3 Athletes/Safe Sport, 3.4 Results/Points, 3.5 Funding/Insurance/Science Hours, 3.6 Selection/Rosters/Appeals, 3.7 Commercial Deals
- §4 Endpoint Definitions (40 rows, 4 columns), §5 Error Code Catalogue (27 rows, 2 columns)

**Exit checklist:**
- (a) **All 27 error_ids verbatim** — programmatically confirmed present, and each §5 row's HTTP status matches the scaffold (401/403/404/400/409/412/422 correctly paired).
- (b) **All constants with literal values** — confirmed: score weights 0.40/0.35/0.25, thresholds 70/85, remediation bonus 10, cycle cap 120 days, placing ladder 40/32/26/20/16/12/8/4, grade multipliers 1.5/1.25/1.0, recency 180 days at full / 181–365 at 0.5, trailing window 365, tiers 100/60/30 with stipends 300000/200000/100000 cents, insurance 60 points + 30 days, composite weights 0.7/0.3, 2 alternates, quota bonus 250 → +1 slot, revenue split 30%/40% + athlete remainder with 10% agency fee on NET_BASIS, science caps 40/25/10, posture 3-in-365, screening 730 days, publish lead 90 days, registration close 14 days, appeal window 72 hours inclusive, deal exclusivity gap 1 day (closed interval).
- (c) **Unprefixed clock endpoint** — `POST /_clock/set_current_utc` explicitly documented in §2.5 as living outside `/api`, startup default exactly `2026-09-01T00:00:00Z`, never falls back to wall-clock, `to_iso8601` input, `{ "current_utc": string }` response, and all four auto-transitions enumerated (screening expiry, deal expiry, REMEDIATION → CLOSED_FAILED past 120 days, posture re-evaluation); appears 3 times in the doc.
- (d) **Chunked-write verification** — 1 Write + 8 quoted-heredoc appends, each followed by `wc -l` + `tail -3`: growth 98 → 134 → 162 → 189 → 203 → 225 → 262 → 316 lines, no stalls.

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 100 required (entity fields + endpoint inputs + query/path params), 100 present, 0 missing — **PASS** (one gap, `roster_id`, found and repaired; re-ran to empty diff). Note: a naive backtick-regex false-failed on the §2.2 fenced JSON blocks; verification strips code fences before tokenizing.
- Contract 2 (Rule Coverage): all six high-risk categories walked — priority ladder stated as explicit ordering, both OCC rules named with endpoint/field/error/status in stale-read framing, all cascade chains (decertification, abuse 4-link, retirement, suspension/reinstatement, cycle-close, roster-confirm, appeal-upheld) spelled out, applies_to sets enumerated, field defaults/nullability/computed content placed, sibling branches symmetric (UPHELD/DENIED, SUBSTANTIATED/DISMISSED, both adjudicated outcomes) — **PASS**.
- Contract 3 (§3 Path Purity): 680 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos — **PASS**.

Orchestrator verification: PRD.md exists at 316 lines; 59 `ERR_` mentions; unprefixed `POST /_clock/set_current_utc` documented in both §2.5 prose and the §4 endpoint table; startup default `2026-09-01T00:00:00Z` present; 95 domain-term matches (athlete/governing body/certification/roster/stipend).

## Step 5a: Generate Test Helpers (frozen) — 2026-10-02T17:35:00.000Z

Stage 1 (test helpers + conftest) is complete for task_3485. **No `test_suite/test_*.py` files were written** — scope respected.

## Files written (10 files, 2758 lines)

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 410 | 24 enums + 13 TypedDicts (11 entities + TrialsEntry/RosterSlot embeds), all carrying full common fields per PRD §2.4 |
| `test_helpers/constants.py` | 215 | All PRD literals + round-half-up/formula helpers |
| `test_helpers/api_errors.py` | 72 | 27 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map` |
| `test_helpers/test_users.py` | 109 | Distinct opaque ids per SoD half + entity-backed builders |
| `test_helpers/api_client.py` | 316 | 40 endpoint methods (39 `/api` + unprefixed clock) |
| `test_helpers/assertions.py` | 359 | 11 entity assertions + invariant checkers (allocation bounds, decline conservation, deal-share conservation, pagination meta) |
| `test_helpers/factories.py` | 195 | 10 create factories + 6 transition-payload builders, defaults PRD-legal at the startup clock |
| `test_helpers/fixtures.py` | 903 | 85 helpers across all 5 tiers (state progression, hierarchy, lifecycle, threshold targeting, terminal states) |
| `test_helpers/__init__.py` | 54 | Barrel export |
| `test_suite/conftest.py` | 125 | `api` session fixture, 14 role-header fixtures, builder fixtures, autouse clock-tracker reset |

## Verification
- `py_compile` on every file: ALL_COMPILE_OK
- Import-graph check (`import test_helpers.api_client, .assertions, .factories, .fixtures, .constants, .test_users`): OK; 40 client methods present; error map registered (27 ids, `ERR_STALE_VERSION`→412); importlib submodule resolution verified against the singleton-shadowing trap
- `pytest --collect-only test_suite/`: imports clean, no tests (expected)
- Constants sanity-checked against the design index's worked values: `weighted_compliance(80,70,60)==71.5`, `remediation_final_score(80,70,60)==74.0`, composites 96.5/87.0/81.7/66.8, `revenue_shares(999999,'NET_BASIS')==(270000,360000,269999)` (athlete absorbs remainder)

## Constants table (name → value, all grep-confirmed in PRD.md)
`SCORE_WEIGHT_GOVERNANCE/ATHLETE_REP/FINANCIAL` 0.40/0.35/0.25 · `COMPLIANCE_PASS_THRESHOLD` 70 · `COMPLIANCE_EXCELLENT_THRESHOLD` 85 · `REMEDIATION_BONUS_CAP` 10 · `CYCLE_MAX_DURATION_DAYS` 120 · `PLACING_POINTS` {1:40,2:32,3:26,4:20,5:16,6:12,7:8,8:4} · `EVENT_MULTIPLIER` A=1.5/B=1.25/C=1.0 · `RECENCY_FULL_DAYS` 180, `RECENCY_HALF_WEIGHT` 0.5, `TRAILING_WINDOW_DAYS` 365 · tiers 100/60/30 → stipends 300000/200000/100000 cents · `INSURANCE_MIN_POINTS` 60, `INSURANCE_WAIT_DAYS` 30 · `COMPOSITE_TRIALS_WEIGHT` 0.7/`COMPOSITE_SEASON_WEIGHT` 0.3, `ALTERNATE_COUNT` 2 · `QUOTA_BONUS_THRESHOLD` 250 → `QUOTA_BONUS_SLOTS` 1 · shares 0.30/0.40 + athlete remainder, `AGENCY_FEE_PCT` 0.10 on NET_BASIS · science caps 40/25/10 · posture 3 in 365 days · `SCREENING_VALIDITY_DAYS` 730 · `TRAINING_VALIDITY_DAYS` 365 · `MIN_PUBLISH_LEAD_DAYS` 90 · `REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS` 14 · `APPEAL_WINDOW_HOURS` 72 (inclusive) · `DEAL_EXCLUSIVITY_MIN_GAP_DAYS` 1 (closed interval) · `CLOCK_STARTUP_DEFAULT` "2026-09-01T00:00:00Z" · pagination 10/1/100/0. No dead duplicates.

## Role/id model
7 roles per PRD §2.1. Entity-backed: `make_ngb_admin_headers(body_id)`, `make_athlete_headers(athlete_id)` — mandatory builders, used by every ownership-gated fixture (procedures/rosters/entries under `make_ngb_admin_headers(gb_id)`; results/appeals/slot-decisions/consent/retirement under `make_athlete_headers(athlete_id)`). Opaque five carry stable distinct literal ids; segregated pairs never share one: `AUDITOR_ISSUER_ID="auditor-issuer-1"` vs `AUDITOR_CLOSER_ID="auditor-closer-2"` (cycle issue/close, complaint triage/resolve), `RESULTS_OFFICIAL_ID` vs athlete UUIDs (submit/verify). `INTERIM_MANAGER_ID` + `setup_interim_manager_headers()` cover the interim-managed roster-submission path.

## Clock helper
`set_clock(client, to_iso8601, headers) -> Response` in `api_client.py`, hitting the bare `/_clock/set_current_utc` path (grep-verified unprefixed). Fixtures layer `set_logical_clock(iso, api=None) -> str` on top with envelope-tolerant `current_utc` extraction, plus `iso_plus_days/hours/seconds`, `parse_iso/format_iso`, and a `current_clock()` tracker reset per test by conftest (server restarts per test). Time-sensitive fixtures (`hold_trials`, `finalize_results`, `setup_active_agreement`, `setup_enrolled_agreement`, `setup_nominated_roster`, `setup_probation_body`) set the clock BEFORE the dependent write, matching the design recipes' clock choreography (e.g., insurance enrolled at exactly activated_at+30d, nominations stamped at 2026-12-20 for the 72h appeal window).

One adjudication note for Stage 2: the PRD is ambiguous on whether the clock endpoint's 200 response is enveloped (§2.2 says all 2xx responses use the envelope; §2.5 says the body is `{ "current_utc": string }`) — `set_logical_clock` deliberately accepts both shapes rather than pinning one.

Orchestrator verification: all 10 files present; py_compile clean on every file; import graph resolves (`IMPORT_OK`); api_client.py lines 5/17-19 confirm `/_clock/set_current_utc` uses the bare path; no test_*.py files exist yet. Queue sizes measured by orchestrator directly from the YAMLs: Queue A (difficulty) = 18 active (9 rules × 2, 0 stubs); Queue B (corner) = 42 active + 3 excluded_because stubs (calculations/trailing_day_365_included_boundary, calculations/recency_half_weight_decays, validations/priority_ordering_state_beats_safety). Grand total 60.

## Step 5b: Generate Difficulty-Queue Tests (queue A) — 2026-10-02T18:05:00.000Z

All done. Collection is clean: exactly 18 tests, zero errors.

## Summary

**Files written (9, one per difficulty rule, 2 tests each = 18 tests):**

| File | Tests | Design tags |
|---|---|---|
| `test_difficulty_dual_variant_calc.py` | 2 | `certification_provisional_vs_final_score`, `funding_trailing_vs_season_points` |
| `test_difficulty_combinatorial_formula.py` | 2 | `commercial_split_rounding_order`, `quota_bonus_evaluation_order` |
| `test_difficulty_non_linear_state_machine.py` | 2 | `athlete_parallel_dimensions_suspend_reinstate_loop`, `roster_nominated_draft_renomination_loop` |
| `test_difficulty_transitive_cascade.py` | 2 | `abuse_substantiation_cascade_depth4`, `decertification_cascade_procedure_roster_appeals` |
| `test_difficulty_priority_pair_validation_conflict.py` | 2 | `state_before_safety_on_trials_entry`, `temporal_before_referential_on_appeal` |
| `test_difficulty_boundary_precision_check.py` | 2 | `insurance_points_and_wait_boundaries`, `appeal_window_boundary_72h` |
| `test_difficulty_cross_entity_state_dependency.py` | 2 | `roster_submission_gated_by_body_status`, `trials_entry_gated_by_athlete_eligibility` |
| `test_difficulty_resource_temporal_overlap.py` | 2 | `certification_cycle_half_open_adjacency`, `deal_exclusivity_closed_interval_gap` |
| `test_difficulty_compensating_invariant.py` | 2 | `roster_slot_decline_promotion_conservation`, `stipend_suspend_resume_conservation` |

**Instances skipped: none.** All 18 queue-A instances passed the PRD-first two-condition filter (41 verbatim citation substrings grep-verified against PRD.md).

**Key adjudications:**
- Two orchestrator-listed names were truncations; tags use the verbatim YAML names (`..._suspend_reinstate_loop`, `..._roster_appeals`), confirmed by an AST audit resolving every tag against the source index (exactly one tag per test, tag is the docstring's last line).
- `abuse_substantiation_cascade_depth4`'s literal call order is clock-unreachable: insurance enrollment at activated_at+30d pushes the clock to 2026-10-31, where procedure publish would violate the 90-day lead against trials_start 2026-12-15. Reordered setup (selection chain first at the default clock, then the funding/insurance chain at the 2026-12-20 nomination clock, enrolling at 2027-01-19 = activated_at+30d). Every recipe literal survives the reorder: A's 2026-08-01 result is 141 days old at creation (full weight → 60.00/TIER_B/200000) and 171 days at enrollment (still full weight → ≥60 gate holds under either stored or recomputed reading); composites stay 82.4/65.6.
- `test_roster_submission_gated_by_body_status` asserts `submitted_by_user_id == COMMITTEE_ADMIN_ID` per the PRD's "The submitter is recorded as `submitted_by_user_id`".
- Timestamps compared via `parse_iso` (instant equality) rather than string equality to avoid pinning the Z-vs-offset serialization format the PRD leaves open.
- All creates validated with explicit 201 via the frozen helpers; error paths use direct client calls + `validate_error` against the registered status map; OCC versions threaded through fresh roster/deal reads.

**Collection tail:** `18 tests collected in 0.33s`, no errors.

Orchestrator verification: `pytest --collect-only -q` → 18 tests collected, 0 errors; 9 test_difficulty_*.py files; exactly 18 `Design: Difficulty/` docstring tags.

## Step 5c: Generate Corner-Queue Tests, Wave 1 — 2026-10-02T18:25:00.000Z

All probes pass ("recomputation" was a filler probe, not a citation — every actual quoted sentence greps verbatim in PRD.md). Work complete.

## Summary

**Files written** (all under `test_suite/`), each `py_compile`-clean before the next was started:

| File | Tests | Design tags emitted |
|---|---|---|
| `test_corner_entities.py` | 7 | `entities/create_governing_body_success`, `entities/governing_body_not_found_returns_404`, `entities/athlete_creation_defaults_applied`, `entities/create_athlete_missing_required_field`, `entities/athlete_creation_with_unknown_body_returns_not_found`, `entities/list_athletes_filter_and_pagination`, `entities/create_result_with_system_fields_input_ignored` |
| `test_corner_state_machines.py` | 7 | `state_machines/complaint_initial_state_filed`, `state_machines/complaint_resolve_from_filed_rejected`, `state_machines/decertified_body_terminal_lockdown`, `state_machines/cycle_remediation_reissue_loop`, `state_machines/result_resubmission_loop`, `state_machines/funding_terminated_lockdown`, `state_machines/screening_auto_expiry_on_clock` |
| `test_corner_calculations.py` | 4 | `calculations/placing_points_constants_applied`, `calculations/funding_points_input_set_filtering`, `calculations/science_hours_waterfall_partial_fill`, `calculations/composite_tiebreak_higher_trials_wins` |
| `test_corner_endpoints.py` | 2 | `endpoints/results_finalization_atomic`, `endpoints/response_envelope_shape` |
| `test_corner_consistency_model.py` | 1 | `consistency_model/immediate_consistency_create_read` |

**New tests added: 21** (exactly the 21 wave-1 non-stub instances; the two `excluded_because` calculations stubs were not translated). **Total collected: 39** (18 pre-existing difficulty + 21 corner), zero collection errors. Queue A files untouched; no wave-2 sections (validations/rbac/cross_cutting) written.

**Skipped instances: none.** Every wave-1 instance passed the PRD-first two-condition filter — verbatim rule-bearing PRD sentences exist for each (§2.2 envelope, §2.3 pagination, §2.4 system fields, §2.5 auto-transitions, §2.6 validation tiers, §2.10 FK existence, §3.1–§3.6 business rules), and a 27-probe verbatim grep against `PRD.md` confirmed every quoted citation survives literally.

**Design-tag audit:** AST walk confirms each of the 21 tests has exactly one `Design: Corner/<section>/<name>` line as the final docstring line, and every tag resolves to a real instance in `SCAFFOLD_CORNER_DESIGN.yaml`.

**Key construction choices:** all setup uses frozen helpers only (`setup_certified_body`, `setup_eligible_athlete`, `add_verified_result(s)`, `setup_procedure_with_entries`, `hold_trials`, `run_nominations`, etc.); entity-backed calls thread real ids (`make_athlete_headers(athlete["id"])`, `make_ngb_admin_headers(body["id"])`); SoD pairs use distinct ids (issuer `auditor-issuer-1` / closer `auditor-closer-2` via fixture defaults); creates pass explicit `201` to `validate_success`; clock advances via `set_logical_clock` before time-sensitive writes; every test builds its full precondition chain from scratch for per-test-server isolation. Literal expected values copied from the design index (32.5, 60.0/TIER_B, waterfall 40/25/15/0 → 80, composites 78.0/78.0 with trials tie-break 90>87) with `pytest.approx` for decimals.

**Collect-only tail:** `39 tests collected in 0.30s` (full `pytest test_suite/ --collect-only -q`, no errors).

Orchestrator verification: `pytest --collect-only -q` → 39 tests collected, 0 errors; exactly 21 `Design: Corner/` tags across the 5 new files.

## Step 5d: Generate Corner-Queue Tests, Wave 2 — 2026-10-02T18:45:00.000Z

Queue B wave 2 complete. All 21 target instances translated, 60 total collected, zero errors.

## Files written (3, each py_compile-clean before the next started)

| File | Tests | Design tags |
|---|---|---|
| `test_corner_validations.py` | 11 | `validations/score_out_of_range_rejected`, `cycle_window_end_not_after_start`, `publish_lead_time_short`, `registration_closed_after_deadline`, `funding_budget_exceeded_on_activation`, `deal_activation_requires_consent`, `nomination_before_results_final`, `pending_appeals_block_submit`, `pending_slot_decisions_block_submit`, `duplicate_entry_rejected`, `agreement_window_overlap_rejected` |
| `test_corner_rbac.py` | 5 | `rbac/athlete_cannot_transition_governing_body`, `ngbadmin_cannot_touch_other_body`, `sod_cycle_issuer_cannot_close`, `sod_complaint_triager_cannot_resolve`, `athlete_cannot_verify_own_result` |
| `test_corner_cross_cutting_complexity_layers.py` | 5 | `cross_cutting_complexity_layers/occ_nomination_stale_roster_version`, `occ_deal_transition_stale_version`, `complaint_posture_threshold_trigger`, `derived_points_recomputed_on_verify`, `selector_excludes_declined_on_retry` |

**New tests: 21 (exactly the wave-2 list). Total collected: 60 (39 pre-existing + 21), zero collection errors.** Queue-A and wave-1 files untouched. The excluded stub `validations/priority_ordering_state_beats_safety` was not translated.

## Audits
- **Design-tag AST audit: PASS** — each of the 21 tests has exactly one `Design: Corner/<section>/<name>` line as the final docstring line, and every tag resolves to a real instance in `SCAFFOLD_CORNER_DESIGN.yaml`.
- **Verbatim-citation grep: PASS** — 34 distinctive ≥8-word probes (one per quoted PRD sentence) all survive literal (whitespace-normalized) match against `PRD.md`.
- Collect-only tail: `60 tests collected in 0.28s`.

## Skips
None.

## Adjudication requiring orchestrator attention (1)
**`rbac/athlete_cannot_verify_own_result`** — the corner instance asserts `ERR_UNAUTHORIZED`, but the PRD uniquely derives a different error for this exact scenario. PRD §3.4 states verbatim: *"A `ResultsOfficial` then verifies or rejects it — never the same person as the submitting athlete, with a self-verification rejected as `ERR_SEGREGATION_OF_DUTIES`"*, and PRD §2.1 defines `ERR_UNAUTHORIZED` at endpoint role-list granularity (Athlete IS on the `POST /api/results/{id}/transitions` list per §4). The scaffold's own validations table (priority 7: "result submitter != verifier" → `ERR_SEGREGATION_OF_DUTIES`, applies_to the results transitions endpoint) agrees with the PRD. The test asserts the PRD-derived outcome (403 `ERR_SEGREGATION_OF_DUTIES` + result stays SUBMITTED with `base_points` null), tagged to the instance. If the implementation instead returns `ERR_UNAUTHORIZED` here, treat it as an impl bug against §3.4 at Step 9, not a test bug — the corner-design instance's `error_id` is the outlier.

## Construction notes
- Every test builds its full chain from scratch (per-test-server isolation) using only frozen helpers: `setup_certified_body`, `setup_eligible_athlete`, `add_verified_result(s)`, `setup_procedure_with_entries`, `setup_finalized_procedure`, `setup_nominated_roster`, `setup_active_agreement`, `hold_trials`, `answer_slot`, `file_appeal`, etc.; error triggers call `api.<method>` directly + `validate_error` against the registered status map.
- Clock choreography via `set_logical_clock` before time-sensitive writes (post-deadline entry at 2026-12-02, nominations at 2026-12-20, complaint resolutions at 2026-09-10/20/30, agreement creation at 2026-10-01).
- Entity-backed headers thread real ids (`make_ngb_admin_headers(body["id"])`, `make_athlete_headers(athlete["id"])`); SoD pairs use distinct opaque ids (`AUDITOR_ISSUER_ID` vs `AUDITOR_CLOSER_ID`); creates pass explicit 201 to `validate_success`.
- OCC tests read versions from responses, mutate through a competing transition, replay stale expecting 412 `ERR_STALE_VERSION`, then succeed with the fresh version (roster 1→2→3; deal consent v1→v2, stale terminate 412, fresh terminate 200).
- Literal expectations copied from the design recipes and cross-checked against PRD formulas: 120.00 pts → TIER_A/300000 with budget 3600000 (equality allowed, then 7200000 > budget), 60.0 → TIER_B/200000 on the verify cascade, posture count 2 → NORMAL/CERTIFIED then 3 → ELEVATED/PROBATION, selector composites 75.0/71.5 with the declined athlete (78.5) absent after the UPHELD revert.

## Orchestrator AST tag audit (run independently after wave 2)
60 test functions across 17 test files; 60 valid active instance tags measured from the two YAMLs (18 Difficulty + 42 Corner); every test has exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance; every active instance is covered exactly once; 0 uncovered, 0 duplicates, 0 unresolved. **VERDICT: CLEAN.** Total suite: 60 tests = 18 difficulty + 42 corner.

## Step 6: Generate Implementation — 2026-10-02T19:35:00.000Z

NOTE: the first Step 6 subagent died on an API timeout after 4 read-only calls (no artifacts written — verified implementation/ did not exist). Resumed the same agent via SendMessage; it completed from its intact context. ISOLATION RULE and PROCESS SAFETY were in force throughout; the subagent never saw the design indices or the test tree.

The implementation is complete and verified. Final summary:

## Files delivered (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded pip install, `exec python3 app.py`, PORT/0.0.0.0, foreground |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 58 | blueprint registration, ApiError/404/405/500 envelope handlers, per-request mark reset |
| `constants.py` | 103 | every named constant, defined once |
| `errors.py` | 76 | ApiError + all 27 error IDs with exact HTTP statuses |
| `db.py` | 98 | in-memory stores, common fields, per-request version-bump dedupe |
| `timeutil.py` | 82 | logical clock (default `2026-09-01T00:00:00Z`), ISO8601 parse/format |
| `envelope.py` | 102 | `meta`/`response_type`/`data` envelope, pagination (limit/offset/total_count/has_more) |
| `validate.py` | 139 | tier-1 auth, role/ownership checks, typed body validators |
| `calc.py` | 314 | all 9 calculations (Decimal, round-half-up) |
| `cascades.py` | 299 | all cascade links + clock-driven auto-transitions |
| `routes_clock.py` | 23 | unprefixed `POST /_clock/set_current_utc` |
| `routes_gb.py` | 404 | governing bodies, certification cycles, complaints |
| `routes_athletes.py` | 280 | athletes (parallel dims), performance results |
| `routes_funding.py` | 178 | funding agreements + insurance dimension |
| `routes_safety.py` | 87 | abuse reports + adjudication cascade |
| `routes_selection.py` | 249 | procedures, trials entries, atomic results finalization |
| `routes_rosters.py` | 232 | rosters, OCC nominations, slot decisions/promotion, submit/confirm |
| `routes_appeals.py` | 138 | appeals with 72h window and UPHELD revert |
| `routes_commercial.py` | 159 | deals with OCC, pinned revenue split, exclusivity gap rule |

All 40 endpoints implemented. **py_compile: all 18 modules pass. Constant check: CLEAN** (AST scan — every ALL_CAPS/ERR_* name defined exactly once; all local imports resolve).

## Smoke tests (all servers on dynamic ports, killed by saved PID only)

- **Suite 1 (curl slice): 25/25 PASS** — GB 201, athlete 201, unprefixed clock 200 raw `{"current_utc":...}`, `/api/_clock` → 404 envelope, result 201, verify 200 (`base_points` 48.0), self-verify 403 ERR_SEGREGATION_OF_DUTIES, envelope shape, 401/404 envelopes, screening→training→ELIGIBLE, agreement 201 TIER_C, activate 200, committed 100000, pagination meta.
- **Suite 2 (deep selection): 78/78 PASS** — cycle fast-path, publish/lock/entries/held/finalize gates, duplicate entry 409, stale nomination 412, composite ranking, appeal window + UPHELD revert (slots cleared, `nominated_at` not refreshed), decline→promotion invariant, pending-appeals/slots 409s, submit→confirm→procedure COMPLETED, deal OCC 412, consent-required 409, pinned split (30000/40000/30001 on 100001 gross), 1-day-gap deal allowed, auto-expiry, CRITICAL→INTERIM_MANAGED, decertification cascade, terminal 409.
- **Suite 3 (funding/safety): 58/58 PASS** — remediation bonus (80/80/80 → financial wins tie → final 82.5), budget-exceeded 422, agreement overlap 409, insurance wait/points gates + re-enroll from LAPSED, waterfall caps, abuse cascade (flag→suspend→stipend reversal→insurance lapse→science zeroed), screening-shortcut reinstatement restoring ACTIVE + stipend exactly, reassess-to-NONE suspension, screening auto-expiry on read, posture cascade (3rd substantiation → ELEVATED + PROBATION), remediation auto-CLOSED_FAILED past 120d, NGBAdmin/Athlete ownership 403s, limit>100 → 400.
- **Reboot check**: fresh `start.sh` boot → previously created entity returns 404 (state fully wiped); start.sh idempotent.

## Interpretations chosen where PRD admitted multiple readings (audit candidates)

1. **Clock endpoint returns raw `{"current_utc": ...}`** (no envelope) — §2.5's explicit "the response body is { current_utc: string }" read as overriding §2.2 for this platform endpoint; its errors still use the standard envelope.
2. **`created_at`/`updated_at` use wall clock; domain timestamps use the logical clock** — scaffold marks only domain fields "logical-clock"; wall clock also keeps `created_at` tie-breaks distinct (final tie-break: creation sequence, never `id`).
3. **Unknown `to_state` → 400 ERR_INVALID_REQUEST** (unknown enum member); known-but-illegal → 409 ERR_INVALID_STATE; terminal → 409 ERR_ALREADY_TERMINAL before body parsing.
4. **Per-transition actor restrictions → 403 ERR_UNAUTHORIZED** (e.g. Athlete sending SUBMITTED, CommitteeAdmin sending CONSENT_GRANTED).
5. **Ownership ordering**: endpoint role-list before existence; ownership compares X-User-ID to the path id directly when it is the owner key (403 before 404); deeper resources resolve chain first.
6. **Single-resource reads are ownership-gated** for NGBAdmin/Athlete (§2.1 "cross-body/cross-athlete access is denied"); top-level lists are not; abuse-report *filing* is not ownership-gated (reporter_role distinguishes), the *list* is (subject athlete).
7. **Result verification recomputes points + tier + stipend** (tier_assignment trigger includes "verify") and reconciles the body's committed total delta on ACTIVE agreements + waterfall, preserving the declared computed-sum invariant; verify never changes agreement status.
8. **Insurance uses the agreement's stored operative points**; `activated_at` stamped only on OFFERED→ACTIVE, not on resume.
9. **Slot decisions accept NOMINATED *and* PROMOTED slots** — the submission gate counts both as awaiting decision, so the literal "NOMINATED only" precondition would deadlock rosters after a decline-with-promotion. Alternate declines don't promote; unpromotable declined PRIMARYs collapse to REMOVED; promoted alternates take the vacated rank.
10. **Cascade slot removal touches only NOMINATED/SUBMITTED rosters** (not CONFIRMED/CANCELLED); abuse promotes, retirement doesn't.
11. **Appeal filing requires roster NOMINATED or SUBMITTED** (else 409); UPHELD reverts from either to DRAFT (scaffold names only NOMINATED→DRAFT; SUBMITTED gap filled identically).
12. **Precondition failures without a catalog error_id → 409 ERR_INVALID_STATE** (decertification evidence, OPEN/HELD/RESULTS_FINALIZED timing, body-standing gates, tier-NONE activation, consent-while-RETIRED, duplicate non-terminal roster, roster on terminal procedure).
13. **Procedure create-time guards**: reversed trials window → 422 ERR_CYCLE_WINDOW_INVALID; registration_deadline <14d before trials_start → 400; quota_slots <1 → 400; publish re-checks both lead rules as ERR_PUBLISH_LEAD_TIME.
14. **RESULTS_FINALIZED array errors → 400**, validated atomically before any mutation.
15. **Version discipline**: at most one version bump per entity per request, including cascades and read-time auto-transitions.
16. **Trailing window as timedeltas** (0 ≤ age ≤ 365d; full ≤180d), thresholds inclusive per §2.8; roster season points use calendar year of `trials_end` with `event_date <= now`.
17. **Unknown list-filter values → empty page**, not 400.

Orchestrator verification: all 20 files present (18 .py + start.sh + requirements.txt); `py_compile` clean on all 18 modules; `routes_clock.py` mounts `/_clock/set_current_utc` unprefixed and app.py registers it; constants.py spot-check matches PRD literals (0.40/0.35/0.25, 120d, 365d, 730d, 250, 0.40 NGB share, 90d, 14d, 72h).

## Step 7: Run Tests and Iterate — 2026-10-02T21:00:00.000Z

Clean 8-round sweep achieved. Summary:

**Iterations run:** 2 (initial sweep: 56/60 in all 8 rounds with the same 4 failures; post-fix sweep: 60/60 in all 8 rounds).

**Tests deleted:** None. Two assertions (not whole tests) were removed under STEP 1c partial-coverage handling:
- `test_difficulty_resource_temporal_overlap.py::test_certification_cycle_half_open_adjacency` — removed `assert cycle_c["window_start"] == "2026-12-01T00:00:00Z"` (replaced with the PRD-verbatim `status == "SCHEDULED"` check). Collapse pattern: representation silence — PRD pins three-fractional-digit ISO 8601 only for server-generated timestamps (`api_request_timestamp`, `created_at`, `updated_at`, §2.2/§2.4) and says nothing about whether user-supplied `window_start` echoes verbatim or canonicalizes; two faithful readers diverge. Scaffold driver: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` instance `resource_temporal_overlap/certification_cycle_half_open_adjacency` payloads use millisecond-less literals.
- Same file, `test_deal_exclusivity_closed_interval_gap` — removed `assert deal_c["exclusivity_start"] == "2027-04-01T00:00:00Z"`; same silence pattern, scaffold instance `deal_exclusivity_closed_interval_gap`. All PRD-covered assertions (overlap rejection, adjacency acceptance, statuses, counts) were kept.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** Only the two assertion removals above.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_athletes.py` — `result_transition()`: an `Athlete` caller attempting `VERIFIED`/`REJECTED` on their own result now raises `ERR_SEGREGATION_OF_DUTIES` (403) per PRD §3.4's verbatim "a self-verification rejected as `ERR_SEGREGATION_OF_DUTIES`" (the pre-adjudicated item). The old code raised `ERR_UNAUTHORIZED` from the role guard before the segregation check was reachable — generation-interpretation #4 over-guard. Cross-athlete access still denies with `ERR_UNAUTHORIZED`, and tier-4 state legality still precedes the tier-7 segregation check per the §2.6 ladder.
- `workspace/implementation/routes_selection.py` — `RESULTS_FINALIZED` branch: added a tier-3 existence pass over the `results` array so a non-existent `athlete_id` foreign key raises `ERR_NOT_FOUND` (404) per PRD §2.6 tier 3 ("body-supplied foreign-key references such as `athlete_id` … exist; otherwise `ERR_NOT_FOUND`"), ahead of the tier-7 constraint errors — generation-interpretation #14 ("array errors → 400") had over-generalized. Atomicity is preserved: the scan runs before any mutation, and existing-but-unentered athlete_ids still draw `ERR_INVALID_REQUEST`.

**Final sweep evidence:** Rounds 1–8 each `passed=60 total=60` (0 failures, no flakiness in the union). `results.1.json` … `results.8.json` remain on disk in `workspace/implementation/`.

Orchestrator verification: all 8 results files present (~17.8 KB each, timestamped 20:59); each parses with passed=60 total=60 failed=0; every results file is newer than every implementation .py source (post-fix sweep confirmed as the final state); no test tree files modified after the sweep.

## Step 8: Finalize PRD — 2026-10-02T21:20:00.000Z

All checks pass. The work is complete.

**File:** `workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 316 lines → PRD_FINALIZED.md 318 lines (+2 lines, +0.63%). Three edits, all scoped to the `<step_7_diff>` items.

### Changes (one bullet per edit)

- **§2.2 (API Response Structure)** — insert — new paragraph after the pagination bullet pinning that every datetime the server emits uses the canonical UTC form with exactly three fractional digits, and that all client-supplied ISO 8601 datetime fields (`window_start`/`window_end`, `event_date`, `coverage_start`/`coverage_end`, `trials_start`/`trials_end`/`registration_deadline`, `exclusivity_start`/`exclusivity_end`, clock `to_iso8601`) are parsed to an instant and re-rendered in that form rather than echoed verbatim (submitted `2026-12-01T00:00:00Z` reads back `2026-12-01T00:00:00.000Z`); date-only `date_of_birth` keeps its `YYYY-MM-DD` form — `implementation/validate.py:111` (`req_datetime` discards the input string), `implementation/timeutil.py:15-18` (`iso3`), `implementation/envelope.py:38-39` (serialize → iso3), `implementation/timeutil.py:39-50` (`parse_date` echoes the validated string), `implementation/routes_clock.py:23`.
- **§3.4 (Performance Results)** — revise — after the existing self-verification sentence, pinned that an `Athlete` caller attempting `VERIFIED`/`REJECTED` on their own result is the self-verification case (`ERR_SEGREGATION_OF_DUTIES`, never a generic role denial), cross-athlete attempts draw `ERR_UNAUTHORIZED` per §2.1 ownership, and state legality (must be `SUBMITTED`) precedes the segregation check per the §2.6 ladder — `implementation/routes_athletes.py:233-253`.
- **§3.6 (Team Selection, RESULTS_FINALIZED)** — revise — replaced "any unknown `athlete_id` or duplicated athlete rejects the whole request unchanged" with the error split the impl implements: existence of every array `athlete_id` is validated before any other per-item check (`ERR_NOT_FOUND` for a non-existent Athlete); malformed items, existing-but-not-still-`REGISTERED` entrants, duplicates, and incomplete coverage all reject with `ERR_INVALID_REQUEST`, atomically — `implementation/routes_selection.py:173-204`.

### Per-edit pre-edit search log

**Edit 1 (datetime canonicalization).** (a) Subject: output representation of user-supplied datetime fields. (b) Enumerated and read: `validate.py` (`req_datetime`/`req_date`), `timeutil.py` (`parse_dt`, `iso3`, `now_iso`, `wall_now_iso`), `envelope.py` (`serialize` — sole serializer for all object/list/error responses), `db.py` (`create`/`mark` use `wall_now_iso`), `routes_clock.py:23` (bare `jsonify` with `now_iso` — the only serialize bypass, still canonical), plus grep of every `req_datetime` callsite (routes_gb.py:162-163, routes_commercial.py:43-44, routes_funding.py:38-39, routes_selection.py:46-48, routes_athletes.py:197) and every server-side `_at` stamp (15 sites, all `datetime` objects). (c) Wording adjustment: listed the datetime fields explicitly and added the `date_of_birth` carve-out so the universal claim ("every datetime the server emits") does not misdescribe the one date-only path that echoes verbatim; clock `current_utc` covered by "every datetime the server emits" without disturbing §2.5's existing bare-body description.

**Edit 2 (self-verification segregation).** (a) Subject: authorization/error precedence on `POST /api/results/{id}/transitions`. (b) Enumerated and read: `routes_athletes.py:225-272` (the only result-transition path — Athlete-self branch lines 241-247, ResultsOfficial branch 248-253, resubmit branch 265-266), the endpoint role list at line 228 and PRD §4's table row, the other segregation pairs (routes_gb.py:285/312/396 — cycle-close and complaint-resolve compare opaque auditor ids; separate subject, untouched), and `_recompute_agreements` (post-verify cascade, no auth relevance). (c) Wording adjustment: added "Per the §2.6 ladder, state legality … is evaluated before the segregation check" because the bare "never with a generic role denial" claim would otherwise misdescribe the Athlete-self-on-non-SUBMITTED path, which returns `ERR_INVALID_STATE` (409) — consistent with both impl branches and with §2.6's existing global tier order.

**Edit 3 (array-element FK existence).** (a) Subject: validation of the `results` array in the RESULTS_FINALIZED transition. (b) Enumerated and read: `routes_selection.py:164-214` (the branch), plus a sweep of every other array-carrying endpoint — `slot_decisions` in `routes_rosters.py:155-200` (its `athlete_id` is ownership-matched to `X-User-ID`, never entity-existence-checked; a universal "array FKs get tier-3 checks" claim would have created a new mismatch there) — and every scalar body-FK site (`athlete_id` on entries, `governing_body_id` on athlete create) plus `interim_manager_id` (routes_gb.py:105 — opaque operator id, no existence check). (c) Wording adjustment: deliberately scoped to the finalization site and omitted any "§2.6 tier 3" citation or "immediately after path resolution" phrasing, because the impl runs the array existence scan *after* the tier-4 state checks (trials `HELD`, window ended) on this endpoint — a tier citation would have implied a ladder position the impl does not exhibit; the wording asserts only ordering *within* the per-item checks, which the impl does satisfy.

No edit touches behavior outside its Step 7 site; the zero-edit fallback was not applicable since all four diff items corresponded to genuine PRD silences or ambiguity now resolved toward the shipped implementation.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the three reported edits (§2.2 insert at line 48-49, §3.4 revise at line 180, §3.6 revise at line 213) and nothing else; 316 → 318 lines confirmed.

## Step 9: Complete PRD — 2026-10-02T21:50:00.000Z

Done. PRD_COMPLETED.md is written and verified against the source.

## File stats
- Source: `PRD_FINALIZED.md` (existed; copied per Step 0) — 318 lines / 63,539 chars
- Output: `PRD_COMPLETED.md` — 319 lines / 67,270 chars (+1 line, +3,731 chars)
- `diff -q`: **differ** (21 revised paragraphs + 1 added error-catalog row; diff hunks at lines 17, 52, 74, 85, 89, 100, 128, 154, 164, 172, 176, 189, 197, 205, 209, 213, 215, 217, 219, 221, 227, 318a319 — all intentional, listed below)

## Counts
- Ambiguity-pins: **20** (PRD silent, impl's choice now pinned)
- Mismatch-revisions: **2** (both adjudicated, see below)

## Changes (per change bullet)
- §2.1 — insert — ambiguity — `GET /api/athletes` and `GET /api/rosters` are explicitly ownership-unscoped; all other reads/lists keep ownership rules — routes_athletes.py:69-84, routes_rosters.py:66-76
- §2.2 — revise — ambiguity — error envelope also covers the uncaught-failure guard `ERR_INTERNAL`/500 — app.py:47-50, errors.py:40
- §2.3 — revise — ambiguity — non-integer/`<1`/`>100` limit, non-integer/negative offset → `ERR_INVALID_REQUEST` (400); `created_at` ties break by creation sequence — envelope.py:54-75, db.py:96-98
- §2.4 — revise — ambiguity — `created_at`/`updated_at` are wall-clock stamps (logical clock governs domain timestamps only); per-resource version advances at most once per request — db.py:61-85 (request-scoped `_marked` dedup)
- §2.5 — insert — ambiguity — clock set accepts any instant, no monotonicity guard — routes_clock.py:15-23
- §2.5 — insert — ambiguity — on-read due-checks scoped to the returned resources' own type (athletes/deals/cycles/body) — cascades.py:291-299 + read endpoints
- §2.8 — insert — ambiguity — decimals render as plain JSON numbers (`48.00` → `48.0`) — envelope.py:40-41
- §3.1 — insert — ambiguity — pass close against `INTERIM_MANAGED` and fail close against `PROBATION`/`INTERIM_MANAGED` are no-ops — cascades.py:188-203
- §3.2 — insert — ambiguity — decertification without evidence → `ERR_INVALID_STATE` (409) — routes_gb.py:144-148
- §3.3 — insert — ambiguity — failed prongs on the athlete `ELIGIBLE` transition → generic `ERR_INVALID_STATE`, not the tier-5 safety errors — routes_athletes.py:148-157
- §3.3 — insert — ambiguity — abuse-report filing has no subject-ownership requirement (Athlete may file on any athlete) — routes_safety.py:27-44
- §3.4 — insert — ambiguity — verification-driven recompute touches every non-`TERMINATED` agreement, `SUSPENDED` included — routes_athletes.py:275-292
- §3.5 — insert — ambiguity — `activated_at` written only on initial `OFFERED`→`ACTIVE`; reassessment/resume leave it (insurance wait from first activation) — routes_funding.py:154-156, cascades.py:68-76
- §3.5 — insert — ambiguity — waterfall final tiebreak falls through `created_at` to creation sequence — calc.py:172-175
- §3.6 — insert — ambiguity — drafting-time error ids: reversed trials window → `ERR_CYCLE_WINDOW_INVALID` (422); 14-day deadline or `quota_slots < 1` → `ERR_INVALID_REQUEST` (400) — routes_selection.py:51-60
- §3.6 — insert — ambiguity — roster creation on terminal procedure / with live non-terminal roster → `ERR_INVALID_STATE` (409) — routes_rosters.py:46-52
- §3.6 — insert — ambiguity — ALTERNATE ranks continue the sequence (N+1, N+2) — calc.py:289-299
- §3.6 — insert — ambiguity — trials entry is not a standalone resource; entry creation returns the updated procedure with 201 — routes_selection.py:248-255
- §3.6 — insert — mismatch-adjacent scope gap — upheld appeal reverts `NOMINATED` **or `SUBMITTED`** roster to `DRAFT` — routes_appeals.py:132-137
- §3.6 — insert — ambiguity — appeals fileable only while roster is `NOMINATED`/`SUBMITTED` (else `ERR_INVALID_STATE`) — routes_appeals.py:34-36
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row — errors.py:40
- §3.6 — **revise — mismatch** — slot decisions may target `slot_status` `NOMINATED` **or `PROMOTED`** (was "still `NOMINATED`"); batch validated atomically — routes_rosters.py:175-198
- §3.6 — **revise — mismatch** — dropped phantom `DISQUALIFIED` entry status: duplicate-entry rule now "an entry of any status", and the re-run example "after an entry disqualification" → "after an entrant's eligibility, screening, or training currency has changed" — routes_selection.py:244-247 (duplicate check rejects any existing entry)

## Mismatch adjudications
1. **PROMOTED slot decisions** (PRD §3.6 said slots "still `NOMINATED`"): revised PRD. Adjudication (a) applies: PRD self-contradicts — the submission gate (§3.6 and §2.6 tier-7 `ERR_PENDING_SLOT_DECISIONS`) counts `PROMOTED` primaries as awaiting an answer, so if PROMOTED slots were unanswerable, any roster with a promotion could never be submitted (circular-precondition deadlock). Impl's reading is the only satisfiable one.
2. **`DISQUALIFIED` entry status** (two PRD references): revised PRD. Adjudication (b) applies: no disqualify transition, endpoint, or state is defined anywhere in §3/§4 — the status is unimplementable as stated and the qualifier is vacuous (all entries are non-DISQUALIFIED, so impl's "any existing entry blocks" is behaviorally identical to the PRD rule minus the phantom).

## IMPL BUGS
**None found.** Evidence of the required enumerations:
- *Prose-only uniqueness*: `grep -i unique PRD_FINALIZED.md` → only `api_request_id` and `error_id` (both inherent); no domain-field uniqueness declarations exist to be dropped.
- *Dead checks*: enumerated all 90 helper/route function defs; only `opt_str`, `opt_int`, `req_bool` are uncalled — inert field validators guarding nothing, not dropped PRD rules. All catalog error_ids raised in routes are defined in errors.py; no call-into-undefined (no KeyError→500 path).
- *Crash-path enumeration*: walked every read of each PRD-nullable field — `certified_at`, `interim_manager_id`, cycle `*_score`/`opened_at`/`closed_at`, complaint `triaged_by`/`resolved_by`/`resolved_at`, athlete `screening_expires_at`/`training_completed_at`, result `base_points`/`verified_by_user_id`, agreement `activated_at`/`insurance_enrolled_at`, procedure `published_at`/`locked_at` + entry `score`/`result_recorded_at`, roster `nominated_at`/`submitted_by_user_id`, appeal `decision_rationale`, deal share fields/`consented_at`/`activated_at`/`forwarded_at`/`adjudicated_at`. Every read is either None-guarded (calc.py:136-139, 173-175, 220-229, 266; cascades.py:151-153, 258-263, 272-274; routes_appeals.py:38) or unreachable-while-null because the writing transition strictly precedes the reading state. Orphaned-parent dereferences are guarded (`proc is None` / `gb is None` branches in routes_rosters.py, routes_funding.py:95-96, routes_appeals.py:46-51).
- Latest sweep `results.8.json`: 60/60 passed.

Orchestrator verification: PRD_COMPLETED.md exists at 319 lines and differs from PRD_FINALIZED.md (`diff -q`); the two mismatch revisions fall in the recognized exoneration classes (PRD self-contradiction → circular-precondition deadlock; unimplementable phantom status), so no Step 9b impl fix + re-sweep is warranted; all 8 results.*.json remain on disk, each 60/60, all newer than every implementation source (Step 9 wrote no impl files); `ERR_INTERNAL` catalog row and the PROMOTED-slot revision confirmed present in PRD_COMPLETED.md, and the PROMOTED wording is consistent with the submission-gate sentence two paragraphs later.

## Pipeline complete — final state
- 60/60 tests passing across 8/8 parallel stability-sweep rounds under `--isolation per-test-server`.
- Contract chain: PRD.md (316) → PRD_FINALIZED.md (318, +3 Step-7-site edits) → PRD_COMPLETED.md (319, +20 ambiguity pins, 2 adjudicated mismatch revisions).
- Step 7 record: 2 iterations, 0 tests deleted, 2 assertions removed (STEP 1c representation silence), 0 test_helpers fixes, 2 implementation fixes (self-verification SoD error; RESULTS_FINALIZED array FK existence).
