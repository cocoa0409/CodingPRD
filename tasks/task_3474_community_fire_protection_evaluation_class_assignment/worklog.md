# Worklog — task_3474_community_fire_protection_evaluation_class_assignment

## Step 1: Create task directory — 2026-10-02T11:32:00.000Z

Task directory pre-allocated by the orchestration harness at `./tasks/task_3474_community_fire_protection_evaluation_class_assignment/` with empty `workspace/` inside. Verified present; no new index computed.

## Step 2: Generate scaffold — 2026-10-02T13:06:00.000Z

Scaffold generation complete for task_3474. All three artifacts are written, parse as YAML, and pass `scaffold_lint.py` with a clean verdict on the first full run.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Counts
- **Endpoints: 58** (57 under `/ppc` + unprefixed `POST /_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- **Entities: 14** (flat topology, FK-linked; CommsProfile folded onto Community; dept/water shells auto-created on community registration to solve the entity-backed-role bootstrap)
- **State machines: 11** — including cyclic Community (CLASSIFIED→…→CLASSIFIED reevaluation loop), cyclic EvaluationCycle (PUBLISHED→DISPUTED→FIELD_VERIFICATION→…→PUBLISHED dispute loop), revert loops on ReevaluationRequest and Appeal, asymmetric Apparatus (no OUT_OF_SERVICE→FRONTLINE)
- **Calculations: 13** — dual variants in three entity domains (staffing CE vs raw headcount, municipal vs rural-shuttle water, premium rounding order), circular-cap CRR evaluation order, divergence penalty, split-class derivation, exposure ledger
- **Validations: 49** (priorities 1–49 across auth/existence/state/OCC/SoD/referential/temporal/constraint/fiscal)
- **Error codes: 48**, every one referenced by a validation row and exercised by at least one design instance
- **Roles: 8** with segregation-of-duties (certifier≠publisher, publisher≠adjudicator); 3 entity-backed roles
- **Difficulty-design instances: 19** (all 9 rules ≥2; combinatorial has 3 covering modes a/b/c)
- **Corner-design instances: 76** (69 active + 7 `excluded_because` stubs, all stub refs verified to resolve)
- **Concurrency rules: 2** OCC (score-sheet create on cycle version, quote bind on community version)

## Verification
- Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1021 calls scanned)
- All asserted numbers were computed by executing the formulas in Python beforehand (e.g., flow normalization 1810 gpm, class boundary 90.00→class 1 vs 89.99→class 2, premium provisional 412,781 vs final 412,783 cents, CRR circular cap 4.45 on subtotal 44.48)
- No forbidden concurrency vocabulary; every `${var}` placeholder traces to a `captures:`; all OCC inputs use `${var}` from fresh GETs (cycle/entity versions are re-captured after version-bumping transitions)
- One design fix during authoring: removed unreachable `ERR_ACTIVE_CYCLE_EXISTS` (the community state gate fires first at higher priority) and renumbered downstream priorities, keeping the difficulty file's `validations[priority=N]` grounds in sync

Note for downstream: 58 endpoints exceeds the §0.4 Expert guideline (20–32) per the "harder than expert" directive — the extra surface is mostly lint-mandated per-entity single GETs; Step 6 implementation generation should use the known mitigations (per-domain modules, one file per message, no-truncation prompting).

Orchestrator verification: all three files exist and parse as YAML; api_prefix `/ppc`, domain entities (Community, EvaluationCycle, FireDepartment, Apparatus, WaterSupplySystem) present — on-domain artifact confirmed.

## Step 3: Copy shared files — 2026-10-02T13:08:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T13:20:00.000Z

All contracts pass. The PRD is complete and verified. Final summary:

## PRD Generation Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/workspace/PRD.md` (323 lines)

**Section list:**
- §1. Introduction (2 paragraphs — business-context angle)
- §2. Global Specifications: 2.1 RBAC (8 roles, entity-backed vs opaque identity prose), 2.2 API Response Structure (byte-identical to canonical block — verified), 2.3 Pagination, 2.4 Logical Clock & Calendar Semantics (default 2026-09-01T00:00:00Z, clock endpoint noted as outside `/ppc`), 2.5 Common Resource Properties, 2.6 Numeric Precision & Rounding, 2.7 Optimistic Concurrency Control (all 3 OCC endpoints: score-sheet create, quote bind, request approve), 2.8 Evaluation Data Windows (per-capability window sets), 2.9 Segregation of Duties, 2.10 Cascades & Denormalized Consistency, 2.11 Validation Order & Nested Retrieval
- §3. Business Logic (9 subsections, chronological pipeline grouping): 3.1 Community registration & comms attestation, 3.2 Evaluation cycle ladder, 3.3 Fire department & apparatus, 3.4 Water supply/hydrants/flow tests (incl. normalization formula and 3-link correction cascade), 3.5 Risk-reduction credits, 3.6 Scoring (all subscores, both staffing and water variants, CRR pinned evaluation order, divergence penalty, class thresholds, split class), 3.7 Publication & activation (full cascade, modifier table), 3.8 Properties & premium quoting (both rounding variants, exposure ledger), 3.9 Reevaluation & appeals
- §4. Endpoint table (4 columns; 58 rows — exact match to scaffold), §5. Error catalogue (2 columns; 48 rows — exact match)

**Hard contract reports:**
- Field coverage: 148 required (entities + endpoint inputs + path params), 148 present, 0 missing — **PASS**
- Rule coverage: all 13 calculations expressed in reconstructible prose; all state transitions with preconditions/side effects; all 49 validations matchable to their error ids in prose with per-endpoint ordering made explicit at bind/sheet-create/publish/request-filing/appeal-filing; both OCC rules plus the third from validation 29; cross-entity cascades complete (activation, correction, appeal-revised sheet supersession) — **PASS**
- Path purity: 565 backtick tokens scanned in §3, 0 paths/methods — **PASS**
- Additional audits: all 48 error ids appear in §2/§3 prose; all enum/state values present (including `APPROVED`, `CORRECTED` as target); §2.2 verbatim; one extraction bug found and fixed during checking (the §2.2 fenced JSON blocks break naive backtick pairing — audits strip fences first)

**Scaffold ambiguities I had to resolve/interpret:**
1. **Score-sheet create cycle states** — validation 19 applies `ERR_CYCLE_INVALID_STATE` to sheet creation but never enumerates permitted cycle states; rendered as "a scoring-phase state" without inventing an enumeration (finalize explicitly requires `SCORING`/`CLASSIFICATION_REVIEW`).
2. **Appeal-revise vs. EFFECTIVE classifications** — `ADJUDICATED_REVISED` requires the classification's cycle to be in `CLASSIFICATION_REVIEW`, yet the Classification machine also defines `EFFECTIVE → VACATED` on revised adjudication; an EFFECTIVE classification's cycle is terminal, so that branch's precondition looks unsatisfiable. Projected both rules verbatim without resolving (transition precondition governs).
3. **Two creditworthy-hydrant predicates** — the stored aggregate `creditworthy_hydrant_count` uses raw `max_flow_gpm` ≥ 1000, while the scoring distribution subscore uses staleness-adjusted effective flow ≥ 1000; both rendered as written.
4. **`note` → `decision_note` mapping** on reevaluation transitions/approve (scaffold side effect says "decision_note set" with no other writer).
5. **Publish sheet-validity error id** — "score_sheet FINAL and belongs to cycle" has no dedicated error; attached `ERR_INVALID_REQUEST` per validation 44's applies-to-all-writes scope.
6. **`CORRECTED` target state** is not a FlowTest status — rendered as a transition request that supersedes the original and returns a replacement row created directly in `CERTIFIED`.

The two forbidden design-index files were not opened or referenced. No servers or other pipelines were touched.

## Step 5a: Generate test_helpers — 2026-10-02T13:52:00.000Z

Orchestrator note: Step 5 split into 5a (helpers, frozen) then 5b (tests) per oversized-generation practice. Orchestrator-measured queue: 19 difficulty active + 69 corner active + 7 corner stubs (corner per-section active: entities 9, state_machines 8, calculations 5, validations 15, endpoints 3, errors 18, rbac 7, complexity_layers 3, consistency_model 1).

Step 5a complete. The `test_helpers/` package for task_3474 is written, compiles, and imports cleanly in a fresh process. No `test_suite/` files were created.

## Files (19 modules, 2436 lines)

| file | lines | contents |
|---|---|---|
| `__init__.py` | 46 | barrel: framework generics + all PRD-specific names |
| `types.py` | 155 | 20 enums (UserRole, CommunityStatus, CycleStatus, FlowTestStatus, QuoteStatus, AppealStatus, …); re-exports both TypedDict modules |
| `types_entities.py` | 124 | TypedDicts: Community, EvaluationCycle, FireDepartment, Apparatus, WaterSupplySystem, Hydrant, FlowTest (all common_fields: true → id/created_at/updated_at/version) |
| `types_workflow.py` | 130 | TypedDicts: RiskReductionCredit, ScoreSheet, Classification, PropertyRiskProfile, PremiumQuote, ReevaluationRequest, Appeal |
| `constants.py` | 147 | 72 constants, all 46 numeric checks diffed equal to PRD literals (see below) |
| `api_errors.py` | 122 | `ApiErrorId` (48 members) + `HTTP_STATUS_CODES` (48) + `set_error_http_status_map` registration |
| `api_client_evaluation.py` | 71 | `EvaluationEndpoints` mixin: clock + communities + cycles + sheets + classifications |
| `api_client_field.py` | 86 | `FieldDataEndpoints` mixin: departments, apparatus, water systems, hydrants, flow tests, credits |
| `api_client_insurance.py` | 69 | `InsuranceEndpoints` mixin: properties, quotes, requests, appeals |
| `api_client.py` | 20 | `ApiClient(EvaluationEndpoints, FieldDataEndpoints, InsuranceEndpoints, GenericApiClient)` + `api_client` singleton |
| `factories.py` | 251 | 26 payload factories, input fields only |
| `test_users.py` | 91 | `TEST_USERS` + 8 `make_*_headers` builders + operator-id constants |
| `assertions_entities.py` / `assertions_workflow.py` / `assertions.py` | 129/199/29 | 14 `assert_<entity>` + `assert_common_fields` + 3 invariant checkers |
| `fixtures_core.py` / `fixtures_scoring.py` / `fixtures.py` | 197/337/223/10 | composite fixtures (aggregator re-exports all three) |

## Frozen API surface (what 5b builds against)

**Client**: `api_client` singleton / `ApiClient`. All 58 PRD endpoints as methods, signature `(payload, headers)` for writes, `(id, headers)` for gets, `(headers, params=None)` for lists. Verified with a path-capture probe: every path starts `/ppc/` **except** `set_clock` → `POST /_clock/set_current_utc` (unprefixed, per SCAFFOLD §1.5). Creates return 201 — tests must pass `expected_status=201` to `validate_success` (fixtures use `get_success_data`, immune).
**Import caveat for 5b**: use `from test_helpers import api_client, ApiClient` — never `import test_helpers.api_client as ac` (the package attribute is the singleton, not the module).

**Roles/headers** (`test_users.py`): `TEST_USERS` keys `evaluation_coordinator_headers`, `field_analyst_headers`, `class_registrar_headers`, `fire_chief_headers`, `water_utility_manager_headers`, `comms_supervisor_headers`, `community_official_headers`, `insurer_headers`. Builders: `make_evaluation_coordinator_headers(user_id)`, `make_field_analyst_headers(user_id)`, `make_class_registrar_headers(user_id)` (SoD: pass `"registrar-2"`), `make_comms_supervisor_headers(user_id)`, `make_insurer_headers(user_id)`, and the entity-backed mandatory trio `make_fire_chief_headers(department_id)`, `make_water_utility_manager_headers(system_id)`, `make_community_official_headers(community_id)`. Operator ids: `DEFAULT_ANALYST_ID="analyst-1"`, `SECOND_ANALYST_ID`, `DEFAULT_REGISTRAR_ID="registrar-1"`, `SECOND_REGISTRAR_ID`, `DEFAULT_COORDINATOR_ID`, `DEFAULT_COMMS_SUPERVISOR_ID`, `DEFAULT_INSURER_ID`.

**Fixtures** (all take `api` first; OCC version capture is built in — `create_score_sheet`, `bind_quote`, `approve_reevaluation_request` re-GET the parent version unless `expected_version=` given):
- Core: `set_clock`, `create_community`, `create_community_bundle` → `{community, department, system}`, `get_community`, `get_cycle`, `community_version`, `cycle_version`, `get_department_of`, `get_water_system_of`, `create_cycle`, `transition_cycle`, `advance_cycle_to`, `submit_department_data`, `attest_comms`, `add_apparatus`, `set_apparatus_status`, `patch_water_system`, `add_hydrant`, `set_hydrant_status`, `submit_flow_test`.
- Scoring: `witness/certify/reject/correct_flow_test`, `file_credit`, `verify/reject_credit`, `verify_alternate_supply`, `create_score_sheet`, `finalize_score_sheet`, `publish_classification`, `activate_classification`, and the workhorse `setup_scoring_cycle(api, *, analyst_id, dept_data, comms, apparatus, hydrant_count|hydrants, flow_tests, credits, alternate_supply, verify_alternate, target_state, open_date, freeze_date, **community_overrides)` (apparatus specs accept `"status"`; flow-test specs accept `"hydrant"` index + `"outcome"` certified/rejected/witnessed/submitted; credit specs accept `"outcome"` verified/rejected/pending; verification steps run only when the target reaches FIELD_VERIFICATION, DATA_COLLECTION stop asserted safe), plus lifecycle shortcuts `setup_classification_review`, `setup_published_classification`, `setup_classified_community` (each returns the ctx dict with `community/department/system/cycle/apparatus/hydrants/flow_tests/credits/analyst_id[/sheet][/classification]`).
- Lifecycle: `create_property`, `create_quote`, `bind_quote`, `void_quote`, `get_quote`, `list_quotes`, `file_reevaluation_request`, `transition_request` (raw, explicit headers), `open_documentation_review`, `return_request_for_docs`, `begin_field_reverification`, `deny_reevaluation_request`, `withdraw_reevaluation_request`, `patch_request_evidence`, `approve_reevaluation_request`, `file_appeal`, `transition_appeal` (raw), `begin_data_verification`, `return_appeal_for_evidence`, `adjudicate_upheld`, `adjudicate_revised(new_score_sheet_id=...)`, `withdraw_appeal`.

**Factories**: `community_payload` (unique auto-names; includes `dept_type` + the four hydrologic inputs), `attest_comms_payload` (zero defaults → attested-but-zero comms), `evaluation_cycle_payload`, `cycle_transition_payload`, `score_sheet_create_payload`, `publish_classification_payload`, `activate_classification_payload`, `department_data_payload`, `apparatus_payload`, `apparatus_status_payload`, `water_system_patch_payload`, `hydrant_payload`, `hydrant_status_payload`, `flow_test_payload` (default 80/60/1000 → normalizes to 1810), `flow_test_transition_payload(**corrections)`, `risk_reduction_credit_payload`, `credit_transition_payload`, `property_risk_profile_payload`, `premium_quote_payload`, `bind_quote_payload`, `reevaluation_request_payload`, `request_transition_payload(note=None)`, `approve_reevaluation_payload`, `appeal_payload`, `appeal_transition_payload(adjudication_note, new_score_sheet_id)`, `clock_payload`, `evidence_item`. Defaults are valid against the default clock 2026-09-01 (test dates 2026-08-15 fresh vs the 2026-12-01 freeze, coverage windows 2027+).

**Assertions**: `assert_common_fields`, `assert_community`, `assert_evaluation_cycle`, `assert_fire_department`, `assert_apparatus`, `assert_water_supply_system`, `assert_hydrant`, `assert_flow_test`, `assert_risk_reduction_credit`, `assert_score_sheet`, `assert_classification`, `assert_property_risk_profile`, `assert_premium_quote`, `assert_reevaluation_request`, `assert_appeal`; invariants `assert_score_sheet_invariants` (caps, subscore sums, class thresholds), `assert_modifier_for_class`, `assert_bound_exposure_invariant`.

**Constants**: all PRD-pinned literals under their domain names — `DEFAULT_CLOCK_ISO="2026-09-01T00:00:00Z"`, flow (`REFERENCE_RESIDUAL_PSI=20`, `PRESSURE_EXPONENT=0.54`), equipment (`NEEDED_PUMP_GPM=1750`, `LADDER_MIN_FT=75`, `TANKER_MIN_GAL=1000`), staffing (`NEEDED_ON_SHIFT=6`, `VOLUNTEER_FACTOR=0.5`), training (`TRAINING_HOURS_BENCHMARK=240`, `LIVE_FIRE_CAP=6`), water (`FLOW_TARGET_MULT=1.5`, `HYDRANT_CREDIT_MIN_GPM=1000`, `STORAGE_DURATION_MIN=120`, `STALE_FACTOR=0.5`, `STALE_MONTHS=60`, `ALT_SITE_TARGET=2`), comms (`ALARM_FAST_SECONDS=60`, `ALARM_SLOW_SECONDS=90`, unattested defaults 0/999), CRR (`CRR_ITEM_CAP=2.0`, `CRR_TOTAL_CAP=5.5`, `CRR_PCT_OF_SUBTOTAL=0.10`), divergence (0.5/2), `CLASS_THRESHOLDS` (90→1 … 10→9, else 10), `PREMIUM_MODIFIER_TABLE` (0.65…1.25), `HYDRANT_RADIUS_FT=1000`, `STATION_RADIUS_MI=5.0`, `EXPOSURE_CAP_CENTS=500000000`, `COVERAGE_VALUE_CAP_RATIO=1.5`, windows (`EVAL_INTERVAL_MONTHS=60`, `REEVAL_MIN_MONTHS=12`, `APPEAL_WINDOW_DAYS=90`, `REEVAL_SPAWNED_CYCLE_FREEZE_DAYS=90`), input ranges (NFF 500..50000, psi 20<x≤300 / ≥10, term 1..120), pagination (10/1/100/0), `ROLE_*` names, `ALL_ROLES`. Programmatic diff confirmed all 46 numeric literals match PRD/scaffold — no dead constants.

**Errors**: `ApiErrorId` (48) + `HTTP_STATUS_CODES`; registered with the framework at import so `validate_error` auto-checks HTTP status (401 unauthenticated; 403 forbidden/not-owner/SoD; 404 ×14; 409 ×17; 412 stale; 422 ×11; 400 invalid-request).

**Verification**: `compileall` clean; fresh `python3 -c "import test_helpers"` succeeds; all 58 client methods exercised against a path-capturing stub; header builders, factories (unique names, payload shapes), TypedDict surface, and assertion helpers (run against plausible bodies incl. full `assert_score_sheet_invariants`) all pass.

Orchestrator spot-check: PRD literals 0.54 (flow exponent), 1750 (needed pump gpm), 90→class 1 threshold confirmed present in PRD.md; constants.py matches on those; `import test_helpers` succeeds.

## Step 5b: Generate test_suite — 2026-10-02T14:25:00.000Z

Step 5b complete. Summary:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/test_suite/`)

| File | Lines | Contents |
|---|---|---|
| `conftest.py` | 48 | sys.path wiring + session `api` fixture + role-header fixtures |
| `test_01_envelope_and_consistency.py` | 90 | endpoints ×3, consistency_model ×1 |
| `test_02_community_registration.py` | 143 | entities ×5, validations ×2 (missing auth, NFF range) |
| `test_03_water_field_data.py` | 127 | entities ×3 (hydrant computed-field, 2 list filters), validations ×2 (psi order, future test date) |
| `test_04_flow_testing.py` | 125 | calculations ×2 (normalization 1810, stale half-credit), **Difficulty** flow-correction cascade ×2 |
| `test_05_hydrant_aggregate_conservation.py` | 89 | **Difficulty** hydrant conservation ×2, alternate-supply 422 |
| `test_06_scoring_variants.py` | 115 | **Difficulty** staffing dual-variant ×2, water dual-variant ×2 |
| `test_07_scoring_formulas.py` | 158 | **Difficulty** equipment min/max ×2, CRR cap order ×2, calculations ×2 |
| `test_08_class_boundaries.py` | 154 | **Difficulty** 90.00/89.99 class boundary ×2, 1000ft/5mi distance boundary ×2 |
| `test_09_cycle_windows_and_states.py` | 168 | cycle SM ×2, validations ×3, **Difficulty** analyst half-open windows ×2 |
| `test_10_scoring_gates.py` | 117 | **Difficulty** cross-entity SCORING gate ×2, errors ×2, DRAFT in-place recompute ×1 |
| `test_11_classification_lifecycle.py` | 175 | **Difficulty** activation cascade ×2, quote-requires-EFFECTIVE ×2, modifier table ×1, activate-twice ×1 |
| `test_12_premium_quotes.py` | 172 | **Difficulty** premium rounding order ×2, temporal-beats-fiscal ×2, quote 404, 150% coverage boundary |
| `test_13_binding_and_exposure.py` | 208 | **Difficulty** exposure ledger ×2, closed-interval overlap ×2, exposure cap, OCC bind 412, voided-quote lockdown |
| `test_14_score_sheet_states.py` | 105 | sheet supersede/finalize 409, OCC sheet 412, **Difficulty** state-beats-SoD publish ×2 |
| `test_15_reevaluation.py` | 180 | **Difficulty** community reevaluation loop ×2, request revert loop, duplicate/too-early/empty-evidence |
| `test_16_appeals.py` | 128 | **Difficulty** dispute-rescore loop ×2, appeal revert loop, duplicate appeal |
| `test_17_appeal_gates.py` | 86 | appeal window expired, adjudicate-while-FILED, ERR_APPEAL_PENDING, ERR_NO_APPEAL_IN_VERIFICATION |
| `test_18_apparatus_and_credit_states.py` | 69 | apparatus OOS exit asymmetry, REJECTED test lockdown, REJECTED credit lockdown |
| `test_19_rbac.py` | 152 | RBAC ×7 (endpoint roles, entity-backed ownership, both SoD rules) |
| `test_20_error_catalog_not_found.py` | 157 | all 11 not-found 404s |

## Audit results

- **`pytest --collect-only`: 107 tests collected, 0 errors** (run from the task root).
- **AST tag audit: 88 distinct `Design:` tags emitted = 19 Difficulty + 69 Corner; 0 missing, 0 phantom, 0 untagged, 0 dual-tagged.** Every Difficulty instance has ≥2 tests (38 tests), every Corner instance exactly 1. **Reconciliation: 88 emitted + 0 skipped = 88 expected.** All 7 `excluded_because:` stubs correctly untranslated.
- **Citation audit: all 107 docstrings contain a verbatim ≥8-word substring that greps `PRD.md`** (C1/C2/C3), each ending in exactly one `Design:` line (C4).
- No `scaffold` references, no `skip`/`skipif`/`xfail`, pyflakes clean, all files ≤ 350 lines.

## Skip log

**Empty.** Every active instance in both indices passed the PRD-first two-condition filter — the PRD verbatim-covers every asserted rule (scoring formulas and pinned rounding/evaluation orders in §3.6, guard ordering in §2.11/§3.6/§3.7, boundary inclusivity in §3.8, temporal windows in §2.4/§3.9, OCC in §2.7, SoD in §2.9).

## Notes for downstream steps

- Numeric expectations were re-derived against PRD prose before emitting (e.g., the CRR-cap instance's subtotal 44.48 depends on `3^0.54 ≈ 1.809858`, making the 850-gpm test normalize to 1538 — consistent with the design index; the correction cascade's 30.87 adjusted total includes the default facility-level-C training point).
- Difficulty test pairs were built as independent angles on one instance (e.g., cascade link 1+2 vs link 3, ledger forward vs compensating void, priority-pair masking vs unmasked control) rather than duplicated runs.
- The activation-cascade and reevaluation-loop tests rely on the published cycle becoming terminal (`EFFECTIVE`) after activation so a same-analyst follow-up cycle creation doesn't trip `ERR_CYCLE_WINDOW_CONFLICT` — this matches the pre-audited design recipes and PRD §3.2's non-terminal definition.

Orchestrator verification: re-ran `pytest --collect-only` (107 collected, 0 errors) and an independent AST tag audit (107 tests, 88 distinct tags, difficulty/corner name sets fully covered, no phantoms).

## Step 6: Generate implementation — 2026-10-02T15:05:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/workspace/implementation/`. All three smoke suites passed end-to-end, and a fresh `start.sh` boot verified an empty store.

## Module list (line counts)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded pip install (no-op once flask present), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 53 | App factory, 9 blueprints, ApiError/404/405/500 envelope handlers, `$PORT`/0.0.0.0 |
| `errors.py` | 66 | ApiError + all 48 catalogued error IDs with fixed HTTP statuses |
| `response.py` | 59 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination meta, Decimal→JSON |
| `db.py` | 129 | Empty in-memory store (14 entity tables), logical clock (default `2026-09-01T00:00:00Z`), `new_entity`/`touch` (version++), domain lookups |
| `middleware.py` | 36 | X-User-ID/X-User-Role auth (401), role gate (403), ownership (403) |
| `util.py` | 168 | Strict YYYY-MM-DD/ISO8601 parsing, calendar-month arithmetic, round-half-up helpers, typed field validators, limit/offset parsing |
| `scoring.py` | 211 | All 13 calculations: flow normalization (Decimal `^0.54`), equipment/staffing(both variants)/training/response, water (MUNICIPAL + RURAL_SHUTTLE, staleness halving per hydrant), comms, CRR waterfall (subtotal-first pinned order), divergence/class thresholds, split class, premium provisional/final (pinned rounding orders), modifier table, exposure cap |
| `cascade.py` | 135 | Data-window gate, SCORING data-completeness gate, DRAFT-sheet in-place recompute, hydrant/system aggregate recompute, property applicable-class split logic, full activation cascade (supersede prior, community denorms, property recompute, QUOTED→EXPIRED) |
| `routes_community.py` | 153 | Community register (auto-creates dept + water shells), list/get, attest-comms, **`POST /_clock/set_current_utc` mounted unprefixed** |
| `routes_cycle.py` | 265 | Cycle create (window conflict, freeze>open, community→UNDER_EVALUATION), list/get, transition ladder + WITHDRAWN revert, score-sheet create (OCC, DRAFT supersede), sheet list/get/finalize, publish-classification (SoD) |
| `routes_classification.py` | 56 | List/get, activate (PUBLISHED gate, appeal-pending gate, effective_from≥clock, full cascade) |
| `routes_field.py` | 166 | Department list/get/PATCH (FireChief ownership, data_submitted), apparatus CRUD + state machine (OUT_OF_SERVICE→FRONTLINE forbidden) |
| `routes_water.py` | 302 | System list/get/PATCH, verify-alternate-supply, hydrant CRUD + aggregates, flow-test submit/witness/certify/reject/CORRECTED with 3-link cascade |
| `routes_credits.py` | 100 | Credit claim/list/get/transition (verify cap 2.0, revoke) |
| `routes_insurance.py` | 204 | Property profiles (split-aware class at create), quotes create/bind (OCC, closed-interval overlap, exposure cap, per-month final rounding)/void (compensating ledger) |
| `routes_reeval.py` | 188 | Request create (12-month rule, per-target role map), evidence PATCH, transitions, approve (OCC, spawns cycle: open=clock, freeze=clock+90d) |
| `routes_appeals.py` | 192 | Appeal file (90-day window, cycle→DISPUTED), transitions (SoD adjudication, ADJUDICATED_REVISED cascade: VACATED + replacement PUBLISHED + cycle→PUBLISHED) |

## Endpoint coverage: 58/58
All 57 `/ppc` endpoints from PRD §4 plus the unprefixed `POST /_clock/set_current_utc` are wired and exercised.

## Self-smoke-test evidence (server on port 53471, PID killed after; fresh reboot on 54623 confirmed empty store)
- Full happy path: clock set → community 201 → cycle 201 → INTAKE→DATA_COLLECTION→FIELD_VERIFICATION→SCORING → sheet 201 (OCC 412 on stale version) → finalize → CLASSIFICATION_REVIEW → publish 201 (SoD 403 for analyst-as-registrar) → activate 200 → community `CLASSIFIED class=2 next_due=2031-10-01` → property/quote 201 → bind (ledger 30000000) → void (ledger 0).
- Calculation spot-checks verified by hand: flow 1500·((100−20)/(100−60))^0.54 → **2181**; sheet `fd=43.7 water=31.59 comms=10 adjusted=85.29 base=2 split=4`; premium provisional=final=252000.
- Error-path probes all correct: 401 unauthenticated, 403 role/SoD, 400 kind-driven apparatus field + past effective_from, 409 window/state/appeal-pending/duplicate, 412 OCC, 422 future test-date/no-FINAL-sheet/reeval-too-early.
- Correction cascade: original→SUPERSEDED, replacement CERTIFIED (flow 1623→2181), hydrant updated, `?supersedes_test_id=` filter traces the chain.
- Dispute loop: appeal on PUBLISHED → cycle DISPUTED → (409 without DATA_VERIFICATION appeal) → FIELD_VERIFICATION rework → new FINAL sheet supersedes old FINAL → ADJUDICATED_REVISED → old VACATED + replacement PUBLISHED + cycle PUBLISHED → activate → community classified.
- Reevaluation: 422 too-early, 201 at +12 months, approve spawns cycle `number=2 open=2027-10-01 freeze=2027-12-30`, analyst window conflict 409 on overlap / 201 on touching endpoints, withdraw reverts community to REGISTERED.

## PRD interpretations chosen (candidate over-guard audit list)
1. **Score-sheet create requires `SCORING` only** ("a scoring-phase state" read literally; finalize allows `{SCORING, CLASSIFICATION_REVIEW}` per the explicit scaffold list — a DRAFT created in SCORING can be finalized in REVIEW).
2. **Missing OCC field → `ERR_INVALID_REQUEST` (400)**; present-but-mismatched → `ERR_STALE_VERSION` (PRD: "requires the request to carry").
3. **`current_utc` echoes the submitted `to_iso8601` string verbatim**; internal timestamps (`created_at` etc.) use 3-fractional-digit format per §2.5.
4. **Unknown `target_state`** on transition endpoints → the entity's `ERR_*_INVALID_STATE` (PRD "any other transition is ERR_X_INVALID_STATE"); per-target role check (403) applies to recognized targets.
5. **Flow-test create rejects hydrant/system mismatch** with `ERR_INVALID_REQUEST` (hydrant belongs to system).
6. **Correction replacement row**: `certified_by` = correcting analyst, `witnessed_by` = null, `test_date` copied from original.
7. **Hydrant PATCH same-status allowed** (no `ERR_HYDRANT_INVALID_STATE` exists in the catalog; any ACTIVE↔OUT_OF_SERVICE value accepted).
8. **Ownership before existence only where decidable without loading** (body FKs and same-type path IDs); for path targets owned via a different entity (apparatus→dept, hydrant→system, request/appeal→community), existence 404 precedes `ERR_NOT_OWNER`.
9. **Check orders per ladder**: cycle create does window-conflict (38) before freeze>open (44); quote create: NO_EFFECTIVE_CLASSIFICATION → COVERAGE_PERIOD_INVALID → field ranges → COVERAGE_EXCEEDS_VALUE; reeval create: COMMUNITY_INVALID_STATE → REEVALUATION_TOO_EARLY → evidence validity → DUPLICATE_ACTIVE_REQUEST.
10. **`adjudication_note` accepted but not persisted** (Appeal entity has no note field).
11. Scoring's `creditworthy` hydrant count uses staleness-adjusted effective flow (PRD §3.6), while `WaterSupplySystem.creditworthy_hydrant_count` aggregate uses raw `max_flow_gpm` ≥ 1000 (per entity definition) — two distinct definitions implemented as written.
12. `state_code` validated as string only (length-2 not enforced); unknown extra payload fields ignored rather than rejected.

Orchestrator verification: all 19 modules present, `compileall` clean, community blueprint carries literal `/ppc/...` paths while `/_clock/set_current_utc` is mounted unprefixed (blueprints registered without url_prefix). Interpretation list retained as Step 7 candidate over-guard watch items.

## Step 7: Test-fix iteration loop — 2026-10-02T15:35:00.000Z

Clean 8-round parallel sweep achieved. Summary:

**Iterations run:** 3 sweeps (initial diagnosis, post-ladder-fix, post-test-fixes).

**Tests deleted (1):**
- `test_15_reevaluation.py::test_duplicate_active_request_returns_conflict` — unique-derivability collapse (STEP 1b). PRD §3.9 states the filing gates "evaluated in this order: the community must be `CLASSIFIED` … ; and the community must not already hold a non-terminal request", and filing verbatim moves the community CLASSIFIED→REEVALUATION_REQUESTED, so an immediate second filing deterministically trips gate 1 (`ERR_COMMUNITY_INVALID_STATE`). The asserted `ERR_DUPLICATE_ACTIVE_REQUEST` came from the corner-design doc (`Corner/validations/duplicate_active_request_returns_conflict`), which contradicts both the PRD gate order and the scaffold's own validation ladder (priority 18 COMMUNITY_INVALID_STATE before priority 45 DUPLICATE_ACTIVE_REQUEST) — a scaffold self-contradiction where first-failure-wins shadows the duplicate claim. No API-reachable state pairs CLASSIFIED with a non-terminal request (deny/withdraw/approve all terminate the request), so no faithful rewrite could exercise the gate either.

**Fixes applied to `test_helpers/` (1):**
- `fixtures_core.py` — `_CYCLE_LADDER` was missing `SCHEDULED`. PRD §3.2 and SCAFFOLD both make SCHEDULED the initial cycle state (SCHEDULED→INTAKE is clock-gated, satisfied at the default clock 2026-09-01 = default open date). `advance_cycle_to` asserted `current in _CYCLE_LADDER` and aborted on every fresh cycle — the single cause of all 74 round-1 failures.

**Fixes applied to `test_suite/` (1):**
- `test_15_reevaluation.py::_drive_reevaluation_loop` — returned the stale creation-time request snapshot (status SUBMITTED) instead of the approved snapshot; `test_reevaluation_loop_returns_community_to_classified` then failed `assert request["status"] == "APPROVED"` despite a correct approval. Now returns `approved`. PRD §3.9: "approves it, moving the request to `APPROVED`."

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every failure (gate order, stale-version OCC, spawn cycle, SCHEDULED initial state all correct as built).

**Sibling unasserted paths** (test-side fixes dominated — 107 assertions moved, 0 impl edits; Step 8 should note these):
- Request-filing gate 1 (`ERR_COMMUNITY_INVALID_STATE` on filing from REGISTERED/UNDER_EVALUATION/REEVALUATION_REQUESTED) now has no coverage anywhere in the suite.
- `ERR_DUPLICATE_ACTIVE_REQUEST` is unreachable end-to-end under the PRD gate order (dead check by construction, though correctly implemented in `routes_reeval.py`).
- The 73 recovered tests exercise hydrant/flow-test/scoring/quote/appeal ladders that were previously never reached past cycle creation; their green status is first-time evidence, not regression confirmation.

**Final sweep evidence:** round 1: 106/106, round 2: 106/106, round 3: 106/106, round 4: 106/106, round 5: 106/106, round 6: 106/106, round 7: 106/106, round 8: 106/106 (total dropped 107→106 due to the single deletion). All 8 `results.{1..8}.json` artifacts remain in `workspace/implementation/`. Debug servers killed; no stray processes.

Orchestrator verification: all 8 results files re-read from disk — 106/106 × 8 confirmed.

## Step 8: Finalize PRD — 2026-10-02T15:45:00.000Z

Done. `PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` — the minimal patch is the **empty patch** (zero edits), verified with `diff -q`.

## Summary

- **Line counts:** PRD.md 323 lines, PRD_FINALIZED.md 323 lines, **0.0% delta**.
- **Changes:** none. Every `<step_7_diff>` item traced to behavior the PRD already uniquely pins; the one deletion is explicitly sanctioned to leave verbatim when the prose is unambiguous, and it is.

## Per-item pre-edit search log (each candidate edit evaluated; all concluded NO EDIT)

**Candidate 1 — §3.9 filing gate order / `ERR_DUPLICATE_ACTIVE_REQUEST` reachability** (from deleted `test_duplicate_active_request_returns_conflict`)
- (a) Subject: the three filing gates' evaluation order and the duplicate-active check.
- (b) Impl paths enumerated and read: `implementation/routes_reeval.py:34-69` (`create_request`: gate 1 community-state at lines 44-46, gate 2 too-early at 47-51 with `REEVAL_MIN_MONTHS = 12` from `scoring.py:46`, payload validation at 52-53, gate 3 duplicate at 54-57); `routes_reeval.py:111-138` (deny/withdraw terminate the request and return the community to `CLASSIFIED`); `routes_reeval.py:141-188` (approve terminates the request, community → `UNDER_REEVALUATION`); `implementation/routes_cycle.py:117-127` (cycle withdrawal returns community to `CLASSIFIED` only via `current_class_number`, with the request already terminal).
- (c) No wording adjustment: PRD §3.9 already states "Three gates apply at filing, evaluated in this order: the community must be `CLASSIFIED` … ; … twelve calendar months … ; and the community must not already hold a non-terminal request" — the ordering is explicit, not ambiguous, and the impl matches it exactly. The gate-3 unreachability follows entirely from PRD-pinned facts (filing moves CLASSIFIED→REEVALUATION_REQUESTED; all paths back to CLASSIFIED terminate the request), and the impl still implements the check at the PRD-mandated position. Per the task note, a dead-but-correctly-implemented check is not a PRD defect — left verbatim.

**Candidate 2 — §3.2 cycle initial state `SCHEDULED` and the SCHEDULED→INTAKE clock gate** (from `fixtures_core.py` `_CYCLE_LADDER` fix)
- (a) Subject: cycle creation state and first ladder rung.
- (b) Impl paths enumerated and read: `routes_cycle.py:46-79` (`create_cycle`: `"status": "SCHEDULED"` at line 74, community → `UNDER_EVALUATION` at 77); `routes_cycle.py:129-136` (INTAKE gate `clock_date < scheduled_open_date` → `ERR_CYCLE_NOT_OPEN_YET`, i.e. equality passes); `routes_reeval.py:177-185` (approval-spawned cycle also created `SCHEDULED` with `opened_at: None`); `test_helpers/fixtures_core.py:27` (fixed ladder now `["SCHEDULED", "INTAKE", ...]`).
- (c) No wording adjustment: PRD §3.2 already pins "is created in `SCHEDULED` status" and "enters `INTAKE` once the logical clock date has reached `scheduled_open_date`" (inclusive, matching the impl's `<`); §2.4 pins the default clock 2026-09-01T00:00:00Z. Pure fixture bug — PRD already determines the behavior.

**Candidate 3 — §3.9 approve endpoint response semantics** (from `_drive_reevaluation_loop` stale-snapshot fix)
- (a) Subject: what the approve operation returns and the request's resulting state.
- (b) Impl paths enumerated and read: `routes_reeval.py:141-188` (sets `req["status"] = "APPROVED"` at line 174, returns the updated request via `ok(db.pub(req))` at 188); `test_suite/test_15_reevaluation.py:44-59` (fixed helper now returns the `approved` snapshot).
- (c) No wording adjustment: PRD §3.9 already pins "approves it, moving the request to `APPROVED`", and §2.2 pins "operations that create or modify a resource will return the created or updated resource object in the data field". Pure test-side bug — PRD already determines the behavior.

**Candidate 4 — implementation fixes:** none were applied in Step 7 ("the implementation was PRD-faithful on every failure"), so there is nothing to trace.

**Sibling unasserted paths:** coverage observations only (gate-1 coverage gap, dead duplicate check, first-time green ladders); none alters what the PRD must say, and the duplicate-check note is covered by Candidate 1's leave-verbatim ruling.

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → byte-identical; both 323 lines. Zero-edit outcome accepted (all Step 7 items were test-side bugs against PRD-pinned behavior).

## Step 9: Complete PRD scan — 2026-10-02T16:20:00.000Z

All edits verified. The diff is clean — 25 hunks, and the IMPL-BUG sentence in §3.7 ("must belong to the community's active cycle") is preserved verbatim at line 185.

## Summary

**Source vs output:** `/home/ubuntu/github/CodingPRD/tasks/task_3474_community_fire_protection_evaluation_class_assignment/workspace/PRD_FINALIZED.md` (323 lines / 59,320 chars; byte-identical to PRD.md) → `workspace/PRD_COMPLETED.md` (325 lines / 63,859 chars; **+4,539 chars**, 28 inline edits, no new sections).

**Counts:** 27 ambiguity-pins, 1 mismatch-revision (the §2.11 ownership-before-existence blanket statement — unimplementable as written for cross-linked path targets, revised to the impl's two-regime rule).

**IMPL BUGS found (PRD left unchanged):**
1. **Missing activation guard (medium).** `implementation/routes_classification.py:38-56` (and `cascade.py:100-135`) never checks that the activated classification's cycle is the community's active cycle, violating PRD §3.7: *"The classification activated out of a reevaluation cycle must belong to the community's active reevaluation cycle, just as an original activation must belong to the community's active cycle."* Reachable: publish a classification, withdraw the cycle (allowed from PUBLISHED/DISPUTED) — the classification stays PUBLISHED — then activate it; impl activates and even flips the WITHDRAWN cycle to EFFECTIVE.
2. **Check order, low severity (doubly-invalid input only).** `routes_cycle.py:51-58` validates `scheduled_open_date`/`data_freeze_date` (structural) before the community existence lookup, contradicting §2.11: *"Only after the target exists does the server evaluate … structural payload constraints"* (malformed date + nonexistent `community_id` → impl 400, ladder implies `ERR_COMMUNITY_NOT_FOUND` 404). All other create endpoints follow the ladder.
3. **Check order, low severity (doubly-invalid input only).** Withdrawal ownership is evaluated after the state-edge check in `routes_reeval.py:122-126` and `routes_appeals.py:122-128`; §2.11 puts entity-backed ownership ahead of state-machine legality (non-owner withdrawing from an illegal state → impl 409 `ERR_*_INVALID_STATE`, ladder implies 403 `ERR_NOT_OWNER`).

**Over-guard audit:** none — every impl check is PRD-stated or composable from the §2.11 structural rung; the leniency direction (state_code string-only, unknown fields ignored) was pinned instead.

**Change log (section — insert|revise — class — what — impl ref):**
- §2.2 — revise — ambiguity — `api_request_timestamp` pinned to server wall clock; logical clock governs resource stamps — response.py:10-12 vs db.py:53-54
- §2.2 — insert — ambiguity — routing-level `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) sit outside §5 catalogue — app.py:35-45
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; creation-timestamp ties broken by insertion sequence — util.py:145-168, db.py:88-90
- §2.4 — revise — ambiguity — clock-set echoes the submitted `to_iso8601` string verbatim as `current_utc`; malformed → 400 — routes_community.py:148-153
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — db.py:68
- §2.6 — insert — ambiguity — scores serialized as JSON numbers; trailing zeros not preserved — response.py:22-32
- §2.7 — insert — ambiguity — missing/non-integer version field → 400 `ERR_INVALID_REQUEST`; 412 reserved for present-but-mismatched — routes_cycle.py:172-174, routes_insurance.py:159-161, routes_reeval.py:153-155
- §2.11 — revise — **mismatch** (unimplementable as written) — ownership precedes existence only for same-type identifiers (body FKs, same-type path ids); cross-linked path targets 404 first, ownership enforced on the loaded linkage — routes_field.py:52/155, routes_water.py:116/161, routes_reeval.py:99-101, routes_credits.py:32-35
- §2.11 — insert — ambiguity — data-window check sits on the state-legality rung; payload leniency (extra fields ignored, strings format-free) — routes_water.py:163-165 vs 187-193, routes_community.py:23
- §3.1 — insert — ambiguity — comms numeric figures non-negative integers, flags boolean — routes_community.py:122-127
- §3.2 — insert — ambiguity — cycle-create order: community state → window conflict → freeze-after-open — routes_cycle.py:59-66
- §3.3 — insert — ambiguity — department numeric fields non-negative (two integer-typed) — routes_field.py:58-78
- §3.3 — insert — ambiguity — unknown apparatus `status` value → 400; known-but-illegal → 409 — routes_field.py:157-160
- §3.4 — insert — ambiguity — water-system PATCH re-validates registration bounds — routes_water.py:69-87
- §3.4 — insert — ambiguity — hydrant PATCH: status must be known enum (else 400); same-status accepted as a genuine mutation — routes_water.py:163-169
- §3.4 — insert — ambiguity — hydrant∉system mismatch → 400, checked after future-date, before pressure bounds — routes_water.py:188-193
- §3.4 — insert — ambiguity — corrected measurements re-validated against submission bounds; replacement copies `test_date`, `witnessed_by`=null, `certified_by`=correcting analyst — routes_water.py:280-297
- §3.6 — revise — ambiguity — score-sheet create requires cycle = `SCORING` (was "a scoring-phase state") — routes_cycle.py:168-170
- §3.6 — insert — ambiguity — `crr_raw_points`/`crr_effective_points` not re-rounded; only the percentage cap is — scoring.py:163-168
- §3.7 — insert — ambiguity — activation moves the classification's own cycle to `EFFECTIVE` — cascade.py:133-135
- §3.8 — revise — ambiguity — hydrant distance non-negative integer, station distance non-negative number — routes_insurance.py:30-34
- §3.8 — revise — ambiguity — `coverage_amount_cents`/`base_rate_bp` positive integers, `term_months` integer 1-120 — routes_insurance.py:97-101
- §3.8 — insert — ambiguity — quote-create order: classification presence → coverage period → numeric ranges → coverage cap — routes_insurance.py:86-104
- §3.9 — insert — ambiguity — reeval payload validation sits between the twelve-month gate and the duplicate gate — routes_reeval.py:48-57
- §3.9 — insert — ambiguity — denial `note` optional; `decision_note` null when omitted — routes_reeval.py:129-132
- §3.9 — revise — ambiguity — appeal window is exactly 90 days after `published_at` at timestamp precision; payload/community-match validation sits between window gate and duplicate gate — routes_appeals.py:52-63
- §3.9 — insert — ambiguity — `adjudication_note` accepted but not persisted (no such Appeal field) — routes_appeals.py:65-74

All 12 self-reported interpretation choices were verified against the code and are either now pinned (1,2,3,5,6,7,8,9,10,12) or were already PRD-pinned (4: unknown `target_state` → entity's own `ERR_*_INVALID_STATE`; 11: dual creditworthy-hydrant definitions in §3.4 raw vs §3.6 staleness-adjusted).

Orchestrator verification: PRD_COMPLETED.md 325 lines, 50 changed lines vs PRD_FINALIZED.md; §3.7 active-cycle sentence preserved verbatim at line 185. All 3 IMPL BUGs independently spot-confirmed in code: routes_classification.py `activate()` has no active-cycle check; routes_cycle.py validates dates (lines 53-54) before community existence (line 56); routes_reeval.py state-edge check precedes WITHDRAWN ownership check. → Proceeding to Step 9b (targeted impl fixes + full re-sweep).

## Step 9b: Fix 3 impl bugs + re-sweep — 2026-10-02T16:45:00.000Z

All 8 rounds pass 106/106. The fixes are complete and verified. Final summary:

## Step 9b fixes — task_3474

### Per-bug fix description

**BUG 1 (missing activation guard)** — `workspace/implementation/routes_classification.py`, `activate()`. After the existing checks (role → 404 → PUBLISHED → appeal-pending → `effective_from` temporal, order and error ids unchanged) and immediately before `activate_classification(...)`, added: load the classification's cycle via `db.find("cycles", cl["cycle_id"])`; if the cycle is missing or terminal (`EFFECTIVE`/`WITHDRAWN`), reject with `ERR_CYCLE_INVALID_STATE` (HTTP 409). Since a community has at most one non-terminal cycle, "classification's cycle is non-terminal" coincides with "is the community's active cycle" per PRD §3.7.

**BUG 2 (check order in cycle create)** — `implementation/routes_cycle.py`, `create_cycle()`. Reordered so `community_id` extraction (presence + `v_str` only) and the community 404 (`ERR_COMMUNITY_NOT_FOUND`) happen before `field_analyst_id`/date parsing and all other payload validation. Later checks unchanged and in original order: community state → analyst window conflict → freeze-after-open (PRD_COMPLETED §3.2), matching the pattern in `create_request()`.

**BUG 3 (withdrawal ownership after state-edge check)** — `implementation/routes_reeval.py` (`transition_request`) and `implementation/routes_appeals.py` (`transition_appeal`). In both, for `target == "WITHDRAWN"` only, the ownership check (`require_owner(... == uid)` → `ERR_NOT_OWNER` 403) now runs after the 404 and the per-target role gate but before the state-edge legality check. All other targets keep their order; unknown-target → `ERR_*_INVALID_STATE` behavior intact.

### Probe evidence (fresh server, dynamic port, killed exactly its PID)

- BUG1 repro: publish → withdraw cycle (200, `WITHDRAWN`; classification stays `PUBLISHED`) → activate → **409 ERR_CYCLE_INVALID_STATE**. Control: normal activate → **200**, classification `EFFECTIVE`, cycle `EFFECTIVE`.
- BUG2: POST cycle `{"community_id":"no-such-community", "scheduled_open_date":"not-a-date", ...}` → **404 ERR_COMMUNITY_NOT_FOUND**; control with existing community + malformed dates → **400 ERR_INVALID_REQUEST**.
- BUG3 appeals: owner withdraws FILED appeal (200, terminal) → non-owner re-withdraw → **403 ERR_NOT_OWNER**; owner re-withdraw → **409 ERR_APPEAL_INVALID_STATE**.
- BUG3 requests (clock advanced to 2027-10-01): owner withdraws SUBMITTED request (200) → non-owner re-withdraw → **403 ERR_NOT_OWNER**; owner re-withdraw → **409 ERR_REQUEST_INVALID_STATE**.

8/8 probes passed. `python3 -m compileall -q` clean.

### Stability sweep (8 concurrent rounds, per-test-server isolation)

All 8 rounds: **passed=106, failed=0, total=106**. No regressions; no test-side changes were needed or made. PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md / test_suite / test_helpers untouched.

### Artifacts on disk

All 8 required results files remain: `workspace/implementation/results.{1..8}.json`.

Orchestrator verification: re-read all 8 results files from disk — 106/106 × 8 confirmed; activation guard present at routes_classification.py:57; PRD_FINALIZED.md still byte-identical to PRD.md; 8 results files present. Pipeline complete.
