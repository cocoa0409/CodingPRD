# Digital Makeline Capacity API — Product Requirements Document

## 1. Introduction

This document specifies the Digital Make-Line Capacity & Second-Line Throughput Management API for a fast-casual restaurant operator running two physically separated assembly lines: the front-of-house line that serves walk-in guests, and a dedicated second make-line that assembles digital orders out of the in-store queue's way. Digital demand is lumpy and promise-driven — a marketplace surge at the lunch peak can overwhelm a fixed-capacity line within minutes — so the system paces digital order acceptance against a sequence of short production windows, extending quoted promise times to later windows before it ever rejects an order outright.

Behind the pacing layer sit the disciplines that keep a kitchen honest: ingredients are cooked in tracked batches with mandatory hold-time discards, portioning follows standard recipe grams, food cost is compared continuously between a theoretical standard and an actual ledger that absorbs waste and expiry, and ingredient shortages cascade automatically into menu suppression scoped to the affected sales channels. Customized digital bowls are verified against their lid labels before they can be marked ready, staffing deployments split the scheduled headcount between the two lines under a segregation-of-duties lock, and third-party marketplaces inject orders at marked-up prices net of commission. The day ends with a guarded close that freezes the day's food-cost variance and rolls the store forward.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint in the API, which is mounted under `/api/v1`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational capacity in which they act. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `StoreManager`, `GeneralManager`, `LineWorker`, and `MarketplaceChannel`.

- A `PlatformAdmin` is a corporate platform operator who provisions stores, ingredients, and marketplace channels and drives the logical clock.
- A `StoreManager` is a store-level manager who owns the menu, authors and publishes staffing deployments, cancels orders, resolves manual suppression events, and may record waste.
- A `GeneralManager` is an above-store leader who locks staffing deployments (under segregation of duties against the publisher) and runs the day close.
- A `LineWorker` is make-line staff who cooks batches, works orders through production, performs accuracy verification, and records waste.
- A `MarketplaceChannel` represents a third-party marketplace injecting orders under its own channel identity.

For the roles `PlatformAdmin`, `StoreManager`, `GeneralManager`, and `LineWorker`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `verified_by` on an `AccuracyVerification` where a verification pass writes it) but does not compare it to any entity's `id`. When `X-User-Role` is `MarketplaceChannel`, `X-User-ID` is the `id` of the acting `MarketplaceChannel`; the identity check on marketplace order placement compares the order's `marketplace_channel_id` field to `X-User-ID`.

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

List endpoints accept two query parameters: `limit`, the maximum number of items to return, which defaults to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of items to skip, which defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, ties broken by `id`. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the system — hold-time expiry of cooked batches, promise expiry of ready orders, and production-window cutoff — is driven by a server-side logical clock, never by wall-clock time. At startup, before any clock operation has been performed, the logical clock reads exactly `2026-09-01T00:00:00Z`; the implementation must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` advances the clock by submitting a target instant `to_iso8601`; the response echoes the new clock value as `current_utc`. Advancing the clock fires three families of automatic transitions: any `ACTIVE` batch whose `discard_at` has been reached becomes `EXPIRED`; any `READY` order whose promise time plus forty-five minutes has passed without pickup becomes `EXPIRED`; and any `OPEN` production window whose `interval_start` has been reached moves to `CUTOFF`. A store's `current_business_day` is the ISO date of the logical clock, and it rolls forward only at day close.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation, used for optimistic concurrency control.

All fifteen resource types in this domain — stores, ingredients, batches, menu items, recipe components, marketplace channels, production windows, orders, order lines, accuracy verifications, staffing deployments, suppression events, waste events, and day-close records — carry these common fields. Any mutation that recomputes a derived field (for example, re-evaluating a store's `throttle_state`, decrementing a batch's `grams_remaining`, or cascading a menu item's `suppression_state`) is a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values are integer cents; no fractional cents ever appear in stored fields or API responses. Where a computation produces a fractional cent — a per-line marketplace gross, a per-line commission, a menu item's theoretical cost, a waste event's cost, or a food-cost variance ratio — the result is rounded half-up to the nearest integer at the point the scaffold of the computation pins it, and only then summed or stored. Grams, headcounts, entree counts, and interval loads are integers throughout. Unit-cost fields such as `unit_cost_cents_per_gram` and fraction-valued configuration fields such as `overage_threshold_pct`, `markup_pct`, `commission_pct`, `marketplace_commission_pct`, and the predicted mix percentages preserve their input precision as numbers.

### 2.7. Nested Resource Retrieval and Validation Order

The API enforces strict left-to-right validation of path identifiers on nested routes. When a path contains multiple resource identifiers (for example, a store followed by an order), the server resolves each identifier in order and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve — `ERR_STORE_NOT_FOUND` for a store segment, then `ERR_ORDER_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_SUPPRESSION_EVENT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, or `ERR_INGREDIENT_NOT_FOUND` as appropriate — before any business rule is evaluated. Beyond existence, every endpoint applies its checks in a fixed priority order: first the presence and validity of the authentication headers, then role permission for the endpoint, then path-resource existence left to right, then the optimistic-concurrency version check where one applies, then the target entity's state precondition for the requested transition, and only then the business rules specific to the operation (accuracy gating, suppression screening, ingredient sufficiency, window capacity, deployment consistency, segregation of duties, day-close preconditions, and marketplace reference validity, in that relative order where several apply to the same endpoint). A request payload with a missing required field, a wrong-typed value, or an enum value outside its declared set is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent store. Creating a staffing deployment for a store requires a non-optional `expected_store_version` field in the request body carrying the client's last observed `version` of that store; if the store's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Closing the business day likewise requires `expected_store_version` matching the store's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field. Both guarded operations increment the store's `version` by one on success.

