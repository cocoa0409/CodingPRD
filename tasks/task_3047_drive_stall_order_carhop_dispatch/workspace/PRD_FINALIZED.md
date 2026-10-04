# Drive-In Stall Order & Carhop Dispatch API — Product Requirements Document

## 1. Introduction

Drive-in restaurants live and die by the stall. Unlike a single-window quick-service queue, a drive-in must take orders from dozens of individual stalls — over aging intercom hardware or through a mobile app check-in — sequence kitchen preparation against a rush that swells and breaks with the weather, and route trays to cars through carhops who can only carry so much at once. This document specifies the Drive-In Stall Order & Carhop Dispatch API: a stall-based ordering and fulfillment system in which every order is anchored either to a physical stall, a patio table, or the drive-thru lane, and in which delivery is performed by carhops on multi-order tray runs rather than a single pickup window.

The system governs the full arc of a guest visit: stall check-in, order drafting with deep drink and slush customization, combination pricing and happy-hour offers pinned to the moment of check-in, payment authorization and capture with tip handling and store-credit wallets, kitchen admission under a rush cap, dispatch selection of both the carhop and the orders that make up a run, in-sequence delivery against per-channel service targets, and post-visit tip settlement. It also models the operational realities of the format — equipment faults that kill intercoms and menu boards, weather advisories that close the patio or push the lot to curbside-only posture, and stale-check-in expiry as the rush window advances. Latency is measured per order from placement to delivery, and rolled up into location-level timing metrics for managers and corporate operations.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted beneath the `/locations` prefix where a location scope applies.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `ShiftManager`, `KitchenStaff`, `Carhop`, and `Customer`. A request missing a role header, carrying an undeclared role value, or — for entity-backed roles — missing the user identifier is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Carhop`, `X-User-ID` is the `id` of the acting `Carhop`; ownership checks on any resource that references a `Carhop` — such as departing a delivery run — compare the resource's `carhop_id` to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer`, such as an order's `customer_id`, compare the foreign-key field to `X-User-ID`. The remaining three roles are opaque operator identities. When `X-User-Role` is `PlatformAdmin`, `ShiftManager`, or `KitchenStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Role capabilities in brief: a `PlatformAdmin` is the corporate operator who configures locations, the menu, and customization options, and can do everything a `ShiftManager` can; a `ShiftManager` runs the shift — dispatch, refunds, wallet adjustments, fault resolution, rush advancement; `KitchenStaff` advances the preparation pipeline only; a `Carhop` runs trays to stalls, reports equipment faults, and captures payment at the stall; a `Customer` is an app user or stall guest who checks in, builds and places orders, and pays.

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

All error API responses — every non-2xx response, including an unmatched path or method on this API — follow this standard envelope format:

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in this system — Location, MenuItem, CustomizationOption, Customer, Stall, Carhop, Order, OrderLine, Offer, DeliveryRun, TipRecord, EquipmentFault, and ServiceTargetProfile — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation; it is the basis for optimistic concurrency control.

Any change to a resource — including recomputation of derived fields such as a location's `stalls_available` or a carhop's `active_run_load` — counts as a mutation of that resource, refreshing `updated_at` and incrementing `version`, except where a specific workflow states otherwise.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents — prices, discounts, taxes, tips, wallet balances, and tender totals are never fractional. Wherever a calculation produces a fractional cent, the value is rounded half-up to the nearest cent at the calculation's pinned rounding points; the rounding order is fixed per calculation and described with the workflow that performs it. The one non-integer figure in the system is the on-time rate reported by the metrics rollup, which is expressed as a number with four decimal places.

### 2.6. Logical Clock, Timezones, and Offer Windows

The server maintains a logical clock that governs every timestamp the system writes. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `current_utc` instant; this endpoint is restricted to `PlatformAdmin`.

Each location declares an IANA `timezone` (for example, `America/Chicago`). Offer windows are written as local wall-clock times — `window_start_local` inclusive and `window_end_local` exclusive, each in `HH:MM` form — and are always evaluated against the order's check-in instant converted into the location's timezone. A window whose end equals its start runs all day, and a window may wrap across midnight. Offer applicability never depends on when the customer happened to tap "place"; it is pinned to check-in.

### 2.7. Lane Posture, Stall Availability, and Weather

Each location tracks how many drive-in stalls remain usable. `stalls_available` equals the location's `stall_capacity` minus the count of that location's stalls whose `kind` is `STALL` and whose `status` is either `OCCUPIED` or `OUT_OF_SERVICE`. Patio positions (`kind` of `PATIO`) are excluded from drive-in stall math entirely; they follow patio service targets and do not consume `stall_capacity`.

From `stalls_available` and the location's `weather_mode` the system derives `lane_posture`, one of three values. The lane is `CURBSIDE_ONLY` when `stalls_available` reaches zero or when `weather_mode` is `STORM`. Otherwise the lane is `CONGESTED` when `stalls_available` is less than or equal to the stall capacity multiplied by 0.20 and rounded up to a whole number — for a forty-stall lot, that threshold is eight stalls. Otherwise the lane is `OPEN`. Lane posture is recomputed whenever any stall changes status and whenever the weather mode changes.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

A stall check-in request must carry `expected_location_version`, holding the `version` of the parent Location the caller last observed. Because weather changes and other stall events advance the location's `version` and its derived `lane_posture`, a caller acting on a stale read may be checking a guest into a lane that has since gone curbside-only. If the supplied value does not match the location's current `version`, the check-in is rejected with `ERR_STALE_VERSION` (HTTP 412) and the caller must re-read the location before retrying.

