# Subscribe & Save API — Product Requirements Document

## 1. Introduction

Recurring-delivery programs live or die on two numbers: the discount a subscriber believes they are getting, and the freight cost of the boxes that carry it. This document specifies the Subscribe & Save API, a pricing-engine-centric service that lets customers place individual products on a repeating cadence, then consolidates everything due in a calendar month into a single planned delivery on the customer's chosen day. The more qualifying items a consolidated delivery carries, the deeper the per-line discount — but only at the moment the delivery is locked, when prices, availability, substitutions, price caps, coupons, and promotional bonus items are all resolved against the state of the catalog at that instant.

The platform deliberately prices at ship time rather than at subscribe time. A subscription merely records intent — product, cadence, quantity, an optional price ceiling — while the actual charge is computed when the customer locks the month's plan. Between generation and lock, the plan carries an estimated total that may drift as prices move, stock shifts, or lines are skipped; a refresh capability lets the customer re-observe that estimate, guarded by optimistic concurrency so a client never overwrites a snapshot it has not seen. Damaged deliveries flow through a claim, refund, and reshipment lifecycle, cancellations are intercepted by a fixed goodwill-credit retention offer with lazy expiry, and active subscriptions feed a demand forecast that guides inventory placement buys.

Everything in the system runs against a logical clock rather than wall-clock time, so the platform operator can drive monthly consolidation runs, offer expirations, and forecast windows deterministically. The API is mounted under `/sns`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly three roles: `Customer`, `SupportAgent`, and `PlatformAdmin`. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the customer's `X-User-ID` is not required to reference an existing `Customer` record. A request whose role is authenticated but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is resolved as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any customer-scoped resource (subscription, delivery plan, plan line, damage claim, retention offer, notification) compare the resource's owning-customer chain to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). Likewise, the `customer_id` supplied in a subscription-creation body must equal the caller's `X-User-ID`, with the same rejection code on mismatch. When `X-User-Role` is `SupportAgent` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. The batch operations `POST /sns/ops/generate-plans` and `POST /sns/ops/recompute-forecasts` instead return an array of the created or updated plans/forecasts in `data`.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped into that range rather than rejected. The `offset` parameter skips a number of leading items and defaults to 0, with negative values clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All temporal reasoning in the system — delivery dates, retention-offer expiry, coupon and promotion windows, price-event resolution, forecast months, subscription start-date lead time — runs against a **logical clock**, never the host's wall clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it through a test-driving capability that accepts a target instant `to_iso8601` and reports the resulting `current_utc`. Before any such call, the logical clock remains pinned to the startup default and never falls back to wall-clock time. Advancing the logical clock triggers lazy retention-offer expiry evaluation on subsequent reads, as described in §3.4.

### 2.5. Validation Ordering

When a request violates several rules at once, the rejection it receives is determined by a fixed evaluation order. The server checks, in this sequence: (1) request well-formedness — the JSON body must be an object, all required fields present, no unknown fields, field types correct — rejected as `ERR_INVALID_REQUEST`; (2) authentication headers — `ERR_UNAUTHENTICATED`; (3) role authorization for the endpoint — `ERR_FORBIDDEN`; (4) customer ownership of the addressed resource chain — `ERR_OWNERSHIP_MISMATCH`; (5) existence of path- and body-referenced resources, validated left-to-right so an outer identifier is checked before an inner one, each with its own not-found error; (6) state preconditions, including the optimistic-concurrency version match on refresh — the state errors and `ERR_STALE_PLAN_VERSION`; (7) scalar domain ranges — cadence, delivery day, quantity, price cap, claim line shape; (8) catalog usability — subscribability and the presence of a current price; (9) temporal rules — start-date lead time, coupon windows, price-event monotonicity, promotion window overlap, offer expiry; and finally (10) money and stock gates — coupon minimum subtotal, stacking limits, and reshipment stock sufficiency. A later check is only reached when every earlier check passes.

### 2.6. Nested Resource Retrieval

Endpoints whose paths address nested resources validate identifiers sequentially from left to right. A request naming a plan and a line within it is first checked for the plan's existence — a missing plan yields `ERR_PLAN_NOT_FOUND` — and only then for the line, where a missing line, or a line that does not belong to the plan in the path, yields `ERR_LINE_NOT_FOUND`. The same ordering applies wherever one resource is addressed beneath another: the outermost missing identifier determines the error, and inner validations never run against a nonexistent parent.

### 2.7. Common Resource Properties

Primary resources — Customer, Product, InventoryPlacement, Subscription, DeliveryPlan, PlanLine, Coupon (tracked by its `coupon_status`), Promotion (tracked by its `promotion_status`), RetentionOffer (tracked by its `offer_status`), DamageClaim (tracked by its `claim_status`), Reshipment (tracked by its `reshipment_status`), and DemandForecast — carry a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 at creation and increments by exactly 1 on every mutation, powering optimistic concurrency control.

Two resources are exceptions. A PriceEvent carries only `id` and `created_at` — it is an immutable append-only record, so both `updated_at` and `version` are absent. A Notification likewise carries only `id` and `created_at`; it is written once and never mutated. Any recomputation of derived fields on a resource — a plan's totals, a product's availability, a placement's counters — is itself a mutation that refreshes `updated_at` and increments `version` on that resource. Every resource mutation — including no-op-effective pipeline re-evaluations that rewrite a line's current values — refreshes `updated_at` and increments `version`, even when no field value visibly changes.

