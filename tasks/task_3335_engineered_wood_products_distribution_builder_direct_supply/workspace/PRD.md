# Ewp Builder Direct API — Product Requirements Document

## 1. Introduction

This document specifies the REST API for an engineered wood products distribution platform supporting a builder-direct supply program. The platform spans the full commercial cycle of a wholesale building-materials distributor: mill production capacity is planned and split between internal branch replenishment and open-market sales, commodity index prices are published weekly per product family and species, distribution branches hold inventory lots valued on a FIFO basis, and builder customers are extended credit against which account managers place orders for engineered joists, beams, and structural panels.

Builder-direct service is the differentiating motion: a builder's authorized contact opens a take-off request against a specific jobsite, an account manager responds with a design package and a firm quoted total, and the builder can accept the quote — converting it directly into a draft sales order — within a fourteen-day validity window. Orders are priced either at a fixed unit price or off the published commodity index, fulfilled from branch inventory under strict FIFO lot reservation, and delivered by a boom-truck fleet whose shifts are scheduled against jobsite access windows and drop-capacity limits. Credit exposure is tracked at both the builder and the individual-job level, and the platform supports lien filings when delivered-but-unsettled exposure remains outstanding beyond a statutory window.

The API enforces segregation of duties across seven roles — mill planning, branch operations, credit management, account management, fleet coordination, platform administration, and the builder's own contact — so that the party extending credit is never the party entering orders, and the party scheduling a truck is never the party confirming the sale it ships against. All state transitions, calculations, validation orderings, and concurrency rules described here are normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not match one of the declared role names below, the request is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). Once the headers are well-formed, the role must be permitted for the target endpoint per the authorization column of §4; a permitted-role failure, or an entity-ownership failure described below, yields `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the server recognizes them:

- `OpsAdmin` — platform operations administrator; owns the logical clock, product catalog, price index, branch registry, and truck-shift registry.
- `MillPlanner` — mill production planner; owns capacity weeks and their internal/market allocation split.
- `BranchManager` — distribution branch manager; receives inventory lots and reads branch valuation.
- `CreditManager` — credit officer; onboards builders, runs credit reviews, files and releases liens. Deliberately segregated from order entry.
- `AccountManager` — builder-direct account manager; opens jobs, submits take-off design packages, enters/confirms/cancels orders, and requests deliveries. Deliberately segregated from credit decisions and lien filings.
- `FleetCoordinator` — delivery fleet coordinator; schedules deliveries onto truck shifts and records completion outcomes.
- `BuilderContact` — a builder's authorized contact; opens take-off requests, requests revisions, and accepts quotes.

For six of the seven roles — `OpsAdmin`, `MillPlanner`, `BranchManager`, `CreditManager`, `AccountManager`, and `FleetCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `BuilderContact`, `X-User-ID` is the `id` of the acting `Builder`; ownership checks on any resource that references a `Builder` compare the resource's builder foreign-key field to `X-User-ID`. In particular, opening a take-off request on a job, requesting a revision on a quoted take-off, and accepting a quoted take-off all require that the calling `BuilderContact`'s `X-User-ID` equal the `builder_id` of the job that owns the take-off; any mismatch is `ERR_FORBIDDEN`.

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

List endpoints accept the query parameters `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. List responses are sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional results exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits; `version` starts at its initial value on creation and increments by 1 on every mutation of the resource, including mutations caused by cascade side effects from other operations.

The platform does not read wall-clock time. A single server-side logical clock governs every system-stamped field — `received_at` on inventory lots, `quoted_at` on take-off requests, `filed_at` and `released_at` on lien filings, and `completed_at` on deliveries — as well as every time-based rule such as quote expiry, lien deadlines, and truck-shift closure. At server startup the logical clock is exactly 2026-09-01T00:00:00Z and must never fall back to wall-clock time. An `OpsAdmin` may advance the clock to a supplied `to_iso8601` instant through a test-driving capability; the response echoes the new clock value as `current_utc`.

### 2.5. Nested Resource Retrieval and Identifier Existence

