# Adjustable Bed Sleep Retail API — Product Requirements Document

## 1. Introduction

This document specifies the backend for an adjustable-bed retail operation that couples in-store fit consultations with white-glove home delivery, in-home setup, sleep-data subscription services, an in-home trial program, prorated limited warranties, and promotional financing. A customer journey begins at a store, where an associate runs a fit assessment that produces a recommended firmness setting and a four-component product configuration. From there the sale becomes an order, the order becomes one or more scheduled in-home delivery and setup visits, and a verified visit installs smart hardware that streams nightly sleep telemetry into the customer's account.

The same backend also administers everything that happens after the install: a 100-night trial with return logistics and restocking, prorated warranty claims on air chambers, pumps, and electronics, and three flavors of promotional financing whose schedules, delinquency cycles, and deferred-interest retro accrual are computed against a server-controlled logical clock. All time-dependent behavior — nightly score finalization, trial-window expiry, deferred-interest promo expiry, and financing delinquency — is driven by that logical clock, never by wall-clock time.

The system is mounted under the `/sleep` URL prefix, with a single admin-only capability mounted outside that prefix for driving the logical clock forward in test and demo environments.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two HTTP headers: `X-User-ID` and `X-User-Role`. A request missing `X-User-Role`, presenting a role the platform does not recognize, or — for any role other than `Anonymous` — missing `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly these roles, spelled as shown: `Anonymous`, `PlatformAdmin`, `SalesAssociate`, `Customer`, `DeliveryTechnician`, `ServiceAgent`, `FinanceAgent`, and `DeviceGateway`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `Customer` may act only on resources whose `customer_id` equals `X-User-ID`; a mismatch surfaces as `ERR_FORBIDDEN`. On list endpoints readable by the `Customer` role, the result set is instead filtered to the caller's own resources — for `DeliveryVisit`, `TrialReturn`, `WarrantyClaim`, and `FinancingPlan`, which carry no `customer_id` of their own, ownership is derived through the parent order — and never rejected. All other roles — `Anonymous`, `PlatformAdmin`, `SalesAssociate`, `DeliveryTechnician`, `ServiceAgent`, `FinanceAgent`, and `DeviceGateway` — are opaque operator identifiers not tied to any persisted entity; the server does not compare `X-User-ID` for these roles to any entity's `id`. The `Anonymous` role is the only role permitted to register a new customer account.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION`. Responses to list endpoints sort by `created_at` ascending, breaking ties by insertion (creation) order. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Logical Clock

Every persisted entity carries a server-minted `id` that is a UUID with no type prefix, plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits — both stamped from the logical clock, never wall-clock time — plus an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity. Time-dependent rules in this system are all expressed against a logical clock the server maintains. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. An admin-only capability advances the clock to a supplied `to_iso8601` instant, and advancing the clock is what triggers nightly sleep-score finalization, deferred-interest retro accrual, financing delinquency and default recompute, and the trial-expiry sweep that closes delivered orders.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents. Every calculation that produces a cent amount rounds half-up to an integer cent at the point the specification names; where a formula says per-line rounding precedes summation, that order is load-bearing. The `recommended_firmness` score is an integer in steps of 5, also rounded half-up before clamping. Percentages in this document are exact decimal constants; basis points (`apr_bps`) are ten-thousandths of a percent expressed as an integer.

### 2.6. Optimistic Concurrency Control

Two write endpoints are version-guarded; no other endpoint accepts a version field. A request that replaces an order's `line_items` may carry `expected_order_version`; when the field is present it must equal the order's current `version`, and a mismatch means another writer has already modified the order since the client last read it, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A replace that omits the field is accepted without any concurrency check. Likewise, a request that reschedules a delivery visit may carry `expected_visit_version`; when present it must equal that visit's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Successful writes on either resource increment `version` by 1.

### 2.7. Validation Ordering

When a request violates more than one rule, the platform reports the first failure in this priority order: authentication (missing or unknown role, missing `X-User-ID`) is checked first as `ERR_UNAUTHENTICATED`; role authorization and `Customer` ownership as `ERR_FORBIDDEN`; path-identifier resolution (left to right) and body-referenced identifier existence as the appropriate `ERR_*_NOT_FOUND`; generic state-machine legality (including terminal-state lockdown) as `ERR_INVALID_STATE`; the order-terminal guard as `ERR_ORDER_ALREADY_TERMINAL`; the visit-completed guard as `ERR_VISIT_ALREADY_COMPLETED`; optimistic-concurrency mismatches as `ERR_STALE_VERSION`; business-referential rules such as fit-assessment ownership and device-on-order as their specific 422 codes; business constraints such as capacity, team overlap, promo shape, checklist completeness, duplicate sleep nights, and entitlement gates; business temporal rules such as window-in-past, trial window, and warranty expiry; business fiscal rules such as the principal cap, the down-payment floor, and payment-amount bounds; and finally generic schema/type/enum validation as `ERR_VALIDATION` (HTTP 400). Where both the generic state check and the trial-window check would fail on a return initiation, the state check fires first. Three endpoint-specific carve-outs refine this order: on visit scheduling and rescheduling the window-in-past check precedes the capacity check; on the two version-guarded endpoints a supplied `expected_order_version` or `expected_visit_version` is checked before body-referenced identifiers (line-item SKUs, the new window) are resolved; and on window creation the new window's own timestamps are parsed and the end-after-start rule enforced as `ERR_VALIDATION` before the team-overlap check runs.

