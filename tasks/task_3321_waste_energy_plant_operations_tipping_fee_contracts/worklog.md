# Worklog — task_3321_waste_energy_plant_operations_tipping_fee_contracts

## Step 1: Create task directory — 2026-09-30T20:12:00.000Z

Task directory was pre-allocated by the invoker; verified `./tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/workspace/` exists. No new index computed, no other task directory created.

## Step 2: Generate Scaffold — 2026-09-30T20:40:00.000Z

All three scaffold artifacts are written and pass `scaffold_lint.py` with a clean verdict.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Counts:**
- 18 entities (Municipality, HostCommunityAgreement, WasteSupplyAgreement [self-referential amendments], WasteDelivery, Boiler, OutageWindow, DiversionPlan, DiversionLeg, DailyThroughputReport, PowerPurchaseAgreement, EnergyDelivery, MetalsRecoveryContract, MetalsRecoveryBatch, Landfill, AshShipment, AshTest, EmissionsPermit, EmissionsReading)
- 8 state machines (cyclic MetalsRecoveryBatch dispute loop, branching Boiler, guarded/cascading delivery-accept and outage-start chains)
- 10 calculations (incl. dual-variant tipping fee and energy billing, pinned-order nested-rounding metals settlement, mode-(a) prorated capacity payment, mode-(c) thermal→capacity→steam evaluation order, strict-> emissions thresholds, waterfall tip-floor allocation and put-or-pay settlement)
- 29 validations, 81 endpoints (incl. `POST /wte/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z), 25 errors, 5 roles (all `opaque`), 4 OCC concurrency rules
- 20 difficulty instances (≥2 per rule across all 9 rules; combinatorial_formula covers modes a/b/c)
- 43 corner instances (38 active + 5 `excluded_because` stubs) across 9 claim-guide sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (81 endpoints, 18 entities, 20+38 instances, 352 calls scanned)

**Notable design decisions:**
- Profile: compliance/audit primary + quota/allocation secondary; layers = OCC, cascading side effects, dual-variant calc, rate thresholds; hybrid topology with one self-referential FK (agreement amendments).
- Rule 8 differentiation: half-open outage intervals (touching allowed) vs closed host-agreement intervals (touching is overlap) on different resources.
- Rule 6 has 3 instances spanning MW threshold (inclusive), emissions limit (strictly-greater), and empty-test-set count boundary.
- All formula-derived asserts were pre-computed by executing the formulas (e.g. capacity payment 3,870,972¢ for min(60,80)×200000×10/31; put-or-pay monthly rollover 60t→540,000¢ then 10t→90,000¢; tipping fee 80,000 vs projected 90,000 after amendment).
- Two lint fixes during the run: added `projected_fee_cents` to WasteDelivery + the `compute_tip_floor_allocation` rule with `ERR_PRIORITY_NOT_AVAILABLE`, and added `GET /wte/emissions-readings/{id}` so the linter's collection-segment heuristic could verify FK reverse-reachability for EmissionsReading.

## Step 3: Copy shared files — 2026-09-30T20:41:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:52:00.000Z

All key rules are covered. The PRD is complete.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/workspace/PRD.md`
**Line count:** 335 lines (51 KB) — verified on disk by orchestrator (51,495 bytes).

**Note:** the subagent's first invocation exited prematurely after enumerating the field list without writing the file; orchestrator verified PRD.md missing on disk and resumed the same agent, which then completed the write.

**Sections covered:**
- §1 Introduction (3 paragraphs: business context, full operating cycle, logical clock + OCC structural concerns)
- §2 Global Specifications: 2.1 RBAC (all 5 roles, opaque identity prose for each), 2.2 API Response Structure (emitted verbatim, confirmed via `req_RANDOMALPHANUM123456` / `UNIQUE_ERROR_IDENTIFIER_STRING` markers), 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, created_at ascending), 2.4 Logical Clock (startup default `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`, clock-driven expiry), 2.5 Common Resource Properties, 2.6 Validation Ordering (8-step priority cascade), 2.7 Nested Resource Retrieval, 2.8 Precision and Rounding, 2.9 OCC (all 4 rules with exact `expected_*_version` fields and `ERR_STALE_VERSION`/412)
- §3 Business Logic in 11 domain-derived subsections: municipalities/host privilege, supply agreements + amendments, tip-floor receive/accept flow, boilers/deratings/outages, diversion plans/legs/divert, throughput reports (pinned 4-step evaluation order), PPAs/energy billing (contracted vs merchant variants + capacity proration), metals settlement (pinned per-line rounding), ash disposal/testing/landfill auto-close, emissions permits/rolling averages, put-or-pay settlement runs (annual vs monthly variants)
- §4 Endpoint table — 78 rows, 4 columns only (Method/Path/Description/Roles)
- §5 Error catalogue — 25 errors, 2 columns only

