# Drinkware Customization & Dealer Channel API — Product Requirements Document

## 1. Introduction

A premium drinkware and cooler brand runs two businesses that constantly pull on each other: a direct customization program that prints corporate and individual buyers' artwork onto tumblers, coolers, and soft goods, and a wholesale dealer channel that expects launch product to be allocated fairly and protected from unauthorized online resellers. This document specifies the API that operates both. It covers customization order intake with artwork proofing and print-capacity scheduling, the seasonal colorway-drop calendar with its dealer allocation mechanics, dealer authorization built on physical storefront inspection, marketplace enforcement with infraction points, and warranty claim handling across direct and dealer-sold items.

Several pressures shape the design. Personalized goods cannot be restocked, so the return policy is deliberately narrow and every returned unit is written off rather than returned to inventory. Corporate gifting concentrates demand into a year-end peak window, so pricing, dealer scoring, and capacity booking all behave differently inside that season. Dealer trust is managed quantitatively: confirmed marketplace violations accumulate infraction points that tighten a dealer's standing automatically, while restoration of standing is always an explicit human act. All time in the system flows through a single logical clock so that allocation windows, warranty expiry, return windows, and lazy status transitions are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or whose role value is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`. The system recognizes exactly nine roles: `PlatformAdmin`, `ChannelManager`, `FieldInspector`, `Dealer`, `Buyer`, `PrepressTech`, `ProductionLead`, `WarrantyAgent`, and `CustomerCare`. Each operation in §4 names the roles permitted to call it; an attempt to perform an action outside the caller's designated role, or to act on a resource the caller does not own where ownership applies, is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Dealer` record; ownership checks on any resource that references a dealer — the dealer's own record, its applications, its launch allocations — compare the resource's dealer foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ChannelManager`, `FieldInspector`, `Buyer`, `PrepressTech`, `ProductionLead`, `WarrantyAgent`, or `CustomerCare`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `inspector_user_id` on a `DealerApplication`, as `submitted_by` on an `ArtworkProof`, or as `docs_reviewed_by` — but does not compare it to any entity's `id`.

Even for opaque identities, three ownership rules are enforced. A `Dealer` role caller may act only on its own dealer record and on applications and allocations belonging to that dealer. A `Buyer` role caller may act only on customization orders, artwork proofs, and warranty claims whose `buyer_ref` equals the caller's `X-User-ID`. A `FieldInspector` role caller may schedule and record only inspections assigned to them, meaning the application's `inspector_user_id` equals the caller's `X-User-ID`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock; entity timestamps such as `created_at` and `updated_at` instead read the logical clock of §2.4.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties keeping creation order. Where an endpoint documents filter query parameters, several supplied filters combine conjunctively, and a filter value matching nothing simply yields an empty page — filter values are not validated against enum sets. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Lazy Status Transitions

All temporal logic in the system reads a single server-held logical clock, never the wall clock. Before any operator sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it through the clock-setting capability, supplying the target instant as `to_iso8601`; the endpoint responds with the new `current_utc` and never moves the clock backward onto wall-clock time. The setter accepts any target instant, including one behind the current logical reading — the clock simply holds whatever instant was last set.

Three status transitions are lazy and clock-driven rather than triggered by their own write operations: a colorway drop moves from `ALLOCATION_LOCKED` to `LIVE` once the clock reaches its `go_live_at`, and from `LIVE` to `CLOSED` once the clock reaches its `sales_end_at`; a print slot moves from `OPEN` or `LOCKED` to `CLOSED` once the clock reaches its `window_end`; and an enforcement case's `infraction_state` flips from `ACTIVE` to `EXPIRED` once the clock reaches the case's `infraction_expires_at`. These transitions are re-evaluated on every read or write of the affected resource — the server performs no eager background transitions, so a read after a clock advance is what materializes the new state. Because the new state is only materialized on access, a lazy transition is not a mutation for the purposes of §2.5: it does not refresh `updated_at` and does not increment `version`.

### 2.5. Common Resource Properties

Every resource in the system — dealers, applications, enforcement cases, product lines, colorway drops, launch allocations, customization orders, artwork proofs, print slots, and warranty claims — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, captured at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 and increments by 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

When one operation cascades into another resource — for example a dealer suspension that forfeits allocations and recomputes a drop's unit ledgers — each affected resource independently refreshes its `updated_at` and increments its `version`.

### 2.6. Optimistic Concurrency Control

Exactly three write operations participate in optimistic concurrency control, each guarding a parent resource whose version captures a mutable decision basis:

- Resolving an enforcement case with the outcome `CONFIRMED_VIOLATION` against a matched dealer requires the request to carry `expected_dealer_version`, the version of that dealer the client last observed. Because every confirmation recomputes the dealer's infraction standing and bumps the dealer's `version`, a client holding a stale view of that standing is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412).
- Overturning a confirmed case against a matched dealer likewise requires `expected_dealer_version` matching the dealer's current `version`; a mismatch is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412). The overturn recomputes infraction standing and must be based on a current read.
- Locking a drop's allocation requires `expected_drop_version` matching the drop's current `version`; a mismatch is rejected with `ERR_STALE_DROP_VERSION` (HTTP 412). Allocation-request creation and allocation forfeiture both increment the drop's `version`, so a stale version means the request set on which the client based the lock decision is out of date.

Endpoints not listed here do not accept a version field — one supplied anyway is silently ignored, as is a version field supplied on one of these three operations while the guarded relationship is not engaged (a case with no matched dealer). There is no optional-OCC mode: on these three operations the version field is required input whenever the guarded relationship is engaged (a matched dealer on confirm or overturn; always on lock-allocation), and omitting it there fails request validation with `ERR_INVALID_REQUEST`.

### 2.7. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order and the first failure wins. The order is: (1) presence and validity of the `X-User-ID` and `X-User-Role` context headers; (2) role authorization for the endpoint, including role-scoped restrictions such as a `Buyer` filing only `DTC` warranty claims; (3) existence of the resource named by the path — path identifiers resolve left-to-right — surfacing its entity-specific 404 (`ERR_DEALER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`), immediately followed, where ownership applies and the loaded resource carries the owning foreign key, by the ownership comparison, failing with `ERR_FORBIDDEN_FOR_ROLE`; (4) request-body shape — required fields present, types correct, enum values in range, and conditionally required fields satisfied, such as `infraction_category` and `expected_dealer_version` when confirming a case against a matched dealer, `expected_dealer_version` when overturning a matched case, `dealer_id` when a claim's `claim_source` is `DEALER`, `product_line_id` and `purchase_date` when a claim carries no `order_id`, and `resolution` when a return decision is an approval — with any failure reported as `ERR_INVALID_REQUEST`, after which identity fields carried in the body (a `dealer_id`, `buyer_ref`, or `inspector_user_id` that must equal the caller's `X-User-ID`) are compared, failing with `ERR_FORBIDDEN_FOR_ROLE`; (5) existence of resources referenced by body foreign keys, resolved in the endpoint's declared input order and surfacing the same entity-specific 404s — where the referenced resource is the one ownership applies to, as with a proof's order, the ownership comparison follows this load; (6) the target resource's own state permitting the requested transition (`ERR_INVALID_STATE_TRANSITION` and the specific state errors); (7) optimistic concurrency checks; (8) cross-entity state gates such as dealer standing, product-line status, drop phase, slot openness, and peak-window artwork readiness; (9) segregation-of-duties and brand-standard checks on application decisions; (10) cross-reference coherence; (11) time-window rules; (12) shape, capacity, and uniqueness constraints; and (13) the dealer credit check. A later-priority error can therefore mask an earlier one only by never being reached. Where a §3 narrative pins a more specific order among checks within one operation, that operation-local order governs.