### 2.8. Nested Resource Retrieval and Cascading Consistency

Path identifiers resolve left to right: an unknown identifier anywhere in the path short-circuits the request with the corresponding `ERR_*_NOT_FOUND` before any body validation runs. State transitions propagate across entity boundaries as cascades described in §3 — order cancellation releases window slots and triggers waitlist promotion, a verified visit advances its order, and an approved trial return ripples into financing and store-credit balances. Every mutation refreshes `updated_at` and increments `version` on the entity being mutated, including entities reached only via a cascade.

## 3. Business Logic & Workflows

### 3.1. Catalog, Stores, and Customer Registration

A `PlatformAdmin` onboards the physical network by creating stores. Each store carries a `name`, an array of `zone_codes` describing the delivery postal prefixes it serves, and a `default_window_capacity_slots` value that defaults to 4 and seeds the slot budget the store normally grants new delivery windows. The same administrator curates the product catalog: each `ProductModel` has a `sku` identifier (the server does not enforce its uniqueness), a `name`, a `category` drawn from `MATTRESS`, `ADJUSTABLE_BASE`, `AIR_CHAMBER`, `PUMP`, `ELECTRONICS`, and `BEDDING`, a `price_cents`, an optional `replacement_part_price_cents` that defaults to 0 and is used as the proration base when a component fails under warranty, and a `warranty_months` figure describing the limited-warranty length of that model's warranty component category.

A shopper self-registers through the `Anonymous` role by supplying `home_store_id`, `email`, and `full_name`. The new `Customer` starts with `subscription_tier` set to `FREE`, `subscription_status` set to `ACTIVE`, `store_credit_cents` at 0, and a computed `entitlements` array derived from the tier: `FREE` maps to `[SCORE_BASIC]`, `PLUS` maps to `[SCORE_BASIC, SCORE_DETAIL]`, and `PREMIUM` maps to `[SCORE_BASIC, SCORE_DETAIL, TRENDS]`. A `PlatformAdmin` may later adjust a customer's `subscription_tier`; doing so recomputes `entitlements` and bumps the customer's `version` by 1. Reading a customer returns the `store_credit_cents` balance along with the computed entitlements.

### 3.2. Fit Assessment and Recommendation

A `SalesAssociate` begins the in-store consultation by creating a `FitAssessment` for a `customer_id` at a `store_id`, capturing four profile inputs — `sleep_position` (one of `SIDE`, `BACK`, `STOMACH`, `COMBINATION`), `weight_band` (one of `UNDER_130`, `BAND_130_230`, `OVER_230`), `partner_sleeper` (a boolean true when the bed is shared), and `preferred_feel` (one of `PLUSH`, `MEDIUM`, `FIRM`) — and optionally a `supersedes_assessment_id` pointing at an earlier assessment this one replaces. A new assessment starts in `DRAFT` with `completed_at` null.

Completion is the associate's explicit act. When a `DRAFT` assessment is completed, the server requires that all four profile inputs are present, then computes two derived values. The `recommended_firmness` is computed by taking a base value tied to `sleep_position` — 35 for `SIDE`, 55 for `BACK`, 65 for `STOMACH`, 50 for `COMBINATION` — adding a weight adjustment of −10 for `UNDER_130`, 0 for `BAND_130_230`, or +10 for `OVER_230`, adding a feel adjustment of −10 for `PLUSH`, 0 for `MEDIUM`, or +10 for `FIRM`, subtracting 5 when `partner_sleeper` is true, rounding the sum to the nearest multiple of 5 with ties rounding half up (so a raw 52 becomes 50 and a raw 53 becomes 55), and clamping the result to no lower than 5 and no higher than 100. The `recommended_skus` list is computed by selecting, for each of the four required categories `MATTRESS`, `ADJUSTABLE_BASE`, `AIR_CHAMBER`, and `PUMP`, the catalog `ProductModel` with the lowest `price_cents`, breaking ties by earliest `created_at` (never by `id`); the four selected SKUs make up the recommendation. If any of the four required categories has no candidate `ProductModel` at all, completion fails with `ERR_VALIDATION`. Completion also stamps `completed_at` with the logical clock and, when `supersedes_assessment_id` was supplied, transitions the referenced `COMPLETED` predecessor to `SUPERSEDED`. An assessment in `SUPERSEDED` is terminal; no further transitions exist from it.

### 3.3. Order Placement, Pricing, and Modification

