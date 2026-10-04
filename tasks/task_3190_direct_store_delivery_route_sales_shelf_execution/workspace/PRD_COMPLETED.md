# DSD Route Sales API — Product Requirements Document

## 1. Introduction

This document specifies the Direct Store Delivery (DSD) Route Sales & Shelf Execution API, the system of record for a snack-food distribution operation run in the Frito-Lay style: route sales representatives drive a truck of perishable inventory store to store, take orders on a handheld, stock shelves and build displays themselves (rather than relying on store staff), pull stale product for credit, and settle the truck at day end. The API is mounted under the `/dsd` path prefix and governs the complete daily loop — territory and store assignment, route-day planning and truck loading, in-store order capture and delivery, shelf and promotional display execution with store-side verification, stale-product pull-and-credit adjudication under segregation of duties, and the dual-algorithm settlement ledger that reconciles sales, credits, and cash against what physically left the truck.

Two qualities make this domain harder than a routine order-management API. First, money is accounted two different ways at settlement: a chronological event-replay of delivered order lines, and a forward-looking inventory delta over truck lots. The two variants deliberately diverge whenever any line discount is applied, and the reconciliation delta is itself a first-class reported figure rather than an error to be suppressed. Second, freshness is a hard business guarantee, not a suggestion: lots within five days of expiration are undeliverable but exactly those lots are the ones eligible for stale credit, and the boundary case — a lot with precisely five days of shelf life remaining on the service date — sits on the stale side of the line. Segregation of duties runs throughout: the representative who executes shelf and credit work on the truck is never the person who approves it, and store managers verify work only for their own store.

All timestamps in this system are driven by a logical clock, never by wall-clock time. The logical clock starts at exactly 2026-09-01T00:00:00Z when the server boots and advances only when a `PlatformAdmin` operator explicitly moves it forward; every delivery-window check, promo-window expiry, `submitted_at` / `delivered_at` / `posted_at` timestamp, and days-to-expiry computation reads this clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled exactly as follows:

- `PlatformAdmin` — head-office catalog operator: representatives, stores, products, and the logical clock. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `RouteSupervisor` — district supervisor: route planning, assignments, credit adjudication, settlement posting, promo agreements, and service-level checkpoints. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `RouteSalesRep` — the route sales representative who drives the truck. When `X-User-Role` is `RouteSalesRep`, `X-User-ID` is the `id` of the acting `RouteSalesRepresentative`; ownership checks on any resource that references a `RouteSalesRepresentative` — most importantly the `rsr_id` carried on a `Route` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_REP_NOT_ASSIGNED` (HTTP 403).
- `StoreManager` — store-side verifier for shelf and display work. When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Store`; ownership checks compare the resource's `store_id` (or the owning agreement's `store_id`) to `X-User-ID`, and a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403).

A separate segregation-of-duties rule governs stale-credit adjudication: the supervisor who approves or rejects a stale credit must not be the user who created it, or the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- Requests that match no defined route are rejected with `ERR_NOT_FOUND` (HTTP 404); a defined path invoked with the wrong method yields `ERR_METHOD_NOT_ALLOWED` (HTTP 405); an unexpected server failure yields `ERR_INTERNAL` (HTTP 500). These three identifiers are transport-level fallbacks and do not appear in the business error catalogue of §5.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` is the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order, breaking ties (and equal timestamps generally) by `id` ascending. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_VALIDATION`. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Lot Conservation Invariant

