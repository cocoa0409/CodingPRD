# Electronic Component Distribution API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an Electronic Component Distribution API of the kind operated by broad-line franchised distributors (Arrow, Avnet). The system manages the full commercial lifecycle of semiconductor and passive-component distribution: franchised versus open-market sourcing and the authenticity controls that distinguish them, date-code and moisture-sensitivity handling on the warehouse floor, fair-share allocation of scarce parts during shortage conditions, ship-and-debit claims against supplier-registered design wins, scheduled-order lifecycle management under NCNR terms, customer-approved cross-reference substitution, and excess/shortage buy-back programs.

Distributors in this market operate under competing pressures. Suppliers demand rigorous segregation between authorized franchise inventory (which carries full traceability) and open-market stock (which carries counterfeit risk and must be authenticated before it can ship). Customers demand predictable allocation when supply tightens and contractual flexibility through reschedule and cancel windows. Finance demands that every shipment be checked against open credit, and that ship-and-debit claims reconcile cleanly against supplier cost-down agreements. The API described here is the operational backbone that enforces all of these constraints atomically, with a logical-clock-driven sweep that promotes moisture-sensitivity violations into quarantine cascades and expires design registrations as their validity windows pass.

The system is built for six cooperating roles spanning the distributor, its customers, its suppliers, and its quality function, with segregation of duties enforced where an actor could otherwise inspect their own work. All mutating operations are immediately visible to subsequent reads, and a small set of optimistic-concurrency guards prevents clients from overwriting changes they have not observed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `DistributorAdmin`, `SalesRep`, `CustomerBuyer`, `WarehouseOps`, `QualityInspector`, and `SupplierAdmin`. Failure to provide valid headers — either header missing, or a role value not among the six declared roles — results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Access to specific operations is restricted by role; an attempt to perform an action outside of a user's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Five of the six roles carry an opaque operator identity not tied to any persisted entity. When `X-User-Role` is `DistributorAdmin`, `SalesRep`, `WarehouseOps`, `QualityInspector`, or `SupplierAdmin`, `X-User-ID` is an opaque operator identifier; the server may record it (for example, as `received_by_user_id` on an `InventoryLot` at lot receipt, which is the segregation-of-duties anchor for later inspection) but does not compare it to any entity's `id`. When `X-User-Role` is `CustomerBuyer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. This entity-backed identity is what allows a customer-side buyer to act only on their own orders, registrations, alternate approvals, and buy-back requests. Ownership constrains mutating operations only: read operations (`GET`) perform no ownership check, so any authenticated role may read any resource, per the `Any` authorization in §4.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Because many resources can be created within a single logical-clock instant, ties on `created_at` are broken by creation sequence — the order in which the resources were created — on every list endpoint. Order lines carry an additional tie-break: lines created together in a single order-creation request are ordered by their array index in that request.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the System Sweep

The server maintains a logical clock rather than trusting wall-clock time. At startup, before any client has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. A `DistributorAdmin` may advance the logical clock to a supplied `to_iso8601` instant through a test-driving capability; the response reports the resulting `now`. A missing or unparseable `to_iso8601` is `ERR_INVALID_REQUEST`, and the supplied instant is applied as supplied — the server performs no monotonicity check, so the clock can be set to an instant earlier than its current reading.

Advancing the clock triggers the system sweep, which runs two reconciliations in sequence. First, every design registration in `SUBMITTED` or `APPROVED` whose `valid_to` is earlier than the new `now` is transitioned to `EXPIRED`; since `valid_to` is a calendar date, this comparison is by calendar date — a registration expires only once the new current calendar date is strictly after its `valid_to`, so it remains live through its entire `valid_to` day. Second, every lot's cumulative moisture exposure is recomputed from its exposure intervals; any lot in `AVAILABLE` whose recomputed exposure has reached or exceeded its part's floor life is moved to `QUARANTINED`, and the quarantine cascade described in §3.5 runs on it. The same moisture-exposure computation is also evaluated on read, so a lot's `msl_exposure_hours` is always current as of the logical clock.

### 2.5. Franchise Authenticity and Segregation of Duties

Every inventory lot is received with a declared `source_type` of either `FRANCHISED` or `OPEN_MARKET`. A `FRANCHISED` lot is only lawful when the part's manufacturer line is itself a franchised line — that is, the line's `sourcing_channel` is `FRANCHISED`. The inspector's verdict is submitted as a `disposition` of `AUTHENTICATE` or `REJECT`. Receiving a `FRANCHISED` lot for a part whose line is not franchised is rejected with `ERR_CHANNEL_MISMATCH`. Franchised stock is presumed authentic by chain of custody: such lots begin life already `AVAILABLE`, with their `authenticity` recorded as `NOT_REQUIRED`.

Open-market stock carries counterfeit risk and is therefore born suspect. An `OPEN_MARKET` lot begins `IN_INSPECTION` with `authenticity` set to `PENDING_INSPECTION`, and it contributes nothing to available supply until a `QualityInspector` authenticates it. To prevent self-approval, the inspector must be a different operator than the receiver: the lot records the receiving operator's `X-User-ID` as `received_by_user_id` at receipt, and an inspection attempted by that same user is rejected with `ERR_SEGREGATION_OF_DUTIES`. An inspection attempted on a lot that is no longer `IN_INSPECTION` is rejected with `ERR_INSPECTION_NOT_PENDING`. A disposition of `AUTHENTICATE` moves the lot to `AVAILABLE` and stamps `authenticity` as `AUTHENTICATED`; a disposition of `REJECT` moves it to the terminal `REJECTED` state with `authenticity` `REJECTED`.

### 2.6. Moisture Sensitivity and Date-Code Freshness

Parts carry a JEDEC moisture sensitivity level `msl_level` — conventionally in the JEDEC range 1 through 6, though the server records any supplied integer without range validation — together with a `floor_life_hours` budget — the cumulative ambient exposure hours a lot may accumulate since its last bake before it must be re-baked. Warehouse staff open a lot's dry pack by creating a `MoistureExposure` interval against it — the interval's `lot_id` is the lot named in the path — optionally annotated with a `note`; the interval records `opened_at` from the logical clock, and `sealed_at` remains null while the interval is open. Opening is permitted only while the lot is `AVAILABLE` — otherwise `ERR_LOT_NOT_AVAILABLE` — and only when no other interval of the same lot is still unsealed, otherwise `ERR_EXPOSURE_ALREADY_OPEN`. Adjacency at a seal boundary is allowed: a new interval may open at the exact instant the prior one sealed; nesting is not. Sealing an interval stamps `sealed_at` from the logical clock; sealing an already-sealed interval is rejected with `ERR_EXPOSURE_NOT_OPEN`.

A lot's `msl_exposure_hours` is computed over the lot's exposure intervals that began strictly after `last_baked_at`: the server accumulates each qualifying interval's raw elapsed time — `sealed_at` minus `opened_at` for a sealed interval, `now` minus `opened_at` for an interval still open, and nothing for an interval whose end does not exceed its start — and then converts the accumulated total to whole hours, discarding the fractional remainder exactly once, on the total rather than per interval. A lot that has never been baked — `last_baked_at` still null — counts all of its intervals. When this cumulative figure reaches or exceeds the part's `floor_life_hours` (equality is a breach), the lot is quarantined by the sweep.

Independently of moisture, parts enforce date-code freshness at ship time. Each lot carries a `date_code` in `YYYYMM` format (month precision), and each part carries `date_code_limit_months`, the maximum age a lot may have when it ships. The elapsed age in whole months is computed from the calendar-year and calendar-month difference between the logical clock and the lot's date code. A lot whose elapsed age in months is at most the part's limit is shippable — the boundary is inclusive, so a lot exactly at the limit is still fresh, while one month beyond it is stale and any ship pick touching it fails with `ERR_DATE_CODE_TOO_OLD`.

### 2.7. Nested Resource Retrieval

The API enforces strict left-to-right validation for every request that targets nested resources. When an endpoint path contains multiple resource identifiers — for example an order followed by one of its lines, or a lot followed by one of its exposures — the system validates the existence of each identifier in sequence, starting from the leftmost. The request is rejected immediately with the 404 error corresponding to the first identifier that does not resolve to an existing resource: `ERR_ORDER_NOT_FOUND` before `ERR_ORDER_LINE_NOT_FOUND`, and `ERR_LOT_NOT_FOUND` before `ERR_EXPOSURE_NOT_FOUND`. An exposure identifier must additionally belong to the lot named in the path; an exposure that exists under a different lot is reported as `ERR_EXPOSURE_NOT_FOUND` for the path under inspection. The same left-to-right discipline applies to foreign keys carried in request bodies: a `manufacturer_line_id`, `customer_id`, `part_id`, `order_line_id`, `primary_part_id`, or `alternate_part_id` that names no existing resource surfaces its own specific 404 (`ERR_MANUFACTURER_LINE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, and so on through `ERR_REGISTRATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_BUYBACK_NOT_FOUND`, `ERR_ALLOCATION_RUN_NOT_FOUND`, and `ERR_ALTERNATE_APPROVAL_NOT_FOUND`). A request whose path matches no defined endpoint at all is rejected with a generic `ERR_NOT_FOUND` (404), and a defined path invoked with an unsupported HTTP method with `ERR_METHOD_NOT_ALLOWED` (405).

