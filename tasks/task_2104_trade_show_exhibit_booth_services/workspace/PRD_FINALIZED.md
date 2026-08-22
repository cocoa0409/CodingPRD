# Trade Show Exhibit Services API — Product Requirements Document

## 1. Introduction

A general contractor on a trade show floor sits at the intersection of half a dozen businesses that most software treats separately. It designs and fabricates exhibit properties, or rents them out; it receives, stores, hauls and returns freight; it dispatches union crews under jurisdictional rules that change from one convention centre to the next; it prices everything against a calendar of discount deadlines that are unforgiving to the hour; and it invoices, collects, credits and occasionally writes off — all while the show floor is being built, opened and torn down inside a seventy-two hour window. This document specifies the API that runs that business end to end.

The system's organising insight is that almost nothing here is independently priced. A catalog line's price depends on when the order was placed relative to the show's discount deadline; the order's subtotal decides its volume discount; the discounted base — not the subtotal — decides its service fee; the order total lands on an invoice; the invoice lands on the exhibitor's balance; the balance measured against the credit limit decides whether the exhibitor's booths are open for further work at all; and a frozen booth silently cancels the union crews that were already requested against it. Three quantities are conserved across this web and must survive every forward action and its compensating reversal with no drift: money owed by the exhibitor, hundredweight committed at each advance warehouse, and crew-hours committed to each show.

Because deadlines, storage clocks, labor bands and expiry rules all read time, the server does not read the wall clock. It maintains a logical clock that test operators reposition explicitly, and every temporal rule in this specification reads that clock. Six operator roles share the surface — the exhibiting company itself, the contractor's show operations desk, the advance warehouse, the union labor steward, the claims adjuster and accounts receivable — with segregation of duties enforced wherever one operator's money decision reviews another's.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level behaviour that holds for every endpoint in the API, regardless of the business process it serves.

### 2.1. User and Role-Based Access Control

Every request, without exception, must carry two headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity that operator is acting in. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same 401 and the same `ERR_UNAUTHENTICATED` identifier are returned when `X-User-Role` carries a value that is not one of the six roles the system recognises.

Those six roles are `Exhibitor`, `ShowOperations`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster` and `FinanceController`. Each endpoint declares the roles permitted to invoke it (see §4). When an authenticated operator's role is not on that endpoint's list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Passing the role check is not the same as passing the ownership check, and the two are evaluated in that order.

Two of the roles are backed by persisted entities. When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting `Exhibitor` row; ownership checks on any resource that references an exhibitor compare that resource's `exhibitor_id` — reached directly on the resource, or indirectly through the booth, order, crate, asset, design, claim or invoice named by the request — to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `WarehouseAgent`, `X-User-ID` is the `id` of the `Warehouse` the agent staffs; warehouse-scoped writes compare the `warehouse_id` the request targets to `X-User-ID` and reject a mismatch with the same `ERR_NOT_RESOURCE_OWNER`.

The remaining four roles carry opaque identities. When `X-User-Role` is `ShowOperations`, `LaborSupervisor`, `ClaimsAdjuster` or `FinanceController`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands an audit subject — as `created_by_user_id` and `reviewed_by_user_id` on a change order, as `filed_by_user_id` and `adjudicated_by_user_id` on a damage claim, and as `issued_by_user_id` and `voided_by_user_id` on an invoice — but it never compares those values to any entity's `id`.

Recorded identities exist to enforce segregation of duties. Three decisions may not be taken by the operator who originated the thing being decided: approving or rejecting a change order (the acting `X-User-ID` must differ from that change order's `created_by_user_id`), adjudicating a damage claim (must differ from `filed_by_user_id`), and voiding an invoice (must differ from `issued_by_user_id`). A violation of any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every endpoint that returns a collection accepts two query parameters. `limit` caps the number of rows returned; it defaults to 10 when absent, may not be lower than 1, and may not be higher than 100. `offset` is the number of rows to skip before the page begins; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, list results are ordered by the resource's creation timestamp, `created_at`, ascending.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object. `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window.

### 2.4. The Logical Show Clock

Nothing in this system reads the host machine's wall clock. The server maintains a single logical clock, and every deadline comparison, storage day count, labor band split, receiving-hour surcharge test and lifecycle window check reads that clock and nothing else. Before any operator repositions it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time.

Any of the six roles may reposition the clock by calling `POST /_clock/set_current_utc` with a `to_iso8601` instant in the request body; the response reports the new `current_utc`. Repositioning the clock is a pure test-driving capability: no entity is mutated, no derived field is recomputed, and no cascade fires. In particular, moving the clock past a show's discount deadline does not reprice a single existing order, because pricing tiers are frozen onto the order at the instant it was created.

### 2.5. Record Identity, Timestamps and Versioning

Every resource the API persists carries an `id`: a server-minted UUID, with no type prefix and no embedded semantics. Clients never supply it.

Seventeen of the system's eighteen resource types — venues, union jurisdictions, warehouses, shows, exhibitors, booths, exhibit assets, exhibit designs, service orders, crates, drayage shipments, labor calls, change orders, invoices, damage claims, refurbishment work orders and lead-capture licences — additionally carry the full audit triple:

- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written and never changed afterwards.
- `updated_at` — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row, including mutations the server performs on its own initiative as a cascade from some other resource's write.
- `version` — an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including server-initiated cascades.

The single exception is the service order line. A `ServiceOrderLine` is immutable once written and is never soft-deleted, so it carries only `id` and `created_at`: it has neither an `updated_at` field nor a `version` field, and neither should appear in its representation.

Recomputation of a derived field counts as a mutation. When a booth's `posture` is recalculated, when a warehouse's `committed_cwt` moves, when a show's `committed_labor_hours` or `cancelled_labor_call_count` change, or when an exhibitor's `account_balance_cents` is rebuilt, the owning row's `updated_at` is refreshed and its `version` advances — even though no client field was written. This is what makes the optimistic concurrency scheme in §2.7 meaningful.

### 2.6. Cents, Hundredweight and Hours: The Rounding Discipline

All monetary amounts in this system are integers denominated in cents; there are no fractional-cent fields and no decimal money types. Wherever a computation produces a non-integral cent value, it is rounded half up — a value ending in exactly half a cent rounds away from zero to the next whole cent.

Where a total is built from parts, the *place* at which rounding happens is part of the specification and is never a matter of implementer discretion. Three distinct disciplines appear in this document and they do not agree with one another, deliberately:

- **Round each part, then sum.** Service order lines are each rounded to whole cents and the rounded values are added. Warehouse hundredweight is computed per crate — each crate's pound weight divided by one hundred and rounded *up* to a whole number — and the whole numbers are added. Storage charges are computed and rounded per crate and then added.
- **Sum in exact arithmetic, then round once.** A labor call's charge multiplies crew size across three band products and rounds the single final figure.
- **Exact integer arithmetic, no rounding at all.** Subtracting a volume discount from a subtotal, adding a service fee to a discounted base, aggregating an exhibitor's account balance, and computing a refurbishment variance are all exact integer operations.

Multipliers and percentages are carried exactly as declared and are not themselves rounded: a deadline tier multiplier is an exact two-decimal rational, and no rounding occurs at the point the tier is chosen.

Hours are carried to two decimal places. A labor call's scheduled hours and a show's committed crew-hours are both two-decimal quantities, and where a sum of hours is stored it is rounded half up to two decimals.

### 2.7. Stale-Read Rejection on Shared Parents

Three write operations act on a child while depending on the current state of a shared parent that other operators are also moving. Each of those three requires the client to declare, as a mandatory (never optional) request field, the parent `version` it last observed. If the declared value does not equal the parent row's current `version` at the moment the write is processed, the write is rejected outright and no state changes.

- Creating a service order requires `expected_booth_version`, carrying the client's last observed `version` of the target `Booth`. A booth's version advances whenever its posture is recomputed or another order is written against it, so a client working from a stale read would be pricing and credit-checking against a booth state that no longer holds. A mismatch is rejected with `ERR_STALE_BOOTH_VERSION` (HTTP 412).
- Applying a change order — `POST /change-orders/{id}/apply` — requires `expected_service_order_version`, carrying the client's last observed `version` of the target `ServiceOrder`. Several approved change orders may legitimately land on one order, and each application mutates lines and reprices the whole order, so an application computed from a stale view would produce a price delta against the wrong baseline. A mismatch is rejected with `ERR_STALE_SERVICE_ORDER_VERSION` (HTTP 412).
- Checking a crate into a warehouse — `POST /crates/{id}/warehouse-check-in` — requires `expected_warehouse_version`, carrying the client's last observed `version` of the target `Warehouse`. Every check-in and every departure moves `committed_cwt`, so a client holding a stale warehouse view would be reasoning about remaining capacity from a number the warehouse no longer reports. A mismatch is rejected with `ERR_STALE_WAREHOUSE_VERSION` (HTTP 412).

No other endpoint in the API takes a version field, and no other endpoint performs a stale-version check. Supplying one of these three fields is mandatory on its own endpoint; there is no "omit to skip the check" behaviour.

### 2.8. Resolving Paths and Foreign Keys

Identifiers that appear in a URL path are resolved strictly left to right, and the first identifier that does not name an existing row terminates the request with the 404 that belongs to *that* resource type — the server does not proceed to look up anything further to its right. A request naming a jurisdiction under a venue that does not exist therefore fails with `ERR_VENUE_NOT_FOUND`, never with `ERR_JURISDICTION_NOT_FOUND`.

Each resource type has its own not-found identifier, all of them HTTP 404: `ERR_VENUE_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_EXHIBITOR_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_CRATE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFURB_NOT_FOUND` and `ERR_LICENSE_NOT_FOUND`.

The same discipline governs foreign keys carried in a request body. They are resolved in the order the endpoint declares its input fields, and the first one that fails to resolve produces the not-found identifier matching the entity it referenced. This extends into collections: an id inside `crate_ids` that names no crate yields `ERR_CRATE_NOT_FOUND`, and an unresolvable id inside `service_order_ids` yields `ERR_SERVICE_ORDER_NOT_FOUND`.

### 2.9. The Order in Which Requests Are Judged

When a single request would fail several checks at once, exactly one error is returned, and which one is fully determined by the following precedence ladder. A check is only reached when every check above it has passed. Text order elsewhere in this document is narrative convenience; this list is the specification.

