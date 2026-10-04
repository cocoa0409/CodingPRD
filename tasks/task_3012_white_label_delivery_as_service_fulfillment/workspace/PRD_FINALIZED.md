# White-Label Delivery-as-a-Service Fulfillment API — Product Requirements Document

## 1. Introduction

Merchants increasingly want to offer delivery through their own branded channels — their own apps, their own websites, their own order numbers — without building or operating a courier fleet. This document specifies the White-Label Delivery-as-a-Service Fulfillment API: a platform through which a merchant takes orders in its own channel and outsources the physical delivery entirely by API. The end customer never sees the platform; the platform never sees the end customer's identity. The merchant's own `customer_reference` is the only thread that ties a delivery back to the merchant's internal order.

The system covers the full commercial loop of outsourced fulfillment. A merchant configures stores with per-store delivery radii and address-level serviceability overrides, authors pricing policies that express distance bands, order-value surcharges, peak-window uplift, and surge pass-through, and requests quotes that pin a fee for a short validity window. Accepted orders draw against the merchant's prepaid billing balance, are batched to couriers under strict white-label batching restrictions, and settle with a final fee that may differ from the quoted fee when platform surge moves between quote time and dispatch time. Undeliverable orders flow through merchant-directed disposition — return to store or disposal — and disputes flow through a refund-claim process that allocates liability between merchant and platform by fault code. Finally, service-level reporting computes on-time attainment in two variants and converts poor performance into service credits.

Because the platform mediates money in both directions — prepaid balances, invoice reconciliation, refund debits, and credits — the specification pays particular attention to exact rounding, deterministic allocation, optimistic concurrency on the two operations that can silently supersede one another, and a precisely ordered validation pipeline.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response envelopes, pagination, resource identity, the logical clock, validation ordering, monetary precision, and optimistic concurrency control.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four roles: `PlatformAdmin`, `Merchant`, `Courier`, and `SupportAgent`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of the acting Merchant; ownership checks on any resource that references a Merchant — stores, pricing policies, quotes, orders, claims, reports, credits — compare the resource's merchant foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Courier`, `X-User-ID` is the `id` of the acting Courier; ownership checks compare against courier references, most critically the assigned courier of a dispatched batch.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `SupportAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

A `PlatformAdmin` operates the platform itself: merchant onboarding and lifecycle, courier administration, batch creation, settlement and reversal of claims, SLA report finalization, service-credit application, and the clock and surge test-driving controls. A `Merchant` manages its own stores, pricing policies, quotes, and orders up to pickup readiness, decides dispositions, and files and appeals refund claims. A `Courier` executes the physical work: dispatching and failing batches, confirming pickup, driving transit, completing delivery, reporting undeliverable orders, and completing dispositions. A `SupportAgent` triages the refund-claim queue on the merchant's behalf — support routing back to the merchant happens through the claim workflow, never through direct customer contact.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control.

Merchants, stores, pricing policies, serviceability overrides, quotes, delivery orders, couriers, batches, dispositions, refund claims, SLA reports, and service credits all carry the full set. The TrackingEvent is the exception: it is an append-only feed item and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

Every other timestamp field carried on a resource — including `valid_until` on quotes, `occurred_at` on tracking events, `effective_from`/`effective_until` on pricing policies, `pickup_ready_at`, `promised_at`, `delivered_at`, dispatch-window bounds on batches, and report period bounds — is likewise serialized as an ISO 8601 UTC timestamp with three fractional digits.

### 2.5. The Logical Clock and Platform Surge Controls

The platform runs on a logical clock rather than wall time. At startup, before any adjustment, the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall time thereafter. A `PlatformAdmin` advances or sets the clock through an admin-only test-driving capability that accepts a `current_utc` instant and echoes it back; every time-dependent rule in this document — quote validity, lateness measurement, peak-window resolution, report windows — evaluates against this clock. Quotes whose `valid_until` has been reached read as `EXPIRED` from that point on.

A second admin-only capability sets the platform surge multiplier by accepting a `multiplier` value and echoing it back. The surge multiplier defaults to 1.0, meaning no surge. The multiplier in force at quote time is pinned onto each quote, and the multiplier in force at dispatch time drives the final fee variant; the difference between the two is the surge delta that the merchant's pass-through configuration governs.

### 2.6. Validation Ordering and Nested Resource Retrieval