### 2.8. Monetary Values, Points, and Precision

All monetary amounts are integer cents. Rounding uses the round-half-up method, and the rounding steps are pinned where a calculation declares them: the customization quote rounds once after the quantity-tier discount and once more after the seasonal peak multiplier; refund and cancellation-fee math performs a single rounding step per refund and never rounds per unit and then sums. The dealer `allocation_score` is a number carried to exactly 2 decimal places, rounded half up. Infraction points, machine minutes, and unit counts are integers throughout. Calendar arithmetic for warranty expiry is performed in calendar months, with the expiry landing at the same clock time on the expiry month-day; when the expiry month has fewer days than the anchor's day-of-month, the expiry clamps to the expiry month's last day.

### 2.9. The Corporate-Gifting Peak Window

The system's seasonal peak is the half-open window from `2026-10-15T00:00:00Z` up to but not including `2026-12-21T00:00:00Z`. Three behaviors key off this window. A customization quote applies a peak multiplier of 1.25 when its peak probe falls inside the window. A dealer's `allocation_score` switches from its STANDARD weighting to a PEAK weighting that shifts emphasis toward brand presentation and punishes infraction points more heavily while the clock is inside the window. And a print slot whose window intersects the peak window is marked `peak_overlap`, which tightens the artwork readiness required to reserve it.

### 2.10. Capacity and Unit Ledgers

Two ledger invariants hold at all times and are recomputed whenever membership changes. For each print slot, `booked_minutes` is the sum of `reserved_minutes` over the orders pointing at the slot whose `reservation_status` is `HELD`, `CONFIRMED`, or `CONSUMED`, and `available_minutes` is `capacity_minutes` minus `booked_minutes`; the invariant `capacity_minutes` equals `booked_minutes` plus `available_minutes` is preserved by every reservation, release, promotion, and completion, so a held or confirmed booking followed by its release restores `available_minutes` exactly. Reservations consume 4 machine-minutes per unit on `LASER` technology and 2 per unit on `PAD`. For each colorway drop, `dealer_committed_units` is the sum of `allocated_units` over the drop's allocations in `ALLOCATED` status, `warranty_reserved_units` counts the approved-replacement claims resolved to the same colorway against the drop, and `unallocated_units` is `total_units` minus `dtc_reserved_units` minus `dealer_committed_units` minus `warranty_reserved_units`; an allocated allocation that is later forfeited returns its units to the pool and restores `unallocated_units` exactly.

## 3. Business Logic & Workflows

### 3.1. Registering Dealers and the Authorization Fork-Join

A `PlatformAdmin` registers a dealer by supplying its `legal_name`, physical `storefront_address`, sales-territory `region_code`, trailing `sell_through_pct` as a number between 0 and 100, and `tenure_years` as a non-negative integer; the `tier` may be given as `STANDARD` or `PREMIER` and defaults to `STANDARD`, and the wholesale `credit_limit_cents` ceiling — a non-negative integer when supplied — defaults to 500000 cents when omitted. A freshly registered dealer starts in `PENDING` status with `storefront_verified` false and a `brand_presentation_score` of 0, and it stays `PENDING` until an authorization application is approved. The dealer collection supports listing with `status` and `tier` filters alongside the standard `limit` and `offset`. Every read of a dealer recomputes its derived financial and standing fields — `infraction_points`, `outstanding_balance_cents`, and `allocation_score` — from the current logical clock before responding, so a dealer read after a clock advance or an enforcement action always reflects live standing.

Authorization runs as a fork-join over an application. A `ChannelManager` opens an application with the target `dealer_id`, the declared `has_physical_storefront` flag, the `storefront_sqft` footage as a positive integer, and an array of `document_refs` such as the business license and resale certificate. The application starts `SUBMITTED` with `inspection_status` `UNSCHEDULED` and `docs_status` `PENDING`. At most one application per dealer may be open — in `SUBMITTED` or `VETTING` — at a time; opening a second is rejected with `ERR_APPLICATION_ALREADY_OPEN`. Applications can be listed filtered by `dealer_id` and `status`.

The inspection leg belongs to a `FieldInspector`, who schedules the site visit by naming `inspector_user_id` — which must equal the acting inspector's own `X-User-ID` — together with `window_start` and `window_end`, between which no ordering constraint is imposed. An inspector's site-visit windows are closed intervals: both endpoints are occupied, so two windows sharing an endpoint conflict outright, and between consecutive windows on the same inspector a travel buffer of at least 60 minutes is required, meaning the next window's start must be at least 60 minutes after the previous window's end. Only applications whose `inspection_status` is `SCHEDULED` occupy the inspector's calendar, and a collision is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`. Scheduling moves the application from `SUBMITTED` to `VETTING` and records the `inspection_window_start` and `inspection_window_end`. Later, once the scheduled window has ended — the window counts as ended once the clock reaches `window_end`, and recording before that is rejected with `ERR_INSPECTION_WINDOW_NOT_REACHED` — the assigned inspector records the `outcome`, moving `inspection_status` to `PASSED` or `FAILED`, captures the 0-to-100 `brand_presentation_score`, and the server stamps `inspection_recorded_by` with the acting `X-User-ID`.

The documents leg belongs to a `ChannelManager`, whose review `outcome` moves `docs_status` to `VERIFIED` or `REJECTED`, stamps `docs_reviewed_by`, and — like scheduling — moves a still-`SUBMITTED` application into `VETTING`. The two legs advance independently; either may start first, and the decision is the join.

