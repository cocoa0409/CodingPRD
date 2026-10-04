# Barrel Aging Inventory Planning API — Product Requirements Document

## 1. Introduction

Distillation is a business of deferred decisions. The volume a distillery lays down today becomes salable product years later, and no operational lever can accelerate maturation once a barrel is filled. This document specifies the Barrel Aging Inventory Planning API: the system of record for that deferral, covering capacity expansion projects whose construction lag is measured in seasons, rickhouses whose floor-by-floor microclimates shape evaporation, and the barrels themselves as they move from cooperage intake through aging, sampling, blending, and withdrawal from bond.

The API serves eight operational roles spanning planning, warehouse operations, blending, customer-facing private selection, and bonded-warehouse compliance. It tracks two parallel volume doctrines for every barrel — a chronological ledger of recorded events and a statutory rate-table projection — because tax reporting requires both. It enforces age-statement obligations at blend time, segregation of duties across report preparation and acceptance, and reservation quotas for single-barrel programs. All business resources are mounted under the `/barrel-aging` prefix; the platform's logical-clock utility sits outside that prefix at `/_clock/set_current_utc`.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response envelopes, pagination, time conventions, resource metadata, precision doctrine, concurrency control, identifier resolution, structural cascades, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly eight roles: `DistilleryPlanner`, `OperationsDirector`, `WarehouseManager`, `MasterBlender`, `ProgramDirector`, `BondedPreparer`, `ComplianceOfficer`, and `PlatformAdmin`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

For all eight roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit trail — as `prepared_by_user_id`, `filed_by_user_id`, and `decided_by_user_id` on bonded-period reports — and the segregation-of-duties rule in §3.7 compares one operator's identifier against another's, but `X-User-ID` is never compared against any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100, and a `limit` outside that range is a payload-shape violation rejected with `ERR_VALIDATION`. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

Individual list endpoints accept optional filter parameters that narrow the result set to exact matches: `expansion_project_id` and `posture` on the rickhouse list; `status` on the occupancy lists; `maturation_status`, `custody_status`, and `spirit_type` on the barrel list; `state` on the barrel-reservation, blend-batch, program-reservation, and bonded-report lists; `kind` on the assessment list; and `label_id` on the blend-batch list.

### 2.4. The Logical Clock and the Uniform Calendar

All timestamps in this system are instants of a **logical clock**, never the wall clock. Before any clock call the server's clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. The clock is monotonic non-decreasing: a `PlatformAdmin` advances it through the clock-setting capability by supplying `to_iso8601`, and an attempt to set it earlier than the current instant is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). A successful set responds with the new `current_utc` and immediately re-evaluates every lazy auto-transition in the system.

Calendar arithmetic is uniform by design: every month is 30 days and every year is 365 days. No calendar-month or leap-year logic exists anywhere — construction lags, maturation minimums, seasoning durations, evaporation blocks, reservation windows, and age calculations all count fixed-length days.

Three families of transitions are lazy rather than event-pushed: barrel maturation eligibility, reservation expiry, and rickhouse posture flips. Each is re-evaluated on every clock-set and again on every read of the affected entity, so a client reading a barrel, a reservation, a program, or a rickhouse always observes its derived state as of the current logical clock.

### 2.5. Common Resource Properties and Versioning

Every primary resource carries four system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, in the same format, refreshed on any mutation; and `version`, an integer that increments by one on every mutation of the resource. Two record types are the exception: slot occupancies and barrel assessments carry only `id` and `created_at`, because each is an immutable fact once written — `updated_at` and `version` are absent on both.

Every state transition, cascade touch, and ledger event described in §3 is a mutation of the entities it names: where a workflow calls out a version increment or a refreshed timestamp, §2.5's semantics are what it means.

Lifecycle fields are null until the event that fills them: `approved_at` and `commissioned_at` stay null until approval and commissioning; `validated_at` stays null until a batch's first validation, and `committed_at` and `final_blend_volume_liters` stay null until commit; `withdrawn_at` and `withdrawn_volume_liters` stay null until withdrawal. An occupancy's `end_at` is null while the occupancy is open, a barrel's `current_slot_id` is null when no occupancy is open, and an omitted `quality_score` is null.

### 2.6. Volume Arithmetic: Precision and Rounding Doctrine

All volumes are liters expressed as decimal numbers; the domain is entirely money-free. Three rounding doctrines coexist, and the differences are contractual:

- **The barrel ledger rounds after every event.** As the ledger replays each recorded event (§3.3), the running volume is floored at zero and rounded to two decimal places, round half up, after every single event — never once at the end.
- **The statutory projection rounds once at the end.** The rate-table projection (§3.3) carries full precision through every block and rounds a single time — two decimal places, round half up — after the last block is applied.
- **Bonded reports round per barrel, then sum.** Opening-inventory and both loss figures round each barrel's contribution to two decimal places, round half up, before summing (§3.7). The alternative order — sum first, round once — is a rejected variant that yields different cents.

Warehouse heat factors are likewise two-decimal values (§3.1). Volumes in API responses are plain JSON numbers, never strings.

### 2.7. Optimistic Concurrency Control on Parent Versions

Three write operations are guarded by optimistic concurrency control on a parent entity's `version`, and each names its expectation field explicitly:

- Adding a component to a blend batch — `POST /barrel-aging/blend-batches/{id}/components` — requires `expected_blend_batch_version` carrying the batch `version` the client last observed. If the batch's current `version` differs, the request is rejected with `ERR_STALE_BLEND_BATCH_VERSION` (HTTP 412).
- Creating a reservation under a program — `POST /barrel-aging/private-selection-programs/{id}/reservations` — requires `expected_program_version` carrying the program `version` the client last observed; a mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).
- Rotating a barrel — `POST /barrel-aging/barrels/{id}/rotations` — requires `expected_barrel_version` carrying the barrel `version` the client last observed; a mismatch is rejected with `ERR_STALE_BARREL_VERSION` (HTTP 412).

The rejection means the client's view is stale: another write has advanced the parent's `version` since the client last read it, and applying the client's intention would overwrite a state it never observed. Re-reading the parent and retrying with the fresh `version` succeeds whenever the business rules still hold. No endpoint outside these three accepts a version-expectation field.

### 2.8. Nested Resource Retrieval and Identifier Resolution

Requests that target nested resources are validated left to right along the path. Each identifier in the path must resolve to an existing resource before the next is examined, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. Identifiers supplied in the request body — `slot_id` on barrel creation, `to_slot_id` on rotation, `label_id` on batch proposal, `barrel_id` on components and reservations — are held to the same rule: each must name an existing entity. Payload-shape validation runs before any of these existence checks (§2.10), so a malformed body draws `ERR_VALIDATION` even when its identifiers would not have resolved.

### 2.9. Structural Cascades Between Projects, Rickhouses, and Slots

The system's structure is a three-level tree — a capacity expansion project owns one rickhouse, which owns a grid of warehouse slots — while barrels, blend batches, private selection programs, and bonded-period reports stand as cross-cutting aggregates that reference the tree through flat identifiers. State changes propagate along this structure in both directions. Downward: approving a project creates its rickhouse in `PLANNED` posture with the project's physical specification copied across; commissioning the project activates the rickhouse and materializes the full slot grid. Upward: every barrel occupancy that opens or closes re-derives the rickhouse's `occupied_slots` and can flip its posture between `OPERATING` and `FULL`. These cascades are side effects of the triggering operation, specified per workflow in §3; derived fields such as `occupied_slots` and `posture` recompute from the underlying records rather than being written directly.

### 2.10. Validation Evaluation Order

When several checks fail at once, the rejection a request receives is deterministic. The server evaluates ten ordered gates:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the eight declared roles (`ERR_UNAUTHENTICATED`, HTTP 401).
2. **Authorization** — the role is listed among the endpoint's authorized roles (`ERR_FORBIDDEN_ROLE`, HTTP 403).
3. **Payload shape** — all required input fields are present, no undeclared fields appear, types match, enum values are valid, numeric ranges hold (`char_level` within 1 to 4, `drawn_volume_liters` above zero, `period_start` before `period_end`, `scheduled_bottling_date` strictly in the future, `limit` within 1 to 100), and kind-conditional assessment inputs are present (`ERR_VALIDATION`, HTTP 400).
4. **Existence** — every path identifier and every body-supplied identifier resolves to an existing entity (`ERR_NOT_FOUND`, HTTP 404).
5. **Optimistic concurrency** — any version-expectation field equals the parent entity's current `version` (the three HTTP 412 errors of §2.7).
6. **State-machine preconditions** — the target entity's current state permits the requested transition, checked first; then the cross-entity readiness gates: rickhouse posture `OPERATING` for placements and rotations, construction lag elapsed for commissioning, period closed for reconciliation, label `ACTIVE` for blend validation and commit (`ERR_INVALID_STATE_TRANSITION`, `ERR_RICKHOUSE_NOT_OPERATING`, `ERR_CONSTRUCTION_LAG_NOT_ELAPSED`, `ERR_LABEL_NOT_ACTIVE`, all HTTP 409).
7. **Compliance** — the age-statement obligation, the covering-report requirement, report-period overlap, and segregation of duties (`ERR_AGE_STATEMENT_VIOLATION` is HTTP 422; `ERR_COVERING_REPORT_NOT_FILED` and `ERR_REPORT_PERIOD_OVERLAP` are HTTP 409; `ERR_SEGREGATION_OF_DUTIES` is HTTP 403).
8. **Capacity and conflict** — slot-occupancy overlap, the thirty-day sampling buffer, reservation quota, barrel eligibility, duplicate blend components, and clock regression (`ERR_SLOT_OCCUPANCY_OVERLAP`, `ERR_SAMPLE_BUFFER_VIOLATION`, `ERR_RESERVATION_QUOTA_EXHAUSTED`, and `ERR_DUPLICATE_BLEND_COMPONENT` are HTTP 409; `ERR_BARREL_NOT_ELIGIBLE` and `ERR_CLOCK_REGRESSION` are HTTP 422).
9. **Referential integrity on destructive actions** — no active reservation before withdrawal, no committed blend component before dumping (`ERR_BARREL_RESERVED`, `ERR_BARREL_IN_COMMITTED_BLEND`, HTTP 409).
10. **Volume sufficiency** — draws and evaporation readings checked against the ledger volume (`ERR_INSUFFICIENT_VOLUME`, `ERR_ASSESSMENT_VOLUME_INCONSISTENT`, HTTP 422).