### 2.9. Production Windows, Interval Loads, and Throttle Bands

Digital demand is paced against **production windows**: contiguous half-open intervals of `pacing_interval_minutes` length belonging to a store. The window whose `interval_end` is still in the future and which opens earliest is the store's *current window*. Each store exposes two live load counters — `digital_interval_load` and `instore_interval_load` — counting committed but not yet picked-up entrees on each line for the current window, alongside the window's own `digital_committed`, `instore_committed`, and `digital_completed` counters. When no `OPEN` window exists, both store counters read zero.

The store's `throttle_state` is a derived projection over the current window's committed digital load, recomputed on every mutation of that load (order acceptance, pickup, expiry, or cancellation). It takes exactly three values. When no `OPEN` window exists, the state is `OPEN`. When the current window's `digital_committed` is at or above the store's `digital_line_capacity_per_interval`, the state is `CLOSED`. When the committed load is below capacity but at or above the threshold formed by rounding the product of `overage_threshold_pct` and `digital_line_capacity_per_interval` up to a whole number of entrees, the state is `THROTTLED`. Below that threshold the state is `OPEN`. The boundary is inclusive on both bands: a committed load exactly equal to the threshold is `THROTTLED`, and a load exactly equal to capacity is `CLOSED`. Because the capacity check is evaluated first, a store whose threshold rounds up to exactly its capacity simply has a collapsed `THROTTLED` band and moves directly between `OPEN` and `CLOSED`. Crucially, `THROTTLED` and `CLOSED` describe only the current window: throttling pushes a new digital order's `promised_at` out by one interval into the next open window, and a full current window overflows slotting to later open windows. An order is refused with `ERR_LINE_CAPACITY_EXCEEDED` only when no open window has room for it. As pickups, expiries, and cancellations release committed entrees, the state relaxes back through the same bands — from `CLOSED` to `THROTTLED` when the load returns to the band between the threshold and capacity, and to `OPEN` once it drops below the threshold; a single large order may also jump the current window directly from `OPEN` to `CLOSED`.

### 2.10. Roles and Segregation of Duties

Deployment authoring is deliberately split across two roles and two people. A `StoreManager` creates and publishes staffing deployments; only a `GeneralManager` may lock a published deployment, and the locking user's `X-User-ID` must differ from the publishing user's `X-User-ID`. A lock attempted by the same user who published the deployment is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Provisioning Stores, Ingredients, and Batches

A `PlatformAdmin` onboards a store by supplying its `store_code` (a human-readable code unique per tenant), a display `name`, and the pacing configuration: `digital_line_capacity_per_interval` and `instore_line_capacity_per_interval` (the maximum entrees each make-line can assemble in one pacing window), `pacing_interval_minutes` (the length of one window), the `overage_threshold_pct` fraction of digital capacity at which throttling engages, and `marketplace_commission_pct`, the fraction of marketplace gross the store expects to pay in commission. An optional `forecast_day_cents` seeds the day's revenue forecast and defaults to zero. A new store starts with `throttle_state` `OPEN`, both interval loads at zero, `theoretical_food_cost_cents` and `actual_food_cost_cents` at zero, `food_cost_variance_bps` at zero, and `current_business_day` set to the logical clock's date. The quoted minutes from `placed_at` to `promised_at` for in-store orders, `instore_promise_minutes`, defaults to 15 and must be an integer of at least one when supplied. The capacity fields `digital_line_capacity_per_interval`, `instore_line_capacity_per_interval`, and `pacing_interval_minutes` must each be integers of at least one. `forecast_day_cents`, when supplied, must be an integer. No uniqueness constraint is enforced on `store_code`.

Ingredients are provisioned centrally with a stable `ingredient_code`, a `display_name`, the theoretical `unit_cost_cents_per_gram`, the start-of-day target `par_level_grams`, the `hold_time_minutes` a cooked batch may be served before mandatory discard, and the standard `batch_size_grams` for a cook. `par_level_grams`, `hold_time_minutes`, and `batch_size_grams` are integers of at least zero. A freshly registered ingredient has `on_hand_grams` zero and `shortage_state` `STOCKED`.

