# Instant-Needs MFC API — Product Requirements Document

## 1. Introduction

Instant-needs retail lives or dies on the last fifteen minutes. A customer opens the app at 11:40 PM wanting ice cream, cold medicine, and a phone charger; the business either delivers from a small neighborhood micro-fulfillment site before the craving fades, or it loses the basket to a convenience store run. This document specifies the Instant-Needs Micro-Fulfillment Center (MFC) Operations API: the backend that runs a single fixed-dispatch-site model in the style of Gopuff, where each site carries a few thousand locally curated items as owned inventory, picks customer orders in minutes against strict batch capacity limits, and dispatches its own drivers inside a bounded delivery radius.

The operating reality of a small-footprint site shapes the system's design. Inventory is owned, so vendor replenishment is a first-class workflow with purchase orders that move through `DRAFT`, `PLACED`, and `FINALIZED` states, and the site itself visibly enters a replenishment posture while goods are on the way. Picking is capacity-constrained: a single picker owns a batch, a second picker must seal it, and the site enforces hard ceilings on orders per batch and items per batch. Compliance is non-negotiable: age-restricted products require identification scanning at handoff, with the same driver who carries the bag recording the scan, and refusals feed a structured return-to-stock flow. Around these mechanics the API layers a subscription membership that waives delivery fees above a basket threshold, a loyalty wallet that accrues credit on delivered orders, perishable stock-lot expiry control driven by a logical clock, and a demand forecast that projects late-night and weather-driven spikes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every endpoint of the API. All resources are mounted under the `/mfc` prefix.

### 2.1. User and Role-Based Access Control

Every request carries two authentication headers: `X-User-ID` identifies the acting party and `X-User-Role` declares the caller's operational capacity. The system recognizes exactly four roles: `Customer`, `Picker`, `Driver`, and `SiteOps`; any other role value is malformed. A request missing a well-formed `X-User-Role`, or missing `X-User-ID` where the declared role is entity-backed (`Customer`, `Picker`, or `Driver`), is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint, or whose entity-backed identity does not own the resource being acted on, is rejected with `ERR_UNAUTHORIZED`.

Identity is bound to persisted entities for three of the four roles. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` — an order's `customer_id`, a membership's `customer_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Picker`, `X-User-ID` is the `id` of the acting `Picker`; batch ownership and the self-seal prohibition compare `picker_id` and `sealed_by_id` to `X-User-ID`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; handoff scans, departures, completions, and failed-handoff records all require the bag's `driver_id` to equal `X-User-ID`. When `X-User-Role` is `SiteOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`, and `SiteOps` carries full configuration and exception authority across the API.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource return the created or updated resource object in `data` — that convention covers every state transition (site suspend/resume, product retire, batch append/seal, bag assign/scan/depart/complete/fail-handoff, order cancel, replenish place/finalize/cancel, membership close/renew/cancel) as well; the two exceptions that return a different `data` shape are the clock endpoint and stock adjustments (§3.2).
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and rejects values above 100 with `ERR_INVALID_REQUEST`, as it rejects non-integer values. The `offset` parameter specifies how many items to skip and defaults to 0; a negative or non-integer `offset` is likewise rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system does not consult wall-clock time for any business rule. A server-side logical clock governs stock-lot expiry, age verification at handoff, peak-window fee surcharges, and membership billing periods. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time, and it changes only when a `SiteOps` operator sets it through the test-driving clock endpoint by supplying a `current_utc` instant. A malformed `current_utc` is rejected with `ERR_INVALID_REQUEST`; a successful set returns `200` with `data` of the form `{"current_utc": "<echoed instant>"}` rather than a resource object. Advancing the clock is observable immediately: stock lots recompute their `FRESH` / `EXPIRING` / `EXPIRED` status against the new instant on their next read, and site postures follow on the same basis.

### 2.5. Site Posture and the Replenishment Interlock

A `Site` carries a persisted `status` that moves cyclically between `OPERATING` and `SUSPENDED`, and a derived `effective_status` computed on every read. The rule for `effective_status` is fixed: if the site's `status` is `SUSPENDED`, the effective posture is `SUSPENDED`; otherwise, if any `ReplenishOrder` belonging to the site is in `PLACED`, the effective posture is `OPENED_REPLENISH`; otherwise it is `OPERATING`. The `OPENED_REPLENISH` posture is an interlock, not a shutdown: it blocks new customer order placement but never interferes with picking, sealing, or dispatch of work already in flight.

Suspending a site is deliberately conservative. The transition `OPERATING → SUSPENDED` requires that no `PickBatch` at the site is `OPEN` or `SEALED` and that no `Order` at the site is `PICKING`, `AWAITING_HANDOFF`, or `OUT_FOR_DELIVERY`; a violation is rejected with `ERR_SITE_BUSY`. Resuming returns the site to `OPERATING` provided it is currently `SUSPENDED`. Every transition on the site — suspend, resume, capacity-profile update — mutates the site resource, which refreshes its `updated_at` and increments its `version`.

### 2.6. Common Resource Properties and Cross-Resource Validation

Every resource in the API — `Site`, `Product`, `InventoryBalance`, `StockLot`, `Customer`, `Membership`, `ReplenishOrder`, `Order`, `PickBatch`, `Picker`, `Driver`, and `DeliveryBag` — carries a standard set of system-managed fields (resources are created with `version` 1):

- **`id` (string):** a server-minted UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- **`version` (integer):** incremented by exactly 1 on every mutation of the resource, including mutations performed as side effects of another resource's transition.

Validation of identifiers follows a fixed order. Authentication and role checks come first (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`). Existence checks come next: path identifiers are validated left to right, and each missing identifier produces the corresponding not-found error — `ERR_SITE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PICK_BATCH_NOT_FOUND`, `ERR_PICKER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_DELIVERY_BAG_NOT_FOUND`, `ERR_REPLENISH_ORDER_NOT_FOUND`, `ERR_STOCK_LOT_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`. There is no balance-specific not-found error: an `InventoryBalance` path identifier that matches no row is rejected with `ERR_INVALID_REQUEST`. Body foreign-key fields are then validated in the order they are declared in the endpoint's input contract; for a body-supplied entity identifier that must also match the caller's identity (such as `customer_id` on order placement or membership enrollment), the existence check precedes the ownership comparison against `X-User-ID`. Only after existence does the server evaluate state-transition legality (`ERR_INVALID_STATE`), business-safety rules, capacity and fiscal constraints, optimistic-concurrency checks, uniqueness (`ERR_DUPLICATE_RESOURCE`), and finally payload well-formedness (`ERR_INVALID_REQUEST`). This ordering is normative: when several violations coexist, the earliest category in this sequence determines the response.

