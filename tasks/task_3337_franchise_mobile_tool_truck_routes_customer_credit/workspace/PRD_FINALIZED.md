# Franchise Tool Truck Credit API — Product Requirements Document

## 1. Introduction

A mobile tool truck is a route business carried on wheels: a franchisee drives a truck along a
territory list of repair shops on a fixed weekly cycle, sells hand tools to the technicians who work
at those shops, extends them credit on the spot, and collects a weekly payment when the truck
returns. Everything valuable in this business is a consequence of that cadence — the day of the week
the truck visits a shop determines when a payment is expected, which franchisee carries the risk of a
defaulting technician, and how quickly a delinquent account ages into a charge-off. The franchise
model adds a second layer: the franchisee invests in truck inventory and replenishment, the
franchisor adjudicates the credit it finances, and territories are developed, qualified, surrendered
and resold as the network grows or contracts.

This document specifies the REST interface for the franchise tool-truck network. It covers route and
territory management, shop and technician records, credit applications and their adjudication by
either the franchisee or the franchisor, revolving and lease receivable accounts with weekly
finance-charge accrual, the weekly collection run with its booking, collection, miss and reversal
outcomes, sales orders written against truck stock, warranty claims priced and adjudicated at the
truck, replenishment orders filled against an investment ceiling, share pledges that let an account
underwrite a portion of a replenishment order, launch allocation of a new product across in-service
routes, and territory resale with its reopening fee. Every monetary quantity in the system is carried
as a whole number of cents.

The system is designed for correctness under adversarial conditions. Two operators may hold different
views of the same document, a route may be suspended mid-week while its shops still owe money, a
technician may change shops or leave the trade entirely with a live balance, and a warranty claim may
be approved and later reopened. The interface therefore pins optimistic concurrency on the small set
of writes where a superseded view would be genuinely ambiguous, pins the evaluation order of every
formula whose rounding order is observable, and pins each rejection to a named error identifier so
that a caller can always tell why a write was refused.

Three modelling choices shape the rest of this document. First, nothing in the system reads the host
clock: all temporal behaviour is driven by a single logical clock whose startup value is exactly
`2026-09-01T00:00:00Z`, so a weekly cadence, a delinquency anniversary and a charge-off window are all
reproducible. Second, every account carries its recourse model as a frozen fact rather than a live
lookup, so a territory can be surrendered without rewriting the risk behind money already lent.
Third, every quantity that a client can observe is recomputed on the write that changes it, so a
route's exposure, a technician's available line and a franchisee's outstanding book are never stale
by design.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply to the entire API. The service is mounted under the top-level path
segment `/retail`; every endpoint path in Section 4 carries that prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role`
names that principal's operational capacity. A request that omits either header, or that names a role
the service does not recognise, is rejected with `ERR_MISSING_USER_CONTEXT` and HTTP status 400. A
request whose role is not permitted for the operation it attempts — or whose entity-backed actor does
not own the resource it is mutating — is rejected with `ERR_UNAUTHORIZED` and HTTP status 403.

The service recognises exactly seven role names, spelled as follows: `PlatformAdmin`,
`FranchiseOwner`, `FranchiseManager`, `CreditOfficer`, `RouteSalesRep`, `WarrantyAdmin`, and
`Technician`.

`PlatformAdmin` is an opaque operator role: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an
opaque operator identifier not tied to any persisted entity. The server may record it but does not
compare it to any entity's `id`. This role owns the logical clock and the product catalogue and
performs no business mutation of routes, accounts or orders. `FranchiseManager`, `CreditOfficer` and
`WarrantyAdmin` are likewise opaque operator roles: when `X-User-Role` is one of those three,
`X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not
compare it to any entity's `id`.

