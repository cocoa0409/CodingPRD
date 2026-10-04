# Worklog — task_3480_federal_water_project_contract_allocation_reservoir_operation

## Step 1: Create task directory — 2026-10-02T13:20:00.000Z

Task directory `./tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/` was pre-allocated per command args; verified it exists with an empty `workspace/` subdirectory. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T14:16:00.000Z

All checks pass. The scaffold is complete and verified.

## Summary

**Output files (all written):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **15** | State machine entries: **11** (incl. DeliveryOrder parallel axes ×2) | Calculations: **12** | Validation priority rows: **11** | Endpoints: **48** | Error catalog: **34** | Roles: **7** (segregation-of-duties model; DistrictManager is entity-backed)
- §1.8 difficulty instances: **19** (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c)
- §1.9 corner instances: **69** (57 full recipes + 12 `excluded_because` stubs), spanning all 9 taxonomy sections
- 88 instance names unique across both files

**Difficulty design (beyond expert):** quota/allocation archetype × compliance/audit secondary; dual-variant calcs on two domains (priority-waterfall vs shortage-sharing on AllocationLine; projected vs settled on RevenuePeriod); combinatorial modes (a) nested min/max flood-holdback supply formula, (b) pinned per-release-then-sum rounding, (c) pinned supply→tier→share→cap evaluation order; cyclic transfer review loop (3-round cap) + parallel delivery axes; depth-3 curtailment cascade on publish vs depth-2 compliance-hold cascade on execute; priority pairs state-vs-fiscal and safety-vs-temporal; boundaries at exact ratio 0.75 and zero-quantity; pairwise half-open pulse windows vs aggregate daily outlet capacity; two compensating invariants (transfer acre-foot conservation, repayment dollar conservation with 1-cent remainder fixture); one OCC rule on WaterYear.version. All pinned literals (declared supplies 7,500/7,499/6,700/5,900/9,500, volumes 19,835/3,967/661, revenues 53,554,500/44,628,750/66,100/1, etc.) were verified by executing the formulas as code.

**Verification:** `scaffold_lint.py` verdict: **clean lint** — 805 calls scanned across both design files, all conform to §1.5; all §1.1 FKs reverse-reachable. Forbidden race vocabulary absent; file split honored; logical-clock default 2026-09-01T00:00:00Z declared on the `/\_clock/set_current_utc` endpoint.

**Heads-up for downstream:** 48 endpoints exceeds the 40-endpoint Step 6 threshold noted in memory (`scaffold-endpoint-overshoot-breaks-impl-gen`) — deliberate here given the "much harder than expert" instruction, but the impl-gen step should run with the pre-constraining prompt (one file per message, per-domain modules, no-truncation, self-smoke-test).

Orchestrator verification: all three YAMLs parse; SCAFFOLD.yaml top keys are §1.0–§1.7 with no design keys; api_prefix is `/water`; entities are District, WaterContract, WaterYear, HydrologyObservation, AllocationAnnouncement, AllocationLine, Reservoir, ReleaseOrder, EnvironmentalConstraint, ComplianceIncident, DeliveryOrder, RevenuePeriod, TransferRequest, ImpactReview, ShortageAgreement (15, all water-domain); 334 domain-vocabulary grep hits — no foreign-domain contamination.

## Step 3: Copy shared files — 2026-10-02T14:19:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T14:35:00.000Z

