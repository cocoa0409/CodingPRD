# Oilseed Crush Origination API — Product Requirements Document

## 1. Introduction

Origination desks at a soybean processor live or die on a narrow spread: the difference between what the oil and meal crushed out of a bushel will fetch and what the bushel itself costs. That spread is managed across a chain of commitments that begins at a country elevator, where a grower delivers against a cash, basis, or deferred-pricing contract, and ends at the loadout dock, where meal, oil, and biodiesel feedstock move to commercial buyers against delivery-windowed sales contracts. The Oilseed Crush Origination API is the system of record for that entire chain. It governs farmer origination contracts and their pricing elections, scale-ticket grading against published quality discount schedules, storage-lot accounting and elevator capacity, freight lanes and shipments across truck, rail, and barge, crush-run planning and execution at the plants, board crush hedge positions with enforced segregation of duties, product sales contracts with quality specifications, and the default-and-claims machinery that protects the processor when a buyer fails to take delivery.

The platform replaces a patchwork of spreadsheets, phone calls, and end-of-day reconciliation with a single immediately consistent API. Every mutation is visible in the response that carries it and in every subsequent read; there is no eventual-consistency window anywhere in the system. All money is integer cents, all bushel quantities carry three decimal places, and all crush spreads carry two — rounding is always half-up, and the pinned rounding order for settlement lines is part of the commercial contract, not an implementation detail. A logical clock, never the wall clock, governs every deadline in the system: it starts at exactly 2026-09-01T00:00:00Z, and advancing it synchronously runs the sweep that force-prices expired deferred contracts, defaults lapsed sales contracts, and expires stale hedge positions.

Two structural principles shape every workflow that follows. First, pricing is dual-variant wherever money meets the market: farmer settlements carry a provisional estimate that moves with the board alongside a final settlement computed only at settle time, and crush runs carry a planned margin locked at creation alongside a realized margin recomputed at completion. Second, contention is controlled explicitly rather than implicitly: the two writes most exposed to stale reads — pricing elections and crush-run scheduling — carry optimistic concurrency tokens, and hedge entry and hedge confirmation are split across two different human operators by rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names the operational capacity in which that user acts. A request that omits `X-User-Role`, or whose value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); per the validation order in §2.9, authentication is always evaluated before authorization.

The system declares exactly ten roles:

- `PlatformAdmin` — the back-office operator. Registers farmers, elevators, quality discount schedules, sustainability programs, crush plants, and buyers; posts market quotes; drives the logical clock.
- `OriginationMerchandiser` — the elevator merchandiser. Writes origination contracts, creates and applies delivery tickets, settles contracts, and shares pricing-election rights with the grower.
- `Farmer` — the grower counterparty. Reads only its own origination contracts and prices elections only on contracts it owns.
- `CrushTrader` — the hedge desk trader. Enters and offsets board crush positions.
- `RiskManager` — confirms hedge positions; segregation of duties forbids confirming a position entered under the same user identifier.
- `PlantScheduler` — plans, schedules, drives, and cancels crush runs at the plants.
- `LogisticsCoordinator` — builds freight lanes, requests routing quotes, books shipments, and marks them delivered or cancelled.
- `ProductMerchandiser` — sells meal, oil, and biodiesel feedstock and records deliveries against sales contracts.
- `CommercialBuyer` — the meal and oil customer. Reads only its own sales contracts.
- `SustainabilityAuditor` — the certification body representative. Closes sustainability programs.

Two roles are entity-backed. When `X-User-Role` is `Farmer`, `X-User-ID` is the `id` of the acting Farmer; ownership checks on any resource that references a Farmer compare the resource's `farmer_id` field to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `CommercialBuyer`, `X-User-ID` is the `id` of the acting Buyer; ownership checks on any resource that references a Buyer compare the resource's `buyer_id` field to `X-User-ID`, and a mismatch is likewise `ERR_FORBIDDEN`. The remaining eight roles — `PlatformAdmin`, `OriginationMerchandiser`, `CrushTrader`, `RiskManager`, `PlantScheduler`, `LogisticsCoordinator`, `ProductMerchandiser`, and `SustainabilityAuditor` — are opaque: for each of them, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, as `entered_by_user_id` or `confirmed_by_user_id` on a hedge position) but never compares it to an entity's `id` for ownership.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. `offset` sets the number of items skipped and defaults to 0. Unless a section states otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, so a client can always tell whether further pages exist.

### 2.4. Resource Identity and Common Fields

Every resource is a top-level citizen: the API surface is flat, with each resource addressed directly by its own identifier under the `/api` prefix, and cross-resource linkage travels in request and response fields rather than in nested URLs. All resources share a common identity block:

