# Hot-N-Ready Forecast Production & Pickup Portal API — Product Requirements Document

## 1. Introduction

A Hot-N-Ready store lives and dies by a simple promise: a walk-in or portal customer gets a fresh pizza immediately, without waiting for a bake cycle. Keeping that promise profitably means producing ahead of demand — but every pizza that sits too long in the warming rack becomes waste, and every portal order that is not waiting in a heated locker when the customer arrives becomes a refund. This document specifies the API that coordinates that balancing act: forecast-driven made-ahead production planned per daypart, in-store dough and cheese preparation governed by strict proofing and resting windows, a heated self-service pickup portal with time-boxed pickup codes, and end-of-day waste reconciliation measured against a fixed target percentage of production.

The system is built around a logical, test-driveable clock. Daypart windows, proofing floors, hold-time expiry, pickup-code validity, demand-event status, and all automatic sweeps evaluate against this clock rather than the wall clock, so an operator (or an automated test harness) can replay an entire business day deterministically. Four roles share the work: a `StoreManager` plans the day and owns the catalogue, a `ShiftLead` runs the floor, a `CrewMember` works the stations, and a `Customer` interacts with the portal. Throughout, the design favors speed-protecting discipline — limited customization, promotional price-point integrity, and a hard waste threshold that, once breached, restricts further made-ahead commitments for the rest of the day.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or invalid is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled as follows: `StoreManager`, `ShiftLead`, `CrewMember`, and `Customer`. Each operation is restricted to a designated set of roles (enumerated per endpoint in §4); an authenticated caller whose role is not permitted for the attempted operation is rejected with `ERR_UNAUTHORIZED`.

For all four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Specifically: when `X-User-Role` is `StoreManager`, `ShiftLead`, or `CrewMember`, the header value is an opaque handle recorded nowhere on resources and never matched against a foreign key. When `X-User-Role` is `Customer`, `X-User-ID` is an opaque customer handle with one additional ownership rule: on order-scoped calls it must equal the `customer_id` recorded on the target `Order` at creation. A portal customer attempting to pay, claim, cancel, read, or otherwise act on an order whose `customer_id` does not match the presented `X-User-ID` is rejected with `ERR_UNAUTHORIZED` — this includes a `Customer` placing an order whose `customer_id` is not the caller's own handle (and `COUNTER` orders may only be placed by a `ShiftLead`, portal kinds only by a `Customer`).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100; a `limit` or `offset` value that is not an integer, or a `limit` outside 1–100 or a negative `offset`, is rejected with `ERR_VALIDATION`. The `offset` parameter skips a number of items before returning the page and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties (common under the logical clock) broken by creation sequence so the ordering is fully deterministic. The `has_more` flag is true exactly when `offset` plus the size of the returned page is strictly less than `total_count`. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Clock-Driven Sweeps

All temporal semantics in the system — daypart activation windows, dough proofing floors and ceilings, hold-time expiry, pickup-code windows, locker cleaning durations, and demand-event status — evaluate against a single server-held **logical clock**, never against the wall clock. Before any call is made, the logical clock reads exactly `2026-09-01T00:00:00Z` (the startup default). A `StoreManager` may advance the logical clock to an arbitrary ISO 8601 UTC instant through an admin-only test-driving capability (`POST /_clock/set_current_utc`) that accepts a `to_iso8601` field and responds with the resulting `current_utc`. Timestamps are parsed leniently: a trailing `Z` denotes UTC, a naive timestamp without an offset is interpreted as UTC, and an explicit offset is accepted and converted to UTC. A missing or malformed `to_iso8601` is rejected with `ERR_VALIDATION`.

Setting the clock is not a passive readjustment: at the new instant the server runs every clock-driven sweep. Dough batches whose proofed lifetime has elapsed become `EXPIRED`; hold units whose hold window has elapsed are swept from `HOLDING` to `DISCARDED`; portal orders still `READY` past their pickup-code window are swept to `EXPIRED_NO_SHOW`; locker slots whose cleaning interval has completed return from `CLEANING` to `IDLE`; every demand event's status is recomputed against the new instant; and any daypart whose activation window has been reached while its store day is `OPEN` auto-activates from `PLANNED` to `ACTIVE`. Because the same sweeps also fire lazily as part of ordinary operations, a client may observe their effects on any subsequent read.

### 2.5. Common Resource Properties

Every primary resource — store days, dayparts, demand events, dough batches, cheese batches, products, production runs, hold units, orders, locker slots, and crew shifts — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; because every stamp is minted from the logical clock, resources created without an intervening clock set share the same timestamp, and list ordering within an identical timestamp is stabilized by creation sequence (§2.3).
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation, including mutations driven by system side effects such as counter recomputation on a parent.

The waste log is the single exception. A `WasteLog` row is an immutable audit append: it carries `id` and `created_at`, but `updated_at` and `version` are absent entirely. When a side effect mutates a parent — for example racking a production run, which increases the store day's produced counter — the parent's `updated_at` is refreshed and its `version` is incremented independently of the child write.

### 2.6. Numbers, Currency, and Rounding

Monetary amounts are integer cents throughout; no fractional cents ever appear in requests or responses. Percentages (`waste_pct_standard`, `waste_pct_net`) are numbers with exactly 2 decimal places, produced with the round-half-up method. Forecasts, targets, and unit counters are whole units; whenever a multiplication would yield a fractional unit (forecast demand, made-ahead targets), the result is rounded half-up to the nearest integer. Where a per-line fee is computed, each line's fee is rounded half-up to a whole cent first and the rounded per-line fees are then summed — the rounding order is pinned, and summing unrounded fees before rounding once is forbidden because it produces different cents.

### 2.7. Minute Windows and Instant Windows