All audits pass. The PRD is complete.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/workspace/PRD.md` — 302 lines.

**Section list:**
- §1 Introduction (2 paragraphs: dual water/money ledgers, priority vs shortage-sharing framing)
- §2 Global Specifications: 2.1 RBAC (7 roles, identity semantics per role), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock & System Mount (unprefixed clock endpoint, fixed `2026-09-01T00:00:00Z` startup default), 2.5 Common Resource Properties (incl. the `HydrologyObservation` no-`updated_at`/no-`version` exception), 2.6 Units/Precision/Rounding, 2.7 OCC (single rule), 2.8 Nested/Referenced Resource Resolution, 2.9 Validation Ordering (all 11 tiers + sub-orders), 2.10 Standing Water & Money Invariants
- §3 Business Logic (8 subsections): 3.1 seeding (districts/contracts/reservoir), 3.2 water year & hydrology, 3.3 announcements (publish pipeline in 6 pinned steps), 3.4 shortage-sharing agreements, 3.5 releases & environmental compliance, 3.6 deliveries, 3.7 revenue & repayment settlement, 3.8 transfers/impact review/objection window
- §4 Endpoint Definitions (48 rows: 47 `/water` + `/_clock/set_current_utc`; 4 columns only)
- §5 Error Code Catalogue (34 rows, 2 columns)

**Zero-Silence Rule self-audit (scaffold rule → verbatim PRD mapping):** confirmed, no intentional gaps.
- Contract 1 (field names): 95 required identifiers (entity fields + request/query/path params incl. `current_utc`, `expected_water_year_version`, `decision`, `rationale`, `outcome`, `water_year_label`), 95 present in backticks, 0 missing.
- Contract 2 (rules): all 11 validation priority tiers expressed in §2.9 with explicit ordering/masking plus sub-orders (suspension-before-year, seller-before-buyer, safety a–d, storage-before-window); 1 OCC rule with endpoint + field + `ERR_STALE_VERSION`/412 and the "no other endpoint takes a version field" clause; all 11 state machines' transitions with preconditions paired to error ids and every side effect (publish cascade, curtailment, posture restore/unflag, settle credits, transfer line movements, SUSTAINED→VOIDED, quorum auto-RATIFIED, activation in-place recompute); all 12 calculations in precise reconstructible prose (incl. 1.9835 conversion, strict-less-than tier boundaries 0.50/0.75, per-contract rounding before cap, remainder-to-largest-outstanding rule, half-open interval overlap with adjacency allowed, per-day aggregate outlet capacity with equality allowed); every `applies_to` scope enumerated; structured field content (defaults, null-until fields, initial states) placed on owning entities — four `null until …` details patched in a follow-up pass; sibling branches (partial/full delivery, three decide outcomes, SUSTAINED/DISMISSED, projected/settled, waterfall/sharing) rendered with equal density. All 34 error ids appear in §2/§3 narrative.
- Contract 3 (§3 path purity): 518 §3 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

**Constraint compliance:** the two SCAFFOLD_*_DESIGN.yaml files were never opened or referenced; no processes were killed; all writes went only to the target PRD.md.

Orchestrator verification: PRD.md is 302 lines; `/_clock/set_current_utc` present (2 hits); startup default `2026-09-01T00:00:00Z` present; literals 1.9835 / 0.50 / 0.75 / ERR_STALE_VERSION all present.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T15:10:00.000Z

All checks pass — no duplication, file terminates cleanly. Stage 1 is complete.

## Stage 1 Summary — task_3480 test_helpers

### Files written (all py_compile OK, all import cleanly, error map registered with framework)

| File | Lines | Content |
|---|---|---|
| `test_helpers/__init__.py` | 197 | Barrel export: framework generics + all PRD-specific layers; documents the `api_client` singleton shadowing |
| `test_helpers/types.py` | 365 | 22 status/enum classes + 15 entity TypedDicts; `HydrologyObservation` correctly omits `updated_at`/`version` (PRD §2.5 sole exception) |
| `test_helpers/api_client.py` | 235 | 48 endpoint methods + `canonical_instant` + module singleton. Clock is **unprefixed** `POST /_clock/set_current_utc`; all other routes under `/water` (verified against PRD §2.4) |
| `test_helpers/api_errors.py` | 112 | 34 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map` (verified live: 34 entries in the framework registry) |
| `test_helpers/assertions.py` | 358 | `assert_{entity}` × 15, `assert_instant`/`assert_cents`/`assert_acre_feet`/`assert_two_dp`, envelope/common-field checks, `assert_repayment_invariant`, `assert_line_remaining` |
| `test_helpers/factories.py` | 430 | 31 payload builders; conditional-field constraint builder emits `required_min_cfs` XOR `max_release_cfs` per `requirement_type`, with override injection for the forbidden-field test; `price_cents` omitted unless given (server default 0) |
| `test_helpers/constants.py` | 276 | See table below |
| `test_helpers/test_users.py` | 91 | 7 roles; `make_district_manager_headers(district_id)` builder for the one entity-backed role; malformed-credential helpers + `UNDECLARED_ROLE` |
| `test_helpers/fixtures.py` | 868 | 73 functions in 5 tiers (see inventory below) |
| `test_suite/conftest.py` | 56 | Session-scoped `api` fixture returning the singleton + 6 opaque-role header fixtures |

### Constants table (name → value → PRD trace)

| Name | Value | PRD sentence |
|---|---|---|
| `CLOCK_STARTUP_DEFAULT` | `2026-09-01T00:00:00Z` | §2.4 "the logical clock reads exactly 2026-09-01T00:00:00Z" |
| `DEFAULT_LIMIT/MIN_LIMIT/MAX_LIMIT/DEFAULT_OFFSET` | 10/1/100/0 | §2.3 pagination defaults |
| Role constants ×7 | `SystemAdmin`…`RegionalDirector` | §2.1 "exactly seven roles" |
| `CFS_DAY_TO_AF` | 1.9835 | §2.6 "a fixed rate of 1.9835 acre-feet per cubic-foot-per-second sustained for one day" |
| `FLOOD_MONTHS` | (11,12,1,2,3) | §3.1 "November, December, January, February, and March" |
| `FLOOD_HOLDBACK_PCT` | 0.10 | §3.3 "multiplied by one tenth, rounded half up" |
| `TIER_1_RATIO` / `TIER_2_RATIO` | 0.75 / 0.50 | §3.3 "strictly below 0.50 classifies TIER_2; otherwise strictly below 0.75 classifies TIER_1" |
| `TRANSFER_REVISION_LIMIT` | 3 | §3.8 "a hard cap of three revision rounds applies" |
| `OBJECTION_WINDOW_HOURS` | 72 | §3.8 "seventy-two-hour objection window" |