Path parameters are validated strictly left-to-right: each identifier in a nested URL must exist before the next is examined, and the first missing identifier short-circuits the request with `ERR_NOT_FOUND` (HTTP 404). Identifiers referenced inside a request body — such as `product_id`, `branch_id`, `truck_shift_id`, or the `product_id` of an order line — are likewise checked for existence and reject with `ERR_NOT_FOUND` when absent. Malformed payloads, missing required fields, unknown enum members, and non-positive quantities or amounts reject with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents. Where a calculation produces a fractional cent, the result is rounded half-up to integer cents at the granularity the rule specifies — per order line for order pricing, per fee component for delivery fees — and only then summed. The one non-monetary computed ratio, a capacity week's `fill_rate_pct`, is expressed to 4 decimal places using round-half-up. Inventory quantities are integer thousand board feet (mbf) throughout; no fractional mbf exists anywhere in the system.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry an optimistic-concurrency obligation, and no others do.

Creating a direct sales order against a job requires the request body to carry `expected_builder_version`, the client-last-observed `version` of the `Builder` that owns the job. Order creation mutates the builder's exposure basis and bumps `Builder.version`, so if the builder's current `version` no longer matches `expected_builder_version` — because another writer has advanced it since the client last read the builder — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Adjusting the allocation split of a mill capacity week requires the request body to carry `expected_capacity_week_version`, the client-last-observed `version` of the `MillCapacityWeek`. Each successful allocation bumps the week's `version`, so a mismatch against the week's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field.

### 2.8. Validation Priority Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. The order is: first, the context-header check (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`); second, the role-and-ownership check (`ERR_FORBIDDEN`); third, identifier existence (`ERR_NOT_FOUND`); fourth, optimistic-concurrency version checks (`ERR_STALE_VERSION`); fifth, state-machine legality (`ERR_INVALID_STATE`); sixth, business-temporal rules (quote expiry, delivery-window containment, the drop buffer, lien deadlines); seventh, specialty compliance (`ERR_CODE_REPORT_REQUIRED`); eighth, capacity and fleet constraint conflicts (HTTP 409 codes such as `ERR_CAPACITY_EXCEEDED`, `ERR_PRICE_INDEX_MISSING`, `ERR_INSUFFICIENT_INVENTORY`); and ninth, fiscal checks (the HTTP 402 credit and exposure family). A request failing an earlier category is rejected there even if a later category would also fail.

### 2.9. Catalog Enumerations

The product catalog recognizes four product families — `I_JOIST`, `LVL_BEAM`, `GLULAM_BEAM`, and `STRUCTURAL_PANEL` — and three species — `DOUGLAS_FIR`, `SOUTHERN_PINE`, and `SPRUCE_PINE_FIR`. Jobsite placement difficulty is one of `STANDARD`, `TIGHT_ACCESS`, or `CRANE_ASSIST`. An order's pricing week mode is `LOCK_AT_ACCEPT` or `FLOAT_TO_SHIP`, and each order line's price basis is `FIXED` or `INDEX`. These spellings are exact; any other value in an enum-typed field is `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Planning the Mill Week: Capacity, Allocation, and the Closing Waterfall

A `MillPlanner` opens a production week by registering a `MillCapacityWeek` identified by `mill_code` and `week_start_date` — the ISO date of the Monday starting the week, unique per mill — together with `total_capacity_mbf`, the week's total production capacity in thousand board feet. The week begins in `week_status` `OPEN`, with `internal_alloc_mbf` and `market_alloc_mbf` both starting at 0. Its computed fields — `committed_internal_mbf`, `committed_market_mbf`, and `fill_rate_pct` — all read 0 until close, and `internal_grants` is an empty list until the close waterfall populates it.

While the week remains `OPEN`, the planner may set the split between branch replenishment and open-market sales by submitting `internal_alloc_mbf` and `market_alloc_mbf` through the allocate operation, which requires `expected_capacity_week_version` per §2.7. The sum of the two allocation legs may not exceed `total_capacity_mbf`; when it does, the request is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409). Each successful allocation bumps the week's `version`. Attempting to allocate on a week that is no longer `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 400).

Closing the week is the one-way transition from `OPEN` to `CLOSED`. At close, the system runs the internal allocation waterfall. The candidate branches are exactly those whose `replenishment_enabled` flag is true — a branch is created with this flag defaulting to true unless explicitly disabled — ranked by `activity_score` descending, with ties broken by the branch's `created_at` ascending (never by `id`). Each branch's demand is the greater of zero and its `target_stock_mbf` minus its current on-hand position, where on-hand is the sum, over all of that branch's inventory lots, of each lot's `qty_available_mbf` plus `qty_reserved_mbf`. The pool starts at `internal_alloc_mbf`; walking the ranked branches in order, each branch is granted the smaller of its demand and the remaining pool, an entry recording the branch's `branch_id` and its `granted_mbf` is appended to `internal_grants` in grant order, and the pool is reduced by the grant. When the walk completes, `committed_internal_mbf` is the original `internal_alloc_mbf` minus whatever remains in the pool, `committed_market_mbf` equals `market_alloc_mbf` in full, and `fill_rate_pct` is the sum of the two committed legs divided by `total_capacity_mbf`, rounded half-up to 4 decimal places. Closing also bumps the week's `version` by 1, and a `CLOSED` week is terminal: no further transitions or allocations are possible.

