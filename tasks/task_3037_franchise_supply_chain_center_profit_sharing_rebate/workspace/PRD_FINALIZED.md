# Franchise Supply Chain API — Product Requirements Document

## 1. Introduction

Franchised quick-service restaurant networks face a structural tension: the brand wants every store buying from approved suppliers so quality stays consistent, while franchisees want a financial reason to keep buying from the company-owned supply arm rather than shopping the open market. The traditional answer — used at scale by pizza franchise systems such as Domino's — is a company-operated network of supply centers that produce fresh dough and distribute food, packaging, equipment, and smallwares to franchised stores on a fixed weekly cadence, priced at cost plus a transparent markup, with a quarterly profit-sharing rebate that returns a slice of the supply chain's surplus to franchisees who purchase exclusively.

This document specifies the Franchise Supply Chain API, the backend for that model. It covers the full operational loop: onboarding a supply center and its stores, maintaining a product catalogue and tiered price books, planning weekly delivery routes that serve multiple stores from a single truck, capturing weekly purchase orders from store managers, confirming them against production capacity, tracking each order through loading, delivery, and settlement, and reconciling the books at week and quarter end. On top of that operational spine sit three cross-cutting financial disciplines: a cost-plus pricing engine with volume tiers, a food-cost variance analysis that compares each store's actual ingredient spend against the theoretical usage implied by its settled orders, and a compliance-driven rebate pool that accrues credits per settled order, holds back disputed amounts, and settles quarterly against each store's outstanding balance.

Two concerns shape the API's design. First, money and capacity are both contended resources: a store manager submitting an order and an administrator re-pricing a product can act on the same store or center within moments of each other, so the API protects the most collision-prone writes with optimistic concurrency checks. Second, the network runs on a weekly drumbeat: a logical operations checkpoint advances the center's cadence, expiring stale orders, re-evaluating franchisee compliance, reconciling capacity plans, and progressing rebate settlements. An administrative test-driving capability advances the logical clock so that all time-dependent behavior can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting caller, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or carrying a malformed or unrecognized value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not permitted for the targeted operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Four role names are recognized, spelled exactly as follows: `SupplyChainAdmin`, `StoreManager`, `RouteCoordinator`, and `Any`.

- `SupplyChainAdmin` is the corporate supply-chain administrator — the hierarchical override role. It manages centers, stores, products, price books, promotions, rebate pools and ledger entries, compliance agreements, capacity plans, and variance analyses, and it can confirm, reject, and settle purchase orders. When `X-User-Role` is `SupplyChainAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `StoreManager` is the franchise store manager — it creates and submits purchase orders, adds lines to them, cancels them, and files weekly compliance reports. When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting Store; ownership checks on any resource that references a Store compare the resource's `store_id` foreign-key field to `X-User-ID`, so a store manager can only create orders for, submit compliance reports for, and act on behalf of their own store.
- `RouteCoordinator` is the logistics coordinator — it plans routes, dispatches trucks, records arrivals and completions at stops, skips stops, loads and delivers purchase orders, and marks lines shorted. When `X-User-Role` is `RouteCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `Any` denotes shared read access available to every authenticated role. It is not a distinct caller identity; when `X-User-Role` is `Any` or any other role on a read-only endpoint, `X-User-ID` is treated as an opaque operator identifier.

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

Endpoints that return lists are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter says how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits marking creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that starts at its initial value and increments by one on every mutation to the resource. The `version` field is the backbone of the optimistic concurrency protocol described in §2.7.

### 2.5. Money, Units, and Precision

All monetary amounts are integer cents — there are no fractional-cent values anywhere in the API, and fields whose names end in `_cents` are integers. Where a money calculation produces a fraction (the per-unit cost-plus price, the per-line theoretical usage, a store's rebate accrual, a store's rebate share of the pool), the fractional part is discarded by rounding down to the next whole cent. Percentages and ratios that are exposed to callers — `food_cost_variance_pct`, `variance_pct`, `exclusive_purchase_pct`, and route utilization — are carried at four decimal places using round-half-up. Capacity figures such as `surge_units` are whole dough-equivalent units; any fractional surplus from a multiplier is rounded down to a whole unit.

### 2.6. The Validation Pipeline

Every request passes through a fixed, priority-ordered pipeline of checks, and the ordering is part of the contract because it determines which error a request receives when several rules are violated at once. The pipeline is evaluated in this order:

1. **Header authentication** — `X-User-ID` and `X-User-Role` must be present and valid, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization** — the role must be permitted for the operation, else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Applies to all endpoints.
3. **Scoped existence** — every resource identifier in the path must exist within its parent scope, else the matching not-found error: `ERR_CENTER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_LEDGER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, or `ERR_VARIANCE_NOT_FOUND` (all HTTP 404). Applies to all resource endpoints; path identifiers are validated left to right, so a bad center id surfaces `ERR_CENTER_NOT_FOUND` before any deeper identifier is examined.
4. **Center operational state** — the center must be `ACTIVE` or in `SURGE_MODE` posture for operational actions, else `ERR_CENTER_NOT_ACTIVE` (HTTP 409). This gate applies to store activation, purchase order submission, route dispatch, and promotion confirmation.
5. **Store operational state** — the store must be `ACTIVE` for purchase order operations, else `ERR_STORE_NOT_ACTIVE` (HTTP 409). This gate applies to order submission and order cancellation.
6. **Transition legality** — the target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Applies to every state-transition endpoint.
7. **Product availability** — the product must be `ACTIVE` and not `RECALLED`, else `ERR_PRODUCT_UNAVAILABLE` (HTTP 409). Applies to order line creation and price book creation.
8. **Capacity availability** — the week's capacity plan must have enough available units, else `ERR_CAPACITY_EXCEEDED` (HTTP 409). Applies to purchase order confirmation.
9. **Truck load** — the route's total load must not exceed truck capacity, else `ERR_ROUTE_OVERLOADED` (HTTP 409). Applies to route dispatch; purchase order confirmation does not check truck load.
10. **Store credit** — the order must not push the store past its credit ceiling, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409). Applies to purchase order submission.
11. **Price book non-overlap** — a new price book's effective window must not overlap an existing `ACTIVE` book for the same product and store tier, else `ERR_PRICE_BOOK_OVERLAP` (HTTP 409). Applies to price book creation.
12. **Promotion non-overlap** — a promotion's date range must not overlap an existing `CONFIRMED` or `EXECUTING` promotion covering the same products, else `ERR_PROMOTION_OVERLAP` (HTTP 409). Applies to promotion confirmation.
13. **Date-range sanity** — an effective-from must be strictly before its effective-until, and a promotion's start strictly before its end, else `ERR_INVALID_DATE_RANGE` (HTTP 400). Applies to price book creation and promotion creation.
14. **Compliance gate for rebate accrual** — a store must hold an `ACTIVE` compliance agreement to accrue rebate, else `ERR_COMPLIANCE_REQUIRED` (HTTP 409). Applies to purchase order settlement when a rebate accrual would be posted.
15. **Pool solvency** — the rebate pool must hold sufficient balance to cover a settlement, else `ERR_POOL_INSUFFICIENT` (HTTP 409). Applies to rebate settlement.

Malformed request bodies, missing required fields, invalid enumeration values, and other constraint violations that do not match a more specific rule are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Three write endpoints carry an explicit optimistic-concurrency contract. On each, the request body must include a non-optional version field carrying the caller's last observed `version` of the named parent entity; if the value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Submitting a purchase order requires `expected_store_version` matching the store's current `version`. If another writer has advanced the store's version since the client last read it — for example by settling an order (which changes `outstanding_balance_cents`) or suspending the store — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot submit against a credit picture it has not observed.
- Creating a price book entry requires `expected_center_version` matching the center's current `version`. If another writer has advanced the center's version since the client last read it — for example by confirming a promotion that changed the center's posture or capacity multiplier — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), so pricing is never authored against a center state the client has not observed.
- Locking a capacity plan requires `expected_center_version` matching the center's current `version`. If another writer has advanced the center's version since the client last read it — for example by confirming an order that consumed allocated units — the lock is rejected with `ERR_STALE_VERSION` (HTTP 412), so a plan is never locked against an allocation picture the client has not observed.

Endpoints not named above do not take a version field; a request that sends one elsewhere has no concurrency effect.

### 2.8. Posture, Hierarchy, and Cascading Consistency

Each supply center carries, alongside its lifecycle `status`, a computed operational `posture` drawn from `ACTIVE`, `CONSTRAINED`, `SURGE_MODE`, and `SUSPENDED`. Posture is derived, never set directly: confirming a national promotion pushes the center into `SURGE_MODE`; a capacity plan that becomes `OVERBOOKED` pushes it into `CONSTRAINED`; suspension of the center drives posture to `SUSPENDED`; and closing a promotion or recovering an overbooked plan causes posture to be re-evaluated from current conditions.

State changes cascade down the resource hierarchy so the system never holds a child commitment its parent can no longer honor. Suspending a center cancels all of its `PLANNED` routes and rejects all of its `DRAFT` and `SUBMITTED` purchase orders. Suspending a store cancels that store's `DRAFT` and `SUBMITTED` purchase orders. Decommissioning a center terminates all of its remaining stores, and terminating a store terminates all of its compliance agreements. Cancelling a route unassigns and reverts the orders riding on it; cancelling a promotion rejects the orders that referenced it. Each such cascade is a mutation of the affected resource and therefore refreshes that resource's `updated_at` and increments its `version`, and each reconciliation that mutates a parent likewise updates the parent's `updated_at` and `version`.

### 2.9. The Weekly Operations Checkpoint

Each center maintains `ops_run_index`, a monotone counter that starts at zero and is incremented by one every time the operations checkpoint runs. The checkpoint is the network's weekly drumbeat; a single run performs five sweeps in one pass: stale purchase orders are expired, franchisee compliance is re-evaluated against the trailing purchase window, capacity plans for the ending week are reconciled, rebate settlements whose scheduled date has been reached are processed, and every time-dependent automatic transition in the system is given the opportunity to fire. The exact per-sweep rules live with their workflows in §3.

A test-driving capability restricted to `SupplyChainAdmin` sets the system's logical clock to a supplied `to_iso8601` instant and re-evaluates all time-dependent computations against the new time. The logical clock starts at 2026-09-01T00:00:00Z on a fresh deployment. This capability exists so that weekly and quarterly cadences can be exercised deterministically in tests and demos; it returns the effective time as `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Center: Catalogue, Pricing, and Activation

A `SupplyChainAdmin` opens the network by creating a supply center with a `center_code`, a human-readable `display_name`, a `base_weekly_capacity_units` figure expressed in dough-equivalent units per week, and an optional `surge_capacity_multiplier` that defaults to 1.0, meaning no surge. The `center_code` is unique across the system and immutable once assigned. A new center is born in `DRAFT` status with `posture` of `ACTIVE`, an `ops_run_index` of zero, and both `rebate_pool_balance_cents` and `rebate_pool_locked_cents` at zero.