Fixture-armed data (shared with the test plans): reservoir profiles `RESERVOIR_SMALL` (10,500 storage/5,000 dead/20,000 flood max/15,000 outlet/0.5 conv), `RESERVOIR_BIG` (3,000,000/200,000/3,600,000/…), `RESERVOIR_FLOOD` (initial 4,000,000 > flood max); districts SR/JR/TP; contracts C-100 SENIOR 6,000af/120M, C-200 JUNIOR 4,000af/80M, C-300 JUNIOR 1,000af/5M; settlement trio C-A/B/C at 7M/5M/3M; agreement 70/40/55/25 quorum 2; all clock waypoints. Derived expectations each carry the formula in a comment and were re-verified arithmetically: `DECLARED_BASE=7500` (NONE), `DECLARED_BOUNDARY=7499` (TIER_1), `DECLARED_SHORTAGE=5000` (TIER_1; sharing → SR 4200/JR 800), `DECLARED_REVISION=6700`, `DECLARED_APRIL=9500`, `DECLARED_LATE_OBS=5900`, `DECLARED_BIG=2,444,000`; volumes 19,835/3,967/661/42/2/397; revenue 11,901.0 MWh→53,554,500¢ projected vs 9,917.5→44,628,750¢ settled; 1-cent settle remainder → `UNRECOVERED_AFTER_ONE_CENT=14,999,999`.

### Factory/fixture inventory (name → entity → key preconditions)

- **Tier 1 atomics** (one API call each, correct role bound): `set_clock`, `create_district`, `create_contract`, `suspend_contract`, `create_reservoir(profile)`, `create_water_year`, `finalize_water_year`, `post_observation`, `create_announcement(expected_version)` (OCC), `publish_announcement`, `find_announcement`/`find_line`/`find_release` (list-based reads — the contract exposes no GET-single for those), `create_release`, `execute_release`, `create_constraint`, `find_open_incident`, `resolve_incident`, `create_delivery_order` (district-bound headers), `record_delivery`, `create_revenue_period`, `settle_period`, `create_transfer`/`decide_transfer`/`resubmit_transfer`/`execute_transfer`, `file_review` (reviewer-district headers), `resolve_review`, `create_agreement`/`ratify_agreement` (signatory = caller district)/`activate_agreement`.
- **Tier 2**: `setup_project(reservoir_profile, contract_plan)` — clock + reservoir + 3 districts + contracts ("standard" C-100/C-200, "standard_with_third", "settlement" trio, or None); returns a documented `world` dict including per-district manager headers.
- **Tier 3**: `setup_open_year` (project + year + hydrology, no announcement — for `ERR_YEAR_NOT_ANNOUNCED`/finalize/OCC tests), `setup_announced_year` (the workhorse base fixture: declared 7,500, NONE, SR 6,000/JR 1,500; parameterized by reservoir profile/snowpack/runoff/publish clock), `publish_revision` (optional fresher observations → clock → OCC-safe re-create → publish; handles both the April no-new-obs and the runoff-revision shapes).
- **Tier 4**: `setup_shortage_agreement(quorum, ratifiers, activate=)` (PROPOSED→RATIFIED→ACTIVATED with in-place line refresh), `setup_compliance_violation` (weak 400-cfs release + MIN_FLOW 500 + execute → OPEN incident, COMPLIANCE_HOLD), `setup_flagged_delivery` (announced big-reservoir year + hold + FLAGGED order), `setup_revenue_scenario(releases, executions, month, rate, settle=)` (covers all five revenue instances), `create_delivery`/`deliver_steps`, `create_transfer_request`, `setup_transfer_under_review`, `setup_transfer_approved`, `approve_transfer`, `advance_to_window_end`, `loop_transfer_revisions` (3 bounded rounds), `file_third_party_review`.
- **Tier 5**: `setup_transfer_executed` (approve → clock to exact window end → execute → lines refreshed), `setup_closed_year`.

### Verification results
- `python3 -m py_compile`: OK for all 10 files.
- Full package import + attribute sweep of fixtures (30 names) and factories (31 names): OK.
- Framework registration: `vv._error_http_status_map` has 34 entries with correct statuses (412/422/403 spot-checked).
- Constants arithmetic re-derived from the PRD formulas in Python: all match.
- Clock endpoint grep: unprefixed everywhere; no "scaffold" references in any generated file.

One note for Stage 2: there is **no GET-single endpoint** for announcements or releases — use `fixtures.find_announcement` / `fixtures.find_release` (list-filtered reads) when asserting on those rows after the fact.