1. Both `X-User-Role` and `X-User-ID` are present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. `X-User-Role` names one of the six roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
3. The acting role appears on the endpoint's authorised list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint.
4. Ownership: an acting `Exhibitor`'s `X-User-ID` equals the `exhibitor_id` reachable from the target resource, and an acting `WarehouseAgent`'s `X-User-ID` equals the `warehouse_id` the request targets — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to every exhibitor-scoped and warehouse-scoped endpoint.
5. Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /change-orders/{id}/review`, `POST /damage-claims/{id}/adjudication` and `POST /invoices/{id}/void`.
6. Request shape: every required body field is present, every enum value is a declared member of its enumeration, every integer field is a non-negative integer, and every datetime parses as ISO 8601 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every write endpoint.
7. Pagination bounds — otherwise `ERR_INVALID_PAGINATION` (400). Applies to every list endpoint.
8. Path-segment existence, left to right — otherwise the matching 404 identifier. Applies to every endpoint carrying a path parameter.
9. Body foreign-key existence, in declared input order — otherwise the matching 404 identifier. Applies to every write endpoint carrying foreign keys.
10. The target sits in a from-state the requested transition declares — otherwise `ERR_INVALID_STATE_TRANSITION` (409). Applies to every state-transition endpoint.
11. The target is not already in a terminal state of its machine — otherwise `ERR_ENTITY_TERMINAL` (409). Applies to every state-transition endpoint. Rungs 10 and 11 are evaluated in the opposite order to their numbering: the terminal test runs first, so a target whose own current status is a terminal status of its machine is refused with `ERR_ENTITY_TERMINAL` even though that same status is equally not a from-state the requested transition declares, and rung 10's `ERR_INVALID_STATE_TRANSITION` is reached only once the target's own status has been found non-terminal. Checks further down this ladder, and the transition-specific rules described elsewhere in this document, keep their own identifiers — including rules that refuse with `ERR_INVALID_STATE_TRANSITION` because some *other* row the transition depends on sits in a terminal status of its own machine.
12. The supplied `expected_booth_version`, `expected_service_order_version` or `expected_warehouse_version` matches its parent's current `version` — otherwise the matching 412 identifier from §2.7. Applies to `POST /service-orders`, `POST /change-orders/{id}/apply` and `POST /crates/{id}/warehouse-check-in`.
13. The show reached from the target is in a status that admits the operation — otherwise `ERR_SHOW_NOT_ACCEPTING` (409). Applies to `POST /service-orders`, `POST /service-orders/{id}/fulfillment`, `POST /labor-calls`, `POST /labor-calls/{id}/dispatch`, `POST /lead-capture-licenses/{id}/lead-batches` and `POST /crates/{id}/movements`.
14. The booth reached from the target is not `FROZEN` — otherwise `ERR_BOOTH_FROZEN` (409). Applies to `POST /service-orders`, `POST /service-orders/{id}/fulfillment`, `POST /labor-calls`, `POST /labor-calls/{id}/dispatch`, `POST /change-orders`, `POST /change-orders/{id}/submit`, `POST /change-orders/{id}/apply`, `POST /exhibit-designs/{id}/quote`, `POST /exhibit-designs/{id}/release` and `POST /lead-capture-licenses/{id}/lead-batches`.
15. The booth reached from the target is not `RESTRICTED`, for the narrower set of operations that `RESTRICTED` also blocks — otherwise `ERR_BOOTH_RESTRICTED` (409). Applies to `POST /labor-calls/{id}/dispatch` and to `POST /exhibit-designs/{id}/decision` when the decision is `APPROVE`.
16. Self-install is permitted by the named jurisdiction — otherwise `ERR_UNION_JURISDICTION_REQUIRED` (422). Applies to `POST /labor-calls`.
17. The venue permits the booth's geometry to fly a hanging sign — otherwise `ERR_HANGING_SIGN_NOT_PERMITTED` (422). Applies to `POST /exhibit-designs` and `POST /exhibit-designs/{id}/quote`.
18. No crate on the shipment exceeds the venue's forklift limit — otherwise `ERR_CRATE_WEIGHT_LIMIT_EXCEEDED` (422). Applies to `POST /drayage-shipments`.
19. The requested crew window is well formed and inside the show envelope — otherwise `ERR_LABOR_WINDOW_OUTSIDE_SHOW` (422). Applies to `POST /labor-calls`.
20. Buffered crew overlap — otherwise `ERR_LABOR_CALL_OVERLAP` (409). Applies to `POST /labor-calls`.
21. Booth floor-occupancy collision — otherwise `ERR_BOOTH_WINDOW_CONFLICT` (409). Applies to `POST /service-orders`.
22. Aggregate dock capacity at the warehouse — otherwise `ERR_DOCK_CAPACITY_EXCEEDED` (409). Applies to `POST /drayage-shipments`.
23. The jurisdiction belongs to the venue hosting the booth's show — otherwise `ERR_JURISDICTION_VENUE_MISMATCH` (422). Applies to `POST /labor-calls`.
24. Every listed crate belongs to the shipment's exhibitor — otherwise `ERR_CRATE_EXHIBITOR_MISMATCH` (422). Applies to `POST /drayage-shipments`.
25. The polymorphic change target exists and sits on the change order's booth — otherwise `ERR_CHANGE_TARGET_MISMATCH` (422). Applies to `POST /change-orders` and `POST /change-orders/{id}/apply`.
26. Every swept order belongs to the invoice's exhibitor and show — otherwise `ERR_INVOICE_SCOPE_MISMATCH` (422). Applies to `POST /invoices`.
27. The cited crate is packed with the claimed asset and the asset belongs to the claimant — otherwise `ERR_CLAIM_REFERENCE_MISMATCH` (422). Applies to `POST /damage-claims`.
28. Warehouse capacity and receiving status — otherwise `ERR_WAREHOUSE_CAPACITY_EXCEEDED` (409). Applies to `POST /crates/{id}/warehouse-check-in`.
29. Crew size within the jurisdiction's bounds — otherwise `ERR_CREW_SIZE_LIMIT` (422). Applies to `POST /labor-calls`.
30. Collection inputs are non-empty — otherwise `ERR_EMPTY_COLLECTION` (422). Applies to `POST /service-orders`, `POST /drayage-shipments`, `POST /invoices` and `POST /lead-capture-licenses/{id}/lead-batches`.
31. Line sequence numbers are unique and contiguous from 1 — otherwise `ERR_INVALID_LINE_SEQUENCE` (422). Applies to `POST /service-orders`.
32. Booth number uniqueness within the show — otherwise `ERR_DUPLICATE_BOOTH_NUMBER` (409). Applies to `POST /booths`.
33. The design revision budget is not exhausted — otherwise `ERR_DESIGN_REVISION_LIMIT` (409). Applies to `POST /exhibit-designs/{id}/decision` when the decision is `REQUEST_REVISION`.
34. The claim appeal budget is not exhausted — otherwise `ERR_CLAIM_APPEAL_LIMIT` (409). Applies to `POST /damage-claims/{id}/appeal`.
35. Refurbishment cost overrun is within tolerance or covered — otherwise `ERR_REFURB_OVERRUN_UNAPPROVED` (422). Applies to `POST /refurb-work-orders/{id}/progress` when the target status is `COMPLETED`.
36. The post-refurbishment grade does not regress — otherwise `ERR_CONDITION_GRADE_REGRESSION` (422). Applies to `POST /refurb-work-orders/{id}/progress` when the target status is `COMPLETED`.
37. The lead-capture licence is still open — otherwise `ERR_LICENSE_CLOSED` (409). Applies to `POST /lead-capture-licenses/{id}/lead-batches`.
38. Projected credit exposure is within the exhibitor's limit — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (402). Applies to `POST /service-orders`.
39. The payment amount is positive and does not overshoot the invoice — otherwise `ERR_PAYMENT_EXCEEDS_BALANCE` (422). Applies to `POST /invoices/{id}/payments`.
40. The declared value does not exceed the asset's list value — otherwise `ERR_DECLARED_VALUE_EXCEEDS_ASSET` (422). Applies to `POST /damage-claims`.
41. The requested coverage basis is available — otherwise `ERR_COVERAGE_BASIS_UNAVAILABLE` (422). Applies to `POST /damage-claims/{id}/adjudication`.
42. The exhibitor is not suspended — otherwise `ERR_EXHIBITOR_SUSPENDED` (402). Applies to `POST /invoices/{id}/issue`.

### 2.10. Booth Posture: The Universal Gate on Booth-Scoped Work

Almost every operation in this API eventually touches a booth, and the booth carries a derived gate called `posture` that decides whether that work may proceed. Posture is never written by a client. It is recomputed from scratch on every write that touches the booth's exhibitor, its show, its labor calls, its exhibitor's drayage shipments on that show, or its change orders, and it takes one of three values: `OPEN`, `RESTRICTED` or `FROZEN`. Alongside it the booth carries `posture_reason`, an enum token naming the single highest-priority clause that produced the current value.

The clauses are evaluated in a fixed order and the first one that holds wins, fixing both `posture` and `posture_reason`. Every freezing clause outranks every restricting clause:

1. The booth's exhibitor has `status` `SUSPENDED` — posture `FROZEN`, reason `EXHIBITOR_SUSPENDED`.
2. The exhibitor's `account_balance_cents` is strictly greater than its `credit_limit_cents` — posture `FROZEN`, reason `CREDIT_LIMIT_BREACHED`. A balance exactly equal to the limit is not a breach.
3. The booth's show has `status` `CLOSED` — posture `FROZEN`, reason `SHOW_CLOSED`.
4. The booth's show has `status` `CANCELLED` — posture `FROZEN`, reason `SHOW_CANCELLED`.
5. At least one labor call on this booth has `status` `NO_SHOW` — posture `RESTRICTED`, reason `LABOR_NO_SHOW`.
6. At least one drayage shipment matching this booth's exhibitor and this booth's show carries `hold_flag` true — posture `RESTRICTED`, reason `FREIGHT_HOLD`.
7. At least one change order on this booth has `status` `APPROVED` — posture `RESTRICTED`, reason `CHANGE_ORDER_APPROVED`.

When no clause holds, `posture` is `OPEN` and `posture_reason` is null.

A `FROZEN` booth blocks the ten operations enumerated at rung 14 of §2.9, each rejected with `ERR_BOOTH_FROZEN`. A `RESTRICTED` booth blocks the narrower pair at rung 15 — dispatching a labor crew, and approving a quoted exhibit design — each rejected with `ERR_BOOTH_RESTRICTED`. Everything a `RESTRICTED` booth blocks, a `FROZEN` booth also blocks, and where both would apply the `FROZEN` rejection is the one returned, because it sits higher on the ladder.

### 2.11. Conserved Quantities and Cascade Discipline

Three derived aggregates are the system's conserved quantities, and each is rebuilt by full recomputation from its source rows every time it is touched. None of them is maintained as an incremental delta, because a forward action and its compensating reversal must land the aggregate back on exactly the figure it held before — issuing and then voiding an invoice is a perfect round trip, and checking a crate in and then moving it out returns a warehouse's committed weight to its prior value.

- `Exhibitor.account_balance_cents` aggregates invoices and settled claims (§3.9).
- `Warehouse.committed_cwt` aggregates the hundredweight of crates physically held (§3.6).
- `Show.committed_labor_hours` aggregates crew-hours on calls that are out on the floor (§3.7).

Cascades in this system are immediate and synchronous: by the time a write's response is returned, every dependent row it touches has already moved. A single request may therefore mutate several rows — an approved loss claim writes off an asset, which sends that asset's crates to `LOST`, which recomputes the holding warehouse's committed weight — and each mutated row independently refreshes its own `updated_at` and increments its own `version`. Cascades run downward only: the server never resurrects a row that a cascade previously terminated, so a compensating action restores what it can and explicitly leaves the rest, as noted in the individual workflows below.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Show Ground

Before any exhibitor can order anything, `ShowOperations` must describe the physical and contractual world the show happens in. A **Venue** is registered with a trade `name` and the `city` it sits in, plus the operating parameters that later govern labor and freight. The straight-time labor band is declared as two UTC times of day in `HH:MM` form: `straight_time_start_hhmm`, defaulting to `08:00`, and `straight_time_end_hhmm`, defaulting to `16:30`, whose instant is the exclusive end of the band. Venue-local time is defined to equal UTC throughout this system, so no timezone conversion is ever performed. `max_forklift_capacity_lbs` is the heaviest single crate the venue's material-handling equipment may lift and defaults to 6000 pounds. `hanging_sign_booth_types` lists the booth geometries permitted to fly a hanging sign here and defaults to `ISLAND` and `PENINSULA`. `dock_count` records how many receiving docks the building has and defaults to 4. A venue's `status` is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE`.

