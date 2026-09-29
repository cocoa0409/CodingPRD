# Worklog — task_2889_airport_checkpoint_staffing_wait_time_management

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2889_airport_checkpoint_staffing_wait_time_management` and its `workspace/` subdirectory. Index 2889 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate Scaffold — 2026-09-05T13:42:49.711586083Z

Scaffold for task 2889 is complete and lint-clean.

**Final lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2889_airport_checkpoint_staffing_wait_time_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2889_airport_checkpoint_staffing_wait_time_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2889_airport_checkpoint_staffing_wait_time_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1268

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2889_airport_checkpoint_staffing_wait_time_management/`)

| file | bytes | lines |
|---|---|---|
| SCAFFOLD.yaml | 161261 | 2179 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 94423 | 1480 |
| SCAFFOLD_CORNER_DESIGN.yaml | 215378 | 3612 |

Top-level keys verified by `yaml.safe_load`: SCAFFOLD.yaml carries only §1.0–§1.7 keys (no `scaffold_difficulty_design` / `scaffold_corner_design`); the two design files each have exactly their single required top-level key. Scenario text is byte-identical to the assignment.

**Scaffold summary**

- **Entities: 13** — Checkpoint, Lane, Equipment, Officer, FlightSchedule, ShowUpCurve, TimeBand, StaffingPlan, LaneAssignment, WaitTimeObservation, EscalationTicket, SecondaryScreeningReferral, SurgeDetail. `entity_topology: flat`, so all relationships are FK references with reverse-reachability through list endpoints.
- **Endpoints: 59**; **errors: 48**; **validations: 30** (priority-ordered); **roles: 6** (StaffingPlanner, DutyManager, CheckpointManager, SupervisoryOfficer, ScreeningOfficer, ForecastAnalyst) under `role_model: segregation_of_duties`.
- **State machines: 9** — Checkpoint posture, Lane, Equipment, Officer duty axis, StaffingPlan, LaneAssignment, EscalationTicket, SecondaryScreeningReferral, SurgeDetail. `state_machine_shape: parallel` (Lane operational state and Officer duty axis advance independently and combine at check-in). Two §1.2.1 `concurrency_rules` (OCC on Checkpoint.version for plan creation, on Officer.version for surge details).
- **Key calculations (7)**: `band_passenger_forecast` (dual-variant SCHEDULE_ONLY vs CURVE_BLENDED, seasonal multiplier optional, show-up buckets must tile the window and sum to 100); `required_lanes` (ceil of forecast ÷ per-lane throughput, floored at MIN_OPEN_LANES per lane type); `wait_time_weighted_average` (sample-size-weighted, 2dp half-up) feeding `threshold_breach_counter` (rate/threshold trigger: 2 consecutive breaches per lane type raise a ticket and escalate posture, dropping below threshold resets the counter and expires the ticket); `staffing_plan_cost` (regular/overtime split at the weekly cap, plus detail cost, plus an admin fee rate on the subtotal → total, with a per-checkpoint cost cap enforced strictly above); `secondary_capacity` (concurrent referral slots per checkpoint); `throughput_diversion_analysis` (pure read).
- **§1.8 `scaffold_difficulty_design`: 18 instances** — 9 rule_ids × 2, including a depth-4 equipment-fault cascade and a depth-3 plan-supersede cascade (both with `verify_calls:`).
- **§1.9 `scaffold_corner_design`: 62 instances** across all nine sections — entities 11, state_machines 15, calculations 12, validations 12, endpoints 6, errors 3, rbac 7, cross-cutting complexity layers 5, consistency model 1 (two of these are `excluded_because` stubs deferring to §1.8).

Final change this session closed a §1.2/§1.8 grounding gap: the Officer `ON_DUTY -> OFF_DUTY` edge now declares the system-driven variant (last live LaneAssignment retired by a plan supersede/close driving `committed_duty_minutes` to 0), so the depth-3 cascade's link-3 assertion is backed by an explicit transition rather than only by the StaffingPlan side-effect prose.

**Orchestrator note (post-subagent verification):** the scaffold generator had copied the difficulty directive line "Generate task harder than expert level!" into `SCAFFOLD.yaml`'s `scenario:` block, and had written a header comment describing the task as deliberately above the Expert envelope. Both were stripped by the orchestrator so the directive cannot reach PRD.md via the doc generator. `yaml.safe_load` re-verified on all three files after the edit; scenario text otherwise byte-identical to the assignment.

## Step 3: Copy Shared Files — 2026-09-05T13:42:49.723363541Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T13:59:36.313464701Z

PRD generation for task 2889 is complete.

**Output**: `workspace/PRD.md`
- **467 lines / 118,275 characters**, built by 14 chunked `cat >>` appends (no single large Write).
- **Tail intact**: last heading in the file is `## 5. Error Code Catalogue`; final line is `| \`ERR_BAND_NOT_FORECAST\` | 422 |` — a complete table row at a real section boundary. No audit footer, no contract-report block in the file.

**Top-level sections present** (`grep -n '^## '`): `## 1. Introduction` (3), `## 2. Global Specifications & System-Wide Principles` (11), `## 3. Business Logic & Workflows` (177), `## 4. Endpoint Definitions` (348), `## 5. Error Code Catalogue` (414). Subsections: 2.1–2.10 and 3.1–3.9.

**Counts**: 59 endpoint rows in the §4 table (Method / Path / Description / Authorized Role(s)) and 48 error rows in §5 (Error ID / HTTP Status Code) — both generated programmatically from the scaffold, so no transcription drift. §2.2 diffs byte-identical against `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (only a trailing blank separator line added).

**Hard Contract reports**

```
Field-name coverage (Contract 1):
- required names (entities[].fields[].name + endpoints[].input + path_params + query_params + expected_*_version): 151
- backtick tokens extracted from PRD (fenced blocks excluded): 431
- missing: 0
Status: PASS
```
Two passes were run as mandated. Pass 1 found exactly one omission — `outcome`, the referral-resolve request key — which was added to §3.9 ("Resolution is a four-way fork selected by the request's `outcome`..."); pass 2 was clean.

```
Rule coverage (Contract 2):
- state transitions in scaffold: 53 — all narrated (preconditions + side effects), incl. the depth-4 equipment-fault cascade and depth-3 approval-supersede cascade
- calculations: 7/7 (time_band_pax_forecast with both variants, lane_requirement waterfall, officer_duty_ledger with both variants, staffing_plan_cost 8 steps + fee tiers, published_wait_time, checkpoint_posture 4 ordered branches, throughput_and_diversion_index)
- validation priorities: 30/30 rendered as an ordered ladder in §2.8, each paired with its error_id; trigger conditions also restated at the workflow they guard
- concurrency rules: 2/2 (expected_checkpoint_version / ERR_STALE_CHECKPOINT_VERSION, expected_officer_version / ERR_STALE_OFFICER_VERSION, both 412)
- error IDs referenced in §1–§4 prose: 48/48 (none appear only in the §5 table)
- invariants: lane-position, officer duty-minute and secondary-slot conservation all in §2.9
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1098
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Two scaffold inconsistencies resolved deliberately** (worth flagging to whoever reviews the tests):
1. **Calibration boundary** — the `calibration_due_utc` field description and the `CLOSED -> OPEN` transition imply a unit due exactly at the clock blocks the open, while validation priority 17 says only *strictly earlier* blocks. Written per priority 17: strictly earlier is `ERR_CALIBRATION_OVERDUE`, exactly-due is acceptable.
2. **Duty-ledger variant at check-in** — validation 29 names `FORWARD_LOOKING_PLANNED` for all three overtime-capped writes, but the `SCHEDULED -> CHECKED_IN` precondition names `CHRONOLOGICAL_ACTUAL`. Resolved specific-over-general: check-in uses the chronological-actual ledger including that row's `planned_minutes`; assignment creation and surge-detail decision use forward-looking.