Orchestrator verification: all 10 files re-compiled clean (2,988 lines total); constants spot-check matches PRD (TIER_1_RATIO=0.75, TIER_2_RATIO=0.50, CFS_DAY_TO_AF=1.9835, CLOCK_STARTUP_DEFAULT=2026-09-01T00:00:00Z); clock endpoint unprefixed in api_client.py. Orchestrator-measured design-index queues: queue A = 19 difficulty instances (all full; dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, resource_temporal_overlap 2, cross_entity_state_dependency 2, compensating_invariant 2); queue B = 57 corner full + 12 stubs (entities 10/0, state_machines 13/0, calculations 4/1, validations 21/0, endpoints 0/1, errors 0/8, rbac 5/1, cross_cutting 3/1, consistency_model 1/0). Stage 2 target: exactly 76 tests.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T15:55:00.000Z

All done. Final state verified: 76/76 tests, full tag resolution, complete queue coverage, all citations verbatim.

## Summary

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/test_suite/`, conftest.py untouched):

| File | Lines | Tests | Contents |
|---|---|---|---|
| test_01_contract_registry.py | 314 | 12 | 8 contract entity corners + duplicate number, singleton reservoir, version-on-suspend, 401 auth |
| test_02_water_years_and_announcements.py | 263 | 9 | finalize gate, supersede/repoint, double-publish, duplicate label, closed-year intake, immediate consistency, OCC 412 + OCC happy path, publish RBAC |
| test_03_supply_tier_and_volume.py | 170 | 5 | flood-holdback on/off (7,500 vs 9,500), 0.75 boundary (NONE vs TIER_1 at 7,499), latest-observed-on wins, round-half-up volume 42, suspended contract excluded from publish |
| test_04_delivery_and_curtailment.py | 333 | 10 | depth-3 curtailment cascade, suspension gate (×2, incl. priority over fiscal), zero quantity, remaining-balance formula, over/exactly-remaining, over-outstanding, terminal record-delivery, ownership 403 |
| test_05_release_scheduling_gates.py | 345 | 9 | min-flow beats past-schedule, aggregate outlet capacity (15,000 ok / 15,001 rejected), min-before-max sub-order, max alone, flood gate purpose-conditional, storage-before-window, past-schedule alone, half-open execution window, execute RBAC |
| test_06_environmental_compliance.py | 271 | 6 | parallel fulfillment/compliance axes, violation→HOLD→blocked-release cascade (deficit 100, storage 2,996,033), pulse adjacency vs overlap, storage ledger 3,030,165, conditional-field shape 400, constraint RBAC |
| test_07_revenue_and_settlement.py | 241 | 6 | projected-vs-settled divergence (11,901.0/9,917.5 MWh), per-release rounding order (661 vs 660.5), 1-cent remainder conservation (7M/5M/3M trio), month windowing, double-settle 409, duplicate period |
| test_08_transfer_lifecycle.py | 249 | 8 | bounded 3-round revision cycle, OPEN-year gate, transfer conservation (5,000+2,500=7,500), price_cents default 0, REJECTED lockdown, from-line fiscal gate, from==to 400, objection-window-open 409 |
| test_09_impact_reviews.py | 158 | 5 | SUSTAINED voids transfer (no ledger movement), ERR_REVIEW_PENDING gate released by DISMISSED, window-closed filing, duplicate review, reviewer-conflict SoD |
| test_10_shortage_sharing.py | 227 | 6 | waterfall→sharing dual basis (5,000/0 → 4,200/800), pinned cap evaluation order, quorum flip, unratified activate 409, NONE-tier activation conflict, duplicate ratify |

**AST audit table**: 76 tests, 76 tagged (each exactly one `Design:` tag as the docstring's last line), 0 tags pointing at non-existent instances, 0 tags on stubs, 0 dual-covers. Queue A 19/19, Queue B 57/57; the 12 `excluded_because` stubs correctly untranslated (cross-references all resolve to real difficulty instances). Separate citation audit: 108 PRD quotes across all docstrings, every one survives a whitespace-normalized literal grep of PRD.md.

**Skip list: empty.** Every non-stub instance passed the two-condition filter (verbatim PRD coverage + unique derivability).

**Helper-layer issues found (not fixed, per instructions)**:
1. `fixtures.publish_new_announcement` / `setup_announced_year` cannot publish when a contract in the world is SUSPENDED — `refresh_lines` calls `find_line` per world contract and asserts exactly one row, but a suspended contract correctly gets no line (PRD §3.3 ACTIVE-only input set). Worked around in `test_suspended_contract_skipped_by_next_publish` by hand-rolling create+publish without the line refresh.
2. One deliberate recipe deviation in `test_contract_version_increments_on_suspend_mutation`: the logical clock is advanced one day between create and suspend, because the recipe's "updated_at later than created_at" assertion is not uniquely derivable when both mutations share one logical instant (PRD §2.5 says only "refreshed"). With the clock moved, the inequality is forced by the PRD.

**Judgment call kept (not skipped)**: `contract_create_with_status_and_version_input_ignored` — acceptance of system-managed fields is the uniquely derivable reading because PRD §2.9 step 3 enumerates the shape checks exhaustively (none rejects documented system-managed fields) and §3.1 pins "its `status` starts `ACTIVE`" as the outcome regardless.

No tests were run against a server (none exists yet), as instructed; `python3 -m py_compile` passes on all 10 files.

Orchestrator independent AST re-audit: 76 tests, 0 with != 1 tag, 0 unresolved tags, 76/76 expected instances resolved, no missing, no duplicate coverage. Subagent claims verified against source.

## Step 6: Generate implementation — 2026-10-02T16:45:00.000Z

Implementation complete. All work verified end-to-end.

## Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Foreground launcher, guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 81 | App factory, **unprefixed** `POST /_clock/set_current_utc`, error handlers, blueprint registration |
| `store.py` | 90 | In-memory DB dicts (empty at boot, no seeding), logical clock (default `2026-09-01T00:00:00Z`), id/timestamp helpers |
| `errors.py` | 34 | `ApiError` + catalog helpers |
| `envelope.py` | 90 | `meta`/`response_type`/`data` envelope, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range 1..100) |
| `auth.py` | 34 | `X-User-ID`/`X-User-Role` checks, 7 roles |
| `validate.py` | 86 | Shape validators (types, enums, ranges, datetimes, `YYYY-MM`) |
| `serial.py` | 236 | 15 entity serializers (HydrologyObservation without `updated_at`/`version`) |
| `calc.py` | 294 | All 12 calculation rules (Decimal round-half-up throughout) |
| `routes_districts.py` | 120 | districts + contracts + suspend |
| `routes_years.py` | 115 | water years + finalize + observations |
| `routes_announce.py` | 166 | OCC-guarded announcement create, publish (supply→tier→basis→lines→supersede→cascade), allocation lines |
| `routes_reservoir.py` | 137 | singleton reservoir + environmental constraints |
| `routes_releases.py` | 160 | release orders (posture→min-flow→max-release→flood→capacity→past gate chain) + execute with incident creation |
| `routes_compliance.py` | 65 | incidents list/get/resolve + posture restore + unflag cascade |
| `routes_deliveries.py` | 118 | delivery orders + record-delivery (parallel compliance dimension) |
| `routes_revenue.py` | 88 | revenue periods (projected/settled) + credit distribution |
| `routes_transfers.py` | 206 | transfers: create/decide/resubmit/execute |
| `routes_reviews.py` | 110 | impact reviews + SUSTAINED→VOIDED |
| `routes_agreements.py` | 125 | shortage agreements: create/ratify(quorum)/activate(in-place sharing recompute) |

## Endpoint table — 48 routes registered (verified via `app.url_map`)
1 unprefixed clock + 47 under `/water`: districts (POST, GET), contracts (POST, GET, GET list, suspend), water-years (POST, GET, finalize), hydrology-observations (POST, GET), allocation-announcements (POST, GET, publish), allocation-lines (GET, GET id), reservoirs (POST, GET), release-orders (POST, GET, execute), environmental-constraints (POST, GET), compliance-incidents (GET, GET id, resolve), delivery-orders (POST, GET, GET id, record-delivery), revenue-periods (POST, GET, settle), transfer-requests (POST, GET, GET id, decide, resubmit, execute, impact-reviews POST), impact-reviews (GET, GET id, resolve), shortage-agreements (POST, GET, ratify, activate). Role assignments per PRD §4.

## Constant audit
All cross-module ALL-CAPS references resolve to exactly one definition: `calc.{CFS_DAY_TO_AF=1.9835, FC_HOLDBACK_PCT=0.10, FLOOD_MONTHS=(11,12,1,2,3), TIER_1_THRESHOLD_PCT=75, TIER_2_THRESHOLD_PCT=50, TRANSFER_REVISION_CAP=3, OBJECTION_WINDOW_HOURS=72, ACTIVE_ORDER_STATES, QUANT_INT, QUANT_MWH}`, `auth.ROLES/ALL_ROLES`, `store.DB/DEFAULT_CLOCK`, `envelope.DEFAULT_LIMIT/MIN_LIMIT/MAX_LIMIT/DEFAULT_OFFSET`, plus per-route enum tuples. Three initially-unused constants were removed. No referenced-but-undefined names; `python3 -m py_compile` passes on all 19 files.

## Smoke-test transcript (two self-launched servers on dynamic ports, both killed by exact PID)
- `POST /_clock/set_current_utc` (SystemAdmin) → 200 echoes `2026-10-15T08:00:00Z`; wrong role → 403 `ERR_FORBIDDEN`; no headers → 401 `ERR_UNAUTHENTICATED`
- District create → 201 (created_at uses logical clock); contract create → 201; duplicate `contract_number` → 409 `ERR_DUPLICATE_CONTRACT_NUMBER`; list → `response_type:"array"` with all 4 pagination meta fields
- Water year → `version:1`; announcement with `expected_water_year_version:99` → 412 `ERR_STALE_VERSION`; with 1 → 201, seq 1
- Reservoir (storage 40000, dead 5000, flood max 30000) + forecast 20000 + snowpack 80 → publish: `declared_supply_af=51000` (35000 usable + 16000 adjusted, October ⇒ no holdback), tier NONE, basis PRIORITY_WATERFALL; line allocated 5000/remaining 5000
- Delivery 500 by owning DistrictManager → CONFIRMED/CLEARED; foreign district → 403 `ERR_OWNERSHIP_MISMATCH`; record 200 → PARTIALLY_DELIVERED, 300 → DELIVERED; over-record → 409; line remaining 4500; suspend → 200 v2, new order → 409 `ERR_CONTRACT_SUSPENDED`
- Release 100 cfs×2d → volume 397; early execute → 422 `ERR_RELEASE_WINDOW_INVALID`; in-window execute → storage 39603; late-registered MIN_FLOW 500 constraint → new violating release blocked 422 `ERR_ENV_MIN_FLOW_VIOLATION`, but pre-scheduled R2 executes anyway → incident deficit 400, posture COMPLIANCE_HOLD; creation under hold → 409 `ERR_COMPLIANCE_HOLD`; resolve → posture NORMAL
- Revision publish in November (flood month): declared 47405 = 34405 usable + 16000 − 3000 holdback; transfer C-200→C-300 500 af: FILED review blocks APPROVE (`ERR_REVIEW_PENDING`), DISMISSED → APPROVED with window_end = clock+72h; early execute → 409 `ERR_OBJECTION_WINDOW_OPEN`; execute at exactly window end → 200, lines transfer_out/in 500, remaining 3500/3500
- Revenue period 2026-10: projected_mwh 198.5 (397 af × 0.5), revenue 992500; duplicate → 409; settle → credits 476400/317600/198500 across contracts (per-contract rounding, remainder 0); invariant `Σrepaid + unrecovered = total_obligation` holds (992500 + −742500 = 250000)
- Agreement: ratify ×1 → PROPOSED, re-ratify → 409 `ERR_ALREADY_RATIFIED`, second district → RATIFIED at quorum; activate on NONE-tier year → 409 `ERR_ACTIVATION_CONFLICT`
- **Fresh-boot isolation**: second launch showed `total_count: 0` on all lists and default-clock rejection (`ERR_SCHEDULE_IN_PAST` for an Aug-2026 schedule), confirming no carry-over state; both servers stopped cleanly via saved PIDs.

One judgment call to flag: the scaffold header says `endpoint_count: 46` but its own endpoint table (and the PRD §4 table) lists 48 — I implemented all 48 from the table. OCC-vs-year-CLOSED precedence on announcement create is unspecified (ERR_STALE_VERSION appears in no priority tier); I check `ERR_YEAR_CLOSED` (explicit priority 6) first, then OCC.

Orchestrator verification: all 19 .py files re-compile clean (2,365 lines + start.sh); live `app.url_map` shows exactly 48 rules with the sole unprefixed route `/_clock/set_current_utc`; no sqlite/file/pickle persistence anywhere. Subagent claims verified against source.

## Step 7: Run tests and iterate — 2026-10-02T16:43:18.000Z

All 8 rounds pass 76/76, and the evidence files remain in place.

## Summary

- **Iterations run:** 2 sweeps (initial: 75/76 in all 8 rounds, one consistent failure; final: 76/76 × 8 rounds, clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3480_federal_water_project_contract_allocation_reservoir_operation/test_suite/test_10_shortage_sharing.py` — `test_activate_unratified_agreement_returns_invalid_state`: the test activated a PROPOSED agreement against `water_year_label` 2027 while its setup (`setup_project` with no year opened) created no water year at all. That made the request carry an unresolvable body foreign key, which PRD §2.9 ("4. Existence — path identifiers resolve left to right, then body foreign keys in declared input order (ERR_NOT_FOUND)" before "6. State gates ... (ERR_INVALID_STATE)"; "an earlier failure masks every later one") requires to surface `ERR_NOT_FOUND`, masking the `ERR_INVALID_STATE` state gate the test asserted. The implementation was PRD-faithful; the test fixture was not. Fix: capture the `setup_project` world and call `fixtures.open_year(api, world)` so label 2027 exists and the state gate becomes the uniquely rejecting check; docstring updated to drop the PRD-contradicting "regardless of the year payload" claim and cite §2.9.