An order is created by a `Customer` or a `SalesAssociate` against a specific `fit_assessment_id`. The referenced assessment must belong to the same customer as the order's `customer_id` and must currently be `COMPLETED` — a `DRAFT` or `SUPERSEDED` assessment, or one tied to a different customer, is rejected with `ERR_FIT_ASSESSMENT_MISMATCH`. The caller supplies `line_items` as a non-empty array of `{sku, qty}` elements — anything else fails with `ERR_VALIDATION` — where `qty` must be an integer (no positivity or range constraint is applied) and each `sku` must resolve to a catalog `ProductModel` or the request fails with `ERR_PRODUCT_MODEL_NOT_FOUND`.

Pricing is computed in a pinned order. First, each line is expanded: the server snapshots the `unit_price_cents` from the `ProductModel.price_cents` at the moment of the write, and computes the line total as the quantity multiplied by the snapshot, rounded half-up to an integer cent; the result is stored as `line_total_cents`. Second, `subtotal_cents` is the sum of those line totals. Third, the discount tier is selected on the subtotal before any discount is applied: a subtotal of at least 1000000 cents earns 0.15, a subtotal of at least 500000 but below 1000000 earns 0.10, and anything below 500000 earns no discount; `discount_cents` is the subtotal multiplied by the selected rate, rounded half-up once. Fourth, `delivery_fee_cents` is 0 when the pre-discount subtotal is at least 200000 cents and 9900 otherwise. Fifth, `total_due_cents` is the subtotal minus the discount plus the delivery fee. The order begins life in `PLACED` with `payment_status` `UNPAID`, `total_paid_cents` at 0, and `trial_verified_at` null.

While an order is still `PLACED`, its `line_items` may be replaced. When that write carries `expected_order_version` it must match the order's current `version` and is rejected with `ERR_STALE_VERSION` on a mismatch; a successful replace re-runs the entire pricing pipeline against the new lines and increments `version` by 1. Attempting to confirm, cancel, patch, or attach financing to a `CANCELLED`, `CLOSED`, or `RETURNED` order is rejected with `ERR_ORDER_ALREADY_TERMINAL`.

### 3.4. Confirmation, Financing, and Cancellation

Confirmation is the point of sale. A `SalesAssociate` confirms a `PLACED` order by naming a `payment_method`. With `payment_method` equal to `PAY_IN_FULL`, the order captures `total_paid_cents` equal to `total_due_cents` and `payment_status` moves from `UNPAID` to `PAID`. With `payment_method` equal to `FINANCING`, the request must also carry a `financing_plan_id` — a missing field fails with `ERR_VALIDATION`, an unknown id with `ERR_FINANCING_PLAN_NOT_FOUND`, and a plan that is not in `ACCEPTED` status for this order with `ERR_INVALID_STATE`; on success the order moves to `CONFIRMED`, `payment_status` moves to `FINANCED`, the linked plan transitions from `ACCEPTED` to `ACTIVE`, and the plan's `activated_at` is stamped with the logical clock. Under either payment method the order captures `total_paid_cents` equal to `total_due_cents` at confirmation. `payment_status` is a parallel dimension that evolves independently of `order_status` except where transitions pin it: the lifecycle is `UNPAID` to `PAID` or `FINANCED`, and then to `REFUNDED` on return.

Cancellation cascades. From `PLACED`, a `Customer` or `SalesAssociate` may cancel with no further preconditions. From `CONFIRMED` or `FULFILLING`, cancellation additionally requires that no delivery visit for the order has yet reached `VERIFIED`; a verified visit blocks cancellation. Any of the three paths runs the same three-link cascade. First, every non-terminal `DeliveryVisit` for the order — any visit in `SCHEDULED`, `WAITLISTED`, or `FAILED_SETUP` — transitions to `CANCELLED`. Second, each `SCHEDULED` visit so cancelled releases its `slot_need` back to its `DeliveryWindow`, decrementing the window's `reserved_slots`. Third, each window that freed slots runs waitlist promotion, promoting eligible `WAITLISTED` visits to `SCHEDULED` and re-consuming slots. Cancellation also voids financing: an `ACCEPTED` plan transitions to `VOIDED`, and from `CONFIRMED` or `FULFILLING` an `ACTIVE` plan likewise transitions to `VOIDED` while `payment_status` moves from `PAID` or `FINANCED` to `REFUNDED`.

### 3.5. Delivery Windows, Visit Scheduling, and In-Home Setup

A `PlatformAdmin` creates delivery windows for a store team. Each window has a `store_id`, an opaque `team_id` crew identifier, a `window_start` that is inclusive, a `window_end` that must be strictly later than `window_start` and is exclusive (the interval is half-open), and a `capacity_slots` budget. Two windows belonging to the same `(store_id, team_id)` pair must not overlap; because the interval is half-open, an existing window whose `window_end` equals the new window's `window_start` is adjacency, not overlap, and is allowed. A violating window is rejected with `ERR_WINDOW_TEAM_OVERLAP`. A window tracks `reserved_slots`, initially 0, computed as the sum of `slot_need` over its `SCHEDULED` visits. The list read for windows accepts `store_id`, `team_id`, and `window_date` (a calendar date in `YYYY-MM-DD` form) as filters alongside the standard pagination parameters.