Cooking is how stock enters the system. A `LineWorker` or `StoreManager` cooks a batch against an ingredient, naming the `store_id` doing the cooking, the `cooked_at` timestamp, and the `grams_cooked`, which must be an integer of at least one. The new batch starts `ACTIVE` with `grams_remaining` initialized to `grams_cooked`, a `discard_at` computed as the `cooked_at` instant plus the ingredient's `hold_time_minutes`, and `discarded_grams` at zero; the ingredient's `on_hand_grams` increases by `grams_cooked`. Cooking is also a recovery trigger: the ingredient's shortage state is re-evaluated immediately, so a cook that restores on-hand to at least half of par resolves its shortage-driven suppression events per §3.7. Batches may be listed per ingredient or across the system filtered by `ingredient_id`, `store_id`, or `status`.

### 3.2. The Menu, Recipes, and Marketplace Pricing

A `StoreManager` builds the store's menu item by item. Each menu item carries an `item_code`, a customer-facing `display_name`, a `base_price_cents` (an integer of at least zero) that serves both walk-in and first-party digital guests, and an `is_digital_eligible` flag (defaulting to true) controlling whether the item may be sold on the digital make-line. A new item's `suppression_state` is `SELLABLE` and its `theoretical_cost_cents` is zero until its recipe is defined.

Recipes attach to menu items as recipe components, each pairing an `ingredient_id` with the `standard_grams` portioned per entree, an integer of at least one. Adding a component immediately recomputes the item's `theoretical_cost_cents` as the sum, over all of its components, of each component's `standard_grams` multiplied by the ingredient's `unit_cost_cents_per_gram`, with the total rounded half-up to a whole cent once per item (the per-component products are not individually rounded). Components can be listed per menu item or across the system filtered by `menu_item_id` or `ingredient_id`.

Marketplace channels are provisioned by a `PlatformAdmin` with a `channel_code`, a `markup_pct` applied over `base_price_cents` to form the marketplace menu price, a `commission_pct` taken by the marketplace on gross marketplace sales, and an `active` flag (defaulting to true) controlling whether the channel currently injects orders. A negative `markup_pct` or `commission_pct` is rejected with `ERR_INVALID_REQUEST`; there is no upper bound, so a zero-commission or zero-markup channel is permitted. Pricing follows two pinned variants. For a marketplace order, each order line's gross unit price is the item's `base_price_cents` multiplied by one plus the channel's `markup_pct`, rounded half-up to a whole cent and then multiplied by the line's quantity; the line's commission is the line gross multiplied by the channel's `commission_pct`, again rounded half-up to a whole cent *per line before any summing*. The order's `subtotal_cents` is the sum of the per-line grosses, its `commission_cents` the sum of the per-line commissions, and its `net_revenue_cents` the subtotal minus the commission. For first-party digital and in-store orders there is no markup and no commission: the line's `unit_price_cents` is simply `base_price_cents`, `commission_cents` is zero, and `net_revenue_cents` equals `subtotal_cents` — so the same basket yields a different net revenue under the two variants.

### 3.3. Production Windows and Promise Slotting

A `StoreManager` or `PlatformAdmin` opens a production window for a store by giving its `interval_start` (inclusive) and `interval_end` (exclusive); the end must be exactly the store's `pacing_interval_minutes` after the start, and the new interval must not overlap any existing window for the store — half-open adjacency, where one window's start equals another's end, is permitted, while a true overlap is rejected with `ERR_WINDOW_OVERLAP`. At creation the window snapshots the store's `digital_line_capacity_per_interval` into its own `digital_capacity`, zeroes `digital_committed`, `digital_completed`, and `instore_committed`, and enters the `OPEN` status — unless its `interval_start` is already at or before the logical clock, in which case it is created directly in `CUTOFF`. When the logical clock reaches a window's `interval_start`, the window moves from `OPEN` to `CUTOFF`: it accepts no further commitments, and any late digital order that would have slotted there re-slots into the next open window. A `CUTOFF` window becomes `SETTLED` at day close, or when the logical clock reaches its `interval_end` and all of its orders have resolved (an order counts as unresolved for this purpose while its `fulfillment_status` is `PLACED`, `ACCEPTED`, `IN_PRODUCTION`, or `READY`); settlement reconciles `digital_completed` against `digital_committed`, with any shortfall recorded on the day-close record.

Digital and marketplace orders are slotted into windows by a waterfall. The server walks the store's windows in ascending `interval_start` order (ties on `created_at`, then `id`) — never primarily by identifier — and considers a window eligible when it is `OPEN`, its `interval_end` is after the order's `placed_at`, and its `digital_committed` plus the order's `entree_count` does not exceed its `digital_capacity`. When the store's `throttle_state` is `THROTTLED` or `CLOSED`, the current window is skipped — this is the quote-extension variant of throttling — and the walk continues to the next eligible open window. The first eligible window in start order wins, and the order's `promised_at` is stamped as that window's `interval_end`. If no open window is eligible, placement is rejected with `ERR_LINE_CAPACITY_EXCEEDED`. In-store orders do not participate in the waterfall: their `promised_at` is `placed_at` plus the store's `instore_promise_minutes`, but their entrees still count against the in-store line, and an in-store order whose `entree_count` would push the current window's `instore_committed` above `instore_line_capacity_per_interval` is likewise rejected with `ERR_LINE_CAPACITY_EXCEEDED`. When no current window exists, an in-store order is accepted without any window commitment and its `production_window_id` is null; the store's interval loads are unaffected, and its entrees are released nowhere on pickup or cancellation.

### 3.4. Placing an Order: The Acceptance Chain

Orders enter through three channels, recorded on the order's `channel` field: `FIRST_PARTY_DIGITAL`, `IN_STORE`, or `MARKETPLACE`; any other channel value is rejected with `ERR_INVALID_REQUEST`, and `lines` must be a non-empty array. A `LineWorker` or `StoreManager` may place an order (a `LineWorker` only on the in-store channel — a `LineWorker` attempting the digital or marketplace channel is rejected with `ERR_FORBIDDEN_ROLE` (403)); a `MarketplaceChannel` injects marketplace orders under its own identity and may place only `MARKETPLACE`-channel orders — a `MarketplaceChannel` attempting to place an order on any other channel is rejected with `ERR_FORBIDDEN_ROLE` (403) — so a marketplace order's `marketplace_channel_id` must equal the caller's `X-User-ID` when the caller is a `MarketplaceChannel` (a `StoreManager` may place a `MARKETPLACE` order naming any channel id) — a `marketplace_channel_id` that does not resolve is `ERR_CHANNEL_NOT_FOUND`. Marketplace orders must additionally carry an `external_order_ref`, the marketplace-provided reference, and both fields are required if and only if the channel is `MARKETPLACE`; a missing `marketplace_channel_id` or `external_order_ref` on a marketplace order is rejected with `ERR_MARKETPLACE_REFERENCE_INVALID`, as is the presence of either field on a non-marketplace order. The referenced channel must be `active`, and the `external_order_ref` must be unique within that channel; a violation is rejected with `ERR_MARKETPLACE_REFERENCE_INVALID`.

The placement payload names the `channel`, the optional `marketplace_channel_id` and `external_order_ref`, and a `lines` array. Each line names a `menu_item_id`, a `quantity` of at least one, and an optional `customizations` list (defaulting to empty), whose entries each name an `ingredient_id`, an `action` of `EXTRA`, `LIGHT`, `NONE`, or `SUB`, and — for substitutions — a `sub_ingredient_id` (required when the action is `SUB`; a `SUB` customization without one is rejected with `ERR_INVALID_REQUEST`). Every line's `menu_item_id` must resolve to an item of the target store, otherwise `ERR_MENU_ITEM_NOT_FOUND`. Before the acceptance chain runs, a digital or marketplace order is also screened for digital eligibility: any line whose item is not `is_digital_eligible` is rejected with `ERR_ITEM_SUPPRESSED`. Once persisted, every line traces back to its owning order through its `order_id` field, and the order itself records the store it belongs to through its `store_id`. The order's `placed_at` is stamped from the logical clock, its `line` is assigned at acceptance — `DIGITAL` for first-party digital and marketplace orders, `IN_STORE` for in-store orders — and each line is minted a `lid_label_code`, the short code printed on the bowl's lid for later accuracy verification, and each line's `accuracy_check` begins `PENDING`.

Acceptance runs a fixed chain of checks, in order: suppression screening first, then ingredient sufficiency, then window capacity. Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`. Then, for every component of every line, the grams available across the ingredient's `ACTIVE` batches must cover the requirement, with an `EXTRA` customization doubling the standard grams for that component, a `LIGHT` customization halving them (integer floor), a `NONE` customization zeroing them, and a `SUB` customization moving the full standard grams to the named `sub_ingredient_id`; a shortfall is rejected with `ERR_INSUFFICIENT_INGREDIENT`. Finally the capacity waterfall of §3.3 must find the order a home, failing with `ERR_LINE_CAPACITY_EXCEEDED`.

On acceptance the order's `fulfillment_status` moves from the transient `PLACED` straight to `ACCEPTED`, `payment_status` is `AUTHORIZED`, and `accuracy_status` begins `UNVERIFIED`. The selected window's `digital_committed` (or `instore_committed` for in-store orders) and the store's matching interval load each increase by `entree_count`, and the throttle band is re-evaluated. Consumption follows strict first-in-first-out: grams are drawn from the ingredient's `ACTIVE` batches in ascending `cooked_at` order, with ascending `created_at` as the tie-break — never by identifier — taking from each batch the smaller of what is needed and that batch's `grams_remaining` until each line's required grams are satisfied. Each draw decrements the batch's `grams_remaining` and the ingredient's `on_hand_grams`; a batch drained to zero transitions from `ACTIVE` to `DEPLETED`, which may trip the shortage cascade of §3.7. The order's pricing fields are computed per §3.2, its `entree_count` is the sum of the line quantities, its `theoretical_cost_cents` is the sum, over the lines, of each menu item's `theoretical_cost_cents` multiplied by the line quantity, and its `production_window_id` records the window it was committed into.

### 3.5. Working the Order: Production, Accuracy, Ready, Pickup

Production begins when a `LineWorker` starts an `ACCEPTED` order, moving `fulfillment_status` from `ACCEPTED` to `IN_PRODUCTION`. Two preconditions gate the start: the order must currently be `ACCEPTED` (any other state is `ERR_INVALID_STATE`, and any terminal state is `ERR_ALREADY_TERMINAL`), and a staffing deployment covering the store for a `shift_date` equal to the store's `current_business_day` must exist in `PUBLISHED` or `LOCKED` status — without one the start is refused with `ERR_DEPLOYMENT_MISSING` (HTTP 409; the gate is per store and day and does not consider the order's line). Starting production captures payment, moving `payment_status` from `AUTHORIZED` to `CAPTURED`.

Before an in-production order may be marked ready, every one of its lines must pass accuracy verification. A `LineWorker` submits a verification pass with per-line match results (`line_results`); the server counts the order's lines into `checked_components`, counts the lines whose checked contents diverge from the standard recipe as modified by their customizations into `mismatched_lines`, records the acting worker's `X-User-ID` as `verified_by`, and stamps `created_at_note` with the pass ordinal in the form `pass-N`, where N counts that order's verification passes including the new one. Each `line_results` entry may identify its order line by the line's `id` or by its `menu_item_id` (the keys `line_id`, `order_line_id`, and `id` are also accepted); instead of identifying entries, the caller may submit a positional array of booleans matching the order's lines in `created_at` order, where `false` marks that line as mismatched. An entry reporting a mismatch that identifies no line of the order still makes the pass `FAIL` and is counted in `mismatched_lines`, but no specific line's `accuracy_check` is flagged by it. When no line mismatches, the pass `result` is `PASS`, every line's `accuracy_check` becomes `MATCHED`, and the order's `accuracy_status` becomes `VERIFIED`. When at least one line mismatches, the result is `FAIL`, the offending lines' `accuracy_check` becomes `MISMATCHED` while lines not flagged become `MATCHED`, and the order's `accuracy_status` becomes `MISMATCHED`; the order remains `IN_PRODUCTION`, and after rework it may be verified again — the accuracy axis is cyclic, so `MISMATCHED` may legitimately return to `VERIFIED` on a later pass. A `LineWorker` may then mark the order ready, moving it from `IN_PRODUCTION` to `READY`, only when every line's `accuracy_check` is `MATCHED` following at least one `PASS` verification; otherwise the transition is rejected with `ERR_ACCURACY_UNVERIFIED`. Marking ready surfaces the lid labels for the handoff shelf.

Pickup, performed by a `LineWorker`, moves a `READY` order to `PICKED_UP`. Pickup releases the order's `entree_count` from the store's matching interval load (re-evaluating the throttle band), adds the order's `theoretical_cost_cents` to the store's `theoretical_food_cost_cents`, and values the grams the order actually consumed at unit cost into `actual_food_cost_cents` (each ingredient's consumed grams are multiplied by its `unit_cost_cents_per_gram` and rounded half-up per ingredient before summing). For a digital order, pickup also increases its production window's `digital_completed` by `entree_count`. If a ready order is never collected, the system expires it once the logical clock passes `promised_at` plus forty-five minutes: `fulfillment_status` moves from `READY` to `EXPIRED`, the captured payment is refunded (`CAPTURED` to `REFUNDED`), and the store's interval load is released.

### 3.6. Cancellation and Compensation

A `StoreManager` may cancel an order while its `fulfillment_status` is `PLACED` or `ACCEPTED`, moving it to the terminal `CANCELLED` state; from any other state the request is rejected with `ERR_INVALID_STATE`, and from a terminal state (`PICKED_UP`, `CANCELLED`, or `EXPIRED`) with `ERR_ALREADY_TERMINAL`. Cancellation is fully compensating: the committed entrees are released back to the production window's committed counter and to the store's interval load, the throttle band is re-evaluated, the grams the order consumed are restored to the newest `ACTIVE` batch of each ingredient (the batch with the latest `created_at`, ties broken by the latest `cooked_at`) — when no `ACTIVE` batch exists for an ingredient, its `on_hand_grams` is still restored without crediting any batch — suppression states are re-evaluated against the restored stock, and `payment_status` moves to `VOIDED`.

### 3.7. Shortage, Suppression Cascade, and Waste

Every ingredient's `shortage_state` is derived from `on_hand_grams` against its `par_level_grams`. While on-hand is at least half of par the ingredient is `STOCKED`. Once on-hand falls below half of par but stays at or above a quarter of par, the ingredient is `LOW`, and the cascade fires: for every menu item whose recipe includes the ingredient, if the item `is_digital_eligible` the system creates a `SuppressionEvent` with `scope` `MARKETPLACE` and `cause` `SHORTAGE`, and the item's `suppression_state` becomes `SUPPRESSED_MARKETPLACE`. (A suppression event's `cause` is one of `SHORTAGE`, `MANUAL`, or `RESTORED`; `RESTORED` marks an event raised as part of a recovery bookkeeping pass.) If on-hand falls below a quarter of par the ingredient is `DEPLETED`: every `ACTIVE` shortage-driven suppression event for the ingredient escalates to `scope` `ALL`, and affected items become `SUPPRESSED_ALL`. A straight drop from `STOCKED` to `DEPLETED` may leave a digital-eligible item with no prior event to escalate; in that case a new `ACTIVE` suppression event with `scope` `ALL` and `cause` `SHORTAGE` is created for the item so that it still becomes `SUPPRESSED_ALL`. An item's `suppression_state` is recomputed from the `ACTIVE` events covering it: it is `SUPPRESSED_ALL` when any active event has scope `ALL` or when scopes `MARKETPLACE` and `DIGITAL` are both present, `SUPPRESSED_MARKETPLACE` when only `MARKETPLACE` is present, `SUPPRESSED_DIGITAL` when only `DIGITAL` is present, and `SELLABLE` when no active event covers it. The cascade evaluates `on_hand_grams` first and then propagates to items in ascending `item_code` order — deterministically, never by identifier. Suppression events are born `ACTIVE`; recovery is also automatic — when a new batch cook pushes `on_hand_grams` back to at least half of par, the ingredient's `ACTIVE` shortage-caused events resolve to `RESOLVED`, and each item's `suppression_state` is recomputed, returning to `SELLABLE` when no other active event covers it. A `StoreManager` may also resolve a suppression event manually, but only one with `cause` `MANUAL`; attempting to manually resolve a shortage-caused event is rejected with `ERR_MANUAL_SUPPRESSION_ONLY`, and attempting to resolve an already-`RESOLVED` event is rejected with `ERR_ALREADY_TERMINAL`. Manual resolution likewise recomputes the covered item's `suppression_state`.

Waste is recorded by a `LineWorker` or `StoreManager` against a specific batch, naming the `ingredient_batch_id`, the `grams` wasted (an integer of at least one), and a `reason` of `HOLD_TIME_EXPIRED`, `CONTAMINATION`, or `OVERPRODUCTION`. The event's `cost_cents` is the wasted grams multiplied by the ingredient's `unit_cost_cents_per_gram`, rounded half-up; the ingredient's `on_hand_grams` and the batch's `grams_remaining` fall by the wasted amount, the batch's `discarded_grams` grows by the same, and the store's `actual_food_cost_cents` absorbs `cost_cents`. Recording waste in excess of the batch's `grams_remaining` is rejected with `ERR_WASTE_EXCEEDS_BATCH`; this check precedes the batch-state check, so waste in excess of the remaining grams is rejected with `ERR_WASTE_EXCEEDS_BATCH` even when the batch is already in a terminal state. A batch in `DEPLETED`, `EXPIRED`, or `WASTED` status is rejected with `ERR_ALREADY_TERMINAL`, and a batch in any other non-`ACTIVE` status with `ERR_INVALID_STATE`. A partial waste leaves the batch `ACTIVE`; a full-batch waste — grams equal to `grams_remaining`, with a `CONTAMINATION` or `OVERPRODUCTION` reason — transitions the batch from `ACTIVE` to `WASTED`. Separately, when the logical clock reaches an `ACTIVE` batch's `discard_at` with grams still remaining, the batch expires: a waste event is created with reason `HOLD_TIME_EXPIRED` covering the full `grams_remaining`, `on_hand_grams` falls accordingly, the expired grams at unit cost post to `actual_food_cost_cents`, `discarded_grams` absorbs the former remainder, `grams_remaining` is set to zero, and the batch becomes `EXPIRED`. Either path may cross a shortage threshold and fire the cascade above.

### 3.8. Staffing Deployments

A `StoreManager` drafts a staffing deployment for a store by naming the `shift_date` it covers, the `predicted_digital_mix_pct` and `predicted_instore_mix_pct` fractions of transactions expected on each line, the total `headcount` scheduled, and — because creation is concurrency-guarded per §2.8 — the `expected_store_version`. The two mix fractions must sum to one (within a tolerance of one part in a billion), the headcount must be at least two, and the `shift_date` must not be earlier than the logical clock's date (a `shift_date` equal to the clock's date is permitted); a violation is rejected with `ERR_INVALID_DEPLOYMENT`. Creation increments the store's `version` by one and supersedes any existing `DRAFT` deployment for the same `shift_date`, moving it to `SUPERSEDED`. The deployment starts in `DRAFT`, with `digital_headcount` and `instore_headcount` computed at creation exactly as at publish.

Publishing, also by a `StoreManager`, moves a deployment from `DRAFT` to `PUBLISHED` under the same consistency rules — the mix fractions summing to one and a headcount of at least two — and computes the line split: `digital_headcount` is the `headcount` multiplied by `predicted_digital_mix_pct` rounded half-up to a whole person, and `instore_headcount` is the remainder of `headcount` once the digital share is removed, so the two always sum exactly to the scheduled total. Publishing also supersedes whatever deployment was previously `PUBLISHED` for the same `shift_date`, moving it to `SUPERSEDED`. Publishing or locking a deployment already in `LOCKED` or `SUPERSEDED` is rejected with `ERR_ALREADY_TERMINAL`; publishing a deployment not in `DRAFT` (or locking one not in `PUBLISHED`) is rejected with `ERR_INVALID_STATE`. Finally, a `GeneralManager` — necessarily a different person than the publisher, per the segregation-of-duties rule of §2.10 — locks a `PUBLISHED` deployment, moving it to `LOCKED`; a same-user lock is refused with `ERR_SEGREGATION_OF_DUTIES`. Both `LOCKED` and `SUPERSEDED` are terminal.

### 3.9. Day Close and Food-Cost Variance

The store's food-cost position is tracked continuously. `theoretical_food_cost_cents` accumulates, over picked-up orders, the sum across their lines of each menu item's `theoretical_cost_cents` multiplied by the line quantity. `actual_food_cost_cents` accumulates the grams actually consumed by picked-up orders valued at unit cost, plus every waste event's `cost_cents`, plus the expired grams of every expired batch valued at unit cost. The store's `food_cost_variance_bps` is the actual minus the theoretical, divided by the theoretical (or by one if the theoretical is zero), scaled by ten thousand, and rounded half-up to a whole basis point. Read before close, the variance is provisional — it includes unsettled waste; closing the day freezes the snapshot, and waste recorded afterward posts to the next day.

Day close is a `GeneralManager` operation guarded by `expected_store_version` per §2.8. The close is refused with `ERR_DAY_NOT_CLOSABLE` unless no production window of the store remains `OPEN` and no order remains in `PLACED`, `ACCEPTED`, or `IN_PRODUCTION`. A successful close settles any remaining `CUTOFF` windows (moving them to `SETTLED` and reconciling each window's `digital_completed` against `digital_committed`, with shortfalls recorded on the close record), persists a `DayClose` — already in `CLOSED` status at creation — capturing the `business_day` being closed, the `orders_accepted` count (all orders recorded for the store) and the `orders_completed` count (orders in `PICKED_UP`) for the day, the `digital_net_revenue_cents` across digital and marketplace orders and the `instore_net_revenue_cents` across in-store orders, and a snapshot of `food_cost_variance_bps` at close. The store's `version` increments by one, and the store's `current_business_day` advances to the next day.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or advance its state return `200 OK`. All endpoints are mounted under `/api/v1`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/api/v1/stores` | Create a store with dual make-line capacities and pacing config | PlatformAdmin |
| GET | `/api/v1/stores` | List stores | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/stores/{storeId}` | Get one store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/ingredients` | Register an ingredient with par level, hold time, unit cost, batch size | PlatformAdmin |
| GET | `/api/v1/ingredients` | List ingredients | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/ingredients/{ingredientId}` | Get one ingredient | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/ingredients/{ingredientId}/batches` | Cook a batch; starts the hold-time clock | LineWorker, StoreManager |
| GET | `/api/v1/ingredients/{ingredientId}/batches` | List batches for an ingredient | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/batches/{batchId}` | Get one batch | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/batches` | List batches filtered by ingredient or store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/menu-items` | Create a menu item for a store | StoreManager |
| GET | `/api/v1/stores/{storeId}/menu-items` | List menu items for a store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/menu-items/{menuItemId}` | Get one menu item | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/menu-items` | List menu items filtered by store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/menu-items/{menuItemId}/recipe-components` | Add a recipe component; recomputes theoretical cost | StoreManager |
| GET | `/api/v1/menu-items/{menuItemId}/recipe-components` | List recipe components of a menu item | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/recipe-components` | List recipe components filtered by menu item or ingredient | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/recipe-components/{componentId}` | Get one recipe component | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/marketplace-channels` | Register a third-party marketplace with markup and commission | PlatformAdmin |
| GET | `/api/v1/marketplace-channels` | List marketplace channels | PlatformAdmin, StoreManager, GeneralManager |
| GET | `/api/v1/marketplace-channels/{channelId}` | Get one marketplace channel | PlatformAdmin, StoreManager, GeneralManager |
| POST | `/api/v1/stores/{storeId}/production-windows` | Open a pacing window for the store | StoreManager, PlatformAdmin |
| GET | `/api/v1/stores/{storeId}/production-windows` | List production windows | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/production-windows/{windowId}` | Get one window | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/production-windows` | List production windows filtered by store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/orders` | Place an order; runs the full acceptance chain | LineWorker, StoreManager, MarketplaceChannel |
| GET | `/api/v1/stores/{storeId}/orders` | List orders for a store with filters | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/orders/{orderId}` | Get one order | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/orders` | List orders filtered by store, channel, marketplace channel, or window | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/orders/{orderId}/lines` | List an order's lines | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/order-lines` | List order lines filtered by order or menu item | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/order-lines/{lineId}` | Get one order line | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/orders/{orderId}/start-production` | Move an accepted order into production; captures payment | LineWorker |
| POST | `/api/v1/stores/{storeId}/orders/{orderId}/verify-accuracy` | Submit an accuracy verification pass with per-line results | LineWorker |
| POST | `/api/v1/stores/{storeId}/orders/{orderId}/mark-ready` | Mark an in-production order ready; gated on accuracy | LineWorker |
| POST | `/api/v1/stores/{storeId}/orders/{orderId}/pickup` | Record pickup; releases interval load and posts theoretical cost | LineWorker |
| POST | `/api/v1/stores/{storeId}/orders/{orderId}/cancel` | Cancel a placed or accepted order; compensates capacity and inventory | StoreManager |
| GET | `/api/v1/orders/{orderId}/verifications` | List accuracy verifications for an order | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/verifications` | List verifications filtered by order | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/verifications/{verificationId}` | Get one accuracy verification | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/staffing-deployments` | Create a staffing deployment (OCC-guarded); supersedes same-day drafts | StoreManager |
| GET | `/api/v1/stores/{storeId}/staffing-deployments` | List deployments for a store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/staffing-deployments/{deploymentId}` | Get one deployment | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/staffing-deployments` | List deployments filtered by store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/staffing-deployments/{deploymentId}/publish` | Publish a draft deployment; supersedes the prior published one | StoreManager |
| POST | `/api/v1/stores/{storeId}/staffing-deployments/{deploymentId}/lock` | Lock a published deployment (locker differs from publisher) | GeneralManager |
| GET | `/api/v1/stores/{storeId}/suppression-events` | List suppression events for a store | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/suppression-events/{eventId}` | Get one suppression event | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| GET | `/api/v1/suppression-events` | List suppression events filtered by store, menu item, or ingredient | PlatformAdmin, StoreManager, GeneralManager, LineWorker |
| POST | `/api/v1/stores/{storeId}/suppression-events/{eventId}/resolve` | Manually resolve a manual-scope suppression event | StoreManager |
| POST | `/api/v1/stores/{storeId}/waste-events` | Record waste against a batch | LineWorker, StoreManager |
| GET | `/api/v1/stores/{storeId}/waste-events` | List waste events for a store | PlatformAdmin, StoreManager, GeneralManager |
| GET | `/api/v1/waste-events` | List waste events filtered by store or batch | PlatformAdmin, StoreManager, GeneralManager |
| GET | `/api/v1/waste-events/{wasteEventId}` | Get one waste event | PlatformAdmin, StoreManager, GeneralManager |
| POST | `/api/v1/stores/{storeId}/day-close` | Close the business day (OCC-guarded); freezes variance and advances the day | GeneralManager |
| GET | `/health` | Liveness probe, mounted outside `/api/v1`; returns `{"status": "ok"}` with no authentication | (none) |
| GET | `/api/v1/stores/{storeId}/day-closes` | List day-close records for a store | PlatformAdmin, StoreManager, GeneralManager |
| GET | `/api/v1/day-closes` | List day-close records filtered by store | PlatformAdmin, StoreManager, GeneralManager |
| GET | `/api/v1/day-closes/{dayCloseId}` | Get one day-close record | PlatformAdmin, StoreManager, GeneralManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_DEPLOYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPRESSION_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CHANNEL_NOT_FOUND` | 404 Not Found |
| `ERR_INGREDIENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_ACCURACY_UNVERIFIED` | 409 Conflict |
| `ERR_ITEM_SUPPRESSED` | 409 Conflict |
| `ERR_INSUFFICIENT_INGREDIENT` | 409 Conflict |
| `ERR_LINE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_DEPLOYMENT` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DAY_NOT_CLOSABLE` | 409 Conflict |
| `ERR_MARKETPLACE_REFERENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_WASTE_EXCEEDS_BATCH` | 422 Unprocessable Entity |
| `ERR_MANUAL_SUPPRESSION_ONLY` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DEPLOYMENT_MISSING` | 409 Conflict |
| `ERR_NOT_FOUND` | 404 Not Found |

`ERR_DEPLOYMENT_MISSING` gates start-production when no usable staffing deployment exists (§3.5). `ERR_NOT_FOUND` is the generic 404 for resources without a dedicated catalog entry — production windows, recipe components, order lines, accuracy verifications, waste events, and day-close records — and for requests whose path matches no route.