The decision itself is a `ChannelManager` action carrying a `decision` of `APPROVE` or `REJECT` plus a free-text `decision_reason`. An approval is refused until the join is satisfied: it requires `inspection_status` `PASSED` and `docs_status` `VERIFIED`, and attempting it earlier is rejected with `ERR_APPLICATION_INCOMPLETE`. Beyond the join, approval demands that `has_physical_storefront` be true — authorization is impossible without a brick-and-mortar location, failing with `ERR_STOREFRONT_REQUIRED` — and that the recorded `brand_presentation_score` be at least 70, failing with `ERR_BRAND_STANDARD_BELOW_THRESHOLD`. Segregation of duties is enforced at the join: the deciding `X-User-ID` must differ from both `inspection_recorded_by` and `docs_reviewed_by`, otherwise the decision is rejected with `ERR_SOD_VIOLATION`. Approval also requires the dealer to still be `PENDING`, failing with `ERR_INVALID_STATE_TRANSITION` otherwise. Within an approval these checks run in this order: the join (`ERR_APPLICATION_INCOMPLETE`), the storefront requirement (`ERR_STOREFRONT_REQUIRED`), the brand-standard threshold (`ERR_BRAND_STANDARD_BELOW_THRESHOLD`), segregation of duties (`ERR_SOD_VIOLATION`), and finally the dealer-still-`PENDING` gate. When all of this holds, the application lands in `APPROVED` and the dealer cascades from `PENDING` to `AUTHORIZED`: `storefront_verified` becomes true, the application's `brand_presentation_score` is copied onto the dealer, and the dealer's `version` increments. A rejection can be issued from `SUBMITTED` or `VETTING`, lands the application in `REJECTED`, and records the `decision_reason`. Both `APPROVED` and `REJECTED` are terminal.

### 3.2. Marketplace Enforcement and Dealer Standing

Unauthorized-reseller detection begins when a `ChannelManager` opens an enforcement case from a marketplace listing, supplying the `marketplace` — one of `AMAZON`, `EBAY`, `WALMART`, or `OTHER` — the suspected `seller_handle`, the `listing_url`, and optionally a `matched_dealer_id` tracing the listing to an authorized dealer; the field stays null when the listing is unattributed. The case starts `UNDER_REVIEW`. Cases can be listed filtered by `matched_dealer_id`, `status`, and `marketplace`.

Resolving a case offers three outcomes. From `UNDER_REVIEW` the case may be escalated to `ESCALATED_LEGAL`. From either `UNDER_REVIEW` or `ESCALATED_LEGAL` it may be dismissed into `DISMISSED`, or confirmed into `CONFIRMED_VIOLATION`. Confirming against a matched dealer is the heavyweight path: the request must name the `infraction_category` — `MAP_VIOLATION`, `UNAUTHORIZED_MARKETPLACE`, `BRAND_STANDARD`, or `CHANNEL_DIVERSION` — or it fails validation with `ERR_INVALID_REQUEST`, and it must carry `expected_dealer_version` per §2.6. On a matched confirmation the server stamps `infraction_issued_at` with the logical clock, sets `infraction_expires_at` 365 days later, and scores the case from the points table: a `MAP_VIOLATION` is worth 4 points, an `UNAUTHORIZED_MARKETPLACE` case 6, a `BRAND_STANDARD` case 3, and a `CHANNEL_DIVERSION` case 5. A confirmation with no matched dealer records 0 `infraction_points` and no expiry. Free-text `resolution_notes` may be captured at resolve time.

A dealer's live `infraction_points` is the sum of points over its matched cases that are in `CONFIRMED_VIOLATION` and whose `infraction_expires_at` is still in the future; expired cases and overturned cases contribute nothing. Each case also derives an `infraction_state` of `NONE`, `ACTIVE`, `EXPIRED`, or `OVERTURNED` from its status and the clock. Threshold crossings are evaluated at resolve time and only ever tighten standing: when a recomputation lands the dealer at 12 or more points, the dealer moves to `SUSPENDED` from either `AUTHORIZED` or `PROBATION`; when it lands at 8 or more but fewer than 12 on an `AUTHORIZED` dealer, the dealer moves to `PROBATION`. Exactly 8 points is probation and exactly 12 is suspension. Standing never relaxes automatically — overturning a case lowers the points but does not restore status.

Suspension is expensive. Whether it arrives by threshold cascade or by a `ChannelManager`'s manual suspend action (permitted from `AUTHORIZED` or `PROBATION`, with a free-text `reason`), every launch allocation of the dealer in `REQUESTED` or `ALLOCATED` whose drop is still `ANNOUNCED`, `ALLOCATION_OPEN`, or `ALLOCATION_LOCKED` transitions to `FORFEITED` with `forfeit_reason` `DEALER_SUSPENDED`; allocations on drops already `LIVE` or `CLOSED` are untouched. Each forfeited `ALLOCATED` allocation recomputes its drop's `dealer_committed_units` and `unallocated_units`, returning the freed units to the pool, and increments the drop's `version`; the dealer's `version` increments as well.

A confirmed case can be appealed: overturning moves it from `CONFIRMED_VIOLATION` to `OVERTURNED` with a recorded `reason` that is stored into the case's `resolution_notes`, requires `expected_dealer_version` when the case is matched to a dealer, recomputes the dealer's points with this case excluded, and increments the dealer's `version` — while deliberately leaving the dealer's status untouched. Restoring standing is a separate `ChannelManager` act: reinstatement recomputes the dealer's live points from the clock and lands the dealer in `AUTHORIZED` when the recomputed total is below 8, or — for a `SUSPENDED` dealer — in `PROBATION` when it is 8 up to 11 inclusive; the landing state is derived, never chosen by the caller, and a recomputation that would leave standing unchanged — a `SUSPENDED` dealer still at 12 or more points, or a `PROBATION` dealer still inside the 8-to-11 band — is rejected with `ERR_INVALID_STATE_TRANSITION`. Reinstatement is available to both `SUSPENDED` and `PROBATION` dealers, so a probation dealer relaxes to `AUTHORIZED` only through reinstatement, and a suspended dealer whose points have fallen into the probation band lands in `PROBATION` rather than full standing. Termination is the terminal act: it requires a free-text `reason` like suspension, and from `PENDING`, `AUTHORIZED`, `PROBATION`, or `SUSPENDED` the dealer moves to `TERMINATED`, the same allocation-forfeiture cascade fires with `forfeit_reason` `DEALER_TERMINATED`, and any of the dealer's applications still in `SUBMITTED` or `VETTING` are rejected with the `decision_reason` "dealer terminated". Every one of these transitions increments the dealer's `version`.

### 3.3. Product Lines and the Colorway-Drop Calendar

A `PlatformAdmin` builds the catalog. Each product line carries a display `name`, a `category` of `HARD_COOLER`, `SOFT_GOOD`, or `DRINKWARE`, a canonical `base_sku` root that must be unique across all product lines — reuse is rejected with `ERR_DUPLICATE_SKU` — the customization unit `base_custom_price_cents`, the `map_price_cents` dealers must honor as minimum advertised price, the `min_custom_quantity` floor for customization orders, and three component warranty terms: `warranty_months_lid`, `warranty_months_insulation`, and `warranty_months_hardware`. The prices, the minimum quantity, and the three warranty terms are positive integers. A line is born `ACTIVE` and can be discontinued, moving to `DISCONTINUED`, which is terminal. Discontinuation does not block creating new customization orders that reference the line, but submitting such an order is rejected with `ERR_PRODUCT_LINE_DISCONTINUED`, and announcing a new colorway drop for the line is rejected with the same error. The catalog can be listed filtered by `category` and `status`.