Each venue owns a set of **Union Jurisdictions**, created beneath the venue in the URL hierarchy so that `venue_id` is taken from the creation path rather than from the body — a jurisdiction is scoped to exactly one venue. A jurisdiction names a `trade`, one of `RIGGING`, `ELECTRICAL`, `CARPENTRY`, `MATERIAL_HANDLING` or `CLEANING`, and carries the commercial terms under which that craft dispatches crews: `straight_time_rate_cents_per_hour` is the mandatory per-worker hourly rate in cents; `overtime_multiplier` scales that rate for hours falling outside the venue's straight-time band and defaults to 1.5; `doubletime_multiplier` scales it for Sunday calls and defaults to 2.0; `min_call_hours` is the minimum billable duration of any dispatched call regardless of hours actually worked and defaults to 4.0; `crew_max_size` caps the workers dispatched to a single call and defaults to 8; `exhibitor_self_install_allowed` says whether exhibitor personnel may perform this trade themselves and defaults to false; and `turnaround_buffer_minutes` is the mandatory idle gap the jurisdiction insists on between two of its calls at the same booth, defaulting to 30. Jurisdictions at a venue can be listed and filtered by `trade`.

Advance **Warehouses** are registered independently of venues, with a `name`, a `city`, and a mandatory `capacity_cwt` giving the total hundredweight the building can hold. `storage_rate_cents_per_cwt_per_month` sets the between-show storage rate in cents per hundredweight per billable month and defaults to 2200. `free_days` grants a grace period before metered storage begins and defaults to 30 days. `dock_capacity_cwt` caps the aggregate hundredweight of receiving appointments that may overlap any single instant and defaults to 300. A warehouse's `status` is `ACCEPTING` or `CLOSED` and defaults to `ACCEPTING`; a `CLOSED` warehouse takes no new crates. `committed_cwt` is derived, starts at 0, and is described in §3.6.

A **Show** binds a venue to a calendar. Creating one supplies `venue_id`, a `name`, and seven instants that together define every deadline the pricing engine reads: `discount_deadline`, `advance_warehouse_deadline`, `move_in_start`, `move_in_end`, `show_open`, `show_close` and `move_out_end`. Shows are born in `DRAFT` with `committed_labor_hours` at 0 and `cancelled_labor_call_count` at 0, and their `status` is server-managed throughout. Shows may be listed and filtered by `venue_id` and by `status`.

Advancing the show lifecycle is exclusive to `ShowOperations`, who names the desired `to_status`. The first advance, `DRAFT → OPEN_FOR_ORDERS`, is where the calendar is validated: `discount_deadline` must be strictly earlier than `advance_warehouse_deadline`, which must be strictly earlier than `move_in_start`, which must be strictly earlier than `move_in_end`, which must be no later than `show_open`, which must be strictly earlier than `show_close`, which must be no later than `move_out_end`. A calendar failing that chain is refused. On success the show's `updated_at` is refreshed and its `version` advances by one.

`OPEN_FOR_ORDERS → ADVANCE_CLOSED` closes the advance-order window going forward but reprices nothing: a service order's `deadline_tier` is frozen at its `ordered_at` instant and is never re-derived by any later show transition. `ADVANCE_CLOSED → MOVE_IN` leaves freight exactly where it is — every crate sitting at an advance warehouse for this show stays `AT_ADVANCE_WAREHOUSE`, because crate movement is operator-driven and never implied by a show transition. `MOVE_IN → ON_SITE` likewise leaves lead-capture licences alone: a licence in `PROVISIONED` stays `PROVISIONED` until its first accepted lead batch.

`ON_SITE → MOVE_OUT` is the first transition that cascades. Every drayage shipment on this show sitting in `DELIVERED_TO_BOOTH` moves to `CLOSED`, and as each shipment closes its `hold_flag` is forced to false and every booth of that shipment's exhibitor on that show recomputes its posture — which is how a freight hold lifts automatically at tear-down. In the same transition, every lead-capture licence on a booth of this show whose `status` is `ACTIVE` moves to `CLOSED` and its `license_total_cents` is frozen at the figure it then holds.

`MOVE_OUT → CLOSED` may only proceed when no labor call on any booth of this show is still `DISPATCHED` or `ON_SITE`; crews must be off the floor before the show can close. On success, every booth of the show recomputes posture and lands on `FROZEN` with `posture_reason` `SHOW_CLOSED`, and every lead-capture licence still in `PROVISIONED` moves to `CLOSED`. `CLOSED` is terminal.

Cancellation is available from `DRAFT`, `OPEN_FOR_ORDERS` and `ADVANCE_CLOSED` only. Requesting it from `MOVE_IN` or anything later is refused with `ERR_INVALID_STATE_TRANSITION`, and requesting any transition out of `CLOSED` or `CANCELLED` is refused with `ERR_ENTITY_TERMINAL`. When a show is cancelled, every service order on a booth of that show whose `fulfillment_status` is `PENDING`, `CONFIRMED`, `SCHEDULED` or `HELD` moves to `CANCELLED`, and every booth recomputes posture and lands on `FROZEN` with `posture_reason` `SHOW_CANCELLED`.

### 3.2. Exhibitor Accounts and Booth Assignment

An **Exhibitor** account is opened with a `company_name` and a `contact_email`, and optionally a `credit_limit_cents` that defaults to 500000 — five thousand dollars of permitted exposure. Accounts open `ACTIVE` with `account_balance_cents` at 0 and `suspension_reason` null.

Accounts receivable controls standing. A `FinanceController` may move an exhibitor's `status` between `ACTIVE` and `SUSPENDED` by naming a `to_status`, optionally supplying a `reason` that is captured verbatim into `suspension_reason` when the account becomes `SUSPENDED`. Suspension is the sharpest instrument in the system, and it fires a four-link chain: the exhibitor's `status` becomes `SUSPENDED`; every booth that exhibitor holds recomputes posture and, because the suspension clause outranks everything, lands on `FROZEN` with `posture_reason` `EXHIBITOR_SUSPENDED`; every service order on those booths whose `fulfillment_status` is `PENDING` moves to `HELD`; and every labor call attached to one of those held orders whose `status` is `REQUESTED` moves to `CANCELLED`, which in turn recomputes that show's `cancelled_labor_call_count` and its `committed_labor_hours`. Reinstating the exhibitor to `ACTIVE` walks the chain back only as far as it honestly can: postures are recomputed, and orders that were driven to `HELD` return to `PENDING` once their booth is no longer `FROZEN` — but cancelled labor calls are not resurrected, because a crew that was released has been released.

A **Booth** is a rented rectangle of floor. `ShowOperations` assigns one by supplying the `show_id` it sits on, the `exhibitor_id` holding it, a `booth_number` from the floor plan, the contracted `sqft`, and a `booth_type` of `INLINE`, `CORNER`, `PENINSULA` or `ISLAND`. Booth numbers must be unique within their show; a repeat within the same `show_id` is refused with `ERR_DUPLICATE_BOOTH_NUMBER`, while the same number on a different show is perfectly acceptable. A newly created booth immediately computes its `posture` and `posture_reason` from the clauses in §2.10 — a booth assigned to an already-suspended exhibitor is born `FROZEN`. Booths may be listed and filtered by `show_id`, by `exhibitor_id` and by `posture`.

Because posture recomputation is a mutation, and because writing a service order against a booth also mutates it, a booth's `version` is a moving target — which is precisely what makes it worth pinning on order creation, as §2.7 requires.

### 3.3. Exhibit Design and the Rental-Versus-Purchase Decision

An exhibiting company decides how to hold its exhibit property before it decides anything else, and this system's job is to make that decision quantitative. An `Exhibitor` opens an **Exhibit Design** by naming its own `exhibitor_id`, the `booth_id` the design is drawn for, the footprint `sqft`, the `linear_feet` of structural wall, and a `selected_acquisition_mode` of either `RENTAL` or `PURCHASE`. Two optional inputs shape the economics: `has_hanging_sign` defaults to false, and `expected_show_count` — the number of shows the exhibitor projects reusing the property across, and the amortisation denominator — defaults to 1. A design is born in `DRAFT` with `asset_id` null, `revision_count` at 0, and all six quote fields null. Designs may be listed and filtered by `exhibitor_id`, `booth_id`, `asset_id` and `status`.

A hanging sign is a venue-permission question, not a design question. If `has_hanging_sign` is true, the `booth_type` of the design's booth must appear in the `hanging_sign_booth_types` list of the venue hosting that booth's show; otherwise the request is refused with `ERR_HANGING_SIGN_NOT_PERMITTED`. This check runs both when the design is created and again when it is quoted, because a venue's policy may have been edited in between.

Quoting is the exhibitor's own action and advances the design `DRAFT → QUOTED`. It requires the design to be in `DRAFT`, the booth's posture to be anything other than `FROZEN`, and the design's `revision_count` to be no greater than 3. The quote body may carry `selected_acquisition_mode` to change the mode being priced. The quote run always prices **both** variants and stores both, so the exhibitor can see the road not taken.

The rental variant works forward from catalogue rates. A rental base is assembled as `sqft` multiplied by 2400 cents per square foot, plus `linear_feet` multiplied by 15000 cents per linear foot, plus a flat 85000 cents when `has_hanging_sign` is true and nothing when it is false. `rental_quote_cents` is that base multiplied by one plus a twelve percent refurbishment load — that is, multiplied by 1.12 — and rounded half up to a whole cent. `rental_per_show_cents` equals `rental_quote_cents` exactly, because a rental is re-rented in full for every show and carries neither residual value nor an amortisation denominator.

The purchase variant capitalises a build. A build cost is assembled as `sqft` multiplied by 7800 cents per square foot, plus `linear_feet` multiplied by 38000 cents per linear foot, plus a flat 210000 cents when `has_hanging_sign` is true. `purchase_quote_cents` is that build cost multiplied by one plus a fifteen percent design fee — multiplied by 1.15 — and rounded half up. A residual is then taken as `purchase_quote_cents` multiplied by 0.20 and rounded half up. `purchase_per_show_cents` is the difference between `purchase_quote_cents` and that residual, divided by `expected_show_count` and rounded half up, with a flat 45000 cents of per-show storage-and-refurbishment carry added on afterwards — the carry is added after the division has been rounded, never folded in before it. For identical geometry the purchase figure runs to several times the rental figure, which is exactly why the breakeven number matters.

`breakeven_show_count` is the smallest whole number of reuses at which purchasing beats renting on a per-show basis. Candidate reuse counts are scanned in ascending order from 1 through 20 inclusive; for each candidate, the difference between `purchase_quote_cents` and the residual is divided by that candidate and rounded half up, then 45000 cents of carry is added, and the first candidate whose result is less than or equal to `rental_per_show_cents` is the answer. When no candidate within that twenty-show horizon satisfies the comparison, `breakeven_show_count` is set to 0 — a sentinel meaning the property never breaks even, not a real reuse count. Finally, `quoted_price_cents` takes the value of `rental_quote_cents` when `selected_acquisition_mode` is `RENTAL` and of `purchase_quote_cents` when it is `PURCHASE`.

Design decisions belong to `ShowOperations`, who supplies a `decision` of `APPROVE`, `REQUEST_REVISION` or `CANCEL`, plus an optional `note`. `APPROVE` moves a `QUOTED` design to `APPROVED`; it requires the booth's posture to be exactly `OPEN` — a `RESTRICTED` booth is refused with `ERR_BOOTH_RESTRICTED` — and requires `quoted_price_cents` to be non-null. Approval pins the quote: while a design sits in `APPROVED` or `RELEASED_TO_FAB`, no later quote run may overwrite its stored figures.