### 2.7. Monetary Precision and Rounding

All monetary values are integer cents. Fee schedules, wallet balances, order money fields, membership fees, and loyalty credit amounts are all expressed in whole cents; the API never emits fractional monetary values. Every rounding applied during a calculation rounds half-up to the nearest integer cent, and the points at which rounding occurs are pinned per calculation in §3 — in particular, order tax rounds each taxed line to cents before summing, and summing raw amounts before a single rounding is a rejected alternative that can differ from the pinned rule. Non-monetary derived counts (projected orders in the demand forecast) round half-up to whole units.

### 2.8. Optimistic Concurrency Control

Two write operations in the API are protected by optimistic concurrency control against a parent entity's `version`.

A capacity-profile update on a `Site` — touching `batch_max_lines`, `batch_max_items`, `expiry_horizon_days`, or `fee_waiver_threshold_cents` — requires the client to supply `expected_site_version` carrying the site `version` the client last observed; a missing or non-integer `expected_site_version` is rejected with `ERR_INVALID_REQUEST`. If the site's current `version` has advanced since that observation, the update is rejected with `ERR_STALE_VERSION` (HTTP 412): the client would otherwise be configuring caps and horizons it never saw.

Renewing or cancelling a `Membership` is restricted to the `Customer` role (per §4), requires the caller to own the membership, and requires the client to supply `expected_customer_version` matching the owning `Customer`'s current `version`. Because a loyalty accrual on a delivered order bumps `Customer.version`, a membership write carrying a version observed before that accrual is rejected with `ERR_STALE_VERSION` (HTTP 412), keeping membership lifecycle writes serialized against wallet-mutating cascades.

Endpoints not listed here do not accept a version field and perform no OCC check.

### 2.9. Batch Capacity and Segregation of Duties

Pick capacity at a site is bounded by two ceilings configured on the site itself: `batch_max_lines` caps the number of distinct orders in one open batch, and `batch_max_items` caps the summed line quantities across those orders. The line ceiling is inclusive — a batch already holding exactly `batch_max_lines` orders is full — while the item ceiling rejects on overflow, when the incoming order's quantities would push the batch past `batch_max_items`. Both rejections surface as `ERR_BATCH_FULL`.

The picking workflow enforces segregation of duties. Exactly one picker owns a batch, and the picker who seals a batch must be a different picker than the owner; a self-seal attempt is rejected with `ERR_SELF_SEAL_FORBIDDEN`. Only `ACTIVE` pickers may own or seal batches; a batch-open naming an `INACTIVE` picker is rejected with `ERR_INVALID_REQUEST`, while a sealing attempt by an `INACTIVE` (or unknown) picker is rejected with `ERR_UNAUTHORIZED`. Drivers likewise may not act on bags assigned to another driver: handoff scans, departures, completions, and failure records on a bag whose `driver_id` differs from the acting driver's identity are rejected with `ERR_UNAUTHORIZED`.

## 3. Business Logic & Workflows

### 3.1. Sites, Catalog, and Capacity Profiles

A `SiteOps` operator onboards a micro-fulfillment site by creating a `Site` with a human-readable `code` (unique across all sites), a display `name`, and the operating parameters that every downstream rule depends on: `delivery_radius_miles` (strictly greater than zero; orders beyond this straight-line distance are rejected), the `fee_schedule` object, `fee_waiver_threshold_cents` (zero or greater), the batch ceilings `batch_max_lines` and `batch_max_items` (each at least 1), `expiry_horizon_days` (zero or greater), and an optional `peak_windows` list. A new site starts in `OPERATING` with `version` 1.