### 2.8. Money, Precision, and Rounding

All monetary values are integer counts of cents. Discount percentages are exact fractions (`0.05`, `0.10`). Wherever a charge is computed from a percentage — per-line tier discounting, per-step coupon discounting, and the price-increase notice baseline — the result is rounded to whole cents using round-half-up. The rounding order for plan charges is pinned: each line is rounded to whole cents first, and only then are the rounded line values summed. Computing the discount over an unrounded sum and rounding once at the end is forbidden.

### 2.9. Price History as an Append-Only Log

A product's price is not a mutable attribute but a chronological series of PriceEvent records, each carrying a `price_cents` value and an `effective_from` instant. The price of a product at any instant is the `price_cents` of the PriceEvent whose `effective_from` is the latest one at or before that instant; if no such event exists, the price is undefined and the product is treated as having no current price. The product's `current_price_cents` field always reflects this resolution against the logical clock and is null while no effective event exists. Price events for a product must be strictly increasing in `effective_from`: appending an event whose `effective_from` is not strictly greater than every existing event for that product is rejected with `ERR_PRICE_EVENT_NOT_MONOTONIC` (HTTP 409).

### 2.10. Inventory Conservation and Derived Availability

Every InventoryPlacement ledger-conserves its units. At all times, `received_total_units` equals the sum of `on_hand_units`, `reserved_units`, and `shipped_units`. Receiving stock adds to `received_total_units` and `on_hand_units`; locking a plan moves quantity from `on_hand_units` into `reserved_units`; shipping a plan moves it from `reserved_units` into `shipped_units`; dispatching a reshipment moves it directly from `on_hand_units` into `shipped_units`. No operation may drive `on_hand_units` or `reserved_units` below zero.

A product's `availability_status` is derived, never set directly: it is `DISCONTINUED` whenever the product's `discontinued` flag is true; otherwise `IN_STOCK` when the sum of `on_hand_units` across the product's placements in the product's own region is greater than zero; otherwise `OUT_OF_STOCK`. Any mutation that takes a placement's `on_hand_units` to zero therefore flips the product to `OUT_OF_STOCK` immediately, including a lock-time reservation that consumes the last unit.

### 2.11. Optimistic Concurrency Control on Plan Refresh

Exactly one write operation in the API is version-guarded: refreshing an `OPEN` delivery plan. A refresh request must carry `expected_plan_version`, holding the value of the plan's `version` the client last observed. If the plan's current `version` differs from `expected_plan_version` — because some other write has advanced it since the client's last read — the refresh is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), forcing the client to re-read the plan before re-estimating it. A successful refresh itself increments the plan's `version` by exactly 1. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Catalog, Pricing, and Stock

Before anything can be subscribed to, a `PlatformAdmin` builds the catalog. A product is created with a `sku` (unique across the catalog — a duplicate is rejected with `ERR_INVALID_REQUEST`), a display `name`, the fulfillment `region` it is stocked in, and three optional flags: `subscription_eligible` (defaulting to true), `discontinued` (defaulting to false), and `substitute_product_id`, which names the product to be offered in its place when the original is unavailable at lock time and defaults to null. The administrator may later revise those three fields by patching the product; any such change re-derives `availability_status`. Both at creation and at patch time, a designated substitute must reference an existing product — a dangling `substitute_product_id` is rejected with `ERR_PRODUCT_NOT_FOUND`; the reference is not otherwise constrained (a patch may even point a product at itself).

Prices enter the catalog exclusively as price events. Appending a price event to a product requires a positive `price_cents` — zero or negative is rejected with `ERR_INVALID_REQUEST` — and an `effective_from` strictly later than every existing event for that product, per §2.9, and recomputes the product's `current_price_cents`. Products can be listed with optional `region` and `substitute_product_id` filters, and their price history can be listed per product.

Stock is managed per product per region through inventory placements. Creating a placement binds a `product_id` to a `region`, unique as a pair — a second placement for the same product and region is rejected as `ERR_INVALID_REQUEST` — with all four counters (`received_total_units`, `on_hand_units`, `reserved_units`, `shipped_units`) starting at zero. The named product must exist (`ERR_PRODUCT_NOT_FOUND`), and a missing placement id is likewise reported as `ERR_PRODUCT_NOT_FOUND`. Receiving stock takes a positive `units` quantity — a value of zero or less is rejected with `ERR_QUANTITY_OUT_OF_RANGE` — and adds it to both `received_total_units` and `on_hand_units`, after which availability is re-derived per §2.10. Placements may be listed filtered by `product_id` or `region`, and the subscriptions riding on a given product may be listed by operations staff.

### 3.2. Customer Accounts

A `PlatformAdmin` provisions a customer account with an `email` (unique across customers — a duplicate is rejected with `ERR_INVALID_REQUEST`), a `full_name`, a fulfillment `region` code, and an optional `preferred_delivery_day` — the day of month on which consolidated deliveries are scheduled, between 1 and 28 inclusive, defaulting to 15 when omitted. New accounts start `ACTIVE` with a `credit_balance_cents` of zero; the balance records promotional goodwill credits and never goes negative. An out-of-range `preferred_delivery_day`, whether at creation or on a later patch, is rejected with `ERR_INVALID_DELIVERY_DAY`; both the administrator and the customer themselves may patch that field on their own record.