`REQUEST_REVISION` sends a `QUOTED` design back to `DRAFT`. It is permitted only while `revision_count` is strictly below 3; a fourth request against a design that has already cycled three times is refused with `ERR_DESIGN_REVISION_LIMIT`. On success `revision_count` increases by one and all six computed figures — `rental_quote_cents`, `purchase_quote_cents`, `rental_per_show_cents`, `purchase_per_show_cents`, `breakeven_show_count` and `quoted_price_cents` — are cleared back to null, so a re-quote starts from a clean slate. `CANCEL` is available from `DRAFT`, `QUOTED` and `APPROVED` and moves the design to the terminal `CANCELLED`; no asset is minted, and if `asset_id` has already been set the cancellation is refused with `ERR_INVALID_STATE_TRANSITION`.

Releasing an approved design to fabrication is the moment the design becomes property. It moves the design `APPROVED → RELEASED_TO_FAB`, requires the booth's posture to be anything other than `FROZEN`, and mints a brand-new exhibit asset in the same transaction: the asset's `exhibitor_id` is copied from the design, its `acquisition_mode` from the design's `selected_acquisition_mode`, its `list_value_cents` from the design's `quoted_price_cents`, and its `shipping_weight_lbs` from the design's `sqft` multiplied by 12 pounds per square foot. The new asset starts in `IN_DESIGN` with `condition_grade` `A`, and the design's `asset_id` is set to point at it.

### 3.4. Exhibit Property Between Shows: Storage, Refurbishment and Retirement

An **Exhibit Asset** is the physical property itself. Most assets are minted by a design release, but an exhibitor may also register property it already owns, supplying its `exhibitor_id`, the `acquisition_mode` (`RENTAL` or `PURCHASE`), the `list_value_cents` that serves as the undepreciated replacement value and the declared-value ceiling on any claim, and the `shipping_weight_lbs` that becomes the tariff weight basis when a claim cites no crate. A `condition_grade` of `A`, `B`, `C` or `D` may be supplied and defaults to `A`. An optional `derived_from_asset_id` points back at a predecessor asset when this one was split out of a refurbished parent — a self-reference that the asset listing can filter on, alongside `exhibitor_id`, `current_warehouse_id` and `status`. Registered assets begin `IN_DESIGN` with `current_warehouse_id` null, `refurb_cycles_count` at 0 and `stored_since` null.

The asset lifecycle is driven by naming a `to_status`, optionally with a `warehouse_id`. From `IN_DESIGN` the asset advances to `FABRICATED`, a pure state change that bumps the asset's `version`. Entry into `IN_STORAGE` is permitted from `FABRICATED`, from `ON_SHOW_FLOOR` and from `IN_REFURB`, requires the named warehouse's `status` to be `ACCEPTING`, and sets `current_warehouse_id` to that warehouse while stamping `stored_since` with the logical clock's current instant. From `IN_STORAGE` an asset may be pulled to `STAGED`, which clears `stored_since` back to null and is refused while any refurbishment work order on that asset is still `OPEN` or `IN_PROGRESS`. A `STAGED` asset advances to `ON_SHOW_FLOOR`, clearing `current_warehouse_id` to null.

Retirement is available from `IN_STORAGE` and from `FABRICATED`. It is refused while any damage claim against the asset is still `FILED`, `UNDER_INVESTIGATION` or `APPROVED` — an asset under claim cannot be quietly disposed of. Retirement clears `current_warehouse_id` to null; note that it does not move any warehouse's `committed_cwt`, because assets carry no weight in this system — crates do. `RETIRED` is terminal, as is `WRITTEN_OFF`, which is reached only by cascade from an approved loss claim as described in §3.9.

A **Refurbishment Work Order** is opened against stored property by naming the `asset_id`, the `warehouse_id` of the shop doing the work, a `scope` of `GRAPHICS_REFRESH`, `STRUCTURAL_REPAIR` or `FULL_REBUILD`, and a quoted `estimate_cents`. It is born `OPEN` with `actual_cents`, `variance_cents` and `condition_grade_after` all null. Work orders may be listed and filtered by `asset_id` and `warehouse_id`.

Progress is recorded by naming a `to_status`, with `actual_cents` and `condition_grade_after` supplied where the transition needs them. Starting the work moves the order `OPEN → IN_PROGRESS` and requires the asset to be `IN_STORAGE` with its `current_warehouse_id` equal to the work order's `warehouse_id` — the shop must actually hold the property. Starting also cascades the asset `IN_STORAGE → IN_REFURB`, which is what makes it unavailable for staging.

Completing the work moves the order `IN_PROGRESS → COMPLETED` and is the most heavily guarded transition in this subsection. `actual_cents` must be supplied. It may not exceed the estimate inflated by the twenty percent overrun tolerance — that is, `estimate_cents` multiplied by 1.20 and rounded half up — unless an `APPLIED` change order exists that covers the overrun; a bare overrun is refused with `ERR_REFURB_OVERRUN_UNAPPROVED`. And `condition_grade_after` may not be worse than the asset's current `condition_grade`, where the grades run `A` better than `B` better than `C` better than `D`; a regression is refused with `ERR_CONDITION_GRADE_REGRESSION`. On success the work order records `variance_cents` as `actual_cents` minus `estimate_cents` — a figure that may legitimately be negative when the shop came in under estimate — and the asset cascades `IN_REFURB → IN_STORAGE` with `refurb_cycles_count` increased by one, `condition_grade` overwritten by `condition_grade_after`, and `stored_since` re-stamped with the logical clock's current instant, restarting the free-day allowance.

Cancelling a work order is available from `OPEN` and from `IN_PROGRESS`, and also fires as a cascade when the asset is written off. When the asset was `IN_REFURB` it returns to `IN_STORAGE`, but `refurb_cycles_count` does not increase — no cycle was completed — and `variance_cents` stays null.

Metered storage is billed by a run at the warehouse, requested with a single `as_of` instant. The run considers every crate whose `warehouse_id` is this warehouse, whose `status` is `AT_ADVANCE_WAREHOUSE` or `RETURNED_TO_WAREHOUSE`, and whose `stored_since` is non-null; crates in any other status are skipped entirely and keep whatever `storage_charge_cents` they already carried. Qualifying crates are processed in ascending `created_at` order. For each one, the elapsed time from `stored_since` to `as_of` is converted to whole days by discarding any partial day; the warehouse's `free_days` allowance is subtracted, with the result floored at zero to give the billable days; and those billable days are divided by thirty and rounded **up** to a whole number of billable months. The crate's `storage_charge_cents` is then its `weight_lbs` divided by one hundred and rounded up to a whole hundredweight, multiplied by the warehouse's `storage_rate_cents_per_cwt_per_month`, multiplied by the billable months, all rounded half up to a whole cent. The run's response reports the warehouse, the `as_of` instant it used, the `crate_count` it charged and the `total_storage_charge_cents`, which is the sum of the per-crate rounded charges. The boundary is exact: a crate stored for exactly `free_days` days yields zero billable days, zero billable months and a charge of exactly zero, while one further day yields a full month.

### 3.5. Ordering Show Services and the Pricing Waterfall

A **Service Order** is how an exhibitor buys anything the contractor performs at the booth. Either the `Exhibitor` itself or `ShowOperations` on its behalf raises one against a `booth_id`, naming a `service_type` of `ELECTRICAL`, `RIGGING`, `MATERIAL_HANDLING`, `CLEANING` or `INSTALL_DISMANTLE`, supplying the order's `lines`, and pinning the booth it read with `expected_booth_version`. Two further inputs, `window_start` and `window_end`, declare the interval during which the crew will occupy the booth floor; they are mandatory when `service_type` is `RIGGING` or `INSTALL_DISMANTLE` and optional otherwise. That window is a **closed** interval — both endpoints count as occupied.

The `lines` collection must be non-empty, or the order is refused with `ERR_EMPTY_COLLECTION`. Each line carries a `line_seq`, a `catalog_item_code` naming the catalogue SKU, a `unit_qty`, a `unit_rate_cents` giving the catalogue rate per unit, and an optional per-line `discount_pct` expressed as a fraction and defaulting to 0. The `line_seq` values must be unique within the order and must form a contiguous run starting at 1; a gap or a duplicate is refused with `ERR_INVALID_LINE_SEQUENCE`. Line rows are immutable once written, are never soft-deleted, and each stores its own computed `line_total_cents`. They can be listed under their owning order, where the stored `service_order_id` provides the reverse link.

Deadline tiering is decided once, at creation, from the logical clock alone. The instant the order is written is stamped onto it as `ordered_at`, and the show is reached from the order's booth. If `ordered_at` is at or before the show's `discount_deadline`, the order's `deadline_tier` is `ADVANCE` and its `tier_multiplier` is 1.00. Otherwise, if `ordered_at` is at or before the show's `move_in_start`, the tier is `STANDARD` and the multiplier is 1.30. In every remaining case the tier is `ONSITE` and the multiplier is 1.65. Both comparisons include their boundary instant, so an order placed at exactly `discount_deadline` is `ADVANCE` and one placed at exactly `move_in_start` is `STANDARD`; one microsecond later flips the tier. The show's own `status` plays no part in tiering — only those two timestamps do — and once stamped, the tier is frozen and is never re-derived by any subsequent show transition.

Line pricing then runs in ascending `line_seq` order, which is well defined because sequence numbers are unique within the order. For each line, `unit_qty` is multiplied by `unit_rate_cents` to give an exact integer cent gross; that gross is multiplied by one minus the line's `discount_pct`; the result is multiplied by the order's `tier_multiplier`; and **that** product is rounded half up to a whole cent and stored as `line_total_cents`. `subtotal_cents` is the exact integer sum of the per-line rounded values. The rounding site is pinned: each line is rounded to whole cents first and the rounded figures are then added. Summing the unrounded per-line products and rounding the sum once is not the rule and produces a different answer — three lines each landing exactly on half a cent contribute three extra cents under the pinned rule and only one extra cent under the forbidden one, and that discrepancy then propagates through the discount and fee bands into the order total.

From the subtotal, the order total is built by a waterfall whose evaluation order is pinned because the dependencies would otherwise look circular. Step one is `subtotal_cents` as just computed. Step two selects a volume-discount rate keyed on `subtotal_cents`: below 100000 cents the rate is zero; from 100000 up to but not including 500000 it is four percent; from 500000 up to but not including 1500000 it is seven percent; at 1500000 and above it is ten percent. Step three computes `volume_discount_cents` as `subtotal_cents` multiplied by that rate, rounded half up. Step four computes `discounted_base_cents` as `subtotal_cents` minus `volume_discount_cents`, exact integer arithmetic. Step five selects a service-fee rate keyed on `discounted_base_cents` — not on the subtotal and not on the total: below 50000 cents the rate is nine percent; from 50000 up to but not including 200000 it is seven percent; at 200000 and above it is five percent. Step six computes `service_fee_cents` as `discounted_base_cents` multiplied by that rate, rounded half up. Step seven computes `total_cents` as `discounted_base_cents` plus `service_fee_cents`, again exact integer arithmetic. The keying matters: a subtotal of 200000 cents earns the four percent volume band, leaving a discounted base of 192000, which falls into the **seven** percent fee band — not the five percent band that keying the fee off the subtotal would have selected. Volume tiers are strictly per order; there is no aggregation across an exhibitor's other orders.

Creating an order is gated by four booth-and-show conditions and one fiscal one. The show reached from the booth must be in `OPEN_FOR_ORDERS`, `ADVANCE_CLOSED`, `MOVE_IN` or `ON_SITE`, or the request is refused with `ERR_SHOW_NOT_ACCEPTING`. The booth must not be `FROZEN`, or the request is refused with `ERR_BOOTH_FROZEN`. The `expected_booth_version` must match, or the request is refused with `ERR_STALE_BOOTH_VERSION`. The requested floor window must not collide with any live window on the same booth: for every existing service order on that `booth_id` with a non-null window whose `fulfillment_status` is `PENDING`, `CONFIRMED`, `SCHEDULED` or `HELD`, the request is refused with `ERR_BOOTH_WINDOW_CONFLICT` when the new `window_start` is at or before that order's `window_end` **and** that order's `window_start` is at or before the new `window_end`. Because the interval is closed, two windows that merely touch at an endpoint do collide.