The `fee_schedule` is an object of six fields, each a non-negative integer (the monetary fields in integer cents): `base_cents`, `per_mile_cents`, `included_miles` (whole miles), `peak_surcharge_cents`, `min_fee_cents`, and `max_fee_cents`. The `peak_windows` list holds entries of the form `{ day_of_week, start, end }`, where `day_of_week` is one of `MON` through `SUN` and the times are `HH:MM` strings interpreted in UTC with hours 00–23 and minutes 00–59 — with `24:00` additionally accepted as the end-of-day boundary, allowing an overnight peak to be expressed as e.g. FRI 22:00→24:00 plus SAT 00:00→04:00; an order whose placement hour-of-week falls inside any window pays the peak surcharge, and an empty list means the site never peaks. These capacity and fee parameters are not frozen at creation: a `SiteOps` operator may later retune `batch_max_lines`, `batch_max_items`, `expiry_horizon_days`, and `fee_waiver_threshold_cents` through the capacity-profile update, which operates under the optimistic-concurrency rule of §2.8 and increments the site's `version` on success.

The product catalog is flat and merchant-owned. A `SiteOps` operator creates a `Product` with a `sku` (unique across the catalog), a display `name`, a `price_cents` unit price strictly greater than zero, and a `product_class` of `STANDARD`, `AGE_RESTRICTED`, or `PERISHABLE`. Two read-only mirrors are derived from the class: `restricted` is true exactly when the class is `AGE_RESTRICTED`, and `perishable` is true exactly when the class is `PERISHABLE`. Products are created `ACTIVE` and may later be retired; retirement is one-way, requires the product to currently be `ACTIVE`, and is blocked with `ERR_PRODUCT_IN_USE` while any order line references the product on an order in `PLACED`, `PICKING`, `AWAITING_HANDOFF`, or `OUT_FOR_DELIVERY` (a `HANDOFF_FAILED` order no longer counts as in-flight). A `RETIRED` product is unpickable: order placement for a non-`ACTIVE` product fails with `ERR_PRODUCT_UNSELLABLE`.

### 3.2. Inventory Foundations: Balances, Lots, and Stock Adjustments

Owned inventory is tracked per site and product on an `InventoryBalance` row. Creating the row requires a `site_id` and a `product_id` and accepts an optional `min_par_level` (defaulting to 0, never negative); the row is born with `on_hand` 0, `reserved` 0, and `on_order` 0. At most one balance exists per (site, product) pair: a second creation for a pair that already has a row is rejected with `ERR_DUPLICATE_RESOURCE`. The `on_hand` figure is a derived physical count that clients never set directly: it is seeded by stock adjustments of `kind` `RECEIPT`, advanced by finalized replenishment receipts, consumed by committed picks, and restored by return-to-stock receipts. The `reserved` figure counts units allocated to `PLACED` orders at the site, and `on_order` counts units sitting on vendor purchase orders in `PLACED` status.

Stock adjustments give operators the two sanctioned ways to move `on_hand` outside the order lifecycle. A receipt adjustment carries a `kind` of `RECEIPT` and a `qty` of at least 1 and adds that quantity to `on_hand` — the canonical way to seed opening stock or apply count corrections. A shrink disposal carries a `kind` of `SHRINK_DISPOSE` and a `lot_id`, writes off units from that specific stock lot, and is guarded: the lot must be `EXPIRED` at the logical clock, and the disposed `qty` may not exceed the lot's `remaining_qty`; violations of either guard are rejected with `ERR_SHRINK_EXCEEDS_LOT`. A successful disposal decrements both the lot's `remaining_qty` and the balance's `on_hand` by the disposed quantity. Both adjustment kinds return `201` with a `data` object of the form `{balance_id, on_hand, applied_qty}` — the resulting balance's `on_hand` and the applied quantity — rather than a resource object, and both accept an optional `reason` for the audit trail.

Perishable inventory is lot-tracked. A `StockLot` records its `site_id`, `product_id`, a vendor `lot_code` unique per site-and-product pair, a `received_qty` of at least 1, a `remaining_qty` that shrinks as picks and disposals consume the lot, and an `expires_at` instant. The lot's `status` is derived on every read against the logical clock with exact boundary semantics: a lot whose `expires_at` is at or before the current logical instant is `EXPIRED`; otherwise, a lot whose `expires_at` falls within the site's `expiry_horizon_days` of the current instant is `EXPIRING`; all other lots are `FRESH`. Expiry exactly at the horizon edge counts as `EXPIRING` and is therefore blocked from picking; expiry exactly at the current instant counts as `EXPIRED` and becomes eligible for write-off.

The availability model is forward-looking. The pickable quantity for a product is the balance's `on_hand` minus its `reserved`, and a line is pickable only when that available figure covers the requested quantity and the product is `ACTIVE`. Perishable lines carry an additional gate, evaluated at batch-append time: the sum of `remaining_qty` across that product's `FRESH` lots at the site must cover the requested quantity, otherwise the append fails with `ERR_PRODUCT_UNSELLABLE`. Separately, the replenishment-facing stockout posture flags a site-product pair as stocked out when `on_hand` plus `on_order` falls below `min_par_level` — the reorder signal weighs units already committed to vendors, not just what sits on the shelf.

### 3.3. Vendor Replenishment and Site Posture

Replenishment is a purchase-order workflow owned by `SiteOps`. Creating a `ReplenishOrder` requires the target `site_id`, a vendor-facing `reference` unique within the site, a non-empty `lines` list whose entries each carry a `product_id`, a `qty` of at least 1, and a `unit_cost_cents` of zero or more, an `expected_at` vendor delivery instant, and an `idempotency_key`. The idempotency key is unique per site: replaying the creation with the same key returns the original record without creating a second order. New purchase orders are born `DRAFT`.

