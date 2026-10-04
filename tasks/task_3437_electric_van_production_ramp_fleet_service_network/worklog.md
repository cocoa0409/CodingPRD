# Worklog — task_3437_electric_van_production_ramp_fleet_service_network

## Step 1: Create task directory — 2026-10-02T02:36:00.000Z

Task directory pre-allocated by the caller: `tasks/task_3437_electric_van_production_ramp_fleet_service_network/` with `workspace/` inside. Verified present; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T03:47:00.000Z

All three hits are "in-flight" (in-progress projects) — legitimate domain usage, no foreign contamination. The scaffold package is complete and verified.

## Summary

**Task**: task_3437_electric_van_production_ramp_fleet_service_network — Electric Van Production Ramp & Fleet Service Network (Rivian-style), designed at harder-than-expert density.

**Output files** (all parse-verified, lint-clean):
- `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/SCAFFOLD.yaml` — 2133 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1328 lines, single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/SCAFFOLD_CORNER_DESIGN.yaml` — 2499 lines, single top key `scaffold_corner_design`

**Counts**: 14 entities, 7 state machines (cyclic rework loop on BatteryModule, cyclic redesign loop on ChargingProject, branching+pause/resume cycle on SoftwareCampaign, parallel delivery×telematics dimensions on Vehicle), 9 calculations, 16 ordered validation rows, 31 error codes, 11 roles (segregation-of-duties role model: registrar≠inspector, diagnostician≠adjudicator, supplier-registrar≠auditor), 3 OCC concurrency rules (Depot / VehicleOrder / UptimeContract versions).

**§1.8**: 19 instances across all 9 rules — dual-variant calcs on two domains (uptime ROUTE_DAY 12000¢ vs VEHICLE_HOUR 0¢ for identical event; battery EOL REFURBISH 630000 vs RECOVERY 632016), all three combinatorial modes (a: tiered credit 440000; b: per-line rounding 92735 vs 92734; c: pinned depot-capacity evaluation order), depth-3 rollback cascade (campaign→vehicle hold→IN_TRANSIT recall→order hold_count) and depth-2 parts-consumption cascade, plus priority conflicts, strict `<`/inclusive `<=` boundaries, cross-entity gates, two interval semantics (van 45-min buffer vs depot closed-window crew aggregate), and two compensating invariants (parts accounting identity; depot kW headroom).

**§1.9**: 67 instances (58 active + 9 excluded_because stubs) across all 9 guide sections; every one of the 31 error codes is triggerable by at least one instance.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint` (47 endpoints, 14 entities, 19 + 58 instances, 1079 calls, 0 violations); independent grounds/name audit — 0 unresolvable grounds refs, 86 unique instance names; forbidden concurrency vocabulary — none; domain vocabulary present (van/battery/fleet/depot/service/charging/warranty/franchise all present), no foreign-domain terms. Two latent dead-code hazards were fixed during design: `ERR_ORDER_QUANTITY_FULL` was unreachable (auto-FULFILLED shadows it — removed), and the `software_hold` gate on AT_DEPOT-entry was unreachable (rollback recalls IN_TRANSIT vehicles first — gate kept only on COMMISSIONED, which is reachable and corner-tested).

Orchestrator verification: all three files exist on disk (2133/1328/2499 lines), all parse as YAML, correct top-level keys (`scenario/domain_name/api_prefix/...`, `scaffold_difficulty_design`, `scaffold_corner_design`).

## Step 3: Copy INSTRUCTION.md — 2026-10-02T03:48:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Verified present.

## Step 4: Generate PRD — 2026-10-02T03:56:00.000Z

