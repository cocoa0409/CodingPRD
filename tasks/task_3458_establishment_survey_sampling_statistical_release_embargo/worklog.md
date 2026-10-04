# Worklog — task_3458_establishment_survey_sampling_statistical_release_embargo

## Step 1: Create Task Directory — 2026-10-02T06:50:00.000Z

Pre-allocated task directory `./tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/` verified to exist with empty `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T08:16:00.000Z

Subagent returned (verbatim):

  All three scaffold artifacts are complete and pass every check. Final report:

  ## Files written
  - `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/SCAFFOLD.yaml` — 1379 lines (§1.0–§1.7 only; no design keys)
  - `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1180 lines (single key `scaffold_difficulty_design`)
  - `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/SCAFFOLD_CORNER_DESIGN.yaml` — 1555 lines (single key `scaffold_corner_design`)

  ## Lint verdict (verbatim)
  ```
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
  (1346 calls scanned across both design files; all checks (a)–(f) clean.)

  ## Structural summary
  - **api_prefix**: `/survey` (logical-clock endpoint `POST /_clock/set_current_utc` deliberately outside the prefix, startup default pinned at `2026-09-01T00:00:00Z`, rewind permitted)
  - **Entities**: 14 (SurveyProgram, SampleFrame with embedded strata, Establishment, PanelEnrollment, SurveyCycle, ResponseReport, FollowUpCase, CellEstimate, SeasonalFactorSet, BenchmarkRun, MethodologyNotice, ReleaseEvent, MediaOutlet, EmbargoGrant)
  - **State machines**: 12 — non-linear shapes include ResponseReport SUBMITTED↔RETURNED, SurveyCycle PUBLISHED→REVISION_OPEN→CERTIFIED→PUBLISHED revision loop, PanelEnrollment ENROLLED↔SUSPENDED, MediaOutlet ACCREDITED↔SUSPENDED, CellEstimate REVISED self-loop + FINAL→RECONSTRUCTED, and ReleaseEvent with parallel pub_status × disclosure_status dimensions
  - **Calculations**: 9 — three dual-variant pairs (link-relative vs stratum-mean imputation; weighted vs unweighted response rate; concurrent vs revised seasonal adjustment), plus combinatorial modes (a) Neyman allocation with min-clamp-then-remainder order, (b) benchmark wedge per-month rounding (1913 vs 1912 split), (c) suppression fixed-point with totals-computed-before-complementary-selection pin
  - **Endpoints**: 41 (one over the nominal 40 ceiling — a deliberate cheap read endpoint `GET /sample-frames/{id}` to keep frame SUPERSEDED observable)
  - **Error catalog**: 54 (exceeds the Expert guideline band; every error is wired to a validation and exercised by at least one design instance — verified by audit)
  - **Roles**: 8, `segregation_of_duties` role model (certifying EstimationAnalyst's X-User-ID is barred from disclosure-approving that cycle's release); Respondent and AccreditedMedia are entity-backed with ownership checks
  - **Concurrency rules**: 2 OCC (frame-create on `SurveyProgram.version`, release-advance on `ReleaseEvent.version`)
  - **§1.8 instances**: 21 — every rule ≥2, with rules 1–3 carrying 3 each; all numeric asserts are precomputed literals (1033/1100 imputation split, 0.713542 vs 0.800000 rates, 1048 vs 1078 seasonal vintages, 941/972/1045 wedge, 1150 reconstruction, 0.600000 exact-threshold certification, embargo exact-open instant)
  - **§1.9 instances**: 69 total (62 with full test_recipe across all 9 taxonomy sections, 7 `excluded_because` stubs pointing at covering §1.8 instances)

  ## Audit issues found and fixed during generation
  - Quota violation in the suppression fixture (3 enrollments into a size-2 allocation) — reworked to a budget-24 fixture with recomputed literals (cells 100/100/120/133, totals 200/253)
  - Weighted-rate literal corrected to 0.713542 after the fixture was slimmed
  - Masked-bulletin total corrected to 150 (imputed non-respondent counts toward the estimate)
  - Dominance behavior at zero cell estimate pinned; frame-period duplicate-before-gap sub-order pinned; clock rewind documented
  - YAML hazards fixed: bracketed JSONPath captures quoted, a heredoc terminator that leaked into the corner file removed, grounds bracket-refs quoted

  No sibling task directories were read at any point; the design was derived purely from the scenario text and the skill specification.

Orchestrator verification: all three YAMLs parse via yaml.safe_load; SCAFFOLD.yaml top-level keys are scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities (no design keys); design files carry single top-level keys as specified; domain grep confirms survey/establishment/embargo vocabulary; api_prefix `/survey` with unprefixed `POST /_clock/set_current_utc` confirmed.

## Step 3: Copy Shared Files — 2026-10-02T08:17:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T08:45:00.000Z

Subagent returned (verbatim):

  All contracts pass. The PRD is complete and verified. Final summary:

  **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/workspace/PRD.md` — 347 lines.

  **Section list:**
  - §1 Introduction (3 paragraphs: agency context, revision-openness/embargo discipline, logical clock + segregation of duties)
  - §2 Global Specifications: 2.1 RBAC (8 roles, per-action role split, identity semantics for opaque vs entity-backed roles), 2.2 API Response Structure (byte-verbatim canonical block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, all list filters enumerated), 2.4 The Logical Clock (startup default `2026-09-01T00:00:00Z`, rewindable, `to_iso8601`/`current_utc`, mounted outside `/survey`), 2.5 Common Resource Properties, 2.6 Precision and Rounding (6dp rates/weights vs 0dp person counts, round half up), 2.7 OCC (both rules, exact field names and `ERR_STALE_VERSION`/412), 2.8 Validation Order and First-Failure Semantics (full 12-stage priority pipeline), 2.9 Release Calendar Arithmetic and Embargo Windows (3-day lead, half-open window, overlap exclusion of POSTPONED/PUBLISHED)
  - §3 Business Logic (9 subsections): 3.1 Programs & Sample Frames (incl. full Neyman allocation with 4/15/50 dispersion proxies, min-2 clamp, tie-breaks), 3.2 Establishments & Enrollment (frame gates, quota, snapshot weight), 3.3 Collection Cycle & Reports (derived window 1st–20th, submit/return/resubmit loop, close cascades), 3.4 Follow-Up & Burden Ledger (24h spacing, 480-min cap, escalation 2-contacts/7-days, void compensating pair, year rollover), 3.5 Estimation/Imputation/Suppression (LINK_RELATIVE vs STRATUM_MEAN, pinned rounding order, HT variance, response rates, 3-step suppression with fixed-point complementary selection, certify gates, revision loop), 3.6 Seasonal Adjustment (12-factor validity, concurrent-frozen vs revised-at-finalize, Jan-1-of-year+1 gate), 3.7 Benchmark Realignment (wedge rules, zero-cell handling, FINAL/RECONSTRUCTED untouched), 3.8 Methodology Notices (ppm reconstruction, scope semantics, cascades), 3.9 Releases/Disclosure/Embargo (parallel pub×disclosure dimensions, segregation of duties, grant issuance/access/revocation, breach depth-3 cascade)
  - §4 Endpoint Definitions: 41-row table, 4 columns only
  - §5 Error Code Catalogue: 54-row table, 2 columns only

  **Hard contract reports:**
  ```
  Field coverage check (Contract 1):
  - required identifiers (entities[].fields + request_body/input + query_params + path_params + clock/bulletin I/O): 107 required, 107 present, 0 missing
  Status: PASS

  Rule coverage check (Contract 2 — audited by category):
  - validation priority ordering: 31 rules expressed in §2.8's ordered 12-stage pipeline with first-failure semantics, 0 missing
  - concurrency_rules OCC: 2/2 expressed (write_endpoint + expected_program_version/expected_release_version + ERR_STALE_VERSION/412), 0 missing
  - state_machines transitions: all transitions of all 12 machines expressed with from/to, preconditions paired to error ids, and side effects (incl. the SUSPENDED→REVOKE no-grants asymmetry and reinstated-outlet grant non-restoration), 0 missing
  - calculations: 9/9 expressed as reconstructible prose (Neyman, base weight, imputation w/ both variants and pinned rounding order, variance, response rates, seasonal concurrent/revised, suppression 3-step, benchmark wedge, reconstruction), 0 missing
  - validations conditions: all 31 matchable to error ids in §2.8/§3 prose, 0 missing
  - endpoints side_effects / applies_to: all expressed (frame-create program version bump, +15 burden per submission, VOID_CONTACT compensating pair, bulletin masking, clock rewind), 0 missing
  - fields structured content: defaults (30/120/1/false), snapshot semantics, null-until semantics all stated, 0 missing
  - sibling-branch symmetry: parallel transitions rendered with equal density, 0 asymmetric
  Status: PASS

  Path purity check (Contract 3, §3 only):
  - backtick tokens scanned: 599
  - tokens starting with `/`: 0
  - bare HTTP-method tokens: 0
  - method+path combined tokens: 0
  Status: PASS
  ```

  **Self-audit notes on scaffold rules verified verbatim in prose:** §2.2 block is byte-identical to the canonical source (diff-verified). All 54 error IDs appear in §1–§4 prose (not just §5). All 55 state/enum values present. Boundary inclusivity rendered precisely throughout: dominance "exactly 60 percent is dominant", burden contact landing exactly on budget permitted, half-open embargo window with back-to-back adjacency allowed, `ANNOUNCE` strictly-future vs `ACTIVATE` at-or-after `effective_from`, clock "at or before" `collection_close_at` for submissions vs "reached" for opens/closes. Constants embedded in prose: dispersion 4/15/50, min stratum sample 2, min cell respondents 3, dominance 0.60, response-rate floor 0.600000, 15 min/submission, 24h spacing, 7-day escalation, 1–480 contact minutes, 3-day pre-announce, factor bounds [0.2, 5.0] with mean within 1.0 ± 0.0005, ppm baseline 1,000,000. The clock endpoint is documented as unprefixed (`/_clock/set_current_utc`) in both §2.4 and the §4 table. One repair was needed during verification: the `action` request-field token was initially absent; added to §2.1. The `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened or referenced.

Orchestrator verification: PRD.md exists at 347 lines. Orchestrator independently measured design-index queues from YAML (for Step 5 fan-out sizing): queue A (difficulty) = 21 full instances [dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2]; queue B (corner) = 62 full / 7 stubs [entities 9, state_machines 8, calculations 6, validations 27, endpoints 3, errors 0 full (5 stubs), rbac 6, complexity_layers 2 full (2 stubs), consistency_model 1]. Total non-stub = 83.

## Step 5a: Generate Test Helpers (Stage 1 of split Step 5) — 2026-10-02T09:05:00.000Z

Subagent returned (verbatim):

  Stage 1 is complete and frozen. Summary:

  ## Files written — `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/test_helpers/` (9 files, 2,094 lines)

  | File | Lines | Contents |
  |---|---|---|
  | `types.py` | 441 | 8-role `UserRole`, 14 status enums, 7 action enums, 14 entity TypedDicts + 4 nested (Stratum/ContactEntry/AdminCellCount/SeriesRef) + `Bulletin`. All entities carry id/created_at/updated_at/version (scaffold has `common_fields: true` for every entity — no append-only exceptions). |
  | `api_client.py` | 164 | `ApiClient(GenericApiClient)` with one method per PRD endpoint (36 business + clock), singleton `api_client`. |
  | `api_errors.py` | 126 | `ApiErrorId` (54 ids) + full HTTP status map, registered via `set_error_http_status_map`. |
  | `assertions.py` | 284 | `assert_<entity>` × 14 + `assert_bulletin` + invariant checkers (`assert_burden_invariants`, `assert_release_invariants`); `assert_follow_up_case` recomputes `total_contact_minutes` from non-voided contacts. |
  | `factories.py` | 264 | 13 create-payload factories (input fields only; optional program knobs omitted unless overridden) + 8 action-payload factories + `make_factor_list` (12-factor list with 1-indexed month overrides) + unique EIN/outlet-code generators. |
  | `constants.py` | 75 | All PRD-pinned thresholds + `collection_open_instant` / `collection_close_passed_instant` helpers. |
  | `test_users.py` | 69 | `TEST_USERS` with 7 distinct opaque ids (admin-1, methodologist-1, collector-1, analyst-1, analyst-2, officer-7, release-manager-1) + never-matching fallbacks for the two entity-backed roles; builders `make_respondent_headers(establishment_id)`, `make_accredited_media_headers(outlet_id)`, plus free-id builders for DisclosureOfficer/EstimationAnalyst (segregation-of-duties tests). |
  | `fixtures.py` | 621 | ~45 helpers in tiers: clock; program/frame (OCC-aware `get_program_version` via list endpoint); panel enrollment with identity threading; cycle collection pipeline (`collect_cycle`, `setup_certified_cycle`); follow-up case work; factor-set/benchmark/notice; full release pipeline (`setup_embargoed_release`, `setup_published_release`) with OCC version auto-read. All use a `_setup` guard that raises "Setup failed: …" with the response body. |
  | `__init__.py` | 50 | Barrel export; 137-name public surface verified by import. |

  Package compiles and imports under the runner's PYTHONPATH; `api_client` binds the singleton as intended.

  ## Constants-diff result (item 4)
  All 26 numeric literals in `constants.py` grep-verified verbatim against PRD.md prose: clock start 2026-09-01T00:00:00Z; embargo window 30 / 1–1440; burden budget 120 / min 15; sample_budget ≥ 2; dispersion 4/15/50; min stratum sample 2; min cell respondents 3; dominance 0.60 inclusive; response-rate floor 0.600000; 15 burden-minutes per submission; contacts 1–480; 24h spacing; 2 contacts / 7 days escalation; collection 1st–20th; 3-day pre-announce lead; 12 factors in [0.2, 5.0] with mean 1.0 ± 0.0005; ppm baseline 1,000,000; pagination 10/1/100/0. **No scaffold-only values present; no drift.**

  ## Clock-reachability self-check (item 5)
  All fixture-derived instants are ≥ the 2026-09-01T00:00:00Z startup and internally ordered: open (month-01T00:00Z) ≤ close-passed (month-21T00:00Z); default release_at = close + 10d satisfies the 3-day lead; create → embargo_open → publish is monotonic. The one rewind recipe in the design indices (bulletin read 1s before `embargo_open_at`) is PRD-legal ("rewinding is permitted"), and `set_clock` imposes no monotonicity constraint.

  ## Prefix check (item 6)
  Clock is unprefixed (`CLOCK_PATH = "/_clock/set_current_utc"`); all 36 business methods build paths from `SURVEY_PREFIX = "/survey"`; zero occurrences of `/survey/_clock` in the package.

  ## PRD gaps noticed (reported, not papered over)
  1. **No `GET /survey/programs/{id}`** — only the list endpoint exists, and programs have no `code` filter. OCC re-reads must list-and-match by code; fixtures do this in `get_program_version`.
  2. **Program-code and outlet-code conflicts surface as `ERR_VALIDATION` (400)**, not a dedicated `ERR_DUPLICATE_*` id — Stage 2 must not assert a nonexistent duplicate-code error.
  3. **Bulletin payload is not an entity** — `release_status` mirrors `PubStatus`; cell masking (null `employment_estimate` + both seasonal fields, totals still full) is asserted per-field in Stage 2, not in `assert_bulletin` (shape only).
  4. **FollowUpCase has no create endpoint** — cases exist only via the CLOSE_COLLECTION cascade; `find_case(enrollment_id, cycle_id)` locates them via the list filter.
  5. **`estimates_computed_at` is cleared by both CLOSE_COLLECTION and REOPEN_REVISION** — Optional in types; the cleared-then-recomputed assertion belongs to Stage 2.

  No `test_suite/` or `test_*.py` files were created; `workspace/implementation/` was not touched.

## Step 5b: Generate Test Suite (Stage 2 of split Step 5) — 2026-10-02T09:40:00.000Z

Subagent returned (verbatim):

  Stage 2 is complete. Final report:

  ## Files written (all under `.../task_3458_establishment_survey_sampling_statistical_release_embargo/test_suite/`)

  - `conftest.py` — 59 lines (session `api` fixture + one fixture per TEST_USERS role key)
  - `test_01_estimation_dual_variants.py` — 148 (A: dual_variant_calc ×3)
  - `test_02_allocation_benchmark_suppression.py` — 180 (A: combinatorial_formula ×3)
  - `test_03_nonlinear_state_machines.py` — 139 (A: non_linear_state_machine ×3)
  - `test_04_transitive_cascades.py` — 152 (A: transitive_cascade ×2)
  - `test_05_validation_order_and_boundaries.py` — 170 (A: priority_pair ×2, boundary_precision ×2)
  - `test_06_cross_entity_and_intervals.py` — 169 (A: cross_entity ×2, resource_temporal_overlap ×2)
  - `test_07_compensating_pairs.py` — 97 (A: compensating_invariant ×2)
  - `test_08_corner_entities.py` — 249 (B: entities 9)
  - `test_09_corner_state_machines.py` — 236 (B: state_machines 8)
  - `test_10_corner_calculations.py` — 211 (B: calculations 6)
  - `test_11_corner_validations_collection.py` — 185 (B: validations 1–9)
  - `test_12_corner_validations_followup.py` — 213 (B: validations 10–18)
  - `test_13_corner_validations_release_benchmark.py` — 244 (B: validations 19–27)
  - `test_14_corner_bulletins.py` — 125 (B: endpoints 3)
  - `test_15_corner_rbac.py` — 118 (B: rbac 6)
  - `test_16_corner_occ_and_consistency.py` — 116 (B: complexity_layers 2, consistency_model 1)

  ## Coverage

  - **Total tests emitted: 83** — exactly one per non-stub instance, each tagged `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` as the last docstring line.
  - **Queue A: 21/21. Queue B: 62/62.** No two-condition-filter skips — the PRD (esp. §2.8's explicit stage ordering and §3's named error ids) verbatim-covers and uniquely derives every instance. The 7 stubs (5 errors, 2 complexity_layers) were not translated, per spec.

  ## Verbatim audit outputs

  AST audit (parses both YAMLs, extracts every `Design:` tag from every `test_*` function, checks resolution/uniqueness/last-line placement):
  ```
  expected non-stub instances: 83 (A=21, B=62); stubs: 7
  test functions: 83
  instances covered: 83 / 83
  missing coverage: 0
  problems: 0
  ```

  `pytest --collect-only -q test_suite/` (PYTHONPATH=task root) tail:
  ```
  tasks/.../test_16_corner_occ_and_consistency.py::test_occ_stale_program_version_on_frame_create
  tasks/.../test_16_corner_occ_and_consistency.py::test_occ_stale_release_version_on_reschedule
  tasks/.../test_16_corner_occ_and_consistency.py::test_immediate_consistency_mutation_visible_in_response

  83 tests collected in 0.40s
  ```
  Package graph imports cleanly. Greps: 0 skip/xfail markers, 0 "scaffold" mentions. `test_helpers/` untouched.

  ## Notes for downstream steps (not patched, per instructions)

  1. **Bulletin `industry_totals` field name**: two instances (`bulletin_masks_suppressed_cells_but_totals_full`, `suppression_fixed_point_row_column_iteration_order`) assert `totals[i]["total_employment"]`. PRD §3.9 pins "totals still show the full figures" but never names the value field; both design instances pre-commit to `total_employment`, and frozen-helper note #3 says to assert totals per-field, so I followed the indices. If Step 6 implements a different field name, these two tests (not the impl) are where the drift surfaces.
  2. **Unobservable state re-reads dropped**: `benchmark_apply_missing_cell_rejected` asserts "the run stays DRAFT" and `notice_activate_before_effective_rejected` asserts "the notice remains ANNOUNCED", but neither BenchmarkRun nor MethodologyNotice has a GET endpoint. I asserted the observable cores instead (error id + the untouched PRELIMINARY cell; successful ANNOUNCE + rejected ACTIVATE). The dropped sub-claims are unreachable from the PRD surface — flag for Step 9 adjudication if desired.
  3. **Literal timestamp equality**: several design asserts pin exact `"....T..:..:..Z"` strings (`frozen_at`, `embargo_open_at`, `first_accessed_at`, `applied_at`, `submitted_at`). PRD §2.5's three-fractional-digit rule is stated for `created_at`/`updated_at`; an impl emitting `.000Z` on these computed instants would fail these assertions. I copied the design literals verbatim per the translation rule.
  4. No helper bugs encountered; all fixture/factory/client signatures worked as documented in the Stage-1 report (unprefixed clock path, 201 creates passed explicitly to `validate_success`, per-entity header builders used for Respondent/AccreditedMedia calls).

Orchestrator independent re-audit (AST walk over all 16 test files vs both YAML indices): 83 expected non-stub instances; 83 tagged test functions; 0 untagged; 0 duplicate tags; 0 tags failing to resolve; 0 instances uncovered. `pytest --collect-only` collected 83 tests cleanly. Hand-back claims verified against source.

## Step 6: Generate Implementation — 2026-10-02T09:56:00.000Z

Subagent returned (verbatim):

  All verification complete. Final summary:

  ## Step 6 Implementation Complete

  **Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/workspace/implementation/`

  ### Files written (27 source files + start.sh + requirements.txt; all `py_compile`-clean)

  | File | Lines | Role |
  |---|---|---|
  | start.sh | 10 | Guarded pip install + `exec python3 app.py` (PORT/0.0.0.0/foreground) |
  | requirements.txt | 1 | flask>=3.0 |
  | app.py | 75 | Assembly, lock, ApiError/404/405/500 envelope handlers |
  | store.py | 170 | In-memory DB (dicts), logical clock (starts 2026-09-01T00:00:00Z), all constants, serialize (datetime→3-fraction-digit ISO Z, Decimal→float) |
  | errors.py | 70 | All 41 PRD error ids with HTTP statuses |
  | envelope.py | 76 | `{meta, response_type, data}` envelope, pagination meta |
  | authz.py | 40 | X-User-ID/X-User-Role, 8 roles, per-action split, ownership |
  | validate.py | 119 | Shape helpers, YYYY-Qn / YYYY-MM / ISO8601 parsing |
  | burden.py | 34 | Burden ledger with calendar-year rollover |
  | calc_alloc.py | 77 | Neyman allocation (exact Fraction arithmetic) + base weight |
  | calc_est.py | 230 | Cell estimation, LINK_RELATIVE/STRATUM_MEAN imputation, variance, rates, suppression fixed point |
  | calc_apply.py | 171 | Benchmark wedge realignment, methodology reconstruction, published-release re-flag |
  | releases_util.py | 59 | Half-open embargo overlap, grant-count recompute, revocations |
  | bp_*.py (15 modules) | 63–224 each | programs, frames, establishments, enrollments, cycles, reports, followups, estimates, seasonal, benchmark, notices, releases, outlets, grants, clock |

  ### Route count
  Registered routes: **40 under `/survey` + 1 unprefixed `POST /_clock/set_current_utc` = 41 total**. Note: the prompt said "expect 41 prefixed + 1 unprefixed," but the PRD §4 table and scaffold §1.5 both define exactly 40 prefixed + 1 clock (41 rows total) — the implementation matches the source tables route-for-route (verified via `app.url_map`).

  ### Constants grep (item 4)
  All named constants are defined **exactly once** in `store.py` with PRD-verbatim values: dispersion 4/15/50, MIN_STRATUM_SAMPLE 2, MIN_CELL_RESPONDENTS 3, DOMINANCE_THRESHOLD 0.60 (inclusive `>=`), MIN_WEIGHTED_RESPONSE_RATE 0.600000, 15 min/submission, budget default 120 (min 15), contacts 1–480, 24h spacing, escalation 2 contacts + 7 days, close day 20, 3-day lead, embargo default 30 (1–1440), 12 factors in [0.2, 5.0] mean 1.0±0.0005, PPM_BASELINE 1_000_000, pagination 10/1/100/0, CLOCK_START 2026-09-01T00:00:00Z. No guessed or duplicated constants.

  ### Key interpretations chosen (item 3)
  1. **Neyman reconciliation literal**: fractional parts never recomputed, so deficit `+1`s all land on the single largest-fraction unclamped stratum; overshoot drains the smallest-fraction stratum until it hits 2, then the next.
  2. **Gate ordering follows §2.8 stages, not §3.9 prose order** (e.g. OPEN_EMBARGO: state → OCC → cycle-certified → disclosure → timing).
  3. **burden_minutes_ytd born 0 / burden_year null** (scaffold's explicit null language is only on burden_year).
  4. VOID_CONTACT triggers the same year-rollover view before subtracting; rewind across years never resets backward.
  5. Pagination out-of-range/non-integer → ERR_VALIDATION (read "accepts min 1 / max 100" as a constraint, not clamping).
  6. `api_request_timestamp` is wall-clock (request metadata); every resource-stamped timestamp is the logical clock, emitted uniformly with 3 fractional digits — including computed instants and the clock echo.
  7. Replacement frame with mismatched quarter → ERR_FRAME_PERIOD_GAP; SUPERSEDED replacement target → ERR_INVALID_STATE.
  8. VOID_CONTACT on a closed case → ERR_INVALID_STATE; unknown contact_seq → ERR_VALIDATION (stage 5, before state).
  9. STRATUM_MEAN with zero respondents → impute 0; LR with zero matched-pair prior sum → stratum-mean fallback.
  10. COMPUTE never touches FINAL/RECONSTRUCTED cells (no such transition exists); suppression still considers them with stored counts.
  11. `seasonally_adjusted_concurrent` re-frozen at each compute; `_revised` only at finalize.
  12. Missing benchmark-month cycle on apply → ERR_CYCLE_NOT_CERTIFIED (not 404).
  13. Bulletin: exact contract keys + `size_totals` (§3.9 says both row and column totals show); totals field named `employment_total`; masked cells null `employment_estimate` + both SA fields; `embargoed = clock < release_at`.
  14. Release advance bumps `version` exactly once per action (cascade recomputes inside an advance don't double-bump).
  15. Notice `series` with ALL_SERIES stored unvalidated ("ignored").

  ### Smoke transcripts (item 7)
  Three fresh-process runs on dynamically allocated ports, each killed by its saved `$!` PID:

  **Contract smoke (item 7 spec):** (a) `POST /_clock/set_current_utc` → 200 `{"current_utc":"2026-09-01T00:00:00.000Z"}`; (b) `POST /survey/programs` → 201 with defaults (embargo 30, budget 120, version 1); (c) `GET /survey/programs` → 200 array envelope with `limit/offset/total_count/has_more`; (d) missing `name` → 400 `ERR_VALIDATION`. All PASS.

  **Scenario A (full pipeline):** 45/45 PASS — Neyman (3200/8000/1600/3600 shares of 2050 → [2,2,2,2], total 8), base weights (50/10/25), ownership 403, window derivation (1st→20th 23:59:59), accept cascade, close→case creation, estimation (1500/400/0, rates 0.814815/0.75), certify, release create (embargo_open = release_at − 30m), segregation-of-duties 403, approve, ERR_RELEASE_TOO_EARLY 422, open embargo → 1 grant, bulletin masking (all PRIMARY nulled, totals MANUFACTURING 1900 / RETAIL 0 intact), grant ISSUED→ACCESSED stamp, publish → cycle PUBLISHED, reopen → release re-flagged (revision_notice_required true, APPROVED→PENDING).

  **Scenario B/C (suppression fixed point, factor sets, benchmark, reconstruction, follow-ups):** 4 initial FAILs were all script-side errors (an EXITed enrollment correctly left the denominator; my "adjacent" math ignored the 60-min window; state-409 correctly precedes OCC-412). After correcting the script: complementary suppression cascades exactly as pinned (row pass marks RETAIL/MEDIUM → column pass marks MFG/MEDIUM and MFG/LARGE → fixed point; only MFG/SMALL + RETAIL/SMALL publishable), factor-set 422s (13 entries / mean / range), finalize-too-early 422, frame gap/duplicate/replacement, freeze infeasible 422, duplicate codes/ein/enrollment/cycle/release, stratum unknown/full, RETURN without reason 400, accept-of-RETURNED 409, resubmit (submit_count 2, burden 45), late report 422, EXIT blocked 409, refused-close without contacts 422, contact spacing 422, budget edge (exactly 120 permitted; 121 → 422), escalation timing 422, void −45 / double-void 409 / unknown seq 400, close-unresponsive, EXIT after close, benchmark wedge (6600/6000 → 1.1, anchored FINAL rev 2), reconstruction ×1.5 → 9900 RECONSTRUCTED rev 3, FINAL factor set → SUPERSEDED. All PASS.

  **Scenario D (LR imputation, OCC, breach):** 28/28 PASS — matched-pair link relative 2.2 imputes 88 (=40×2.2) rounded before weighting → estimate 440, variance 29040; OCC 412 on stale version; missing version 400; half-open adjacency permitted; bulletin wrong-owner/wrong-role 403; second read keeps `first_accessed_at`; breach cascade depth-3 (grant BREACHED → outlet SUSPENDED → sibling grants REVOKED → counts recomputed); reinstatement never restores grants.

  **Isolation/empty-boot:** fresh process returns `total_count: 0` on all lists; no seeding anywhere (verified by grep + boot check).

Orchestrator verification of hand-back claims against source: (1) `errors.py` actually defines **54** error ids (subagent summary said 41 — a misstatement in the prose, not the code); impl / PRD §5 / test_helpers id sets are byte-identical (diff clean). (2) All 26 `*.py` files py_compile clean. (3) Blueprint route decorators cover the clock endpoint unprefixed + business paths under `/survey`. (4) Independent boot smoke on dynamic port 58539: clock set → 200; list envelope `{data, meta{limit,offset,total_count,has_more}, response_type:"array"}` → 200; missing-field create → 400 `ERR_VALIDATION`; missing `sample_budget` likewise → 400. Server killed by exact saved PID.

## Step 7: Run Tests and Iterate — 2026-10-02T10:16:00.000Z

Subagent returned (verbatim):

  Clean sweep achieved. Final summary:

  ## Summary

  **Iterations run:** 2 (sweep 1: 69/83 in all 8 rounds, deterministic; sweep 2 after fixes: **83/83 in all 8 rounds**).

  **Tests deleted:** none.

  **Fixes applied to `test_helpers/`:**
  - `test_helpers/assertions.py` — added `parse_instant` + exported `assert_same_instant`. PRD pins the three-fractional-digit serialization only for `api_request_timestamp`, `created_at`, `updated_at` (§2.2/§2.5) and is silent on the string format of computed/stamped instants (`frozen_at`, `applied_at`, `embargo_open_at`, `first_accessed_at`, `submitted_at`, `collection_open_at`, `collection_close_at`). Exact-string equality on those fields failed STEP 1b (two PRD-faithful serializers diverge); per STEP 1c the instant value (PRD-covered) is now compared at full strength and the string form (PRD-silent) is dropped.

  **Fixes applied to `test_suite/`:**
  - `test_02_allocation_benchmark_suppression.py` — `test_neyman_min_clamp_before_fractional_remainder` and `test_benchmark_wedge_rounds_per_month_not_annual`: timestamp asserts → `assert_same_instant`. `test_suppression_fixed_point_row_column_iteration_order`: fixture re-engineered (`sample_budget` 24→38, same strata) so raw Neyman shares are exactly 4/15/4/15 — no clamping/reconciliation is invoked, making the allocation identical under both readings of PRD §3.1's ambiguous reconciliation clause ("largest leftover fractional part — the raw share minus its floor", static vs. largest-remainder); expected estimates updated to 75/60/90/80 and bulletin totals to 135/170, with totals located by value (PRD never names the per-entry value field).
  - `test_05`, `test_06`, `test_08`, `test_12`, `test_14`, `test_16` — 9 further timestamp asserts → `assert_same_instant` (including two hidden second-failures at test_06:131 and test_12:178).
  - `test_14_corner_bulletins.py` — `test_bulletin_masks_suppressed_cells_but_totals_full`: `totals[0]["total_employment"]` KeyError → row and figure now located by value membership (tension point #1: the value field name is not in PRD; the full-figure total of 150 is).

  **Fixes applied to `implementation/`** (STEP 3 — PRD §2.8 verbatim: stage 2 "Authorization … for action-style endpoints, on the named action" precedes stage 3 "Path existence"):
  - `bp_reports.py` `advance_report`, `bp_cycles.py` `advance_cycle`, `bp_releases.py` `advance_release`, `bp_enrollments.py` `lifecycle` — per-action role check moved before path-resource load via a non-raising JSON peek, so a wrong role on a missing resource now yields `ERR_FORBIDDEN` (403) instead of 404, while malformed bodies still report at stage 5 and unknown actions on missing resources still 404 (verified by smoke).

  **Artifacts:** all 8 `results.*.json` files remain in `workspace/implementation/`, every one showing `passed == total == 83`.

Orchestrator post-Step-7 verification: (1) all 8 `results.*.json` show passed=83/total=83/failed=0/errors=0; (2) no `.py` source in implementation/, test_suite/, or test_helpers/ is newer than the results files — sweep is fresh, not invalidated by post-sweep edits; (3) zero skip/xfail markers in test trees; (4) spot-checks: `parse_instant`+`assert_same_instant` present in test_helpers/assertions.py:21,26; non-raising JSON peek + per-action role check present in bp_reports.py:113-115; 20 `assert_same_instant` uses across test_suite; zero remaining `total_employment` references. Hand-back claims verified against source.

## Step 8: Finalize PRD — 2026-10-02T10:35:00.000Z

Subagent returned (verbatim):

  The patch is complete: exactly three in-place revisions, no other drift. Final summary:

  ## Result

  **File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/workspace/PRD_FINALIZED.md` — 347 lines (same as PRD.md; all edits are in-place sentence revisions), 67,369 → 68,287 chars (+1.36%).

  ### Changes (3 revisions, 0 insertions of new sections)

  - **§2.5 — revise** — extended the stamped-instants sentence to pin that every timestamp field the server emits on a resource serializes as ISO 8601 UTC with exactly three fractional digits, same format as `created_at`/`updated_at` — `implementation/store.py:121-126` (`fmt_ts`, the sole datetime serializer, applied to all response data via `serialize()` at `store.py:156-164` and `envelope.py:27,35`). Covers the `test_helpers/assertions.py` `assert_same_instant` fix and all 11 timestamp-assert conversions in test_02/05/06/08/12/14/16 (`frozen_at`, `submitted_at`, `embargo_open_at`, `first_accessed_at`, `applied_at`, `collection_open_at`, `collection_close_at`, etc.).
  - **§3.1 — revise** — reconciliation clause now states the leftover fractional parts are computed once from the raw shares and never recomputed, so a multi-unit shortfall lands entirely on the single largest-fraction stratum and a multi-unit overshoot is drawn from the single smallest-fraction stratum until it reaches the minimum of 2 — `implementation/calc_alloc.py:36` (`fracs` computed once, never mutated), loops at `calc_alloc.py:38-54`. This pins the static reading of the clause Step 7 found ambiguous (static vs. largest-remainder) and worked around by re-engineering the `test_suppression_fixed_point_row_column_iteration_order` fixture.
  - **§3.9 — revise** — bulletin payload sentence now names the `size_totals` array alongside `industry_totals`, and pins the per-entry fields: `industry_code`/`employment_total` and `size_class`/`employment_total` — `implementation/bp_grants.py:63-88` (`_bulletin_payload`). Resolves the silence behind the `totals[0]["total_employment"]` KeyError in `test_14` and the value-membership lookups in `test_02:178-190`.

  ### No-edit items (evidence)

  - **Four `implementation/` fixes (`bp_reports.py:110-116`, `bp_cycles.py:139-147`, `bp_releases.py:117-124`, `bp_enrollments.py:126-133`)** — these brought impl *into* compliance with PRD §2.8, which already fully determines the corrected behavior: stage 2 "Authorization … for action-style endpoints, on the named action per the split in §2.1 … rejected with `ERR_FORBIDDEN`" precedes stage 3 "Path existence", and "The first failing stage determines the response: its error is returned and no later stage is consulted." Wrong role on missing resource → 403 is the verbatim consequence. Unknown actions have no §2.1 split entry (impl `authz.py:31-35` no-ops) and surface at stage 5 ("enum values are valid") after the stage-3 404 — also as §2.8 prescribes. No PRD edit owed.
  - **Test deletions:** none.

  ### Per-edit pre-edit search log

  1. **Edit §2.5 (timestamp format).** (a) Subject: serialization format of every server-emitted instant. (b) Enumerated paths: `store.py:121-126` `fmt_ts`; `store.py:156-164` `serialize` (universal response path via `envelope.py:27,35`); `envelope.py:19` `api_request_timestamp` (already PRD-pinned); `bp_clock.py:20` `current_utc`; every datetime field assignment — `bp_frames.py:154`, `bp_reports.py:166`, `bp_cycles.py:57,106,110,179`, `calc_est.py:226`, `bp_seasonal.py:118`, `bp_grants.py:106`, `bp_releases.py:57,63,183,198-199,210`, `bp_notices.py:84`, `calc_apply.py:121,170`, `bp_followups.py:83`; inputs parsed to `datetime` via `validate.py:100-105` `req_instant`. All are `datetime` objects → all serialize through `fmt_ts` with 3 fractional digits; no alternate formatter exists (grep for `isoformat`/`strftime`/`%f` output paths). (c) Wording scoped to "every timestamp field the server emits on a resource" — true of 100% of enumerated paths — rather than a narrower list that would miss `collection_open_at`/`collection_close_at`/`release_at`, and without claiming the non-resource `current_utc` (not a step_7 item).
  2. **Edit §3.1 (static fractional parts).** (a) Subject: freeze Neyman reconciliation. (b) Enumerated paths: `calc_alloc.py:18-55` `neyman_allocate` — the only allocation routine, called only from `bp_frames.py:149`; downstream consumer `calc_alloc.py:69-77` `base_weight_for` reads only the final `allocated_sample_size`. Verified `fracs` (line 36) is computed once and never mutated; the additive loop's candidate set (`not clamped`) is invariant across iterations, so the argmax stratum absorbs the entire shortfall; the subtractive loop re-filters `allocs[i] > MIN_STRATUM_SAMPLE` each iteration, drawing one stratum down to 2 before the next. (c) Added the explicit static-quantity sentence and the "single stratum" consequences in both directions, since the largest-remainder reading (each stratum at most +1) is the plausible misreading the fixture re-engineering sidestepped; kept tie-break text verbatim (matches `_tie_index` at `calc_alloc.py:11-15` against `INDUSTRIES`/`SIZE_CLASSES` at `store.py:45-46`).
  3. **Edit §3.9 (totals representation).** (a) Subject: bulletin payload totals arrays and entry field names. (b) Enumerated paths: `bp_grants.py:44-88` `_bulletin_payload` — the only totals computation in the codebase (grep for `industry_totals`/`size_totals`/`employment_total` hits nothing else; `calc_est.py` computes suppression only); sole caller `read_bulletin` at `bp_grants.py:108`. (c) Wording names the two arrays and the three entry fields exactly as emitted (`industry_code`, `size_class`, `employment_total`) but deliberately makes no claim about entry ordering or completeness across all industries/sizes (impl skips empty groups at `bp_grants.py:66,74` — not a step_7 item, left under-determined), staying consistent with the immediately following masking sentence ("industry row totals and size column totals still show the full figures").

  No IMPL BUGs to report: every implementation fix moved the code toward the PRD, and no PRD-stated rule was found violated by the current implementation in the areas examined.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly 3 hunks (lines 93, 148, 234) matching the three reported revisions verbatim — no other drift; both files 347 lines.

## Step 9: Complete PRD — 2026-10-02T10:55:00.000Z

Subagent returned (verbatim):

  Task complete. PRD_COMPLETED.md is produced and verified.

  ## Summary

  **Files:** `/home/ubuntu/github/CodingPRD/tasks/task_3458_establishment_survey_sampling_statistical_release_embargo/workspace/PRD_FINALIZED.md` (347 lines / 68,566 chars) → `PRD_COMPLETED.md` (347 lines / 71,684 chars). Char delta **+3,118**; exactly 15 paragraphs touched, all in-place revisions (no new sections, no new paragraphs, no line-count change).

  **Counts:** 15 ambiguity-pins, 0 mismatch-revisions.

  **Changes** (all are `ambiguity` pins — PRD silent/multi-reading, impl behavior pinned):
  - §2.2 — revise — ambiguity — `api_request_timestamp` pinned as a wall-clock reading, not the logical clock — `envelope.py:19`
  - §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` and non-integer `year` filter → `ERR_VALIDATION`; `created_at` ties broken by creation order; `total_count` counts the filtered set — `envelope.py:48-76`, `store.py:170`, `bp_seasonal.py:92-98`
  - §3.1 — revise — ambiguity — `replaces_frame_id` naming a non-`DRAFT`/`FROZEN` frame → `ERR_INVALID_STATE`; quarter mismatch or cross-program frame → `ERR_FRAME_PERIOD_GAP` — `bp_frames.py:79-106`
  - §3.2 — revise — ambiguity — `burden_minutes_ytd` starts at 0 — `bp_enrollments.py:88`
  - §3.3 — revise — ambiguity — no program-consistency check between `enrollment_id` and `cycle_id` on report create — `bp_reports.py:33-66`
  - §3.4 — revise — ambiguity — voiding requires a live case (`ERR_INVALID_STATE` from closed), state check before already-voided check — `bp_followups.py:94-103`
  - §3.4 — revise — ambiguity — `outcome` outside `REFUSED`/`UNRESPONSIVE` (incl. `CLOSED_RESPONDED`) → `ERR_VALIDATION` — `bp_followups.py:124-127`
  - §3.4 — revise — ambiguity — burden rollover never runs backwards under clock rewind — `burden.py:13-21`
  - §3.5 — revise — ambiguity — link relative is an unrounded intermediate; matched pairs whose prior-cycle employment sums to zero fall back to `STRATUM_MEAN`; zero-respondent cells impute nonrespondents at 0 — `calc_est.py:34-42,64-84`
  - §3.5 — revise — ambiguity — recomputation never touches `FINAL`/`RECONSTRUCTED` cells, and stale cells (no `ENROLLED` enrollments at compute time) are left untouched, never deleted — `calc_est.py:183-184,165-168`
  - §3.5 — revise — ambiguity — suppression resolution covers every cell estimate of the cycle regardless of `estimate_status` — `calc_est.py:229-230`
  - §3.6 — revise — ambiguity — each recomputation re-derives `seasonally_adjusted_concurrent` from the recomputed estimate and then-current factor set; "never changes afterward" covers only later factor revision — `calc_est.py:185-188,210`
  - §3.6 — revise — ambiguity — `factors` missing/not-an-array → `ERR_VALIDATION`; array-level constraint failures → `ERR_FACTOR_SET_INVALID` — `bp_seasonal.py:22-41`
  - §3.9 — revise — ambiguity — bulletin `cells` ordered by `industry_code` asc then `size_class` `SMALL,MEDIUM,LARGE`; empty industries/size classes omitted from totals — `bp_grants.py:49-50,63-78`
  - §5 — revise — ambiguity — three transport-level ids outside the catalogue: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `app.py:58-71`

  **IMPL BUG list: empty.** I walked all 41 endpoints (40 under `/survey` + `/_clock/set_current_utc`), all 12 state machines (frame, enrollment, cycle, report, case, cell estimate, factor set, benchmark run, notice, release pub/d disclosure dimensions, outlet, grant), all calculation formulas (Neyman allocation incl. fractional-part reconciliation and tie-breaks, base weight, link-relative/stratum-mean imputation with pinned rounding order, HT variance proxy, response rates, dominance/suppression fixed point, concurrent/revised seasonal division, benchmark wedge, ppm reconstruction), the §2.8 stage ordering as actually implemented in each endpoint, both OCC guards, every default (embargo 30 min, burden 120 min, pagination 10/1/100), and every side-effect cascade (close→case creation, accept→case closure, reopen/benchmark/activate→release re-flag, embargo open→grant issuance, postpone/suspend/revoke/breach→grant revocation with counter recompute). Every impl behavior matched PRD text or filled a PRD silence; no place where impl violates a clear, implementable, self-consistent PRD rule was found. All 54 catalog error ids are raised somewhere in the code (no dead catalog entries), and the latest sweep (`results.8.json`) is 83/83 passed.

Orchestrator verification: (1) `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows exactly 15 hunks, both files 347 lines — matches report; no mid-flight kill (byte-identical no-op ruled out by diff -q). (2) Adjudicated the one pin that codifies an *absent* check (§3.3 "no program-consistency check between enrollment_id and cycle_id on report create") against SCAFFOLD.yaml directly: the scaffold's report-create validations are cycle-COLLECTING (pri 12), enrollment-ENROLLED (pri 13), window (pri 26), and duplicate-report — no program-consistency rule exists in the scaffold, so the pin fills a genuine silence rather than stripping scaffold intent. The other 14 pins describe additive impl behavior; 0 mismatch-revisions means nothing was revised away. (3) All 8 `results.*.json` still present in implementation/, re-verified passed==total==83, failed==0, errors==0 in every round. No impl/ writes occurred after the Step 7 sweep (Steps 8/9 touched only workspace/*.md), so the sweep remains valid.

## Pipeline complete — 2026-10-02T10:56:00.000Z

Final state: 83/83 tests passing across all 8 parallel stability rounds under `--isolation per-test-server`; 0 test deletions; test_helpers 1 fix (assert_same_instant); test_suite 13 tests adjusted (timestamp-instant comparisons, bulletin totals by value, suppression fixture re-engineered to avoid the ambiguous Neyman reconciliation path); implementation 4 files fixed (per-action authorization ordering per PRD §2.8); PRD_FINALIZED.md = 3 revisions; PRD_COMPLETED.md = 15 ambiguity-pins, 0 mismatch-revisions, 0 impl bugs.