Placing the order with the vendor transitions it `DRAFT → PLACED`. Placement requires the site's `effective_status` to be `OPERATING`; a suspended site, or one already in `OPENED_REPLENISH` posture, rejects the placement with `ERR_SITE_NOT_OPERATING`. Every line's product must also already have an `InventoryBalance` row at the site; a line without one rejects the placement with `ERR_INVALID_REQUEST`. On placement, each line credits `on_order` on the corresponding `InventoryBalance` by its `qty`, and each such credit re-derives that balance's stockout posture — once `on_hand` plus `on_order` reaches `min_par_level`, the stockout flag clears. Because the site now has a purchase order in `PLACED`, the site's `effective_status` reads `OPENED_REPLENISH` on subsequent reads, and the order's `version` increments.

Receiving the goods transitions the purchase order `PLACED → FINALIZED` as one atomic, all-or-nothing operation. Every line's `qty` moves from `on_order` to `on_hand` on its balance. For every line whose product is `PERISHABLE`, the server creates a `StockLot` with `received_qty` and `remaining_qty` equal to the line quantity, a server-generated `lot_code` unique for the (site, product) pair, and an `expires_at` taken from the `lot_expiries` supplied with the finalization request, keyed by `product_id`; the payload must supply an expiry for every perishable line. Finalization likewise requires every line's product to already have an `InventoryBalance` row at the site, rejecting with `ERR_INVALID_REQUEST` otherwise, and it validates all lines before applying any change, so a rejected finalization leaves the order and balances untouched. With no purchase order left in `PLACED` at the site, the site's posture recomputes and `effective_status` falls back to `OPERATING`. Alternatively, a vendor shortfall is handled by cancelling a `PLACED` order, which transitions it to `CANCELLED` and debits each line's `qty` back out of `on_order` — the exact compensation of the placement side effect — without touching `on_hand`.

### 3.4. Customer Registration, Wallets, and the FAM Membership

Customers register themselves by supplying an `email` (unique), a `full_name` used later for age-restricted handoff comparison, and a `date_of_birth`. A new customer starts `ACTIVE` with a `wallet_credit_cents` balance of 0. Customer accounts cycle between `ACTIVE` and `SUSPENDED`. The wallet is the customer's loyalty credit balance: it accrues on delivered orders per the accrual rule of §3.7, is consumed at order placement before fee computation per §3.5, and can be adjusted directly by `SiteOps` through an operator credit or debit carrying an `amount_cents` (positive or negative) and a `reason`; operator adjustments floor the resulting balance at 0, require a `reason` string, return the updated customer with `201`, and increment the customer's `version`.

The subscription program is the `FAM` membership tier — the instant-needs free-delivery membership. A customer enrolls themselves by providing their `customer_id`, the `tier` (currently always `FAM`), a `monthly_fee_cents` of zero or more, and an optional `auto_renew` flag defaulting to true (a non-boolean `auto_renew` is rejected with `ERR_INVALID_REQUEST`). At most one membership exists per customer; a second enrollment attempt is rejected with `ERR_DUPLICATE_RESOURCE`. Enrollment creates an `ACTIVE` membership whose `current_period_start` is the current logical instant and whose `current_period_end` is exactly 30 days later, with `periods_paid`, `period_orders_count`, `period_credit_earned_cents`, and `tenure_discount_bps` all starting at zero.

The billing close is an ops-run checkpoint: once the logical clock reaches `current_period_end` — at the exact end instant or later — a `SiteOps` operator runs the close supplying `period_fee_paid`; an early close is rejected with `ERR_INVALID_STATE`. The close may run on an `ACTIVE` or `LAPSED` membership, never on a `CANCELLED` one. The close follows a pinned evaluation order. First, the fee for the period just ended is charged as `monthly_fee_cents` reduced by the `tenure_discount_bps` in force *before* this close — a basis-point discount expressed in ten-thousandths — rounded half-up to integer cents. Second, if `period_fee_paid` is true, `periods_paid` increments by 1. Third, `tenure_discount_bps` is recomputed for the *next* period: it becomes 500 basis points (a 5% discount) once `periods_paid` has reached 12, and remains 0 below that tenure threshold. Fourth, the period window advances: `current_period_start` becomes the old `current_period_end`, and the new `current_period_end` is 30 days beyond that. Fifth, `period_orders_count` and `period_credit_earned_cents` reset to 0. Finally, if the period fee went unpaid, the membership transitions `ACTIVE → LAPSED`.

A `LAPSED` membership can be revived: the owning customer renews it, which requires the membership to currently be `LAPSED`, operates under the customer-version OCC rule of §2.8, and on success returns the membership to `ACTIVE` with a fresh 30-day period starting at the logical clock. A customer may also cancel an `ACTIVE` membership outright; cancellation is one-way to `CANCELLED`, requires the customer to own the membership, and carries the same `expected_customer_version` OCC guard — a stale version is rejected with `ERR_STALE_VERSION`. Both renewal and cancellation increment the membership's and the customer's `version`.

### 3.5. Order Placement and Basket Pricing