A `SalesAssociate` schedules a visit against an `order_id` and a `delivery_window_id`, optionally flagging `remove_old_mattress` (defaulting to false, and adding 1 slot when true), recording `room_prep_notes`, and optionally setting `allow_waitlist`. The visit's `slot_need` is computed as 2 plus 1 when `remove_old_mattress` is true. The target window's `window_start` must lie strictly after the logical clock or the request fails with `ERR_WINDOW_IN_PAST`. Capacity is then checked: a window accepts the visit when `reserved_slots` plus `slot_need` is no greater than `capacity_slots`, with equality allowed. When capacity suffices the visit lands in `SCHEDULED` and the window's `reserved_slots` increases by `slot_need`; the first `SCHEDULED` visit on an order moves the order from `CONFIRMED` to `FULFILLING`. When capacity is insufficient and `allow_waitlist` is true, the visit lands instead in `WAITLISTED` with `delivery_window_id` retained as the requested window and no slots consumed. When capacity is insufficient and `allow_waitlist` is not set, the request fails with `ERR_WINDOW_CAPACITY_EXCEEDED`.

Rescheduling moves a `SCHEDULED` or `FAILED_SETUP` visit to a new window. The caller supplies `expected_visit_version`, a `new_delivery_window_id`, and optionally `allow_waitlist`. A stale `expected_visit_version` is rejected with `ERR_STALE_VERSION`; a target window whose `window_start` is not after the logical clock is rejected with `ERR_WINDOW_IN_PAST`; attempting to reschedule a `VERIFIED` or `CANCELLED` visit is rejected with `ERR_VISIT_ALREADY_COMPLETED`. On success the visit releases its `slot_need` on the old window (which triggers waitlist promotion there), consumes `slot_need` on the new window and stays `SCHEDULED` — or, if the new window is full and `allow_waitlist` was set, moves to `WAITLISTED` against the new window — and increments its `version` by 1. The `FAILED_SETUP → SCHEDULED` leg and the `SCHEDULED → SCHEDULED` leg share this mechanics; the failed-setup cycle is repeatable. A `FAILED_SETUP` visit continues to hold its `slot_need` reservation on its window until it is rescheduled — the release and waitlist promotion described above apply to the `FAILED_SETUP` leg exactly as to the `SCHEDULED` leg. (When an order cancellation cancels a `FAILED_SETUP` visit, the visit transitions to `CANCELLED`; per §3.4 only `SCHEDULED` visits release slots on cancellation.)

Waitlist promotion runs whenever a window frees slots. Candidates are the `WAITLISTED` visits whose `delivery_window_id` equals that window. A candidate is eligible while its `slot_need` fits in the window's remaining capacity. Candidates are ranked by `created_at` ascending, breaking ties by `slot_need` ascending (never by `id`), and promoted greedily in that order while eligibility holds; each promotion consumes `slot_need` on the window. The invariant across all operations is that for every window, `reserved_slots` equals the sum of `slot_need` over its `SCHEDULED` visits, and the freed-capacity arithmetic is exact.

A `DeliveryTechnician` completes a `SCHEDULED` visit by submitting an `outcome` and a `setup_checklist`. The checklist is an object with `base_assembled`, `chambers_connected`, `remote_configured`, and `connectivity_verified` flags. With `outcome` equal to `VERIFIED`, all four flags must be true — any false flag is rejected with `ERR_SETUP_CHECKLIST_INCOMPLETE` — and every `Device` of `kind` `BASE` registered under the order must have `pairing_status` equal to `PAIRED`, else the request fails with `ERR_DEVICE_NOT_PAIRED`. A verified completion moves the order from `FULFILLING` to `DELIVERED` and stamps `trial_verified_at` with the logical clock, starting the 100-night trial. With `outcome` equal to `FAILED_SETUP` the visit simply moves to `FAILED_SETUP` and can later be rescheduled. Completing a `VERIFIED` or `CANCELLED` visit is rejected with `ERR_VISIT_ALREADY_COMPLETED`.

### 3.6. Device Registration, Pairing, and Sleep Telemetry

Once hardware is installed, a `DeliveryTechnician` registers each `Device` under an `order_id`, supplying a `kind` of `BASE`, `PUMP`, `CHAMBER`, or `SENSOR`, a `serial_number` unique per `kind`, and the `firmware_version` flashed at install. Registration denormalizes `customer_id` from the order. The order must not be in a terminal state. A device begins `UNPAIRED` with `connectivity` `OFFLINE` and `final_nights_count` at 0.