The system uses two distinct interval semantics, and confusing them changes outcomes.

Daypart windows and crew-shift windows are expressed in whole minutes after the store day's 00:00 UTC boundary and use **half-open** semantics: the window includes its start minute and excludes its end minute. Two such windows overlap only when the candidate's start is strictly before the existing window's end and the existing window's start is strictly before the candidate's end; two windows that merely touch — the candidate starting at the exact minute the other ends — do not overlap. A daypart auto-activates when the clock's minute-of-day has reached its `window_start_minute` but has not yet reached its `window_end_minute`.

Demand-event windows, hold-unit expiry, pickup-code validity, proofing floors, and cleaning intervals are expressed as instants and use **closed or inclusive-boundary** semantics as stated per rule: a demand event is `ACTIVE` from its `window_start_at` through its `window_end_at` inclusive; a hold unit is expired once the clock reaches its `hold_expires_at` (the boundary instant itself is expired); a pickup code remains claimable while the clock is at or before `code_expires_at`; a dough batch may be marked proofed once the clock reaches the proofing floor exactly; and a locker slot returns to `IDLE` once the clock reaches the end of its cleaning interval exactly.

### 2.8. Waste Measurement and the RESTRICTED Posture

Every discarded pizza unit is counted against the store day, and the day's waste performance is measured two ways. The **standard** waste percentage counts every discarded unit, donated or not: it is the `discarded_units` divided by `produced_units`, multiplied by 100, rounded half-up to 2 decimal places — and is defined as 0.0 while `produced_units` is zero. The **net** waste percentage subtracts `donated_units` from the numerator before the same division and rounding, so identical raw waste data yields a lower percentage than the standard variant whenever donations occurred. The standard variant drives operational gating and store reporting; the net variant is reported for waste-performance analysis only and never gates anything.

The waste target for a store day is 5.0 percent under the standard measure. A daypart's derived `posture` is `RESTRICTED` exactly when its parent store day's `waste_pct_standard` is greater than or equal to that 5.0 target — the boundary is inclusive, so a day sitting at exactly 5.0 percent is already restricted — and `NORMAL` otherwise. Because `posture` is derived from the live parent counters, a single discard can flip every remaining daypart of the day to `RESTRICTED` at once, and a `RESTRICTED` posture gates order preparation as described in §3.7.

### 2.9. Optimistic Concurrency Control

Two update operations carry mandatory optimistic concurrency control, and no other endpoint takes a version field.

Updating a daypart's planning attributes requires the request to carry `expected_daypart_version` holding the `version` the client last observed on that daypart. If the daypart's current `version` no longer matches — for example because a preorder payment advanced the reservation counter and bumped the version after the client read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a daypart state it has not observed.

Updating a store day likewise requires `expected_store_day_version` matching the day row's current `version`. Any mutation that advanced the day since the client's last read — a racked production run incrementing `produced_units`, a discard recomputing the waste counters — causes the mismatch, and the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Validation Order and Nested Resource Resolution

Two error-catalogue corner cases are pinned here. Reading a waste-log row whose identifier does not resolve is rejected with HTTP 404 carrying `error_id` `ERR_VALIDATION` (no dedicated `ERR_WASTE_LOG_NOT_FOUND` exists); and any unrouted path or unsupported method likewise surfaces `ERR_VALIDATION` — with the routing layer's own 404 or 405 status — rather than a dedicated error code.