`FranchiseOwner` is an entity-backed role. When `X-User-Role` is `FranchiseOwner`, `X-User-ID` is the
`id` of the acting `Franchisee`; ownership checks on any resource that references a `Franchisee`
compare the resource's foreign-key field to `X-User-ID`. In practice the routes, shops, technicians,
replenishment orders, inventory positions and resale filings a `FranchiseOwner` mutates must belong to
that franchisee. `RouteSalesRep` is also entity-backed to `Franchisee`. When `X-User-Role` is
`RouteSalesRep`, `X-User-ID` is the `id` of the acting `Franchisee`; the sales representative may only
create, edit and advance sales orders on that franchisee's own routes, book and collect payments on
the credit accounts of technicians whose home route belongs to that franchisee, and file warranty
claims against that franchisee's orders. `Technician` is entity-backed to the `Technician` entity
itself. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`;
ownership checks on a credit account compare the account's `technician_id` to `X-User-ID`, and the
role is entirely read-only — a `Technician` may read its own accounts, its own payment history and its
own orders but mutates nothing.

Role exclusivity is enforced per operation. `PlatformAdmin` alone may set the logical clock and create
or update products. `FranchiseOwner` alone may enrol, certify or recertify a franchisee, create a
route, update route attributes, create a shop, onboard or update a technician, create a replenishment
order or an inventory position, file a territory resale and open a development round. `FranchiseManager`
alone adjudicates route suspension, reinstatement and retirement, territory surrender, resale
decisions, charge-off settlement and closure, the marking of a booking as missed or cancelled, the
recording of a trade exit, and the shipping, allocation or cancellation of a replenishment order.
`CreditOfficer` alone reviews and decides franchisor-sourced applications, mints credit accounts and
reverses a collected payment. `WarrantyAdmin` alone approves, rejects or reopens a warranty claim.
`RouteSalesRep` alone creates and edits sales orders, advances them through confirmation, delivery,
settlement and cancellation, books a payment, collects a payment and files a warranty claim. Read
access is broader: most role lists in Section 4 include the read endpoints a role legitimately needs,
and a role absent from an endpoint's authorised list is refused with `ERR_UNAUTHORIZED`.

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

List endpoints accept a `limit` and an `offset` query parameter. The `limit` parameter caps how many
items are returned; it defaults to 10, its minimum is 1 and its maximum is 100. The `offset`
parameter counts how many items to skip from the front of the result and defaults to 0. When a caller
supplies a `limit` below 1 or above 100, or a non-integer value for either parameter, the request is
refused with `ERR_INVALID_REQUEST` and HTTP status 400.

Unless a narrative in Section 3 states otherwise, list endpoints return resources ordered by
`created_at` ascending. The `meta` object of a list response carries the four pagination fields
`limit`, `offset`, `total_count` and `has_more`.

### 2.4. The Logical Clock and the Weekly Cadence

The service does not read wall-clock time for business purposes. It reads a logical clock that a
`PlatformAdmin` may set through the clock capability, supplying a `current_utc` instant; the response
carries both the accepted `current_utc` and the `current_week_start` it implies. The startup default
of the logical clock is exactly `2026-09-01T00:00:00Z`: before any clock call the service reads that
instant and never falls back to the host's wall clock. Attempting to set the clock to an instant
earlier than the current logical clock is rejected with `ERR_WEEK_CLOCK_BEHIND` and HTTP status 422 —
the clock may only move forward.

Weeks in this system are anchored to Monday. A week's start is the Monday `00:00:00Z` of the week in
which an instant falls, and every week-valued field in the domain — `accrual_iso_week`,
`effective_iso_week`, `filed_iso_week`, `resolved_iso_week`, `in_force_from_week`, `in_force_to_week`,
`expected_week_start`, `last_payment_week_start`, `sale_iso_week`, `launch_iso_week` and
`charge_resolved_iso_week` — carries a Monday `00:00:00Z` value, not an arbitrary instant. Every
week-valued field is serialised at second resolution, so a Monday week start is rendered
`2026-09-07T00:00:00Z` with no fractional digits, and that same second-resolution form is used for the
route's `schedule_anchor_utc`, for the `current_utc` and `current_week_start` the clock capability
returns, and for the instants stamped straight from the logical clock onto `account_status_changed_at`
and `certified_on`; only `created_at`, `updated_at` and `api_request_timestamp` carry the three
fractional digits described in Sections 2.2 and 2.5. Setting the clock is not a pure read: evaluating
the clock also runs the charge-off sweep over every non-closed account, so an account whose
delinquency anniversary has been reached flips to `CHARGED_OFF` on that request rather than on some
later one.

Weekly cadence reaches further than the clock. A route carries a `visit_weekday` between 1 and 7 where
1 is Monday and 7 is Sunday, and every credit account minted on that route inherits it as its
`payment_due_weekday`, which is the day of the week a truck collection is expected. A payment's
`expected_week_start` must itself be a Monday `00:00:00Z` and must not precede the logical clock's
current week; a payment booked with a non-Monday or a past week is rejected with
`ERR_PAYMENT_WEEK_IN_PAST` and HTTP status 422.

### 2.5. Common Resource Properties

All fifteen resource types in this API — `Franchisee`, `Route`, `ShopLocation`, `Technician`,
`CreditApplication`, `CreditAccount`, `FinanceCharge`, `Payment`, `SalesOrder`, `WarrantyClaim`,
`Product`, `InventoryPosition`, `ProductOrder`, `SharePledge` and `LaunchAllocation` — carry the same
four system-managed fields. Every one of them declares `common_fields: true`, so none of the four is
absent on any resource.

- The `id` field is a server-minted UUID string with no type prefix and no embedded entity name.
- The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, for example
  `2025-05-24T10:30:00.123Z`, stamped when the row is first written.
- The `updated_at` field is an ISO 8601 UTC timestamp with three fractional digits, refreshed on
  every mutation of the row, including mutations of the row's derived fields.
- The `version` field is an integer that starts at 1 and increments by exactly 1 on every modification
  to the resource.

Derived fields are not exceptions to this rule. When the service recomputes a derived attribute — a
route's `inventory_at_risk_cents`, a franchisee's `outstanding_credit_cents`, an account's
`current_balance_cents`, an order's `gross_total_cents` — it bumps the owning row's `updated_at` and
increments its `version` exactly as if a client had written the row directly. The sweep and accrual
work performed while evaluating the clock is subject to the same rule.

### 2.6. Nested Resource Retrieval and Validation Order

Requests that target nested resources carry several identifiers in one path, and the service applies
them left to right: the parent is resolved before the child. A path naming a route under a franchisee
resolves the franchisee first, then the route, and a route that exists but belongs to a different
franchisee is treated exactly as a missing route. The rejection for a missing path resource is an HTTP
status 404 whose identifier names the failing entity: `ERR_FRANCHISEE_NOT_FOUND`,
`ERR_ROUTE_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
`ERR_APPLICATION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
`ERR_CLAIM_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_ORDER_NOT_FOUND`, and
`ERR_INVENTORY_POSITION_NOT_FOUND`. A child identifier that is syntactically present but does not
belong to the parent named ahead of it in the same path — a payment that is not on the named account,
a claim that is not on the named order — is reported with the same 404 identifier as a wholly absent
row.

An identifier carried in the request body rather than the path is resolved after every path
identifier has been resolved. When a body references a product or an account, a missing target is
reported as `ERR_PRODUCT_NOT_FOUND` or `ERR_ACCOUNT_NOT_FOUND` respectively, and only after the path
has been validated. Two nested child identifiers are addressed directly in their own right: the
`paymentId` that names one payment on a credit account, and the `claimId` that names one warranty
claim on a sales order. Both are resolved under the parent named ahead of them, and a child whose
identifier resolves to a row belonging to a different parent is treated as absent.

Beyond existence, the service evaluates requests under a fixed priority order. The lowest-numbered
rule that fails is the one reported, so a caller never sees a downstream error in place of an upstream
one. Malformed requests come first: a body that omits a required field, supplies the wrong type,
carries an enum member outside the declared set, or places a numeric field outside its stated range is
rejected with `ERR_INVALID_REQUEST` and HTTP status 400. A resource whose current state has no
transition for the requested trigger is rejected with `ERR_INVALID_STATE` and HTTP status 409, before
any business rule is consulted. Only once these are satisfied are the domain rules in Section 3
evaluated, in the priority order stated there.

### 2.7. Money, Rounding and Precision

Money is never a floating-point quantity in this API. Every monetary field — `unit_cost_cents`,
`retail_price_cents`, `requested_limit_cents`, `approved_limit_cents`, `credit_limit_cents`,
`credit_line_limit_cents`, `credit_ceiling_cents`, `inventory_invested_cents`,
`investment_ceiling_cents`, `requested_cost_cents`, `ordered_cost_cents`, `gross_total_cents`,
`financed_principal_cents`, `current_balance_cents`, `principal_balance_cents`,
`accrued_finance_charge_cents`, `charge_amount_cents`, `collection_applied_cents`,
`charge_applied_cents`, `principal_allocated_cents`, `replacement_charge_cents`,
`warranty_credit_amount_cents`, `sustained_amount_cents`, `reopening_fee_cents`,
`installment_due_cents`, `minimum_payment_due_cents`, `amount_cents`, `allocated_amount_cents`,
`inventory_at_risk_cents`, `over_pledge_cents`, `outstanding_credit_cents`,
`recourse_exposure_cents`, `franchisee_capital_at_risk_cents` and `credit_available_cents` — is a
whole number of cents carried exactly, regardless of the precision of the rate that produced it.

Where a rate is applied, the rounding method is round half up and the rounding point is stated with
the rule. Rounding is applied once, at the point named in the rule, and never re-applied to an
already-rounded intermediate. Two rules deserve emphasis here because their rounding order is
observable in the returned cents. The order gross total rounds each line's extended amount
independently and then sums the rounded line amounts, so a caller can distinguish it from the
prohibited variant that sums first and rounds once. The finance-charge accrual rounds once at the end
of its formula, after the rate has been applied to the full basis. The lease amortisation rounds the
monthly installment once and then multiplies, with the closing installment absorbing the residue so
that the schedule sums exactly. Unless a rule says otherwise, an intermediate value is not rounded and
the final monetary result is an exact integer number of cents.

Two ceiling constants guard the money rules of this system. `CREDIT_ABSOLUTE_CAP_CENTS` is the hard
ceiling on a requested revolving or lease limit and is fixed at 2000000 cents. The second,
`FRANCHISEE_RESALE_FEE_CAP_CENTS`, is the ceiling above which a pending resale filing may not be
approved, and is fixed at 900000 cents. Both are compared against exact integer cents, and each
guards a rule stated in Section 3.

Ten of the derived quantities in this system carry a named rule whose rounding point or evaluation
order is pinned and observable: the order gross total, the order financing variant, the finance-charge
accrual, the credit decision score, the credit decision limit, the route replenishment allocation, the
mixed-inventory plan, the launch allocation plan, the warranty replacement charge and the warranty
principal allocation. Nine further rules are aggregations, selectors or temporal-window derivations
with no rounding step of their own: the recourse-holder resolution, the payment allocation, the
minimum payment due, the lease amortisation, the charge-off week, the route schedule anchor, the
inventory over-pledge aggregate, the reopening fee and the franchisee training progress. Each of the
nineteen is stated in full — with its inputs, its constants and its rounding — in the cross-cutting
subsection that owns it or in Section 3.

### 2.8. Optimistic Concurrency Control on Contended Writes

Five write operations require the client to assert the version of the parent document it last read.
Each takes a non-optional body field carrying that assertion, and each rejects the write with
`ERR_STALE_VERSION` and HTTP status 412 when the assertion disagrees with the parent's current
`version`. The rejections are framed strictly as stale-view protection: a client holding a superseded
view of the parent is refused, regardless of any other request in flight.

Minting a `CreditAccount` against a `CreditApplication` requires `expected_application_version`
matching the application's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP
status 412. Confirming a `SalesOrder` requires `expected_sales_order_version` matching the order's
current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412. Creating a
`SharePledge` against a `ProductOrder` requires `expected_product_order_version` matching that order's
current `version`, and receiving the same `ProductOrder` also requires
`expected_product_order_version` matching its current `version`; either mismatch is rejected with
`ERR_STALE_VERSION` and HTTP status 412. Retiring a `Route` requires `expected_route_version` matching
the route's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412.

No other endpoint in this API accepts a version field, and the endpoints named above accept no
alternative spelling. A route's ordinary lifecycle actions other than retirement, a
`ProductOrder`'s submit, ship, allocate and cancel actions, and a `SalesOrder`'s deliver, settle and
cancel actions are all guarded by their state preconditions rather than by a version assertion, and a
client that supplies a version field to them is refused with `ERR_INVALID_REQUEST`.

### 2.9. Unique Keys and Protected Fields

Four uniqueness invariants are enforced across the network. A `route_code` is globally unique across
every route, so a create or update that reuses one is rejected with `ERR_ROUTE_CODE_DUPLICATE`. A
`sku` is globally unique across every product, so a create that reuses one is rejected with
`ERR_SKU_DUPLICATE`. A route holds at most one inventory position per product, so a second position
for the same product on the same route is rejected with `ERR_INVENTORY_POSITION_DUPLICATE`; a route
that holds no position for a product at all reports `ERR_INVENTORY_POSITION_NOT_FOUND`. A
territory-level product mix is unique per franchisee. Any of these four collisions may also be
reported under the general identifier `ERR_UNIQUENESS_VIOLATION`, which carries HTTP status 409.

Several fields are protected rather than freely writable. A product's `launch_status` moves from
`ANNOUNCED` to `ALLOCATED` to `LIVE` under launch-planning control and is never accepted from a client
body. An inventory position's `unit_cost_cents` is frozen from the product's cost at the moment the
position is created and is not revisable afterwards, even when the product's own cost later changes.
An account's `recourse_holder` is frozen at minting, and neither a shop change nor a territory
surrender recomputes it. A franchisee's `certified_on` is stamped by the certification transition
itself and is cleared, not edited, by a recertification.

Empty line collections are refused everywhere a line collection is meaningful. A sales order created
or edited with an empty `lines` array, and a replenishment order submitted with empty
`requested_lines`, are rejected with `ERR_EMPTY_MIX_LINES` and HTTP status 422; a claim whose
`line_index` falls outside the parent order's `lines` array is rejected with
`ERR_WARRANTY_LINE_OUT_OF_RANGE`, also at HTTP status 422. A non-terminal warranty claim already
standing against the same order and the same `line_index` blocks a second filing with
`ERR_WARRANTY_ALREADY_CLAIMED` and HTTP status 409. A franchisee whose training points fall below the
certification threshold cannot be certified, and the attempt is refused with
`ERR_CERTIFICATION_POINTS_SHORT` at HTTP status 422. A credit application that asks for more than
`CREDIT_ABSOLUTE_CAP_CENTS` is refused outright with `ERR_CREDIT_REQUEST_ABOVE_CAP` at HTTP status 402,
before any scoring runs.

### 2.10. Franchisee Standing, Certification and Territory Qualification

A franchisee's `training_status` is one of `NOT_ENROLLED`, `ENROLLED` or `CERTIFIED`, and it is set
from the training points reported on the call that moves it. Reporting at least 40 `training_points`
certifies the franchisee, and reporting fewer leaves it `ENROLLED`; the boundary is inclusive on the
high side, so exactly 40 points certifies and 39 points does not. The scalar expression is direct:
the resulting training status produced by the rule `franchisee_training_progress` is `CERTIFIED` when
the franchisee's training points are greater than or equal to 40, and `ENROLLED` otherwise. A certification request whose points are below the threshold is
refused with `ERR_CERTIFICATION_POINTS_SHORT` and HTTP status 422 rather than silently enrolling the
franchisee. `can_resell_territory` is a derived boolean that is true exactly when `training_status` is
`CERTIFIED` and false otherwise, and it is recomputed on every training transition and on every
transition that clears `certified_on`.

Certification gates three things and each refusal carries `ERR_FRANCHISEE_NOT_CERTIFIED` at HTTP
status 409: activating a route requires that the owning franchisee be `CERTIFIED`, filing a resale
requires that the selling franchisee be `CERTIFIED`, and a development round that would qualify a
territory requires that the owning franchisee be `CERTIFIED`. The rule is stated identically on route
activation, on resale filing and on development, so an uncertified franchisee cannot move any of the
three forward.

Franchisee-level roll-ups are recomputed whenever their inputs move. `total_route_count` counts every
route owned by the franchisee regardless of `route_status`; `active_route_count` counts only routes
whose `route_status` is `IN_SERVICE`; `credit_ceiling_cents` sums `credit_limit_cents` over the
franchisee's credit accounts whose `account_status` is `ACTIVE` or `DELINQUENT`;
`outstanding_credit_cents` sums `current_balance_cents` over those same `ACTIVE` and `DELINQUENT`
accounts; `recourse_exposure_cents` sums `current_balance_cents` over the franchisee's accounts whose
`recourse_holder` is `FRANCHISEE` and whose `account_status` is `ACTIVE`, `DELINQUENT` or
`CHARGED_OFF`. `franchisee_capital_at_risk_cents` is `outstanding_credit_cents` minus
`recourse_exposure_cents`, and it is zero whenever every open account is franchisor-recourse.

The franchisee also carries a deterministic collection fallback. `fallback_shop_location_id` points at
the `ShopLocation` with `shop_status` equal to `ACTIVE` on one of the franchisee's routes that was
created earliest, and it is null when the franchisee has no such shop. A franchisor-draft collection
that needs the fallback but finds none is refused with `ERR_FALLBACK_LOCATION_MISSING` and HTTP status
422. The franchisor's draft eligibility summary for a franchisee reports the resolved fallback
together with the franchisee's `franchisee_id`, its `active_account_count` and its
`recourse_exposure_cents`, and that summary is the read a franchisor runs before drafting; when the
franchisee has no `ACTIVE` shop on any route the summary is refused with the same
`ERR_FALLBACK_LOCATION_MISSING` identifier at HTTP status 422 rather than returning a null fallback.

Territory development is scored on the route itself. `territory_points` is the development score a
route has earned toward qualification, and a round qualifies when the route's `territory_points`
reach at least 60 while the route's `route_status` is `IN_SERVICE`. The boundary is inclusive: 60
points qualifies and 59 does not. Any operation that requires a `QUALIFIED` territory — resale filing
`ERR_TERRITORY_NOT_QUALIFIED` at HTTP status 409 when the territory is in any other development
status. Territory windows on one route may not overlap: opening a development round while an earlier
round on the same route is still in force, meaning its `in_force_to_week` is still null, is rejected
with `ERR_TERRITORY_WINDOW_CONFLICT`. The stated HTTP status for that rejection is 422 with the
identifier `ERR_TERRITORY_WINDOW_CONFLICT`.

### 2.11. Resale Pricing and the Buyer's Training Discount

A resale filing is priced by the reopening fee computed under the rule `reopening_fee`, and the fee is
a step function keyed first on the
prospective buyer's training state and then on the buyer's accumulated points. The base amount is
`FEE_NOT_ENROLLED` (900000 cents) when the route's `resale_buyer_training_status` is `NOT_ENROLLED`,
`FEE_ENROLLED` (650000 cents) when it is `ENROLLED`, and `FEE_CERTIFIED` (250000 cents) when it is
`CERTIFIED`. A points discount is then computed as the number of whole discount units the buyer has
earned, where each unit is `POINTS_PER_DISCOUNT_UNIT` (10 points) capped at `POINTS_CAP` (60 points),
multiplied by `DISCOUNT_PER_UNIT_CENTS` (15000 cents). The reopening fee is the base amount minus the
points discount, floored at `FEE_FLOOR_CENTS` (200000 cents). The unit count is a floor: exactly 10
points earns exactly one discount unit and 9 points earns none. The points discount applies to
`ENROLLED` and `NOT_ENROLLED` buyers only — a `CERTIFIED` buyer pays `FEE_CERTIFIED` flat. Two
consequences are worth stating plainly. A buyer with 60 points takes the full 6 units, or 90000 cents,
off the base. A buyer with 61 points takes no more, because the point count is capped at 60 before the
unit count is taken.

The cap constrains the decision rather than the pricing: a pending resale may be approved only while
the freshly computed `reopening_fee_cents` is less than or equal to `FRANCHISEE_RESALE_FEE_CAP_CENTS`,
which is the same 900000-cent amount that a `NOT_ENROLLED` buyer with no points pays. A pending filing
whose fee exceeds that cap may not be approved.

### 2.12. Route Derivation: Schedule Anchor and Inventory Aggregates

A route's `schedule_anchor_utc` is derived by the rule `route_schedule_anchor`: it is the most recent
occurrence of the route's visit weekday at `08:00:00Z` that falls strictly before the logical clock. The comparison is strict, and that matters
at the boundary: if the logical clock reads exactly Monday `08:00:00Z` and the route's
`visit_weekday` is 1, the anchor is the previous Monday at `08:00:00Z`, seven days earlier, not the
current instant. Only the route's `visit_weekday` participates in the anchor; `zip_codes` and
`truck_label` are irrelevant to it. The anchor is second-resolution, and the logical clock's own
seconds are preserved in the arithmetic.

Inventory on a truck is modelled as positions, one per product per route. A position's `on_hand_qty`
is the number of units physically on the truck, its `reserved_qty` is the number of units committed to
that route's sales orders in `CONFIRMED` status, and its `remaining_qty` is `on_hand_qty` minus
`reserved_qty`. The route-level roll-ups, including the aggregate `inventory_over_pledge`, are derived from the whole
set of positions rather than from a per-pair lookup: `inventory_at_risk_cents` is the sum over every position on the route of
`reserved_qty` multiplied by `unit_cost_cents`, and `over_pledge_cents` is the sum over every
`(route, product)` pair of the excess of committed units over physical units multiplied by cost — the
quantity committed minus the quantity on hand, floored at zero, times the position's
`unit_cost_cents`. A position that is committed exactly to its on-hand quantity contributes zero: a
fully committed position is not over-pledged, and only a strictly larger committed quantity adds cost.
A product with no position on the route contributes zero to both aggregates.

An inventory position can be created or adjusted in place. Omitting the position to adjust creates a
new one and freezes `unit_cost_cents` from the product's current cost; supplying an existing
`inventory_position_id` together with a new `on_hand_qty` adjusts that position instead. Every such
write recomputes the route's `over_pledge_cents` and `inventory_at_risk_cents` and refreshes the route
row itself, so the route's `updated_at` is refreshed and its `version` advances even when both
aggregates keep their previous value. The `product_id` names
the SKU the position holds, and a route holds at most one position per product.

### 2.13. Credit Facilities, Lines and Fiscal Ceilings

Two ceilings bound what a technician may owe, and they are distinct. The technician-level
`credit_line_limit_cents` is a revolving ceiling shared across every revolving account the technician
holds; the per-account `credit_limit_cents` is frozen from the approving application's
`approved_limit_cents` when the account is minted and applies to that account alone. A technician's
`revolving_used_cents` sums `current_balance_cents` over the technician's accounts whose `account_kind`
is `REVOLVING` and whose `account_status` is `ACTIVE` or `DELINQUENT`, and
`revolving_available_cents` is `credit_line_limit_cents` minus `revolving_used_cents`, floored at
zero. An account's `credit_available_cents` is `credit_limit_cents` minus `current_balance_cents`,
floored at zero, and `open_account_count` counts the technician's accounts whose `account_status` is
`ACTIVE`, `DELINQUENT` or `CHARGED_OFF`.

Two fiscal refusals guard the two ceilings. A sales order whose `financed_principal_cents` exceeds the
target credit account's `credit_available_cents` is refused with `ERR_ACCOUNT_LIMIT_EXCEEDED` and HTTP
status 402. A revolving financed amount that exceeds the technician's `revolving_available_cents` — the
technician's `credit_line_limit_cents` less his `revolving_used_cents` — is refused with
`ERR_CREDIT_LIMIT_EXCEEDED` and HTTP status 402. The second refusal can be raised both when a sales
order is advanced and when a credit account is minted, so a mint that would overdraw the shared line
is refused at mint time as well as at financing time.

Two statuses on a technician's facility remain reachable: `credit_line_status` is `ACTIVE`,
`RESTRICTED` or `TERMINATED`, and a request to terminate a line while the technician still carries a
balance is refused with `ERR_ACCOUNT_HAS_BALANCE` at HTTP status 422 — the same identifier a closure
of an account with a non-zero `current_balance_cents` receives. The two account-kind predicates are
exact opposites by construction: `is_lease_program` is true when `account_kind` is `LEASE`,
`is_revolving_program` is true when `account_kind` is `REVOLVING`, and exactly one of the two is true
on any account.

### 2.14. Account Posture, Delinquency and the Charge-Off Anniversary

An account's `account_status` is one of `ACTIVE`, `SUSPENDED`, `DELINQUENT`, `CHARGED_OFF` or
`CLOSED`. Its `account_status_changed_at` records the logical-clock instant of the last change and is
what anchors the charge-off window. Delinquency is the stronger posture of the two adverse states: a
`suspended` account that misses a payment moves directly to `DELINQUENT` without an intervening
reinstatement, and a `DELINQUENT` account is cured only when both its `missed_payment_count` is zero
and its `accrued_finance_charge_cents` is zero.

Three state refusals frame the posture domain and each carries HTTP status 409:
`ERR_ACCOUNT_NOT_ACTIVE` when financing or an account mutation requires the account to be `ACTIVE`,
`ERR_ACCOUNT_NOT_DELINQUENT` when a cure is attempted on any other posture, and
`ERR_ACCOUNT_NOT_SUSPENDED` when a reinstatement is attempted on an account that is neither
`SUSPENDED` nor `DELINQUENT`. A mutation attempted against a `CLOSED` account is refused with
`ERR_ACCOUNT_ALREADY_CLOSED`, also at HTTP status 409. A charge-off requested before the account's
charge-off week has been reached, or a closure requested while the balance is non-zero, is refused
with `ERR_CHARGE_OFF_NOT_DUE` at HTTP status 422.

The charge-off week — the temporal window `charge_off_week` — is half-open and anchored on the
account's delinquency anniversary. Taking
`base_week` as the Monday `00:00:00Z` of the week containing `account_status_changed_at`, the
effective charge-off week is that week start plus 26 weeks. The sweep fires when the effective
charge-off week is less than or equal to the Monday `00:00:00Z` of the current logical clock's week —
inclusive at the boundary, so a clock parked exactly on the anniversary week flips the account to
`CHARGED_OFF` on that very request. Once an account is `CHARGED_OFF`, `base_week` is frozen and a
further sweep does not move it. The sweep evaluates accounts whose `account_status` is `ACTIVE` or
`DELINQUENT`; `SUSPENDED` and `CLOSED` accounts are excluded.

The next payment due is derived rather than stored. `next_due_weekday` is the weekday of the
`expected_week_start` of the earliest payment on the account that is in `BOOKED` status, and equals
`payment_due_weekday` whenever no payment is booked. `missed_payment_count` counts the account's
payments in `MISSED` status, and `last_payment_week_start` is the `expected_week_start` of the latest
payment in `COLLECTED` status, or null when none has collected.

## 3. Business Logic & Workflows

The subsections below follow the business from the franchisee's paperwork outward to the customer's
money: standing and territory first, then shops and technicians, then adjudication of credit, then the
truck's inventory and order book, then collection, then warranty and replenishment, then launch
allocation, and finally the failure paths that cross all of them.

### 3.1. Franchisee Standing, Route Lifecycle and Territory Development

A franchisee begins with a `legal_name` and nothing else: `training_status` starts at `NOT_ENROLLED`,
`certified_on` is null, and `can_resell_territory` is false. The `FranchiseOwner` moves the franchisee
through training with an action that either enrols, certifies or recertifies, and the payload carries
the `action` together with the `training_points` the programme has accumulated. Enrolling moves
`NOT_ENROLLED` to `ENROLLED` and recomputes `can_resell_territory` to false. Certifying moves
`ENROLLED` to `CERTIFIED`, stamps `certified_on` with the logical clock, and recomputes
`can_resell_territory` to true — but only when the reported `training_points` are at least 40; a
certification attempt below that threshold is refused with `ERR_CERTIFICATION_POINTS_SHORT` rather
than leaving the franchisee enrolled by default. Recertifying moves `CERTIFIED` back to `ENROLLED`,
clears `certified_on` to null, and recomputes `can_resell_territory` to false. The cycle is genuine in
both directions: a certified franchisee who returns for re-certification re-enters the development
cycle rather than being grandfathered. Enrollment itself records `training_points` on the enrollment
row as the programme's progress, and the certification threshold reads those points rather than the
route's development points.

Routes are created by a `FranchiseOwner` under one of his own franchisees, and the creation payload
names the `route_code`, the `route_tier`, the `zip_codes` the territory covers, the `visit_weekday`,
the `truck_label`, the `inventory_invested_cents` the franchisee is putting into the truck, the
`mix_plan` the route intends to sell, and the `territory_model` that will become the default recourse
model for accounts opened while the territory is in force; `territory_points` may be supplied at
creation but is not required. A new route starts at `route_status` `DRAFT`, at
`territory_development_status` `UNASSIGNED`, and at `resale_status` `NONE`, and its
`schedule_anchor_utc` is computed on creation. The `route_tier` is one of `A`, `B` or `C`, where `A` is
the highest-volume territory band, and the `mix_plan` is one of `DIAGNOSTIC_WEIGHTED`, `TOOL_STORAGE`
or `POWER_TOOLS`. The `zip_codes` array must be non-empty; an empty one blocks activation. Route
attributes — the `route_code`, `route_tier`, `zip_codes`, `visit_weekday`, `truck_label`,
`inventory_invested_cents`, `mix_plan`, `territory_model` and `territory_points` — may be revised by
the owning `FranchiseOwner` afterwards, and a revision that changes `visit_weekday` forces
`schedule_anchor_utc` to be recomputed.

Activating a route moves `route_status` from `DRAFT` to `IN_SERVICE` and is refused unless four
conditions hold: the route is currently `DRAFT`, its `zip_codes` array is non-empty, the owning
franchisee is `CERTIFIED`, and its `inventory_invested_cents` is at least 1. The uncertified case is
reported as `ERR_FRANCHISEE_NOT_CERTIFIED`; an activation attempted against a route that is not
`DRAFT` is reported as `ERR_ROUTE_ALREADY_IN_SERVICE`. Activation recomputes
`schedule_anchor_utc` and refreshes the franchisee's `active_route_count`. Once a route is
`IN_SERVICE`, later certificate renewals do not require re-activation, so the certification chain
flows forward without the route being touched again.

Suspension is a `FranchiseManager` act that moves `IN_SERVICE` to `SUSPENDED` and cascades downward.
Every shop on that route whose `shop_status` is `ACTIVE` becomes `INACTIVE`, and each of those shops
in turn affects the technicians who work there, as Section 3.2 describes. Reinstatement moves
`SUSPENDED` back to `IN_SERVICE`, and it deliberately does not reopen the shops that suspension
closed: a shop left `INACTIVE` by suspension stays `INACTIVE` until it is deliberately reactivated.
Both moves recompute the franchisee's `active_route_count`. Retirement may be requested from `DRAFT`
or from `SUSPENDED` — never from `IN_SERVICE` — and moves the route to `RETIRED`, which is terminal.
A cultivating route whose `resale_status` is `PENDING` may not be retired, because the filing is still
live. A retirement attempted against a route that is in any status other than `DRAFT` or `SUSPENDED`,
and a retirement attempted while `resale_status` is `PENDING`, are both refused with `ERR_INVALID_STATE`
at HTTP status 409. Retirement requires the `expected_route_version` described in Section 2.8. When a
route retires while its `territory_development_status` is `QUALIFIED`, the territory is moved to `SURRENDERED` at the
same moment and its `in_force_to_week` is stamped. An operation that needs the route `IN_SERVICE` and
finds it otherwise — including a territory qualification attempt — is refused with
`ERR_ROUTE_NOT_IN_SERVICE` at HTTP status 409.

Territory development is a second, independent axis on the same route, and it does not track
`route_status`. A development round is opened by a `FranchiseOwner` moving
`territory_development_status` from `UNASSIGNED` to `IN_DEVELOPMENT`; the payload supplies the
`territory_points` the round is opening with, and the `territory_model` must already be set on the
route. Opening a round stamps `in_force_from_week` with the Monday `00:00:00Z` of the logical clock's
week and records the requested points. Qualification is reached when a development round reports
`territory_points` of at least 60 while the route is `IN_SERVICE`, moving the territory from
`IN_DEVELOPMENT` to `QUALIFIED`; a round that is opened from `UNASSIGNED` with at least 60 points on a
route that is already `IN_SERVICE` therefore reaches `QUALIFIED` on that same opening call, and a
refused qualification leaves the route's development state untouched. The qualification rule is refused as
`ERR_FRANCHISEE_NOT_CERTIFIED` when the owning franchisee is uncertified and as
`ERR_ROUTE_NOT_IN_SERVICE` when the route is not in service. Accounts opened from a `QUALIFIED` territory inherit that route's `territory_model` as their
`recourse_holder` at minting, as Section 3.5 explains.

Two backward edges keep the development axis honest. A `FranchiseManager` may restart a `QUALIFIED`
territory as a fresh `IN_DEVELOPMENT` round, which resets `territory_points` to 0. Either a `QUALIFIED`
territory or an `IN_DEVELOPMENT` round may be surrendered by a `FranchiseManager`, moving the territory
to `SURRENDERED` and stamping `in_force_to_week` with the Monday `00:00:00Z` of the logical clock's
week; surrender is terminal on this axis and independent of `route_status`. An abandoned development
round can therefore be surrendered without ever qualifying: the surrendered point floor defers the
points above the 60-point qualification threshold to 0 when the round never qualified. Surrender is
refused while `resale_status` is other than `NONE`, and a development round may not open while an
earlier round of the same route is still in force, which is reported as
`ERR_TERRITORY_WINDOW_CONFLICT`. Crucially, surrender does not rewrite history for money already
lent: credit accounts whose opening territory was this route keep their `territory_id`, and their
`recourse_holder` stays frozen rather than being recomputed.

Resale is a third parallel axis, enabled by certification and by qualification. A `FranchiseOwner`
files a resale by moving `resale_status` from `NONE` to `PENDING`, and the filing is refused unless the
selling franchisee is `CERTIFIED` and the territory is `QUALIFIED`; the payload carries the prospective
buyer's `buyer_training_status` and `buyer_training_points`, which are recorded on the route as
`resale_buyer_training_status` and `resale_trained_points`. The filing recomputes
`reopening_fee_cents` by the fee rule in Section 2.11. A second filing while one is already `PENDING`
is refused with `ERR_RESALE_ALREADY_PENDING`, and a decision attempted while no filing is pending is
refused with `ERR_RESALE_NOT_PENDING`; both carry HTTP status 409. A `FranchiseManager` approves or
declines a pending filing: approval moves `PENDING` to `APPROVED` and is permitted only while
`reopening_fee_cents` is at most `FRANCHISEE_RESALE_FEE_CAP_CENTS`, while a decline moves `PENDING` to
`DECLINED` with no fee test. A declined filing may be re-filed by the `FranchiseOwner` — provided the
selling franchisee is still `CERTIFIED` — which returns it to `PENDING` and reprices the fee. When the
buyer actually takes over, the system returns `resale_status` to `NONE`, resets
`resale_buyer_training_status` to `NOT_ENROLLED` and resets `resale_trained_points` to 0, so the next
filing starts clean. A resale filing that is attempted with no live qualification behind it is refused
as `ERR_TERRITORY_NOT_QUALIFIED`.

### 3.2. Shops, Technicians and the Cascade of a Route Suspension

A `FranchiseOwner` adds a repair shop to one of his routes by supplying the `shop_name`, the
`street_line` and the `zip_code`. The zip code must appear in the owning route's `zip_codes`; a shop
whose zip code falls outside the territory is rejected with `ERR_SHOP_ZIP_NOT_IN_TERRITORY` and HTTP
status 400. New shops start at `shop_status` `ACTIVE`, and the write recomputes the owning
franchisee's `fallback_shop_location_id`. A shop's `shop_name`, `street_line` and `shop_status` may be
revised by the owning `FranchiseOwner`, and each such revision also refreshes the franchisee's
fallback pointer. A shop's `active_technician_count` is derived: it counts the technicians whose
`technician_status` is `ACTIVE` and whose `current_shop_location_id` is that shop.

Technicians are onboarded by a `FranchiseOwner` at a specific shop. The onboarding payload names the
`full_name`, the `current_shop_location_id`, the `credit_line_limit_cents` that sets the shared
revolving ceiling, the `months_in_trade` the technician has worked in the trade, and the
`employment_verified` flag captured at onboarding. A new technician starts with `technician_status`
`ACTIVE` and `credit_line_status` `ACTIVE`, and `home_route_id` is derived immediately from the shop —
the route that owns the shop — so a technician is always attached to a route through the shop he works
at rather than through a direct reference. The onboarding write refreshes the shop's
`active_technician_count`. The `full_name`, `credit_line_limit_cents`, `months_in_trade` and
`employment_verified` attributes may be revised later, and such a revision recomputes
`revolving_available_cents`.

Technician standing moves through three states besides the initial one. A `FranchiseOwner` records a
shop change, moving `technician_status` from `ACTIVE` to `SHOP_CHANGE_PENDING`; the payload carries
`target_shop_location_id`. A shop change is refused unless the technician is currently `ACTIVE`, the
target shop is `ACTIVE`, and every credit account the technician holds is in one of the standing
postures `ACTIVE`, `SUSPENDED`, `DELINQUENT` or `CHARGED_OFF` — a closed account is not blocking, but
a technician with no open account at all is refused as `ERR_TECHNICIAN_NOT_ACTIVE` when he is not
`ACTIVE` in the first place. The move immediately repoints `current_shop_location_id` at the target
shop, recomputes `home_route_id` from the new shop, and refreshes the source and target shops'
`active_technician_count`. Two things do not move: each of the technician's credit accounts keeps its
`territory_id` and its `recourse_holder`, so a shop change never re-prices the recourse on money
already lent.

Confirming the pending shop change returns the technician from `SHOP_CHANGE_PENDING` to `ACTIVE` and
recomputes `home_route_id`. The pending change may also be abandoned: cancelling it returns the
technician to `ACTIVE` at his prior shop — the transition requires that a prior shop is still on file
in `current_shop_location_id` — repoints `current_shop_location_id` back to that prior shop, recomputes
`home_route_id`, and refreshes the abandoned target shop's `active_technician_count`. `SHOP_CHANGE_PENDING`
is not a terminal state in either direction.

Leaving the trade is the terminal move and it cascades. A `FranchiseManager` records a trade exit from
either `ACTIVE` or `SHOP_CHANGE_PENDING`, moving `technician_status` to `TRADE_EXITED`. The exit
captures `last_known_shop_name` from the current shop's `shop_name`, clears `current_shop_location_id`
to null and clears `home_route_id` to null, refreshes the source shop's `active_technician_count`, and
suspends money: every credit account of that technician whose `account_status` is `ACTIVE` moves to
`SUSPENDED`. Accounts already `DELINQUENT`, `CHARGED_OFF` or `CLOSED` are not disturbed. A trade exit
is refused while the technician still has a sales order in `CONFIRMED` status with unreserved stock —
the request must name only technicians whose open orders are `DELIVERED` or beyond — and the refusal
carries `ERR_TRADE_EXIT_OPEN_ORDER` at HTTP status 422. Any later operation attempted against an
already exited technician is refused with `ERR_TECHNICIAN_EXITED` at HTTP status 409.

The suspension cascade reaches technicians from above. When a route is suspended, its `ACTIVE` shops
become `INACTIVE`. A shop that is `INACTIVE` stops counting its technicians as active, and the
franchisee's effective presence on the territory contracts with it; because the shop's
`active_technician_count` counts only technicians whose own standing is `ACTIVE`, an inactive shop
reports the reduced count immediately. The route suspension and the trade exit are therefore two
independent routes into the same place: one closes the workplace, the other closes the person.

### 3.3. Credit Applications: Scoring and Adjudication

Credit begins with an application filed against a shop. A `FranchiseOwner` or a `CreditOfficer` files
it, naming the `technician_id` of the applicant, the `requested_limit_cents`, the `requested_kind`
(`REVOLVING` or `LEASE`), the `requested_term_months` that a lease requires, the `employment_verified`
flag, the `months_in_trade` at application time, the `prior_delinquency_count` on file, and the
`decision_source` that names which party will adjudicate. The applicant's `current_shop_location_id`
must equal the shop the application is filed under, so filing is inherently a statement about where
the technician currently works. A new application starts at `application_status` `SUBMITTED`, and its
`decision_score` is computed immediately on filing by the scoring rule below. A lease application that
omits `requested_term_months` is refused with `ERR_LEASE_TERM_REQUIRED` at HTTP status 422; a
revolving application that carries a term is accepted, and the value is simply ignored.

The decision score — the rule `credit_decision_score` — is a weighted, clamped, non-linear aggregate of
that application's own fields and nothing else — no other entity contributes to it. The computation begins from a base of 40. It adds
one half point for each month the technician has worked in the trade, counting at most 120 months, so
the months contribution saturates at 60 for a veteran. It subtracts 9 points for each prior
delinquency on file. It adds 12 points when the application's `employment_verified` flag is true. It
adds a further 4 points when the application's `requested_kind` is `LEASE`. The resulting base is then
scaled: when the `requested_limit_cents` are at least 500000, the base is multiplied by 1.05; below
that boundary it is multiplied by 1.00, which leaves it unchanged. The scaled value is then floored to
an integer — truncating any fractional part downward — and the floored value is clamped to the integer
range 1 to 100 inclusive. The floor binds before the ceiling ever does, which is visible in the
arithmetic: seven prior delinquencies at 9 points each drive the base far below zero and the floor at 1
is what a caller actually observes. The result is stored as `decision_score` and is recomputed on
franchisor review and on the reopening of a franchisee-declined application.

Adjudication branches on `decision_source`, and the two branches are deliberately asymmetric. When
`decision_source` is `FRANCHISOR`, a `CreditOfficer` first opens a review, moving `SUBMITTED` to
`UNDER_REVIEW` and recomputing the score; approval then moves `UNDER_REVIEW` to `APPROVED` and
requires `decision_score` of at least 55, while a decline moves `UNDER_REVIEW` to `DECLINED` with no
score test. When `decision_source` is `FRANCHISEE`, the `FranchiseOwner` decides the application
directly from `SUBMITTED`, with no review step: approval requires `decision_score` of at least 40 and
`employment_verified` equal to true, and a decline moves `SUBMITTED` to `DECLINED` with no score test.
The 55-point hurdle therefore belongs to the franchisor's review path and the 40-point hurdle to the
franchisee's direct path; a score between the two is approvable by the franchisee and not by the
franchisor.

Approval freezes the outcome onto the application. All four side effects are stated here so that the
two branches are read as identical: the `application_status` becomes `APPROVED`, `approved_limit_cents`
is set to the limit computed by the marginal tier rule below, `approved_kind` is set to the
application's `requested_kind`, and `approved_term_months` is set to the application's
`requested_term_months`, which is 0 for a revolving application. A `decision_note` is stamped on the
approval. All four side effects are likewise identical on a decline except that
`approved_limit_cents` is set to 0 — a declined application records no limit — and the
`decision_note` records the refusal. Before a decision, `approved_limit_cents` is 0, `approved_kind`
is null and `approved_term_months` is 0.

The granted limit is tiered marginally on the approved decision score by the rule
`credit_decision_limit`, and the word marginally is load-bearing: each tier's rate applies only to the points that fall inside that tier. When the
`decision_score` is 40 or below, `approved_limit_cents` is 750 cents multiplied by the score, so a
score of 40 grants 30000 cents. When the score is above 40 but at or below 60, the amount is
750 cents multiplied by 40, plus 500 cents multiplied by the score less 40. When the score is above
60, the amount is 750 cents multiplied by 40, plus 500 cents multiplied by the span of the middle tier
(60 less 40), plus 250 cents multiplied by the score less 60. The result is then capped by the
requested amount: `approved_limit_cents` is the smaller of the tiered amount and the application's
`requested_limit_cents`. The contrast with an average rate is deliberate and observable — a score of
60 grants 30000 plus 500 multiplied by 20, which is 40000 cents, not 60 multiplied by 750, which would
be 45000. No rounding is applied at any tier boundary; every amount is an exact whole number of cents.
A declined application sets `approved_limit_cents` to 0. Two separate checks guard the ceiling above
this rule: filing an application whose `requested_limit_cents` exceed `CREDIT_ABSOLUTE_CAP_CENTS` is
refused with `ERR_CREDIT_REQUEST_ABOVE_CAP` at HTTP status 402, and deciding one is refused the same
way, because the tiered grant can never exceed the requested amount and the requested amount is what
is tested.

Two more moves exist on this machine. A `FranchiseOwner` may withdraw an undecided application,
moving either `SUBMITTED` or `UNDER_REVIEW` to `WITHDRAWN`, which is terminal. A `FranchiseOwner` may
also reopen a franchisee-declined application, moving `DECLINED` back to `SUBMITTED` and recomputing
`decision_score`; this backward edge exists only on the franchisee path, so a franchisor decline is
final. A decision requested against an application that is already `APPROVED`, `DECLINED` or
`WITHDRAWN` is refused with `ERR_APPLICATION_ALREADY_DECIDED` and HTTP status 409.

### 3.4. The Truck's Order Book: Sales Orders, Pricing and Stock

A `RouteSalesRep` writes a sales order against one of his own routes, naming the `technician_id` who
is buying, the `credit_account_id` the sale will be financed against, the `mix_profile` that selects
the route's product mix ranking, and the `lines` array. Each entry of `lines` is a `{product_id,
quantity, unit_price_cents, warranty_terms}` record, where `warranty_terms` itself carries a `type` and
a `months` count; the array index is the line index, and it is stable and meaningful — a warranty
claim later names a line by that index. A new order starts at `order_status` `DRAFT`. An order with an
empty `lines` array is refused with `ERR_EMPTY_MIX_LINES`, and a `line_count` of zero cannot survive
creation. The `mix_profile` is one of `DIAGNOSTIC_WEIGHTED`, `TOOL_STORAGE` or `POWER_TOOLS`, the same
three values the route's `mix_plan` uses, and it selects which product category is ranked first both
in replenishment and in the pricing multiplier below.

Pricing an order — the rule the system calls `order_gross_total` — is an aggregation over its lines with a per-mix multiplier, and the rounding order is
pinned. A multiplier is selected from the order's `mix_profile`: `DIAGNOSTIC_WEIGHTED` uses
`1.0075`, `TOOL_STORAGE` uses `1.0150`, and `POWER_TOOLS` uses `1.0025`. Each line's extended amount is
the line's `unit_price_cents` multiplied by the line's `quantity` multiplied by the selected
multiplier, rounded half up to a whole number of cents, and that rounding is performed per line,
independently. The order's `gross_total_cents` is then the exact integer sum of those per-line rounded
amounts, evaluated in line order with no further rounding. The order of operations is observable and
it is deliberate: rounding the total once at the end, after summing the unrounded extended amounts,
produces a different cent value for the same order, and that variant is prohibited. Every line
contributes: a line with quantity 0 contributes 0, and no line is filtered out.

Selling requires stock, and stock is checked against the route's own positions. When an order is
advanced past `DRAFT`, every line's quantity must be at most the `remaining_qty` of the matching
inventory position on the order's route — the quantity on hand less the quantity already reserved. A
line that exceeds it is refused with `ERR_INSUFFICIENT_INVENTORY` and HTTP status 409. The buyer must
also be a customer of the route he is buying from: the order's technician must have `home_route_id`
equal to the order's route. Confirmation additionally requires that the order be `DRAFT`, that
`line_count` be at least 1, and that the credit account named on the order be `ACTIVE`; an order that
is not `DRAFT` is refused as `ERR_ORDER_NOT_CONFIRMABLE` and an account that is not `ACTIVE` as
`ERR_ACCOUNT_NOT_ACTIVE`. Because editing lines is a legitimate re-confirmation path, the confirmation
write requires `expected_sales_order_version` as Section 2.8 describes.

Confirming reserves, delivering writes principal, settling closes, and cancelling releases. On
confirmation each line's inventory position has its `reserved_qty` incremented by the line quantity,
which lifts the route's `inventory_at_risk_cents` and `over_pledge_cents` and reduces what later orders
can reserve; the order's `gross_total_cents` and `financed_principal_cents` are recomputed at the same
time. On delivery each line's position is decremented twice — `on_hand_qty` by the line quantity and
`reserved_qty` by the same quantity — so the units physically leave the truck and stop being reserved
in one move, and the target credit account's `principal_balance_cents` is increased by
`financed_principal_cents` with `current_balance_cents`, `credit_available_cents`,
`revolving_used_cents` and the franchisee's `outstanding_credit_cents` all recomputed after it.
Delivery requires the order to be `CONFIRMED` and is otherwise refused as `ERR_ORDER_NOT_DELIVERABLE`;
it also requires that the credit account named on the order be `ACTIVE`, failing which it is refused
with `ERR_ACCOUNT_NOT_ACTIVE` at HTTP status 409 before any fiscal ceiling is evaluated; it also
requires that the order's `financed_principal_cents` fit the account's `credit_available_cents`,
failing which it is refused with `ERR_ACCOUNT_LIMIT_EXCEEDED`. Settlement moves `DELIVERED` to
`SETTLED` and is permitted only when no warranty claim on the order is in `OPEN` or `SUBMITTED` status
and the order carries no outstanding charge allocated to a reversed payment; otherwise it is refused
with `ERR_ORDER_NOT_SETTLEABLE`. Cancellation is allowed from `DRAFT` or `CONFIRMED` and releases the
reservation: each line's `reserved_qty` is decremented by the line quantity and the route's
`inventory_at_risk_cents` and `over_pledge_cents` are recomputed. Cancellation is pure compensation —
no account principal was written while the order was merely confirmed, so no ledger entry needs
reversing.

The financed principal of an order — the dual-variant rule `order_financing_variant` — has two valid
bases, and the settlement status decides which one is live. The provisional basis and the final basis are the two named variants of this rule: the
provisional basis is the gross order value, and the final basis is the gross order value less the
approved warranty allocations. While the order is `DRAFT` or `CONFIRMED`, the provisional basis
applies and `financed_principal_cents` equals `gross_total_cents`; warranty allocations that already
exist against the order are ignored. Once the order reaches `DELIVERED`, the final basis applies and
`financed_principal_cents` equals `gross_total_cents` minus the sum of `principal_allocated_cents` over
every warranty claim on this order whose `claim_status` is `APPROVED` — claims in `OPEN`, `SUBMITTED`
or `REJECTED` status contribute 0. The difference is concrete: for an order carrying one approved
allocation of 3600 cents, the two bases differ by exactly 3600. There is no recovery path for a claim
resolved after the order settled: once `order_status` is `SETTLED`, the final basis is frozen and a
later warranty approval does not move it. The `financed_principal_cents` recomputed under the final
basis is also what is compared against the account's available credit when the order is delivered, so
an approval that lands between confirmation and delivery legitimately lowers the principal written to
the account.

### 3.5. Credit Accounts, Recourse, Accrual and Collection

An account is minted against an approved application by a `CreditOfficer`. The mint requires that the
parent application's `application_status` be `APPROVED`, failing which it is refused with
`ERR_APPLICATION_NOT_APPROVED` at HTTP status 409, and it requires
`expected_application_version` matching the application's current `version` per Section 2.8, so a mint
attempted against a superseded view of the application is refused with `ERR_STALE_VERSION` at HTTP
status 412. This is a real ambiguity rather than a theoretical one: an application that was reopened
and re-approved legitimately mints a second account, so a strictly sequential second mint would
otherwise succeed; the stale version is what distinguishes an intentional re-mint from a writer
working off an outdated view.

Minting freezes the account's terms from the application and resolves its recourse. The new account
starts at `account_status` `ACTIVE` — `APPLIED` is a transient initial state that exists only in the
instant of creation. `credit_limit_cents` is taken from the application's `approved_limit_cents`,
`account_kind` from the application's `approved_kind`, and `account_status_changed_at` is
stamped with the logical clock. `is_lease_program` and `is_revolving_program` are recomputed from the
kind, `payment_due_weekday` is inherited from the opening route's `visit_weekday`, and
`installment_due_cents` is computed for lease accounts by the amortisation rule below while remaining 0
for revolving accounts. The recourse holder is resolved by the rule in the next paragraph. Minting
also recomputes the technician's `revolving_used_cents` and the franchisee's `credit_ceiling_cents`,
and it will refuse with `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP status 402 if the new account would push
the technician's revolving exposure past his shared `credit_line_limit_cents`.