Writing the order is itself a mutation of the booth: a successful creation increments that booth's `version` by one, which is why two clients working from the same booth read cannot both succeed without one of them re-reading.

The fiscal gate is a projected-exposure test. The exhibitor's projected exposure is its current `account_balance_cents` plus the sum of `total_cents` across all of its service orders whose `billing_status` is `UNBILLED`, counting the order now being created. That figure must not exceed the exhibitor's `credit_limit_cents`; equality is permitted, and only a strictly greater figure is refused, with `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402.

Once written, a service order carries two status dimensions that advance completely independently of one another. The operational dimension, `fulfillment_status`, begins at `PENDING`. Naming a `to_status` — optionally with an explanatory `note` — advances it: `PENDING → CONFIRMED` requires the show to be in one of the four ordering statuses above and the booth not to be `FROZEN`, and leaves `billing_status` untouched; `CONFIRMED → SCHEDULED` requires the booth not to be `FROZEN` and bumps the order's `version`; `SCHEDULED → DELIVERED` requires the show to be in `MOVE_IN`, `ON_SITE` or `MOVE_OUT`, and once delivered the order is no longer eligible as a change-order target. Cancellation is reachable from `PENDING`, `CONFIRMED`, `SCHEDULED` and `HELD`, but only while `billing_status` is `UNBILLED` or `CREDITED`; cancelling also sends every labor call attached to that order whose `status` is `REQUESTED` or `DISPATCHED` to `CANCELLED` and recomputes the show's committed crew-hours. `CANCELLED` is the terminal fulfillment state.

`HELD` is not operator-driven. An order in `PENDING` moves to `HELD` purely as a cascade when its booth's posture becomes `FROZEN`, whether through exhibitor suspension or a credit-limit breach; that same cascade cancels every labor call on the order that was still `REQUESTED`, then recomputes the show's `cancelled_labor_call_count` and its `committed_labor_hours`. When the booth later stops being `FROZEN` — through reinstatement, a payment, an invoice void, or a claim settlement — the order returns from `HELD` to `PENDING`. The compensating move restores the fulfillment dimension only: the cancelled labor calls stay cancelled.

The financial dimension, `billing_status`, begins at `UNBILLED` and is likewise never written directly by a client. It advances to `INVOICED` when an invoice listing this order is issued, at which point the order's `invoice_id` is set and `fulfillment_status` is left untouched. It moves `INVOICED → REBILL_PENDING` when a change order is applied to it while it was already invoiced, and back `REBILL_PENDING → INVOICED` when a `FinanceController` re-issues the same invoice, which requires that invoice to be `ISSUED` or `PARTIALLY_SETTLED` and moves no money because the invoice total already reflects the adjustment. From `INVOICED` or `REBILL_PENDING` it reaches `SETTLED` when a payment drives the invoice's `settled_cents` up to its `total_cents`, and `CREDITED` when an unsettled invoice is voided, at which point the order's `invoice_id` is cleared back to null. Orders can be listed and filtered by `booth_id`, `invoice_id`, `fulfillment_status` and `billing_status`.

### 3.6. Freight: Crates, Drayage Receipts and the Advance Warehouse

A **Crate** is registered by its owner or by a warehouse agent with the owning `exhibitor_id`, an exhibitor-applied `crate_label`, a `crate_type` of `WOOD_CRATE`, `FIBER_CASE` or `LOOSE_UNCRATED`, and a gross `weight_lbs`. An optional `asset_id` names the exhibit asset packed inside. Crates are born `REGISTERED` with `warehouse_id` null, `shipment_id` null, `stored_since` null and `storage_charge_cents` at 0, and may be listed and filtered by `exhibitor_id`, `asset_id`, `warehouse_id`, `shipment_id` and `status`.

Checking a crate in is the warehouse agent's exclusive act and is the only operation that touches a warehouse's committed weight upward. It names the `warehouse_id` and the `expected_warehouse_version` the agent last read. It serves two distinct edges: a `REGISTERED` crate becomes `AT_ADVANCE_WAREHOUSE`, and a crate that came off the floor in `OUTBOUND_STAGED` becomes `RETURNED_TO_WAREHOUSE`. Both edges require the warehouse's `status` to be `ACCEPTING` and require that the warehouse's current `committed_cwt` plus this crate's own hundredweight — its `weight_lbs` divided by one hundred and rounded up to a whole number — be no greater than the warehouse's `capacity_cwt`; a closed warehouse or an overflow is refused with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`. On success the crate's `warehouse_id` is set, its `stored_since` is stamped with the logical clock's current instant, the warehouse's `committed_cwt` is recomputed upward and the warehouse's `version` increases by one.

`Warehouse.committed_cwt` is a full recomputation, never a delta: it is the sum, over every crate whose `warehouse_id` is this warehouse and whose `status` is `AT_ADVANCE_WAREHOUSE` or `RETURNED_TO_WAREHOUSE`, of that crate's `weight_lbs` divided by one hundred and rounded up to a whole hundredweight. Rounding up happens per crate and the whole numbers are then added; summing raw pounds across crates and rounding once at the end is not the rule. Crates in any other status contribute nothing at all — an `EMPTY_STORED` crate sits in accessible storage on the show floor, carries no `warehouse_id`, and is invisible to this aggregate.

Crate movement along the rest of the lifecycle is requested by naming a `to_status`, optionally with a `shipment_id` and an explanatory `note`. From `AT_ADVANCE_WAREHOUSE` a crate moves to `IN_TRANSIT_TO_SHOW` provided its `shipment_id` is non-null and that shipment's show is in `ADVANCE_CLOSED`, `MOVE_IN` or `ON_SITE`; departure clears `warehouse_id` and `stored_since` back to null, recomputes the warehouse's `committed_cwt` downward, and moves the shipment from `RECEIVED` to `IN_TRANSIT` if it was still `RECEIVED`. A crate reaches `ON_SHOW_FLOOR` from `REGISTERED`, from `IN_TRANSIT_TO_SHOW` or from `EMPTY_STORED`, again requiring a non-null `shipment_id` and requiring the shipment's show to be in `MOVE_IN`, `ON_SITE` or `MOVE_OUT`; every movement whose show-status requirement is unmet is refused with `ERR_SHOW_NOT_ACCEPTING`. Direct-to-show freight uses the `REGISTERED → ON_SHOW_FLOOR` edge and never touches a warehouse at all. Whenever every crate belonging to a shipment has reached `ON_SHOW_FLOOR`, that shipment bubbles up to `DELIVERED_TO_BOOTH`.

During the show a crate cycles between `ON_SHOW_FLOOR` and `EMPTY_STORED`. Emptying it requires the show to be in `MOVE_IN` or `ON_SITE` and deliberately does **not** set `stored_since`: accessible empty-crate storage during a show is not metered storage and is never billed by a storage run. Bringing it back to `ON_SHOW_FLOOR` requires the show to be in `ON_SITE` or `MOVE_OUT` and re-evaluates the shipment bubble-up. At tear-down, a crate on the floor moves to `OUTBOUND_STAGED` while the show is in `MOVE_OUT`, queueing it either for the outbound carrier or for a return to the warehouse. From `OUTBOUND_STAGED` it either goes back to the warehouse through a check-in, or moves to `RELEASED_TO_CARRIER`, which is terminal and accepts no further movement.

`LOST` is the other terminal crate status and is reachable from every non-terminal one — that is, from anything other than `RELEASED_TO_CARRIER` and `LOST` itself. It is reached either by an explicit movement or by cascade from an approved loss claim on the packed asset. Either way, the crate's `warehouse_id` and `stored_since` are cleared to null and the holding warehouse's `committed_cwt` is recomputed downward.

A **Drayage Shipment** is the receipt that prices material handling, and only a `WarehouseAgent` may create one. It names the destination `show_id`, the consignor `exhibitor_id`, a `channel` of `ADVANCE_WAREHOUSE` or `DIRECT_TO_SHOW`, an ordered and non-empty `crate_ids` list of the crates covered, the `received_at` instant at which the freight was tendered, and a receiving appointment expressed as `dock_window_start` and `dock_window_end` — a **half-open** interval whose end instant is not itself occupied. A `warehouse_id` is required when `channel` is `ADVANCE_WAREHOUSE` and forbidden when it is `DIRECT_TO_SHOW`. An optional `declared_value_coverage` flag, defaulting to false, records whether the exhibitor bought declared-value coverage; it is what later unlocks the declared-value settlement variant on a claim. Shipments are born `RECEIVED` with `hold_flag` false and `hold_reason` null, and every listed crate has its `shipment_id` set to the new shipment. Shipments can be listed and filtered by `show_id`, `exhibitor_id`, `warehouse_id` and `status`.

Three checks guard the receipt. No listed crate may have a `weight_lbs` greater than the `max_forklift_capacity_lbs` of the venue hosting the destination show, or the receipt is refused with `ERR_CRATE_WEIGHT_LIMIT_EXCEEDED`. Every listed crate's `exhibitor_id` must equal the shipment's own `exhibitor_id`, or it is refused with `ERR_CRATE_EXHIBITOR_MISMATCH`. And the receiving appointment must fit the dock: over the half-open interval from `dock_window_start` up to but not including `dock_window_end`, the sum of `billable_cwt` across this shipment and every existing shipment at the same warehouse whose `status` is `RECEIVED` or `IN_TRANSIT` and whose own half-open window intersects this one must not exceed the warehouse's `dock_capacity_cwt`; an overflow is refused with `ERR_DOCK_CAPACITY_EXCEEDED`. Because both windows are half-open, an existing appointment ending at exactly the instant the new one starts does not intersect it.

Pricing the receipt writes three fields. `gross_weight_lbs` is the exact sum of `weight_lbs` over every crate whose id appears in `crate_ids`, taken regardless of each crate's current `status`; crates sitting at the same warehouse but absent from the list never contribute a pound. `billable_cwt` is the greater of two and the gross weight in pounds divided by one hundred rounded up to a whole number — a two-hundredweight minimum applies to even the lightest shipment. The base rate is 9800 cents per hundredweight when `channel` is `ADVANCE_WAREHOUSE` and 11500 cents per hundredweight when it is `DIRECT_TO_SHOW`. Three independent surcharge fractions are then accumulated onto a running total that starts at zero: thirty percent is added when any crate in `crate_ids` has `crate_type` `LOOSE_UNCRATED`; twenty-five percent is added when the UTC hour of `received_at` is below 8 or is 16 or greater; and thirty-five percent is added when `channel` is `ADVANCE_WAREHOUSE` and `received_at` falls strictly after the show's `advance_warehouse_deadline`. Any subset of the three may hold at once. `drayage_charge_cents` is then `billable_cwt` multiplied by the base rate, multiplied by one plus the accumulated surcharge fraction, rounded half up to a whole cent. The surcharges are additive on the base and are never compounded: a loose, after-hours receipt carries a combined fraction of 0.55 and therefore a multiplier of 1.55, not the 1.625 that multiplying 1.30 by 1.25 would give.