**Zero-Silence coverage audit:**
- Contract 1 (Field-Name Coverage): **PASS** — 115/115 required identifiers present in backticks (entities, request bodies, query params, OCC fields, settlement output fields). Two initially missing (`diversion_plan_id`, `shipment_id`) were repaired in place and the audit re-run to zero missing.
- Contract 2 (Rule Coverage): **PASS** — all 28 validation priorities expressed (8-step ordering stated explicitly in §2.6, business rules paired with their error IDs in §3); all 4 OCC rules name write action + `expected_*_version` field + `ERR_STALE_VERSION`/412; all state-machine transitions across 8 state machines expressed with from/to states, preconditions, and side-effect cascades (incl. depth-2/depth-3 cascades: terminate→divert deliveries, accept→cumulative tonnage, outage start→boiler OUTAGE→capacity pool, divert→leg execution ranking with tie-break, complete→landfill decrement→auto-CLOSED); all 9 calculations rendered as precise prose with constants (1000 t/day, 0.32 tph/MW, 25% ash fraction, 12 months, 86400 s/day, strict-greater boundary semantics, inclusive cap boundary, closed vs half-open interval distinctions); all 25 error IDs mentioned in §2/§3 narrative.
- Contract 3 (§3 Path Purity): **PASS** — 448 backticked tokens scanned in §3, zero path tokens, zero bare HTTP methods, zero method+path combinations; all endpoints referenced via state-transition framing or role+verb.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read or referenced.

## Step 5: Generate Unit Tests — 2026-09-30T21:09:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/test_helpers/`:
- `types.py` — 18 entity TypedDicts (all common-fields entities) + 14 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (60 endpoints) + `api_client` singleton
- `api_errors.py` — 25 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions
- `factories.py` — 18 payload factories (input fields only; manifest auto-uniquifier)
- `constants.py` — DAILY_CAPACITY_TONNES=1000, STEAM_EFFICIENCY=0.32, ASH_FRACTION=0.25, clock startup default
- `test_users.py` — 5 opaque role header constants + per-role builders
- `fixtures.py` — composite helpers: `make_municipality`/`make_host_municipality`/`make_host_agreement`, `make_boiler`, `make_active_agreement` (returns post-activation dict so `version` is OCC-ready), `make_delivery`/`make_received_delivery`/`make_accepted_delivery` (re-fetches agreement version), `make_outage_with_approved_plan`/`start_outage`, `make_active_ppa`/`make_active_merchant_ppa`, `make_landfill`/`make_pending_shipment`/`complete_shipment`, `make_emissions_permit`/`make_emissions_reading`, `set_clock`
- `__init__.py` — barrel export (framework generics + PRD-specific)

**`test_suite/`** (13 files + `conftest.py`) under `.../test_suite/`, 79 tests total.