Recourse resolution — the rule `resolve_recourse_holder` — is a deterministic selection over in-force
qualified territories. The candidates
are the territories that are published as `QUALIFIED`, that are the route referenced by the account's
territory, that came into force on or before the current week, and that are still in force — meaning
either their `in_force_to_week` is null or the current week is strictly before it. `SURRENDERED`,
`IN_DEVELOPMENT` and `UNASSIGNED` territories are excluded. When at least one candidate exists, the
earliest by `created_at` is chosen — ties are broken on `created_at` alone and the `id` is never
consulted — and the chosen territory's `territory_model` is mapped to a holder: a
`FRANCHISEE_ASSUMED` territory yields a `FRANCHISOR` recourse holder, and a `FRANCHISOR_RECOURSE`
territory yields a `FRANCHISEE` recourse holder. The mapping is deliberately inverted: the model names
who assumed the risk, and the holder names who carries it. When no candidate exists, the empty-pool
fallback gives a `FRANCHISOR` recourse holder, so an account opened with no in-force territory is
franchisor-recourse. The holder is frozen at minting and is never recomputed — neither a later
surrender of the opening territory nor a shop change touches it.

Lease accounts amortise under the rule `lease_amortization`. For a lease account the monthly rate is
the annual lease rate of `0.2400` divided by 12, and the raw installment is the principal multiplied
by that monthly rate and divided by
one minus the term-length factor — the quantity one plus the monthly rate raised to the negative power
of the term in months. The raw installment is rounded half up exactly once to a whole number of cents,
and that rounded installment is multiplied by the term to build the schedule. For an account in
`DELINQUENT` status the installment due is instead the rounded installment multiplied by the
delinquency uplift of 1.25, rounded half up again. The schedule's final installment is the principal
plus total interest minus the rounded installment multiplied by one less than the term, so the
installments sum exactly to principal plus total interest and the rounding residue is absorbed in the
last payment. Only lease accounts carry a schedule: a revolving account's `installment_due_cents` is 0
and it is excluded from amortisation entirely. Amortisation is re-run whenever principal is written to
a lease account, so the schedule always reflects the current balance rather than the balance at
minting.