Suspension is an administrative lever. Suspending an `ACTIVE` customer moves `account_status` to `SUSPENDED` and excludes the customer from all future plan-generation runs; unsuspending returns them to `ACTIVE`. Suspending a customer not currently `ACTIVE`, or unsuspending one not currently `SUSPENDED`, is rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 409). While an account is `SUSPENDED`, two customer-initiated operations are blocked with `ERR_CUSTOMER_SUSPENDED` (HTTP 409): creating a new subscription, and resuming a paused one.

### 3.3. Subscribing: Cadence, Quantity, and the Price Ceiling

A `Customer` subscribes by supplying a payload containing their own `customer_id`, the `product_id`, a `cadence_months` between 1 and 6 inclusive, a `quantity` between 1 and 30 units per delivery, a `start_date` for the first delivery, and an optional `price_cap_cents`. The product must be usable for subscription: a discontinued product or one with `subscription_eligible` set false is rejected with `ERR_PRODUCT_NOT_SUBSCRIBABLE`, and a product with no effective price at the logical present is rejected with `ERR_PRODUCT_WITHOUT_PRICE`. The `start_date` must be at least two days after the logical today — anything earlier is rejected with `ERR_START_DATE_TOO_SOON`. An out-of-range cadence is rejected with `ERR_INVALID_CADENCE`, an out-of-range quantity with `ERR_QUANTITY_OUT_OF_RANGE`. A `price_cap_cents`, when supplied, must be a positive integer — a non-positive cap is rejected with `ERR_INVALID_REQUEST` — and it expresses the maximum acceptable pre-tier unit price at ship time; a null cap means uncapped.

On creation the subscription is `ACTIVE`, its `next_delivery_date` equals its `start_date`, and the system captures the product's `current_price_cents` into `subscribe_price_cents` — the baseline against which price-increase notices are later judged.

While a subscription is `ACTIVE`, the customer may patch its `cadence_months`, `quantity`, or `price_cap_cents`; the same range validations apply. A cadence change recomputes `next_delivery_date` so the subscriber neither gains nor loses a cycle: the schedule is first anchored back by the old cadence from the current `next_delivery_date`, then advanced by the new cadence from that anchor, and then advanced by the new cadence repeatedly until the result is at least two days after the logical today. Month-end clamping applies to every step.

Month arithmetic everywhere in the subscription lifecycle uses clamped month addition: the target year and month are computed from the source date plus the cadence, and the day-of-month is the lesser of the source day and the number of days in the target month — so a January 31 anchor advanced by one month lands on the last day of February, not March 3. This same clamping governs plan-generation advancement, resume fix-up, and cadence changes alike.

### 3.4. Pause, Resume, Cancel, and the Retention Offer

A subscriber may pause an `ACTIVE` subscription, moving its `status` to `PAUSED`; a paused subscription is excluded from future plan-generation runs and from the committed side of demand forecasts. Resuming requires the subscription to be `PAUSED` and the customer's account to be `ACTIVE` (a suspended account surfaces `ERR_CUSTOMER_SUSPENDED`); on resume the `next_delivery_date` is advanced by `cadence_months` — month-end clamped — repeatedly until it is at least two days after the logical today (a date already that far out is left unchanged). Pausing or resuming a subscription in any other status is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`.