When a request violates several rules at once, the rejection it receives is deterministic because validation layers are evaluated in a fixed priority order. The layers, from first to last, are:

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Role authorization.** The role must be permitted for the endpoint (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. **Path identifier existence.** For nested paths, identifiers are validated strictly left-to-right: a request naming a merchant and a pricing policy under it is rejected with `ERR_MERCHANT_NOT_FOUND` (HTTP 404) if the merchant does not exist, before the policy id is ever examined; a nonexistent policy under an existing merchant yields `ERR_PRICING_POLICY_NOT_FOUND`. The same pattern applies to stores (`ERR_STORE_NOT_FOUND`), quotes (`ERR_QUOTE_NOT_FOUND`), delivery orders (`ERR_DELIVERY_ORDER_NOT_FOUND`), couriers (`ERR_COURIER_NOT_FOUND`), batches (`ERR_BATCH_NOT_FOUND`), dispositions (`ERR_DISPOSITION_NOT_FOUND`), claims (`ERR_CLAIM_NOT_FOUND`), reports (`ERR_REPORT_NOT_FOUND`), and credits (`ERR_CREDIT_NOT_FOUND`).
4. **Body foreign-key existence.** Identifiers carried in the request body are validated in the endpoint's declared input order — for example, when creating a batch, `store_id` is checked before `courier_id`, which is checked before `order_ids` — and a missing referenced resource yields the corresponding not-found error.
5. **Optimistic concurrency.** Where an endpoint declares an expected-version field, the supplied value must match the parent entity's current `version` (`ERR_STALE_MERCHANT_VERSION` or `ERR_STALE_COURIER_VERSION`, HTTP 412); see §2.8.
6. **State preconditions.** The target entity must be in the state the transition requires (`ERR_INVALID_STATE`, `ERR_MERCHANT_SUSPENDED`, `ERR_STORE_NOT_ACTIVE`, `ERR_QUOTE_EXPIRED`, `ERR_DISPOSITION_NOT_REQUIRED`, HTTP 409).
7. **Temporal conflicts.** Courier dispatch-window conflicts (`ERR_COURIER_WINDOW_CONFLICT`) and pricing-policy effective-window overlaps (`ERR_POLICY_WINDOW_OVERLAP`), both HTTP 409.
8. **Business constraints.** Batching restrictions, courier capacity, batch size, address serviceability, band coverage, appeal limits, claim amounts, and disposition-outcome matching (`ERR_BATCHING_RESTRICTION_VIOLATION`, `ERR_COURIER_CAPACITY_EXCEEDED`, `ERR_INVALID_BATCH_SIZE`, `ERR_ADDRESS_NOT_SERVICEABLE`, `ERR_OUTSIDE_DELIVERY_RADIUS`, `ERR_APPEAL_LIMIT_EXCEEDED`, `ERR_CLAIM_EXCEEDS_INVOICE`, `ERR_INVALID_REQUEST`). Within this layer, address serviceability is checked before band coverage: when a payload violates both, the rejection is `ERR_ADDRESS_NOT_SERVICEABLE`.
9. **Fiscal sufficiency.** The merchant's billing balance must cover the funds being committed (`ERR_INSUFFICIENT_BILLING_BALANCE`, HTTP 402).

Because the layers are ordered, a request that fails an earlier layer never reaches a later one: a stale-version rejection, for example, always masks any business-constraint problem the same payload might also have, and an authentication failure masks everything.

### 2.7. Monetary Precision and Rounding

All monetary values are integer cents; no fractional cents ever appear in stored fields or responses. Where a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Two rounding disciplines matter throughout: first, within the delivery-fee calculation, every component (the peak uplift, the surge component, the pass-through delta) is individually rounded half up to whole cents *before* the components are summed — the component-then-sum order is pinned and must not be reversed; second, in the batch fee allocation, each order's share is rounded *down* to whole cents and the leftover remainder is granted to a single order, so the allocated shares always sum exactly back to the batch courier cost. Attainment rates on SLA reports are the one non-integer quantity in the system: they are stored as decimals rounded half up to four decimal places.

### 2.8. Optimistic Concurrency Control

Two write operations mutate a parent entity's `version` as a side effect and therefore require the caller to prove it has observed the parent's current state. Endpoints not listed here take no version field.

- Activating a pricing policy (`POST /merchants/{id}/pricing-policies/{pid}/activate`) archives the merchant's currently active policy and increments the merchant's `version`. The request must carry `expected_merchant_version` equal to the merchant's current `version`. If the merchant's version has advanced since the client last read it, the request is rejected with `ERR_STALE_MERCHANT_VERSION` (HTTP 412), so a superseding activation is never silently clobbered by a stale one.
- Creating a delivery batch (`POST /delivery-batches`) commits workload against a courier and increments the courier's `version`. The request must carry `expected_courier_version` equal to the courier's current `version`. If the courier's version has advanced since the client last read it, the request is rejected with `ERR_STALE_COURIER_VERSION` (HTTP 412), preventing the client from building on a view of the courier's committed workload it has not observed.

## 3. Business Logic & Workflows

### 3.1. Merchant Onboarding and the Billing Balance

A `PlatformAdmin` creates a merchant by supplying its brand `name` and an initial prepaid `billing_balance_cents`, and may optionally set `default_refund_split_merchant_pct` — the merchant's share, as a whole percentage from 0 to 100 inclusive, applied to refund faults attributed to customer unavailability or address problems, defaulting to 50 — and `late_credit_enabled`, a boolean defaulting to true that controls whether accrued late-delivery credits are applied automatically. A new merchant starts in `ONBOARDING` status with `credit_balance_cents` at zero; the credit balance is the running sum of `amount_cents` across the merchant's service credits in `APPLIED` status, excluding any in `VOIDED`.

Activation moves the merchant from `ONBOARDING` to `ACTIVE` and increments its `version`; only a merchant currently in `ONBOARDING` can be activated, otherwise the request fails with `ERR_INVALID_STATE`. Suspension moves an `ACTIVE` merchant to `SUSPENDED` and cascades through its book of work: every delivery order still in `QUOTED`, `ACCEPTED`, or `READY_FOR_PICKUP` is cancelled, each such order's billing moves to `VOIDED`, and any order whose fee had been authorized releases its hold by adding its `quoted_fee_cents` back to the merchant's `billing_balance_cents`. Suspension can also be triggered by the platform itself when a refund settlement drives `billing_balance_cents` below zero. Resuming returns a `SUSPENDED` merchant to `ACTIVE`. Each of these lifecycle transitions increments the merchant's `version`, as does any configuration update to `default_refund_split_merchant_pct` or `late_credit_enabled`. A merchant that is not `ACTIVE` cannot accept orders — the attempt is rejected with `ERR_MERCHANT_SUSPENDED`.

### 3.2. Stores, Delivery Radius, and Address Serviceability

A merchant (or a `PlatformAdmin` on its behalf) creates a store with a `name`, a pickup `address_text`, coordinates `lat` and `lng` in degrees, a `delivery_radius_m` in meters, and an IANA `timezone`. The store begins `ACTIVE`; it can later be updated — a new `delivery_radius_m`, a new `timezone`, or a `status` change to `CLOSED` — and each update increments the store's `version`. Every delivery from the store originates at the store's coordinates, and the store's timezone is what resolves clock timestamps against local peak windows. Order acceptance requires the pickup store to be `ACTIVE`; otherwise the request fails with `ERR_STORE_NOT_ACTIVE`.

The straight-line distance between store and dropoff is computed with a Manhattan-planar approximation in integer meters, rounded half up: take the absolute difference in latitude degrees and multiply by 111320, take the absolute difference in longitude degrees, multiply by the cosine of the mean latitude of the two points expressed in radians, and multiply that by 111320 as well; the distance is the sum of the two products, rounded half up to a whole meter.

Serviceability is decided per dropoff address. A store may carry address-level overrides, each created with an `address_pattern` and an `effect` of either `ALLOW` or `DENY`. When a dropoff address is checked — either through the standalone serviceability check, which takes `dropoff_lat`, `dropoff_lng`, and `address_text` and reports a `serviceable` boolean, the computed `distance_m`, and the `matched_override_effect`, or implicitly at quote time — the system collects every override of the store whose `address_pattern` is a case-insensitive substring of the dropoff `address_text`. If at least one override matches, the winner is the matching override with the longest `address_pattern`, with ties broken by earliest `created_at`; a winning `DENY` makes the address not serviceable regardless of distance, while a winning `ALLOW` falls through to the radius test. With no matching override, the radius test alone decides: the address is serviceable when the computed distance is no greater than `delivery_radius_m` — the boundary is inclusive, so a dropoff exactly on the radius is serviceable. An address that fails this verdict is rejected with `ERR_ADDRESS_NOT_SERVICEABLE`.

### 3.3. Pricing Policies and Activation

Pricing is configured per merchant as a policy composed of five inputs: `distance_bands`, an ordered array of entries each carrying `max_m`, `base_cents`, and `per_100m_cents`, where the first band covers distances from zero up to its `max_m` and each later band covers distances above the previous band's `max_m` up to its own; `value_tiers`, an ordered array of entries each carrying `min_order_value_cents` and `surcharge_cents`; `peak_windows`, an array of half-open local-time windows each defined by `start_local_hhmm` and `end_local_hhmm` in the store's timezone; `peak_uplift_pct`, the fractional uplift applied during peak windows; and `surge_passthrough_pct`, the fraction of the dispatch-time surge delta passed through to the merchant invoice. Every policy also declares a half-open effective window from `effective_from` to `effective_until`, the end strictly after the start.

A new policy is `DRAFT`. Activation — performed by the merchant with an `expected_merchant_version` as described in §2.8 — moves the policy to `ACTIVE`, automatically archives whatever policy of the same merchant was previously `ACTIVE` (the `ACTIVE` to `ARCHIVED` transition is system-driven and needs no request), and increments the merchant's `version`. At most one policy per merchant may be `ACTIVE` at any time, and activation is rejected with `ERR_INVALID_STATE` unless the policy is `DRAFT`. The candidate policy's half-open effective window must not overlap the effective window of any other `ACTIVE` policy of the same merchant; an overlap is rejected with `ERR_POLICY_WINDOW_OVERLAP`. `ARCHIVED` is terminal.

### 3.4. Quoting and the Dual-Variant Delivery Fee

A merchant requests a quote by naming the pickup `store_id` and supplying `dropoff_lat`, `dropoff_lng`, the dropoff `address_text`, the merchandise `order_value_cents`, and a merchant-declared `pickup_ready_at`; the quoting merchant is the caller identified by `X-User-ID`. Quoting first re-runs the distance and serviceability logic of §3.2 — an address denied by override or beyond the radius fails with `ERR_ADDRESS_NOT_SERVICEABLE` — and requires an `ACTIVE` pricing policy of the merchant whose effective window contains the current clock; with none, the request fails with `ERR_NO_ACTIVE_PRICING_POLICY`. If the computed distance exceeds the last distance band's `max_m`, the quote is rejected with `ERR_OUTSIDE_DELIVERY_RADIUS`.

The quoted fee is assembled from four components, each an integer number of cents and each rounded half up before summing. The `band_fee_cents` come from the first band in array order whose `max_m` is at least the distance: for the first band that is simply its `base_cents`; for any later band it is the band's `base_cents` plus its `per_100m_cents` multiplied by the excess distance over the previous band's `max_m`, with the excess divided into 100-meter increments and any partial increment rounded up to a whole increment. The `value_surcharge_cents` are the `surcharge_cents` of the highest value tier whose `min_order_value_cents` is at most the `order_value_cents`, and zero when no tier qualifies. The `peak_uplift_cents` apply when `pickup_ready_at`, converted into the store's timezone, falls inside any of the policy's half-open peak windows: the uplift is the sum of band fee and value surcharge multiplied by `peak_uplift_pct`, rounded half up, and zero off-peak. The sum of these three is the base total. The `surge_component_cents` are the base total multiplied by the amount by which the current platform surge multiplier exceeds one, rounded half up; with the multiplier at its default of 1.0 the surge component is zero. The `quoted_fee_cents` are the base total plus the surge component.

The quote pins the policy it used as `pricing_policy_id` and the surge multiplier in force as `quoted_surge_multiplier`, records the computed `distance_m`, and is usable for fifteen minutes: `valid_until` is set to the creation clock time plus fifteen minutes. A quote is `ACTIVE` until it is consumed or its validity lapses; any read or use at or after `valid_until` marks it `EXPIRED`, and an attempt to consume an expired quote is rejected with `ERR_QUOTE_EXPIRED`. `CONSUMED` and `EXPIRED` are terminal.

The fee has a second, final variant computed at batch dispatch. The final variant recomputes the surge component using the platform surge multiplier in force at dispatch time rather than at quote time, yielding the order's `final_fee_cents`. What the merchant actually pays, the `merchant_invoice_cents`, is the base total plus the *quoted* surge component plus the pass-through of the surge delta: the difference between the final surge component and the quoted surge component, multiplied by the policy's `surge_passthrough_pct`, rounded half up. The invoice is floored at the base total, so a negative surge delta can reduce the invoice down to the base total but never below it. Identical inputs can therefore legitimately produce an invoice different from the quoted fee whenever surge moved between quote and dispatch.

### 3.5. Order Intake, Acceptance, and Cancellation

A merchant turns a quote into a delivery order by submitting the `quote_id`, its own `customer_reference` — the white-label link back to the merchant's channel, since the platform never learns the end customer's identity — and an `idempotency_key`. The key is scoped to the merchant: repeating the same key returns the original order rather than creating a duplicate. Consuming the quote moves it to `CONSUMED` and creates the order with `merchant_id` and `store_id` copied from the quote, `quoted_fee_cents` copied and thereafter immutable, fulfillment status `QUOTED` and billing status `PENDING` — the order carries these two status dimensions in parallel — `batch_id` empty until batching, `final_fee_cents`, `merchant_invoice_cents`, and `batch_fee_share_cents` empty until dispatch, `late_credit_cents` at zero, and `delivered_at` empty until delivery.

Acceptance, performed by the merchant, supplies the `promised_at` delivery time against which lateness is later measured, and moves the order's `fulfillment_status` from `QUOTED` to `ACCEPTED`. Acceptance authorizes funds: the `billing_status` dimension moves from `PENDING` to `AUTHORIZED` and the merchant's `billing_balance_cents` is debited by the `quoted_fee_cents`. An order not in `QUOTED` cannot be accepted (`ERR_INVALID_STATE`); acceptance also requires the merchant to be `ACTIVE` (`ERR_MERCHANT_SUSPENDED`), the store to be `ACTIVE` (`ERR_STORE_NOT_ACTIVE`), and the billing balance to be at least the quoted fee — a shortfall is rejected with `ERR_INSUFFICIENT_BILLING_BALANCE` (HTTP 402). Acceptance emits a merchant-visible `ORDER_ACCEPTED` tracking event. The merchant then signals pickup readiness by moving the order from `ACCEPTED` to `READY_FOR_PICKUP`; only `ACCEPTED` orders can be marked ready.

Cancellation is available from either pre-pickup state. Cancelling a `QUOTED` order moves it to `CANCELLED` and voids its billing — no hold ever existed, so nothing is returned. Cancelling an `ACCEPTED` order moves it to `CANCELLED`, voids the billing, and releases the hold by crediting `quoted_fee_cents` back to `billing_balance_cents`, emitting a `CANCELLED` tracking event. From any other fulfillment state, cancellation is rejected with `ERR_INVALID_STATE`.

### 3.6. Batching, Dispatch, and Courier Execution

Couriers are administered by the `PlatformAdmin`: created with a display `name` (internal only — never shown to merchant customers) and an optional `max_active_deliveries` capacity cap defaulting to 4, starting `ACTIVE`. An `ACTIVE` courier can be suspended and a `SUSPENDED` one reactivated by updating the courier's `status`; capacity can be adjusted the same way, and every such update increments the courier's `version`.

Batching is where the white-label restriction bites: a batch is created by a `PlatformAdmin` naming a `store_id`, a `courier_id`, an `order_ids` array of between one and three orders, a closed dispatch window from `dispatch_window_start` to `dispatch_window_end` (the end strictly after the start), and the `expected_courier_version` of §2.8. Every order in the batch must belong to the batch's store — white-label orders of different stores are never co-batched — and every order must already be `READY_FOR_PICKUP`; violations are rejected with `ERR_BATCHING_RESTRICTION_VIOLATION`, and an `order_ids` array outside the one-to-three range with `ERR_INVALID_BATCH_SIZE`. Creation sets each order's `batch_id`, computes the batch's `courier_cost_cents` as a base of 400 cents plus 150 cents per order, increments the courier's `version`, and leaves the batch `COURIER_ASSIGNED`.

Dispatch, performed by the assigned courier, moves the batch from `COURIER_ASSIGNED` to `DISPATCHED` and is where the final money is fixed. Dispatch requires the batch to be `COURIER_ASSIGNED` and the courier `ACTIVE` (otherwise `ERR_INVALID_STATE`), that every order in the batch is `READY_FOR_PICKUP`, that the closed dispatch window not overlap the dispatch window of any other `DISPATCHED` batch of the same courier — windows that merely touch at an endpoint count as overlapping and are rejected with `ERR_COURIER_WINDOW_CONFLICT` — and that the courier's committed load stay within capacity: the number of orders across the courier's other `DISPATCHED` batches plus this batch's size must not exceed `max_active_deliveries`, else `ERR_COURIER_CAPACITY_EXCEEDED`. On dispatch, each order's final fee variant is computed — `final_fee_cents` and `merchant_invoice_cents` per §3.4 — and each order's `batch_fee_share_cents` is allocated from the batch courier cost: every order's raw share is the courier cost multiplied by that order's invoice and divided by the sum of invoices across the batch, each share is floored to whole cents, and the leftover remainder after flooring is granted to the order with the earliest `created_at`, so the shares sum exactly back to the courier cost. Dispatch increments the courier's `version` and emits a `COURIER_ASSIGNED` tracking event for each order.

The courier then walks each order through the physical leg. Confirming pickup moves an order from `READY_FOR_PICKUP` to `PICKED_UP` and requires the acting courier to be the one whose `courier_id` is on the order's `DISPATCHED` batch — the `X-User-ID` must match — otherwise `ERR_INVALID_STATE`; a merchant-visible `PICKED_UP` event is emitted. Starting transit moves `PICKED_UP` to `IN_TRANSIT` with a merchant-visible `IN_TRANSIT` event.

A batch can also fail. Failing a batch in `COURIER_ASSIGNED` or `DISPATCHED` (any other state yields `ERR_INVALID_STATE`) releases all of its non-terminal orders by clearing their `batch_id`, making them available for a later batch. When a `DISPATCHED` batch fails, orders that were never picked up revert to `READY_FOR_PICKUP`; invoiced amounts already computed stay on the orders, and a later re-dispatch recomputes them. A batch reaches `COMPLETED` automatically the moment every order in it has reached a terminal fulfillment state.

### 3.7. Completion, Undeliverable Disposition, and Late-Delivery Credits

Completing a delivery moves an order from `IN_TRANSIT` to `DELIVERED` and performs settlement. The clock time is recorded as `delivered_at`; the billing dimension moves from `AUTHORIZED` to `SETTLED`; and the invoice is reconciled against the hold by adjusting the merchant's `billing_balance_cents` by the difference between `merchant_invoice_cents` and `quoted_fee_cents` — a negative difference refunds the merchant. Completion also computes the order's late-delivery credit and emits a merchant-visible `DELIVERED` event; if every order in the parent batch is now in a terminal fulfillment state, the batch moves to `COMPLETED`.

An order that cannot be delivered is reported undeliverable from either `PICKED_UP` or `IN_TRANSIT` by the courier, who supplies a `reason_code` recorded as the order's `undeliverable_reason`: one of `CUSTOMER_UNAVAILABLE`, `ADDRESS_ISSUE`, or `DAMAGED_IN_TRANSIT`. Reporting settles the order financially exactly as a completed delivery — billing moves to `SETTLED`, the invoice is reconciled the same way, and the merchant still pays — and emits a merchant-visible `UNDELIVERABLE` event. The late-delivery credit is computed against the clock at report time.

The late-delivery credit itself is a threshold rule over lateness, measured as the gap between the event's clock time and `promised_at`. Lateness up to and including ten minutes (600 seconds) earns no credit — exactly ten minutes is still on time. Lateness beyond ten minutes and up to and including thirty minutes (1800 seconds) earns a credit of the `merchant_invoice_cents` multiplied by one quarter (25 percent), rounded half up. Lateness beyond thirty minutes earns a credit equal to the full `merchant_invoice_cents`. The result is stored on the order as `late_credit_cents`.

An `UNDELIVERABLE` order awaits the merchant's disposition. Choosing `RETURN_TO_STORE` as the `resolution` creates a `PENDING` disposition whose `return_fee_cents` carry the platform's fixed return-handling fee of 500 cents, debits that fee from the merchant's `billing_balance_cents`, moves the order to `RETURN_IN_PROGRESS`, and emits a merchant-visible `RETURN_IN_PROGRESS` event. Choosing `DISPOSE` creates a `PENDING` disposition with `return_fee_cents` of zero and moves the order to `DISPOSAL_PENDING`. Requesting a disposition for an order that is not `UNDELIVERABLE`, or a second disposition for an order already disposed, is rejected with `ERR_DISPOSITION_NOT_REQUIRED`. The courier then completes the disposition by supplying an `outcome`: `RETURNED` completes a return-to-store disposition and moves the order to `RETURNED_TO_STORE` with the corresponding merchant-visible event; `DISPOSED` completes a dispose disposition and moves the order to `DISPOSED` likewise. The outcome must match the disposition's `resolution`, the disposition must still be `PENDING` (otherwise `ERR_INVALID_STATE`), and completion marks the disposition `COMPLETED` and auto-completes the parent batch when all its orders are terminal.

### 3.8. Refund Claims and Liability Allocation

A merchant files a refund claim against one of its orders by naming the `delivery_order_id`, a `fault_code`, and a `claimed_amount_cents`; the claim copies the `merchant_id` from the order. The order's billing must be `SETTLED` — a claim against an order in any other billing state is rejected with `ERR_CLAIM_ORDER_NOT_SETTLED` — and the claimed amount must not exceed the order's `merchant_invoice_cents`, else `ERR_CLAIM_EXCEEDS_INVOICE`. The fault code is one of `COURIER_DELAY`, `PLATFORM_OUTAGE`, `MERCHANT_FULFILLMENT`, `CUSTOMER_UNAVAILABLE`, or `ADDRESS_ISSUE`. A new claim is `FILED` with `appeal_count` zero.

A `SupportAgent` picks the claim up, moving `FILED` to `UNDER_REVIEW`, and then decides it by supplying a `decision`. A `decision` of `DENY` moves the claim to `DENIED` with no further effect. A `decision` of `APPROVE` moves it to `APPROVED` and computes the liability split in a pinned order. The order's `merchant_invoice_cents`, already fixed at dispatch, is used as-is. The merchant's percentage of the fault is determined first: zero for `COURIER_DELAY` or `PLATFORM_OUTAGE`, one hundred for `MERCHANT_FULFILLMENT`, and the merchant's configured `default_refund_split_merchant_pct` for `CUSTOMER_UNAVAILABLE` or `ADDRESS_ISSUE`. The `merchant_share_cents` are then the `claimed_amount_cents` multiplied by that percentage and divided by one hundred, rounded half up, and the `platform_share_cents` are the remainder of the claimed amount. A platform cap applies only to the delay and outage faults: the platform's share is capped at the order's invoice multiplied by two, rounded half up, and if the computed platform share exceeds the cap, the platform share is reduced to the cap and the merchant absorbs the rest of the claimed amount. The two shares always sum exactly to the claimed amount.

A denied claim may be appealed by the merchant exactly once: appealing a `DENIED` claim increments `appeal_count` and moves the claim to `APPEALED`, from which a `SupportAgent` starts a second review pass back into `UNDER_REVIEW`; any appeal beyond the first is rejected with `ERR_APPEAL_LIMIT_EXCEEDED`.

Settlement and reversal belong to the `PlatformAdmin`. Settling an `APPROVED` claim moves it to `SETTLED`, flips the order's billing from `SETTLED` to `REFUNDED`, and debits the `merchant_share_cents` from the merchant's `billing_balance_cents` — the merchant pays its share. If that debit drives the balance below zero, the merchant is suspended and the full suspension cascade of §3.1 fires: its non-terminal orders are cancelled, their billing voided, and their holds released. Reversing a `SETTLED` claim is the exact compensation: the `merchant_share_cents` are credited back to the billing balance, the order's billing returns from `REFUNDED` to `SETTLED`, and the claim becomes `REVERSED`. `SETTLED` and `REVERSED` are the claim's terminal states, and each transition enforces its source state with `ERR_INVALID_STATE`.

### 3.9. SLA Reporting and Service Credits

A `PlatformAdmin` opens an SLA report for a merchant over a half-open period from `period_start` to `period_end`, the end strictly after the start; the report begins `OPEN`. Finalizing an `OPEN` report (any other state yields `ERR_INVALID_STATE`) computes four measures and accrues credits. The population is the merchant's delivered orders whose `delivered_at` falls inside the half-open window; `total_deliveries` is its size, and an order counts as late when its `delivered_at` is later than its `promised_at` plus the ten-minute grace. `late_deliveries_gross` counts every late order regardless of fault, and `attainment_rate_gross` is one minus the ratio of late to total — defined as 1.0 when there are no deliveries at all. The `attainment_rate_fault_adjusted` variant excludes from both the numerator and the denominator any late order that carries a `SETTLED` refund claim whose `fault_code` is `MERCHANT_FULFILLMENT`, so identical data can yield a higher fault-adjusted rate than the gross one; it is likewise 1.0 when its adjusted population is empty. Both rates are stored rounded half up to four decimal places.

Credits accrue when the gross attainment falls below 97 percent: one service credit per late order in the gross population, each copying that order's `late_credit_cents` as its `amount_cents`, stamped with the `reason` `LATE_DELIVERY`, linked to the report through `sla_report_id` and to the order through `delivery_order_id`, and starting `ACCRUED`. When the merchant's `late_credit_enabled` flag is set, finalization immediately applies each new credit: the credit moves to `APPLIED` and the merchant's `credit_balance_cents` grows by the credit's amount. Otherwise the credit waits in `ACCRUED` until a `PlatformAdmin` applies it — which adds `amount_cents` to the merchant's `credit_balance_cents` — or voids it, which moves it to `VOIDED` with no balance effect. Both apply and void require the credit to be `ACCRUED`, else `ERR_INVALID_STATE`; `APPLIED` and `VOIDED` are terminal.

Tracking runs alongside every workflow above. Beyond the lifecycle events the system emits, a courier or `PlatformAdmin` may append a tracking event to an order directly, supplying an `event_type` — one of `ORDER_ACCEPTED`, `COURIER_ASSIGNED`, `PICKED_UP`, `IN_TRANSIT`, `DELIVERED`, `UNDELIVERABLE`, `RETURN_IN_PROGRESS`, `RETURNED_TO_STORE`, `DISPOSED`, `CANCELLED`, or `NOTE` — an optional free-text `note` defaulting to empty, and a `visibility` of `MERCHANT_VISIBLE` or `INTERNAL_ONLY`, defaulting to `MERCHANT_VISIBLE`; the event records the logical clock time as `occurred_at`. The branded tracking feed for an order shows `MERCHANT_VISIBLE` events only when read by a `Merchant`, and all events regardless of visibility when read by a `Courier`, `SupportAgent`, or `PlatformAdmin`.

Throughout §3, malformed payloads are caught uniformly: a missing required field, a type mismatch, an enum value outside its declared set, or a structural payload error — for example an `order_ids` array whose size falls outside the one-to-three range or a disposition completion whose `outcome` does not match the disposition's `resolution` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. An idempotency-key replay creates no new resource, so it returns `200 OK` carrying the originally created resource. Request payloads, side effects, and preconditions for each endpoint are specified in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_surge/set_current` | Set the platform surge multiplier | PlatformAdmin |
| POST | `/merchants` | Create merchant (ONBOARDING) | PlatformAdmin |
| GET | `/merchants` | List merchants | PlatformAdmin, SupportAgent |
| GET | `/merchants/{id}` | Get merchant | PlatformAdmin, SupportAgent, Merchant |
| PATCH | `/merchants/{id}` | Update merchant config (refund split pct, late_credit_enabled) | PlatformAdmin, Merchant |
| POST | `/merchants/{id}/activate` | ONBOARDING → ACTIVE | PlatformAdmin |
| POST | `/merchants/{id}/suspend` | ACTIVE → SUSPENDED with order-cancellation cascade | PlatformAdmin |
| POST | `/merchants/{id}/resume` | SUSPENDED → ACTIVE | PlatformAdmin |
| POST | `/merchants/{id}/stores` | Create store for merchant | Merchant, PlatformAdmin |
| GET | `/merchants/{id}/stores` | List stores of merchant | Merchant, PlatformAdmin, SupportAgent |
| GET | `/stores/{id}` | Get store | Merchant, PlatformAdmin, SupportAgent |
| PATCH | `/stores/{id}` | Update store (delivery_radius_m, status, timezone) | Merchant, PlatformAdmin |
| POST | `/stores/{id}/serviceability-overrides` | Create address-level ALLOW/DENY override | Merchant, PlatformAdmin |
| GET | `/stores/{id}/serviceability-overrides` | List overrides of store | Merchant, PlatformAdmin, SupportAgent |
| POST | `/stores/{id}/check-serviceability` | Compute distance and serviceability verdict for a dropoff address | Merchant, PlatformAdmin |
| POST | `/merchants/{id}/pricing-policies` | Create pricing policy (DRAFT) | Merchant, PlatformAdmin |
| GET | `/merchants/{id}/pricing-policies` | List policies of merchant | Merchant, PlatformAdmin, SupportAgent |
| GET | `/pricing-policies/{id}` | Get policy | Merchant, PlatformAdmin, SupportAgent |
| POST | `/merchants/{id}/pricing-policies/{pid}/activate` | DRAFT → ACTIVE; archives the merchant's current ACTIVE policy (OCC-guarded) | Merchant |
| POST | `/delivery-quotes` | Quote a delivery: serviceability + quoted fee; pins ACTIVE policy and current surge | Merchant |
| GET | `/delivery-quotes` | List quotes | Merchant, PlatformAdmin |
| GET | `/delivery-quotes/{id}` | Get quote (EXPIRED applied on read when past valid_until) | Merchant, PlatformAdmin |
| POST | `/delivery-orders` | Create order from quote (consumes quote); idempotent on idempotency key | Merchant |
| GET | `/delivery-orders` | List orders with filters | Merchant, PlatformAdmin, SupportAgent, Courier |
| GET | `/delivery-orders/{id}` | Get order | Merchant, PlatformAdmin, SupportAgent, Courier |
| POST | `/delivery-orders/{id}/accept` | QUOTED → ACCEPTED; authorizes quoted fee against billing balance | Merchant |
| POST | `/delivery-orders/{id}/cancel` | QUOTED/ACCEPTED → CANCELLED; releases any billing hold | Merchant |
| POST | `/delivery-orders/{id}/mark-ready` | ACCEPTED → READY_FOR_PICKUP | Merchant |
| POST | `/delivery-orders/{id}/confirm-pickup` | READY_FOR_PICKUP → PICKED_UP (courier must hold the dispatched batch) | Courier |
| POST | `/delivery-orders/{id}/start-transit` | PICKED_UP → IN_TRANSIT | Courier |
| POST | `/delivery-orders/{id}/complete-delivery` | IN_TRANSIT → DELIVERED; settles billing, reconciles invoice delta, computes late credit | Courier |
| POST | `/delivery-orders/{id}/report-undeliverable` | PICKED_UP/IN_TRANSIT → UNDELIVERABLE; billing settles as delivered | Courier |
| POST | `/delivery-orders/{id}/disposition` | Merchant decides RETURN_TO_STORE or DISPOSE for an UNDELIVERABLE order | Merchant |
| GET | `/delivery-orders/{id}/disposition` | Get dispositions of order | Merchant, PlatformAdmin, SupportAgent, Courier |
| POST | `/dispositions/{id}/complete` | Courier confirms RETURNED or DISPOSED; outcome must match resolution | Courier |
| POST | `/delivery-orders/{id}/tracking-events` | Emit a tracking event | Courier, PlatformAdmin |
| GET | `/delivery-orders/{id}/tracking-events` | Branded tracking feed (visibility-filtered by role) | Merchant, Courier, SupportAgent, PlatformAdmin |
| POST | `/couriers` | Create courier | PlatformAdmin |
| GET | `/couriers` | List couriers | PlatformAdmin, SupportAgent |
| GET | `/couriers/{id}` | Get courier | PlatformAdmin, SupportAgent, Courier |
| PATCH | `/couriers/{id}` | Update courier status or capacity | PlatformAdmin |
| POST | `/delivery-batches` | Create batch assigning 1–3 READY_FOR_PICKUP orders of one store to a courier (OCC-guarded) | PlatformAdmin |
| GET | `/delivery-batches` | List batches | PlatformAdmin, Courier, SupportAgent |
| GET | `/delivery-batches/{id}` | Get batch | PlatformAdmin, Courier, SupportAgent, Merchant |
| POST | `/delivery-batches/{id}/dispatch` | COURIER_ASSIGNED → DISPATCHED; computes final fee variant and batch fee allocation | Courier |
| POST | `/delivery-batches/{id}/fail` | COURIER_ASSIGNED/DISPATCHED → FAILED; releases orders for re-batching | Courier |
| POST | `/refund-claims` | File refund claim against a SETTLED-billing order | Merchant |
| GET | `/refund-claims` | List claims | Merchant, SupportAgent, PlatformAdmin |
| GET | `/refund-claims/{id}` | Get claim | Merchant, SupportAgent, PlatformAdmin |
| POST | `/refund-claims/{id}/start-review` | FILED/APPEALED → UNDER_REVIEW | SupportAgent |
| POST | `/refund-claims/{id}/decide` | UNDER_REVIEW → APPROVED (computes liability split) or DENIED | SupportAgent |
| POST | `/refund-claims/{id}/appeal` | DENIED → APPEALED (max 1 appeal) | Merchant |
| POST | `/refund-claims/{id}/settle` | APPROVED → SETTLED; debits merchant share, cascades order billing and possible suspension | PlatformAdmin |
| POST | `/refund-claims/{id}/reverse` | SETTLED → REVERSED; exact compensation restoring balance and order billing | PlatformAdmin |
| POST | `/merchants/{id}/sla-reports` | Open an SLA report for a half-open period | PlatformAdmin |
| GET | `/merchants/{id}/sla-reports` | List SLA reports of merchant | Merchant, PlatformAdmin, SupportAgent |
| GET | `/sla-reports/{id}` | Get SLA report | Merchant, PlatformAdmin, SupportAgent |
| POST | `/sla-reports/{id}/finalize` | OPEN → FINALIZED; computes attainment variants and accrues late-delivery credits | PlatformAdmin |
| GET | `/sla-reports/{id}/service-credits` | List credits accrued by a report | Merchant, PlatformAdmin, SupportAgent |
| GET | `/service-credits/{id}` | Get service credit | Merchant, PlatformAdmin, SupportAgent |
| GET | `/service-credits` | List service credits (cross-merchant admin view) | PlatformAdmin, SupportAgent |
| GET | `/merchants/{id}/service-credits` | List service credits of merchant | Merchant, PlatformAdmin, SupportAgent |
| POST | `/service-credits/{id}/apply` | ACCRUED → APPLIED; credits merchant credit balance | PlatformAdmin |
| POST | `/service-credits/{id}/void` | ACCRUED → VOIDED; no balance effect | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MERCHANT_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_COURIER_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_DISPOSITION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MERCHANT_SUSPENDED` | 409 Conflict |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_DISPOSITION_NOT_REQUIRED` | 409 Conflict |
| `ERR_STALE_MERCHANT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_COURIER_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COURIER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_COURIER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_BATCH_SIZE` | 409 Conflict |
| `ERR_BATCHING_RESTRICTION_VIOLATION` | 409 Conflict |
| `ERR_ADDRESS_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_OUTSIDE_DELIVERY_RADIUS` | 409 Conflict |
| `ERR_APPEAL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_INVOICE` | 409 Conflict |
| `ERR_CLAIM_ORDER_NOT_SETTLED` | 409 Conflict |
| `ERR_INSUFFICIENT_BILLING_BALANCE` | 402 Payment Required |
| `ERR_NO_ACTIVE_PRICING_POLICY` | 409 Conflict |