Minor gap-fills also documented as such in the PRD: plan submission with no live assignments maps to `ERR_INVALID_STATE_TRANSITION` (no dedicated code exists), and the LaneAssignment `CANCEL` role conflict (state-machine actor `StaffingPlanner` vs endpoint roles) is left unnamed in §3 so §4's table is the single authority.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator verification (anti-truncation guard):** re-ran `wc -l -c` (467 / 118275), `grep -n '^## '` (all 5 top-level sections at lines 3/11/177/348/414), and read the tail directly — the file ends on a complete `| \`ERR_BAND_NOT_FORECAST\` | 422 |` table row, not mid-sentence. Also grepped PRD.md for "harder than expert", "scaffold", "SCAFFOLD.yaml", "test_recipe": zero hits, so neither the difficulty directive nor scaffold-internal vocabulary leaked. PRD accepted without regeneration.

## Step 6: Generate Implementation — 2026-09-05T14:49:07.449727684Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so Step 6's impl generator could not see `test_suite/` — the directory did not exist at its spawn time. Step 6 returned first; Step 5's entry follows below.)

Implementation complete. All work is inside `workspace/implementation/` — nothing outside it was read or written (no `test_helpers/`, no `test_suite/`, no `worklog.md`, no sibling task dirs; scratch confined to `/tmp/task_2889_impl/`).

## Files (16, all chunked-appended and `ast.parse`-verified)

| lines | file | role |
|---|---|---|
| 654 | `routes_ops.py` | wait observations, wait-time, escalation tickets, referrals, surge details, throughput analysis |
| 642 | `routes_plans.py` | staffing plans (8 endpoints) + lane assignments (5) |
| 498 | `routes_core.py` | clock, show-up curves, checkpoints, lanes, equipment units |
| 399 | `calc.py` | the seven PRD calculations |
| 318 | `routes_staff.py` | officers, duty ledger, flight schedule, time bands, forecast |
| 302 | `cascade.py` | system-driven multi-link side effects |
| 293 | `req.py` | auth, body/field validation, FK resolution, pagination, filters |
| 180 | `derive.py` | computed fields and conserved quantities |
| 142 | `util.py` | ids, canonical ISO-8601, Decimal/rounding helpers |
| 123 | `store.py` | in-memory dict tables, logical clock, JSON projection |
| 102 | `errors.py` | 48 error ids -> HTTP status map, `ApiError` |
| 91 | `consts.py` | every tunable constant and enum tuple |
| 65 | `serial.py` | per-entity serializers |
| 63 | `app.py` | app factory, blueprint registration, envelope error handlers |
| 37 | `envelope.py` | object/array/error envelopes |
| — | `start.sh`, `requirements.txt` | launcher (reads `$PORT`, binds `0.0.0.0`, foreground `exec python3 app.py`, no reloader) |

3909 Python lines total. Every `.py` parses and `py_compile`s; `__pycache__` removed and `PYTHONDONTWRITEBYTECODE=1` is set by `start.sh`.

## Endpoint count
**59 exactly**, enumerated from Flask's URL map and matched one-for-one against PRD §4 (27 GET, 31 POST, 1 PATCH). No extra endpoints, fields or side effects beyond the PRD.

## Organisation
- **State machines**: cyclic/parallel machines live with their resource routes; every *system-driven* transition (lane pause/reopen/close, `CHECKED_IN <-> REASSIGN_PENDING`, plan supersede/close retirement, break end, officer `ON_DUTY->OFF_DUTY`, ticket raise/expire) is centralised in `cascade.py`, so the depth-4 `equipment_fault_to_escalation` and depth-3 `plan_approval_supersede` chains have exactly one implementation. `Checkpoint.posture` is derived, never stored authoritatively; a `flask.g` guard caps `Checkpoint`/`Officer` version at one bump per request. `POSTURE_DEGRADATION` tickets fire only on a genuine `NORMAL->ELEVATED` edge with a breaching latest STANDARD publication.
- **Calculations**: all seven in `calc.py` (`time_band_pax_forecast`, `lane_requirement`, `officer_duty_ledger`, `staffing_plan_cost`, `published_wait_time`, `throughput_and_diversion_index`) plus `derive.posture`. Decimal + ROUND_HALF_UP throughout, money as integer cents, and only the three PRD-mandated ratios serialized as fixed-precision strings (`admin_fee_rate` 3dp, `weighted_average_seconds` 2dp, `diversion_rate` 4dp). Conserved quantities (`available_lane_positions`, `committed_duty_minutes`, `approved_detail_minutes`, `secondary_slots_in_use`) are always recomputed from scratch.
- **Validation** follows the 30-rung precedence ladder in declaration order per endpoint; timestamps are a single canonical `YYYY-MM-DDTHH:MM:SS.mmmZ`; store is pure dicts with zero seeding and no disk I/O.

## Smoke check (ports 57891/57892, killed by exact pid — no pattern kill)
Two scripted flows, **0 failures, 0 server-side tracebacks**:
- Happy path: clock set -> checkpoint -> lane + 4 units -> lane open (`SERVICEABLE`) -> curve -> flight (`projected_pax=160`) -> 3 forecast bands (`CURVE_BLENDED` 36/54/54, `required_standard=1`, `required_expedited=1`) -> plan -> assignments -> submit (`reg=100, ot=20, subtotal=14200, fee=0.045, total=14839`) -> reject -> revise (rev 2, costs nulled) -> resubmit -> approve -> activate -> check-in -> surge detail approve (`6000`c, officer committed 60->120) -> cancel (exact reversal to 60) -> break `DUE` at +65min -> START/END (`taken=15`, `actual=65`) -> ALARM referral begin/`REFERRED_LEO` (lane `PAUSED/SECURITY_INCIDENT`, assignment `REASSIGN_PENDING`) -> reopen (crew recalled to `CHECKED_IN`) -> equipment `OUT_OF_SERVICE` cascade (lane paused, posture `ELEVATED`) -> 2 breaching observations raise one `WAIT_THRESHOLD_BREACH` ticket -> acknowledge -> `MITIGATED_BY_DIVERSION` (`diverted=25`, `diversion_rate=0.1736`) -> suspend/un-suspend -> plan close (assignments `RELEASED`, officer auto `OFF_DUTY`) -> stand-down chain -> separation.
- Negative paths confirmed: 401 missing headers, 403 unknown/wrong role + SoD + non-owner + action-for-role, 404 unknown id, 400 shape/enum/limit, 412 both OCC gates, 409 duplicate band, break-not-due, illegal transitions, lane capacity, rest buffer, secondary capacity, 422 certification, equipment unavailable, min-lanes-not-met, resolution-lane-invalid.

Three earlier "failures" in my own smoke script turned out to be my expectations being wrong, not implementation bugs (closed-interval lane contention at a shared band endpoint, `PAUSED->PAUSED` rejection, and an officer already auto-moved to `OFF_DUTY` by the plan-close cascade) — each confirmed the spec'd behaviour.

## Step 5: Generate Unit Tests — 2026-09-05T15:28:33.372324916Z

Verification complete. Both stages are done and clean.

## Output location (verified)
`ls -la` on the task root shows `test_helpers/` and `test_suite/` as siblings of `workspace/`; `workspace/test_helpers` and `workspace/test_suite` do not exist. Nothing outside the two output directories was created or modified (`git status` on the task dir shows only the single untracked task directory; `workspace/implementation/`, `workspace/PRD.md` and `worklog.md` untouched).

## Files written

`test_helpers/` (Stage 1, 2,224 lines)
- `__init__.py` 98, `api_client.py` 315, `api_errors.py` 129, `assertions.py` 406, `constants.py` 216, `factories.py` 331, `fixtures.py` 606, `test_users.py` 123, `types.py` 30