Cancellation is deliberately a two-step negotiation rather than a switch. Cancelling from either `ACTIVE` or `PAUSED` — cancelling from any other status is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE` — moves the subscription to `PENDING_CANCEL` and creates a RetentionOffer in `OFFERED` status: a fixed goodwill credit of exactly 500 cents, recorded as `offer_type` `CREDIT` with `credit_amount_cents` 500, expiring seven days after the cancellation request date (`expires_on` is the request date plus 7 days). The customer is informed via an `OFFER_CREATED` notification.

While the offer is `OFFERED`, the customer may accept or decline it; acting on an offer in any other status is rejected with `ERR_OFFER_NOT_OPEN`. Accepting — which additionally requires the logical today to be on or before `expires_on` — moves the offer to `ACCEPTED`, returns the subscription to `ACTIVE`, and adds 500 cents to the customer's `credit_balance_cents`. Declining moves the offer to `DECLINED` and the subscription to `CANCELLED`, which is terminal. Both actions return the updated RetentionOffer object.

If the customer simply lets the offer lapse, expiry is applied lazily: whenever the system reads or mutates the subscription, or reads its offers or the customer's notifications, and finds an `OFFERED` offer whose `expires_on` is strictly before the logical today, the offer flips to `EXPIRED`, the subscription flips to `CANCELLED` (if it is still `PENDING_CANCEL`), and an `OFFER_EXPIRED` notification is created for the customer. When the customer reads the notification feed, this lazy evaluation is applied across all of the customer's subscriptions. A subscription's offers can be listed by the customer, support, or the administrator.

### 3.5. Monthly Consolidation: Generating Delivery Plans

Once a month, a `PlatformAdmin` runs plan generation for a target `delivery_month` (a `YYYY-MM` string — any other shape is rejected with `ERR_INVALID_REQUEST`). For each customer whose `account_status` is `ACTIVE` and who does not already have a plan for that month, the system collects the customer's `ACTIVE` subscriptions whose `next_delivery_date` falls within the calendar month, both endpoints of the window inclusive. A customer with no eligible subscriptions gets no plan. Otherwise a DeliveryPlan is created in `OPEN` status with its `delivery_date` set to the customer's `preferred_delivery_day` within the target month, and one PlanLine in `SCHEDULED` status per eligible subscription — `quantity` copied from the subscription, `product_id` copied from the subscription, `subscription_id` pointing back at it, and `plan_id` anchoring the line to its plan, `is_bonus` false, `was_substituted` false, `skip_reason` null, and `unit_price_cents` and `line_charged_cents` both null until lock. Every subscription consolidated into the plan immediately has its `next_delivery_date` advanced by its cadence per the clamped arithmetic of §3.3. The operation returns the array of plans it created.

At generation the plan's `estimated_total_cents` is computed from then-current prices through the same tier and rounding pipeline used at lock (the estimated variant of §3.6), and `tier_discount_pct` and `active_line_count` are set accordingly. The `charged_total_cents` remains null until lock; `gross_line_total_cents` and `refunded_total_cents` start at zero; `applied_coupon_codes` starts empty. Because the estimate uses prices effective at the generation instant while lock resolves prices effective at the lock instant, a price change landing between the two makes `estimated_total_cents` and `charged_total_cents` legitimately diverge for identical lines.

### 3.6. The Lock Pipeline: Price-at-Ship, Substitution, Caps, and the Tier

Locking is the pivotal act of the program: the customer locks an `OPEN` plan — any other `plan_status` is rejected with `ERR_PLAN_NOT_OPEN` — and the system runs a single evaluation pipeline whose step order is pinned. Later steps observe earlier steps' outputs, never the reverse, which resolves the apparent circularity between availability, prices, caps, and the tier.

**Step 1 — availability and substitution.** For each `SCHEDULED` non-bonus line, the product's placement in the plan customer's region is checked (a product with no placement there counts as zero on hand): if `on_hand_units` covers the line's `quantity`, the line proceeds untouched. If it does not, the product's designated substitute is considered: when a `substitute_product_id` is set, the substitute exists, is `IN_STOCK` in the region with enough on hand, has a current price, and that price passes the step-3 cap check, the line's `product_id` is rewritten to the substitute and `was_substituted` becomes true. Otherwise the line is moved to `AUTO_SKIPPED` with `skip_reason` `UNAVAILABLE` — silently, with no notification.

**Step 2 — price-at-ship.** Each surviving line's `unit_price_cents` is resolved against the (possibly substituted) product's price history per §2.9, evaluated at the lock instant — the final variant of price resolution. The lock instant is the logical clock's reading at the moment the lock request is processed, so the resolved price is always the latest PriceEvent effective at or before that reading, regardless of the subscription's original subscribe price or of any earlier estimate. If the product has no price effective at the lock instant, `unit_price_cents` is left unchanged (null for a fresh line), the cap check below does not fire, and the line contributes zero to the plan totals.

**Step 3 — the price-cap check.** If the line's subscription carries a non-null `price_cap_cents` and the resolved `unit_price_cents` is strictly greater than the cap, the line moves to `AUTO_SKIPPED` with `skip_reason` `PRICE_CAP`, and the customer receives a `PRICE_CAP_SKIP` notification. The cap compares the pre-tier unit price, and a price exactly equal to the cap passes.

**Step 4 — the shipment-count tier.** The plan's `tier_discount_pct` is selected from the surviving lines: count the PlanLines with `line_status` `SCHEDULED`, `is_bonus` false, and `quantity` at least 1. With at least 5 such lines the tier is `0.10`; with at least 3 it is `0.05`; below that it is `0.00`. Boundaries are inclusive — exactly 3 lines earns `0.05` and exactly 5 earns `0.10`.

**Step 5 — per-line charges.** For each `SCHEDULED` non-bonus line, `line_charged_cents` is the line's `unit_price_cents` multiplied by its `quantity`, discounted by the tier fraction, rounded half-up to whole cents — with the rounding applied per line before summing, per §2.8. The plan's `gross_line_total_cents` is the sum of `line_charged_cents` over all `SCHEDULED` lines, bonus lines included (they contribute zero), and serves as the invariant anchor for §3.9.

**Step 6 — coupons.** Attached coupons are applied to `gross_line_total_cents` in attach order, as detailed in §3.7, producing `charged_total_cents`.

**Step 7 — promotional bonus lines.** Only after the tier is fixed do promotions attach bonus lines, per §3.8; bonus lines never feed back into step 4.

Locking also reserves inventory: for every remaining `SCHEDULED` non-bonus line, the placement's `on_hand_units` decreases and its `reserved_units` increases by the line's `quantity`, and any decrement that empties a placement flips the product's availability per §2.10. Bonus lines consume no inventory. Finally, for every charged non-bonus line whose locked `unit_price_cents` is strictly greater than the round-half-up of the subscription's `subscribe_price_cents` multiplied by 1.10, the customer receives a `PRICE_INCREASE` notification; a locked price sitting exactly at 110 percent of the subscribe price does not notify. The plan emerges `LOCKED` with `charged_total_cents`, `gross_line_total_cents`, `tier_discount_pct`, and `active_line_count` all set, and the updated plan is returned.

While the plan is still `OPEN`, the customer may instead refresh it. Refresh re-runs steps 1 through 3 of the pipeline in estimated mode — re-evaluating availability, substitution, and caps against current prices, with the same substitution, auto-skip, and `PRICE_CAP_SKIP` notification effects as at lock — recomputes the tier and `estimated_total_cents`, and increments the plan's `version` by exactly 1. Refresh is the one optimistic-concurrency-guarded operation described in §2.11: it requires `expected_plan_version`, and a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). The refresh response carries the updated plan object; the state check (`ERR_PLAN_NOT_OPEN`) precedes the version check.

### 3.7. Coupons: Attachment Rules and Stacking Order

A `PlatformAdmin` creates coupons with a unique `code`, a `discount_type` of `PERCENT` or `FLAT`, a validity window `valid_from`/`valid_to`, and the matching value field — `percent_off`, a fraction greater than 0 and at most 1, is required for `PERCENT` coupons, while `flat_off_cents`, a positive integer, is required for `FLAT` coupons; the value fields are mutually exclusive with the type — a `PERCENT` coupon must carry `percent_off` and no `flat_off_cents`, and a `FLAT` coupon must carry `flat_off_cents` and no `percent_off` — and supplying the wrong combination (the other type's value field set, or the matching one missing), an unknown `discount_type`, a duplicate `code`, or a negative `min_subtotal_cents` is malformed and rejected as `ERR_INVALID_REQUEST`. A coupon may also declare `stackable` (defaulting to false) and a `min_subtotal_cents` (defaulting to 0, meaning no floor). Coupons start `ACTIVE`; an administrator may disable one — disabling a coupon that is not `ACTIVE` is rejected with `ERR_INVALID_REQUEST` — after which it can no longer be attached to any plan.

A `Customer` attaches a coupon to one of their `OPEN` plans by supplying the `coupon_code` — an unrecognized code is `ERR_COUPON_NOT_FOUND`, and a `DISABLED` coupon surfaces the same `ERR_COUPON_NOT_FOUND`. Attach-time checks are evaluated against the plan's delivery date and its current estimated subtotal: a plan whose `delivery_date` falls before the coupon's `valid_from` is rejected with `ERR_COUPON_NOT_YET_VALID`; one whose `delivery_date` falls after the coupon's `valid_to` — the upper bound is inclusive — is rejected with `ERR_COUPON_EXPIRED`; a plan whose estimated subtotal is below the coupon's `min_subtotal_cents` — the floor is inclusive — is rejected with `ERR_SUBTOTAL_BELOW_COUPON_MIN`. Stacking is limited: a plan carries at most 2 coupons, so attaching a third is rejected with `ERR_COUPON_STACK_LIMIT`; and a non-stackable coupon may never be combined with any other coupon in either direction, so attaching a non-stackable coupon to a plan that already holds one, or attaching any coupon to a plan already holding a non-stackable one, is rejected with `ERR_COUPON_NOT_STACKABLE`. A successful attach appends the code to the plan's `applied_coupon_codes` and recomputes the estimated totals.

When charges are computed — at lock in the charged variant, at generation and refresh in the estimated variant — coupons apply to the gross line total in the order they were attached. A `PERCENT` step multiplies the running total by one minus `percent_off` and rounds the result half-up to whole cents before the next step; a `FLAT` step subtracts `flat_off_cents` but never takes the total below zero. The end result is the plan's `charged_total_cents` at lock or `estimated_total_cents` beforehand.

### 3.8. Promotions: Bonus Lines After the Tier Is Fixed

A `PlatformAdmin` creates a promotion naming a `bonus_product_id`, a `min_line_count` of at least 1, and a half-open window `starts_on` to `ends_on` with `starts_on` strictly before `ends_on`; a `min_line_count` below 1 or a misordered window is rejected with `ERR_INVALID_REQUEST`. Two `ACTIVE` promotions for the same bonus product may not have overlapping half-open windows; a conflicting creation is rejected with `ERR_PROMOTION_WINDOW_OVERLAP` (HTTP 409). The named bonus product must exist. Promotions start `ACTIVE`; disabling one — a `PlatformAdmin` action — makes it stop qualifying plans at lock, and disabling a promotion that is not `ACTIVE` is rejected with `ERR_INVALID_REQUEST`.

At lock, after tier and charges are fixed, every `ACTIVE` promotion whose window contains the plan's `delivery_date` — the lower bound inclusive, the upper bound exclusive — is tested against the plan's final `active_line_count`: when the count is at least the promotion's `min_line_count` (the threshold inclusive), one bonus line is appended to the plan carrying the promotion's `bonus_product_id`, `is_bonus` true, `quantity` 1, `unit_price_cents` 0, `line_charged_cents` 0, `subscription_id` null, and `line_status` `SCHEDULED`. Bonus lines are excluded from the tier count and receive no discount, so they never change the outcome they qualified under. When several promotions qualify, each appends exactly one bonus line, processed in promotion creation order, earliest first. Bonus lines also cannot be customer-skipped — an attempt is rejected with `ERR_LINE_NOT_SKIPPABLE`.

### 3.9. Shipping, Delivery, and the Money Invariant

Shipping is an operational act: a `PlatformAdmin` ships a `LOCKED` plan — anything else is `ERR_PLAN_NOT_LOCKED` — which moves every `SCHEDULED` PlanLine to `SHIPPED`, releases each shipped non-bonus line's reservation (the placement's `reserved_units` decreases and `shipped_units` increases by the line's quantity), and sends the customer a `PLAN_SHIPPED` notification. Bonus lines ship without touching any placement counters. Marking the shipment delivered — again a `PlatformAdmin` act requiring `SHIPPED` status, with any other plan status rejected as `ERR_PLAN_NOT_LOCKED` — moves the plan to `DELIVERED`.

From that point the plan's books must balance. For every plan that has been locked, `gross_line_total_cents` always equals the sum of `line_charged_cents` over lines in `SHIPPED` or `RESHIPPED` status, plus `refunded_total_cents`, plus the sum of `line_charged_cents` over lines still `SCHEDULED`. Refunds and reshipments redistribute value across these buckets; they never create or destroy it.

Closure has two forms. A `SupportAgent` may resolve a `DELIVERED` plan — resolving a plan in any other status is rejected with `ERR_PLAN_NOT_DELIVERED` — but only when no damage claim for that plan sits in `REPORTED` or `APPROVED_RESHIP` status; resolving a plan with an open claim is rejected with the same `ERR_PLAN_NOT_DELIVERED`, since the claim pipeline must finish first. Resolution moves the plan to `RESOLVED`, which is terminal. Alternatively, while a plan is still `OPEN` — any other plan status is rejected with `ERR_PLAN_NOT_OPEN` — a `SupportAgent` may cancel it outright: every `SCHEDULED` line moves to `SKIPPED` with `skip_reason` `CUSTOMER` (other lines are left as they are), and the plan becomes `CANCELLED`, also terminal. Cancelling a plan touches nothing upstream — the subscriptions survive untouched and will simply be consolidated again on the next generation run.

### 3.10. Line-Level Skip and Unskip

While a plan is `OPEN`, the customer may curate it line by line. Skipping a `SCHEDULED` non-bonus line moves it to `SKIPPED` with `skip_reason` `CUSTOMER`; skipping a line that is not `SCHEDULED` — or any bonus line — is rejected with `ERR_LINE_NOT_SKIPPABLE`, and operating on a plan that is not `OPEN` is `ERR_PLAN_NOT_OPEN`. A customer-skip can be walked back: unskipping requires the line to be `SKIPPED` with `skip_reason` `CUSTOMER` and its subscription to be `ACTIVE` — a line whose subscription has since moved on is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE` — and returns the line to `SCHEDULED` with `skip_reason` cleared. Lines auto-skipped by the system for `PRICE_CAP` or `UNAVAILABLE` cannot be manually unskipped.