A customer places an order by supplying their own `customer_id` (which must equal their identity), the fulfilling `site_id`, a non-empty `lines` list whose entries each carry a `product_id` and a `qty` of at least 1, and the `delivery_distance_miles` from site to drop-off (a non-negative number; zero is allowed and fractional miles are billable). Placement enforces a sequence of gates, in this order: the site's `effective_status` must be `OPERATING` (otherwise `ERR_SITE_NOT_OPERATING`); then the distance may not exceed the site's `delivery_radius_miles` (otherwise `ERR_DELIVERY_RADIUS_EXCEEDED`); then every line's product must be `ACTIVE` (otherwise `ERR_PRODUCT_UNSELLABLE`). The server then computes the order's money fields in a pinned order and creates the order in `PLACED` with `pick_batch_id` null.

First, the basket: `subtotal_cents` is the sum of each line's unit price multiplied by its quantity, and `contains_age_restricted` is set true exactly when any line's product is `AGE_RESTRICTED`.

Second, wallet absorption: the customer's loyalty wallet offsets the basket before any fee is computed. The applied amount, recorded as `loyalty_credit_applied_cents`, is the smaller of the customer's `wallet_credit_cents` and the subtotal (the wallet floor is zero, so the wallet can absorb up to the full subtotal), and the wallet is debited by that amount immediately. When credit is absorbed, the customer's `version` increments as part of the placement; a placement that absorbs nothing leaves the customer's `version` unchanged.

Third, tax: only `AGE_RESTRICTED` lines are taxed, at a rate of 7 percent. The pinned rounding order is per-line-then-sum: each taxed line's amount — quantity multiplied by unit price multiplied by the 7 percent rate — is rounded half-up to integer cents individually, and the rounded line amounts are summed into `tax_cents`. Summing raw line amounts and rounding once at the end is a rejected alternative; it can diverge from the pinned rule by a cent or more.

Fourth, the delivery fee, computed on the raw subtotal rather than the post-absorption amount because the membership waiver speaks of the basket, not the amount charged. The fee starts at the schedule's `base_cents`; the billable distance is the order's `delivery_distance_miles` minus the schedule's `included_miles`, floored at zero, and the billable miles multiplied by `per_mile_cents` — rounded half-up to integer cents — is added. If the placement instant falls inside any of the site's `peak_windows`, the `peak_surcharge_cents` is added. The result is then clamped: raised to at least `min_fee_cents` and capped at `max_fee_cents`. Finally, the waiver applies: if the customer holds an `ACTIVE` membership and the order's `subtotal_cents` is at least the site's `fee_waiver_threshold_cents` — meeting the threshold exactly waives the fee — the fee becomes 0. The result is recorded as `delivery_fee_cents`, and the order's `total_cents` is the subtotal plus tax plus the delivery fee minus the applied loyalty credit.

### 3.6. Picking Waves and Batch Sealing

Fulfilment work is organized into pick batches. A batch is opened with a `site_id` and the `picker_id` of the single picker who owns it, and is born `OPEN` with an empty `order_ids` list and `total_items` 0. Only `ACTIVE` pickers may own batches. When the caller is itself a `Picker` (rather than `SiteOps`), it may open batches only for itself: a `picker_id` that differs from the caller's `X-User-ID` is rejected with `ERR_UNAUTHORIZED`. A batch's `total_items` is a derived field, recomputed on every read as the summed line quantities across the orders currently in `order_ids`.

Appending an order to an open batch — the append request names the target `order_id` — is the moment an order leaves the customer's hands and enters the warehouse floor, transitioning the order `PLACED → PICKING` automatically. The order must currently be `PLACED` (otherwise `ERR_INVALID_STATE`) and must belong to the same site as the batch (a cross-site order is rejected with `ERR_INVALID_REQUEST`). The append is heavily guarded, and the guards are evaluated in the validation priority order of §2.6: the batch must be `OPEN` (otherwise `ERR_INVALID_STATE`); both capacity ceilings of §2.9 apply, so a batch already holding `batch_max_lines` orders, or one whose `total_items` plus the incoming order's quantities would exceed `batch_max_items`, rejects with `ERR_BATCH_FULL`; every line's available stock — `on_hand` minus `reserved` — must cover the requested quantity, otherwise `ERR_INSUFFICIENT_STOCK`; every perishable line must have sufficient `FRESH`-lot cover, otherwise `ERR_PRODUCT_UNSELLABLE`; and if the order `contains_age_restricted`, the customer's age at the logical clock must be at least 21 — a customer whose 21st birthday is the current date passes — otherwise the append is rejected with `ERR_AGE_VERIFICATION_REQUIRED` as a pre-screen ahead of the physical handoff. On success, each line's quantity is added to the balance's `reserved` (the reservation that later commits to a physical pick), the order's `pick_batch_id` is set to the batch, the batch's `order_ids` extends and `total_items` recomputes, and both the order's and the batch's `version` increment.