Finance charges accrue under the rule `finance_charge_accrual`, once a week, and the basis they accrue
on is selected by a predicate that is frozen at minting. `use_final_basis` equals `is_lease_program` at creation: it is true for every lease account
and false for every revolving account. The accrual runs the first time a request is served whose
logical clock week is later than the account's last `accrual_iso_week`, and it is skipped entirely for
accounts whose `account_status` is `CLOSED` — `ACTIVE`, `SUSPENDED`, `DELINQUENT` and `CHARGED_OFF`
accounts all accrue. The week's `opening_balance_cents` is recorded on the charge row.

The accrual basis is one of two variants. When `use_final_basis` is false — every revolving account —
the basis is the week's `opening_balance_cents` in full, so payments that collect in the same week do
not reduce the charge. When `use_final_basis` is true — every lease account — the basis is the opening
balance reduced by the `charge_applied_cents` of every payment on the account that is in `COLLECTED`
status and whose `effective_iso_week` equals the week being accrued, so a payment that lands in the
same week reduces a lease account's charge and leaves an identical payment on a revolving account
untouched. A tiered annual rate is then selected from the basis: when the basis is less than 50000
cents the low rate of `0.1560` applies, when the basis is less than 200000 cents the mid rate of
`0.1820` applies, and otherwise the high rate of `0.2080` applies. The boundaries are on the cents and
inclusive upward: a basis of exactly 50000 cents takes the mid rate, not the low rate, and a basis of
exactly 200000 cents takes the high rate. The charge amount is the basis multiplied by the selected
rate, divided by the 52 weeks in the year, and rounded half up to a whole number of cents exactly once
at the end of that formula — never at an intermediate step. Each accrual is written as a new charge row
with its own `accrual_iso_week`, a monotonic `accrual_seq` that restarts at 1 within each week, and a
`charge_status` of `OPEN`.

