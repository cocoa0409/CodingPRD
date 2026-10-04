## Step 1: Create task directory — 2026-10-02T00:31:00.000Z

Pre-allocated directory `tasks/task_3424_barrel_aging_inventory_planning_warehouse_management/` verified present with `workspace/` inside; no new index computed, no other task dir created.

## Step 2: Generate scaffold — 2026-10-02T00:31:00.000Z

All three scaffold artifacts are complete, lint-clean, and self-consistent. Summary:

### Files written

| File | Size | Lines | Contents |
|---|---|---|---|
| `SCAFFOLD.yaml` | 78,605 B | 1,612 | §1.0–§1.7 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 71,952 B | 1,173 | `scaffold_difficulty_design:` — 9 rules × 2 instances = 18 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 133,119 B | 1,785 | `scaffold_corner_design:` — 49 active + 5 `excluded_because` stubs, 9 sections |

**Counts**: 12 entities, 48 endpoints, 25 error codes, 8 roles (all opaque), 8 calculations, 10 state-machine entries, 3 OCC concurrency rules, 10 ordered validation rows.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(48 endpoints, 12 entities, 18+49 instances, 770 calls scanned, 0 violations.) Supplementary audits also clean: 72 unique instance names, zero unbound `${var}` placeholders (setup→trigger closure), zero dangling grounds, all 25 error ids exercised, no forbidden concurrency vocabulary.

### Design decisions worth recording in the worklog