`test_suite/` (Stage 2, 5,941 lines, 17 files)
- `conftest.py` 32
- `test_01_checkpoint_floor_registry.py` 353 (11 tests), `test_02_lane_and_officer_state_machines.py` 540 (11), `test_03_demand_forecasting.py` 285 (8), `test_04_staffing_plan_pricing.py` 293 (6), `test_05_plan_approval_chain.py` 294 (6), `test_06_duty_ledger_and_break_cycle.py` 311 (6), `test_07_wait_time_publication.py` 261 (6), `test_08_equipment_and_posture_cascades.py` 331 (6), `test_09_assignment_temporal_guards.py` 273 (6), `test_10_conservation_and_priority_ladders.py` 377 (6), `test_11_assignment_and_plan_validations.py` 378 (6), `test_12_reference_data_and_capacity_validations.py` 384 (5), `test_13_endpoint_contracts.py` 415 (6), `test_14_cross_entity_guards_and_error_catalogue.py` 391 (7), `test_15_rbac_and_ownership.py` 551 (7), `test_16_concurrency_and_immediate_consistency.py` 441 (5)

## Quality gates
- `ast.parse` on all 26 generated .py files: 0 syntax errors. No `__pycache__`/`.pytest_cache` left behind.
- `pyflakes test_suite/test_*.py`: clean (fixed one unused `OPERATIONAL_DATE` import in test_05 during this pass). Remaining warnings are only the deliberate re-export surfaces in `test_helpers/__init__.py` and `test_suite/conftest.py`.
- `pytest --collect-only`: **111 collected, 0 collection errors** — 108 test functions, one of which is `@parametrize`d into 4 cases in test_12.

## Design-index coverage
- **108 tagged tests, 80 distinct `Design:` tags.** Every test has exactly one `Design:` line and it is the last non-blank line of its docstring. **Dangling tags: 0.**
- **§1.8 (Difficulty): 18/18 instances translated** (0 stubs in that file), 38 tests — every instance has >=2 tests (the supersede cascade has 4).
- **§1.9 (Corner): 62/62 non-stub instances translated**, 70 tests. No stub instance was translated.

## Skipped instances
No instance was skipped for PRD-silence or non-unique-derivability. The only skips are the 10 corner instances the design yaml itself marks `excluded_because` (each defers to a §1.8 instance that already covers it end-to-end):
- `Corner/state_machines/lane_assignment_two_axes_advance_independently_on_one_row` -> dup of `non_linear_state_machine/lane_assignment_break_cycle_runs_parallel_to_duty_axis`
- `Corner/state_machines/staffing_plan_backward_edge_reopens_the_draft` -> `non_linear_state_machine/staffing_plan_rejected_to_draft_revision_cycle`
- `Corner/state_machines/equipment_fault_cascade_reaches_the_escalation_ticket` -> `transitive_cascade/equipment_fault_to_escalation_depth_four`
- `Corner/state_machines/plan_approval_supersede_cascade_recomputes_the_officer_ledger` -> `transitive_cascade/plan_approval_supersede_depth_three`
- `Corner/calculations/forecast_two_variants_diverge_on_identical_flight_data` -> `dual_variant_calc/forecast_variant_divergence_schedule_only_vs_curve_blended`
- `Corner/calculations/forecast_rounds_each_flight_contribution_before_summing` -> `combinatorial_formula/forecast_rounding_order_round_per_flight_then_sum`
- `Corner/calculations/duty_ledger_variant_selection_by_call_context` -> `dual_variant_calc/officer_duty_ledger_planned_vs_chronological_actual_divergence`
- `Corner/calculations/admin_fee_rate_keyed_on_subtotal_not_total` -> `combinatorial_formula/plan_cost_admin_fee_tier_keyed_on_subtotal_not_total`
- `Corner/validations/two_violations_at_different_priorities_report_the_lower_number` -> `priority_pair_validation_conflict/check_in_plan_not_activated_outranks_calibration_overdue`
- `Corner/cross-cutting complexity layers/cascade_chain_from_equipment_fault_reaches_four_entities` -> `transitive_cascade/equipment_fault_to_escalation_depth_four`