A `RouteSalesRep` books a payment and later collects it on the truck. Booking names the `amount_cents`,
which must be a positive integer, the `collection_source` — one of `TRUCK_COLLECTION`,
`FRANCHISOR_DRAFT` or `SETTLEMENT_APPLIED` — and the `expected_week_start`. A new payment starts at
`payment_status` `BOOKED` and has a null `effective_iso_week`; booking recomputes the account's
`next_due_weekday`. Collecting a booked payment moves it to `COLLECTED`, stamps `effective_iso_week`
with the Monday `00:00:00Z` of the logical clock's week, and runs the allocation rule below.
Collecting requires the payment to be `BOOKED` and the payment's `amount_cents` to be positive; a
collection attempted against a payment that is not booked is refused with `ERR_PAYMENT_NOT_BOOKED` at
HTTP status 409. Collection is refused for an account whose `account_status` is `CLOSED`, reported as
`ERR_ACCOUNT_ALREADY_CLOSED`, and is allowed for accounts that are `ACTIVE`, `SUSPENDED` or
`DELINQUENT`. A collection on a `SUSPENDED` account that leaves the account with positive
`credit_available_cents` returns the account to `ACTIVE` as part of the same write.

Allocation of a collected payment — the rule `payment_allocation` — is oldest-accrual-first and exact. The cash is applied against the
account's finance charges that are in `OPEN` status, taken in ascending order of `accrual_iso_week`,
then ascending `accrual_seq`, then ascending `created_at`; charges that are already `CLOSED` are never
re-credited by a new payment. For each charge in that order, the amount taken is the smaller of the
cash still in hand and the charge's `charge_amount_cents` less what has already been applied to it;
that amount is added to the charge's `collection_applied_cents` and subtracted from the cash. When a
charge's `collection_applied_cents` reaches its `charge_amount_cents` the charge flips to `CLOSED` and
its `charge_resolved_iso_week` is stamped with the payment's `effective_iso_week`. The walk stops as
soon as the cash is exhausted. Any cash left after every open charge has been fully covered reduces the
account's principal instead. `charge_applied_cents` on the payment records the amount that went to
charges, and the invariant holds exactly: the amount applied to charges plus the amount that reduced
principal equals the payment's `amount_cents`, with no residue. After allocation the account's
`principal_balance_cents`, `accrued_finance_charge_cents`, `current_balance_cents`,
`credit_available_cents` and `last_payment_week_start` are all recomputed, along with the technician's
`revolving_used_cents` and the franchisee's `outstanding_credit_cents` and `recourse_exposure_cents`.

The outstanding periodic due is computed by the rule `minimum_payment_due` from the account's own
balance and posture alone, and its evaluation order is pinned so that the result is unambiguous. The tier is read from the account's
current balance, never from the value the formula is about to produce: first the current balance is
read, then the percentage is selected from that opening figure, then the due is derived. When the
balance is below 25000 cents the minimum tier percentage of `0.05` applies; when it is below
150000 cents the mid tier percentage of `0.10` applies; otherwise the maximum tier percentage of
`0.20` applies. The percentage due is the balance multiplied by the selected percentage, rounded half
up to a whole number of cents, and the `minimum_payment_due_cents` is that value or the flat minimum
of 2500 cents, whichever is larger. One override sits outside both: if the account's `account_status`
is `DELINQUENT`, the minimum payment due is raised to the account's full `current_balance_cents`, and
that override is applied after the flat minimum, so it wins over both the tier result and the floor.
Lease accounts do not use this formula at all — their due is the amortised `installment_due_cents`.