- **Difficulty via density, not sprawl**: 12 entities / 48 endpoints (deliberately above the Expert band's 32 but under the ~50 impl-gen breaking point from prior memory). Maximal coupling instead: every entity participates in at least one cross-entity gate, cascade, or invariant.
- **Archetype**: temporal_windowing primary, compliance_audit secondary; layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + scheduled_actions. Role model is segregation_of_duties (report filer ≠ acceptor via X-User-ID).
- **Signature mechanics**: (1) Barrel has parallel state dimensions (maturation × custody) with a withdraw-requires-DUMPED join gate; (2) dual-variant volume accounting — chronological ledger replay vs statutory season/floor/age rate-table decay — with both variants surfaced per-barrel AND per bonded report; (3) pinned round-per-barrel-THEN-sum loss aggregation (3.04 vs rejected 3.03; 7.92 vs 7.93 — literals computed by executing the formula); (4) posture-driven rickhouse FULL⇄OPERATING flips; (5) BlendBatch revision cycle and BondedPeriodReport amend cycle; (6) 3 true-race OCC rules (blend-component add, reservation create, rotation).
- **Two authoring bugs caught and fixed during self-audit** (both recorded in case they recur downstream): I6's bottling date was 1 day short of its own 2-year age statement (729 vs 730 days — leap-year-free 365-day arithmetic), fixed to 2030-09-01; `ERR_LABEL_NOT_ACTIVE` was referenced by the BlendBatch machine and difficulty instance but missing from §1.6/§1.4 — added to the catalog and pinned into priority 6 (cross-entity state gate, checked before the p7 age-statement rule).
- **Setup-chain shape**: every barrel needs the expansion→approve→clock+lag→commission→slot chain (commission at exactly approved_at + 720 days for a 24-month lag), so all recipes are long but fully replayable; default clock 2026-09-01T00:00:00Z with monotonic non-decreasing enforcement (ERR_CLOCK_REGRESSION).
- **Deliberate scope cuts** (scenario fidelity preserved via fields, not extra tables): cooperage wood/seasoning/char folded into Barrel creation inputs; distillation-volume planning folded into CapacityExpansionProject; sampling modeled as a BarrelAssessment kind with a 30-day buffer rule.

## Step 3: Copy shared files — 2026-10-02T00:32:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T00:58:00.000Z

PRD generation complete. Summary:

**Output**: `workspace/PRD.md` — 323 lines.

**Section list**: §1 Introduction (2 paragraphs, business-deferral angle) · §2.1 RBAC · §2.2 API Response Structure (byte-identical verbatim block, verified) · §2.3 Pagination · §2.4 The Logical Clock and the Uniform Calendar · §2.5 Common Resource Properties and Versioning · §2.6 Volume Arithmetic: Precision and Rounding Doctrine · §2.7 Optimistic Concurrency Control on Parent Versions · §2.8 Nested Resource Retrieval and Identifier Resolution · §2.9 Structural Cascades Between Projects, Rickhouses, and Slots · §2.10 Validation Evaluation Order · §3.1 Capacity: Proposal → Commissioned Rickhouse · §3.2 Filling, Placing, Rotating Barrels · §3.3 Maturation, Angel's Share, Assessment · §3.4 Dumping and Withdrawal · §3.5 Labels, Blend Batches, Age Statement · §3.6 Private Selection and Reservations · §3.7 Bonded-Period Reporting · §4 Endpoint Definitions (48 rows, 4 columns) · §5 Error Code Catalogue (25 rows, 2 columns).

**Hard contract reports**:
- Contract 1 (field coverage): 83 required identifiers (entities + endpoint inputs/query/path params), 83 present in backticks, 0 missing. PASS
- Contract 2 (rule coverage): validation priorities 10/10 expressed as an explicit ordered pipeline with sub-orderings (shape>existence, from-state>cross-entity, label-active>age-statement, quota>eligibility); OCC rules 3/3 (endpoint + `expected_*_version` + error id + 412 each); state transitions 27/27 fully expressed; calculations 8/8 in precise prose (no pseudocode, boundary inclusivity preserved); endpoint side-effects 48/48; sibling-branch groups 6/6 symmetric (dump×2, file×2, abort×2, accept/reject×2, volume variants×2, loss methods×2). PASS
- Contract 3 (§3 path purity): 376 backtick tokens scanned, 0 path/method violations. PASS

**Scaffold-to-prose mapping decisions**: the 10-priority validation table became a numbered §2.10 pipeline; the dual volume doctrines (event-replay ledger vs 90-day-block statutory decay) got full side-by-side formulas in §3.3 with the three rounding doctrines concentrated in §2.6; all 8 roles share one combined opaque-identity sentence in §2.1; null-until-event lifecycle fields are stated as one §2.5 sentence; withdrawal coverage keeps the scaffold's inclusive `period_start ≤ now ≤ period_end` bounds, deliberately distinct from the half-open overlap rule; list-endpoint filter params are enumerated in §2.3 for field coverage without schema tables.

One verification note: an initial coverage scan false-alarmed because the naive backtick tokenizer miscounted across §2.2's fenced JSON blocks — stripping fenced blocks before token extraction fixed the check (document itself was never defective). The two forbidden design-index files were never opened.

### Subagent's own appended entry (written directly to this file by the subagent):

- Output: workspace/PRD.md, 323 lines. Sections: 1 Introduction; 2.1-2.10 globals (RBAC, verbatim 2.2 envelope, pagination, logical clock + uniform calendar, common properties, precision doctrine, OCC, nested retrieval, structural cascades, validation evaluation order); 3.1-3.7 workflows (capacity planning, barrel fill/placement/rotation, maturation + dual volume doctrines, dump/withdraw, labels/blends, private selection, bonded reporting); 4 endpoint table (48 rows); 5 error catalogue (25 rows).
- Hard contracts: Contract 1 field coverage 83/83 present; Contract 3 section-3 path purity 376 tokens, 0 violations; section 2.2 emitted byte-identical to section-2.2-response-structure.md; all 25 error ids and all 29 state values appear in prose.
- Mapping decisions:
  - The 10-priority validation table was rendered as an explicit numbered pipeline in section 2.10, with sub-orderings called out in prose (payload-shape before existence; from-state before cross-entity gates; label-ACTIVE before age-statement; quota before barrel eligibility).
  - The two volume doctrines (ledger replay vs statutory 90-day-block decay) were given side-by-side full-formula prose in section 3.3; rounding doctrine contrast (per-event vs round-once vs round-then-sum) concentrated in section 2.6 and restated per workflow.
  - All role identities are opaque in the scaffold, so section 2.1 carries one combined identity sentence naming all eight roles plus the segregation-of-duties comparison caveat.
  - Null-until-event semantics for lifecycle fields (approved_at, commissioned_at, validated_at, committed_at, final_blend_volume_liters, withdrawn_at, withdrawn_volume_liters) were stated as a standalone sentence in section 2.5 rather than scattered.
  - Withdrawal coverage check uses inclusive period bounds (period_start at-or-before now AND period_end at-or-after now) per scaffold, distinct from the half-open period-overlap rule; both phrasings preserved.
  - Query-param filters enumerated in section 2.3 per list endpoint to satisfy field-name coverage without a schema table.

## Step 5a: Generate test helpers (Stage 1 of 2) — 2026-10-02T01:15:00.000Z

Stage 1 is complete and frozen. Summary follows.

### Files written (all py_compile-clean; package imports cleanly with zero missing symbols)

| File | Bytes | Contents |
|---|---|---|
| `test_helpers/__init__.py` | 1,350 | Barrel export (framework + all PRD-specific modules) |
| `test_helpers/types.py` | 6,319 | 15 enums + 12 entity TypedDicts |
| `test_helpers/api_client.py` | 8,737 | `ApiClient(GenericApiClient)` with 48 endpoint methods (all PRD §4 rows) + `api_client` singleton |
| `test_helpers/api_errors.py` | 3,080 | `ApiErrorId` (25 errors) + `HTTP_STATUS_CODES` + framework registration |
| `test_helpers/assertions.py` | 12,401 | 13 entity asserters + `assert_heat_factor` + `assert_barrel_invariants` |
| `test_helpers/constants.py` | 4,179 | PRD-audited contract constants + `TEST_DEFAULTS` |
| `test_helpers/factories.py` | 4,436 | 11 payload factories (input fields only) |
| `test_helpers/test_users.py` | 3,281 | `TEST_USERS` (8 roles) + 8 `make_*_headers` builders + preparer/officer id constants |
| `test_helpers/fixtures.py` | 18,766 | 38 composite setup helpers |
| `test_suite/conftest.py` | 1,251 | Session `api` fixture + 8 role-header fixtures |

### Exported-symbol index (the Stage 2 contract)

- **types.py**: `UserRole`, `ProjectState`, `RickhousePosture`, `WoodOrigin`, `SpiritType`, `MaturationStatus`, `CustodyStatus`, `MoveReason`, `OccupancyStatus`, `AssessmentKind`, `LabelState`, `BlendBatchState`, `ProgramState`, `ReservationState`, `ReportState`; TypedDicts `CapacityExpansionProject`, `Rickhouse`, `WarehouseSlot`, `Barrel`, `SlotOccupancy`, `BarrelAssessment`, `Label`, `BlendBatch`, `BlendComponent`, `PrivateSelectionProgram`, `BarrelReservation`, `BondedPeriodReport`. Append-only records (SlotOccupancy, BarrelAssessment) carry **only** `id` + `created_at` per PRD §2.5.
- **api_client.py**: `set_clock`, `create/get_expansion_project`, `approve/commission_expansion_project`, `get/list_rickhouses`, `list_rickhouse_slots`, `get_warehouse_slot`, `list_slot_occupancies`, `create/get/list_barrels`, `list_barrel_occupancies/blend_components/reservations/assessments`, `create_barrel_assessment`, `rotate/dump/withdraw_barrel`, `create/get_label`, `activate_label`, `create/get/list_blend_batches`, `add_blend_component`, `list_blend_components`, `validate/revise/commit/abort_blend_batch`, `create/get_private_selection_program`, `list_eligible_barrels`, `create_reservation`, `list_program_reservations`, `consume/release_reservation`, `create/get/list_bonded_reports`, `reconcile/file/accept/reject/amend_bonded_report`.
- **api_errors.py**: `ApiErrorId` (25 ids), `HTTP_STATUS_CODES`.
- **assertions.py**: `assert_expansion_project`, `assert_rickhouse`, `assert_warehouse_slot`, `assert_heat_factor`, `assert_barrel`, `assert_slot_occupancy`, `assert_barrel_assessment`, `assert_label`, `assert_blend_batch`, `assert_blend_component`, `assert_private_selection_program`, `assert_barrel_reservation`, `assert_bonded_period_report`, `assert_barrel_invariants`.
- **factories.py**: `set_clock_payload`, `create_expansion_project_payload`, `create_barrel_payload`, `create_assessment_payload` (kind-conditional), `rotate_barrel_payload`, `create_label_payload`, `create_blend_batch_payload`, `add_blend_component_payload`, `create_program_payload`, `create_reservation_payload`, `create_bonded_report_payload`.
- **constants.py**: `DEFAULT_CLOCK_ISO`, `DAYS_PER_MONTH` (30), `DAYS_PER_YEAR` (365), `BASE_QUARTERLY_RATE` (0.01), `STATUTORY_BLOCK_DAYS` (90), `SEASON_MULTIPLIERS` (0.7/1.0/1.5/1.0), `AGE_MULTIPLIER_UNDER_2Y/2Y_TO_6Y/6Y_PLUS` (1.2/1.0/0.8), `SEASONED_WOOD_THRESHOLD_MONTHS` (18), `SEASONED_WOOD_DISCOUNT` (0.95), `STATUTORY_RATE_CAP` (0.05), `HEAT_FACTOR_BASE/PER_FLOOR/FLOOR_1/FLOOR_2/FLOOR_3` (1.00/0.05/1.00/1.05/1.10), `SAMPLE_BUFFER_DAYS` (30), `CHAR_LEVEL_MIN/MAX` (1/4), `QUALITY_SCORE_MIN/MAX` (0/100), `LIMIT_DEFAULT/MIN/MAX` (10/1/100), `OFFSET_DEFAULT`, `VOLUME_DECIMAL_PLACES` (2), `STANDARD_CONSTRUCTION_LAG_MONTHS` (24), `STANDARD_COMMISSION_ISO`, `STANDARD_FILL_ISO`, `STANDARD_BOTTLING_ISO`, `TEST_DEFAULTS`.
- **test_users.py**: `TEST_USERS` (8 keys: `<role>_headers`), `DEFAULT_PREPARER_USER_ID` (`test-bonded-preparer-1`), `DEFAULT_OFFICER_USER_ID` (`test-compliance-officer-1` — distinct from filer, so default fixtures satisfy segregation of duties), `make_<role>_headers(user_id)` ×8.
- **fixtures.py**: clock/calendar — `set_clock`, `iso_plus_days`, `commission_date_for`; capacity chain — `create_commissioned_rickhouse(reset_clock=True, ready_clock=STANDARD_FILL_ISO, …)` → `{project, rickhouse, slots}` (approves at default clock, computes commission instant as `approved_at + lag*30d` dynamically, verified 2026-09-01 + 720d = 2028-08-21T00:00:00Z); barrels — `fill_placed_barrel`, `fill_mature_barrel` (min_maturation_months=0), `fill_barrels_on_slots`, `setup_barrel_scenario`, `setup_mature_barrel_scenario`, `get_barrel_fresh`, OCC-aware `rotate_barrel` (re-reads version), `dump_barrel`, `withdraw_barrel`, `record_evaporation_reading`, `record_quality_sample` (omits `quality_score` when None); blends — `create_active_label`, `create_blend_batch`, `get_blend_batch_fresh`, `add_component` (fresh OCC version), `create_batch_with_component`, `create_validated_batch`, `create_committed_batch`; programs — `create_program`, `get_program_fresh`, `get_eligible_barrels`, `create_reservation` (fresh OCC version), `consume/release_reservation`, `setup_program_with_mature_barrel`; reports — `create_report`, `reconcile_report` (defaults clock to period_end), `file_report`, `accept_report`, `reject_report`, `amend_report`, `create_reconciled_report`, `create_filed_report`, `create_accepted_report`.

### PRD-vs-scaffold literal conflicts
**None found.** Every contract literal in `constants.py` greps to PRD prose (rate table §3.3, heat §3.1, buffer §3.3, ranges §2.10, pagination §2.3, clock default §2.4); all 25 error HTTP statuses match PRD §5 exactly. The `STANDARD_*` timestamps and `TEST_DEFAULTS` payload values are fixture conventions (aligned to design-recipe arithmetic), clearly marked non-contractual — no dead constants carried. All 8 roles are `identity: opaque` (PRD §2.1), so no entity-backed header threading exists; the only id-sensitive rule is segregation of duties, handled via distinct default preparer/officer ids plus per-instance builders.

### Verification
- `py_compile`: 10/10 pass. `import test_helpers`: all 141 expected public symbols resolve. Calendar sanity checks (commission date, reservation expiry 2028-09-01+45d = 2028-10-16) match the design indices. No `test_*.py` files exist; no "scaffold" references in generated code. test_helpers/ is now frozen for Stage 2.

## Step 5b-1: Difficulty tests (Stage 2, part 1 of 3) — 2026-10-02T01:50:00.000Z

Stage 2 (part 1 of 3) complete. Summary:

### Files written (6 files, 18 tests — one per active §1.8 instance)

| File | Bytes | Tests |
|---|---|---|
| `test_suite/test_difficulty_volume_variants.py` | 8,510 | dual_variant_calc ×2, combinatorial_formula ×2 |
| `test_suite/test_difficulty_state_machines.py` | 8,681 | non_linear_state_machine ×2, cross_entity_state_dependency ×2 |
| `test_suite/test_difficulty_cascades.py` | 5,435 | transitive_cascade ×2 |
| `test_suite/test_difficulty_validation_conflicts.py` | 4,544 | priority_pair_validation_conflict ×2 |
| `test_suite/test_difficulty_boundaries.py` | 3,401 | boundary_precision_check ×2 |
| `test_suite/test_difficulty_temporal.py` | 10,284 | resource_temporal_overlap ×2, compensating_invariant ×2 |

All under `test_suite/`. `test_helpers/` and `conftest.py` untouched (mtimes confirm).

### Skipped instances
None — all 18 passed the PRD-first two-condition filter. The two priority-pair instances are legitimate because PRD §2.10 explicitly orders the gates and states "An earlier gate masks every later one."

### Literal corrections (important — design index contradicts PRD here)
Verified all expected literals by executing the PRD formulas in Decimal arithmetic **before** writing tests. Two instances shipped wrong literals in the design yaml:

- **report_loss_actual_vs_statutory_divergence**: design asserts `loss_actual == 3.02` / `closing == 396.98`. That figure requires replaying the ledger at full precision, but PRD §2.6 pins "rounded to two decimal places, round half up, after every single event — never once at the end" — the readings 198.995/197.995 become 199.00/198.00 in the replay, so per-barrel losses are 1.00 + 2.00. Tests assert the PRD-derived **3.00 / 397.00** (statutory 7.92, opening 400.00 confirmed correct as designed; the headline divergence 3.00 ≠ 7.92 survives).
- **report_loss_round_per_barrel_then_sum**: design asserts **3.04** (vs rejected 3.03). With per-event rounding, per-barrel losses are 1.00/2.00/0.01 → **3.01**, and closing 596.99. Side effect: the two rounding orders now coincide at 3.01, so this instance no longer discriminates round-per-barrel-then-sum from sum-then-round — its discriminating power was built on the design's unrounded-replay error.
- **blend_batch_revision_cycle_commits**: design pins `version == 6`, which assumes initial version 1; PRD pins only "+1 on every mutation". Test asserts relative increments (v_create+5, per-step +1) — two-reader safe.

All other design literals verified correct (191.27, 181.85 with the 8-block rate set, 7.92, and all dates: 2028-08-21 commission, 2032-08-11 maturation, 1460-day age boundary, 2029-03-31 buffer boundary).

### Audit results
- `pytest test_suite/ --collect-only -q`: **18 collected, 0 errors**
- AST tag audit: **18/18 instances covered exactly once**; every test docstring ends with exactly one `Design: Difficulty/<rule>/<name>` line resolving to a real instance; no duplicates, no wrong namespace
- Citation audit: all **32 long (≥8-word) docstring quotes survive verbatim whitespace-normalized grep of PRD.md** (one fix applied: the §2.10 gate-6 quote was re-sliced to avoid markdown bold markers)
- `py_compile`: all 6 files clean

## Step 5b-2: Corner tests A — entities/state_machines/calculations (Stage 2, part 2 of 3) — 2026-10-02T02:15:00.000Z

Done. All three Stage-2 (part 2) files are written, collect cleanly, and pass the tag and citation audits.

### Files written

| File | Size | Tests |
|---|---|---|
| `test_suite/test_corner_entities.py` | 9,778 B | 7 |
| `test_suite/test_corner_state_machines.py` | 13,243 B | 8 |
| `test_suite/test_corner_calculations.py` | 12,471 B | 7 |

### Instance → test mapping
All 22 active instances covered, one test each, same-named: 7 entities (missing fill_volume → ERR_VALIDATION, char_level 5 rejected, undeclared computed field rejected, initial state/system fields, unknown-id 404, list pagination, quality_score omitted → null), 8 state machines (dump-already-dumped, file-OPEN-report, revise-PROPOSED-batch, consume-RELEASED-reservation, bonded-report amend cycle through ACCEPTED with version 7 and `decided_by_user_id`, aborted-batch terminality, label double-activate, program bubble-up lock), 7 calculations (ledger authoritative reset 188.00 → 185.50, statutory recompute on rotation 191.27 → 190.84, eligibility ranking score-DESC/fill-ASC, empty pool 200/[], age one day short → ERR_AGE_STATEMENT_VIOLATION, commit draw == ledger allowed → 0.00, abort-committed restores 200.00 with frozen 120.00).

### Skips
None among active instances. The two `excluded_because:` stubs (`slot_heat_factor_computed_per_floor`, `withdraw_before_dump_join_gate`) were not translated per contract — both difficulty-instance cross-references resolve (`statutory_evaporation_multi_factor_rate`, `barrel_parallel_maturation_and_custody_dimensions`, both present in part-1 files).

### Literal verification / corrections
- **Re-derived all calculation literals against PRD §3.3 in fixed-point arithmetic**: 191.27 = 200×0.988³×0.9916 and 190.84 = 200×0.9874³×0.99118 (block rates 0.012/0.012/0.0084/0.012 and 0.0126/0.0126/0.00882/0.0126, round once at end) — both design literals confirmed. Age boundary: real datetime delta 2028-09-01→2032-08-30 = 1459 days → floor(1459/365)=3 < 4 confirmed.
- **Dropped one sub-assert** in `test_program_locks_when_quota_consumed`: the design's `version == 3` is not uniquely derivable — PRD §3.6 attributes a program-version increment to both the consume and the bubble-up lock transition, so 4 is an equally faithful reading. All unambiguous asserts kept (state LOCKED, `available_slots == 0`, locked-gate ERR_INVALID_STATE_TRANSITION with fresh OCC version, no reservation persisted for barrel 2).
- `ledger_reading_is_authoritative_reset`: interleaved a mid-sequence GET to assert the 188.00 intermediate (design's asserts cover both stages; trigger only read at the end).
- Bonded-report tests pass `at_clock=DEFAULT_CLOCK_ISO` explicitly — the `reconcile_report` fixture's default would set the clock to `period_end` (2026-07-01), a regression against the current 2026-09-01 clock.
- Citation fix: dropped the `**Payload shape** —` bold-marker prefix from one §2.10 quote so it survives a literal grep.

### Audits
- `pytest --collect-only`: 22 tests in my files collect with no errors (40 total including the untouched difficulty files).
- AST tag audit: all 22 active instances covered exactly once; every docstring ends with exactly one `Design: Corner/<section>/<name>` line resolving to a real instance; no dual/untagged tests.
- Citation sweep: every quoted PRD fragment verified verbatim against PRD.md.

## Step 5b-3: Corner tests B — validations/endpoints/errors/rbac/cross_cutting (Stage 2, part 3 of 3) — 2026-10-02T02:45:00.000Z

All checks pass. Final summary:

### Files written (all under `test_suite/`)

| File | Size | Tests |
|---|---|---|
| `test_corner_validations.py` | 3,617 B | 2 |
| `test_corner_endpoints.py` | 15,222 B | 7 |
| `test_corner_errors.py` | 17,285 B | 10 |
| `test_corner_rbac.py` | 4,838 B | 4 |
| `test_corner_cross_cutting.py` | 9,566 B | 4 |

### Instance → test mapping (27/27 active instances covered, exactly one test each)

- **validations**: `payload_validation_beats_existence`, `reservation_quota_checked_before_eligibility` → same-named tests in test_corner_validations.py
- **endpoints** (both section entries): `success_envelope_has_meta_and_object_type`, `error_envelope_has_error_id_and_message`, `slots_listed_in_floor_row_position_order`, `barrels_filtered_by_maturation_status`, `blend_components_reverse_lookup`, `single_resource_retrieval_reads`, `filtered_lists_and_reverse_lookups` → test_corner_endpoints.py
- **errors**: all 10 (`report_period_overlap_rejected_adjacency_allowed`, `commission_before_lag_rejected_at_boundary`, `fill_into_full_rickhouse_rejected`, `reserve_non_mature_barrel_rejected`, `same_barrel_twice_in_batch_rejected`, `withdraw_with_active_reservation_after_report_filed`, `dump_barrel_in_committed_blend_rejected`, `commit_rechecks_volume_after_reading`, `reading_above_ledger_rejected`, `clock_cannot_move_backwards`) → test_corner_errors.py
- **rbac**: all 4 (`missing_auth_headers_unauthenticated` sends `headers={}` — verified `GenericApiClient._request` passes headers through verbatim; `warehouse_manager_cannot_create_label`; `cross_role_exclusive_ops_forbidden`; `filer_cannot_accept_own_report` using `make_compliance_officer_headers("prep-1")` vs `("officer-9")`) → test_corner_rbac.py
- **cross_cutting_complexity_layers**: all 4 (three sequential-OCC stale-version tests + lazy reservation expiry) → test_corner_cross_cutting.py

### Skipped instances

None among the 27 active. The 3 stubs in my sections (`cross_cutting_cascade_covered_by_commission_chain`, `cross_cutting_dual_variant_covered_by_barrel_volume`, `consistency_model/immediate_consistency_covered_by_commit_cycle`) are `excluded_because:` stubs — not translated by design. (`state_machines/program_locks_when_quota_consumed` at the tail of the yaml is outside my assignment and already exists in test_corner_state_machines.py.)

### Assertion-precision adjustments (design yaml vs PRD — PRD won)

1. **Relative version increments**: design asserted absolute versions (`BlendBatch.version == 2`, `Barrel.version == 2`); PRD §2.5 pins only "increments by one on every mutation", not the initial value. All three OCC tests assert `observed_version + 1` against the creation-response version.
2. **Day-prefix lifecycle timestamps**: `single_resource_retrieval_reads` asserts `approved_at`/`commissioned_at` by day prefix (`2026-09-01` / `2028-08-21`, the latter = approved + 24×30 days) rather than exact-string equality, since PRD pins the stamped instant but §2.5's three-fractional-digit format is stated only for `created_at`/`updated_at`. Same discipline for `period_start` in the adjacency test and `current_utc` in the clock test.
3. **Clock-regression sharpness**: the "clock unchanged" proof uses a probe set to `2026-08-31T12:00:00Z` (must also 422) plus an equal-instant set accepted with `current_utc` at 2026-09-01 — distinguishes "rejected correctly" from "clock silently moved".
4. **Non-verifiable sub-assertions dropped**: "no label is persisted" (PRD declares no label list endpoint) in the rbac label test; the error is the asserted outcome.

No calculation literals were needed in my sections (all date arithmetic derived via `iso_plus_days`/`DAYS_PER_MONTH` from the live `approved_at`, never hardcoded; boundary at 719 vs 720 days preserved).

### Verification results

- `pytest test_suite/ --collect-only -q`: **67 tests collected, 0 errors** (my 5 files import cleanly alongside the pre-existing suite).
- AST tag audit (real parse): 27/27 assigned active instances covered by exactly one test; every test docstring ends with exactly one `Design: Corner/<section>/<name>` line as its last non-empty line; every tagged name resolves to a real instance in SCAFFOLD_CORNER_DESIGN.yaml; zero untagged/dual-tagged/foreign-tag tests in my files.
- PRD citation sweep: 65 quoted citation spans across my 27 docstrings, all found verbatim (whitespace-normalized) in PRD.md — including the exact §2.3 filter-list sentence, §2.7 OCC bullets, §3.4 compliance/referential guards, and §3.7 segregation-of-duties sentences.
- No files in `test_helpers/`, `conftest.py`, or other test files were modified.

**Step 5 complete**: 67/67 active design instances translated (18 difficulty + 49 corner), 0 skips, suite collects cleanly.

## Step 6: Generate implementation — 2026-10-02T03:10:00.000Z

Implementation complete and verified. Summary:

### Module list (workspace/implementation/)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install; `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 52 | Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers |
| `store.py` | 90 | In-memory dicts (empty at boot), logical clock (default exactly 2026-09-01T00:00:00Z), UUID/seq/ISO-8601 3-fractional-digit timestamps |
| `envelope.py` | 160 | `meta`/`response_type`/`data` envelope, error body `error_id`/`message`, full 24-error catalog with exact HTTP statuses |
| `validation.py` | 175 | Gate 1-3: X-User-ID/X-User-Role auth, 8-role RBAC, strict payload whitelists, typed field validators, limit/offset pagination (1-100) |
| `calc.py` | 427 | Ledger replay (round-half-up 2dp after every event, EVAP reset / sample / commit-draw / abort-restore), statutory 90-day-block decay (season/age/heat/seasoned-discount/rate-cap, round once at end), posture, eligibility ranking, lazy transitions, report figures (per-barrel round-then-sum) |
| `serializers.py` | 209 | Entity serialization with computed fields (occupancies/assessments carry only id+created_at per spec) |
| `routes_capacity.py` | 230 | Projects, approve/commission cascades, rickhouses, slots (heat_factor, floor-row-position order) |
| `routes_barrels.py` | 381 | Barrel fill+place, assessments (30-day buffer, kind-conditional fields), rotations (OCC), dump, withdraw (join gate + covering report) |
| `routes_blends.py` | 341 | Labels, batches, components (OCC), validate/revise/commit/abort with atomic commit and exact abort compensation |
| `routes_programs.py` | 227 | Programs, ranked eligible-barrels, reservations (OCC, quota-before-eligibility), consume bubble-lock, release |
| `routes_reports.py` | 184 | Bonded reports (overlap, reconcile, segregation of duties, amend loop) + `/_clock/set_current_utc` |

**Endpoints implemented: 48/48** (all from the scaffold endpoint table including the clock utility).

**py_compile:** passes on all 11 `.py` files.

### Smoke-test transcript (two boots, own PIDs only, both killed)

Boot 1 (PORT=18771) — happy-path chain plus failure cases:
- POST expansion-projects → 201; approve → 200; commission early → 409 `ERR_CONSTRUCTION_LAG_NOT_ELAPSED`; clock +90d → 200; commission → 200 (cascade: rickhouse OPERATING, 8 slots, heat 1.0/1.05, floor-row-position order)
- POST barrels → 201 (AGING/BONDED in one request, ledger+statutory both 200.0, current_slot_id set); rickhouse occupied_slots=1
- Bad char_level → 400 `ERR_VALIDATION`; wrong role → 403 `ERR_FORBIDDEN_ROLE`; missing headers → 401 `ERR_UNAUTHENTICATED`; occupied slot → 409 `ERR_SLOT_OCCUPANCY_OVERLAP`; clock backwards → 422 `ERR_CLOCK_REGRESSION`; unknown id → 404 `ERR_NOT_FOUND`
- Labels/activate → 201/200; batch create → 201; past bottling date → 400; component add → 201; stale version → 412 `ERR_STALE_BLEND_BATCH_VERSION`; duplicate → 409; validate → 200; commit → 200 (ledger 150.0, final_blend 50.0); abort COMMITTED → ledger restored exactly to 200.0
- Clock to 2030-12-01 → barrel lazily MATURE_ELIGIBLE; program → 201 (available_slots 1); eligible-barrels → 1 entry; reserve → 201; consume → 200; program LOCKED (version 4)
- Rotation with fresh version → 200; stale retry → 412 `ERR_STALE_BARREL_VERSION`
- Report create → 201; overlap → 409 `ERR_REPORT_PERIOD_OVERLAP`; reconcile → 200 (opening 0, fills 200, withdrawals 0, loss_actual 0.0 — commit+abort net zero; loss_statutory 32.7 — hand-verified plausible vs 16-block decay; closing 200); file → 200; same-user accept → 403 `ERR_SEGREGATION_OF_DUTIES`; other officer accept → 200 ACCEPTED

Boot 2 (PORT=18772) — fresh-process isolation: barrel list empty, clock at default, equal clock-set allowed. Confirms the per-test-server restart contract.

## Step 7: Test/fix iteration loop — 2026-10-02T03:12:00.000Z

Clean 8-round parallel sweep achieved: 67/67 passing in every round, with `results.1.json`–`results.8.json` preserved in `workspace/implementation/` as the final sweep evidence.

### Summary

**Iterations run:** 3 sweeps (initial diagnosis → fix → confirmation of partial fix → final clean sweep).

**Tests deleted:** None.

**Fixes applied to `test_suite/`** (both were test bugs, no implementation changes needed):

1. `test_suite/test_corner_entities.py` — `test_barrel_create_initial_state_and_system_fields`: exact-string assertions on `fill_date` and `start_at` were not uniquely derivable from PRD. PRD §3.2 pins the *instant* ("The barrel's `fill_date` is the logical clock at creation"; "stamping `start_at` with the current clock"), but §2.5's three-fractional-digit string format is stated only for `created_at`/`updated_at`/`api_request_timestamp` — a uniform-millis serializer (`...T00:00:00.000Z`, what the impl ships) and a raw-clock-string serializer (`...T00:00:00Z`) are both PRD-faithful. Per STEP 1b/1c and this task's own Step 5b-3 day-prefix precedent, kept the covered assertion at full strength by comparing parsed instants (added a `_parse_instant` helper, `datetime.fromisoformat` after `Z`→`+00:00`), dropping only the uncovered string-format claim.

2. `test_suite/test_corner_errors.py` — `test_same_barrel_twice_in_batch_rejected`: two plain NameErrors — the test used `create_label_payload` and `create_blend_batch` without importing them. Added both to the `from test_helpers import (...)` list. Verified with pyflakes across the whole suite (no other undefined names).

**Fixes applied to `test_helpers/`:** None — helpers were correct; the symbols existed and were properly exported.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on both failure paths (uniform three-fractional-digit timestamp serialization; duplicate-component guard behavior was never even reached due to the NameError).

**Final state:** 67/67 tests pass in all 8 parallel rounds under `--isolation per-test-server`; sweep evidence files intact.

**Orchestrator verification:** all 8 `results.*.json` independently re-read (67/67, 0 failed each); newest impl source mtime 02:53 and newest test source mtime 03:08 both pre-date the final sweep results (03:11) — no post-sweep writes; the two test_suite mtimes match exactly the two reported fixes.

## Step 8: Finalize PRD — 2026-10-02T03:20:00.000Z

Done. The edit is applied and verified — exactly one line changed, everything else byte-identical.

### Summary

**Line counts / %-delta:** `PRD.md` 322 lines → `PRD_FINALIZED.md` 322 lines (0% delta; one sentence appended inline to an existing paragraph, no lines added or removed).

**Changes (one edit total):**

- **§2.5 — revise —** Appended a sentence pinning that every timestamp the API emits is serialized as ISO 8601 UTC with exactly three fractional digits (e.g. `2026-09-01T00:00:00.000Z`), explicitly covering lifecycle/domain instants (`approved_at`, `commissioned_at`, `fill_date`, `start_at`, `end_at`, `assessed_at`, `validated_at`, `committed_at`, `expires_at`, `withdrawn_at`, `scheduled_bottling_date`, `period_start`, `period_end`), the clock-set response's `current_utc`, and null→null serialization. Trace: `store.fmt_ts` at `implementation/store.py:65-69` (the single formatting chokepoint), all 12 serializers in `implementation/serializers.py` (35 `store.fmt_ts` call sites), clock response at `implementation/routes_reports.py:184`, envelope at `implementation/envelope.py:31`.

**Step_7_diff item disposition:**
- Item 1 (timestamp string format on `fill_date`/`start_at`): substantive PRD silence → the §2.5 edit above. The impl's uniform-millis serializer is now pinned for all timestamps, so a fresh implementer cannot PRD-faithfully emit `...T00:00:00Z`.
- Item 2 (NameError, missing test imports): pure test bug, no PRD implication → no edit. The duplicate-component guard it was exercising (routes_blends.py:193) is already fully pinned by PRD §3.5 and §2.10 gate 8.

**Pre-edit search log (mandatory, for the single edit):**

- (a) **Subject:** wire format of timestamps emitted by the API — whether the three-fractional-digit ISO 8601 format (PRD-pinned only for `created_at`/`updated_at`/`api_request_timestamp`) applies to all other timestamp fields.
- (b) **Impl paths enumerated:** read `serializers.py` in full (all 12 serializers — project, rickhouse, slot, occupancy, barrel, assessment, label, batch, component, program, reservation, report; every timestamp field routes through `store.fmt_ts`); read `store.py:65-90` (`fmt_ts`: `strftime("%Y-%m-%dT%H:%M:%S.") + f"{microsecond // 1000:03d}Z"`, `None`→`None`; `parse_dt` accepts arbitrary ISO inputs, so echoed client-supplied instants like `scheduled_bottling_date`/`period_start`/`period_end` are re-serialized in the uniform format); read `envelope.py` (`api_request_timestamp` formatted identically at line 31); greped `strftime|isoformat|fmt_ts|current_utc` across `app.py`, all `routes_*.py`, `calc.py`, `validation.py` — the only non-serializer emission is the clock-set response `current_utc` via `store.fmt_ts` (routes_reports.py:184); no error message or other path formats a timestamp.
- (c) **Wording adjustments made:** (i) used a universal quantifier ("every timestamp the API emits") with a "such as" exemplar list rather than a closed enumeration, so no field is falsely excluded; (ii) explicitly named the clock-set response's `current_utc`, since it is not a resource field and a resources-only phrasing would have mis-described it; (iii) added the "null serializes as null" clause to match `fmt_ts(None)` and stay consistent with §2.5's existing null-lifecycle-fields paragraph; (iv) scoped the claim to emitted/serialized timestamps so it does not contradict §2.4's value-statement "the server's clock reads exactly 2026-09-01T00:00:00Z" (an instant, not a wire format). Millisecond truncation (`// 1000`) was deliberately left unpinned — it is outside the Step 7 site (tests compare parsed instants) and pinning it would add un-traced scope.

Output file: `workspace/PRD_FINALIZED.md`

**Orchestrator verification:** `diff -q PRD.md PRD_FINALIZED.md` confirms a real difference; both 322 lines.

## Step 9: Complete PRD — 2026-10-02T03:45:00.000Z

All edits verified — 17 diff hunks, line count unchanged, all in-place paragraph edits. Here is the completion report.

### Summary

**Source vs output:** `PRD_FINALIZED.md` (322 lines, 50,584 chars) → `PRD_COMPLETED.md` (322 lines, 52,841 chars; **+2,257 chars**, 17 hunks, all inline paragraph edits — no new sections or paragraphs).

**Counts:** 16 ambiguity-pins (across 17 hunks — one hunk pair in §2.3 was a single logical pin split over two paragraphs), 1 mismatch-revision.

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock transport metadata, exempt from the logical-clock doctrine — `implementation/envelope.py:29-32` (uses `datetime.now(timezone.utc)`).
- §2.2 — insert — ambiguity — undefined paths and unsupported methods return `ERR_NOT_FOUND` (404) in the standard envelope — `implementation/app.py:32-39` (404 and 405 handlers both emit `err_not_found`).
- §2.3 — insert — ambiguity — `limit` must be an integer in [1,100]; `offset` must be a non-negative integer, else `ERR_VALIDATION`; created-timestamp ties fall back to creation order — `implementation/validation.py:149-169`.
- §2.3 — insert — ambiguity — `total_count` counts the filtered set; `has_more` ⟺ `offset + len(page) < total_count` — `implementation/envelope.py:40-47`.
- §2.4 — revise — mismatch — blanket "all timestamps… never the wall clock" narrowed to domain timestamps, exempting the envelope field (the §2.2 definition never pinned logical-clock source, so this is a legitimate reading, not an impl bug) — `implementation/envelope.py:30-32`.
- §2.5 — insert — ambiguity — `version` starts at 1 and `updated_at` equals `created_at` at creation — e.g. `implementation/routes_capacity.py:47-49`, `implementation/routes_barrels.py:76-78`.
- §2.10 gate 3 — insert — ambiguity — required string fields must be non-empty — `implementation/validation.py:81-85`.
- §3.1 — insert — ambiguity — `planned_annual_distillation_liters` is a whole-liter integer ≥ 0 (decimals rejected) — `implementation/routes_capacity.py:32`.
- §3.1 — insert — ambiguity — commissioning touches the rickhouse record only in `updated_at`; its `version` does not increment (posture/occupied_slots are derived, never stored) — `implementation/routes_capacity.py:129-130`.
- §3.2 — insert — ambiguity — rotation requires a rotatable barrel (not `DUMPED`, not `WITHDRAWN`, holding an `OPEN` occupancy), else `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_barrels.py:289-293`.
- §3.3 — insert — ambiguity — the lazy `AGING`→`MATURE_ELIGIBLE` flip changes only `maturation_status`; no `version` increment or `updated_at` refresh — `implementation/calc.py:60-65`.
- §3.3 — insert — ambiguity — assessments may be recorded in any maturation/custody state; `measured_volume_liters` carries no lower bound; supplying the other kind's input (e.g. `sample_draw_liters` on a reading) is `ERR_VALIDATION` — `implementation/routes_barrels.py:196-233`.
- §3.6 — insert — ambiguity — a latest `QUALITY_SAMPLE` with null `quality_score` scores zero; candidate-ranking ties beyond `created_at` fall back to creation order — `implementation/calc.py:297-306`, `implementation/routes_programs.py:87-89`.
- §3.6 — insert — ambiguity — lazy expiry changes the reservation's `state`/`updated_at` only; the reservation's own `version` does not increment (only the program's does) — `implementation/calc.py:68-76`.
- §3.7 — insert — ambiguity — a report's seven figures and `prepared_by_user_id`/`filed_by_user_id`/`decided_by_user_id` are null until the workflow step that fills each — `implementation/routes_reports.py:42-60`.
- §3.7 — insert — ambiguity — opening-inventory replay uses only ledger events strictly before `period_start` — `implementation/calc.py:367-369` (`ledger_at(b, ps)` strict-before semantics).
- §3.7 — insert — ambiguity — "inside the loss window" means half-open [window_start, window_end) for sample draws, commit draws, and abort restores — `implementation/calc.py:394-404`.

### Suspected implementation gaps deliberately NOT papered over

None. Every PRD-stated guard was found live in the implementation (gate order verified endpoint-by-endpoint against §2.10, all 44 PRD endpoints present with matching roles, no dead or missing checks detected). Two borderline items were judged legitimate alternative readings and pinned rather than flagged: (a) assessments accepted on `DUMPED`/`WITHDRAWN` barrels — PRD states no state gate; (b) negative `measured_volume_liters` accepted (ledger zero-floors on replay) — PRD pins only the upper bound. The §2.4 wall-clock exemption is the one judgment call where a broad PRD sentence read against the impl; §2.2's own definition of the field supports the impl's reading.

**Orchestrator verification:** `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (+2,257 chars); the §2.4 narrowing edit spot-checked in the file and cross-consistent with the new §2.2 pin; all 8 `results.*.json` still intact.
