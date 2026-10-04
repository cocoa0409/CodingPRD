# Worklog — task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs

Scenario: Emissions Certification, Aftertreatment Warranty & Rebuild Programs (Cummins). User instruction to scaffold-generator: "Generate task much harder than expert level!" Task directory pre-allocated by the caller; Steps 5 and 6 run SEQUENTIALLY (model endpoint duplicates parallel tool calls), with an explicit read-ban substituted for the lost concurrency isolation.

## Step 1: Create task directory — 2026-10-01T23:52:46.633Z

Pre-allocated directory `tasks/task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs/` verified to exist with empty `workspace/` inside; no new index computed, no other task_* directory created. Project-root `INSTRUCTION.md` verified present for Step 3.

## Step 2: Generate Scaffold (subagent) — 2026-10-02T00:00:00.000Z

Orchestrator verification before this entry: all three files parse with yaml.safe_load; SCAFFOLD.yaml has no design keys; 349 domain-keyword hits (emission/aftertreatment/engine); api_prefix=/emissions; clock default 2026-09-01T00:00:00Z; line counts 2141/1724/4176 match the subagent report.

Verbatim subagent summary:

All checks pass. The scaffold is complete and verified.

---

## Generation summary — task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs

**Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs/`):**
- `SCAFFOLD.yaml` — 2141 lines (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1724 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4176 lines (single top-level key `scaffold_corner_design`)

**Surface counts:**
- Entities: 16 — RegulationStandard (self-referential `successor_standard_id`), EngineFamily, AftertreatmentSpec, CertificationTestRun, Fleet, EngineUnit (parallel state dimensions lifecycle × campaign_compliance), MaintenanceRecord (append-only, `common_fields: false`), TelematicsSnapshot (append-only), ServiceCenter, Technician, DiagnosticTool, WarrantyClaim, FieldCampaign, CampaignWorkOrder, RemanOrder, InUseComplianceResult
- Endpoints: 85, grouped in 13 per-domain modules: _system 1, regulation-standards 5, engine-families 14, aftertreatment-specs 4, test-runs 5, fleet-operations (fleets + engine-units) 11, telematics 2, service-network 13, warranty 8, campaigns 6, campaign-work-orders 7, reman 8, in-use-compliance 1
- State machines: 13 (incl. cyclic claim-review loop bounded at 2 rounds, campaign COMPLETION_REVIEW revert loop, spec supersede, center reinstatement loop, lazy EXPIRED/RECAL_DUE transitions)
- Calculations: 13 (dual variants on WarrantyClaim proration and RemanOrder core credit; combinatorial modes (a) neglect tiering, (b) pinned rate-first rounding, (c) pinned reman-invoice evaluation order; aggregate day-bucket capacity vs strict half-open lab overlap; weighted fault-risk scoring; threshold conformity/completion/dosing)
- Validations: 13 ordered priority rows; Errors: 50; Roles: 7 (PlatformAdmin, CertificationEngineer, RegulatoryOfficer, FleetManager `entity_backed:Fleet`, ServiceAdvisor `entity_backed:ServiceCenter`, WarrantyAdjudicator, RemanPlanner; segregation-of-duties on certify); Concurrency rules: 2 OCC (`spec-create-stale-family` on EngineFamily.version, `reman-create-stale-unit` on EngineUnit.version)

**Design-index instance counts (drive test fan-out):**
- §1.8 non-stub instances: **19** — dual_variant_calc 2, combinatorial_formula 3 (one per mode a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth-4 verify chain, depth-3 core-reject chain), priority_pair_validation_conflict 2 (state×temporal, safety×fiscal), boundary_precision_check 2 (conformity ratio, core-return date), cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2
- §1.9 non-stub instances: **78 active + 7 excluded_because stubs** — entities 11, state_machines 16, calculations 10, validations 25, endpoints 3, errors 1 (+7 stubs), rbac 6, cross_cutting_layers 5, consistency_model 1

**api_prefix:** `/emissions` — core entity names for domain-fidelity grep: EngineFamily, RegulationStandard, AftertreatmentSpec, CertificationTestRun, EngineUnit, WarrantyClaim, FieldCampaign, CampaignWorkOrder, RemanOrder, ServiceCenter, Technician, DiagnosticTool, TelematicsSnapshot, InUseComplianceResult, Fleet, MaintenanceRecord.

**Confirmations:**
- All three files parse cleanly with `yaml.safe_load` (verified after every append; two YAML hazards fixed en route: unquoted `?` optionals in flow lists and a mangled heredoc, both re-parsed clean).
- `scaffold_lint.py` verdict (run on the task dir, verbatim tail): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (2358 calls scanned; 2 FK_REVERSE_UNREACHABLE violations found and fixed by normalizing `{centerId}`→`{id}` path templates.)
- Every referenced constant is defined with a concrete value in SCAFFOLD.yaml's top-level `constants:` block (46 keys; audit found only prose/enum tokens outside it).
- Creation graph is acyclic: standards → families → specs/runs → fleets/units → centers/techs/tools → claims/campaigns/work-orders/reman/in-use; the one near-cycle found during audit (ServiceCenter machine referenced but undeclared) was fixed by adding the machine.
- Logical clock defaults to `2026-09-01T00:00:00Z` (declared on the `POST /_clock/set_current_utc` endpoint); all 345 datetime literals across the three files are ≥ the clock start; two fixture bugs found in replay (in_service dates ahead of the clock; two missing clock-sets before `announced_at`/`verified_at` asserts; one wrong +365-day leap-year literal) were corrected.
- No forbidden race vocabulary; all `expected_*_version` payloads reference `${var}` captures; every error id is referenced by at least one validation/transition/design instance; all instance names unique across both design files; all `grounds` resolve; all 7 `excluded_because` stubs point at existing §1.8 instances.

**Note for downstream:** 85 endpoints exceeds the known impl-gen overshoot threshold — Step 6 should be run with the per-domain-module prompt pre-constraints (one file per message, per-module files, no-truncation, self-smoke-test).

## Step 3: Copy shared files — 2026-10-02T01:16:26.473Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). No other shared files required.

## Step 4: Generate PRD (subagent) — 2026-10-02T01:25:00.000Z

Orchestrator spot-check before this entry: PRD.md 400 lines; clock literal 2026-09-01T00:00:00Z present; boundary/error literals (0.9000, ERR_STALE_VERSION, ERR_SAMPLE_SIZE_TOO_SMALL) present; 85 endpoint table rows; ends cleanly at the §5 final row; 104 emission/aftertreatment hits.

Verbatim subagent summary:

All verification passes are green. The PRD is complete and intact.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs/workspace/PRD.md` — 400 lines.