Three adverse moves remain. A `CreditOfficer` may suspend an `ACTIVE` account, but only when the
account's `credit_available_cents` is exactly zero — a suspension is the posture of a fully drawn
account and cannot be applied while headroom remains. A `CreditOfficer` may reinstate a `SUSPENDED`
account, which requires `credit_available_cents` greater than zero, or cure a `DELINQUENT` account,
which requires both `missed_payment_count` of zero and `accrued_finance_charge_cents` of zero;
reinstatement of an account that is neither `SUSPENDED` nor `DELINQUENT` is refused with
`ERR_ACCOUNT_NOT_SUSPENDED`, and a cure of an account that is not `DELINQUENT` with
`ERR_ACCOUNT_NOT_DELINQUENT`. A `FranchiseManager` may charge off an account once its charge-off week
has been reached, settle a charged-off account whose `current_balance_cents` is zero into `CLOSED`, or
close an account whose balance is zero; a charge-off requested too early is refused with
`ERR_CHARGE_OFF_NOT_DUE` and a closure requested with a non-zero balance with `ERR_ACCOUNT_HAS_BALANCE`.
Every one of these moves stamps `account_status_changed_at` with the logical clock, and each recomputes
the technician's `revolving_available_cents` and the franchisee's `outstanding_credit_cents`.

A payment that was missed is not lost. A `FranchiseManager` marks an overdue booked payment as missed,
which requires the payment to be `BOOKED` and its `expected_week_start` to fall strictly before the
Monday `00:00:00Z` of the logical clock's week; a booking that is not yet overdue cannot be marked
missed. The miss moves the payment to `MISSED`, clears its `effective_iso_week` to null, and moves the
parent account to `DELINQUENT` — from `ACTIVE` or from `SUSPENDED` alike, with no intervening
reinstatement step — recomputing `missed_payment_count`, `accrued_finance_charge_cents` and
`minimum_payment_due_cents` afterwards. A missed booking can still be cured by a late truck collection:
collecting a `MISSED` payment from a `DELINQUENT` account moves the payment to `COLLECTED`, stamps its
effective week, runs the allocation rule, and recomputes `missed_payment_count` and
`current_balance_cents`. A booked payment that is no longer wanted may be cancelled by a
`FranchiseManager`, which moves `BOOKED` to `CANCELLED` and recomputes the account's
`next_due_weekday`. A `CreditOfficer` may reverse a `COLLECTED` payment, which un-credits every finance
charge the payment had credited, returning each charge's `collection_applied_cents` by the amount it
received and restoring any charge whose `collection_applied_cents` returns to zero to `OPEN` status
with its `charge_resolved_iso_week` cleared; the account's `principal_balance_cents`,
`accrued_finance_charge_cents`, `current_balance_cents` and `credit_available_cents` are recomputed,
along with the technician's `revolving_used_cents` and the franchisee's `outstanding_credit_cents`. A
reversal attempted against a payment that is not `COLLECTED` is refused with
`ERR_PAYMENT_NOT_COLLECTED`. Reversal is not itself reversible: once a payment is `REVERSED` it stays
`REVERSED`. The three terminal states of this machine are `COLLECTED`, `REVERSED` and `CANCELLED`, and
`MISSED` is deliberately not among them — a missed booking can still collect.

### 3.6. Replenishment, Ceiling Fill and Share Pledges

Restocking the truck is a separate order book from selling off it. A `FranchiseOwner` creates a
replenishment order for one of his routes, naming the `mix_profile` that determines which product
category is ranked first, the `investment_ceiling_cents` that caps this order, and the
`requested_lines` array, whose entries are `{product_id, requested_qty}` pairs in the client's requested
order — the array index is that line's index and it is the final tie-breaker in the fill rule below.
A new replenishment order starts at `product_order_status` `DRAFT` and its `requested_cost_cents` is
the sum over the requested lines of the requested quantity multiplied by the product's current
`unit_cost_cents`. The ceiling fill is previewed immediately at creation: `ordered_lines`,
`ordered_cost_cents`, `deferred_lines` and `is_fully_covered` are all computed when the draft is
created and recomputed again when the order is submitted, so a draft already carries the ordered
quantities that a share pledge will be measured against.

The fill rule — the waterfall `route_replenishment_allocation` — is deterministic over the ceiling,
and its ordering is the whole point. Each
requested line is ranked by a three-part key. First, a line whose product's `category` is the leading
category for the order's mix profile sorts ahead of a line that is not, where `DIAGNOSTIC_WEIGHTED`
leads with `DIAGNOSTICS`, `TOOL_STORAGE` leads with `TOOL_STORAGE`, and `POWER_TOOLS` leads with
`POWER_TOOLS`. Second, within a leading or non-leading band, a cheaper SKU sorts ahead of a dearer one,
by ascending `unit_cost_cents`. Third, remaining ties are broken by ascending line index, preserving
the client's requested order. The ceiling is then consumed in that sequence: starting with the whole
`investment_ceiling_cents` as the remaining budget, each line in priority order is granted the smaller
of its requested quantity and the quantity that the remaining budget can afford, where the affordable
quantity is the remaining budget divided by the line's unit cost, rounded down to a whole unit. The
granted quantity is written as the line's `ordered_qty`, and the remaining budget is reduced by that
quantity multiplied by the unit cost before the next line is considered. A line whose unit cost exceeds
the remaining budget is skipped with a `deferred_qty` equal to its full requested quantity, and the
loop continues to cheaper lines that the budget can still cover — the budget is never held back for a
later line while an earlier one is short, and it is never handed to a later line while an earlier one
can still be filled. The `deferred_lines` array records, for each shortfall, the `product_id`, the
`line_index` and the `deferred_qty`. `ordered_cost_cents` is the sum over the ordered lines of
`ordered_qty` multiplied by `unit_cost_cents`, and it can never exceed `investment_ceiling_cents`.
`is_fully_covered` is true exactly when every requested line came through in full, meaning every
deferred quantity is zero. A line with a requested quantity of zero is retained in `ordered_lines`
with an `ordered_qty` of 0 rather than dropped.

Submitting a replenishment order moves it from `DRAFT` to `SUBMITTED` and is refused unless the order
is currently `DRAFT`, unless `requested_lines` is non-empty, and unless `requested_cost_cents` is at
most `investment_ceiling_cents`. An order whose requested cost exceeds the ceiling is refused with
`ERR_ALLOCATION_CEILING_EXCEEDED` and HTTP status 422. Submission is what finalises the fill: the
ordered lines, their cost, the deferred lines and the full-coverage flag are all recomputed at that
moment. An order that is not `DRAFT` when a pledge is filed against it is refused with
`ERR_PRODUCT_ORDER_NOT_DRAFT` at HTTP status 409.

Shipping requires that every share pledge under the order be in `BOUND` or `RELEASED` status — no
pledge may still be merely `HELD` when the truck order leaves — and moves `SUBMITTED` to `SHIPPED`.
Receiving moves `SHIPPED` to `RECEIVED`, requires `expected_product_order_version` matching the
order's current `version` per Section 2.8, and posts stock: each ordered line's inventory position has
its `on_hand_qty` increased by the ordered quantity, and a position is created for the route when the
route holds none for that product yet. The receive write refreshes the route's `inventory_at_risk_cents`.
The stale-version guard matters here because the receive transition's effects depend on the ordered
line quantities the client observed; a superseded view would post a quantity the order no longer
carries. Allocating moves `RECEIVED` to `ALLOCATED` and requires that every share pledge under the
order be `BOUND`; on allocation each pledge becomes `CONSUMED`, each pledge's `sustained_amount_cents` is
recomputed by the mixed-inventory rule below, and each bound credit account's `credit_available_cents`
is recomputed. Cancellation is available from `DRAFT`, `SUBMITTED`, `SHIPPED` or `RECEIVED` and is
terminal; it releases every share pledge under the order to `RELEASED`. `ALLOCATED` and `CANCELLED`
are the two terminal states of this machine.

A share pledge lets a credit account underwrite a slice of a draft replenishment order. A
`FranchiseOwner` or a `RouteSalesRep` files one, naming the `credit_account_id` that will settle the
share, the `pledged_lines` array of `{product_id, qty}` entries the account agrees to settle, and the
`expected_product_order_version` described in Section 2.8. The pledge starts at `pledge_status`
`HELD`, and the filing increments the parent order's `version`. Filing is permitted only while the
order is `DRAFT`; a pledge against any other status is refused with `ERR_PRODUCT_ORDER_NOT_DRAFT`. The
pledged quantity for a product may not exceed the order's ordered quantity for that product, and a
pledge that oversubscribes is refused with `ERR_PLEDGE_OVERSUBSCRIBED` and HTTP status 422. A
`FranchiseOwner` or `FranchiseManager` then advances the pledge: binding confirms the account will
settle its share and moves `HELD` to `BOUND`, while releasing withdraws it and moves `HELD` to
`RELEASED`.

A unit pledged to a replenishment order may be claimed by at most one share pledge, and the rule
`mixed_inventory_plan` enforces that conservation. Pledges under the order that are in `HELD` or `BOUND`
status are considered, in ascending order of their line index and then by ascending `created_at`;
pledges that are `RELEASED` or `CONSUMED` are excluded entirely. Walking the pledges in that order,
each pledged line is matched against the inventory position for the same route and product, and the
quantity the pledge sustains on that line is the smaller of the quantity it pledged and whatever of
the position's `remaining_qty` has not already been claimed by an earlier pledge in the walk —
floored at zero, so a line whose capacity is exhausted sustains nothing. The claimed total for that
product advances by the sustained quantity before the next pledge is considered, and the pledge's
`sustained_amount_cents` increases by the sustained quantity multiplied by the position's
`unit_cost_cents`. Two invariants follow and are worth stating: the quantities sustained across all
pledges for a product never exceed the position's `remaining_qty`, and no pledge's
`sustained_amount_cents` ever exceeds the amount it pledged valued at share-set unit costs.

### 3.7. Product Launches and Route Allocation

A new product enters the catalogue with a `launch_status`: a product flagged `is_new_launch` is
created `ANNOUNCED` and carries a `launch_iso_week`, while a product that is not a launch product is
created directly at `LIVE`. The `sku`, `product_name`, `category`, `unit_cost_cents`,
`retail_price_cents` and `default_warranty_months` are supplied at creation, and the `category` is one
of `DIAGNOSTICS`, `TOOL_STORAGE` or `POWER_TOOLS`. When an `ANNOUNCED` product is ready, a
`FranchiseManager` plans its allocation across the network, supplying the `total_launch_qty` to be
distributed and a `run_priority`. `PRIMARY` plans the launch for the first time; `SECONDARY` re-plans,
and it is refused with `ERR_LAUNCH_ALREADY_ALLOCATED` and HTTP status 409 once the product has already
reached `ALLOCATED` or `LIVE`, so a given product can be planned once per launch run. The planning
write produces one allocation row per eligible route, recomputes each row's `priority_score`,
`allocated_qty` and `launch_risk_band`, and moves the product's `launch_status` to `ALLOCATED`.

The planning rule `launch_allocation_plan` is what distributes the units. Eligibility is narrow: only
routes whose `route_status` is `IN_SERVICE` participate, and `DRAFT`,
`SUSPENDED`, `PENDING_TRANSFER` and `RETIRED` routes are excluded from the pool entirely. Each
eligible route's `priority_score` is the route's tier weight multiplied by its `territory_points` and
divided by one plus its open order count, where the tier weight is 3 for a tier `A` territory, 2 for a
tier `B` territory and 1 for a tier `C` territory; dividing by one plus the open order count means a
route already carrying orders is discounted rather than excluded. Those scores are normalised across
the eligible pool, and each route's initial `allocated_qty` is the floor of the product's
`total_launch_qty` multiplied by that route's normalised weight — a whole number of units, rounded
down. Because the floors do not in general absorb the whole launch quantity, the leftover units — the
launch quantity less the sum of the initial floors — are distributed one unit at a time. Routes are
ranked for that distribution by descending remaining fraction, with ties broken by ascending
`created_at`; the `id` is never consulted. Each route in that order receives one unit before any route
receives a second, and the distribution continues until the leftover is exhausted. A route's
`allocated_amount_cents` is its `allocated_qty` multiplied by the product's `unit_cost_cents`.