- **Fixes applied to `implementation/`:** none — the implementation's existence-before-state-gate ordering in `routes_agreements.py::activate_agreement` is exactly what PRD §2.9 prescribes.

Final state: 8/8 rounds clean (76 passed / 0 failed each), `results.{1..8}.json` preserved in `workspace/implementation/` per the output contract.

Orchestrator verification: all 8 results.${i}.json independently re-read — each passed=76/76 failed=0. Newest implementation source mtime (app.py 16:25:37) predates the final sweep results (16:43:18) — no post-sweep impl writes. test_10_shortage_sharing.py (mtime 16:40:55, the only recently-touched test file) contains the claimed `fixtures.open_year(api, world)` fix at line 163 and 0 hits for the removed PRD-contradicting phrase. Claims verified against source.

## Step 8: Finalize PRD — 2026-10-02T17:05:00.000Z

## Summary

**Result: zero edits. `PRD_FINALIZED.md` is byte-identical to `PRD.md`** (302 lines each, 0% delta; `diff -q` confirms identical).

### Per-item investigation evidence (mandatory for the zero-edit outcome)

The `<step_7_diff>` contains exactly one item: a pure test-fixture fix to `test_suite/test_10_shortage_sharing.py::test_activate_unratified_agreement_returns_invalid_state`, with zero implementation changes.