## Test counts by queue
- **Queue A (Difficulty): 30 tests across 20/20 instances** (every instance ≥2 tests, exactly 2 each except as split by aspect)
- **Queue B (Corner): 49 tests across 38/38 non-stub instances** (every non-stub instance ≥1 test)
- Emitted 58 distinct `Design:` tags = 20 difficulty + 38 corner non-stub; the 5 `excluded_because:` stubs were not translated and their difficulty cross-references all resolve.

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter — the PRD carries verbatim rule coverage for every asserted behavior (the put-or-pay response shape is in PRD §3.11, which un-skips `delivery_accept_cascades_to_settlement_base` and `put_or_pay_monthly_rollover_deduction`).

## Clock verification
All recipe dates (Sept–Nov 2026) are reachable from the 2026-09-01T00:00:00Z startup default; the monthly put-or-pay test explicitly sets the clock to 2026-10-15/2026-11-15 before each settlement run, and the host-priority window 2026-01-01..2027-01-01 contains the default logical now. No literal contradicted the PRD.

## Self-audit verdicts
- **Stage 1: PASS** — all 9 helper files parse; client methods match the endpoints the tests call (read back before Stage 2).
- **Stage 2: PASS** — 79 tests collect cleanly under pytest; every test has exactly one `Design:` line resolving to a real instance; all 133 quoted PRD citations survive an 8-word verbatim grep of `workspace/PRD.md`; no skip/xfail markers; no "scaffold"/§1.x references in generated code. Notes: the priority-conflict tests assert only PRD-stated orderings (state category 5 before business category 6; safety gate per §3.9/§2.6); version-literal assertions are pinned by the PRD §2.5 increment-per-mutation rule.

Orchestrator disk verification: 9 helper files and 14 test_suite files present; `grep -c "def test_"` totals 79 tests.

## Step 6: Generate Implementation — 2026-09-30T21:24:00.000Z

Done. Summary:

## Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/workspace/implementation/`)

| File | Bytes | Purpose |
|---|---|---|
| start.sh | 396 | Launcher (executable) |
| requirements.txt | 11 | flask>=3.0 |
| app.py | 1450 | Flask wiring, error handlers, blueprint registration |
| db.py | 991 | In-memory store, empty at boot; logical clock starts 2026-09-01T00:00:00Z |
| errors.py | 1078 | ApiError + error-id constructors |
| helpers.py | 5206 | ids, ISO timestamps, envelope, pagination, Decimal rounding (round-half-up) |
| auth.py | 619 | X-User-Role check (401) + per-endpoint role check (403) |
| calculations.py | 4560 | tipping fee, thermal input/capacity check, steam (0.32 cap), ash (25%), energy billing (PPA/MERCHANT variants), capacity payment proration, metals settlement (pinned per-line rounding), outage length, period indexing |
| serializers.py | 9441 | Wire shape for all 18 entity types |
| routes_municipalities.py | 5245 | municipalities + host community agreements (closed-interval overlap, ERR_NOT_HOST_COMMUNITY) |
| routes_agreements.py | 5564 | supply agreements, amendment OCC, activate/terminate with cascade to SCHEDULED deliveries |
| routes_deliveries.py | 9527 | delivery lifecycle: schedule, PUT, receive (1000 t/day tip-floor cap incl. boundary, host-community override), accept (OCC + fee + cumulative), reject, divert (cap = max_tpd × ceil-days, leg execution by planned_tonnes DESC/created_at ASC) |
| routes_boilers.py | 11397 | boilers (derate/restore/decommission), outage windows (half-open overlap, start OCC + approved-plan gate + boiler→OUTAGE cascade), diversion plans/legs |
| routes_reports.py | 4089 | daily throughput reports (pinned compute order, unique report_date, finalize gated on capacity_check == OK) |
| routes_energy.py | 6818 | PPAs + energy deliveries (term check, merchant price rule, billing + capacity payment) |
| routes_metals.py | 6633 | metals contracts (suspend/terminate) + batches (settle/dispute/resolve with recompute) |
| routes_ash.py | 8246 | landfills, ash shipments (tests before completion, OCC on landfill, capacity + daily-receipt caps, auto-CLOSE at zero), ash tests (passed = measured ≤ limit, recorded_at = logical clock) |
| routes_emissions.py | 4878 | permits (one ACTIVE per pollutant, suspend by Regulator) + readings (strictly-greater hourly breach + inclusive rolling-window daily average, 6dp) |
| routes_clock_settlements.py | 4362 | clock set (Regulator; fires agreement/PPA expiry) + put-or-pay settlement run (annual/monthly variants, already-billed tonnage-equivalent deduction, per-period superseding records) |