- `id` — a server-minted UUID with no type prefix, assigned at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` — a system-managed integer that increments by exactly one on every mutation of the resource, including mutations caused by the cross-entity cascades described in §3.

The sole exception is the market quote. Quotes are append-only observations: a quote carries `id` and `created_at` only; `updated_at` and `version` are absent because a quote, once posted, never changes.

### 2.5. The Logical Clock

All temporal rules in the system — deadlines, windows, expiry, arrival — read a single logical clock, never the wall clock. At startup the clock reads exactly 2026-09-01T00:00:00Z. Only a `PlatformAdmin` may advance it, through a test-driving capability that takes a `to_iso8601` timestamp and returns the resulting `current_utc`. Advancing the clock is never a passive store-and-return: the advance synchronously runs a three-phase deadline sweep before the response is returned. First, deferred-pricing contracts whose `pricing_deadline` has passed are force-priced; second, sales contracts whose delivery window has closed short of full delivery are defaulted, with claims and buyer suspension cascading from each default; third, hedge positions whose `expiry_date` has passed are expired. Section 3.9 specifies each phase and its ordering guarantees in full.

### 2.6. Market Data and the As-Of Quote Selector

Futures prices enter the system as market quotes posted by a `PlatformAdmin`. Each quote records a `commodity` — one of `BEAN`, `OIL`, or `MEAL` — a `quote_month` in `YYYY-MM` format (for example, 2026-11), a `price_cents`, and the `quote_date` at which the quote is effective. Quote units follow the board's convention: bean quotes are cents per bushel, while oil and meal quotes are cents per pound. Prices may be negative; the system accepts and uses them exactly as posted.

Whenever a workflow needs the futures price for a commodity and month, it uses the as-of selector: among all quotes for that `commodity` and `quote_month`, the selector picks the one with the latest `quote_date` that is still on or before the current logical clock, and ties on `quote_date` are broken by the latest `created_at`. The selector prices basis and deferred pricing elections, the planned and realized crush margins, board crush locks and offsets, and carry assessments. When a required leg has no eligible quote, the operation that needed it is rejected with `ERR_NO_MARKET_QUOTE` (HTTP 422). Quote lists can be filtered by `commodity` and `quote_month`.

### 2.7. Units, Precision, and Rounding Discipline

Monetary amounts are integer cents everywhere — prices, discounts, premiums, freight charges, claims, margins, and settlements are all whole cents, never fractional and never floating-point approximations. Bushel quantities carry exactly three decimal places, and crush spreads per bushel carry exactly two. All rounding in the system is round half up: a discarded fraction of exactly one half rounds away from zero. Freight charges are the one place a fractional intermediate appears — three-decimal bushels multiplied by an integer cent rate can yield fractional cents — and the product is rounded half up to whole cents before it is stored. Day counts used by storage accrual are whole UTC calendar days computed from date parts only, so an event timestamped at midnight contributes exact integers. Percentage fields — moisture, damage, foreign material, protein, free fatty acids, feedstock share — are plain numbers of percent, not fractions.

### 2.8. Optimistic Concurrency Control

Exactly two writes in the API carry an optimistic concurrency token; no other endpoint accepts a version field.

- A pricing election must carry `expected_contract_version`, the `version` of the origination contract as the client last observed it. If the contract's current `version` no longer matches — because another election, or the forced-pricing sweep, has advanced the contract since that read — the election is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), so the client cannot price against a `priced_bushels` pool it has not observed.
- Scheduling a crush run must carry `expected_run_version`, the `version` of the run as the client last observed it. A mismatch with the run's current `version` is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412), protecting the day's capacity accounting from a stale view of earlier schedule and unschedule cycles.

Both checks are evaluated before any state check: a stale write is rejected without inspecting whether the transition would otherwise be legal.

### 2.9. Validation Priority Order

When a single request violates several rules at once, the system reports exactly one error — the one belonging to the earliest applicable rule in the following fixed order:

1. Authentication: `X-User-Role` present and naming a declared role (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted on the endpoint and, for entity-backed callers, the caller owns the target resource (`ERR_FORBIDDEN`).
3. Path existence: every identifier in the URL path resolves to an existing entity, checked left-to-right along the path; the first failure produces that resource's not-found error — `ERR_CONTRACT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SALES_CONTRACT_NOT_FOUND`, `ERR_ELEVATOR_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, or `ERR_PROGRAM_NOT_FOUND`.
4. Body references: every foreign key supplied in the request body resolves — `farmer_id` to `ERR_FARMER_NOT_FOUND`, `elevator_id` to `ERR_ELEVATOR_NOT_FOUND`, `program_id` and `certified_program_id` to `ERR_PROGRAM_NOT_FOUND`, `active_discount_schedule_id` to `ERR_SCHEDULE_NOT_FOUND`, `contract_id` to `ERR_CONTRACT_NOT_FOUND`, `lane_id` to `ERR_LANE_NOT_FOUND`, `buyer_id` to `ERR_BUYER_NOT_FOUND`, and `plant_id` to `ERR_PLANT_NOT_FOUND`.
5. Stale versions: the optimistic concurrency tokens of §2.8 (`ERR_STALE_CONTRACT_VERSION`, `ERR_STALE_RUN_VERSION`). A stale write never observes state.
6. State preconditions: the target entity is in a state that permits the transition — ticket `RECEIVED`, contract not yet `PRICED` for elections, contract `DELIVERED` and `PRICED` for settlement, run `PLANNED` for scheduling, position `ENTERED` for confirmation or `CONFIRMED` for offset, shipment `BOOKED` for delivery or cancellation (`ERR_INVALID_STATE`, with the dedicated variants `ERR_CONTRACT_NOT_PRICABLE`, `ERR_CONTRACT_NOT_SETTLEABLE`, and `ERR_POSITION_NOT_CONFIRMED` where §3 names them).
7. Temporal rules: run dates and shipment departures not in the past (`ERR_RUN_DATE_IN_PAST`), sales windows well-formed and deliveries inside them (`ERR_DELIVERY_WINDOW_INVALID`, `ERR_DELIVERY_OUTSIDE_WINDOW`), arrival reached before a shipment is delivered (`ERR_SHIPMENT_NOT_ARRIVED`), and deferred-pricing deadlines in the future at contract creation (`ERR_DELIVERY_WINDOW_INVALID`).
8. Safety rules: segregation of duties on hedge confirmation (`ERR_SEGREGATION_OF_DUTIES`) and the certified chain of custody on shipment draws (`ERR_CERTIFICATION_BREAK`).
9. Shape and quantity rules: missing required fields, invalid enum or numeric values, type-matched price and quality-spec fields, positive quantities, and no over-fill (`ERR_INVALID_REQUEST`, `ERR_OVER_DELIVERY`, `ERR_PRICING_EXCEEDS_QUANTITY`, `ERR_QUALITY_SPEC_FAILED`).
10. Capacity rules: the elevator receiving gate and storage headroom (`ERR_ELEVATOR_AT_CAPACITY`), plant per-day crush capacity (`ERR_PLANT_CAPACITY_EXCEEDED`), truck and rail lane daily capacity (`ERR_LANE_DAILY_CAPACITY_EXCEEDED`), barge interval overlap (`ERR_BARGE_SCHEDULE_OVERLAP`), drawable bushels at the origin (`ERR_INSUFFICIENT_STORED_BUSHELS`), plant bean inventory at run start (`ERR_INSUFFICIENT_PLANT_INVENTORY`), and the biodiesel feedstock quota (`ERR_FEEDSTOCK_QUOTA_EXCEEDED`).
11. Referenced-entity state: a published discount schedule for elevator creation (`ERR_SCHEDULE_NOT_PUBLISHED`), an active program for certified contracts (`ERR_PROGRAM_CLOSED`), an active plant for run scheduling (`ERR_PLANT_NOT_ACTIVE`), an active buyer for sales creation (`ERR_BUYER_NOT_ACTIVE`), market quotes for every priced operation (`ERR_NO_MARKET_QUOTE`), and a non-empty lane pool for routing quotes (`ERR_NO_ROUTE_AVAILABLE`).
12. Fiscal viability: the non-negative planned margin on crush-run scheduling (`ERR_NEGATIVE_CRUSH_MARGIN`), always the last check evaluated.

### 2.10. Derived Inventory Counters and Cross-Entity Consistency