**PRD passages re-read (verbatim):**

- §2.9, line 107: "When several checks could reject the same request, the server applies them in a fixed order, and an earlier failure masks every later one."
- §2.9, line 112: "4. **Existence** — path identifiers resolve left to right, then body foreign keys in declared input order (`ERR_NOT_FOUND`)."
- §2.9, line 114: "6. **State gates** — the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE` ...)."
- §3.4, line 164: "A `RegionalDirector` activates a `RATIFIED` agreement — activating from any other status fails with `ERR_INVALID_STATE` — by naming a `water_year_label`. A water year with that label must exist (otherwise `ERR_NOT_FOUND`)."

**Impl code path inspected** — `workspace/implementation/routes_agreements.py`, `activate_agreement` (lines 78–94):
- Line 83: `agreement_or_404(agreement_id)` — path-identifier existence (§2.9 step 4).
- Lines 85–91: water-year lookup by label → `not_found("WaterYear")` — body foreign-key existence (§2.9 step 4, `ERR_NOT_FOUND`).
- Lines 92–94: `agreement["status"] != "RATIFIED"` → `ERR_INVALID_STATE` (§2.9 step 6).

The implementation checks the body-FK existence **before** the state gate, exactly matching §2.9's global ordering (existence at priority 4 masks the state gate at priority 6) and §3.4's endpoint-specific enumeration.

