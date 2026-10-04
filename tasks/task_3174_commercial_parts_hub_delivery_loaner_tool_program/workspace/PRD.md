# Commercial Parts Hub Delivery & Loaner Tool Program API — Product Requirements Document

## 1. Introduction

Repair shops live and die by whether the right part reaches the bay before the vehicle is promised back to its owner. This platform exists to make that promise keepable for the professional installer: it sets up a commercial account for a shop with negotiated credit terms and a delivery service level, then routes every parts order through the cheapest inventory node that can still meet the quoted window — the shop's own counter, a surrounding hub, a mega-hub, or a distribution center. Because the deep assortment that a shop actually needs rarely lives on a single shelf, the system is designed around a hub-and-mega-hub topology in which warehouses feed the stores around them inside fixed delivery cutoffs.

The commercial relationship is more than a price list. Accounts carry revolving credit that must never be quietly overspent, net-terms receivables that age into credit suspension if left unpaid, and a loaner tool program that puts specialist equipment in a technician's hands against a refundable deposit. Every one of those surfaces moves money — a deposit held at checkout, a wear-adjusted forfeiture at inspection, a core credit posted against a returned water pump, a warranty replacement honored without a receipt. The same system therefore has to be a small ledger as much as a catalogue, and it has to keep the ledger conserved while the physical world (drivers, tools, cores, warranty windows) moves around it.

This document specifies the API that exposes all of it: catalogue and fitment lookup across supersession chains and competitor interchange numbers, order authoring and reservation, driver route construction and dispatch, tool and core return processing, warranty registration, and commercial sales-representative coverage. It is written for the engineer who will implement the service, so it states the exact enumeration values, error identifiers and monetary rules the automated contract depends on.

## 2. Global Specifications & System-Wide Principles