Pairing is cyclic. A `DeliveryTechnician` drives a device to `PAIRED` by submitting `target_status` equal to `PAIRED` and optionally `connectivity_verified`; pairing is refused when the parent order is `CANCELLED` or `RETURNED`, surfacing as `ERR_INVALID_STATE`. When the pair action carried `connectivity_verified` true, the device's `connectivity` becomes `ONLINE`; otherwise it stays `OFFLINE`. Driving a device back to `UNPAIRED` always sets `connectivity` to `OFFLINE`. Re-pairing is allowed.

Nightly telemetry arrives through the `DeviceGateway` role, which posts one record per device per night carrying `night_date` (a calendar date in `YYYY-MM-DD` form), `minutes_asleep`, `restlessness_events`, and `avg_heart_rate`. A second record for the same `(device_id, night_date)` pair is rejected with `ERR_DUPLICATE_NIGHT`. At ingest the record lands in `PROVISIONAL` with `customer_id` denormalized from the device, `final_score` null, and a `provisional_score` computed from partial-night data. Scoring shares three components: a rest component equal to 100 minus 2 per `restlessness_events`, floored at 0; a duration component equal to `minutes_asleep` multiplied by 100 and divided by 480, rounded half-up, capped at 100; and a heart component equal to 100 minus the absolute difference between `avg_heart_rate` and 60, floored at 0. The `provisional_score` weights rest at 0.6 and duration at 0.4, ignoring heart rate, and rounds half-up to an integer. When the logical clock is set to a time at or past noon UTC on the day after `night_date`, the night finalizes: `status` moves from `PROVISIONAL` to `FINAL`, `final_score` is computed with weights 0.5 rest, 0.3 duration, and 0.2 heart, rounded half-up and clamped between 0 and 100 — the same inputs generally yield a different number than the provisional variant — and the device's `final_nights_count` increments by 1.

Reading sleep data back is entitlement-gated. Listing sleep nights accepts `device_id`, `customer_id`, and a `detail` parameter; asking for `detail` equal to `FULL` requires the owning customer's `subscription_tier` to be `PLUS` or `PREMIUM` with `subscription_status` `ACTIVE`, and a `FREE` tier or `CANCELLED` subscription is rejected with `ERR_ENTITLEMENT_REQUIRED`.

### 3.7. The 100-Night Trial and Returns

A `Customer` initiates a trial return against a `DELIVERED` order by supplying a free-text `reason` and a `refund_destination` of `ORIGINAL_PAYMENT` or `STORE_CREDIT`. The server computes `initiated_night_index` as the number of whole 86400-second days between `trial_verified_at` and the logical clock, rounded down. The trial is 100 nights: an index of 99 or less is permitted, while an index of 100 — that is, a clock at or past `trial_verified_at` plus exactly 100 days — is rejected with `ERR_TRIAL_WINDOW_EXPIRED`. The new `TrialReturn` begins in `INITIATED` with `condition`, `depreciation_cents`, `restocking_fee_cents`, and `refund_cents` unset. When no non-terminal return is open, the order closes automatically once the logical clock reaches `trial_verified_at` plus 101 days — a one-day grace past the trial boundary — transitioning `DELIVERED` to `CLOSED`.

Inspection is performed by a `ServiceAgent` submitting an `outcome` and a `condition` of `GOOD` or `DAMAGED`. An `outcome` of `REJECTED` simply terminates the return in `REJECTED`. An `outcome` of `APPROVED` runs the restocking waterfall in a pinned rounding order. Per order line, the depreciation rate depends on the line's `ProductModel.category` and the inspected `condition`: when `GOOD`, a `MATTRESS` line depreciates at 0.15, an `ADJUSTABLE_BASE` line at 0.10, and any other category at 0.05; when `DAMAGED`, those rates become 0.30, 0.20, and 0.10 respectively. Each line's depreciation is the line's `line_total_cents` multiplied by its rate, rounded half-up per line before summing; the sum is `depreciation_cents`. The `restocking_fee_cents` is the greater of 9900 and one tenth of the order's `total_paid_cents` rounded half-up. The `refund_cents` is the greater of 0 and `total_paid_cents` minus `depreciation_cents` minus `restocking_fee_cents`. Approval then cascades: the order moves from `DELIVERED` to `RETURNED` and `payment_status` moves to `REFUNDED`; if the order carries an `ACTIVE` `FinancingPlan`, the plan's `settled_credit_cents` is set to the lesser of `refund_cents` and the plan's `balance_cents`, that amount is subtracted from `balance_cents`, and the plan transitions from `ACTIVE` to `SETTLED_EARLY`; and when `refund_destination` is `STORE_CREDIT`, the customer's `store_credit_cents` increases by `refund_cents` minus `settled_credit_cents`.

### 3.8. Warranty Claims and Prorated Credit