Before the center can serve anyone, it needs a catalogue. Products are created per center with a `sku` that is unique within the center, a display `name`, a `category` drawn from `DOUGH`, `FOOD_INGREDIENT`, `EQUIPMENT`, `SMALLWARES`, and `PACKAGING`, and a `base_cost_cents_per_unit` representing the production or acquisition cost of one unit. Perishable products carry a `shelf_life_days`; for non-perishables that field is null. A product that participates in national promotions is flagged with `is_promotion_eligible`, which defaults to false. Products are born `ACTIVE`; an administrator may later discontinue one (moving it to `DISCONTINUED`) or recall one with a `reason` (moving it to `RECALLED`). Order lines and price book entries may only reference a product that is `ACTIVE` and not `RECALLED`; anything else is refused with `ERR_PRODUCT_UNAVAILABLE`.

Pricing is expressed through price book entries, each tying a `product_id` to a `store_tier` of `STANDARD`, `VOLUME_DISCOUNT`, or `PREMIUM`, with a `markup_pct` expressed as a fraction of base cost (for example 0.15 for a fifteen percent markup), a `min_quantity` that defaults to 1, and an effective window from `effective_from` to `effective_until`. The window is half-open: an entry applies when the current time is on or after `effective_from` and strictly before `effective_until`, and a creation whose `effective_from` is not strictly before its `effective_until` fails with `ERR_INVALID_DATE_RANGE`. Two `ACTIVE` entries for the same product and store tier may never have overlapping windows — an overlapping creation is rejected with `ERR_PRICE_BOOK_OVERLAP`. Per the §2.6 ordering the overlap rule is evaluated before date-range sanity; because the overlap test compares window intersections under the half-open convention, an inverted window (one whose `effective_from` is not before its `effective_until`) intersects nothing and therefore passes the overlap check, surfacing `ERR_INVALID_DATE_RANGE` instead. Entries whose window has passed are `EXPIRED`, and an entry replaced by a newer one is `SUPERSEDED`; only `ACTIVE` entries participate in pricing. Creating a price book entry is a center-level decision and so it carries the optimistic-concurrency contract described in §2.7: the request must include `expected_center_version`, and successful creation increments the center's `version` by one.

Activation is the last step of center setup. Moving a center from `DRAFT` to `ACTIVE` requires a `base_weekly_capacity_units` greater than zero and at least one product in `ACTIVE` status; the transition also sets the center's `posture` to `ACTIVE`. A suspended center can be reactivated by the same transition, which moves it `SUSPENDED → ACTIVE` with no additional preconditions.

Suspension is the blunt instrument: moving a center `ACTIVE → SUSPENDED` — which accepts an optional `reason` — cancels every `PLANNED` route under the center and rejects every purchase order still in `DRAFT` or `SUBMITTED`. Decommissioning is the permanent one, allowed only when the center is a ghost of itself: no store in `ACTIVE` status (else `ERR_CENTER_HAS_ACTIVE_STORES`), no purchase order in `SUBMITTED`, `CONFIRMED`, `LOADED`, or `DELIVERED`, no route in `PLANNED` or `DISPATCHED`, and every rebate pool in `CLOSED` status. When those conditions hold, `ACTIVE → DECOMMISSIONED` terminates all remaining stores as a cascade.

### 3.2. Onboarding Stores and Governing Compliance

Stores join a center in `ONBOARDING` status, created with a `store_number` unique within the center and immutable, the franchisee's legal `operator_name`, and a `credit_limit_cents` ceiling on unpaid invoiced amounts. A new store starts with `compliance_tier` of `FULL_COMPLIANCE`, `rebate_eligibility_status` of `ELIGIBLE`, an `exclusive_purchase_pct` of 0, and an `outstanding_balance_cents` of 0.

Activation requires two things: the center must be `ACTIVE` (otherwise `ERR_CENTER_NOT_ACTIVE`), and the store must hold at least one compliance agreement in `ACTIVE` status. Compliance agreements are the legal rails of the exclusive-purchase model. Each agreement is created under a store with an `agreement_type` of `EXCLUSIVE_PURCHASE`, `APPROVED_SUPPLIER`, or `BRAND_STANDARD`, a `start_date`, an optional `end_date` (null for a perpetual agreement), and an `exclusive_purchase_threshold` expressed as a fraction such as 0.95. Agreements are born `PROPOSED`; a `SupplyChainAdmin` activates one — permitted while the store is `ACTIVE` or still `ONBOARDING` — and activation re-evaluates the store's `rebate_eligibility_status` by recomputing the store's trailing four-week `exclusive_purchase_pct` and re-deriving both `rebate_eligibility_status` and `compliance_tier` from the recomputed percentage and the store's current agreement statuses.

Exclusive purchasing is measured weekly. A `StoreManager` files the store's weekly compliance report with the `week_start_date` and the store's `external_purchases_cents` — everything the store bought outside this center that week. The report returns the recomputed `exclusive_purchase_pct` alongside a `report_id`. That percentage is computed over a trailing four-week window: the numerator is the sum of `total_cents` across the store's `SETTLED` purchase orders from this center in the window; the denominator is that sum plus the reported external purchases; the ratio is carried at four decimal places with round-half-up. When the denominator is zero — the store has neither settled purchases nor reported external purchases in the window — the percentage is 0. Whenever the percentage moves, the store's `compliance_tier` is re-evaluated: any `ACTIVE` agreement currently in `BREACHED` status forces `NON_COMPLIANT`; otherwise a percentage of at least 0.95 earns `FULL_COMPLIANCE`, at least 0.80 earns `PROBATION`, and anything below that is `NON_COMPLIANT`.

