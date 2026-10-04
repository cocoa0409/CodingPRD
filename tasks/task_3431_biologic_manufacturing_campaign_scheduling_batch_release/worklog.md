# Worklog — task_3431_biologic_manufacturing_campaign_scheduling_batch_release

## Step 1: Create Task Directory — 2026-10-02T01:19:00.000Z

Task directory `./tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/` was pre-allocated by the caller with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created. `INSTRUCTION.md` and `skills/prd-bench-scaffold-generator/SKILL.md` confirmed present at project root.

## Step 2: Generate Scaffold — 2026-10-02T02:24:00.000Z

Scaffold generation complete for **task_3431_biologic_manufacturing_campaign_scheduling_batch_release**. All three artifacts are written, parse cleanly, and `scaffold_lint.py` reports **VERDICT: clean lint** (1343 setup/trigger calls checked, zero violations).

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/SCAFFOLD.yaml` (1744 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1640 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/SCAFFOLD_CORNER_DESIGN.yaml` (2348 lines)

**Counts**
- Entities: **13** (Site, Product, BioreactorTrain, Campaign, SeedTrainStage, BatchLot, InProcessTest, Deviation, Shipment, TemperatureReading, ComparabilityStudy, RegulatoryInspection, MaterialLot)
- State machines: **9** — non-linear shapes on Campaign (ALLOCATED⇄PROPOSED cycle + system PREEMPTED), BatchLot (parallel process×quality dimensions with an UNDER_INVESTIGATION hold-return loop), SeedTrainStage (FAILED/EXPIRED→RUNNING retry cycles), Deviation (CLOSED⇄REOPENED), ComparabilityStudy (NOT_COMPARABLE→PROTOCOL_APPROVED rework loop), Shipment (EXCURSION_HOLD branch)
- Endpoints: **42** (at the ~40 ceiling; depth carried by rules, not sprawl)
- Calculations: **11** — incl. per-component nested rounding for allocated hours (order pinned), clinical-over-commercial preemption waterfall with deterministic selector, MKT excursion evaluation (ΔH/R = 10000.0 exactly; 3-guard, 3-dp pin), single-pass-outlier comparability equivalence (mode-c evaluation order pinned), posture threshold aggregation
- Validations: **30** ordered rows; Errors: **52**; Roles: **8** (segregation-of-duties model: SoD on disposition vs manufacturer/verifier IDs, four-eyes on test verification)
- §1.8 instances: **21** (all nine rules at ≥2; modes/domains/pairs differentiated; all formula-derived asserts pre-computed as literals, e.g. provisional 400000 vs final 625000 yield, MKT 7.621/9.000 boundary, margin 2.9408)
- §1.9 instances: **60** (56 active + 4 `excluded_because` stubs)
- api_prefix: **`/`** (multi-root collections; the lint's FK segment derivation works from the declared single-resource GETs)
- Concurrency: 1 OCC rule (`expected_batch_version` on test record/retest, ERR_STALE_BATCH_VERSION 412)

**Difficulty levers (beyond-expert, rules-first):** posture-driven gating (site FROZEN/CONDITIONAL/CLEAR recomputed from deviations + inspection findings, gating commercial release), two transitive cascades of depth 3 and 2 (OOS verify → auto-deviation → posture freeze → campaign preemption; confirmed complaint → batch quarantine → shipment quarantine with unit restoration), seed-train viability windows with backward-expiry recovery, and a logical clock defaulting to 2026-09-01T00:00:00Z.

**Notable design fixes made during authoring:** added the COMPLETED→EXPIRED system transition (twice — including the inoculation-window failure path) so a blown window can't deadlock a campaign; normalized all nested path params to `{id}` after lint flagged the sub-resource FK check; repaired two YAML hazards (a list-index capture needing quotes inside a flow mapping, and two aliases illegally carrying `captures:` keys).

Orchestrator verification: all three YAML files parse via yaml.safe_load; top-level keys correct (SCAFFOLD.yaml has api_prefix/entities/endpoints/...; DIFFICULTY has single key scaffold_difficulty_design; CORNER has single key scaffold_corner_design); 394 domain-token hits (bioreactor|campaign|batch|seed_train|deviation|cold_chain|temperature|comparability) in SCAFFOLD.yaml; api_prefix "/". Files not truncated.

## Step 3: Copy Shared Files — 2026-10-02T02:25:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T02:44:00.000Z

All audits pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/workspace/PRD.md` — **333 lines** (long prose paragraphs), ending at §5 with no audit footer. The withheld design-index files were never opened; no sibling task directories were touched.

**Section list:** 1. Introduction · 2. Global Specifications (2.1 RBAC, 2.2 API Response Structure [byte-identical to canonical block], 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Nested Retrieval & Validation Ordering, 2.7 Precision/Rounding/Units, 2.8 OCC, 2.9 Site Release Posture & Freeze Cascade, 2.10 Four-Eyes & Segregation of Duties, 2.11 Firm Capacity & Cold Storage) · 3. Business Logic (3.1 Master Data, 3.2 Campaign Scheduling & Capacity Waterfall, 3.3 Seed Train & Timing Windows, 3.4 Batch Processing/Testing/Yield, 3.5 Deviations & Disposition, 3.6 Distribution & Cold Chain, 3.7 Comparability & Inspections) · 4. Endpoint Definitions (42 rows, 4 columns) · 5. Error Code Catalogue (52 rows, 2 columns).

**Coverage self-audit (scaffold vs PRD):**
- Entities: 13 / 13 (TemperatureReading's absent `updated_at`/`version` stated explicitly)
- State machines: 9 / 9, incl. BatchLot's two parallel dimensions
- Transitions: 49 / 49 (41 distinct prose probes matched, incl. both seed-stage retry paths, both COMPLETED→EXPIRED triggers, all 3 quarantine-cascade sources, the NOT_COMPARABLE rework loop)
- Calculations: 11 / 11 — all constants verbatim (8h/24h/4h blocks; 36h/24h windows with inclusive boundaries; titer 2.0 × 125 × 0.8; ΔH/R = 10000.0 exactly from 83.14472/0.008314472; MKT allowances 1.0/5.0/0.5, 3-decimal pre-comparison rounding; comparability 1.5σ exclusion, margins 1.5 and 0.03, 4-decimal round-half-up, pinned compute-once order; overage 1.10 at 2 decimals; freeze threshold ≥2; 720-hour shelf gate; clock default 2026-09-01T00:00:00Z)
- Validations: 30 / 30, with the 7-stage global pipeline and per-endpoint orderings stated (OCC before business; supersede before phase; window before capacity; single-source before shortage; disposition gate order state→SoD→posture→shelf-life→comparability)
- Errors: 52 / 52 in §5 and each trigger expressed in §2/§3 prose
- Roles: 8 / 8 with per-role opaque-identity prose and full §4 permission mapping
- Endpoints: 42 / 42, including all query filters

**Hard contracts:** Contract 1 PASS (101/101 identifiers in backticks, 0 missing); Contract 2 PASS (49 transitions, 11 calculations, 30 validations, 1 OCC rule with `expected_batch_version`/`ERR_STALE_BATCH_VERSION`/412, all side-effect cascades and sibling branches expressed); Contract 3 PASS (650 §3 backtick tokens, 0 path/method violations); §2.2 byte-identical; fuzzy-word scan clean (0 hits).

One judgment call to flag: the scaffold requires batch creation only from `PRODUCTION_IN_PROGRESS` campaigns but names no error for it; I mapped the rejection to `ERR_INVALID_CAMPAIGN_STATE` (the catalog's campaign-state guard) rather than leave the rule untestable.

Orchestrator verification: PRD.md exists at 333 lines; 89 `ERR_` mentions; key constants present verbatim (10000.0 kinetic ratio, 2026-09-01T00:00:00Z clock default, ERR_STALE_BATCH_VERSION/412 OCC).

## Step 5a: Generate Test Helpers (Stage 1 of split Step 5) — 2026-10-02T03:05:00.000Z

Stage 1 is complete and verified. All 13 files parse (`ast.parse` clean), and the package imports end-to-end (`import test_helpers` → 184 exported names, error map registered with the framework, no circulars).

## Files written

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 26 |
| `test_helpers/constants.py` | 50 |
| `test_helpers/types.py` | 178 |
| `test_helpers/entity_types.py` | 200 |
| `test_helpers/api_errors.py` | 128 |
| `test_helpers/api_client.py` | 152 |
| `test_helpers/test_users.py` | 75 |
| `test_helpers/factories.py` | 140 |
| `test_helpers/assertions.py` | 180 |
| `test_helpers/fixtures_core.py` | 191 |
| `test_helpers/fixtures_batch.py` | 243 |
| `test_helpers/fixtures.py` | 9 (re-export shim) |
| `test_suite/conftest.py` | 69 |

No `test_suite/test_*.py` files were written — that's Stage 2. All paths under `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/`.

Domain specifics handled: OCC endpoint `create_test` carries `expected_batch_version` in payload (412 `ERR_STALE_BATCH_VERSION` registered); all 8 roles get distinct stable identities with multiples for SoD/four-eyes (`op-1`/`op-9`, `qc-1`/`qc-2`, `qa-1`/`qa-2`/`qa-3`); all roles are `identity: opaque` per scaffold so shared constants are canonical and builders exist for identity-threading; logical clock helper `set_logical_clock` + `iso_shift` derive all datetimes from the clock; `DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"`, `FIXTURE_CLOCK_START = "2026-10-01T00:00:00Z"`; all constants copied from PRD §2–§3 (no dead constants); `TemperatureReading` TypedDict and assertion carry only `id`/`created_at` (assertion also asserts `updated_at`/`version` absence per PRD §2.5); api_prefix "/" handled by root-absolute paths.

## Public API surface (Stage 2 contract)

**Framework re-exports via `test_helpers/__init__.py`:** `validate_success(response, expected_status=200)`, `validate_error`, `validate_paginated`, `validate_error_is_one_of`, `get_success_data`, `is_valid_uuid`, `is_iso8601_timestamp`, `assert_cost_precision`, `assert_version_incremented`, `assert_timestamp_format`, `assert_race_outcome`, `assert_exactly_one_succeeds`, `assert_at_least_one_succeeds`, `run_race`, `build_user_headers`, `NON_EXISTENT_UUID`.

**constants.py** (26 names): `DEFAULT_CLOCK_UTC`, `FIXTURE_CLOCK_START`, `SEED_SHIFT_HOURS=8`, `PRODUCTION_BLOCK_HOURS=24`, `CHANGEOVER_BLOCK_HOURS=4`, `TRANSFER_WINDOW_HOURS=36`, `INOCULATION_WINDOW_HOURS=24`, `DESIGN_TITER_G_PER_L=2.0`, `UNITS_PER_GRAM=125`, `PROVISIONAL_RECOVERY_FACTOR=0.8`, `EXCURSION_SPIKE_GUARD_C=5.0`, `EXCURSION_FREEZE_GUARD_C=0.5`, `EXCURSION_COUNT_GUARD=2`, `DELTA_H_KJ_MOL=83.14472`, `R_GAS=0.008314472`, `MKT_KINETIC_RATIO=10000.0`, `MKT_ALLOWANCE_C=1.0`, `SPIKE_ALLOWANCE_C=5.0`, `FREEZE_ALLOWANCE_C=0.5`, `SCREENING_MAX_EXCURSION_COUNT=2`, `MIN_REMAINING_SHELF_LIFE_HOURS=720`, `EXCLUSION_SIGMA=1.5`, `ABS_MARGIN=1.5`, `REL_MARGIN=0.03`, `CRITICAL_DEVIATION_FREEZE_THRESHOLD=2`, `OVERAGE_FACTOR=0.10`.

**types.py** — enums (all `str, Enum`): `UserRole`, `ReleasePosture`, `CampaignStatus`, `SeedStageStatus`, `BatchProcessStatus`, `BatchQualityStatus`, `TestStatus`, `TestType`, `TestPhase`, `DeviationKind`, `DeviationSeverity`, `DeviationStatus`, `DeviationConclusion`, `ShipmentStatus`, `ExcursionEvaluation`, `EvaluationVariant`, `StudyStatus`, `ChangeType`, `InspectionStatus`, `MaterialLotStatus`, `MoleculeType`, `MarketScope`, `DemandType`, `Authority`. Re-exports TypedDicts from entity_types.py: `ManufacturingSite`, `Product`, `BioreactorTrain`, `Campaign`, `SeedTrainStage`, `BatchLot`, `InProcessTest`, `Deviation`, `Shipment`, `TemperatureReading`, `ComparabilityStudy`, `RegulatoryInspection`, `MaterialLot`.

**api_errors.py**: `ApiErrorId` (52 members, exact PRD §5 catalog incl. `ERR_STALE_BATCH_VERSION`, `ERR_MARKET_SCOPE_VIOLATION` 422), `HTTP_STATUS_CODES: dict` (registered via `set_error_http_status_map` at import).

**api_client.py**: `api_client` singleton, `class ApiClient(GenericApiClient)` with 42 methods (one per PRD §4 endpoint): `set_clock(current_utc, headers)`; `create_site(payload, headers)`, `get_site(site_id, headers)`; `create_train(site_id, payload, headers)`, `list_trains(site_id, headers, params=None)`; `create_material(site_id, payload, headers)`, `list_materials(site_id, headers, params=None)`, `hold_material(material_id, quarantined, headers)`; `create_inspection(site_id, payload, headers)`, `list_inspections(site_id, headers, params=None)`, `inspection_action(inspection_id, payload, headers)`; `create_product(payload, headers)`, `get_product(product_id, headers)`; `create_comparability_study(product_id, payload, headers)`, `list_comparability_studies(product_id, headers, params=None)`, `study_action(study_id, action, authority=None)`; `create_campaign(train_id, payload, headers)`, `list_campaigns(headers, params=None)`, `get_campaign(campaign_id, headers)`, `advance_campaign(campaign_id, to_status, headers)`; `create_seed_stage(campaign_id, payload, headers)`, `list_seed_stages(campaign_id, headers, params=None)`, `advance_seed_stage(stage_id, to_status, headers)`; `create_batch(campaign_id, payload, headers)`, `list_batches(campaign_id, headers, params=None)`, `get_batch(batch_id, headers)`, `advance_batch(batch_id, to_status, headers)`, `submit_batch_for_review(batch_id, headers)`, `disposition_batch(batch_id, payload, headers)`; `create_test(batch_id, payload, headers)`, `list_tests(batch_id, headers, params=None)`, `verify_test(test_id, headers)`; `create_deviation(batch_id, payload, headers)`, `list_deviations(batch_id, headers, params=None)`, `deviation_action(deviation_id, payload, headers)`; `create_shipment(batch_id, payload, headers)`, `list_shipments(batch_id, headers, params=None)`, `get_shipment(shipment_id, headers)`, `shipment_action(shipment_id, action, headers)`, `create_reading(shipment_id, payload, headers)`, `list_readings(shipment_id, headers, params=None)`, `evaluate_excursion(shipment_id, headers)`.

**test_users.py**: `USER_IDS` (keys: admin/engineer/operator/operator_2/analyst/analyst_2/reviewer/reviewer_2/reviewer_3/planner/regulatory → `"admin-1"`,`"pe-1"`,`"op-1"`,`"op-9"`,`"qc-1"`,`"qc-2"`,`"qa-1"`,`"qa-2"`,`"qa-3"`,`"sp-1"`,`"ra-1"`); `TEST_USERS` (11 keys: `platform_admin_headers`, `process_engineer_headers`, `manufacturing_operator_headers`, `manufacturing_operator_2_headers`, `quality_control_analyst_headers`, `quality_control_analyst_2_headers`, `quality_assurance_reviewer_headers`, `quality_assurance_reviewer_2_headers`, `quality_assurance_reviewer_3_headers`, `supply_planner_headers`, `regulatory_affairs_specialist_headers`); `NO_AUTH_HEADERS`; builders `make_platform_admin_headers(user_id)`, `make_process_engineer_headers(user_id)`, `make_manufacturing_operator_headers(user_id)`, `make_quality_control_analyst_headers(user_id)`, `make_quality_assurance_reviewer_headers(user_id)`, `make_supply_planner_headers(user_id)`, `make_regulatory_affairs_specialist_headers(user_id)`.

**factories.py** (input fields only, `**overrides`): `create_site_payload()`, `create_product_payload()`, `create_train_payload()`, `create_material_payload()`, `create_inspection_payload()`, `create_comparability_study_payload(candidate_batch_ids=None, **overrides)`, `create_campaign_payload(product_id, **overrides)`, `create_seed_stage_payload()`, `create_batch_payload()`, `create_test_payload(expected_batch_version, **overrides)`, `create_deviation_payload()`, `create_shipment_payload()`, `create_reading_payload()`.

**assertions.py**: `assert_site(data)`, `assert_product(data)`, `assert_train(data)`, `assert_material_lot(data)`, `assert_inspection(data)`, `assert_comparability_study(data)`, `assert_campaign(data)`, `assert_seed_stage(data)`, `assert_batch(data)`, `assert_in_process_test(data)`, `assert_deviation(data)`, `assert_shipment(data)`, `assert_temperature_reading(data)`, `assert_site_posture_invariants(data)`, `assert_batch_ledger_invariants(data)`.

**fixtures (via fixtures.py → fixtures_core.py + fixtures_batch.py)** — all use `get_success_data` internally and return entity dicts or env dicts (`{"site", "product", "train", "campaign", "seed_stages", "batch", ...}`):
- fixtures_core: `iso_shift(base_utc, hours=0, seconds=0) -> str`, `set_logical_clock(current_utc=FIXTURE_CLOCK_START)`, `create_site_entity(**overrides)`, `create_product_entity(**overrides)`, `create_train_entity(site_id, **overrides)`, `create_material_lot(site_id, **overrides)`, `create_inspection_entity(site_id, **overrides)`, `create_study_entity(product_id, candidate_batch_ids, **overrides)`, `study_action(study_id, action, authority=None)`, `inspection_action(inspection_id, action, findings=None, response_summary=None)`, `create_campaign_entity(train_id, product_id, **overrides)`, `setup_master_data(clock_utc=FIXTURE_CLOCK_START, set_clock=True, site_overrides=None, product_overrides=None, train_overrides=None)`, `setup_campaign(clock_utc=FIXTURE_CLOCK_START, set_clock=True, site_overrides=None, product_overrides=None, train_overrides=None, campaign_overrides=None)`, `advance_campaign(campaign_id, to_status)`, `setup_allocated_campaign(**kwargs)`, `add_seed_stage(campaign_id, stage_index=1, planned_duration_hours=10)`, `advance_seed_stage(stage_id, to_status)`, `run_seed_stage_to_completed(stage_id, duration_hours, start_clock_utc) -> (stage, finish_utc)`, `seed_campaign(campaign_id, stage_durations=(10, 8), seed_start_utc=FIXTURE_CLOCK_START) -> {"stages", "last_completed_at"}`, `setup_campaign_in_production(stage_durations=(10, 8), **kwargs)`.
- fixtures_batch: `DEFAULT_TITER_VALUES=(2.4, 2.6)`, `create_batch_entity(campaign_id, lot_number="LOT-0001", operator_user_id="op-1")`, `get_batch_entity(batch_id)`, `advance_batch(batch_id, to_status, operator_user_id="op-1")`, `record_test(batch_id, batch_version=None, operator_user_id="op-1", **overrides)` (None re-reads fresh OCC version), `verify_test_entity(test_id, analyst_user_id="qc-1")`, `record_and_verify_test(batch_id, batch_version=None, **overrides) -> (verified_test, new_batch_version)`, `setup_batch_upstream(**chain_kwargs)`, `setup_batch_with_verified_upstream(**chain_kwargs)`, `setup_batch_downstream(**chain_kwargs)`, `setup_batch_process_complete(titer_values=DEFAULT_TITER_VALUES, **chain_kwargs)` (final yield 625000 on default 2000 L train), `setup_batch_pending_disposition(**chain_kwargs)`, `setup_released_batch(**chain_kwargs)`, `submit_batch_for_review(batch_id, reviewer_user_id="qa-1")`, `disposition_batch(batch_id, decision="RELEASED", rationale="All specifications met", reviewer_user_id="qa-1")`, `create_deviation_entity(batch_id, kind="PROCESS", severity="MINOR", description="Deviation under test", headers=None)`, `deviation_action(deviation_id, payload, reviewer_user_id="qa-1")`, `close_deviation(conclusion, capa_summary=None, reviewer_user_id="qa-1")`, `reopen_deviation(deviation_id, justification="New information received", reviewer_user_id="qa-1")`, `create_shipment_entity(batch_id, quantity_units=1000, market_type="COMMERCIAL", destination_region="IE-DUB", planner_user_id="sp-1")`, `shipment_action(shipment_id, action, planner_user_id="sp-1")`, `create_reading_entity(shipment_id, temperature_c, recorded_at="2026-10-02T01:00:00Z", planner_user_id="sp-1")`, `record_readings(shipment_id, temperatures, start_utc="2026-10-02T01:00:00Z", step_hours=1) -> list`, `evaluate_excursion(shipment_id, reviewer_user_id="qa-2")`, `setup_shipment_in_transit(quantity_units=1000, market_type="COMMERCIAL", **chain_kwargs)`.

**test_suite/conftest.py** fixtures: `api` (session-scoped `ApiClient`), plus `platform_admin_headers`, `process_engineer_headers`, `manufacturing_operator_headers`, `manufacturing_operator_2_headers`, `quality_control_analyst_headers`, `quality_control_analyst_2_headers`, `quality_assurance_reviewer_headers`, `quality_assurance_reviewer_2_headers`, `quality_assurance_reviewer_3_headers`, `supply_planner_headers`, `regulatory_affairs_specialist_headers`.

Notes for Stage 2: canonical identity threading is manufactured-by `op-1`, verified-by `qc-1`, dispositioned-by `qa-1` (SoD-clean); creates return 201 — pass `expected_status=201` to `validate_success` on all create endpoints; the seed chain in `setup_campaign_in_production` derives its seed-start instant from `campaign_overrides["planned_start_utc"]` so the start-too-early gate holds by construction; `run_race` is available for the OCC race form but the sequential stale-version form is already supported via `record_test(batch_id, batch_version=<stale>)`.

Orchestrator verification: `import test_helpers` → 184 exported names; all 11 submodules import via importlib; `ApiClient` has 46 public methods; `ApiErrorId` has 52 members.

## Step 5b: Generate Test Suite (Stage 2 of split Step 5) — 2026-10-02T03:38:00.000Z

All checks pass. Generation complete.

## Summary

**16 test files written** to `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/test_suite/` (conftest.py untouched, frozen helpers only imported):

| File | Tests |
|---|---|
| test_01_master_data_envelope.py | 8 |
| test_02_campaign_listing_consistency.py | 2 |
| test_03_campaign_batch_state_machines.py | 4 |
| test_04_train_window_rules.py | 6 |
| test_05_capacity_waterfall.py | 5 |
| test_06_seed_train_timing.py | 9 |
| test_07_material_coverage.py | 4 |
| test_08_batch_creation_yield.py | 6 |
| test_09_in_process_testing.py | 10 |
| test_10_deviations.py | 5 |
| test_11_disposition_controls.py | 6 |
| test_12_disposition_site_gates.py | 6 |
| test_13_comparability_studies.py | 7 |
| test_14_shipments_cold_storage.py | 9 |
| test_15_excursion_evaluation.py | 5 |
| test_16_posture_freeze_cascades.py | 6 |

**Total: 98 tests — queue A: 42 (21/21 instances, exactly 2 each); queue B: 56 (56/56 non-stub instances, 1 each).**

**Queue A tags** (each on 2 tests): `Difficulty/dual_variant_calc/{batch_yield_provisional_then_final_diverge, excursion_screening_vs_mkt_verdicts_diverge}`, `Difficulty/combinatorial_formula/{allocated_hours_per_component_rounding_order, mkt_three_guard_boundary_at_allowance, comparability_single_pass_outlier_exclusion}`, `Difficulty/non_linear_state_machine/{campaign_allocate_deallocate_reallocate_cycle, batch_parallel_dimensions_evolve_independently, deviation_close_reopen_close_cycle}`, `Difficulty/transitive_cascade/{oos_verify_cascades_to_posture_freeze_and_campaign_preemption, complaint_confirm_cascades_batch_and_shipment_quarantine}`, `Difficulty/priority_pair_validation_conflict/{disposition_state_error_precedes_posture_freeze, shipment_create_referential_error_precedes_storage_fiscal}`, `Difficulty/boundary_precision_check/{train_changeover_gap_exact_boundary, critical_deviation_count_threshold_boundary}`, `Difficulty/cross_entity_state_dependency/{disposition_gated_by_inspection_driven_posture, seed_start_gated_by_single_source_material_stock, commercial_release_gated_by_comparability_filing}`, `Difficulty/resource_temporal_overlap/{train_window_buffered_adjacency_overlap_semantics, cold_storage_aggregate_capacity_overlap_semantics}`, `Difficulty/compensating_invariant/{allocate_deallocate_roundtrip_conserves_capacity_hours, shipment_create_cancel_roundtrip_conserves_sellable_units}`.

**Queue B tags**: all 56 non-stub instances across sections `entities` (8), `state_machines` (8), `calculations` (6), `validations` (26), `errors` (1), `rbac` (4), `complexity_layers` (2), `consistency_model` (1) — verified by AST tag audit.

**Skipped instances** (the 4 `excluded_because:` stubs, not translated per spec; all cross-references verified to resolve to real queue-A instances):
1. `Corner/validations/shipment_create_requires_released_batch` — owned by `priority_pair_validation_conflict/shipment_create_referential_error_precedes_storage_fiscal`
2. `Corner/complexity_layers/oos_posture_freeze_cascade` — owned by `transitive_cascade/oos_verify_cascades_to_posture_freeze_and_campaign_preemption`
3. `Corner/complexity_layers/excursion_dual_variant_verdicts` — owned by `dual_variant_calc/excursion_screening_vs_mkt_verdicts_diverge`
4. `Corner/complexity_layers/batch_yield_variant_switch_at_process_complete` — owned by `dual_variant_calc/batch_yield_provisional_then_final_diverge`

No PRD-first filter skips were needed — every non-stub instance had verbatim PRD coverage with a uniquely derivable outcome.

**Verification performed**: (1) `ast.parse` on all 17 files in test_suite/ — OK; (2) AST tag audit — no untagged/dual-tagged/orphaned tests, all stub cross-refs resolve, coverage counts exact; (3) all 148 PRD citation lines literal-grep against PRD.md — 0 failures (three §4 table citations were rewritten to verbatim table-row text after the first sweep flagged pseudo-quotes).

**Judgment calls**: timestamp asserts on clock-stamped fields (`started_at`, `expiry_utc`) use prefix matching since PRD doesn't pin `...Z` vs `....000Z` serialization (two-reader relaxation); the MKT literal 7.621 is asserted only through the ACCEPTABLE verdict (the PRD shipment serializer exposes no MKT value field — asserting one would be a computed-field violation); identity threading follows the frozen canonical chain (op-1 manufactures, qc-1 verifies, qa-1 dispositions, qa-2 evaluates excursions, colliding identities only in SoD/four-eyes negatives).

Orchestrator verification (independent): AST-walked all test_suite/test_*.py — 77 unique Design tags on 98 tests (21 Difficulty + 56 Corner), 0 missing vs indices, 0 orphan tags, 0 stub-tagged tests, 0 queue-B duplicates, 0 untagged tests. `pytest --collect-only` collects 98 tests in 0.40s with no import errors.

## Step 6: Generate Implementation — 2026-10-02T03:53:00.000Z

Everything is clean — the only remaining `app.py` processes belong to other tasks (3360, 3429), untouched. My servers are all stopped, `start.sh` is executable, and `__pycache__` is removed.

## Summary

Complete Python + Flask implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/workspace/implementation/`. Both self-smoke-suites pass end-to-end from a fresh boot; no server left running.

### File list (22 source files + launcher + deps; all ≤ 250 lines)

| File | Lines | Role |
|---|---|---|
| start.sh | 9 | exec launcher, PORT env (default 10000), 0.0.0.0, guarded pip install |
| requirements.txt | 1 | flask>=3.0 |
| app.py | 63 | bootstrap, ApiError/404/405/500 handlers, blueprint registration |
| constants.py | 88 | every constant defined exactly once (clock default 2026-09-01T00:00:00Z, 8/24/4 blocks, 36/24h windows, titer 2.0/125/0.8, kinetic ratio 10000.0, 1.0/5.0/0.5 allowances, 720h, 1.5σ/1.5/0.03 margins, freeze threshold 2, overage 0.10, all enum vocabularies) |
| errors.py | 85 | ApiError + full 52-id catalog |
| clock.py | 67 | logical clock, ISO parse/format (3 fractional digits, second precision) |
| store.py | 70 | in-memory dicts, empty at boot, version=1 at create, touch() bumps |
| envelope.py | 43 | meta/api_request_id/response_type/data envelope + pagination meta |
| auth.py | 40 | X-User-ID/X-User-Role presence + per-endpoint role check |
| validate.py | 169 | body/field validators, existence fetchers, pagination |
| serialize.py | 231 | per-entity wire format, live `available_to_ship_units` |
| posture.py | 81 | site_release_posture recompute + one-way freeze cascade |
| calc_capacity.py | 164 | allocated_hours, window conflict, capacity waterfall w/ preemption, material coverage + consumption |
| calc_quality.py | 110 | batch yield (provisional/final), excursion SCREENING/MKT, comparability equivalence |
| routes_clock.py, routes_master.py, routes_products.py, routes_inspections.py, routes_comparability.py, routes_campaigns.py, routes_seed.py, routes_batches.py, routes_tests.py, routes_deviations.py, routes_shipments.py | 18–189 each | per-domain route modules |

### Counts
- **Endpoints: 42/42** (verified via Flask url_map; 43rd entry is Flask's built-in `/static` rule)
- **Error catalog: 52/52** (verified by counting `ERROR_CATALOG`)
- **State machines: 9/9** — Campaign (incl. system preemption/completion), BatchLot (two parallel dimensions + hold/return + quarantine), SeedTrainStage (incl. EXPIRED flip side-effects), InProcessTest (OOS auto-deviation), Deviation (close/reopen + cascades), Shipment (excursion hold/evaluate + cascades), ComparabilityStudy (rework loop), RegulatoryInspection, MaterialLot
- All 11 calculations, 30 validations (in PRD §2.6 pipeline order), 8 roles implemented.

### Interpretation choices (PRD left open — candidate over/under-guards for audit)
1. `version` starts at **1** at creation (PRD never pins the initial value).
2. All entity timestamps (`created_at`, `updated_at`, `started_at`, etc.) read the **logical clock** (scaffold's preemption note about "positioning the clock between creations" implies it), emitted as `....Z` with exactly 3 fractional digits.
3. Clock-set endpoint returns the **normalized** `current_utc` (`.000Z` form), not the raw input string.
4. Datetime parsing truncates fractional seconds (PRD second-precision rule); numeric offsets accepted, converted to UTC.
5. Unknown role strings (incl. literal `Any`) → **ERR_FORBIDDEN_ROLE** (403); header check is presence-only.
6. Out-of-range/non-integer `limit`/`offset` → **ERR_INVALID_REQUEST** (chose rejection over clamping; PRD says limit "must lie between" 1 and 100).
7. Uniqueness of `product_code`, `train_code`-within-site, `stage_index`-within-campaign enforced with **ERR_INVALID_REQUEST** (PRD says "unique" but names no error id).
8. List filter query params are exact-match with **no validation** of filter values (unknown value → empty page).
9. An **insertion sequence number** breaks all created_at ties (window predecessor, preemption rank, most-recent study, most-recent VERIFIED PURITY test) — needed because the logical clock may not move between creations.
10. Material coverage precedence read **globally**: all single-source shortfalls checked before any generic shortage (scaffold priorities 24<25 + "evaluated before"), not purely per-entry.
11. Auto-created OOS deviation `description` is synthesized text; PRD doesn't specify content.
12. `version`/`updated_at` bumped on **every** mutation including system cascades (PRD 2.5); site touched only when a counter/posture actually changes.
13. Disposition requires `rationale` present (any string); `expected_batch_version` must be present+integer (400 stage-4) before the 412 comparison (stage-5).
14. Temperature readings accepted in **any** shipment state (no PRD-stated guard — deliberately not invented); excursion detection fires only while IN_TRANSIT per the machine.
15. Material lot `quantity` has no positivity check (PRD states none).
16. Invalid `decision` values → ERR_INVALID_REQUEST (ERR_UNSUPPORTED_ACTION scoped to `action`/`to_status` only).
17. Well-formedness (stage 4) runs **before** state admission (stage 6) per PRD §2.6 pipeline + scaffold priorities — e.g. inadmissible conclusion on a CLOSED deviation returns 400, not 409. (PRD §3.5 narrative lists state first; followed the explicit pipeline.)
18. Seed transfer window uses the **highest lower-indexed stage** as predecessor when indices skip; no check if no lower stage exists.
19. No guards invented: no state guard on seed-stage creation, no lot_number uniqueness, no OCC outside POST /batches/{id}/tests, no ownership checks beyond PRD's SoD/four-eyes.

### Smoke-test transcript (2 fresh boots, dynamic ports, servers killed afterward)
- **Suite 1 (happy path, 77 calls, all pass):** auth negatives (400 no headers, 403 wrong role) → clock set 200 → site 201/get 200 → train 201/list 200 → material 201/hold/release 200 → product 201/get 200 → campaign 201 (`allocated_hours=176` = ceil(100/8)·8 + ceil(50/24)·24 + 0) → allocate 200 → 2 seed stages 201 → seed start 200 (materials consumed) → stages RUNNING/COMPLETED 200 → production start 200 → batch 201 (provisional 400000 = 2000·2.0·125·0.8) → OCC stale 412 → tests 201, four-eyes 403, verify 200 → DOWNSTREAM 200 → titer/purity 201+verify 200 → PROCESS_COMPLETE 200 (final 525000 = floor(2.1·2000·125), expiry +2000h, campaign auto-COMPLETED) → submit-for-review 200 → SoD 403 → RELEASED 200 → shipment 201 → SHIP 200 → 4 readings 201 (4th triggers EXCURSION_HOLD via count>2) → evaluate 200 (**ACCEPTABLE/MKT/IN_TRANSIT**) → DELIVER 200 → deviation 201 (OOS manual create 400) → close/reopen/reclose 200 → inspection 201 → ISSUE_FINDINGS 200 (posture **FROZEN**) → CLOSE 200 (posture **CLEAR**) → study 201 → APPROVE 200 → RECORD_ASSESSMENT 200 (**COMPARABLE, baseline_mean 99, margin 2.97** — matches hand computation) → SUBMIT_FILING 200.
- **Suite 2 (edge paths, 66 calls, all pass):** window conflict 409 + exact-4h-gap allowed; CLINICAL preemption (ALLOCATED COMMERCIAL → PREEMPTED, hours released); unsupported to_status 400; seed start too early 409; stage order violation 409; transfer window 36h+1s → 409 with predecessor flipped to **EXPIRED**, retry path works; OOS verify → auto deviation (OOS/MAJOR/OPEN/`system`); inadmissible conclusion 400; INVALIDATED_TEST close → test INVALIDATED → retest with `supersedes_test_id` 201; phase mismatch 409; two CRITICAL deviations → posture CONDITIONAL → FROZEN with PROPOSED COMMERCIAL campaign auto-PREEMPTED.

Orchestrator verification: 24 files present in implementation/ (22 .py + start.sh + requirements.txt), all compile via py_compile, start.sh passes bash -n and is executable.

## Step 7: Run Tests and Iterate — 2026-10-02T04:05:00.000Z

All 8 sweep rounds pass 98/98 with the required artifacts preserved.

## Summary

- **Iterations run**: 2 (baseline sweep: 93/98 with 5 deterministic failures, identical across all 8 rounds; post-fix sweep: 98/98 × 8 rounds, all clean, zero flakiness observed).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/test_suite/test_08_batch_creation_yield.py` — `test_process_dimension_moves_while_quality_stays_in_testing`: second `setup_batch_downstream()` call now passes `product_overrides={"product_code": "MAB-002"}`. The test builds two independent environments against one server; both defaulted to `MAB-001`, tripping the PRD-required uniqueness check (PRD §3.2: "A product master is created with a unique `product_code`"). Fix matches the suite's own convention (test_07's `_MEDIA_PRODUCT`/`_SINGLE_SOURCE_PRODUCT` overrides).
- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/workspace/implementation/store.py` — `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.1 (line 88) verbatim requires "a server-minted UUID, with no type prefix"; the dashless hex form failed the canonical-UUID assertion in 4 tests (site/campaign/batch/shipment create). One-line impl fix covering all entity types since every create path funnels through `create_rec` → `new_id`.