Against an `ACTIVE` line, a `PlatformAdmin` announces a colorway drop: the `product_line_id`, the marketing `color_name`, the `pantone_code` used for customization color matching, a `drop_type` of `STANDARD` or `LIMITED_EDITION`, the `total_units` manufactured as a positive integer, the `dtc_reserved_units` carved out for the direct-to-consumer channel as a non-negative integer — which may not exceed `total_units`, failing with `ERR_DTC_RESERVE_EXCEEDS_TOTAL` — and the wholesale `dealer_unit_price_cents` as a positive integer. Four instants schedule the drop's life: `allocation_opens_at`, `allocation_closes_at`, `go_live_at`, and `sales_end_at`, which must be strictly ordered in that sequence or creation fails with `ERR_INVALID_WINDOW_ORDER`. A drop starts `ANNOUNCED`; drops can be listed filtered by `product_line_id` and `status`.

Opening the dealer allocation window moves the drop from `ANNOUNCED` to `ALLOCATION_OPEN` and is permitted only while the clock is inside the half-open window from `allocation_opens_at` up to but not including `allocation_closes_at`; outside that window the attempt is rejected with `ERR_ALLOCATION_WINDOW_NOT_OPEN`. Closing the window is the lock: permitted only once the clock has reached `allocation_closes_at` — earlier attempts are rejected with `ERR_ALLOCATION_WINDOW_OPEN` — and guarded by `expected_drop_version` per §2.6. Locking runs the distribution described in §3.4, lands the drop in `ALLOCATION_LOCKED`, recomputes `dealer_committed_units` and `unallocated_units`, and increments the drop's `version`. Thereafter the drop's life is clock-driven per §2.4: `ALLOCATION_LOCKED` to `LIVE` at `go_live_at`, and `LIVE` to `CLOSED` at `sales_end_at`. Both opening and locking increment the drop's `version`, as do allocation requests and forfeitures — so the lock's version check genuinely guards the request set.

### 3.4. Launch Allocations: Requests, the Lock-Time Distribution, and Forfeiture

While a drop is `ALLOCATION_OPEN`, a `Dealer` requests units by naming its `dealer_id` — which must equal the acting dealer identity — the `drop_id`, and the `requested_units`, at least 1. Several gates stand in front of a request, and per §2.7 they are reached in precedence order. The dealer must be `AUTHORIZED`; a request from a `PENDING`, `PROBATION`, `SUSPENDED`, or `TERMINATED` dealer is rejected with `ERR_DEALER_NOT_AUTHORIZED`. The drop must be `ALLOCATION_OPEN`, else `ERR_DROP_NOT_OPEN_FOR_ALLOCATION`, and the clock must still be before `allocation_closes_at`, else `ERR_ALLOCATION_WINDOW_CLOSED`. A dealer may hold at most one `REQUESTED` allocation per drop; a second is rejected with `ERR_DUPLICATE_ALLOCATION_REQUEST`. Finally the dealer's credit is checked: the dealer's `outstanding_balance_cents` — the sum of `allocated_units` times `unit_price_cents` across the dealer's allocations currently in `ALLOCATED` — plus the requested units times the drop's `dealer_unit_price_cents` must not exceed the dealer's `credit_limit_cents`, failing with `ERR_CREDIT_LIMIT_EXCEEDED`. A successful request records a snapshot of the drop's `dealer_unit_price_cents` into the allocation's `unit_price_cents`, starts in `REQUESTED` with `allocated_units` at 0, and increments the drop's `version` because the request set changed. Allocations can be listed filtered by `dealer_id`, `drop_id`, and `status`; for a `Dealer` caller the `dealer_id` filter is forced to the acting dealer.

The lock distributes the dealer pool, which is `total_units` minus `dtc_reserved_units` minus `warranty_reserved_units`. Every request whose dealer is not `AUTHORIZED` at lock time expires into `EXPIRED`. If the eligible requests sum to no more than the pool, each is granted in full and moves to `ALLOCATED`. Otherwise the distribution is a pinned floor-then-cap largest-remainder waterfall: each eligible dealer's weight is its current-season `allocation_score` floored at a minimum of 1; each request's raw share is the pool times its weight divided by the sum of all weights; the base grant is the request's `requested_units` capped above by the raw share rounded down to a whole unit — floor first, then cap, never the other order; and the leftover pool then goes out in repeated passes over the candidates whose base grant is still below their request, ranked by the fractional part of the raw share descending, then `allocation_score` descending, then the allocation's `created_at` ascending, granting one unit per candidate per pass until the leftover is exhausted or no candidate can take more, with any residue staying unallocated. Eligible requests granted zero units expire. The dealer score behind the weights is computed from the dealer's `sell_through_pct`, `brand_presentation_score`, `tenure_years`, and live `infraction_points`: outside the peak window the STANDARD weighting is 0.50 on sell-through, 0.30 on brand presentation, 2 per tenure year, and a penalty of 5 per infraction point; inside the peak window the PEAK weighting shifts to 0.35 on sell-through, 0.45 on brand presentation, keeps 2 per tenure year, and punishes 8 per infraction point. The score is rounded half up to 2 decimal places, is recomputed on every dealer read, and is read fresh at lock time.

An allocation can also leave the pool by forfeiture. A dealer may forfeit its own allocation, and a `ChannelManager` may forfeit any; manual forfeiture is permitted only while the drop is `ANNOUNCED`, `ALLOCATION_OPEN`, or `ALLOCATION_LOCKED` — allocations on `LIVE` or `CLOSED` drops cannot be forfeited, and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. Manual forfeiture lands the allocation in `FORFEITED` with `forfeit_reason` `DEALER_CHOICE`; the system cascades of §3.2 use `DEALER_SUSPENDED` or `DEALER_TERMINATED` instead. When a forfeited allocation was `ALLOCATED`, its units return to the pool and the drop's `dealer_committed_units` and `unallocated_units` recompute; every forfeiture increments the drop's `version`. `EXPIRED` and `FORFEITED` are terminal.

### 3.5. Customization Order Intake and the Two-Variant Quote

A `Buyer` opens a customization order with a `buyer_type` of `CORPORATE` or `INDIVIDUAL`, an opaque `buyer_ref` that must equal the acting buyer's `X-User-ID`, the chosen `product_line_id` and `colorway_drop_id`, a `quantity` of at least 1, the buyer-declared `declared_color_count` between 1 and 8 and `declared_placement_count` between 1 and 4, the `print_technology` the order will consume — `LASER` or `PAD` — and a `requested_ship_date`. Creation checks that the referenced product line and drop exist; the line's status and the colorway's coherence are deliberately deferred to submit. A new order starts with every axis at rest: `order_state` `ACTIVE`, `artwork_status` `NO_ART`, `proof_round` 0, `schedule_status` `UNSCHEDULED`, `payment_status` `UNPAID`, `return_status` `NONE` with no `return_reason` or `return_resolution` yet, `reservation_status` `NONE` with no `slot_id`, and `quote_variant` `NONE`. Orders can be listed filtered by `buyer_ref`, `product_line_id`, `colorway_drop_id`, `slot_id`, `schedule_status`, and `reservation_status`; for a `Buyer` caller the `buyer_ref` filter is forced to the acting buyer.