The shipment's own lifecycle is derived from its crates and from the show. `RECEIVED → IN_TRANSIT` fires when the first crate of an `ADVANCE_WAREHOUSE` shipment leaves the warehouse for the floor, and bumps the shipment's `version`. `DELIVERED_TO_BOOTH` is reached when every crate on the shipment has reached `ON_SHOW_FLOOR` — from `IN_TRANSIT` for advance freight, and directly from `RECEIVED` for direct-to-show freight, which never passes through `IN_TRANSIT`. Reaching it recomputes no charge: `drayage_charge_cents` is frozen at receipt and never re-derived. `CLOSED`, the terminal status, is reached only as a cascade when the show advances into `MOVE_OUT`, and closing forces `hold_flag` to false and recomputes the posture of every booth of that exhibitor on that show.

Holds are the warehouse's lever over an exhibitor that has not settled its freight paperwork. Either a `WarehouseAgent` or `ShowOperations` may set or lift a shipment's `hold_flag`, optionally supplying a `reason` that is captured into `hold_reason` when the flag is raised. A raised hold drives every booth of that shipment's exhibitor on that shipment's show to recompute posture, which lands them on `RESTRICTED` with `posture_reason` `FREIGHT_HOLD` unless a freezing clause outranks it; lifting the hold recomputes them again.

### 3.7. Union Labor on the Show Floor

Every hour of work performed at a booth is dispatched through a **Labor Call**. An `Exhibitor` or `ShowOperations` requests one by naming the `booth_id` the crew will work, the `jurisdiction_id` of the craft supplying the crew, the requested `scheduled_start` and the exclusive `scheduled_end` of the window, and the `crew_size` — the number of workers wanted. Two optional inputs complete the request: `service_order_id`, linking the call to the service order it fulfils, and `self_install_requested`, defaulting to false, by which the exhibitor declares it intends to perform the work with its own personnel. On creation the call copies the jurisdiction's `trade` onto itself, and computes `scheduled_hours` as the difference between `scheduled_end` and `scheduled_start` expressed in hours to two decimal places. That figure is computed once and is never re-derived from `actual_start` or `actual_end`. The call is born `REQUESTED` with `actual_start`, `actual_end`, `billed_hours`, `st_hours`, `ot_hours`, `dt_hours` and `labor_charge_cents` all null. Calls may be listed and filtered by `booth_id`, `jurisdiction_id`, `service_order_id` and `status`.

Five checks guard the request, in the precedence order §2.9 fixes. Self-install is only honoured where the union permits it: when `self_install_requested` is true and the named jurisdiction's `exhibitor_self_install_allowed` is false, the request is refused with `ERR_UNION_JURISDICTION_REQUIRED`. The window must be well formed and inside the show envelope: `scheduled_start` must be strictly earlier than `scheduled_end`, and the whole interval must lie within the show's `move_in_start` through `move_out_end` inclusive, or the request is refused with `ERR_LABOR_WINDOW_OUTSIDE_SHOW`. The crew resource must be free, accounting for the jurisdiction's mandatory turnaround: considering the same `jurisdiction_id` and `booth_id` pair, and every existing call on that pair whose `status` is `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly before the existing call's `scheduled_end` extended forward by `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls strictly before the new `scheduled_end` extended forward by the same buffer. A gap exactly equal to the buffer is accepted. The craft must belong to the right building: the named jurisdiction's `venue_id` must equal the `venue_id` of the show reached from the booth, or the request is refused with `ERR_JURISDICTION_VENUE_MISMATCH`. And the crew must be a legal size: `crew_size` must be at least 1 and no greater than the jurisdiction's `crew_max_size`, or the request is refused with `ERR_CREW_SIZE_LIMIT`.

Dispatching the crew is the `LaborSupervisor`'s exclusive act and advances the call `REQUESTED → DISPATCHED`. It requires the booth's posture to be exactly `OPEN` — a booth that a previous no-show has driven to `RESTRICTED` cannot take a new crew, and is refused with `ERR_BOOTH_RESTRICTED` — and requires the show to be in `MOVE_IN`, `ON_SITE` or `MOVE_OUT`, or the request is refused with `ERR_SHOW_NOT_ACCEPTING`. Dispatch is the moment crew-hours become a commitment against the show.

`Show.committed_labor_hours` is a full recomputation over the show's calls: it sums, for every labor call reachable through a booth of this show whose `status` is `DISPATCHED` or `ON_SITE`, that call's `crew_size` multiplied by its `scheduled_hours`, with the final sum rounded half up to two decimal places. Calls still `REQUESTED` are not yet committed, and calls that have reached `COMPLETED`, `NO_SHOW` or `CANCELLED` are no longer committed. Every dispatch, check-in, completion and cancellation recomputes the figure, as does every cascade that cancels a call.

Check-in advances `DISPATCHED → ON_SITE` and records the supplied `actual_start`, which must fall within the show's `move_in_start` through `move_out_end` inclusive. Completion closes the call by naming an `outcome`, with `actual_end` supplied when the crew actually worked.

An `outcome` of `COMPLETED` advances `ON_SITE → COMPLETED` and requires `actual_end` to be strictly later than `actual_start`. Billing then runs. The elapsed time from `actual_start` to `actual_end` is taken in whole minutes; that minute count is divided by sixty and rounded **up** to the next half hour. `billed_hours` is the greater of the jurisdiction's `min_call_hours` and that rounded-up elapsed figure — a twenty-minute call under a four-hour minimum bills four hours.

Band allocation then walks the worked interval — from `actual_start` up to but not including `actual_end` — one minute at a time in chronological order. A minute counts as straight time when its time of day falls at or after the venue's `straight_time_start_hhmm` and strictly before its `straight_time_end_hhmm`; every other minute counts as overtime. There is one override: when `actual_start` falls on a Sunday in UTC, the entire call is double time, `st_hours` and `ot_hours` are both zero, and `dt_hours` equals `billed_hours`. The override is decided by `actual_start` alone, so a call that begins on a Saturday evening and ends on Sunday morning is not double time. Outside the Sunday case, `dt_hours` is zero.

Minimum-call padding is then assigned. The padding is `billed_hours` multiplied by sixty, minus the elapsed minutes actually worked. All of that padding goes to the band containing the **last worked minute** — the minute that begins one minute before `actual_end`. Padding is never split across the two bands and is never assigned to the band containing `actual_start`. `st_hours` is the straight-time minute count divided by sixty and `ot_hours` is the overtime minute count divided by sixty, both carried to two decimal places.

`labor_charge_cents` is then the `crew_size` multiplied by the sum of three band products: `st_hours` times the jurisdiction's `straight_time_rate_cents_per_hour`, plus `ot_hours` times that same rate times the jurisdiction's `overtime_multiplier`, plus `dt_hours` times that same rate times the jurisdiction's `doubletime_multiplier`. The crew multiplication and the three products are carried in exact arithmetic and the single final figure is rounded half up to a whole cent exactly once at the end — the opposite discipline from service order lines, which round before they sum. Completion also recomputes the show's committed crew-hours downward, since the call is no longer live.

An `outcome` of `NO_SHOW` advances `DISPATCHED → NO_SHOW` and takes a different billing path entirely. No interval exists, so bands, padding and the Sunday override are not consulted at all: `labor_charge_cents` is simply `crew_size` multiplied by the jurisdiction's `min_call_hours` multiplied by its `straight_time_rate_cents_per_hour`, rounded half up. The show's committed crew-hours are recomputed downward, and the booth recomputes posture, landing on `RESTRICTED` with `posture_reason` `LABOR_NO_SHOW` unless a freezing clause outranks it — which is why a no-show blocks the next dispatch at that booth until the situation is resolved.

Cancellation is available from `REQUESTED` and from `DISPATCHED`, either by explicit request from a `LaborSupervisor` or `ShowOperations` with an optional `reason`, or as a cascade when the call's service order enters `HELD` or `CANCELLED`. Either way the show's `cancelled_labor_call_count` increases by one and its `committed_labor_hours` are recomputed — which releases the crew-hours when the call had been `DISPATCHED` and changes nothing when it was merely `REQUESTED`, since a requested call never contributed. A cancelled call's `labor_charge_cents` stays null: nothing is billed. `COMPLETED`, `NO_SHOW` and `CANCELLED` are all terminal.

### 3.8. On the Floor: Change Orders and Lead Capture

Plans change on a show floor, and a **Change Order** is the controlled way to change one. An `Exhibitor` or `ShowOperations` raises one against a `booth_id`, declaring what is being changed through a polymorphic pair: `target_type` is `SERVICE_ORDER`, `LABOR_CALL` or `EXHIBIT_DESIGN`, and `target_id` names a row of the corresponding kind. The referenced row's own `booth_id` must equal the change order's `booth_id`, and a target that does not exist for its declared type, or that sits on a different booth, is refused with `ERR_CHANGE_TARGET_MISMATCH` — a check that runs both at creation and again at apply time. `delta_kind` classifies the change as `QTY_INCREASE`, `QTY_DECREASE`, `CREW_INCREASE` or `SCOPE_UPGRADE`; the optional `delta_qty` carries its magnitude, applied to the target's lowest-`line_seq` line for the two quantity kinds and to the target's `crew_size` for `CREW_INCREASE`. A mandatory `reason` captures the justification given on the floor. The change order is born `DRAFT`, with `created_by_user_id` taken from the acting `X-User-ID`, `reviewed_by_user_id` null and `price_delta_cents` null. Change orders may be listed and filtered by `booth_id`, `status` and `target_type`.

The review chain is deliberately slow. Submitting moves a change order from `DRAFT` or from `RETURNED` into `SUBMITTED`, requires the booth not to be `FROZEN`, and bumps the change order's `version`. `ShowOperations` then drives review by supplying a `decision` and an optional `note`. A change order resting in `UNDER_REVIEW` awaits exactly one of three outcomes, and no other status accepts a decision. A `decision` of `START_REVIEW` moves `SUBMITTED → UNDER_REVIEW` and records no reviewer identity yet — segregation of duties is enforced at the decision, not at the opening. A `decision` of `APPROVE` moves `UNDER_REVIEW → APPROVED`, requires the acting `X-User-ID` to differ from the change order's `created_by_user_id`, and records that operator as `reviewed_by_user_id`; the booth then recomputes posture and lands on `RESTRICTED` with `posture_reason` `CHANGE_ORDER_APPROVED` unless a freezing clause outranks it. A `decision` of `RETURN` moves `UNDER_REVIEW → RETURNED`, leaving `price_delta_cents` null and re-opening the submit cycle so the exhibitor can resubmit. A `decision` of `REJECT` moves `UNDER_REVIEW → REJECTED`, also requires the acting operator to differ from the creator, and recomputes the booth's posture — with the change order no longer `APPROVED`, that restricting clause stops holding. `REJECTED` and `APPLIED` are the terminal statuses.

Applying an approved change order is where the money moves. The request carries `expected_service_order_version` pinning the target order. Application requires the change order to be `APPROVED`, the target service order's `fulfillment_status` to be anything other than `DELIVERED` or `CANCELLED`, and the booth not to be `FROZEN`. On success the target order's lines are mutated according to `delta_kind` and `delta_qty`, and then the **entire** order is repriced — every line, through the same line-pricing and waterfall rules of §3.5 — but at the deadline tier in force at the moment of application, derived afresh from the logical clock rather than from the tier stored on the order. An order placed at `ADVANCE` and changed on the show floor therefore reprices every one of its lines at the `ONSITE` multiplier. `price_delta_cents` is recorded as the repriced `total_cents` minus the order's pre-change `total_cents`, and the target order's `version` increases by one.

Applying a change order is deliberately **not** credit checked. If the repricing pushes the exhibitor past its credit limit, that breach is caught by the booth-posture freeze the next time posture is computed, not by refusing the application. When the target order's `billing_status` was already `INVOICED`, application also starts the billing cascade: the order moves to `REBILL_PENDING`, the carrying invoice's `adjustments_cents` accumulates the `price_delta_cents`, the invoice's `total_cents` is recomputed, and the exhibitor's `account_balance_cents` is recomputed from scratch.

The floor's other on-site business is lead capture. An `Exhibitor` provisions a **Lead Capture Licence** against a `booth_id` by naming a `device_count` — the number of scanners licensed — and optionally `included_leads`, the number of leads bundled before overage billing begins, defaulting to 250. The licence is born `PROVISIONED` with an empty `ingested_badge_ids` array, `leads_ingested_count` at 0, `billable_overage_leads` at 0, `lead_overage_cents` at 0, and `license_total_cents` already computed. Licences provisioned for a booth can be listed under that booth.

Scanning is reported in batches: each batch carries a `badge_ids` array and the `captured_at` instant it was scanned. Batches are only accepted while the booth's show is `ON_SITE` or `MOVE_OUT` — otherwise `ERR_SHOW_NOT_ACCEPTING` — while the booth is not `FROZEN` — otherwise `ERR_BOOTH_FROZEN` — and while the licence itself is not `CLOSED`, a batch arriving after closure being refused with `ERR_LICENSE_CLOSED`. An empty `badge_ids` array is refused with `ERR_EMPTY_COLLECTION`. The first batch that accepts at least one badge id advances the licence `PROVISIONED → ACTIVE`.

Badge ids are deduplicated against `ingested_badge_ids`, which holds every badge id ever accepted on this licence in first-seen order. Ids from the request that are not already present are appended in request order; ids already present are silently skipped and raise no error, and duplicates within a single request body are collapsed with the first occurrence winning. `leads_ingested_count` is then the number of entries in `ingested_badge_ids`. `billable_overage_leads` is that count minus `included_leads`, floored at zero — a count exactly equal to `included_leads` yields zero overage. `lead_overage_cents` is `billable_overage_leads` multiplied by 150 cents per overage lead. `license_total_cents` is `device_count` multiplied by 32500 cents per device, plus `lead_overage_cents`. All four figures are exact integer cents with no rounding. When the show advances into `MOVE_OUT`, an `ACTIVE` licence moves to the terminal `CLOSED` and its `license_total_cents` is frozen at the figure it then holds; a licence still in `PROVISIONED` at that point remains `PROVISIONED` and only closes on the later `MOVE_OUT → CLOSED` show edge.

### 3.9. The Money Trail: Invoicing, Settlement and Claims

An **Invoice** sweeps a set of service orders into a single receivable. A `FinanceController` opens one by naming the `exhibitor_id` being billed, the `show_id` the charges belong to, and a non-empty `service_order_ids` array; an empty array is refused with `ERR_EMPTY_COLLECTION`. Every swept order must sit on a booth whose `exhibitor_id` and `show_id` match the invoice's own, or the request is refused with `ERR_INVOICE_SCOPE_MISMATCH`. The invoice is born `DRAFT` with `subtotal_cents` and `total_cents` computed, `adjustments_cents` at 0, `settled_cents` at 0, and both `issued_by_user_id` and `voided_by_user_id` null. `subtotal_cents` is the sum of `total_cents` across the listed orders as of issue time; `total_cents` is `subtotal_cents` plus `adjustments_cents`, where `adjustments_cents` is the running sum of applied change-order price deltas and refurbishment credits. Invoices may be listed and filtered by `exhibitor_id`, `show_id` and `status`.

Issuing moves the invoice `DRAFT → ISSUED`. Every listed service order must have a `billing_status` of `UNBILLED` or `REBILL_PENDING`, and the exhibitor's `status` must be `ACTIVE` — issuing against a `SUSPENDED` exhibitor is refused with `ERR_EXHIBITOR_SUSPENDED` and HTTP 402. On success `subtotal_cents` and `total_cents` are recomputed, `issued_by_user_id` is set from the acting `X-User-ID`, every listed order's `billing_status` becomes `INVOICED` with its `invoice_id` set, the exhibitor's `account_balance_cents` is recomputed, and every booth that exhibitor holds recomputes posture — which is how a large invoice can freeze an exhibitor's entire floor presence in one write. Re-issuing an already-`ISSUED` or `PARTIALLY_SETTLED` invoice after a change-order adjustment returns its `REBILL_PENDING` orders to `INVOICED` and moves no further money, because `total_cents` already reflects the adjustment.

Payments are applied by supplying an `amount_cents`, which must be strictly positive and must not drive `settled_cents` beyond `total_cents`; a non-positive or overshooting amount is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`. A payment that leaves a remainder moves the invoice from `ISSUED` to `PARTIALLY_SETTLED` and may be repeated; a payment that brings `settled_cents` to exactly `total_cents` moves the invoice to the terminal `SETTLED` and moves every listed order's `billing_status` to `SETTLED`. Every payment recomputes the exhibitor's `account_balance_cents` and re-evaluates the posture of every booth that exhibitor holds, which is how paying down a balance unfreezes a floor.

