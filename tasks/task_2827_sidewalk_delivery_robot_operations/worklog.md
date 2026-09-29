# Worklog — task_2827_sidewalk_delivery_robot_operations

## Step 1: Create task directory — 2026-09-05T02:59:47.116Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations` and its `workspace/` subdirectory. Index 2827 was pre-assigned by the orchestrating invocation (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T04:54:00.000Z

Subagent summary (verbatim):

Scaffold generation for task 2827 is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations/` and nothing outside that directory was created or modified.

## SCAFFOLD.yaml — 3815 lines (186 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations/SCAFFOLD.yaml`
- §1.0 profile: `expert_plus`, primary archetype `graph_constraint`, secondary `temporal_windowing`, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, cyclic state machines, `segregation_of_duties`, immediate consistency.
- §1.1: **12 entities**, 151 fields (ServiceZone, SidewalkSegment, SegmentClosure, Merchant, Robot, DepotBay, BayReservation, DeliveryOrder, DeliveryMission, RoutePlan, InterventionEvent, IncidentReport).
- §1.2: **12 state-machine blocks / 78 transitions**; §1.2.1: **3 concurrency rules** (OCC on Robot, DeliveryMission, DepotBay).
- §1.3: **12 calculations** (fee quote dual-variant, blockage-credit settlement with a 40% cap, remedy waterfall + inclusive budget gate, plan geometry/derated duration, clearance margin, crossing risk score, zone economics pipeline, intervention rate thresholds, lid-code derivation).
- §1.4: **65 validations** (priority-ordered); §1.5: **53 endpoints** (25 GET / 28 POST); §1.6: **48 error rows**; §1.7: **6 roles**.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2679 lines (171 KB)
Single top-level key `scaffold_difficulty_design`. **9 rules / 23 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

## SCAFFOLD_CORNER_DESIGN.yaml — 6891 lines (444 KB)
Single top-level key `scaffold_corner_design`. **9 sections / 96 instances = 68 with full `test_recipe` + 28 `excluded_because` stubs** pointing at the §1.8 instance that already covers them: entities 15 (14/1), state_machines 19 (13/6), calculations 13 (6/7), validations 18 (14/4), endpoints 8 (6/2), errors 6 (4/2), rbac 5 (4/1), cross_cutting_complexity_layers 7 (4/3), consistency_model 5 (3/2).

## Verification
`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2827_sidewalk_delivery_robot_operations`:

```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1915

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional checks: SCAFFOLD.yaml contains neither design key (confirmed programmatically); a custom walker over every instance's `setup_api_calls` → `trigger` reported **0 unbound `${var}` references** and **0 duplicate instance names** across both design files; all 28 stub `difficulty_instance` targets resolve to real §1.8 instance names; every OCC `expected_*_version` is a captured variable, never a literal.

## One flag for the caller (not changed by me)
`SCAFFOLD.yaml`'s `scenario:` value still begins with the verbatim line `Generate task harder than expert level!`, because the scenario text was required to be used verbatim. Per the known `prd-bench-difficulty-directive-leaks-via-scaffold` failure mode, that line reaches PRD.md through the scenario key and should be stripped after Step 2, before PRD generation.

### Orchestrator post-step action (difficulty-directive leak)
Confirmed the leak the subagent flagged: `SCAFFOLD.yaml:2` carried the verbatim line `Generate task harder than expert level!` inside the `scenario:` block, and line 31 repeated it in a `difficulty_level` comment. Both were stripped by the orchestrator before Step 4 (backup at `/tmp/task2827_scaffold_prestrip.yaml`). `grep -rn "harder than expert"` over the task dir is now clean; `yaml.safe_load` still parses SCAFFOLD.yaml. SCAFFOLD.yaml is now 3813 lines.

## Step 3: Copy shared files — 2026-09-05T04:55:13.705Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_2827_sidewalk_delivery_robot_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T05:17:00.000Z

Subagent summary (verbatim):

The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations/workspace/PRD.md`

**Line count: 445**

**Section list (25 headings)**
- `## 1. Introduction`
- `## 2.` Global behaviour — 2.1 Roles & Authorization (RBAC), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, confirmed by substring match), 2.3 Pagination & List Ordering, 2.4 Common Properties / Timestamps / Logical Clock, 2.5 Optimistic Concurrency & Parent Version Pinning, 2.6 Numeric Precision & Rounding, 2.7 Ordinance & Accessibility Envelope, 2.8 Conserved Quantities, Mirrors & Cascade Discipline, 2.9 Path Identifiers & Reverse Lookups, 2.10 The Rejection Ladder
- `## 3.` Domain behaviour — 3.1 Zone Mapping & Permitting, 3.2 Closures & the Five-Link Reroute Cascade, 3.3 Merchant Integration, Order Intake & Fee Quote, 3.4 Fleet Registration, Duty Cycle & Depot Bay Capacity, 3.5 Robot Health, Telemetry & Autonomy Index, 3.6 Dispatch & Route Planning, 3.7 The Delivery Run, 3.8 Delivery Exceptions & the Customer Remedy Waterfall, 3.9 Incident Reporting & Zone Unit Economics
- `## 4. Endpoint Definitions` — 4 columns (Method, Path, Description, Authorized Role(s)), 53 data rows
- `## 5. Error Code Catalogue` — 2 columns (Error ID, HTTP Status Code), 48 data rows