Everything in this section applies uniformly across every resource and every operation described later. Where a subsections states a rule, that rule overrides any looser reading a workflow narrative might suggest.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` states the capacity in which they are acting. Both headers are mandatory, and the role named must be one of the declared roles. If either header is absent, or if the role is not a recognized role name, the request is refused with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are valid but the caller's role is not among the roles authorized for the target operation, the request is refused with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes eight role names, spelled exactly as follows: `CommercialSalesRep`, `DeliveryDriver`, `ToolCribAttendant`, `CreditAnalyst`, `RouteDispatcher`, `PartsCategoryManager`, `PlatformAdmin`, and `Any`.

The identity carried in `X-User-ID` means different things for different roles, and this distinction governs every ownership check in the system.

When `X-User-Role` is `CommercialSalesRep`, `X-User-ID` is the `id` of the acting `SalesRep`. Ownership checks on any resource that references a `SalesRep` — specifically a `RepCoverage`, which is reached through its `rep_id` — compare that field to `X-User-ID`.

For every other role the identifier is opaque. When `X-User-Role` is `DeliveryDriver`, `ToolCribAttendant`, `CreditAnalyst`, `RouteDispatcher`, `PartsCategoryManager`, `PlatformAdmin`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example where a transition stamps an operator reference) but does not compare it to any entity's `id`.

A `CommercialSalesRep` exclusively owns shop-facing writes: creating accounts, writing and progressing orders, opening core returns, recording warranties, assigning representative coverage, registering vehicles and reps, and requesting loaner tools. A `DeliveryDriver` owns the road: dispatching and delivering orders, delivering or missing route stops, moving cores into transit, and receiving loaner tools back. A `ToolCribAttendant` owns the crib and the core bench: the tool catalogue, tool fitments, wear adjustments and resets, tool inspection, loan closure and forfeiture, and core inspection and rejection. A `CreditAnalyst` owns credit and ledger outcomes: placing and releasing holds, restoring suspended accounts, closing and archiving accounts, adjusting deposits on checked-out loans, posting core credits, and voiding orders that have reached `ALLOCATED` or `PICKING`. A `RouteDispatcher` owns route construction and stop sequencing. A `PartsCategoryManager` owns the catalogue and stock: parts, vehicle fitments, interchange numbers, supersessions, stores, and inventory lines. `PlatformAdmin` operates only the system clock and the business-day epoch and is not a commercial actor. `Any` is read-only and shares all GET access with every authenticated role.

Account master data updates — amendments to `shop_name`, `billing_address`, `shipping_address`, `credit_limit_cents`, `credit_terms_days` or `delivery_service_level` — are shared between `CommercialSalesRep` and `CreditAnalyst`.

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

List responses are paged through query parameters. `limit` caps how many items a single page returns; when omitted it defaults to 10, and any value supplied must be at least 1 and at most 100. `offset` states how many leading items to skip and defaults to 0. Every list endpoint sorts its results by creation timestamp ascending unless the endpoint's own description says otherwise. Paged and non-paged list responses both carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity Conventions

Most persisted resources — `CommercialAccount`, `Vehicle`, `Part`, `Store`, `InventoryItem`, `SalesRep`, `RepCoverage`, `PartOrder`, `ToolLoan`, `ToolCatalog`, `CoreReturn`, `RouteStop`, and `ServiceRoute` — share a common audit spine:

- `id` is a server-minted UUID and carries no type prefix or mnemonic.
- `created_at` is an ISO 8601 UTC timestamp with exactly three fractional digits.
- `updated_at` is an ISO 8601 UTC timestamp with exactly three fractional digits, refreshed on every mutation of the resource.
- `version` is an integer that starts at its creation value and increments by one on every modification. It is the anchor for the optimistic concurrency checks described in §2.9.

Three entity types are deliberately slimmer. A `ToolFitment`, a `PartInterchange`, and a `PartFitment` are child records that carry only `id` and `created_at`; neither `updated_at` nor `version` exists on them, and no mutation of a parent propagates a version to them. A `WarrantyRegistration` is likewise slim, carrying only `id` and `created_at`; once registered it is not modified. Derived mutations count: when a recompute writes `credit_exposure_cents`, `account_posture`, `parts_subtotal_cents`, or any other derived field on a resource, that write refreshes the resource's `updated_at` and increments its `version` exactly as a client-supplied change would.

### 2.5. Hierarchical Consistency and the Cascading Void

Relationships are not declared as schemas to the client; they are implied by the identifiers a payload carries. An order references its shop through the `account_id` it is written with; a core return references its order through `order_id`; a route stop references its route through `route_id`. What matters is that a state change on one resource is frequently not local.

When an account is placed on hold, the consequence cascades downward. Every `PartOrder` on that account sitting in `DRAFT`, `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED` is moved to `VOID`. For each of those orders that had reserved units, the reserved source's `reserved_units` is released by the order's `reserved_unit_count`, and the reserved source's `committed_units_today` is reduced by the same count. For each voided order that carried a non-null `service_route_id`, the `RouteStop` it was dropped at is moved to `REJECTED` and every later stop on that `ServiceRoute` is re-derived — `stop_sequence`, `projected_arrival_at`, `projected_departure_at`, and `lateness_minutes` are recomputed. Only after the whole cascade completes is the account's `credit_exposure_cents` recomputed.

The same downward-propagation pattern holds elsewhere. Rejecting a stop removes it from its route and re-derives every later stop. Missing a stop pushes its orders back to `CONFIRMED` and re-derives the stops behind it. Cancelling a route turns every stop on it to `REJECTED` and pushes every `DISPATCHED` order on it back to `CONFIRMED`. Superseding a part rewrites the `supersession_depth` of every part whose forward chain passes through it. In each case the parent's write is the trigger and the children are reconciled without a separate client request.

### 2.6. The Revolving Credit Ledger and Account Posture

Each `CommercialAccount` is governed by a revolving credit ceiling — `credit_limit_cents` — and by a derived posture — `account_posture` — that is computed by the server and can never be set directly by a client. The posture enumerates `OPEN`, `ON_HOLD`, `CREDIT_SUSPENDED`, and `CLOSED`.

The exposure the ceiling is measured against is `credit_exposure_cents`, a read-only figure. It is the sum, over this account's `PartOrder`s in `DRAFT`, `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED`, of each order's `parts_subtotal_cents`, plus the sum, over this account's `ToolLoan`s whose `deposit_state` is `HELD`, of each loan's `deposit_amount_cents`. Orders in `DELIVERED`, `RETURNED` or `VOID` contribute nothing: they have left the provisional exposure pool and moved onto the receivable.

A second derived figure, `deposit_liability_cents`, is the sum over `ToolLoan`s with `deposit_state` `HELD` of each loan's `deposit_amount_cents` less its `deposit_forfeited_cents`. The store's conserved deposit position is `petty_cash_cents` minus `deposit_liability_cents`; a correct implementation keeps that difference at zero at rest.

The receivable is `receivable_balance_cents`, the sum of `captured_cents` over all non-`VOID` invoices on the account. When `receivable_balance_cents` is above zero and the account's oldest `PartOrder.delivered_payment_due_at` falls strictly earlier than the logical clock minus the sum of `credit_terms_days` and a 30-day aging grace, the posture derives to `CREDIT_SUSPENDED`. If that oldest due instant is exactly the allowed span before the clock, the account is not suspended — the test is strictly earlier. An account already in `CLOSED` is terminal and never re-derives. An account in `ON_HOLD` stays `ON_HOLD` until it is explicitly released, even if the aging condition would otherwise push it elsewhere. `ON_HOLD` is only ever set by the hold operation and only ever cleared by the release operation. The archival flag `is_archived` is a soft-delete marker that hides the account from default list reads while leaving it addressable by id.

### 2.7. Pricing, Rounding and Monetary Precision

Every monetary value in the system is an integer number of cents. The only rounding primitive is round-half-up to the cent, and it is applied at exactly the points named in the calculation rules in §3 and nowhere else — where a formula does not name a rounding point, no rounding takes place. Ceiling is used only where a rule explicitly names it, and never as a general substitute for round-half-up.

Orders are priced by a tier discount band. The band is a step function of the account's `order_sequence` captured at creation, not a marginal schedule: the entire basket takes a single band's rate. The four bands and their `discount_rate` and `promise_multiplier` are: `BRONZE` at a discount rate of 0.00 and a promise multiplier of 1.00; `SILVER` at 0.05 and 0.80; `GOLD` at 0.10 and 0.60; `PLATINUM` at 0.15 and 0.50. A new account starts at the `BRONZE` tier. Two readings of the same order exist: while the order's `status` is `DRAFT` or `CONFIRMED` it is read provisionally, with each line rounded independently; from `ALLOCATED` onward it is read finally, with discount re-based on one order-level rounding of the summed list amount. The two readings can differ by up to one cent per line for identical input, and the final reading deliberately leaves `unit_price_cents` at its provisional per-line value, so the order's subtotal and the sum of its line unit prices disagree after allocation. This divergence is intended, not a defect.

### 2.8. Delivery Routing, Promise Windows and Daily Capacity

Order routing picks the shallowest inventory node that can still meet the shop's window, and it reads the account's home store as its starting point. The account's home store is a `Store`; a store may itself be a satellite, a `HUB`, a `MEGA_HUB`, or a `DC`, and it may name a parent through `hub_store_id`. Each store carries a `delivery_radius_miles`, a `cutoff_hour_local`, a `cutoff_buffer_minutes`, a `promise_time_minutes`, a `daily_capacity_units`, a `committed_units_today` counter, and a `capacity_epoch_at` instant at which that counter was last reset.

Two delivery bands are in play. The `SHOP_DELIVERY` band covers deliveries from 0 up to and including 15 miles and can be sourced from the shop's own store, its hub, the hub's mega-hub, or the mega-hub's distribution center. Beyond 35 miles nothing routes and the order is `UNROUTABLE`. A store's `committed_units_today` may never exceed its `daily_capacity_units`; that ceiling is re-checked after reservation. The business-day boundary itself is observable through an operator relay that resets `committed_units_today` to zero for stores whose `capacity_epoch_at` is at least 24 hours behind the requested instant and stamps `capacity_epoch_at` forward for those stores only.

### 2.9. Optimistic Concurrency Control

Writes that attach new work to a shared parent take an explicit expected-version field and refuse the request if the parent has moved on since the client last read it. The rules are precise and are enumerated in §3 alongside the workflows they guard; what follows is the general mechanism.

Creating a parts order against an account requires `expected_account_version`, the client's last-observed `version` of that `CommercialAccount`. If the account's current `version` no longer matches, the create is refused with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Checking out a loaner tool against an account carries the same `expected_account_version` requirement and the same rejection. Attaching a stop to a route requires `expected_route_version`, the client's last-observed `version` of that `ServiceRoute`, and a mismatch is refused with `ERR_STALE_ROUTE_VERSION` (HTTP 412). The guard is also enforced on the order update, confirm and allocate writes, on the account master-data update, on the loan update, and on route planning, all through the account- or route-version field appropriate to their parent. The framing is purely one of staleness: the server rejects a write made against a parent version the client has not observed. Operations that are not listed as parent-versioned writes take no version field.

### 2.10. Nested Resource Retrieval and Path Validation

When a request addresses a resource through a path that contains more than one identifier, the identifiers are validated left to right in path order, and the first one that does not resolve to an existing resource determines the failure. That failure is a 404 carrying the not-found identifier for the kind of resource the failing segment names: `ERR_COMMERCIAL_ACCOUNT_NOT_FOUND`, `ERR_PART_ORDER_NOT_FOUND`, `ERR_TOOL_LOAN_NOT_FOUND`, `ERR_CORE_RETURN_NOT_FOUND`, `ERR_SERVICE_ROUTE_NOT_FOUND`, `ERR_ROUTE_STOP_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_SALES_REP_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_TOOL_CATALOG_NOT_FOUND`, or `ERR_INVENTORY_ITEM_NOT_FOUND`. A malformed request body on any of these returns `ERR_INVALID_REQUEST` (HTTP 400) instead. The parent segment is always checked before the child segment, so a request for a stop beneath a non-existent route fails on the route, never on the stop.

### 2.11. The Tool Crib Ledger — Deposits, Wear and Conservation

The loaner tool program maintains its own money movement. A `ToolCatalog` entry carries a standard `deposit_amount_cents` taken at checkout, plus a `replacement_unit_cost_cents` used as the fallback base for a replacement charge. Each catalogue tool accumulates `wear_accumulated`, and on every return whose condition is `WORN` or `BROKEN` that figure advances by 0.4. The accumulated wear selects a `wear_band` of `LEVEL_1`, `LEVEL_2`, `LEVEL_3`, `LEVEL_4`, or `LEVEL_5`, and the band in turn selects three derived values: a `wear_multiplier_rate` between 1.00 and 2.00, a `wear_forfeiture_rate` between 0.00 and 1.00, and a `wear_grace_period_hours` that falls from 48 down to 12 as wear rises. The catalogue also holds a `replacement_part_id`, re-selected whenever the band advances.

Money taken as a deposit is parked in the account's `petty_cash_cents`. When a loan is closed with a refund, `petty_cash_cents` is drawn down by the deposit less whatever was forfeited. When a deposit is forfeited against a live receivable the money is applied to that balance rather than returned. Whatever path is taken, the pair (`petty_cash_cents`, `deposit_liability_cents`) moves together so the store's conserved deposit position is untouched.

### 2.12. Validation Precedence

When an operation is subject to several checks, they are not independent — they are evaluated in a fixed precedence and the first failing check determines the error the caller sees. Implementations that evaluate them in a different order, or that batch them and report an arbitrary failure, will disagree with the contract whenever a request violates more than one rule at once.

The precedence runs in the following sequence, and within each step the individual checks of that step are applied in the order given.

Authentication and authorization come first. The presence and validity of `X-User-ID` and `X-User-Role` is checked before anything else, then the caller's role against the endpoint's authorized roles. A request missing headers never reaches a permission check, and a request with an unauthorized role never reaches a resource lookup.

Resource existence comes next, validated left to right along the path as §2.10 describes. A request naming a non-existent parent fails on the parent's not-found identifier rather than on a child's, and a malformed body on any of these endpoints returns the generic invalid-request error rather than a not-found identifier.

State preconditions follow. The target resource must be in the state its transition starts from, and a state mismatch is the error the caller sees even when a later business rule would also have failed. This is why, for example, an order that is neither `DRAFT` nor `CONFIRMED` reports a not-voidable error rather than a reservation error.

Business rules then apply in this order. A hazardous part on a `DELIVERY_DESK` order is rejected before fitment is considered. Fitment year-range validity is checked before fitment matching. Order-line fitment matching precedes supersession-chain validity. Supersession-chain validity — target existence, then target terminality, then cycle-freedom — precedes the archive guard. The archive guard precedes stock availability. Stock reservability precedes the same-day slot rule, which in turn precedes the daily-capacity ceiling. The return window precedes core-quantity sufficiency. Delivery-window well-formedness precedes the stop-window overlap test and the coverage overlap test, and the driver route conflict follows those. The credit-limit ceiling precedes the receivable-balance demand. Warranty expiry precedes the deposit-versus-charge comparison. The positive line reference precedes the destination identifier match, which precedes the account-band match and the delivery-address match. Returnability of parts precedes the restocking-fee misapplication check, which is deliberately evaluated last among the core-return rules. The 30-minute rollback window is checked alongside the state and stop-state conditions that gate refit and stop rejection.

The optimistic concurrency guard is the final step. For a parent-versioned write, the supplied expected version is compared against the parent's current `version` only after the checks above have passed, and a mismatch returns the stale-version error of §2.9 rather than whatever business error might otherwise have been due.

## 3. Business Logic & Workflows

The subsections below follow the commercial relationship from the shop counter outward: setting up an account and the people who serve it, building the catalogue it buys from, writing and pricing an order, choosing which warehouse can supply it, running the truck that delivers it, and closing the loop on the tools and cores that come back. Rules are stated where the workflow needs them rather than grouped by kind, so a reader assembling an implementation should read the sections in order at least once.

### 3.1. Account Onboarding, Commercial Terms and Representative Coverage

A `CommercialSalesRep` opens a shop's account by supplying the shop's legal identity and its commercial terms in one payload. The legal identity is `shop_name`, a `tax_id` that must be unique across the whole customer base, a `billing_address`, and an optional `shipping_address`. The commercial terms are the `home_store_id` of the Commercial Parts Store the account is homed to, the `credit_limit_cents` ceiling, the `credit_terms_days` net window, and the `delivery_service_level` the shop has bought.

`credit_terms_days` maps to conventional net terms — 30 is `NET_30`, 45 is `NET_45`, and 60 is `NET_60` — and the same number is later added to a delivery instant to derive when payment falls due. `delivery_service_level` is one of `DELIVERY_DESK`, `SHOP_DELIVERY`, `HUB_DAILY`, or `HOTSHOT`, and its value changes both the fee treatment and the promise window in ways described in §3.4. When `shipping_address` is omitted it is stored as null and falls back to `billing_address` for dispatches; it must never be silently populated with the account's own home store when an order is delivered, because a delivery address that resolves to a store belonging to some unrelated account is a hard rejection — see the delivery discussion in §3.4 for the exact rule and its identifier.

Creation establishes the account's derived furniture in one shot: `tier` starts at `BRONZE`, `petty_cash_cents` starts at 0, `order_sequence` starts at 0, and `is_archived` starts false. The account's `account_posture` is then derived by the rule in §2.6, and a fresh account with no orders, no loans and a zero receivable derives to `OPEN`.

Amending terms later is a shared write, available to both `CommercialSalesRep` and `CreditAnalyst`. Any subset of `shop_name`, `billing_address`, `shipping_address`, `credit_limit_cents`, `credit_terms_days`, and `delivery_service_level` may be changed, and the request must carry `expected_account_version`. After the amendment the account's `account_posture` is re-derived. Two derived instants follow the account rather than any single order: `next_cutoff_at`, the next delivery cutoff instant for the account's schedule, and, on each order, `promised_at`.

A `PartsCategoryManager` creates the physical network the account draws on. A store is registered with a `store_code` that is unique across stores, a display `name`, and a `store_type` of `SATELLITE`, `HUB`, `MEGA_HUB`, or `DC`. Its delivery characteristics are `delivery_radius_miles`, `cutoff_hour_local` (defaulting to 15), `cutoff_buffer_minutes` (defaulting to 30), `promise_time_minutes`, and `daily_capacity_units`. Its place in the replenishment chain is `hub_store_id`, the hub or mega-hub it is replenished from, which is null for a hub, a mega-hub or a DC. The `cutoff_hour_local` field is what turns a calendar date into a cutoff instant: the cutoff falls at that local hour on the date of the request, and the ordering window actually closes `cutoff_buffer_minutes` before it. On creation `committed_units_today` is 0 and `is_archived` is false; `capacity_epoch_at` begins at the fixed startup instant `2026-09-01T00:00:00Z`.

Sales coverage is modelled as an explicit, dated assignment. A `SalesRep` is created with an `email` unique across reps, a `full_name`, a `district_code`, and a `home_store_id` naming the store they report to. The rep's `active_account_count` is derived, never supplied: it counts the non-archived `CommercialAccount`s whose `home_store_id` is assigned to that rep on the current coverage date.

A `RepCoverage` row ties a specific `rep_id` to a specific `account_id` for a window that runs from `effective_from` up to `effective_to`, which must be strictly after `effective_from`. Its `coverage_posture` — `ACTIVE`, `SCHEDULED`, or `EXPIRED` — is derived from the logical clock against that window rather than stored by a client: a window whose start is still in the future is `SCHEDULED`, one spanning the current instant is `ACTIVE`, and one whose end has passed is `EXPIRED`.

New coverage windows must not collide. A request to record coverage for an account whose window would overlap an existing non-`EXPIRED` window for that same account is refused with `ERR_COVERAGE_OVERLAP` (HTTP 409). The same overlap check guards the moment a `SCHEDULED` window would start: a scheduled row advances to `ACTIVE` only when the logical clock has reached its `effective_from` (otherwise `ERR_COVERAGE_NOT_STARTED`) and only when no other `ACTIVE` row for the same account spans that instant (otherwise `ERR_COVERAGE_OVERLAP`). A window leaves `ACTIVE` for `EXPIRED` only once the logical clock is strictly past its `effective_to`; a request to expire it earlier is refused with `ERR_COVERAGE_STILL_OPEN`.

Amendments to coverage are owned by `CommercialSalesRep`. Extending an expired window forward requires the row to be in `EXPIRED` (otherwise `ERR_COVERAGE_NOT_EXPIRED`), requires the new `effective_to` to be strictly after the logical clock (otherwise `ERR_COVERAGE_EXTENSION_NOT_FORWARD`), and requires that no other `ACTIVE` coverage for the same account spans the current instant (otherwise `ERR_COVERAGE_OVERLAP`). On success the row's `effective_to` is set to the new value and its posture returns to `ACTIVE`, and `active_account_count` is re-derived for both the departing and the arriving rep. Ending a window early works from either `SCHEDULED` or `ACTIVE` (any other posture is refused with `ERR_COVERAGE_NOT_ENDABLE`), again requires the new `effective_to` to be strictly after the logical clock (otherwise `ERR_COVERAGE_EXTENSION_NOT_FORWARD`), and leaves the row in `EXPIRED` with the same recomputation of `active_account_count`.

Vehicles are registered by `CommercialSalesRep` so that orders can be written against a specific car. The payload carries the seventeen-character `vin`, which is unique across vehicles, plus the `year`, `make`, `model`, `engine_code` (for example `2.4L-I4` or `3.6L-V6`), and `drive_type`, the last being `FWD`, `RWD`, `AWD`, or `FOUR_WD`. Vehicles are reference data for fitment and play no further role in the money movement described below.

### 3.2. Catalogue, Fitment, Interchange and Supersession

Parts enter the catalogue through a `PartsCategoryManager`, who supplies a `sku` unique across the active catalogue, a `description`, a `line_code`, and a `list_price_cents`. Three optional attributes default rather than being required: `core_charge_cents` defaults to 0 and is the refundable core deposit the part carries (0 for a part with no core), `is_hazardous` defaults to false and marks parts that ship under hazardous-materials rules, and `is_returnable` defaults to true and is false for special-order and electrical parts that may not come back. A `superseded_by_part_id` may be supplied to point the new part at the part that replaces it, or left null for a part that is current.

Registration seeds the part's derived attributes: `catalog_state` becomes `ACTIVE`, `supersession_depth` becomes 0, and `is_archived` becomes false. `supersession_depth` is read-only and tracks how many forward links stand between this part and the current one: it is 0 for a part that is current, and otherwise one more than the depth of the part it is superseded by, resolved through to the terminal current part of the chain.

Fitment data answers the question a counter clerk actually asks — will this part work on the car in the bay. A `PartFitment` row belongs to a catalogue part and is described by `part_id`, a model-year range running from `year_from` to `year_to`, a `make`, a `model`, an `engine_code` defaulting to the literal `ANY`, and a `drive_type` that is one of `FWD`, `RWD`, `AWD`, `FOUR_WD`, or `ANY`. The year range must be well-formed: a row whose `year_to` is earlier than its `year_from` is refused with `ERR_FITMENT_YEAR_RANGE_INVALID` (HTTP 400). A row whose `engine_code` is `ANY` matches any engine, and a row whose `drive_type` is `ANY` matches any driveline.

Interchange data captures equivalence with other vendors. A `PartInterchange` row names a `part_id` and the `interchange_sku` — the competitor or alternate-vendor number that is functionally equivalent — together with the `interchange_brand` that sells it. Interchange rows broaden what counts as a fit, and they also broaden what a core return can be matched against, as §3.7 explains.

Supersession is the catalogue's version of a part being replaced by a newer one, and it is reversible. A part that is `ACTIVE` may be superseded by naming a `superseding_part_id`; a part whose `catalog_state` is already `SUPERSEDED` is refused with `ERR_PART_ALREADY_SUPERSEDED`. The named target must itself exist and be non-archived, or the request fails with `ERR_SUPERSEDING_PART_NOT_FOUND`; it must be the terminal current part of its own chain, meaning its own `superseded_by_part_id` is null, or the request fails with `ERR_SUPERSEDING_PART_NOT_TERMINAL`; and it must not be reachable from the part being superseded by following `superseded_by_part_id` links, or the request fails with `ERR_SUPERSESSION_CYCLE`. These three conditions are evaluated in exactly that order and the first failure wins, which matters when a payload could satisfy more than one of them.

A successful supersession writes the target into `superseded_by_part_id`, moves `catalog_state` to `SUPERSEDED`, and recomputes `supersession_depth` for every part whose forward supersession chain contains the superseded part. Critically, open order lines are not rewritten at supersession time — the chain is resolved later, when the order is confirmed, as §3.3 describes. Undoing a supersession requires the part to be in `SUPERSEDED` (otherwise `ERR_PART_NOT_SUPERSEDED`), clears `superseded_by_part_id`, returns `catalog_state` to `ACTIVE`, and recomputes the depth of every part whose chain contained it.

A catalogue part can be soft-deleted by setting `is_archived` true, and a store can be soft-deleted the same way. Neither may be archived while a non-terminal resource still depends on it: the guard names accounts, parts and stores, and it is enforced on part archive and store archive, refusing with `ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE` (HTTP 409).

Resolving what a part reference really means today is a read the client can request directly. Supplying a `queried_part_id` returns the `current_part_id`, the `current_sku`, and the resulting `supersession_depth` after walking the chain to its terminal current part. A companion lookup answers fitment in reverse: given a `vehicle_id`, or a `part_id`, or both, and optionally `include_archived`, it returns the catalogue parts that fit, honouring interchange equivalence and following supersession forward to current parts, and excluding archived catalogue entries unless archived results were explicitly asked for.

Stock is held as inventory lines. A `PartsCategoryManager` receives stock by naming the `store_id`, the `part_id`, and the `on_hand_units`; the line starts with `reserved_units` at 0, and its `available_units` is read-only and always the larger of zero and `on_hand_units` minus `reserved_units`, so a shelf can never present a negative availability to a shopper. On-hand counts are adjusted later by writing a new `on_hand_units` to an existing line, after which `available_units` is recomputed. Listing inventory can be narrowed by `store_id`, by `part_id`, or by `include_archived` where a soft-deleted store's lines might otherwise be hidden.

### 3.3. Writing, Pricing and Confirming a Parts Order

An order is written by a `CommercialSalesRep` against an account, using the payload's `account_id`, an optional `vehicle_id` for the car the work is for, a `line_items` array whose entries each carry a `part_id`, a `quantity` and a `unit_price_cents`, and an optional `shipping_address` and `destination_id`. The write must carry `expected_account_version`, the account's `version` as the client last observed it. If another writer has advanced that account's `version` in the meantime, the create is refused with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412); the same refusal applies on any payload whose `expected_account_version` no longer matches the account's current `version`. `destination_id`, when present, is a routing hint about where the payload is meant to land; if it does not agree with the identifier carried in the path of a subsequent modification, the request is refused with `ERR_DESTINATION_MISMATCH` (HTTP 400).

Every line's `record_id` must be greater than zero. A line carrying a `record_id` of zero or a negative value is refused with `ERR_INVALID_LINE_REFERENCE` (HTTP 400), and that check guards order creation, order line mutation, and confirmation alike.

Fitment is enforced at write time. A part on an order line must either fit the order's vehicle directly through a `PartFitment` row, or resolve to a part that does — either through a `PartInterchange` equivalence or by following the supersession chain. A line whose part cannot be reconciled this way is refused with `ERR_FITMENT_MISMATCH` (HTTP 409). When the order names no vehicle at all, fitment is not applicable and the check passes. Note that a `PartFitment` row whose `engine_code` is `ANY` or whose `drive_type` is `ANY` matches on the vehicle's actual engine code or driveline without narrowing the match, and the fitment lookup honours `include_archived` the same way catalogue listing does.

One safety rule prunes what a shop can order at all. A line whose part has `is_hazardous` true may not be added to an order whose owning account has a `delivery_service_level` of `DELIVERY_DESK`; such a line is refused with `ERR_HAZARDOUS_PART_NOT_DELIVERABLE` (HTTP 400). This guard is evaluated on both the line-mutation write and the confirmation write.

At creation the order receives its identity and its provisional economics. The account's `order_sequence` counter is read and incremented, and the order's `member_sequence` is set to the value the counter held before the increment — so the account's very first order carries `member_sequence` 1, its second 2, and so on up to the highest sequence the account has reached. This read-then-increment is the reason the create is version-guarded: two writers racing for the same slot would otherwise both believe they hold the same `member_sequence`.

The `member_sequence` fixes the order's `pricing_band`, which is read-only and resolves as follows. A member sequence of 1 or 2 is `BRONZE`; 3, 4 or 5 is `SILVER`; 6 or 7 is `GOLD`; 8 or greater is `PLATINUM`. The band is settled at creation and does not move afterwards even as the account's counter keeps climbing. An order may only ever be priced at the band its own account has reached, so any attempt to repoint an order at a different account whose `order_sequence` would imply a different band is refused with `ERR_ACCOUNT_TIER_MISMATCH` (HTTP 409).

Line pricing resolves supersession before it resolves money. For each line independently, the resolved list amount is the `list_price_cents` of the line's terminal current part after the supersession chain has been walked. The band's `discount_rate` is then applied to that resolved amount, and the per-line discount is the resolved list amount multiplied by the rate, rounded half-up to the cent. The line's `unit_price_cents` is the resolved list amount minus that line discount. The order's `parts_subtotal_cents` is the sum over lines of the line's unit price multiplied by its quantity, and the order's `tier_discount_cents` is the sum over lines of the line discount multiplied by its quantity. This is the provisional reading, in force while the order's `status` is `DRAFT` or `CONFIRMED`, and because each line is rounded on its own the order-level discount it produces can exceed the true order-level figure by as much as one cent per line.

The same basket carries a satisfaction score. The order's `order_base_cents` is computed once, at creation, from the creation-time line basket and then stored: it is the sum over those lines of the resolved list amount multiplied by the quantity, with the total scaled by a base fraction of 0.015, rounded half-up to the cent. On creation and on every later recompute the order's `satisfaction_cents` is derived from that stored base: the base is scaled by one plus the `member_sequence` multiplied by a growth rate of 0.20, the result rounded half-up to the cent, and the final score is the smaller of that figure and a saturation ceiling of 1200 cents. Because `order_base_cents` is frozen at creation, adding a line to the order afterwards changes nothing in this score — the recompute reads the stored base, not a fresh basket.

The order also carries the core and deposit arithmetic that will matter when it is later returned. The order's `core_charge_total_cents` is the sum over lines of the catalogue `core_charge_cents` of the line's part multiplied by the line quantity. The order's `refundable_deposit_cents` is the refundable ceiling the shop ultimately gets back, and it is assembled in two parts: the order's total core charge scaled by a deposit fraction of 0.20 and rounded half-up to the cent once at the order level, plus the sum of `deposit_amount_cents` over every `ToolLoan` on the account whose `loaned_order_id` is this order. The single order-level rounding is deliberate: the core subtotal is summed first and rounded once, never line by line. The order's `refundable_deposit_consumed_cents` starts at 0 and is the running cap accounting described in §3.7.

Modifying an existing draft order re-derives everything the basket touches. The payload may change `vehicle_id`, `line_items`, `shipping_address` and `destination_id`, and must carry `expected_order_version` (the order's own `version`) as well as `expected_account_version`. After the write, `parts_subtotal_cents`, `tier_discount_cents`, `core_charge_total_cents`, `refundable_deposit_cents`, `delivery_fee_cents` and `satisfaction_cents` are all recomputed, and `fulfillment_route` and `promised_at` are re-derived from the source promise table of §3.4.

Confirmation is where a draft becomes a commitment, and it is the moment supersession finally lands on the lines. A `CommercialSalesRep` confirms an order by presenting `expected_order_version` and `expected_account_version`. The order's `status` must be `DRAFT`, or the request is refused with `ERR_ORDER_NOT_DRAFT` (HTTP 409). The owning account's `account_posture` must be `OPEN`, or the request is refused with `ERR_ACCOUNT_NOT_OPEN` (HTTP 409). The order's `fulfillment_route` must not be `UNROUTABLE`, or the request is refused with `ERR_NO_FULFILLMENT_SOURCE` (HTTP 409). Every line must be reservable: the selected source must hold an `available_units` figure at least as large as the line quantity for the resolved current part, or the request is refused with `ERR_INSUFFICIENT_STOCK` (HTTP 409).

Confirmation then performs its work in a fixed sequence. Every line whose `part_id` is superseded is repointed to the terminal current part of its supersession chain. Every line's `unit_price_cents` is recomputed from the resolved current part's list price and the account's tier band. For every line the selected source's `reserved_units` is increased by the line quantity, and the selected source's `committed_units_today` is increased by the line quantity. Because those two increments can push a store past its ceiling, the store's `daily_capacity_units` is re-checked in a second pass after reservation and the capacity epoch has been applied; a store whose `committed_units_today` would exceed its `daily_capacity_units` causes the confirmation to be refused with `ERR_CAPACITY_EXCEEDED` (HTTP 409). The order's `promised_at` and `fulfillment_route` are recomputed from the source promise table, and its `parts_subtotal_cents`, `core_charge_total_cents`, `tier_discount_cents`, `refundable_deposit_cents`, `delivery_fee_cents` and `satisfaction_cents` are recomputed. The account's `credit_exposure_cents` is recomputed and its `order_sequence` advances by one. The order's `reserved_unit_count` is set to the sum of its line quantities, which is what it now holds against the source store's `reserved_units`.

One consequence of advancing `order_sequence` is easy to miss and must be implemented deliberately. Because a band is keyed on the account's `order_sequence` at creation, and that value has just moved, every existing `PartOrder` on the same account whose `status` is `DRAFT` or `CONFIRMED` is re-priced at this order's band. For those sibling orders, `parts_subtotal_cents` and `tier_discount_cents` are recomputed, but their already-fulfilled lines are left alone; and the account's `credit_exposure_cents` is recomputed once more after the sibling re-pricing, not before it.

A confirmed order moves through allocation and picking on a slot rule. A `CommercialSalesRep` allocates a confirmed order with the same two version fields. The order's `status` must be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`), and the owning account must not already hold a `PartOrder` in `ALLOCATED` or `PICKING` carrying the same `member_sequence` on the same business day — a collision is refused with `ERR_SAME_DAY_SLOT_TAKEN` (HTTP 409). The slot is keyed on the account and the order, never on the source store, so two orders sourcing from the same warehouse do not collide unless they share the account and the sequence. Allocation moves the order to `ALLOCATED` and recomputes its `promised_at`, and this is also the point at which the order re-bases to the final pricing reading: `tier_discount_cents` is recomputed as one order-level round-half-up of the summed list amount multiplied by the band rate, and `parts_subtotal_cents` becomes that summed list amount less the order-level discount. `unit_price_cents` is deliberately not rewritten, so it retains its provisional per-line value and the order's subtotal and the sum of its line unit prices disagree from here on. Picking is a simple progression: an order in `ALLOCATED` (otherwise `ERR_ORDER_NOT_ALLOCATED`) moves to `PICKING`.