Several entities carry read-only counters that the server derives from other entities' activity; clients never write them directly. An elevator's `stored_bushels` is the sum of `current_bushels` over all storage positions at that elevator, and its `certified_stored_bushels` is the same sum restricted to positions enrolled in a sustainability program; both are recomputed on every ticket apply, every shipment booking, and every shipment cancellation. From `stored_bushels` the server re-derives `receiving_open` after every change: the gate is false exactly when `stored_bushels` has reached `storage_capacity_bushels`, and while it is false the elevator rejects new delivery tickets. A crush plant's `bean_inventory_bushels` rises when shipments are marked delivered and falls when crush runs start. A buyer's `open_claims_count` counts that buyer's defaulted sales contracts. An origination contract's `delivered_bushels`, `priced_bushels`, `priced_value_cents`, `unpriced_pool_bushels`, and settlement fields are likewise server-maintained. Every such recomputation is a mutation of the owning entity: `updated_at` refreshes and `version` increments with it, and the new values are visible in the triggering request's response and in every subsequent read. Consistency is immediate — there is no caching tier and no delayed projection anywhere between a write and a read.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Counterparties, Sites, and Reference Data

Before a single bushel moves, a `PlatformAdmin` builds the commercial landscape. Farmers are registered with a `legal_name` and the `county` of the home farm operation. Buyers are registered with a `company_name` and begin life `ACTIVE` with an `open_claims_count` of zero. Crush plants are registered with a `name`, a `daily_crush_capacity_bushels` and a `daily_refinery_capacity_lbs` (both must be positive), and a `biodiesel_feedstock_share_pct` between 0 and 100 that reserves a share of refinery capacity for feedstock demand; a plant may be registered directly in `MAINTENANCE` status when the operator knows the site is down, and otherwise starts `ACTIVE` with `bean_inventory_bushels` at zero. Only `ACTIVE` plants accept crush-run scheduling.

Quality policy arrives as a discount schedule, created in `DRAFT` with a `name` and the full grading grid: `moisture_base_pct` (the moisture at or below which nothing is charged), `moisture_shrink_pct_per_point`, `moisture_discount_cents_per_point`, `damage_free_pct`, `damage_discount_cents_per_point`, `fm_free_pct`, `fm_discount_cents_per_point`, and the `reject_moisture_pct` ceiling above which a load is refused outright. Publishing is a one-way door: a `PlatformAdmin` publishes a `DRAFT` schedule, moving it to `PUBLISHED`, which is terminal, increments the schedule's `version`, and makes it pinnable to elevators. An elevator is then registered with a `name`, a `region`, a positive `storage_capacity_bushels`, and an `active_discount_schedule_id` that must reference a schedule already `PUBLISHED` — anything else is rejected `ERR_SCHEDULE_NOT_PUBLISHED`. The pin is for the elevator's lifetime: every ticket ever applied at that elevator grades against that exact schedule. A new elevator starts with `stored_bushels` and `certified_stored_bushels` at zero and `receiving_open` true. Elevator lists can be filtered by `active_discount_schedule_id`.

Certified crop streams are declared as sustainability programs with a `name`, a `cert_standard` of `ISCC`, `REGEN`, or `ORGANIC`, and a non-negative `premium_cents_per_bushel` paid per net bushel on certified delivery tickets. Programs are born `ACTIVE`; a `SustainabilityAuditor` may close one, moving it to `CLOSED` — terminal and version-incrementing — after which any new origination contract naming the program is rejected `ERR_PROGRAM_CLOSED`. Market data, finally, flows in as the append-only quotes of §2.6.

### 3.2. Writing the Origination Contract: Cash, Basis, and Deferred Pricing

An `OriginationMerchandiser` originates bushels by writing a contract that names the grower (`farmer_id`), the delivery destination (`elevator_id`), optionally a certified stream (`program_id`, left null for conventional bushels), a `contract_type` of `CASH`, `BASIS`, or `DEFERRED`, and a positive `quantity_bushels` carried to three decimals. When `program_id` is present it must resolve to a program that is still `ACTIVE`; naming a `CLOSED` program is rejected `ERR_PROGRAM_CLOSED`.

The price fields are type-matched, and the matching is strict in both directions. A `CASH` contract requires `cash_price_cents_per_bushel` and forbids the basis, futures-month, deadline, and storage-rate fields. A `BASIS` contract requires `basis_cents_per_bushel` — which may be negative, reflecting a basis booked under the board — together with a `futures_month` in `YYYY-MM` form, and forbids the cash, deadline, and storage-rate fields. A `DEFERRED` contract requires `futures_month`, a `pricing_deadline` that must still be in the future at creation (`ERR_DELIVERY_WINDOW_INVALID` otherwise), and a non-negative `storage_rate_cents_per_bushel_day`, and forbids the cash and basis fields. Supplying a field the chosen type forbids, or omitting one it requires, is `ERR_INVALID_REQUEST`.

Pricing state and fulfillment state are independent parallel dimensions, and the contract tracks both from birth. Fulfillment always starts `OPEN` on the `fulfillment_status` dimension. Pricing starts `PRICED` on the `pricing_status` dimension for `CASH` — creation seeds `elections` with a single election covering the full `quantity_bushels` at the agreed `cash_price_cents_per_bushel`, sets `priced_bushels` equal to `quantity_bushels`, and sets `priced_value_cents` to their exact integer product — and starts `UNPRICED` for `BASIS` and `DEFERRED`, which accumulate price later through elections. Thereafter a contract is `PRICED` exactly when `priced_bushels` equals `quantity_bushels`, and `PARTIALLY_PRICED` whenever some but not all of the quantity is priced. The remaining server-maintained fields start at zero or null: `delivered_bushels`, `accrued_storage_cents`, and `unpriced_pool_bushels` at zero; `last_accrual_date` null while the unpriced pool is empty; and the three settlement figures `settlement_line_total_cents`, `settlement_accrual_deduction_cents`, and `settlement_net_payable_cents` null until settlement defines them. The provisional `estimated_settlement_cents` is refreshed on every ticket apply and every pricing election, and is null whenever a futures quote needed to value unpriced bushels is missing.

A `Farmer` caller sees only its own contracts: reads and elections on a contract whose `farmer_id` does not match the caller's `X-User-ID` are `ERR_FORBIDDEN`. Contract lists can be filtered by `farmer_id`, `elevator_id`, `program_id`, `pricing_status`, or `fulfillment_status`.

### 3.3. Delivery Tickets, Quality Grading, and the Storage Cascade

When a truck pulls onto the scale, the `OriginationMerchandiser` writes a delivery ticket against a contract: the `contract_id`, the scale-ticket `gross_bushels` (which must be positive), and the measured `moisture_pct`, `damage_pct`, and `foreign_material_pct` (each zero or greater). Creation is gated twice: the contract's fulfillment must be `OPEN` or `DELIVERING`, and the destination elevator's `receiving_open` gate must be true — a full house rejects the ticket with `ERR_ELEVATOR_AT_CAPACITY` before a kernel is graded. The new ticket is born `RECEIVED`, with `elevator_id` and `program_id` copied from its contract, so a certified contract's deliveries stay inside the certified stream from the moment they arrive. Ticket lists can be filtered by `contract_id`, `elevator_id`, `schedule_id`, or `program_id`.

