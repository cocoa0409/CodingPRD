# Farm Ranch Retail API — Product Requirements Document

## 1. Introduction

Farm and ranch retail runs on a calendar that no other retail segment shares. For a few weeks each spring, stores sell live poultry out of brooders in the middle of the sales floor; the rest of the year the same square footage flips between winter heating, spring planting, and fall feed layouts. Propane moves by the pound and is dispensed under a daily hazmat cap. Loyalty members expect to be found by phone number at the register — no card, no receipt — and expect their feed purchases in October to count double. This document specifies the API that backs all of it: chick-days live poultry ordering with hatchery scheduling, minimum-purchase rules and brooder verification, live-animal care logging with mortality-driven quarantine, seasonal planogram-reset campaigns that flip a store's commercial posture, weight-based bulk feed and propane exchange sales with provisional-then-final pricing, a loyalty program with tier accrual, redemption, reversals, and posture-aware fuel-and-feed offers, buy-online-pickup-in-store fulfillment for oversized items with staging-bay allocation and load-out assistance, and in-store pet wash and vet clinic event scheduling.

A defining property of this system is that a store's **posture** — the season installed by its currently active campaign — is not cosmetic. Posture gates whether chick orders can be placed at all, whether the weighted-sale floor is open, how many loyalty points a feed purchase earns, and which offers a member qualifies for. Activating a new campaign is therefore a consequential, cascaded operation: it completes the campaign it supersedes, recomputes the store's posture, and (outside spring) tears down every live poultry sale in progress. Time throughout the system is governed by a controllable logical clock so that windowed rules — sale windows, pickup deadlines, claim windows, check-in windows, booking slots — are deterministic and testable. All endpoints are mounted at the server root path.

The readership is the engineering team implementing the service. Contract-level concerns (envelopes, pagination, identifiers, concurrency, validation order) appear in Section 2; business workflows, with their rules deliberately woven into narrative context, appear in Section 3; Section 4 summarizes the endpoint surface; Section 5 catalogs the error identifiers.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles, spelled exactly, are `RegionalAdmin`, `StoreManager`, `StoreAssociate`, `Customer`, and `Anonymous`. When the role is syntactically valid but not permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The role model is hierarchical: `RegionalAdmin` can perform every `StoreManager` operation plus its own exclusive operations (driving the logical clock, creating stores, creating campaigns, verifying, activating, and cancelling campaigns); `StoreManager` can perform every `StoreAssociate` operation plus its own (staging bays, hatchery schedules, livestock lots, mortality-claim review, weighted-sale voids, account status changes, service events, and the teardown/complete-reset campaign steps); `StoreAssociate` covers the front-line writes (care logs, weighted sale creation and finalization, brooder verification, fulfillment, ledger posting, receipt-free lookup, staging and load-out, event check-in); all three staff roles may use every read endpoint.

Role identity resolves as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `LoyaltyAccount`; ownership checks on any resource that references a `LoyaltyAccount` compare the resource's `loyalty_account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_IDENTITY` (HTTP 403). This ownership rule applies to creating chick orders, cancelling one's own chick order, opening mortality claims, creating pickup orders, requesting load-out assistance, cancelling one's own pickup order, creating event bookings, cancelling one's own booking, and reading one's own account. When `X-User-Role` is `RegionalAdmin`, `StoreManager`, `StoreAssociate`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `Anonymous` exists solely for public loyalty registration.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. List responses are always sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching records and `has_more` indicates whether additional records exist beyond the returned window.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — assigned at creation. Most resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at 1 and increments by exactly one on every mutation of that resource. Two resources are append-only logs and deliberately break this pattern: a `CareLogEntry` and a `LoyaltyLedgerEntry` each carry only `id` and `created_at`; neither has `updated_at` nor `version`, and neither can be modified after creation. Creating a new resource returns HTTP 201 with the created resource in the envelope; any operation that modifies an existing resource returns HTTP 200 with the updated resource.

### 2.5. The Logical Clock and Calendar Semantics

All temporal reasoning in the system — sale windows, freshness checks, deadlines, rolling windows, daily tallies — reads a single logical clock, never the host's wall clock. Before any clock-setting call is made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `RegionalAdmin` may advance the logical clock to a supplied `to_iso8601` instant through a dedicated administrative capability that answers 200 with the resulting `current_utc`. Phrases like "today" or "the current date" throughout this document mean the calendar date of the logical clock in UTC, and durations such as "48 hours" are measured against logical timestamps stored on resources.

### 2.6. Store Posture and Derived Store State

A `Store` is created by a `RegionalAdmin` from a `store_name` and a `region_code`; it begins life with `posture` equal to `OFFSEASON`, `active_campaign_id` null, and `version` 1. The `posture` field is an enumeration — `OFFSEASON`, `WINTER_HEATING`, `SPRING_PLANTING`, `FALL_FEED` — and it is never set directly: it is derived from the season of the store's currently `ACTIVE` `SeasonCampaign`, falling back to `OFFSEASON` when no campaign is active. Every recomputation of posture increments the store's `version` and refreshes its `updated_at`. The store resource also exposes `hazmat_gallons_used_today`, a computed tally of the propane gallons dispensed by all `FINALIZED` `PROPANE_EXCHANGE` weighted sales whose `finalized_at` calendar date (UTC, logical clock) equals the current logical date. Posture is load-bearing across the product: chick orders exist only under `SPRING_PLANTING`, the weighted-sale floor closes under `OFFSEASON`, feed accrual doubles under `FALL_FEED`, and offers key on the querying store's current posture.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client views with optimistic concurrency control, and only these two endpoints accept a version field.

Activating a season campaign requires the request to carry `expected_store_version`, the store `version` the client last observed. Because activation legitimately supersedes whatever campaign is currently `ACTIVE` on the store, a client whose observed store version no longer matches the store's current `version` is acting on an out-of-date view of which campaign is live; the activation is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412).

Creating a chick order requires the request to carry `expected_livestock_lot_version`, the lot `version` the client last observed. Because a reservation legitimately decrements the lot's sellable quantity, a client whose observed lot version no longer matches the lot's current `version` is deciding on an out-of-date view of remaining availability; the reservation is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Endpoints not named here do not take any version field.

### 2.8. Precision, Rounding, and Monetary Representation