**Why unique-derivability already holds:** The fixed test asserts that activating a PROPOSED agreement against an *existing* water year (label 2027, opened via `fixtures.open_year`) yields `ERR_INVALID_STATE`. A fresh implementer reading PRD.md alone derives: (a) from §3.4, non-RATIFIED activation fails with `ERR_INVALID_STATE` and a missing year fails with `ERR_NOT_FOUND`; (b) from §2.9, when both checks could reject, existence fires first and masks the state gate. Both the old fixture's outcome (unresolvable label → `ERR_NOT_FOUND`) and the fixed fixture's outcome (resolvable label + PROPOSED → `ERR_INVALID_STATE`) are uniquely pinned. No PRD silence, no PRD/impl mismatch.

**No-new-mismatch global check:** Although no edit was committed, I still swept for contradicting wording that a hypothetical edit might have interacted with: grepped all `regardless` occurrences (lines 123, 192 — both about repayment-obligation sums over contracts "regardless of status," unrelated to activation ordering), all activation mentions (lines 7, 151, 162, 164, 261 — none assert state-gate-before-existence or a "regardless of the year payload" claim), and the ratification state-gate sentence (line 162, a different endpoint). Nothing in the PRD contradicts §2.9 + §3.4 for this behavior.

### Files
- `workspace/PRD_FINALIZED.md` — created, byte-identical copy of PRD.md.

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` run independently — BYTE-IDENTICAL confirmed (302 lines each).

## Step 9: Complete PRD — 2026-10-02T17:40:00.000Z

All 20 changed lines are the intended in-place edits; line count unchanged (302 → 302), +2,812 chars. The work is complete. Final verification: PRD_COMPLETED.md differs from PRD_FINALIZED.md only in the 20 pinned lines, and every catalog error_id in the impl is live (dead-code grep was clean — all 34 ids raised in reachable paths).

## Summary

**Produced** `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Stats:** PRD_FINALIZED.md 302 lines / 52,464 chars → PRD_COMPLETED.md 302 lines / 55,302 chars (char delta +2,812; 20 lines edited in place, no lines added or removed, no new sections).

**Counts:** 18 ambiguity-pins (all inserts/revisions within existing paragraphs), 0 mismatch-revisions, **0 IMPL BUGs** — every PRD-pinned formula, state gate, validation order tier, and error catalog entry was found correctly implemented and reachable; nothing unambiguous in the PRD is violated.