Every resource in this API carries a server-minted `id` formatted as a UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. With one exception, every resource also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on any mutation, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that resource. The exception is the order line: an `OrderLine` is an immutable sub-record of its order — it carries only `id` and `created_at`; both `updated_at` and `version` are absent on order lines. (An unknown order-line id on the order-line endpoints is reported as `ERR_ORDER_NOT_FOUND`, the sub-record sharing its parent's not-found error.) Whenever a truck lot is mutated (cases delivered, stales approved, returns posted), the parent route day's `loaded_cases`, `delivered_cases`, and `stale_pulled_cases` totals are recomputed from the lots, and the route day's own `updated_at` and `version` advance accordingly.

A strict conservation invariant governs every truck lot at all times: a lot's `remaining_cases` is always its `loaded_cases` minus its `delivered_cases` minus its `stale_pulled_cases` minus its `returned_cases`. Cases may move from the truck to a store shelf (delivery), from the truck to the stale-credit bin (approval of a credit), or back to the depot (returns at settle or cancel), but they are never created or destroyed inside a route day.

### 2.5. Validation Order and Nested Identifier Resolution

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the first failure wins. The order is: (1) presence and recognizability of the auth headers; (2) role permission and ownership scope — rep owns the route day through the route's `rsr_id`, store managers are scoped to their own store; (3) existence of path identifiers, validated left to right, followed by foreign-key identifiers in the request body in the endpoint's declared input order, each miss producing its resource-specific `ERR_..._NOT_FOUND` (HTTP 404); (4) optimistic-concurrency version matching on the endpoints that take a version field; (5) state preconditions — the target resource in a valid from-state, the route `ACTIVE`, the store `ACTIVE`, the route day `IN_PROGRESS` or `LOADED` as the transition requires, the promo agreement `ACTIVE`; (6) segregation of duties on credit adjudication; (7) the freshness guarantee on delivery; (8) temporal window checks — the delivery window, promo-window overlap, assignment weekday conflicts, scheduled-stop coverage, agreement activation windows; (9) referential allocation checks — the product is on the truck that day, deliver lines reference products actually on the order; (10) capacity and stock sufficiency; and finally (11) the per-store stale-credit cap. Because path identifiers are validated left to right, a request naming a non-existent parent and a non-existent child reports the parent's `ERR_..._NOT_FOUND` first.

### 2.6. Monetary Precision and Rounding

All monetary values are integer cents. The single rounding rule used throughout the system is round half up. Order line pricing rounds each line's total to whole cents individually and only then sums the rounded line totals into the order's `gross_total_cents` — rounding the unrounded sum is not equivalent and is not permitted. Rates used by measurement calculations (`fill_rate`, `oos_rate`, `stale_ratio`) are carried to exactly 4 decimal places, round half up.

### 2.7. Optimistic Concurrency Control

Two write endpoints are version-guarded. Revising a draft order requires the request to carry `expected_store_order_version`, holding the client's last observed `version` of the order; if the field is absent the guard is skipped, and if it is present and differs from the order's current `version` on the server — because another accepted revision already replaced the line set — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a line set it has not observed. Submitting a promo execution requires `expected_promo_agreement_version`, holding the client's last observed `version` of the agreement, with the same absent-means-skipped rule; if the agreement's `version` has advanced since (for example because a prior execution submission already bumped it), the submission is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not accept a version field at all.

### 2.8. The Logical Clock and Date Windows

The server maintains a logical clock whose value at startup is exactly 2026-09-01T00:00:00Z and which never reads wall-clock time. A `PlatformAdmin` may advance it by supplying a target `current_utc` instant (an ISO 8601 datetime, accepted with a `Z` suffix or an explicit offset and normalized to UTC; an unparseable value is `ERR_VALIDATION`), and the clock accepts the new value literally — it may be set forward or backward. Advancing the clock has a standing side effect: every promo agreement still in `SCHEDULED` or `ACTIVE` whose `window_end` is on or before the new clock date transitions automatically to `EXPIRED` (each such expiry refreshes the agreement's `updated_at` and increments its `version`). The endpoint returns `200 OK` with `{"current_utc": "<clock value>"}`. All window comparisons in the system — store delivery windows expressed in minutes-of-day UTC, promo windows expressed as ISO dates — are half-open: the start is inclusive and the end is exclusive, so a submission at exactly the window's end minute (or a clock date exactly equal to `window_end`) falls outside the window.

## 3. Business Logic & Workflows

### 3.1. Territory Setup: Representatives, Stores, and the Catalog

Head office onboards the cast before any route runs. A `PlatformAdmin` registers each route sales representative with a `full_name` and a `home_depot` distribution-depot code (both non-empty strings); the rep's `status` defaults to `ACTIVE` on creation and may also be supplied explicitly as `INACTIVE`. An `INACTIVE` representative cannot be the basis for reactivating a suspended route — reactivation requires the rep referenced by the route to be `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise.

Store accounts carry the commercial terms of the retailer relationship. Creating a store requires a `store_code` unique across all stores, a display `name`, a `format` of `CONVENIENCE`, `GROCERY`, `SUPERCENTER`, or `DOLLAR`, and a `credit_policy` of `FULL_RETAIL` or `SALVAGE_RATE` that governs how stale-product credits are priced for this retailer. The store's delivery window is expressed as `delivery_window_start_minute` (an integer from 0 through 1439 inclusive, and strictly less than the end) and `delivery_window_end_minute` (an integer from 1 through 1440 inclusive, and strictly greater than the start); any out-of-range minute or a malformed window — an end minute at or before the start minute — is rejected with `ERR_VALIDATION`. The `store_credit_cap_cents` (a required integer, zero or more) bounds the total stale-credit value the store may accumulate per route day. A duplicate `store_code` is rejected with `ERR_VALIDATION`. New stores begin with `status` set to `ACTIVE` and a `promo_rebate_balance_cents` of zero; the balance accumulates rebates as verified promotional displays post.

The product catalog is similarly flat: each product has a unique `sku` (a duplicate `sku` is rejected with `ERR_VALIDATION`), a display `name`, a strictly positive `case_price_cents` list price per case, a strictly positive informational `shelf_life_days`, and a `promo_eligible` flag defaulting to true. A route is created by a `RouteSupervisor` with a unique `territory_code` (a duplicate is rejected with `ERR_VALIDATION`), the `rsr_id` of the single representative assigned to it (`ERR_REP_NOT_FOUND` when the rep does not exist), a strictly positive `base_capacity_cases` standard daily allocation, and a strictly positive `truck_cap_cases` physical ceiling; the two capacities are independent inputs and no ordering between them is enforced. New routes begin `ACTIVE` with `performance_flag` of `CLEAR`.

Both stores and routes are cyclically suspendable. A `RouteSupervisor` may suspend a route (`ACTIVE` → `SUSPENDED`), after which planning route days, creating assignments, or loading the truck on that route is rejected with `ERR_ROUTE_NOT_ACTIVE`; reactivation (`SUSPENDED` → `ACTIVE`) succeeds only while the assigned representative is `ACTIVE`. Suspending a store (`ACTIVE` → `SUSPENDED`) blocks order creation and submission, stale-credit creation, shelf-execution creation, and promo-agreement creation against that store with `ERR_STORE_NOT_ACTIVE`, until the store is reactivated. Both transitions are strict: suspend is rejected with `ERR_INVALID_STATE` from any state other than `ACTIVE`, and reactivate is rejected with `ERR_INVALID_STATE` from any state other than `SUSPENDED`. Each suspension and reactivation increments the resource's `version` by 1.

### 3.2. Assignment Scheduling and Route-Day Planning

A `RouteSupervisor` wires the territory together by assigning stores to routes. Each assignment names a `route_id` and a `store_id` (both must exist, validated in that order: `ERR_ROUTE_NOT_FOUND`, then `ERR_STORE_NOT_FOUND`), requires the route to be `ACTIVE` (`ERR_ROUTE_NOT_ACTIVE`), a non-empty `service_weekdays` list drawn from MON through SUN (duplicate entries are deduplicated), and a `stop_sequence` of at least 1 fixing the store's position in the route's stop order. The system refuses to create an assignment whose weekday set intersects that of another `ACTIVE` assignment for the same store — regardless of which route the other assignment belongs to — rejecting with `ERR_ASSIGNMENT_DAY_CONFLICT`. Assignments retire (`ACTIVE` → `RETIRED`, with any other from-state rejected as `ERR_INVALID_STATE`) rather than delete; a `RETIRED` assignment is excluded from weekday-coverage and day-conflict checks from retirement onward.

Planning a route day is a supervisor action naming the `route_id` and an ISO-date `service_date`, with an optional `is_event_day` flag (defaulting to false) for seasonal or event surges and an optional `event_surge_cases` (defaulting to 0, and never negative — a negative value is `ERR_VALIDATION`). The route must be `ACTIVE` (`ERR_ROUTE_NOT_ACTIVE`). Two rules shape the day at creation. First, the day's `capacity_cases` is computed as the route's `base_capacity_cases` plus the surge — where the surge is `event_surge_cases` on an event day and zero on a standard day regardless of any payload value (a positive `event_surge_cases` on a non-event day is `ERR_VALIDATION`) — capped at the route's `truck_cap_cases`; equality with the cap is permitted. The payload's `is_event_day` and `event_surge_cases` are persisted on the route day as supplied, alongside the computed `capacity_cases`. Second, the service date's weekday must be covered by at least one `ACTIVE` assignment of the route, failing with `ERR_NO_SCHEDULED_STOP` otherwise. A new route day is born `PLANNED` with `loaded_cases`, `delivered_cases`, and `stale_pulled_cases` all at zero.

### 3.3. Loading the Truck and Starting the Day

On the morning of the run, the assigned representative loads the truck. Loading is permitted only while the route day is `PLANNED` (any other state is `ERR_INVALID_STATE`), the route itself is `ACTIVE`, and the acting rep's identity matches the route's `rsr_id` (`ERR_REP_NOT_ASSIGNED` otherwise). The payload carries a non-empty `lots` list, one entry per production lot; each entry names a `product_id` (each must exist, else `ERR_PRODUCT_NOT_FOUND`), a `lot_code`, an ISO-date `expiration_date` (any valid date is accepted — there is no minimum remaining-shelf-life check at load time), and a strictly positive `loaded_cases`. The summed `loaded_cases` across the payload may not exceed the day's `capacity_cases` — `ERR_CAPACITY_EXCEEDED` when it does. Loading creates one truck-inventory lot per payload entry in `SEALED` status, recomputes the route day's `loaded_cases`, transitions the day `PLANNED` → `LOADED`, and increments the route day's `version` (the day's `version` and `updated_at` advance once for the load as a whole, not once per lot). The endpoint returns `200 OK` carrying the updated route day. Lot identifiers are discoverable afterward through the lot list filtered by `route_day_id`, and individual lots are addressable by their own `id`.

Starting the route day — again the assigned rep's action, requiring the day to be `LOADED` (`ERR_ROUTE_DAY_NOT_LOADED` otherwise) — flips every lot of the day from `SEALED` to `OPEN` and moves the day to `IN_PROGRESS`, incrementing the day's `version` (each opened lot also increments its own `version` and refreshes its `updated_at`). A `RouteSupervisor` may instead cancel a route day from `PLANNED` (no lot effects, since nothing is loaded) or from `LOADED` — any other from-state is `ERR_INVALID_STATE`; canceling a `LOADED` day sets every lot's `returned_cases` to its `loaded_cases` minus delivered minus stale-pulled — which equals the full loaded quantity because no movement is possible before start — closes every lot to `CLOSED`, recomputes the day's totals so the conservation invariant is restored with all cases returned, and moves the day to `CANCELLED`. The `load`, `start`, and `cancel` actions all return `200 OK` carrying the updated route day.

### 3.4. Handheld Order Entry, Submission, and the Delivery Window

While the route day is `IN_PROGRESS` and the store is `ACTIVE`, the rep captures an order on the handheld: a payload containing the `route_day_id`, the `store_id` (existence validated in that declared order: `ERR_ROUTE_DAY_NOT_FOUND`, then `ERR_STORE_NOT_FOUND`), an `order_type` (defaulting to `STANDARD`; `EVENT_SURGE` is permitted only on an event day, and supplying it on a standard day is `ERR_VALIDATION`), and a non-empty `lines` array (an empty array is `ERR_VALIDATION`). Each line names a `product_id` (each must exist, else `ERR_PRODUCT_NOT_FOUND`), a strictly positive `qty_ordered_cases`, and an optional `line_discount_pct` — a fractional discount of at least 0 and strictly less than 1, defaulting to 0. Every line product must be allocated on the truck that day, meaning an `OPEN` lot exists for it (`ERR_PRODUCT_NOT_ALLOCATED` otherwise), and an `ACTIVE` assignment must cover the route, the store, and the service date's weekday. A new order is born `DRAFT` with `submitted_at` and `delivered_at` unset.

Pricing is pinned at write time. Each line's `line_total_cents` is the line's `qty_ordered_cases` multiplied by the product's `case_price_cents`, multiplied by one minus the `line_discount_pct`, rounded half up to whole cents; the order's `gross_total_cents` is the sum of those per-line rounded totals. Each line also records its parent order through `order_id`, carries its 1-based `line_seq` position within the order payload, and each line's `qty_delivered_cases` starts at 0. Two payload lines may reference the same product; each becomes its own order line with its own `line_seq`, and at delivery time all such lines for the product receive the same delivered quantity — the per-product total requested in the delivery payload.

A draft order's lines may be revised wholesale — the replacement non-empty `lines` payload swaps the entire line set, recomputes per-line totals and the gross total, and increments the order's `version` — subject to the `expected_store_order_version` concurrency guard described in §2.7, and every replacement line's product must still be allocated on the truck that day (`ERR_PRODUCT_NOT_ALLOCATED` otherwise); a revision is only possible from `DRAFT` (any other state is `ERR_INVALID_STATE`).

Submission converts a `DRAFT` order to `SUBMITTED`. Four gates apply, in validation priority order: the order's route day must be `IN_PROGRESS` (`ERR_ROUTE_DAY_NOT_IN_PROGRESS`), the store must be `ACTIVE` (`ERR_STORE_NOT_ACTIVE`), the logical clock's minute-of-day must fall inside the store's half-open delivery window — at or after `delivery_window_start_minute` and strictly before `delivery_window_end_minute`, with a delivery at exactly the end minute rejected as `ERR_DELIVERY_WINDOW_MISSED` — and the order must carry at least one line (`ERR_VALIDATION` on an empty set). A successful submission stamps `submitted_at` with the logical clock and increments the order's `version`. The revision loop is explicit: the rep may pull a `SUBMITTED` order back to `DRAFT` via the unsubmit action (version increments again; `submitted_at` is retained) to edit on the handheld, and may cancel an order from either `DRAFT` or `SUBMITTED`, moving it to `CANCELLED`.

### 3.5. Delivery, FEFO Consumption, and the Freshness Guarantee

Delivery is the moment inventory physically moves. The rep delivers a `SUBMITTED` order with a payload of `lines` carrying actual `qty_delivered_cases` per line; lines of the order absent from the payload default to zero delivered. Each payload line names a `product_id` and a `qty_delivered_cases` of zero or more (negative is `ERR_VALIDATION`), and multiple payload lines naming the same product aggregate into a single per-product requested quantity. Every payload line must reference a product present on the order (`ERR_DELIVERY_LINE_NOT_ON_ORDER`), the aggregated per-product quantity may not exceed that product's total `qty_ordered_cases` (`ERR_VALIDATION`), and the route day must still be `IN_PROGRESS`. Delivery succeeds even when every line delivers zero cases, provided the referential checks pass.

Consumption follows first-expired-first-out against the day's `OPEN` lots. A lot's days-to-expiry is its `expiration_date` minus the route day's `service_date`, in whole days. The freshness guarantee is absolute: a delivery may only consume lots whose days-to-expiry is strictly greater than 5 — a lot at exactly 5 days is undeliverable, and the violation is detected per requested product: when the freshness-eligible lots cannot cover the requested quantity but the day's `OPEN` lots for that product (eligible or not) hold enough remaining stock in total, fulfilling the line would require a lot at 5 days or fewer and the delivery fails with `ERR_FRESHNESS_GUARANTEE_VIOLATION`. These delivery checks are evaluated in the validation-priority order of §2.5, so when more than one of them would reject the same request the earlier-priority failure is the one reported — the freshness guarantee (level 7) before the line-on-order referential check (level 9), and stock sufficiency (level 10) last. For each line, the system consumes from the day's freshness-eligible lots of that product in ascending `expiration_date` order, breaking ties by the lot's `created_at` ascending — never by lot id — incrementing each lot's `delivered_cases` as it goes; if the freshness-eligible remaining stock across those lots is short of the requested quantity (and no freshness violation was detected, i.e. even the ineligible lots could not close the gap), the delivery fails with `ERR_INSUFFICIENT_TRUCK_STOCK`. All checks for every requested product complete before any lot is mutated, so a failed delivery leaves the truck untouched.

A successful delivery stamps `delivered_at` with the logical clock, moves the order to `DELIVERED`, increments its `version`, and triggers two recomputes: the route day's `delivered_cases` refreshes from the lots, and if a settlement already exists for the day in `OPEN` status, its `gross_delivered_cents`, `forward_expected_cents`, and `chronological_expected_cents` are recomputed as well — a settlement in `BALANCED` auto-reopens to `OPEN` on the same trigger (see §3.9).

### 3.6. Shelf Execution Under Store-Manager Verification

The rep, not store staff, works the shelf. Recording a shelf execution — permitted only while the route day is `IN_PROGRESS`, the store `ACTIVE`, and the product allocated on the day — captures the `route_day_id`, `store_id`, `product_id` (existence validated in that declared order), the `qty_placed_cases` the rep put on shelf or display (zero or more, required), a `rotated` flag recording whether stock was rotated oldest-to-front, and a `display_built` flag recording whether a display was built or rebuilt (both flags required booleans). No scheduled-stop coverage is checked for shelf work. The system stamps `created_by_user_id` with the acting rep's identity and the record begins `RECORDED` with `verified_by_user_id` unset.

Verification belongs to the store. A `StoreManager` acting on the execution confirms it with an `outcome` of `VERIFIED` or disputes it with an `outcome` of `REJECTED` accompanied by a `reject_reason` (any other outcome value is `ERR_VALIDATION`); the acting manager's identity must equal the execution's `store_id`, failing with `ERR_STORE_SCOPE_VIOLATION` otherwise. The execution must still be `RECORDED` — verifying an already-decided execution is `ERR_INVALID_STATE`. Either outcome stamps `verified_by_user_id` with the acting manager; a rejection also records the supplied reason. Both `VERIFIED` and `REJECTED` are terminal.

### 3.7. Stale Pulls, Credit Pricing, and Adjudication

Stale product is pulled from the shelf and credited back to the store. Either the rep or a supervisor may originate a stale credit, naming the `route_day_id`, `store_id`, `product_id`, and a strictly positive `qty_cases`; the route day must be `IN_PROGRESS`, the store `ACTIVE`, and the product allocated on the day. The pull is stale-window eligible only when some `OPEN` lot of that product on the day has days-to-expiry of 5 or fewer — the exact complement of the freshness guarantee, so a lot at precisely 5 days is stale-eligible but undeliverable — and the absence of any such lot is `ERR_PRODUCT_NOT_STALE_ELIGIBLE`. Only `OPEN` lots with positive remaining stock count toward eligibility. Among stale-eligible lots the system selects by the same FEFO ordering (ascending `expiration_date`, ties on lot `created_at` ascending) and pins the single first lot in that order onto the credit's `lot_id` at creation; if the stale-eligible remaining stock across all such lots is short of `qty_cases`, the request fails with `ERR_INSUFFICIENT_TRUCK_STOCK`. Crucially, creation does not mutate the lot — the lot's `stale_pulled_cases` moves only when the credit is approved.

Pricing snapshots the store's policy at creation onto the credit's `pricing_variant`. Under `FULL_RETAIL`, `credit_cents` is the `qty_cases` multiplied by the product's `case_price_cents` — the full list value. Under `SALVAGE_RATE`, `credit_cents` is the same product multiplied by 0.40 and rounded half up to whole cents — forty percent of list — so the two variants diverge for identical quantities and prices. The store's per-day cap then gates creation: the sum of `credit_cents` over the store's `PENDING_APPROVAL` and `APPROVED` credits for that route day, plus the new credit's amount, may not exceed the store's `store_credit_cap_cents`, with equality permitted; breach is `ERR_STORE_CREDIT_CAP_EXCEEDED` (HTTP 402). A created credit records `created_by_user_id` and begins `PENDING_APPROVAL` with `decided_by_user_id` and `reject_reason` unset.

Adjudication belongs to a `RouteSupervisor`, but never the same user who created the credit — `ERR_SEGREGATION_OF_DUTIES` guards both directions, and the adjudicator must not have created the credit regardless of the role under which it was created (a credit created by a supervisor cannot be decided by that same supervisor). Approval requires the credit to be `PENDING_APPROVAL` (any other state is `ERR_INVALID_STATE`), stamps `decided_by_user_id`, moves the credit to `APPROVED` (terminal), and only now mutates inventory: the pinned lot's `stale_pulled_cases` increases by `qty_cases`, the route day's stale totals recompute from the lots, and if a settlement exists for the day its `credits_cents` and both expected variants recompute — with a `BALANCED` settlement auto-reopening to `OPEN`. Rejection likewise requires `PENDING_APPROVAL`, requires a `reject_reason` (`ERR_VALIDATION` when omitted), stamps `decided_by_user_id`, and leaves lots and settlement untouched. Rejection is not the end: while the route day remains `IN_PROGRESS` (`ERR_ROUTE_DAY_NOT_IN_PROGRESS` otherwise), the rep may resubmit a `REJECTED` credit, returning it to `PENDING_APPROVAL` with `reject_reason` and `decided_by_user_id` cleared — the reject–resubmit loop may cycle any number of times.

### 3.8. Promotional Agreements and Compliance Verification

Retailers pay for display execution through promo agreements. A `RouteSupervisor` creates an agreement naming the `store_id`, `product_id`, a half-open execution window from `window_start` (inclusive) to `window_end` (exclusive, and strictly after the start), a `display_type` of `ENDCAP`, `AISLE`, `DUMP_BIN`, or `COUNTER`, and a `rebate_cents` of zero or more. The store must be `ACTIVE`. Agreements for the same store and product may not overlap: creation is rejected with `ERR_PROMO_WINDOW_OVERLAP` when an existing `SCHEDULED`, `ACTIVE`, or `COMPLETED` agreement's window intersects the new one — intersection meaning the existing window starts before the new window ends and the new window starts before the existing window ends — while pure adjacency (one window's end equal to the other's start) is permitted. A new agreement begins `SCHEDULED`.

Activation (`SCHEDULED` → `ACTIVE`, with any other from-state rejected as `ERR_INVALID_STATE`) is permitted only while the logical clock's date falls inside the half-open window — `ERR_AGREEMENT_NOT_ACTIVE` otherwise. A supervisor may also mark an `ACTIVE` agreement `BREACHED` for retailer non-compliance (from any other state, `ERR_INVALID_STATE`); both transitions increment the agreement's `version`. Clock advancement does the rest: any agreement still `SCHEDULED` or `ACTIVE` whose `window_end` is reached or passed by the logical clock expires automatically.

The rep executes against an `ACTIVE` agreement by submitting a promo execution carrying the `agreement_id`, the `route_day_id` of an `IN_PROGRESS` day, a `photo_url` of compliance evidence, and the `expected_promo_agreement_version` concurrency guard — a stale view of the agreement fails with `ERR_STALE_VERSION`. The execution need not fall inside the agreement's window: only the agreement's `ACTIVE` state gates submission. Only one pending execution may exist per agreement: a second submission while another is still `SUBMITTED` fails with `ERR_PENDING_EXECUTION_EXISTS`. Submission stamps `built_by_user_id` with the acting rep, begins the execution at `SUBMITTED` with `verified_by_user_id` and `reject_reason` unset, and increments the agreement's `version` by 1.

Compliance review is shared: the store manager of the agreement's store (identity matched against the agreement's `store_id`, else `ERR_STORE_SCOPE_VIOLATION`) or any `RouteSupervisor` may decide. Verification — permitted only while the execution is `SUBMITTED` (any other state is `ERR_INVALID_STATE`) and the agreement remains `ACTIVE` — moves the execution to `VERIFIED`, completes the agreement (`ACTIVE` → `COMPLETED`), and posts the agreement's `rebate_cents` onto the store's `promo_rebate_balance_cents`. Rejection requires a `reject_reason` and moves the execution to `REJECTED`, also stamping `verified_by_user_id`; the agreement's `ACTIVE` state is not required for rejection — a rejected verdict is accepted even after the agreement has expired — the agreement's own status is left unchanged, and a fresh execution may be submitted to supersede the rejected one.

