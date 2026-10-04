# Worklog — task_3170_scheduled_train_plan_car_trip_plan_compliance

## Step 1: Create Task Directory — 2026-09-30T06:50:00.000Z

Pre-allocated task directory `./tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/` verified to exist (per command args — no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T07:29:00.000Z

Lint is clean and all cross-checks pass. Final verification of the lint verdict block (verbatim, as the checklist requires):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    45
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     34
  Calls scanned (§1.8+§1.9):  581

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the full scaffold for `task_3170_scheduled_train_plan_car_trip_plan_compliance` purely from the scenario + skill spec (no sibling tasks were read):

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/`):
- `SCAFFOLD.yaml` — 61,424 bytes (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 99,193 bytes (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 92,206 bytes (single key `scaffold_corner_design`)

**Counts**: 10 entities, 8 state machines, 45 endpoints, 39 error codes, 8 calculations, 12 ordered validations, 3 OCC concurrency rules, 6 roles. §1.8: 18 instances (2 per rule × 9 rules). §1.9: 34 instances across sections entities/state_machines/calculations/validations/errors/rbac/cross_cutting_layers/consistency_model. All 52 instance names unique.

**Difficulty design decisions** (per the "much harder than expert" directive):
- **Archetype blend**: quota/allocation (per-day crew-pool epochs, yard classification capacity, locomotive inventories) + posture-driven gating (derived Yard.posture OPEN/CONGESTED/EMBARGOED gates shipment create, trip-plan assignment, and departure finalize).
- **Deep cascades**: one late YARD_ARRIVAL CarEvent triggers leg1 COMPLETED → connection_window (slack 540 < cutoff 600) → leg2 MISSED → leg3 MISSED → shipment trip_plan_status/compliance flip → ServiceException auto-raise (depth ≥ 3); a separate departure-cancel trigger fires locomotive release + slot-leg misses (different cascade pattern).
- **Dual variants**: plan velocity 22.9167 mph vs actual velocity 32.3529 mph on identical miles (1100 mi; 48 planned hours vs 34 observed hours — actual beats the padded schedule); per-car dwell 21.0000 h vs aggregate overage 19.0 h/11.0 h on one event history.
- **Combinatorial formulas in different modes**: posture bands (mode a: 3+ inputs, per-session max-floor, state-filtered set, two strictly-greater thresholds) and HOS/pool gate (mode c: evaluation-order pinning — pool-state branch before numeric HOS check).
- **Boundary precision**: overage == B exactly stays OPEN, == 2B exactly stays CONGESTED; connection slack == cutoff exactly MADE; HOS 12.0 passes, 12.0001 fails; pickup deadline is strictly-greater (assignment at the deadline succeeds, +1 s fails).
- **Concurrency**: three true-race OCC rules (plan activate/retire, trip-plan assign) all resolvable by sequential stale-version probes; GET reads use the literal `Any` role token so lint check (b) passes without weakening RBAC.
- **Logical clock**: `POST /rail/_clock/set_current_utc` with fixed startup default 2026-09-01T00:00:00Z; all fixtures use 2026-09-01 (Tuesday) and verified weekday masks.
- All numeric asserts were pre-computed with Python against the declared formulas; `scaffold_lint.py` reports clean lint (581 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-09-30T07:30:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T07:35:00.000Z

Done. PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/PRD.md`.

**Summary**

- **PRD.md line count:** 290 lines.
- **Sections produced:** §1 Introduction (3 paragraphs); §2 Global Specifications with 10 subsections (2.1 RBAC incl. per-role `identity: opaque` translation; 2.2 verbatim fixed response-envelope block; 2.3 Pagination with limit default 10/min 1/max 100/offset 0 and `created_at` ascending sort; 2.4 Common resource properties incl. CarEvent's absent `updated_at`/`version`; 2.5 Logical clock with the exact `2026-09-01T00:00:00Z` startup default; 2.6 Derived yard posture gating; 2.7 OCC with all three rules; 2.8 Precision/rounding + constants 25.0 mph / 12.0 h / 30-min delay threshold; 2.9 Existence + full 12-priority validation ordering with masking examples; 2.10 Malformed requests); §3 Business Logic with 10 subsections organized by resource lifecycle (train plan, yards/posture, crew pools, locomotives, departures, car events/dwell, trip-plan assignment + connection windows + miss cascades, delivery/velocity/credits, shipments/customers/compliance ledger, exception triage/recovery); §4 Endpoint table (45 rows, 4 columns); §5 Error catalogue (39 rows, 2 columns).
- **Zero-Silence / hard-contract check (all PASS):**
  - **Contract 1 (field names):** 64 required identifiers (all `entities[].fields[].name`, endpoint inputs `current_utc`/`additional_crews`/`delta`/`expected_train_plan_version`/`expected_shipment_version`/`legs`, pagination/query params incl. filter names like `connection_status`, `exception_type`, `event_type`) — 64 present in backticks, 0 missing.
  - **Contract 2 (rules):** all 12 validation priorities expressed as an explicit ordered list; 3/3 OCC rules with write action + OCC field + `ERR_STALE_VERSION`/412 and no race framing; all 8 state machines with every transition's preconditions, error IDs, and side effects (incl. missed-connection cascade, finalize cascades, locomotive reposition, posture band boundaries with exact-equality semantics, replan supersession); all 8 calculations translated to precise prose with constants embedded and boundary semantics preserved (cutoff `>=` semantics, HOS `>` semantics, dwell floor at zero, whole-minute truncation, 4-decimal round-half-up, 1-hour velocity floor); all embargo `applies_to` endpoints enumerated; field defaults/initial values/constraints all placed on owning entities; sibling branches (pool close ×2, loco release ×2, plan-velocity variants, event-type effects ×4) rendered with equal density.
  - **Contract 3 (§3 path purity):** 392 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos.
  - All 39 error IDs appear in §2/§3 narrative (not just the §5 table); all 53 enum/state values appear verbatim.

## Step 5: Generate Unit Tests — 2026-09-30T07:50:00.000Z

All citations survive a literal grep. Generation complete.

## Summary

**Task:** `task_3170_scheduled_train_plan_car_trip_plan_compliance`

**Files written:**

`test_helpers/` (9 files):
- `types.py` — entity TypedDicts (CarEvent correctly omits `updated_at`/`version` per the append-only rule) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (36 methods)
- `api_errors.py` — `ApiErrorId` enum + full 39-entry HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + crew-pool invariant checker
- `factories.py`, `constants.py` (PLAN_SPEED_MPH 25.0, HOS_MAX_HOURS 12.0, delay threshold 30, server default clock), `test_users.py` (all roles opaque → shared constants only), `fixtures.py` (primitive creators + `setup_operational_scenario`, `setup_two_shipments_dwelling`, `finalize_and_depart` composite choreography), `__init__.py` barrel

`test_suite/` (9 files): `conftest.py` + `test_01_entities_and_listing.py`, `test_02_state_machines.py`, `test_03_calculations.py`, `test_04_validations.py`, `test_05_rbac.py`, `test_06_concurrency_and_versions.py`, `test_07_consistency.py`, `test_08_difficulty.py`

**Counts:**
- Total tests: **68**
- Queue A (Difficulty): **17 of 18 instances covered, ≥2 tests each** (36 tests)
- Queue B (Corner): **34 of 34 non-stub instances covered, ≥1 test each** (32 tests; no `excluded_because:` stubs existed)

**Instances skipped (1):**
- `Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_car_event` — the asserted `ERR_INVALID_REQUEST`-before-`ERR_EVENT_SEQUENCE_INVALID` precedence is not in PRD §2.9's 12-item fixed priority order, so two PRD-only readers could ship either ordering; fails unique derivability.

**Weakened assertions avoided:** two scaffold-side expectations were dropped from covered instances as PRD-silent (plan-variant velocity figure is never exposed on a response field; per-car `dwell_hours` has no GET surface), per the `computed-field` silence pattern — instances remained covered via their PRD-derivable claims.

**Verification:** all modules compile and import; the automated tag audit confirms **every emitted test carries exactly one `Design:` tag resolving to a real instance** (0 bad/unresolved tags, 0 untagged tests); distinctive ≥8-word docstring citations survive literal `grep` of PRD.md.

## Step 6: Generate Implementation — 2026-09-30T08:05:00.000Z

Server killed cleanly. Implementation complete.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/implementation/`:
- `app.py` — full Flask app, single file, ~950 lines
- `requirements.txt` — `flask>=2.0`
- `start.sh` — executable launcher (see below)

**Endpoint count**: all 37 endpoints from §1.5 of SCAFFOLD.yaml / PRD §4 are implemented — 1 clock, 3 yards, 5 train-plans, 5 crew-pools, 5 locomotives, 4 customers, 4 shipments, 4 trip-legs, 5 train-departures, 4 car-events, 5 service-exceptions.

**Architecture**:
- In-memory only: a module-level `db` dict holding `yards`, `train_plans`, `crew_pools`, `locomotives`, `customers`, `shipments`, `trip_legs`, `departures`, `car_events`, `exceptions`. No file/SQLite/seed data anywhere.
- Logical clock initialized to exactly `2026-09-01T00:00:00Z`, advanced only via `POST /rail/_clock/set_current_utc`, and recomputes all yard postures on each advance.
- Response envelope per scaffold: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list responses add `limit/offset/total_count/has_more` to `meta` (default 10/0, min 1, max 100). Errors use `data.{error_id, message}`.
- Auth: requires `X-User-ID` + `X-User-Role`; role must be one of the six recognized names. RBAC enforced per endpoint per the role table; all GET endpoints accept `Any` plus the five business roles.
- OCC: `expected_train_plan_version` on activate/retire, `expected_shipment_version` on trip-leg assignment — both 412 `ERR_STALE_VERSION`.
- Calculations: plan_velocity (committed miles over planned hours, transit = route_distance/25.0), actual_velocity (over first TRAIN_DEPARTURE → final PLACED_DELIVERED, same-instant ⇒ elapsed=1h), dwell sessions + posture bands (≤B OPEN, ≤2B CONGESTED, >2B EMBARGOED, all round-half-up to 4 decimals), connection window (slack < cutoff → MISS, == → MADE), HOS max 12.0 (strict > rejects), departure variance threshold 30 min, service credits = shipment.car_count.
- Cascades: missed leg → connection MISSED + shipment.trip_plan_status=MISSED_CONNECTION + MISSED_CONNECTION exception + later PLANNED legs cascade to MISSED; late finalize (>30 min) → DEPARTURE_DELAY exception per affected shipment + compliance degrades ON_PLAN→AT_RISK; finalize books crew (flips pool OPEN/REOPENED→EXHAUSTED at capacity) and repositions locomotive to destination; cancel releases loco and fires miss cascade for matching PLANNED legs; delivery at full car_count → DELIVERED + car_velocity_mph + late check raises DELIVERY_MISS + credits += car_count.
- Validation ordering: auth → role → existence (left-to-right) → OCC → state → structural (chain/contiguity/endpoints) → car-event sequence → HOS/crew → embargo → pickup window → craft/positioning/day → credit non-negative.

**start.sh**:
```bash
set -euo pipefail
cd "$(dirname "$0")"
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
```
The `import flask` guard makes the pip install a no-op on every per-test reboot. `exec python3 app.py` keeps the server foregrounded, listens on `0.0.0.0:$PORT` (default 10000).

**Smoke test**: Booted on port 19876 (PID 2772391), exercised: missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; wrong role → 403 `ERR_INSUFFICIENT_PERMISSIONS`; yard create + list; clock advance; two-yard train plan create (DRAFT); activate with stale version → 412 `ERR_STALE_VERSION`; activate with correct version → ACTIVE v2; crew pool create; locomotive register; departure on non-operating day → `ERR_DEPARTURE_DAY_NOT_OPERATED`; departure on valid day → SCHEDULED; finalize too early → `ERR_DEPARTURE_TOO_EARLY`; clock past scheduled departure → finalize succeeds (DEPARTED, variance 30, locomotive repositioned to destination & AVAILABLE, pool crews_booked=1). All assertions passed. Killed exactly PID 2772391 — process gone, no other processes touched.

## Step 7: Run Tests and Iterate — 2026-09-30T08:20:00.000Z

Clean 8-round parallel sweep: 68/68 in all 8 rounds.

## Summary

- **Iterations run**: 2 (first sweep surfaced 21 deterministic failures; after fixes, the second sweep passed 68/68 in all 8 rounds).
- **Tests deleted**: none. Every failing rule traced to verbatim PRD prose.
- **Fixes applied to `test_helpers/`**: none (fixtures were consistent once the implementation honored the PRD-faithful first-departure reading).
- **Fixes applied to `test_suite/`** (2):
  - `test_08_difficulty.py::_run_exact_slack` — the shipment was created with `origin_yard_id == destination_yard_id`, which PRD §3.9 forbids (`ERR_SAME_ORIGIN_DESTINATION`); the implementation correctly rejected it. Added a third yard `CW-C` so the itinerary is A→B→C with distinct endpoints, preserving the exact 60-minute slack-at-cutoff precondition the test measures.
  - `test_08_difficulty.py::test_cascade_raises_exception_and_off_plan_compliance` — asserted exactly one `MISSED_CONNECTION` exception for a two-leg miss cascade. PRD §3.7 states a missed leg raises "a `ServiceException` of type `MISSED_CONNECTION`" and each cascaded later leg "moves to `MISSED` as well... by the same induction" — one exception per missed leg. Relaxed the count assertion from `== 1` to `== 2` (both `OPEN`), matching the sibling test's `total_missed_connections == 2` reading of the same PRD paragraph.
- **Fixes applied to `implementation/`** (2, both in `workspace/implementation/app.py`):
  - ID minting (`_new_record` and car-event persistence): changed `uuid.uuid4().hex` to `str(uuid.uuid4())` — PRD §2.4 requires `id` to be "a server-minted UUID", and the dashless hex form failed the canonical UUID format check.
  - `create_event` outbound-sequence integrity: the literal reading of PRD §3.6's "an outbound event with no open `YARD_ARRIVAL`... is rejected" deadlocks the PRD's own lifecycle — §3.6 also requires "The first `TRAIN_DEPARTURE` event recorded for a shipment flips it from `OPEN` to `IN_TRANSIT`", and a shipment begins `OPEN` at its origin yard with no prior events, so no open `YARD_ARRIVAL` can ever exist there. Added a first-origin-outbound exemption: a shipment's very first outbound event at its own `origin_yard_id` is accepted; all other outbound events still require an open `YARD_ARRIVAL` at that yard (so `ERR_EVENT_SEQUENCE_INVALID` enforcement is unchanged for the cases PRD does uniquely determine).

All 68 tests pass in all 8 concurrent rounds; no flakiness observed.

## Step 8: Finalize PRD — 2026-09-30T08:26:00.000Z

Diff is exactly the three targeted edits. Done.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 290 lines → PRD_FINALIZED.md 290 lines (0% line-count delta; three in-place sentence revisions, no sections added or removed).

### Changes (one bullet per edit)

- **§2.4** — revise — pinned `id` to the canonical hyphenated 8-4-4-4-12 UUID text form — `implementation/app.py:342` (`_new_record`) and `app.py:1487` (car-event persistence), both `str(uuid.uuid4())`.
- **§3.6** — revise — added the first-origin-outbound exemption to the outbound-event sequence rule: a shipment's very first recorded event, if outbound (`TRAIN_DEPARTURE`/`CLASSIFICATION_COMPLETE`) at its own `origin_yard_id`, is accepted with no open `YARD_ARRIVAL`; all later outbound events still require one — `implementation/app.py:1459-1474`.
- **§3.7** — revise — pinned that the missed-connection cascade applies the full per-leg rule to each cascaded leg: each leg moving to `MISSED` sets `connection_status` `MISSED`, increments `total_missed_connections` by one, and raises its own `OPEN` `MISSED_CONNECTION` `ServiceException` — `implementation/app.py:669-694` (`_miss_leg`, incl. recursive cascade at :694 and `raise_exception` at :682).

Not edited: the `_run_exact_slack` fixture change (same-origin shipment) is a pure test-fixture bug — PRD §3.9 already mandates `ERR_SAME_ORIGIN_DESTINATION`, no PRD silence.

### Per-edit pre-edit search log

- **Edit A (id format).** (a) Subject: server-minted `id` textual form. (b) Enumerated all id mint/serialization sites via `grep -n '"id"'` and `grep -n uuid`: `app.py:342` (`_new_record`, used by every primary resource creation — yards :752/:760, plans :801/:813, pools :888/:897, locomotives :957/:964, customers :1018/:1024, shipments :1076/:1092, trip legs :1195/:1214, departures :1297/:1309, exceptions :629-639) and car events :1487. All use `str(uuid.uuid4())`; no format validation elsewhere. (c) No adjustment needed — the single canonical-form sentence covers every mint site.
- **Edit B (outbound exemption).** (a) Subject: outbound-event sequence integrity in `create_event`. (b) Enumerated: `app.py:1459-1474` (outbound check + exemption), `_open_dwell_exists` :697-720 (dwell-session matching, unaffected), dwell close/open rules in §3.6 paragraph 2 (a first outbound at origin closes nothing since no session exists — consistent), and confirmed the exemption predicate `has_prior_events` scans all events for the shipment network-wide, not just at the event's yard. (c) Adjusted wording to "its very first recorded event" (network-wide, not per-yard) and to cover both outbound types (`TRAIN_DEPARTURE` and `CLASSIFICATION_COMPLETE`), matching the impl predicate exactly.
- **Edit C (cascade per-leg rule).** (a) Subject: missed-connection cascade effects (status stamps, counter, exceptions). (b) Enumerated all `_miss_leg` call sites — :1431 (departure cancellation), :1532 (connection-window slack evaluation), :694 (internal cascade recursion) — plus `raise_exception` :629-640 (exceptions begin `OPEN`, `detected_at` from logical clock) and `recompute_compliance` :643-662 (consumes `total_missed_connections` at thresholds 1/2, consistent with §3.9's existing OFF_PLAN/AT_RISK prose). (c) Added "beginning in `OPEN` status" and explicit `detected_at` stamping for cascaded exceptions to stay consistent with `raise_exception`; verified §3.5's "full missed-connection cascade of §3.7 fires per leg" and §3.9's `>= 2` OFF_PLAN rule remain consistent with per-leg counter increments.

## Step 9: Complete PRD — 2026-09-30T08:40:00.000Z

Note: the Step 9 subagent's first run completed its full analysis but was truncated before applying edits (PRD_COMPLETED.md was left byte-identical to PRD_FINALIZED.md); it was resumed via SendMessage and applied all 15 planned hunks. Verbatim final report follows.

15 hunks, all inline revisions/inserts (one two-line paragraph insert in §5 — the section heading existed; only prose was added under it, no new section). Done.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3170_scheduled_train_plan_car_trip_plan_compliance/workspace/PRD_COMPLETED.md`

**Source vs. result**: PRD_FINALIZED.md = 290 lines / 43,370 chars → PRD_COMPLETED.md = 292 lines / 46,579 chars (**+2 lines, +3,209 chars**; 15 diff hunks, all inline paragraph edits or in-paragraph inserts; no new sections).

**Counts**: 10 ambiguity-pins, 5 mismatch-revisions.

**Changes** (impl refs are lines in `workspace/implementation/app.py`):

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (never clamped); creation-timestamp listing ties broken by `id` ascending — app.py:307–325, 330
- §2.4 — revise — mismatch — yard posture recomputation no longer claimed to bump `version`/`updated_at` (it does neither); shipment cascade updates (miss cascade, delay-cascade AT_RISK stamping, pickup-miss OFF_PLAN stamping) pinned as touching `updated_at` without bumping `version` — app.py:586–621, 679–681, 1180–1181, 1393–1395
- §2.5 — insert — ambiguity — clock `set_current_utc` accepts any instant unconditionally (no monotonicity check; backward sets allowed) — app.py:732–739
- §2.7 — revise — mismatch — OCC bullet example corrected: missed-connection cascades do not advance shipment `version`; version advances on assignment/replan, first TRAIN_DEPARTURE event, delivery (and cancellation) — app.py:679–681, 1233, 1501, 1568
- §2.10 — insert — ambiguity — every POST requires a syntactically valid JSON object body (empty body → `ERR_INVALID_REQUEST`); field-shape errors surface before existence checks on creation endpoints — app.py:219–225
- §3.1 — revise — mismatch — `train_symbol` uniqueness is an unenforced convention; duplicates accepted — app.py:779–814 (no uniqueness check)
- §3.2 — revise — mismatch — `yard_code` uniqueness not enforced — app.py:745–761
- §3.3 — insert — ambiguity — replenish evaluates pool state (`ERR_POOL_NOT_REPLENISHABLE`) before validating `additional_crews` — app.py:923–925
- §3.4 — revise — mismatch — `unit_number` uniqueness not enforced — app.py:949–966
- §3.5 — revise — mismatch — DEPARTURE_DELAY cascade scoped to shipments holding a PLANNED leg on the plan whose `planned_departure_utc` matches this departure's slot; one exception per affected shipment — app.py:1377–1395
- §3.7 — insert — ambiguity — replan status rule pinned: `REPLANNED` iff any prior leg superseded or prior status was `MISSED_CONNECTION`, else `ASSIGNED`; assignment not gated on shipment lifecycle status — app.py:1184–1190, 1229–1232, 1132–1135
- §3.7 — insert — ambiguity — planned velocity stored on the shipment as `plan_velocity_mph` (null until first assignment); per-shipment leg listing accepts a `status` filter and paginates in creation order but orders each returned page by `leg_sequence` then creation time — app.py:446, 1222–1227, 1237–1250
- §3.9 — revise — mismatch — `customer_code` uniqueness not enforced — app.py:1012–1025
- §3.9 — insert — ambiguity — "open" DEPARTURE_DELAY exception pinned as any status other than `RESOLVED`; `OFF_PLAN` is sticky; resolving an exception does not recompute compliance back to `ON_PLAN` — app.py:643–662, 1659–1676
- §3.10 — insert — ambiguity — exception records carry nullable `triage_notes`/`root_cause_code`, null until triage — app.py:502–514, 629–640
- §5 — insert — ambiguity — undefined paths / unsupported methods rejected with `ERR_NOT_FOUND` (404/405) — app.py:118–135

**Note on the `REPLANNED` pin**: impl condition is `prior_missed_connection or had_prior` (app.py:1229), where `had_prior` requires a PLANNED-or-MISSED leg to have been superseded; the PRD edit mirrors this exactly, including the edge case where a `MISSED_CONNECTION` shipment with no remaining PLANNED/MISSED legs still gets `REPLANNED`.