An earlier gate masks every later one. A malformed body on a non-existent resource returns `ERR_VALIDATION`, never `ERR_NOT_FOUND`. A stale parent version surfaces before any state-machine complaint. Within gate 6 the entity's own from-state is checked before the cross-entity readiness gates, and a label that is not `ACTIVE` surfaces as `ERR_LABEL_NOT_ACTIVE` before the age-statement compliance of gate 7 is examined. Within gate 8 the reservation quota is examined before barrel eligibility, so an exhausted program answers `ERR_RESERVATION_QUOTA_EXHAUSTED` even when the named barrel would also fail eligibility.

## 3. Business Logic & Workflows

This section walks the operational workflows in the order the business lives them: capacity is planned first, barrels are filled and moved, maturation is measured, barrels are dumped and withdrawn, blends are composed under age-statement law, private selection runs its reservation market, and the bonded ledger is reconciled and filed. Rules stated in §2 are referenced rather than repeated.

### 3.1. Planning Capacity: From Project Proposal to a Commissioned Rickhouse

A `DistilleryPlanner` opens the capacity conversation by proposing an expansion project: a `name` for the project; a `region_code` tagging its location (such as KY or TN — the location axis along which evaporation varies); the rickhouse's physical spec as `floors`, `rows_per_floor`, and `positions_per_row`, each at least 1; the `construction_lag_months` between approval and commissionability, at least 1 and counted in 30-day months; and the `planned_annual_distillation_liters` the site is expected to absorb — the distillation volume decision made years ahead of demand, zero or more. The project is created in `PROPOSED`.

An `OperationsDirector` approves a `PROPOSED` project, moving it to `APPROVED`. Approval stamps `approved_at` with the current logical clock, increments the project's `version`, and cascades: a rickhouse is created in `PLANNED` posture with `name`, `region_code`, `floors`, `rows_per_floor`, and `positions_per_row` copied from the project, its `expansion_project_id` pointing back to the project that spawned it. The rickhouse's `total_slots` is the product of those three dimensions.

Commissioning is the second gate. The same director commissions an `APPROVED` project — but only once the construction lag has fully elapsed: the current logical clock must have reached `approved_at` plus `construction_lag_months` times thirty days, and an early attempt is rejected with `ERR_CONSTRUCTION_LAG_NOT_ELAPSED` (HTTP 409). Commissioning stamps `commissioned_at`, increments the project's `version`, moves the project to its terminal `COMMISSIONED` state, and fires a multi-part cascade: the rickhouse transitions `PLANNED` → `OPERATING`; the full slot grid materializes — exactly the product of `floors`, `rows_per_floor`, and `positions_per_row` slots, one per combination, enumerated in `floor_index`, then `row_index`, then `position_index` ascending order, each index 1-based with `floor_index` 1 at ground level; every slot records its `rickhouse_id` and a computed `heat_factor`; and the rickhouse's `occupied_slots` initializes to zero with its posture recomputed — still `OPERATING` at zero occupancy. A rickhouse's slot listing always returns this deterministic floor-row-position order.

Heat is altitude. Each slot's `heat_factor` is one plus five one-hundredths for every floor above ground — one plus 0.05 multiplied by the slot's `floor_index` minus one — rounded to two decimal places: exactly 1.00 on the ground floor, 1.05 on the second floor, 1.10 on the third, and so on. Higher floors run hotter, and the statutory evaporation of §3.3 multiplies by this factor.

### 3.2. Filling, Placing, and Rotating Barrels

Barrel intake belongs to the `WarehouseManager`. Filling a barrel takes a `slot_id` to place it in; the cooperage specification — `wood_origin` (one of `AMERICAN_WHITE_OAK`, `FRENCH_OAK`, `MIZUNARA`), `seasoning_months` (zero or more 30-day months; eighteen or more earns the statutory evaporation discount of §3.3), and `char_level` (an integer from 1 to 4); the spirit specification, `spirit_type` (one of `BOURBON`, `RYE`, `TENNESSEE`, `SINGLE_MALT`) and `fill_proof` (above zero); the `fill_volume_liters` (above zero); and the `min_maturation_months` (zero or more) the spirit must rest before it can be called mature. The barrel's `fill_date` is the logical clock at creation; it begins `BONDED` in custody and `FILLED` in maturation.

Placement is part of the same request. The system opens a slot occupancy on the named slot with `move_reason` `INITIAL_FILL`, stamping `start_at` with the current clock and leaving `end_at` null — a null `end_at` is exactly what makes an occupancy's `status` `OPEN` rather than `CLOSED`, and occupancy intervals are half-open: `start_at` inclusive, `end_at` exclusive. Within that same request the barrel's maturation advances `FILLED` → `AGING`, so the creation response already shows `AGING`. The rickhouse's `occupied_slots` increases by one and its posture recomputes — the placement may be the one that fills the house.

Two gates protect placement. The destination slot's rickhouse must be `OPERATING`: a house still `PLANNED` or already `FULL` rejects the placement with `ERR_RICKHOUSE_NOT_OPERATING` (HTTP 409). And the slot must be free: if an existing `OPEN` occupancy on that slot overlaps the new interval, the request fails with `ERR_SLOT_OCCUPANCY_OVERLAP` (HTTP 409) — because intervals are half-open, adjacency is allowed, so a new occupancy starting exactly when the old one ends is not an overlap.