Dispatch by a `DeliveryDriver` requires the order to be in `PICKING` (otherwise `ERR_ORDER_NOT_PICKING`, HTTP 409) and requires the order to already be committed to a route — an order whose `service_route_id` is still null is refused with `ERR_ORDER_NOT_ON_ROUTE` (HTTP 409). On success the order moves to `DISPATCHED`.

An order in `CONFIRMED` or `DRAFT` that has not yet been allocated may be voided by a `CommercialSalesRep`. The order's `status` must be in `{DRAFT, CONFIRMED}`, otherwise the request is refused with `ERR_ORDER_NOT_VOIDABLE` (HTTP 409). Voiding a `DRAFT` order simply moves it to `VOID` and recomputes the account's `credit_exposure_cents`. Voiding a `CONFIRMED` order does more: `reserved_unit_count` is reset to 0, `refundable_deposit_consumed_cents` is written back into the account's live deposit pool so the compensated quantity is exactly restored, and for every line the reserved source's `reserved_units` and `committed_units_today` are both reduced by the line quantity. Then the order moves to `VOID` and `credit_exposure_cents` is recomputed. Orders that have reached `ALLOCATED` or `PICKING` are voidable only by a `CreditAnalyst` (otherwise `ERR_ORDER_NOT_VOIDABLE`); a `DISPATCHED` order is rejected here outright. Voiding from `ALLOCATED` or `PICKING` releases the same reserved units and committed capacity line by line, moves the order to `VOID`, and recomputes the account's exposure. The release of `reserved_units` and `committed_units_today` is the reserved-unit bookkeeping that §2.8's capacity ceiling depends on; omitting it would leave a store permanently over-committed.