Orchestrator verification (independent): all 8 `results.${i}.json` files present in workspace/implementation/; each reports passed=98 total=98 failed=0 errors=0. Step 8 is NOT skipped (1 implementation/ fix occurred).

## Step 8: Finalize PRD — 2026-10-02T04:19:00.000Z

**ZERO-EDIT OUTCOME.** `/home/ubuntu/github/CodingPRD/tasks/task_3431_biologic_manufacturing_campaign_scheduling_batch_release/workspace/PRD_FINALIZED.md` is a byte-identical copy of PRD.md (both 333 lines, md5 `04369314497d9951033b96d90cbb8579`, diff -q clean). 0% delta.

**Per-item justification (verbatim pinning quotes):**

- **test_suite fix — `test_08_batch_creation_yield.py` (second `setup_batch_downstream()` now passes `product_overrides={"product_code": "MAB-002"}`)**: Pure fixture bug, not a PRD silence. The test built two independent environment chains against one shared server; both defaulted to `MAB-001`, tripping a check the PRD already requires. Pinning quote, PRD §3.1 (line 155): *"A **product** master is created with a unique `product_code`"*. (Note: the step_7_diff narrative cites §3.2; the actual text lives in §3.1 — quote is verbatim.) The impl enforces this at `implementation/routes_products.py:37-39` (rejects duplicates with `ERR_INVALID_REQUEST`). The fix changed only the fixture to stop colliding with an already-pinned rule — no behavior was left open, so no PRD edit.