Staging a delivery run must carry `expected_carhop_version`, holding the `version` of the selected Carhop the dispatcher last observed. Because every run assignment advances the carhop's `version` (its `active_run_load` changes), a stale read means the dispatcher is working from an outdated load picture. A mismatch with the carhop's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Nested Resource Retrieval and Flat Alias Reads

Requests targeting nested resources are validated left-to-right along the path, whose parameter names are spelled `locationId`, `stallId`, `faultId`, `orderId`, `runId`, `tipId`, `itemId`, `lineId`, `offerId`, `customerId`, and `carhopId` respectively: the location is resolved first, then the stall, then the fault, order, run, or tip record beneath it, and each identifier must not only exist but belong to the enclosing resource named earlier in the path. The first identifier that fails existence or nesting yields `ERR_NOT_FOUND` (HTTP 404) before later segments are examined. The same rule applies to body references: identifiers supplied in a request body — `menu_item_id`, `customer_id`, option codes, and the parents named by the OCC fields — must exist, or the request fails with `ERR_NOT_FOUND` (HTTP 404).

Alongside the nested routes, the API exposes flat alias reads and flat filtered lists — single-resource reads by bare `id` and collection listings filterable by foreign keys such as `location_id`, `stall_id`, `customer_id`, `delivery_run_id`, `order_id`, `carhop_id`, and `menu_item_id` — so that any entity remains reachable from a reference held on another resource. These aliases are read-only; all writes go through the nested routes.

### 2.10. Validation Priority Order

When several validation rules could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence and left-to-right nesting of path resources (`ERR_NOT_FOUND`), then existence of body references (`ERR_NOT_FOUND`). Next comes the optimistic-concurrency check (`ERR_STALE_VERSION`), then the state-machine from-state check including terminal-state lockdown (`ERR_INVALID_STATE`). Only after those structural gates do business rules fire, in this order: weather and lane safety gates (`ERR_LANE_CLOSED`, `ERR_STALL_WEATHER_CLOSED`); stall occupancy and equipment gates (`ERR_STALL_OCCUPIED`, `ERR_STALL_NOT_OCCUPIED_BY_ORDER`, `ERR_INTERCOM_UNAVAILABLE`, `ERR_FAULT_STILL_OPEN`); menu and catalog integrity (`ERR_MENU_ITEM_RETIRED`, `ERR_SIZE_REQUIRED`, `ERR_OPTION_INVALID`, `ERR_INVALID_REQUEST`); offer-window and app-only applicability (`ERR_OFFER_NOT_APPLICABLE`, `ERR_APP_ONLY`); payment sequencing (`ERR_PAYMENT_NOT_CAPTURED`, `ERR_PAYMENT_CAPTURED_REQUIRES_REFUND`); dispatch constraints (`ERR_EMPTY_RUN`, `ERR_NO_CARHOP_ELIGIBLE`, `ERR_RUN_SEQUENCE_VIOLATION`, `ERR_NOT_ASSIGNED_CARHOP`); and finally capacity constraints (`ERR_KITCHEN_SATURATED`, `ERR_NO_SERVICE_TARGET`).

Malformed input — an unrecognized enum value, a `quantity` below 1, a missing required field, a non-positive `stall_capacity` or `target_seconds` — is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Location Setup, Weather Shifts, and Rush Windows

A `PlatformAdmin` opens a new drive-in by creating a Location with its unique store `code` (for example, `OKC-114`), a display `name`, the IANA `timezone` used for offer-window evaluation, and the physical `stall_capacity`, which must be greater than zero. A freshly created location starts calm: `weather_mode` is `NORMAL`, `rush_index` is 0, `stalls_available` equals `stall_capacity`, and `lane_posture` is `OPEN`. Reading a location returns these computed posture fields alongside the configured ones.

Weather moves the whole lot. A `ShiftManager` or `PlatformAdmin` sets the location's `weather_mode` to `NORMAL`, `HEAT_ADVISORY`, or `STORM`; the change recomputes `stalls_available` and `lane_posture` immediately and increments the location's `version` by one. A `HEAT_ADVISORY` closes every patio position to new check-ins, rejected with `ERR_STALL_WEATHER_CLOSED`. A `STORM` goes further: it forces `lane_posture` to `CURBSIDE_ONLY`, which blocks intercom check-in with `ERR_LANE_CLOSED` and blocks placement of any `STALL_INTERCOM` order, while still accepting app check-ins and drive-thru orders.

The kitchen's appetite is paced by rush windows. A `ShiftManager` advances the rush, which increments `rush_index` by one and sweeps the lot for stale drafts: any stall-check-in order still in `DRAFT` whose recorded check-in rush index is more than two windows behind the new `rush_index` is cancelled outright, with the stall-release cascade described in §3.3 (directly created drive-thru drafts carry no check-in rush index and are never expired by this sweep). Advancing the rush also increments the location's `version` by one, so a check-in caller holding a pre-advance location read will fail the optimistic-concurrency check and must re-read.

### 3.2. Menu Catalog and Customization

The catalog is corporate-managed. A `PlatformAdmin` creates each MenuItem with a unique `sku`, a display `name`, a `category` of `FOOD`, `DRINK`, `SLUSH`, `DESSERT`, or `ADDIN`, and a non-negative `base_price_cents`. Customers, by contrast, register themselves: a `Customer` or `PlatformAdmin` creates the account with a unique login `email` and a `display_name`, optionally presetting a `stored_tip_default_pct`; registration flips `app_user` to true and opens an empty wallet. Items default to `size_scheme` of `NONE`; a drink or slush item can instead declare `DRINK_SIZES`, which enables size upcharge tiers for that item. The `half_price_eligible` flag, defaulting to false, marks whether the item participates in happy-hour half-price drinks and slushes. New items are born `ACTIVE`; retiring one flips its `status` to `RETIRED`, after which it cannot be added to new orders or placed, though it remains visible on historical orders. The catalog can be listed with optional `category` and `status` filters.

Customization options come in two flavors sharing one resource. Each CustomizationOption carries a unique `code` (such as `CHERRY` or `XL`), an `applies_to_category` of `DRINK`, `SLUSH`, or `ANY`, and a flat non-negative `price_cents`. Options with `is_size` set to true are size options (small through extra-large): instead of adding `price_cents` flat, a size option contributes its `size_upcharge_cents` — defaulting to 0 and only meaningful when `is_size` is true — when selected on a `DRINK_SIZES` item. Options are created `ACTIVE` and may be filtered by `status` when listed. Add-in options apply only where their category matches: an option whose `applies_to_category` is `DRINK` flavors drink lines, `SLUSH` flavors slush lines, and `ANY` is accepted on either; any other pairing is rejected with `ERR_OPTION_INVALID` (HTTP 422), as is referencing an option that is not `ACTIVE`. A size option may never be listed among `addin_option_codes` — a size is selected only through `size_option_code`; a non-`DRINK_SIZES` item may optionally carry a `size_option_code` naming an `ACTIVE` size option, which then contributes nothing to the line's price.

### 3.3. Stall Check-In and Order Drafting

Every stall and patio table at a location is a Stall, created by a `ShiftManager` or `PlatformAdmin` with a `stall_number` unique within the location and a `kind` of `STALL` or `PATIO`. A new stall starts `IDLE` with `intercom_functional` true, and its creation recomputes the location's `stalls_available`. The stall's `current_order_id` points at the order currently occupying it and is null while the stall is `IDLE`; the stall list can be filtered by `status`, `kind`, `location_id`, or `current_order_id`.

A guest visit begins at check-in, performed by a `Customer` or a `ShiftManager` on the guest's behalf. Intercom check-in requires the stall to be `IDLE` — otherwise `ERR_STALL_OCCUPIED` — requires the lane not to be `CURBSIDE_ONLY` (else `ERR_LANE_CLOSED`), and carries the OCC field `expected_location_version` described in §2.8; it may optionally name a `customer_id`. App-initiated check-in is exclusive to the `Customer` role and requires a `customer_id` naming an existing customer whose `app_user` flag is true; anyone else is turned away with `ERR_APP_ONLY`. Weather gates both paths: a `HEAT_ADVISORY` refuses check-in at patio stalls with `ERR_STALL_WEATHER_CLOSED`, and a `STORM` refuses intercom check-in everywhere. A successful check-in occupies the stall (`IDLE` → `OCCUPIED`), creates a `DRAFT` order bound to the stall with `checked_in_at` set to the current logical time, sets the stall's `current_order_id` to the new order, and recomputes `stalls_available` and `lane_posture`. The created order's `channel` reflects how the guest arrived: `STALL_INTERCOM` for an intercom check-in at a drive-in stall, `APP_CHECKIN` for an app check-in at a drive-in stall, and `PATIO` for either check-in flavor at a patio position. Notably, check-in mutates the stall, not the location row itself, so the location's `version` is unchanged by it.

Drive-thru is the one channel with no stall. A `Customer` or `ShiftManager` may create a draft order directly, but only with `channel` equal to `DRIVE_THRU` — stall channels come into existence exclusively through check-in — and such an order has a null `stall_id`. Stall-channel orders may carry a null `customer_id` as intercom guest orders. Orders are listed with filters for `status`, `channel`, `payment_status`, `location_id`, `stall_id`, `customer_id`, and `delivery_run_id`.

While an order is in `DRAFT`, a `Customer` or `ShiftManager` builds its lines. Each line references a `menu_item_id` and a `quantity` of at least 1. When the menu item's `size_scheme` is `DRINK_SIZES`, the line must also carry a `size_option_code` naming a size option; omitting it is rejected with `ERR_SIZE_REQUIRED` (HTTP 422). Optional `addin_option_codes` list non-size option codes, each of which must be `ACTIVE` and applicable to the item's category. Lines may be added and removed only while the order is in `DRAFT`; attempting line changes later fails the from-state check with `ERR_INVALID_STATE`.

### 3.4. Placing the Order: Pricing, Happy Hour, and Offers

Line pricing starts simple and compounds. A line's `unit_price_cents` is the item's `base_price_cents`, plus the selected size option's `size_upcharge_cents` when the item uses `DRINK_SIZES` (zero otherwise), plus the sum of `price_cents` across the line's add-ins. The line's `extended_price_cents` begins as `unit_price_cents` multiplied by `quantity`, rounded per line. Combination pricing then rewards drink and slush pairs: taking every unit on every line whose item's `category` is `DRINK` or `SLUSH`, the units are sorted in ascending `unit_price_cents` order — ties broken by the line's `created_at`, earlier first — and dealt into consecutive pairs from the front of that ordering (the first unit full price, the second discounted); the second unit of each pair is discounted by half of its unit price, rounded half-up to the cent, and an unpaired leftover unit receives no discount. The discount for each half-price unit is folded back into its line's `extended_price_cents`, and the order's `subtotal_cents` is the sum of the adjusted extended prices — round per line first, then sum, always in that order. While the order remains in `DRAFT` this provisional pricing is what a cart preview shows: combination pricing applied, but no offers, no happy hour, and `tax_cents` estimated as 0.

Placement is the pivot where provisional becomes final, and it is guarded. The order must have at least one line (`ERR_EMPTY_ORDER`), every line's menu item must still be `ACTIVE` at place time (`ERR_MENU_ITEM_RETIRED`, HTTP 409), and a stall-channel order may only be placed while its stall is `OCCUPIED` with `current_order_id` pointing at this very order (`ERR_STALL_NOT_OCCUPIED_BY_ORDER`). An intercom order additionally needs a working speaker: `intercom_functional` must be true, unless the stall has an open fault of kind `INTERCOM_DEAD` and the request explicitly carries `fallback_confirmed` set to true — the manual fallback for a guest who ordered by shouting at the carhop — and otherwise placement is rejected with `ERR_INTERCOM_UNAVAILABLE`. Placement of a `STALL_INTERCOM` order at a `CURBSIDE_ONLY` location is refused with `ERR_LANE_CLOSED`; curbside-only locations accept `APP_CHECKIN` and `DRIVE_THRU` placement only.

At the instant of placement, pricing is frozen through a fixed sequence. First, happy hour reprices eligible lines: for every `ACTIVE` offer of kind `HAPPY_HOUR` with `discount_type` `HALF_PRICE_DRINKS` whose daily window contains the local time of `checked_in_at`, every line whose item is `half_price_eligible` and whose category is `DRINK` or `SLUSH` has its `unit_price_cents` replaced by half of itself, rounded half-up to the cent; the line's `happy_hour_priced` flag becomes true and its `extended_price_cents` is recomputed. Happy hour is window-based, not account-based, so it applies even to a guest intercom order with no customer attached. Second, a single additional offer is selected: among the location's remaining `ACTIVE` offers — excluding `HAPPY_HOUR` ones already applied — whose window contains the local check-in time and whose `app_only` restriction is satisfied (an app-restricted offer applies only when the order's `channel` is `APP_CHECKIN` and the customer's `app_user` is true), the system picks the offer producing the largest discount. A `PERCENT_OFF_ORDER` offer discounts the post-happy-hour subtotal by `discount_value` percent, rounded half-up to the cent; a `FIXED_OFF_CENTS` offer discounts by `discount_value` cents, capped at the post-happy-hour subtotal so the discount never exceeds it. Ties break toward the offer with the earliest `created_at`, and no further tie-break exists because offer creation timestamps are unique. Stacking is limited: exactly one non-happy-hour offer may apply per order, and happy hour may stack with that one offer. A placer may also force a specific offer by naming an `offer_code`; if that offer is not `ACTIVE`, its window does not contain the check-in time, or its app-only restriction is not met, placement fails with `ERR_OFFER_NOT_APPLICABLE`. The order's `subtotal_cents` is the happy-hour-repriced, combination-adjusted sum of the line extended prices; the order's `offer_discount_cents` is the happy-hour savings — the provisional pre-happy-hour subtotal minus this repriced subtotal — plus the selected offer's discount, frozen at placement.

Tax and totals fall out of the frozen figures. `tax_cents` is computed on `subtotal_cents` minus `offer_discount_cents`, rounded half-up per order; the system's configured tax rate is zero, so `tax_cents` is 0 at placement. The order's `total_cents` is `subtotal_cents` minus `offer_discount_cents` plus `tax_cents`. Placement also stamps `placed_at` and snapshots `service_target_seconds` from the location's service-target profiles: the `ACTIVE` ServiceTargetProfile matching the order's `channel` and the location's current `weather_mode` supplies its `target_seconds`; if no profile exists for that exact weather mode, the `ACTIVE` profile for the same channel under `NORMAL` weather is used instead; if neither exists, placement is rejected with `ERR_NO_SERVICE_TARGET`. The snapshot persists for the life of the order even if the weather mode later changes. Once placed, the order moves `DRAFT` → `PLACED` and its pricing fields no longer move.

Offers themselves are location-scoped and manager-curated. A `ShiftManager` or `PlatformAdmin` creates an Offer with a `code` unique within the location, a `kind` of `HAPPY_HOUR`, `APP_ONLY`, or `PROMO`, a `discount_type` of `HALF_PRICE_DRINKS`, `PERCENT_OFF_ORDER`, or `FIXED_OFF_CENTS`, and a `discount_value` — a whole percent between 1 and 90 for percentage offers, a cent amount for fixed offers, and ignored for half-price-drinks offers. The daily window runs from `window_start_local` inclusive to `window_end_local` exclusive, with equal endpoints meaning all-day; `app_only` defaults to false. Offers are born `ACTIVE`, may be listed with `status` and `kind` filters, and are retired from circulation by disabling them, which sets `status` to `DISABLED`.

### 3.5. Kitchen Flow, Service Targets, and Late Evaluation

Once placed, the kitchen takes over. A `KitchenStaff` member or `ShiftManager` starts preparation, moving the order `PLACED` → `PREPARING` — but only while the kitchen has room: the number of orders currently in `PREPARING` at the location must be fewer than eight. Exactly eight orders in preparation rejects the ninth with `ERR_KITCHEN_SATURATED`, while seven admits the eighth. When the food is bagged, marking the order ready moves it `PREPARING` → `READY` and stamps `ready_at`. From `READY`, a stall or patio order waits for a tray run; a drive-thru order never touches a run at all — it is handed off at the window.

Service targets are configured per location, per channel, per weather. A `ShiftManager` or `PlatformAdmin` creates a ServiceTargetProfile naming a `channel`, a `weather_mode` of `NORMAL`, `HEAT_ADVISORY`, or `STORM` during which the profile applies, and a `target_seconds` that must be greater than zero. Profiles are born `ACTIVE`, and at most one `ACTIVE` profile may exist for any pairing of channel and weather mode at a location: creating a new `ACTIVE` profile for a pairing that already has one retires the incumbent, flipping its `status` to `RETIRED`. Profiles can be listed filtered by `channel` and `status`. Because placement snapshots the profile into `service_target_seconds`, mid-flight profile changes never rewrite history.

Delivery is where lateness is judged. When an order reaches `DELIVERED`, the system stamps `delivered_at` and computes `late_flag` by comparing the elapsed seconds from `placed_at` to `delivered_at` against the snapshotted `service_target_seconds`: strictly greater is late; an elapsed time exactly equal to the target counts as on time. Managers read the rollup through the location metrics view, which aggregates the location's delivered orders — optionally filtered by `channel` and by a `placed_at` range from `from` inclusive to `to` exclusive — into `count_delivered`; `count_late`, the number with `late_flag` true; `avg_checkout_to_ready_seconds`, the mean of `ready_at` minus `placed_at`; `avg_ready_to_delivered_seconds`, the mean of `delivered_at` minus `ready_at`; and `on_time_rate`, the share of delivered orders that were not late, computed as the delivered count minus the late count, divided by the delivered count, to four decimal places. All means are rounded half-up to whole seconds. Over an empty set the rollup reports `count_delivered` of 0 with both means and the on-time rate null.

### 3.6. Dispatch: Staging, Departure, and In-Sequence Delivery

Carhops are hired per location by a `ShiftManager` or `PlatformAdmin`, each with a display `name`, a `zone` of `NORTH`, `SOUTH`, or `PATIO` that filters dispatch eligibility, an `on_shift` flag defaulting to true (off-shift carhops are never dispatch-eligible), and a `max_trays` defaulting to 3 — the maximum number of orders one DeliveryRun may ask that carhop to carry. A new carhop starts with `active_run_load` 0 and both tip counters at 0; the roster lists with `zone` and `on_shift` filters.

Staging a run is a `ShiftManager` decision executed by the dispatch selector. The request names a `carhop_id` and must carry `expected_carhop_version` per §2.8; it may also carry an explicit `order_ids` list restricting which orders are considered and an optional `route_note`. Order selection takes candidate orders in `READY` at the location whose channel is not `DRIVE_THRU` — drive-thru hands off at the window and never rides a tray — and which are not already staged on a run, ranks them by `placed_at` ascending with ties broken by `created_at` ascending, and takes up to the chosen carhop's `max_trays`. The chosen carhop must be eligible: `on_shift` true, and the sum of `active_run_load` and the number of selected orders must not exceed `max_trays`. The carhop's `zone` must match the run's required zone, which is the zone covering the selected orders' earliest-placed order (in the `placed_at`-ascending selection order, tie-broken by `created_at`): a patio order maps to zone `PATIO`, and a drive-in stall order maps by `stall_number` parity, even numbers to `NORTH` and odd to `SOUTH`. When the request leaves the carhop choice open, candidates are ranked by `active_run_load` ascending, then by `created_at` ascending; if no carhop qualifies, staging fails with `ERR_NO_CARHOP_ELIGIBLE`. A staged run is born in `LOADED` with `staged_at` stamped; its orders receive `delivery_run_id` and a 1-based `run_position` assigned in `placed_at` order; the carhop's `active_run_load` increases by the run's `order_count`; and the carhop's `version` increments by one — which is exactly why the next staging attempt against a stale carhop read fails the OCC check. Staging also attaches the carhop to each staged order's `RECORDED` TipRecord when the tip was captured before staging and still has a null `carhop_id`, and adds that tip amount to the carhop's `tips_outstanding_cents`.

Departure belongs to the carhop on the run, or to a `ShiftManager`. A run departs only with at least one order aboard (`ERR_EMPTY_RUN`), and a departing `Carhop` must be the run's assigned carhop — anyone else is rejected with `ERR_NOT_ASSIGNED_CARHOP`, while a `ShiftManager` may depart any run. Departure moves the run `LOADED` → `OUT`, stamps `out_at`, and moves every staged order `READY` → `OUT_FOR_DELIVERY`; there is no per-order movement again until delivery.

Delivery off the run is strictly sequenced. Delivering an order requires the order's payment to be `CAPTURED` (`ERR_PAYMENT_NOT_CAPTURED` otherwise) and requires that every order on the same run with a smaller `run_position` already be `DELIVERED` or `CANCELLED` — skipping ahead in the route is rejected with `ERR_RUN_SEQUENCE_VIOLATION`. A successful delivery stamps `delivered_at`, computes `late_flag` as in §3.5, and, when the delivered order is its stall's current order (channels `STALL_INTERCOM`, `APP_CHECKIN`, and `PATIO`), clears the stall's `current_order_id` and returns the stall to `IDLE`, after which `stalls_available` and `lane_posture` are recomputed. When the last open order on a run resolves — every order `DELIVERED` or `CANCELLED` — the run completes automatically (`OUT` → `COMPLETED`) and the carhop's `active_run_load` decreases by the run's `order_count`.

A manager can also abort a run before it leaves. Voiding a `LOADED` run moves it to `VOIDED`, strips every staged order of its `delivery_run_id` and `run_position` while leaving each in `READY`, and decrements the carhop's `active_run_load` by the run's `order_count`. Runs list with `status` and `carhop_id` filters.

### 3.7. Payment, Wallets, and Refunds

Payment is an axis independent of fulfillment: every order carries a `payment_status` of `UNPAID`, `AUTHORIZED`, `CAPTURED`, `VOIDED`, or `REFUNDED`, evolving alongside — never inside — the fulfillment states. Authorization, available to a `Customer` or `ShiftManager`, moves `UNPAID` → `AUTHORIZED` and is only meaningful while the order is in `DRAFT`, `PLACED`, `PREPARING`, or `READY`; attempting it elsewhere fails with `ERR_INVALID_STATE`.

Capture is where money actually moves, and a `Customer`, `Carhop`, or `ShiftManager` may perform it. Capture requires `AUTHORIZED` and resolves the tip first: an explicit `tip_cents` in the request wins outright; otherwise, when the order has a customer whose `stored_tip_default_pct` — a number between 0 and 0.50, defaulting to 0 — is greater than zero, the tip is `total_cents` multiplied by that percentage, rounded half-up to the cent; otherwise the tip is zero. The order's `total_tendered_cents` is then `total_cents` plus `tip_cents`, and the tender draws on the customer's `wallet_credit_cents` first, debiting up to the wallet balance against the tendered amount and charging any remainder to the card; the wallet debit is immediate at capture. Capture also creates a TipRecord in `RECORDED` state, snapshotting the resolved `tip_cents`, with `carhop_id` set to the delivering run's carhop when one is already known and null otherwise — as for a drive-thru window handoff.

Captured orders cannot simply be cancelled; they must be refunded, and only a `ShiftManager` refunds. A refund requires `payment_status` of `CAPTURED` and is freely allowed on a `DELIVERED` order; refunding an order in any other fulfillment state requires the request to carry `manager_override` set to true, and a non-delivered refund attempted without it is rejected with `ERR_PAYMENT_NOT_CAPTURED`. Refund moves `CAPTURED` → `REFUNDED`, voids the order's TipRecord, decrements the carhop's `tips_outstanding_cents` by the recorded tip, and — when the request's `refund_mode` is `STORE_CREDIT` — credits the customer's `wallet_credit_cents` by `total_cents` when the order has a customer attached, notably excluding the tip.

Customers carry store credit on `wallet_credit_cents`, which starts at 0 on registration. A `ShiftManager` may adjust a wallet directly with a signed `delta_cents` and a `reason`; the balance must never go negative, so any adjustment or tender that would drive `wallet_credit_cents` below 0 is rejected with `ERR_WALLET_NEGATIVE`.

### 3.8. Cancellation and Stall Release

Cancellation rules depend on how far the order has travelled and who is asking. A customer may cancel their own order while it is still a `DRAFT`. From `PLACED`, `PREPARING`, or `READY`, cancellation is a `ShiftManager`-only act and requires the payment to be `UNPAID`, `AUTHORIZED`, or `VOIDED`; a captured order refuses cancellation with `ERR_PAYMENT_CAPTURED_REQUIRES_REFUND` and must go through refund instead. Whenever an authorized order is cancelled, its `payment_status` cascades from `AUTHORIZED` to `VOIDED` in the same breath. And whenever a cancelled order was occupying a stall, the stall's `current_order_id` is cleared, the stall returns to `IDLE`, and the location's `stalls_available` is recomputed. The same stall-release cascade fires on delivery, on rush-window draft expiry, and on forced out-of-service events — the stall never stays pinned to a dead order.

### 3.9. Equipment Faults and Manual Stall Management

Carhops and managers are the eyes of the lot. Either may report an EquipmentFault on a stall, recording the `reported_by_role` as `CARHOP` or `SHIFT_MANAGER`, a `kind` of `INTERCOM_DEAD`, `PAYMENT_TERMINAL_DEAD`, or `MENU_BOARD_DEAD`, and a free-text `note`. Reporting is one of the few acts a `Carhop` performs in their own name, and a carhop reporter uses `CARHOP` as the role. Every open fault flips the stall's `intercom_functional` to false — the speaker is presumed untrustworthy until proven repaired — and a `MENU_BOARD_DEAD` fault additionally drives the stall straight to `OUT_OF_SERVICE` with `stalls_available` recomputed. Faults are born `OPEN` and list with a `status` filter.

A `ShiftManager` resolves a fault, moving it `OPEN` → `RESOLVED`; when no other `OPEN` fault remains on the stall, `intercom_functional` returns to true. Managers can also take a stall out of service directly: on an `IDLE` stall this simply moves it to `OUT_OF_SERVICE` and recomputes availability, but on an `OCCUPIED` stall the request must carry `force_cancel` set to true, which cancels the occupying order in the same request — with the payment-void cascade if it was authorized — before the stall goes down; without `force_cancel` the attempt fails with `ERR_STALL_OCCUPIED`. Returning a stall to service requires a clean bill of health: any `OPEN` fault on the stall blocks the return with `ERR_FAULT_STILL_OPEN`, and a successful return moves the stall back to `IDLE`, restores `intercom_functional` to true, and recomputes `stalls_available`.

### 3.10. Tip Settlement After the Rush

Tips live on TipRecords, one per captured order, carrying the `order_id`, the `carhop_id` of whoever ran the tray (null for window handoffs), and the snapshotted `tip_cents`. Managers and carhops browse them with `carhop_id`, `status`, and `order_id` filters, and a carhop's two counters summarize the books: `tips_outstanding_cents` sums the `tip_cents` of that carhop's `RECORDED` records, while `tips_settled_cents` sums those of `SETTLED` records.

Settlement is a `ShiftManager` close-of-shift ritual. Settling a `RECORDED` tip moves it to `SETTLED`; if the request supplies `adjusted_tip_cents` — which must be at least 0 — the record's `tip_cents` is replaced by the adjustment first. Either way, the settled amount leaves `tips_outstanding_cents` and lands in `tips_settled_cents` on the carhop. When an order's payment is later refunded, its tip record voids automatically (`RECORDED` → `VOIDED`) and the outstanding counter gives the amount back.

## 4. Endpoint Definitions

New resources are returned with 201 on creation; modifications, state transitions, and reads return 200; the line-removal endpoint returns 204 with no body. All responses use the envelope defined in §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /locations | Create a drive-in location | PlatformAdmin |
| GET | /locations/{locationId} | Get a location with computed posture fields | PlatformAdmin, ShiftManager, Carhop, KitchenStaff, Customer |
| POST | /locations/{locationId}/weather | Set weather mode; drives stall closures and lane posture | ShiftManager, PlatformAdmin |
| POST | /locations/{locationId}/advance_rush | Advance the rush window; expires stale DRAFT orders | ShiftManager |
| GET | /locations/{locationId}/metrics | Timing metrics rollup over delivered orders | ShiftManager, PlatformAdmin |
| POST | /menu-items | Create a menu item | PlatformAdmin |
| GET | /menu-items | List menu items | PlatformAdmin, ShiftManager, Carhop, KitchenStaff, Customer |
| GET | /menu-items/{itemId} | Get a menu item | PlatformAdmin, ShiftManager, Carhop, KitchenStaff, Customer |
| POST | /menu-items/{itemId}/retire | Retire a menu item | PlatformAdmin |
| POST | /customization-options | Create a customization option (add-in or size) | PlatformAdmin |
| GET | /customization-options | List customization options | PlatformAdmin, ShiftManager, Carhop, KitchenStaff, Customer |
| POST | /customers | Register an app customer | Customer, PlatformAdmin |
| GET | /customers/{customerId} | Get a customer | Customer, ShiftManager, PlatformAdmin |
| GET | /customers | List customers | ShiftManager, PlatformAdmin |
| POST | /customers/{customerId}/wallet/adjust | Manager wallet credit/debit adjustment | ShiftManager |
| POST | /locations/{locationId}/stalls | Create a stall (or patio table) | ShiftManager, PlatformAdmin |
| GET | /locations/{locationId}/stalls | List stalls of a location | ShiftManager, Carhop, KitchenStaff, PlatformAdmin, Customer |
| GET | /locations/{locationId}/stalls/{stallId} | Get a stall | ShiftManager, Carhop, KitchenStaff, PlatformAdmin, Customer |
| POST | /locations/{locationId}/stalls/{stallId}/checkin | Intercom check-in: occupies the stall and opens a DRAFT order; OCC-guarded on the location | Customer, ShiftManager |
| POST | /locations/{locationId}/stalls/{stallId}/app-checkin | App-initiated check-in; requires an existing app-user customer | Customer |
| POST | /locations/{locationId}/stalls/{stallId}/faults | Report equipment fault on a stall | Carhop, ShiftManager |
| GET | /locations/{locationId}/stalls/{stallId}/faults | List faults of a stall | Carhop, ShiftManager, PlatformAdmin |
| POST | /locations/{locationId}/stalls/{stallId}/faults/{faultId}/resolve | Resolve an equipment fault | ShiftManager |
| POST | /locations/{locationId}/stalls/{stallId}/set_out_of_service | Force a stall out of service; occupied stalls require force_cancel | ShiftManager |
| POST | /locations/{locationId}/stalls/{stallId}/return_to_service | Return a stall to IDLE | ShiftManager |
| POST | /locations/{locationId}/orders | Create a DRAFT drive-thru order | Customer, ShiftManager |
| GET | /locations/{locationId}/orders | List orders with filters | ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| GET | /locations/{locationId}/orders/{orderId} | Get an order with computed pricing fields | Customer, ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| POST | /locations/{locationId}/orders/{orderId}/lines | Add an order line (DRAFT only) | Customer, ShiftManager |
| GET | /locations/{locationId}/orders/{orderId}/lines | List lines of an order | Customer, ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| DELETE | /locations/{locationId}/orders/{orderId}/lines/{lineId} | Remove an order line (DRAFT only) | Customer, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/place | Place the order: happy-hour repricing, offer selection, service-target snapshot | Customer, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/start_preparation | Move order to PREPARING (kitchen cap enforced) | KitchenStaff, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/mark_ready | Move order to READY | KitchenStaff, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/authorize_payment | Authorize payment (UNPAID to AUTHORIZED) | Customer, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/capture_payment | Capture payment with tip resolution and wallet tender | Customer, Carhop, ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/refund | Refund a captured order | ShiftManager |
| POST | /locations/{locationId}/orders/{orderId}/cancel | Cancel an order (channel rules and payment-state gates apply) | Customer, ShiftManager |
| POST | /locations/{locationId}/offers | Create an offer | ShiftManager, PlatformAdmin |
| GET | /locations/{locationId}/offers | List offers of a location | ShiftManager, PlatformAdmin, Customer |
| GET | /locations/{locationId}/offers/{offerId} | Get an offer | ShiftManager, PlatformAdmin, Customer |
| POST | /locations/{locationId}/offers/{offerId}/disable | Disable an offer | ShiftManager, PlatformAdmin |
| POST | /locations/{locationId}/service-targets | Create a service target profile; at most one ACTIVE per (channel, weather_mode) | ShiftManager, PlatformAdmin |
| GET | /locations/{locationId}/service-targets | List service target profiles | ShiftManager, PlatformAdmin |
| POST | /locations/{locationId}/carhops | Hire a carhop | ShiftManager, PlatformAdmin |
| GET | /locations/{locationId}/carhops | List carhops | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/{locationId}/carhops/{carhopId} | Get a carhop with tip and load counters | ShiftManager, Carhop, PlatformAdmin |
| POST | /locations/{locationId}/delivery-runs | Stage a delivery run; OCC-guarded on the selected carhop | ShiftManager |
| GET | /locations/{locationId}/delivery-runs | List delivery runs | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/{locationId}/delivery-runs/{runId} | Get a delivery run | ShiftManager, Carhop, PlatformAdmin |
| POST | /locations/{locationId}/delivery-runs/{runId}/depart | Depart the run (orders move to OUT_FOR_DELIVERY) | Carhop, ShiftManager |
| POST | /locations/{locationId}/delivery-runs/{runId}/void | Void a LOADED run; orders return to READY unstaged | ShiftManager |
| POST | /locations/{locationId}/delivery-runs/{runId}/orders/{orderId}/deliver | Deliver one order off the run, in run_position order | Carhop, ShiftManager |
| GET | /locations/{locationId}/tip-records | List tip records | ShiftManager, Carhop, PlatformAdmin |
| POST | /locations/{locationId}/tip-records/{tipId}/settle | Settle a tip (optional adjustment) | ShiftManager |
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-09-01T00:00:00Z; never wall-clock) | PlatformAdmin |
| GET | /locations/stalls/{id} | Get a Stall by id (flat alias read) | ShiftManager, Carhop, KitchenStaff, PlatformAdmin, Customer |
| GET | /locations/carhops/{id} | Get a Carhop by id (flat alias read) | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/orders/{id} | Get an Order by id (flat alias read) | Customer, ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| GET | /locations/offers/{id} | Get an Offer by id (flat alias read) | ShiftManager, PlatformAdmin, Customer |
| GET | /locations/service-targets/{id} | Get a ServiceTargetProfile by id (flat alias read) | ShiftManager, PlatformAdmin |
| GET | /locations/delivery-runs/{id} | Get a DeliveryRun by id (flat alias read) | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/tip-records/{id} | Get a TipRecord by id (flat alias read) | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/order-lines/{id} | Get an OrderLine by id (flat alias read) | Customer, ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| GET | /locations/faults/{id} | Get an EquipmentFault by id (flat alias read) | Carhop, ShiftManager, PlatformAdmin |
| GET | /locations/stalls | Flat filtered list of Stall | ShiftManager, Carhop, KitchenStaff, PlatformAdmin, Customer |
| GET | /locations/carhops | Flat filtered list of Carhop | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/orders | Flat filtered list of Order | ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| GET | /locations/offers | Flat filtered list of Offer | ShiftManager, PlatformAdmin, Customer |
| GET | /locations/service-targets | Flat filtered list of ServiceTargetProfile | ShiftManager, PlatformAdmin |
| GET | /locations/delivery-runs | Flat filtered list of DeliveryRun | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/tip-records | Flat filtered list of TipRecord | ShiftManager, Carhop, PlatformAdmin |
| GET | /locations/order-lines | Flat filtered list of OrderLine | Customer, ShiftManager, Carhop, KitchenStaff, PlatformAdmin |
| GET | /locations/faults | Flat filtered list of EquipmentFault | Carhop, ShiftManager, PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_STALL_OCCUPIED | 409 |
| ERR_STALL_NOT_OCCUPIED_BY_ORDER | 409 |
| ERR_INTERCOM_UNAVAILABLE | 409 |
| ERR_FAULT_STILL_OPEN | 409 |
| ERR_LANE_CLOSED | 409 |
| ERR_STALL_WEATHER_CLOSED | 409 |
| ERR_APP_ONLY | 409 |
| ERR_MENU_ITEM_RETIRED | 409 |
| ERR_SIZE_REQUIRED | 422 |
| ERR_OPTION_INVALID | 422 |
| ERR_EMPTY_ORDER | 409 |
| ERR_NO_SERVICE_TARGET | 409 |
| ERR_OFFER_NOT_APPLICABLE | 409 |
| ERR_PAYMENT_NOT_CAPTURED | 409 |
| ERR_PAYMENT_CAPTURED_REQUIRES_REFUND | 409 |
| ERR_WALLET_NEGATIVE | 409 |
| ERR_KITCHEN_SATURATED | 409 |
| ERR_EMPTY_RUN | 409 |
| ERR_NO_CARHOP_ELIGIBLE | 409 |
| ERR_NOT_ASSIGNED_CARHOP | 409 |
| ERR_RUN_SEQUENCE_VIOLATION | 409 |