### 3.2. Catalog and Commodity Pricing: Products and the Price Index

An `OpsAdmin` maintains the product catalog. Each product carries a unique `sku_code`, a `product_family` and `species` from the enumerations of §2.9, a free-text `dimension_label`, and three commercial flags: `specialty_flag` (default false) marking specialty-program products, `requires_code_report` (default false) which forces order confirmation to carry a code report reference, and `requires_design_support` (default false) marking products whose take-offs must include floor system design. The catalog price lever is `index_premium_cents` (default 0), the premium in cents per mbf that the product commands over the commodity index.

Commodity pricing enters the platform as `PriceIndexEntry` records posted by `OpsAdmin`: each names a `product_family`, a `species`, the `effective_week_start` Monday on which the price takes effect, and `index_price_cents_per_mbf`. When an INDEX-priced order line is priced, the applicable entry is the one matching the line product's family and species whose `effective_week_start` is on or before the pricing week; the latest such `effective_week_start` wins, and ties on the same effective week are broken by the entry's later `created_at`, so a re-posted price supersedes the earlier one. If no entry qualifies, the pricing attempt fails with `ERR_PRICE_INDEX_MISSING` (HTTP 409).

### 3.3. Branch Inventory: Receipt, Lots, and Valuation

An `OpsAdmin` registers each distribution branch with a unique `branch_code`, a `region_code` such as PNW, a `species_preference` drawn from the species enumeration reflecting regional building preference, a `target_stock_mbf` that drives replenishment demand in the closing waterfall, an `activity_score` from 0 to 100 that drives allocation ranking, and an optional `replenishment_enabled` flag. A `BranchManager` stocks a branch by receiving inventory lots. Receipt names the `product_id`, the `qty_received_mbf`, and the `unit_cost_cents_per_mbf` acquisition basis; the server stamps `received_at` from the logical clock, and that stamp drives FIFO ordering for the life of the lot. A fresh lot starts with `qty_available_mbf` equal to `qty_received_mbf`, both `qty_reserved_mbf` and `qty_sold_mbf` at 0, and `lot_status` `ON_HAND`.

Lot status is entirely derived from quantities, and lots move between statuses without any explicit operator action. When an order confirmation reserves the last available unit so that `qty_available_mbf` reaches 0 while `qty_reserved_mbf` is still positive, the lot moves from `ON_HAND` to `DEPLETED`. When a cancellation or a credit-suspension release restores availability above zero, the lot returns from `DEPLETED` to `ON_HAND`. When delivery completion converts the last reserved units into sold units, leaving `qty_available_mbf` at 0, `qty_reserved_mbf` at 0, and `qty_sold_mbf` positive, the lot becomes `SOLD_OUT` — including the direct path from `ON_HAND` to `SOLD_OUT` when a delivery completes against a lot whose entire remaining quantity was reserved. `SOLD_OUT` is terminal.

Branch valuation is a computed read offered to `BranchManager` and `OpsAdmin`, reporting two figures side by side. The FIFO figure, returned as `fifo_value_cents`, values each lot with remaining quantity — remaining being `qty_available_mbf` plus `qty_reserved_mbf`, sold quantity excluded — at that lot's own `unit_cost_cents_per_mbf`, walking lots oldest-first by `received_at` ascending with `created_at` ascending as the tie-break, which is the same order in which sales consume lots. The weighted-average figure, returned as `weighted_avg_value_cents`, computes a pool average cost per mbf as the sum of each lot's `qty_received_mbf` times its `unit_cost_cents_per_mbf`, divided by the sum of `qty_received_mbf`, over all lots ever received at the branch; the remaining value is that pool average multiplied by the total remaining quantity, rounded half-up to integer cents, and sales decrement the pool at the pool average rather than at any lot's own cost. Lots with zero remaining quantity are excluded from both figures. The response also carries `delta_cents`, the difference between the two figures. Both valuations are integer cents with no additional rounding.

### 3.4. Builder Onboarding and the Credit Lifecycle

A `CreditManager` onboards a builder by registering its `legal_name` and `lien_rights_state_code`, the two-letter state code that will govern lien rights on the builder's jobs. A new builder's `credit_status` is `PROVISIONAL`, its `credit_limit_cents` is 0, and both exposure counters start at 0.

Credit review is the `CreditManager`'s decision instrument, taking a `decision` of `APPROVE`, `SUSPEND`, or `CLOSE` plus, for approvals, a `credit_limit_cents`. Approving a `PROVISIONAL` builder moves it to `ACTIVE` and sets `credit_limit_cents`; the limit must be present and greater than 0. Approving a `SUSPENDED` builder returns it to `ACTIVE` and updates `credit_limit_cents` under the same requirement — but suspension is not self-healing: orders parked `ON_HOLD` by the suspension are not automatically re-confirmed and each requires an explicit confirm call afterward. Every credit-review transition bumps the builder's `version` by 1.

Suspending an `ACTIVE` builder moves it to `SUSPENDED` and triggers the broadest cascade in the system. Every one of the builder's sales orders currently `CONFIRMED` transitions to `ON_HOLD`; each such order's reserved inventory is released, decrementing `qty_reserved_mbf` and incrementing `qty_available_mbf` on the reserved lots, and any lot in `DEPLETED` whose availability is thereby restored returns to `ON_HAND`. The builder's `exposure_committed_cents` is deliberately left unchanged through the cascade — `ON_HOLD` orders still count as committed exposure.

Closing a builder, from either `ACTIVE` or `SUSPENDED`, is allowed only when the builder has no sales order in `CONFIRMED` or `ON_HOLD` and `exposure_settled_cents` is 0; the transition is otherwise rejected with `ERR_INVALID_STATE`. `CLOSED` is terminal. Throughout the lifecycle, `exposure_committed_cents` is the sum of `order_total_cents` over the builder's orders in `CONFIRMED` or `ON_HOLD`, and `exposure_settled_cents` is the sum of `delivered_total_cents` over the builder's orders in `DELIVERED`; a computed exposure read also reports `credit_limit_cents` and `credit_headroom_cents`, the last being the credit limit minus committed exposure minus settled exposure. Because settled exposure counts only delivered orders at `delivered_total_cents`, identical input data always yields a settled figure no larger than the committed one whenever any order is undelivered.

### 3.5. Jobs, Take-Offs, and the Builder-Direct Quote Cycle

An `AccountManager` opens a `BuilderJob` for a builder, supplying the `job_name`, the jobsite access window `access_window_start` and `access_window_end` (a closed interval — deliveries may touch either endpoint), a `placement_difficulty` of `STANDARD`, `TIGHT_ACCESS`, or `CRANE_ASSIST` (defaulting to `STANDARD` when omitted) which drives the delivery-fee multiplier, and `job_exposure_cap_cents`, the job-level ceiling on committed exposure. The job tracks its own `exposure_committed_cents` and `exposure_settled_cents` with the same definitions as the builder-level counters but scoped to this job's orders, and `last_completed_delivery_date`, which stays null until the job's first delivery completes.

The take-off service begins when a `BuilderContact` opens a `TakeoffRequest` on a job — the caller's `X-User-ID` must equal the job's `builder_id` or the attempt is `ERR_FORBIDDEN` — supplying a `plan_reference` for the uploaded plan set and `includes_floor_system_design` indicating whether floor system design support is requested; products whose `requires_design_support` flag is set expect this. The request starts in `takeoff_status` `SUBMITTED` with `design_package_reference`, `quoted_total_cents`, and `quoted_at` all null and `revision_count` at 0.

An `AccountManager` answers by submitting a design package, carrying `design_package_reference` and `quoted_total_cents`. From `SUBMITTED` this moves the request to `QUOTED`, setting both fields and stamping `quoted_at` from the logical clock. The same submission is also valid from `REVISION_REQUESTED`, in which case both fields are overwritten and `quoted_at` is refreshed. Submitting a design from any other status is `ERR_INVALID_STATE`.

A builder who wants changes requests a revision while the request is `QUOTED`, supplying a `revision_note`; the request moves to `REVISION_REQUESTED` and `revision_count` increments by 1. A builder who is satisfied accepts the quote, supplying the fulfilling `branch_id` and a `pricing_week_mode` of `LOCK_AT_ACCEPT` or `FLOAT_TO_SHIP`. Acceptance is guarded by three checks: the request must be `QUOTED`; the quote must be unexpired — acceptance or revision is rejected with `ERR_QUOTE_EXPIRED` (HTTP 400) once the logical clock is strictly later than `quoted_at` plus 14 days, while a quote at exactly the fourteen-day mark is still valid; and the builder's `credit_status` must be `ACTIVE`, with `SUSPENDED` rejecting as `ERR_BUILDER_CREDIT_SUSPENDED` (HTTP 402) and `PROVISIONAL` or `CLOSED` rejecting as `ERR_BUILDER_NOT_CREDIT_ACTIVE` (HTTP 402). Both revise and accept also enforce builder ownership as above. A successful acceptance moves the request to `ACCEPTED` and creates a `SalesOrder` in `DRAFT` whose `job_id`, `takeoff_request_id`, `branch_id`, and `pricing_week_mode` are set, whose `order_total_cents` equals the accepted `quoted_total_cents`, and whose `lines` is empty; the builder's `version` increments by 1. If the quote lapses, the request is treated as `EXPIRED` — the system evaluates the expiry at the moment an accept or revise is attempted against the strict fourteen-day comparison, and `EXPIRED` is terminal alongside `ACCEPTED`.

### 3.6. Order Entry, Pricing, and the Confirmation Gauntlet

Beyond take-off acceptance, an `AccountManager` may create a direct order on a job, supplying `branch_id`, `pricing_week_mode`, the `lines` array, an optional `code_report_reference`, and `expected_builder_version` per §2.7; the builder's `version` bumps by 1 on creation, and `takeoff_request_id` stays null on direct orders. Each entry of `lines` names a `product_id`, a `qty_mbf`, and a `price_basis` of `FIXED` or `INDEX`; a `FIXED` line must carry `fixed_unit_price_cents_per_mbf`, while an `INDEX` line ignores it. A new order is `DRAFT`, with `order_total_cents` and `delivered_total_cents` at 0 and `priced_week_start` null until pricing runs.

Confirming an order — valid from `DRAFT` and from `ON_HOLD` alike, with identical checks — is the gauntlet where pricing, inventory, and credit all engage. First the order must belong to a builder whose `credit_status` is `ACTIVE`, with the same split of `ERR_BUILDER_CREDIT_SUSPENDED` versus `ERR_BUILDER_NOT_CREDIT_ACTIVE` as take-off acceptance. Fiscal checks follow: the builder's `exposure_committed_cents` plus this order's `order_total_cents` must not exceed `credit_limit_cents` — equality is allowed — or the confirm is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402); likewise the job's `exposure_committed_cents` plus `order_total_cents` must not exceed `job_exposure_cap_cents`, equality allowed, or the confirm is `ERR_JOB_EXPOSURE_CAP_EXCEEDED` (HTTP 402). Specialty compliance requires that if any line's product has `requires_code_report` true, the order's `code_report_reference` must be non-null, else `ERR_CODE_REPORT_REQUIRED` (HTTP 400).

Pricing then runs per line. The pricing week is the Monday of the week containing the confirm date when `pricing_week_mode` is `LOCK_AT_ACCEPT`, and confirm pins `priced_week_start` to that week; `FLOAT_TO_SHIP` orders defer their final pricing to delivery completion as described in §3.7. For a `FIXED` line the unit price is `fixed_unit_price_cents_per_mbf`. For an `INDEX` line the unit price is the applicable index entry's `index_price_cents_per_mbf` plus the product's `index_premium_cents`, selected per the rules of §3.2 and failing with `ERR_PRICE_INDEX_MISSING` when no entry qualifies. A volume discount applies per line: no discount when `qty_mbf` is below 50, three percent when `qty_mbf` is at least 50 but below 100, and five percent when `qty_mbf` is 100 or more. Each line total is the quantity times the unit price times one minus the discount rate, rounded half-up to integer cents per line; `order_total_cents` is then the sum of the per-line rounded totals. The per-line-then-sum order is pinned — summing raw amounts and rounding once at the end is forbidden.

Inventory reservation is FIFO and atomic. For each line, the candidate lots are those at the order's `branch_id` for the line's product with `qty_available_mbf` greater than 0, walked oldest-first by `received_at` ascending with `created_at` ascending as tie-break. From each lot in turn the reservation takes the smaller of the line's remaining quantity and the lot's `qty_available_mbf`, incrementing the lot's `qty_reserved_mbf` and decrementing `qty_available_mbf` accordingly, until the line's `qty_mbf` is fully satisfied; a lot driven to zero availability with reservations outstanding becomes `DEPLETED`. If the total available across all candidate lots falls short of the line quantity, the entire confirm is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409) and nothing is reserved — there are no partial reservations.

A successful confirm moves the order to `CONFIRMED`, adds `order_total_cents` to both the builder's and the job's `exposure_committed_cents`, and bumps the builder's `version` by 1. Re-confirming from `ON_HOLD` — the path back after a credit suspension — re-runs this entire gauntlet, including a fresh FIFO reservation.

Cancellation is available from `DRAFT`, `CONFIRMED`, and `ON_HOLD`. From `DRAFT` the order simply becomes `CANCELLED` and the builder's `version` bumps. From `CONFIRMED`, cancellation additionally releases every reserved lot (restoring `qty_available_mbf` from `qty_reserved_mbf` and returning restored `DEPLETED` lots to `ON_HAND`), subtracts `order_total_cents` from both committed-exposure counters, and cascades the order's non-terminal deliveries — those `REQUESTED` or `SCHEDULED` — to `CANCELLED`, with a `SCHEDULED` delivery's truck shift having its `booked_drops` decremented. From `ON_HOLD`, cancellation subtracts `order_total_cents` from both committed counters without touching lots, since suspension already released them. Attempting to confirm or cancel an order in any other status, including the terminal `DELIVERED` and `CANCELLED`, is `ERR_INVALID_STATE`.

### 3.7. Fleet Operations: Scheduling, Completion, and Settlement

Delivery begins when an `AccountManager` requests one against a `CONFIRMED` order, supplying `boom_required`, and the requested window `window_start` to `window_end` interpreted as a half-open interval. An order that is not `CONFIRMED`, or that already has a non-terminal delivery outstanding, rejects the request with `ERR_ORDER_NOT_DELIVERABLE` (HTTP 400) — at most one live delivery exists per order at any time. The new delivery starts `REQUESTED` with `truck_shift_id`, `delivery_fee_cents`, and `completed_at` null and `fail_count` at 0.

Truck shifts are registered by `OpsAdmin` with a `fleet_code`, a `shift_date`, a half-open shift window `window_start` to `window_end`, a `boom_capable` flag, and an optional `max_drops` that defaults to 4 when omitted; `booked_drops` starts at 0. A new shift's `shift_status` is `OPEN`, and it remains `OPEN` while the logical clock is earlier than its `window_end`, becoming `CLOSED` otherwise.

Scheduling a delivery onto a shift is the `FleetCoordinator`'s responsibility, by `truck_shift_id`, and is valid from `REQUESTED` or `FAILED_ACCESS` under seven checks. The delivery's order must be `CONFIRMED`, else `ERR_ORDER_NOT_DELIVERABLE`. The shift must be `OPEN` — scheduling against a `CLOSED` shift is rejected with `ERR_INVALID_STATE` (HTTP 400). The delivery window must lie within the shift's half-open window `[window_start, window_end)`, else `ERR_DELIVERY_WINDOW_OUTSIDE_SHIFT` (HTTP 400). The delivery window must also lie within the job's access window `[access_window_start, access_window_end]` under closed containment — touching either endpoint is allowed — else `ERR_JOBSITE_ACCESS_WINDOW_VIOLATION` (HTTP 400). No other `SCHEDULED` delivery on the same shift may sit within a 45-minute buffer of the new window: if the new window starts before an existing delivery's window end plus 45 minutes, or an existing delivery's window starts before the new window's end plus 45 minutes, the attempt is `ERR_TRUCK_SHIFT_OVERLAP` (HTTP 409). A delivery with `boom_required` true may only take a shift whose `boom_capable` is true, else `ERR_BOOM_CAPABILITY_MISMATCH` (HTTP 409). And the shift's `booked_drops` must be below `max_drops`, else `ERR_SHIFT_DROP_LIMIT_REACHED` (HTTP 409).

A successful schedule moves the delivery to `SCHEDULED`, sets `truck_shift_id`, increments the shift's `booked_drops` by 1, and computes `delivery_fee_cents`. The fee is built from two components, each rounded half-up to integer cents before they are summed: the base component is 7501 cents times the job's placement multiplier, and the boom component — present only when `boom_required` is true — is 4003 cents times the same multiplier. The multiplier is 1.0 for `STANDARD`, 1.25 for `TIGHT_ACCESS`, and 1.5 for `CRANE_ASSIST`. Component-wise rounding then summation is pinned; rounding the combined amount once is the forbidden order.

Completing a `SCHEDULED` delivery takes an `outcome`. When `outcome` is `COMPLETED`, `completed_at` is stamped from the logical clock and the parent order cascades from `CONFIRMED` to `DELIVERED`: on every reserved lot the delivered quantity moves from `qty_reserved_mbf` into `qty_sold_mbf`, with fully sold lots becoming `SOLD_OUT`; for `FLOAT_TO_SHIP` orders, `priced_week_start` is pinned to the Monday of the delivery-completion week and `order_total_cents` is recomputed via the same per-line pricing of §3.6 before any exposure accounting occurs; `delivered_total_cents` becomes `order_total_cents`; the job's `exposure_committed_cents` decreases by `order_total_cents` while its `exposure_settled_cents` increases by `delivered_total_cents`, and `last_completed_delivery_date` is set to the completion date; the builder's committed and settled counters shift identically; and the builder's `version` bumps by 1. When `outcome` is `FAILED_ACCESS`, the delivery instead moves to `FAILED_ACCESS`, `fail_count` increments by 1, the shift's `booked_drops` decrements by 1, and `truck_shift_id` is cleared to null — the delivery is then eligible to be scheduled again under the same seven checks. Deliveries `REQUESTED` or `SCHEDULED` that fall under an order cancellation move to `CANCELLED` as described in §3.6, with a scheduled one also decrementing its shift's `booked_drops`. `COMPLETED` and `CANCELLED` are terminal; completing a delivery in any status other than `SCHEDULED` is `ERR_INVALID_STATE`.

### 3.8. Lien Rights: Filing, Deadlines, and Release

When delivered exposure on a job goes unsettled, a `CreditManager` may file a `LienFiling` against the job. Filing is guarded by three checks evaluated in a pinned order. First, the job's `exposure_settled_cents` must be greater than 0, else `ERR_LIEN_NO_OUTSTANDING_EXPOSURE` (HTTP 402). Second, the logical-clock date must be on or before the lien deadline — filing exactly on the deadline day is allowed — where the deadline is the job's `last_completed_delivery_date` plus 90 days; a date past the deadline rejects with `ERR_LIEN_DEADLINE_PASSED` (HTTP 400). Third, no other lien on the same job may currently be in `FILED`, else `ERR_LIEN_ALREADY_ACTIVE` (HTTP 409). A filed lien starts in `lien_status` `FILED`, records `amount_cents` as the job's `exposure_settled_cents` at filing time, stamps `filed_at` from the logical clock, carries the computed `deadline_date`, and holds `released_at` null until release.