The quote runs twice over the same tiered structure with different evidence, and the second run replaces rather than adjusts the first. The unit price is the line's `base_custom_price_cents` plus 150 cents for each declared or actual color beyond the first, plus 200 cents for each placement beyond the first — colors and placements below one never reduce the base. The subtotal is the `quantity` times that unit price. A quantity-tier discount applies to `CORPORATE` buyers only: 22 percent off at 500 units or more, 15 percent at 144 up to 499, and 8 percent at 48 up to 143; `INDIVIDUAL` orders never receive a quantity rate. The discounted subtotal is rounded half up to whole cents — this rounding step is pinned to occur before anything else is added. A setup fee of 8000 cents is then added unless the quantity is at least 144, in which case the fee is waived for both buyer types. Finally, if the variant's peak probe says the peak window applies, the sum of discounted subtotal and setup is multiplied by 1.25 and rounded half up to whole cents; otherwise it stands as is. The flag `peak_applied` records whether the multiplier entered the current quote.

The PROVISIONAL variant runs at submit. Submitting guards that the order is still `ACTIVE` — a second submit on the same order is a replay of a consumed transition and is rejected with `ERR_INVALID_STATE_TRANSITION` — and that payment is still `UNPAID`, which fails with the same `ERR_INVALID_STATE_TRANSITION`. The product line must be `ACTIVE`, failing with `ERR_PRODUCT_LINE_DISCONTINUED`. The chosen drop must belong to the same product line as the order and must not be `CLOSED`, failing with `ERR_COLORWAY_NOT_AVAILABLE`. And the `quantity` must meet the line's `min_custom_quantity`, failing with `ERR_BELOW_MINIMUM_QUANTITY`. The provisional probe treats the peak window as applicable when the `requested_ship_date` falls inside it. A successful submit stores the total in `provisional_quote_cents`, sets `quote_variant` to `PROVISIONAL`, sets `peak_applied`, and moves `payment_status` from `UNPAID` to `AUTHORIZED`.

### 3.6. Artwork Proofing Rounds

Artwork advances on a cyclic axis with at most three rounds. A `Buyer` submits a proof for its own order with the `order_id`, an `artwork_file_ref`, the actual `color_count` between 1 and 8, the actual `placement_count` between 1 and 4, and the array of `pantone_codes` used in the artwork. Submission requires the order to be `ACTIVE` and its artwork axis to be at `NO_ART` or `CHANGES_REQUESTED`, and it requires `proof_round` to still be below 3 — the round-cap check is applied before the artwork-axis check, so a fourth submission is rejected with `ERR_PROOF_ROUND_EXHAUSTED` even though the artwork axis has by then left `NO_ART` and `CHANGES_REQUESTED`. On acceptance the order's `proof_round` increments, the new proof is created in `SUBMITTED` with its `round_number` set to the new `proof_round` and `submitted_by` stamped with the buyer's `X-User-ID`, any earlier proof of the order sitting in `CHANGES_REQUESTED` moves to `SUPERSEDED`, and the order's artwork axis becomes `PROOF_SUBMITTED`. Proofs can be listed filtered by `order_id` and `status`.

Review belongs to a `PrepressTech`, and only the latest round of an `ACTIVE` order is reviewable — the proof's `round_number` must equal the order's current `proof_round` and the proof must be `SUBMITTED`; older rounds are `SUPERSEDED`. Approving the latest proof moves it to `APPROVED`, moves the order's artwork axis to `ART_APPROVED`, and computes the FINAL quote from the approved proof's actual `color_count` and `placement_count`; for this variant the peak probe reads the reserved slot's `peak_overlap` when the order's `reservation_status` is `HELD`, `WAITLISTED`, or `CONFIRMED`, and falls back to the `requested_ship_date` probe otherwise. The result replaces the provisional figure in `final_quote_cents`, flips `quote_variant` to `FINAL`, and recomputes `peak_applied`. When the order's reservation was sitting `HELD`, approval confirms it atomically: `reservation_status` moves to `CONFIRMED` and `schedule_status` moves from `RESERVED` to `CONFIRMED` in the same step.

Requesting changes instead captures `review_notes`, moves the proof to `CHANGES_REQUESTED`, and returns the order's artwork axis to `CHANGES_REQUESTED` — unless the proof was already the third round, in which case the artwork axis lands in `PROOF_EXHAUSTED`, the cycle closes, and only cancellation remains for the order. Both `ART_APPROVED` and `PROOF_EXHAUSTED` are terminal for the artwork axis, and `APPROVED` and `SUPERSEDED` are terminal for a proof.

### 3.7. Print Capacity: Slots, Reservations, and the Waitlist

A `ProductionLead` opens capacity by defining a print slot: the physical `station_code`, the `technology` the window runs (`LASER` or `PAD`), the `window_start` and `window_end`, and the bookable `capacity_minutes`. Slot windows are half-open intervals — the start is occupied, the end is not — scoped per `station_code`. Two windows on the same station running the same technology are rejected only when their intervals genuinely intersect, so touching endpoints are allowed; windows of different technologies additionally require a changeover gap of at least 20 minutes on both sides, and a smaller gap is a conflict. Any overlap violation is rejected with `ERR_SLOT_OVERLAP_CONFLICT`; the overlap check runs against every slot on the station regardless of that slot's status and is evaluated before the window-order and capacity checks. The `window_end` must be strictly after `window_start`, failing with `ERR_INVALID_WINDOW_ORDER`, and `capacity_minutes` must be positive and no greater than the window's duration in minutes, failing with `ERR_CAPACITY_EXCEEDS_WINDOW`. A new slot starts `OPEN`, and its `peak_overlap` is computed at creation as true when the window intersects the peak window of §2.9. Slots can be listed filtered by `station_code`, `technology`, and `status`.

Locking a slot moves it from `OPEN` to `LOCKED`: new reservations are then rejected with `ERR_SLOT_NOT_OPEN`, existing held or confirmed reservations are unaffected, and orders already confirmed on the slot become eligible to start production. A slot closes lazily per §2.4 once the clock reaches its `window_end`.