Both actions ripple through the plan's arithmetic. Any change to the set of `SCHEDULED` lines recomputes `active_line_count`; the count change itself re-triggers tier selection; and the tier change re-triggers estimated per-line repricing and a fresh `estimated_total_cents`.

Auto-skipped lines get a symmetric second chance at refresh time. While the plan remains `OPEN`, a refresh that finds an `AUTO_SKIPPED` line's conditions healed — the product having a current price at or under the subscription's cap (or the cap null) and the product `IN_STOCK` in region with sufficient on hand — restores the line to `SCHEDULED`, clears `skip_reason`, and triggers the same count-tier-total recomputation chain. A line whose product has no current price at refresh stays `AUTO_SKIPPED`.

### 3.11. Damage Claims, Refunds, and Reshipments

When a consolidated delivery arrives damaged, the customer reports it on a `DELIVERED` plan — a claim against a plan in any other status is rejected with `ERR_PLAN_NOT_DELIVERED` — by naming the `damaged_line_ids`, a non-empty array of lines belonging to that plan, every one of them in `SHIPPED` status. An empty array, an id that is not on the plan, or a line not in `SHIPPED` status is rejected with `ERR_CLAIM_LINES_INVALID`. A valid report creates a DamageClaim in `REPORTED` status, with its `customer_id` copied from the plan and `claim_refund_cents` null pending review.