## Endpoint coverage
81 route registrations, matching the scaffold's 81-endpoint table exactly (verified by grep listing above) across every category: municipalities, host community agreements, waste supply agreements (+amendments), waste deliveries, boilers, outage windows, diversion plans/legs, throughput reports, PPAs, energy deliveries, metals contracts/batches, landfills, ash shipments/tests, emissions permits/readings, clock, put-or-pay settlements.

## Verified behaviors (live smoke tests against a booted server)
- Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`) and error shape; pagination fields in meta.
- Auth: missing role → 401 ERR_UNAUTHENTICATED; wrong role → 403 ERR_UNAUTHORIZED; unknown id → 404 ERR_NOT_FOUND.
- Delivery flow: projected_fee_cents (127500 = 25.5 × 5000), receive → accept with OCC → cumulative_delivered_tonnes grew to 25.5 and agreement version bumped.
- Capacity boundary: report at exactly 50.0 MW vs 50 MW boiler → OK, finalizable (fixed a rounding bug found in testing: capacity check now uses the 3dp-rounded thermal value).
- Outage flow: empty-plan approve → ERR_NO_DIVERSION_LEGS; start with stale boiler version → ERR_STALE_VERSION; start OK → boiler OUTAGE; divert marks largest leg executed.
- Landfill completion decremented remaining capacity; emissions hourly breach (strictly >) flagged exceedance; clock set fires nothing prematurely; settlement run returned annual-variant figures (shortfall 11974.5 t → 59,872,500 cents).
- Fresh `bash start.sh` boot (with `__pycache__` removed) served HTTP 200 within 3 s.

## start.sh contract confirmation
Reads `$PORT` (default 10000), binds `0.0.0.0` via `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))`, runs the server in the foreground via `exec python3 app.py`, and guards the pip install behind `python3 -c "import flask"` so per-test reboots skip it. No entity seeding anywhere — the store starts empty on every boot. All test-spawned processes were killed by their saved PIDs only.

Orchestrator disk verification: all 19 files present with matching sizes; `@bp.(get|post|put|patch|delete)` decorator count = 81; independent boot smoke test on port 19877 returned HTTP 200 for GET /wte/municipalities within ~3 s (killed own PID only).

## Step 7: Test-diagnose-fix loop — 2026-09-30T21:50:00.000Z

Clean 8-round sweep achieved: all rounds report 79/79 passed.

## Summary

**Iterations run:** 2 (first sweep: 17 stable failures across all 8 rounds; second sweep: 79/79 × 8 rounds, zero flakes).

**Tests deleted:** None. Every failing test's core assertion traced to verbatim PRD prose; failures were fixture bugs and implementation bugs, not PRD-silent assertions.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/test_helpers/factories.py` — `create_daily_throughput_report_payload` default `operating_hours` changed 30 → 24. PRD §3.6 caps `operating_hours` at 24; the default violated the PRD precondition and caused the shared "operating_hours must be > 0 and <= 24" setup failure in 5 tests.