PRD generation complete and all contracts verified. Final report:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/workspace/PRD.md` — 326 lines, built in 9 verified appends (tail re-checked after each; no truncation).

**Structure**: §1 intro (2 paragraphs) → §2 with 10 domain-derived subsections (RBAC, verbatim response envelope, pagination, logical clock, resource properties, OCC, precision, validation priority, segregation of duties, depot capacity accounting) → §3 with 11 lifecycle-grouped subsections → §4 endpoint table (4 columns) → §5 error catalogue (2 columns). Ends at §5 with no audit footer.

**Grep counts (all confirmed in prose/tables)**:
- 47/47 endpoints — every path verbatim, including the unprefixed `POST /_clock/set_current_utc` kept outside `/evfleet` in both §2.4 prose and §4 table
- 31/31 error codes in §5, each also mentioned in §2/§3 narrative
- 7/7 state machines — 40/40 distinct state names in backticks (span-aware), all 58 transition pairs expressed
- 9/9 calculations — every formula fully narrated with all 22 constants embedded (verified per-calc key-value presence), no pseudocode operators, no fuzzy words

**Hard contracts**: Contract 1 (field-name coverage): 114/114 required names in backticks, 0 missing after one repair (bare `status` added to §2.5). Contract 2 (rule coverage): 15-priority validation ordering stated as first-failure-wins; all 3 OCC rules with `expected_*_version` + `ERR_STALE_VERSION`/412; all cascades (quarantine, rollback 3-link, parts conservation, EOL dual valuation) with secondary effects; sibling branches (pause/resume × 3 stages, rollback × 4 states, CANCELLED × 4 charging states) at equal density. Contract 3 (§3 path purity): 505 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. §2.2 block byte-identical to `section-2.2-response-structure.md`.

**Scaffold ambiguities resolved**:
1. **Phantom error id**: validation priority 14 declares `error_id: ERR_ORDER_QUANTITY_FULL` (422), but the error catalog deliberately omits it and the check text itself states the condition is unreachable (auto-fulfillment lands the attempt on terminal `FULFILLED` → `ERR_ALREADY_TERMINAL`). I followed the catalog: no §5 row, no named phantom id, and §2.8 item 14 states the unreachability rule with the observable error.
2. **Overlapping month-window conditions**: `ERR_WINDOW_INVALID` (priority 9) and `ERR_MONTH_OUT_OF_ORDER` (priority 6) both mention "before `measurement_start_date`'s month" in the scaffold. I transcribed both mentions faithfully and stated the priority ordering so first-failure-wins derives (priority 6 fires first); no editorial deduplication.

Orchestrator verification: PRD.md on disk at 326 lines; `/_clock/set_current_utc` unprefixed in both SCAFFOLD.yaml:1572 and PRD.md:76,242; api_prefix `/evfleet` confirmed. Logical clock start pinned at 2026-09-01T00:00:00Z.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T04:19:00.000Z

Stage 1 is complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `constants.py` | 122 | PRD-pinned thresholds (below) |
| `types.py` | 397 | 23 enums + 14 entity TypedDicts (all entities carry id/created_at/updated_at/version — every one has `common_fields: true` in the scaffold) |
| `api_errors.py` | 81 | 31 `ApiErrorId` members + HTTP map, registered with `set_error_http_status_map` at import |
| `api_client.py` | 181 | 42 endpoint methods on `ApiClient(GenericApiClient)`; **`POST /_clock/set_current_utc` routed unprefixed** (verified: the only unprefixed path in scaffold+PRD) |
| `test_users.py` | 93 | 11 roles + builders (below) |
| `factories.py` | 280 | Payload factories, input fields only; required FKs are mandatory args; optional fields omitted when None |
| `assertions.py` | 291 | 14 `assert_<entity>()` + invariants: parts conservation (`received == on_hand + consumed`, reserved subset, strict-below restock flag), depot committed bounds, campaign counter reconciliation, fresh-vehicle defaults |
| `fixtures.py` | 749 | 5 tiers: clock, single-entity creators, state walkers (`advance_project_to_commissioned`, `commission_vehicle`, `start/complete/cancel_visit`), composites (`setup_base_fleet`, `setup_commissioned_fleet`, `setup_service_scenario`, `setup_uptime_contract_with_fleet`, `setup_settled_claim`/`setup_denied_claim`), threshold targeting (`setup_depot_with_project`, `register_count` slot control for ramp-gate boundaries). OCC fields always refetched fresh inside fixtures; raw-Response variants (`register_vehicle_raw`, `create_charging_project_raw`) provided for OCC/error tests |
| `__init__.py` | 46 | Barrel: framework generics + all PRD-specific modules |

## Constants pinned (each grep-verified against a verbatim PRD line)
`LOGICAL_CLOCK_DEFAULT=2026-09-01T00:00:00Z` (§2.4); `FRANCHISE_BLOCKED_STATES=[TX,MI,WV]` (§3.5); `MAX_DEPOT_CREW=4` (§3.2); `VAN_TRAVEL_BUFFER_MINUTES=45` (§3.9); `MODULE_MAX_FAILURES=2` (§3.4); tiers `A: 95.0/98.0/0-corrective`, `B: 85.0/92.0/≤2` (§3.3); ramp `8 base + {A:24,B:10,C:0,UNAUDITED:0}` (§3.5); demand gate `19.2 kW × 0.8 utilization` (§3.6); EOL `SOH_EOL_THRESHOLD=70.0` (strict), `PACK_BASE_VALUE_CENTS=1800000`, band multipliers 0.85/0.70/0.55/0.35, `RECOVERY_RATE_PER_KWH_CENTS=12000` (§3.9); warranty `LABOR_RATE=17500`, `DEDUCTIBLE=25000`, coverage `{BATTERY:1.0, POWERTRAIN:1.0, CHARGING:0.9, BODY:0.8}` (§3.11); uptime credit tiers 2%/5%/10% at 2.0/5.0 widths, `CREDIT_CAP_PCT=30.0` (§3.10); rollout `CANARY_MIN_COHORT=3`, `EXPANDED_MIN_COHORT=10`, `ROLLOUT_SUCCESS_RATE_MIN=0.95` (§3.7); promise `28 + 7×⌈q/10⌉` days, `SUPPLY_RISK_PUSH_DAYS=14` (§3.5); pagination 10/1/100/0 (§2.3). No dead/superseded constants kept.

## Role → id scheme
11 roles. Shared opaque ids aligned to the design indices so provenance assertions work: `pa-1` PlatformAdmin, `pp-1` ProductionPlanner, `qi-1` QualityInspector, `co-1` ComplianceOfficer, `cc-1` ChargingCoordinator, `sd-1` ServiceDispatcher, `st-1`/`st-2` ServiceTechnician, `ca-1` ClaimsAdjuster, `rm-1` ReleaseManager, `ti-1` TelematicsIngestion. FleetManager is the sole entity-backed role: `make_fleet_manager_headers(customer["id"])` is mandatory for ownership-gated calls and is threaded through every fixture; the shared `fleet_manager_headers` constant is documented as non-ownership-tests-only. `make_<role>_headers(user_id)` builders exist for all roles to support the three segregation-of-duties separations.

## Verification
- `python3 -m py_compile` on each file individually and all together: OK
- Package import check `import test_helpers` from task root: OK, zero missing exports among 20 spot-checked names, 31 errors registered, clock method confirmed unprefixed by source inspection
- Fixture datetimes all ≥ clock start (install windows 2026-09-05/2026-10-01, visits 2026-09-10)
- No `test_suite/` or `test_*.py` created (the `find` match is `test_helpers/test_users.py`, part of the Stage 1 contract)

Orchestrator verification: 9 helper files on disk; `import test_helpers` OK from task root; clock call passes raw unprefixed path (api_client.py:16) while all other methods prepend `API_PREFIX` at the call site.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T05:02:00.000Z

Done. Final report:

## Stage 2 complete — task_3437 test suite generated

**Files written** (`/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/test_suite/`):

| File | Lines | Tests |
|---|---|---|
| conftest.py | 80 | — |
| test_01_envelope_and_auth.py | 96 | 4 |
| test_02_customers_and_depots.py | 163 | 7 |
| test_03_charging_project_lifecycle.py | 179 | 5 |
| test_04_charging_capacity_and_crew.py | 352 | 10 |
| test_05_supplier_readiness.py | 150 | 4 |
| test_06_battery_modules.py | 112 | 4 |
| test_07_vehicle_orders.py | 242 | 9 |
| test_08_vehicle_registration.py | 227 | 9 |
| test_09_vehicle_delivery_and_commissioning.py | 137 | 4 |
| test_10_software_campaigns.py | 230 | 9 |
| test_11_service_visits_and_parts.py | 343 | 12 |
| test_12_warranty_claims.py | 156 | 6 |
| test_13_battery_health.py | 134 | 6 |
| test_14_uptime_contracts.py | 214 | 7 |

Total: 2815 lines, **96 tests**.

**AST tag audit** (real `ast.parse`, tags diffed against both indices):
- Queue A (Difficulty): **19/19 instances emitted, exactly 2 tests each (38 tests), 0 skipped** — no shortfalls.
- Queue B (Corner): **58/58 non-stub instances emitted, 1 test each (58 tests), 0 skipped**; 9 `excluded_because` stubs correctly untranslated (all cross-references resolve to real difficulty instances — zero orphan tags confirms).
- 0 untagged tests, 0 dual-tagged tests, 0 tags pointing to non-existent instances.

**Citation check**: every test's docstring quotes PRD verbatim — automated 8-word-window grep against PRD.md passes for all 96 (9 initially flagged tests were short/abbreviated quotes; all fixed to full verbatim spans and re-verified).

**Collection**: `pytest test_suite/ --collect-only -q` → **96 tests collected, 0 errors** (test_helpers importable; the only "error" strings in output are test names).

**Adjudication notes**: the two required-field/enum instances (`depot_create_missing_required_state_code_returns_validation`, `vehicle_order_invalid_pack_enum_rejected`) were kept — ERR_VALIDATION is uniquely derivable by elimination from the closed §5 catalog (only other 400 is window-specific). All FleetManager ownership-gated calls use `make_fleet_manager_headers(customer["id"])`; creates assert 201 explicitly; the logical clock is driven via the unprefixed `/_clock/set_current_utc` client method; all fixture datetimes sit at/after the 2026-09-01T00:00:00Z clock start, and all computed expectations (92735-cent settlement, 96.7/98.3 uptimes, 12000/440000-cent credits, 2026-10-06/2026-10-20 promise dates, ramp gate at 8/9) were re-derived from PRD formulas rather than copied.

Orchestrator verification: re-ran `pytest --collect-only -q` myself → 96 tests collected in 0.22s; re-ran independent AST tag walk → 96 Design tags, 0 unresolvable instance names.

## Step 6: Generate implementation — 2026-10-02T06:12:00.000Z

All deliverables are in place, the smoke server was killed by its exact PID (179573), and temp files are cleaned up.

## Summary

**Implementation** at `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/workspace/implementation/`:

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded pip install + `exec python3 app.py` (PORT env, default 10000, 0.0.0.0) |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 70 | Flask app, unprefixed `POST /_clock/set_current_utc`, blueprint registration, enveloped 404/405/500 handlers |
| `errors.py` | 45 | `ApiError` + all 31 catalog error ids |
| `store.py` | 75 | In-memory dicts (empty at boot, no seeding), logical clock pinned at 2026-09-01T00:00:00Z, `stamp_new`/`touch` (version+1, 3-fraction-digit ISO timestamps) |
| `util.py` | 198 | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, max 100, sorted by created_at), auth (X-User-ID/X-User-Role + 11 declared roles), ownership/OCC helpers, typed field validators |
| `calc.py` | 323 | All 9 calculations with Decimal/Fraction exactness and ROUND_HALF_UP where specified |
| `routes_customers.py` | 55 | fleet-customers ×4 |
| `routes_depots_charging.py` | 191 | depots ×3 + charging-projects ×2 (committed-kW accounting, pointwise crew-window aggregate, OCC, per-transition depot version bumps) |
| `routes_suppliers_modules.py` | 187 | suppliers ×4 + battery-modules ×2 (readiness tiers, quarantine/recovery cascades, auto-scrap at 2 failures, segregation) |
| `routes_orders.py` | 157 | vehicle-orders ×4 (franchise gate TX/MI/WV, promise dates, ownership) |
| `routes_vehicles.py` | 213 | vehicles ×5 (ramp gate, parallel DELIVERY/TELEMATICS dimensions, commissioning gates, EOL valuations) |
| `routes_service.py` | 126 | service-centers ×4, mobile-vans, parts-stocks upsert (conservation invariant) |
| `routes_visits.py` | 208 | service-visits ×4 (45-min van buffer, atomic parts reservation, consume/release cascades) |
| `routes_software.py` | 177 | campaigns ×4 (rollout gates 3/10 cohorts at exact 0.95, pause/resume, 3-link rollback cascade) |
| `routes_warranty.py` | 156 | claims ×5 (pinned per-line nested rounding, segregation) |
| `routes_uptime.py` | 143 | contracts ×3 (chronology, ROUTE_DAY/VEHICLE_HOUR close) |

**Endpoints: 47/47** (46 in blueprints + unprefixed clock in app.py; Flask's URL map shows 48 rules including its static route). Full `import app` check passes.

**Smoke tests** (dynamic ports, server PID saved and killed exactly): two scripts, 41 + 44 checks, all passing against fresh boots — including the PRD's worked numbers: promise date 2026-10-06 for qty 2 confirmed 2026-09-01; EOL valuations 630000/632016 at soh 68.4/77 kWh; warranty settlement 92735 (nested rounding, not 92734); ROUTE_DAY close (70.0% → 30% cap → 600000) and VEHICLE_HOUR (8.5 days → 71.7%); downgrade cascade push to 2026-10-20 with no pull-back on recovery; recall of a held IN_TRANSIT vehicle with hold_count recompute; OCC 412s; ownership 403; segregation 403; headroom 422; van-buffer 409; parts invariant after completion.

**PRD ambiguities resolved (auditable interpretations):**
1. Basic field validation placement: FK presence is checked at existence time (priority 3); enums/ranges/non-empty shape at priority 10; transition narratives (utility_denial_reason, diagnosis_notes, denial_reason) where the state-machine preconditions name them. §2.8 ranks ERR_VALIDATION only at priority 10.
2. Tier-scope mismatch on vehicle-results has no catalogued error id → I emit `ERR_VALIDATION` (400).
3. Unknown `to_state`: `ERR_VALIDATION` on single-role transition endpoints; on multi-role endpoints an unmappable `to_state` draws `ERR_FORBIDDEN` at priority 2 (role not permitted for the requested to_state).
4. Parts-stock upsert updates `reorder_threshold` to the supplied value on every call (upsert semantics).
5. Out-of-range `limit`/`offset` → `ERR_VALIDATION` 400 (PRD states bounds but no error id).
6. Vehicle `COMMISSIONED` is a *soft* terminal: transitions out of it → `ERR_INVALID_STATE`, not `ERR_ALREADY_TERMINAL` (scaffold's own wording; no terminal error is specified for vehicles).
7. Parent-order `hold_count` recomputation bumps the order's version only when the value actually changes.
8. Downtime events with `ended_at < started_at` are accepted (no PRD check stated — none invented); day-counting touches days from start date through (end − ε), open events through the month's last instant.
9. Audit percentages accept any number (no 0–100 constraint stated); `pack_kwh` requires integer 52/77.
10. `ERR_ORDER_QUANTITY_FULL` is intentionally never emitted — the PRD declares it unreachable (over-registration dies on terminal `FULFILLED` → `ERR_ALREADY_TERMINAL`, which is implemented and smoke-verified).

Orchestrator verification: `import app` OK with 48 URL rules (47 endpoints + static); clock route unprefixed at app.py:20; key constants in calc.py match test_helpers/constants.py and PRD.md verbatim (19.2 kW × 0.8, 1800000/12000 EOL, 17500/25000 warranty, band multipliers 0.85/0.70/0.55/0.35, SOH 70.0 strict, 0.95 exact rollout gate, 45-min van buffer).

## Step 7: Test-fix iteration loop — 2026-10-02T06:14:00.000Z

Clean sweep: all 8 rounds pass 96/96.

## Summary

- **Iterations run**: 2 (initial sweep → fix → verification sweep).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/test_suite/test_11_service_visits_and_parts.py` — `test_restock_flag_stays_false_above_threshold`: added the missing `setup_completed_visit` name to the `from test_helpers import (...)` block. The helper existed and was exported (`test_helpers/fixtures.py:687`, via `from .fixtures import *` in `__init__.py`), but the test file's import list omitted it, producing `NameError` at call time (the sole failure, deterministic across all 8 rounds).
- **Fixes applied to `implementation/`**: none — the implementation was already faithful.