### 3.4. Source Selection, the Promise Clock and the Delivery Fee

Deciding which warehouse supplies an order is the system's central routing problem, and it is solved as a sequence of bands evaluated in order, where the first band whose conditions all hold wins. The band is chosen on the order's first line only, and every line of the order then shares one `fulfillment_route`; a mixed basket does not split across warehouses.

Band 1 covers shops within the shop-delivery radius — from 0 up to and including 15 miles. It sources from the account's own satellite store when the request instant is at or before the cutoff instant minus the store's `cutoff_buffer_minutes`, when that satellite's `available_units` for the line is at least the line quantity, and when the satellite's `committed_units_today` plus the line quantity does not exceed its `daily_capacity_units`. The resulting source is the satellite, the duration is 0 days, and the route resolves to `STORE`. Notice that band 1 is the only band that consults `committed_units_today` and the ordering window together; deeper bands trade latency for availability.

Band 2, still within the same 0-to-15-mile radius, sources from the hub instead: the hub must hold `available_units` at least equal to the line quantity, the cutoff instant must be at or after the request instant, and the cutoff instant advanced by a cushion of 120 minutes must be at or after the request instant advanced by a hub run of 60 minutes. That resolves to `HUB` with 0 days. Band 3 is the same shape against the mega-hub, requiring the same cutoff ordering and a mega-hub run of 90 minutes against the same 120-minute cushion, resolving to `MEGA_HUB` with 0 days. Band 4 falls back to the distribution center within the 0-to-15-mile radius, requiring only that the distribution center holds the quantity and that the cutoff instant is at or after the request instant, and resolves to `DC` with 1 day of latency.

Band 5 covers shops between 15 and 35 miles. Availability alone decides here: a hub holding the quantity resolves to `HUB`, and the source duration is 1 day. Band 6 is the same test against the mega-hub, resolving to `MEGA_HUB` with 1 day. Band 7 routes the extended-radius shop to the distribution center, resolving to `DC` with 2 days. Band 8 is the empty band: beyond 35 miles nothing routes at all and the order's `fulfillment_route` becomes `UNROUTABLE`. The full set of routing outcomes is therefore `STORE`, `HUB`, `MEGA_HUB`, `DC`, and `UNROUTABLE` — there is no short or expedited routing outcome, because expediting is expressed through the service level rather than through the route.

The replenishment chain itself constrains which bands are reachable. Bands 3, 4, 6 and 7 are only reachable when the account's home store resolves the full chain satellite to hub to mega-hub to distribution center. When the account's home store is itself a hub or a mega-hub, those bands are skipped silently rather than failing — no error is raised — and when it is a distribution center the first seven bands all fail against the center's own stock, so such an order resolves through band 5 or band 6 against the hub that center names. An implementer who treats a skipped band as an error will fail the routing tests.

The routing decision also produces the published promise. The winning source store's `promise_time_minutes` is the base promise, and the account's tier band supplies a promise multiplier — the multiplier from the account's band applies when the source is a `STORE` or a `HUB`, while a `MEGA_HUB` or `DC` source always uses a multiplier of exactly 1.00, so warehouse drops get no tier acceleration. The quoted instant is the midnight following the request date plus the source's day count, set to `08:00:00Z`, then advanced by the base promise minutes multiplied by the promise multiplier and rounded half-up to a whole minute. That instant is stored as `promised_at`. The `HOTSHOT` delivery service level is what truncates the promise window, and it does so for `STORE` and `HUB` sources; the `DELIVERY_DESK` level in contrast does not deliver at all in the sense that matters here, because hazardous parts may not be added to such an order at all per §3.3.

Two readings of the routing decision exist and they can disagree on identical input. The provisional reading is evaluated when the order is created, against the home store's live availability, and may route to the home store while stock is still unpromised. The selected reading is evaluated at confirmation, after earlier orders on the same account and store have already been committed, and the identical basket can shift to a deeper band, producing a different `fulfillment_route` and a later `promised_at`. Both readings write the same fields, so an order's route and promise can legitimately change between draft and confirmation.

The delivery fee follows from the route and the service level, and it is a two-outcome schedule. The base fee is 795 cents. Delivery is free when the order's `fulfillment_route` is exactly `STORE`, or when the route is exactly `HUB` and the account's `delivery_service_level` is exactly `HUB_DAILY`. The comparison is exact-string on both sides: a service level whose name merely resembles `HUB_DAILY` does not satisfy the free-delivery clause, and neither does a route that differs from `STORE` or `HUB` by more than casing. When delivery is not free, the fee is the full 795 cents. There is no rounding in this calculation; it produces an integer cent figure directly. The fee is read at draft and confirmation as a point-of-sale quote, and read again at delivery as the final actual; the two readings are equal unless the confirmed source store differs from the delivered source store, in which case identical routing inputs can read either 0 or 795 depending on which moment is observed. The fee is not recomputed at allocation and not recomputed at delivery, so the point-of-sale figure is what stands unless the source itself moved.

Delivering a dispatched order to the shop is a `DeliveryDriver` action with three gates. The order's `status` must be `DISPATCHED` (otherwise `ERR_ORDER_NOT_DISPATCHED`), the `RouteStop` carrying the order must be in `SEQUENCED` or `EN_ROUTE` (otherwise `ERR_ROUTE_STOP_NOT_ACTIVE`), and the order's `delivered_at` must still be unset, because a delivered order cannot be delivered a second time (otherwise `ERR_ORDER_ALREADY_DELIVERED`). Where the order carries a `shipping_address`, that address must resolve to the account's own `shipping_address`, to its `billing_address`, or to the address of its home store; an address that is the home store resolved for some unrelated account is refused with `ERR_DELIVERY_ADDRESS_MISMATCH` (HTTP 409). If several orders are dropped at the same stop, delivering one while another order at that stop has not yet been delivered is refused with `ERR_ROUTE_SLICE_INCOMPLETE` (HTTP 409).

On success the physical and financial movements happen together. For every line, the source store's `on_hand_units` is reduced by the line quantity and its `reserved_units` is reduced by the line quantity as well, and the source store's `committed_units_today` is reduced by the line quantity. The order's `delivered_at` is stamped with the logical clock, and its `delivered_payment_due_at` is derived as `delivered_at` plus the account's `credit_terms_days`. The account's `receivable_balance_cents` is recomputed over its non-`VOID` orders, and the order moves to `DELIVERED`. That derived due instant is the input to the account posture aging test in §3.8, so a delivery is what starts the net-terms clock on the money.

An order that was dispatched but whose stop ended badly can be pushed back for re-routing. A `CommercialSalesRep` may refit an order only while its `status` is `DISPATCHED` (otherwise `ERR_ORDER_NOT_DISPATCHED`) and only when the `RouteStop` carrying it is in `REJECTED` or `MISSED` (otherwise `ERR_ROUTE_STOP_NOT_TERMINAL`). Such a rollback must happen inside a 30-minute rollback window measured from the earliest `RouteStop.delivered_at` on the route; once that window has passed the request is refused with `ERR_WINDOW_EXPIRED` (HTTP 409). A successful refit clears the order's `service_route_id`, returns its `status` to `CONFIRMED`, removes the rejected stop from its route, and re-derives every later stop on that route.

Returning a delivered order is the last order transition. A `CommercialSalesRep` may return an order only while its `status` is `DELIVERED` (otherwise `ERR_ORDER_NOT_DELIVERED`) and only while the logical clock is at most the order's `delivered_at` plus the account's `credit_terms_days` plus 30 days (otherwise `ERR_RETURN_WINDOW_CLOSED`). Every line on the order must carry a part whose `is_returnable` is true; a non-returnable part anywhere on the order is refused with `ERR_PART_NOT_RETURNABLE` (HTTP 409). The return sets `reserved_unit_count` to 0 and writes `refundable_deposit_consumed_cents` back into the account's live deposit pool, moves the order to `RETURNED`, and — when at least one line's part carries a `core_charge_cents` above zero — opens a `CoreReturn` in `INITIATED` against the order and the owning account. The order's reservations have already been released by that point, and the account's `credit_exposure_cents` is recomputed. The core return this opens is taken up in §3.7.

### 3.5. Building and Running the Driver Route

Routes are built by a `RouteDispatcher` and are the mechanism by which dispatched orders actually travel. A `ServiceRoute` is created from a `route_code` unique per service date, a `service_date`, a `driver_id`, a `driver_type` of `OWNED` or `AFFILIATE`, a `departure_at` instant at which the driver leaves the hub, and a `shift_end_at` instant bounding the driver's day. The route begins in `DRAFT`, and `driver_type` is not cosmetic — it selects which branch of the driver credit calculation applies when the route completes. A driver may hold at most one route in `{DRAFT, PLANNED, DISPATCHED}` per service date; attempting to create a second is refused with `ERR_DRIVER_ROUTE_CONFLICT` (HTTP 409).

Stops are attached to a draft route by the same dispatcher. A stop carries the `account_id` of the shop it serves, a `stop_kind` of `CUSTOMER` or `RETURN_DESK` defaulting to `CUSTOMER`, a delivery window running from `delivery_window_start` to `delivery_window_end`, a `travel_minutes_from_previous` drive time, a `drop_minutes` dwell time, and an optional `order_ids` list naming the orders dropped there. The stop's position on the route, `stop_sequence`, is read-only and is assigned by the ordering rule below rather than supplied. Attaching a stop requires `expected_route_version`, the route's `version` as last observed by the client; if the route's `version` has advanced since — for example because another writer already added or rejected a stop and thereby re-sequenced the stops behind it — the attach is refused with `ERR_STALE_ROUTE_VERSION` (HTTP 412).

Two temporal rules constrain a new stop. The window must be well formed: a `delivery_window_end` that is not strictly after its `delivery_window_start` is refused with `ERR_INVALID_DELIVERY_WINDOW` (HTTP 400). And a new `CUSTOMER` stop's window may not overlap an existing non-`REJECTED` `CUSTOMER` stop's window for the same account on the same service date; an overlap is refused with `ERR_STOP_WINDOW_OVERLAP` (HTTP 409). `RETURN_DESK` stops are exempt from that overlap test precisely so that a shop's return-desk stop and its delivery stop may share a day. A third rule cuts across both attachment and planning: no stop's `delivery_window_end` may be earlier than the route's `departure_at`, and a stop that closes before the truck leaves is refused with `ERR_STOP_WINDOW_BEFORE_DEPARTURE` (HTTP 400).

Planning a route is the act that freezes its geometry, and it is guarded on three fronts. The route's `status` must be `DRAFT` (otherwise `ERR_ROUTE_NOT_DRAFT`); the route must carry at least one stop (otherwise `ERR_ROUTE_HAS_NO_STOPS`); and no stop on the route may have a `delivery_window_end` earlier than the route's `departure_at` (otherwise `ERR_STOP_WINDOW_BEFORE_DEPARTURE`). Planning also carries `expected_route_version`. On success, the stop ordering and projection machinery runs, `effective_departure_at` is derived, and every stop moves to `SEQUENCED`.

The ordering rule is explicit and forbids any use of the stop's identifier. Every non-`REJECTED` stop on the route is ordered by a key that compares `delivery_window_start` ascending and then `created_at` ascending. The stop identifier is never a key, not even as a last tie-break, so two stops sharing a window start are separated by their `created_at`, and the stop that was attached first is served first. `stop_sequence` is then numbered from 1 upward over that ordering, and the projection chain is walked in the same order.