Sealing the batch is the point of no return, and it belongs to a *different* picker than the owner — the segregation-of-duties rule of §2.9. Sealing requires the batch to be `OPEN` with at least one appended order; sealing an empty batch is rejected with `ERR_BATCH_EMPTY`. When both violations coexist, the business-safety self-seal check (`ERR_SELF_SEAL_FORBIDDEN`) precedes the capacity check (`ERR_BATCH_EMPTY`), per the normative priority ordering of §2.6. The seal writes `sealed_at` and `sealed_by_id`, moves the batch to `SEALED`, and fans out a per-order cascade: every appended order transitions `PICKING → AWAITING_HANDOFF`; for every line, the reservation commits, subtracting the quantity from `reserved` and from `on_hand`; and for every line on a perishable product, the quantity is deducted from that product's `FRESH` lots at the site in earliest-expiry-first order — ordered by `expires_at` ascending, ties broken by `created_at` ascending — attributing the pick to specific lots. The batch closes automatically: once every appended order has reached a terminal state (`DELIVERED` or `CANCELLED`), the batch transitions `SEALED → CLOSED` with no operator action.

### 3.7. Dispatch, Handoff Compliance, and Delivery

Once an order reaches `AWAITING_HANDOFF`, a `SiteOps` operator creates its `DeliveryBag` — creation requires the order to be `AWAITING_HANDOFF` (otherwise `ERR_INVALID_STATE`), and there is at most one bag per order, with duplicates rejected as `ERR_DUPLICATE_RESOURCE`. The bag is born with `delivery_status` `UNASSIGNED` and `handoff_status` `NONE`, its `driver_id` null; its site is that of the parent order.

Dispatch assigns the bag to a driver. The operator may name a driver explicitly by supplying `driver_id` — an explicit assignment needs no further eligibility checks, so any rostered driver may be named regardless of site, status, or current run — or omit it to invoke the server-side selector. Either way the parent order must be `AWAITING_HANDOFF` and the bag `UNASSIGNED`, with violations rejected as `ERR_INVALID_STATE`. The selector's candidate set is the drivers of the bag's site whose `status` is `AVAILABLE` and whose current run — bags they hold in `ASSIGNED` or `OUT_FOR_DELIVERY` — carries strictly fewer orders than their `max_run_orders`. Candidates are ranked by current run size ascending, ties broken by the driver's `created_at` ascending — the earliest-rostered driver wins. An empty candidate set rejects the assignment with `ERR_NO_DRIVER_AVAILABLE`. A successful assignment sets `driver_id` and `assigned_at` and moves the bag `UNASSIGNED → ASSIGNED`. Drivers themselves are rostered by `SiteOps` at a site with a `name`, a `max_run_orders` of at least 1, and a `status` of `AVAILABLE`, `OFF_DUTY`, or `SUSPENDED` (defaulting to `AVAILABLE`); pickers are rostered similarly at a site with a `status` of `ACTIVE` or `INACTIVE` (defaulting to `ACTIVE`).

Age-restricted handoff is a compliance gate with its own state machine living on the bag's `handoff_status`, which evolves independently of `delivery_status`. After assignment and before departure, the assigned driver scans the recipient's identification, supplying the `scanned_birthdate` and the `scanned_id_last4` — the last four characters of the document, retained as the audit trail. The scan is permitted only when the order `contains_age_restricted` (scanning for an order with no restricted lines is rejected with `ERR_HANDOFF_NOT_REQUIRED`), the handoff is still in `NONE` and the bag's `delivery_status` is `ASSIGNED` (violations of either are `ERR_INVALID_STATE`), and the acting driver is the bag's assignee. The scan moves `handoff_status` from `NONE` to `ID_SCANNED` and immediately resolves: if the scanned birthdate makes the recipient at least 21 years old at the logical clock — a recipient whose 21st birthday is the current date counts as 21 — the handoff advances to `AGE_VERIFIED`; otherwise it moves to `REFUSED`, and the order becomes eligible for the failed-handoff path of §3.8.

Departure transitions the order `AWAITING_HANDOFF → OUT_FOR_DELIVERY` and the bag's `delivery_status` to `OUT_FOR_DELIVERY` in one cascade. The driver must be the bag's assignee, the bag must be `ASSIGNED` (otherwise `ERR_BAG_NOT_ASSIGNED`), and — critically — an order that `contains_age_restricted` may not depart unless the handoff has reached `AGE_VERIFIED`; departing otherwise is rejected with `ERR_HANDOFF_NOT_VERIFIED`.

Completing the delivery transitions the order to `DELIVERED` and the bag's `delivery_status` to `DELIVERED`. The bag must currently be `OUT_FOR_DELIVERY` — completing from any other state is rejected with `ERR_INVALID_STATE` — and the acting driver must again be the bag's assignee. Completion is the loyalty accrual point, and it follows a dual-variant rule: if the order absorbed wallet credit at placement — `loyalty_credit_applied_cents` greater than zero — the order earns exactly 0 cents, because the customer already saved at placement; otherwise the order earns the smaller of 500 cents and 3 percent of the sum of `subtotal_cents` and `delivery_fee_cents`, rounded half-up to integer cents. The earned amount is added to the customer's `wallet_credit_cents`, and when the customer holds a membership — of any status — the same amount is added to `period_credit_earned_cents` while `period_orders_count` increments by 1. Completion increments the `version` of the order, the bag, and the customer (and the membership when one exists), and when the completed order was the last non-terminal order of its batch, the batch auto-closes per §3.6. The completion response returns the updated bag.

### 3.8. Failure Paths: Refusals, Returns, and Cancellations

Two cancellation paths exist, distinguished by the order's state, the actor, and a mandatory `reason`.