The launch risk band is derived from the same score and is attached to the allocation row and to the
route. A route whose `priority_score` is at least 120 is banded `LOW`; one scoring at least 60 but
below 120 is banded `MEDIUM`; anything below 60 is banded `HIGH`. The band boundaries are inclusive on
the low side of each named band, so exactly 120 is `LOW` and exactly 60 is `MEDIUM`. A
`FranchiseManager` may move part of one route's allocation to another eligible route by naming a
`target_route_id` and the `allocated_qty` to move; the source row's quantity is decremented by that
amount, the target row is created or incremented by it, and both rows' `priority_score` and
`launch_risk_band` are recomputed. A manager may also flag a route's allocation for review, or clear
that flag, by setting the row's `review_flag` — the flag is set when a route's launch risk band is
disputed and needs a manager to look at it.

### 3.8. Warranty Claims and Tool Replacement at the Truck

A tool that fails is handled where it was sold. A `RouteSalesRep` files a warranty claim against a
line of a delivered order, naming the `line_index` into the parent order's `lines` array, the
`claim_kind` — `WARRANTY_REPLACEMENT` or `CLAIM` — and a client-supplied `idempotency_key` scoped to
the parent order; a `CLAIM` also names the `apply_to_account_id` of the account that will absorb the
replacement charge, while a `WARRANTY_REPLACEMENT` ignores that field. A new claim starts at
`claim_status` `OPEN` with its `filed_iso_week` stamped at the Monday `00:00:00Z` of the logical
clock's week and its `resolved_iso_week` null. Three conditions bound the filing. The parent order must
be `DELIVERED` or `SETTLED`, so a claim against a draft or merely confirmed order is refused before any
credit arithmetic runs, with `ERR_WARRANTY_ORDER_NOT_DELIVERED` and HTTP status 422. The `line_index`
must fall within the parent order's lines array; one that does not is refused with
`ERR_WARRANTY_LINE_OUT_OF_RANGE` at HTTP status 422. And no non-terminal claim may already stand
against the same order and the same line: a second filing there is refused with
`ERR_WARRANTY_ALREADY_CLAIMED` at HTTP status 409. The idempotency key is the deliberate exception to
that last rule — filing a claim whose `idempotency_key` already exists on the same order replays the
existing claim and sets `is_idempotent_replay` to true rather than creating a duplicate, so a retried
filing is safe.

Submitting a claim prices it under the rule `warranty_replacement_charge`. Submission moves `OPEN` to `SUBMITTED` and requires the claim's
`line_index` to be within the parent order's lines array. Pricing reads the single line named by that
index — other lines of the same order do not contribute — and its product, and computes the elapsed
whole months from the parent order's `sale_iso_week` to the logical clock's week. The claim is inside
warranty when that elapsed count is strictly less than the line's `warranty_terms.months`, and the
strictness is deliberate: a claim whose elapsed months equal the nominal warranty term is outside
warranty, so the replacement charge switches on exactly at the nominal expiry rather than a month
later. Inside warranty the `replacement_charge_cents` is 0. Outside warranty it is the smaller of the
line's `unit_price_cents` and 40 percent of the product's `unit_cost_cents` — a `CAP_RATE` of `0.40`,
rounded down to a whole number of cents. The `warranty_credit_amount_cents` is computed alongside it:
it is the smaller of the line's `unit_price_cents` and 60 percent of the product's `unit_cost_cents` —
a `CREDIT_RATE` of `0.60`, also rounded down to a whole number of cents — and only when the claim's
`claim_kind` is `CLAIM` and its `claim_status` is `APPROVED`; in every other case it is 0.

Resolution moves the claim to a terminal state and, for an approval, writes money under the rule
`warranty_principal_allocation`. Approval by a
`WarrantyAdmin` moves `SUBMITTED` to `APPROVED` and requires that a `CLAIM` name an existing credit
account in `apply_to_account_id`, while a `WARRANTY_REPLACEMENT` carries no such account and
contributes nothing to any balance. On approval the claim's `resolved_iso_week` is stamped with the
Monday `00:00:00Z` of the logical clock's week, and `principal_allocated_cents` is computed under one
of two bases. Under the charge basis, used when the claim's `claim_kind` is `CLAIM`, the allocation
equals the claim's `replacement_charge_cents` and it is written onto the named account as new
principal, increasing that account's `principal_balance_cents` by the allocated amount. Under the
credit basis, used when the claim's `claim_kind` is `WARRANTY_REPLACEMENT`, the allocation equals the
claim's `warranty_credit_amount_cents` and it is credited away from the named account, reducing that
account's `principal_balance_cents` by the allocated amount — but never below zero, because the
allocated amount is capped at the account's current `principal_balance_cents`, so a credit larger than
the outstanding principal is absorbed in part and the unabsorbed remainder simply lapses. After the
write the account's `current_balance_cents` and `credit_available_cents`, the parent order's
`financed_principal_cents` under its final basis, the technician's `revolving_used_cents` and the
franchisee's `outstanding_credit_cents` are all recomputed.

A rejected claim terminates the pipeline without moving money — a `WarrantyAdmin` moves `SUBMITTED` to
`REJECTED`, stamps `resolved_iso_week`, and sets `principal_allocated_cents` to 0 — and a `REJECTED`
claim's `warranty_credit_amount_cents` is 0, as is every claim that is not at once a `CLAIM` and
`APPROVED`. Two backward edges keep the pipeline
honest. An approval may be reopened, moving `APPROVED` back to `SUBMITTED`, clearing
`resolved_iso_week` to null, removing the principal that was previously allocated from the target
account exactly as it was written, and recomputing the parent order's `financed_principal_cents`. A
rejected claim may be resubmitted by the `RouteSalesRep` under its original `idempotency_key`,
provided the key is unchanged from the rejected submission, moving `REJECTED` back to `SUBMITTED` and
clearing `resolved_iso_week`. Approvals and rejections are terminal until they are deliberately
reopened or resubmitted: a decision requested against a claim that is already `APPROVED` or `REJECTED`
is refused with `ERR_CLAIM_ALREADY_TERMINAL` at HTTP status 409, and a reopen requested against a claim
that is in any other status is refused with `ERR_CLAIM_NOT_TERMINAL`, also at HTTP status 409.

### 3.9. The Fixed Order of Refusals

Every request that fails does so under a fixed priority order, and the lowest-numbered failing rule is
the one reported. This matters most where two rules would both be violated by the same request: the
caller must see the earlier rule's identifier, never a later one's.

