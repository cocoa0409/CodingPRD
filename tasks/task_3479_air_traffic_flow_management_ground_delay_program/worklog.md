# Worklog — task_3479_air_traffic_flow_management_ground_delay_program

## Step 1: Create task directory — 2026-10-02T13:14:24.482Z

Task directory `./tasks/task_3479_air_traffic_flow_management_ground_delay_program/` was pre-allocated by the caller (already created with `workspace/` inside); verified it exists and used it as-is. No new index computed, no other task_* directory created. Scenario: FAA Air Traffic Flow Management & Ground Delay Program Administration. Difficulty instruction: "Generate task much harder than expert level!" (applies to scaffold generation only).

## Step 2: Generate scaffold — 2026-10-02T13:14Z (subagent), verified by orchestrator at completion

All checks pass. The scaffold package is complete and verified.

## Summary

**Task**: Air Traffic Flow Management & Ground Delay Program Administration — quota/allocation archetype (arrival-slot pool) blended with temporal windowing, flat topology, segregation-of-duties role model, immediate consistency. Difficulty is carried by coupling (RBS positional allocation, waterfall compression with in-pass slot reuse, dual-variant capacity and delay attribution, a depth-3 auto-downgrade cascade), not raw surface area.

**(a) Files (all parse as YAML, verified after every write):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/SCAFFOLD.yaml` — 1431 lines (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1428 lines, single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/SCAFFOLD_CORNER_DESIGN.yaml` — 2316 lines, single key `scaffold_corner_design`

**(b)** api_prefix: `/atfm` (clock endpoint deliberately unprefixed: `POST /_clock/set_current_utc`). Entities (13): Facility, Operator, ConstraintEvent, CapacityForecast, TrafficManagementInitiative, TMIRevision, Flight, ArrivalSlot, SlotTransaction, CompressionRun, GAAccommodationRequest, RerouteAssignment, OperatorDelayLedger.

**(c)** 43 endpoints — deliberately above the Expert band; note for the pipeline: >40 endpoints is the known impl-gen risk threshold, so Step 6 should be pre-constrained (per-domain modules, one file per message, self-smoke-test).

**(d)** §1.8: **19 instances across all 9 rules** (dual_variant 2, combinatorial 3 — one per mode a/b/c, non_linear 2, cascade 2, priority-conflict 2 with distinct category pairs, boundary 2 on distinct metrics/endpoints, cross-entity 2 on distinct pairs, overlap 2 with distinct interval semantics, invariant 2 on distinct conserved quantities). §1.9: **61 instances (53 full recipes + 8 excluded_because stubs)** across all 9 guide sections (entities 8, state_machines 10, calculations 7, validations 10, endpoints 4, errors 12, rbac 5, cross_cutting 4, consistency_model 1).