A rickhouse's posture is derived, never set directly. Its `occupied_slots` counts the rickhouse's slots that hold an `OPEN` occupancy, and its `total_slots` is the full grid capacity. While its parent project is uncommissioned the posture is `PLANNED`. Once commissioned, the posture is `FULL` the moment `occupied_slots` reaches `total_slots` — equality is the trigger, so a house one slot short of capacity remains `OPERATING` — and it returns to `OPERATING` whenever occupancy drops back below capacity. Posture recomputes after every occupancy that opens or closes, on commissioning, and on read.

Rotating a barrel moves it to a different slot. The `WarehouseManager` supplies `to_slot_id` and — per §2.7 — `expected_barrel_version`. Rotation closes the barrel's currently `OPEN` occupancy (its `end_at` is stamped with the current clock and its `status` becomes `CLOSED`) and opens a successor occupancy on the destination slot with `move_reason` `ROTATION`; the barrel's `version` increments, and posture recomputes on both the source and destination rickhouses. The same two placement gates apply to the destination: the target rickhouse must be `OPERATING`, and the target slot must be free of an overlapping open occupancy.

A barrel never stores where it lives. Its `current_slot_id` is computed — the `slot_id` of its `OPEN` occupancy, or null when no occupancy is open — and the occupancy records, keyed by `barrel_id` and `slot_id`, are the source of truth. A barrel's occupancy history and a slot's occupancy history are both listed in `start_at` ascending order.

### 3.3. Maturation, the Angel's Share, and Barrel Assessment

Every barrel carries two independent state dimensions. The maturation dimension, `maturation_status`, runs `FILLED` → `AGING` → `MATURE_ELIGIBLE`, with `DUMPED` as a terminal exit from either `AGING` or `MATURE_ELIGIBLE`. The custody dimension, `custody_status`, runs `BONDED` → `WITHDRAWN`. The two evolve independently with a single join gate — withdrawal demands the barrel be `DUMPED` first (§3.4).

Maturation eligibility is lazy. When the current logical clock reaches the barrel's `fill_date` plus `min_maturation_months` times thirty days, the barrel becomes `MATURE_ELIGIBLE` — not by push notification, but by re-evaluation on every clock-set and on every read of the barrel (§2.4).

Every barrel also carries two volume figures, and they answer different questions. `current_volume_ledger_liters` is the volume of record — the number withdrawals, blends, and loss reporting all trust. `current_volume_statutory_liters` is a rate-table projection used for bonded comparison and what-if planning. On identical data the two diverge, deliberately.

The ledger replays history. It starts at the barrel's `fill_volume_liters` and replays, in chronological order, every recorded event touching the barrel: an `EVAPORATION_READING` assessment resets the running volume outright to its `measured_volume_liters` — an authoritative measurement of what is actually in the barrel, not a delta; a `QUALITY_SAMPLE` subtracts its `sample_draw_liters`; the commit of a blend batch containing the barrel subtracts that component's `drawn_volume_liters` at the batch's `committed_at` instant; and the abort of a previously committed batch adds the same `drawn_volume_liters` back at the abort instant. Events are ordered by their event instant, ties broken by earliest `created_at`. After every single event the running volume is floored at zero and rounded to two decimal places, round half up, before the next event applies. The ledger recomputes on every assessment, on every blend commit or abort touching the barrel, and on every read of the barrel.

The statutory projection replays no history; it decays. Starting from the same `fill_volume_liters` at full precision, it divides the time since fill into consecutive ninety-day blocks — the first covering the ninety days from fill, the second the next ninety, and so on, each block half-open — and applies a block only when it has fully elapsed, meaning the block's end day is at or before the evaluation instant. For each counted block, the rate is assembled from four factors. The season of the block's first day: December, January, or February is WINTER with a multiplier of 0.7; March, April, or May is SPRING at 1.0; June, July, or August is SUMMER at 1.5; September, October, or November is AUTUMN at 1.0. The barrel's age at the block's first day, in whole years — days since fill divided by 365 and rounded down — maps to an age multiplier of 1.2 under two years, 1.0 at two years or more but under six, and 0.8 at six years or more. The heat of the barrel's location at the evaluation instant — the `heat_factor` of the slot holding its `OPEN` occupancy, or of the slot from its most recently `CLOSED` occupancy when none is open — scales the rate for rickhouse microclimate. And a base rate of one percent (0.01) per block anchors the table. The block's rate is the base rate multiplied by the heat factor, the season multiplier, and the age multiplier; when the barrel's `seasoning_months` is at least eighteen, the result is further multiplied by 0.95, the well-seasoned-wood discount; and the final rate is capped at 0.05, so no block ever removes more than five percent of the running volume. The running volume is then multiplied by one minus that rate. After all counted blocks apply, the projection is floored at zero and rounded exactly once — two decimal places, round half up. It is recomputed on every read of the barrel at the current logical clock, and the bonded report reconciliation consults it at period boundaries (§3.7).