**Adjudication trail (diagnostic protocol)**: STEP 1a passed — PRD §3.8 states verbatim: "`restock_needed` is recomputed after every mutation as true exactly when `on_hand_qty` falls strictly below `reorder_threshold`. A row at exactly its threshold does not need restock." STEP 1b passed — with on_hand=4, threshold=1, "strictly below" uniquely yields `restock_needed is False`. STEP 2 found the test's logic faithful (helper defaults: stock 5, threshold 1, one 1-unit line consumed → on_hand 4, matching the test's comment and assertions); the defect was purely the import omission in the test file, fixed in place without touching any assertion.

**Verification**: post-fix 8-round parallel sweep (`--isolation per-test-server`, 96 tests/round) — 96/96 passed in every round, 0 failed, 0 errors. No flakiness observed in either sweep (the pre-fix failure was deterministic, 8/8 rounds).

Orchestrator verification: all 8 `results.{1..8}.json` on disk, each `passed=96/96, failed=0`, mtimes 06:11 (after the 06:08 test fix; all implementation/*.py mtimes predate the sweep — no post-sweep impl writes). Independent orchestrator-run confirmation round: 96/96 passed, 0 failed (161.3s).

## Step 8: Finalize PRD — 2026-10-02T06:22:00.000Z

Done. `PRD_FINALIZED.md` written as a byte-identical copy of `PRD.md` (zero-edit outcome, verified: `diff -q` silent, identical md5 `d443b00f9f7d4d77abfaae1161dd7399`).

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/workspace/PRD_FINALIZED.md`

**Line counts / %-delta:** PRD.md 326 lines, PRD_FINALIZED.md 326 lines — 0% delta (zero-edit).

**Changes:** none.

**Per-item adjudication log (1 item in `<step_7_diff>`):**

- `test_suite/test_11_service_visits_and_parts.py` — `test_restock_flag_stays_false_above_threshold` import fix — **no PRD edit required.** Verified all three Step 7 claims against source:
  1. The helper `setup_completed_visit` exists and is exported at `test_helpers/fixtures.py:687`; the test file now imports it (line 20) and calls it (line 179). The defect was a pure test-side import omission (NameError) — no assertion touched, so it reveals nothing about PRD silence or PRD/impl mismatch.
  2. PRD §3.8 (PRD.md line 204) already pins the rule verbatim and with a boundary clarification: "`restock_needed` is recomputed after every mutation as true exactly when `on_hand_qty` falls strictly below `reorder_threshold`. A row at exactly its threshold does not need restock." With on_hand=4, threshold=1 this uniquely determines `restock_needed is False` — no implementer latitude exists.
  3. The implementation matches the PRD exactly at every mutation site, all using strict `<`: `routes_service.py:114` (upsert-create branch), `routes_service.py:124` (upsert-delta branch), and `routes_visits.py:28` (`_restock` helper), invoked at reserve (`routes_visits.py:120`, visit create) and at consume/release (`routes_visits.py:202`, covering both the completion-consume branch at 196–198 and the cancellation-release branch at 201). "Recomputed after every mutation" holds.

**Per-edit pre-edit search log:** no edits were made, so no pre-edit searches were triggered. (The verification reads above — all impl `restock_needed`/stock-mutation sites enumerated via grep across `implementation/`, plus the PRD §3.8/§3.9 passages and the fixture — served as the consistency check confirming no edit was warranted.)

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical; both 326 lines.

## Step 9: Complete PRD — 2026-10-02T06:45:00.000Z

The diff contains exactly the intended edits and nothing else. All verification is complete. Here is the final report.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3437_electric_van_production_ramp_fleet_service_network/workspace/PRD_COMPLETED.md`
**Source vs output:** PRD_FINALIZED.md 326 lines / 57,050 chars → PRD_COMPLETED.md 330 lines / 61,438 chars (**+4 lines, +4,388 chars**; not zero-edit). 23 diff hunks, all inline inserts/revisions; no new sections; SCAFFOLD/worklog never read.

**Counts:** 22 ambiguity-pins, 2 mismatch-revisions (both adjudication leg (b) — PRD wording contradicts a working impl behavior), **0 impl-omission candidates** (every PRD-stated rule is exhibited by impl; the §2.8 ERR_ORDER_QUANTITY_FULL unreachability note already matches errors.py, which never defines it).

### Changes (one bullet each)

- §2.2 — insert — ambiguity — undeclared paths and unsupported methods answered `ERR_NOT_FOUND` (404) in the standard envelope — `implementation/app.py:54-61`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` (400); sort ties broken by creation order; `total_count`/`has_more` semantics; filters exact-match, conjunctive, unknown id → empty page — `implementation/util.py:37-73`
- §2.4 — insert — ambiguity — clock accepts any well-formed instant (no monotonicity check); offset-less datetimes read as UTC everywhere — `implementation/app.py:20-29`, `implementation/util.py:159-173`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/store.py:55-63`
- §2.7 — revise — **mismatch (leg b)** — percentages compared exactly at submitted precision with no rounding/range validation (replaces "compared at one decimal place"); audit percentages and `open_corrective_actions` unbounded — `implementation/calc.py:40-49`, `implementation/routes_suppliers_modules.py:66-70`
- §2.8 rank 2 — insert — ambiguity — unknown `to_state`: `ERR_FORBIDDEN` at rank 2 on multi-role transition endpoints, `ERR_VALIDATION` within the state rank on single-role ones (charging projects, vehicles, campaigns) — `implementation/routes_orders.py:104-111`, `implementation/routes_suppliers_modules.py:144-151`, `implementation/routes_visits.py:159-166` vs `implementation/routes_depots_charging.py:170-171`, `implementation/routes_vehicles.py:149-168`, `implementation/routes_software.py:60-61`
- §2.8 rank 3 — revise — ambiguity — added `supplier_id` to the body-FK existence list — `implementation/routes_suppliers_modules.py:114-115`
- §2.8 rank 10 — insert — ambiguity — rank 10 hosts all value-domain shape checks (enum membership, numeric bounds, `state_code` form, integer typing) — `implementation/util.py:129-157`, all route files
- §2.8 post-stack — insert — ambiguity — read-time `ERR_VALIDATION` for missing/null/empty/wrong-typed fields at the point of read; integral floats accepted for integers; booleans never coerce — `implementation/util.py:117-148`
- §3.4 — insert — ambiguity — `pack_kwh` is submitted as an integer — `implementation/routes_suppliers_modules.py:117-119`
- §3.5 — insert — ambiguity — order `depot_id` may name any existing depot (no same-customer rule); `battery_pack_kwh` integer — `implementation/routes_orders.py:29-40`
- §3.5 — insert — ambiguity — `exemption_document_ref` stored on approval whenever it is a string, required or not — `implementation/routes_orders.py:149-152`
- §3.5 — insert — ambiguity — VIN registration only on `CONFIRMED`/`IN_PRODUCTION`; `DRAFT`/`SUBMITTED`/`FRANCHISE_HOLD` → `ERR_INVALID_STATE` — `implementation/routes_vehicles.py:46-52`
- §3.6 — revise — ambiguity — `COMMISSIONED` soft-terminal spelled out: no exits, further DELIVERY attempts → `ERR_INVALID_STATE`, never `ERR_ALREADY_TERMINAL` — `implementation/routes_vehicles.py:129-151`
- §3.6 — insert — ambiguity — `hold_count` recompute writes/bumps the order's `version` only when the count actually changes — `implementation/routes_vehicles.py:22-28`
- §3.7 — insert — ambiguity — resume from `PAUSED` re-evaluates no rollout gate — `implementation/routes_software.py:67-94,109-110`
- §3.7 — insert — ambiguity — vehicle tier = parent order's `telematics_tier`; tier outside scope → `ERR_VALIDATION` (400) — `implementation/routes_software.py:157-161`
- §3.8 — insert — ambiguity — parts-stock upsert overwrites `reorder_threshold` on every call, create or update — `implementation/routes_service.py:117-126`
- §3.9 — revise — ambiguity — `parts_lines` is required but may be empty (was "may be empty but, when present…") — `implementation/routes_visits.py:64-66`
- §3.10 — revise — **mismatch (leg b)** — `committed_uptime_pct` "(expressed at one decimal)" softened to a convention; any precision accepted and compared exactly — `implementation/routes_uptime.py:41-44`
- §3.10 — insert — ambiguity — `measurement_start_date` must name a valid calendar date — `implementation/routes_uptime.py:21-31`
- §3.10 — insert — ambiguity — downtime events: any existing vehicle may be named (out-of-fleet events recorded, never measured); no window sanity — inverted `ended_at` accepted, contributes zero — `implementation/routes_uptime.py:78-101`, `implementation/calc.py:277-280`
- §3.10 — insert — ambiguity — malformed `month` refused `ERR_WINDOW_INVALID` before chronology/fleet evaluation — `implementation/routes_uptime.py:112-136`
- §3.10 — insert — ambiguity — ROUTE_DAY counts from the clipped start's date through the date of (end − ε); an event ending exactly at 00:00:00Z does not count the day beginning then — `implementation/calc.py:293-297`
- §4 — revise — ambiguity — downtime-event append returns 201 (body carries updated contract); parts-stock upsert returns 201 on both create and update branches — `implementation/routes_uptime.py:103`, `implementation/routes_service.py:126`

### Known-interpretation coverage
All ten generation-time interpretations are now pinned in PRD prose: (1) §2.8 ranks 3/10 + read-time note; (2) §3.7 tier-scope `ERR_VALIDATION`; (3) §2.8 rank 2 unknown-`to_state` split; (4) §3.8 threshold overwrite; (5) §2.3 limit/offset; (6) §3.6 soft terminal; (7) §3.6 version-on-change; (8) §3.10 downtime sanity/day-counting (open-events-through-month-end was already pinned); (9) §2.7 + §3.4/§3.5 integer pack; (10) already declared in §2.8 rank 14 — no change needed.

Orchestrator adjudication of the 2 mismatch-revisions (§2.7 percentages, §3.10 committed_uptime_pct one-decimal): scaffold says "percentages compared at 1 decimal place exactly as submitted" (line 1281) — internally tense ("exactly as submitted" vs any normalization), divergent only for ≥2-decimal submissions; NO design-index instance probes ≥2-decimal percentages (grepped both indices — only 0.95/0.667 explanatory text), so no test encodes the alternative reading; scaffold has NO 0–100 range validation for audit/soh percentages (only committed_uptime_pct has `0 < x <= 100`, which the revision retains). Both revisions are legitimate ambiguity resolutions pinning the impl's defensible reading, not stripped scaffold rules — ACCEPTED; impl left unchanged so the green sweep stays valid. Spot-checked three other pins against impl source: downtime-append 201 (routes_uptime.py:103), upsert overwrite+201 both branches (routes_service.py:117-126), exemption-ref stored whenever string on approval (routes_orders.py:149-152) — all accurate. Post-Step-9 check: 0 implementation .py files newer than the sweep results; PRD_COMPLETED.md 330 lines.