Applying the ticket is where grading happens, and it is legal only while the ticket is `RECEIVED` and the contract's fulfillment is still `OPEN` or `DELIVERING`; anything else is `ERR_INVALID_STATE`. The apply pins the elevator's `active_discount_schedule_id` onto the ticket as `schedule_id` — version-pinning, so a schedule published later never rewrites a grade already taken — and computes the grading factors from that pinned schedule. The excess moisture is the amount by which `moisture_pct` exceeds `moisture_base_pct`, floored at zero; excess damage and excess foreign material are the same construction against `damage_free_pct` and `fm_free_pct`. Weight shrink is the `gross_bushels` multiplied by the excess moisture points multiplied by `moisture_shrink_pct_per_point`, divided by one hundred, rounded half up to three decimals, and stored as `shrink_bushels`; `net_bushels` is the gross minus the shrink, again at three decimals. The `discount_cents_per_bushel` is the sum of three products — excess moisture points times `moisture_discount_cents_per_point`, excess damage points times `damage_discount_cents_per_point`, and excess foreign-material points times `fm_discount_cents_per_point` — rounded half up to whole cents. The `premium_cents_per_bushel` is the program's `premium_cents_per_bushel` when the contract carries a `program_id`, and zero for conventional bushels. Until the apply, all four computed fields are null.

Two outcomes share the apply. When `moisture_pct` is strictly greater than the pinned schedule's `reject_moisture_pct`, the load is refused: the ticket moves to `REJECTED`, the grading fields are still computed for the record, and the apply returns 200 with the rejected ticket — a business outcome, not a request error — while no contract, position, or elevator state changes. Otherwise the ticket moves to `APPLIED`, its `applied_date` is stamped from the logical clock, and a four-hop cascade runs. First, the contract's `delivered_bushels` grows by `net_bushels`; for a `DEFERRED` contract the delivery also joins the unpriced pool — the accrual of §3.4 first runs any pending leg through the apply instant, then `unpriced_pool_bushels` grows by `net_bushels` and `last_accrual_date` is set to the apply instant. Second, fulfillment auto-advances: the first apply that leaves delivered bushels short of the contract moves `OPEN` to `DELIVERING`; an apply that exactly fills the contract moves `OPEN` or `DELIVERING` straight to `DELIVERED`; further partial applies hold at `DELIVERING`. Third, a storage position is created at the elevator with `source_ticket_id` pointing at the ticket, the ticket's `program_id` (a non-null program marks a certified lot that only certified shipments may draw), and both `bushels_initial` and `current_bushels` set to the ticket's `net_bushels`, in status `OPEN`. Fourth, the elevator's `stored_bushels` — and `certified_stored_bushels` when the lot is certified — grows by `net_bushels`, and `receiving_open` is re-derived, so the apply that fills the house is also the apply that closes the gate. The ticket's `version` increments, and the contract's provisional `estimated_settlement_cents` is recomputed.

On the applied branch, two quantity guards ride along, in this order. Over-delivery is refused when the contract's `delivered_bushels` plus the ticket's `net_bushels` would exceed `quantity_bushels` — `ERR_OVER_DELIVERY`. Storage headroom is refused when the elevator's `stored_bushels` plus `net_bushels` would exceed `storage_capacity_bushels` — `ERR_ELEVATOR_AT_CAPACITY`. Both guards need the computed `net_bushels`, which is one reason grading always runs, on both branches.

Storage is a trading decision as much as a physical one, and the carry assessment is the elevator's read on it. Asked with a `nearby_month` and a `deferred_month`, the assessment computes the month gap between the two — twelve times the year difference plus the month difference, which must be strictly positive or the request is `ERR_INVALID_REQUEST` — prices both legs with the as-of bean selector (`ERR_NO_MARKET_QUOTE` when either leg is missing), and charges five cents per bushel per month of storage across the gap. The `signal_cents_per_bushel` is the deferred quote minus the nearby quote minus that storage cost, and the `decision` is `CARRY` exactly when the signal is strictly positive — a signal of exactly zero is `FLAT`, because the market must pay strictly more than the cost of storage before holding bushels is worth the space. The response carries the two leg prices as `nearby_price_cents` and `deferred_price_cents`, plus the computed `storage_cost_cents_per_bushel`, the `signal_cents_per_bushel`, and the `decision`.

### 3.4. Pricing Elections, Deferred Storage Accrual, and Settlement

A `BASIS` or `DEFERRED` contract earns its price through elections. Either the `OriginationMerchandiser` or the owning `Farmer` may elect, supplying `bushels` and the optimistic-concurrency token `expected_contract_version`. The version check runs first — a mismatch is `ERR_STALE_CONTRACT_VERSION` — then pricability: a `CASH` contract, or one already `PRICED`, rejects with `ERR_CONTRACT_NOT_PRICABLE`. The elected bushels must be positive and must not push `priced_bushels` past `quantity_bushels`, or the election is `ERR_PRICING_EXCEEDS_QUANTITY`. For a `DEFERRED` contract the election must arrive while the logical clock is still on or before the `pricing_deadline`; past it, the sweep has already priced the contract in full, and it is the pricability check that turns the late election away. Finally, the as-of bean quote for the contract's `futures_month` must exist (`ERR_NO_MARKET_QUOTE`).

The unit price of an election is the as-of bean futures price — plus the locked `basis_cents_per_bushel` for a `BASIS` contract — and the election is appended to `elections` with its `bushels`, the computed `unit_price_cents`, the `elected_at` instant, and an `origin` of `CLIENT`. The contract accumulates: `priced_bushels` grows by the elected bushels, and `priced_value_cents` grows by their exact integer product with the unit price. An election that prices every remaining bushel moves pricing to `PRICED`; anything short moves `UNPRICED` to `PARTIALLY_PRICED` or holds it there through further partial elections. The contract's `version` increments and the provisional `estimated_settlement_cents` is recomputed.

Deferred pricing carries a service charge, and it accrues like rent. The accrual unit is the whole UTC calendar day between date parts. Whenever a pricing event — client or forced — prices bushels out of the unpriced pool, the pending leg is finalized first: `accrued_storage_cents` grows by `storage_rate_cents_per_bushel_day` multiplied by the pool's `unpriced_pool_bushels` multiplied by the whole days from `last_accrual_date` to the event. Only then does the pool shrink by the elected bushels, never below zero, and `last_accrual_date` resets to the event instant — or to null when the pool empties. Deliveries feed the pool symmetrically, as §3.3 describes. Once a contract reaches `PRICED` the accrual stops: the final leg runs through the final pricing instant and the balance freezes.