- **implementation fix — `store.py` `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`**: Impl mismatch repaired toward an already-pinning PRD, not a PRD silence. Pinning quote, PRD §2.5 (line 88): *"`id` (string): a server-minted UUID, with no type prefix."* (step_7_diff cites §2.1; actual location is §2.5.) "A UUID" denotes the canonical RFC 4122 hyphenated string form — what `str(uuid.uuid4())` produces; Python's `.hex` is explicitly a 32-char hex serialization, not the UUID string representation. Step 7's adjudication direction confirms this reading: the 4 canonical-UUID test assertions (site/campaign/batch/shipment create) were kept intact and the impl was changed — an assertion survives Step 7 only when the PRD is judged to pin it. The current wording therefore already determines the fixed behavior; pinning it further would be a manufactured edit.

**Pre-edit search log (performed for adjudication; no edits committed):**

1. Subject: entity `id` format.
   - (b) Enumerated paths: `implementation/store.py:32-33` (`new_id()` = `str(uuid.uuid4())`), funneled through `create_rec` at `store.py:41-44`; all 14 create sites confirmed via grep: `routes_master.py:31,64,90`, `routes_products.py:40`, `routes_campaigns.py:52`, `routes_seed.py:26`, `routes_batches.py:40`, `routes_tests.py:56,106`, `routes_deviations.py:43`, `routes_shipments.py:59,125`, `routes_inspections.py:24`, `routes_comparability.py:41`. Sole `uuid4` call in the tree is `store.py:33` — every entity type including versionless temperature readings gets the canonical form. Cross-checked the surviving assertion helper `test_helpers/assertions.py:7,161` → `prd_bench_local_runner.testing.is_valid_uuid`, verified empirically: dashed form passes, dashless fails. All enumerated paths are consistent with the existing PRD sentence.
   - (c) No wording committed; existing prose already describes every path.