A customer may cancel their own order only while it is `PLACED`, with `reason` `CUSTOMER`; acting on another customer's order is `ERR_UNAUTHORIZED`, and any other reason or state is rejected (`ERR_INVALID_REQUEST` or `ERR_INVALID_STATE` respectively). This path refunds the absorbed loyalty credit — the `loyalty_credit_applied_cents` returns to the customer's `wallet_credit_cents` — and increments the order's and the customer's `version` (a cancellation that refunds nothing still touches both). No stock movement occurs because no reservation exists yet at `PLACED`.

The post-refusal path runs through operations. After a handoff refusal, the assigned driver records the failed handoff, which requires `handoff_status` to be `REFUSED` (otherwise `ERR_REFUSAL_REQUIRED`) and transitions the order `AWAITING_HANDOFF → HANDOFF_FAILED` while the bag's `delivery_status` moves to `FAILED` in parallel. From `HANDOFF_FAILED`, a `SiteOps` operator cancels the order with `reason` `RETURN_TO_STOCK`; any other reason — including a well-formed reason that does not match the acting role, such as a Customer sending `RETURN_TO_STOCK` — is `ERR_INVALID_REQUEST`. Return-to-stock restocks every non-perishable line: for each such line the server creates a `StockLot` with `lot_code` formed as `RMA-` followed by the order id and product id, `received_qty` and `remaining_qty` equal to the line quantity, and `expires_at` pinned to `2099-12-31T00:00:00Z` (if such a lot already exists for that (site, product), the line's quantity is added to its `received_qty` and `remaining_qty` instead of creating a duplicate), and adds the quantity back to the balance's `on_hand`. Perishable lines are never restocked — food safety — and are written off instead. Because the delivery never completed, no loyalty was earned on the order, so the reversal instead refunds the absorbed credit: `loyalty_credit_applied_cents` is added back to the customer's `wallet_credit_cents`, and the order's and customer's `version` increment. Both cancellation paths return the updated order in `data`.

### 3.9. Demand Forecasting