Money is represented as integer cents everywhere — unit prices, order totals, sale totals, refunds, coupon values — with no fractional cents ever persisted. Wherever a computation produces a non-integer cent amount, it is rounded half-up to the nearest integer cent at a single, pinned point in the computation (per-calculation rounding points are stated with each calculation in Section 3). The mortality rate on a livestock lot is computed to 4 decimal places, rounded half-up. Propane gallons are computed to 2 decimal places, rounded half-up. Loyalty points are integers; any multiplication that yields a fractional point is rounded half-up to an integer.

### 2.9. Validation Order

When a request violates several rules at once, the error surfaced is determined by a fixed priority ladder, evaluated in ascending priority order. First (priority 0) the request shape is checked — required fields present, types correct, enum values valid — with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400); the receipt-free phone lookup belongs to this tier too, resolving the supplied phone to an account or failing with `ERR_PHONE_NOT_FOUND` (HTTP 404). Next come authentication context (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role permission (priority 2, `ERR_FORBIDDEN_ROLE`), and entity-backed identity (priority 3, `ERR_FORBIDDEN_IDENTITY`). Existence checks follow at priority 4: every resource identifier in the path, validated left to right, and then foreign-key identifiers in the body must resolve, or the request fails with the matching not-found identifier — `ERR_STORE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_PICKUP_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_BOOKING_NOT_FOUND` (all HTTP 404). Optimistic-concurrency staleness (priority 5) is evaluated next — deliberately before all other state and business checks, so a stale client view is always reported as staleness (`ERR_STALE_STORE_VERSION` or `ERR_STALE_LOT_VERSION`, HTTP 412) rather than being masked by a downstream failure. Store posture gates come at priority 6 (`ERR_POSTURE_NOT_SPRING_PLANTING`, `ERR_STORE_FLOOR_CLOSED`, HTTP 409), followed by resource state preconditions at priority 7 (the campaign, schedule, lot, order, sale, account, and event state errors, plus the generic `ERR_INVALID_STATE_TRANSITION`, HTTP 409). Safety rules — brooder checks, brooder freshness, care-log freshness, the hazmat cap, vaccine records — are priority 8 (HTTP 422). Temporal window and overlap rules are priority 9 (HTTP 409). Constraint rules — minimum purchase, capacities, uniqueness, tare feasibility, staging-bay availability, aisle counts, load-out gating — are priority 10 (HTTP 422 unless noted otherwise in Section 5). Fiscal sufficiency (priority 11, `ERR_INSUFFICIENT_POINTS`, HTTP 422) and referential integrity of reversal entries (priority 12, `ERR_ENTRY_NOT_FOUND`, `ERR_REVERSAL_MISMATCH`, HTTP 422) close the ladder.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Store and Running the Seasonal Campaign Cycle

Everything hangs off a store. A `RegionalAdmin` creates the store; from then on its commercial rhythm is driven by `SeasonCampaign` resources, each created in `DRAFT` for a `store_id`, declaring the `season` it installs (`WINTER_HEATING`, `SPRING_PLANTING`, or `FALL_FEED`), the serialized `planogram_map` describing the new layout, and the `aisle_count` the reset must touch (at least 1 aisle; a campaign created with fewer fails `ERR_INVALID_REQUEST`).

The reset itself is a store-floor operation. A `StoreManager` begins teardown, moving the campaign `DRAFT → TEARDOWN`; attempting this on a campaign not in `DRAFT` fails with `ERR_CAMPAIGN_NOT_IN_DRAFT`. When the crew finishes, the manager completes the reset by reporting the `aisles_reset_count`; this is accepted only from `TEARDOWN` (otherwise `ERR_CAMPAIGN_NOT_IN_TEARDOWN`) and only when the reported count exactly equals the campaign's `aisle_count` — a mismatch is rejected with `ERR_AISLE_COUNT_MISMATCH` and nothing changes. A successful completion moves the campaign `TEARDOWN → VERIFY_PENDING` and stores the reported count.

Audit is a regional function. A `RegionalAdmin` verifies the campaign with an `audit_passed` flag; this step requires `VERIFY_PENDING` status, failing otherwise with `ERR_CAMPAIGN_NOT_VERIFY_PENDING`. A passed audit moves the campaign `VERIFY_PENDING → READY`. A failed audit sends the campaign back `VERIFY_PENDING → TEARDOWN` and resets `aisles_reset_count` to 0, so the rework loop from teardown to verification may repeat as many times as needed.

Activation is the consequential step. A `RegionalAdmin` activates a `READY` campaign — any other status fails with `ERR_CAMPAIGN_NOT_READY` — and the request must carry the OCC field `expected_store_version` described in §2.7. A successful activation sets `activated_at` to the logical now and fires a five-hop cascade, each hop caused by the previous hop's mutation rather than by the activation call directly. First, any other `ACTIVE` campaign on the same store is superseded to `COMPLETED`. Second, the store's `posture` is recomputed to the new campaign's `season`, `active_campaign_id` points at the newly active campaign, and the store's `version` increments. Third, if the new posture is anything other than `SPRING_PLANTING`, every `PUBLISHED` hatchery schedule on the store is closed to `CLOSED`. Fourth, each such schedule closure forces every `ON_SALE` livestock lot beneath it to `SALE_CLOSED`. Fifth, each such lot closure expires every `RESERVED` or `BROODER_VERIFIED` chick order against the lot to `EXPIRED`, releasing its reserved quantity back into the lot's `quantity_on_hand`. All five hops complete atomically within the activation request.

A campaign that will not proceed can be cancelled by a `RegionalAdmin` from `DRAFT`, `TEARDOWN`, or `VERIFY_PENDING`, landing in `CANCELLED`; cancelling from any other state is an invalid transition rejected with `ERR_INVALID_STATE_TRANSITION`. `COMPLETED` and `CANCELLED` are terminal.

### 3.2. Hatchery Schedules and the Sanitization Gap

Chick days begin with a `HatcherySchedule`, created in `DRAFT` by a `StoreManager` for a store. The schedule declares the `species` (a code such as `CHICKEN_LAYER`, `CHICKEN_MEAT`, or `DUCK`) and `breed` label, the `hatch_date`, and the sale window: `sale_window_start` is the first instant birds may be sold and `sale_window_end` the last, both inclusive — a closed interval — with the end strictly after the start and the start no earlier than one day after the hatch date. The schedule also carries `daily_capacity`, the maximum birds reservable across all lots of this schedule per UTC calendar day (at least 1), `min_purchase_qty`, the minimum birds per order (at least 1), and `base_price_cents_per_bird`, the unit price before volume discount (at least 1 cent). Shape violations of these constraints are `ERR_INVALID_REQUEST`.

Publishing a schedule — a `StoreManager` action moving it `DRAFT → PUBLISHED`, failing with `ERR_SCHEDULE_NOT_DRAFT` from any other state — runs the sanitization-gap check. For the same store and the same `species`, the candidate's closed sale window must be separated from every other `PUBLISHED` schedule's closed window by a sanitization gap of at least 7 full days on both sides: either the candidate's `sale_window_start` falls at least 7 days after the other's `sale_window_end`, or the candidate's `sale_window_end` falls at least 7 days before the other's `sale_window_start`. Exactly 7 days of gap is allowed. Schedules in `DRAFT`, `CLOSED`, or `CANCELLED` are ignored by this check. A violation rejects the publish with `ERR_SCHEDULE_WINDOW_OVERLAP`.

Closing a schedule has two flavors, both performed by a `StoreManager`. A `PUBLISHED` schedule closes to `CLOSED` — attempted from any other status it fails with `ERR_SCHEDULE_NOT_PUBLISHED` — and the closure cascades: every `ON_SALE` lot under the schedule moves to `SALE_CLOSED`, and each lot closure expires its `RESERVED` and `BROODER_VERIFIED` chick orders to `EXPIRED` with the reserved quantity released back to `quantity_on_hand`. A schedule still in `DRAFT` can instead be cancelled by closing it with `reason` set to `CANCELLED`, moving it `DRAFT → CANCELLED` (this path likewise requires `DRAFT` and otherwise fails with `ERR_SCHEDULE_NOT_DRAFT`). Schedules also close without any explicit call when a posture flip cascades through them, as described in §3.1. `CLOSED` and `CANCELLED` are terminal.

### 3.3. Livestock Lots, Care Logs, and Quarantine

When birds arrive, a `StoreManager` receives a `LivestockLot` under a published schedule, providing the `store_id`, the `hatchery_schedule_id` of the schedule it was received under, the `quantity_received` (at least 1), and the `received_at` logical timestamp. The lot starts in `RECEIVING` with `quantity_sold`, `mortality_count`, and `quantity_quarantined` all 0, `health_flag` `NORMAL`, and `quantity_on_hand` initialized to `quantity_received`. Thereafter `quantity_on_hand` is a derived figure: the birds received minus those sold, minus mortality losses, minus those quarantined, minus those reserved but not yet fulfilled. A reservation decrements it; a cancellation restores it — except when the lot is `SUSPENDED`, in which case the released birds land in `quantity_quarantined` instead.

A lot goes on sale when a `StoreManager` opens it, moving `RECEIVING → ON_SALE`. Three preconditions guard this: the lot must be in `RECEIVING` (otherwise `ERR_LOT_NOT_RECEIVING`), its parent schedule must be `PUBLISHED` (otherwise `ERR_SCHEDULE_NOT_PUBLISHED`), and the logical now must fall inside the schedule's closed sale window (otherwise `ERR_OUTSIDE_SALE_WINDOW`).

While birds are on the floor, associates append `CareLogEntry` records to the lot. Each entry carries the `lot_id`, an `entry_type` of `FEEDING`, `WATER`, `TEMPERATURE`, or `MORTALITY`, and an optional free-text `note`. A `TEMPERATURE` entry must supply `measured_temp_f`, the brooder temperature in Fahrenheit; a `MORTALITY` entry must supply its `mortality_count` of at least 1 dead bird found. Missing required per-type fields are `ERR_INVALID_REQUEST`. Care logs are append-only: they can be listed (filterable by `entry_type`) but never edited.

Mortality entries drive the quarantine rule. Each `MORTALITY` entry adds its count to the lot's cumulative `mortality_count`, after which the lot's `mortality_rate` is recomputed as the cumulative mortality divided by `quantity_received`, rounded half-up to 4 decimal places. When the recomputed rate is strictly greater than 0.05 — a rate of exactly 0.05 does not trigger anything — the lot is quarantined: it transitions `ON_SALE → SUSPENDED`, its `health_flag` becomes `QUARANTINED`, and every `RESERVED` or `BROODER_VERIFIED` chick order against the lot is cancelled by the system with cause quarantine. Those cancellations release their reserved birds into `quantity_quarantined`, not back to `quantity_on_hand`, and each affected order's loyalty account receives an `ADJUSTMENT` ledger entry of +500 goodwill points.

A `StoreManager` closes a lot's sale from `ON_SALE` or from `SUSPENDED`, moving it to `SALE_CLOSED`; attempted from any other state the call fails with `ERR_INVALID_STATE_TRANSITION`. Closing from `ON_SALE` — whether by explicit call or by schedule-closure or posture-flip cascade — expires every `RESERVED` or `BROODER_VERIFIED` chick order against the lot, releasing the reserved birds back to `quantity_on_hand`. A final call on a `SALE_CLOSED` lot with `disposition` set true moves the lot to `DISPOSITIONED`, which is terminal.

### 3.4. Chick Orders from Reservation to Fulfillment

Chick orders are a `Customer`-only affair, and they exist only in spring: creating one requires the selling store's posture to be `SPRING_PLANTING`, failing otherwise with `ERR_POSTURE_NOT_SPRING_PLANTING`. The customer posts the `store_id`, the `livestock_lot_id` of the lot the birds come from, their own `loyalty_account_id` (which must match `X-User-ID` per the identity rule), the `quantity`, the intended `pickup_date`, and the OCC field `expected_livestock_lot_version` (§2.7). The target lot must be `ON_SALE`; reserving against a lot in any other state — including a `SUSPENDED` quarantined lot — fails with `ERR_LOT_NOT_ON_SALE`. The logical now at the moment of reservation must fall inside the schedule's closed sale window, and the `pickup_date` must likewise fall inside the schedule's closed sale window; either violation fails with `ERR_OUTSIDE_SALE_WINDOW`. The `quantity` must meet the schedule's `min_purchase_qty` (otherwise `ERR_MIN_PURCHASE_NOT_MET`), must not push the birds reserved across all lots of that schedule past its `daily_capacity` for the current UTC date (otherwise `ERR_DAILY_CAPACITY_EXCEEDED`), and must not exceed the lot's `quantity_on_hand` (otherwise `ERR_LOT_CAPACITY_EXCEEDED`).

A successful reservation lands in `RESERVED`. The system snapshots `unit_price_cents` from the schedule's `base_price_cents_per_bird`, computes the volume discount bracket, and stores the line total. The bracket keys on quantity: no discount — `discount_pct` 0.00 — for 24 birds or fewer; `discount_pct` 0.10 for 25 through 49 birds; `discount_pct` 0.15 for 50 birds or more. The `total_cents` is the quantity multiplied by the snapshotted unit price, multiplied by one minus the discount percentage, rounded half-up to integer cents; each order is a single line, so this line-level rounding happens exactly once before any summation. The reservation decrements the lot's `quantity_on_hand` by the ordered quantity and increments the lot's `version` by 1.

Before birds leave the store, the customer's home setup is verified. A `StoreAssociate` runs brooder verification on a `RESERVED` order (any other state fails with `ERR_ORDER_NOT_RESERVED`), submitting three flags — `heat_lamp_ok`, `thermometer_ok`, and `bedding_ok`. All three must be true; any false flag rejects the verification with `ERR_BROODER_CHECK_FAILED`. A successful verification moves the order `RESERVED → BROODER_VERIFIED` and stamps `brooder_verified_at` with the logical now.

Fulfillment is the most heavily guarded transition in the system, and its checks interlock. A `StoreAssociate` fulfills a `BROODER_VERIFIED` order. An order still in `RESERVED` fails with `ERR_ORDER_NOT_VERIFIED`; an order that a cascade has already moved to `CANCELLED` or `EXPIRED` fails with `ERR_INVALID_STATE_TRANSITION`. The brooder verification must still be fresh: if the logical now is more than 72 hours past `brooder_verified_at`, the order reverts `BROODER_VERIFIED → RESERVED`, `brooder_verified_at` is cleared to null, and the call fails with `ERR_BROODER_VERIFICATION_EXPIRED`. The lot must be `ON_SALE` at fulfill time (otherwise `ERR_LOT_NOT_ON_SALE`). Fulfillment is permitted up to 48 hours past the schedule's `sale_window_end` as a grace window; past that grace the order transitions to `EXPIRED` and the call fails with `ERR_SALE_WINDOW_CLOSED`. Finally, the lot must show a fresh care log — at least one `CareLogEntry` created within the last 12 hours — failing which the call is rejected with `ERR_CARE_LOG_STALE`. A successful fulfillment stamps `fulfilled_at`, adds the order's quantity to the lot's `quantity_sold`, and leaves `quantity_on_hand` unchanged, because the reservation simply converts to a sale.

Cancellation releases the reservation. A customer may cancel their own order, or a `StoreManager` may cancel any order, from `RESERVED` or `BROODER_VERIFIED` (any other state fails with `ERR_INVALID_STATE_TRANSITION`); the optional `reason` may be recorded. Cancellation from a healthy lot restores the quantity to `quantity_on_hand`; cancellation while the lot is `SUSPENDED` releases the birds into `quantity_quarantined` instead. When the cause is quarantine — the system-driven cancellation of §3.3 — the order's account additionally receives the +500 goodwill `ADJUSTMENT`. Orders expire to `EXPIRED` without any call when their lot closes beneath them or when a fulfillment attempt outlives the sale-window grace, and such expiries release the reserved quantity back to `quantity_on_hand`. `FULFILLED`, `CANCELLED`, and `EXPIRED` are terminal.

### 3.5. Post-Purchase Mortality Claims

Chicks carry a mortality guarantee. On a `FULFILLED` order, the customer who owns it may open a claim by submitting a `mortality_count` — the birds that died after purchase. The claim must be opened within 48 hours of `fulfilled_at`; a later attempt fails with `ERR_CLAIM_WINDOW_EXPIRED`. The claimed count must not exceed the order's `quantity` minus its already-`approved_claim_count`; an over-claim fails with `ERR_CLAIM_EXCEEDS_REMAINING`. An opened claim moves `claim_status` from `NONE` to `CLAIMED` and records the count in `claimed_mortality_count`. The claim itself is a creation (HTTP 201) even though the returned resource is the order.

A `StoreManager` then reviews the open claim with a `decision`. Rejection moves `claim_status` to `REJECTED` with no financial effect. Approval computes the remedy: the `refund_cents` for the claim is the order's `total_cents` multiplied by the `claimed_mortality_count` and divided by the order's `quantity`, rounded half-up to integer cents; goodwill points equal the refund in cents divided by 100, rounded down to a whole point. Approval moves `claim_status` to `APPROVED`, adds the claimed count into `approved_claim_count`, accumulates the refund into the order's `refund_cents`, and posts an `ADJUSTMENT` ledger entry for the goodwill points to the order's loyalty account.

### 3.6. Weighted Sales: Bulk Feed and Propane Exchange

The bulk station sells by weight, and it sells only when the floor is open: creating a `WeightedSale` requires the store's posture to be anything other than `OFFSEASON` — with no `ACTIVE` campaign the floor is closed and creation fails with `ERR_STORE_FLOOR_CLOSED`. A `StoreAssociate` creates the sale with the `store_id`, a `sale_kind` of `FEED_BULK` or `PROPANE_EXCHANGE`, the `container_class` tare class, the scale's `gross_weight_lbs` (which must be greater than 0), and optionally a `loyalty_account_id` for points. The container classes are `BAG_50`, `DRUM`, `TOTE`, and `CYLINDER_20`; a propane exchange must use `CYLINDER_20`, and any other class on a `PROPANE_EXCHANGE` sale fails `ERR_INVALID_REQUEST`.

Creation prices provisionally and lands the sale in `PROVISIONAL`. The `provisional_tare_lbs` comes from the standard class table — 2 pounds for `BAG_50`, 20 for `DRUM`, 60 for `TOTE`, 17 for `CYLINDER_20` — and the net weight is the gross minus that standard tare. For `FEED_BULK`, the net pounds price through marginal tiers at per-pound cent rates: the first 50 pounds at 40 cents per pound, the next 150 pounds at 35 cents per pound, and everything beyond 200 pounds at 30 cents per pound, summed across tiers. For `PROPANE_EXCHANGE`, the dispensed gallons are the net pounds divided by 4.24 pounds per gallon, capped at 20.0 gallons and rounded half-up to 2 decimal places; the price is a flat 1999 cents for the exchange plus the gallons multiplied by 349 cents per gallon, rounded half-up. In both kinds the components sum and the final figure rounds half-up to integer cents, stored as `provisional_total_cents`. The computed `propane_gallons` — the capped, rounded gallon figure — is stored on the sale for a propane exchange and is 0 for a feed sale.

Finalization re-prices against reality. A `StoreAssociate` finalizes a `PROVISIONAL` sale (any other status fails with `ERR_SALE_NOT_PROVISIONAL`, and the same error guards voiding) by recording the `measured_tare_lbs` — the actual container weight, which must be greater than 0 and no greater than the `gross_weight_lbs`, failing otherwise with `ERR_TARE_EXCEEDS_GROSS`. The final price uses the identical tier structure as the provisional price but with the net weight computed from the measured tare, so identical gross weights can price differently once the true tare is known. The evaluation order is pinned: first the net weight, then the tier-or-gallon price, then the rounding to integer cents, then the point-redemption subtraction. For a propane exchange, a safety cap interposes before money moves: the store's `hazmat_gallons_used_today` plus this sale's `propane_gallons` must not exceed the daily hazmat cap of 40 gallons, or finalization fails with `ERR_HAZMAT_DAILY_CAP_EXCEEDED`. These checks surface in the global validation order of §2.9 — sale state first, then the hazmat safety cap, then tare feasibility, then point sufficiency.

Points enter at finalize. The request may carry `redeem_points` (default 0); any positive redemption requires a `loyalty_account_id` on the sale and that account in `ACTIVE` status — otherwise `ERR_ACCOUNT_SUSPENDED` — and the requested points must not exceed the account's `points_balance`, failing with `ERR_INSUFFICIENT_POINTS`. Each point is worth one cent of discount: the `final_total_cents` is the computed price minus the redeemed points, floored at zero, and the sale stamps `finalized_at` and moves `PROVISIONAL → FINALIZED`. Two ledger writes follow atomically when an account is attached: a `REDEMPTION` entry debiting the redeemed points (recorded on the sale as `points_redeemed`), and an `ACCRUAL` entry on the net-of-redemption amount — the sale's `final_total_cents`, which is already the price minus the redeemed points and is not reduced by `points_redeemed` a second time — with `earn_context` `FEED` for a feed sale or `FUEL` for a propane exchange, posted against the sale's store. Finalizing a propane exchange also feeds the store's `hazmat_gallons_used_today` tally. A `StoreManager` may instead void a `PROVISIONAL` sale, moving it to `VOIDED` with no financial effect; `FINALIZED` and `VOIDED` are terminal.

### 3.7. Loyalty Accounts, Points, Tiers, and Offers

Membership is public and receipt-free. An `Anonymous` caller registers a `LoyaltyAccount` with a `full_name`, a `phone`, and an optional `email`; the phone must be unique across all accounts, with a duplicate rejected as `ERR_PHONE_ALREADY_REGISTERED`. A new account starts `ACTIVE` with `tier` `NEIGHBOR` and `points_balance` 0. At the register, an associate finds the member by phone through the receipt-free lookup, which returns the account or fails with `ERR_PHONE_NOT_FOUND`. A `StoreManager` manages account standing through a status-setting operation taking a `status` value: `ACTIVE` suspends to `SUSPENDED`, `SUSPENDED` reactivates to `ACTIVE`, and `ACTIVE` closes to `CLOSED`, which is terminal; any other from-to combination fails with `ERR_INVALID_STATE_TRANSITION`.

All point movement flows through `LoyaltyLedgerEntry` records, appended by associates against an `account_id`. Appending an entry through this endpoint requires the account to be `ACTIVE`; posting against a `SUSPENDED` or `CLOSED` account fails with `ERR_ACCOUNT_SUSPENDED`. There are four `entry_type` values. An `ACCRUAL` requires a `store_id`, a `base_amount_cents` purchase subtotal greater than 0, and an `earn_context` of `FEED`, `FUEL`, or `OTHER`; its `points_delta` is computed, never supplied. A `REDEMPTION` requires a `store_id` and takes its `points_delta` from the client, which must be negative. An `ADJUSTMENT` takes its `points_delta` from the client. A `REVERSAL` requires a `related_entry_id` referencing an existing entry of the same account — a dangling or cross-account reference fails with `ERR_ENTRY_NOT_FOUND` — and its supplied `points_delta` must carry the opposite sign of the referenced entry and must not exceed that entry's remaining unreversed magnitude, failing otherwise with `ERR_REVERSAL_MISMATCH`. Missing or malformed per-type fields are `ERR_INVALID_REQUEST`. Every entry records `counts_toward_tier` — true for `ACCRUAL` and `REVERSAL`, false for `REDEMPTION` and `ADJUSTMENT` — and snapshots `posture_at_entry`, the posting store's posture at creation time (`OFFSEASON` when `store_id` is absent). Entries are append-only.

Accrual points are computed in a pinned order that resolves an otherwise circular dependency between points and tier. First, base points are the `base_amount_cents` divided by 100, rounded down to a whole point; when the floored base points are zero (for example, a system-driven accrual on a small net amount), the entry earns 0 points — the computation never yields a negative `points_delta`. Second, the tier multiplier is read from the account's tier as it stands before this entry is posted: 1.0 for `NEIGHBOR`, 1.25 for `RANCH_HAND`, 1.5 for `HOMESTEAD`. Third, a posture multiplier of 2.0 applies when the entry's `earn_context` is `FEED` and the posting store's posture at entry-creation time is `FALL_FEED`; otherwise the posture multiplier is 1.0. Fourth, the `points_delta` is the base points multiplied by both multipliers, rounded half-up to an integer. Only after the entry posts is the tier re-evaluated — so a tier crossing triggered by this entry never retroactively changes this entry's points; it applies to future purchases.

Tier re-evaluation runs after every ledger write of any type. The account's `tier_qualifying_points` is the sum of `points_delta` over all of the account's entries where `counts_toward_tier` is true and the entry's `created_at` falls within the rolling window from 365 days before the logical now through the logical now, both bounds inclusive. The resulting `tier` is `HOMESTEAD` when qualifying points reach at least 7500, `RANCH_HAND` when they reach at least 2500, and `NEIGHBOR` otherwise; the boundary is inclusive, so exactly 2500 promotes while 2499 does not. The `points_balance`, by contrast, is the plain sum of `points_delta` over all ledger entries regardless of age or tier-counting, and it is never allowed to go negative — redemptions are validated against it before posting.

Offers answer a different question than tier. When an associate or the member queries an account's offers at a specific store (identified by the `store_id` query input), the system computes a season-scoped qualifying total: the sum of `points_delta` over the account's `ACCRUAL` entries whose `posture_at_entry` equals the querying store's current posture — reversals do not count here, and the same purchase history can therefore make a member offer-eligible while their rolling-365-day tier stays `NEIGHBOR`. The response carries `season_qualifying_points`, a `fuel_discount_cents_per_gal` equal to 5 cents for each full 500-point step of the season total, capped at 50 cents per gallon, a `feed_coupon_cents` of 1000 cents when the store's posture is `FALL_FEED` and the account's tier is `RANCH_HAND` or `HOMESTEAD` (0 otherwise), and an `eligible` flag that is true when either the fuel discount or the feed coupon is greater than zero.

### 3.8. Buy-Online-Pickup-In-Store and the Staging Bays

Oversized items ride a two-dimensional order. A `Customer` places a `PickupOrder` with the `store_id`, their `loyalty_account_id`, the `item_sku`, the `item_size_class` (`M`, `L`, or `XL`), and `requires_loadout_assistance`, true when the customer needs an associate's help loading out. The order begins with `fulfillment_status` `PLACED` and `loadout_status` `NOT_REQUIRED` — two parallel dimensions that evolve independently until the fulfillment dimension reaches a terminal state (`COMPLETED`, `CANCELLED`, or `EXPIRED`), at which point the load-out dimension freezes with it.

Staging allocates physical space. A `StoreAssociate` stages a `PLACED` order, and the system selects a staging bay from the order's store: eligible bays are `AVAILABLE` and have a `size_class` large enough for the item, with capacity ordered `M` smaller than `L` smaller than `XL` — a bay holds anything its own size or smaller. Among eligible bays the smallest sufficient one wins, and ties break by ascending `bay_no`. An empty pool rejects the stage outright with `ERR_NO_STAGING_BAY_AVAILABLE`; there is no queuing. A successful stage records the chosen `staging_bay_id`, marks the bay `OCCUPIED`, and moves the order `PLACED → STAGED`. Bay numbers are unique per store — creating a bay with a taken `bay_no` fails with `ERR_BAY_NO_TAKEN` — and a `StoreManager` manages bay availability directly, setting a bay's `status` to `AVAILABLE` or `OUT_OF_SERVICE`; the `OCCUPIED` state is never set by hand, only by staging.

Readiness starts the pickup clock. A `StoreAssociate` marks a `STAGED` order ready, stamping `ready_at` with the logical now and computing the `pickup_deadline` as exactly 5 days later, moving the order `STAGED → READY_FOR_PICKUP`. Completion, also by an associate, requires the order still `READY_FOR_PICKUP` and respects both dimensions: if the load-out dimension sits at `ASSISTANCE_REQUESTED`, completion is refused with `ERR_LOADOUT_NOT_COMPLETED` until the load-out is done; and if the logical now has passed the `pickup_deadline`, the order transitions to `EXPIRED`, its bay is released back to `AVAILABLE`, and the call fails with `ERR_PICKUP_WINDOW_EXPIRED`. A clean completion moves the order `READY_FOR_PICKUP → COMPLETED` and releases the bay to `AVAILABLE`.

Load-out assistance is requested by the customer on their own order, but only once it is `READY_FOR_PICKUP`, only when `requires_loadout_assistance` was declared true at placement (otherwise `ERR_LOADOUT_NOT_APPLICABLE`), and only while the load-out dimension is `NOT_REQUIRED`; the request moves it to `ASSISTANCE_REQUESTED`. An associate then completes the load-out, moving the load-out dimension from `ASSISTANCE_REQUESTED` to `LOADOUT_DONE`, again only while the order is `READY_FOR_PICKUP`. Cancellation is available to the owning customer or a `StoreManager` from `PLACED`, `STAGED`, or `READY_FOR_PICKUP` — any other fulfillment state fails with `ERR_INVALID_STATE_TRANSITION` — and cancelling a staged or ready order releases its bay to `AVAILABLE`.

### 3.9. In-Store Service Events and Bookings

Stores host two kinds of bookable happenings. A `StoreManager` creates a `ServiceEvent` in `DRAFT` with the `store_id`, an `event_kind` of `PET_WASH` or `VET_CLINIC`, a `resource_name` identifying the physical resource (say, a particular wash bay or clinic room), the `event_date` (the calendar date at midnight UTC), the bookable window `slot_window_start` through `slot_window_end` (the end being an exclusive upper bound for slot ends), the `slot_length_minutes` of each booking (at least 5 minutes), a `cleanup_buffer_minutes` gap mandated around each booking's occupancy (0 for open resources), the `capacity_per_slot` maximum overlapping bookings (at least 1), and `requires_vaccine_record` for vet clinics that demand confirmed vaccination. Publishing moves the event `DRAFT → PUBLISHED`; any other source state fails with `ERR_INVALID_STATE_TRANSITION`.

A `Customer` books a slot on a published event — booking against an event that is not `PUBLISHED` fails with `ERR_EVENT_NOT_PUBLISHED` — supplying the `service_event_id`, their `loyalty_account_id`, the `slot_start`, and, when the event requires it, `vaccine_record_confirmed` set true (absent that confirmation on a requiring event, the booking fails with `ERR_VACCINE_RECORD_REQUIRED`). The `slot_start` must fall on the `event_date`, must not precede `slot_window_start`, and the slot it opens must end no later than `slot_window_end`; the `slot_end` itself is computed as the start plus the event's slot length. Shape violations of these bounds are `ERR_INVALID_REQUEST`.

Overlap rules differ by event kind, and both kinds treat bookings in `BOOKED` or `CHECKED_IN` status as occupying the resource, with occupancy shared across all same-store events that share the `resource_name`. For a `PET_WASH`, slots are half-open intervals: a booking occupies from its start up to but not including its end, so a booking starting exactly when another ends does not overlap, and the candidate is rejected with `ERR_BOOKING_OVERLAP` only when the number of already-occupying bookings whose start precedes the candidate's end and whose end follows the candidate's start reaches the event's `capacity_per_slot`. For a `VET_CLINIC`, capacity is always 1 and occupancy is buffered: each booking effectively occupies from `cleanup_buffer_minutes` before its start to `cleanup_buffer_minutes` after its end, and any non-empty intersection between the candidate's effective occupancy and an existing booking's effective occupancy rejects the booking with `ERR_BOOKING_OVERLAP` — the buffer therefore forbids back-to-back slots entirely.

On the day, an associate checks in a `BOOKED` booking within a window that opens 15 minutes before `slot_start` and closes at `slot_end`; outside that window the attempt fails with `ERR_OUTSIDE_CHECKIN_WINDOW`. A checked-in booking completes to `COMPLETED`. A booking that never showed can be marked `NO_SHOW` once the logical now has passed `slot_end`; marking earlier fails with `ERR_BOOKING_NOT_EXPIRED`. The owning customer or a `StoreManager` may cancel a `BOOKED` booking to `CANCELLED`; other states refuse with `ERR_INVALID_STATE_TRANSITION`. On the event side, a `StoreManager` may cancel a `DRAFT` or `PUBLISHED` event, and cancelling a `PUBLISHED` event cascades: every `BOOKED` or `CHECKED_IN` booking on it is cancelled by the system. An event also completes on its own — at read time, once the logical now has passed `slot_window_end` and no `BOOKED` or `CHECKED_IN` bookings remain, the event reads as `COMPLETED`. `COMPLETED` and `CANCELLED` are terminal for events, and `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal for bookings.

## 4. Endpoint Definitions

All endpoints live under the server root. Operations that create a new resource respond 201; operations that modify an existing resource, trigger a state transition, or perform a computation without creating a resource respond 200. Every response uses the envelope of §2.2, list endpoints paginate per §2.3, and authorization follows §2.1 with failures surfaced per the priority ladder of §2.9. Request payloads, computed fields, side effects, and error triggers are specified in the narratives of §2 and §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock to a supplied instant | RegionalAdmin |
| POST | /stores | Create a store (posture OFFSEASON, version 1) | RegionalAdmin |
| GET | /stores | List stores | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /stores/{id} | Get a store, including computed posture and hazmat tally | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /season-campaigns | Create a planogram-reset campaign in DRAFT | RegionalAdmin |
| GET | /season-campaigns | List campaigns, filterable by store and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /season-campaigns/{id} | Get a campaign | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /season-campaigns/{id}/begin-teardown | Move a campaign DRAFT to TEARDOWN | StoreManager, RegionalAdmin |
| POST | /season-campaigns/{id}/complete-reset | Report reset aisle count; TEARDOWN to VERIFY_PENDING | StoreManager, RegionalAdmin |
| POST | /season-campaigns/{id}/verify | Audit a reset; pass to READY or fail back to TEARDOWN | RegionalAdmin |
| POST | /season-campaigns/{id}/activate | Activate a READY campaign; supersedes the live campaign and fires the posture cascade | RegionalAdmin |
| POST | /season-campaigns/{id}/cancel | Cancel a campaign in DRAFT, TEARDOWN, or VERIFY_PENDING | RegionalAdmin |
| POST | /staging-bays | Create a staging bay (bay number unique per store) | StoreManager, RegionalAdmin |
| GET | /staging-bays | List bays, filterable by store and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /staging-bays/{id} | Get a staging bay | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /staging-bays/{id}/set-status | Set a bay AVAILABLE or OUT_OF_SERVICE | StoreManager, RegionalAdmin |
| POST | /hatchery-schedules | Create a chick-days hatchery schedule in DRAFT | StoreManager, RegionalAdmin |
| GET | /hatchery-schedules | List schedules, filterable by store, species, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /hatchery-schedules/{id} | Get a hatchery schedule | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /hatchery-schedules/{id}/publish | Publish a schedule, enforcing the sanitization gap | StoreManager, RegionalAdmin |
| POST | /hatchery-schedules/{id}/close | Close a PUBLISHED schedule (cascading) or cancel a DRAFT one | StoreManager, RegionalAdmin |
| POST | /livestock-lots | Receive a lot under a published schedule | StoreManager, RegionalAdmin |
| GET | /livestock-lots | List lots, filterable by store, schedule, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /livestock-lots/{id} | Get a lot, including computed on-hand and mortality rate | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /livestock-lots/{id}/open-sale | Move a lot RECEIVING to ON_SALE within its sale window | StoreManager, RegionalAdmin |
| POST | /livestock-lots/{id}/close-sale | Close a lot's sale; with disposition, move SALE_CLOSED to DISPOSITIONED | StoreManager, RegionalAdmin |
| POST | /livestock-lots/{id}/care-logs | Append a care log entry; mortality entries drive quarantine | StoreAssociate, StoreManager, RegionalAdmin |
| GET | /livestock-lots/{id}/care-logs | List a lot's care log entries, filterable by type | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /chick-orders | Reserve birds against a lot with OCC on the lot version | Customer |
| GET | /chick-orders | List chick orders, filterable by store, lot, account, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /chick-orders/{id} | Get a chick order | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /chick-orders/{id}/verify-brooder | Verify the home brooder; RESERVED to BROODER_VERIFIED | StoreAssociate, StoreManager |
| POST | /chick-orders/{id}/fulfill | Fulfill a verified order under freshness, window, and care checks | StoreAssociate, StoreManager |
| POST | /chick-orders/{id}/cancel | Cancel a reserved or verified order, releasing the reservation | Customer, StoreManager |
| POST | /chick-orders/{id}/mortality-claims | Open a mortality guarantee claim on a fulfilled order | Customer |
| POST | /chick-orders/{id}/review-mortality-claim | Approve (refund plus goodwill) or reject an open claim | StoreManager |
| POST | /weighted-sales | Create a bulk feed or propane exchange sale with provisional pricing | StoreAssociate, StoreManager |
| GET | /weighted-sales | List weighted sales, filterable by store, account, kind, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /weighted-sales/{id} | Get a weighted sale | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /weighted-sales/{id}/finalize | Record measured tare, compute the final price, redeem and accrue points | StoreAssociate, StoreManager |
| POST | /weighted-sales/{id}/void | Void a provisional sale | StoreManager, RegionalAdmin |
| POST | /loyalty-accounts | Register a loyalty account; phone must be unique | Anonymous |
| GET | /loyalty-accounts | List accounts, filterable by phone and status | RegionalAdmin, StoreManager, StoreAssociate |
| GET | /loyalty-accounts/{id} | Get an account; a Customer may read only their own | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /loyalty-accounts/lookup | Receipt-free lookup of an account by phone | StoreAssociate, StoreManager |
| POST | /loyalty-accounts/{id}/ledger-entries | Append a ledger entry; accrual computes points and re-evaluates tier | StoreAssociate, StoreManager |
| GET | /loyalty-accounts/{id}/ledger-entries | List an account's ledger entries, filterable by type | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /loyalty-ledger-entries | List ledger entries, filterable by account, store, and related entry | RegionalAdmin, StoreManager, StoreAssociate |
| GET | /loyalty-ledger-entries/{id} | Get a single ledger entry | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /loyalty-accounts/{id}/offers | Compute fuel-and-feed offer eligibility at a given store | StoreAssociate, StoreManager, Customer |
| POST | /loyalty-accounts/{id}/set-status | Suspend, reactivate, or close an account | StoreManager, RegionalAdmin |
| POST | /pickup-orders | Place a BOPIS order for an oversized item | Customer |
| GET | /pickup-orders | List pickup orders, filterable by store, account, bay, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /pickup-orders/{id} | Get a pickup order | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /pickup-orders/{id}/stage | Stage an order, allocating the smallest sufficient available bay | StoreAssociate, StoreManager |
| POST | /pickup-orders/{id}/mark-ready | Mark a staged order ready; starts the 5-day pickup deadline | StoreAssociate, StoreManager |
| POST | /pickup-orders/{id}/request-loadout | Request associate load-out assistance on a ready order | Customer |
| POST | /pickup-orders/{id}/complete-loadout | Complete a requested load-out | StoreAssociate, StoreManager |
| POST | /pickup-orders/{id}/complete | Complete pickup before the deadline, releasing the bay | StoreAssociate, StoreManager |
| POST | /pickup-orders/{id}/cancel | Cancel a placed, staged, or ready order, releasing any bay | Customer, StoreManager |
| POST | /service-events | Create a pet wash or vet clinic event in DRAFT | StoreManager, RegionalAdmin |
| GET | /service-events | List events, filterable by store, kind, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /service-events/{id} | Get a service event | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /service-events/{id}/publish | Publish an event for booking | StoreManager, RegionalAdmin |
| POST | /service-events/{id}/cancel | Cancel an event; cancels its non-terminal bookings | StoreManager, RegionalAdmin |
| POST | /event-bookings | Book a slot on a published event under overlap and vaccine rules | Customer |
| GET | /event-bookings | List bookings, filterable by event, account, and status | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| GET | /event-bookings/{id} | Get a booking | RegionalAdmin, StoreManager, StoreAssociate, Customer |
| POST | /event-bookings/{id}/check-in | Check in a booking within its arrival window | StoreAssociate, StoreManager |
| POST | /event-bookings/{id}/complete | Complete a checked-in booking | StoreAssociate, StoreManager |
| POST | /event-bookings/{id}/mark-no-show | Mark a booking no-show once its slot has passed | StoreAssociate, StoreManager |
| POST | /event-bookings/{id}/cancel | Cancel a booked slot | Customer, StoreManager |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_FORBIDDEN_IDENTITY | 403 |
| ERR_STORE_NOT_FOUND | 404 |
| ERR_CAMPAIGN_NOT_FOUND | 404 |
| ERR_BAY_NOT_FOUND | 404 |
| ERR_SCHEDULE_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_ENTRY_NOT_FOUND | 404 |
| ERR_PICKUP_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_PHONE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_STORE_VERSION | 412 |
| ERR_STALE_LOT_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_CAMPAIGN_NOT_IN_DRAFT | 409 |
| ERR_CAMPAIGN_NOT_IN_TEARDOWN | 409 |
| ERR_CAMPAIGN_NOT_VERIFY_PENDING | 409 |
| ERR_CAMPAIGN_NOT_READY | 409 |
| ERR_SCHEDULE_NOT_DRAFT | 409 |
| ERR_SCHEDULE_NOT_PUBLISHED | 409 |
| ERR_POSTURE_NOT_SPRING_PLANTING | 409 |
| ERR_STORE_FLOOR_CLOSED | 409 |
| ERR_LOT_NOT_RECEIVING | 409 |
| ERR_LOT_NOT_ON_SALE | 409 |
| ERR_ORDER_NOT_RESERVED | 409 |
| ERR_ORDER_NOT_VERIFIED | 409 |
| ERR_SALE_NOT_PROVISIONAL | 409 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_EVENT_NOT_PUBLISHED | 409 |
| ERR_BROODER_CHECK_FAILED | 422 |
| ERR_BROODER_VERIFICATION_EXPIRED | 422 |
| ERR_CARE_LOG_STALE | 422 |
| ERR_HAZMAT_DAILY_CAP_EXCEEDED | 422 |
| ERR_VACCINE_RECORD_REQUIRED | 422 |
| ERR_OUTSIDE_SALE_WINDOW | 409 |
| ERR_SALE_WINDOW_CLOSED | 409 |
| ERR_CLAIM_WINDOW_EXPIRED | 422 |
| ERR_PICKUP_WINDOW_EXPIRED | 409 |
| ERR_SCHEDULE_WINDOW_OVERLAP | 409 |
| ERR_BOOKING_OVERLAP | 409 |
| ERR_OUTSIDE_CHECKIN_WINDOW | 409 |
| ERR_BOOKING_NOT_EXPIRED | 409 |
| ERR_MIN_PURCHASE_NOT_MET | 422 |
| ERR_DAILY_CAPACITY_EXCEEDED | 422 |
| ERR_LOT_CAPACITY_EXCEEDED | 422 |
| ERR_CLAIM_EXCEEDS_REMAINING | 422 |
| ERR_TARE_EXCEEDS_GROSS | 422 |
| ERR_NO_STAGING_BAY_AVAILABLE | 422 |
| ERR_PHONE_ALREADY_REGISTERED | 409 |
| ERR_BAY_NO_TAKEN | 409 |
| ERR_AISLE_COUNT_MISMATCH | 422 |
| ERR_LOADOUT_NOT_APPLICABLE | 422 |
| ERR_LOADOUT_NOT_COMPLETED | 409 |
| ERR_INSUFFICIENT_POINTS | 422 |
| ERR_REVERSAL_MISMATCH | 422 |