**(e)** All three files parse; `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (660 calls scanned). Additional mechanical audits passed: zero unbound `${var}` placeholders, 80 unique instance names, no forbidden race vocabulary, every error referenced and test-covered, every ground resolvable, all formula asserts pre-computed as literals (e.g., forecast 21 vs 17; fair shares 18/17 of 35; compression moves 4 / passes 2 / open 8; auto-downgrade to rate 12).

**(f)** Named constants — all pinned to concrete values in SCAFFOLD.yaml: WEATHER_IMPACT_STEP 0.15, STAFFING_IMPACT_STEP 0.10, EQUIPMENT_IMPACT_STEP 0.05, REPORTED_EVENT_WEIGHT 0.5, MIN_CAPACITY_FLOOR_PCT 10, GA_QUOTA_PCT 10, GA_MIN_RESERVED 1, COMPRESSION_MAX_PASSES 3, SUBSTITUTION_MAX_SHIFT_MINUTES 120, FLIGHT_DATA_FRESHNESS_SECONDS 3600, CONSTRAINT_EVENT_MAX_EXTENSIONS 2, GDP rate rule (6–60 and 3600 % r == 0), facility base rate [1,120], severity [1,5]. No named-but-unvalued constants.

**(g)** Logical clock: `POST /_clock/set_current_utc`, startup default **2026-09-01T00:00:00Z** (stated in the endpoint description, never wall-clock). All recipe timeline dates are 2026-09-15; the single sub-default value that briefly existed (a forged `created_at` the server must ignore) was rewritten to 2026-09-01T00:00:01Z, so **no §1.8/§1.9 recipe date precedes the clock default**.

result: task_3479 ATFM/GDP scaffold complete — 3 files (1431/1428/2316 lines), 13 entities, 43 endpoints, 38 errors, 19 difficulty + 61 corner instances, clean scaffold_lint verdict, all constants pinned, clock-safe.

Orchestrator verification: all 3 files exist and yaml.safe_load-parse; top-level keys exactly as claimed; `atfm` prefix present 117×; entity names (ArrivalSlot, CompressionRun, TrafficManagementInitiative) present 37×; clock endpoint path `/_clock/set_current_utc` confirmed unprefixed at SCAFFOLD.yaml:1327. Artifacts describe the ATFM domain (no foreign-domain contamination).

## Step 3: Copy shared files — 2026-10-02T14:42:07.223558453Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T14:5xZ (subagent), spot-checked by orchestrator

All checks pass. The PRD is complete and verified.

result: PRD generated at /home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/PRD.md (317 lines), all mechanical audits PASS.

**Structure**: §1 Introduction (3 paragraphs), §2 with 10 subsections (RBAC with role identities and exclusive/shared operations, verbatim §2.2 response envelope — verified byte-identical to the canonical source, pagination, common resource properties including the four record-type entities that lack `updated_at`/`version`, logical clock, a 20-item ordered validation-priority list, two OCC rules, precision/rounding, half-open window semantics, cascades/path resolution), §3 with 9 domain subsections (standing data, constraint events, forecasting, TMI proposal→activation with ration-by-schedule, flights/substitution/compression, revision cycle, GA accommodation, reroutes, termination/equity), §4 endpoint table (4 columns), §5 error catalogue (2 columns).

**Audit results** (grep/python against SCAFFOLD.yaml):
1. Endpoints: 43/43 `METHOD path` strings verbatim, including unprefixed `POST /_clock/set_current_utc` (no `/atfm` prefix leak; `/atfm/_clock` confirmed absent).
2. Error IDs: 38/38 verbatim, each with trigger conditions in §2.6 or §3 prose.
3. Constants: 11/11 named with adjacent values (WEATHER 0.15, STAFFING 0.10, EQUIPMENT 0.05, REPORTED_EVENT_WEIGHT 0.5, MIN_CAPACITY_FLOOR_PCT 10, GA_QUOTA_PCT 10, GA_MIN_RESERVED 1, COMPRESSION_MAX_PASSES 3, SUBSTITUTION_MAX_SHIFT_MINUTES 120, FLIGHT_DATA_FRESHNESS_SECONDS 3600, CONSTRAINT_EVENT_MAX_EXTENSIONS 2), plus GDP rate 6–60 with 3600-divisibility, base rate 1–120, severity 1–5.
4. Entities 13/13; state/enum names 27/27 verbatim.
5. Clock default `2026-09-01T00:00:00Z` verbatim (stated in §1, §2.5, and §4).
6. Contract 1 field coverage: 88/88 field/input/query/path identifiers in backticks (initial miss of `facility_id` was patched into §3.2).
7. Contract 3 §3 path purity: 578 backticked tokens scanned, 0 violations.
8. Contract 2 rule coverage: all 20 validation priorities with explicit ordering prose, both OCC rules (endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412), all state-machine transitions with preconditions and side effects, all 7 calculations as reconstructible prose formulas, all `applies_to` scopes enumerated — PASS by construction and spot-check.

**Known ambiguity sites for downstream steps** (scaffold-internal tensions transcribed faithfully, not resolved):
1. `cumulative_delay_minutes`: "sum of FINAL delay across COMPLETED programs" vs "adjusted by compensation reversals on TMI cancel" — a cancel cannot follow completion of the same TMI, so the coupling is loose.
2. Ledger invariant "attributed − reversed == 0 after a full cancel" vs per-release "attributed decremented and reversed incremented by the same amount" — taken literally these diverge; PRD states both sentences as the scaffold does.
3. ArrivalSlot `RELEASED` is listed as a terminal state yet has a `RELEASED → OPEN` transition at compression end; PRD phrases it as "terminal disposition, except compression reopening."
4. Substitution swaps `controlled_arrival` between the two flights and "conserves the assigned-slot multiset exactly"; the scaffold (and hence the PRD) does not state whether the ArrivalSlot rows' `assigned_flight_id` pointers exchange or stay put.

Orchestrator spot-check: PRD.md 316 lines; 89 `ERR_` mentions; clock endpoint unprefixed at lines 19/87/271 with `/atfm/_clock` confirmed absent (count 0); named constants present; clock default 2026-09-01T00:00:00Z verbatim.

## Step 5a: Generate test helpers (frozen) — 2026-10-02T15:0xZ (subagent), verified by orchestrator

Confirmed: the only glob match is `test_helpers/test_users.py` (the role-header helper, part of the canonical Stage-1 set); `test_suite/` holds only `conftest.py`. Stage 5a is complete.

**Summary**

**(a) Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/`):
- `test_helpers/__init__.py` — 210 lines (barrel export)
- `test_helpers/types.py` — 306 lines (15 status/type enums, 14 TypedDicts; the 4 append-only record types omit `updated_at`/`version` per PRD §2.4)
- `test_helpers/api_client.py` — 277 lines (`ApiClient(GenericApiClient)`, 48 methods covering all 41 `/atfm` routes + unprefixed `/_clock/set_current_utc`; **no module-level singleton**; plus `canonical_instant`)
- `test_helpers/api_errors.py` — 107 lines (38 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`)
- `test_helpers/assertions.py` — 384 lines (14 entity assertions, envelope/pagination/common-fields assertions, and expected-value computers: `expected_slot_time/count`, `expected_reserved_slots`, `expected_predicted_rate`, `event_factor`, `expected_delay_minutes`, `expected_hourly_bucket`, `is_valid_gdp_rate`, ledger/transaction collection helpers)
- `test_helpers/factories.py` — 266 lines (payload builders for every write endpoint + `at()` time helper pinned to scenario day 2026-09-15)
- `test_helpers/constants.py` — 94 lines
- `test_helpers/test_users.py` — 96 lines
- `test_helpers/fixtures.py` — 813 lines (5 tiers: atomic builders; gate composites; canonical ACTIVE GDP scenario + completed/cancelled variants; compression/GA/reroute/confirmed-events scenario packs; full-page readers with `limit=100` so 12-slot programs never truncate)
- `test_suite/conftest.py` — 58 lines (function-scoped `api` client for per-test-server isolation, role-header fixtures, `world` fixture = canonical ACTIVE GDP)

**(b) Constants and PRD sources** — all PRD-traceable, nothing stale: `CLOCK_STARTUP_DEFAULT` 2026-09-01T00:00:00Z (§2.5); pagination 10/1/100/0 (§2.3); facility rate [1,120] (§3.1); severity [1,5], `CONSTRAINT_EVENT_MAX_EXTENSIONS` 2 (§3.2); `WEATHER_IMPACT_STEP` 0.15, `STAFFING_IMPACT_STEP` 0.10, `EQUIPMENT_IMPACT_STEP` 0.05, `REPORTED_EVENT_WEIGHT` 0.5, `MIN_CAPACITY_FLOOR_PCT` 10 (§3.3); GDP rate 6–60 with `GDP_RATE_DIVISOR` 3600, AFP 1–60, GS 0 (§3.4); `GA_QUOTA_PCT` 10, `GA_MIN_RESERVED` 1 (§3.4); `FLIGHT_DATA_FRESHNESS_SECONDS` 3600, `SUBSTITUTION_MAX_SHIFT_MINUTES` 120, `COMPRESSION_MAX_PASSES` 3 (§3.5); `GA_DESIGNATOR_PREFIX`/`_ID_CHARS` "GA-"/8 (§3.7); role strings (§2.1). The recipe pin `2026-09-15T12:00:00Z` is deliberately in `fixtures.py` (`RECIPE_CLOCK`), not constants.py, since it's a design-index convention rather than a PRD literal.

**(c) Roles and ownership** — `SystemAdministrator` (sa-1), `FlowManager` (fm-1), `CommandCenterAdmin` (cc-1) are opaque per PRD §2.1; their ids are only *recorded* (`proposed_by_user_id`/`published_by_user_id`), so `make_flow_manager_headers`/`make_command_center_headers` exist to steer segregation-of-duties (default fm-1 ≠ cc-1 satisfies it; publishing as fm-1 violates it). `Operator` is entity-backed: `make_operator_headers(operator["id"])` is mandatory for ownership-gated writes and is threaded inside every fixture (`create_carrier`/`create_ga_operator` return `(operator, headers)`; `file_flight`, `update_flight`, `cancel_flight`, `create_ga_request` all build headers from the real operator id). Malformed-header builders (`headers_without_role`, `headers_without_user_id`, `headers_with_empty_role`, `headers_with_undeclared_role`) cover the 401 tier.

**(d) Smoke checks** — both run from the task root, both pass:
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → `ALL_COMPILE_OK`
- `PYTHONPATH=$PWD python3 - <<'EOF' …` importing all 9 modules → each prints `OK (module)`; `test_helpers.api_client` resolves to `module` (not an instance); frozen-surface spot checks reproduce the design recipes' pre-computed literals exactly (rate-21 PLANNING forecast, floor-clamped rate 3, slot 4 at 13:40 for rate 6, 12 slots/1 reserved, delay floor 5, 13:59→13:00 bucket, 7 rejected as a GDP rate). Error map diffed against PRD §5: 38 registered, zero missing, zero extras. No server was started and no pytest was run.

**(e) PRD ambiguities resolved in helper behavior**:
1. *Facility list endpoint*: PRD §2.1's shared-read list omits `GET /atfm/facilities` (collection) — only `GET /atfm/facilities/{id}` exists — so no list-facilities client method was generated (matches the endpoint table).
2. *Flight `estimated_arrival` when omitted*: PRD says it defaults to `scheduled_arrival`, so `assert_flight` requires the field present (non-null) on reads, and factories omit it unless given.
3. *GROUND_STOP vs REROUTE rate*: GS recipes pass `controlled_rate: 0` explicitly while REROUTE omits it (stored 0); `tmi_payload` omits unless given, and `setup_published_tmi` passes 6 only for GDP by default.
4. *List readers*: envelope default limit 10 would truncate 12-slot programs, so fixtures' readers default to `limit=100` (within the PRD max).
5. *`setup_published_tmi` forecast gate*: created only for GDP/AFP since GS/REROUTE are gate-exempt (PRD §3.4).

**(f)** No `test_*.py` test files were written — Stage 5b's job; `test_suite/` contains only `conftest.py`.

result: Stage 5a test infrastructure frozen for task_3479 (ATFM/GDP): 9 helper modules + conftest, 2611 lines, all compile/import checks green, 38/38 PRD errors mapped, recipe math verified against frozen helpers.

Orchestrator verification: 9 helper modules + conftest present; `python3 -m py_compile` on all → COMPILE_OK; `importlib.import_module('test_helpers.api_client')` → type `module` (no singleton shadow); constants WEATHER_IMPACT_STEP=0.15, COMPRESSION_MAX_PASSES=3, SUBSTITUTION_MAX_SHIFT_MINUTES=120, CLOCK_STARTUP_DEFAULT=2026-09-01T00:00:00Z all PRD-correct; api_client has 45 defs.

Orchestrator note for 5b: measured queue sizes from YAML (not subagent-reported): Queue A = 19 instances across 9 rule_ids (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2). Queue B = 53 non-stub (entities 8, state_machines 10, calculations 6, validations 10, endpoints 4, errors 5, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1) + 8 excluded_because stubs that must NOT be emitted. Total non-stub = 72.

## Step 5b: Generate test suite — 2026-10-02T15:4xZ (subagent), independently re-audited by orchestrator

All checks green. Final summary:

**(a) Test files written** (18 files, 2957 lines, all under `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/test_suite/`): test_01_difficulty_dual_variant_calc.py (132), test_02_difficulty_combinatorial_formula.py (207), test_03_difficulty_non_linear_state_machine.py (134), test_04_difficulty_transitive_cascade.py (160), test_05_difficulty_priority_pair.py (108), test_06_difficulty_boundary_precision.py (122), test_07_difficulty_cross_entity_state.py (113), test_08_difficulty_resource_temporal_overlap.py (144), test_09_difficulty_compensating_invariant.py (133), test_10_corner_entities.py (232), test_11_corner_state_machines.py (300), test_12_corner_calculations.py (255), test_13_corner_validations.py (267), test_14_corner_endpoints.py (176), test_15_corner_errors.py (137), test_16_corner_rbac.py (143), test_17_corner_cross_cutting_occ.py (154), test_18_corner_consistency_model.py (40). conftest.py untouched.

**(b) Emitted vs skipped**: Queue A 19/19 emitted; Queue B 53/53 non-stub emitted; 8 `excluded_because` stubs emitted nothing (as required). Zero PRD-silence skips. Total 72 tests = the stated maximum.

**(c) AST tag-audit output (verbatim, final run, EXIT=0)**:
```
authoritative instances: difficulty=19, corner_non_stub=53, corner_stubs=8
tests parsed: 72
emitted tags: 72 (total references: 72)
skipped instances: 0
tag audit: CLEAN (no unknown/stub/duplicate/untagged)
PRD citation check: CLEAN (106 quotations verified)
```
The audit is a real `ast` walk (FunctionDef docstrings via `ast.get_docstring`, `Design:` line collection) diffed against `yaml.safe_load`-parsed instance sets, plus a verbatim-substring check of every `PRD §...: "..."` quotation against PRD.md. It initially flagged 14 non-verbatim quotations (PRD §2.6's bold `**Heading.**` lead-ins and one list-marker boundary sat inside my quoted spans); all 14 were fixed and the rerun is clean. Additionally, all 18 modules were import-smoke-tested against the real frozen `test_helpers` package (PYTHONPATH=..), confirming every imported name exists.

**(d) Frozen integrity**: `sha256sum` of all `test_helpers/*.py` + `test_suite/conftest.py` is byte-identical before/after (`FROZEN-UNMODIFIED`), and no frozen `.py` source is newer than the pre-start marker file.

**(e) PRD-silence skips forced on emittable-expected instances**: none. Two design-index literal bugs were re-derived against the PRD rather than copied (claims preserved, wrong literals dropped): (1) `Corner/endpoints/slot_transactions_chronological` — the YAML's `-5` delta for F2's swap contradicts §3.5's signed-change definition (F2's delay is 0 before and after); I asserted the PRD-derivable core (4-row log, INITIAL-before-SWAP chronology via a mid-test clock advance, F1's +5, filter count 2) and omitted F2's contested delta; (2) `Corner/endpoints/delay_ledgers_dual_reachable` — the recipe's A1 at 12:55 is ineligible (precedes program_start 13:00), so its "attributed 5" is unreachable; re-derived with A1 at 13:05, preserving the dual-reachability claim with attributed 0/0. Also noted: `flight_parallel_dimensions`'s comment line ("slotted at 13:30/13:20") contradicts its own 2-flight API chain; only the PRD-pinned dimension-independence claims are asserted, no CTA literals.

result: Stage 5b complete — 72/72 design instances emitted as tests across 18 files, zero skips, AST tag audit and 106-quotation PRD verbatim check both clean, frozen helpers untouched.

Orchestrator independent re-audit: own AST parse of all 18 test files vs yaml.safe_load of both design YAMLs → expected 72, emitted 72, unique 72, missing [], unknown [], duplicates []. `pytest --collect-only -q` → 72 tests collected, 0 errors (no dangling imports).

## Step 6: Generate implementation — 2026-10-02T16:3xZ (subagent), verified by orchestrator

All checks complete. Final summary follows.

## (a) File tree (workspace/implementation/, 3503 lines total)

```
start.sh              10   requirements.txt       1
app.py                81   storage.py           127
constants.py          82   errors.py             54
util.py              217   serialize.py         237
validation.py        164   ledger.py            164
capacity.py          232   allocation.py        265
ops.py               324   routes_facilities.py 123
routes_events.py     191   routes_forecasts.py   74
routes_tmis.py       434   routes_flights.py    243
routes_slots.py       50   routes_ops.py        115
routes_ga.py         152   routes_reroutes.py   107
routes_ledgers.py     31   routes_clock.py       25
```

## (b) Compile + import evidence

`python3 -m py_compile` on all 23 .py files: clean. `python3 -c "from app import app"`: OK — no dangling imports. `start.sh` is executable, guarded-install, `exec python3 app.py`, binds 0.0.0.0:$PORT (default 10000).

## (c) Smoke-test transcript (two fresh-process boots, dynamic ports 37319/55113/58075)

Slice 1 (run twice, identical results — no cross-boot state): clock set → `{"current_utc": "2026-09-01T00:00:00Z"}`; facility KEWR (base 60) 201; operator 201; flights filed (last_eta_reported_at = logical clock); event WEATHER/2 201 REPORTED; PLANNING forecast predicted 60 (REPORTED excluded) → publish → confirm event → forecast **STALE** via cascade; fresh forecast predicted **42** (=⌊60·(1−0.15·2)⌋); GDP propose → publish by proposer → **422 ERR_SEGREGATION_OF_DUTIES** → publish by other admin 200 → activate → 6 slots (slot 5 `is_ga_reserved`), DAL-style assignment A→06:00 d0, B→06:10 d9; substitution → txn for flight_id_1 with `delay_delta_minutes` +10 (counterpart −9); ledger (fc 2, attributed 10, fair 10, dev 0); cancel A → CANCELLED/UNCONTROLLED/0, ledger (fc 1, attributed 0), RELEASE txn −10; compression → `{released_slot_count:1, moves_made:0, passes_executed:1, remaining_open_slots:5}`; GA request → adjudicate ACCOMMODATE → ACCOMMODATED at 06:50 (reserved slot); complete → COMPLETED, GA operator `cumulative_delay_minutes` 20, carrier 0; activate after completion → **409 ERR_TMI_TERMINAL**. Unauthenticated request → **401 ERR_UNAUTHENTICATED**.

Slice 2 (revision cycle): activate rate 6 (delays 0/9/18, attributed 27) → manual revision 6→12 (OCC `expected_tmi_version`) → substitution while REVISING → **409 ERR_TMI_NOT_ACTIVE** → activate applies revision: B 06:05 d4 / C 06:10 d8 with REVISION_MOVE −5/−10, unchanged flight gets no txn → confirm WEATHER sev5 (implied 15 ≥ 12: no downgrade) → confirm STAFFING sev5 (implied ⌊60·0.25·0.5⌋=7 < 12): TMI auto→REVISING, revision #2 `SYSTEM_AUTO_DOWNGRADE`/`AUTO_CAPACITY_DOWNGRADE`/new_rate 6 → activate applies it (rate 6, CTAs back to 06:10/06:20) → cancel: ledger attributed 27 / reversed 27 (balance 0), flights reverted, 3 REVERSAL txns.

## (d) Endpoint coverage: 43/43

Flask url_map diff against PRD §4: **missing: [], extra: []** (after disabling Flask's built-in /static helper). All 42 `/atfm` routes plus unprefixed `POST /_clock/set_current_utc` registered; clock mounted only unprefixed.

## (e) Interpretations chosen and no-invented-gates self-report

**Interpretations chosen** (PRD admitted multiple readings):
1. **TMI-cancel ledger math** — PRD/scaffold say "attributed decremented AND reversed incremented," but both also state the invariant "attributed − reversed == 0 after a full cancel," which the decrement reading makes arithmetically impossible (it yields −A₀). I increment `reversed_delay_minutes` only; attributed stays, so the twice-stated invariant holds (verified: 27/27).
2. **Overflow flights** — literal field rule "0 while UNCONTROLLED": overflow flights keep `provisional_delay_minutes` 0 (INITIAL_ASSIGNMENT `delay_delta` 0) but count in ledger `flight_count` ("slots or virtual CTAs"). At completion, "each controlled flight" = every flight with a non-null `controlled_arrival` (SLOTTED + overflow); overflow finals compute to 0.
3. **created_at/updated_at/api_request_timestamp use wall clock** — PRD §2.5's logical-clock consumer list names only window/freshness/bucket rules and the four workflow instants (`published_at`, `activated_at`, `applied_at`, `last_eta_reported_at`); created_at is not listed, and wall clock gives natural tie-break ordering. Logical-clock stamps serialize without fraction when whole-second; created_at always 3-digit millis per PRD 2.4.
4. **Validation ordering** — per PRD §2.6 numbers (window 8 → past 9 → overlap 13/14 → rate 15 → capacity 20), overriding the scaffold state-machine bullet order where they disagreed (extend: window → overlap → extension cap). Structural 400s slot after auth/ownership/existence. OCC on flight updates runs before the state check (state machine lists it so); on revisions, after ACTIVE check.
5. **Ownership vs existence for body refs** — ownership (priority 3) is evaluated over resolvable body flight refs first; unresolvable refs then fail existence (404).
6. **Reroute on a non-REROUTE TMI** → `ERR_INVALID_REQUEST` (catalog has no TMI-type error for reroutes); **compression on non-GDP ACTIVE TMI** → `ERR_TMI_TYPE_NOT_GDP` (compression is slot machinery; the catalog id covers slot operations against non-GDP TMIs).
7. **"Opposite delay_delta_minutes"** in substitution = opposite-signed per-flight deltas (new prov − old prov), not forced equal magnitudes.
8. **Substitution transaction slot_id** = the slot the flight moved into.
9. **REAPPLY GA-keep** — GA-accommodated flights keep their exact slot rows/CTAs; coincident new-grid slots adopt the kept row (index/flag updated); off-grid kept rows persist unchanged. New assignments during reapply journal REVISION_MOVE (from null for newly slotted; to null for dropped-from-program).
10. **Flight cancel of an overflow flight** — the release cascade is conditioned on holding an ASSIGNED slot, so an overflow cancel only flips ops_status (no ledger decrement).
11. **Revision rate shape** — PRD §3.6 says a supplied `new_controlled_rate` "must satisfy the GDP rate shape"; applied literally regardless of TMI type. Capacity gate at revision runs only when a new rate is supplied, over the post-revision window.
12. **Cancel of an already-CANCELLED flight** → `ERR_INVALID_STATE` (`ERR_FLIGHT_NOT_CANCELLABLE` is explicitly AIRBORNE/LANDED only).
13. **GA-created flight origin** — cascade specifies designator/scheduled/facility only; `origin` set to the placeholder "GA". GA flights are born SLOTTED at version 1 (creation constitutes the assignment).
14. Compression GA-promotion picks the earliest in-window reserved pool slot; "no WAITLISTED GA request" for carrier access to reserved pool slots is evaluated after promotion (stable across passes). Freshness boundary inclusive: age ≤ 3600s is fresh.

**No-invented-gates self-report** — guards implemented that are not verbatim PRD rules, with justification:
- PATCH /atfm/facilities with neither `base_acceptance_rate` nor `status` → 400 (malformed: no updatable field; "update X and/or Y" implies at least one).
- `base_acceptance_rate` re-validated to [1,120] on PATCH (same field invariant as create).
- Flight update with neither `new_eta` nor `new_ops_status` → 400 ("may carry X, Y, or both" — neither is outside the enumerated set).
- `new_ops_status` outside {AIRBORNE, LANDED} → 400 (unknown enum for the field's domain).
- Negative/non-integer `offset` → 400 (limit's [1,100] is explicit; offset treated symmetrically).
- Reroute-on-non-REROUTE → 400 (item 6 above — the endpoint's stated scope; no catalog id exists).
- 404/405 handlers for undeclared routes return envelope errors (test-harness robustness only).
- `ERR_INTERNAL` 500 catch-all (off-catalog by design; unreachable in the smokes).
No other guards: no invented ownership checks (SystemAdministrator/FlowManager/CommandCenterAdmin ids are opaque, never entity-compared), no invented state gates, capacity gate absent at proposal per PRD.

## (f) Dead-code audit — 38/38 error_ids

Mechanical grep across all modules: every one of the 38 catalog error_ids has ≥1 raise site (`ApiError("ERR_…")` / `error_response("ERR_…")`); zero raise sites reference undefined ids (only the deliberate `ERR_INTERNAL` catch-all). Validator call-site check: `auth_context` and `require_roles` at 43/43 endpoints; `check_window` 4, `check_rate_shape` 1, `check_gdp_rate` 1, `tmi_require_active` 5, `tmi_terminal_guard` 4, `windows_overlap` 7 — every defined validator is called on its request path, and every called validator is defined.

result: ATFM Ground Delay Program implementation complete at /home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/implementation/ — 23 Python modules + start.sh, all compile, app imports, 43/43 routes registered (clock unprefixed), two fresh-boot smoke suites pass end-to-end (forecast math, RBS allocation, substitution, compression, GA accommodation, manual + auto-downgrade revision cycles, cancel compensation, completion attribution), 38/38 error_ids live, constants exact and single-sourced.

Orchestrator verification: py_compile all 23 modules → COMPILE_OK; `from app import app` OK; url_map = 43 routes; clock routes = ['/_clock/set_current_utc'] only; zero non-/atfm non-clock routes; start.sh binds $PORT with guarded pip install. Constants drift check at Step 6→7 hand-off: 11/11 named constants identical between implementation/constants.py and test_helpers/constants.py (0.15/0.10/0.05/0.5/10/10/1/3/120/3600/2) — DRIFTS: none.

## Step 7: Test-fix iteration loop — 2026-10-02T17:3xZ (long-lived subagent), verified by orchestrator

Clean exit sweep confirmed: 72/72 in all 8 parallel rounds, artifacts preserved.

**Summary**

- **Iterations run:** 3 sweeps (round 1: 64/72; round 2 after UUID + ledger fixes: 70/72; round 3 after clock fix: 72/72 × 8, zero union failures).
- **Tests deleted:** none — every failing assertion traced to verbatim PRD prose.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:**
  1. `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/implementation/storage.py` — `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.4: "The `id` is a server-minted UUID"; the canonical UUID rendering is dashed 8-4-4-4-12, which the suite's `is_valid_uuid` requires. Fixed 6 tests (facility/flight/revision/slot_transaction/ledger id assertions).
  2. `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/implementation/routes_tmis.py` — `cancel_tmi` compensation cascade: added `ledger["attributed_delay_minutes"] -= prior` alongside the existing `reversed_delay_minutes += prior`. PRD §3.9 states verbatim "the operator's ledger has `attributed_delay_minutes` decremented and `reversed_delay_minutes` incremented by that same amount"; SCAFFOLD's cascade says the same. The prior implementation satisfied only the PRD's (arithmetically incompatible) "balance reads zero" gloss; the operational rule arbitrates. Fixed `test_cancel_releases_slots_and_reverses_ledgers` and `test_forward_then_compensating_actions_sum_to_zero`.
  3. `/home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/implementation/storage.py` + `util.py` — `create_entity`, `create_record`, `touch`, and the meta `api_request_timestamp` now stamp from the logical clock (`get_clock()`) instead of `now_wall()`. PRD §2.1: "All time-based behavior in the system reads a logical clock rather than the wall clock." Fixed `test_facility_born_operational_with_system_fields` and `test_forged_system_fields_ignored`. The §2.4 three-fractional-digit rendering (`fmt_ts`) is unchanged, and `assert_instant` compares instants semantically, so whole-second logical stamps remain compliant.

result: task_3479 ATFM ground delay program — clean 8-round parallel sweep, 72/72 tests passing in every round, 3 implementation fixes (UUID rendering, TMI-cancel ledger decrement, logical-clock system timestamps), zero test deletions, results.1-8.json preserved in workspace/implementation/.

Orchestrator verification: results.1.json … results.8.json all present on disk; each reports passed=72 total=72 failed=0. Note for Step 8: fix #2 reverses Step 6's "interpretation chosen #1" — PRD_FINALIZED must resolve the doc-gen-flagged §3.9 tension (ledger invariant gloss vs operational decrement+increment sentence) in favor of the operational sentence the implementation now exhibits.

## Step 8: Finalize PRD — 2026-10-02T18:1xZ (subagent), diff verified by orchestrator

Diff verified: exactly 4 lines changed (48, 81, 87, 215), all others byte-identical. The work is complete. Final summary:

## Summary on exit

**Line counts / delta:** PRD.md 316 lines / 67,211 chars; PRD_FINALIZED.md 316 lines / 67,715 chars; +504 chars (**+0.75%**), 4 lines revised, 0 lines added or removed, no new sections.

**Changes (one bullet per change):**
- §2.4 — revise — `id` pinned as "a server-minted UUID (version 4) rendered in the canonical hyphenated 8-4-4-4-12 hexadecimal form" (was: unpinned "server-minted UUID") — implementation/storage.py:50-51 (`new_id` returns `str(uuid.uuid4())`); consumed via create_entity storage.py:106 and create_record storage.py:122.
- §2.4 — revise — `created_at`/`updated_at` pinned as "stamped from the logical clock (§2.5)" — implementation/storage.py:104 (create_entity), storage.py:123 (create_record), storage.py:97 (touch).
- §2.2 — revise — `api_request_timestamp` pinned as "stamped from the logical clock (§2.5)" — implementation/util.py:70 (`_request_meta`, shared by success_object/success_list/error_response).
- §2.5 — revise — consumer enumeration extended: the logical clock also stamps `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2) — same impl sites as above; closes the "§2.5's list is exhaustive" misreading that caused the fixture failures.
- §3.9 — revise — cancel-cascade invariant gloss replaced: the false "attributed-minus-reversed balance reads zero" became "after a full cancellation the ledger's `attributed_delay_minutes` reads zero and its `reversed_delay_minutes` equals the total attributed delay the cancellation reversed" — implementation/routes_tmis.py:379-380 (both the decrement and the increment now ship).

**Per-edit pre-edit search log:**

1. **§2.4 id rendering (fix 1).** (a) Subject: resource-id string format. (b) Enumerated: storage.py:50-51 (sole minting site), create_entity:106 / create_record:122 (every resource and record type); serialize.py:13,22 (id passed through unmodified); ops.py:87 GA designator `"GA-" + request["id"][:8]` — the dash sits at index 8, so the first 8 chars are hex-only and identical under either rendering; util.py:69 `api_request_id` uses `.hex[:20]` but is envelope metadata, not a resource id (§2.2 pins only the `req_` prefix); validation.py:44-104 all `get_*` fetchers are format-agnostic dict lookups (404 on miss regardless of id shape); suite's `is_valid_uuid` regex `^[0-9a-f]{8}-[0-9a-f]{4}-...{12}$` requires dashes, pins no version nibble. (c) Wording adjustment: added "(version 4)" since impl always mints v4; deliberately did not claim version enforcement on input, since no impl path validates inbound id format.

2. **§2.4 created_at/updated_at clock (fix 3).** (a) Subject: source clock for system-maintained common fields. (b) Enumerated: storage.py:104,123,97 (all stamp `get_clock()`; `now_wall` at storage.py:54-55 is defined but never called anywhere); serialize.py:15-16,22 render via `fmt_ts` (util.py:30-34), which always emits three fractional digits — whole-second logical stamps serialize as `.000Z`, so §2.4's "three fractional digits" and §2.8's identical claim stay true; the four record types (§2.4 paragraph 2) get `created_at` via create_record, also covered. (c) Wording: "stamped from the logical clock (§2.5)" / "same format and the same clock" — scoped to the two fields only; no claim about domain datetimes (`fmt_dt` echoes), which stay input-derived.

3. **§2.2 api_request_timestamp clock (fix 3).** (a) Subject: source clock for the envelope meta timestamp. (b) Enumerated: util.py:67-71 `_request_meta` is the single builder, shared by success_object, success_list, and error_response — so the logical-clock source holds for 2xx and 4xx envelopes alike; §2.2's error-envelope section reuses the same meta field, so the one bullet covers both. (c) Wording: appended clause only; left "server-generated ISO 8601 UTC timestamp with three fractional digits" verbatim (fmt_ts guarantees it).

4. **§2.5 consumer list (fix 3, central pin).** (a) Subject: exhaustive-ness of the logical-clock consumer enumeration. (b) Enumerated every `get_clock()` call site: storage.py:97/104/123, util.py:70, routes_tmis.py:81/208/266, routes_forecasts.py:72, allocation.py:172, routes_flights.py:77/165, ops.py:82/93, routes_ops.py:56, routes_clock.py:25; confirmed the pre-existing list items (window checks, freshness, workflow instants) are all real consumers and left them verbatim; noted "reroute hourly bucketing" actually derives from `estimated_arrival` (routes_reroutes.py:52) — a pre-existing oddity outside step_7_diff scope, left untouched and not relied upon. §1's universal "All time-based behavior ... reads a logical clock" is consistent with the addition. (c) Wording: appended a new sentence rather than rewriting the list, explicitly covering §2.4 fields and the §2.2 envelope timestamp so the list can no longer read as exhaustive against them.

5. **§3.9 cancel-cascade gloss (fix 2).** (a) Subject: ledger fields moved by program cancellation and the invariant they establish. (b) Enumerated every writer/reader of `attributed_delay_minutes`/`reversed_delay_minutes`: routes_tmis.py:337-385 (cancel; sole writer of `reversed_delay_minutes`; no fair-share recompute, no `flight_count` change, no `cumulative_delay_minutes` touch); routes_flights.py:172-228 (flight cancel: attributed -= prior, flight_count -= 1, no reversed — §3.5's wording already matches it, so my edit stays scoped to program cancellation); allocation.py:112-135 (recompute_ledgers rebuilds attributed from program flights); ops.py:120/166/293 (GA/substitution/compression delta adjustments); ledger.py:63-80 (zeroed init), 103-164 (fair shares read attributed; deviation = attributed − fair_share); serialize.py:231-232 (read-only). Arithmetic: attributed always equals the sum of provisional delays over currently controlled program flights, and the cancel loop subtracts each such flight's prior exactly once, so attributed reads exactly 0 and reversed equals the pre-cancel attributed total. Checked all other PRD mentions of the subject: §2.10 "reverses ledgers" (generic, consistent), §3.1 `cumulative_delay_minutes` "adjusted by compensation reversals" (different field/entity, vacuous under impl since cancelled programs never completed — out of step_7_diff scope, left verbatim), §3.9 ledger paragraph "reversed_delay_minutes that compensation returns" (consistent with the new gloss). (c) Wording adjustment: replaced only the trailing invariant clause; the operational rule ("decremented and ... incremented by that same amount") was already verbatim-correct against the shipped code and is unchanged.

Sanity check performed: `diff PRD.md PRD_FINALIZED.md` shows exactly the four intended line revisions and nothing else; every edit traced to a step_7_diff item and cross-checked against all logically related impl paths.

result: PRD_FINALIZED.md written at /home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/PRD_FINALIZED.md — 4 minimal revisions (+0.75% chars) pinning dashed v4 UUID ids (§2.4), logical-clock stamping of created_at/updated_at/api_request_timestamp (§2.4/§2.2/§2.5), and the corrected §3.9 cancel-cascade invariant (attributed reads zero, reversed accumulates the reversed total), each verified against every related implementation path.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` = exactly 8 diff lines (4 revised lines: 48, 81, 87, 215), both files 316 lines. No deletions of PRD-required rules.

## Step 9: PRD completeness scan — 2026-10-02T19:0xZ (subagent), diff + bug sites verified by orchestrator

Diff verified: 21 changed paragraphs (42 diff lines: 21 removed + 21 added), line count unchanged at 316, char delta +4712. All edits are in-paragraph inserts/revisions; no new sections.

result: PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_3479_air_traffic_flow_management_ground_delay_program/workspace/PRD_COMPLETED.md — 21 minimal pins over PRD_FINALIZED.md, 3 IMPL BUGs reported (left PRD-untouched).

**Source vs output:** PRD_FINALIZED.md 316 lines / 67983 chars → PRD_COMPLETED.md 316 lines / 72695 chars (+4712). Diff: 42 lines (21 paragraphs revised in place).

**Counts:** 21 ambiguity-pins (all classified ambiguity; none were mismatch-revisions — every place impl diverged from a *clearly stated* PRD rule was reported as an impl bug instead). 0 mismatch-revisions. 3 IMPL BUGs reported.

**Changes (one bullet each):**
- §2.3 — insert — ambiguity — non-integer/negative offset → ERR_INVALID_REQUEST; `has_more` = offset + page-size < total_count; created_at ties break by creation order — util.py:99-128, all list handlers
- §2.4 — revise — ambiguity — `version` born 1, `updated_at`==`created_at` at birth, one bump per request regardless of cascade multi-touch, created-then-mutated stays v1 — storage.py:85-114
- §2.5 — insert — ambiguity — clock set performs no monotonicity check (backward sets accepted), input truncated to whole seconds — routes_clock.py:18-25, util.py:48-63
- §2.8 — revise — ambiguity — datetime inputs truncated to whole seconds, naive inputs interpreted as UTC, domain datetimes echo without fractional part — util.py:30-63
- §2.6 preamble — insert — ambiguity — a field present with JSON null is treated as absent — util.py:146-147
- §2.6 rule 11 — revise — ambiguity — freshness measured as clock minus last report; bound inclusive at exactly 3600s; future-stamped reports pass — routes_ops.py:56-64
- §3.4 — insert — ambiguity — forecast gate evaluated before rate gate; ERR_NO_CURRENT_FORECAST fires even when a live ground stop would zero the feasible rate — capacity.py:105-107, 139-155
- §3.1 — revise — ambiguity — create accepts explicit `status` (else born OPERATIONAL); PATCH needs ≥1 field; patched rate held to [1,120]; accepted patch bumps version even when values unchanged — routes_facilities.py:45, 77-94
- §3.4 — revise — ambiguity — REROUTE `controlled_rate` must still be an integer if supplied (non-integer → ERR_INVALID_REQUEST), value ignored/stored 0 — routes_tmis.py:78, 89-90
- §3.5 — insert — ambiguity — update carrying neither field → ERR_INVALID_REQUEST; `new_ops_status` outside {AIRBORNE, LANDED} → ERR_INVALID_REQUEST; stale-version check fires before ops-state legality — routes_flights.py:126-143
- §3.5 — insert — ambiguity — cancelling an already-CANCELLED flight → ERR_INVALID_STATE — routes_flights.py:183-186
- §3.5 — insert — ambiguity — cancelling an overflow flight (no ASSIGNED slot) runs no release cascade: no RELEASE txn, ledger untouched, virtual CTA and program membership retained; only ops_status flips — routes_flights.py:189-227
- §3.5 — revise — ambiguity — compression against an ACTIVE non-GDP initiative → ERR_TMI_TYPE_NOT_GDP — routes_ops.py:98-103
- §3.5 — revise — ambiguity — reserved-pool availability for carriers evaluated on the post-promotion waitlist state within the same run — ops.py:238-242
- §3.6 — revise — ambiguity — revision creation: from PROPOSED/PUBLISHED/REVISING → ERR_TMI_NOT_ACTIVE, from terminal → ERR_TMI_TERMINAL; state + stale-version checks precede the neither-field rejection; capacity gate recomputes over the post-revision window — routes_tmis.py:245-284
- §3.6 — revise — ambiguity — revision application: unapplied-revision count ≠ 1 → ERR_INVALID_STATE; forecast/rate gates do not re-run at apply — routes_tmis.py:213-228
- §3.6 — insert — ambiguity — a flight dropped from eligibility by the re-snapshot is journaled REVISION_MOVE with to_slot_time null and delta = −prior provisional; cancel/complete while REVISING leaves the pending revision unapplied — allocation.py:248-262, routes_tmis.py:337-435
- §3.7 — insert — ambiguity — GA request filing carries no TMI-state precondition (filing allowed against a program in any status; only adjudication is ACTIVE-gated) — routes_ga.py:30-82
- §3.7 — revise — ambiguity — adjudication: terminal program → ERR_TMI_TERMINAL per §2.6, program-state check fires before request-state check; GA flight gets origin "GA", estimated_arrival = requested_window_start, born SCHEDULED, last_eta_reported_at stamped from logical clock — routes_ga.py:92-99, ops.py:77-101
- §3.8 — revise — ambiguity — reroute assignment against ACTIVE non-REROUTE → ERR_INVALID_REQUEST; terminal → ERR_TMI_TERMINAL; state checks before type check — routes_reroutes.py:37-42
- §3.9 — insert (×3, counted as one paragraph area) — ambiguity — program-level cancellation does not recompute fair shares (fair_share/deviation retain last values); completion reconciliation recomputes fair_share/deviation only, attributed keeps provisional total; operator with zero final-delay sum left untouched; "cancellation removal" in the fair-share trigger list means flight-cancellation removal — routes_tmis.py:337-435, ledger.py:103-164
- §3.4 — revise — ambiguity — overflow flights carry provisional_delay_minutes 0 (provisional rule yields zero for any non-SLOTTED flight) — ledger.py:44-52, allocation.py:79-91

**IMPL BUGs (PRD left untouched):**
- ops.py:69 (`earliest_reserved_open_slot`) and ops.py:224-228 (compression GA promotion) — PRD §2.9: "Every window in the system — … — GA request windows — is half-open: the start instant is included and the end instant is excluded" — impl tests `window_start <= slot_time <= window_end` (end-inclusive) when checking whether a reserved slot's slot_time "lies within the requested window" (§3.7), so a slot exactly at `requested_window_end` is wrongly admitted in both adjudication and compression promotion — suggested fix: change both tests to `window_start <= slot_time < window_end`.
- routes_tmis.py:337-385 (`cancel_tmi`) — PRD §3.7: "when the initiative is cancelled or completed, every `REQUESTED` and `WAITLISTED` request on it expires to `EXPIRED`" — `_expire_pending_ga_requests(tmi["id"])` is only called inside the `ACTIVE`/`REVISING` branch, so cancelling from `PROPOSED`/`PUBLISHED` (a bare flip) strands pending GA requests in REQUESTED/WAITLISTED forever — suggested fix: hoist the `_expire_pending_ga_requests` call out of the branch so it runs on every non-terminal cancellation.
- routes_tmis.py:228 (`activate_tmi` REVISING branch) → allocation.py:56 (`_grid_geometry`) — PRD §3.6 admits a manual revision against "an ACTIVE program" without a type restriction (and §2.6 rule 20 explicitly exempts GROUND_STOP/REROUTE from the capacity gate *at revision*, presupposing they can be revised) — applying a revision to a GROUND_STOP or REROUTE (stored rate 0) computes `3600 // controlled_rate` → ZeroDivisionError → ERR_INTERNAL 500 on a PRD-legal request; for an AIRSPACE_FLOW_PROGRAM it silently builds GDP-style slot machinery the PRD scopes to GDPs — suggested fix: in `reapply_allocation` (or the REVISING activation branch), for non-GROUND_DELAY_PROGRAM types apply the revision's `controlled_rate`/`program_end` fields and flip to ACTIVE without running the slot teardown/rebuild.

Orchestrator verification: diff line count confirmed 42 (21 revised paragraphs), both files 316 lines. Bug sites confirmed: ops.py:69 and ops.py:224-228 both show end-inclusive `<= window_end` comparisons; `_expire_pending_ga_requests` call sites at routes_tmis.py:382 (cancel path) and :431; allocation.py:55 `3600 // tmi["controlled_rate"]` divides by stored rate (0 for GS/REROUTE). All 3 IMPL BUGs real → proceeding to Step 9b (targeted impl fix + full re-sweep; PRD_COMPLETED untouched).

## Step 9b: Fix Step 9 impl bugs + re-sweep — 2026-10-02T18:2xZ (subagent), verified by orchestrator

All clean. Final summary:

## Step 9b complete — task_3479_air_traffic_flow_management_ground_delay_program

### (a) The 3 fixes applied

1. **GA window end-inclusive violation (PRD §2.9 — all windows half-open)**
   - `workspace/implementation/ops.py:69` (`earliest_reserved_open_slot`): `window_start <= s["slot_time"] <= window_end` → `window_start <= s["slot_time"] < window_end` (docstring corrected to "half-open per PRD 2.9").
   - `ops.py:225-228` (compression GA promotion): chained `... <= s["slot_time"] <= request["requested_window_end"]` → `... <= s["slot_time"] < request["requested_window_end"]`.

2. **GA requests stranded on PROPOSED/PUBLISHED cancel (PRD §3.7 — unconditional expiry)**
   - `workspace/implementation/routes_tmis.py`, `cancel_tmi`: moved `_expire_pending_ga_requests(tmi["id"])` out of the `ACTIVE/REVISING` compensation branch so it runs on every non-terminal cancellation, immediately before `tmi["status"] = "CANCELLED"`. Completion path (line ~431) untouched.

3. **Revision apply crash/misbuild for non-GDP TMIs (PRD §3.4/§3.6 — slot machinery is GDP-only)**
   - `workspace/implementation/allocation.py`, `reapply_allocation`: after applying the revision's field values and stamping `applied`/`applied_at`, added early `return` when `tmi["tmi_type"] != "GROUND_DELAY_PROGRAM"` — skipping `_grid_geometry` (`3600 // 0` ZeroDivisionError for GROUND_STOP/REROUTE) and the GDP slot teardown/rebuild. GDP path byte-for-byte preserved; the route still flips status to ACTIVE and touches the TMI.

All three files pass `python3 -m py_compile`.

### (b) Targeted smoke transcript highlights (dynamic port, server killed by exact PID)
- FIX1 boundary: GA request `[02:46:00, 02:48:00]` where 02:48:00 is exactly the first reserved slot's `slot_time` → adjudicate → **WAITLISTED** (was ACCOMMODATED pre-fix). Control `[02:46:00, 02:50:00]` → **ACCOMMODATED at 02:48:00Z**.
- FIX2: GA request filed against a PROPOSED GDP → cancel → request reads **EXPIRED**; same against a PUBLISHED GDP → **EXPIRED**.
- FIX3: GROUND_STOP ACTIVE → revision (`new_program_end` 04:00) → activate → **HTTP 200**, status ACTIVE, `program_end=2026-09-01T04:00:00Z`, revision `applied=true` (was 500 ZeroDivisionError). REROUTE identical → **HTTP 200**, `program_end=2026-09-01T05:00:00Z`.
- `ALL SMOKE CHECKS PASSED`, SMOKE_RC=0.

### (c) 8-round stability sweep (`--isolation per-test-server`)
Every round: **passed=72 total=72 failed=0** — rounds 1-8 all green. No previously-green test regressed; no conflicts to resolve.

### (d) Incidents
One self-inflicted: my first smoke launch backgrounded a shell compound incorrectly, orphaning a server on port 39257; I verified its cwd was this task's impl dir and killed exactly that PID (2486686). The re-run from a script file was clean. Later "stray process" hits were pgrep self-matches from my own probe shells (parent = this session's CLI), confirmed by both smoke ports being free. No other pipeline was touched — all kills were PIDs I started.

### (e) Non-modification confirmation
PRD.md (mtime 15:03), PRD_FINALIZED.md (17:44), PRD_COMPLETED.md (18:10) all predate my edits (18:19); no file under `test_suite/` or `test_helpers/` is newer than PRD_COMPLETED.md. Only `ops.py`, `routes_tmis.py`, `allocation.py` changed, plus the deliverable `results.1-8.json` (18:26) left on disk in `workspace/implementation/`.

result: 3 impl bugs fixed (GA half-open window ×2 sites, GA expiry on PROPOSED/PUBLISHED cancel, non-GDP revision apply crash), smoke green on all three paths, 8/8 sweep rounds at 72/72 passed, PRD/tests untouched, results.1-8.json preserved.

Orchestrator verification: ops.py:69 now `< window_end`, no `<= window_end` sites remain; routes_tmis.py:385 expiry hoisted immediately before `status = "CANCELLED"` (386); allocation.py:174 non-GDP early return present; results.1-8.json all (72,72,0); workspace/ contains INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/.

## PIPELINE COMPLETE — final state

- Scaffold: SCAFFOLD.yaml (1431 lines) + SCAFFOLD_DIFFICULTY_DESIGN.yaml (1428) + SCAFFOLD_CORNER_DESIGN.yaml (2316); 13 entities, 43 endpoints, 38 error_ids; lint clean.
- PRD chain: PRD.md (316) → PRD_FINALIZED.md (316, +504 chars, 4 pins from Step 7) → PRD_COMPLETED.md (316, +4712 chars, 21 ambiguity pins, 0 mismatch revisions).
- Tests: test_helpers/ (9 modules, 2611 lines, frozen in 5a, never modified afterward) + test_suite/ (18 files, 72 tests = 19 difficulty + 53 corner, zero skips, AST tag audit clean by both 5b and orchestrator).
- Implementation: 23 modules + start.sh, 3503 lines, 43/43 routes (clock unprefixed), all constants PRD-exact.
- Iterations: Step 7 = 3 sweeps, 3 impl fixes (UUID rendering, TMI-cancel ledger decrement+increment, logical-clock system stamps), 0 deletions, 0 test fixes. Step 9 = 3 impl bugs found. Step 9b = 3 impl fixes, full re-sweep.
- Final gate: 8/8 parallel per-test-server sweep rounds at 72/72 passed; results.1-8.json preserved in workspace/implementation/.