Release is a `CreditManager` action valid only while the lien is `FILED`; it moves the lien to `RELEASED` and stamps `released_at` from the logical clock, with any other status rejecting as `ERR_INVALID_STATE`. Independently of operator action, a lien still in `FILED` is treated as `EXPIRED` once the job's `exposure_settled_cents` reaches 0 — the system evaluates this on lien-filing reads and on job mutations. `RELEASED` and `EXPIRED` are both terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201; endpoints that modify an existing resource or perform a computed read respond with 200. All responses use the envelope of §2.2, and list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /_clock/set_current_utc | Advance the server logical clock to a supplied `to_iso8601` instant | OpsAdmin |
| POST | /capacity-weeks | Create a mill production capacity week (OPEN) | MillPlanner |
| POST | /capacity-weeks/{capacity_week_id}/allocate | Set the internal/market allocation split on an OPEN week (OCC on week version) | MillPlanner |
| POST | /capacity-weeks/{capacity_week_id}/close | Close the week: run the allocation waterfall, set committed fields and fill rate | MillPlanner |
| POST | /products | Create a product SKU | OpsAdmin |
| POST | /price-index-entries | Post a commodity price index entry for a family+species | OpsAdmin |
| POST | /branches | Create a distribution branch | OpsAdmin |
| GET | /branches/{branch_id}/valuation | Computed read: FIFO and weighted-average inventory valuation for the branch | BranchManager, OpsAdmin |
| POST | /branches/{branch_id}/inventory-lots | Receive an inventory lot at a branch (`received_at` stamped from logical clock) | BranchManager |
| GET | /inventory-lots/{lot_id} | Get a single inventory lot | all roles |
| GET | /inventory-lots | List inventory lots, filterable by `product_id`, `branch_id`, `lot_status` | all roles |
| POST | /builders | Onboard a builder customer (PROVISIONAL) | CreditManager |
| GET | /builders/{builder_id} | Get builder detail (includes `version` for OCC) | all roles |
| POST | /builders/{builder_id}/credit-review | Credit decision: APPROVE (requires `credit_limit_cents`), SUSPEND, or CLOSE | CreditManager |
| GET | /builders/{builder_id}/exposure | Computed read: committed/settled exposure, limit and headroom | CreditManager, AccountManager |
| POST | /builders/{id}/jobs | Create a builder jobsite project | AccountManager |
| GET | /jobs/{job_id} | Get job detail | all roles |
| GET | /builders/{id}/jobs | List a builder's jobs | all roles |
| POST | /jobs/{id}/takeoff-requests | Builder opens a take-off service request on a job (SUBMITTED) | BuilderContact |
| GET | /takeoff-requests/{takeoff_id} | Get takeoff request detail | all roles |
| POST | /takeoff-requests/{takeoff_id}/submit-design | Upload design package and quoted total (SUBMITTED or REVISION_REQUESTED to QUOTED) | AccountManager |
| POST | /takeoff-requests/{takeoff_id}/revise | Builder requests changes on a QUOTED takeoff (to REVISION_REQUESTED) | BuilderContact |
| POST | /takeoff-requests/{takeoff_id}/accept | Builder accepts a QUOTED, unexpired takeoff; creates a DRAFT SalesOrder at `quoted_total_cents` | BuilderContact |
| GET | /jobs/{id}/takeoff-requests | List takeoff requests for a job | all roles |
| POST | /jobs/{job_id}/sales-orders | Create a direct (non-takeoff) DRAFT sales order (OCC on Builder version) | AccountManager |
| GET | /sales-orders/{order_id} | Get sales order detail | all roles |
| GET | /sales-orders | List sales orders, filterable by `job_id`, `branch_id`, `takeoff_request_id`, `order_status` | all roles |
| POST | /sales-orders/{order_id}/confirm | Confirm a DRAFT or ON_HOLD order: pricing, FIFO reservation, credit and cap checks | AccountManager |
| POST | /sales-orders/{order_id}/cancel | Cancel a DRAFT, CONFIRMED or ON_HOLD order; releases reservations and unwinds exposure | AccountManager |
| POST | /sales-orders/{order_id}/deliveries | Request a delivery for a CONFIRMED order (REQUESTED) | AccountManager |
| GET | /deliveries/{delivery_id} | Get delivery detail | all roles |
| GET | /deliveries | List deliveries, filterable by `truck_shift_id`, `sales_order_id`, `delivery_status` | all roles |
| POST | /deliveries/{delivery_id}/schedule | Assign a truck shift; validates windows, buffer, boom, drop limit; computes the delivery fee | FleetCoordinator |
| POST | /deliveries/{delivery_id}/complete | Complete a SCHEDULED delivery with outcome COMPLETED or FAILED_ACCESS | FleetCoordinator |
| POST | /truck-shifts | Create a truck shift resource | OpsAdmin |
| GET | /truck-shifts/{shift_id} | Get truck shift detail | all roles |
| POST | /jobs/{id}/lien-filings | File a lien against a job (immediately FILED when eligible) | CreditManager |
| POST | /lien-filings/{lien_id}/release | Release a FILED lien | CreditManager |
| GET | /jobs/{id}/lien-filings | List lien filings for a job | all roles |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this table is the authoritative identifier-to-status mapping.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 400 |
| ERR_QUOTE_EXPIRED | 400 |
| ERR_DELIVERY_WINDOW_OUTSIDE_SHIFT | 400 |
| ERR_JOBSITE_ACCESS_WINDOW_VIOLATION | 400 |
| ERR_TRUCK_SHIFT_OVERLAP | 409 |
| ERR_LIEN_DEADLINE_PASSED | 400 |
| ERR_CODE_REPORT_REQUIRED | 400 |
| ERR_CAPACITY_EXCEEDED | 409 |
| ERR_PRICE_INDEX_MISSING | 409 |
| ERR_BOOM_CAPABILITY_MISMATCH | 409 |
| ERR_SHIFT_DROP_LIMIT_REACHED | 409 |
| ERR_LIEN_ALREADY_ACTIVE | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_BUILDER_CREDIT_SUSPENDED | 402 |
| ERR_BUILDER_NOT_CREDIT_ACTIVE | 402 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_JOB_EXPOSURE_CAP_EXCEEDED | 402 |
| ERR_LIEN_NO_OUTSTANDING_EXPOSURE | 402 |
| ERR_ORDER_NOT_DELIVERABLE | 400 |