A `Buyer` reserves capacity for its order by naming a `slot_id`. The order must be `ACTIVE` with `schedule_status` `UNSCHEDULED` and a `reservation_status` of `NONE` or `RELEASED`, and its `payment_status` must be `AUTHORIZED` — an order pays its way onto the schedule, and any reservability failure is reported as `ERR_INVALID_STATE_TRANSITION`. The remaining gates are evaluated in this order: the slot must be `OPEN`, failing with `ERR_SLOT_NOT_OPEN`; peak-window slots are stricter — when the slot's `peak_overlap` is true the order's artwork must already be `ART_APPROVED`, failing with `ERR_ARTWORK_NOT_APPROVED`, while off-peak slots accept reservations with art still pending; and the slot's `technology` must match the order's `print_technology`, failing with `ERR_TECHNOLOGY_MISMATCH`. The reservation's footprint is `reserved_minutes`, frozen at reserve time as the order's `quantity` times the per-unit minutes of its technology — 4 for `LASER`, 2 for `PAD`. If the slot's `available_minutes` covers that footprint — an exact fit counts — the reservation lands `HELD` and the schedule moves to `RESERVED`, booking the minutes against the slot; otherwise the reservation lands `WAITLISTED` and the schedule stays `UNSCHEDULED`. When the artwork was already approved at reserve time, the new reservation confirms atomically in the same request: `HELD` to `CONFIRMED` and `RESERVED` to `CONFIRMED`.

Releasing a reservation is the inverse act by the `Buyer`, available on an `ACTIVE` order whose schedule is `UNSCHEDULED`, `RESERVED`, or `CONFIRMED` with the reservation in `HELD`, `CONFIRMED`, or `WAITLISTED` — a waitlisted order thereby abandons its spot — while an order `IN_PRODUCTION` or `COMPLETE` rejects release with `ERR_ORDER_IN_PRODUCTION`. The reservation moves to `RELEASED`, the `slot_id` is cleared, the schedule returns to `UNSCHEDULED`, and minutes booked while `HELD` or `CONFIRMED` are freed back to the slot. Freed capacity immediately runs the waitlist promotion: candidates are the orders pointing at the freed slot with `reservation_status` `WAITLISTED`, still `ACTIVE`, and — when the slot is a peak-window slot — already `ART_APPROVED`; they are ranked by `requested_ship_date` ascending and then `created_at` ascending, and each candidate whose `reserved_minutes` fits the current `available_minutes` is promoted in that order, moving from `WAITLISTED` to `HELD` and from `UNSCHEDULED` to `RESERVED` and booking its minutes, and then auto-confirming to `CONFIRMED` on both axes when its artwork is already approved. An empty candidate set, or no candidate that fits, leaves the capacity open — there is no fallback beyond that, and no id-based tie-breaking anywhere in the ranking.

### 3.8. Production, Cancellation, and the Return Policy

Production belongs to the `ProductionLead`. Starting a run requires the order to be `ACTIVE` with its reservation `CONFIRMED` and the slot `LOCKED` — starting against a slot that is not locked is rejected with `ERR_SLOT_NOT_LOCKED` — and moves the schedule from `CONFIRMED` to `IN_PRODUCTION`. Completing the run carries a `qc_outcome`. A `PASS` moves the schedule to `COMPLETE`, moves the reservation to `CONSUMED` — the minutes stay booked, because the capacity was genuinely spent — captures payment by moving `payment_status` from `AUTHORIZED` to `CAPTURED` for the `final_quote_cents` amount, and stamps `completed_at` with the logical clock, which anchors both the warranty and the return windows. A `FAIL` is the rework loop: the schedule falls back from `IN_PRODUCTION` to `CONFIRMED` and the order's `qc_fail_count` increments.

Cancellation is available to the `Buyer` and to a `PlatformAdmin` while the order is `ACTIVE` and its schedule is `UNSCHEDULED`, `RESERVED`, or `CONFIRMED`; an order already `IN_PRODUCTION` rejects cancellation with `ERR_ORDER_IN_PRODUCTION`, and a `COMPLETE` order belongs to the return flow instead, rejecting cancellation with the same `ERR_ORDER_IN_PRODUCTION`. The cancellation fee is zero while the artwork axis is anything other than `ART_APPROVED`; once art is approved the fee is 10 percent of the `final_quote_cents`, rounded half up. The refund is zero when payment was merely `AUTHORIZED` — the authorization is simply voided — and otherwise the `final_quote_cents` minus the fee, floored at zero; the fee lands in `cancellation_fee_cents` and the cumulative refund in `refund_cents`. Cancellation moves `order_state` to `CANCELLED`, releases any held, confirmed, or waitlisted reservation with the waitlist-promotion cascade of §3.7, and moves `payment_status` to `REFUNDED` when it had been `AUTHORIZED` or `CAPTURED` — an `UNPAID` order stays `UNPAID`.

Because personalized goods can never be restocked, returns are narrow. A `Buyer` may request a return on an order that is `ACTIVE`, schedule `COMPLETE`, and payment `CAPTURED`, within 45 days of `completed_at` — at or after that deadline the request is rejected with `ERR_RETURN_WINDOW_CLOSED`. The request carries a `reason` of `DEFECT`, `ARTWORK_MISMATCH`, or `BUYERS_REMORSE` and an `affected_unit_count` between 1 and the order's `quantity`, and moves `return_status` from `NONE` to `RETURN_REQUESTED`, recording both fields on the order.

The return decision belongs to `CustomerCare`, whose `decision` either denies the request — landing `return_status` in `RETURN_DENIED` — or approves it into `RETURN_SETTLED` with a `resolution` and optional `decision_notes`; the notes text is accepted but not persisted, the order recording the `return_resolution` alone. Three guards fence approval. A `BUYERS_REMORSE` return is never approvable, because personalized goods cannot be restocked, and the attempt is rejected with `ERR_PERSONALIZED_NOT_RETURNABLE`. An `ARTWORK_MISMATCH` return admits only `FULL_REFUND` or `REMAKE`; proposing `PARTIAL_CREDIT` there is rejected with `ERR_RETURN_RESOLUTION_MISMATCH`. And `PARTIAL_CREDIT` requires the `affected_unit_count` to be strictly below the order's `quantity` — when every unit is affected the correct resolution is a full refund — else `ERR_RETURN_RESOLUTION_MISMATCH` again. A `FULL_REFUND` settles `refund_cents` to the full `final_quote_cents` and moves payment to `REFUNDED`. A `PARTIAL_CREDIT` settles `refund_cents` to the `final_quote_cents` prorated by the affected units over the `quantity`, rounded half up in a single step, and moves payment to `PARTIALLY_REFUNDED`. In both money resolutions the goods are written off and never restocked — no units return to any pool. A `REMAKE` instead re-books capacity: the slot must still be usable — re-booking against a `LOCKED` or `CLOSED` slot is rejected with `ERR_SLOT_NOT_OPEN` — and its current `available_minutes` must cover the order's `reserved_minutes`, failing with `ERR_CAPACITY_EXCEEDED`; on success the schedule moves from `COMPLETE` back to `CONFIRMED`, the reservation returns to `HELD` on the same slot, and the minutes are booked again.