The projection chain begins from the route's effective departure. `effective_departure_at` is the route's `departure_at` when no `RETURN_DESK` stop exists, and otherwise the later of `departure_at` and the latest `RETURN_DESK` stop's `delivery_window_start` — the departure is pushed forward to at least the opening of the last return-desk window. The first stop's `projected_arrival_at` is `effective_departure_at` plus its `travel_minutes_from_previous`; every later stop's `projected_arrival_at` is the previous stop's `projected_departure_at` plus its own `travel_minutes_from_previous`. Each stop's `projected_departure_at` is its `projected_arrival_at` plus its `drop_minutes`. Each stop's `lateness_minutes` is the larger of zero and `projected_departure_at` minus `delivery_window_end`, so a stop that finishes before its window closes is exactly zero rather than negative. The route's `return_at` is the last stop's `projected_departure_at`, or the route's `departure_at` when the route has no stops at all.

Dispatching a planned route sets the day in motion and is guarded twice more. The route's `status` must be `PLANNED` (otherwise `ERR_ROUTE_NOT_PLANNED`); no stop's `projected_departure_at` may fall strictly after the route's `shift_end_at` (otherwise `ERR_SHIFT_END_EXCEEDED`); and every order whose `service_route_id` is this route and whose `status` is `ALLOCATED` must have already reached `PICKING` (otherwise `ERR_ROUTE_ORDERS_NOT_PICKED`). On success every stop on the route moves to `EN_ROUTE`, every order on the route that is in `PICKING` moves to `DISPATCHED`, and the route moves to `DISPATCHED`. A planned route can also be pulled back: reverting to draft requires `PLANNED` (otherwise `ERR_ROUTE_NOT_PLANNED`), returns the route to `DRAFT`, and pushes every stop back to `PLANNED` with its `stop_sequence` and projected fields cleared.

A stop's own life is short and irreversible at its end. A stop in `EN_ROUTE` is delivered by a `DeliveryDriver` only when its `lateness_minutes` is exactly zero; a stop whose lateness is above zero cannot be recorded as delivered and is refused with `ERR_STOP_PAST_WINDOW` (HTTP 409). A stop that is not in `EN_ROUTE` at all is refused with `ERR_STOP_NOT_EN_ROUTE`. Delivering a stop stamps its `delivered_at` with the logical clock, moves it to `DELIVERED`, and pushes every order dropped at that stop that is in `DISPATCHED` to `DELIVERED` through exactly the same movements described in §3.4 — inventory decremented, capacity released, due instant derived, receivable recomputed.

A stop in `EN_ROUTE` may instead be marked missed, which requires the same `EN_ROUTE` state (otherwise `ERR_STOP_NOT_EN_ROUTE`). Missing a stop moves it to `MISSED`, pushes every order dropped at it back to `CONFIRMED` with their `service_route_id` cleared, and re-derives every later stop on the same route — `stop_sequence`, `projected_arrival_at`, `projected_departure_at` and `lateness_minutes` all recomputed. A stop may be rejected before it is ever run, from either `PLANNED` or `SEQUENCED` — any other state is refused with `ERR_STOP_NOT_REJECTABLE` — and rejection has the same downstream effects as a miss: the stop becomes `REJECTED`, its orders revert to `CONFIRMED` with their route cleared, and later stops are re-derived. The 30-minute rollback window described in §3.4 also gates stop rejection, so a rejection attempted after the earliest delivered stop on the route is more than 30 minutes old is refused with `ERR_WINDOW_EXPIRED`.

A route can be called off at any point before it finishes. Cancellation is available from `DRAFT`, from `PLANNED`, and from `DISPATCHED` — a route that has already reached `COMPLETED` or `CANCELLED` is refused with `ERR_ROUTE_NOT_CANCELLABLE` (HTTP 409). On success every stop on the route is moved to `REJECTED`, every order referencing the route that is in `DISPATCHED` is pushed back to `CONFIRMED` with its `service_route_id` cleared, and the route moves to `CANCELLED`. Note that this is a broader unwind than refit performs, because it releases the whole route rather than a single order.

Completing a dispatched route closes the driver's day and pays them. Completion requires the route to be in `DISPATCHED` (otherwise `ERR_ROUTE_NOT_DISPATCHED`) and requires that no stop on the route remains in `PLANNED`, `SEQUENCED`, `EN_ROUTE`, or `REJECTED` — an unresolved stop is refused with `ERR_ROUTE_STOPS_UNRESOLVED` (HTTP 409). On success the route's `total_miles` and `run_credit_cents` are computed and the route moves to `COMPLETED`.

The credit calculation branches on `driver_type`, and the two branches read disjoint inputs — a route is credited under exactly one of them. An `AFFILIATE` route is paid by mileage: the per-mile rate is the long-run rate of 20 cents when the route's total distance is at least 40 miles, and the standard rate of 40 cents otherwise; the comparison is a greater-or-equal, so a run of exactly 40 miles already takes the reduced long-run rate, which is exactly half the standard rate. The credit is a base of 500 cents plus that per-mile rate multiplied by the route's total distance rounded half-up to a whole mile. The affiliate branch never reads the orders on the route.

An `OWNED` route is paid by attribution instead: for each `DELIVERED` stop on the route, the `delivery_fee_cents` of the orders dropped there are summed into an attributed amount, and the credit is the larger of that attributed amount multiplied by an owned share of 0.35 and rounded half-up to the cent, and a floor of 150 cents. The owned branch never reads the route's mileage. Note that the owned branch therefore ties a driver's pay to the delivery fees actually charged on the stops they completed, which is why §3.4's fee schedule is not merely a customer-facing number.

### 3.6. The Loaner Tool Program — Checkout, Wear and Inspection

A technician who needs a specialist tool the shop does not own can borrow it against a deposit. A `ToolCribAttendant` maintains the tool catalogue, and a `CommercialSalesRep` requests the loan on the shop's behalf.

A `ToolCatalog` entry is registered with a `tool_sku` unique across the tool catalogue, a `tool_name`, a standard `deposit_amount_cents` charged at checkout, a `replacement_part_id` naming the part offered when the tool comes back worn or broken, and a `replacement_unit_cost_cents`, the store's own cost of that replacement part, which serves as the fallback base for a replacement charge. The catalogue entry starts with `wear_accumulated` at 0.

Which replacement part is offered is not a static pointer; it is re-selected as the tool wears. Selection runs at two distinct levels, and they are not interchangeable.

The catalogue level is used whenever the catalogue's own `replacement_part_id` is re-selected on a wear-band change, and it evaluates three candidate sets in order, taking the first that is non-empty. Candidate set 2a is every part that has a `ToolFitment` row naming this tool and this part, whose `catalog_state` is `ACTIVE`, and which holds a positive `available_units` at an inventory line for the account's `home_store_id`. Candidate set 2b relaxes only the stock condition: every part with a `ToolFitment` row naming this tool and this part and an `ACTIVE` catalogue state, whether or not any store holds it. Candidate set 2c is the single part the catalogue's `replacement_part_id` held immediately before this re-selection, serving as a final fallback that survives even when the candidate sets above are empty.

The loan level is used when a `ToolLoan`'s own `replacement_part_id` is set at inspection for a worn return, and it mirrors the catalogue level exactly while reading the loan's tool in place of the catalogue's. Candidate set 1a is every part with a `ToolFitment` row naming the loan's tool and this part, whose `catalog_state` is `ACTIVE`, and which holds a positive `available_units` at an inventory line for that loan's account `home_store_id`. Candidate set 1b drops the stock condition. Candidate set 1c is the single part the loan's tool holds as `replacement_part_id` at that moment.

Within whichever set wins, candidates are ranked by an explicit four-part sort key, ascending on every position: first `PlacementRank`, then `DepthRank`, then `list_price_cents`, then `Part.created_at`. `PlacementRank` is 1 for a tool fitment whose `placement` is `FRONT` or `REAR_LEFT`, 2 for a `REAR_RIGHT` placement, and 3 for any placement other than those, which in practice is `OTHER`. `DepthRank` is the fitment's `depth_index`, compared ascending so the lower index wins. The part identifier is never a ranking or tie-break key at any position; the part's `created_at` settles any remaining tie. Two boundary facts follow from the rank table and must be honoured: a `FRONT` part and a `REAR_LEFT` part tie on placement at rank 1 and are separated by their depth index, and a `REAR_RIGHT` part is rank 2 and is never ranked as though it were 1.

If every candidate set at every level is empty, the loan's `replacement_part_id` stays null, no replacement is offered, and the tool's deposit is retained in full, with the loan's `forfeiture_rate` pinned to 1.00.

A loan is requested by a `CommercialSalesRep` with the borrowing `account_id`, the `tool_catalog_id`, a `deposit_amount_cents` proposed at request time, and an optional `loaned_order_id` tying the loan to a part order that prompted it. The request starts the loan in `REQUESTED` with `deposit_state` at `UNCHARGED`, and the account's `credit_exposure_cents` is recomputed so the pending loan is visible to the credit picture.

Checkout moves the tool out of the crib and is guarded on five fronts. The loan's `status` must be `REQUESTED` (otherwise `ERR_LOAN_NOT_REQUESTED`); the owning account's `account_posture` must be `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`); the loan's `deposit_amount_cents` must be at least the linked tool's catalogue `deposit_amount_cents` (otherwise `ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 402); the account's `credit_exposure_cents` plus the loan's `deposit_amount_cents` must not exceed the account's `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402); and the tool must not already be on loan to the same account in an open state — a loan in `CHECKED_OUT`, `IN_USE`, `DUE`, or `OVERDUE` for that account is refused with `ERR_TOOL_ALREADY_ON_LOAN` (HTTP 409). The checkout payload also carries `accepted_deposit_cents`, the deposit the shop has agreed to leave with the crib; this is the amount compared against the catalogue minimum and it is what the held deposit is recorded at. Checkout also carries `expected_account_version`, the account's `version` as last observed; a mismatch is refused with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). On success the loan's `deposit_state` moves to `HELD`, the account's `petty_cash_cents` is increased by the loan's `deposit_amount_cents`, and the loan moves to `CHECKED_OUT`.

Once a tool is out, the deposit it holds can be adjusted by a `CreditAnalyst` while the loan is `CHECKED_OUT` (otherwise `ERR_LOAN_NOT_CHECKED_OUT`), provided the new `deposit_amount_cents` remains at least the linked tool's catalogue deposit (otherwise `ERR_DEPOSIT_BELOW_MINIMUM`). The account's `petty_cash_cents` is adjusted by the difference between the new deposit and the previous one, the loan records the new amount, and `credit_exposure_cents` is recomputed. This adjustment also carries `expected_account_version` and is refused on a mismatch with `ERR_STALE_ACCOUNT_VERSION`.

Two distinct facts move a checked-out loan without leaving `CHECKED_OUT`, and they are told apart by what triggered them rather than by their endpoints. The first is the deposit adjustment above. The second is the wear-band re-specification: when the tool's accumulated wear crosses into a new band, the loan's `replacement_part_id` is refreshed from the newly selected catalogue part, the recommendation the crib makes is therefore always current with the tool's condition, and the loan remains `CHECKED_OUT`. A wear-band crossing requires the loan to still be `CHECKED_OUT` (otherwise `ERR_LOAN_NOT_CHECKED_OUT`), and the bands it watches are `LEVEL_2` at 25.0 accumulated wear units, `LEVEL_3` at 45.0, `LEVEL_4` at 65.0, and `LEVEL_5` at 85.0.

Time itself advances a loan that is out in the field. Once the logical clock is strictly after the loan's `loaned_at`, an unconditional system transition sets the loan's `due_at` to the logical clock advanced by exactly 14 days and moves the loan to `IN_USE`. From there the clock drives two further transitions. When the logical clock has reached or passed `due_at` minus 24 hours, the loan moves from `IN_USE` to `DUE`, provided the account's `credit_exposure_cents` has not exceeded its `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). When the logical clock passes `due_at` itself, the loan moves from `DUE` to `OVERDUE` under the same exposure guard, and its `overdue_days` is derived as the whole number of days elapsed since `due_at` — the elapsed seconds divided by 86400, truncated to a whole number, and 0 while the loan is not `OVERDUE`.

Receiving the tool back is a `DeliveryDriver` action available from any of the three out-of-crib states. A loan in `IN_USE`, `DUE`, or `OVERDUE` may be returned — any other state, including `REQUESTED` or `CHECKED_OUT`, is refused with `ERR_LOAN_NOT_OUT`. The return moves the loan to `RETURNED` and stamps its `returned_at` with the logical clock. The tool is now in the crib but not yet judged.