### 3.9. Day-End Settlement: The Dual Ledger, Balancing, and Posting

When the truck returns, a `RouteSupervisor` opens the route day's settlement — at most one per route day, with a second attempt rejected as `ERR_SETTLEMENT_ALREADY_EXISTS` — naming the `route_day_id` of an `IN_PROGRESS` day. The settlement is born `OPEN` and immediately computes its ledger.

The ledger is deliberately dual. The chronological variant replays events: `gross_delivered_cents` is the sum of the orders' `gross_total_cents` over the day's `DELIVERED` orders — the per-order gross totals, which are themselves sums of per-line rounded `line_total_cents` (per-line priced, discounts included); `credits_cents` is the sum of `credit_cents` over the day's `APPROVED` stale credits; and `chronological_expected_cents` is the gross minus the credits. The forward-looking variant walks the inventory delta: for each of the day's lots, everything that left the truck and was neither stale-pulled nor returned — `loaded_cases` minus `stale_pulled_cases` minus `remaining_cases`, which equals `delivered_cases` exactly by the conservation invariant — is presumed sold at the product's list price, summed across lots, with the `credits_cents` then subtracted to form `forward_expected_cents`. The difference between the two variants is reported as `recon_delta_cents` — the forward variant minus the chronological variant — and captures discount drift: because the forward variant values sold cases at list while the chronological variant uses per-line discounted prices, the two diverge on identical data whenever any line carries a positive discount. Both variants, the gross, the credits, and the delta recompute on every delivery, every stale-credit approval, and every balance attempt; `cash_collected_cents` is unset until the first balance and `variance_cents` is the cash collected minus the chronological expectation, remaining unset until cash is first recorded.