**Fixes applied to `test_suite/` (STEP 2 — fixtures/preconditions inconsistent with PRD):**
- `test_06_boundary_precision.py::TestCapacityCheckBoundary` (both tests) — replaced PRD-illegal `operating_hours=30`/`25` fixtures with legal equivalents (540t × 10.0 MJ/kg ÷ 10h = exactly 150.000 MW for the at-capacity case; 541t for the over-capacity case), preserving the boundary semantics.
- `test_06_boundary_precision.py::TestEmissionsLimitEquality::test_hourly_limit_breach_requires_strictly_greater_value` — permit now uses `daily_limit=250` (pollutant SO2) so the daily rolling-average breach can't fire and `exceedance` is decided by the hourly comparison alone, as the test intends.
- `test_06_boundary_precision.py::TestTipFloorInclusiveBoundaryAndHostOverride` — restructured fixtures: host delivery moved to a different UTC day (whether host-priority SCHEDULED deliveries consume the standard cap is not uniquely derivable from PRD §3.3), and the 11-tonne over-cap delivery is created after the day is already at exactly 1000t so "landing exactly at the cap" exercises 990+10=1000 inclusively.
- `test_03_state_machines.py::TestFinalizedReportImmutable` — fixture changed to legal 540/10.0/10 values (thermal input still exactly 150.000 MW).
- `test_04_cascades.py::TestOutageStartCascadesToCapacityCheck._setup` — same illegal-hours fix (540/10.0/10 → 150.000 MW exactly at capacity).
- `test_03_state_machines.py::TestWsaInitialState` — removed the assertion that *scheduling* a delivery against a DRAFT agreement is rejected (PRD §3.3 gates only receive/accept on ACTIVE; a PRD-faithful reader would not gate scheduling — fails unique derivability). Kept the PRD-covered assertions: new agreement is DRAFT, and receive against DRAFT is rejected with `ERR_INVALID_STATE`.
- `test_01_commercial_variants.py::test_merchant_delivery_has_zero_capacity_payment` — added `make_boiler()` so available MW > 0 and the PPA capacity payment is positive per PRD §3.7's min(contracted_mw, available MW) formula.

**Fixes applied to `implementation/`:**
- `workspace/implementation/helpers.py::new_entity` — creation now initializes `version` to 1 (was 0). PRD §2.5's "increments by one on every mutation" with tests asserting version 1 at creation; this single fix resolved 6 failures (metals batch, boiler derate chain, delivery terminal lockdown, system-fields-ignored, municipality list envelope, PUT edit projection).
- `workspace/implementation/routes_deliveries.py::receive_delivery` — daily tip-floor sum now excludes the delivery being received (it is SCHEDULED and was counted in `day_load` and then added again, double-counting it). PRD §3.3's "same-day deliveries ... plus this delivery's tonnes" reads the receiving delivery once.

No tests weakened, no skips/xfails added, no PRD-required implementation checks removed, no data seeded.

Orchestrator verification: the subagent's results.*.json files were absent at hand-back, so the orchestrator re-ran the full 8-round sweep itself — result: 79/79 passed, 0 failed, in ALL 8 rounds. Implementation file mtimes (helpers.py 21:33, routes_deliveries.py 21:30) corroborate the two claimed impl fixes; results files now on disk and passing.

## Step 8: Finalize PRD — 2026-09-30T21:56:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3321_waste_energy_plant_operations_tipping_fee_contracts/workspace/PRD_FINALIZED.md` created as a minimal 2-line patch of PRD.md.

**Line counts / delta:** PRD.md 335 lines, PRD_FINALIZED.md 335 lines — 0% delta (two in-place sentence revisions, no lines added or removed).

**Changes made:**
- §2.5 Common Resource Properties — revise — the `version` bullet now states the integer "starts at 1 when the resource is created and increments by one on every mutation", pinning the initial value PRD left open — `workspace/implementation/helpers.py:182` (`new_entity` sets `"version": 1`).
- §3.3 Receiving — revise — the daily tip-floor cap sentence now reads "total tonnes of **other** same-day deliveries in `SCHEDULED` or `RECEIVED` status — the delivery being received is not itself part of that same-day sum — ... plus this delivery's tonnes", so the receiving delivery contributes its tonnes exactly once — `workspace/implementation/routes_deliveries.py:146-151` (`day_load` excludes `x["id"] != d["id"]`).

