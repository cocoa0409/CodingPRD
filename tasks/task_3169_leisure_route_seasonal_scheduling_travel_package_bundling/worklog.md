# Worklog — task_3169_leisure_route_seasonal_scheduling_travel_package_bundling

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Pre-allocated directory `./tasks/task_3169_leisure_route_seasonal_scheduling_travel_package_bundling/` verified to exist with `workspace/` inside. No new index computed; used the pre-allocated path as instructed.

## Step 2: Generate Scaffold — 2026-09-30T07:05:00.000Z

All three files are written and the scaffold passes `scaffold_lint.py` with a clean verdict.

**Task**: `task_3169_leisure_route_seasonal_scheduling_travel_package_bundling` (Allegiant-style leisure airline)

**Files written**:
- `SCAFFOLD.yaml` (1543 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1073 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (868 lines)

**Scale (top-of-Expert band per the "much harder than expert level" directive)**:
- 15 entities, 68 endpoints, 50 error codes, 9 calculations, 11 state machines, 12 validation priorities, 5 peer roles, 3 OCC concurrency rules

**Complexity profile**: primary archetype `temporal_windowing` + secondary `posture_driven_gating`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions. Hierarchical topology, posture-driven state machine shape, peer-role RBAC, immediate consistency. Logical clock with fixed default `2026-09-01T00:00:00Z`.

**§1.8 Difficulty design** — 9 rules × 2 instances = 18 instances, each with structured `setup_api_calls`/`trigger`/`assert` chains (492 calls lint-checked):
1. **dual_variant_calc**: settlement provisional-vs-final (SupplierSettlement) vs booking fare snapshot (Booking/Route)
2. **combinatorial_formula**: mode (a) peak/non-peak branch in utilization cap; mode (b) per-bundle-then-settlement aggregation order
3. **non_linear_state_machine**: Route posture cycle (ACTIVE↔SUSPENDED) vs Booking STRANDED fork-join
4. **transitive_cascade**: route-suspend depth-4 cascade vs booking-cancel depth-2 settlement-clawback cascade
5. **priority_pair_validation_conflict**: state-vs-temporal on publish; referential-vs-OCC on package booking
6. **boundary_precision_check**: utilization `==` allowed on assign-aircraft; seat-capacity `==` allowed on rebook
7. **cross_entity_state_dependency**: publication⊂window; booking-rebook⊂target-flight
8. **resource_temporal_overlap**: route-week frequency aggregate vs aircraft-day point capacity
9. **compensating_invariant**: seats_sold conserved across book/cancel; settlement ledger identity (final gross + clawback == provisional gross)

**§1.9 Corner design** — 31 instances across 9 sections (entities, state_machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency), with `excluded_because:` stubs where §1.8 already covers the corner.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

Note: `api_prefix` was set to `""` (empty) because the lint's FK-reverse-reachability check derives collection segments from `<prefix>/<segment>/{id}` single-GETs; a non-empty prefix would have forced every entity under `/routes/...`. All list endpoints carry the FK filters the lint requires.

(Orchestrator note: subagent required three spawns — the first two turns ended mid-design without writing files; third turn completed with all three files written and lint-clean.)

## Step 3: Copy Shared Files — 2026-09-30T07:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3169_leisure_route_seasonal_scheduling_travel_package_bundling/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T07:16:00.000Z

PRD generated and verified.

**Output**: `workspace/PRD.md` — 341 lines, 48,426 bytes.

**Structure**:
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications — §2.1 RBAC (5 opaque roles), §2.2 verbatim response envelope, §2.3 pagination, §2.4 logical clock (initial `2026-09-01T00:00:00Z`), §2.5 common resource properties, §2.6 money/precision (integer cents), §2.7 nested retrieval ordering, §2.8 validation priority order, §2.9 OCC (three write endpoints with `expected_window_version` / `expected_flight_version` / `expected_booking_version` → `ERR_STALE_VERSION` 412), §2.10 cascading, §2.11 boundary semantics (strictly-greater rejects; == passes)
- §3 Business Logic — 9 subsections: network building, schedule publication (mask + 180-day horizon + frequency cap), fleet/utilization (peak-day caps), crew basing, bookings/ancillaries/bundles, disruptions/stranding/rebooking, cancellation cascades, supplier settlement (provisional vs final variants + clawback), route lifecycle (suspend/reactivate/close)
- §4 Endpoint table — 68 rows, 4 columns (Method, Path, Description, Authorized Role)
- §5 Error catalogue — 50 rows, 2 columns

**Hard Contracts** (all PASS):
- Contract 1 Field-Name Coverage: 74/74 entity fields, 71/71 request-body identifiers, 38/38 query params, 15/15 path params — 0 missing anywhere.
- Contract 2 Rule Coverage: all 12 validation priorities expressed with ordering; all 3 OCC rules name endpoint + occ field + `ERR_STALE_VERSION`/412; all state-machine transitions, side effects (incl. `suspended_seasons_count += 1`, `LOW_DEMAND` synthesized disruptions, settlement clawback, `STRANDED_REBOOKED → CONFIRMED` on mark-operated), all 9 calculations (stranded_until_date with created_at tie-break, dual-variant settlement gross, utilization caps with == passes, frequency cap with == passes, bundle price sum in hotel→rental→attraction order, base fare snapshot, ancillary recompute, rebook capacity, 180-day horizon) are rendered in prose without pseudocode.
- Contract 3 §3 Path Purity: 172 backticked tokens in §3 scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combinations.

**Constraint adherence**: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-09-30T07:38:00.000Z

All complete and verified. Final report:

### Files written

**test_helpers/ (9 files, 1589 lines)**
- `__init__.py` (30) — barrel export (framework generics + PRD-specific)
- `types.py` (317) — status enums + TypedDicts for all 15 entities (all carry the full common set per PRD §2.5)
- `api_client.py` (305) — one method per PRD §4 endpoint (~50 methods)
- `api_errors.py` (120) — full error catalog, registered via `set_error_http_status_map`
- `assertions.py` (174) — per-entity asserters using framework `is_valid_uuid`/`is_iso8601_timestamp`
- `factories.py` (153) — input-field-only payload factories
- `constants.py` (19) — `PUBLISH_HORIZON_MIN_DAYS = 180`, default clock instant
- `test_users.py` (38) — 5 opaque-role headers + `ANONYMOUS_HEADERS`
- `fixtures.py` (433) — 5-tier composites: `setup_route_with_open_window`, `setup_published_pipeline`, `setup_stranded_booking_on_first_flight`, `setup_settlement_with_package_bookings`, `setup_crew_base_with_member`, plus OCC-threading helpers (`create_air_only_booking`, `create_package_booking` re-read the flight's current version before writing)

**test_suite/ (9 files, 2458 lines)**
- `conftest.py` (35) — session `api` fixture + 5 role-header fixtures
- `test_01_calculations_and_variants.py` (285, 8 tests)
- `test_02_state_machines_and_cascades.py` (292, 8)
- `test_03_validation_and_capacity.py` (560, 12)
- `test_04_boundaries_and_invariants.py` (306, 8)
- `test_05_entities_breadth.py` (227, 7)
- `test_06_state_and_calc_corner.py` (237, 6)
- `test_07_validations_endpoints_rbac.py` (340, 10)
- `test_08_cross_cutting.py` (176, 4)

### Coverage
- **Total tests: 63** (pytest collection verified)
- **Queue A (Difficulty): all 18 instances × 2 tests = 36 tags** — every instance at exactly ≥2
- **Queue B (Corner): all 27 non-stub instances × 1 test = 27 tags** — every non-stub at ≥1
- **Queue B stubs (4, `excluded_because:`): not translated**; cross-references verified to resolve to real difficulty instances (`rebook_gated_by_target_flight_scheduled`, `business_referential_vs_business_constraint_on_package_booking`, `aircraft_daily_utilization_point_capacity`, `weekly_frequency_cap_aggregate_overlap`)

### Skipped instances
None. One corner instance (`entities/seats_sold_is_computed_not_client_settable`) had its asserted HTTP status relaxed from a hard `validate_error(ERR_INVALID_REQUEST, 400)` to a status-400-only check, because PRD never names the error_id for an unknown-field rejection — the 400 itself is uniquely derivable from PRD §3.2's closed input list plus the §5 catalog.

### Verification
- `python3 -m py_compile` on all 18 files: OK
- pytest `--collect-only`: 63 tests discovered cleanly
- Design-tag audit: all 63 tags resolve to real instances; every docstring ends with exactly one `Design:` line
- PRD verbatim-citation audit: 92 quoted citations, all survive whitespace-insensitive literal grep of PRD.md (9 initially failing elisions were rewritten to full verbatim sentences)
- No `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in generated code

## Step 6: Generate Implementation — 2026-09-30T08:00:00.000Z

68 route decorators registered; PID 2568464 confirmed dead. Server killed cleanly.

### File list with line counts

| File | Lines |
|------|------:|
| `start.sh` (executable) | 9 |
| `requirements.txt` | 1 |
| `app.py` | 89 |
| `db.py` | 24 |
| `errors.py` | 37 |
| `response.py` | 83 |
| `middleware.py` | 93 |
| `common.py` | 178 |
| `routes/stations.py` | 60 |
| `routes/routes.py` | 323 |
| `routes/season_windows.py` | 151 |
| `routes/publications.py` | 277 |
| `routes/aircraft.py` | 94 |
| `routes/flight_instances.py` | 129 |
| `routes/crew.py` | 236 |
| `routes/supplier_offers.py` | 72 |
| `routes/bookings.py` | 492 |
| `routes/disruptions.py` | 98 |
| `routes/supplier_settlements.py` | 154 |
| `routes/clock.py` | 26 |
| **Total** | **2 616** |

### Endpoint count
68 route decorators across 12 blueprints covering all 68 endpoints in §1.5 of the scaffold (clock, stations, routes+transitions, season windows nested+flat, publications nested+flat, aircraft, flight instances, crew bases/members/assignments nested+flat, supplier offers, bookings/bundles/ancillaries nested+flat, disruptions nested+flat, supplier settlements + finalize).

### Boot verification
Started `app.py` on `PORT=13169` (PID 2568464). The server bound 0.0.0.0, responded to `POST /_clock/set_current_utc` with HTTP 200, and a full smoke test passed: station creation (origin+destination) → route creation → season window → activate (`SEASONAL_ACTIVE`) → publish (window OCC passed, 9 flight instances generated for Mon+Thu mask across March 2027) → aircraft registration → tail assignment (utilization cap OK) → AIR_ONLY booking (base_fare_total = 2×8900 = 17800, flight `seats_sold` and `version` bumped) → stale-version booking attempt returned HTTP 412 `ERR_STALE_VERSION`. The server was then killed via `kill 2568464` and verified dead with `ps -p`.

### Key contract notes
- Storage is in-memory dicts only; nothing is seeded at startup; `db.py` initializes empty dicts and the logical clock to `2026-09-01T00:00:00Z`.
- Envelope: `{meta:{api_request_id,api_request_timestamp[,limit,offset,total_count,has_more]}, response_type, data}`; errors use `response_type:"error"` and `data:{error_id,message}`.
- `start.sh` guards `pip install` behind a `python3 -c "import flask"` probe and `exec`s `python3 app.py`.
- OCC checks (`expected_window_version`, `expected_flight_version`, `expected_booking_version`) are enforced last, per PRD §2.8.
- Boundary semantics: frequency/utilization/capacity checks reject only on strict `>`; publish horizon rejects only on `<` 180 days.
- Cascades implemented per §2.10: route suspend (windows → publications → flights → bookings+crew), booking cancel (ancillaries → bundle → settlement clawback), bundle cancel → PROVISIONAL settlement clawback + `CLAWED_BACK`, settlement finalize → bundle `SETTLED`, mark-operated → `STRANDED_REBOOKED` → `CONFIRMED`, disruption recovery when all stranded bookings are rebooked or cancelled.

## Step 7: Run Tests and Iterate — 2026-09-30T08:15:00.000Z

All 8 rounds pass with 58/58 (63 − 5 deleted tests). Clean sweep.

**Iterations run:** 2 (initial sweep surfaced failures; one fix round; final sweep clean 8/8).

**Tests deleted (5):**
- `test_booking_create_missing_booking_kind_rejected` (test_05) — asserted `ERR_INVALID_REQUEST`/400 for a missing `booking_kind`; PRD §5's error catalogue "enumerates every error identifier the API can return" and contains no such error. PRD SILENT (scaffold-only error identity for missing required fields).
- `test_ancillary_kind_out_of_enum_rejected` (test_05) — asserted `ERR_INVALID_REQUEST`/400 for out-of-enum `ancillary_kind`; PRD names the enum members but no rejection error. PRD SILENT (scaffold-only enum-violation error).
- `test_seats_sold_is_computed_not_client_settable` (test_05) — asserted 400 for an unknown extra field in the publication payload; PRD never specifies unknown-field rejection, and a faithful implementation may ignore extras while still computing `seats_sold` server-side. Unique-derivability collapse (rejection-behavior silence).
- `test_ledger_conserved_final_gross_plus_clawback_equals_provisional` (test_04) — cancels a booking under a PROVISIONAL settlement (→ CLAWED_BACK) then asserts finalize succeeds; PRD §3.8 verbatim: "Finalization requires the settlement's `settlement_status` to still be `PROVISIONAL` — otherwise … `ERR_SETTLEMENT_NOT_PROVISIONAL`" and "A clawed-back settlement is terminal". Test contradicts PRD (unique-derivability collapse).
- `test_ledger_money_never_vanishes_across_cancel_and_finalize` (test_04) — same pattern/same PRD conflict.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` / `list_flights_for_publication` — re-sort returned flights by `(flight_date, id)`. PRD only guarantees `created_at`-ascending list order; flights generated in the same millisecond tie on `created_at`, making "first flight" nondeterministic. This was the root cause of the flaky `test_stranded_booking_rebooks_onto_later_flight` and `test_route_suspend_strands_booking_with_no_rescue_flight`.

**Fixes applied to `implementation/`:**
- `routes/bookings.py` (`_cancel_booking`, `rebook_booking`) — now invoke `_maybe_recover_disruption` after cancel/rebook so a disruption transitions DECLARED → RECOVERED automatically once every booking it stranded is resolved (PRD §3.6); `_maybe_recover_disruption` previously existed but was never called.
- `routes/routes.py` (`_cancel_flight`) — tag stranded bookings with `_stranded_by_disruption_id` inside `_cancel_flight` itself (covers synthesized cascade disruptions, not just declared ones; the redundant tagging block in `routes/disruptions.py` was removed).
- `routes/routes.py` (new `_recompute_stranded_until_for_route`, called at the end of `suspend_route` and `_suspend_window`) — post-cascade recompute of `stranded_until_date` for STRANDED bookings so no booking points at a rescue flight the same cascade cancelled (PRD §3.6: "cancelled and operated flights never count"; §3.9: "recomputed by the rule in §3.6"). This fixed the deterministic `test_route_suspend_strands_booking_with_no_rescue_flight` failure.
- `response.py` (`ok`) — scrub underscore-prefixed internal bookkeeping fields from response payloads so `_stranded_by_disruption_id` never leaks into API responses.

Final state: 8/8 parallel rounds at 58/58 passed (orchestrator-verified from results.1..8.json).

## Step 8: Finalize PRD — 2026-09-30T08:22:00.000Z

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 341 lines; PRD_FINALIZED.md = 343 lines (+2 lines, +0.6%).

### Changes (one bullet per edit)

- **§2.2 (API Response Structure)** — insert — added a bullet stating that server-internal bookkeeping fields (underscore-prefixed names) are stripped from every success response payload at any nesting depth — `implementation/response.py:30-36` (`_scrub` in `ok`).
- **§2.3 (Pagination)** — revise — list-endpoint ordering sentence now pins `id`-ascending as the tie-break when `created_at` values tie, making list order deterministic — e.g. `implementation/routes/flight_instances.py:49`, `implementation/routes/bookings.py:295` (all 20 list handlers sort `(created_at, id)`).
- **§3.6 (Irregular Operations)** — revise — the automatic DECLARED → RECOVERED paragraph now states that every booking stranded by a flight cancellation is internally attributed to the stranding disruption (declared or cascade-synthesized), that this attribution is never exposed in responses, and that the recovery re-check runs after each booking rebook and each booking cancellation — `implementation/routes/routes.py:131` (`_cancel_flight` tags `_stranded_by_disruption_id`), `implementation/routes/bookings.py:119-133, 171-173, 364-366` (`_maybe_recover_disruption` invoked from `_cancel_booking` and `rebook_booking`).
- **§3.9 (window-level suspension)** — insert — after the window-suspension cascade completes, `stranded_until_date` is recomputed by the §3.6 rule for every booking still STRANDED on the route — `implementation/routes/routes.py:232` (`_recompute_stranded_until_for_route` at the end of `_suspend_window`).
- **§3.9 (route-level suspension)** — insert — same final recomputation pass after the route-suspension cascade — `implementation/routes/routes.py:266`.
- **§5 (Error Code Catalogue)** — revise + insert — added `ERR_VALIDATION | 422` row and a sentence defining it as the generic request-shape error (missing/wrongly-typed required fields, out-of-enum values such as `booking_kind`/`ancillary_kind`, non-positive quantities, malformed dates/times, bad pagination params, missing/non-integer expected-version fields), plus the rule that unrecognized extra request fields are ignored, not rejected — `implementation/common.py:97-178`, `implementation/errors.py:36-37`, `implementation/response.py:76-83`.

No PRD changes for: the two deleted test_04 settlement tests (PRD §3.8 already pins PROVISIONAL-only finalization and terminal CLAWED_BACK — the tests contradicted the PRD), or the `fixtures.py` flight-sort fix (pure test-fixture determinism bug; the §2.3 tie-break edit covers the impl-side ordering contract).

### Per-edit pre-edit search log

1. **§2.2 scrub edit** — (a) subject: response payload field exposure. (b) enumerated: `response.py` (`ok`, `_scrub` — only response builder used by every route handler); grep for `_stranded_by_disruption_id` (only underscore field stored on entities; set in `routes/routes.py:131`, read in `routes/bookings.py:127,171,364`); confirmed no handler bypasses `ok()`. (c) scoped wording to success payloads and any nesting depth (matches recursive `_scrub`).
2. **§2.3 tie-break edit** — (a) subject: list ordering. (b) enumerated all 20 `items.sort` sites across stations/routes/season_windows/publications/aircraft/flight_instances/crew/supplier_offers/bookings/disruptions/supplier_settlements — all `(created_at, id)`; distinguished from the §3.6 stranded-candidate ordering (`(flight_date, created_at)`, routes.py:158), which is not a list endpoint and already has its own PRD rule. (c) scoped the new sentence to list endpoints only.
3. **§3.6 recovery edit** — (a) subject: disruption recovery trigger + stranded-by attribution. (b) enumerated: `_cancel_flight` (single tagging site, reached from `declare_disruption` disruptions.py:55 and `_freeze_publication` routes.py:200, hence from window suspend, route suspend, and declared disruptions); `_maybe_recover_disruption` and its only call sites (`_cancel_booking`, `rebook_booking`); verified no other transition out of STRANDED exists (`mark_operated` only touches STRANDED_REBOOKED; retire only cancels zero-seat flights). (c) stated attribution covers declared and synthesized disruptions; recovery check tied to rebook and cancel only.
4. **§3.9 window-suspend recompute edit** — (a) subject: post-cascade `stranded_until_date` recompute. (b) enumerated call sites of `_recompute_stranded_until_for_route`: `_suspend_window` (routes.py:232; invoked by the window-suspend endpoint season_windows.py:93 and covering auto route suspension inside it) and `suspend_route` (routes.py:266); confirmed `declare_disruption` does NOT run a recompute pass. (c) wording deliberately scoped to suspension cascades, not a universal recompute-after-any-cancellation claim.
5. **§3.9 route-suspend recompute edit** — same subject/enumeration as edit 4; wording mirrors the window-level sentence and stays scoped to the route-suspension cascade.
6. **§5 ERR_VALIDATION edits** — (a) subject: error-catalogue completeness and validation-error identity. (b) enumerated every `ERR_VALIDATION` raise site (common.py field helpers, response.py pagination, clock.py, stations.py, aircraft.py, publications.py, season_windows.py, bookings.py `hotel_offer_id`, supplier_settlements.py) and confirmed no unknown-field rejection exists anywhere (grep for unknown/extra/unexpected). Also confirmed §2.8's ordering narrative is untouched by the edit — the new sentence asserts what ERR_VALIDATION covers, never where it sits in the check ordering. (c) used non-exhaustive "such as" phrasing for enum fields so all `require_enum` sites (station_kind, crew_role, component_kind, booking_kind, ancillary_kind, reason_code) remain covered.

## Step 9: Complete PRD — 2026-09-30T08:38:00.000Z

Line count: 343 → 344 (+1 line, the error-envelope bullet). Char delta: 50883 → 56312 = +5429 chars. All edits are inline inserts/revisions (plus one list bullet).

**Source vs output:** `workspace/PRD_FINALIZED.md` (343 lines / 50,883 chars) → `workspace/PRD_COMPLETED.md` (344 lines / 56,312 chars). Delta: +1 line, +5,429 chars. All changes are inline in-paragraph inserts/revisions plus one list bullet; no new sections.

**Counts:** 21 ambiguity-pins (inserts), 2 mismatch-revisions.

**Changes:**

- §2.2 Error Response Format — insert — ambiguity — pin generic error ids `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) for untyped framework failures — implementation/app.py:49-85
- §2.3 Pagination — revise — ambiguity — `limit` outside 1..100 and negative `offset` rejected with `ERR_VALIDATION` 422, never clamped — implementation/response.py:64-83
- §2.4 Logical Clock — revise — ambiguity — "from server start" replaces "before any client call" — implementation/db.py:23-24
- §2.5 Common Resource Properties — revise — ambiguity — `version` starts at 1; PACKAGE booking attach counts as a modification so a new package booking carries version 2 — implementation/common.py:27, implementation/routes/bookings.py:270-271
- §2.5 — insert — ambiguity — post-suspension `stranded_until_date` recompute touches the booking only when the value actually changes — implementation/routes/routes.py:172-175
- §2.7 Nested existence — insert — ambiguity — nested id existing under a different parent surfaces the same not-found error — implementation/routes/season_windows.py:75-76, implementation/routes/crew.py:199-202
- §3.1 Stations — revise — mismatch — `iata_code` uniqueness is a domain convention, not server-enforced — implementation/routes/stations.py:26-34
- §3.1 Routes — insert — ambiguity — `base_fare_cents >= 0`, `weekly_frequency_cap >= 1`, else `ERR_VALIDATION` 422 — implementation/routes/routes.py:33-34
- §3.1 Season Windows — revise — ambiguity — `window_end_date < window_start_date` → `ERR_VALIDATION` 422; creation-time `suspension_reason` vs suspension-time note clarified — implementation/routes/season_windows.py:37-51
- §3.2 Publications — insert — ambiguity — `last_operating_date < first_operating_date` also raises `ERR_PUBLICATION_OUTSIDE_WINDOW` — implementation/routes/publications.py:79-84
- §3.2 Publications — insert — ambiguity — weekly-frequency count includes every generated flight regardless of `flight_status` — implementation/routes/publications.py:120-137
- §3.2 Publications — revise — mismatch — peak-day set pinned as fixed ISO weekdays 6–7 (Saturday/Sunday), not a route attribute — implementation/routes/publications.py:160-161
- §3.2 Publications retire — insert — ambiguity — retire-cancelled flights keep `cancelled_by_disruption_id` null and never strand bookings — implementation/routes/publications.py:242-249
- §3.3 Aircraft — revise — mismatch — `tail_number` uniqueness not enforced; pin `seat_capacity >= 1`, both caps `>= 0`, peak < daily → `ERR_VALIDATION` 422 — implementation/routes/aircraft.py:29-38
- §3.3 Tail assignment — insert — ambiguity — no `flight_status` gate on assign-aircraft; utilization sum excludes the target flight itself — implementation/routes/flight_instances.py:74-86
- §3.3 Aircraft retire — revise — ambiguity — retiring a non-`IN_SERVICE` aircraft raises `ERR_AIRCRAFT_HAS_LIVE_FLIGHTS` 409 — implementation/routes/aircraft.py:75-80
- §3.4 Crew — revise — mismatch — `employee_number` uniqueness not server-enforced — implementation/routes/crew.py:91-100
- §3.4 Crew assignment — insert — ambiguity — basing check (`ERR_CREW_BASE_MISMATCH`) evaluated before activity check (`ERR_CREW_MEMBER_INACTIVE`) — implementation/routes/crew.py:151-162
- §3.5 Bookings — insert — ambiguity — target flight must be `SCHEDULED` else `ERR_FLIGHT_NOT_SCHEDULED` 409; `passenger_count < 1` → `ERR_VALIDATION` — implementation/routes/bookings.py:184-192
- §3.5 Ancillaries — insert — ambiguity — ancillary creation is not gated on `booking_status`; `amount_cents <= 0` → `ERR_VALIDATION` — implementation/routes/bookings.py:420-438
- §3.5 Package bundle — insert — ambiguity — missing `hotel_offer_id` on PACKAGE → `ERR_VALIDATION`; offer ids ignored on AIR_ONLY; per-slot evaluation order hotel→rental→attraction and per-offer order kind→destination→open; unknown offer id → `ERR_OFFER_NOT_FOUND` 404 — implementation/routes/bookings.py:197-231
- §3.5 Supplier offers — insert — ambiguity — `net_cost_cents`/`sell_price_cents` integers >= 0; `destination_station_id` must exist else `ERR_STATION_NOT_FOUND` — implementation/routes/supplier_offers.py:29-32
- §3.6 Disruptions — insert — ambiguity — flight id unknown or on a different route → `ERR_FLIGHT_NOT_FOUND` 404 — implementation/routes/disruptions.py:30-39
- §3.6/§3.7 Seats recomputation — insert — ambiguity — `seats_sold` on rebook/cancel is recomputed from scratch as sum of `passenger_count` over `CONFIRMED`/`STRANDED`/`STRANDED_REBOOKED` bookings, not delta-adjusted — implementation/routes/bookings.py:58-67
- §3.8 Settlements — insert — ambiguity — `period_end_date < period_start_date` → `ERR_VALIDATION` 422 — implementation/routes/supplier_settlements.py:82-87
- §3.8 Clawback — insert — ambiguity — clawback aggregated per supplier across the bundle's offers, added once per supplier — implementation/routes/bookings.py:89-116
- §3.9 Reactivate — insert — ambiguity — posture check precedes open-window check (`ERR_ROUTE_NOT_SUSPENDED` before `ERR_NO_OPEN_SEASON`) — implementation/routes/routes.py:274-289
- §3.9 Close — insert — ambiguity — closing a route in `PLANNING` or `PERMANENTLY_CLOSED` → `ERR_ROUTE_NOT_ACTIVE` 409, before live-flight/live-booking checks — implementation/routes/routes.py:299-310
- §4 Endpoint preamble — insert — ambiguity — DELETE crew-assignment release returns `200 OK` with the released assignment in `data` — implementation/routes/crew.py:209-211

Output file: `workspace/PRD_COMPLETED.md`

## Pipeline Complete — 2026-09-30T08:38:00.000Z

All 9 steps done. Final state: 58/58 tests passing across 8/8 parallel stability rounds; PRD_FINALIZED.md (+0.6% over PRD.md) and PRD_COMPLETED.md (+1 line / +5,429 chars over PRD_FINALIZED.md) written.