Site operators read an hourly demand projection for the next 24 hours, optionally supplying a `precipitation_prob` between 0 and 1 with the request (defaulting to 0; a value outside that range or non-numeric is rejected with `ERR_INVALID_REQUEST`). The projection for each hour starts from a baseline: the count of orders at the site that reached `DELIVERED` whose creation instant falls within the trailing 7 days up to the logical clock in the same hour-of-day. Two bounded multipliers then adjust the baseline. When the projected hour falls in the late-night window — from 22:00 up to but not including 04:00 — the baseline is scaled by a night multiplier of 1.40 (a 40 percent lift); outside that window the multiplier is 1. The weather multiplier is 1 plus the supplied precipitation probability scaled by 0.25 (a 25 percent lift at certain rain). The projected order count for the hour is the baseline multiplied by both multipliers, rounded half-up to a whole number of orders. The response `data` is `{site_id, hours}`, where `hours` is a 24-entry list covering the 24 consecutive hours starting at the current logical hour, each entry carrying `hour_of_day`, `hour_utc` (the hour's start instant), `baseline_orders`, `night_multiplier`, `weather_multiplier`, and `projected_orders`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Readers should reconstruct each operation's request body, computed fields, and side effects from the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mfc/_clock/set_current_utc` | Set the logical clock | SiteOps |
| POST | `/mfc/sites` | Create a micro-fulfillment site | SiteOps |
| GET | `/mfc/sites` | List sites | SiteOps, Picker, Driver, Customer |
| GET | `/mfc/sites/{siteId}` | Get a site including computed effective_status | SiteOps, Picker, Driver, Customer |
| PUT | `/mfc/sites/{siteId}/capacity-profile` | Update batch caps, expiry horizon, and fee-waiver threshold under OCC | SiteOps |
| POST | `/mfc/sites/{siteId}/suspend` | Suspend a site (no open batches or in-flight orders) | SiteOps |
| POST | `/mfc/sites/{siteId}/resume` | Resume a suspended site | SiteOps |
| GET | `/mfc/sites/{siteId}/demand-forecast` | Hourly demand projection for the next 24 hours | SiteOps |
| POST | `/mfc/products` | Create a catalog product | SiteOps |
| GET | `/mfc/products` | List products | SiteOps, Picker, Driver, Customer |
| GET | `/mfc/products/{productId}` | Get a product | SiteOps, Picker, Driver, Customer |
| POST | `/mfc/products/{productId}/retire` | Retire a product | SiteOps |
| POST | `/mfc/inventory-balances` | Create the (site, product) balance row | SiteOps |
| GET | `/mfc/inventory-balances` | List balances, filterable by site and product | SiteOps, Picker |
| GET | `/mfc/inventory-balances/{balanceId}` | Get one balance row | SiteOps, Picker |
| POST | `/mfc/inventory-balances/{balanceId}/adjustments` | Stock adjustment: RECEIPT seeds on_hand; SHRINK_DISPOSE writes off lot units | SiteOps |
| GET | `/mfc/stock-lots` | List stock lots with computed expiry status | SiteOps, Picker |
| GET | `/mfc/stock-lots/{lotId}` | Get one stock lot | SiteOps, Picker |
| POST | `/mfc/customers` | Register a customer | Customer |
| GET | `/mfc/customers` | List customers | SiteOps |
| GET | `/mfc/customers/{customerId}` | Get a customer (SiteOps any; Customer only self) | SiteOps, Customer |
| POST | `/mfc/customers/{customerId}/wallet/adjustments` | Operator credit/debit of the loyalty wallet | SiteOps |
| POST | `/mfc/memberships` | Enroll a customer in the FAM tier | Customer |
| GET | `/mfc/memberships` | List memberships, filterable by customer | SiteOps, Customer |
| GET | `/mfc/memberships/{membershipId}` | Get a membership | SiteOps, Customer |
| POST | `/mfc/memberships/{membershipId}/close-period` | Run the billing close at or after current_period_end | SiteOps |
| POST | `/mfc/memberships/{membershipId}/renew` | Renew a LAPSED membership under OCC | Customer |
| POST | `/mfc/memberships/{membershipId}/cancel` | Cancel an ACTIVE membership under OCC | Customer |
| POST | `/mfc/replenish-orders` | Create a DRAFT vendor purchase order | SiteOps |
| GET | `/mfc/replenish-orders` | List replenish orders | SiteOps |
| GET | `/mfc/replenish-orders/{replenishOrderId}` | Get a replenish order | SiteOps |
| POST | `/mfc/replenish-orders/{replenishOrderId}/place` | Place the purchase order with the vendor | SiteOps |
| POST | `/mfc/replenish-orders/{replenishOrderId}/finalize` | Receive the goods (bulk, all-or-nothing) | SiteOps |
| POST | `/mfc/replenish-orders/{replenishOrderId}/cancel` | Cancel a placed purchase order | SiteOps |
| POST | `/mfc/pickers` | Roster a picker at a site | SiteOps |
| GET | `/mfc/pickers` | List pickers | SiteOps, Picker |
| GET | `/mfc/pickers/{pickerId}` | Get a picker | SiteOps, Picker |
| POST | `/mfc/drivers` | Roster a driver at a site | SiteOps |
| GET | `/mfc/drivers` | List drivers | SiteOps, Driver |
| GET | `/mfc/drivers/{driverId}` | Get a driver | SiteOps, Driver |
| POST | `/mfc/orders` | Place an order (customer must be self) | Customer |
| GET | `/mfc/orders` | List orders | SiteOps, Picker, Driver, Customer |
| GET | `/mfc/orders/{orderId}` | Get an order | SiteOps, Picker, Driver, Customer |
| POST | `/mfc/orders/{orderId}/cancel` | Cancel a PLACED or HANDOFF_FAILED order | Customer, SiteOps |
| POST | `/mfc/pick-batches` | Open a pick batch owned by a single picker | SiteOps, Picker |
| GET | `/mfc/pick-batches` | List pick batches | SiteOps, Picker |
| GET | `/mfc/pick-batches/{batchId}` | Get a pick batch | SiteOps, Picker |
| POST | `/mfc/pick-batches/{batchId}/orders` | Append a PLACED order to an OPEN batch | Picker |
| POST | `/mfc/pick-batches/{batchId}/seal` | Seal the batch — a different picker than the owner | Picker |
| POST | `/mfc/delivery-bags` | Create the delivery bag for an AWAITING_HANDOFF order | SiteOps |
| GET | `/mfc/delivery-bags` | List delivery bags | SiteOps, Driver |
| GET | `/mfc/delivery-bags/{bagId}` | Get a delivery bag | SiteOps, Driver |
| POST | `/mfc/delivery-bags/{bagId}/assign` | Assign the bag explicitly or via the selector | SiteOps |
| POST | `/mfc/delivery-bags/{bagId}/handoff-scan` | Scan the recipient's identification at handoff | Driver |
| POST | `/mfc/delivery-bags/{bagId}/depart` | Driver departs the site with the bag | Driver |
| POST | `/mfc/delivery-bags/{bagId}/complete` | Mark the delivery completed | Driver |
| POST | `/mfc/delivery-bags/{bagId}/fail-handoff` | Record a failed handoff after a refusal | Driver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_PICK_BATCH_NOT_FOUND` | 404 |
| `ERR_PICKER_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_BAG_NOT_FOUND` | 404 |
| `ERR_REPLENISH_ORDER_NOT_FOUND` | 404 |
| `ERR_STOCK_LOT_NOT_FOUND` | 404 |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SITE_NOT_OPERATING` | 409 |
| `ERR_SITE_BUSY` | 409 |
| `ERR_DELIVERY_RADIUS_EXCEEDED` | 422 |
| `ERR_AGE_VERIFICATION_REQUIRED` | 422 |
| `ERR_SELF_SEAL_FORBIDDEN` | 403 |
| `ERR_BATCH_FULL` | 409 |
| `ERR_BATCH_EMPTY` | 409 |
| `ERR_PRODUCT_UNSELLABLE` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 422 |
| `ERR_PRODUCT_IN_USE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_NO_DRIVER_AVAILABLE` | 409 |
| `ERR_BAG_NOT_ASSIGNED` | 409 |
| `ERR_HANDOFF_NOT_VERIFIED` | 409 |
| `ERR_HANDOFF_NOT_REQUIRED` | 409 |
| `ERR_REFUSAL_REQUIRED` | 409 |
| `ERR_SHRINK_EXCEEDS_LOT` | 422 |