**Step 7 items judged NOT PRD gaps (pure fixture/precondition bugs, no edit):** factories.py operating_hours 30→24 (PRD §3.6 already caps at 24); TestCapacityCheckBoundary / TestFinalizedReportImmutable / TestOutageStartCascadesToCapacityCheck fixture values (illegal hours); TestEmissionsLimitEquality permit daily_limit (PRD §3.10 already specifies OR semantics); TestTipFloorInclusiveBoundaryAndHostOverride host-day restructure (impl behavior confirmed to already match PRD §3.3's existing wording — see pre-edit search below); TestWsaInitialState scheduling-against-DRAFT assertion removal (impl `create_delivery` has no agreement-state gate, consistent with PRD which gates only receive/accept); test_01 merchant capacity payment `make_boiler()` addition (PRD §3.7 already pins min(contracted_mw, available MW)).

**Per-edit pre-edit search log:**

Edit 1 (§2.5 version initial value):
- (a) Subject: initial value of the `version` field at resource creation.
- (b) Enumerated paths: `helpers.py:181-184` (`new_entity`, sole constructor — sets version 1), `helpers.py:176-178` (`touch`, sole mutator — increments), and every creation callsite grepped via `grep -rn "new_entity"` across routes_reports.py:42, routes_emissions.py:41,110, routes_deliveries.py:54, routes_energy.py:48,144, routes_metals.py:38,110, routes_ash.py:39,85 (all entities use `new_entity`); serializers.py exposes `version` uniformly for all resource types. §2.5 is the single global statement covering every resource type, so one edit covers all paths.
- (c) Wording adjustment: scoped strictly to the `version` bullet ("starts at 1 when the resource is created") — the trailing paragraph about mutations/updated_at was left verbatim so all cascade/touch behavior remains accurately described.

Edit 2 (§3.3 daily tip-floor sum):
- (a) Subject: which deliveries contribute tonnes to the 1000-tonne daily cap comparison at receive time.
- (b) Enumerated paths: `grep -rn "DAILY_CAPACITY\|day_load"` — only `calculations.py:11` (constant) and `routes_deliveries.py:146-151` (`receive_delivery`, the sole cap check). The accept/reject/divert paths and the `_host_priority_applies` override were read (routes_deliveries.py:119-157) to confirm no other code consumes the day sum and the host override only skips the already-computed check, so rewording the sum composition cannot misdescribe the override.
- (c) Wording adjustment: changed "same-day deliveries" to "other same-day deliveries" with an explicit exclusion clause for the delivery being received, and appended "so the delivery being received contributes its tonnes exactly once to the comparison" — preserving the existing inclusive-comparison sentence and host-override sentences verbatim, since the impl matches those already (verified against the Step-7-restructured host-override test, which passes against current impl).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two claimed sentence revisions and nothing else (335→335 lines). Implementation mtimes unchanged since the clean sweep (latest 21:33, sweep ran ~21:50) — no post-sweep impl edits.

## Step 9: PRD completeness scan — 2026-09-30T22:04:00.000Z

All edits applied. Diff confirms 20 changed lines, all in-place.

## Summary

**Files**: `workspace/PRD_FINALIZED.md` (335 lines, 51,705 chars) → `workspace/PRD_COMPLETED.md` (335 lines, 55,144 chars; +3,439 chars, 0 line-count change).

**Counts**: ambiguity-pins 18, mismatch-revisions 2, no genuine impl-vs-PRD bugs found (implementation is the alignment target throughout; all differences were resolved by PRD wording).

Changes (all `{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.2 — insert — ambiguity — pinned datetime wire format `YYYY-MM-DDTHH:MM:SSZ` and decimal serialization (int when whole) — serializers.py:7, helpers.py:99
- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending — every list route (e.g. routes_municipalities.py:51)
- §2.5 — insert — ambiguity — amendment rows start at `version` 1 like any resource — routes_agreements.py:63
- §2.6 — insert — ambiguity — within a body, required-field presence runs before field-shape checks; `null` treated as missing — helpers.py:170-173, routes_municipalities.py:23-35
- §2.9 — insert — ambiguity — amendment OCC check runs before payload field-shape validation — routes_agreements.py:43-58
- §3.1 — insert — ambiguity — host-community-agreement list filterable by `municipality_id` — routes_municipalities.py:115-117
- §3.1 — insert — mismatch (validation ordering) — `ERR_NOT_HOST_COMMUNITY` evaluated after field-shape validations — routes_municipalities.py:77-92
- §3.2 — insert — ambiguity — acceptance updates cumulative tonnage by adding the delivery's tonnes (equivalent to recompute) — routes_deliveries.py:180
- §3.2 — insert — ambiguity — termination cascade bumps each diverted delivery's `version` — routes_agreements.py:133-137
- §3.3 — insert — ambiguity — `projected_fee_cents` is null outside `SCHEDULED` status — routes_deliveries.py:24-29, serializers.py:58-76
- §3.3 — insert — ambiguity — agreement-ACTIVE precondition on receive applies even under host priority — routes_deliveries.py:142-144
- §3.3 — insert — ambiguity — delivery `reject_reason` field omitted from representation until set — serializers.py:74-75
- §3.4 — insert — ambiguity — "another outage ACTIVE" check on start is `ERR_INVALID_STATE` (target-state category) — routes_boilers.py:192-195
- §3.5 — insert — ambiguity — leg execution bumps the leg's `version`; plan/ACTIVE precondition checked before capacity bound — routes_boilers.py:223-241
- §3.6 — insert — ambiguity — with no boilers registered, capacity sum is zero (any positive thermal input EXCEEDS) — calculations.py:39-40
- §3.6 — insert — ambiguity — steam output uses the 3-dp-rounded thermal input from step one — calculations.py:36-41
- §3.7 — insert — ambiguity — MERCHANT zero-capacity-payment shape enforced at creation; both kind-shape rules re-checked at activation — routes_energy.py:39-40, 94-97
- §3.7 — insert — ambiguity — PPA-supplied merchant price validated for integer shape, ignored, stored as null — routes_energy.py:138-149
- §3.7 — insert — ambiguity — period-fraction cap applied after six-decimal rounding — calculations.py:71-73
- §3.8 — insert — ambiguity — metals contract termination allowed from ACTIVE or SUSPENDED; rejected only if already TERMINATED — routes_metals.py:87-88
- §3.8 — insert — ambiguity — batch settle's contract-ACTIVE requirement is `ERR_INVALID_STATE` (target-state category) — routes_metals.py:153-154
- §3.9 — insert — ambiguity — failing test detected before no-tests; landfill-ACTIVE requirement is `ERR_INVALID_STATE`; shipment `reject_reason` omitted until set — routes_ash.py:141-147, serializers.py:245-246
- §3.10 — insert — ambiguity — `rolling_avg_window_hours` must be > 0 — routes_emissions.py:39-40
- §3.11 — revise — mismatch — annual-cadence period is the contract year containing the logical clock (anchored at `term_start` anniversaries, end clamped to `term_end`), not always the whole contract year — calculations.py:107-119
- §3.11 — insert — ambiguity — "earlier periods" ordered by `(period_start, period_end)`; tonnage equivalent zero when current rate is zero; `guarantee_tonnes` and `shortfall_tonnes` reported at three decimals — routes_clock_settlements.py:64-84, 102-104

Orchestrator verification: PRD_COMPLETED.md on disk (335 lines, 55,144 chars). `find ... -newermt "2026-09-30 21:50"` over implementation/, test_suite/, test_helpers/ returns nothing — no post-sweep edits, so the clean 8-round sweep (79/79 × 8) remains valid for the final artifact state.