2. Subject: `product_code` uniqueness.
   - (b) Enumerated paths: `implementation/routes_products.py:19` (input parse), `:37-39` (uniqueness rejection over `store.all_recs("products")`), `:40-41` (create), `serialize.py:49` (output); fixture side at `test_suite/test_08_batch_creation_yield.py:101`.
   - (c) No wording committed; §3.1 line 155 already pins uniqueness.

No files under `implementation/`, `test_suite/`, or `test_helpers/` were touched — only `workspace/PRD_FINALIZED.md` was created (as an exact copy).

Orchestrator verification (independent): `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical (333 lines each); newest implementation/ source mtime is store.py at 04:02:33 (Step 7's own fix), all others ≤ 03:48 — no Step 8 writes into implementation/.

## Step 9: Complete PRD — 2026-10-02T04:41:00.000Z

The diff contains exactly the intended edits. Final verification of the workspace state is complete. Here is the summary.

## Summary

**Files:** `PRD_FINALIZED.md` (source): 333 lines / 60,579 chars → `PRD_COMPLETED.md`: 338 lines / 64,272 chars (**+5 lines, +3,693 chars**). Only `workspace/PRD_COMPLETED.md` was edited; nothing under `implementation/`, `test_suite/`, or `test_helpers/` was touched.

**Counts:** 23 ambiguity-pins (across 19 edit hunks), **0 mismatch-revisions** — every PRD-pinned rule (all constants, formulas, check orderings, thresholds, cascade semantics, state machines, envelope shape) matched the implementation exactly; no passage required triage toward either side.

**Changes (one bullet each):**
- §2.1 — revise — ambiguity — role header value outside the seven operational roles (incl. literal `Any`) is `ERR_FORBIDDEN_ROLE` (403) on every endpoint — auth.py:35-39
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + twenty random alphanumeric characters — envelope.py:16
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from server wall clock, not the logical clock — envelope.py:17-18
- §2.2 + §5 — insert/revise — ambiguity — transport-level fallbacks `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) pinned as outside the §5 business-error catalogue — app.py:47-59
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, negative `offset` → `ERR_INVALID_REQUEST` — validate.py:142-161
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence; filter params match literally, never existence-validated; unknown query params ignored — store.py:68-70, routes_campaigns.py:70-85
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — store.py:49
- §2.6 — insert — ambiguity — non-object JSON body → `ERR_INVALID_REQUEST`; absent/unparseable body treated as `{}`; unrecognized body fields ignored — validate.py:39-46
- §2.7 — insert — ambiguity — payload datetimes accepted with `Z` or numeric UTC offset (converted); fractional seconds truncated — clock.py:32-50
- §2.7 — insert — ambiguity — integral decimals serialize as JSON integers, else JSON numbers — serialize.py:14-17
- §2.4 — insert — ambiguity — clock accepts any well-formed instant incl. earlier ones; response `data` is `{"current_utc": ...}` — routes_clock.py:13-18
- §3.1 — insert — ambiguity — `licensed_authorities` may be an empty array — routes_master.py:27
- §3.1 — revise — ambiguity — storage band (`min`/`max_storage_temp_c`, max > min) required on every product, cold-chain or not — routes_products.py:23-26
- §3.1 — insert — ambiguity — `base_quantity` carries no positivity constraint — routes_products.py:35
- §3.1 — insert — ambiguity — lot `quantity` carries no positivity constraint — routes_master.py:89
- §3.2 — insert — ambiguity — preemptions performed before waterfall exhaustion are not rolled back — calc_capacity.py:111-117
- §3.3 — insert — ambiguity — seed-stage definition is not gated on campaign status — routes_seed.py:16-34 (no state check exists)
- §3.3 — insert — ambiguity — "the previous stage" is the lower-indexed stage with the greatest `stage_index`; a stage with no lower-indexed stages faces no transfer-window check — routes_seed.py:59-65
- §3.4 — insert — ambiguity — auto-created OOS deviation carries a system-generated `description` naming the test — routes_tests.py:110
- §3.5 — insert — ambiguity — linked-test transitions on close apply only while the test is still `OOS_SUSPECT`; close-after-reopen leaves test status untouched while remaining cascades run — routes_deviations.py:94-103
- §3.6 — revise — ambiguity — shipment `quantity_units` must be a whole unit (integer ≥ 1); fractional/non-numeric → `ERR_INVALID_REQUEST` — routes_shipments.py:38-40
- §3.6 — insert — ambiguity — readings accepted in any shipment status; detection guards screen only readings recorded while `IN_TRANSIT`; out-of-transit readings still count toward guard-3 history — routes_shipments.py:118-146
- §3.7 — insert — ambiguity — rework via `APPROVE_PROTOCOL` retains stored `baseline_mean`/`equivalence_margin` until the next `RECORD_ASSESSMENT` — routes_comparability.py:79-84