**Changes (one bullet each):**
- §2.3 — revise×3 — ambiguity — out-of-range/non-integer `limit`/`offset` fails `ERR_INVALID_REQUEST` (no clamping); `created_at` ties break by creation order; `total_count`/`has_more` semantics pinned — `envelope.py:52-90`
- §2.4 — revise — ambiguity — clock endpoint returns `200 OK`; `created_at`/`updated_at` explicitly logical-clock stamps; `meta.api_request_timestamp` is the wall-clock exception — `app.py:57`, `store.py:70-89`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `store.py:82`
- §2.7 — insert — ambiguity (the flagged Step-6 candidate) — the OCC comparison sits immediately after the state-gate tier: shape → year existence → `ERR_YEAR_CLOSED` → `ERR_STALE_VERSION`; a CLOSED year beats a stale version — `routes_announce.py:28-34`
- §3.1 — insert — ambiguity — `power_conversion_mwh_per_af` is a positive JSON number, need not be an integer (0.5 valid) — `routes_reservoir.py:41-51`, `validate.py:55`
- §3.2 — insert — ambiguity — observation tie beyond `observed_on`+`created_at` breaks toward the last-posted record — `calc.py:58-67`
- §3.3 — revise — ambiguity — a draft's null fields also include `allocation_basis` — `routes_announce.py:44`
- §3.3 — insert — ambiguity — publish evaluates the `CLOSED`-year refusal before the `DRAFT`-state check — `routes_announce.py:70-75`
- §3.3 — insert — ambiguity — publishing with no reservoir yet: usable storage and flood holdback are both zero — `calc.py:104-113`
- §3.3 — insert — ambiguity — a contract not `ACTIVE` at a revision publish gets no successor line; its orders stay homed on the superseded announcement's line — `routes_announce.py:102-119,139-145`
- §3.3 — revise — ambiguity — "CLOSED blocks deliveries/transfers" pinned to creation acts only (announcement creation, observation posting, delivery-order creation, transfer proposals); recording deliveries, deciding/resubmitting/executing transfers, and filing/resolving reviews keep their own gates — `routes_deliveries.py:98-118`, `routes_transfers.py:148-206`, `routes_reviews.py:24-65`
- §3.4 — insert — ambiguity — activation re-basis strikes shares over contracts `ACTIVE` at that moment; lines of no-longer-ACTIVE contracts keep their `allocated_af` — `routes_agreements.py:115-123`
- §3.4 — insert — ambiguity — a sharing-basis announcement classifying `NONE` (only via post-activation revision) uses the `TIER_1` guarantee columns — `calc.py:148-154`
- §3.6 — insert — ambiguity — delivery-order creation against a contract with no line on the current announcement fails `ERR_ALLOCATION_EXCEEDED` — `routes_deliveries.py:58-61`
- §3.7 — insert — ambiguity — zero total obligation (or no contracts): settlement distributes no credits, nothing else changes — `calc.py:281-294`, `routes_revenue.py:80-87`
- §3.8 — insert — ambiguity — transfer proposal with no seller line fails `ERR_ALLOCATION_EXCEEDED` — `routes_transfers.py:77-80`
- §3.8 — insert — ambiguity — an amended resubmit quantity must be > 0 (`ERR_INVALID_QUANTITY`); missing seller line covered by `ERR_ALLOCATION_EXCEEDED` — `routes_transfers.py:166-173`
- §3.8 — insert — ambiguity — transfer execution with a missing party line fails `ERR_NOT_FOUND` naming the allocation line — `routes_transfers.py:197-198`

**Adjudication notes:** The known OCC-vs-CLOSED candidate was genuine PRD silence (§2.9 never mentions `ERR_STALE_VERSION`), so the impl's order (CLOSED state gate first) is now pinned in §2.7. The §3.3 CLOSED-year sentence was adjudicated ambiguity rather than impl bug: §3.6/§3.8 enumerate exhaustive per-operation gate sets that omit any year check on record-delivery/execute, so the specific-governs-general reading the impl adopted is defensible and now pinned. No dead-code guards found; all 34 catalog error_ids are raised on live paths.

Orchestrator verification: PRD_COMPLETED.md is 302 lines (unchanged count) with exactly 40 diff lines vs PRD_FINALIZED.md (20 in-place edits as claimed). No implementation writes by Step 9 (newest impl source still app.py @ 16:25:37, predating the final sweep) — no re-sweep required. All 8 results.{i}.json files independently re-verified intact: 76/76 passed × 8 rounds.

## PIPELINE COMPLETE — 2026-10-02T17:40:00.000Z

Final state: 76/76 tests passing across all 8 parallel stability-sweep rounds under per-test-server isolation; zero test deletions; one test-fixture repair (Step 7); zero implementation fixes after generation; PRD_FINALIZED.md byte-identical (Step 8 zero-edit, justified); PRD_COMPLETED.md with 18 ambiguity-pins (Step 9). All output-contract artifacts present.