**Hard Contracts**
- Contract 1 Field-Name Coverage: **PASS** — 163/163 identifiers (every `entities[].fields[].name`, every endpoint `input`/query/body identifier with `?` stripped, every `{path_param}`, plus `id`/`created_at`/`updated_at`/`version`) appear verbatim in backticks; MISSING = []. (Initial scan false-negatived on all 163 because §2.2's ```json fences desynchronize naive backtick pairing; stripping fenced blocks before matching resolved it.)
- Contract 2 Rule Coverage: **PASS** — all 78 transition action tokens present, all 48 error ids present, all enum literals present, all 12 calculations expressed in operator-free reconstructable prose, all 65 validation rules represented with ladder ordering in §2.10.
- Contract 3 §3 Path Purity: **PASS** — zero backticked tokens in §3 that start with `/`, are a bare HTTP method, or combine method+path; also no unticked bare collection paths. Paths appear only in §2.5 (allowed) and the §4 table.

**Fixes made during verification:** zone permit actions were wrong (`GRANT`/`REINSTATE` → the scaffold's actual `ACTIVATE_PERMIT`/`LIFT_RESTRICTION`) in both §3.1 and the §4 row; two validation rules lacked explicit error attribution and got it (segment sequence well-formedness → `ERR_INVALID_REQUEST` / `ERR_SEGMENT_NOT_FOUND` in §3.6; null `exception_reason` on a remedy → `ERR_INVALID_STATE_TRANSITION` in §3.8).

**Forbidden-content scan clean:** no "harder than expert" or any difficulty directive, no fuzzy adverbs, no pseudocode/operator syntax.

**Truncation guard honoured:** built as 1 `Write` + 7 heredoc appends (~300 lines max each), with `wc -l` and `tail -3` after every append. `tail -20` ends on the completed final row of the §5 table — a clean section boundary, not mid-sentence. Verbatim last 3 lines:

```
| ERR_NO_ELIGIBLE_ROBOT | 422 |
| ERR_BAY_TYPE_MISMATCH | 422 |
| ERR_REMEDY_BUDGET_EXCEEDED | 402 |
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

### Orchestrator truncation verification
Independently confirmed: `wc -l` = 445, `tail -12` ends on the completed final table row `| ERR_REMEDY_BUDGET_EXCEEDED | 402 |` (clean section boundary, not mid-sentence). `grep -in "harder than expert|expert_plus|scaffold_difficulty|test_recipe"` over PRD.md → clean. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T06:03:00.000Z

Subagent summary (verbatim):

Implementation complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations/workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` | 11 |
| `requirements.txt` | 1 (`flask==3.0.3`) |
| `app.py` | 77 |
| `db.py` | 138 |
| `errors.py` | 82 |
| `response.py` | 43 |
| `middleware.py` | 244 |
| `common.py` | 45 |
| `calc.py` | 465 |
| `cascades.py` | 292 |
| `routes/__init__.py` | 0 |
| `routes/clock.py` | 18 |
| `routes/zones.py` | 195 |
| `routes/segments.py` | 212 |
| `routes/closures.py` | 198 |
| `routes/merchants.py` | 119 |
| `routes/robots.py` | 292 |
| `routes/bays.py` | 240 |
| `routes/orders.py` | 226 |
| `routes/missions.py` | 393 |
| `routes/plans.py` | 233 |
| `routes/interventions.py` | 179 |
| `routes/incidents.py` | 209 |
| **total** | **3912** |

No `__pycache__` left behind; nothing else on disk.

## Endpoints: 53 / 53

`app.url_map` enumerates exactly 53 method+rule pairs, matching the PRD. Collections live at the URL root (`api_prefix: ""`): `/_clock/set_current_utc` (1), `/service-zones` (5, incl. `/economics` and `/permit-transitions`), `/sidewalk-segments` (4), `/segment-closures` (4), `/merchants` (4), `/robots` (6, incl. `duty-transitions`, `health-transitions`, `telemetry`), `/depot-bays` (3), `/bay-reservations` (4), `/delivery-orders` (5, incl. `/cancel`, `/remedy`), `/delivery-missions` (5, incl. `/load`), `/route-plans` (4), `/intervention-events` (4), `/incident-reports` (4).

## The 12 calculations

All centralised in `calc.py`, each with its constants pinned as module-level `Decimal`s directly above it, and every rounding done through `rhu`/`rhu_int` (ROUND_HALF_UP), `ceil_div`, or `floor_dec` — never builtin `round()`, never `float` arithmetic on money:

1. `payload_tier` — 15/30/45 L bands
2. `urgency_flag` — 45-minute promise window
3. `delivery_fee` / `quote_at_order` — base 349 + tier + urgency + crossings, then grade discount
4. `settlement_at_completion` — same ladder plus intervention surcharge and the blockage credit capped at 40 %, reusing the order's *frozen* tier/urgency
5. `rolling_autonomy_index` — 5-mission window, 0.85 decay, clamped 40–100
6. `lifetime_autonomy_index` — same penalties over lifetime counters
7. `crossing_risk_score` — sightline term + control adjustment + flow (capped 28) + grade coefficient + ramp credit
8. `route_clearance_margin` — narrowest segment minus robot width minus the 12 cm buffer
9. `planned_duration_min` — length ÷ (max speed × 0.6 derate), ROUND_CEILING
10. `takeover_mandatory` — confidence vs the zone threshold
11. `customer_remedy_amount` — policy table with the 15000 declared-value cap
12. `zone_economics` — utilization, allocated overhead, variable cost, cost/contribution per delivery, throughput per robot-hour

Plus supporting helpers `window_minutes`, `eligible_robots`/`selector_rank`, `abort_reason_to_exception`.

## The 3 OCC rules

All three pin a **parent** row's version, checked immediately after existence resolution and before any state/business gate, so a stale pin always wins over a 409 from a downstream rule:

- `POST /bay-reservations` — `expected_depot_bay_version` vs `bay.version` → `ERR_STALE_BAY_VERSION` (`routes/bays.py`)
- `POST /delivery-missions` — `expected_delivery_order_version` vs `order.version` → `ERR_STALE_ORDER_VERSION` (`routes/missions.py:97`)
- `POST /route-plans` — `expected_delivery_mission_version` vs `mission.version` → `ERR_STALE_MISSION_VERSION` (`routes/plans.py:92`)

Versions are bumped through `db.bump()`, which keys off `id(row)` in `flask.g` so a multi-row cascade bumps each touched row exactly once per request.

## Smoke test

Launched via `PORT=39828 bash start.sh` (foreground `exec`, bound `0.0.0.0`), then:

- All 12 collections returned `total_count 0` on a fresh boot — **no seeded data anywhere**.
- `POST /service-zones` → 201 with the §2.2 envelope (`meta.api_request_id` `req_` + 20 chars, `api_request_timestamp`, `response_type: "object"`, `data` with `id`/`created_at`/`updated_at`/`version: 1`); `created_at` came from the logical clock default `2026-08-01T00:00:00.000Z`, not wall clock.
- `401 ERR_UNAUTHENTICATED` with no role header, `403` for a role outside the writer set, `404 ERR_ZONE_NOT_FOUND` for a missing id, all in the same envelope.
- Full happy path **over real HTTP** through `start.sh` (order → dispatch → plan → validate → activate → load → depart → arrive → complete → settle → reservation → economics → incident) produced byte-identical numbers to the in-process run: quote 955, settlement 733, clearance margin 68.0, duration 4 min, lid `100001`, active_minutes 20, merchant buckets escrowed 0 / recognized 955 / released 0 / variance -222, bay ledger 60 -> 0, economics `utilization 3.3 / overhead 40450 / variable 36 / cost 40486 / contribution -39753 / throughput 0.1`, incident due +72 h.
- Cascade suite passes: symmetric segment closure, the 5-link closure cascade, REDELIVER money reversal, second-remedy 409, LIFT, abort fan-out, and the 4-link tamper quarantine with its auto-filed `SYSTEM` DRAFT SERIOUS incident blocking `CLEAR`.
- **Restart wipes state**: killed the PID, re-ran `bash start.sh`, and `service-zones`/`delivery-orders` were both back to `total_count 0`.

One fix made this pass: `cascades.order_to_exception` now also accepts an order in `RECEIVED` (in addition to `DISPATCHED`/`IN_TRANSIT`), so aborting a mission whose order was already remedied via REDELIVER correctly re-enters `EXCEPTION` and moves the escrow; terminal and already-`EXCEPTION` orders are still guarded so the merchant fee ledger can never be double-moved.

Process hygiene: every server was killed by its exact PID (verified via `ss -lntp`); both test ports are free and no other pipeline's `python3 app.py` was touched. No broad `pkill` was ever run. All scratch files stayed under `/tmp/task2827impl/`, and `worklog.md` was not modified.

## Step 5: Generate Unit Tests — 2026-09-05T07:10:00.000Z

(Launched concurrently with Step 6 in a single assistant message, so the implementation generator had physical isolation from `test_suite/` — that directory did not exist when Step 6 started. Step 6 finished first and is logged above; Step 5's entry follows.)

Subagent summary (verbatim):

Generation is complete. Both output directories are final and audited.

## Files written (task root, never under `workspace/`)

`test_helpers/` — 2384 lines, unchanged this session: `__init__.py` 38, `api_client.py` 197, `api_errors.py` 114, `assertions.py` 285, `constants.py` 105, `factories.py` 288, `fixtures.py` 810, `test_users.py` 76, `types.py` 471.

`test_suite/` — 7566 lines, 170 tests:

| file | lines | tests | source |
|---|---|---|---|
| conftest.py | 78 | — | fixtures |
| test_01_delivery_fee_quote_and_settlement.py | 221 | 7 | queue A |
| test_02_score_and_fee_formulas.py | 271 | 6 | queue A |
| test_03_mission_and_incident_cycles.py | 306 | 8 | queue A |
| test_04_cascades.py | 203 | 5 | queue A |
| test_05_rejection_ladder_conflicts.py | 283 | 8 | queue A |
| test_06_boundary_precision.py | 215 | 6 | queue A |
| test_07_cross_entity_gates.py | 258 | 7 | queue A |
| test_08_interval_exclusivity.py | 232 | 6 | queue A |
| test_09_conserved_quantities.py | 219 | 5 | queue A |
| test_10_entity_contracts.py | 767 | 14 | Corner/entities |
| test_11_state_machine_paths.py | 898 | 15 | Corner/state_machines |
| test_12_calculation_corners.py | 568 | 14 | Corner/calculations |
| test_13_validation_gates.py | 1049 | 27 | Corner/validations |
| test_14_endpoint_contracts.py | 568 | 12 | Corner/endpoints |
| test_15_error_contract.py | 364 | 8 | Corner/errors |
| test_16_rbac.py | 372 | 8 | Corner/rbac |
| test_17_cross_cutting.py | 412 | 8 | Corner/cross_cutting |
| test_18_consistency_model.py | 282 | 6 | Corner/consistency_model |

## Coverage

- **Queue A (Difficulty): 23/23 instances translated, none skipped**, each with >=2 tagged tests (58 tests total).
- **Queue B (Corner): 68/68 non-stub instances translated, none skipped** (112 tests). The 28 `excluded_because:` stubs were not translated — verified programmatically that no tag resolves to a stub header.
- 170 test functions, 170 `Design:` tags, 91 distinct tags = exactly the 23 + 68 live instances. Every tag resolves to a verbatim `name:` in the source yaml, exactly one per test, always the last docstring line.

Three sub-claims inside otherwise-translated instances were dropped as not uniquely derivable from the PRD, rather than weakened: the load and `REPORT_BLOCKAGE` legs of `mission_actions_after_completed_hit_the_terminal_lock` (only the ABORT leg is asserted); the ordering claim in `bay_reservation_checks_type_then_service_state`, whose title contradicts PRD line 232 (state before type) — the two independent refusals are asserted with no ordering claim; and two arithmetically wrong `crossing_risk_score` literals in the corner index, re-derived from §2.6/§3.2 before assertion.

## Audits (all clean)

- `check_citations.py`: 19 files, 0 non-verbatim quotations.
- `check_sections.py` (new this session, catches quotes attributed to the wrong `§`): 19 files, 0 mislabelled sections.
- `check_coverage.py` (new): 0 unresolved tags, 0 translated stubs, 0 under-covered instances, 0 `pytest.mark.skip/skipif/xfail`.
- pyflakes silent on all of `test_suite/`; `py_compile` OK on all 28 modules (the only pyflakes output is the intentional `# noqa: F401` barrel in `test_helpers/__init__.py`).
- Static resolution check: all names imported from `test_helpers` exist in the barrel, and every `api.<method>` call resolves on `ApiClient`.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — never read or written; `worklog.md` untouched; scratch confined to `/tmp/task2827/`; `__pycache__` dirs from the import checks removed; suite never run.

### Orchestrator layout verification
`test_helpers/` and `test_suite/` are at the task root, not under `workspace/` (checked with `find workspace -type d -name "test_*"` → empty), guarding against the known `prd-bench-test-dirs-written-under-workspace` failure. Independently counted: 19 files in `test_suite/`, 170 `def test_`, 170 `Design:` tags, 0 `pytest.mark.skip`/`xfail`, 0 stray `__pycache__`.

## Step 7: Run Tests and Iterate — 2026-09-05T07:47:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failures traced to verbatim PRD prose and were uniquely derivable, so both were implementation defects.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none. Test count stayed at 170 across both iterations.

**Fixes applied to `implementation/`** — both in `/home/ubuntu/github/CodingPRD/tasks/task_2827_sidewalk_delivery_robot_operations/workspace/implementation/routes/orders.py`:

1. `get_order()` — added the `MerchantOperator` ownership gate (`ERR_NOT_RESOURCE_OWNER`, 403) on `GET /delivery-orders/{order_id}`, evaluated after existence resolution. Previously any `MerchantOperator` could read another merchant's order in full. Grounded in PRD §2.1: *"`MerchantOperator` — a merchant's own staff. … every read and write it makes is scoped to its own merchant"* and *"a `MerchantOperator` request is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) whenever `X-User-ID` does not equal the `Merchant` `id` that owns the target row — the merchant row itself, the `merchant_id` of a target order, …"*. The narrower reading (that §2.1's *"That ownership rule guards order intake, order cancellation, container loading, the single-merchant read and the order list"* enumeration is exhaustive and excludes the single-order read) is defeated by the role description's "every read … is scoped to its own merchant", so the assertion is uniquely derivable.

2. `remedy_order()` — moved the `remedy_kind is not None` → `ERR_REMEDY_ALREADY_ISSUED` check ahead of the `order_state in (EXCEPTION, DELIVERED)` gate. A successful `REFUND` leaves the order in `REFUNDED`, so with the old ordering a second attempt reported `ERR_INVALID_STATE_TRANSITION`. Decisive reading: PRD §3.8 says *"a second attempt, whatever kind it names, is refused with `ERR_REMEDY_ALREADY_ISSUED` (HTTP 409) because `remedy_kind` is no longer null"*, while the competing clause *"An order in `RECEIVED`, … or already `REFUNDED` cannot be remedied"* names no error id. Since `REFUNDED` is only ever reachable *through* a remedy, only the pre-empting order makes both PRD sentences literally true; §2.10's generic state-band ordering (which lists the declared-transition check before the remedy check) is the general rule that the endpoint-specific sentence governs. Verified the reorder cannot regress `TestRemedyNeedsALatchedException` or the budget/REDELIVER tests, all of which act on orders with `remedy_kind` still null.

**Final sweep numbers:** rounds 1–8 all **170 / 170 passed**, 0 failed, 0 errors. The two failures were deterministic (identical in all 8 rounds of iteration 1), so no flakiness or load-induced noise was involved.

### Orchestrator verification of the Step 7 sweep
Independently parsed all 8 `workspace/implementation/results.$i.json` files before accepting the subagent's claim (guarding the known `prd-bench-step7-verify-sweep-artifacts` failure mode where a subagent reports a clean sweep with no artifacts on disk). All 8 exist, parse as JSON, and each reports `passed=170 / total=170`. Step 8 is therefore NOT skipped: Step 7 applied 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-05T07:39:00.000Z

Subagent summary (verbatim):

Done. Both Step 7 items were genuine PRD gaps, so PRD_FINALIZED.md is not byte-identical.

## Line counts
- `PRD.md`: 445 lines / 115,488 bytes
- `PRD_FINALIZED.md`: 445 lines / 116,338 bytes
- Delta: 0 lines (+0.0%); +850 bytes (+0.74%) — three surgical in-paragraph edits, no new sections.

## Changes
- **§2.1 (RBAC, merchant-ownership paragraph)** — *revise* — added `the single-order read` to the enumeration of operations the ownership rule guards; pinned that on the single-order read the comparison is against the order's `merchant_id` and runs **after** the order row resolves (so an unknown `order_id` yields `ERR_ORDER_NOT_FOUND`, not 403), contrasted with the single-merchant read where the path id is itself the compared value and the refusal precedes the lookup; explicitly carved out the delivery-mission reads as unguarded — `implementation/routes/orders.py:70-77`, `routes/merchants.py:50-54`, `routes/missions.py:76-79`.
- **§2.10 (rejection ladder, state band)** — *revise* — moved `whether a remedy has already been issued` from second-to-last position in the state band to the **head** of the band — `implementation/routes/orders.py:192-195`.
- **§3.8 (remedy waterfall, opening paragraph)** — *insert* — one sentence stating the already-issued check is evaluated ahead of every state check on the order including the source-state gate, so a second remedy against a `REFUNDED` order still reports `ERR_REMEDY_ALREADY_ISSUED` — `implementation/routes/orders.py:192-195`.

## Per-edit pre-edit search log

**Edit 1 — §2.1 single-order read**
- (a) Subject: `MerchantOperator` merchant-ownership scoping — which endpoints apply it, what value it compares, and its position relative to the existence band.
- (b) Enumerated: `grep -rn "MerchantOperator|ERR_NOT_RESOURCE_OWNER"` over all of `implementation/`. Read every hit: `routes/orders.py` list_orders:52 (row filter), get_order:71-77 (gate **after** `must`), create_order:85-87 (body-`merchant_id` pre-check **before** existence) and :114-115 (after resolution), cancel_order:163-165 (after `must`); `routes/merchants.py` list_merchants:37 (row filter), get_merchant:50-54 (gate **before** `must`); `routes/missions.py` READ_ROLES:27-33 + list_missions:57-74 + get_mission:76-79 (**no** ownership gate, **no** row filter), load_mission:184-187 (after `must("missions")`); `middleware.py` `authorize`/`caller` (role band only). Also confirmed `routes/interventions.py:126,129` and `routes/incidents.py:159` are the takeover-control and recorded-reviewer checks, a different subject left untouched. Grepped `test_suite/` for MerchantOperator × mission reads: no coverage, so the code is the only authority — impl really does leave mission reads open.
- (c) Adjustments made: (i) scoped the "evaluated after the row resolves" claim to the single-order read only and added the contrasting merchant-read clause, because `get_merchant` checks ownership *before* `must` while `get_order`/`cancel_order`/`load_mission` check it *after* — a single universal ordering sentence would have mis-described one side or the other; (ii) said nothing about `POST /delivery-orders`, whose body-`merchant_id` pre-check at `orders.py:85` fires ahead of the payload and existence bands and would have been contradicted by a blanket "after resolution" rule; (iii) added the explicit delivery-mission carve-out so the §2.1 role bullet's "every read … is scoped to its own merchant" (kept verbatim, and the very clause Step 7 used to justify the order gate) cannot be generalized by a fresh implementer into a mission-read gate the impl does not have.

**Edit 2 — §2.10 state-band position of the already-issued check**
- (a) Subject: global ordering of the `remedy_kind is not None` check relative to the other state-band gates.
- (b) Enumerated: `grep -rn "ERR_REMEDY_ALREADY_ISSUED|remedy_kind"` over `implementation/` — the only evaluation site is `routes/orders.py:192`; `errors.py:39` is the status-code table and `calc.py:275-280` only consumes the kind for the bucket arithmetic. Read `remedy_order()` in full to fix the actual sequence: already-issued → source-state `(EXCEPTION, DELIVERED)` → `REDELIVER`-requires-`EXCEPTION` → `exception_reason is not None` → budget refresh → amount → budget gate. Confirmed the endpoint evaluates no other state-band item (no zone-permit, merchant-active, robot-duty, plan-segment, mission-terminal, reservation or takeover gate), so hoisting the clause to the head of the band is vacuous for every other endpoint.
- (c) No adjustment needed; the clause was moved rather than reworded, and `whether the order has a latched exception at all` stays last in the band, matching the impl's `exception_reason` check sitting after both state gates.

**Edit 3 — §3.8 explicit pre-emption sentence**
- (a) Subject: same as edit 2, stated locally at the remedy endpoint.
- (b) Enumerated: same paths as edit 2, plus a re-read of the surrounding §3.8 prose to confirm the new sentence does not contradict the retained sentences *"An order in `RECEIVED`, `DISPATCHED`, `IN_TRANSIT`, `CANCELLED` or already `REFUNDED` cannot be remedied"* (still true — `REFUNDED` is reachable only through a remedy, so the already-issued check is what refuses it) or the `REDELIVER`-only-from-`EXCEPTION` rule at `orders.py:196-200`.
- (c) Wording kept to the `REFUNDED` example and phrased as "ahead of every state check on the order" rather than "ahead of every check", so it makes no claim about the payload band (`check_enum` on `remedy_kind` at `orders.py:182`) or the existence band (`must("orders")` at `orders.py:184`), both of which do run first in the impl.

### Orchestrator verification
`cmp -s PRD.md PRD_FINALIZED.md` → differs (not byte-identical, which is the expected outcome given Step 7's 2 implementation fixes). `PRD_FINALIZED.md` tail still ends on the completed final error-table row, so no truncation was introduced.

## Step 9: Complete PRD — 2026-09-05T08:19:21.746Z

Orchestrator decision (recorded per the autonomy directive): Step 9 was run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`**, rather than a single subagent. Rationale — a 3912-line implementation across 23 modules exceeds what one subagent can scan exhaustively before its context forces summarisation, and the known failure mode is a subagent that emits a byte-identical `PRD_COMPLETED.md` because the scan never really ran. Partition: pass 1 = core (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `common.py`) + `routes/clock.py|zones.py|segments.py|closures.py`; pass 2 = `calc.py`, `cascades.py`, `routes/merchants.py|robots.py|bays.py`; pass 3 = `routes/orders.py|missions.py|plans.py|interventions.py|incidents.py`. Pass 1 alone performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md` bootstrap; passes 2 and 3 were explicitly forbidden from running `cp` so they could not clobber earlier edits. Pass 3 additionally owned a whole-document cross-pass contradiction read.

Totals across the three passes: **64 edits — 48 ambiguity-pins, 16 mismatch-revisions.** `PRD_FINALIZED.md` 445 lines / 116,338 chars → `PRD_COMPLETED.md` 445 lines / 135,272 chars (+18,934 chars, +16.3%); line count unchanged because every edit was in-paragraph, with no new sections or paragraphs.

### Pass 1 subagent summary (verbatim)

Done. Server probe confirmed every pin; process killed by exact PID.

## Bootstrap
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` ran first (source: **PRD_FINALIZED.md**, the Step 8 output). PRD_COMPLETED.md is the only file written.

## Size
| | lines | chars |
|---|---|---|
| PRD_FINALIZED.md | 445 | 116338 |
| PRD_COMPLETED.md | 445 | 123082 |

Char delta **+6744**; line count unchanged (every edit was in-paragraph, no new sections/paragraphs). 19 lines touched. `tail -3` ends on the last row of the §5 error table — a real section boundary.

## Counts
- ambiguity-pins: **16**
- mismatch-revisions: **3** (clock-default literal, adjacency self-id rule, `active_route_plan_id` claim under link 3)

## Changes
- §2.1 — revise — mismatch/ambiguity — role header falls back to `X-Role`; whitespace-only role = absent (401); missing `X-User-ID` read as `""` and never itself a 401; role compared verbatim so padded names give 403 — `middleware.py:22-32`
- §2.2 success bullets — insert — ambiguity — `api_request_id` = `req_` + exactly 20 upper-case-alnum chars — `response.py:12`
- §2.2 success bullets — insert — ambiguity — `api_request_timestamp` is the one API instant taken from real wall-clock time, not the logical clock — `response.py:16-19`
- §2.2 pagination bullet — insert — ambiguity — pagination meta only on list responses; `total_count` pre-window; `has_more` = `offset + len(page) < total_count`, so an over-the-end window returns empty with `false` — `response.py:27-34`
- §2.3 ¶1 — insert — ambiguity — limit/offset never clamped: non-integer, `limit`<1 or >100, negative `offset` → `ERR_INVALID_REQUEST` 400; empty-string param = omitted — `middleware.py:191-210`
- §2.3 ¶2 — insert — ambiguity — `created_at` ties broken by creation order — `db.py:125-126`, `common.py:40`
- §2.4 version bullet — insert — ambiguity — `version` advances at most once per row per request (multi-write cascade = +1 total, `updated_at` refreshed each write; create-then-adjust still returns `version` 1) — `db.py:111-122`
- §2.4 clock ¶ — revise — mismatch — startup default literal `2026-08-01T00:00:00.000Z`; clock POST answers 200 with `{current_utc}`; nothing is seeded, all collections empty at boot — `db.py:15`, `routes/clock.py:12-18`, `db.py:37-41`
- §2.9 ¶1 — insert — ambiguity — trailing slash insignificant; unknown path → `ERR_INVALID_REQUEST` 404, bad method → `ERR_INVALID_REQUEST` 405 (the only departures from 400); routing precedes auth — `app.py:28,51-57`
- §2.9 ¶2 — insert — ambiguity — filter semantics: empty = absent; unrecognised enum/boolean value → 400; reference/code filters exact-match and unvalidated (no-match → empty page); filters conjunctive and narrow `total_count` — `middleware.py:213-238`
- §2.10 payload band — insert — ambiguity — absent/unparseable/non-object body read as `{}`; explicit `null` = omitted; integral floats accepted for integers; booleans never accepted for number/int/string — `middleware.py:53-146`
- §3.1 adjacency ¶ — revise — mismatch — replaced the unreachable "may not contain its own id → 400" rule with the real one (array of non-empty strings else 400; duplicates de-duplicated keeping first occurrence and submitted order; own id impossible since it is minted post-validation) — `routes/segments.py:89-99,115-133`
- §3.1 mapping ¶ — insert — ambiguity — duplicate `segment_code` → `ERR_INVALID_REQUEST`, counts retired elements, evaluated after zone + neighbour resolution and after the same-zone adjacency check — `routes/segments.py:111-113`
- §3.1 approval ¶ — insert — ambiguity — when clearance and crossing risk both fail, the crossing-risk finding wins (§2.10 safety order) — `routes/segments.py:175-186`
- §3.1 retirement ¶ — insert — ambiguity — refusal code is `ERR_INVALID_STATE_TRANSITION`, also for any non-`SURVEYED`/`APPROVED` status — `routes/segments.py:189-197`
- §3.1 permitting ¶ — insert — ambiguity — `reason` read only by `RESTRICT`/`REVOKE`; ignored (not refused) on `ACTIVATE_PERMIT`/`LIFT_RESTRICTION` — `routes/zones.py:153-157`
- §3.2 activation ¶ — insert — ambiguity — both activation refusals carry `ERR_INVALID_STATE_TRANSITION` 409 — `routes/closures.py:162-172`
- §3.2 second link — insert — ambiguity — a HARD activation whose segment is not `APPROVED` stops after link 1: closure `ACTIVE` +1 version, segment untouched, `reroute_triggered_count` stays 0 — `routes/closures.py:115-117`
- §3.2 fourth link — insert — mismatch — a superseded plan whose mission is not `EN_ROUTE` leaves the mission wholly untouched, its `active_route_plan_id` still naming the superseded plan, and link 5 cannot fire for it — `routes/closures.py:132-152`
- §3.2 lifting ¶ — insert — ambiguity — `LIFTED` is terminal: both `LIFT` and `ACTIVATE` then give `ERR_INVALID_STATE_TRANSITION` — `routes/closures.py:192-196`

Verified as already correctly pinned (no edit): §5 error catalogue matches `errors.py:3-59` exactly (48/48 ids and statuses); zone list ordering (`created_at` desc, `id` asc); zone create field set, ranges and defaults (45.0 / 35 / 25000) vs §2.7; HHMM string-compare window rule; hard-closure inclusive overlap test; permit/segment/closure transition role bands vs §4; read-never-bumps-version despite the on-read `remedy_budget_remaining_cents` refresh.

### Pass 2 subagent summary (verbatim)

Pass 2 complete.

**Integrity:** No `cp` was run — every change was a surgical `Edit` on the existing `workspace/PRD_COMPLETED.md`. All five pass-1 marker sentences I spot-checked (`X-Role` fallback, trailing-slash routing, `reroute_triggered_count` stays at zero, `LIFTED` terminal both ways, adjacency de-duplication) are still present and unmodified; `PRD_FINALIZED.md`, `PRD.md`, `implementation/`, `test_*/` and `worklog.md` were untouched (mtimes confirm only `PRD_COMPLETED.md` changed).

**Size:** 445 lines / 123,082 chars before → 445 lines / 128,965 chars after (all edits inline; no new paragraphs or sections). `tail -3` still ends on the error-catalogue table rows (`ERR_REMEDY_BUDGET_EXCEEDED | 402`), a real section boundary.

**Counts:** 16 ambiguity-pins, 6 mismatch-revisions (22 edits).

- §2.6 Numeric Precision — revise — mismatch — the universal "no intermediate term is rounded" claim was false for the blockage-credit cap; now names the cap's fractional-cent truncation as the one exception, before the credit/cap comparison — `calc.py:90`
- §2.8 Conserved Quantities (merchant money) — insert — ambiguity — every exception cascade requires the order to be in `RECEIVED`/`DISPATCHED`/`IN_TRANSIT`; an already-excepted or terminal order is skipped silently (no second money move, no `exception_count`, no `version` bump) — `cascades.py:105-119`
- §2.8 Derived zone quantities — insert — ambiguity — `on_mission_robot_count` is floored at zero, never negative — `cascades.py:170-172`
- §2.8 Denormalized mirrors — revise — mismatch — `active_route_plan_id` is *not* cleared by an abort, so it goes on naming the plan the abort just rejected — `cascades.py:125-137`
- §2.8 Cascade discipline — insert — ambiguity — `created_at`-ascending cascade sets break ties by creation order — `cascades.py:10-11`
- §3.4 Fleet registration — insert — ambiguity — duplicate `asset_tag` → `ERR_INVALID_REQUEST`, checked after zone resolution and before the ordinance-speed comparison — `routes/robots.py:97-102`
- §3.4 Duty cycle — insert — ambiguity — `MAKE_AVAILABLE` health failure → `ERR_ROBOT_HEALTH_BLOCKED`; sub-35% battery → `ERR_INVALID_STATE_TRANSITION`, not a battery-specific code — `routes/robots.py:171-177`
- §3.4 Depot occupation — insert — ambiguity — missing `bay_reservation_id` is a payload finding raised before robot resolution; the four reservation conditions are evaluated only after the `AVAILABLE` duty gate passes — `routes/robots.py:150-194`
- §3.4 Retirement — revise — mismatch — "every duty state except `ON_MISSION`" also excludes the terminal `RETIRED` itself — `routes/robots.py:199`
- §3.4 Depot bays — insert — ambiguity — `bay_code` collision → `ERR_INVALID_REQUEST`, evaluated after zone resolution; same code in another zone is legal — `routes/bays.py:78-80`
- §3.4 Reserving a bay window — revise — mismatch — the three consistency gates were listed in the reverse of the real order; now zone mismatch → window conflict → bay-type mismatch → out-of-service, matching §2.10 — `routes/bays.py:174-186`
- §3.4 Reservation lifecycle — insert — ambiguity — clock outside the activation window → `ERR_INVALID_STATE_TRANSITION`, evaluated ahead of the bay-`OPEN` check — `routes/bays.py:214-228`
- §3.4 Reservation lifecycle — insert — ambiguity — `ACTIVATE`/`CANCEL` against a non-`HELD` reservation → `ERR_INVALID_STATE_TRANSITION` — `routes/bays.py:215,237`
- §3.5 Telemetry — insert — ambiguity — `battery_pct` bounded 0.0–100.0 inclusive; the two deltas are unbounded and may be negative; no duty/health state gates ingestion; version bumps even for an empty frame — `routes/robots.py:266-279`
- §3.5 Automatic health consequences — revise — mismatch — the low-battery downgrade fires only on a frame that actually carried `battery_pct` (not on the stored value); `tamper_flag: false` is inert; when both consequences fire the quarantine overwrites the downgrade — `routes/robots.py:281-290`
- §3.5 Quarantine cascade — insert — ambiguity — the auto-filed incident's fixed `narrative` literal, its null `reviewed_by_user_id`/`municipal_case_ref`/`insurer_claim_ref`, and that its insurer flag / 72h deadline come from the ordinary §3.9 rules — `cascades.py:208-218, 255-278`
- §3.5 Health transitions — insert — ambiguity — `CLEAR` against a `NOMINAL` or `DEGRADED` robot → `ERR_INVALID_STATE_TRANSITION` — `routes/robots.py:256-257`
- §3.5 Clearing a quarantine — insert — ambiguity — the `ON_MISSION` refusal is `ERR_INVALID_STATE_TRANSITION` and is checked first; the DRAFT scan spans every incident naming the robot regardless of zone/mission — `routes/robots.py:241-249`
- §3.5 Autonomy index (rolling) — insert — ambiguity — rolling-window order adds creation order as the final tie-break after `completed_at_utc` desc and `created_at` asc — `calc.py:152-153`
- §3.6 Read-side eligible pool — revise — mismatch — `eligible_only=true` applies only the five robot-intrinsic clauses (not the dropoff-zone match or container capacity), orders with creation order as last tie-break, and `eligible_only=false` is no filter rather than the complement — `routes/robots.py:59-67`, `calc.py:406-426`
- §3.9 Zone economics step 6 — insert — ambiguity — an order belongs to the zone via its *merchant's* `zone_id`, not its dropoff segment's — `calc.py:339-344`
- §3.9 Zone economics step 7 — insert — ambiguity — null `settled_fee_cents`/`remedy_amount_cents` contribute zero to their side of the revenue difference while the order still counts in the denominator — `calc.py:354-360`

I did not need to correct any pass-1 sentence; the only pass-1-adjacent area I touched is §2.8/§2.6, and both edits extend rather than contradict. `merchants.py` needed no edits — every behavior it exhibits (roles, ownership scoping, defaults, transition gates, zone-`PERMITTED` requirements on `ACTIVATE`/`REINSTATE` but not `SUSPEND`) was already uniquely pinned. Note for pass 3: `cascades.supersede_plan` is dead code (no call sites), so §3.6/§3.7 should not be pinned against it.

### Pass 3 subagent summary (verbatim)

Pass 3 complete.

## Confirmation

- **No `cp` was run** at any point. `PRD_COMPLETED.md` was edited in place with 23 `Edit` calls only.
- **Pass 1 / pass 2 edits intact.** File is 445 lines before and after — every change is in-paragraph, no line was added, deleted or reordered. A word-level diff of every touched line shows the only deletions are the specific incorrect clauses I was correcting; no pass-1/2 sentence was dropped.
- `PRD_COMPLETED.md`: **445 lines / 128,741 bytes / 128,965 chars → 445 lines / 135,005 bytes / 135,272 chars** (+6,264 bytes). md5 `457a20294606510c2aaef78c4a322464`, distinct from `PRD_FINALIZED.md`.
- `tail -3` ends on the final rows of the error-code appendix table (`ERR_NO_ELIGIBLE_ROBOT`, `ERR_BAY_TYPE_MISMATCH`, `ERR_REMEDY_BUDGET_EXCEEDED`) — a real section boundary.
- `git status` shows only `workspace/` as untracked; `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` untouched.
- **23 changes: 7 mismatch-revisions, 16 ambiguity-pins.** All 23 modified lines are inside sections whose subject lives in my partition (`orders.py`, `missions.py`, `plans.py`, `interventions.py`, `incidents.py`). `incidents.py` was audited exhaustively and needed **no** edits — its segregation-of-duties, reviewer, state, counter and flag behaviour already matches §3.9 uniquely.

## Changes

- §2.1 (line 17) — revise — **mismatch** — "each individual action inside them belongs to exactly one role" was false; now "every action to exactly one role except the intervention `RELEASE`, which all three of that endpoint's roles may take" — implementation/routes/interventions.py:43
- §2.1 FleetDispatcher bullet (22) — revise — ambiguity — added that it may open an intervention request and release a takeover — interventions.py:27,43
- §2.1 RemoteOperator bullet (23) — revise — ambiguity — added "plus the release of a takeover it assumed itself" — interventions.py:43,127
- §2.1 SafetyOfficer bullet (24) — revise — **mismatch** — its release is admitted from `REQUESTED` and `ACTIVE` as well as `ESCALATED`, not only from an escalated event — interventions.py:163
- §2.1 MerchantOperator bullet (26) — revise — **mismatch** — "every read and write is scoped to its own merchant" is untrue of the mission reads; hedged to "with the delivery-mission reads the one documented exception" — missions.py:27
- §2.1 (28) — insert — ambiguity — pinned the per-endpoint position of the merchant-ownership check: on intake it precedes both the remaining payload validation and the merchant lookup but only when `merchant_id` arrives as a non-empty string; on container loading it follows the mission lookup and precedes every payload check; on cancellation it follows the body's `reason` check — orders.py:85,163; missions.py:184
- §2.1 (30) — revise — **mismatch** — the takeover-control check applies to a `RemoteOperator` release only; a `SafetyOfficer` or `FleetDispatcher` releasing is never compared against `operator_user_id` — interventions.py:127
- §2.5 (102) — insert — ambiguity — `expected_delivery_mission_version` must be an integer >= 0 or the request fails in the payload band — plans.py:74
- §2.10 (152) — revise — ambiguity — hedged "stops at the first violated rule" to admit the individually documented out-of-band checks — missions.py:306; orders.py:161
- §2.10 (154) — insert — ambiguity — authorisation-band order, incl. that cancellation ownership follows the `reason` check — orders.py:161
- §2.10 (158) — revise — **mismatch** — the terminal-mission test is taken *ahead* of the source-state check on the two mission-target endpoints, so a `COMPLETED`/`ABORTED` mission always answers `ERR_MISSION_ALREADY_TERMINAL` — missions.py:180,373
- §3.1 (182) — revise — **mismatch** — a `RESTRICTED` zone refuses not just new dispatch but also `DEPART` and `RESUME` — missions.py:333
- §3.3 (206) — insert — ambiguity — the dropoff segment resolves before the merchant, so a body naming neither reports `ERR_SEGMENT_NOT_FOUND` — orders.py:111
- §3.3 (214) — insert — ambiguity — `reason` is checked before the `order_id` is resolved, is never persisted, and precedes the ownership refusal — orders.py:161
- §3.6 (268) — insert — ambiguity — sequence well-formedness runs first; `ERR_SEGMENT_NOT_FOUND` beats an unknown `mission_id`; the terminal-mission gate sits after the version pin and before any geometry — plans.py:78,95
- §3.6 (272) — insert — ambiguity — the crossing-risk gate skips null scores and passes vacuously when nothing in the sequence is scored — plans.py:113
- §3.6 (274) — insert — ambiguity — `REJECT` requires one of `OPERATOR_REJECTED`/`SEGMENT_BLOCKED`/`REPLACED_BY_NEWER`; `ACTIVATE` against a terminal mission draws `ERR_INVALID_STATE_TRANSITION`, not the terminal code; the plan list tie-breaks a shared `revision_index` by creation order — plans.py:176,196,40
- §3.7 (278) — insert — ambiguity — handoff ownership is compared as soon as the mission resolves, ahead of both payload checks, and the terminal/live-state split precedes the capacity comparison — missions.py:184
- §3.7 (284) — insert — ambiguity — the `blocking_segment_id` membership test needs the active plan and so runs *after* the `EN_ROUTE` gate — missions.py:306
- §3.7 (286) — insert — ambiguity — resume re-checks the permit between the plan test and the segment scan — missions.py:333
- §3.7 (288) — insert — ambiguity — the only gate on opening an event is the terminal-mission check; `autonomy_confidence_pct` is a whole number 0–100 — interventions.py:85
- §3.7 (290) — insert — ambiguity — apart from `ASSUME`, no takeover transition consults mission state, so an event is still actionable after its mission terminates — interventions.py:131
- §3.7 (292) — revise — **mismatch** — release is admitted from `REQUESTED`, `ACTIVE` and `ESCALATED`; all three endpoint roles may take it; only a `RemoteOperator` is identity-checked; `control_seconds` is 0 exactly when `assumed_at_utc` is null — interventions.py:163

## Cross-pass contradictions found and resolved

1. **"Exactly one role per action" (§2.1 line 17, Step 8 text) vs `interventions.py` three-role `RELEASE`** — the strongest contradiction in the file, and it also clashed with pass 1's §2.10 authorisation-band wording and with §4's role column for the intervention transitions endpoint. Resolved at line 17 with a single carve-out clause, and the surrounding role bullets (22/23/24) brought into line so the six-role list no longer implies the release is a `SafetyOfficer`-only or `ESCALATED`-only act.
2. **"§2.1 every MerchantOperator read is merchant-scoped" (line 26) vs "the delivery-mission reads are not guarded at all" (line 28)** — two sentences four lines apart stating opposite things. Resolved by hedging line 26 rather than touching pass 1's line 28.
3. **"§2.10 the ladder stops at the first violated rule" (line 152) vs three documented out-of-band checks** — the per-action role test (line 17), the cancellation `reason` check (line 154/214) and the blockage membership test (line 284) all violate the strict reading. Resolved with a minimal hedge at line 152 that points at §2.1 and §3 instead of restating the exceptions.
4. **§2.10 state-band order vs the mission endpoints' terminal-first check** — line 158 listed the source-state check before the terminal check while `missions.py` takes the terminal test first on both mission-target endpoints; corrected in place at 158, consistent with Step 8's already-correct §3.8 remedy-first wording immediately above it.

Two things I deliberately left alone: `§3.1`/`§3.6` prose was **not** pinned against `cascades.supersede_plan` (dead code, per pass 2's hand-off) — I verified `missions._report_blockage` supersedes the plan inline at missions.py:318-321, so §3.6's "driven to `SUPERSEDED` with `SEGMENT_BLOCKED`" claim already has a live code path. And §3.6's empty-eligible-pool clause (`ERR_NO_ELIGIBLE_ROBOT`, missions.py:131) is unreachable in practice — a named robot that passes every direct clause is necessarily in its own zone's pool — but line 260 already describes it accurately and no client-observable behaviour contradicts it, so I did not churn it.

### Orchestrator final verification
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (guards the known failure where a byte-identical PRD_COMPLETED.md means the scan never ran). 445 lines / 135,272 chars vs 116,338.
- `tail -3 PRD_COMPLETED.md` ends on the completed final error-table row — no truncation.
- `grep -in "harder than expert|SCAFFOLD|test_recipe|scaffold_difficulty" PRD_COMPLETED.md` → clean; no scaffold or difficulty-directive leakage.
- Step 9 edits documentation only; `implementation/` and both test directories were untouched after the Step 7 sweep, so the clean 8/8 × 170/170 result still stands (final `implementation/routes/orders.py` mtime 07:24 precedes the passing sweep's `results.*.json` mtime 07:29).
- Only one `worklog.md` exists in the task tree (no cwd-drift strays under `workspace/`); all `__pycache__`/`*.pyc` cleaned.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