The first two rules are always evaluated before any business logic. A request whose `X-User-ID` or
`X-User-Role` header is absent, or whose role is unknown, is refused with `ERR_MISSING_USER_CONTEXT`
and HTTP status 400. A request whose acting role is not permitted for the operation, or whose
entity-backed actor does not own the resource being mutated — a `Technician` acting on someone else's
credit account, a `RouteSalesRep` acting on another route's orders — is refused with
`ERR_UNAUTHORIZED` and HTTP status 403. The clock rule follows: a clock change to an instant earlier
than the logical clock is refused with `ERR_WEEK_CLOCK_BEHIND` and HTTP status 422. Resource existence
comes fourth, with the entity-specific 404 identifiers of Section 2.6, and body-shape validation fifth
with `ERR_INVALID_REQUEST` at HTTP status 400. State admissibility comes sixth with `ERR_INVALID_STATE`
at HTTP status 409 and its entity-specific variants `ERR_ROUTE_NOT_IN_SERVICE`,
`ERR_APPLICATION_ALREADY_DECIDED`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_ACCOUNT_NOT_DELINQUENT`,
`ERR_PAYMENT_NOT_BOOKED`, `ERR_CLAIM_ALREADY_TERMINAL` and `ERR_PRODUCT_ORDER_NOT_DRAFT`.

The cross-entity dependency is seventh. Certifying the franchisee is a precondition of activating a
route, filing a resale and qualifying a territory, and a violation is reported as
`ERR_FRANCHISEE_NOT_CERTIFIED` at HTTP status 409 on any of those three operations. Trade-exit safety
is eighth: leaving the trade while any sales order remains in `CONFIRMED` is refused with
`ERR_TRADE_EXIT_OPEN_ORDER` at HTTP status 422. Warranty timing is ninth: filing or deciding a claim
against a parent order that is not yet `DELIVERED` or `SETTLED` is refused with
`ERR_WARRANTY_ORDER_NOT_DELIVERED` at HTTP status 422. Lease completeness is tenth: a lease-kind
application without `requested_term_months` is refused with `ERR_LEASE_TERM_REQUIRED` at HTTP status
422. Uniqueness is eleventh: a collision on `route_code`, `sku`, territory-level product mix or the
one-position-per-product rule is refused with `ERR_UNIQUENESS_VIOLATION` at HTTP status 409, or with
the specific `ERR_ROUTE_CODE_DUPLICATE`, `ERR_SKU_DUPLICATE` or `ERR_INVENTORY_POSITION_DUPLICATE`.
Territory membership of a shop's zip code is twelfth, refused with `ERR_SHOP_ZIP_NOT_IN_TERRITORY` at
HTTP status 400 when a shop is added to a route.

The stock and allocation rules follow. A sales line exceeding the matching position's `remaining_qty`
is refused with `ERR_INSUFFICIENT_INVENTORY` at HTTP status 409, and the rule guards sales-order
creation, sales-order line editing and sales-order advancement alike. A replenishment order whose
`requested_cost_cents` exceeds `investment_ceiling_cents` is refused with
`ERR_ALLOCATION_CEILING_EXCEEDED` at HTTP status 422. A pledge whose pledged quantities exceed the
order's ordered quantities, or a pledge filed against a non-draft order, is refused with
`ERR_PLEDGE_OVERSUBSCRIBED` at HTTP status 422 or `ERR_PRODUCT_ORDER_NOT_DRAFT` at HTTP status 409. A
second launch allocation for a product already `ALLOCATED` or `LIVE` is refused with
`ERR_LAUNCH_ALREADY_ALLOCATED` at HTTP status 409. A payment whose `expected_week_start` is not a
Monday `00:00:00Z` or precedes the current week is refused with `ERR_PAYMENT_WEEK_IN_PAST` at HTTP
status 422. A development round that would open while an earlier round on the same route is still in
force is refused with `ERR_TERRITORY_WINDOW_CONFLICT` at HTTP status 422. A charge-off requested before
the account's charge-off week, or a closure requested with a non-zero balance, is refused with
`ERR_CHARGE_OFF_NOT_DUE` at HTTP status 422.

The fiscal rules come last, and their ordering is deliberate: the account ceiling is checked before
the shared line, and both are checked before the absolute cap. A sales order whose
`financed_principal_cents` exceeds the target account's `credit_available_cents` is refused with
`ERR_ACCOUNT_LIMIT_EXCEEDED` and HTTP status 402; the rule is evaluated when the order is advanced.
A revolving financed amount exceeding the technician's `revolving_available_cents` is refused with
`ERR_CREDIT_LIMIT_EXCEEDED` and HTTP status 402, and this rule guards both the advancement of a sales
order and the minting of a credit account. A requested limit above `CREDIT_ABSOLUTE_CAP_CENTS` is
refused with `ERR_CREDIT_REQUEST_ABOVE_CAP` and HTTP status 402, and this rule guards both the filing
of a credit application and the decision of one. Because the ceiling rules are evaluated after every
structural, state and safety rule, a request that is both malformed and over-limit is reported as
malformed, and a request that is both over the account ceiling and over the shared line is reported
against the account first.

A franchisor-draft collection that needs the franchisee's fallback location but finds none is the one
refusal that does not fit the ladder above: it is raised when the collection is attempted, with
`ERR_FALLBACK_LOCATION_MISSING` and HTTP status 422, and it depends on the franchisee having no
`ACTIVE` shop on any of its routes.

## 4. Endpoint Definitions

Every endpoint below is mounted under the `/retail` prefix. Two status-code conventions apply
throughout. An operation that creates a new, stand-alone resource, or that adds a new and distinct
resource to a collection, returns `201 Created` — a product, a franchisee, a route, a shop, a
technician, a credit application, a credit account, a payment booking, a sales order, a warranty
claim, an inventory position, a replenishment order and a share pledge are all created that way.
Every other successful operation, including all state-advancing actions and all updates to an existing
resource, returns `200 OK`. Reads return `200 OK`. The tables below name the capability and the
authorised roles only; the request payload each endpoint accepts, the effects it produces and the
conditions under which it is refused are specified in Sections 2 and 3.

The request payload keys accepted by each endpoint are those named in the narratives of Section 3:
the clock capability takes `current_utc`; product creation takes `sku`, `product_name`, `category`,
`unit_cost_cents`, `retail_price_cents`, `default_warranty_months`, `is_new_launch` and the optional
`launch_iso_week`; franchisee creation takes `legal_name`; the training action takes `action` and
`training_points`; route creation takes `route_code`, `route_tier`, `zip_codes`, `visit_weekday`,
`truck_label`, `inventory_invested_cents`, `mix_plan`, `territory_model` and the optional
`territory_points`; route update takes those same attributes as optional replacements; the route
lifecycle action takes `action` and the optional `expected_route_version`; the territory action takes
`action` and `territory_points`; the resale action takes `action` with the optional
`buyer_training_status` and `buyer_training_points`; shop creation takes `shop_name`, `street_line`
and `zip_code`; shop update takes `shop_name`, `street_line` and `shop_status`; technician onboarding
takes `full_name`, `current_shop_location_id`, `credit_line_limit_cents`, `months_in_trade` and
`employment_verified`; technician update takes `full_name`, `credit_line_limit_cents`,
`months_in_trade` and `employment_verified` as optional replacements; the technician standing action
takes `action` and the optional `target_shop_location_id`; credit application filing takes
`technician_id`, `requested_limit_cents`, `requested_kind`, the optional `requested_term_months`,
`employment_verified`, `months_in_trade`, `prior_delinquency_count` and `decision_source`; the
application action takes `action`; account minting takes `expected_application_version`; the account
posture action takes `action`; payment booking takes `amount_cents`, `collection_source` and
`expected_week_start`; the payment action takes `action`; sales-order creation takes `technician_id`,
`credit_account_id`, `mix_profile` and `lines`; sales-order editing takes the optional `mix_profile`
and `lines`; the sales-order action takes `action` and the optional `expected_sales_order_version`;
warranty filing takes `line_index`, `claim_kind`, `idempotency_key` and the optional
`apply_to_account_id`; the claim action takes `action`; the inventory-position write takes
`product_id`, `on_hand_qty` and the optional `inventory_position_id`; replenishment-order creation
takes `mix_profile`, `investment_ceiling_cents` and `requested_lines`; the replenishment action takes
`action` and the optional `expected_product_order_version`; pledge filing takes `credit_account_id`,
`pledged_lines` and `expected_product_order_version`; the pledge action takes `action`; launch
planning takes `total_launch_qty` and `run_priority`; reallocation takes `target_route_id` and
`allocated_qty`; and launch review takes `review_flag`.

Filter and pagination query parameters are accepted by the list endpoints: products filter by
`category` and `is_new_launch`; franchisees by `training_status`; routes by `franchisee_id`,
`route_status`, `territory_development_status` and `resale_status`; shops by `route_id`, `shop_status`
and `zip_code`; technicians by `current_shop_location_id` and `technician_status`; credit
applications by `application_status`, `decision_source` and `technician_id`; credit accounts by
`technician_id`, `account_status`, `account_kind`, `recourse_holder` and `application_id`; payments by
`payment_status` and `collection_source`; finance charges by `charge_status`; sales orders by
`route_id`, `technician_id`, `credit_account_id` and `order_status`; warranty claims by `order_id`,
`apply_to_account_id`, `claim_status` and `claim_kind`; inventory positions by `route_id` and
`product_id`; replenishment orders by `route_id` and `product_order_status`; pledges by
`product_order_id`, `credit_account_id` and `pledge_status`; and launch allocations by `product_id`,
`route_id`, `allocation_status` and `launch_risk_band`. Every list endpoint additionally accepts
`limit` and `offset` as described in Section 2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/retail/_clock/set_current_utc` | Test-driving endpoint. | PlatformAdmin |
| POST | `/retail/products` | Create a product. | PlatformAdmin |
| GET | `/retail/products` | List products. | Any |
| GET | `/retail/products/{id}` | Get a product. | Any |
| PUT | `/retail/products/{id}` | Update a product. | PlatformAdmin |
| POST | `/retail/franchisees` | Create a franchisee. | PlatformAdmin |
| GET | `/retail/franchisees` | List franchisees. | PlatformAdmin, FranchiseManager, CreditOfficer |
| GET | `/retail/franchisees/{id}/draft-summary` | Franchisor draft eligibility summary for a franchisee. | PlatformAdmin, FranchiseManager, CreditOfficer |
| GET | `/retail/franchisees/{id}` | Get a franchisee. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| POST | `/retail/franchisees/{id}/training` | Advance franchisee training. | FranchiseOwner |
| POST | `/retail/franchisees/{id}/routes` | Create a route under a franchisee. | FranchiseOwner |
| GET | `/retail/routes` | List routes. | Any |
| GET | `/retail/routes/{id}` | Get a route. | Any |
| PUT | `/retail/routes/{id}` | Update route attributes. | FranchiseOwner |
| POST | `/retail/routes/{id}/status` | Advance a route's lifecycle. | FranchiseOwner, FranchiseManager |
| POST | `/retail/routes/{id}/territory` | Advance territory development. | FranchiseOwner, FranchiseManager |
| POST | `/retail/routes/{id}/resale` | File a territory resale application, or decide one. | FranchiseOwner, FranchiseManager |
| POST | `/retail/routes/{id}/shop-locations` | Add a repair shop to a route. | FranchiseOwner |
| GET | `/retail/shop-locations` | List shops. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| GET | `/retail/shop-locations/{id}` | Get a shop. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| PUT | `/retail/shop-locations/{id}` | Update a shop. | FranchiseOwner |
| GET | `/retail/shop-locations/{id}/technicians` | List the technicians currently working at a shop. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| POST | `/retail/technicians` | Onboard a technician at a shop. | FranchiseOwner |
| GET | `/retail/technicians` | List technicians. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| GET | `/retail/technicians/{id}` | Get a technician. | Any |
| PUT | `/retail/technicians/{id}` | Update a technician's attributes. | FranchiseOwner |
| POST | `/retail/technicians/{id}/status` | Advance a technician's standing. | FranchiseOwner, FranchiseManager |
| POST | `/retail/shop-locations/{id}/credit-applications` | File a credit application for a technician at a shop. | FranchiseOwner, CreditOfficer |
| GET | `/retail/credit-applications` | List credit applications. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| GET | `/retail/credit-applications/{id}` | Get a credit application. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| POST | `/retail/credit-applications/{id}/status` | Advance an application. | CreditOfficer, FranchiseOwner |
| POST | `/retail/credit-applications/{id}/accounts` | Mint a credit account against an approved application. | CreditOfficer |
| GET | `/retail/credit-accounts` | List credit accounts. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, Technician |
| GET | `/retail/credit-accounts/{id}` | Get a credit account, accruing any finance charge due and applying the charge-off sweep before the read. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, Technician |
| POST | `/retail/credit-accounts/{id}/status` | Advance an account's posture. | CreditOfficer, FranchiseManager |
| POST | `/retail/credit-accounts/{id}/payments` | Book a scheduled payment against an account. | RouteSalesRep |
| GET | `/retail/credit-accounts/{id}/payments` | List the payments on an account. | Any |
| GET | `/retail/credit-accounts/{id}/finance-charges` | List the finance charges on an account. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, Technician |
| POST | `/retail/credit-accounts/{id}/payments/{paymentId}/status` | Advance a payment. | RouteSalesRep, FranchiseManager, CreditOfficer |
| POST | `/retail/routes/{id}/sales-orders` | Create a draft sales order on a route. | RouteSalesRep |
| GET | `/retail/sales-orders` | List sales orders. | Any |
| GET | `/retail/sales-orders/{id}` | Get a sales order. | Any |
| PATCH | `/retail/sales-orders/{id}` | Replace a draft order's line set. | RouteSalesRep |
| POST | `/retail/sales-orders/{id}/status` | Advance a sales order. | RouteSalesRep |
| POST | `/retail/sales-orders/{id}/warranty-claims` | File a warranty claim. | RouteSalesRep |
| GET | `/retail/warranty-claims` | List warranty claims. | Any |
| POST | `/retail/sales-orders/{id}/warranty-claims/{claimId}/status` | Advance a warranty claim. | RouteSalesRep, WarrantyAdmin |
| POST | `/retail/routes/{id}/inventory-positions` | Create a stock position on a route's truck, or adjust one. | FranchiseOwner, FranchiseManager |
| GET | `/retail/inventory-positions` | List inventory positions. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| POST | `/retail/routes/{id}/product-orders` | Create a draft replenishment order for a route's truck. | FranchiseOwner |
| GET | `/retail/product-orders` | List replenishment orders. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| GET | `/retail/product-orders/{id}` | Get a replenishment order. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| POST | `/retail/product-orders/{id}/status` | Advance a replenishment order. | FranchiseOwner, FranchiseManager |
| POST | `/retail/product-orders/{id}/pledges` | Pledge an account's share of a draft replenishment order. | FranchiseOwner, RouteSalesRep |
| GET | `/retail/pledges` | List share pledges. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| GET | `/retail/credit-accounts/{id}/pledges` | List the share pledges filed by an account (its own pledges against draft replenishment orders). | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, RouteSalesRep |
| POST | `/retail/pledges/{id}/status` | Advance a pledge: action=BIND confirms the account will settle its share; action=RELEASE withdraws it. | FranchiseOwner, FranchiseManager |
| POST | `/retail/products/{id}/launch-allocations` | Plan a launch allocation across eligible in-service routes. | FranchiseManager |
| GET | `/retail/launch-allocations` | List launch allocations. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer |
| POST | `/retail/launch-allocations/{id}/reallocate` | Move part of a route's launch allocation to another eligible route. | FranchiseManager |
| POST | `/retail/launch-allocations/{id}/review` | Flag or clear a route's launch allocation for manager review. | FranchiseManager |


## 5. Error Code Catalogue

Every rejection in this API is identified by one of the identifiers below. The conditions that trigger
each one are stated with the rule they guard — in Section 2 for the global rules and in Section 3 for
the business rules — and are deliberately not repeated here; a caller should read the narrative that
governs the operation it attempted.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_WEEK_CLOCK_BEHIND` | 422 |
| `ERR_FRANCHISEE_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_SHOP_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_ORDER_NOT_FOUND` | 404 |
| `ERR_INVENTORY_POSITION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ROUTE_NOT_IN_SERVICE` | 409 |
| `ERR_ROUTE_ALREADY_IN_SERVICE` | 409 |
| `ERR_APPLICATION_ALREADY_DECIDED` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_NOT_DELINQUENT` | 409 |
| `ERR_ACCOUNT_NOT_SUSPENDED` | 409 |
| `ERR_ACCOUNT_ALREADY_CLOSED` | 409 |
| `ERR_PAYMENT_NOT_BOOKED` | 409 |
| `ERR_PAYMENT_NOT_COLLECTED` | 409 |
| `ERR_CLAIM_ALREADY_TERMINAL` | 409 |
| `ERR_CLAIM_NOT_TERMINAL` | 409 |
| `ERR_PRODUCT_ORDER_NOT_DRAFT` | 409 |
| `ERR_ORDER_NOT_CONFIRMABLE` | 409 |
| `ERR_ORDER_NOT_DELIVERABLE` | 409 |
| `ERR_ORDER_NOT_SETTLEABLE` | 409 |
| `ERR_TERRITORY_NOT_QUALIFIED` | 409 |
| `ERR_RESALE_NOT_PENDING` | 409 |
| `ERR_RESALE_ALREADY_PENDING` | 409 |
| `ERR_TECHNICIAN_NOT_ACTIVE` | 409 |
| `ERR_TECHNICIAN_EXITED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FRANCHISEE_NOT_CERTIFIED` | 409 |
| `ERR_TRADE_EXIT_OPEN_ORDER` | 422 |
| `ERR_WARRANTY_ORDER_NOT_DELIVERED` | 422 |
| `ERR_LEASE_TERM_REQUIRED` | 422 |
| `ERR_UNIQUENESS_VIOLATION` | 409 |
| `ERR_ROUTE_CODE_DUPLICATE` | 409 |
| `ERR_SKU_DUPLICATE` | 409 |
| `ERR_INVENTORY_POSITION_DUPLICATE` | 409 |
| `ERR_SHOP_ZIP_NOT_IN_TERRITORY` | 400 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_ALLOCATION_CEILING_EXCEEDED` | 422 |
| `ERR_PLEDGE_OVERSUBSCRIBED` | 422 |
| `ERR_LAUNCH_ALREADY_ALLOCATED` | 409 |
| `ERR_PAYMENT_WEEK_IN_PAST` | 422 |
| `ERR_TERRITORY_WINDOW_CONFLICT` | 422 |
| `ERR_CHARGE_OFF_NOT_DUE` | 422 |
| `ERR_ACCOUNT_LIMIT_EXCEEDED` | 402 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_CREDIT_REQUEST_ABOVE_CAP` | 402 |
| `ERR_ACCOUNT_HAS_BALANCE` | 422 |
| `ERR_FALLBACK_LOCATION_MISSING` | 422 |
| `ERR_EMPTY_MIX_LINES` | 422 |
| `ERR_WARRANTY_LINE_OUT_OF_RANGE` | 422 |
| `ERR_WARRANTY_ALREADY_CLAIMED` | 409 |
| `ERR_CERTIFICATION_POINTS_SHORT` | 422 |