Inspection is where the tool's condition and its deposit outcome are decided, and it is owned by a `ToolCribAttendant`. The loan must be in `RETURNED` (otherwise `ERR_LOAN_NOT_RETURNED`); the supplied `return_condition` must be one of `GOOD`, `WORN`, `BROKEN`, or `LOST` (otherwise `ERR_INVALID_RETURN_CONDITION`, HTTP 400); and a `RETURN_DESK` `RouteStop` for the owning account must exist on a `ServiceRoute` that is not `CANCELLED` (otherwise `ERR_RETURN_DESK_STOP_MISSING`, HTTP 409). The return-desk requirement is the reason §3.1's coverage and §3.5's stop handling matter to the tool program: a shop with no return-desk stop on a live route cannot have its tool inspected at all.

Inspection computes three derived readings from the condition and then applies them. The loan's `wear_intensity` is a value between 0 and 100 derived from the tool's accumulated wear. The loan's `damage_multiplier` is the multiplier applied to the replacement part's list price on a broken return. The loan's `forfeiture_rate` is the fraction between 0.00 and 1.00 of the deposit retained on inspection, selected from the severity band. The deposit retention itself is the loan's `deposit_amount_cents` multiplied by that `forfeiture_rate`, rounded half-up to the cent, stored as `deposit_forfeited_cents`. A return whose requested refundable amount exceeds the deposit originally charged is refused with `ERR_DEPOSIT_AMOUNT_EXCEEDS_CHARGE` (HTTP 409).

The condition also drives the tool's own wear and its replacement recommendation. A return recorded as `WORN` or `BROKEN` advances the catalogue tool's `wear_accumulated` by 0.4. A return recorded as `WORN` selects the loan's `replacement_part_id` through the loan-level selection set described above. A return recorded as `LOST` sets the loan's `replacement_part_id` to the catalogue tool's own `replacement_part_id` rather than running the selector, because a lost tool has no worn part to replace. A return recorded as `GOOD` triggers neither wear nor replacement selection. The loan then moves to `INSPECTED`.

Advancing wear can itself move the tool into a new band, and that is a catalogue-level change with account-wide consequences. Accumulated wear reaching 25.0 moves the band from `LEVEL_1` to `LEVEL_2`; 45.0 moves `LEVEL_2` to `LEVEL_3`; 65.0 moves `LEVEL_3` to `LEVEL_4`; and 85.0 moves `LEVEL_4` to `LEVEL_5`. Each of those transitions requires the accumulated wear to be at or above the band threshold (otherwise `ERR_INSUFFICIENT_TOOL_WEAR`) and requires the current band to be the one the transition starts from (otherwise `ERR_INVALID_TOOL_WEAR_BAND`). A band advance writes the new band and its three companion values: at `LEVEL_2` the multiplier becomes 1.20, the forfeiture rate 0.40, and the grace period 36 hours; at `LEVEL_3` they become 1.45, 0.60, and 24 hours; at `LEVEL_4`, 1.70, 0.80, and 18 hours; at `LEVEL_5`, 2.00, 1.00, and 12 hours. Under `LEVEL_1` the corresponding values are a multiplier of 1.00, a forfeiture rate of 0.00, and a grace period of 48 hours. Every band advance re-selects the catalogue's `replacement_part_id` through the catalogue-level selector and refreshes the `replacement_part_id` of every loan on that tool that is in `CHECKED_OUT`, `IN_USE`, `DUE`, or `OVERDUE`. The advance to `LEVEL_5` does more: every loan on that tool in `REQUESTED`, `CHECKED_OUT`, `IN_USE`, `DUE`, or `OVERDUE` is set to `CHECKED_OUT` with its `due_at` set to the logical clock, which forcibly resets the clock on loans that have drifted far past their windows.

Wear can also be corrected out of band by a `ToolCribAttendant`, after a crib rebuild or a bench correction, by supplying a `wear_delta_units`. The tool's `wear_accumulated` becomes the larger of zero and its current value plus that delta, so a negative correction can never drive accumulated wear below zero. The band is then recomputed from the new accumulation, and it is raised only when a band threshold has actually been crossed — a correction that leaves wear inside the current band changes nothing. When the band does advance, the catalogue's `replacement_part_id` is re-selected through the catalogue-level selector, every loan on the tool in `CHECKED_OUT`, `IN_USE`, `DUE`, `OVERDUE`, or `REQUESTED` has its `replacement_part_id` refreshed, and an advance to `LEVEL_5` forces those loans to `CHECKED_OUT` with `due_at` at the logical clock exactly as a wear-driven advance would.

A tool can also be returned to a clean slate. A `ToolCribAttendant` may reset an inspection-free tool's wear from any of `LEVEL_2`, `LEVEL_3`, `LEVEL_4`, or `LEVEL_5` — a reset attempted from `LEVEL_1` is refused with `ERR_INVALID_TOOL_WEAR_BAND`. The reset sets `wear_accumulated` to 0, returns the band to `LEVEL_1`, and restores the companion values to a multiplier of 1.00, a forfeiture rate of 0.00, and a grace period of 48 hours.

An inspected loan ends in one of two ways, both owned by the `ToolCribAttendant`. To close it, the loan must be `INSPECTED` (otherwise `ERR_LOAN_NOT_INSPECTED`), the `return_condition` must be `GOOD` or `WORN` (otherwise `ERR_LOAN_NOT_CLOSABLE`), and the `deposit_state` must be `HELD` (otherwise `ERR_DEPOSIT_NOT_HELD`). Closing refunds the unearned deposit: `deposit_state` moves to `REFUNDED`, the account's `petty_cash_cents` is reduced by the deposit amount less the forfeited amount, `credit_exposure_cents` is recomputed, and the loan moves to `CLOSED`.

To forfeit instead, the loan must be `INSPECTED` (otherwise `ERR_LOAN_NOT_INSPECTED`) and its `deposit_state` must be `HELD` (otherwise `ERR_DEPOSIT_NOT_HELD`). Forfeiture sets `deposit_forfeited_cents` to the full `deposit_amount_cents` and then branches on whether the shop owes money. When the account's `receivable_balance_cents` is above zero, the deposit is applied against that debt: `deposit_state` moves to `APPLIED_TO_BALANCE` and `receivable_balance_cents` is reduced by the deposit amount. When the account's `receivable_balance_cents` is exactly zero, there is no debt to absorb it, so `deposit_state` moves to `FORFEITED` and `petty_cash_cents` is reduced by the deposit amount. Either way `credit_exposure_cents` is recomputed and the loan moves to `FORFEITED`. A loan therefore terminates in either `CLOSED` or `FORFEITED`, and its deposit reaches exactly one of `REFUNDED`, `APPLIED_TO_BALANCE`, or `FORFEITED` depending on which door it left by.

### 3.7. Core Returns, the Deposit Waterfall and Warranty Without Receipt

Automotive parts come with a core: an old alternator, a water pump housing, a rebuilt injector. The shop brings the old unit back, the store refunds a core deposit, and that flow is modelled as a `CoreReturn`.

A `CoreReturn` is opened against a `PartOrder` and its account, and its lines are the classic core lines: each carries a `part_id` and a `quantity`. It starts in `INITIATED` with its `core_subtotal_cents` computed as the sum over its lines of the `core_charge_cents` of the line's part multiplied by the line quantity. A `CommercialSalesRep` opens it, and the core return may also be created automatically when an order is returned, as §3.4 describes. A core return raised against an order outside the delivery-plus-30-days window is refused with `ERR_RETURN_WINDOW_CLOSED` (HTTP 409), the same window that gates the order return itself.

The core travels back to the hub before it can be judged. A `DeliveryDriver` marks a core return in `INITIATED` (otherwise `ERR_CORE_RETURN_NOT_INITIATED`) as `IN_TRANSIT`. It may also be rejected before it is inspected: a core return in `INITIATED` or `IN_TRANSIT` may be rejected by a `ToolCribAttendant` (any other state is refused with `ERR_CORE_RETURN_NOT_REJECTABLE`), and rejection moves it to `REJECTED` and posts no credit at all.

Inspection is the moment the credit is computed, and it is owned by a `ToolCribAttendant`. The core return must be in `IN_TRANSIT` (otherwise `ERR_CORE_RETURN_NOT_IN_TRANSIT`), and for every line the line quantity must not exceed the quantity of that same part on the referenced order — a line claiming more than was bought is refused with `ERR_CORE_QUANTITY_EXCEEDS_PURCHASE` (HTTP 409). Inspection then computes `core_subtotal_cents`, pins `warranty_covered`, computes `restocking_fee_cents`, and computes `credit_amount_cents`.

The warranty determination is deliberately generous and deliberately blind to paperwork. A core return's `warranty_covered` is true when any registration exists for this account covering any part on the return or any part on that part's supersession chain, whose warranty is still live at the moment of inspection. Concretely, it is true when there exists a `WarrantyRegistration` whose `account_id` equals the return's `account_id`, whose `part_id` is any part on the core return or any part on that part's supersession chain, and whose `warranty_expires_at` is at or after the logical clock at inspection. The lookup performs no match on `claim_reference` and no match on `purchase_order_id`: a credit is issued whether or not the shop can present a receipt, and the registration's `purchase_order_id` may legitimately be null for a warranty recorded without a purchase record. The result is immutable once written, pinned for the life of the record; a warranty that expires later does not retroactively un-cover an inspected return. A warranty-covered credit must belong to a registration whose `warranty_expires_at` is at or after the logical clock; an expired warranty does not block the credit but removes the restocking-fee waiver, and a credit computed as warranty-covered when its registration has in fact lapsed is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409).

The credit itself is assembled from two portions. The refundable portion is the core return's `core_subtotal_cents` multiplied by a refundable rate of 0.20 and rounded half-up to the cent, capped at the order's remaining deposit headroom — that is, the smaller of that computed figure and the order's `refundable_deposit_cents` less its `refundable_deposit_consumed_cents`. The core-charge portion is the larger of two ceiling figures: the core return's `core_subtotal_cents` multiplied by 0.60, rounded up to a whole cent, and the order's `core_charge_total_cents` multiplied by 0.30, also rounded up to a whole cent; the maximum of those two ceiling values is taken after both are rounded. The restocking fee is zero when the return is warranty-covered, and otherwise is the core-charge portion multiplied by a restocking rate of 0.15, rounded half-up to the cent. The core-charge credit is the core-charge portion less the restocking fee, and the total `credit_amount_cents` is the refundable portion plus the core-charge credit. The two readings this produces are worth contrasting: with a live warranty the whole core-charge portion is credited, and without one the restocking fee is netted out of it, so an otherwise identical basket yields a strictly smaller credit. A restocking fee that has been computed on a warranty-covered credit is itself refused with `ERR_RESTOCKING_FEE_MISAPPLIED` (HTTP 409); that check is deliberately kept separate from the other fee checks and evaluated last.

The refundable portion is drawn against a waterfall, and the waterfall's ceiling is assembled at order time. The order's `refundable_deposit_cents` is the order-level core subtotal scaled by a deposit fraction of 0.20 and rounded once at the order level, plus the sum of `deposit_amount_cents` over every tool loan on the account whose `loaned_order_id` is that order — the tool deposit flows into the same pool. Payouts are drawn against that ceiling in ascending core-line index order. For each payout, the remaining headroom is the order's `refundable_deposit_cents` less its `refundable_deposit_consumed_cents`, the refundable portion is the smaller of the payout being requested and that headroom, and the order's `refundable_deposit_consumed_cents` advances by the amount paid. Once the ceiling is exhausted, further payouts are zero, never negative. Two derived readings sit beside the payout calculation and should not be confused with it: `core_subtotal_cents` is the gross core value of the returned lines and is not capped, and the amount the account is entitled to purely as a function of what it bought is computed separately by walking the core lines in ascending line index order, matching each line's quantity against the quantity of that part on the referenced order — taking the smaller of the two — accumulating the matched quantity, and summing the `core_charge_cents` of each line's part multiplied by its matched quantity. That entitlement figure is not capped; it is the waterfall's ceiling that caps the actual payout. Unordered credit is never allowed, so a core line for a part the order never contained contributes nothing.