**Section list**: §1 Introduction (2 paragraphs); §2 Global Specifications with subsections 2.1 User and Role-Based Access Control, 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Clock and Lazy Expiry, 2.5 Common Resource Properties, 2.6 Numeric Precision/Rounding/Monetary Representation, 2.7 Optimistic Concurrency Control, 2.8 Validation Order and Error Precedence (all 13 scaffold priority levels, ordered), 2.9 Hierarchical Consistency and Cascade Semantics; §3 Business Logic with 9 subsections (3.1 Regulation Standards, 3.2 Engine Family Certification, 3.3 Aftertreatment Design & Test Execution, 3.4 Fleets/Units/In-Use Compliance, 3.5 Telematics & Fault Prediction, 3.6 Service Network, 3.7 Warranty Claims, 3.8 Field Campaigns & Shop Execution, 3.9 Remanufacturing & Core Credit); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Endpoint coverage**: 85 of 85 documented. A programmatic diff of the §4 table paths against every `path:` in SCAFFOLD.yaml returned an exact match (`PATHS_MATCH`), including the `/_clock/set_current_utc` test-driving endpoint.

**Constant-literal coverage**: 46 of 46 scaffold constants appear as explicit literals in prose — verified by grep over the distinctive values: `2026-09-01T00:00:00Z` (with the never-falls-back-to-wall-clock rule stated verbatim), 5 years / 100,000 miles / 3,000 hours, 15,000-mile interval, 25/15/20 neglect points, cap 100, bands 30/60, 50% share cap, fleet suspension at 3, 0.6 provisional / 1.0 / 0.75 / 0.5 / 0.0 grades / 0.4 price cap / 1.0 / 1.15 / 1.3 multipliers, center suspension at 2 reversals, 0.9 conformity (0.9000 boundary inclusive), 0.95 completion default, 40/20/5 fault weights, divisor 10, drift cap 30, 500-mile DEF threshold, 25 penalty points, score cap 100, latch at 70, 730-day cert validity, 365-day tool validity, LEVEL_2 at 3 bay-days, 6.0 g/kWh over 12.0 L reference, 0.05 tolerance (0.0500 calibrates), 400 ppm NOx max, 2 review rounds, minimum sample 5. Omitted: none.

**Contract checks**: Contract 1 (field names) PASS — all entity fields, request-body keys, query params, path params, and the five coverage-read output fields (`base_covered`, `base_coverage_end`, `extended_covered`, `extended_coverage_end`, `extended_applies_to`) appear backticked; scripted diff reported zero missing. Contract 2 (rules) PASS — all state transitions with preconditions/error IDs, all 13 calculations in reconstructible prose (pinned rounding orders and the forbidden bare-price cap alternative stated), both OCC rules with `expected_engine_family_version`/`expected_engine_unit_version` + `ERR_STALE_VERSION` (412), all cascade hops, all validation orderings, all 50 error IDs mentioned in prose. Contract 3 (§3 path purity) PASS — zero backticked tokens starting with `/` or bare HTTP methods in §3. One gap found and fixed during verification: the test-review `decision` values now explicitly name `ACCEPT` / `REJECT`.

**No truncation**: document ends cleanly at the §5 table's final row (`ERR_SAMPLE_SIZE_TOO_SMALL`). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point; no other task directory was inspected.

## Step 5a: Generate test helpers (subagent, Stage 1 of split Step 5) — 2026-10-02T01:50:00.000Z

Split decision: 97 non-stub design-index instances (19 §1.8 + 78 §1.9) on a "much harder than expert level" task — Step 5 split into 5a (helpers, frozen) → 5b (queue A tests) → 5c (queue B tests), sequential, per the oversized-generation-step playbook.

Orchestrator verification before this entry: all 10 files present; py_compile clean; `import test_helpers` clean; zero hardcoded ports/hosts; DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"; base validators (validate_success / validate_error / validate_error_is_one_of) come from `prd_bench_local_runner.testing` and are re-exported via test_helpers/__init__.py.

Verbatim subagent summary:

Stage 1 is complete and verified. Summary for the worklog:

## Files generated (all under `/home/ubuntu/github/CodingPRD/tasks/task_3427_emissions_certification_aftertreatment_warranty_rebuild_programs/`)

| File | Lines |
|---|---|
| `test_helpers/types.py` | 517 |
| `test_helpers/api_client.py` | 280 |
| `test_helpers/api_errors.py` | 125 |
| `test_helpers/assertions.py` | 583 |
| `test_helpers/factories.py` | 343 |
| `test_helpers/constants.py` | 113 |
| `test_helpers/test_users.py` | 75 |
| `test_helpers/fixtures.py` | 568 |
| `test_helpers/__init__.py` | 49 |
| `test_suite/conftest.py` | 62 |