Requests are validated in a fixed precedence so that failures surface deterministically. First the authentication context is checked (missing or invalid headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization and customer ownership (`ERR_UNAUTHORIZED`). Next, resource identifiers are resolved: when a path or payload references several resources, identifiers are validated left to right, path parameters before body references, and the request is rejected with the 404 error corresponding to the first identifier that does not resolve — `ERR_STORE_DAY_NOT_FOUND`, `ERR_DAYPART_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND` (for either batch kind), `ERR_LOCKER_SLOT_NOT_FOUND`, `ERR_CREW_SHIFT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_HOLD_UNIT_NOT_FOUND`. Only after every referenced resource exists does the server evaluate state preconditions (`ERR_INVALID_STATE` and the operation-specific state errors), then the posture gate on order preparation, then the business-safety rules in their defined sequence (daypart window overlap, demand-event window overlap, crew-shift conflict, proof and rest timing, batch availability at start-baking), then the fiscal rules (promotional price validity, then the promotional price lock), then the remaining business constraints (customization permission, order-placement daypart status, rack capacity, locker availability), then the pickup-code checks on claims, then optimistic-concurrency version matching, then uniqueness, and finally field shape and range (`ERR_VALIDATION`).

## 3. Business Logic & Workflows

### 3.1. Planning the Store Day: Dayparts, Demand Events, and the Demand Forecast

A `StoreManager` opens planning by creating a store day identified by its `business_date`, a `YYYY-MM-DD` UTC calendar date that must be unique across all store days — a duplicate is rejected with `ERR_DUPLICATE_BUSINESS_DATE`. The new day starts in `PLANNING` status with its counters (`produced_units`, `sold_units`, `discarded_units`, `donated_units`) all at zero and both waste percentages at 0.0. While the day is in `PLANNING`, the manager may correct the `business_date` through the store-day update operation, which requires `expected_store_day_version` per §2.9 (a present, non-null value must match, else `ERR_STALE_VERSION`) and bumps the day's `version` by one; the corrected date must not collide with another store day's `business_date`, otherwise `ERR_DUPLICATE_BUSINESS_DATE`. Store days can be listed with `limit`, `offset`, and an optional `status` filter.

Within the day, the manager defines **dayparts** — the named selling windows `LUNCH`, `DINNER`, and `LATE_NIGHT` — each created with a `label`, a `window_start_minute` and `window_end_minute` (minutes after the day's 00:00 UTC boundary; the start must be at least 0 and the end must be strictly greater than the start, otherwise `ERR_VALIDATION`), a `rack_capacity` of at least 1 (the maximum number of units that may simultaneously sit in the warming rack for that daypart, counting both uncommitted and allocated units), and a `base_demand_units` forecast of at least 0. Two dayparts of the same store day may not overlap in time under the half-open minute semantics of §2.7, regardless of label; touching windows are permitted, but any true overlap is rejected with `ERR_DAYPART_WINDOW_OVERLAP`. While a daypart is still `PLANNED`, the manager may revise its window minutes, `rack_capacity`, or `base_demand_units` through the daypart update operation carrying `expected_daypart_version` (a present, non-null value must match, else `ERR_STALE_VERSION`); the revision recomputes the forecast and the made-ahead target and increments the daypart's `version`. Once a daypart has left `PLANNED`, the update is rejected with `ERR_INVALID_STATE`.

Each daypart carries a **provisional forecast**, `forecast_units_provisional`, computed at creation and recomputed whenever the demand picture changes. The forecast considers every non-cancelled demand event of the same store day whose status is `SCHEDULED` or `ACTIVE` and whose window overlaps the daypart window under closed-interval semantics — that is, the event's `window_start_at` is no later than the daypart's end instant and the daypart's start instant is no later than the event's `window_end_at`. The demand multiplier is the larger of 1.0 and the sum of the overlapping events' `demand_multiplier` values, so a daypart with no overlapping events forecasts at its base. The provisional forecast is then the `base_demand_units` multiplied by that multiplier, rounded half-up to a whole unit. A second, **final** variant, `forecast_units_final`, is computed once when the daypart closes and frozen thereafter: it counts only events in `ACTIVE` or `ENDED` status at close time under the same overlap predicate, so a still-`SCHEDULED` event is excluded and the same event set can yield a different number than the provisional value. Until close, `forecast_units_final` is null.

From the provisional forecast the system derives the daypart's `made_ahead_target`: the provisional forecast is multiplied by the made-ahead ratio of 0.6 and rounded half-up to a whole unit; that figure is then clamped so it never exceeds the daypart's `rack_capacity`; and finally the `preorder_reserved_units` (units already promised to paid preorders, initially 0) are subtracted — after the capacity clamp, not before — with the result never allowed to fall below zero. The target is recomputed whenever the provisional forecast or the reservation count changes.

**Demand events** capture sports days, local festivals, and similar spikes. A `StoreManager` creates one with a `name`, an inclusive `window_start_at` and `window_end_at` (the end must not precede the start, otherwise `ERR_VALIDATION`), and a `demand_multiplier` that must be greater than 0. A new event is rejected with `ERR_EVENT_WINDOW_OVERLAP` when any other non-cancelled event of the same store day intersects its window under closed-interval semantics — and because the semantics are closed, two events that merely touch, one's `window_end_at` landing exactly on the other's `window_start_at`, do intersect and are rejected. An event's `status` is derived from the clock and its `cancelled` flag: `CANCELLED` once cancelled; otherwise `SCHEDULED` while the clock precedes `window_start_at`, `ACTIVE` from `window_start_at` through `window_end_at` inclusive, and `ENDED` once the clock passes `window_end_at`. Only a `SCHEDULED` event may be cancelled — attempting to cancel one whose window has already begun is rejected with `ERR_EVENT_NOT_CANCELLABLE` — and cancellation sets `cancelled` to true, moves the event to `CANCELLED`, and immediately recomputes the provisional forecast and made-ahead target of every `PLANNED` or `ACTIVE` daypart of the same store day whose window intersects the event's, with the cancelled event removed from the inclusion set. Creating an event triggers the same recomputation with the new event included. Demand events can be listed per store day or across store days, with `limit`, `offset`, and a `store_day_id` filter.

Opening the store day is a `StoreManager` action that moves the day from `PLANNING` to `OPEN`. It requires at least one daypart to exist for the day in `PLANNED` status; with none defined, the open is rejected with `ERR_NO_DAYPARTS_DEFINED`. Once the day is `OPEN`, daypart auto-activation may fire immediately: any `PLANNED` daypart whose start minute the clock has reached (and whose end minute it has not) moves to `ACTIVE`, and the same sweep runs on every subsequent clock set per §2.4. Auto-activation also fulfills waiting preorders: the moment a daypart turns `ACTIVE`, every `PAID` `PORTAL_PREORDER` still `PLACED` against it is automatically carried through preparation and readiness exactly as if start-preparation (without the posture gate) and mark-ready had fired — allocating made-ahead units where available, occupying the lowest-numbered `IDLE` locker, minting a pickup code, and converting its allocated units to `SOLD`. An unpaid preorder is untouched and remains `PLACED` until it is paid and prepared in the ordinary way. If no `IDLE` locker exists at that moment, the auto-fulfillment aborts partway — the store day (or clock) change and the daypart activation have already been applied, and the order may already sit in `IN_PREPARATION` — and the triggering operation (the store-day open or the clock set) responds with the `ERR_NO_LOCKER_AVAILABLE` error raised by the readiness step.

### 3.2. In-Store Dough and Cheese Production

Dough is made in-house in batches. A `CrewMember` mixes a batch by declaring its `size_units` — the number of pizza units the batch can support, at least 1 — and the batch is born in `MIXING` with `mixing_started_at` stamped from the logical clock and `remaining_units` initialized to the full `size_units`. Advancing the batch moves it `MIXING → PROOFING`, stamping `proofing_started_at`; advancing it again moves it `PROOFING → PROOFED`, stamping `proofed_at`, but only once the clock has reached `proofing_started_at` plus 120 minutes — the proofing floor is inclusive, so exactly 120 minutes is enough, and an earlier attempt is rejected with `ERR_PROOF_NOT_READY`. Calling advance on a batch whose state has no forward transition is rejected with `ERR_BATCH_STATE`. A `PROOFED` batch is usable for baking until its proofing ceiling: once the clock reaches `proofed_at` plus 240 minutes (again inclusive), the batch is swept to the terminal `EXPIRED` state and its `remaining_units` are frozen, unusable. When baking consumption drives `remaining_units` to zero, the batch moves automatically from `PROOFED` to the terminal `DEPLETED` state.

Cheese prep follows a parallel but shorter discipline. A `CrewMember` preps a cheese batch with its own `size_units` (at least 1); the batch starts in `PREPPING` with `prepped_at` stamped and `remaining_units` equal to `size_units`. Advancing moves it `PREPPING → RESTING`, and a second advance moves it `RESTING → READY`, stamping `ready_at`, only once the clock has reached `prepped_at` plus 30 minutes — earlier attempts are rejected with `ERR_CHEESE_NOT_READY`, and advancing from a state with no forward transition yields `ERR_BATCH_STATE`. Cheese batches do not expire; a `READY` batch becomes `DEPLETED` automatically when its `remaining_units` reach zero through baking consumption. Both batch kinds can be listed per store day or across store days, filtered by `store_day_id` and `status` with the usual `limit` and `offset`.

### 3.3. Production Runs and the Warming Rack

A `ShiftLead` plans a **production run** against a specific daypart by naming the `product_id` to bake, the `dough_batch_id` and `cheese_batch_id` to consume, and the `quantity` of units (at least 1). The three referenced resources must exist at planning time (otherwise `ERR_PRODUCT_NOT_FOUND` or `ERR_BATCH_NOT_FOUND` per §2.10), but their readiness states are not checked until start-baking. The run is created in `PLANNED`. Production runs can be listed per daypart or across dayparts, filterable by `daypart_id`, `product_id`, `dough_batch_id`, `cheese_batch_id`, and `status`.

When the oven is ready, a `CrewMember` starts baking the run. This requires the run to still be `PLANNED` (otherwise `ERR_INVALID_STATE`), the owning daypart to be `ACTIVE` (otherwise `ERR_DAYPART_NOT_ACTIVE`), the referenced dough batch to be `PROOFED` with `remaining_units` of at least the run's `quantity` (otherwise `ERR_DOUGH_UNAVAILABLE`), and the referenced cheese batch to be `READY` with `remaining_units` of at least the `quantity` (otherwise `ERR_CHEESE_UNAVAILABLE`). Starting the bake decrements both batches' `remaining_units` by the run's `quantity` — a batch driven to zero depletes automatically per §3.2 — stamps `baked_at`, and moves the run to `BAKING`.

Racking is the moment made-ahead inventory comes into existence. A `CrewMember` racks a `BAKING` run of an `ACTIVE` daypart (violations yield `ERR_INVALID_STATE` or `ERR_DAYPART_NOT_ACTIVE` respectively), but only if the rack has room: the daypart's current rack occupancy — the count of its hold units in `HOLDING` or `ALLOCATED` status — plus the run's `quantity` must not exceed the daypart's `rack_capacity`, otherwise the rack is rejected wholesale with `ERR_RACK_CAPACITY_EXCEEDED`. A successful rack creates exactly `quantity` hold units, each in `HOLDING` status with `racked_at` stamped from the clock, `hold_expires_at` computed 30 minutes later, and its `product_id` denormalized from the run. The run's `units_available` is set to the full `quantity`, `racked_at` is stamped, and the run moves to `HOLDING`. On the parent store day, `produced_units` increases by the run's `quantity`, both waste percentages are recomputed, and the day's `updated_at` and `version` advance accordingly. A run whose `units_available` reaches zero — every unit allocated, sold, or discarded — closes automatically to the terminal `CLOSED` state.

### 3.4. Hold Units: Allocation, Expiry, and Discard

Each hold unit is one pizza on the rack, tracked individually from racking to outcome. While `HOLDING`, a unit is eligible for allocation to an order being prepared in the same daypart (§3.7), provided it is still fresh: the clock must be strictly before the unit's `hold_expires_at`, because the boundary instant itself counts as expired — a unit whose 30-minute hold window has just elapsed cannot be allocated. Allocation stamps the unit's `allocated_order_id` and moves it to `ALLOCATED`, decrementing the source run's `units_available` by one (and closing the run when that reaches zero).

Hold units can be listed with `limit` and `offset` and filtered by `production_run_id`, `status`, `product_id`, or `allocated_order_id`.

A unit leaves the rack in one of three ways. It is **sold** when the order it was allocated to reaches readiness, moving from `ALLOCATED` to the terminal `SOLD` state and adding one to the store day's `sold_units` per unit. It is **released** when the allocating order is cancelled or expires before ever reaching readiness: a released unit whose hold window is still fresh returns from `ALLOCATED` to `HOLDING`, its `allocated_order_id` is cleared, and the run's `units_available` is incremented — although a run that already closed stays `CLOSED` — whereas a released unit whose expiry has already arrived or passed does not return to the rack at all and goes directly to `DISCARDED` with reason `HOLD_EXPIRED` and a waste-log row. And it is **discarded**, moving from `HOLDING` to the terminal `DISCARDED` state, either automatically when the expiry sweep finds the clock at or past `hold_expires_at`, or manually by a `ShiftLead`. A manual discard requires the unit to still be `HOLDING` (otherwise `ERR_INVALID_STATE`) and a `reason` of `DAMAGED` or `QUALITY` — any other reason, including `HOLD_EXPIRED` or `NO_SHOW`, is rejected with `ERR_INVALID_DISCARD_REASON`, and the reason is validated before the unit's state so an invalid reason on a non-`HOLDING` unit yields `ERR_INVALID_DISCARD_REASON` — and may carry an optional `donated` flag, defaulting to false, marking the unit as donated rather than trashed.

Every discard, from any path, records the `discarded_reason` on the unit (`HOLD_EXPIRED`, `DAMAGED`, `QUALITY`, or `NO_SHOW` as applicable) and appends exactly one `WasteLog` row per unit — the row's `quantity` is always 1 — capturing the `store_day_id`, the `daypart_id` of the discarded unit's run, the `hold_unit_id`, the `reason`, the `donated` flag (taken from the operator's input on a manual discard; always false for sweeps and automatic discards), and a `logged_at` clock stamp. The store day's `discarded_units` increases by one, `donated_units` increases by one only when the row was donated, and both waste percentages are recomputed per §2.8, advancing the parent day's `version`. Waste-log rows are immutable audit records (§2.5) and can be listed per store day or across store days: the per-store-day list filters by `reason`, while the across-store-days list filters by `store_day_id`, `daypart_id`, `hold_unit_id`, or `reason`.

### 3.5. The Product Catalogue and Promotional Price Discipline

The catalogue is small and deliberately rigid — speed depends on it. A `StoreManager` creates a product with a unique `sku` (duplicates rejected with `ERR_DUPLICATE_SKU`), a display `name`, a `list_price_cents` of at least 1, an optional `promo_price_cents`, and a `customization_allowed` flag that defaults to false. Promotional price points must sit strictly below the list price: a `promo_price_cents` that is present but not less than `list_price_cents` is rejected with `ERR_PROMO_PRICE_INVALID`, both at creation and on update. The manager may later update a product's `name`, `list_price_cents`, `promo_price_cents`, or `customization_allowed`; passing `promo_price_cents` as explicit null clears the promotional price, and the strictly-below-list rule is evaluated against the resulting list/promo pair.

Once a product is in live production, its promotional price is frozen. The derived `promo_locked` flag is true while any `OPEN` store day has a daypart carrying a production run that references this product and has not yet reached `CLOSED`. While `promo_locked` is true, the promotional price may not be created, changed, or removed — any update request whose `promo_price_cents` would differ from the current value (including clearing it to null) is rejected with `ERR_PROMO_PRICE_LOCKED`, while a request that repeats the current value is not a change and proceeds — although other attributes remain editable. The lock lifts once the referencing runs close or their store day closes.

### 3.6. Placing and Paying for Orders

Orders come in three kinds, spelled exactly `PORTAL_STANDARD`, `PORTAL_PREORDER`, and `COUNTER`. A `Customer` places portal orders; a `ShiftLead` places `COUNTER` orders on behalf of walk-ins. Placement supplies the `store_day_id`, the promised `daypart_id`, the `customer_id` (an opaque handle that later anchors portal ownership per §2.1), the `kind`, and the `lines` — an array of entries each giving a `product_id`, a `quantity` of at least 1, and a `customized` flag. The promised daypart must be in the right state for the kind: a `PORTAL_PREORDER` promises a daypart that is still `PLANNED` (otherwise `ERR_PREORDER_DAYPART_NOT_PLANNED`), while `PORTAL_STANDARD` and `COUNTER` orders require the daypart to already be `ACTIVE` (otherwise `ERR_DAYPART_NOT_ACTIVE`). Customization is the exception, not the rule: any line with `customized` set true must reference a product whose `customization_allowed` is true, otherwise placement is rejected with `ERR_CUSTOMIZATION_NOT_ALLOWED`.

Pricing is computed once at placement and frozen on the order thereafter. For each line, the unit price is the product's `promo_price_cents` when the product carries one and the line is not customized, and the `list_price_cents` otherwise — a customized line never receives the promotional price. The line subtotal is that unit price times the line `quantity`. For portal kinds, each line additionally accrues a portal fee equal to the line subtotal multiplied by the 5 percent portal fee rate, rounded half-up to a whole cent per line; `COUNTER` lines accrue no fee. The order's `subtotal_cents` is the sum of the line subtotals; its `portal_fee_cents` is the sum of the already-rounded per-line fees (per §2.6, per-line rounding precedes summation); and its `total_cents` is the two added together.

A new order is born with `payment_status` `UNPAID` and `fulfillment_status` `PLACED` — two parallel dimensions that evolve independently. The customer pays through the pay action, which requires the order to be both `UNPAID` and still `PLACED` (either violation yields `ERR_INVALID_STATE`; in particular, no payment is accepted once preparation has begun). Payment moves `payment_status` to `PAID`. When a `PORTAL_PREORDER` is paid while its promised daypart is still `PLANNED`, the payment additionally reserves capacity: the daypart's `preorder_reserved_units` increases by the order's total line quantity, the provisional forecast and `made_ahead_target` are recomputed per §3.1, and the daypart's `version` advances — which is precisely why a stale daypart update is rejected under §2.9. A preorder paid after its daypart has already left `PLANNED` reserves nothing. Refunds are never initiated directly: `payment_status` moves from `PAID` to `REFUNDED` only as the companion of a fulfillment-side cancellation or expiry. Orders can be listed with `limit` and `offset` and filtered by `store_day_id`, `daypart_id`, `customer_id`, `kind`, `fulfillment_status`, or `locker_slot_id`.

### 3.7. Preparation, the Pickup Portal, and Fulfilment Closeout

Preparation begins when a `CrewMember` starts preparation on a `PLACED` order. Four preconditions are evaluated in order: the order must be `PLACED` (otherwise `ERR_INVALID_STATE`); a `PORTAL_PREORDER` may only begin preparation once its promised daypart is `ACTIVE` (otherwise `ERR_PREORDER_DAYPART_NOT_ACTIVE`); the order must be `PAID` unless it is a `COUNTER` order (otherwise `ERR_ORDER_NOT_PAID`); and the promised daypart's `posture` must be `NORMAL` — if the store day's standard waste percentage has reached the 5.0 target and flipped the posture to `RESTRICTED`, the entire request is rejected with `ERR_DAYPART_RESTRICTED` before any partial allocation occurs.

An accepted start-preparation pulls from made-ahead inventory first, line by line in request order. For each line, the desired pull from the rack is the line `quantity` reduced by one when the line is `customized` — a customized pizza is always baked to order for its customized unit — so a single-unit customized line pulls zero from hold. The candidate pool is the hold units in `HOLDING` status whose `product_id` matches the line's product, whose production run belongs to the order's promised daypart, and whose hold window is still fresh under the strict-before-expiry rule of §3.4. The pool is drawn oldest first, ordered by `racked_at` ascending with ties broken by `created_at` ascending, and the line takes the smaller of its desired pull and the pool's size; whatever remains is made to order. An empty pool is not an error — the line simply falls back entirely to made-to-order, and no locker-related error is raised at this stage. The order records the split in `made_ahead_units` and `made_to_order_units`, each allocated unit transitions per §3.4 with its run's `units_available` decremented, and the order moves to `IN_PREPARATION`.

Marking the order ready is the fulfillment pivot, performed by a `CrewMember` on an `IN_PREPARATION` order (otherwise `ERR_INVALID_STATE`). For portal kinds, readiness requires a heated locker: the pool is the store day's locker slots in `IDLE` status, and if that pool is empty the mark-ready is rejected with `ERR_NO_LOCKER_AVAILABLE`. The winner is deterministic — the `IDLE` slot with the lowest `slot_number`, with the slot's `id` never consulted — and it flips to `OCCUPIED` with `current_order_id` set and `occupied_at` stamped. The order receives a `pickup_code` — a zero-padded 6-digit numeric string (leading zeros retained, e.g. `042417`) minted randomly and retried until unique among codes in the same store day whose `code_expires_at` has not yet passed — and a `code_expires_at` set 45 minutes after readiness; `ready_at` is stamped. A `COUNTER` order is simply stamped `ready_at` — no locker, no code. In all cases, every hold unit allocated to the order converts to `SOLD` and the store day's `sold_units` increases by the count. The order is now `READY`.

The customer claims a portal order by presenting its `pickup_code`. Claiming a `COUNTER` order is rejected with `ERR_NOT_PORTAL_ORDER`; claiming an order that is not `READY` yields `ERR_INVALID_STATE`; a code that does not match is rejected with `ERR_PICKUP_CODE_INVALID`; and a claim arriving after `code_expires_at` — the boundary itself is still valid, so the clock sitting exactly at expiry claims successfully — is rejected with `ERR_PICKUP_CODE_EXPIRED`. A successful claim moves the order to the terminal `PICKED_UP` state and sends its locker slot to `CLEANING`.

Lockers cycle. A `StoreManager` installs slots for a store day by `slot_number`, a positive integer unique within the day (duplicates rejected with `ERR_DUPLICATE_SLOT_NUMBER`); slots are born `IDLE`. From `OCCUPIED`, a slot moves to `CLEANING` — with `cleaning_started_at` stamped and `current_order_id` retained for audit — when its order is claimed, when the order is swept as a no-show, or when a daypart close expires the preorder occupying it. Once the clock reaches `cleaning_started_at` plus 15 minutes, the slot returns to `IDLE`, its `current_order_id` is cleared, and the slot's `version` increments. All locker state transitions (occupation, cleaning, return to idle) likewise stamp `updated_at` and bump `version` per §2.5. Slots can be listed per store day or across store days: the per-store-day list filters by `status`, while the across-store-days list filters by `store_day_id`, `status`, or `current_order_id`.

A customer may cancel an order while it is `PLACED` or `IN_PREPARATION` (otherwise `ERR_INVALID_STATE`). Cancellation refunds a `PAID` order to `REFUNDED`; returns any preorder reservation the order had consumed — the daypart's `preorder_reserved_units` decreases by the order's total line quantity and the `made_ahead_target` is recomputed — and releases the order's allocated hold units per the release rule of §3.4, fresh units returning to the rack and already-expired units discarding straight to `HOLD_EXPIRED` waste. The order ends in the terminal `CANCELLED` state.

If the customer never comes, the no-show sweep handles it: a portal order still `READY` once the clock has passed `code_expires_at` moves to the terminal `EXPIRED_NO_SHOW` state, a `PAID` order is refunded to `REFUNDED`, and its locker slot goes to `CLEANING`. Notably, the order's units were already counted as sold at readiness — and they stay counted as sold — yet each unit is also appended to the waste log with reason `NO_SHOW` (donated false, one row per unit, and — since the units themselves were sold rather than discarded — with a null `hold_unit_id` and the `daypart_id` taken from the order), the store day's `discarded_units` increases by the count, and the waste percentages are recomputed; `produced_units` is unchanged. A no-show order therefore contributes to both `sold_units` and `discarded_units` simultaneously.

### 3.8. End-of-Daypart and End-of-Day Reconciliation

When a selling window finishes, a `ShiftLead` closes the daypart. Closing requires that no production run of the daypart still be `BAKING` — outstanding bakes block the close with `ERR_RUNS_IN_PROGRESS`. The close is a heavy cascade, evaluated as one action: the daypart moves from `ACTIVE` to the terminal `CLOSED` state; the final demand forecast `forecast_units_final` is computed under the chronological variant of §3.1 and frozen; every hold unit of the daypart still `HOLDING` is discarded with reason `HOLD_EXPIRED`, one waste-log row per unit with `donated` false; the parent store day's `discarded_units` increases by that count and both waste percentages are recomputed, advancing the day's `version`; and every paid preorder promising this daypart that never reached `READY` or `PICKED_UP` is moved to `EXPIRED_NO_SHOW` with its payment refunded to `REFUNDED`, sending any locker slot still occupied for such an order to `CLEANING`. Unlike the no-show sweep of §3.7, this close-time expiry appends no waste-log rows and does not change the day's counters, because none of the order's units were ever counted as sold.

Closing the store day is a `StoreManager` action with two guards, checked in order: every daypart of the day must already be `CLOSED` (otherwise `ERR_DAYPARTS_STILL_ACTIVE`), and no locker slot of the day may be `OCCUPIED` (otherwise `ERR_LOCKER_SLOTS_OCCUPIED`). Closing moves the day from `OPEN` to `CLOSED` and sweeps every remaining `HOLDING` unit of the day to `DISCARDED` with reason `HOLD_EXPIRED`, appending one waste-log row per unit with `donated` false and recomputing the day's waste counters. A later reconcile action moves the day from `CLOSED` to the terminal `RECONCILED` state, at which point `waste_pct_standard` and `waste_pct_net` are recomputed one final time and frozen.

At any point, a `StoreManager` or `ShiftLead` can read the day's waste report, which returns the `store_day_id`, the four counters `produced_units`, `sold_units`, `discarded_units`, and `donated_units`, both percentages `waste_pct_standard` and `waste_pct_net`, the applicable `waste_target_pct` (5.0), and a `target_breached` boolean that is true exactly when the standard percentage has reached or exceeded that target — the same inclusive threshold that drives daypart `posture`.

### 3.9. Crew Station Assignment in a Small-Footprint Kitchen

The kitchen is small enough that each station seats exactly one worker at a time. A `ShiftLead` assigns a crew shift by naming the `crew_member_id` (an opaque handle), the `station` — one of `OVEN`, `CUT_TABLE`, `LOCKER_BAY`, or `DOUGH_PREP` — and the `start_minute` and `end_minute` of the window (the start at least 0 and the end strictly greater than the start, otherwise `ERR_VALIDATION`). Two conflict rules guard assignment, both evaluated under the half-open minute semantics of §2.7, and a violation of either is rejected with `ERR_SHIFT_CONFLICT`. First, the same crew member may not be double-booked: the candidate conflicts with any existing `SCHEDULED` shift of the same `crew_member_id` when the candidate's start is strictly before the existing shift's end and the existing shift's start is strictly before the candidate's end — back-to-back shifts, where the candidate starts at the exact minute the other ends, do not conflict and are permitted. Second, the small-footprint rule: at most one `SCHEDULED` shift per station may cover any minute of the candidate window, regardless of which crew members are involved. A shift is born `SCHEDULED` and a `ShiftLead` ends it, moving it to the terminal `ENDED` state; ending a shift that is not `SCHEDULED` yields `ERR_INVALID_STATE`. Shifts can be listed per store day (filterable by `crew_member_id` or `station`) or across store days (filterable by `store_day_id`, `crew_member_id`, `station`, or `status`).

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; runs all clock-driven sweeps | StoreManager |
| POST | `/store-days` | Create a store day | StoreManager |
| GET | `/store-days` | List store days | StoreManager, ShiftLead, CrewMember, Customer |
| GET | `/store-days/{dayId}` | Get a store day | StoreManager, ShiftLead, CrewMember, Customer |
| PUT | `/store-days/{dayId}` | Update a store day's `business_date` with OCC | StoreManager |
| POST | `/store-days/{dayId}/open` | Open the store day | StoreManager |
| POST | `/store-days/{dayId}/close` | Close the store day; discards all remaining hold units | StoreManager |
| POST | `/store-days/{dayId}/reconcile` | Reconcile the day and freeze waste figures | StoreManager |
| GET | `/store-days/{dayId}/waste-report` | Waste report for a store day | StoreManager, ShiftLead |
| POST | `/store-days/{dayId}/dayparts` | Create a daypart within a store day | StoreManager |
| GET | `/store-days/{dayId}/dayparts` | List dayparts of a store day | StoreManager, ShiftLead, CrewMember, Customer |
| GET | `/dayparts/{daypartId}` | Get a daypart | StoreManager, ShiftLead, CrewMember, Customer |
| PUT | `/dayparts/{daypartId}` | Update a planned daypart with OCC | StoreManager |
| POST | `/dayparts/{daypartId}/close` | Close a daypart and freeze its final forecast | ShiftLead |
| POST | `/store-days/{dayId}/demand-events` | Create a demand event | StoreManager |
| GET | `/store-days/{dayId}/demand-events` | List demand events of a store day | StoreManager, ShiftLead, CrewMember |
| GET | `/demand-events/{eventId}` | Get a demand event | StoreManager, ShiftLead, CrewMember |
| POST | `/demand-events/{eventId}/cancel` | Cancel a scheduled demand event | StoreManager |
| POST | `/store-days/{dayId}/dough-batches` | Mix a dough batch | CrewMember |
| GET | `/dough-batches/{batchId}` | Get a dough batch | StoreManager, ShiftLead, CrewMember |
| GET | `/store-days/{dayId}/dough-batches` | List dough batches of a store day | StoreManager, ShiftLead, CrewMember |
| POST | `/dough-batches/{batchId}/advance` | Advance a dough batch's state | CrewMember |
| POST | `/store-days/{dayId}/cheese-batches` | Prep a cheese batch | CrewMember |
| GET | `/cheese-batches/{batchId}` | Get a cheese batch | StoreManager, ShiftLead, CrewMember |
| GET | `/store-days/{dayId}/cheese-batches` | List cheese batches of a store day | StoreManager, ShiftLead, CrewMember |
| POST | `/cheese-batches/{batchId}/advance` | Advance a cheese batch's state | CrewMember |
| POST | `/products` | Create a product | StoreManager |
| GET | `/products` | List products | StoreManager, ShiftLead, CrewMember, Customer |
| GET | `/products/{productId}` | Get a product | StoreManager, ShiftLead, CrewMember, Customer |
| PUT | `/products/{productId}` | Update a product under promo price discipline | StoreManager |
| POST | `/dayparts/{daypartId}/production-runs` | Plan a production run for a daypart | ShiftLead |
| GET | `/dayparts/{daypartId}/production-runs` | List production runs of a daypart | StoreManager, ShiftLead, CrewMember |
| GET | `/production-runs/{runId}` | Get a production run | StoreManager, ShiftLead, CrewMember |
| POST | `/production-runs/{runId}/start-baking` | Start baking a planned run; consumes dough and cheese | CrewMember |
| POST | `/production-runs/{runId}/rack` | Rack a baked run; mints hold units | CrewMember |
| GET | `/hold-units` | List hold units, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/hold-units/{unitId}` | Get a hold unit | StoreManager, ShiftLead, CrewMember |
| POST | `/hold-units/{unitId}/discard` | Manually discard a holding unit, optionally as a donation | ShiftLead |
| POST | `/orders` | Place an order of any kind | Customer, ShiftLead |
| GET | `/orders` | List orders, filterable | StoreManager, ShiftLead, CrewMember, Customer |
| GET | `/orders/{orderId}` | Get an order | StoreManager, ShiftLead, CrewMember, Customer |
| POST | `/orders/{orderId}/pay` | Pay for an order | Customer |
| POST | `/orders/{orderId}/start-preparation` | Start preparing an order; pulls made-ahead inventory first | CrewMember |
| POST | `/orders/{orderId}/mark-ready` | Mark an order ready; portal kinds occupy a locker and mint a code | CrewMember |
| POST | `/orders/{orderId}/claim` | Claim a portal order with its pickup code | Customer |
| POST | `/orders/{orderId}/cancel` | Cancel an order before it is ready | Customer |
| POST | `/store-days/{dayId}/locker-slots` | Install a heated locker slot for a store day | StoreManager |
| GET | `/store-days/{dayId}/locker-slots` | List locker slots of a store day | StoreManager, ShiftLead, CrewMember |
| GET | `/locker-slots/{slotId}` | Get a locker slot | StoreManager, ShiftLead, CrewMember |
| GET | `/store-days/{dayId}/waste-logs` | List waste log rows of a store day | StoreManager, ShiftLead |
| POST | `/store-days/{dayId}/crew-shifts` | Assign a crew member to a station window | ShiftLead |
| GET | `/store-days/{dayId}/crew-shifts` | List crew shifts of a store day | StoreManager, ShiftLead, CrewMember |
| GET | `/crew-shifts/{shiftId}` | Get a crew shift | StoreManager, ShiftLead, CrewMember |
| POST | `/crew-shifts/{shiftId}/end` | End a crew shift | ShiftLead |
| GET | `/dayparts` | List dayparts across store days, filterable | StoreManager, ShiftLead, CrewMember, Customer |
| GET | `/demand-events` | List demand events across store days, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/dough-batches` | List dough batches across store days, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/cheese-batches` | List cheese batches across store days, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/production-runs` | List production runs across dayparts, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/locker-slots` | List locker slots across store days, filterable | StoreManager, ShiftLead, CrewMember |
| GET | `/waste-logs` | List waste log rows across store days, filterable | StoreManager, ShiftLead |
| GET | `/waste-logs/{wasteLogId}` | Get a waste log row | StoreManager, ShiftLead |
| GET | `/crew-shifts` | List crew shifts across store days, filterable | StoreManager, ShiftLead, CrewMember |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STORE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_DAYPART_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_LOCKER_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_DAYPARTS_DEFINED` | 409 Conflict |
| `ERR_DAYPARTS_STILL_ACTIVE` | 409 Conflict |
| `ERR_LOCKER_SLOTS_OCCUPIED` | 409 Conflict |
| `ERR_RUNS_IN_PROGRESS` | 409 Conflict |
| `ERR_DAYPART_NOT_ACTIVE` | 409 Conflict |
| `ERR_PREORDER_DAYPART_NOT_PLANNED` | 409 Conflict |
| `ERR_PREORDER_DAYPART_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_DAYPART_RESTRICTED` | 409 Conflict |
| `ERR_DAYPART_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIFT_CONFLICT` | 409 Conflict |
| `ERR_BATCH_STATE` | 409 Conflict |
| `ERR_PROOF_NOT_READY` | 409 Conflict |
| `ERR_CHEESE_NOT_READY` | 409 Conflict |
| `ERR_DOUGH_UNAVAILABLE` | 409 Conflict |
| `ERR_CHEESE_UNAVAILABLE` | 409 Conflict |
| `ERR_RACK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NO_LOCKER_AVAILABLE` | 409 Conflict |
| `ERR_NOT_PORTAL_ORDER` | 409 Conflict |
| `ERR_PICKUP_CODE_INVALID` | 409 Conflict |
| `ERR_PICKUP_CODE_EXPIRED` | 409 Conflict |
| `ERR_INVALID_DISCARD_REASON` | 400 Bad Request |
| `ERR_PROMO_PRICE_INVALID` | 422 Unprocessable Entity |
| `ERR_PROMO_PRICE_LOCKED` | 409 Conflict |
| `ERR_CUSTOMIZATION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BUSINESS_DATE` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_SLOT_NUMBER` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