Posting the credit is a `CreditAnalyst` action and completes the flow. The core return must be in `INSPECTED` (otherwise `ERR_CORE_RETURN_NOT_INSPECTED`), and the owning account's `account_posture` must not be `CLOSED` (otherwise `ERR_ACCOUNT_CLOSED`, HTTP 409). On success the account's `petty_cash_cents` is increased by the return's `credit_amount_cents`, the account's `receivable_balance_cents` is recomputed over its non-`VOID` orders, the account's `credit_exposure_cents` is recomputed, and the core return moves to `CREDITED`. A core return thus terminates in either `CREDITED` or `REJECTED`.

Warranties are registered independently of any purchase, which is what makes the no-receipt credit possible. A `CommercialSalesRep` records a warranty with an `account_id`, a `part_id`, an optional `purchase_order_id` naming the original purchase, the `purchased_at` instant, the `warranty_expires_at` instant, and an optional `claim_reference` free-text reference that may be null. The expiry must be strictly after the purchase instant. A registration is immutable in all material respects: it carries only `id` and `created_at` alongside its business fields and is not amended after creation. Listings narrow by `account_id`, `part_id`, or `purchase_order_id`, and a warranty can also be read back through the account it belongs to.

### 3.8. Credit Governance — Holds, Suspension, Release and Closure

Credit governance is owned by the `CreditAnalyst` and runs on the exposure and receivable figures defined in §2.6. Three of its outcomes are business-day and ledger facts rather than schedules: the exposure ceiling, the receivable balance, and the age of the oldest due instant.

Placing an account on hold is a deliberate over-limit action and it is guarded. The account's `account_posture` must be `OPEN` (otherwise `ERR_INVALID_ACCOUNT_POSTURE`), and the account's `credit_exposure_cents` must exceed its `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). Note that the hold therefore cannot be used on an account that is inside its limit; it exists to stop a shop that has already overrun. On success the account moves to `ON_HOLD` and the cascading void described in §2.5 fires in full — every non-`DISPATCHED` order on the account voided, reservations and committed capacity released, affected route stops rejected and their successors re-derived, and finally `credit_exposure_cents` recomputed.

The hold operation is also the entry point for credit suspension evaluation, which is otherwise a background derivation. Evaluating the aging test — the account carries a receivable above zero and its oldest due instant falls strictly earlier than the logical clock minus the sum of its `credit_terms_days` and the 30-day grace — yields `CREDIT_SUSPENDED`. The suspended posture is readable without holding: the posture read returns the account's `account_posture`, its `credit_exposure_cents`, its `receivable_balance_cents`, the `oldest_due_at` instant driving the aging test, and the `status_needed` instant at which the account would fall due under the test, and reading it does not mutate anything. Because the posture derivation of §2.6 runs on every write that can change the receivable, the orders, the loans, or the core returns, a suspended account usually surfaces through an ordinary write rather than through an explicit call.

Releasing and restoring are the two exits from a non-open posture and both are limited to `CreditAnalyst`. Releasing requires the account to be `ON_HOLD` (otherwise `ERR_INVALID_ACCOUNT_POSTURE`) and requires its `credit_exposure_cents` to no longer exceed its `credit_limit_cents` — an account still over its ceiling cannot be released and the request is refused with `ERR_CREDIT_LIMIT_STILL_EXCEEDED` (HTTP 409). Restoring requires the account to be `CREDIT_SUSPENDED` (otherwise `ERR_INVALID_ACCOUNT_POSTURE`) and carries the same exposure gate, with the same refusal. Both successful exits return the account to `OPEN`.

Closing is the terminal act and it demands a clean slate on four fronts. The account's posture must not already be `CLOSED`. No `PartOrder` on the account may remain in `DRAFT`, `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED` (otherwise `ERR_OPEN_ORDERS_EXIST`). No `ToolLoan` on the account may remain in `REQUESTED`, `CHECKED_OUT`, `IN_USE`, `DUE`, `OVERDUE`, `RETURNED`, or `INSPECTED` (otherwise `ERR_OPEN_LOANS_EXIST`). No `CoreReturn` on the account may remain in `INITIATED`, `IN_TRANSIT`, or `INSPECTED` (otherwise `ERR_OPEN_CORE_RETURNS_EXIST`). And the account's `receivable_balance_cents` must be exactly zero (otherwise `ERR_RECEIVABLE_BALANCE_OUTSTANDING`, HTTP 402). Closure is available from `OPEN`, from `ON_HOLD`, and from `CREDIT_SUSPENDED`, and from each of those the account moves to `CLOSED`. Once `CLOSED` the account is terminal: nothing re-derives it, and a core credit attempted against a closed account is refused with `ERR_ACCOUNT_CLOSED`.

Soft deletion is a separate act from closure and carries its own guard. Archiving an account, a part, or a store sets its `is_archived` flag so that default list reads stop returning it while it remains addressable by identifier, and it is refused with `ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE` (HTTP 409) while a non-terminal resource still depends on it. The listing endpoints accept an `include_archived` flag for exactly this reason: without it, archived rows are invisible.

### 3.9. The Logical Clock and the Business-Day Epoch

The system does not read the wall clock. Before any clock instruction is given, the logical clock reads a fixed startup default of `2026-09-01T00:00:00Z`, and every time-dependent rule in this document — the aging test, the return window, the coverage windows, the loan due instants, the rollback window, the wear grace periods — is evaluated against that instant until it is moved. A `PlatformAdmin` may set the logical clock to any supplied instant by naming it in `to_iso8601`; the current and default values are readable back. Moving the clock forward is what makes the aging and overdue behaviours observable, and it is the only way to exercise them.

Separately, the business-day boundary for store capacity is advanced by an operator relay rather than by the clock. The relay takes the same `to_iso8601` instant and advances the epoch for every store whose `capacity_epoch_at` is at least 24 hours behind that instant: those stores have their `committed_units_today` reset to zero and their `capacity_epoch_at` stamped to the requested instant. Stores whose `capacity_epoch_at` is already within 24 hours of the requested instant are left untouched. The relay reports which stores it advanced and the total unit quantity it reset. Without it, a store that has committed its daily capacity stays committed forever, and §3.3's capacity guard would eventually block every order against it.

## 4. Endpoint Definitions

The table below is a routing map only; the request payloads, arithmetic and side effects for each row are specified in the §3 workflow narratives above. Two status conventions apply throughout. An operation that creates a new stand-alone resource, or adds a new distinct resource to a collection, returns `201 Created`; every other successful operation, including modifications to an existing resource and actions that drive a state machine, returns `200 OK`. A read returns `200 OK` with the resource or the page of resources in the `data` field. Where a collection is listed, filtering is available through query parameters whose names match the field they filter on — for example listing accounts accepts `include_archived`, `shop_name` and `home_store_id`; listing orders accepts `account_id`, `status`, `vehicle_id` and `service_route_id`; listing loans accepts `account_id`, `status`, `tool_catalog_id`, `loaned_order_id` and `replacement_part_id`; listing stores accepts `include_archived`, `store_type` and `hub_store_id`; listing parts accepts `include_archived`, `catalog_state`, `line_code`, `sku` and `superseded_by_part_id`; listing inventory accepts `store_id` and `part_id`; listing vehicles accepts `make` and `year`; listing reps accepts `district_code` and `home_store_id`; listing coverage accepts `rep_id` and `account_id`; listing fitments accepts `part_id`, `make` and `model`; listing interchanges accepts `part_id` and `interchange_sku`; listing tool fitments accepts `tool_catalog_id`, `part_id` and `placement`; listing routes accepts `service_date`, `driver_id` and `status`; listing stops accepts `route_id`, `account_id`, `status`, `stop_kind` and `order_ids`; listing core returns accepts `order_id`, `account_id` and `status`; and listing warranties accepts `account_id`, `part_id` and `purchase_order_id`. Every list accepts `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/commercial/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/commercial/_epoch/advance` | Advance the business-day capacity epoch for eligible stores | PlatformAdmin |
| POST | `/commercial/commercial-accounts` | Create a commercial account for a repair shop | CommercialSalesRep |
| GET | `/commercial/commercial-accounts` | List commercial accounts | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/commercial-accounts/{accountId}` | Get one commercial account | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/commercial-accounts/{accountId}/part-orders` | Find the part orders placed by an account | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/commercial-accounts/{accountId}/tool-loans` | Find the loaner tool records held by an account | ToolCribAttendant, CommercialSalesRep, CreditAnalyst, DeliveryDriver, Any |
| GET | `/commercial/commercial-accounts/{accountId}/core-returns` | Find the core returns raised by an account | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| GET | `/commercial/commercial-accounts/{accountId}/rep-coverages` | Find the coverage windows recorded for an account | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/commercial-accounts/{accountId}/warranty-registrations` | Find the warranty registrations held by an account | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| PUT | `/commercial/commercial-accounts/{accountId}` | Update account master data and commercial terms | CommercialSalesRep, CreditAnalyst |
| GET | `/commercial/commercial-accounts/{accountId}/posture` | Read the derived account posture without mutating the account | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| POST | `/commercial/commercial-accounts/{accountId}/hold` | Place an over-limit account on hold or apply credit suspension | CreditAnalyst |
| POST | `/commercial/commercial-accounts/{accountId}/release` | Release an account from hold | CreditAnalyst |
| POST | `/commercial/commercial-accounts/{accountId}/restore` | Restore a credit-suspended account | CreditAnalyst |
| POST | `/commercial/commercial-accounts/{accountId}/close` | Close an account | CreditAnalyst |
| POST | `/commercial/commercial-accounts/{accountId}/archive` | Soft-delete an account | CreditAnalyst |
| POST | `/commercial/stores` | Create a store, hub, mega-hub or distribution center | PartsCategoryManager |
| GET | `/commercial/stores` | List stores | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/stores/{storeId}` | Get one store | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/stores/{storeId}/child-stores` | Find the satellite stores replenished from a hub, mega-hub or DC | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/stores/{storeId}/commercial-accounts` | Find the commercial accounts homed to a store | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/stores/{storeId}/inventory-items` | Find the inventory lines held at a store | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| POST | `/commercial/stores/{storeId}/archive` | Soft-delete a store | PartsCategoryManager |
| POST | `/commercial/inventory-items` | Receive stock into a store | PartsCategoryManager |
| GET | `/commercial/inventory-items` | List inventory lines across stores | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/inventory-items/{itemId}` | Get one inventory line | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| PUT | `/commercial/inventory-items/{itemId}` | Adjust the on-hand count of an inventory line | PartsCategoryManager |
| GET | `/commercial/parts/{partId}/inventory-items` | Find the inventory lines held for a part across stores | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| POST | `/commercial/parts` | Register a part in the catalogue | PartsCategoryManager |
| GET | `/commercial/parts` | List catalogue parts | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/parts/current` | Resolve a part reference to its terminal current part | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/parts/fitment-lookup` | Look up the parts that fit a vehicle | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/parts/{partId}` | Get one catalogue part | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/parts/{partId}/fitments` | List the fitment rows declared for a part | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| POST | `/commercial/parts/{partId}/fitments` | Declare a fitment row for a part | PartsCategoryManager |
| GET | `/commercial/parts/{partId}/interchanges` | List the interchange numbers declared for a part | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| POST | `/commercial/parts/{partId}/interchanges` | Declare an interchange number for a part | PartsCategoryManager |
| GET | `/commercial/parts/{partId}/tool-fitments` | Find the tool fitment rows naming a part as a replacement part | PartsCategoryManager, ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| POST | `/commercial/parts/{partId}/supersede` | Supersede a part with a replacement part | PartsCategoryManager |
| POST | `/commercial/parts/{partId}/unsupersede` | Undo a supersession | PartsCategoryManager |
| POST | `/commercial/parts/{partId}/archive` | Soft-delete a catalogue part | PartsCategoryManager |
| GET | `/commercial/part-fitments` | List vehicle fitment rows across the catalogue | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/part-fitments/{fitmentId}` | Get one vehicle fitment row | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/part-interchanges` | List interchange numbers across the catalogue | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/part-interchanges/{interchangeId}` | Get one interchange number | PartsCategoryManager, CommercialSalesRep, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/tool-fitments` | List the replacement-part fitments declared against loaner tools | PartsCategoryManager, ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| GET | `/commercial/tool-fitments/{fitmentId}` | Get one tool replacement-part fitment | PartsCategoryManager, ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| POST | `/commercial/vehicles` | Register a vehicle | CommercialSalesRep |
| GET | `/commercial/vehicles` | List registered vehicles | CommercialSalesRep, PartsCategoryManager, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| GET | `/commercial/vehicles/{vehicleId}` | Get one vehicle | CommercialSalesRep, PartsCategoryManager, RouteDispatcher, DeliveryDriver, CreditAnalyst, Any |
| POST | `/commercial/sales-reps` | Create a commercial sales representative | CommercialSalesRep |
| GET | `/commercial/sales-reps` | List commercial sales representatives | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/sales-reps/{repId}` | Get one commercial sales representative | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/sales-reps/{repId}/coverages` | Find the coverage assignments held by a representative | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| POST | `/commercial/rep-coverages` | Assign a representative to cover an account for a date window | CommercialSalesRep |
| GET | `/commercial/rep-coverages` | List coverage assignments | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/rep-coverages/{coverageId}` | Get one coverage assignment | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| POST | `/commercial/rep-coverages/{coverageId}/extend` | Extend an expired coverage window forward | CommercialSalesRep |
| POST | `/commercial/rep-coverages/{coverageId}/end` | End a scheduled or active coverage window early | CommercialSalesRep |
| POST | `/commercial/part-orders` | Write a commercial part order | CommercialSalesRep |
| GET | `/commercial/part-orders` | List part orders | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| GET | `/commercial/part-orders/{orderId}` | Get one part order | CommercialSalesRep, CreditAnalyst, RouteDispatcher, DeliveryDriver, PartsCategoryManager, Any |
| PUT | `/commercial/part-orders/{orderId}` | Update the vehicle or line items of a draft order | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/confirm` | Confirm a draft order, resolve supersession, price it and reserve stock | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/allocate` | Allocate a confirmed order to its source slot | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/pick` | Begin picking an allocated order | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/dispatch` | Mark a picked order as loaded on its route | DeliveryDriver |
| POST | `/commercial/part-orders/{orderId}/deliver` | Deliver a dispatched order to the shop | DeliveryDriver |
| POST | `/commercial/part-orders/{orderId}/refit` | Push a dispatched order back to confirmed after a terminal route stop | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/return` | Return a delivered order and open a core return | CommercialSalesRep |
| POST | `/commercial/part-orders/{orderId}/void` | Void an order | CommercialSalesRep, CreditAnalyst |
| GET | `/commercial/part-orders/{orderId}/core-returns` | Find the core returns opened against a part order | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| GET | `/commercial/part-orders/{orderId}/route-stops` | Find the route stops at which a part order is dropped | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| POST | `/commercial/tool-catalog` | Register a loaner tool in the tool catalogue | ToolCribAttendant |
| GET | `/commercial/tool-catalog` | List loaner tools | ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| GET | `/commercial/tool-catalog/{toolCatalogId}` | Get one loaner tool | ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| POST | `/commercial/tool-catalog/{toolCatalogId}/adjust-wear` | Log an out-of-band wear adjustment | ToolCribAttendant |
| POST | `/commercial/tool-catalog/{toolCatalogId}/reset-wear` | Reset a tool's accumulated wear to the base band | ToolCribAttendant |
| GET | `/commercial/tool-catalog/{toolCatalogId}/fitments` | Find the replacement-part fitments declared for a tool | ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| POST | `/commercial/tool-catalog/{toolCatalogId}/fitments` | Declare that a replacement part fits a tool | ToolCribAttendant |
| POST | `/commercial/tool-loans` | Request a loaner tool for an account | CommercialSalesRep |
| GET | `/commercial/tool-loans` | List tool loans | ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| GET | `/commercial/tool-loans/{loanId}` | Get one tool loan | ToolCribAttendant, CommercialSalesRep, DeliveryDriver, RouteDispatcher, CreditAnalyst, Any |
| PUT | `/commercial/tool-loans/{loanId}` | Adjust the deposit held on a checked-out loan | CreditAnalyst |
| POST | `/commercial/tool-loans/{loanId}/checkout` | Check out a requested loaner tool and take the deposit | CommercialSalesRep |
| POST | `/commercial/tool-loans/{loanId}/return` | Record a loaner tool as returned by the driver | DeliveryDriver |
| POST | `/commercial/tool-loans/{loanId}/inspect` | Inspect a returned loaner tool and record its condition | ToolCribAttendant |
| POST | `/commercial/tool-loans/{loanId}/close` | Close an inspected loan, refunding the unearned deposit | ToolCribAttendant |
| POST | `/commercial/tool-loans/{loanId}/forfeit` | Close an inspected loan by forfeiting the deposit | ToolCribAttendant |
| POST | `/commercial/core-returns` | Open a core return against a delivered order | CommercialSalesRep |
| GET | `/commercial/core-returns` | List core returns | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| GET | `/commercial/core-returns/{coreReturnId}` | Get one core return | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| POST | `/commercial/core-returns/{coreReturnId}/transit` | Mark a core return as in transit back to the hub | DeliveryDriver |
| POST | `/commercial/core-returns/{coreReturnId}/inspect` | Inspect a core return and compute its credit | ToolCribAttendant |
| POST | `/commercial/core-returns/{coreReturnId}/credit` | Post the inspected core credit to the account | CreditAnalyst |
| POST | `/commercial/core-returns/{coreReturnId}/reject` | Reject a core return before inspection or in transit | ToolCribAttendant |
| POST | `/commercial/warranty-registrations` | Record a warranty for an account and part without a receipt lookup | CommercialSalesRep |
| GET | `/commercial/warranty-registrations` | List warranty registrations | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| GET | `/commercial/warranty-registrations/{registrationId}` | Get one warranty registration | CommercialSalesRep, CreditAnalyst, ToolCribAttendant, DeliveryDriver, Any |
| POST | `/commercial/service-routes` | Create a driver service route | RouteDispatcher |
| GET | `/commercial/service-routes` | List service routes | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| GET | `/commercial/service-routes/{routeId}` | Get one service route | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| POST | `/commercial/service-routes/{routeId}/stops` | Attach a delivery stop to a draft route | RouteDispatcher |
| GET | `/commercial/service-routes/{routeId}/stops` | Find the stops on a service route | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| GET | `/commercial/service-routes/{routeId}/stops/{stopId}` | Get one stop on a service route | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| POST | `/commercial/service-routes/{routeId}/plan` | Sequence a draft route's stops and compute projections | RouteDispatcher |
| POST | `/commercial/service-routes/{routeId}/dispatch` | Dispatch a planned route and its picked orders | RouteDispatcher |
| POST | `/commercial/service-routes/{routeId}/revert-to-draft` | Return a planned route to draft | RouteDispatcher |
| POST | `/commercial/service-routes/{routeId}/complete` | Complete a dispatched route and compute the driver credit | RouteDispatcher |
| POST | `/commercial/service-routes/{routeId}/cancel` | Cancel a route | RouteDispatcher |
| GET | `/commercial/route-stops` | List route stops | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| GET | `/commercial/route-stops/{stopId}` | Get one route stop | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| GET | `/commercial/route-stops/{stopId}/orders` | Find the part orders dropped at a route stop | RouteDispatcher, DeliveryDriver, CommercialSalesRep, CreditAnalyst, Any |
| POST | `/commercial/route-stops/{stopId}/deliver` | Complete a stop at the shop | DeliveryDriver |
| POST | `/commercial/route-stops/{stopId}/miss` | Record a stop as missed | DeliveryDriver |
| POST | `/commercial/route-stops/{stopId}/reject` | Reject a stop before dispatch | RouteDispatcher |

## 5. Error Code Catalogue

The identifiers below are the complete set the service may return. Their trigger conditions live in the §2 and §3 narratives above, and this table states only the identifier and the status code it is carried in.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DELIVERY_WINDOW` | 400 Bad Request |
| `ERR_FITMENT_YEAR_RANGE_INVALID` | 400 Bad Request |
| `ERR_HAZARDOUS_PART_NOT_DELIVERABLE` | 400 Bad Request |
| `ERR_INVALID_RETURN_CONDITION` | 400 Bad Request |
| `ERR_STOP_WINDOW_BEFORE_DEPARTURE` | 400 Bad Request |
| `ERR_INVALID_LINE_REFERENCE` | 400 Bad Request |
| `ERR_DESTINATION_MISMATCH` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_COMMERCIAL_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_PART_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TOOL_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_CORE_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_SALES_REP_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_NOT_FOUND` | 404 Not Found |
| `ERR_TOOL_CATALOG_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_ALLOCATED` | 409 Conflict |
| `ERR_ORDER_NOT_PICKING` | 409 Conflict |
| `ERR_ORDER_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_ORDER_NOT_VOIDABLE` | 409 Conflict |
| `ERR_ORDER_ALREADY_DELIVERED` | 409 Conflict |
| `ERR_LOAN_NOT_REQUESTED` | 409 Conflict |
| `ERR_LOAN_NOT_CHECKED_OUT` | 409 Conflict |
| `ERR_LOAN_NOT_OUT` | 409 Conflict |
| `ERR_LOAN_NOT_RETURNED` | 409 Conflict |
| `ERR_LOAN_NOT_INSPECTED` | 409 Conflict |
| `ERR_LOAN_NOT_CLOSABLE` | 409 Conflict |
| `ERR_DEPOSIT_NOT_HELD` | 409 Conflict |
| `ERR_DEPOSIT_AMOUNT_EXCEEDS_CHARGE` | 409 Conflict |
| `ERR_INSUFFICIENT_TOOL_WEAR` | 409 Conflict |
| `ERR_INVALID_TOOL_WEAR_BAND` | 409 Conflict |
| `ERR_INVALID_ACCOUNT_POSTURE` | 409 Conflict |
| `ERR_CREDIT_LIMIT_STILL_EXCEEDED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_OPEN` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_OPEN_LOANS_EXIST` | 409 Conflict |
| `ERR_OPEN_CORE_RETURNS_EXIST` | 409 Conflict |
| `ERR_CORE_RETURN_NOT_INITIATED` | 409 Conflict |
| `ERR_CORE_RETURN_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_CORE_RETURN_NOT_INSPECTED` | 409 Conflict |
| `ERR_CORE_RETURN_NOT_REJECTABLE` | 409 Conflict |
| `ERR_CORE_QUANTITY_EXCEEDS_PURCHASE` | 409 Conflict |
| `ERR_ROUTE_NOT_DRAFT` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNED` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROUTE_STOP_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUTE_STOP_NOT_TERMINAL` | 409 Conflict |
| `ERR_ROUTE_STOPS_UNRESOLVED` | 409 Conflict |
| `ERR_ROUTE_HAS_NO_STOPS` | 409 Conflict |
| `ERR_ROUTE_ORDERS_NOT_PICKED` | 409 Conflict |
| `ERR_ROUTE_SLICE_INCOMPLETE` | 409 Conflict |
| `ERR_SHIFT_END_EXCEEDED` | 409 Conflict |
| `ERR_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_STOP_NOT_EN_ROUTE` | 409 Conflict |
| `ERR_STOP_NOT_REJECTABLE` | 409 Conflict |
| `ERR_STOP_PAST_WINDOW` | 409 Conflict |
| `ERR_STOP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DRIVER_ROUTE_CONFLICT` | 409 Conflict |
| `ERR_PART_ALREADY_SUPERSEDED` | 409 Conflict |
| `ERR_PART_NOT_SUPERSEDED` | 409 Conflict |
| `ERR_PART_NOT_RETURNABLE` | 409 Conflict |
| `ERR_SUPERSEDING_PART_NOT_FOUND` | 409 Conflict |
| `ERR_SUPERSEDING_PART_NOT_TERMINAL` | 409 Conflict |
| `ERR_SUPERSESSION_CYCLE` | 409 Conflict |
| `ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE` | 409 Conflict |
| `ERR_FITMENT_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_NO_FULFILLMENT_SOURCE` | 409 Conflict |
| `ERR_SAME_DAY_SLOT_TAKEN` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RETURN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_RESTOCKING_FEE_MISAPPLIED` | 409 Conflict |
| `ERR_ACCOUNT_TIER_MISMATCH` | 409 Conflict |
| `ERR_DELIVERY_ADDRESS_MISMATCH` | 409 Conflict |
| `ERR_TOOL_ALREADY_ON_LOAN` | 409 Conflict |
| `ERR_RETURN_DESK_STOP_MISSING` | 409 Conflict |
| `ERR_COVERAGE_NOT_STARTED` | 409 Conflict |
| `ERR_COVERAGE_STILL_OPEN` | 409 Conflict |
| `ERR_COVERAGE_NOT_EXPIRED` | 409 Conflict |
| `ERR_COVERAGE_NOT_ENDABLE` | 409 Conflict |
| `ERR_COVERAGE_EXTENSION_NOT_FORWARD` | 409 Conflict |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_RECEIVABLE_BALANCE_OUTSTANDING` | 402 Payment Required |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 402 Payment Required |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ROUTE_VERSION` | 412 Precondition Failed |