Assessments are how the ledger learns. A `WarehouseManager` records an assessment against a barrel with a `kind` of `EVAPORATION_READING` or `QUALITY_SAMPLE`. An evaporation reading requires `measured_volume_liters`, the authoritative gauge of what remains; it may not exceed the barrel's current ledger volume — a reading that does is rejected with `ERR_ASSESSMENT_VOLUME_INCONSISTENT` (HTTP 422). A quality sample requires `sample_draw_liters` (above zero), the volume drawn and consumed, and may carry an optional `quality_score`, an integer from 0 to 100 that is null when omitted and meaningful only for samples. Omitting the input its `kind` requires is a payload-shape failure (`ERR_VALIDATION`). Sampling is rate-limited per barrel: a `QUALITY_SAMPLE` recorded fewer than thirty days after the same barrel's previous `QUALITY_SAMPLE` is rejected with `ERR_SAMPLE_BUFFER_VIOLATION` (HTTP 409); exactly thirty days is allowed. Each assessment stamps `assessed_at` at creation and increments the barrel's `version`. A barrel's assessments list in `assessed_at` ascending order.

### 3.4. Dumping and Withdrawal from Bond

Dumping empties a barrel for bottling and ends its maturation. A `WarehouseManager` may dump a barrel in either `AGING` or `MATURE_ELIGIBLE`; from both states the destination is `DUMPED`, and both paths enforce the same referential guard: if any blend component naming this barrel belongs to a `COMMITTED` batch, the dump is rejected with `ERR_BARREL_IN_COMMITTED_BLEND` (HTTP 409). A dump cascades: the barrel's `OPEN` occupancy, if any, closes — `end_at` stamped with the current clock, `status` becoming `CLOSED`, and `current_slot_id` becoming null; the affected rickhouse's `occupied_slots` decreases by one; and the house's posture recomputes, flipping `FULL` → `OPERATING` when occupancy falls below capacity. The barrel's `version` increments.