Review belongs to a `SupportAgent` and takes a `decision` of `APPROVE_REFUND`, `APPROVE_RESHIP`, or `REJECT`; any other decision value is rejected with `ERR_INVALID_REQUEST`, and reviewing a claim no longer in `REPORTED` status is rejected with `ERR_CLAIM_NOT_REVIEWABLE`. A refund approval completes the claim immediately: `claim_refund_cents` is set to the sum of the damaged lines' `line_charged_cents`, every damaged line moves to `REFUNDED`, the plan's `refunded_total_cents` increases by the same amount, and the claim moves to `COMPLETED`. Coupon savings are forfeited on refund — the refund is the full `line_charged_cents`, never a coupon-prorated figure — which is exactly what keeps the §3.9 money invariant anchored on the gross line total.

A reship approval is gated on stock: for every damaged line, the line's product must have a placement in the plan customer's region with `on_hand_units` at least the line's `quantity`, or the review is rejected with `ERR_INSUFFICIENT_INVENTORY`. Approval moves the claim to `APPROVED_RESHIP`, creates a Reshipment in `PENDING` status whose `claim_id` points back at the claim and whose `reshipped_line_ids` are copied from the claim's `damaged_line_ids`, and moves every damaged line to `RESHIPPED`.

The reshipment then travels under `PlatformAdmin` control. Dispatching requires `PENDING` status — any other reshipment status is rejected with `ERR_INVALID_REQUEST` — and re-verifies stock: every reshipped line's placement must still hold at least the line's quantity on hand, or the dispatch is rejected with `ERR_INSUFFICIENT_INVENTORY`; dispatch then moves each line's quantity from `on_hand_units` into `shipped_units`, flips any emptied product's availability per §2.10, sends the customer a `RESHIP_DISPATCHED` notification, and moves the reshipment to `DISPATCHED`. Marking it delivered requires `DISPATCHED` status — any other status is rejected with `ERR_INVALID_REQUEST` — moves the reshipment to `DELIVERED`, and completes the claim by moving it to `COMPLETED`. A rejection simply moves the claim to `REJECTED`, terminal, with no further effects. Claims can be listed per customer or per plan, and each claim's reshipments can be listed.