No `test_suite/test_*.py` written (Stage 2's job).

## Frozen public API surface (module → exports Stage 2 codes against)

- **types.py**: `UserRole`, 25 domain enums (`RegulationStandardStatus`, `CertificationStatus`, `InUseComplianceStatus`, `Architecture`, `SpecStatus`, `CalibrationStatus`, `TestType`, `TestResult`, `TestRunStatus`, `FleetStatus`, `UnitLifecycle`, `CampaignCompliance`, `MaintenanceType`, `FaultSeverity`, `AuthorizationTier`, `AuthStatus`, `CertificationLevel`, `CertStatus`, `ToolStatus`, `InUseOutcome`, `ComponentClass`, `CoverageVariant`, `ClaimStatus`, `AdjudicateDecision`, `ReviewDecision`, `CampaignType`, `CampaignStatus`, `WorkOrderStatus`, `RemanScope`, `ComponentType`, `SpecLevel`, `CoreGrade`, `RemanOrderStatus`), 16 entity TypedDicts + `FaultCode` + `CoverageRead`. Append-only entities (`MaintenanceRecord`, `TelematicsSnapshot`, `InUseComplianceResult`) carry only `id` + `created_at` per PRD §2.5.
- **api_client.py**: `ApiClient(GenericApiClient)` with 85 endpoint methods (full §4 surface incl. `set_clock` on `/_clock/set_current_utc`) + module-level `api_client`. Base URL from `API_BASE_URL` env (runner-injected).
- **api_errors.py**: `ApiErrorId` (50 IDs), `HTTP_STATUS_CODES` (50 mappings), registered with the framework via `set_error_http_status_map` at import.
- **assertions.py**: `assert_<entity>` ×16 + `assert_coverage_read`, `assert_claim_financials_balance`, `assert_list_sorted_by_created_at`, `assert_pagination_meta`; PRD-exact calculators `round_half_up`, `compute_adjusted_emission`, `expected_test_result`, `compute_conformity_ratio`, `expected_in_use_outcome`, `compute_dosing_target`, `compute_dosing_deviation`, `expected_calibration_status`, `compute_fault_risk_score`, `compute_neglect_score`, `compute_partial_proration`, `compute_provisional_core_credit`, `compute_spec_level_surcharge`, `compute_effective_price`, `compute_final_core_credit`, `compute_invoice_total`, `compute_completion_rate` — all verified to reproduce every pre-computed literal in both design indices (12467/87533, 25000/75000, 12467/87524, 120000/150000/350000, 60000/184000/276000, 0.9000-CONFORMING, 0.8889-NON_CONFORMING, neglect 65/40/0/cap-100, fault-70 boundary, DEF-penalty >500-only, dosing 7.45, completion 0.5/0/1.0).
- **factories.py**: 24 payload factories; scoped-unique fields minted per call; FK/OCC fields are keyword-only required; OCC helpers `occ_spec_payload(family)` / `occ_reman_order_payload(unit, ...)` read the parent's current version; `completion_threshold` and `component_type` conditional-inclusion rules honored.
- **constants.py**: all 46 PRD-pinned constants (flat names, PRD section annotated per value — see below).
- **test_users.py**: `TEST_USERS` (7 keys) + `make_<role>_headers` ×7; `SUBMITTER_USER_ID="ce-quinn"` / `CERTIFIER_USER_ID="ro-mara"` distinct for the certify segregation-of-duties gate; entity-backed builders `make_fleet_manager_headers(fleet_id)` / `make_service_advisor_headers(center_id)` mandatory for ownership-gated calls.
- **fixtures.py**: `set_logical_clock`, standard/family chain (`create_draft_standard`, `create_published_standard`, `create_family`, `add_spec_version`, `begin_family_testing`, `schedule_test_run`, `record_run_results`, `review_run`, `add_accepted_test_run`, `setup_family_testing`, `setup_family_under_review`, `certify_family`, `setup_family_certified`, `setup_family_in_production`), `setup_fleet`, `setup_service_center` (center+tech+tool), `setup_engine_unit`, `ingest_snapshot`, `add_maintenance_record`, claim lifecycle (`file_claim`, `start_claim_review`, `setup_claim_under_review`, `request_info`, `resubmit_claim`, `adjudicate`, `pay_claim`), in-use (`record_in_use_result`, `stamp_family_non_conforming`), campaigns (`declare_campaign`, `announce_campaign`, `setup_campaign_announced`, `setup_campaign_in_progress`), work orders (`schedule_work_order`, `start/complete/verify/cancel_work_order`, `setup_work_order_completed`), reman (`setup_reman_order_quoted/awaiting_core/core_received`, `grade_core`, `forfeit_core`, `close_reman_order`), `setup_full_environment()` = the canonical 24-call certified-program environment shared by all 19 difficulty instances. All setup via `get_success_data`; ownership-gated calls thread entity ids.
- **conftest.py**: session-scoped `api` + 7 role-header fixtures (entity-backed fixtures documented as non-ownership fallbacks).

## constants.py key → PRD verification

`DEFAULT_CLOCK_UTC` §2.4; pagination 10/1/100/0 §2.3; `REQUIRED_TEST_TYPES` §3.2; 4dp/2dp rounding §2.6; extended warranty 5y/100000mi/3000h + 5 emissions classes §3.7; neglect 15000-mi interval, 25/15/20 pts, cap 100, bands 30/60, 50% share cap, fleet-suspend-at-3, review-rounds 2 §3.7; core 0.6 provisional, grade 1.0/0.75/0.5/0.0, 40% cap, spec multipliers 1.0/1.15/1.3, center-suspend-at-2 §3.9; conformity 0.9 inclusive + min sample 5 §3.4; completion default 0.95 §3.8; fault weights 40/20/5, drift ÷10 cap 30, DEF 500-mi/25-pt, score cap 100, predictive 70 §3.5; tech 730d / tool 365d §3.6; LEVEL_2 at ≥3 bay-days §3.8; dosing 6.0/12.0/0.05/400 §3.3. Every value greps verbatim in PRD.md; no dead scaffold-only constants carried.

## Final check

- `py_compile` clean on all 10 files (one real bug caught and fixed during verification: `compute_neglect_score` parameter typo).
- `import test_helpers` clean; all 70+ spot-checked public names resolve; `ApiClient` exposes 89 methods (85 endpoints + 4 base conveniences).
- No hardcoded ports/hostnames/URLs anywhere (grep-verified).
- Distinct-per-owner identity builders present and used inside fixtures; clock helper `set_logical_clock` present; no fixture reads wall-clock and none uses dates earlier than 2026-09-01T00:00:00Z.

## Step 5b: Generate difficulty tests (subagent, Stage 2A) — 2026-10-02T02:20:00.000Z

Orchestrator verification before this entry: `pytest --collect-only` = 38 tests, 0 errors; independent AST tag-audit = 38 test functions, 38 well-formed `Design: Difficulty/...` tags, 0 malformed.

Verbatim subagent summary:

Stage 2A complete. All 19 Queue-A instances translated; both final checks pass.

**Per-instance coverage table** (Difficulty/<rule_id>/<instance> → test file::test function):

| Instance | Tests |
|---|---|
| dual_variant_calc/claim_proration_time_based_vs_mileage_based | test_difficulty_dual_variant_calc.py::test_base_warranty_proration_uses_elapsed_days_and_daily_rate, ::test_extended_emissions_proration_uses_accumulated_miles_and_per_mile_rate |
| dual_variant_calc/core_credit_provisional_vs_final | test_difficulty_dual_variant_calc.py::test_provisional_core_credit_is_flat_sixty_percent_posted_at_confirm, ::test_final_core_credit_grade_b_settles_delta_to_center_ledger |
| combinatorial_formula/neglect_score_tiered_band_gating | test_difficulty_combinatorial_formula.py::test_approve_full_rejected_when_neglect_score_in_deny_band, ::test_deny_neglect_decision_succeeds_and_increments_fleet_count |
| combinatorial_formula/proration_daily_rate_rounding_order | test_difficulty_combinatorial_formula.py::test_partial_proration_rounds_daily_rate_before_multiplying, ::test_partial_proration_share_capped_at_half_and_money_balances |
| combinatorial_formula/reman_invoice_evaluation_order | test_difficulty_combinatorial_formula.py::test_final_core_credit_capped_against_effective_price_with_surcharge, ::test_invoice_total_is_effective_price_minus_final_credit |
| non_linear_state_machine/claim_review_cycle_two_rounds_then_must_decide | test_difficulty_non_linear_state_machine.py::test_third_request_info_rejected_when_review_rounds_exhausted, ::test_claim_still_adjudicates_after_review_cycle_exhausted |
| non_linear_state_machine/campaign_completion_review_revert_loop | test_difficulty_non_linear_state_machine.py::test_completion_review_below_threshold_parks_campaign, ::test_resume_execution_reverts_campaign_to_in_progress |
| transitive_cascade/work_order_verify_four_hop_close_releases_family | test_difficulty_transitive_cascade.py::test_verify_remediates_unit_and_recomputes_campaign_rate, ::test_verify_closes_campaign_and_releases_family_from_hold |
| transitive_cascade/core_reject_three_hop_suspends_center | test_difficulty_transitive_cascade.py::test_first_core_reject_reverses_provisional_credit, ::test_second_core_reject_suspends_service_center |
| priority_pair_validation_conflict/claim_state_gate_beats_coverage_temporal_gate | test_difficulty_priority_pair_validation_conflict.py::test_unit_state_gate_precedes_coverage_expiry_on_claim_filing, ::test_rejected_filing_leaves_no_claim_row |
| priority_pair_validation_conflict/work_order_technician_safety_beats_capacity_fiscal | test_difficulty_priority_pair_validation_conflict.py::test_technician_qualification_gate_precedes_bay_capacity, ::test_qualified_work_order_survives_rejected_conflicting_pairing |
| boundary_precision_check/conformity_ratio_exactly_at_threshold_conforms | test_difficulty_boundary_precision_check.py::test_conformity_ratio_exactly_at_threshold_conforms, ::test_conformity_ratio_below_threshold_restamps_family_non_conforming |
| boundary_precision_check/core_return_exactly_on_due_date_accepted | test_difficulty_boundary_precision_check.py::test_core_received_exactly_at_return_deadline_accepted, ::test_core_received_one_day_late_rejected_then_forfeits |
| cross_entity_state_dependency/claim_create_gated_by_engine_unit_lifecycle | test_difficulty_cross_entity_state_dependency.py::test_claim_filing_rejected_when_unit_decommissioned_despite_open_coverage, ::test_identical_filing_on_in_service_unit_succeeds |
| cross_entity_state_dependency/work_order_gated_by_service_center_authorization | test_difficulty_cross_entity_state_dependency.py::test_work_order_rejected_when_center_suspended, ::test_rejected_work_order_leaves_unit_campaign_open |
| resource_temporal_overlap/lab_window_half_open_adjacency | test_difficulty_resource_temporal_overlap.py::test_adjacent_lab_windows_allowed_under_half_open_semantics, ::test_interior_lab_overlap_rejected_and_other_lab_unaffected |
| resource_temporal_overlap/bay_capacity_day_bucket_aggregate | test_difficulty_resource_temporal_overlap.py::test_work_orders_sharing_day_at_exact_capacity_allowed, ::test_order_exceeding_day_bucket_capacity_rejected |
| compensating_invariant/bay_day_occupancy_restored_by_cancel | test_difficulty_compensating_invariant.py::test_overlapping_order_rejected_while_single_bay_occupied, ::test_cancelling_order_restores_bay_capacity |
| compensating_invariant/core_credit_ledger_confirm_then_forfeit_nets_zero | test_difficulty_compensating_invariant.py::test_core_credit_ledger_tracks_confirm_and_grade_delta, ::test_compensating_forfeit_returns_ledger_to_effective_credit_sum |

**SKIPPED instances: none.** Every instance passed the PRD-first two-condition filter; all asserted rules have verbatim PRD prose (§2.6, §2.8, §3.2–§3.9) and uniquely-derived outcomes (rounding orders, gate priorities, and boundary inclusivity are all explicitly pinned in the PRD).

**File list (line counts), all under test_suite/:**
- test_difficulty_dual_variant_calc.py — 211
- test_difficulty_combinatorial_formula.py — 264
- test_difficulty_non_linear_state_machine.py — 213
- test_difficulty_transitive_cascade.py — 220
- test_difficulty_priority_pair_validation_conflict.py — 196
- test_difficulty_boundary_precision_check.py — 201
- test_difficulty_cross_entity_state_dependency.py — 183
- test_difficulty_resource_temporal_overlap.py — 187
- test_difficulty_compensating_invariant.py — 230

Total: 1905 lines, **38 tests collected** (2 per instance).

**pytest --collect-only verdict:** clean — `38 tests collected in 0.32s`, no collection errors.

**AST tag-audit verdict:** PASS — every test function's docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` line, all 19 tags resolve to non-stub §1.8 instances, all 19 instances covered with ≥2 tests. A separate verbatim sweep matched all **83 PRD citations** against PRD.md (whitespace-normalized literal containment).

**validate_error_is_one_of uses: none.** All error assertions use exact `validate_error` with the registered HTTP status map (ERR_UNIT_NOT_IN_SERVICE 409, ERR_TECHNICIAN_NOT_QUALIFIED 409, ERR_CAPACITY_EXCEEDED 409, ERR_LAB_WINDOW_OVERLAP 409, ERR_REVIEW_ROUNDS_EXHAUSTED 409, ERR_CENTER_NOT_AUTHORIZED 409, ERR_CORE_RETURN_WINDOW_CLOSED 409, ERR_DECISION_INCONSISTENT_WITH_SCORE 422) — the PRD pins each specific error_id, so no relaxation was warranted.

**Key implementation choices:**
- All clock literals are ≥ the 2026-09-01T00:00:00Z startup clock (max advance 2029-01-02 for the coverage-expired pairing); no clock-reachability re-derivation was needed.
- Resource-creating POSTs asserted with explicit `validate_success(resp, 201)`; transitions default 200.
- OCC-safe: reman orders go through `setup_reman_order_*` which re-reads the unit version immediately before create; no hardcoded versions anywhere.
- Identity: fleet/center ownership threaded via `make_fleet_manager_headers(fleet["id"])` / `make_service_advisor_headers(center["id"])`; segregation-of-duties handled inside the frozen family fixtures (SUBMITTER ce-quinn ≠ CERTIFIER ro-mara).
- No files under test_helpers/ or conftest.py were modified.

## Step 5c: Generate corner tests (subagent, Stage 2B) — 2026-10-02T03:10:00.000Z

Orchestrator verification before this entry: `pytest --collect-only` = 116 tests, 0 errors; independent AST tag-diff against both design indices: 97 expected non-stub instances, 97 distinct Design tags in tests, 0 missing, 0 extra, 7 stubs correctly excluded. Test suite is measurably complete.

Verbatim subagent summary:

Stage 2B complete. All checks green.

**Per-section coverage (78/78 non-stub instances translated, 0 skipped, 0 untranslated):**
- entities → 11/11
- state_machines → 16/16
- calculations → 10/10
- validations → 25/25
- endpoints → 3/3
- errors → 1/1 (7 `excluded_because` stubs correctly not translated)
- rbac → 6/6
- cross_cutting_layers → 5/5
- consistency_model → 1/1

**File list (test_suite/, line counts):**
- test_corner_entities.py (214), test_corner_entities_2.py (232)
- test_corner_state_machines.py (294), test_corner_state_machines_2.py (353)
- test_corner_calculations.py (240), test_corner_calculations_2.py (306)
- test_corner_validations.py (306), test_corner_validations_2.py (369), test_corner_validations_3.py (302)
- test_corner_endpoints.py (148), test_corner_errors.py (35), test_corner_rbac.py (191)
- test_corner_cross_cutting.py (286), test_corner_consistency_model.py (65)
- Total new: 14 files, 3341 lines, **78 corner tests**; grand total collected **116** (38 difficulty + 78 corner).

**pytest --collect-only verdict:** clean — `116 tests collected`, no collection errors. AST tag-audit verdict: clean — every corner test's docstring ends with exactly one `Design: Corner/<section>/<name>` line as its last line; all 78 tags resolve to non-stub §1.9 instances; no stub tagged; no duplicates. Separately, all 151 PRD citations in the new files pass a verbatim 8-word-window grep against workspace/PRD.md.

**validate_error_is_one_of uses:** none — every asserted error is pinned to a single PRD-named error_id.

**Translation decisions worth flagging:**
1. `Corner/validations/work_order_for_unit_not_flagged_by_campaign_rejected` — the recipe's literal path (register unit UN-LATE *after* announce) is unreachable under the PRD: announce moves the family to COMPLIANCE_HOLD, and unit registration requires IN_PRODUCTION (`ERR_FAMILY_NOT_IN_PRODUCTION`). Translated via a PRD-legal equivalent: the unit is remedied under the campaign (CAMPAIGN_OPEN→REMEDIED via verify), then a second work order for that same-family IN_SERVICE unit fails `ERR_UNIT_CAMPAIGN_NOT_OPEN` — the identical gate and error_id the instance asserts, with no ambiguity about which gate fires.
2. Timestamp assertions (certified_at, expires_at, announced_at, paid_at, verified_at, last_snapshot_at, coverage ends) compare parsed instants (`datetime.fromisoformat`) against the PRD-pinned values — the PRD pins the stamped instant ("stamped from the logical clock") while §2.5 leaves the fractional-digit representation open; the exact instant is still asserted. Not a weakening.
3. `engine_unit_model_year_copied_from_family` sends `model_year: 2099` in the create payload to directly exercise the verbatim PRD rule "any client-supplied value for it is ignored", asserting the stored value equals the family's 2027.
4. No-op clock sets to the startup default (the `k_clock0` anchors) were omitted — conftest guarantees the clock starts at 2026-09-01T00:00:00Z; every non-default clock state is set explicitly via `set_logical_clock`.
5. OCC tests capture parent versions from live reads, never literals; RBAC denials thread entity-backed identities (`make_fleet_manager_headers(fleet.id)` / `make_service_advisor_headers(center.id)`) so each 403 comes from the role gate; the segregation-of-duties pair uses SUBMITTER `ce-quinn` vs CERTIFIER `ro-mara`.

No files under test_helpers/, conftest.py, or the Stage 2A test_difficulty_*.py files were modified.

## Step 6: Generate implementation (subagent) — 2026-10-02T04:05:00.000Z

Steps 5 and 6 ran SEQUENTIALLY (endpoint constraint); the isolation rule was enforced via the verbatim read-ban in the Step 6 prompt instead of concurrency.

Orchestrator verification before this entry: py_compile clean on all impl files; `bash -n start.sh` clean; start.sh guards pip install and uses exec; constant spot-check (0.6 / 1.15 / 1.3 / 0.9-inclusive-0.9000 / 0.95 / clock 2026-09-01T00:00:00Z) matches PRD; neglect constants (25/15/20, cap 100, bands 30/60) identical across calculations.py, test_helpers/constants.py, and PRD §3.7 prose; no wall-clock reads; no persistence/seeding.

Verbatim subagent summary:

Implementation complete and verified. Here is the exit summary for the worklog.

## File list (all in `workspace/implementation/`), line counts

| File | Lines |
|---|---|
| start.sh | 10 |
| requirements.txt | 1 (flask>=2.0) |
| clock.py | 56 |
| store.py | 34 |
| errors.py | 10 |
| rbac.py | 45 |
| validators.py | 237 |
| calculations.py | 248 |
| cascade.py | 61 |
| app.py | 89 |
| regulation_standards.py | 117 |
| engine_families.py | 228 |
| aftertreatment_specs.py | 106 |
| test_runs.py | 124 |
| fleets_units.py | 223 |
| telematics.py | 84 |
| service_network.py | 243 |
| warranty.py | 205 |
| campaigns.py | 153 |
| work_orders.py | 190 |
| reman.py | 211 |
| in_use_compliance.py | 53 |

**Endpoint count: 85/85** (verified by enumerating the Flask url_map; matches PRD §4 exactly, including `POST /_clock/set_current_utc`).

## Guards implemented → PRD section mapping

- Auth headers + role admission (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER 400 / ERR_FORBIDDEN_FOR_ROLE 403) — §2.1, §2.8 priorities 1-2; in `rbac.py`.
- Request shape (enums, ranges, required fields, `component_type` iff `reman_scope==COMPONENT`, `scheduled_end > scheduled_start`, pagination limit 1..100/offset>=0) — §2.8 priority 3; `validators.py`.
- Existence left-to-right, path ids before body FKs — §2.8 priority 4 + §2.8 note.
- Ownership: FleetManager↔fleet_id, ServiceAdvisor↔service_center_id on claim create/resubmit, maintenance create, WO create/start/complete/cancel, reman create/confirm/receive/forfeit/close — §2.1, §2.8 priority 5.
- Segregation of duties on certify (passes when submitted_by null) — §3.2, priority 6.
- State gates: unit IN_SERVICE → filer fleet ACTIVE → center AUTHORIZED on claim create (§3.7 pinned order); family IN_PRODUCTION for unit create/in-use results; family DESIGN/TESTING for spec create/activate; campaign IN_PROGRESS + unit CAMPAIGN_OPEN for WO create; standard PUBLISHED for family create/certify/supersede-successor; result PASS for review-accept; no open campaigns for phase-out; all generic from-state gates — priority 7.
- OCC on the two pinned endpoints only (spec create, reman create), missing field → ERR_INVALID_REQUEST — §2.7, priority 8.
- Technician qualification (center membership, lazy CERT_ACTIVE, endorsed, LEVEL_2+ when bay_days>=3), decision-band consistency, authorize needs qualified tech — §3.6-3.8, priority 9.
- Referential: supersession window strictly later, model-year in window, RECALL requires NON_CONFORMING, spec activate requires CALIBRATED — priority 10.
- Uniqueness/structural: standard code, family_code/model_year, serial/family, badge/center, tool serial, campaign code/family, FTP/RMC/SET accepted coverage, active spec, lab half-open overlap, published-window overlap, review rounds < 2, notified > 0, decommission blockers, sample_size >= 5 — priority 11.
- Temporal: coverage windows (strict `<`, extended precedence), core receive `<=` deadline inclusive, forfeit strictly after, odometer/hours monotonic, recorded_at strictly after, in_service_date `<=` clock, service odometer bound — §3.4/3.5/3.7/3.9, priority 12.
- Bay capacity day-bucket check last — §3.8, priority 13.
- Calculations per §3 with pinned rounding: adjusted emissions 4dp half-up (equality passes), dosing target 2dp + deviation 4dp (0.0500 calibrates), conformity 4dp (0.9000 conforms), completion rate 4dp, neglect score (25/15/20, cap 100, bands 30/60), proration rate-first rounding with 50% share cap (TIME_BASED vs MILEAGE_BASED), core credit 0.6 provisional / grade 1.0-0.75-0.5 / 40%-of-effective-price cap (surcharge included), spec multipliers 1.0/1.15/1.3, fault risk 40/20/5 + drift ÷10 cap 30 + DEF-zero 25 cap 100 latch 70 — §2.6, §3.3-3.9.
- Cascades with per-hop version bumps: announce (family hold + unit flagging), verify 4-hop, completion-review same-request close, DENY→fleet count + suspend-at-3, REJECT/FORFEIT→ledger reversal + suspend-at-2 — §2.9, §3.7-3.9.
- Lazy EXPIRED/RECAL_DUE with strictly-greater comparison, materialized (with version bump) on every read and use — §2.4.

## Interpretations chosen (PRD left open)

1. **Fleet `fleet_code` uniqueness** — §3.4 says "unique program-wide" but the error catalog and §2.8 priority-11 list contain no fleet-code duplicate error; implemented no rejection check (no error id exists to return).
2. **Coverage read `extended_applies_to`** — scaffold types it as a plain string; returned the comma-joined emissions class list `"AFTERTREATMENT_SCR,AFTERTREATMENT_DPF,DOSING_SYSTEM,NOX_SENSOR,EGR_SYSTEM"`; `extended_covered` evaluates the time/miles/hours legs only (component class is a claim-time input).
3. **Pagination bounds** — limit outside 1..100 or offset < 0 or non-integer → ERR_INVALID_REQUEST 400 (rejected, not clamped), reading §2.3's bounds as constraints.
4. **Clock endpoint echo** — echoes the `current_utc` input string verbatim ("echoes that current_utc back"); all other stamped timestamps render canonical ISO with 3 fractional digits from the logical clock.
5. **`api_request_timestamp`** — reads the logical clock (§2.4: every stamped timestamp reads this clock), not wall-clock.
6. **Technician create into REVOKED center** — §3.6 forbids it without naming an error; mapped to ERR_INVALID_STATE_TRANSITION 409. Diagnostic-tool create has no stated center-state gate, so none was added.
7. **Verify hop 1** — unit flips CAMPAIGN_OPEN→REMEDIED only when currently CAMPAIGN_OPEN (the only defined source state); the rest of the cascade runs regardless.
8. **Version starts at 1**; created_at == updated_at at create.
9. **Lazy materialization on "use"** — recertify/recalibrate/authorize/work-order-create first materialize (version bump) then evaluate, per §2.4's "any read or use" + "each materialization is a mutation".
10. **Certify check order** — SoD (6) → UNDER_REVIEW + standard PUBLISHED (7) → accepted coverage (11), per §2.8 priorities overriding the scaffold's precondition listing order.

## Self-smoke-test transcript

- **Shallow boot smoke**: dynamic port 38017, `bash start.sh` backgrounded (PID 3861802), polled `GET /emissions/regulation-standards` → 200 with empty array. Then: no-headers → 400 ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER; create standard → 201 DRAFT v1 with `created_at 2026-09-01T00:00:00.000Z`; read-back → 200; duplicate code → 409; RegulatoryOfficer create → 403 ERR_FORBIDDEN_FOR_ROLE; publish → 200 PUBLISHED v2; clock set → 200 echoes input; family create → 201 DESIGN/NOT_TESTED; list meta pagination fields present; limit=0 → 400; missing id → 404. Killed exactly PID 3861802.
- **Deep smoke** (fresh server, another dynamic port): full pipeline exercised — spec OCC (412 stale, family version bump), calibrate (target 7.5, CALIBRATED), 3 test runs PASS/ACCEPT, submit-review, SoD 403 for submitter-as-certifier, certify, enter-production; unit + coverage read; snapshot (score 6, monotonicity 409s); maintenance (odometer-exceeds 422); center audit/authorize (ERR_NO_QUALIFIED_TECHNICIAN then success); claim → review cycle → inconsistent-decision 422 → APPROVE_FULL → PAID; in-use 8/10 → NON_CONFORMING (sample<5 → 422); RECALL announce cascade (family hold, unit flagged); work-order create/start/complete/verify cascade (unit REMEDIED, rate 1.0, completion-review closes campaign, family released to IN_PRODUCTION); reman full money path (surcharge 15000, provisional 12000, grade A final 20000 capped check, invoice 95000, ledger delta +8000, close); REJECT + late-forfeit reversal cascade suspending center at 2 reversals, reinstate resets; lazy EXPIRED/RECAL_DUE at 2030 clock, recertify/recalibrate. 3 initial FAILs were smoke-script expectation errors (lab-overlap test ran after the blocker run was already ACCEPTED — ACCEPTED runs don't block per §3.3; ledger arithmetic), confirmed by a focused re-run: overlap vs SCHEDULED → 409, adjacency → 201, different lab → 201, end==start → 400. Final deep smoke: **0 real failures, 0 HTTP 500s in server log**.

## Confirmations

- `python3 -m py_compile` clean on all 21 Python files; `bash -n` clean on start.sh; `__pycache__` removed.
- In-memory dicts only; no SQLite/JSON-dump/open()/pickle anywhere (grep clean); `start.sh` re-invocation wipes all state (fresh process).
- No seeding: store starts empty; no `seed_*` anywhere (grep clean).
- No wall-clock reads anywhere (no `datetime.now`/`time.time`/`utcnow`); clock default 2026-09-01T00:00:00Z.
- start.sh guards the pip install (`if ! python3 -c "import flask"`), uses `exec`, binds 0.0.0.0:$PORT (default 10000).
- Measured cold boot to first HTTP response: **~0.6s**.
- Did not read SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/; did not run the test suite. Only PIDs started by this session were killed (saved `$!` each time; no pkill/killall).

## Step 7: Run tests and iterate (subagent) — 2026-10-02T03:55:00.000Z

Orchestrator verification before this entry: all 8 `results.{i}.json` files present (fresh, 03:46), each parsed and confirmed passed=116/total=116/failed=0/errors=0. Dead-code audit: grep confirms every calculations.py/cascade.py/telematics.py helper has a real call site (the naive AST scan's 105 "unreferenced" hits were decorator-registered Flask route handlers plus import-alias artifacts — false positives).

Verbatim subagent summary:

Clean 8-round parallel sweep on the first iteration — no failures to diagnose.

Summary:
- Iterations run: 1
- Tests deleted: none
- Fixes applied to `test_helpers/`: none
- Fixes applied to `test_suite/`: none
- Fixes applied to `implementation/`: none
- Final results.*.json inventory: 8 files present in `workspace/implementation/`, each passed == total == 116:
  - results.1.json: 116/116
  - results.2.json: 116/116
  - results.3.json: 116/116
  - results.4.json: 116/116
  - results.5.json: 116/116
  - results.6.json: 116/116
  - results.7.json: 116/116
  - results.8.json: 116/116

The implementation and test suite are stable — no flakiness surfaced across 8 concurrent rounds under per-test-server isolation, so no diagnostic steps were triggered.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T03:55:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — zero iterations beyond baseline, so PRD.md already determines every behavior the implementation exhibits. No PRD_FINALIZED.md produced. Step 9 (always runs) will read PRD.md directly. Note for Step 9: Step 6's "interpretations chosen" list (10 items, see Step 6 worklog entry) names the places impl picked a behavior PRD left open — those are the expected ambiguity-pin sites.

## Step 9: Complete PRD (subagent) — 2026-10-02T04:40:00.000Z

Orchestrator verification before this entry: `diff -q PRD.md PRD_COMPLETED.md` → differ (no silent no-op); claimed edits spot-verified verbatim (§2.8 extra-fields-ignored clause, §3.4 extended_applies_to comma-joined list, §3.6 RECAL_DUE-gated recalibration); newest impl source mtime 03:34 and newest test source mtime 03:01 both PREDATE the 03:46 sweep results → no post-Step-7 writes, sweep remains authoritative; all 8 results.*.json still present.

Orchestrator adjudication of the 1 mismatch-revision (memory protocol: read Step 9's mismatch list as potentially lost scaffold intent and consider fixing impl instead): the fleet_code uniqueness claim was considered for an impl-side fix, but the scaffold's error catalog defines no duplicate-fleet-code error id and §2.8 assigns it no precedence slot — enforcing it would require inventing contract surface (new error id, HTTP status, precedence position) that no layer defines, and would invalidate the clean sweep. Accepted the PRD revision documenting actual behavior.

Verbatim subagent summary:

All 16 inserted phrases verified present exactly once (the §2.3 edit carried two clauses on one line, hence 14 changed lines for 15 edits). Task complete.

**Completion proof:** `diff -q PRD.md PRD_COMPLETED.md` → "Files PRD.md and PRD_COMPLETED.md differ". Line counts: 400 → 400 (all edits are in-paragraph; no lines added or removed). Char delta: 70,414 → 72,822 (+2,408). 14 lines changed. Latest sweep (results.8.json) was already clean at 116/116; Step 7 made zero fixes, tests used only as auxiliary cross-reference.

**Counts:** 14 ambiguity-pins, 1 mismatch-revision, 0 impl-omission escalations. All 10 known open choices verified against code and pinned.

**Changes (one bullet each):**
- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, not wall-clock — implementation/validators.py:34,46
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400, never clamped — implementation/validators.py:160-181
- §2.3 — insert — ambiguity — `created_at` ties broken by creation (insertion) order; `has_more` true exactly when `offset`+`limit` < `total_count` — implementation/validators.py:184-194
- §2.4 — insert — ambiguity — clock endpoint echoes the request's `current_utc` string verbatim, unparseable values rejected 400 — implementation/app.py:70-81
- §2.4 — insert — ambiguity — lazy materialization also fires on in-request reads by other endpoints (authorize/recertify/recalibrate/work-order create+start), persists even when the enclosing request is rejected, and a materialize-then-mutate in one request increments `version` twice — implementation/cascade.py:14-25; service_network.py:78,179,235; work_orders.py:61,126
- §2.5 — insert — ambiguity — `version` starts at 1, `created_at` == `updated_at` at creation — implementation/validators.py:201-210
- §2.8 item 3 — insert — ambiguity — request fields beyond those an endpoint names are ignored — implementation/validators.py:64-141 (all extractors use `.get`)
- §3.2 — insert — ambiguity — certify's three gates evaluate in §2.8 order: segregation of duties, then state gates (UNDER_REVIEW, standard still PUBLISHED), then accepted coverage — implementation/engine_families.py:144-159
- §3.3 — revise — ambiguity — `deterioration_factor` is set to 1.0 at creation and any client-supplied value is ignored (PRD said "defaulting to 1.0 when not supplied"); authoritative value arrives at record-results — implementation/test_runs.py:36-52,70
- §3.3 — insert — ambiguity — zero dosing target (zero displacement) yields deviation 0 — implementation/calculations.py:82-83
- §3.4 — revise — mismatch — `fleet_code` stored as supplied with no duplicate rejection (PRD claimed program-wide uniqueness; per known-choices directive, pinned to impl rather than escalated) — implementation/fleets_units.py:23-39
- §3.4 — insert — ambiguity — coverage read's `extended_covered` evaluates only the time/miles/hours legs (no component class in scope); `extended_applies_to` is the comma-joined five-class list — implementation/fleets_units.py:161-174; calculations.py:109-138
- §3.6 — revise — ambiguity — technician create into a REVOKED center rejected `ERR_INVALID_STATE_TRANSITION` 409, and that is the only center-state gate (APPLIED/AUDITED/SUSPENDED permitted) — implementation/service_network.py:137-140
- §3.6 — insert — ambiguity — diagnostic-tool issuance has no center-state gate — implementation/service_network.py:194-216
- §3.6 — insert — ambiguity — tool recalibration is available only while `RECAL_DUE`; a `CALIBRATED_ACTIVE` tool rejects with `ERR_INVALID_STATE_TRANSITION` 409 — implementation/service_network.py:231-243
- §3.8 — revise — ambiguity — verify hop 1 flips the unit to `REMEDIED` only when currently `CAMPAIGN_OPEN`; otherwise the unit is left unchanged (campaign counters still increment) — implementation/work_orders.py:163-173

**Impl-omission escalations:** none — no site found where the PRD affirmatively states a behavior the impl simply lacks (the fleet_code case is the one known-choice explicitly designated for pinning, and every other PRD claim — all 85 endpoints, every cascade hop, rounding order, threshold inclusivity, error catalogue mapping — was verified present in code).

## Pipeline complete — 2026-10-02T04:45:00.000Z

Final state: 116/116 tests passing across 8/8 concurrent per-test-server isolation rounds, zero fixes needed anywhere in the pipeline; PRD_COMPLETED.md is the final contract (PRD_FINALIZED.md absent because Step 8's skip condition was met).