### 3.9. Warranty Claims and Replacement Resolution

Warranty intake is shared: a `Buyer` files claims for the direct channel, a `Dealer` files for items it sold, and a `WarrantyAgent` may file on either's behalf — a `Buyer` caller may file only `DTC` claims and a `Dealer` caller only `DEALER` claims, with a crossed source rejected with `ERR_FORBIDDEN_FOR_ROLE`. The claim names a `claim_source` of `DTC` or `DEALER`, the item's `serial_number`, the failed `component` — `LID`, `INSULATION`, or `HARDWARE` — and a free-text `failure_description`. When `claim_source` is `DEALER` the `dealer_id` is required and, for a `Dealer` caller, must equal the acting identity; when it is `DTC` the `buyer_ref` is required with the same ownership rule. When the claimed item is a customized order, the `order_id` is supplied and the order must have reached schedule `COMPLETE`, failing with `ERR_INVALID_STATE_TRANSITION` otherwise; for a `DTC` claim the claim's buyer must match the order's, and the warranty then anchors on the order's `completed_at`. Cross-references must be coherent throughout intake — the drop referenced by an order must belong to the order's product line (guaranteed by the submit-time gate), and a `DTC` claim that names an order must belong to the same buyer as that order; a coherence failure on these references is rejected with `ERR_COLORWAY_NOT_AVAILABLE`. A dealer-source claim whose `dealer_id` does not resolve is rejected with `ERR_DEALER_NOT_FOUND` at the existence step of §2.7 rather than as a coherence failure, and no claimant comparison applies to a `DEALER` claim naming an order, since orders carry no dealer reference. Without an `order_id`, the `product_line_id` and `purchase_date` are required and the warranty anchors on the purchase date. Claims can be listed filtered by `dealer_id`, `buyer_ref`, `order_id`, `product_line_id`, and `status`.

At filing the server stamps `filed_at` with the logical clock, resolves the `warranty_anchor_at`, and computes `warranty_expires_at` as the anchor plus the component's warranty term in calendar months from the product line — `warranty_months_lid`, `warranty_months_insulation`, or `warranty_months_hardware`. The claim is valid only while it is filed strictly before the expiry; filing exactly at the expiry moment is rejected with `ERR_WARRANTY_EXPIRED`. The server also evaluates the fraud flag: `fraud_flag` is set true when the claimant — keyed by `dealer_id` for dealer-source claims and by `buyer_ref` for direct ones — already has at least 3 other claims not in `DENIED` status filed within the trailing 365 days, the trailing window including both endpoints so that claims filed exactly 365 days earlier or at the same clock instant count.

Review starts with a `WarrantyAgent` moving the claim from `FILED` to `UNDER_REVIEW`, and deciding offers three outcomes: `APPROVE_REPAIR`, `APPROVE_REPLACEMENT`, or `DENY`, each with a `decision_reason`. The fraud gate stands in front of every decision: a fraud-flagged claim may not be decided directly from `FILED` and must pass through review first, else the decision is rejected with `ERR_FRAUD_REVIEW_REQUIRED`. A denial lands the claim in `DENIED`; a repair approval lands it in `APPROVED_REPAIR`.