### 3.12. Demand Forecasting

Subscriptions are not just commitments to customers; they are a demand signal to the supply chain. A `PlatformAdmin` may recompute forecasts for a given `region` and `forecast_month` (a `YYYY-MM` string — any other shape is rejected with `ERR_INVALID_REQUEST`). For each product stocked in that region, the system considers subscriptions whose `next_delivery_date` falls within the forecast month, both ends inclusive, and produces two unit counts. `committed_units` is the sum of `quantity` over `ACTIVE` subscriptions in scope — the figure used for inventory placement buys. `provisional_units` is the planning view: the committed figure plus half of the summed quantity over `PAUSED` subscriptions in scope, with that half-weight contribution floored to a whole unit. Subscriptions in `PENDING_CANCEL` or `CANCELLED` status are excluded from both figures. The run creates or updates the DemandForecast row keyed on the product, region, and month — re-running for the same triple updates in place rather than duplicating — and returns the array of forecast rows it wrote. Forecasts may be listed filtered by `product_id`, `region`, or `forecast_month`, or read individually (`ERR_FORECAST_NOT_FOUND` for an unknown id).

### 3.13. Notifications

The system keeps a per-customer notification feed. Six notification types exist: `OFFER_CREATED` when a retention offer is minted, `OFFER_EXPIRED` when one lapses, `PRICE_INCREASE` when a locked line price breaches the 110-percent notice threshold, `PRICE_CAP_SKIP` when a line is auto-skipped for breaching its price cap, `PLAN_SHIPPED` when a plan ships, and `RESHIP_DISPATCHED` when a reshipment goes out. Each notification carries its `notification_type`, a human-readable `message`, and, where a plan is involved, a `related_plan_id` (null otherwise). Customers, support agents, and administrators can list a customer's feed, optionally filtered by `notification_type`, and reading the feed participates in the lazy offer-expiry evaluation of §3.4.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, product, price event, inventory placement, subscription, coupon, promotion, damage claim, or a batch of generated plans — return `201 Created`. Operations that read or modify existing resources return `200 OK`. All paths below are served under the `/sns` mount.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sns/customers` | Create a customer account | PlatformAdmin |
| GET | `/sns/customers/{id}` | Read a customer | PlatformAdmin, SupportAgent, Customer |
| PATCH | `/sns/customers/{id}` | Update preferred delivery day | PlatformAdmin, Customer |
| POST | `/sns/customers/{id}/suspend` | Suspend a customer account | PlatformAdmin |
| POST | `/sns/customers/{id}/unsuspend` | Reactivate a suspended customer | PlatformAdmin |
| GET | `/sns/customers/{id}/subscriptions` | List a customer's subscriptions | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/customers/{id}/delivery-plans` | List a customer's delivery plans | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/customers/{id}/notifications` | List a customer's notifications | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/customers/{id}/damage-claims` | List a customer's damage claims | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/products` | Create a catalog product | PlatformAdmin |
| GET | `/sns/products/{id}` | Read a product | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/products` | List and filter products | PlatformAdmin, SupportAgent, Customer |
| PATCH | `/sns/products/{id}` | Update product flags and substitute | PlatformAdmin |
| POST | `/sns/products/{id}/price-events` | Append a price event | PlatformAdmin |
| GET | `/sns/products/{id}/price-events` | List a product's price history | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/products/{id}/subscriptions` | List subscriptions of a product | PlatformAdmin, SupportAgent |
| POST | `/sns/inventory-placements` | Create an inventory placement | PlatformAdmin |
| GET | `/sns/inventory-placements/{id}` | Read a placement | PlatformAdmin, SupportAgent |
| GET | `/sns/inventory-placements` | List and filter placements | PlatformAdmin, SupportAgent |
| POST | `/sns/inventory-placements/{id}/receive` | Receive stock into a placement | PlatformAdmin |
| POST | `/sns/subscriptions` | Create a subscription | Customer |
| GET | `/sns/subscriptions/{id}` | Read a subscription | PlatformAdmin, SupportAgent, Customer |
| PATCH | `/sns/subscriptions/{id}` | Change cadence, quantity, or price cap | Customer |
| POST | `/sns/subscriptions/{id}/pause` | Pause an ACTIVE subscription | Customer |
| POST | `/sns/subscriptions/{id}/resume` | Resume a PAUSED subscription | Customer |
| POST | `/sns/subscriptions/{id}/cancel` | Begin cancellation; creates a retention offer | Customer |
| GET | `/sns/subscriptions/{id}/retention-offers` | List a subscription's retention offers | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/retention-offers/{id}` | Read a retention offer | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/retention-offers/{id}/accept` | Accept the offer; credit granted, subscription stays active | Customer |
| POST | `/sns/retention-offers/{id}/decline` | Decline the offer; subscription cancels | Customer |
| POST | `/sns/coupons` | Create a coupon | PlatformAdmin |
| GET | `/sns/coupons/{id}` | Read a coupon | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/coupons/{id}/disable` | Disable a coupon | PlatformAdmin |
| POST | `/sns/promotions` | Create a promotion | PlatformAdmin |
| GET | `/sns/promotions/{id}` | Read a promotion | PlatformAdmin, SupportAgent |
| GET | `/sns/promotions` | List and filter promotions | PlatformAdmin, SupportAgent |
| POST | `/sns/promotions/{id}/disable` | Disable a promotion | PlatformAdmin |
| POST | `/sns/ops/generate-plans` | Generate consolidated plans for a month | PlatformAdmin |
| POST | `/sns/ops/recompute-forecasts` | Recompute demand forecasts for a region and month | PlatformAdmin |
| GET | `/sns/demand-forecasts` | List and filter forecasts | PlatformAdmin, SupportAgent |
| GET | `/sns/demand-forecasts/{id}` | Read a forecast | PlatformAdmin, SupportAgent |
| GET | `/sns/delivery-plans/{id}` | Read a delivery plan with derived totals | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/delivery-plans/{id}/lines` | List a plan's lines | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/delivery-plans/{id}/refresh` | Re-estimate an OPEN plan (version-guarded) | Customer |
| POST | `/sns/delivery-plans/{id}/lock` | Lock an OPEN plan | Customer |
| POST | `/sns/delivery-plans/{id}/ship` | Ship a LOCKED plan | PlatformAdmin |
| POST | `/sns/delivery-plans/{id}/mark-delivered` | Mark a SHIPPED plan delivered | PlatformAdmin |
| POST | `/sns/delivery-plans/{id}/resolve` | Resolve a DELIVERED plan with no open claims | SupportAgent |
| POST | `/sns/delivery-plans/{id}/cancel` | Cancel an OPEN plan | SupportAgent |
| POST | `/sns/delivery-plans/{id}/lines/{line_id}/skip` | Customer-skip a SCHEDULED line | Customer |
| POST | `/sns/delivery-plans/{id}/lines/{line_id}/unskip` | Restore a CUSTOMER-skipped line | Customer |
| POST | `/sns/delivery-plans/{id}/coupons` | Attach a coupon to an OPEN plan | Customer |
| POST | `/sns/delivery-plans/{id}/damage-claims` | Report damaged lines on a DELIVERED plan | Customer |
| GET | `/sns/delivery-plans/{id}/damage-claims` | List a plan's damage claims | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/plan-lines/{id}` | Read a plan line | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/plan-lines` | List and filter plan lines | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/damage-claims/{id}` | Read a damage claim | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/damage-claims/{id}/review` | Review a REPORTED claim | SupportAgent |
| GET | `/sns/damage-claims/{id}/reshipments` | List a claim's reshipments | PlatformAdmin, SupportAgent, Customer |
| GET | `/sns/reshipments/{id}` | Read a reshipment | PlatformAdmin, SupportAgent, Customer |
| POST | `/sns/reshipments/{id}/dispatch` | Dispatch a PENDING reshipment | PlatformAdmin |
| POST | `/sns/reshipments/{id}/mark-delivered` | Mark a DISPATCHED reshipment delivered | PlatformAdmin |
| POST | `/sns/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_COUPON_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_RESHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FORECAST_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_OPEN` | 409 Conflict |
| `ERR_PLAN_NOT_LOCKED` | 409 Conflict |
| `ERR_PLAN_NOT_DELIVERED` | 409 Conflict |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_OFFER_NOT_OPEN` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_LINE_NOT_SKIPPABLE` | 409 Conflict |
| `ERR_PRICE_EVENT_NOT_MONOTONIC` | 409 Conflict |
| `ERR_PROMOTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_CADENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_DELIVERY_DAY` | 422 Unprocessable Entity |
| `ERR_QUANTITY_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_START_DATE_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_SUBSCRIBABLE` | 422 Unprocessable Entity |
| `ERR_PRODUCT_WITHOUT_PRICE` | 422 Unprocessable Entity |
| `ERR_CLAIM_LINES_INVALID` | 422 Unprocessable Entity |
| `ERR_COUPON_NOT_YET_VALID` | 422 Unprocessable Entity |
| `ERR_COUPON_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SUBTOTAL_BELOW_COUPON_MIN` | 422 Unprocessable Entity |
| `ERR_COUPON_NOT_STACKABLE` | 422 Unprocessable Entity |
| `ERR_COUPON_STACK_LIMIT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