Breaches are detected automatically: when an agreement's measured `exclusive_purchase_pct` sits below its `exclusive_purchase_threshold` for two consecutive weeks, the agreement moves `ACTIVE → BREACHED`, its `breach_count` increments by one, a `cure_deadline` is set seven days out, the store's `rebate_eligibility_status` drops to `CONDITIONAL`, and its `compliance_tier` drops to `PROBATION`. The store can recover: curing a breached agreement requires the current `exclusive_purchase_pct` to be at or above the threshold, and moves the agreement `BREACHED → CURED` while re-evaluating both the store's `rebate_eligibility_status` and `compliance_tier`. If the `cure_deadline` passes without a cure, or an administrator terminates the agreement outright, it moves `BREACHED → TERMINATED`, the store's `rebate_eligibility_status` becomes `INELIGIBLE`, and its `compliance_tier` becomes `NON_COMPLIANT`.

A store is suspended either administratively (with an optional `reason`) or automatically the moment its `outstanding_balance_cents` exceeds its `credit_limit_cents`; either way, every `DRAFT` and `SUBMITTED` purchase order the store holds is cancelled as a cascade. Reinstatement from `SUSPENDED` to `ACTIVE` is gated on the store's `outstanding_balance_cents` being no greater than its `credit_limit_cents` — a store still over its ceiling cannot be reactivated. Termination is final and allowed only when the store holds no purchase order in `SUBMITTED`, `CONFIRMED`, `LOADED`, or `DELIVERED` — a store with such orders cannot be terminated and the attempt is rejected with `ERR_STORE_HAS_ACTIVE_ORDERS` — and when its `outstanding_balance_cents` is exactly zero. Termination cascades to every compliance agreement, moving them all to `TERMINATED`.

### 3.3. Planning Capacity and Running Promotions

Capacity is planned one week at a time. A `SupplyChainAdmin` creates a capacity plan for a `week_start_date` — the Monday that opens the week — and the plan is born `OPEN` with `baseline_units` copied from the center's `base_weekly_capacity_units`, `surge_units` at zero, `allocated_units` at zero, and `available_units` equal to the baseline. As orders are confirmed against the week, `allocated_units` climbs and `available_units` — always the baseline plus surge minus allocation — falls.

National promotions are the reason surge capacity exists. A promotion event is created with a `promotion_code`, a `start_date` and `end_date` (a start that is not strictly before the end fails with `ERR_INVALID_DATE_RANGE`), a `surge_multiplier` such as 2.5 meaning demand is expected to run at two and a half times normal, and the list of `affected_product_ids` participating. Promotions are born `FORECASTED`. Confirming one requires the center to be `ACTIVE` or in `SURGE_MODE` and to have sufficient surge capacity, and it must not collide with another promotion: if any existing `CONFIRMED` or `EXECUTING` promotion for the same products has an overlapping date range, the confirmation is rejected with `ERR_PROMOTION_OVERLAP`. Promotion date ranges are treated as half-open intervals — a promotion is considered to run from its `start_date` up to but not including its `end_date` — so two promotions whose windows merely touch (one's `start_date` equal to the other's `end_date`) do not overlap. Confirmation moves the promotion `FORECASTED → CONFIRMED` and re-shapes the center: `posture` becomes `SURGE_MODE`, the center's `surge_capacity_multiplier` is set to the promotion's `surge_multiplier`, and for each affected week the plan's `surge_units` is raised by the baseline multiplied by the amount the multiplier exceeds one, rounded down to whole units — so a 2.5 multiplier on a 4,000-unit baseline adds 6,000 surge units. The plan's `capacity_reserved_units` on the promotion tracks the production reserved for it.

When the calendar reaches the promotion's `start_date` it moves `CONFIRMED → EXECUTING` automatically; when the `end_date` is reached it closes automatically, and an administrator may also close it early. Either path moves `EXECUTING → CLOSED`, resets the center's `surge_capacity_multiplier` to 1.0, re-evaluates the center's `posture`, and resets `surge_units` on capacity plans for future weeks. Cancellation is possible from `FORECASTED` without conditions and rejects every purchase order referencing the promotion; from `CONFIRMED` it is allowed only while no referencing order has advanced beyond `SUBMITTED` — a promotion whose orders are `CONFIRMED` or further along cannot be cancelled and the attempt fails with `ERR_PROMOTION_HAS_COMMITTED_ORDERS` — and cancellation re-evaluates the center's `posture` and rejects the affected orders.