Voiding is available from `DRAFT` and from `ISSUED`, requires `settled_cents` to be exactly 0, and requires the acting `X-User-ID` to differ from the invoice's `issued_by_user_id`, a violation being refused with `ERR_SEGREGATION_OF_DUTIES`. The request carries a mandatory `reason`. On success the invoice moves to the terminal `VOID`, `voided_by_user_id` is recorded, every listed order's `billing_status` becomes `CREDITED` with its `invoice_id` cleared back to null, the exhibitor's balance is recomputed, and every booth of the exhibitor recomputes posture.

The exhibitor's `account_balance_cents` is a full recomputation from source rows on every occasion that touches it — invoice issue, payment, void, claim settlement, and the billing cascade of a change-order application. It is the sum of `total_cents` over that exhibitor's invoices whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of `settled_cents` over those same invoices, minus the sum of `settlement_cents` over that exhibitor's damage claims whose `status` is `SETTLED`. There is no time window: the aggregate covers the exhibitor's entire history. Invoices in `DRAFT`, `SETTLED` and `VOID` are excluded outright, which is exactly what makes issuing and then voiding a perfect round trip back to the pre-issue figure.

A **Damage Claim** is filed against exhibitor property by the `Exhibitor` itself or by a `ClaimsAdjuster`, naming the claimant `exhibitor_id`, the damaged or lost `asset_id`, the `claim_type` of `DAMAGE` or `LOSS`, the `declared_value_cents` the exhibitor asserts, and the `incident_at` instant at which the damage or loss occurred. Two optional references shape the settlement: `crate_id` names the crate whose weight forms the tariff basis, and `shipment_id` names the shipment whose `declared_value_coverage` gates the alternative settlement variant. When a `crate_id` is supplied, that crate must be packed with the claimed asset and the asset must belong to the claiming exhibitor, or the filing is refused with `ERR_CLAIM_REFERENCE_MISMATCH`. `declared_value_cents` may not exceed the asset's `list_value_cents`, or the filing is refused with `ERR_DECLARED_VALUE_EXCEEDS_ASSET`. Claims are born `FILED` with `coverage_basis` defaulting to `TARIFF_LIABILITY`, `settlement_cents` null, `appeal_count` at 0, `filed_by_user_id` taken from the acting `X-User-ID` and `adjudicated_by_user_id` null. Claims may be listed and filtered by `exhibitor_id`, `asset_id`, `crate_id`, `shipment_id` and `status`.

Opening the investigation moves the claim `FILED → UNDER_INVESTIGATION`, is refused when the asset has already been `RETIRED`, and bumps the claim's `version`. Adjudication follows, supplying a `decision` of `APPROVE` or `DENY`, an optional `coverage_basis` and an optional `note`. Either decision requires the acting `X-User-ID` to differ from the claim's `filed_by_user_id`, and either decision records that operator as `adjudicated_by_user_id`. A `DENY` moves the claim `UNDER_INVESTIGATION → DENIED` and leaves `settlement_cents` null. An `APPROVE` moves it `UNDER_INVESTIGATION → APPROVED`, requires the asset to be in neither `RETIRED` nor `WRITTEN_OFF`, and computes the settlement.

Two settlement variants exist. The **tariff liability** variant is the default and is the only one available when the cited shipment did not carry declared-value coverage. Its weight basis is the cited crate's `weight_lbs` when `crate_id` is non-null, and otherwise the asset's `shipping_weight_lbs`; weight is never summed across crates, only the single cited crate counts. `settlement_cents` is then the smallest of three figures: the claim's `declared_value_cents`; the weight basis multiplied by 30 cents per pound and rounded half up; and a flat per-claim ceiling of 5000000 cents. The weight cap bites hard — a 1250-pound crate caps liability at 37500 cents no matter how valuable the property inside it was.

The **declared value** variant is selected by supplying `coverage_basis` as `DECLARED_VALUE` at adjudication, and requires the claim to name a `shipment_id` whose shipment carries `declared_value_coverage` true; selecting it without such a shipment is refused with `ERR_COVERAGE_BASIS_UNAVAILABLE`. Under it, a depreciation fraction is read from the asset's `condition_grade`: grade `A` depreciates nothing, grade `B` depreciates ten percent, grade `C` twenty-five percent and grade `D` forty percent. The lesser of the claim's `declared_value_cents` and the asset's `list_value_cents` is multiplied by one minus that depreciation fraction and rounded half up; a flat deductible of 25000 cents is then subtracted from the rounded figure; and the result is floored at zero rather than being allowed to go negative. The deductible is subtracted after the rounding, never before it. For the same claim this variant can exceed the tariff figure by more than an order of magnitude, which is why coverage is worth buying.

Approval also cascades into the property itself. When `claim_type` is `DAMAGE`, the linked asset's `condition_grade` is downgraded by exactly one step along `A` to `B` to `C` to `D`, and a grade already at `D` stays at `D`. When `claim_type` is `LOSS`, the chain is longer: the linked asset transitions to the terminal `WRITTEN_OFF`, which sends every crate packed with that asset whose `status` is neither `LOST` nor `RELEASED_TO_CARRIER` to `LOST`, which in turn recomputes the `committed_cwt` of whichever warehouses were holding those crates; and every refurbishment work order on that asset still `OPEN` or `IN_PROGRESS` moves to `CANCELLED`.

A claim resting in `DENIED` is not the end of the road: it may be appealed by the `Exhibitor` or a `ClaimsAdjuster`, supplying a mandatory `note`. The appeal moves the claim `DENIED → UNDER_INVESTIGATION`, increases `appeal_count` by one, and clears `adjudicated_by_user_id` back to null so that the next adjudication re-runs the segregation-of-duties check against whoever filed. A claim may consume at most two appeals; a third is refused with `ERR_CLAIM_APPEAL_LIMIT`.

Settlement closes the loop. Moving an `APPROVED` claim to the terminal `SETTLED` requires `settlement_cents` to be non-null and recomputes the exhibitor's `account_balance_cents` downward by that amount. Every booth of that exhibitor then recomputes posture, and booths that were frozen solely by the credit-limit clause leave `FROZEN`; for each such booth, every service order sitting in `HELD` returns to `PENDING`. Labor calls that were cancelled on the way down are not resurrected.

## 4. Endpoint Definitions

The table below is a routing summary only: it lists each endpoint's method, path, purpose and authorised roles. It deliberately does not restate request bodies, response payloads or side effects — those are specified in the narratives of §2 and §3, and an implementer must read them there to reconstruct the full contract for any given call.