When fulfillment has reached `DELIVERED` and pricing has reached `PRICED` — and only then — an `OriginationMerchandiser` may settle; any other combination is `ERR_CONTRACT_NOT_SETTLEABLE`. Because `DELIVERED` means delivered equals contracted and `PRICED` means priced equals contracted, settlement consumes both pools exactly. The final settlement walks the applied tickets in `applied_date` order, ties broken by `created_at`, and consumes elections first-in-first-out in the order they were appended to `elections`; rejected tickets never participate. A ticket whose bushels straddle two elections contributes one sub-line per election segment: the segment's net bushels multiplied by that election's unit price, minus the ticket's `discount_cents_per_bushel`, plus its `premium_cents_per_bushel`. The rounding order is pinned and load-bearing: each line or sub-line is rounded half up to whole cents first, and only then are the rounded lines summed — the alternative of summing exact values and rounding once is not used, and it produces different cents on fractional nets. The sum becomes `settlement_line_total_cents`; `settlement_accrual_deduction_cents` is the frozen `accrued_storage_cents`; and `settlement_net_payable_cents` is the line total minus the accrual deduction. The contract moves to `SETTLED`, terminal, and its `version` increments.

The provisional estimate mirrors this machinery while the contract is live. `estimated_settlement_cents` applies the same FIFO line math to the tickets applied so far, values bushels not yet covered by any election at the current as-of futures-derived unit price — basis plus futures for `BASIS`, futures alone for `DEFERRED`, while a `CASH` contract is fully covered from creation — and takes the accrual as the frozen `accrued_storage_cents` plus the pending leg through the present instant. It is null whenever a required futures quote is missing, and it moves with the market until settlement replaces it with the final figures.

### 3.5. Freight Lanes, Routing Quotes, and Shipments

A `LogisticsCoordinator` builds the haulage network as freight lanes, each running from an `origin_elevator_id` to a `destination_plant_id` with a `mode` of `TRUCK`, `RAIL`, or `BARGE`, a non-negative `freight_cents_per_bushel`, a `transit_days` count of calendar days, and a positive `daily_capacity_bushels`. The capacity field governs per-departure-date totals for truck and rail; barges ignore it, because barge occupancy is governed by interval semantics instead. Lane lists can be filtered by `origin_elevator_id` or `destination_plant_id`.

Destination optimization is a computed read. Asked for a routing quote out of an origin elevator for a given `bushels`, the system considers every lane from that origin whose destination plant is `ACTIVE` and whose capacity admits the load — every barge lane qualifies on capacity grounds, while a truck or rail lane qualifies only when its `daily_capacity_bushels` is at least the requested `bushels`. Eligible lanes rank by `freight_cents_per_bushel` ascending, then `transit_days` ascending, then the lane's `created_at` ascending; no random factor participates and identifiers never break ties. An empty candidate pool is rejected `ERR_NO_ROUTE_AVAILABLE`.

Booking a shipment takes a `lane_id`, a positive `bushels`, a `departure_date` on or after the current clock date (an earlier date is `ERR_RUN_DATE_IN_PAST`), and an optional `certified_program_id`. The booking draws the bushels out of the origin elevator's storage lots oldest-first by `created_at`, appending each draw — the `position_id` and the drawn `bushels` — to the shipment's `draws` log in draw order and decrementing each lot's `current_bushels`; a lot whose balance reaches zero flips from `OPEN` to `DEPLETED`. Chain of custody is enforced at the draw: a shipment carrying `certified_program_id` may draw only lots of that same program, and when the certified supply cannot fill the booking the request is `ERR_CERTIFICATION_BREAK`; a shipment without it may draw only conventional lots, and any shortfall of drawable bushels within the requested certification class is `ERR_INSUFFICIENT_STORED_BUSHELS`. The elevator's `stored_bushels` — and `certified_stored_bushels` for a certified draw — falls by the shipped amount, and `receiving_open` re-derives, so a booking that pulls a full house back below capacity reopens the gate. Lane occupancy is enforced by mode: for truck and rail, the sum over the lane's non-cancelled shipments sharing the departure date, plus the new booking, must not exceed `daily_capacity_bushels` (`ERR_LANE_DAILY_CAPACITY_EXCEEDED`); for barges, the half-open interval from `departure_date` to `arrival_date` — departure inclusive, arrival exclusive — must not overlap any other booked barge movement on the same lane, though back-to-back runs where one barge's arrival equals the next departure are legal (`ERR_BARGE_SCHEDULE_OVERLAP`). The booking computes `arrival_date` as the departure plus the lane's `transit_days` calendar days and `freight_cost_cents` as the `bushels` multiplied by the lane's `freight_cents_per_bushel`, rounded half up to whole cents, and the shipment is born `BOOKED`. Shipment lists can be filtered by `lane_id` or `certified_program_id`.

Delivery credits the plant. Once the logical clock has reached `arrival_date` — before that, the attempt is `ERR_SHIPMENT_NOT_ARRIVED` — the coordinator marks the shipment delivered: it moves from `BOOKED` to `DELIVERED`, terminal, the destination plant's `bean_inventory_bushels` grows by the shipped bushels, and the shipment's `version` increments. Cancellation is the mirror image and is legal only from `BOOKED`: every entry in `draws` is restored in reverse draw order, each lot's `current_bushels` climbing back by exactly what was drawn — a `DEPLETED` lot that rises above zero returns to `OPEN` — the elevator's stored and certified counters recover and the gate re-derives, the lane occupancy frees for rebooking, and the shipment lands in `CANCELLED`, terminal, with a version increment. Any deliver or cancel attempt on a shipment no longer `BOOKED` is `ERR_INVALID_STATE`. Storage lots themselves are readable on their own, and lot lists can be filtered by `elevator_id`, `source_ticket_id`, or `program_id`.

### 3.6. Crush Runs: Planning, Scheduling, and the Crush Margin

A `PlantScheduler` plans a crush run by naming the `plant_id`, the `run_date` — canonicalized to UTC midnight of the campaign day — a positive whole-bushel `planned_bushels`, and the `futures_month` whose board prices the margin. Creation requires the as-of bean, oil, and meal quotes for that month (`ERR_NO_MARKET_QUOTE` when any leg is missing) and computes the run's economics immediately. Expected yields come off the standard crush: eleven pounds of oil per bushel land in `expected_oil_lbs` and forty-seven pounds of meal per bushel land in `expected_meal_lbs`. The `spread_cents_per_bushel` is the oil quote multiplied by eleven, plus the meal quote multiplied by forty-seven, minus the bean quote, rounded half up to two decimals; `planned_margin_cents` is that spread multiplied by `planned_bushels`, rounded half up to whole cents. The run is born `PLANNED` with `realized_margin_cents` null. Run lists can be filtered by `plant_id`.