A `Customer` files a `WarrantyClaim` against an `order_id` and a `device_id`, naming the `component_category` — `CHAMBER`, `PUMP`, `ELECTRONICS`, or `STRUCTURAL` — and selecting a `proration_variant` of `TIME_BASED` or `NIGHTS_USED`, along with a free-text `description`. The `device_id` must be registered under the named order or the request is rejected with `ERR_DEVICE_NOT_ON_ORDER`. At filing, the server snapshots `months_in_service` as the whole days since the order's `trial_verified_at` divided by 30, rounded down, and `final_nights_used` as the device's current `final_nights_count`. The claim is only inside its warranty window when `months_in_service` is strictly less than the `warranty_months` for the claimed `component_category` — `STRUCTURAL` allows 120 months, `CHAMBER` 60, `PUMP` 36, and `ELECTRONICS` 24; a `months_in_service` equal to the limit means the warranty has already expired and the filing is rejected with `ERR_WARRANTY_EXPIRED`. A filed claim begins in `FILED` with `credit_cents` and `applied_to` unset.

Review is the `ServiceAgent`'s decision. A `decision` of `DENY` moves the claim from `FILED` — or later from `APPEALED` — to `DENIED`, with an optional `denial_reason` recorded. A `decision` of `APPROVE` requires the parent order to be outside `CANCELLED` and `RETURNED`, else the review fails with `ERR_INVALID_STATE`. On approval the server computes `credit_cents` using the claim's `proration_variant`. The base price is the `replacement_part_price_cents` of the `ProductModel` whose `sku` appears on the order's `line_items` and whose category maps to the claim's `component_category` — `AIR_CHAMBER` maps to `CHAMBER`, `PUMP` maps to `PUMP`, `ELECTRONICS` maps to `ELECTRONICS`, and both `MATTRESS` and `ADJUSTABLE_BASE` map to `STRUCTURAL`; among matching lines the selector picks the one with the highest `replacement_part_price_cents`, breaking ties by lowest `price_cents` and then earliest `created_at` of the `ProductModel`. Under `TIME_BASED`, the remaining fraction is 1 minus `months_in_service` divided by `warranty_months`, floored at 0. Under `NIGHTS_USED`, the expected lifetime is `warranty_months` multiplied by 30 nights, and the remaining fraction is 1 minus `final_nights_used` divided by that expectation, floored at 0, ignoring calendar time entirely. The credit is the base price multiplied by the remaining fraction, rounded half-up. The credit lands in one of two places, recorded on `applied_to`: when the order has an `ACTIVE` `FinancingPlan`, the plan's `balance_cents` is reduced by the credit and `applied_to` is `FINANCING_BALANCE`; otherwise the customer's `store_credit_cents` increases by the credit and `applied_to` is `STORE_CREDIT`. Approval is terminal; a `DENIED` claim can be appealed by the `Customer`, moving to `APPEALED`, and the `DENIED → APPEALED → DENIED` cycle may repeat.

### 3.9. Financing Offers, Schedules, and Collections

A `FinanceAgent` creates a financing offer against a `PLACED` order, supplying `offer_type` — `ZERO_APR`, `DEFERRED_INTEREST`, or `STANDARD` — along with `term_months`, `apr_bps`, and an optional `down_payment_cents` defaulting to 0. The `term_months` must be one of 12, 24, or 36; `ZERO_APR` requires `apr_bps` equal to 0; and `DEFERRED_INTEREST` requires `apr_bps` strictly greater than 0 — any violation is rejected with `ERR_PROMO_TERM_INVALID`. The financed `principal_cents` is the order's `total_due_cents` minus `down_payment_cents` and must not exceed 500000 cents, else the create fails with `ERR_CREDIT_LIMIT_EXCEEDED`. A `DEFERRED_INTEREST` plan additionally enforces a down-payment floor of one tenth of the order's `total_due_cents` rounded half-up; falling short is rejected with `ERR_DOWN_PAYMENT_INSUFFICIENT`.

The monthly payment depends on the offer shape. For `ZERO_APR`, `monthly_payment_cents` is the principal divided by `term_months`, rounded up to a whole cent. For `DEFERRED_INTEREST`, `promo_months` is set to 12 and `monthly_payment_cents` is 0.03 of the principal, rounded up to a whole cent. For `STANDARD`, `promo_months` is 0 and the payment is the standard amortization: the monthly rate is `apr_bps` divided by 10000 and then by 12, and `monthly_payment_cents` is the principal multiplied by that rate and divided by one minus one-plus-that-rate raised to the negative `term_months` power, rounded half-up to a whole cent. The new plan starts `OFFERED` with `paid_cents` at 0, `balance_cents` equal to principal, `retro_interest_posted` false, `settled_credit_cents` at 0, and `activated_at` null.

The `Customer` accepts an `OFFERED` plan, moving it to `ACCEPTED`; acceptance re-checks nothing structural because the shape was enforced at create. From `ACCEPTED`, an order confirmation with `payment_method` equal to `FINANCING` flips the plan to `ACTIVE` and stamps `activated_at`; an order cancellation instead voids the plan. While `ACTIVE`, the `balance_cents` is the principal plus any retro interest posted, minus `paid_cents`, minus any warranty or return credits applied.