### 2.8. Common Resource Properties

Every top-level resource — manufacturer lines, parts, customers, design registrations, orders, order lines, inventory lots, moisture exposures, alternate-part approvals, allocation runs, ship-and-debit claims, and buy-back requests — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; refreshed on every mutation.
- **`version`** (integer): a system-managed integer that increments by one on every mutation, and which backs the optimistic-concurrency guards of §2.10.

Mutations that cascade — a quarantine releasing reservations across many orders, an allocation publish touching many lines — refresh `updated_at` and increment `version` on each touched parent resource individually, so clients always observe a consistent read-after-write snapshot.

Beyond `created_at` and `updated_at`, four further fields are stamped from the logical clock as operations occur: a moisture exposure's `opened_at` and `sealed_at` (§2.6), a lot's `last_baked_at` (§3.5), and an order line's `last_shipped_at` (§3.6). Each is an ISO 8601 UTC timestamp rendered at seconds precision — for example `2026-08-01T00:00:00Z` — whenever the logical clock sits exactly on a whole-second instant, and with three fractional digits, like `created_at`, at any other instant.

### 2.9. Monetary Precision and Rounding

All monetary amounts are carried as integer cents; there is no floating-point money anywhere in the system. Derived credit amounts are rounded only once, after the full product of units, price basis, and net-of-fee fraction has been computed, using the round-half-up method to integer cents. Allocation arithmetic works in whole units: raw fair shares are floored per line before remainder units are distributed one at a time, and no exact-split rounding is ever applied. Moisture exposure accrues in whole hours, and date-code age in whole months. Fee-tier boundaries and percentage caps are evaluated against these integer quantities.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. A request to create an allocation run must carry `expected_part_version` equal to the target part's current `version`; if another writer has advanced the part's version since the client last read it — for example by publishing an earlier run — the creation is rejected with `ERR_STALE_PART_VERSION` (HTTP 412), because a writer holding a stale part view would otherwise supersede the prior provisional run on the basis of an out-of-date supply-and-demand picture. Symmetrically, a request to reschedule an order line must carry `expected_order_version` equal to the order's current `version`; a mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), since rescheduling against a stale view could move a ship date without awareness of an intervening reschedule or line cancellation. No other endpoint accepts a version field; the OCC fields are non-optional on these two operations.

### 2.11. Validation Priority Order