A replacement approval lands the claim in `APPROVED_REPLACEMENT` and resolves where the replacement unit comes from. When the claim carries an `order_id` whose order's drop is currently `ALLOCATION_LOCKED` or `LIVE` and still has at least one `unallocated_units`, the `replacement_colorway_resolution` is `SAME_COLORWAY` and the drop's `warranty_reserved_units` increases by one, preserving the unit-ledger invariant of §2.10. Failing that, when the product line is still `ACTIVE`, the resolution is `NEAREST_AVAILABLE`. Otherwise the resolution is `CREDIT_EQUIVALENT` and the `credit_equivalent_cents` is set to the product line's `map_price_cents` snapshot. All three outcomes are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — dealers, applications, enforcement cases, product lines, colorway drops, launch allocations, customization orders, artwork proofs, print slots, and warranty claims — return `201 Created`. Operations that modify an existing resource, including all state-transition actions, return `200 OK`. Request and response payloads are governed by the narratives in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/drinkware/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/drinkware/dealers` | Register a dealer (status PENDING until an application is approved) | PlatformAdmin |
| GET | `/drinkware/dealers/{id}` | Read a dealer (Dealer role: own record only) | PlatformAdmin, ChannelManager, Dealer, WarrantyAgent |
| GET | `/drinkware/dealers` | List dealers with filters and pagination | PlatformAdmin, ChannelManager, WarrantyAgent |
| POST | `/drinkware/dealers/{id}/suspend` | Manually suspend an AUTHORIZED or PROBATION dealer; forfeits non-live-drop allocations | ChannelManager |
| POST | `/drinkware/dealers/{id}/reinstate` | Reinstate a SUSPENDED or PROBATION dealer; landing state recomputed from live infraction points | ChannelManager |
| POST | `/drinkware/dealers/{id}/terminate` | Terminate a dealer (terminal); forfeits non-live-drop allocations and rejects open applications | ChannelManager |
| POST | `/drinkware/dealer-applications` | Open an authorization application for a PENDING dealer | ChannelManager |
| GET | `/drinkware/dealer-applications/{id}` | Read an application (Dealer role: own dealer's applications only) | ChannelManager, FieldInspector, Dealer |
| GET | `/drinkware/dealer-applications` | List applications with filters and pagination | ChannelManager, FieldInspector |
| POST | `/drinkware/dealer-applications/{id}/schedule-inspection` | Schedule the site-visit window with the acting inspector | FieldInspector |
| POST | `/drinkware/dealer-applications/{id}/record-inspection` | Record the inspection outcome (assigned inspector only, after the window ends) | FieldInspector |
| POST | `/drinkware/dealer-applications/{id}/verify-documents` | Verify or reject the document leg of vetting | ChannelManager |
| POST | `/drinkware/dealer-applications/{id}/decide` | Authorization decision (the fork-join join) | ChannelManager |
| POST | `/drinkware/enforcement-cases` | Open an unauthorized-reseller detection case from a marketplace listing | ChannelManager |
| GET | `/drinkware/enforcement-cases/{id}` | Read an enforcement case | ChannelManager, PlatformAdmin |
| GET | `/drinkware/enforcement-cases` | List enforcement cases with filters and pagination | ChannelManager, PlatformAdmin |
| POST | `/drinkware/enforcement-cases/{id}/resolve` | Resolve a case: CONFIRMED_VIOLATION, DISMISSED, or ESCALATED_LEGAL | ChannelManager |
| POST | `/drinkware/enforcement-cases/{id}/overturn` | Overturn a CONFIRMED_VIOLATION; removes the points but never auto-restores dealer status | ChannelManager |
| POST | `/drinkware/product-lines` | Create a product line (hard cooler, soft good, or drinkware) | PlatformAdmin |
| GET | `/drinkware/product-lines/{id}` | Read a product line | Any declared role |
| GET | `/drinkware/product-lines` | List product lines with filters and pagination | Any declared role |
| POST | `/drinkware/product-lines/{id}/discontinue` | Discontinue a product line (terminal) | PlatformAdmin |
| POST | `/drinkware/colorway-drops` | Announce a colorway drop or limited edition with its dealer/DTC unit split and allocation window | PlatformAdmin |
| GET | `/drinkware/colorway-drops/{id}` | Read a drop (lazy LIVE/CLOSED evaluation; unit ledgers recomputed) | Any declared role |
| GET | `/drinkware/colorway-drops` | List drops with filters and pagination | Any declared role |
| POST | `/drinkware/colorway-drops/{id}/open-allocation` | Open the dealer allocation window | PlatformAdmin |
| POST | `/drinkware/colorway-drops/{id}/lock-allocation` | Close the window and distribute the dealer pool via largest-remainder allocation | PlatformAdmin |
| POST | `/drinkware/launch-allocations` | Dealer requests units from an open drop | Dealer |
| GET | `/drinkware/launch-allocations/{id}` | Read an allocation (Dealer role: own allocations only) | Dealer, PlatformAdmin, ChannelManager |
| GET | `/drinkware/launch-allocations` | List allocations (Dealer role: dealer filter forced to the acting dealer) | Dealer, PlatformAdmin, ChannelManager |
| POST | `/drinkware/launch-allocations/{id}/forfeit` | Forfeit a REQUESTED or ALLOCATED allocation while its drop is not yet LIVE | Dealer, ChannelManager |
| POST | `/drinkware/customization-orders` | Create a customization order | Buyer |
| GET | `/drinkware/customization-orders/{id}` | Read an order (Buyer role: own orders only) | Buyer, PlatformAdmin, ProductionLead, PrepressTech, CustomerCare, WarrantyAgent |
| GET | `/drinkware/customization-orders` | List orders (Buyer role: buyer filter forced to the acting buyer) | Buyer, PlatformAdmin, ProductionLead, CustomerCare |
| POST | `/drinkware/customization-orders/{id}/submit` | Submit the order: validates MOQ, colorway match, line status; computes the PROVISIONAL quote and authorizes payment | Buyer |
| POST | `/drinkware/customization-orders/{id}/cancel` | Cancel an order that is not yet in production | Buyer, PlatformAdmin |
| POST | `/drinkware/customization-orders/{id}/reserve-slot` | Reserve print capacity on an OPEN slot; insufficient capacity waitlists the order | Buyer |
| POST | `/drinkware/customization-orders/{id}/release-slot` | Release a reservation or abandon a waitlist spot; promotes the waitlist | Buyer |
| POST | `/drinkware/customization-orders/{id}/start-production` | Begin printing: requires a CONFIRMED reservation on a LOCKED slot | ProductionLead |
| POST | `/drinkware/customization-orders/{id}/complete-production` | Finish a production run: PASS completes and captures payment; FAIL loops back for rework | ProductionLead |
| POST | `/drinkware/customization-orders/{id}/request-return` | Request a return on a completed, captured order within 45 days of completion | Buyer |
| POST | `/drinkware/customization-orders/{id}/decide-return` | Decide a return request; approval settles immediately | CustomerCare |
| POST | `/drinkware/artwork-proofs` | Submit a proof round for an order (max 3 rounds) | Buyer |
| GET | `/drinkware/artwork-proofs/{id}` | Read a proof (Buyer role: own orders' proofs only) | Buyer, PrepressTech, PlatformAdmin |
| GET | `/drinkware/artwork-proofs` | List proofs with filters and pagination | PrepressTech, PlatformAdmin |
| POST | `/drinkware/artwork-proofs/{id}/approve` | Approve the latest proof round: computes the FINAL quote and confirms a held reservation | PrepressTech |
| POST | `/drinkware/artwork-proofs/{id}/request-changes` | Request artwork changes on the latest proof round | PrepressTech |
| POST | `/drinkware/print-slots` | Open a capacity window on a print station | ProductionLead |
| GET | `/drinkware/print-slots/{id}` | Read a slot (lazy CLOSED evaluation; ledgers recomputed) | Any declared role |
| GET | `/drinkware/print-slots` | List slots with filters and pagination | Any declared role |
| POST | `/drinkware/print-slots/{id}/lock` | Lock a slot for production day | ProductionLead |
| POST | `/drinkware/warranty-claims` | File a warranty claim (DTC buyers or dealers) | Buyer, Dealer, WarrantyAgent |
| GET | `/drinkware/warranty-claims/{id}` | Read a claim (Buyer/Dealer roles: own claims only) | WarrantyAgent, PlatformAdmin, Dealer, Buyer |
| GET | `/drinkware/warranty-claims` | List claims with filters and pagination | WarrantyAgent, PlatformAdmin |
| POST | `/drinkware/warranty-claims/{id}/start-review` | Move a claim FILED to UNDER_REVIEW (mandatory first step for fraud-flagged claims) | WarrantyAgent |
| POST | `/drinkware/warranty-claims/{id}/decide` | Decide a claim: APPROVE_REPAIR, APPROVE_REPLACEMENT, or DENY | WarrantyAgent |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is an identifier reference only. Three further identifiers exist outside the catalogue for transport-level failures, all in the standard error envelope: a request matching no defined route fails with `ERR_NOT_FOUND` (404), a defined route called with an unsupported method with `ERR_METHOD_NOT_ALLOWED` (405), and an unexpected server failure with `ERR_INTERNAL` (500).

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_DROP_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PROOF_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_APPLICATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_DROP_NOT_OPEN_FOR_ALLOCATION` | 409 Conflict |
| `ERR_SLOT_NOT_OPEN` | 409 Conflict |
| `ERR_SLOT_NOT_LOCKED` | 409 Conflict |
| `ERR_ORDER_IN_PRODUCTION` | 409 Conflict |
| `ERR_FRAUD_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_PRODUCT_LINE_DISCONTINUED` | 409 Conflict |
| `ERR_DUPLICATE_ALLOCATION_REQUEST` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_STALE_DEALER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DROP_VERSION` | 412 Precondition Failed |
| `ERR_DEALER_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_ARTWORK_NOT_APPROVED` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_STOREFRONT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BRAND_STANDARD_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_APPLICATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_COLORWAY_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP_CONFLICT` | 409 Conflict |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ALLOCATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_WINDOW_OPEN` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_WINDOW_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_BELOW_MINIMUM_QUANTITY` | 422 Unprocessable Entity |
| `ERR_PROOF_ROUND_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDS_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW_ORDER` | 422 Unprocessable Entity |
| `ERR_RETURN_RESOLUTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PERSONALIZED_NOT_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_TECHNOLOGY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DTC_RESERVE_EXCEEDS_TOTAL` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