Balancing is a threshold, not an error path. Balancing is possible from `OPEN` or `BALANCED` (any other state is `ERR_INVALID_STATE`). The supervisor records `cash_collected_cents` (an integer); the settlement moves `OPEN` → `BALANCED` exactly when the absolute value of `variance_cents` is at most 200 cents — an absolute variance of precisely 200 balances, while 201 does not — and when the variance exceeds the tolerance the request still returns 200 with the settlement left `OPEN`, carrying the recorded cash and recomputed variance. A `BALANCED` settlement is stale the moment the underlying ledger moves: any subsequent delivery or stale-credit approval for the day auto-reopens it to `OPEN`, retaining `cash_collected_cents` for the next balance (each such auto-reopen also refreshes the settlement's `updated_at` and increments its `version`).

Posting is the point of no return. A `BALANCED` settlement may be posted only while no order of the route day remains `SUBMITTED` (`ERR_UNRESOLVED_ORDERS` otherwise); posting stamps `posted_at` with the logical clock, moves the settlement to `POSTED` (terminal), settles the route day itself (`IN_PROGRESS` → `SETTLED`), and closes the truck: every `OPEN` lot's `returned_cases` is set to its `remaining_cases` and its status to `CLOSED`, so all unsold, un-staled cases return to depot.

Disputes ride alongside. The route's assigned rep (identity matched to `rsr_id`, else `ERR_REP_NOT_ASSIGNED`) may dispute a settlement from either `OPEN` or `BALANCED` (any other state is `ERR_INVALID_STATE`), moving it to `DISPUTED`; a supervisor resolves the dispute, returning the settlement to `OPEN` (resolving from any state other than `DISPUTED` is `ERR_INVALID_STATE`). The dispute cycle may repeat, but posting is unreachable from `DISPUTED` — the settlement must first resolve and re-balance.

### 3.10. Service-Level Measurement and Route Performance

Periodically, a `RouteSupervisor` takes a checkpoint on a route's execution quality by requesting a service-level snapshot with a half-open measurement window from `period_start` (inclusive) to `period_end` (exclusive, strictly after the start). The window matches route days of the route by their `service_date`.

The measurement aggregates only `DELIVERED` orders on those in-window route days — `DRAFT`, `SUBMITTED`, and `CANCELLED` orders are excluded. `orders_count` is the count of those delivered orders; if the window contains none, the request fails with `ERR_NO_DELIVERED_ORDERS`. The `fill_rate` is the sum of `qty_delivered_cases` divided by the sum of `qty_ordered_cases` over those orders, rounded half up to 4 decimal places; the `oos_rate` is one minus the fill rate, also at 4 decimal places. The `service_grade` tiers on the out-of-stock rate: `GOLD` when the rate is strictly below 0.02, `SILVER` when strictly below 0.05, otherwise `BRONZE` — so a rate of exactly 0.02 earns `SILVER`, not `GOLD`, and exactly 0.05 earns `BRONZE`.

The same snapshot computes the route's performance ratio. `stale_ratio` is the sum of `credit_cents` over `APPROVED` stale credits on the route's in-window route days divided by the sum of `gross_total_cents` over the in-window delivered orders, rounded half up to 4 decimal places, and zero when the gross is zero. The `performance_flag_result` is `PERFORMANCE_WATCH` when the ratio is strictly greater than 0.08 and `CLEAR` otherwise — a ratio of exactly 0.08 is `CLEAR`. Creating the snapshot also overwrites the route's `performance_flag` with this result and increments the route's `version` by 1, so the checkpoint doubles as the fleet's early-warning signal. The snapshot record itself carries `route_id`, `period_start`, `period_end`, `orders_count`, `fill_rate`, `oos_rate`, `service_grade`, `stale_ratio`, and `performance_flag_result`, and is created with the usual `201 Created` semantics.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. One status-code nuance belongs to the settlement balance action: when the recorded cash leaves the variance outside the tolerance, the response is still `200 OK` with the settlement returned in `OPEN` status — falling short of balance is a state, not an error.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dsd/_clock/set_current_utc` | Advance the logical clock; expires out-of-window promo agreements | PlatformAdmin |
| POST | `/dsd/reps` | Register a route sales representative | PlatformAdmin |
| GET | `/dsd/reps/{repId}` | Get a rep | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/stores` | Create a store account with its service agreement terms | PlatformAdmin |
| GET | `/dsd/stores/{storeId}` | Get a store | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/stores/{storeId}/suspend` | Suspend a store (blocks new orders, credits, executions) | RouteSupervisor |
| POST | `/dsd/stores/{storeId}/reactivate` | Reactivate a suspended store | RouteSupervisor |
| POST | `/dsd/products` | Create a catalog product | PlatformAdmin |
| GET | `/dsd/products/{productId}` | Get a product | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/routes` | Create a route with its assigned rep and capacity parameters | RouteSupervisor |
| GET | `/dsd/routes/{routeId}` | Get a route | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/routes` | List routes, optionally filtered by `rsr_id` | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/routes/{routeId}/suspend` | Suspend a route | RouteSupervisor |
| POST | `/dsd/routes/{routeId}/reactivate` | Reactivate a suspended route | RouteSupervisor |
| POST | `/dsd/route-assignments` | Assign a store to a route with a service-weekday schedule | RouteSupervisor |
| GET | `/dsd/route-assignments/{assignmentId}` | Get an assignment | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/route-assignments` | List assignments filtered by route and/or store | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/route-assignments/{assignmentId}/retire` | Retire an assignment | RouteSupervisor |
| POST | `/dsd/route-days` | Plan a route day for a service date | RouteSupervisor |
| GET | `/dsd/route-days/{routeDayId}` | Get a route day | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/route-days` | List route days filtered by route and/or status | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/route-days/{routeDayId}/load` | Load the truck: creates one lot per payload entry (`PLANNED` → `LOADED`) | RouteSalesRep |
| POST | `/dsd/route-days/{routeDayId}/start` | Start the route day (`LOADED` → `IN_PROGRESS`; lots open) | RouteSalesRep |
| POST | `/dsd/route-days/{routeDayId}/cancel` | Cancel a `PLANNED` or `LOADED` route day; returns all cases to depot | RouteSupervisor |
| GET | `/dsd/truck-lots/{lotId}` | Get a truck inventory lot | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/truck-lots` | List lots filtered by route day, product, and/or lot code | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/orders` | Handheld order entry: create a `DRAFT` order at a store | RouteSalesRep |
| GET | `/dsd/orders/{orderId}` | Get an order | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/orders` | List orders filtered by route day, store, and/or status | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| PUT | `/dsd/orders/{orderId}` | Revise a `DRAFT` order's lines wholesale (version-guarded) | RouteSalesRep |
| POST | `/dsd/orders/{orderId}/submit` | Submit a `DRAFT` order (delivery-window checked) | RouteSalesRep |
| POST | `/dsd/orders/{orderId}/unsubmit` | Pull a `SUBMITTED` order back to `DRAFT` for revision | RouteSalesRep |
| POST | `/dsd/orders/{orderId}/deliver` | Deliver a `SUBMITTED` order with actual quantities; FEFO lot consumption | RouteSalesRep |
| POST | `/dsd/orders/{orderId}/cancel` | Cancel a `DRAFT` or `SUBMITTED` order | RouteSalesRep |
| GET | `/dsd/order-lines/{lineId}` | Get a single order line | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/order-lines` | List order lines filtered by order and/or product | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/shelf-executions` | Record rep-executed shelf stocking, rotation, and display work | RouteSalesRep |
| GET | `/dsd/shelf-executions/{execId}` | Get a shelf execution | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/shelf-executions` | List shelf executions filtered by store, route day, and/or product | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/shelf-executions/{execId}/verify` | Store manager verifies or rejects the shelf work | StoreManager |
| POST | `/dsd/stale-credits` | Pull stale product and request credit; FEFO lot selection | RouteSalesRep, RouteSupervisor |
| GET | `/dsd/stale-credits/{creditId}` | Get a stale credit | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/stale-credits` | List stale credits filtered by store, route day, product, lot, and/or status | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/stale-credits/{creditId}/approve` | Approve a pending credit (segregation of duties enforced) | RouteSupervisor |
| POST | `/dsd/stale-credits/{creditId}/reject` | Reject a pending credit (segregation of duties enforced) | RouteSupervisor |
| POST | `/dsd/stale-credits/{creditId}/resubmit` | Resubmit a rejected credit for reconsideration | RouteSalesRep |
| POST | `/dsd/promo-agreements` | Create a promotional display agreement with a half-open window | RouteSupervisor |
| GET | `/dsd/promo-agreements/{agreementId}` | Get a promo agreement | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/promo-agreements` | List promo agreements filtered by store, product, and/or status | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/promo-agreements/{agreementId}/activate` | Activate an agreement when the clock is inside its window | RouteSupervisor |
| POST | `/dsd/promo-agreements/{agreementId}/breach` | Mark an `ACTIVE` agreement breached | RouteSupervisor |
| POST | `/dsd/promo-executions` | Submit display execution with compliance photo (version-guarded) | RouteSalesRep |
| GET | `/dsd/promo-executions/{execId}` | Get a promo execution | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/promo-executions` | List promo executions filtered by agreement and/or route day | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/promo-executions/{execId}/verify` | Verify compliant display: completes the agreement and posts the rebate | StoreManager, RouteSupervisor |
| POST | `/dsd/promo-executions/{execId}/reject` | Reject non-compliant display; agreement stays `ACTIVE` | StoreManager, RouteSupervisor |
| POST | `/dsd/route-settlements` | Open day-end settlement for an `IN_PROGRESS` route day (one per day) | RouteSupervisor |
| GET | `/dsd/route-settlements/{settlementId}` | Get a settlement | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/route-settlements` | List settlements filtered by route day | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| POST | `/dsd/route-settlements/{settlementId}/balance` | Record collected cash; balances when the absolute variance is at most 200 cents | RouteSupervisor |
| POST | `/dsd/route-settlements/{settlementId}/post` | Post a `BALANCED` settlement; settles the route day and closes its lots | RouteSupervisor |
| POST | `/dsd/route-settlements/{settlementId}/dispute` | Route rep disputes an `OPEN` or `BALANCED` settlement | RouteSalesRep |
| POST | `/dsd/route-settlements/{settlementId}/resolve` | Resolve a dispute, returning the settlement to `OPEN` | RouteSupervisor |
| POST | `/dsd/routes/{routeId}/service-level-snapshots` | Compute the service-level checkpoint over a half-open window; updates the route's performance flag | RouteSupervisor |
| GET | `/dsd/service-level-snapshots/{snapshotId}` | Get a snapshot | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |
| GET | `/dsd/service-level-snapshots` | List snapshots filtered by route | PlatformAdmin, RouteSupervisor, RouteSalesRep, StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_REP_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_STORE_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REP_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SHELF_EXECUTION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMO_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMO_EXECUTION_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_NOT_ACTIVE` | 409 Conflict |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUTE_DAY_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_ROUTE_DAY_NOT_LOADED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_SCHEDULED_STOP` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_MISSED` | 409 Conflict |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ASSIGNMENT_DAY_CONFLICT` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PENDING_EXECUTION_EXISTS` | 409 Conflict |
| `ERR_UNRESOLVED_ORDERS` | 409 Conflict |
| `ERR_NO_DELIVERED_ORDERS` | 409 Conflict |
| `ERR_FRESHNESS_GUARANTEE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_ALLOCATED` | 422 Unprocessable Entity |
| `ERR_DELIVERY_LINE_NOT_ON_ORDER` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_TRUCK_STOCK` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_STALE_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_STORE_CREDIT_CAP_EXCEEDED` | 402 Payment Required |