When several rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. Authentication context comes first (missing or malformed identity headers), followed by role authorization for the endpoint. Request shape is validated next — a missing required field, a wrong type, an invalid enum member, a non-positive quantity, a malformed date, datetime, or `date_code` field, or an empty `lines` array is `ERR_INVALID_REQUEST` — and then path identifiers are resolved to their 404s, leftmost first per §2.7. `CustomerBuyer` ownership is checked once the acting customer is known — from the resolved path resource (for example, the resolved order's `customer_id`) or from the body's `customer_id` — and only then are body foreign keys resolved to their 404s. State preconditions on the target resource follow — this group includes the shipped-lines guard at whole-order cancel (`ERR_ORDER_HAS_SHIPPED_LINES`) and the optimistic-concurrency version guard of §2.10, which is evaluated immediately after the state preconditions on its target resource (or, where the target carries no state precondition, as on allocation-run creation, immediately after its identifier resolves) — then business-safety checks (segregation of duties at inspection, date-code freshness at ship), then business constraints (uniqueness, channel match, exposure interval discipline, registration window overlap, quantity sufficiency), then temporal-window checks (cancel, reschedule, ship-date, NCNR, and buy-back windows), then referential checks (alternate approval, shortage-in-effect), and finally fiscal checks — the credit limit at ship and the buy-back cap — which always run last. Within the cancellation-terms group, the NCNR check is evaluated before the cancel-window check, so a non-cancellable line surfaces `ERR_LINE_NCNR` even when its window has also closed. Likewise, safety beats fiscal: a ship that would fail both the date-code check and the credit check surfaces `ERR_DATE_CODE_TOO_OLD`.

## 3. Business Logic & Workflows

### 3.1. Catalog: Manufacturer Lines and Parts

A `DistributorAdmin` builds the catalog from the top down. A manufacturer line is created with a `line_code` that must be unique across all lines — a duplicate is rejected with `ERR_DUPLICATE_LINE_CODE` — plus a human-readable `name` and a `sourcing_channel` of `FRANCHISED` or `OPEN_MARKET` declaring whether the line is an authorized franchise line. Three commercial terms attach to the line and shape every order placed against it: `ncnr`, a boolean defaulting to false, marking all of the line's parts as non-cancellable/non-returnable; `cancel_window_days`, defaulting to 30, the number of days before a line's ship date by which cancellation must occur; and `reschedule_window_days`, defaulting to 20, the analogous cutoff for moving a ship date. The line also declares an `allocation_policy` — `BACKLOG_BASIS` by default, or `USAGE_BASIS` — which selects the fair-share weighting used when shortage allocation runs are computed for its parts. Each line maintains a running `open_debit_balance_cents`, initialized to zero at creation and reconciled later by ship-and-debit settlement (§3.7).

Parts are created under a line by reference to `manufacturer_line_id`, with a `part_number` unique within that line — duplicates are rejected with `ERR_DUPLICATE_PART_NUMBER`. Alongside the moisture and date-code attributes of §2.6, a part carries two commercial prices: `standard_cost_cents`, the distributor's standard buy cost per unit, which becomes the supplier debit baseline for ship-and-debit; and `book_price_cents`, the default sell price per unit, which is snapshotted onto order lines at acknowledge time. Three computed quantities summarize a part's position at all times: `qty_on_hand`, the sum of unreserved units over the part's `AVAILABLE` lots; `qty_reserved`, the sum of reserved units over those same lots; and `open_demand_qty`, the sum of `quantity` over the part's order lines that are `OPEN` under an `ACKNOWLEDGED` order. These figures are recomputed on every event that moves inventory or demand — lot receipt, inspection, quarantine, bake, order acknowledge, allocation publish, cancel release, and ship.

Customers are created with a `name`, a `credit_limit_cents`, and an externally maintained accounts-receivable `open_balance_cents` that defaults to zero. Two CRM-maintained trailing-twelve-month figures, `trailing_12mo_purchases_cents` and `trailing_12mo_component_usage_units`, both default to zero and feed respectively the excess buy-back cap and the usage-basis allocation weight of §3.6. A customer's `status` begins `GOOD_STANDING` unless the creation request explicitly supplies a `status` — the only recognized values are `GOOD_STANDING` and `CREDIT_HOLD`, and any other value is `ERR_INVALID_REQUEST`; since there is no customer-update operation, creation-time status is the only way a customer enters `CREDIT_HOLD`. A customer in `CREDIT_HOLD` may not place new orders and may not have orders acknowledged — both attempts are rejected with `ERR_CUSTOMER_CREDIT_HOLD`.

### 3.2. Design Registrations

When the distributor wins a design at an end customer, a `SalesRep` or the `CustomerBuyer` submits a design registration naming the `customer_id`, the registered `part_id`, the `end_customer_name` where the design win occurred, the supplier-approved special cost `registered_cost_cents`, the maximum coverable units `max_registered_qty`, and a validity window from `valid_from` through `valid_to`. The server does not require `valid_from` to be on or before `valid_to`; an inverted window is stored as supplied and simply never covers a ship date. The window is a closed interval on both ends, and windows for the same customer and part may not overlap among registrations in `SUBMITTED` or `APPROVED` — because the intervals are closed, a new window whose `valid_from` lands exactly on an existing window's `valid_to` already conflicts and is rejected with `ERR_REGISTRATION_WINDOW_OVERLAP`.

A registration is born `SUBMITTED` with `registered_qty_remaining` at zero; it covers nothing until the supplier acts. A `SupplierAdmin` renders the outcome as a `decision` of `APPROVE` or `REJECT` with an optional `reason`: approving moves the registration to `APPROVED` and initializes `registered_qty_remaining` to the full `max_registered_qty`; rejecting moves it to `REJECTED`. The `reason` — like the optional `reason` or `note` carried by the other decision-style operations in this document — is accepted by the server but not persisted on the resource and never echoed in responses. A decision attempted on a registration that has left `SUBMITTED` is rejected with `ERR_REGISTRATION_NOT_SUBMITTED`. The logical-clock sweep expires any `SUBMITTED` or `APPROVED` registration once `now` passes `valid_to`. An approved registration whose remaining quantity is fully consumed by claims transitions to `EXHAUSTED`; if a later claim rejection or reversal restores remaining quantity above zero, the registration returns automatically from `EXHAUSTED` to `APPROVED`.

### 3.3. Orders: Booking, Acknowledgement, and the Cancellation Terms

An order is booked by a `SalesRep`, or by a `CustomerBuyer` acting for their own account, with a `customer_id`, an optional `note`, and a non-empty `lines` array — an order without lines is `ERR_INVALID_REQUEST`. Each line names a `part_id`, a `quantity` greater than zero, and a requested `ship_date`. Lines are created inline with the order and begin `OPEN`; the order itself begins `SUBMITTED`. Booking against a customer in `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_CREDIT_HOLD`.

Acknowledgement by a `SalesRep` is the moment commercial terms crystallize. It is permitted only from `SUBMITTED` — otherwise `ERR_ORDER_NOT_SUBMITTED` — and only while the customer remains `GOOD_STANDING`. On acknowledgement the system snapshots onto every line the part's current `book_price_cents` as `unit_price_cents`, the line's `ncnr_snapshot` from the manufacturer line, and both window lengths as `cancel_window_days_snapshot` and `reschedule_window_days_snapshot`. From those snapshots each line's `cancel_by_date` is computed as its `ship_date` minus `cancel_window_days_snapshot`. The order advances to `ACKNOWLEDGED`, its `open_exposure_cents` is computed for the first time, and its `version` increments. Both order monetary figures are sums over the order's lines at snapshot prices: `open_exposure_cents` is the sum of (`quantity` minus `shipped_qty`) times `unit_price_cents` over lines still `OPEN` or `ALLOCATED`, and `allocated_value_cents` is the sum of `allocated_qty` times `unit_price_cents` over all lines; every later "recompute" of these figures in this document applies these same two formulas.

From acknowledgement onward, the cancellation terms govern both whole-order cancellation by a `SalesRep` or the owning `CustomerBuyer`, and single-line cancellation. Cancelling an entire order requires it to be `ACKNOWLEDGED` (from any other state the attempt draws `ERR_ORDER_NOT_ACKNOWLEDGED`), requires that no line have a `shipped_qty` greater than zero (`ERR_ORDER_HAS_SHIPPED_LINES`), and then applies the cancellation-terms group to every line still `OPEN` or `ALLOCATED`: the NCNR check first, rejecting with `ERR_LINE_NCNR` when `ncnr_snapshot` is true, then the window check, rejecting with `ERR_CANCEL_WINDOW_CLOSED` once the logical clock's calendar date has reached or passed the line's `cancel_by_date` — the comparison is by calendar date, and the window is open only while the current date is strictly before that date. The terms group is validated against every open line before any line is cancelled, so a single failing line rejects a whole-order cancel atomically, with no line cancelled. Cancelling one line follows the same terms group against the line itself, and additionally requires the order to be `ACKNOWLEDGED` or `PARTIALLY_SHIPPED` and the line to be `OPEN` or `ALLOCATED`; a line already `SHIPPED` or `CANCELLED` draws `ERR_LINE_NOT_OPEN_OR_ALLOCATED`.

Cancellation releases what it touches. Every cancelled line moves to `CANCELLED`; for a line that held an allocation, its reserved units walk back across the part's lots — oldest date code first, ties broken by lot creation order, considering only lots with `qty_reserved` above zero — moving units from `qty_reserved` back into `qty_on_hand`. A whole-order cancel zeroes the order's `open_exposure_cents` and `allocated_value_cents`; a single-line cancel recomputes them. Either way the order's `version` increments. When every line of an acknowledged order has been cancelled individually and nothing ever shipped, the order itself falls automatically to `CANCELLED` with both monetary figures zeroed.

Rescheduling moves a line's `ship_date` to a `new_ship_date`, permitted to a `SalesRep` or the owning `CustomerBuyer` while the order is `ACKNOWLEDGED` and while the logical clock's calendar date is still strictly earlier than the current `ship_date` minus `reschedule_window_days_snapshot` — the cutoff comparison is by calendar date, and at or past that cutoff date the attempt is `ERR_RESCHEDULE_WINDOW_CLOSED`. The new date must be strictly later than the current calendar date, and for an NCNR line the reschedule may only push the date outward — the new date must be strictly later than the current `ship_date`, so rescheduling an NCNR line to its existing date is also rejected; either violation surfaces `ERR_SHIP_DATE_IN_PAST`. A successful reschedule rewrites the line's `ship_date`, recomputes its `cancel_by_date` from the snapshot window, and increments the order's `version`. This operation is one of the two OCC-guarded writes of §2.10: the request must carry `expected_order_version` matching the order's current `version`, or it is refused with `ERR_STALE_ORDER_VERSION`; the order-state precondition is evaluated before the version check, so a reschedule against a non-`ACKNOWLEDGED` order draws `ERR_ORDER_NOT_ACKNOWLEDGED` even when the expected version is also stale.

### 3.4. Shortage Allocation: Fair-Share Runs and Publication

When a part is scarce, a `DistributorAdmin` computes a fair-share allocation run. Creating a run is OCC-guarded on the part: the request must carry `expected_part_version` equal to the part's current `version`, else `ERR_STALE_PART_VERSION`. At most one `PROVISIONAL` run exists per part at a time, so creating a new run automatically moves any prior `PROVISIONAL` run for the same part to `SUPERSEDED`; creation also increments the part's `version`.

The run snapshots its `basis` from the part's line `allocation_policy` at creation time, and computes supply and demand from the live state: `total_supply_qty` is the sum of `qty_on_hand` across the part's `AVAILABLE` lots, and `total_demand_qty` is the sum of `quantity` across eligible lines — those that are `OPEN`, belong to an `ACKNOWLEDGED` order, and reference the run's part. An empty supply is rejected with `ERR_NO_ALLOCATABLE_SUPPLY`; empty eligible demand with `ERR_NO_OPEN_DEMAND`. When supply meets or exceeds demand, every eligible line is allocated its full `quantity`. In shortage, the waterfall runs: each line's weight is its booked `quantity` under `BACKLOG_BASIS`, or its ordering customer's `trailing_12mo_component_usage_units` under `USAGE_BASIS` — so identical booked quantities split equally under backlog basis but can diverge sharply under usage basis. Each line's raw share is the floor of the total supply multiplied by its weight and divided by the sum of all weights — if every weight is zero (possible under `USAGE_BASIS`), every raw share is zero and the whole supply flows into the remainder distribution below; each line is tentatively allocated the lesser of its raw share and its booked quantity. The units left over after this flooring are then distributed one unit per pass, iterating the lines that remain below their booked quantity ordered by line creation order — the sequence in which the lines were created, with lines created together in a single order-creation request following their array index in that request, so the ordering stays total even when several lines carry the same `created_at` timestamp — then by ship date, then by descending quantity, granting one unit each and repeating passes until the remainder is exhausted. The computed `lines` array of `{ order_line_id, allocated_qty }` pairs is stored on the run sorted by order line creation time ascending.

A provisional run changes nothing on the ground until a `DistributorAdmin` publishes it. Publishing requires the run still be `PROVISIONAL` — otherwise `ERR_ALLOCATION_RUN_NOT_PROVISIONAL` — and re-verifies that the current available supply still covers the sum of the run's allocated quantities; if intervening events have eroded supply below that total, publication fails with `ERR_QUANTITY_EXCEEDS_AVAILABLE`. On publish, each run line's target order line moves from `OPEN` to `ALLOCATED` with its `allocated_qty` set from the run — a run line whose target order line is no longer `OPEN` at publish time (for example, a line cancelled since the run was computed) is skipped and receives no allocation, though the supply re-verification and the reservation waterfall still use the run's full stored totals — and the reservation waterfall walks the part's `AVAILABLE` lots oldest date code first (ties by creation order), moving units from `qty_on_hand` into `qty_reserved` until every allocated unit is reserved. Each touched order's `allocated_value_cents` is recomputed, with its `version` and `updated_at` bumped; the part's `qty_on_hand`, `qty_reserved`, and `open_demand_qty` are recomputed; and the part's `version` increments.

### 3.5. Quarantine, Bake, and the Release Cascade

The quarantine cascade is the system's deepest automatic reconciliation. When the clock sweep finds an `AVAILABLE` lot whose recomputed `msl_exposure_hours` has reached its part's `floor_life_hours`, the lot moves to `QUARANTINED` and its reservations unwind: the lot's `qty_on_hand` absorbs its full `qty_reserved`, which is then zeroed. Those released units are then clawed back from the part's `ALLOCATED` order lines newest first — descending line creation time, ties broken by descending ship date — decrementing each line's `allocated_qty` by the released amount in turn; a line whose allocation falls to zero drops back from `ALLOCATED` to `OPEN`. Every order touched by the cascade has its `allocated_value_cents` and `open_exposure_cents` recomputed and its `version` and `updated_at` bumped, and the part's availability figures are recomputed. The cascade is the intended serialization point between shortage allocation and moisture handling: an order line can lose its allocation without any client action, simply because the clock moved.

A quarantined lot is not lost; it must be baked. A `WarehouseOps` operator bakes a lot that is `QUARANTINED` — any other state draws `ERR_LOT_NOT_QUARANTINED` — and only while no exposure interval of the lot remains unsealed (`ERR_EXPOSURE_ALREADY_OPEN` otherwise). Baking stamps `last_baked_at` from the logical clock, resets `msl_exposure_hours` to zero, returns the lot to `AVAILABLE`, and recomputes the part's availability. Earlier intervals, being before the new `last_baked_at`, are excluded from future accrual; the quarantine-bake cycle can repeat as often as handling requires.

A lot reaches its terminal `DEPLETED` state automatically when a ship leaves it with `qty_on_hand` at zero, `qty_reserved` at zero, and `qty_shipped` equal to `qty_received`; depletion recomputes the part's availability one final time for that lot.

### 3.6. Shipping: FEFO Pick, Credit, Substitutes, and Claim Genesis

Shipping is the warehouse's act. A `WarehouseOps` operator ships against a line that is `ALLOCATED` — any other line state draws `ERR_LINE_NOT_ALLOCATED` — on an order that is not `ON_HOLD` (`ERR_ORDER_ON_HOLD` while held). The shipped `qty` must be at least one and no more than the line's unshipped allocated remainder; because every successful ship decrements `allocated_qty` by the shipped amount (below), that remainder is simply the line's current `allocated_qty`, and overshooting it is `ERR_QUANTITY_EXCEEDS_AVAILABLE`.

Lots are picked FEFO: among the shipped part's lots with `qty_reserved` above zero, ordered by date code ascending and then creation time ascending, units move from `qty_reserved` to `qty_shipped`. Every picked lot must pass the date-code freshness check of §2.6; a stale lot anywhere in the pick rejects the whole ship with `ERR_DATE_CODE_TOO_OLD`. When the shipment uses an approved substitute — the request carries a `substitute_part_id` — there must exist an alternate-part approval (§3.8) for this customer, this line's part as primary, and the substitute as alternate, in `APPROVED`; otherwise `ERR_ALTERNATE_NOT_APPROVED`. Substitute shipments draw from the substitute part's lots, and because substitutes carry no reservation, their pick moves units directly from `qty_on_hand` to `qty_shipped`, again FEFO among lots with stock; the pick draws what is available, so when the substitute's lots collectively hold fewer units than the requested `qty`, the ship still commits the full requested quantity against the line — only the line's allocated remainder bounds `qty`.

The fiscal gate runs at ship time: the customer's `open_balance_cents` plus the shipment's value — `qty` times the line's `unit_price_cents` — must not exceed `credit_limit_cents`. Equality is allowed; exceeding it rejects the ship with `ERR_CREDIT_LIMIT_EXCEEDED` and simultaneously moves the order from `ACKNOWLEDGED` or `PARTIALLY_SHIPPED` to `ON_HOLD`. An order on hold can be released back to `ACKNOWLEDGED` by a `SalesRep` or `DistributorAdmin`; release from any state other than `ON_HOLD` is `ERR_ORDER_NOT_ACKNOWLEDGED`, and a successful release increments the order's `version`.

A successful ship moves the line's `shipped_qty` up by `qty`, its `allocated_qty` down by `qty`, and stamps `last_shipped_at` from the logical clock; a line whose shipped quantity reaches its booked `quantity` moves to `SHIPPED`. The customer's `open_balance_cents` rises by the shipment's value. The first successful ship on an order moves it from `ACKNOWLEDGED` to `PARTIALLY_SHIPPED`, and when every line is `SHIPPED` or `CANCELLED` with at least one line shipped, the order completes to `COMPLETED`. Both order monetary figures are recomputed with each ship, and the order's `version` and `updated_at` bump accordingly.

Every shipment also tests for ship-and-debit coverage. The system selects the covering registration for the shipped part — the substitute part when the request carried `substitute_part_id`, otherwise the line's part: the registration's `customer_id` must equal the order's customer, its `part_id` must equal the shipped part, its status must be `APPROVED`, the logical-clock date must fall within its closed validity window, and its `registered_qty_remaining` must exceed zero; among qualifying candidates the one with the earliest `valid_from` wins, ties broken by creation time. The covered quantity is the lesser of the shipped `qty` and that remaining quantity. When coverage is positive, a ship-and-debit claim is created in `SUBMITTED` with `qty` set to the covered amount, `registration_id` and `order_line_id` pointing at the covering registration and the shipped line, and both cost baselines snapshotted — `standard_cost_cents` from the shipped part and `registered_cost_cents` from the registration. The registration's `registered_qty_remaining` falls by the covered amount, and a registration whose remaining quantity reaches zero transitions to `EXHAUSTED`.

### 3.7. Ship-and-Debit Claims: Provisional Amounts, Audit, Settlement

A claim's provisional amount is pinned at creation: `amount_provisional_cents` is the claim `qty` multiplied by the gap between its snapshotted `standard_cost_cents` and `registered_cost_cents` — exact integer-cents multiplication, no rounding. The claim then waits for the supplier.

A `SupplierAdmin` renders the supplier decision, optionally accompanied by a `reason`, on a claim in `SUBMITTED` (or, for rejection only, in `DISPUTED`); acting from any other state is `ERR_CLAIM_INVALID_STATE`. Three outcomes exist. Approving accepts an optional `audited_cost_cents`; when omitted it defaults to the claim's `registered_cost_cents`. The claim moves to `SUPPLIER_APPROVED` with `amount_final_cents` computed as `qty` times the gap between `standard_cost_cents` and `audited_cost_cents` — so when the audited cost differs from the registered cost, the final amount diverges from the provisional. Rejecting moves the claim to the terminal `SUPPLIER_REJECTED` and returns the claim's `qty` to the registration's `registered_qty_remaining`; if that restoration lifts an `EXHAUSTED` registration back above zero, the registration returns to `APPROVED`. Disputing moves the claim sideways to `DISPUTED` with no amounts changed, and a `SalesRep` may later resubmit it — optionally with a `note` — back to `SUBMITTED`, ready for a fresh supplier decision; resubmit is only lawful from `DISPUTED`.

Settlement posts the debit. A `SupplierAdmin` settles a claim from `SUPPLIER_APPROVED` — the only lawful source state — moving it to `SETTLED` and adding its `amount_final_cents` to the `open_debit_balance_cents` of the manufacturer line of the claim's order line's part (the primary part, even when the claim arose from a substitute shipment). A settled claim can later be reversed, optionally with a `reason`, moving it to the terminal `REVERSED`: the line's `open_debit_balance_cents` is decremented by the same `amount_final_cents`, the claim's `qty` is restored to the registration's `registered_qty_remaining`, and an `EXHAUSTED` registration whose remaining quantity is thereby lifted above zero returns to `APPROVED`. A settle followed by its compensating reverse therefore leaves the line's debit balance unchanged — the ledger's net-drift is zero by construction, since the balance at any moment equals the sum of final amounts over `SETTLED` claims on the line's parts minus the sum over `REVERSED` claims.

### 3.8. Cross-Reference and Alternate Part Approval

A `SalesRep` or `CustomerBuyer` may propose that a customer accept a substitute part, creating an alternate-part approval from the `customer_id`, the originally ordered `primary_part_id`, and the proposed `alternate_part_id`; the alternate must differ from the primary — a same-part proposal is `ERR_INVALID_REQUEST`. The approval is born `PROPOSED`. The decision belongs to the customer side alone: a `CustomerBuyer` acting for that customer approves or rejects from `PROPOSED`, and may later revoke an `APPROVED` approval to `REVOKED`. Acting from the wrong state — anything but `PROPOSED` for approve or reject, anything but `APPROVED` for revoke — is `ERR_ALTERNATE_APPROVAL_INVALID_STATE`, and a decision may carry an optional `reason`. Only an approval currently `APPROVED` authorizes a substitute ship under §3.6.

### 3.9. Excess Returns and Shortage Buy-Backs

The buy-back program lets a customer return excess stock or sell shortage stock back to the distributor. A `SalesRep` or the owning `CustomerBuyer` creates a request naming the `customer_id`, the original purchase `order_line_id`, a `kind` of `EXCESS_RETURN` or `SHORTAGE_BUYBACK`, and the offered `qty`, which must be positive and no more than the line's `shipped_qty` minus quantities already covered by other `REQUESTED`, `APPROVED`, or `RECEIVED` buy-backs on that line — each covering request contributes its full requested `qty` (not its `received_qty`) — and overshooting is `ERR_BUYBACK_QTY_EXCEEDED`. The server does not verify that the named order line belongs to the named customer.

The price basis differs by kind. For an excess return, `price_basis_cents` is the lesser of the order line's snapshotted `unit_price_cents` and the part's current `book_price_cents`; for a shortage buy-back it is simply the part's current `book_price_cents`. The restocking fee is tiered by whole days elapsed between the line's `last_shipped_at` and the evaluation instant, and the selected fraction is recorded as `fee_pct`: within ninety days the fee fraction is 0.10; from ninety-one through one hundred eighty days it is 0.25, and it remains 0.25 beyond one hundred eighty days (reachable only at receipt time, since creation enforces the one-hundred-eighty-day window); shortage buy-backs always carry a zero fee. The provisional credit, computed at request time, is `provisional_credit_cents` — the offered `qty` multiplied by the price basis and by one minus the request-date `fee_pct`, the full product rounded half-up to integer cents.

Two further gates guard creation. An excess return is only lawful within one hundred eighty days of the line's `last_shipped_at`, inclusive — the window is measured as an exact elapsed duration (one hundred eighty 24-hour days) from the `last_shipped_at` instant rather than in whole days, so the request is allowed while the logical clock is at or before `last_shipped_at` plus one hundred eighty days; later, it is `ERR_BUYBACK_WINDOW_CLOSED`. And excess returns are capped against the customer's trailing business: the cap is the floor of fifteen percent of `trailing_12mo_purchases_cents`, and the customer's usage toward the cap is the sum over their `EXCESS_RETURN` buy-backs created within the trailing three hundred sixty-five days — again an exact elapsed duration, inclusive of the boundary instant — and still in `REQUESTED`, `APPROVED`, or `RECEIVED`, counting each request's final credit when received, else its provisional credit. The new request is allowed only while used-plus-new-provisional stays at or under the cap; equality is allowed, and a breach is `ERR_BUYBACK_CAP_EXCEEDED`. A shortage buy-back instead requires that shortage conditions actually be in effect for the part: a `PUBLISHED` allocation run must exist for it whose `total_demand_qty` exceeds its `total_supply_qty`, otherwise `ERR_SHORTAGE_NOT_IN_EFFECT`.

A `DistributorAdmin` renders the distributor decision — approve or reject, with an optional `reason` — on a request still `REQUESTED`; acting from any other state is `ERR_BUYBACK_INVALID_STATE`. Approval moves the request to `APPROVED`; rejection to the terminal `REJECTED`.

Physical receipt is the warehouse's final act: a `WarehouseOps` operator receives against an `APPROVED` request, reporting the `received_qty` — a non-positive `received_qty` is `ERR_INVALID_REQUEST` per §2.11, and one exceeding the requested `qty` is `ERR_BUYBACK_QTY_EXCEEDED` — and the returned stock's `lot_date_code`, which must be a valid `YYYYMM` date code (`ERR_INVALID_REQUEST` otherwise). Receipt re-prices the credit at the receipt date: the fee tier is re-selected from the whole days between `last_shipped_at` and the receive instant, so a receipt landing in a later tier yields a smaller credit than the provisional; `final_credit_cents` is the received quantity times the price basis times one minus that receipt-date fee fraction, rounded half-up to integer cents. The order line's `returned_qty` rises by the received amount, and the returned units re-enter the building as a brand-new inventory lot: `OPEN_MARKET` sourcing, `authenticity` `PENDING_INSPECTION`, status `IN_INSPECTION`, `qty_received` equal to the received quantity, `date_code` taken from the receipt's `lot_date_code`. Because returns re-enter as open-market stock, they must clear the same authenticity inspection of §2.5 before they can sell again; the new lot is discoverable through the lot listing filtered by `part_id`. The request itself moves to the terminal `RECEIVED`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a manufacturer line, a part, a customer, a design registration, an order, an alternate approval, an inventory lot, an allocation run, a buy-back request) or add new distinct resources to a collection (a moisture-exposure interval on a lot) return a `201 Created` status code. Operations that modify an existing resource — acknowledge, release-hold, cancel, reschedule, ship, inspect, seal, bake, publish, supplier or distributor decisions, resubmit, settle, reverse, receive, and the logical-clock advance — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; runs registration expiry and MSL quarantine sweeps | DistributorAdmin |
| POST | `/manufacturer-lines` | Create a franchise or open-market manufacturer line | DistributorAdmin |
| GET | `/manufacturer-lines` | List manufacturer lines | Any |
| GET | `/manufacturer-lines/{lineId}` | Get one manufacturer line (includes `open_debit_balance_cents`) | Any |
| POST | `/parts` | Create a catalog part on a line | DistributorAdmin |
| GET | `/parts` | List parts, filterable by `manufacturer_line_id` | Any |
| GET | `/parts/{partId}` | Get one part (computed availability figures and `version`) | Any |
| POST | `/customers` | Create a customer account | DistributorAdmin |
| GET | `/customers` | List customers | Any |
| GET | `/customers/{customerId}` | Get one customer | Any |
| POST | `/design-registrations` | Submit a design registration (window-overlap enforced) | SalesRep, CustomerBuyer |
| GET | `/design-registrations` | List design registrations, filterable by `customer_id`, `part_id`, `status` | Any |
| GET | `/design-registrations/{registrationId}` | Get one design registration | Any |
| POST | `/design-registrations/{registrationId}/decision` | Supplier approve/reject decision on a `SUBMITTED` registration | SupplierAdmin |
| POST | `/orders` | Create an order with inline scheduled lines; starts `SUBMITTED` | SalesRep, CustomerBuyer |
| GET | `/orders` | List orders, filterable by `customer_id`, `status` | Any |
| GET | `/orders/{orderId}` | Get one order (includes `version` for OCC) | Any |
| POST | `/orders/{orderId}/acknowledge` | Acknowledge a `SUBMITTED` order; snapshots prices and cancellation terms | SalesRep |
| POST | `/orders/{orderId}/release-hold` | Release an `ON_HOLD` order back to `ACKNOWLEDGED` | SalesRep, DistributorAdmin |
| POST | `/orders/{orderId}/cancel` | Cancel an `ACKNOWLEDGED` order under the cancellation terms | SalesRep, CustomerBuyer |
| POST | `/orders/{orderId}/lines/{lineId}/reschedule` | Reschedule a line's `ship_date`; OCC-guarded on the order version | SalesRep, CustomerBuyer |
| POST | `/orders/{orderId}/lines/{lineId}/cancel` | Cancel one `OPEN`/`ALLOCATED` line under the cancellation terms | SalesRep, CustomerBuyer |
| POST | `/orders/{orderId}/lines/{lineId}/ship` | Ship units of an `ALLOCATED` line (FEFO pick; may auto-create a claim) | WarehouseOps |
| GET | `/order-lines` | List order lines, filterable by `order_id`, `part_id`, `status` | Any |
| GET | `/order-lines/{lineId}` | Get one order line | Any |
| POST | `/alternate-approvals` | Propose a cross-reference alternate part for a customer | SalesRep, CustomerBuyer |
| GET | `/alternate-approvals` | List alternate-part approvals, filterable by `customer_id`, `primary_part_id`, `alternate_part_id`, `status` | Any |
| GET | `/alternate-approvals/{approvalId}` | Get one alternate-part approval | Any |
| POST | `/alternate-approvals/{approvalId}/decision` | Customer decision: approve or reject from `PROPOSED`, revoke from `APPROVED` | CustomerBuyer |
| POST | `/lots` | Receive an inventory lot; open-market lots start `IN_INSPECTION` | WarehouseOps |
| GET | `/lots` | List lots, filterable by `part_id`, `status`, `authenticity` | Any |
| GET | `/lots/{lotId}` | Get one lot | Any |
| POST | `/lots/{lotId}/inspect` | Authenticate or reject an open-market lot (segregation of duties) | QualityInspector |
| POST | `/lots/{lotId}/exposures` | Open the dry pack of an `AVAILABLE` lot, starting an exposure interval | WarehouseOps |
| GET | `/lots/{id}/exposures` | List the exposure intervals of a lot | Any |
| POST | `/lots/{lotId}/exposures/{exposureId}/seal` | Seal an open exposure interval | WarehouseOps |
| POST | `/lots/{lotId}/bake` | Bake a `QUARANTINED` lot with no open exposure; returns it to `AVAILABLE` | WarehouseOps |
| POST | `/allocation-runs` | Create a `PROVISIONAL` fair-share allocation run; OCC-guarded on the part version | DistributorAdmin |
| GET | `/allocation-runs` | List allocation runs, filterable by `part_id`, `status` | Any |
| GET | `/allocation-runs/{runId}` | Get one allocation run (includes the computed `lines` array) | Any |
| POST | `/allocation-runs/{runId}/publish` | Publish a `PROVISIONAL` run: applies line allocations and FEFO reservations | DistributorAdmin |
| GET | `/claims` | List ship-and-debit claims, filterable by `registration_id`, `order_line_id`, `status` | Any |
| GET | `/claims/{claimId}` | Get one claim | Any |
| POST | `/claims/{claimId}/supplier-decision` | Supplier decision on a `SUBMITTED`/`DISPUTED` claim: approve, reject, or dispute | SupplierAdmin |
| POST | `/claims/{claimId}/resubmit` | Resubmit a `DISPUTED` claim back to `SUBMITTED` | SalesRep |
| POST | `/claims/{claimId}/settle` | Settle a `SUPPLIER_APPROVED` claim; posts the debit to the manufacturer line | SupplierAdmin |
| POST | `/claims/{claimId}/reverse` | Reverse a `SETTLED` claim; compensates the debit and restores registration quantity | SupplierAdmin |
| POST | `/buy-backs` | Request an excess return or shortage buy-back; computes the provisional credit | SalesRep, CustomerBuyer |
| GET | `/buy-backs` | List buy-back requests, filterable by `customer_id`, `order_line_id`, `status` | Any |
| GET | `/buy-backs/{buyBackId}` | Get one buy-back request | Any |
| POST | `/buy-backs/{buyBackId}/decision` | Distributor decision on a `REQUESTED` buy-back | DistributorAdmin |
| POST | `/buy-backs/{buyBackId}/receive` | Receive returned units; computes the final credit and creates an inspection lot | WarehouseOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MANUFACTURER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_EXPOSURE_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_BUYBACK_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_ALTERNATE_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_LINE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_PART_NUMBER` | 409 Conflict |
| `ERR_CHANNEL_MISMATCH` | 409 Conflict |
| `ERR_ORDER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ORDER_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_ORDER_ON_HOLD` | 409 Conflict |
| `ERR_ORDER_HAS_SHIPPED_LINES` | 409 Conflict |
| `ERR_LINE_NOT_ALLOCATED` | 409 Conflict |
| `ERR_LINE_NOT_OPEN_OR_ALLOCATED` | 409 Conflict |
| `ERR_LINE_NCNR` | 409 Conflict |
| `ERR_CANCEL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RESCHEDULE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SHIP_DATE_IN_PAST` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_INSPECTION_NOT_PENDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EXPOSURE_ALREADY_OPEN` | 409 Conflict |
| `ERR_EXPOSURE_NOT_OPEN` | 409 Conflict |
| `ERR_DATE_CODE_TOO_OLD` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_REGISTRATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REGISTRATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_BUYBACK_INVALID_STATE` | 409 Conflict |
| `ERR_BUYBACK_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BUYBACK_QTY_EXCEEDED` | 409 Conflict |
| `ERR_BUYBACK_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SHORTAGE_NOT_IN_EFFECT` | 409 Conflict |
| `ERR_ALTERNATE_NOT_APPROVED` | 409 Conflict |
| `ERR_ALTERNATE_APPROVAL_INVALID_STATE` | 409 Conflict |
| `ERR_NO_ALLOCATABLE_SUPPLY` | 409 Conflict |
| `ERR_NO_OPEN_DEMAND` | 409 Conflict |
| `ERR_QUANTITY_EXCEEDS_AVAILABLE` | 409 Conflict |
| `ERR_ALLOCATION_RUN_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_STALE_PART_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_CREDIT_HOLD` | 409 Conflict |