Scheduling commits the run to its day, and it is the most heavily guarded transition in the plant workflow. The request must carry `expected_run_version`; a stale token is `ERR_STALE_RUN_VERSION`, rejected before any state inspection. The run must be `PLANNED` (`ERR_INVALID_STATE`). Under the priority order of §2.9 the remaining gates then fall in line: the `run_date` must not be before the current clock date (`ERR_RUN_DATE_IN_PAST`); the plant's per-day aggregate — the sum of `planned_bushels` over that plant's runs in `SCHEDULED`, `RUNNING`, or `COMPLETE` on the same `run_date`, plus this run's own bushels — must not exceed `daily_crush_capacity_bushels` (`ERR_PLANT_CAPACITY_EXCEEDED`); the plant must be `ACTIVE` (`ERR_PLANT_NOT_ACTIVE`); and finally the fiscal check, always last: `planned_margin_cents` must not be negative (`ERR_NEGATIVE_CRUSH_MARGIN`). A successful schedule moves the run to `SCHEDULED` and increments its `version`.

From `SCHEDULED` the scheduler may still retreat. A revert — requested through the run's transition capability with `to_status` set to `PLANNED` — moves the run back to `PLANNED`, frees the day's aggregate capacity, and increments the version. Starting the run (`to_status` `RUNNING`) is legal from `SCHEDULED`, requires the plant's `bean_inventory_bushels` to be at least `planned_bushels` (`ERR_INSUFFICIENT_PLANT_INVENTORY`), and debits exactly that much from the plant's inventory as the run moves to `RUNNING`. Completing the run (`to_status` `COMPLETE`) is legal from `RUNNING`, requires as-of bean, oil, and meal quotes for the run's `futures_month` (`ERR_NO_MARKET_QUOTE`), and writes the realized economics: the spread is recomputed from the completion-time quotes and `realized_margin_cents` is set to `planned_bushels` multiplied by the new spread, rounded half up to whole cents — the realized variant supersedes the planned margin whenever the board moved in between. Cancellation (`to_status` `CANCELLED`) is legal from `PLANNED` or `SCHEDULED` and, like `COMPLETE`, is terminal. Every transition increments the run's `version`, and a `to_status` that names a state the run's current state cannot reach is `ERR_INVALID_STATE`.

### 3.7. Board Crush Hedges and Segregation of Duties

The hedge desk manages margin risk with board crush positions: long bean futures against short oil and meal in the same futures month. A `CrushTrader` enters a position with a `futures_month` shared by all three legs, a `bean_lots_long` of at least one, an `oil_lots_short` and a `meal_lots_short` of zero or more, and an `expiry_date`. Entry locks the economics from the as-of quotes (`ERR_NO_MARKET_QUOTE` when any leg is missing): `locked_spread_cents_per_bushel` is the same crush-spread construction as §3.6 — the oil quote times eleven, plus the meal quote times forty-seven, minus the bean quote, rounded half up to two decimals — and `locked_margin_cents` is that spread multiplied by `bean_lots_long` multiplied by five thousand bushels per bean futures contract, rounded half up to whole cents. The position is born `ENTERED`, and the desk records who wrote it: `entered_by_user_id` carries the entering trader's `X-User-ID`.

Confirmation belongs to a different pair of hands. A `RiskManager` confirms a position still in `ENTERED`; the confirming user's `X-User-ID` must differ from `entered_by_user_id`, and a match is rejected `ERR_SEGREGATION_OF_DUTIES`. Confirmation is only meaningful before expiry — once the clock passes `expiry_date` the sweep has already moved the position to `EXPIRED`, and it is the state check that turns a late confirm away with `ERR_INVALID_STATE`. A clean confirm records the confirmer as `confirmed_by_user_id`, moves the position to `CONFIRMED`, and increments its `version`.

Offsetting realizes the trade. A `CrushTrader` offsets a `CONFIRMED` position — any other state is `ERR_POSITION_NOT_CONFIRMED` — which requires current as-of bean, oil, and meal quotes for the position's `futures_month` (`ERR_NO_MARKET_QUOTE`). The current spread is recomputed with the same formula used at entry, and `realized_pnl_cents` is the spread's move — the current spread minus `locked_spread_cents_per_bushel` — multiplied by `bean_lots_long` multiplied by five thousand, rounded half up to whole cents; a narrowing spread yields a negative figure, which stands as a realized loss. The position lands in `OFFSET`, terminal, with a version increment. Positions that are never offset die with the clock: the sweep moves both `ENTERED` and `CONFIRMED` positions to `EXPIRED` once `expiry_date` falls behind the logical clock.

### 3.8. Product Sales Contracts, Delivery Windows, and Claims

A `ProductMerchandiser` sells the crush's output through sales contracts naming a `buyer_id`, an origin `plant_id`, a `product` of `SOY_MEAL`, `SOY_OIL`, or `BIODIESEL_FEEDSTOCK`, a positive `quantity_lbs`, a positive `price_cents_per_lb`, and a delivery window running from `delivery_window_start` through `delivery_window_end`, both ends inclusive. The window must be well-formed: the end must come after the start and the span must not exceed sixty-two days, otherwise `ERR_DELIVERY_WINDOW_INVALID`. The buyer must be `ACTIVE` — selling to a suspended buyer is `ERR_BUYER_NOT_ACTIVE`. Quality specifications are product-matched in both directions: `min_protein_pct` is required exactly when the product is `SOY_MEAL`, `max_ffa_pct` is required exactly when the product is `SOY_OIL` or `BIODIESEL_FEEDSTOCK`, and any other combination is `ERR_INVALID_REQUEST`. Biodiesel feedstock carries a plant-level quota: the sum of `quantity_lbs` over every feedstock contract at that plant that has not defaulted, plus the new contract's quantity, must not exceed the plant's `daily_refinery_capacity_lbs` multiplied by its `biodiesel_feedstock_share_pct` divided by one hundred, multiplied across a thirty-day horizon — a breach is `ERR_FEEDSTOCK_QUOTA_EXCEEDED`. A new contract starts `OPEN` with `delivered_lbs` at zero, an empty `deliveries` log, and `claim_cents` null. Sales lists can be filtered by `buyer_id` or `plant_id`, and a `CommercialBuyer` caller sees only its own contracts — any other access is `ERR_FORBIDDEN`.

Deliveries are recorded one at a time against the contract, each appending an immutable entry to the delivery log — which is why a successful delivery records with 201 even though the contract is the resource returned. The merchandiser supplies the `delivery_date`, the `quantity_lbs`, and the measured quality figures: `actual_protein_pct` for meal, `actual_ffa_pct` for oil and feedstock. The date must fall inside the window, both ends inclusive (`ERR_DELIVERY_OUTSIDE_WINDOW`); the delivery must not push `delivered_lbs` past the contracted `quantity_lbs` (`ERR_OVER_DELIVERY`); and the product's spec must hold — protein at least `min_protein_pct` for meal, free fatty acids at most `max_ffa_pct` for oil and feedstock (`ERR_QUALITY_SPEC_FAILED`). A clean delivery appends the entry with its `delivery_date`, `quantity_lbs`, `actual_protein_pct`, `actual_ffa_pct`, and a `recorded_at` stamp, grows `delivered_lbs` by the delivered quantity, increments the contract's `version`, and auto-advances fulfillment: the first delivery short of the full quantity moves `OPEN` to `DELIVERING`, a delivery that exactly fills the contract moves `OPEN` or `DELIVERING` straight to `FULFILLED` — terminal — and further partial deliveries hold at `DELIVERING`.

A window that closes with pounds undelivered is a default, and the clock sweep of §3.9 executes it: the contract moves to `DEFAULTED`, terminal, and the shortfall becomes a claim against the buyer.

### 3.9. The Deadline Sweep: Forced Pricing, Default Claims, and Position Expiry

Every clock advance runs the three-phase sweep synchronously, in this order, before the new `current_utc` is returned. The sweep is the only writer that moves entities without a client request on that entity, and every state it lands is terminal by construction.

Phase one force-prices deferred contracts. Every `DEFERRED` contract whose `pricing_deadline` has fallen behind the new clock and whose pricing is not yet `PRICED` is priced in full: the forced election covers all remaining unpriced bushels at the bean futures quote as-of the deadline date itself, is appended to `elections` with an `origin` of `FORCED` and an `elected_at` of the `pricing_deadline`, and runs the final accrual leg from `last_accrual_date` through the deadline before the pool empties and the anchor clears. A contract whose deadline-date quote does not exist is left unpriced — the sweep does not guess — and is retried on the next advance. Forced and client elections never collide on consumption order, because settlement consumes `elections` strictly in append order.

Phase two defaults lapsed sales contracts. Every sales contract in `OPEN` or `DELIVERING` whose `delivery_window_end` has fallen behind the new clock, with `delivered_lbs` still short of `quantity_lbs`, moves to `DEFAULTED`. Each default sets `claim_cents` to the undelivered pounds multiplied by `price_cents_per_lb` multiplied by ten percent, rounded half up to whole cents; increments the buyer's `open_claims_count` by one; and suspends the buyer — `ACTIVE` to `SUSPENDED`, terminal — the moment the count reaches three open claims. A suspended buyer can no longer be named on a new sales contract (`ERR_BUYER_NOT_ACTIVE`). The phase processes contracts in a deterministic order: `delivery_window_end` ascending, ties broken by `created_at` ascending.

Phase three expires hedge positions. Every board crush position in `ENTERED` or `CONFIRMED` whose `expiry_date` has fallen behind the new clock moves to `EXPIRED`, terminal. Positions already `OFFSET` are untouched, and nothing in the sweep reverses.

## 4. Endpoint Definitions

All endpoints live under the `/api` prefix. Endpoints that create a new resource return 201 with the created resource; the delivery-recording action on a sales contract also returns 201, because each call appends a new immutable entry to the contract's delivery log. All other actions, transitions, computed reads, and plain reads return 200. The table below is a locator only — request fields, preconditions, and side effects are specified by the narratives in §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and run the deadline sweep synchronously | PlatformAdmin |
| POST | `/api/farmers` | Register a farmer counterparty | PlatformAdmin |
| POST | `/api/elevators` | Register an elevator with its lifetime-pinned discount schedule | PlatformAdmin |
| GET | `/api/elevators/{id}` | Read one elevator, including derived storage counters and the receiving gate | PlatformAdmin, OriginationMerchandiser, LogisticsCoordinator |
| GET | `/api/elevators` | List elevators; filterable by `active_discount_schedule_id` | PlatformAdmin, OriginationMerchandiser |
| GET | `/api/elevators/{id}/carry-assessment` | Computed carry-versus-flat decision for stored bushels from nearby and deferred bean quotes | PlatformAdmin, OriginationMerchandiser, CrushTrader |
| POST | `/api/quality-discount-schedules` | Create a quality discount schedule in `DRAFT` | PlatformAdmin |
| POST | `/api/quality-discount-schedules/{id}/publish` | Publish a schedule (`DRAFT` to `PUBLISHED`, terminal) | PlatformAdmin |
| POST | `/api/sustainability-programs` | Create a certified crop stream program (`ACTIVE`) | PlatformAdmin |
| POST | `/api/sustainability-programs/{id}/close` | Close a program (`ACTIVE` to `CLOSED`, terminal) | SustainabilityAuditor |
| POST | `/api/market-quotes` | Post an append-only futures market quote | PlatformAdmin |
| GET | `/api/market-quotes` | List quotes; filterable by `commodity` and `quote_month` | PlatformAdmin, OriginationMerchandiser, CrushTrader, PlantScheduler |
| POST | `/api/crush-plants` | Register a crush plant, optionally directly in `MAINTENANCE` | PlatformAdmin |
| GET | `/api/crush-plants/{id}` | Read one plant, including `bean_inventory_bushels` | PlatformAdmin, PlantScheduler, LogisticsCoordinator |
| POST | `/api/buyers` | Register a meal/oil buyer | PlatformAdmin |
| GET | `/api/buyers/{id}` | Read one buyer, including `status` and `open_claims_count` | PlatformAdmin, ProductMerchandiser |
| POST | `/api/origination-contracts` | Write a cash, basis, or deferred-pricing origination contract | OriginationMerchandiser |
| GET | `/api/origination-contracts/{id}` | Read one contract; Farmer callers must own it | PlatformAdmin, OriginationMerchandiser, Farmer |
| GET | `/api/origination-contracts` | List contracts; filterable by `farmer_id`, `elevator_id`, `program_id`, `pricing_status`, `fulfillment_status` | PlatformAdmin, OriginationMerchandiser, Farmer |
| POST | `/api/origination-contracts/{id}/pricing-elections` | Elect a price for bushels of a basis or deferred contract; OCC on the contract version | OriginationMerchandiser, Farmer |
| POST | `/api/origination-contracts/{id}/settle` | Settle a delivered, fully priced contract (final settlement) | OriginationMerchandiser |
| POST | `/api/delivery-tickets` | Write a scale ticket against a contract | OriginationMerchandiser |
| GET | `/api/delivery-tickets/{id}` | Read one ticket, including computed grading fields | PlatformAdmin, OriginationMerchandiser |
| GET | `/api/delivery-tickets` | List tickets; filterable by `contract_id`, `elevator_id`, `schedule_id`, `program_id` | PlatformAdmin, OriginationMerchandiser |
| POST | `/api/delivery-tickets/{id}/apply` | Grade the ticket against the pinned schedule and apply it, or reject it on moisture | OriginationMerchandiser |
| GET | `/api/storage-positions/{id}` | Read one storage lot | PlatformAdmin, OriginationMerchandiser, LogisticsCoordinator |
| GET | `/api/storage-positions` | List storage lots; filterable by `elevator_id`, `source_ticket_id`, `program_id` | PlatformAdmin, OriginationMerchandiser, LogisticsCoordinator |
| POST | `/api/freight-lanes` | Create a truck, rail, or barge lane from an elevator to a plant | LogisticsCoordinator |
| GET | `/api/freight-lanes/{id}` | Read one lane | PlatformAdmin, LogisticsCoordinator |
| GET | `/api/freight-lanes` | List lanes; filterable by `origin_elevator_id`, `destination_plant_id` | PlatformAdmin, LogisticsCoordinator |
| POST | `/api/shipment-routing-quotes` | Rank the eligible lanes out of an origin elevator for a load | LogisticsCoordinator |
| POST | `/api/shipments` | Book a bean shipment, drawing origin storage lots oldest-first | LogisticsCoordinator |
| GET | `/api/shipments/{id}` | Read one shipment, including its lot draws | PlatformAdmin, LogisticsCoordinator |
| GET | `/api/shipments` | List shipments; filterable by `lane_id`, `certified_program_id` | PlatformAdmin, LogisticsCoordinator |
| POST | `/api/shipments/{id}/deliver` | Mark a booked shipment delivered and credit the plant's bean inventory | LogisticsCoordinator |
| POST | `/api/shipments/{id}/cancel` | Cancel a booked shipment and restore every drawn lot exactly | LogisticsCoordinator |
| POST | `/api/crush-runs` | Plan a crush run and lock its planned margin from as-of quotes | PlantScheduler |
| GET | `/api/crush-runs/{id}` | Read one run, including planned and realized margins | PlatformAdmin, PlantScheduler, CrushTrader |
| GET | `/api/crush-runs` | List runs; filterable by `plant_id` | PlatformAdmin, PlantScheduler, CrushTrader |
| POST | `/api/crush-runs/{id}/schedule` | Schedule a planned run onto its run date; OCC on the run version | PlantScheduler |
| POST | `/api/crush-runs/{id}/transitions` | Drive a run's lifecycle: revert to `PLANNED`, start, complete, or cancel | PlantScheduler |
| POST | `/api/board-crush-positions` | Enter a board crush hedge and lock its spread | CrushTrader |
| GET | `/api/board-crush-positions/{id}` | Read one hedge position | PlatformAdmin, CrushTrader, RiskManager |
| POST | `/api/board-crush-positions/{id}/confirm` | Confirm an entered hedge; segregation of duties applies | RiskManager |
| POST | `/api/board-crush-positions/{id}/offset` | Offset a confirmed hedge and realize its P&L | CrushTrader |
| POST | `/api/product-sales-contracts` | Write a meal, oil, or biodiesel-feedstock sales contract | ProductMerchandiser |
| GET | `/api/product-sales-contracts/{id}` | Read one sales contract; CommercialBuyer callers must own it | PlatformAdmin, ProductMerchandiser, CommercialBuyer |
| GET | `/api/product-sales-contracts` | List sales contracts; filterable by `buyer_id`, `plant_id` | PlatformAdmin, ProductMerchandiser, CommercialBuyer |
| POST | `/api/product-sales-contracts/{id}/deliver` | Record a delivery against the contract (returns 201) | ProductMerchandiser |

## 5. Error Code Catalogue

The catalogue below is a locator only — the trigger condition for each error is specified in the §2 and §3 narratives where the rule lives, not here.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_FARMER_NOT_FOUND | 404 |
| ERR_ELEVATOR_NOT_FOUND | 404 |
| ERR_SCHEDULE_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_POSITION_NOT_FOUND | 404 |
| ERR_LANE_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_PLANT_NOT_FOUND | 404 |
| ERR_RUN_NOT_FOUND | 404 |
| ERR_BUYER_NOT_FOUND | 404 |
| ERR_SALES_CONTRACT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_CONTRACT_NOT_PRICABLE | 409 |
| ERR_CONTRACT_NOT_SETTLEABLE | 409 |
| ERR_POSITION_NOT_CONFIRMED | 409 |
| ERR_STALE_CONTRACT_VERSION | 412 |
| ERR_STALE_RUN_VERSION | 412 |
| ERR_OVER_DELIVERY | 422 |
| ERR_PRICING_EXCEEDS_QUANTITY | 422 |
| ERR_ELEVATOR_AT_CAPACITY | 422 |
| ERR_PLANT_CAPACITY_EXCEEDED | 422 |
| ERR_LANE_DAILY_CAPACITY_EXCEEDED | 422 |
| ERR_BARGE_SCHEDULE_OVERLAP | 409 |
| ERR_DELIVERY_WINDOW_INVALID | 422 |
| ERR_DELIVERY_OUTSIDE_WINDOW | 422 |
| ERR_RUN_DATE_IN_PAST | 422 |
| ERR_SHIPMENT_NOT_ARRIVED | 422 |
| ERR_NEGATIVE_CRUSH_MARGIN | 422 |
| ERR_NO_MARKET_QUOTE | 422 |
| ERR_NO_ROUTE_AVAILABLE | 422 |
| ERR_QUALITY_SPEC_FAILED | 422 |
| ERR_CERTIFICATION_BREAK | 422 |
| ERR_FEEDSTOCK_QUOTA_EXCEEDED | 422 |
| ERR_INSUFFICIENT_STORED_BUSHELS | 422 |
| ERR_INSUFFICIENT_PLANT_INVENTORY | 422 |
| ERR_SCHEDULE_NOT_PUBLISHED | 422 |
| ERR_PROGRAM_CLOSED | 422 |
| ERR_PLANT_NOT_ACTIVE | 422 |
| ERR_BUYER_NOT_ACTIVE | 422 |