Locking a capacity plan is the weekly commitment point: it requires `allocated_units` not to exceed baseline plus surge, it carries the §2.7 optimistic-concurrency contract (the request must include `expected_center_version`, a mismatch is `ERR_STALE_VERSION`, and a successful lock increments the center's `version`), and it moves the plan `OPEN → LOCKED`. A locked plan accepts no further modifications — attempts to change it are rejected with `ERR_CAPACITY_PLAN_LOCKED` — until the week's operations checkpoint reconciles it to `RECONCILED`, recording the variance between allocated and actual production. If at any point `allocated_units` climbs past baseline plus surge, the plan flips automatically from `OPEN` to `OVERBOOKED`, the center's `posture` becomes `CONSTRAINED`, and new order confirmations are blocked; when cancellations bring allocation back within capacity the plan returns `OVERBOOKED → OPEN` and the center's posture is re-evaluated.

### 3.4. The Weekly Order: Drafting, Pricing, and Submission

The purchase order is where stores and the center actually trade. A `StoreManager` creates a draft order under their store for a `week_start_date`, optionally tying it to a `promotion_id` if the order rides a national promotion. Drafts are where orders are assembled: lines are added one product at a time with a `product_id` and a `quantity`, and each line's economics are computed at creation. The line's `unit_price_cents` comes from the tiered cost-plus rule: among `ACTIVE` price book entries matching the center, the product, and the store's tier whose window contains the current time and whose `min_quantity` is at most the ordered `quantity`, the entry with the highest qualifying `min_quantity` wins; the unit price is the product's `base_cost_cents_per_unit` multiplied by one plus that entry's `markup_pct`, with the fractional cent rounded down. The line's `extended_price_cents` is the unit price times the quantity, and its `theoretical_usage_cents` records the ingredient-cost component used later for variance analysis. Standard network tiers mark up at fifteen percent; orders of one hundred units or more qualify for the `VOLUME_DISCOUNT` tier at twelve percent; the `PREMIUM` tier marks up at twenty percent. Lines are born `PENDING`.

While an order sits in `DRAFT` or `SUBMITTED`, its pricing is provisional — lines are priced off the current price book and re-priced on submission. From `CONFIRMED` onward, prices are locked; changing them requires re-confirmation.

Submission is the moment of accountability, and it stacks several gates in the §2.6 order: the store must be `ACTIVE` (else `ERR_STORE_NOT_ACTIVE`), the center must be `ACTIVE` or in `SURGE_MODE` (else `ERR_CENTER_NOT_ACTIVE`), and the order must contain at least one line (else `ERR_ORDER_HAS_NO_LINES`). Submission is also one of the three OCC-protected writes: the request must carry `expected_store_version`, and a store whose `version` has advanced since the client last read it rejects the submission with `ERR_STALE_VERSION`. When the gates pass, the order's money fields are computed. The `subtotal_cents` is the sum of `extended_price_cents` over all `PENDING` and `CONFIRMED` lines. The `markup_cents` is the subtotal minus the sum of each line's base cost times quantity — the supply chain's gross margin on the order. The `delivery_fee_cents` is the route delivery surcharge computed for the store, center, and week. The `total_cents` is subtotal plus markup plus delivery fee. Under an active promotion the delivery fee is waived and a surge surcharge is applied to the subtotal instead. The credit gate then applies: if the order's total exceeds the store's `credit_limit_cents` minus its current `outstanding_balance_cents`, submission fails with `ERR_CREDIT_LIMIT_EXCEEDED`. A successful submission moves the order `DRAFT → SUBMITTED` and increments the store's `version` by one.

A store manager can cancel an order while it is `DRAFT` or `SUBMITTED` (with an optional `reason`); an administrator can reject a `SUBMITTED` order with a `reason`, moving it to `REJECTED`. Both are terminal.

### 3.5. Confirmation, Capacity Consumption, and Route Assignment

Confirmation is the center's acceptance of an order, performed by a `SupplyChainAdmin`, and it is where capacity and logistics bind. The week's capacity plan must have `available_units` at least equal to the order's total units, else `ERR_CAPACITY_EXCEEDED`; if the order carries a `promotion_id`, the referenced promotion must be `CONFIRMED` or `EXECUTING`. Confirmation does not check truck load: an order is confirmed onto its assigned route even when that pushes the route past capacity, and the over-capacity load is refused later, at dispatch, with `ERR_ROUTE_OVERLOADED` (§3.6).

A confirmed order is assigned to the next `PLANNED` route that covers the store, recorded on the order's `route_id`; if no planned route serves the store for the order's week, confirmation fails with `ERR_NO_ROUTE_AVAILABLE`. Confirmation cascades: every line moves `PENDING → CONFIRMED`, and the week's capacity plan absorbs the order's units into `allocated_units`. If that absorption pushes allocation past baseline plus surge, the plan's automatic overbooking rule from §3.3 fires.

### 3.6. Routes, Stops, and the Delivery Run

Logistics is the `RouteCoordinator`'s domain. A route is created with a `route_code`, a `day_of_week` (`MONDAY` through `SUNDAY`), a `truck_capacity_units` ceiling expressed in dough-equivalent units, and an ordered `assigned_store_ids` list naming the stores the truck will serve and the order it will serve them in. Routes are born `PLANNED`.

Dispatch requires the center to be `ACTIVE` or in `SURGE_MODE` (else `ERR_CENTER_NOT_ACTIVE`), every assigned store to be `ACTIVE`, and the total load — the sum of `quantity` across all `CONFIRMED` and `LOADED` orders assigned to the route — to sit at or under `truck_capacity_units`. Utilization is tracked at four decimal places as load divided by capacity; a load exceeding capacity is refused with `ERR_ROUTE_OVERLOADED`. Dispatch moves the route `PLANNED → DISPATCHED`, stamps `dispatched_at` with the current time, and flips every stop to `PENDING`.

Each stop on a route belongs to one store, carries a 1-based `sequence_number` fixing its position in the run, and a system-projected `estimated_arrival`. As the truck works its route, the coordinator marks each stop arrived — recording the `actual_arrival` — then completed, moving it `PENDING → ARRIVED → COMPLETED`. A stop that cannot be served is skipped with a `reason`; the orders on it remain `LOADED` for a later attempt. A stop may also end `FAILED`.

Orders move with the truck. Loading an order — permitted once its assigned route is `DISPATCHED` — moves it `CONFIRMED → LOADED` and every line `CONFIRMED → SHIPPED`. Delivery is recorded per order at the stop: it requires the stop for that store to be `ARRIVED`, moves the order `LOADED → DELIVERED`, moves every line `SHIPPED → DELIVERED`, and captures the invoice's actual ingredient cost as the order's `actual_usage_cents`, supplied with the delivery call. As each line moves `SHIPPED → DELIVERED`, its `theoretical_usage_cents` is computed per the formula of §3.7 — quantity times the product's `base_cost_cents_per_unit` times the category's ingredient yield factor, rounded down per line to whole cents — and the order's `theoretical_usage_cents` is set to the sum over its `DELIVERED` lines, so both figures are already populated on the delivered order before settlement. When a line cannot be fully supplied, the coordinator marks it shorted: the line moves `SHIPPED → SHORTED`, the order's `total_cents` is recalculated without that line, and the week's capacity plan returns the line's quantity to `allocated_units`. When every stop on a dispatched route has resolved to `COMPLETED`, `SKIPPED`, or `FAILED`, the route completes automatically, and every `DELIVERED` order on it is settled as a cascade.

Route cancellation unwinds differently depending on timing. Cancelling a `PLANNED` route (with an optional `reason`) returns every `CONFIRMED` order assigned to it to `SUBMITTED`, unassigned from any route. Cancelling a `DISPATCHED` route is allowed only while no stop on it has reached `COMPLETED`; it moves every stop to `SKIPPED` and returns every `LOADED` order to `CONFIRMED`.

### 3.7. Settlement, Food-Cost Variance, and Rebate Accrual

Settlement closes the order's books. It happens automatically when the route completes, or explicitly when a `SupplyChainAdmin` settles a delivered order. Settlement requires every line to be `DELIVERED` or `SHORTED`, and it fans out into four computations.

First, theoretical usage. For each `DELIVERED` line, the theoretical ingredient cost is the line's quantity times the product's `base_cost_cents_per_unit` times the category's ingredient yield factor — 0.85 for `DOUGH`, 0.92 for `FOOD_INGREDIENT`, 1.00 for `PACKAGING`, and 0.00 for `EQUIPMENT` and `SMALLWARES`, which are excluded from food cost entirely — rounded down per line to whole cents. The order's `theoretical_usage_cents` is the sum across lines. These values are first computed when the order is delivered (§3.6); settlement (re)computes them over the lines that are `DELIVERED` at settlement time.

Second, the food-cost variance. When the order's theoretical usage is zero — an order of nothing but equipment and smallwares — `food_cost_variance_pct` is null and the week's severity is `GREEN`. Otherwise the variance is `actual_usage_cents` minus `theoretical_usage_cents`, and the percentage is that difference divided by the theoretical figure, at four decimal places with round-half-up. A percentage of at most 0.05 is `GREEN`, at most 0.10 is `YELLOW`, and anything above is `RED`.

Third, the store's balance: the order's `total_cents` is added to the store's `outstanding_balance_cents` — which is why settlement can push a store over its credit limit and trigger the automatic suspension from §3.2.

Fourth, the rebate accrual. A store whose `rebate_eligibility_status` is `INELIGIBLE` accrues nothing. A `CONDITIONAL` store accrues its order's `total_cents` multiplied by two percent and by its `exclusive_purchase_pct`, rounded down to whole cents. An `ELIGIBLE` store accrues at five percent on the same basis. When the order rides an `EXECUTING` promotion, the rate is multiplied by one and a half for promotional items. Accrual requires the store to hold an `ACTIVE` compliance agreement; settling an order that would accrue for a store without one fails with `ERR_COMPLIANCE_REQUIRED`. Each accrual is written to the rebate ledger as an `ACCRUAL` entry linked back to the order through `source_order_id`.

Each store also carries a weekly `FoodCostVariance` analysis. An administrator creates one for a `week_start_date`; it is born `PENDING` with `theoretical_cents` and `actual_cents` summed from all of the store's settled orders that week, `variance_cents` as actual minus theoretical, and `variance_pct` as the variance divided by the theoretical figure. Its `severity` follows the same thresholds — at most 0.05 `GREEN`, at most 0.10 `YELLOW`, otherwise `RED`. When a variance crosses into `RED`, the analysis is automatically `FLAGGED`, an alert goes to the `SupplyChainAdmin`, and the store's `compliance_tier` may be downgraded. Analyses that stay within tolerance are finalized to `FINALIZED` by the week's operations checkpoint. Settlement of an order updates the week's analysis as part of its fan-out.

### 3.8. The Rebate Pool: Quarterly Calculation, Holdback, and Settlement

The profit-sharing rebate runs on a quarterly cycle. A `SupplyChainAdmin` opens a rebate pool for a `quarter` such as 2026-Q3; the pool is born `OPEN` with `pool_total_cents`, `distributed_cents`, and `holdback_cents` all at zero, and accruals accumulate against it as orders settle through the quarter.

At quarter end — automatically, or on an administrator's explicit calculation call — the pool moves `OPEN → CALCULATING` and the pool math runs: `pool_total_cents` is ten percent of the summed `total_cents` of every `SETTLED` order in the quarter. Each store whose `rebate_eligibility_status` is anything but `INELIGIBLE` earns a share proportional to its accrued amount — its share of the total accruals across all participating stores — and its rebate is the pool total multiplied by that share, rounded down to whole cents. Amounts under dispute or flagged are reserved into `holdback_cents`, and `distributed_cents` is the pool total less the holdback.

Settlement moves the pool `CALCULATING → SETTLING`. Every ledger entry must be `POSTED` or `SETTLED` before the pool can settle — the transition cascades `PENDING` entries to `POSTED` — and the pool must hold sufficient balance, else `ERR_POOL_INSUFFICIENT`. Settling creates `HOLDBACK` entries for disputed amounts, each scheduled with a `settlement_date` thirty days after the pool closes, and schedules the `SETTLEMENT` entries for payment. The ledger itself records, per entry, its `pool_id`, the `store_id` it credits, an `entry_type` of `ACCRUAL`, `HOLDBACK`, `SETTLEMENT`, `ADJUSTMENT`, or `FORFEITURE`, a signed `amount_cents` (positive credits the store, negative claws back), and a `running_balance_cents` showing the store's cumulative rebate balance after that entry.

Settlement entries are processed in a fixed chronological order: sorted by store, then by `settlement_date`, then by creation time. Each entry whose store has no active dispute settles automatically when its `settlement_date` arrives, moving `POSTED → SETTLED` and — for positive amounts — subtracting `amount_cents` from the store's `outstanding_balance_cents`, so rebates directly pay down what the store owes. Disputed entries stay `POSTED` until the dispute resolves. An administrator may void an entry that is not yet settled — attempting to void a settled one fails with `ERR_REBATE_ALREADY_SETTLED` — moving it `POSTED → VOIDED` and adjusting the pool's `distributed_cents` downward by the entry's amount with `holdback_cents` adjusted accordingly. When every `SETTLEMENT` entry has reached `SETTLED` or `VOIDED`, the pool closes automatically, and the center's `rebate_pool_balance_cents` and `rebate_pool_locked_cents` both reset to zero.

### 3.9. The Operations Checkpoint in Detail

The weekly checkpoint introduced in §2.9 deserves a precise statement of its sweeps, because several of the system's automatic behaviors hang off it. Each run increments the center's `ops_run_index` by one and then sweeps:

- **Stale order expiry.** A purchase order still in `DRAFT` two or more ops runs after its creation is cancelled. A purchase order still in `SUBMITTED` one or more ops runs after its submission is rejected.
- **Compliance evaluation.** The trailing four-week `exclusive_purchase_pct` is recomputed per store, tiers are re-evaluated per the thresholds in §3.2, and two-consecutive-week breaches move agreements to `BREACHED` with the side effects described there.
- **Capacity reconciliation.** The ending week's `LOCKED` plans move to `RECONCILED` with their allocated-versus-actual variance recorded, and `PENDING` food-cost variance analyses for the week move to `FINALIZED`.
- **Rebate settlement progress.** Ledger entries whose `settlement_date` has been reached and whose stores carry no active dispute move to `SETTLED`; pools whose settlement entries have all resolved close.

Every cascade triggered by a run follows the mutation rules of §2.8: affected resources get a fresh `updated_at` and an incremented `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state transitions, return `200 OK`. Nested paths validate their identifiers left to right per §2.6. Flat list endpoints accept the filter parameters shown in §3 and the pagination parameters of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/supply-centers` | Create a new Supply Center | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}` | Get a Supply Center | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/activate` | Activate a Supply Center | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/suspend` | Suspend a Supply Center | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/decommission` | Decommission a Supply Center | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/run_ops` | Run operations checkpoint | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores` | Create a Store | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/stores/{storeId}` | Get a Store | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/stores` | List Stores | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/activate` | Activate a Store | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/suspend` | Suspend a Store | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/terminate` | Terminate a Store | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/products` | Create a Product | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/products/{productId}` | Get a Product | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/products` | List Products | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/products/{productId}/discontinue` | Discontinue a Product | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/products/{productId}/recall` | Recall a Product | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/price-books` | Create a Price Book entry | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/price-books/{priceBookId}` | Get a Price Book | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/price-books` | List Price Books | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes` | Create a Delivery Route | RouteCoordinator |
| GET | `/supply-centers/{centerId}/routes/{routeId}` | Get a Delivery Route | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/routes` | List Delivery Routes | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes/{routeId}/dispatch` | Dispatch a Delivery Route | RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes/{routeId}/cancel` | Cancel a Delivery Route | RouteCoordinator |
| GET | `/supply-centers/{centerId}/routes/{routeId}/stops/{stopId}` | Get a Delivery Stop | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/routes/{routeId}/stops` | List Delivery Stops for a route | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes/{routeId}/stops/{stopId}/arrive` | Mark stop as arrived | RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes/{routeId}/stops/{stopId}/complete` | Complete a delivery stop | RouteCoordinator |
| POST | `/supply-centers/{centerId}/routes/{routeId}/stops/{stopId}/skip` | Skip a delivery stop | RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/purchase-orders` | Create a draft Purchase Order | StoreManager |
| GET | `/supply-centers/{centerId}/purchase-orders/{orderId}` | Get a Purchase Order | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/purchase-orders` | List Purchase Orders | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/purchase-orders/{orderId}/lines` | Add a line to a Purchase Order | StoreManager |
| GET | `/supply-centers/{centerId}/purchase-orders/{orderId}/lines` | List Order Lines | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/purchase-orders/{orderId}/submit` | Submit a Purchase Order | StoreManager |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/confirm` | Confirm a Purchase Order | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/load` | Load a Purchase Order onto truck | RouteCoordinator |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/deliver` | Mark Purchase Order as delivered | RouteCoordinator |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/settle` | Settle a Purchase Order | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/purchase-orders/{orderId}/cancel` | Cancel a Purchase Order | StoreManager |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/reject` | Reject a Purchase Order | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/purchase-orders/{orderId}/lines/{lineId}/mark-shorted` | Mark an order line as shorted | RouteCoordinator |
| POST | `/supply-centers/{centerId}/promotions` | Create a Promotion Event | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/promotions/{promotionId}` | Get a Promotion Event | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/promotions` | List Promotion Events | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/promotions/{promotionId}/confirm` | Confirm a Promotion | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/promotions/{promotionId}/close` | Close a Promotion | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/promotions/{promotionId}/cancel` | Cancel a Promotion | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/rebate-pools` | Create a Rebate Pool for a quarter | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/rebate-pools/{poolId}` | Get a Rebate Pool | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/rebate-pools` | List Rebate Pools | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/rebate-pools/{poolId}/calculate` | Calculate rebate pool totals | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/rebate-pools/{poolId}/settle` | Settle a Rebate Pool | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/rebate-ledgers/{ledgerId}` | Get a Rebate Ledger entry | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/rebate-ledgers` | List Rebate Ledger entries | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/rebate-ledgers/{ledgerId}/void` | Void a Rebate Ledger entry | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/compliance-agreements` | Create a Compliance Agreement | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/compliance-agreements/{agreementId}` | Get a Compliance Agreement | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/compliance-agreements` | List Compliance Agreements | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/compliance-agreements/{agreementId}/activate` | Activate a Compliance Agreement | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/compliance-agreements/{agreementId}/cure` | Cure a breached Compliance Agreement | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/compliance-agreements/{agreementId}/terminate` | Terminate a Compliance Agreement | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/capacity-plans` | Create a Capacity Plan for a week | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/capacity-plans/{planId}` | Get a Capacity Plan | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/capacity-plans` | List Capacity Plans | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/capacity-plans/{planId}/lock` | Lock a Capacity Plan | SupplyChainAdmin |
| GET | `/supply-centers/{centerId}/stores/{storeId}/food-cost-variances/{varianceId}` | Get a Food Cost Variance | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/supply-centers/{centerId}/food-cost-variances` | List Food Cost Variances | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/supply-centers/{centerId}/stores/{storeId}/food-cost-variances` | Create a Food Cost Variance analysis | SupplyChainAdmin |
| POST | `/supply-centers/{centerId}/stores/{storeId}/compliance-reports` | Submit weekly compliance report with external purchases | StoreManager |
| GET | `/stores/{storeId}` | Get a Store by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/stores` | List Stores (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/products/{productId}` | Get a Product by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/products` | List Products (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/routes/{routeId}` | Get a Delivery Route by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/routes` | List Routes (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/delivery-stops/{stopId}` | Get a Delivery Stop by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/delivery-stops` | List Delivery Stops (flat, filterable by `route_id` or `store_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/purchase-orders/{orderId}` | Get a Purchase Order by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/purchase-orders` | List Purchase Orders (flat, filterable) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/order-lines/{lineId}` | Get an Order Line by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/order-lines` | List Order Lines (flat, filterable) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/price-books/{priceBookId}` | Get a Price Book by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/price-books` | List Price Books (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/rebate-pools/{poolId}` | Get a Rebate Pool by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/rebate-pools` | List Rebate Pools (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/rebate-ledgers/{ledgerId}` | Get a Rebate Ledger by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/rebate-ledgers` | List Rebate Ledgers (flat, filterable) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/compliance-agreements/{agreementId}` | Get a Compliance Agreement by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/compliance-agreements` | List Compliance Agreements (flat, filterable) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/promotions/{promotionId}` | Get a Promotion Event by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/promotions` | List Promotion Events (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/capacity-plans/{planId}` | Get a Capacity Plan by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/capacity-plans` | List Capacity Plans (flat, filterable by `center_id`) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/food-cost-variances/{varianceId}` | Get a Food Cost Variance by ID (flat access) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| GET | `/food-cost-variances` | List Food Cost Variances (flat, filterable) | Any, SupplyChainAdmin, StoreManager, RouteCoordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock (default startup time: 2026-09-01T00:00:00Z) | SupplyChainAdmin |

List endpoints accept filter query parameters matching their resource: stores filter by `status` and `compliance_tier`; products by `category` and `status`; routes by `day_of_week` and `status`; stops by `status` (flat access also by `route_id` or `store_id`); purchase orders by `store_id`, `status`, `week_start_date`, and `promotion_id` (flat access also by `center_id` and `route_id`); order lines by `order_id`, `product_id`, and `status`; price books by `product_id`, `store_tier`, and `status`; rebate pools by `quarter` and `status`; rebate ledgers by `pool_id`, `store_id`, `source_order_id`, `entry_type`, and `status`; compliance agreements by `store_id` and `status`; promotions by `status`; capacity plans by `week_start_date` and `status`; food-cost variances by `store_id`, `week_start_date`, `severity`, and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANCE_NOT_FOUND` | 404 Not Found |
| `ERR_CENTER_NOT_ACTIVE` | 409 Conflict |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_PRODUCT_UNAVAILABLE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUTE_OVERLOADED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PRICE_BOOK_OVERLAP` | 409 Conflict |
| `ERR_PROMOTION_OVERLAP` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_COMPLIANCE_REQUIRED` | 409 Conflict |
| `ERR_POOL_INSUFFICIENT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STORE_HAS_ACTIVE_ORDERS` | 409 Conflict |
| `ERR_CENTER_HAS_ACTIVE_STORES` | 409 Conflict |
| `ERR_NO_ROUTE_AVAILABLE` | 409 Conflict |
| `ERR_ORDER_HAS_NO_LINES` | 409 Conflict |
| `ERR_PROMOTION_HAS_COMMITTED_ORDERS` | 409 Conflict |
| `ERR_REBATE_ALREADY_SETTLED` | 409 Conflict |
| `ERR_CAPACITY_PLAN_LOCKED` | 409 Conflict |