Status codes follow one rule throughout. An endpoint that brings a brand-new resource into existence responds 201 Created; every other successful call — state transitions, decisions, payments, movements, billing runs, list reads and single reads — responds 200 OK. Error responses use the status attached to the error identifier in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/venues` | Register a venue with its straight-time band, forklift limit and hanging-sign policy | `ShowOperations` |
| GET | `/venues/{id}` | Read one venue | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/venues/{id}/union-jurisdictions` | Declare a craft jurisdiction and its labor rules at this venue | `ShowOperations` |
| GET | `/venues/{id}/union-jurisdictions` | List the jurisdictions declared at a venue; reverse-reachability for UnionJurisdiction.venue_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/warehouses` | Register an advance warehouse with its storage rate, free-day allowance and dock capacity | `ShowOperations` |
| GET | `/warehouses/{id}` | Read one warehouse including its derived committed_cwt and current version | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/warehouses/{id}/storage-billing-runs` | Run between-show storage billing at a supplied as_of instant and stamp Crate.storage_charge_cents | `WarehouseAgent`, `FinanceController` |
| POST | `/shows` | Create a show with its full deadline calendar | `ShowOperations` |
| GET | `/shows/{id}` | Read one show including committed_labor_hours and cancelled_labor_call_count | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/shows` | List shows; reverse-reachability for Show.venue_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/shows/{id}/status` | Advance the show lifecycle; cascades to shipments, licences and booth postures | `ShowOperations` |
| POST | `/exhibitors` | Open an exhibitor account with a credit limit | `ShowOperations`, `FinanceController` |
| GET | `/exhibitors/{id}` | Read one exhibitor including the derived account_balance_cents | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/exhibitors/{id}/status` | Suspend or reinstate an exhibitor; suspension freezes every booth it holds | `FinanceController` |
| POST | `/booths` | Assign a booth space on a show floor to an exhibitor | `ShowOperations` |
| GET | `/booths/{id}` | Read one booth including its derived posture and posture_reason | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/booths` | List booths; reverse-reachability for Booth.show_id and Booth.exhibitor_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/exhibit-assets` | Register exhibitor-owned property that was not minted by a design release | `Exhibitor`, `ShowOperations` |
| GET | `/exhibit-assets/{id}` | Read one asset | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/exhibit-assets` | List assets; reverse-reachability for ExhibitAsset.exhibitor_id, current_warehouse_id and the self-referential derived_from_asset_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/exhibit-assets/{id}/lifecycle` | Move an asset through fabrication, storage, staging, the show floor and retirement | `ShowOperations`, `WarehouseAgent` |
| POST | `/exhibit-designs` | Open a design record for a booth, declaring geometry and the acquisition mode to be quoted | `Exhibitor` |
| GET | `/exhibit-designs/{id}` | Read one design including both quote variants and the breakeven reuse count | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/exhibit-designs` | List designs; reverse-reachability for ExhibitDesign.exhibitor_id, booth_id and asset_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/exhibit-designs/{id}/quote` | Price the design under both the rental and the purchase algorithm and select one | `Exhibitor` |
| POST | `/exhibit-designs/{id}/decision` | Approve a quoted design, send it back for revision, or cancel it | `ShowOperations` |
| POST | `/exhibit-designs/{id}/release` | Release an approved design to fabrication, minting the physical asset | `ShowOperations` |
| POST | `/service-orders` | Order a show service against a booth; tiers, prices and credit-checks the order in one call | `Exhibitor`, `ShowOperations` |
| GET | `/service-orders/{id}` | Read one service order with both status dimensions and the full price breakdown | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/service-orders` | List service orders; reverse-reachability for ServiceOrder.booth_id and invoice_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/service-orders/{id}/lines` | List the immutable priced lines of an order; reverse-reachability for ServiceOrderLine.service_order_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/service-orders/{id}/fulfillment` | Advance or cancel the operational dimension of a service order | `ShowOperations`, `Exhibitor` |
| POST | `/crates` | Register a crate of exhibitor freight | `Exhibitor`, `WarehouseAgent` |
| GET | `/crates/{id}` | Read one crate including its storage charge and storage clock | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/crates` | List crates; reverse-reachability for Crate.exhibitor_id, asset_id, warehouse_id and shipment_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/crates/{id}/warehouse-check-in` | Check a crate into an advance warehouse against the warehouse version the client last observed | `WarehouseAgent` |
| POST | `/crates/{id}/movements` | Move a crate along its location lifecycle, including declaring it lost | `WarehouseAgent`, `ShowOperations` |
| POST | `/drayage-shipments` | Receive freight through the advance warehouse or direct to show and price the material handling | `WarehouseAgent` |
| GET | `/drayage-shipments/{id}` | Read one shipment including its billable weight and charge | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/drayage-shipments` | List shipments; reverse-reachability for DrayageShipment.show_id, exhibitor_id and warehouse_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/drayage-shipments/{id}/hold` | Place or lift an operational hold on a shipment, which restricts the exhibitor's booths on that show | `WarehouseAgent`, `ShowOperations` |
| POST | `/labor-calls` | Request a union crew for a booth under a named jurisdiction and time window | `Exhibitor`, `ShowOperations` |
| GET | `/labor-calls/{id}` | Read one labor call including its band split and charge | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/labor-calls` | List labor calls; reverse-reachability for LaborCall.booth_id, jurisdiction_id and service_order_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/labor-calls/{id}/dispatch` | Dispatch the crew, committing the scheduled crew-hours to the show | `LaborSupervisor` |
| POST | `/labor-calls/{id}/check-in` | Record the crew arriving on the floor | `LaborSupervisor` |
| POST | `/labor-calls/{id}/completion` | Close a call as worked or as a no-show and bill the hours | `LaborSupervisor` |
| POST | `/labor-calls/{id}/cancel` | Cancel a requested or dispatched call | `LaborSupervisor`, `ShowOperations` |
| POST | `/change-orders` | Raise an on-site change against a service order, labor call or design | `Exhibitor`, `ShowOperations` |
| GET | `/change-orders/{id}` | Read one change order including its applied price delta | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/change-orders` | List change orders; reverse-reachability for ChangeOrder.booth_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/change-orders/{id}/submit` | Submit a draft or returned change order for review | `Exhibitor`, `ShowOperations` |
| POST | `/change-orders/{id}/review` | Open review, approve, return or reject a change order under segregation of duties | `ShowOperations` |
| POST | `/change-orders/{id}/apply` | Apply an approved change to its target, repricing at the deadline tier in force right now | `ShowOperations` |
| POST | `/invoices` | Open a draft invoice sweeping a set of service orders for one exhibitor and show | `FinanceController` |
| GET | `/invoices/{id}` | Read one invoice including adjustments and settled amount | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/invoices` | List invoices; reverse-reachability for Invoice.exhibitor_id and show_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/invoices/{id}/issue` | Issue a draft invoice, moving its orders to INVOICED and its total onto the exhibitor balance | `FinanceController` |
| POST | `/invoices/{id}/payments` | Apply a payment against an issued invoice | `FinanceController` |
| POST | `/invoices/{id}/void` | Void an unsettled invoice under segregation of duties, restoring the exhibitor balance exactly | `FinanceController` |
| POST | `/damage-claims` | File a damage or loss claim against exhibitor property | `Exhibitor`, `ClaimsAdjuster` |
| GET | `/damage-claims/{id}` | Read one claim including its settlement figure and coverage basis | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/damage-claims` | List claims; reverse-reachability for DamageClaim.exhibitor_id, asset_id, crate_id and shipment_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/damage-claims/{id}/investigation` | Open the investigation on a filed claim | `ClaimsAdjuster` |
| POST | `/damage-claims/{id}/adjudication` | Approve or deny a claim under segregation of duties, selecting the settlement variant | `ClaimsAdjuster` |
| POST | `/damage-claims/{id}/appeal` | Appeal a denied claim back into investigation | `Exhibitor`, `ClaimsAdjuster` |
| POST | `/damage-claims/{id}/settlement` | Settle an approved claim, crediting the exhibitor account | `ClaimsAdjuster`, `FinanceController` |
| POST | `/refurb-work-orders` | Open a between-shows refurbishment work order against stored property | `WarehouseAgent`, `ShowOperations` |
| GET | `/refurb-work-orders/{id}` | Read one refurbishment work order including its variance | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| GET | `/refurb-work-orders` | List refurbishment work orders; reverse-reachability for RefurbWorkOrder.asset_id and warehouse_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/refurb-work-orders/{id}/progress` | Start, complete or cancel a refurbishment, moving the asset in and out of IN_REFURB | `WarehouseAgent` |
| POST | `/lead-capture-licenses` | Provision lead-capture scanners for a booth | `Exhibitor` |
| GET | `/booths/{id}/lead-capture-licenses` | List the licences provisioned for a booth; reverse-reachability for LeadCaptureLicense.booth_id | `ShowOperations`, `Exhibitor`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `FinanceController` |
| POST | `/lead-capture-licenses/{id}/lead-batches` | Ingest a batch of scanned badge ids, deduplicated against everything seen before | `Exhibitor` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. | `ShowOperations`, `FinanceController`, `WarehouseAgent`, `LaborSupervisor`, `ClaimsAdjuster`, `Exhibitor` |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in `data.error_id`, with the HTTP status shown. Trigger conditions are not repeated here; each one is stated in the §2 principle or §3 workflow that the check guards, and §2.9 fixes the order in which competing checks are evaluated.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 |
| `ERR_SHOW_NOT_FOUND` | 404 |
| `ERR_EXHIBITOR_NOT_FOUND` | 404 |
| `ERR_BOOTH_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_DESIGN_NOT_FOUND` | 404 |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 |
| `ERR_CRATE_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_LABOR_CALL_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_REFURB_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_ENTITY_TERMINAL` | 409 |
| `ERR_STALE_BOOTH_VERSION` | 412 |
| `ERR_STALE_SERVICE_ORDER_VERSION` | 412 |
| `ERR_STALE_WAREHOUSE_VERSION` | 412 |
| `ERR_SHOW_NOT_ACCEPTING` | 409 |
| `ERR_BOOTH_FROZEN` | 409 |
| `ERR_BOOTH_RESTRICTED` | 409 |
| `ERR_UNION_JURISDICTION_REQUIRED` | 422 |
| `ERR_HANGING_SIGN_NOT_PERMITTED` | 422 |
| `ERR_CRATE_WEIGHT_LIMIT_EXCEEDED` | 422 |
| `ERR_LABOR_WINDOW_OUTSIDE_SHOW` | 422 |
| `ERR_LABOR_CALL_OVERLAP` | 409 |
| `ERR_BOOTH_WINDOW_CONFLICT` | 409 |
| `ERR_DOCK_CAPACITY_EXCEEDED` | 409 |
| `ERR_JURISDICTION_VENUE_MISMATCH` | 422 |
| `ERR_CRATE_EXHIBITOR_MISMATCH` | 422 |
| `ERR_CHANGE_TARGET_MISMATCH` | 422 |
| `ERR_INVOICE_SCOPE_MISMATCH` | 422 |
| `ERR_CLAIM_REFERENCE_MISMATCH` | 422 |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 |
| `ERR_CREW_SIZE_LIMIT` | 422 |
| `ERR_EMPTY_COLLECTION` | 422 |
| `ERR_INVALID_LINE_SEQUENCE` | 422 |
| `ERR_DUPLICATE_BOOTH_NUMBER` | 409 |
| `ERR_DESIGN_REVISION_LIMIT` | 409 |
| `ERR_CLAIM_APPEAL_LIMIT` | 409 |
| `ERR_REFURB_OVERRUN_UNAPPROVED` | 422 |
| `ERR_CONDITION_GRADE_REGRESSION` | 422 |
| `ERR_LICENSE_CLOSED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_DECLARED_VALUE_EXCEEDS_ASSET` | 422 |
| `ERR_COVERAGE_BASIS_UNAVAILABLE` | 422 |
| `ERR_EXHIBITOR_SUSPENDED` | 402 |