## Notable design adjustments (kept PRD-derivable)
Three design assertions were narrowed rather than asserted as written, each with an in-test comment: the supervisor-certification instance nominates a certified second officer (self-nomination would also trip PRD §3.9's nominee-!=-detector rule, making the expected error non-unique); `seasonal_multiplier` is compared numerically because the PRD declares only `admin_fee_rate`, `weighted_average_seconds` and `diversion_rate` as decimal strings; and a "no other checkpoint exists" assertion was replaced with an empty plan listing plus an unchanged checkpoint version, since the PRD exposes no `GET /checkpoints` collection.

**Orchestrator verification:** `ls -d workspace/test_helpers workspace/test_suite` -> both absent; `test_helpers/` and `test_suite/` confirmed at the task root as siblings of `workspace/`. No move was needed.

## Step 7: Run Tests and Iterate — 2026-09-05T15:57:11.669742188Z

All 8 rounds are fully green: **111/111 passing in every round**.

## Summary

**Iterations run:** 2 sweeps (baseline + confirmation). Baseline was deterministic — the same 7 failures in all 8 rounds, no flakiness, no load-induced noise.

**Final sweep evidence** (`workspace/implementation/results.{1..8}.json`):
| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 111/111 | 111/111 | 111/111 | 111/111 | 111/111 | 111/111 | 111/111 | 111/111 |

0 failed, 0 errors, 0 skipped in all rounds. Baseline was 104/111 x8.

**Tests deleted:** none. One partial-coverage trim under STEP 1c:
- `test_06_duty_ledger_and_break_cycle.py::test_a_completed_break_rearms_and_leaves_the_release_fields_null` — removed only the two `actual_minutes is None` assertions on a **CHECKED_IN** row (COMPUTED-FIELD SILENCE). PRD §3.3 names exactly `SCHEDULED` or `CANCELLED` as the null states ("that last field stays null for as long as the assignment is `SCHEDULED` or `CANCELLED`"), and §4 calls it "the computed `planned_minutes` / `actual_minutes`" — so a faithful reader may legitimately expose a live elapsed-minus-breaks value while checked in (the impl returned 65). Every other assertion in the test (`released_at_utc` null, `break_state` DUE, `break_minutes_taken` 15, `assignment_state` CHECKED_IN) is verbatim-covered and was kept. Scaffold driver: `non_linear_state_machine/lane_assignment_break_cycle_runs_parallel_to_duty_axis`.

**Fixes applied to `test_helpers/`:** none — the helpers were clean (no money-as-string, no date-only literals, no envelope double-unwrap; `api_client` already canonicalises ISO instants).

**Fixes applied to `test_suite/`:**
- `test_05_plan_approval_chain.py`, `_rival_plan_ready_to_approve` — gave `rival_officer` `ADVANCED_IMAGING` alongside `STANDARD_LANE`. The shared lane is a STANDARD lane, which per §3.1 hosts an `ADVANCED_IMAGING` unit, and §3.3 requires that certification "when the target lane hosts an advanced imaging unit". The impl was correctly returning `ERR_OFFICER_NOT_CERTIFIED`; this one fixture line was failing the setup of all 4 `TestSupersedeCascade` tests.
- `test_12_reference_data_and_capacity_validations.py::test_a_third_begin_is_refused_until_a_slot_is_released` — two setup bugs. (1) The test raised 3 referrals against a capacity of 2 up front, then expected the first two begins to succeed. Under §3.9's rule (other held slots must be *strictly below* capacity) the other-count is a constant 2 for all three begins, so its expected shape was arithmetically impossible at any capacity. Restructured to raise 2 -> begin both (others=1 < 2, which is what proves the own-slot exclusion) -> raise the 3rd -> its begin is refused (others=2) -> clear one -> retry succeeds. (2) The `CLEARED` resolve was sent by the same supervisor who raised the referral, a latent `ERR_SEGREGATION_OF_DUTIES` violation (§2.1/§3.9); it now goes through the nominated resolver as a `ScreeningOfficer`, which is exactly §3.9's "may clear only the referral they were themselves nominated to work".

**Fixes applied to `implementation/`:**
- `calc.py`, `apply_plan_cost` — widened the state gate from `("SUBMITTED","APPROVED","ACTIVATED")` to include `"DRAFT"`. PRD §3.3 states assignment creation "recomputes the owning plan's cost" and that "the same computation is re-run on every later write that changes the plan's assignments or its approved details", neither conditioned on submission; the only PRD-mandated nulls are at create ("a plan with no assignments has nothing to price") and after a revise, both of which still hold since `apply_plan_cost` is only reached from an assignment/detail write. No cost-cap enforcement was added here — that stays at submission and surge-detail decision per the §2.8 ladder (priority 30).

Notably, 3 of the 4 root causes were test-side (STEP 2) and only 1 was a genuine implementation defect; no PRD-required check was weakened, no assertion was downgraded, and `workspace/PRD.md` and `worklog.md` were left untouched.

**Orchestrator verification (independent of the subagent's claim):** read all 8 `workspace/implementation/results.$i.json` directly — each reports `passed=111, failed=0, errors=0, skipped=0, total=111` with 111 per-test records and `duration_seconds` ~148s; all 8 files carry the same mtime (15:45Z) and near-identical byte sizes, consistent with one genuine concurrent sweep rather than a stale or partial run. Step 8 is therefore NOT skipped: Step 7 applied 1 `implementation/` fix, 2 `test_suite/` fixes and 1 partial-coverage trim.

## Step 8: Finalize PRD — 2026-09-05T16:06:38.452615163Z

Verification complete. `PRD_FINALIZED.md` is 467 lines (identical to `PRD.md`), all five top-level sections present, file still ends on the `ERR_BAND_NOT_FORECAST` row of the §5 error table, and `diff` shows exactly four changed lines.

## Line counts
- `PRD.md`: 467 lines / 118,275 chars
- `PRD_FINALIZED.md`: 467 lines / 120,519 chars
- Delta: **0 lines (0.0%)**, +2,244 chars (**+1.90%**) — four in-place sentence revisions, no new sections, no reflow.

## Changes
- **§3.3 (assignment creation, line 223)** — *revise* — pinned `actual_minutes` as a read-time computed field: null only while `SCHEDULED`/`CANCELLED` or never-checked-in, otherwise whole minutes from `checked_in_at_utc` to `released_at_utc` **or to the current logical clock** while still `CHECKED_IN`/`REASSIGN_PENDING`, floored at zero then less `break_minutes_taken`; and pinned that assignment creation recomputes the plan cost **while the plan is still `DRAFT`** — `derive.py:155-162`, `serial.py:42-44`, `routes_plans.py:487`, `calc.py:273-287`.
- **§3.3 (assignment guards, line 225)** — *revise* — the `ADVANCED_IMAGING` certification requirement is triggered by the bare presence of an `ADVANCED_IMAGING` unit on the lane, whatever its serviceability state — `derive.py:44-45`, `routes_plans.py:356-357`.
- **§3.3 (pricing paragraph, line 233)** — *revise* — enumerated the writes that re-run the cost computation (assignment create / release / cancel, detail approve / cancel), gated the write-back on plan `state in {DRAFT, SUBMITTED, APPROVED, ACTIVATED}` with `REJECTED`/`CLOSED`/`SUPERSEDED` keeping their last figures, noted the write-back does not bump the plan's `version` and enforces no ceiling, noted a lane pause into `REASSIGN_PENDING` does *not* trigger it, and noted the cost-summary read always recomputes live — `calc.py:273-287`, `routes_plans.py:203,246,266,310,487,602,610`, `routes_ops.py:633,653`, `cascade.py:176-186,240-265`.
- **§3.9 (`CLEARED` bullet, line 335)** — *revise* — replaced the `X-User-ID == resolving_officer_id` ownership claim (which the implementation does not enforce) with the reason-driven certification gate it actually applies to a `ScreeningOfficer` (`SPECIAL_PROCEDURES` / `ETD_RESOLUTION` / none for `RANDOM`, else `ERR_OFFICER_NOT_CERTIFIED`), and stated a `SupervisoryOfficer` needs no certification — `routes_ops.py:262-267,429-434`.

## Per-edit pre-edit search log

**Edit 1 — `actual_minutes` + DRAFT cost at assignment create**
- (a) Subject: the computed `actual_minutes` field, and the trigger point of the plan cost recompute.
- (b) Enumerated/read: `grep -n "actual_minutes"` across all impl modules -> only `derive.actual_minutes` (definition) and `serial.lane_assignment` (sole projection site, therefore shared by the single read, the list read, and every duty/break/create mutation response); confirmed the field is never persisted on the row (`routes_plans.create_assignment` never sets it, `store.project` injects it); confirmed `max(0, elapsed) - break_minutes_taken` floors *before* subtracting breaks, matching §3.7's existing release wording, and deliberately unlike `calc.officer_duty_ledger`'s `max(0, elapsed - breaks)` which §3.7 already describes separately; checked `cascade.release_assignment` / `close_lane` / `retire_plan_assignments` to confirm every path into `RELEASED` passes through a `CHECKED_IN`/`REASSIGN_PENDING` row so `checked_in_at_utc` is always set.
- (c) Adjustment: added "and also on any row that never checked in" so the second null branch in `derive.actual_minutes` is not contradicted; framed the release as "freezes that same expression simply by fixing `released_at_utc`" instead of claiming a stored snapshot, so §3.7's pre-existing "freezes" prose stays true against a computed-only field.

**Edit 2 — `ADVANCED_IMAGING` certification trigger**
- (a) Subject: what makes the `ADVANCED_IMAGING` certification mandatory on an assignment.
- (b) Enumerated/read: `grep -n "ADVANCED_IMAGING"` across impl -> `derive.lane_has_advanced_imaging` (no state filter, sole definition), its one caller `routes_plans._check_certified:356`, and `consts.REQUIRED_EQUIPMENT_BY_LANE_TYPE["STANDARD"]`. Verified no referral-begin or lane-open path consults the certification rule, and that `create_assignment` does not require the lane to be open — so a `STANDARD` lane with no imaging unit installed genuinely does *not* demand the certification.
- (c) Adjustment: scoped the clause to the *certification* trigger only, so it cannot be misread as touching `consts.REQUIRED_EQUIPMENT_BY_LANE_TYPE` (the `equipment_state` derivation and the lane-open gate, which do care about unit state).

**Edit 3 — cost re-run state gate**
- (a) Subject: when the nine plan-level cost fields are written, cleared, or left alone.
- (b) Enumerated/read: `grep -n "apply_plan_cost\|COST_FIELDS"` -> `calc.apply_plan_cost` (the widened gate), `routes_plans.py:203` submit, `:246` approve, `:266` revise (nulls), `:310` cost-summary (payload only, never persisted), `:487` assignment create, `:602` duty RELEASE, `:610` duty CANCEL, `routes_ops.py:633` detail approve, `:653` detail cancel, plus `create_plan:58-66` (nulls). Also traced every path that changes the cost *input set* without a write-back: `cascade.pause_lane` (`CHECKED_IN -> REASSIGN_PENDING`, excluded from `plan_assignments`, no write-back), `cascade.close_lane` (releases only — `RELEASED` still counted, so result-neutral), `cascade.retire_plan_assignments` / `supersede_other_plans` (cancels, but the plan is `CLOSED`/`SUPERSEDED` by then so the gate excludes it anyway). Confirmed `apply_plan_cost` never calls `store.touch`, so no `version` bump.
- (c) Adjustment: two widenings. Added the explicit "Nor is it triggered by a lane pause...so the stored figures can lag the live computation" clause rather than letting the original blanket phrase "every later write that changes the plan's assignments" over-claim against `pause_lane`; and deferred the cost-cap enforcement points to "the operations §2.8 and §3.4 name" instead of enumerating them, because §2.8 item 30 lists only submission and the detail decision while §3.4 also re-checks at approval (which `routes_plans.py:242` does) — enumerating would have manufactured a contradiction.

**Edit 4 — `CLEARED` outcome gate**
- (a) Subject: the authorisation gates on a `CLEARED` referral resolution.
- (b) Enumerated/read: `routes_ops.resolve_referral:407-467` line by line — role membership, `ERR_FORBIDDEN_ACTION_FOR_ROLE` for a non-`CLEARED` `ScreeningOfficer`, segregation of duties against `detecting_officer_id` (applied to **all four** outcomes), required state, then the `role == "ScreeningOfficer"` certification branch; confirmed **no** comparison of `X-User-ID` to `resolving_officer_id` anywhere in the module, and that a `SupervisoryOfficer` clearing passes no certification check (`_require_supervisor` is only reached for `REFERRED_LEO`/`DENIED_ENTRY`/`WITHDRAWN`); read `CERT_BY_REASON:262-267` for the exact reason->certification map and confirmed `RANDOM` is absent; cross-checked `begin_referral:374-376` uses the same map against the *nominated* officer, which §3.9's begin paragraph already states correctly and which I left untouched; confirmed the observed check order matches §2.8 rungs 6 -> 8 -> 11 -> 15; confirmed §2.8 rung 15 already lists "referral resolution" for `ERR_OFFICER_NOT_CERTIFIED`, so no ladder edit is needed; grepped `test_suite/` for any `resolving_officer_id` ownership assertion — only positive-path field assertions exist (`test_15:76,392`), nothing my wording contradicts.
- (c) Adjustment: kept "on their checkpoint" verbatim on the supervisory clause (pre-existing text, and vacuous in this model since officers carry no checkpoint link) rather than deleting it; softened the nominated-resolver expectation to "is expected to be" instead of dropping it outright, so the sentence records the intent while stating plainly that the enforced gate is the certification check and not the identity comparison.

**Orchestrator verification:** `wc -l -c` -> 467 / 120519; `grep -n '^## '` -> all five top-level sections intact at lines 3/11/177/348/414; `diff PRD.md PRD_FINALIZED.md` -> exactly 8 changed lines (4 removed + 4 added, i.e. the four in-place revisions claimed); tail still ends on the complete `| \`ERR_BAND_NOT_FORECAST\` | 422 |` table row. No truncation.

## Step 9: Complete PRD — pass 1 of 3 (routes_core / routes_staff / infra) — 2026-09-05T16:24:08.321378152Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as THREE sequential, implementation-module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than one whole-implementation scan. Rationale: the implementation is ~3,900 lines across 15 modules, and a single subagent asked to "walk implementation/ exhaustively" at that size reliably under-covers it (the failure signature being a `PRD_COMPLETED.md` nearly identical to its input). Partition: pass 1 = `routes_core.py` + `routes_staff.py` + `req.py`/`app.py`/`envelope.py`/`errors.py`/`consts.py`/`store.py`/`util.py`/`serial.py`; pass 2 = `routes_plans.py` + `calc.py`; pass 3 = `routes_ops.py` + `cascade.py` + `derive.py`. Only pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edit the existing file in place and were explicitly forbidden from recreating it. Each pass may read outside its partition for context but may only edit prose whose subject it owns, and each hands off cross-partition observations to the next.

Pass 1 complete.

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed exactly once; all edits applied to `PRD_COMPLETED.md` only via targeted `Edit` calls.

**File verification:** both files 467 lines; PRD_FINALIZED 120,519 chars -> PRD_COMPLETED 128,032 chars (**+7,513**). `diff` shows 24 changed lines, all inside the intended passages (21, 48-49, 78, 86, 96, 106, 116, 124, 183-193, 197, 201, 267-277, 287, 357, 363). All five `## ` sections survive; file still ends on the `ERR_BAND_NOT_FORECAST` row of §5.

**Counts:** 25 patches across 24 lines — **17 ambiguity-pins**, **8 mismatch-revisions**.

Changes:

- §2.1 — insert — ambiguity — an `X-User-ID` matching no `Officer` row is never `ERR_OFFICER_NOT_FOUND`; treated as matching no officer FK and holding no certifications — routes_core.py:293-304, routes_ops.py:152-159, routes_ops.py:431-433, routes_plans.py:538-541
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics — util.py:19-20
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — envelope.py:9-13
- §2.3 — insert — ambiguity — unparseable/empty `limit`/`offset` is also `ERR_INVALID_REQUEST` — req.py:236-251
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, so `created_at` ties are broken by server creation order — store.py:78-91, store.py:61-62
- §2.5 — insert/revise — ambiguity — enum filters reject undeclared members with `ERR_INVALID_REQUEST` while identifier filters match literally (unknown id => empty page); empty query param = absent; lane `position_index` ties broken by creation order; band `from_utc`/`to_utc` range applies to `band_start_utc` (inclusive/exclusive) — req.py:255-289, routes_core.py:288, routes_staff.py:293-297
- §2.6 — revise — mismatch — the three client percentages are JSON numbers (strings rejected), the two-decimal granularity is *not* enforced, and trailing zeros are lost on the way back (`1.00` -> `1`) — req.py:87-98, store.py:107-110, routes_staff.py:258
- §2.7 — revise — mismatch — a `version` field sent anyway is silently ignored, not rejected; and the checkpoint `version` rule now reads "an equipment report that pauses a lane or moves the posture" (a `SERVICEABLE -> DEGRADED` report bumps nothing) — req.py:170-183, routes_core.py:491-497
- §2.8 rung 3 — insert — ambiguity — explicit JSON `null` = absent; blank/whitespace strings rejected except an equipment `note`; 500-char note ceiling; lenient ISO-8601 instant parsing with canonical echo — req.py:170-183, req.py:60-74, req.py:117-123, util.py:36-58, routes_core.py:472
- §3.1 — revise — mismatch — a create supplying `suspended` true reports `posture` `SUSPENDED`, not `NORMAL` — routes_core.py:152-153
- §3.1 — insert — ambiguity — every accepted checkpoint update bumps `version` once even with an empty/no-op body; a no-op `suspended` set is `ERR_INVALID_STATE_TRANSITION`; capacities/thresholds may be lowered below what is in use without revisiting referrals, counters or tickets — routes_core.py:165-206
- §3.1 — insert — ambiguity — lane `secondary_positions` is informational (the gate reads the checkpoint's `secondary_slot_capacity`); creating a lane re-derives posture to `ELEVATED` until equipment is installed, and neither lane creation nor equipment installation ever auto-raises a ticket — routes_core.py:256-257, routes_core.py:441-443, routes_ops.py:390
- §3.1 — revise — mismatch — equipment `serial_number` uniqueness is *not* enforced — routes_core.py:423-444
- §3.1 — revise — mismatch — lane `equipment_state` `DEGRADED` derivation is best-unit-per-type then worst-across-types, so a healthy duplicate masks a degraded unit — derive.py:24-35
- §3.1 — revise — mismatch — show-up curve `name` uniqueness is *not* enforced; plus error-code split: window start <= end => `ERR_INVALID_REQUEST` (before the histogram), bucket start <= end => `ERR_CURVE_BUCKETS_INVALID`, malformed bucket keys/types => `ERR_INVALID_REQUEST`, `share_pct` need not be integral — routes_core.py:70-89, routes_core.py:50-67, req.py:147-167
- §3.1 — insert — ambiguity — `buckets` are echoed in the order supplied — req.py:160-167
- §3.2 — insert — ambiguity — a flight's `carrier_type` is never matched against the referenced curve's `carrier_type`/`season_code` — routes_staff.py:160-181, calc.py:38-76
- §3.2 — insert — ambiguity — `band_start_utc` misalignment is judged at the shape stage and therefore outranks the `checkpoint_id` FK check — routes_staff.py:244-246
- §3.6 — insert — ambiguity — the calibration test consults only the required-type units in `SERVICEABLE`/`DEGRADED` condition (never an OOS unit, never `ETD`/`CT`) — routes_core.py:316-335
- §3.6 — revise — mismatch — the reopen recall applies only to `REASSIGN_PENDING` rows whose owning plan is still `ACTIVATED` — cascade.py:204-215
- §3.6 — insert — ambiguity — closing without a reason code retains the lane's existing `paused_reason_code` — cascade.py:189-194, routes_core.py:398
- §3.6 — revise — ambiguity — each equipment report rewrites `last_state_note` outright, clearing it when the note is omitted; 500-char ceiling — routes_core.py:472, routes_core.py:489
- §3.6 — revise — mismatch — a posture-degradation ticket always carries a non-null `published_wait_minutes_at_raise`, because no ticket is raised at all without a qualifying standard-queue snapshot — cascade.py:60-78
- §3.7 — insert — ambiguity — `ON_BREAK` is not a legal *source* for the duty-status operation either — routes_staff.py:83-89
- §4 table — revise — mismatch — `/checkpoints` row notes the `SUSPENDED` create case; `/lanes/{id}/open` row now says required equipment must be `SERVICEABLE` **or** `DEGRADED` (was "SERVICEABLE") — routes_core.py:316-330

**Left for later passes (noticed, not touched):**
- **Pass 3, important:** §3.8 (line 315) still says a posture-degradation ticket "may carry a null `published_wait_minutes_at_raise` when the publication window was empty" — false in `cascade.py:60-78` (the ticket is suppressed entirely). Pass 1 fixed the parallel sentence in §3.6; this one needs the same fix or the document self-contradicts.
- Pass 2/3: `derive.evaluate_all_breaks()` runs system-wide (every assignment, not just the subject's) on `GET /officers/{id}/duty-ledger` (routes_staff.py:124) and `GET /lane-assignments` (routes_plans.py:510); §3.7's break-due wording is only loosely compatible.
- Pass 2: `calc.apply_plan_cost` write-back gate (`calc.py:283`) and `officer_duty_ledger`'s `extra_minutes` hooks (`calc.py:137`).
- Pass 3: `resolution_note` is capped at 500 chars and rejects blank strings on both the escalation-resolve and referral-resolve bodies (routes_ops.py:188, routes_ops.py:401) — unpinned in §3.8/§3.9.
- Unowned by any pass: `app.py:37-49` maps an unknown path to `ERR_NOT_FOUND` (404) and a wrong method to `ERR_INVALID_REQUEST` (400); neither identifier appears in the §5 catalogue. Pass 1 left §5 alone rather than add rows.

## Step 9: Complete PRD — pass 2 of 3 (routes_plans / calc) — 2026-09-05T16:43:29.89955816Z

PASS 2 complete.

## Integrity confirmation

- No `cp`, recreate, truncate or overwrite of `PRD_COMPLETED.md`. Every change was a targeted `Edit`.
- Baseline observed on entry: **467 lines / 128,032 chars** (exactly the predicted pass-1 state).
- Exit state: **467 lines / 133,760 chars** -> **+5,728 chars, +0 lines**.
- Structural verification: all five `^## ` sections present (lines 3, 11, 177, 348, 414); tail still ends on `| ERR_BAND_NOT_FORECAST | 422 |`; `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields **41 changed lines, all `NcN` single-line substitutions** — zero `a`/`d` hunks, so no line was inserted or lost and pass 1's ~22 lines are untouched.

## Counts

22 `Edit` calls -> **26 textual changes: 20 ambiguity-pins, 6 mismatch-revisions.**

## Changes

- §2.1 — revise — mismatch — supervisory release carve-out no longer claims a checkpoint restriction; now states the comparison is skipped entirely and any assignment may be released, because an `Officer` row carries no checkpoint FK — `routes_plans.py:562`
- §2.5 — insert — ambiguity — an unparseable date/instant filter value is `ERR_VALIDATION` like other malformed filters — `req.py:266`
- §2.7 — insert — ambiguity — `expected_checkpoint_version` must be an integer >= 0; non-integer/negative is `ERR_INVALID_REQUEST` at the shape stage, before the version comparison — `routes_plans.py:37`
- §2.8 rung 29 — revise — mismatch — added plan submission and plan decision to the `ERR_OVERTIME_CAP_EXCEEDED` site list — `routes_plans.py:199,241`
- §2.8 rung 30 — revise — mismatch — added the plan decision to the `ERR_PLAN_COST_CAP_EXCEEDED` site list — `routes_plans.py:242`
- §3.3 — insert — ambiguity — assignment-creation FK resolution order pinned to declaration order (rung 5) — `routes_plans.py:436`
- §3.3 — revise — mismatch — pinned that the owning plan's `state` is **not** a gate: an assignment may be created against a plan in any state — `routes_plans.py:436-488`
- §3.3 — insert — ambiguity — two `ERR_INVALID_STATE_TRANSITION` gates (`SEPARATED` officer, `DECOMMISSIONED` lane) precede certification — `routes_plans.py:451,457`
- §3.3 — insert — ambiguity — band whose exclusive `band_end_utc` lands on the following midnight is inside the operational day — `routes_plans.py:466`
- §3.3 — insert — ambiguity — rest buffer is symmetric, not forward-looking: touching/overlapping intervals merge into maximal runs and the containing run's span must not exceed 60 min — `routes_plans.py:380-400`
- §3.3 — insert — ambiguity — creation overtime gate evaluated as though the row existed (band's 30 `planned_minutes` added before the regular/overtime split) — `routes_plans.py:581`
- §3.3 — insert — ambiguity — on submit, cost is computed end-to-end and both fiscal gates (per-officer overtime cap, then `plan_cost_cap_cents`) applied before any write — `routes_plans.py:199-200`
- §3.3 — revise — mismatch — write-back trigger list narrowed to client writes only (assignment creation, that assignment's own release/cancellation, surge-detail approval/cancellation) and explicitly excludes system-driven movement (lane pause/close, plan close/supersede) — `calc.py:283`, `cascade.py`
- §3.3 — insert — ambiguity — `officer_breakdown` entry field list in ascending `badge_number` order; empty plan reads back zero in all eight integers with `admin_fee_rate` `0.060` and an empty breakdown while the row keeps its creation nulls — `calc.py:227-237,252`
- §3.4 — insert — ambiguity — a conditional `rejection_reason_code` mistake is judged at the shape stage, ahead of the plan's existence check — `routes_plans.py:225`
- §3.4 — insert — ambiguity — both decision gates read a **fresh** cost run, not the submitted figures, and that run's nine figures are written back — `routes_plans.py:241-242`
- §3.7 — revise — mismatch — check-in calibration examines every required unit whatever its serviceability, so an `OUT_OF_SERVICE` required unit masked by a serviceable sibling still blocks check-in (unlike §3.6's lane-open gate) — `routes_plans.py:545`
- §3.7 — revise — mismatch — check-in overtime gate is measured on the **forward-looking planned** ledger variant, not the chronological-actual one, and already counts this `SCHEDULED` row's `planned_minutes` — `routes_plans.py:581`, `calc.py:150-152`
- §3.7 — insert — ambiguity — an officer already `ON_DUTY` or `ON_BREAK` elsewhere keeps their `duty_status`; only `OFF_DUTY -> ON_DUTY` bumps the officer's `version` — `routes_plans.py:591`
- §3.7 — revise — mismatch — supervisory release skips the ownership comparison entirely; neither release nor cancellation touches the officer's `duty_status`/`version` even at zero committed minutes — `routes_plans.py:562`
- §3.7 — insert — ambiguity — break-due evaluation leaves `version`/`updated_at` alone (re-derivation, not mutation) — `derive`/`serial.py:43`
- §3.7 — insert — ambiguity — the lane-assignment collection read evaluates breaks system-wide and **before** the `break_state` filter, so a row coming due on that request is matched by `break_state=DUE` — `routes_plans.py:510-511`
- §3.8 — insert — ambiguity — empty window still reports `breached` false with `threshold_minutes` and both window instants — `calc.py:314-326`
- §3.8 — insert — ambiguity — under the `<3`-sample fallback, `sample_count` still reports every sample in the window, not the one consumed — `calc.py:319,327`
- §3.9 — insert — ambiguity — `band_results` entry field list, one entry per walked band in chronological order — `calc.py:382-391`

## Pass 1 sentences corrected

Two, both the same defect: §2.1 and §3.7 asserted a `SupervisoryOfficer` may release only assignments "whose lane belongs to their own checkpoint" / "on a lane of their checkpoint". `routes_plans.py:562` skips the ownership comparison unconditionally for supervisory releases, and `routes_staff.py`'s `OFFICER_SPEC` gives `Officer` rows no checkpoint FK, so the qualification is not merely unimplemented — it is unimplementable. Both sentences now say the comparison is skipped altogether. (These lines existed in `PRD_FINALIZED.md` too, so the wording predates pass 1; noted because they fall on pass-1-owned §2.1 auth prose.)

## Deliberately not patched

`consts.REST_BUFFER_MINUTES = 15` is dead code — the impl only requires a non-touching gap, so the PRD's "fifteen minutes" is not literally enforced. But `routes_staff.py` forces `band_start_utc` onto :00/:30 with zero seconds, making the minimum non-touching gap 30 minutes >= 15, so the divergence is unobservable. Per the minimal-change rule the sentence was left and only the run-symmetry clause added.

## Left for pass 3

- `cascade.retire_plan_assignments` ends an `ON_BREAK` break before releasing during a **supersede**; §3.4's supersede link is silent on this (its close paragraph does document the analogous behavior).
- `derive.py` internals of `evaluate_break_due` / `evaluate_all_breaks` — pass 2 only pinned what the §3.7 collection read observably does, in deliberately under-determined wording.

## Step 9: Complete PRD — pass 3 of 3 (routes_ops / cascade / derive) — 2026-09-05T17:13:22.31738547Z

Pass 3 complete. Final report:

## No-overwrite confirmation
No `cp`, no `Write`, no truncation. `workspace/PRD_COMPLETED.md` was edited exclusively with targeted `Edit` calls. Baseline on entry: **467 lines / 133,760 chars** (51 patches from passes 1-2 all intact — every line they changed is still changed).

## Counts
- Entry: 467 lines / 133,760 chars -> **Exit: 467 lines / 145,939 chars** (+12,179 chars, +0 lines)
- Final vs `PRD_FINALIZED.md` (467 lines / 120,519 chars): **+25,420 chars, 71 lines changed across all three passes**, every hunk a 1:1 in-place substitution (67 `c` hunks, 71 removed / 71 added, zero `a`/`d` hunks — no line lost or created)
- This pass: **39 `Edit` calls over 34 lines** — **29 ambiguity-pins**, **10 mismatch-revisions**

## Changes (this pass)
- §2.1 — revise — mismatch — SoD "applies to two operations" -> four, adding the surge-detail decision and the referral begin (rule displaced onto the nominated officer) — `routes_ops.py:583`, `:345`
- §2.5 — insert — ambiguity — the two body-FK-before-path-FK exceptions (escalation resolve, referral begin) — `routes_ops.py:207-208`, `:342-343`
- §2.8 rung 5 — revise — mismatch — "referral resolution" -> "referral begin"; referral resolution carries no body FK — `routes_ops.py:399-402`
- §2.8 rung 8 — insert — ambiguity — SoD sites include referral begin and referral resolution — `routes_ops.py:345`, `:418`
- §2.8 rung 10 — insert — ambiguity — referral begin gated on suspension, referral resolution deliberately not — `routes_ops.py:352` vs `:407-467`
- §2.8 rung 16 — insert — ambiguity — ALARM/ETD equipment rung evaluated ahead of rung 15 on begin — `routes_ops.py:363-376`
- §2.8 rung 18 — insert — ambiguity — supervisor-certification sites enumerated — `routes_ops.py:171`, `:211`, `:378`, `:436`, `:440`
- §2.10 (posture) — insert — ambiguity — derivation recomputed on every projection, so a read reports live posture/counters with no `version` move — `derive.py:100-116`, `serial.py:7-9`
- §2.10 (versioning) — insert — ambiguity — checkpoint bumped once per request; officer bumped once per duty transition (twice on a lane close) — `cascade.py:22-35`
- §3.4 — insert — ambiguity — supersede ends an `ON_BREAK` break before releasing — `cascade.py:240-249`, `:131-145`
- §3.5 (request) — insert — ambiguity — `SEPARATED` refusal; plan state not a gate; window ending exactly at midnight accepted — `routes_ops.py:510-518`
- §3.5 (decision) — insert — ambiguity — `denial_reason_code` forbidden on approve, both shape faults judged before the detail's existence — `routes_ops.py:578-582`
- §3.5 (approval) — insert — ambiguity — overtime gate measured on `FORWARD_LOOKING_PLANNED` + `extra_detail_minutes`, strictly-greater breach, both gates pre-write — `routes_ops.py:606-622`
- §3.5 (denial) — insert — ambiguity — records `decided_by_user_id`, still bumps officer `version` — `routes_ops.py:592-596`
- §3.5 (cancel) — insert — ambiguity — `decided_by_user_id`/`decided_at_utc` retained; no SoD comparison; no fiscal re-check — `routes_ops.py:637-654`
- §3.6 (reopen) — insert — ambiguity — recall rewinds neither `checked_in_at_utc` nor `break_state`; no `duty_status` move — `cascade.py:204-215`
- §3.6 (lane close) — revise — mismatch — full break-end mechanics plus `ON_DUTY->OFF_DUTY` retirement, for both close-from-`OPEN` and close-from-`PAUSED` — `cascade.py:189-201`
- §3.7 (line 287) — revise — mismatch — a **lane close** also retires officers; `APPROVED` detail minutes block the stand-down; a pause never stands anyone down — `cascade.py:201`, `derive.py:133-139`
- §3.7 (line 295) — revise — mismatch — supersede added to the release list; break ended first in all cases; stand-down at zero — `cascade.py:240-249`
- §3.7 (line 297) — insert — ambiguity — the duty-ledger read runs the system-wide break sweep; all other single-row paths evaluate one row — `derive.py:178-180`
- §3.8 (publication read) — insert — ambiguity — `lane_type` is a **required** query param, reported ahead of the path checkpoint — `routes_ops.py:111-112`
- §3.8 (observation) — insert — ambiguity — posting re-derives posture with **no** settlement, so a new breach ticket never auto-raises a `POSTURE_DEGRADATION` ticket — `routes_ops.py:72-76` vs `cascade.py:102-109`
- §3.8 (ticket creation) — **revise — mismatch** — the flagged self-contradiction: `published_wait_minutes_at_raise` is **never** null on any ticket; plus an `ALL`-scope ticket can never be resolved via `LANE_OPENED`; plus the null-field creation shape — `cascade.py:60-99`, `routes_ops.py:215-220`
- §3.8 (acknowledge) — insert — ambiguity — `ERR_SUPERVISOR_CERTIFICATION_REQUIRED` judged after the state check; checkpoint untouched — `routes_ops.py:163-176`
- §3.8 (resolve intro) — insert — ambiguity — supervisor certification also required (after state); `resolution_note` <=500, non-blank, null when omitted; branch-shape faults precede the ticket's existence — `routes_ops.py:188`, `:195-211`
- §3.8 (resolve counters) — revise — mismatch — an `ALL`-scope ticket resets **both** queue counters — `routes_ops.py:232-236`
- §3.8 (expiry) — revise — mismatch — expiry is scoped to the ticket whose `lane_type_scope` equals the sampled queue; the counter resets regardless; at most one candidate — `cascade.py:289-302`
- §3.9 (creation) — insert — ambiguity — raising is never refused for capacity (so `secondary_slots_in_use` may sit at/above capacity) and does not bump the checkpoint's `version` — `routes_ops.py:270-298`
- §3.9 (begin, role) — **revise — mismatch** — `SUPERVISOR` certification required **only** when `requires_private_screening`; SoD falls on the nominated officer and is judged before suspension and state; non-`ON_DUTY` nominee is `ERR_INVALID_STATE_TRANSITION` — `routes_ops.py:340-359`, `:377-378`
- §3.9 (begin, gates) — insert — ambiguity — ETD shortfall is `ERR_LANE_EQUIPMENT_UNAVAILABLE` ahead of the certification; a non-`OPEN` lane is `ERR_INVALID_STATE_TRANSITION`, **not** `ERR_LANE_NOT_OPEN`; suspension tested early — `routes_ops.py:352`, `:360-376`
- §3.9 (begin, capacity) — insert — ambiguity — capacity is the last gate, after the private-screening check; checkpoint `version` unmoved — `routes_ops.py:379-395`
- §3.9 (resolve intro) — insert — ambiguity — `resolution_note` <=500 non-blank; its conditional requirement is judged **last**, behind role-value, SoD, state, certification and supervisor gates; every outcome bumps the checkpoint once and re-derives posture — `routes_ops.py:401`, `:413-467`
- §3.9 (`CLEARED` bullet) — revise — mismatch — dropped the stale "any referral **on their checkpoint**" scoping (officers carry no checkpoint FK) — `routes_ops.py:429-434`
- §3.9 (`REFERRED_LEO` bullet) — insert — ambiguity — the pause leg fires only if the lane is still `OPEN`; otherwise silently skipped, reason code not overwritten — `routes_ops.py:458-464`
- §4 `/checkpoints/{id}/wait-time` — insert — ambiguity — `lane_type` marked required — `routes_ops.py:111`
- §4 escalation-ticket read — revise — mismatch — tickets arise from **two** routes, not only the wait-observation cascade — `cascade.py:102-109`
- §4 referral resolve — revise — mismatch — `WITHDRAWN` also requires the `SUPERVISOR` certification — `routes_ops.py:439-440`

## Consistency sweep
- **§3.8 flagged item resolved**: the "may carry a null `published_wait_minutes_at_raise`" sentence is gone; §3.8 now agrees with §3.6 line 277 that no posture-degradation ticket exists without a qualifying standard-queue snapshot.
- §3.9 begin vs §4 row 405: the unconditional-`SUPERVISOR` contradiction is gone; §3.9 now matches the row's `requires_private_screening` wording.
- §3.9 `WITHDRAWN` bullet vs §4 row 406: reconciled (row was wrong).
- §3.8 ticket-origin sentence vs §4 row 398: reconciled (row was wrong).
- §2.8 rungs 5/8/10/15/16/18 re-checked against every ops guard order — consistent. §2.x line 96 already pins all list filters (`lane_type_scope`, referral `state`/`referral_reason`, observation `measurement_method`), so the abbreviated §4 list rows are summaries, not contradictions — left alone.
- §2.10 line 169 posture ladder verified verbatim against `derive.posture`; line 189 `equipment_state` derivation and line 163 `committed_duty_minutes` verified verbatim against `derive.py` — no change needed.
- §2.10 line 173's "posture up ... may auto-raise a ticket" is scoped to the equipment chain, so it does not clash with the new §3.8 statement. Wording deliberately softened from "belongs to the equipment-report path and no other operation" to "only an operation that performs the posture *settlement* can reach it, and in practice the equipment-fault chain is the only route that ever does" — `cascade.settle_posture` has five call sites (`routes_core.py:205,343,403,495`, `routes_ops.py:466`) but only the equipment report can actually produce a `NORMAL -> ELEVATED` move.

## Earlier-pass sentences corrected
- §3.7 line 287 and line 295 (pass 1/2 text): both claimed the system-driven stand-down/release set excluded a lane close or a supersede; `cascade.close_lane` calls `settle_officer(..., retire=True)` (`cascade.py:201`) and `retire_plan_assignments` runs on supersede (`cascade.py:265`).
- §3.9 line 335 (untouched original): removed "any referral **on their checkpoint**" — same stale officer-checkpoint scoping pass 2 stripped from §2.1/§3.7. No checkpoint-scoping claim for officers now remains anywhere (`grep` for "on their checkpoint" returns nothing).
- §5 catalogue left untouched, as pass 1 directed — no genuine mismatch surfaced in the pass-3 modules.

## Structural verification
```
467 145939 PRD_COMPLETED.md          (PRD_FINALIZED.md: 467 120519)
3:## 1. Introduction
11:## 2. Global Specifications & System-Wide Principles
177:## 3. Business Logic & Workflows
348:## 4. Endpoint Definitions
414:## 5. Error Code Catalogue
diff PRD_FINALIZED.md PRD_COMPLETED.md -> 71 removed / 71 added, 67 substitution hunks, 0 add/delete hunks
tail -> | `ERR_BAND_NOT_FORECAST` | 422 |
```
All five sections survive, line count is unchanged at 467, every hunk is an in-place substitution, and the file still ends on the `ERR_BAND_NOT_FORECAST` row. The document is final.

---

## Pipeline complete — orchestrator final verification — see timestamp above

Step 9 aggregate across the three passes: **90 patches — 66 ambiguity-pins, 24 mismatch-revisions** (pass 1: 25 = 17+8; pass 2: 26 = 20+6; pass 3: 39 = 29+10).

Independently re-verified by the orchestrator after pass 3:
- `wc -l -c workspace/PRD_COMPLETED.md` -> 467 / 145,939. All five `^## ` headings present at lines 3/11/177/348/414. Tail is the complete `| \`ERR_BAND_NOT_FORECAST\` | 422 |` row — no truncation.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs**, and `diff | grep -c '^[<>]'` -> 142 (71 removed + 71 added). The Step 9 scan demonstrably ran; `PRD_COMPLETED.md` is not a byte-identical copy of its input.
- Leak check across all three PRDs (`PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`) for "harder than expert", "SCAFFOLD", "test_recipe", "scaffold_" -> **0 hits in all three**. The difficulty directive never reached the PRD lineage, and no scaffold-internal vocabulary leaked.
- `workspace/implementation/` mtimes: newest source file is `calc.py` at 15:40 (Step 7's single implementation fix); every other module is 14:11-14:33. The green sweep's `results.*.json` are all 15:45. So the implementation has been frozen since before the passing sweep, and Steps 8 and 9 edited documentation only — the 8x 111/111 result remains valid evidence for the shipped code.
- `find` for stray worklogs -> exactly one, at the task root. No `workspace/worklog.md` drift.

Final artifact set: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (17 files, 111 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, sweep.sh, implementation/}` with `results.{1..8}.json` all reporting 111/111.