**Impl-defect candidates:** none. No PRD-stated rule (validation gate, state guard, error path, cascade, calculation step) was found omitted, contradicted, or made unreachable in the implementation.

**Dead-check audit:**
- (a) Catalogue errors never raised: **none** — all 52 §5 ids have reachable raise sites (12 `ERR_*_NOT_FOUND` via `validate.must_get`, 40 via direct `err()` calls, each traced to a reachable endpoint path).
- (b) Raised but not in catalogue: `ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL` (app.py:47-59) — emitted by Flask fallback handlers directly through `envelope.error_response`, bypassing the `ApiError` catalog lookup, so **no KeyError→500 risk**; now pinned in §2.2/§5 as transport-level fallbacks.
- (c) Guards reading never-written fields: **none** — `release_posture`/counters (posture.py:47-72), `quality_hold_return_status` (writers routes_deviations.py:24-29, routes_tests.py:119-122; reader routes_deviations.py:118-126), `expiry_utc` (written routes_batches.py:101; read only post-completion), batch `version` for OCC — all have writers.

**Observed unreachable-but-PRD-consistent defensive branches** (not defects): routes_tests.py:119-122 (UNDER_INVESTIGATION hold on auto-created CRITICAL OOS — a `RECORDED` test cannot exist once quality leaves `IN_TESTING`, since `PROCESS_COMPLETE` requires every test `VERIFIED`/`INVALIDATED`); routes_tests.py:45-46 (secondary `ERR_TEST_NOT_FOUND` after stage-3 `must_get`; the id stays reachable via stage 3); routes_campaigns.py:134 (`not stages` guard — seed start already requires ≥1 stage).

Orchestrator verification (independent): PRD_COMPLETED.md exists at 338 lines and differs from PRD_FINALIZED.md (`diff -q` reports difference; +5 lines as claimed); newest implementation/ source mtime remains 04:02:33 — no Step 9 writes into implementation/, so the Step 7 clean sweep stays valid; all 8 `results.*.json` files still present in workspace/implementation/.