Withdrawal takes a barrel out of bond, and it is where the two state dimensions join. A `WarehouseManager` withdraws only a barrel whose maturation is `DUMPED` — attempting withdrawal before the dump fails the join gate with `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — and whose custody is still `BONDED`. Two further guards apply. Compliance: there must exist a bonded-period report in `FILED` or `ACCEPTED` state whose period covers the current instant — `period_start` at or before now and `period_end` at or after now — otherwise the withdrawal is rejected with `ERR_COVERING_REPORT_NOT_FILED` (HTTP 409). Referential: no reservation on this barrel may be `ACTIVE`, else `ERR_BARREL_RESERVED` (HTTP 409). Withdrawal stamps `withdrawn_at` with the logical clock, freezes `withdrawn_volume_liters` to the barrel's current ledger volume — the tax determination at withdrawal is made on this frozen figure — moves custody to the terminal `WITHDRAWN`, and increments the barrel's `version`.

### 3.5. Labels, Blend Batches, and the Age-Statement Obligation

A `MasterBlender` registers a label with a `name`, an `age_statement_years` declared in whole 365-day years (zero or more), and a `spirit_type`. The age statement is immutable — no update endpoint exists — and it constrains every blend bottled under the label: each component barrel's age at the scheduled bottling date must be at least the statement. A new label is `REGISTERED`; activation by a `MasterBlender` moves it `REGISTERED` → `ACTIVE` and increments its `version`. Only an `ACTIVE` label may be blended.

Proposing a blend batch takes a `label_id` and a `scheduled_bottling_date` that must lie strictly after the current logical clock at creation — a bottling date in the past or present is a payload-shape failure (`ERR_VALIDATION`). The batch is created `PROPOSED`.

Components are added while the batch is `PROPOSED`: each names a `barrel_id` and a `drawn_volume_liters` above zero, and carries `expected_blend_batch_version` per §2.7. Every add increments the batch's `version`, which is precisely why the expectation field exists. Two constraints guard composition: the same barrel may not appear twice in one batch — a repeat is rejected with `ERR_DUPLICATE_BLEND_COMPONENT` (HTTP 409) — and the draw may not exceed the barrel's current ledger volume, else `ERR_INSUFFICIENT_VOLUME` (HTTP 422); the volume check is made when the component is added and made again at commit. Each component records its `blend_batch_id`, and a batch's components list in `created_at` ascending order.

Validation moves the batch `PROPOSED` → `VALIDATED`. The batch must contain at least one component, else `ERR_VALIDATION`. The batch's label must be `ACTIVE` — a cross-entity gate that fails with `ERR_LABEL_NOT_ACTIVE` (HTTP 409) and is evaluated before the age-statement compliance check. Then every component is examined: the barrel's age at the `scheduled_bottling_date` — the days between `fill_date` and that date, divided by 365, rounded down to whole years — must be at least the label's `age_statement_years`; a component whose age is exactly the statement satisfies the obligation, and any younger component fails validation with `ERR_AGE_STATEMENT_VIOLATION` (HTTP 422). Every component's spirit type must also match the label's `spirit_type`; a mismatch is `ERR_VALIDATION`. A successful validation stamps `validated_at` with the current clock and increments the batch's `version`.

A validated batch is not final. Revising sends it `VALIDATED` → `PROPOSED`, increments the `version`, and leaves its components in place — retained and editable again under the proposal-time rules above.

Committing is the point of no return. From `VALIDATED`, the commit re-checks that the label is still `ACTIVE`, re-checks every component's age at the `scheduled_bottling_date` against the same inclusive obligation (a component that has fallen under-age fails with `ERR_AGE_STATEMENT_VIOLATION`), and re-checks each `drawn_volume_liters` against its barrel's current ledger volume (`ERR_INSUFFICIENT_VOLUME`). Committing then draws down the barrels: each component's barrel ledger loses its `drawn_volume_liters` — a commit-draw ledger event stamped at the `committed_at` instant — and each such barrel's `version` increments. The batch freezes `final_blend_volume_liters` as the sum of its components' drawn volumes, stamps `committed_at`, moves to `COMMITTED`, and increments its own `version`.

Abortion has two shapes. From `VALIDATED`, aborting moves the batch to `ABORTED` and increments its `version`; no barrel was drawn, so no barrel is touched. From `COMMITTED`, aborting performs full compensation: every component's `drawn_volume_liters` is added back to its barrel's ledger — an abort-restore ledger event at the abort instant — and each barrel's `version` increments, with the compensating invariant that each barrel's ledger volume returns exactly to its pre-commit value; the batch moves to `ABORTED` and increments its `version`. `COMMITTED` and `ABORTED` are the batch's terminal states — the only exit from `COMMITTED` is the abort described above.

A barrel bound into a `COMMITTED` batch is protected elsewhere in the system: it cannot be dumped (§3.4) and it is ineligible for private selection (§3.6).

### 3.6. Private Selection Programs and Barrel Reservations

A `ProgramDirector` opens a private selection program — the single-barrel offering that lets a customer choose specific barrels — with a `name`, a `spirit_type` restricting eligibility to barrels of that spirit, a `min_quality_score` (an integer from 0 to 100) flooring the barrel quality the program accepts, a `required_barrel_count` (at least 1) the program must consume to lock, and a `reservation_window_days` (at least 1) setting how long a reservation lives. The program is created `SELECTION`.

Eligibility is a ranked selector. A barrel is a candidate when it is `BONDED` in custody, `MATURE_ELIGIBLE` in maturation, of the program's `spirit_type`, free of any reservation in `ACTIVE` or `CONSUMED`, free of any component on a `COMMITTED` blend batch, and carrying a latest quality score of at least the program's `min_quality_score`. The latest quality score is the `quality_score` of the barrel's most recent `QUALITY_SAMPLE` — greatest `assessed_at`, ties broken by earliest `created_at` — and a barrel with no quality sample scores zero. Candidates rank by latest quality score descending, then `fill_date` ascending, then `created_at` ascending. The selector read returns this ranking; an empty candidate pool is not an error and answers 200 with an empty array.

The program's `available_slots` is derived: `required_barrel_count` minus its reservations in `ACTIVE`, minus its reservations in `CONSUMED`. It recomputes on reservation creation, consume, release, and expiry, and on every read of the program.

Reserving takes a `barrel_id` and — per §2.7 — `expected_program_version`. Within the conflict checks, quota comes before eligibility: when `available_slots` has reached zero the reservation is rejected with `ERR_RESERVATION_QUOTA_EXHAUSTED` (HTTP 409) before the barrel is even examined; only then does a barrel failing the eligibility predicate above draw `ERR_BARREL_NOT_ELIGIBLE` (HTTP 422). A successful reservation is created `ACTIVE`, recording its `program_id`, with `expires_at` set to its creation time plus the program's `reservation_window_days`; the new `ACTIVE` reservation drops `available_slots` by one, and the program's `version` increments.

Consuming a reservation is the customer's commitment. Only an `ACTIVE` reservation can be consumed — and because expiry is lazy, a reservation whose `expires_at` has passed has already become `EXPIRED` by the time it is read, so consuming a lapsed reservation fails the from-state check with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The barrel is re-examined at consume time: it must still be `BONDED` and `MATURE_ELIGIBLE`, and no component of it may belong to a `COMMITTED` batch; any failure is `ERR_BARREL_NOT_ELIGIBLE`. A consume moves the reservation `ACTIVE` → `CONSUMED`, recomputes `available_slots`, and increments both the reservation's and the program's `version`. It also bubbles up: when the program's count of `CONSUMED` reservations reaches `required_barrel_count`, the program itself transitions `SELECTION` → `LOCKED`, a transition that increments the program's `version` and closes the door — a `LOCKED` program accepts no further reservations, and attempts fail its state gate.

Releasing is the gentle exit. Releasing an `ACTIVE` reservation moves it to `RELEASED` and compensates the program: `available_slots` increases by exactly one, with the invariant that create-then-release leaves `available_slots` unchanged. Both the reservation's and the program's `version` increment.

Expiry is the lazy exit. When the current logical clock moves strictly past a reservation's `expires_at` — a clock exactly equal to `expires_at` does not expire it — the reservation transitions `ACTIVE` → `EXPIRED` on the next clock-set or read, `available_slots` increases by exactly one, and the program's `version` increments. `CONSUMED`, `RELEASED`, and `EXPIRED` are the reservation's terminal states.

### 3.7. Bonded-Period Reporting, Loss Accounting, and Filing Duties

Bonded warehousing answers to the tax authority in periods. A `BondedPreparer` opens a bonded-period report with a `period_start` (inclusive) and a `period_end` (exclusive) — periods are half-open — where the end must be strictly after the start, else `ERR_VALIDATION`. A new period may not overlap any existing report whose state is not `REJECTED`; an overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409), while adjacency — one report's `period_start` equaling another's `period_end` — is allowed. The report is created `OPEN`.

Reconciliation closes the books on a period, and only a closed period can be reconciled: the current logical clock must be at or after `period_end`, and an earlier attempt fails the state gate with `ERR_INVALID_STATE_TRANSITION`. Reconciling computes seven figures, moves the report `OPEN` → `RECONCILED`, records the preparer's `X-User-ID` as `prepared_by_user_id`, and increments the report's `version`.

Three of the figures are flows. `opening_inventory_liters` sums, over every barrel whose `fill_date` precedes `period_start`, that barrel's ledger volume replayed at `period_start` — each per-barrel value rounded to two decimal places, round half up, before the sum. `period_fills_liters` sums `fill_volume_liters` over barrels filled within the period. `period_withdrawals_liters` sums `withdrawn_volume_liters` over barrels withdrawn within it — both windows half-open like the period itself.

Two figures are the angel's share, computed by rival doctrines over the same barrel set: every barrel bonded at any moment overlapping the period — `fill_date` before `period_end`, and never withdrawn or withdrawn after `period_start`. For each such barrel the measurement window runs from the later of `period_start` and its `fill_date` to the earlier of `period_end` and its `withdrawn_at` — or to `period_end` when never withdrawn. For `loss_actual_liters`, the ledger of §3.3 is replayed at both window boundaries using only events strictly before each, and the drop between the two replayed volumes is reduced by what was legitimately drawn inside the window: quality-sample draws assessed within it, plus the net of commit draws and abort restores whose event instants fall within it. The remainder, floored at zero, is the barrel's actual loss. For `loss_statutory_liters`, the same barrel set and the same windows apply, but the volume at each boundary is the statutory projection of §3.3 evaluated at that instant; the barrel's statutory loss is the drop between the two projections, floored at zero. Both doctrines pin the same rounding order: each barrel's loss is rounded to two decimal places, round half up, individually, and only then summed — round per barrel, then sum; summing first and rounding once is a rejected alternative that yields different cents.

The last two figures fix the filing. `reported_loss_liters` — the loss reported to the tax authority — is pinned equal to `loss_actual_liters`; the statutory figure stands disclosed alongside for comparison only. `closing_inventory_liters` is the opening inventory plus the period's fills, minus the period's withdrawals, minus the reported loss.

Filing moves a report `RECONCILED` → `FILED` under the same `BondedPreparer` role, records the filer's `X-User-ID` as `filed_by_user_id`, and increments the `version`. Judgment belongs to a different desk: a `ComplianceOfficer` accepts a `FILED` report, moving it to the terminal `ACCEPTED`, or rejects it, moving it to `REJECTED` — and in either case the officer's `X-User-ID` must differ from the report's `filed_by_user_id`. An accept or reject attempted by the filer themselves is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a clean decision records the officer as `decided_by_user_id` and increments the `version`.

Rejection is not the end of the road. Amending moves a `REJECTED` report to `AMENDED` and increments its `version`; the amend loop returns the report to a re-fileable state, and filing accepts a report from either `RECONCILED` or `AMENDED`.

These reports also gate the outside world: a withdrawal (§3.4) stands only while some report in `FILED` or `ACCEPTED` covers the current instant — this section is where that coverage comes from.

## 4. Endpoint Definitions

Operations that create new resources — expansion projects, barrels, assessments, labels, blend batches, blend components, private selection programs, reservations, and bonded reports — return `201 Created` with the created resource. Operations that modify an existing resource, including every state transition, barrel rotation, and the clock-set capability, return `200 OK`, as do all reads. Unless otherwise noted, responses carry the created or updated resource in the envelope's `data` field; §3's narratives define each operation's full request payload and side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/barrel-aging/expansion-projects` | Propose a capacity expansion project | DistilleryPlanner |
| GET | `/barrel-aging/expansion-projects/{id}` | Read one expansion project | Any |
| POST | `/barrel-aging/expansion-projects/{id}/approve` | Approve a proposed project; cascades creation of its PLANNED rickhouse | OperationsDirector |
| POST | `/barrel-aging/expansion-projects/{id}/commission` | Commission an approved project once the construction lag has fully elapsed | OperationsDirector |
| GET | `/barrel-aging/rickhouses/{id}` | Read one rickhouse including computed occupied_slots and posture | Any |
| GET | `/barrel-aging/rickhouses` | List rickhouses; optional filters | Any |
| GET | `/barrel-aging/rickhouses/{id}/slots` | List the rickhouse's slots in deterministic floor-row-position order | Any |
| GET | `/barrel-aging/warehouse-slots/{id}` | Read one warehouse slot including computed heat_factor | Any |
| GET | `/barrel-aging/warehouse-slots/{id}/occupancies` | List occupancies of a slot | Any |
| POST | `/barrel-aging/barrels` | Fill a new barrel and place it into a slot (initial occupancy) | WarehouseManager |
| GET | `/barrel-aging/barrels/{id}` | Read one barrel including both computed volume variants | Any |
| GET | `/barrel-aging/barrels` | List barrels; optional filters | Any |
| GET | `/barrel-aging/barrels/{id}/occupancies` | List the barrel's occupancy history | Any |
| GET | `/barrel-aging/barrels/{id}/blend-components` | List blend components referencing this barrel | Any |
| GET | `/barrel-aging/barrels/{id}/reservations` | List reservations referencing this barrel | Any |
| GET | `/barrel-aging/barrels/{id}/assessments` | List the barrel's assessments | Any |
| POST | `/barrel-aging/barrels/{id}/assessments` | Record an evaporation reading or a quality sample against a barrel | WarehouseManager |
| POST | `/barrel-aging/barrels/{id}/rotations` | Rotate a barrel to a different slot (OCC-guarded) | WarehouseManager |
| POST | `/barrel-aging/barrels/{id}/dump` | Dump a barrel; closes its occupancy and frees the slot | WarehouseManager |
| POST | `/barrel-aging/barrels/{id}/withdraw` | Withdraw a dumped barrel from bond | WarehouseManager |
| POST | `/barrel-aging/labels` | Register a label with its immutable age statement | MasterBlender |
| GET | `/barrel-aging/labels/{id}` | Read one label | Any |
| POST | `/barrel-aging/labels/{id}/activate` | Activate a registered label | MasterBlender |
| POST | `/barrel-aging/blend-batches` | Propose a blend batch under a label | MasterBlender |
| GET | `/barrel-aging/blend-batches/{id}` | Read one blend batch | Any |
| GET | `/barrel-aging/blend-batches` | List blend batches; optional filters | Any |
| POST | `/barrel-aging/blend-batches/{id}/components` | Add a component barrel draw to a PROPOSED batch (OCC-guarded) | MasterBlender |
| GET | `/barrel-aging/blend-batches/{id}/components` | List a batch's components | Any |
| POST | `/barrel-aging/blend-batches/{id}/validate` | Validate a proposed batch against label state and the age statement | MasterBlender |
| POST | `/barrel-aging/blend-batches/{id}/revise` | Send a validated batch back to PROPOSED for revision | MasterBlender |
| POST | `/barrel-aging/blend-batches/{id}/commit` | Commit a validated batch, deducting drawn volumes from component barrels | MasterBlender |
| POST | `/barrel-aging/blend-batches/{id}/abort` | Abort a validated or committed batch; aborting COMMITTED restores drawn volumes | MasterBlender |
| POST | `/barrel-aging/private-selection-programs` | Open a single-barrel / private selection program | ProgramDirector |
| GET | `/barrel-aging/private-selection-programs/{id}` | Read one program including computed available_slots | Any |
| GET | `/barrel-aging/private-selection-programs/{id}/eligible-barrels` | Ranked eligible barrels for a program; empty pool returns an empty array | Any |
| POST | `/barrel-aging/private-selection-programs/{id}/reservations` | Reserve a specific barrel into a program (OCC-guarded) | ProgramDirector |
| GET | `/barrel-aging/private-selection-programs/{id}/reservations` | List a program's reservations | Any |
| POST | `/barrel-aging/reservations/{id}/consume` | Consume an active reservation; may bubble-lock the program | ProgramDirector |
| POST | `/barrel-aging/reservations/{id}/release` | Release an active reservation; compensates the program's available_slots | ProgramDirector |
| POST | `/barrel-aging/bonded-reports` | Open a bonded-period report; periods are half-open and non-overlapping | BondedPreparer |
| GET | `/barrel-aging/bonded-reports/{id}` | Read one report | Any |
| GET | `/barrel-aging/bonded-reports` | List reports; optional state filter | Any |
| POST | `/barrel-aging/bonded-reports/{id}/reconcile` | Reconcile an OPEN report, computing inventories and both loss variants | BondedPreparer |
| POST | `/barrel-aging/bonded-reports/{id}/file` | File a reconciled or amended report with the tax authority | BondedPreparer |
| POST | `/barrel-aging/bonded-reports/{id}/accept` | Accept a filed report; the acceptor must not be the filer | ComplianceOfficer |
| POST | `/barrel-aging/bonded-reports/{id}/reject` | Reject a filed report; the rejector must not be the filer | ComplianceOfficer |
| POST | `/barrel-aging/bonded-reports/{id}/amend` | Amend a rejected report, returning it to a re-fileable state | BondedPreparer |
| POST | `/_clock/set_current_utc` | Set the logical clock; re-evaluates lazy auto-transitions | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is described; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_RICKHOUSE_NOT_OPERATING` | 409 Conflict |
| `ERR_CONSTRUCTION_LAG_NOT_ELAPSED` | 409 Conflict |
| `ERR_STALE_BLEND_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BARREL_VERSION` | 412 Precondition Failed |
| `ERR_LABEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGE_STATEMENT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_COVERING_REPORT_NOT_FILED` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SLOT_OCCUPANCY_OVERLAP` | 409 Conflict |
| `ERR_SAMPLE_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_RESERVATION_QUOTA_EXHAUSTED` | 409 Conflict |
| `ERR_BARREL_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BLEND_COMPONENT` | 409 Conflict |
| `ERR_BARREL_RESERVED` | 409 Conflict |
| `ERR_BARREL_IN_COMMITTED_BLEND` | 409 Conflict |
| `ERR_INSUFFICIENT_VOLUME` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_VOLUME_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