A `FinanceAgent` records payments against an `ACTIVE` or `DELINQUENT` plan. Each payment's `amount_cents` must be at least 1 and no greater than the current `balance_cents`, else the request fails with `ERR_PAYMENT_EXCEEDS_BALANCE`; the payment increments `paid_cents` and decrements `balance_cents` by the same amount. When a payment brings `balance_cents` to 0, the plan moves to `PAID_OFF`. Delinquency is recomputed against the logical clock: when the number of installments due minus the number paid reaches 2 or more, the plan slides from `ACTIVE` to `DELINQUENT`; a payment that brings the paid count to within one of the due count cures the plan back to `ACTIVE`; and when the missed count reaches 4 or more, the plan is `DEFAULTED`.

Deferred-interest plans carry a retro accrual. When the logical clock reaches `activated_at` plus `promo_months` months — 12 months for `DEFERRED_INTEREST` — and `balance_cents` is still positive and `retro_interest_posted` is still false, the server computes a retro amount equal to the principal multiplied by `apr_bps` divided by 10000 and then by `promo_months` divided by 12, rounded half-up, adds it to `balance_cents`, and sets `retro_interest_posted` true. If the balance is already 0 at promo end, no retro interest ever posts.

### 3.10. Logical Clock Sweep

The `PlatformAdmin`-only clock capability accepts a `to_iso8601` instant and advances the logical clock to it. Advancing the clock triggers four sweeps in one pass: every `PROVISIONAL` `SleepNight` whose `night_date` plus one day at 12:00 UTC is at or before the new clock finalizes; every `ACTIVE` `DEFERRED_INTEREST` plan evaluates retro accrual; every `ACTIVE` or `DELINQUENT` plan re-evaluates delinquency and default; and every `DELIVERED` order with no non-terminal `TrialReturn` whose `trial_verified_at` plus 101 days is at or before the new clock closes to `CLOSED`.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; modifications, actions, and reads return HTTP 200. All endpoints are mounted under `/sleep` except the logical-clock capability. Role authorization is enforced per the table below in addition to the ownership rules in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sleep/stores | Create a store | PlatformAdmin |
| GET | /sleep/stores/{id} | Read a store | PlatformAdmin, SalesAssociate, ServiceAgent |
| POST | /sleep/product-models | Create a catalog product model | PlatformAdmin |
| POST | /sleep/customers | Register a customer account (self-service) | Anonymous |
| GET | /sleep/customers/{id} | Read a customer incl. computed entitlements and store_credit_cents | PlatformAdmin, SalesAssociate, ServiceAgent, Customer |
| GET | /sleep/customers | List customers; optional filter home_store_id; paginated | PlatformAdmin, SalesAssociate, ServiceAgent |
| PATCH | /sleep/customers/{id}/subscription | Change subscription tier; recomputes entitlements | PlatformAdmin |
| POST | /sleep/fit-assessments | Create an in-store fit assessment (DRAFT); optional supersedes_assessment_id | SalesAssociate |
| GET | /sleep/fit-assessments/{id} | Read a fit assessment | PlatformAdmin, SalesAssociate, Customer |
| GET | /sleep/fit-assessments | List fit assessments; filters customer_id?, store_id?, supersedes_assessment_id? | PlatformAdmin, SalesAssociate |
| POST | /sleep/fit-assessments/{id}/complete | Complete an assessment; computes recommendation; supersedes predecessor | SalesAssociate |
| POST | /sleep/orders | Create an order from a COMPLETED fit assessment; computes totals | Customer, SalesAssociate |
| GET | /sleep/orders/{id} | Read an order | PlatformAdmin, SalesAssociate, ServiceAgent, FinanceAgent, Customer |
| GET | /sleep/orders | List orders; filters customer_id?, fit_assessment_id? | PlatformAdmin, SalesAssociate, ServiceAgent, FinanceAgent |
| PATCH | /sleep/orders/{id} | Replace line_items on a PLACED order (OCC on expected_order_version); recomputes totals | Customer, SalesAssociate |
| POST | /sleep/orders/{id}/confirm | Confirm an order and capture payment or attach an ACCEPTED financing plan | SalesAssociate |
| POST | /sleep/orders/{id}/cancel | Cancel an order; cascades to visits and financing | Customer, SalesAssociate |
| POST | /sleep/delivery-windows | Create a delivery window for a store team | PlatformAdmin |
| GET | /sleep/delivery-windows/{id} | Read a delivery window incl. reserved_slots | PlatformAdmin, SalesAssociate, DeliveryTechnician |
| GET | /sleep/delivery-windows | List windows; filters store_id?, team_id?, window_date? | PlatformAdmin, SalesAssociate, DeliveryTechnician |
| POST | /sleep/delivery-visits | Schedule a delivery/setup visit; capacity check; WAITLISTED when full and allow_waitlist | SalesAssociate |
| GET | /sleep/delivery-visits/{id} | Read a delivery visit | PlatformAdmin, SalesAssociate, DeliveryTechnician, Customer |
| GET | /sleep/delivery-visits | List visits; filters order_id?, delivery_window_id? | PlatformAdmin, SalesAssociate, DeliveryTechnician, Customer |
| POST | /sleep/delivery-visits/{id}/reschedule | Move a SCHEDULED or FAILED_SETUP visit to a new window (OCC) | SalesAssociate, Customer |
| POST | /sleep/delivery-visits/{id}/complete | Complete a visit: outcome VERIFIED or FAILED_SETUP | DeliveryTechnician |
| POST | /sleep/devices | Register installed hardware under an order | DeliveryTechnician |
| GET | /sleep/devices/{id} | Read a device | PlatformAdmin, DeliveryTechnician, ServiceAgent, Customer |
| GET | /sleep/devices | List devices; filters order_id?, customer_id? | PlatformAdmin, DeliveryTechnician, ServiceAgent, Customer |
| POST | /sleep/devices/{id}/pair | Pair or unpair an adjustable base; records connectivity at pair time | DeliveryTechnician |
| POST | /sleep/devices/{id}/sleep-nights | Ingest one night of sleep data (PROVISIONAL) | DeviceGateway |
| GET | /sleep/sleep-nights/{id} | Read a sleep night | PlatformAdmin, ServiceAgent, Customer |
| GET | /sleep/sleep-nights | List sleep nights; filters device_id?, customer_id?, detail? | PlatformAdmin, ServiceAgent, Customer |
| POST | /sleep/orders/{id}/trial-return | Initiate an in-home trial return | Customer |
| GET | /sleep/trial-returns/{id} | Read a trial return | PlatformAdmin, ServiceAgent, Customer |
| GET | /sleep/trial-returns | List trial returns; filter order_id? | PlatformAdmin, ServiceAgent, Customer |
| POST | /sleep/trial-returns/{id}/inspect | Inspect a returned bed: APPROVED computes refund and cascades; REJECTED terminates | ServiceAgent |
| POST | /sleep/warranty-claims | File a prorated limited-warranty claim | Customer |
| GET | /sleep/warranty-claims/{id} | Read a warranty claim | PlatformAdmin, ServiceAgent, Customer |
| GET | /sleep/warranty-claims | List warranty claims; filters order_id?, device_id? | PlatformAdmin, ServiceAgent, Customer |
| POST | /sleep/warranty-claims/{id}/review | Review a FILED or APPEALED claim: APPROVE applies prorated credit; DENY allows appeal | ServiceAgent |
| POST | /sleep/warranty-claims/{id}/appeal | Appeal a DENIED claim | Customer |
| POST | /sleep/financing-plans | Create a financing offer for a PLACED order (OFFERED) | FinanceAgent |
| GET | /sleep/financing-plans/{id} | Read a financing plan | PlatformAdmin, FinanceAgent, ServiceAgent, Customer |
| GET | /sleep/financing-plans | List financing plans; filter order_id? | PlatformAdmin, FinanceAgent, ServiceAgent, Customer |
| POST | /sleep/financing-plans/{id}/accept | Customer accepts an OFFERED plan | Customer |
| POST | /sleep/financing-plans/{id}/payments | Record a payment against an ACTIVE or DELINQUENT plan | FinanceAgent |
| POST | /_clock/set_current_utc | Advance the logical clock; triggers finalization, retro accrual, delinquency, and trial-close sweeps | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_STORE_NOT_FOUND | 404 |
| ERR_PRODUCT_MODEL_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_FIT_ASSESSMENT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_DELIVERY_WINDOW_NOT_FOUND | 404 |
| ERR_DELIVERY_VISIT_NOT_FOUND | 404 |
| ERR_DEVICE_NOT_FOUND | 404 |
| ERR_SLEEP_NIGHT_NOT_FOUND | 404 |
| ERR_TRIAL_RETURN_NOT_FOUND | 404 |
| ERR_WARRANTY_CLAIM_NOT_FOUND | 404 |
| ERR_FINANCING_PLAN_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_ALREADY_TERMINAL | 409 |
| ERR_VISIT_ALREADY_COMPLETED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_FIT_ASSESSMENT_MISMATCH | 422 |
| ERR_DEVICE_NOT_ON_ORDER | 422 |
| ERR_DEVICE_NOT_PAIRED | 422 |
| ERR_WINDOW_CAPACITY_EXCEEDED | 422 |
| ERR_WINDOW_TEAM_OVERLAP | 422 |
| ERR_PROMO_TERM_INVALID | 422 |
| ERR_SETUP_CHECKLIST_INCOMPLETE | 422 |
| ERR_DUPLICATE_NIGHT | 409 |
| ERR_ENTITLEMENT_REQUIRED | 403 |
| ERR_WINDOW_IN_PAST | 422 |
| ERR_TRIAL_WINDOW_EXPIRED | 422 |
| ERR_WARRANTY_EXPIRED | 422 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_DOWN_PAYMENT_INSUFFICIENT | 402 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |
