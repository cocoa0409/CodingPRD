# Vehicle Allocation Turn Earn API — Product Requirements Document

## 1. Introduction

Ford's wholesale organization allocates constrained vehicle production to franchised dealers through a recurring turn-and-earn process: each region's historical retail sales rate and current inventory turn drive how much of each model line's production pool that region's dealers earn for the next ordering cycle. This document specifies the API that backs that process end-to-end — from catalog setup (regions, dealers, model lines, commodities), through allocation run publication and per-dealer allocation bookkeeping, to dealer order entry with constrained-feature rationing, retail-versus-stock prioritization, dealer-to-dealer trades, allocation appeals, incentive accrual for aged inventory and volume performance, and transportation scheduling through carrier assignment and delivery.

The system is deliberately closed-loop: order entry consumes earned capacity, deliveries feed the next cycle's sales counts, trades move earned capacity between stores, and appeals adjust pools mid-cycle. Because multiple writers act on the same allocation pool concurrently (orders, trades, appeals, lock operations), optimistic concurrency control on the parent's version number protects every pool-mutating write. All endpoints live under the `/wholesale` mount.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying an `X-User-Role` value that is not one of the declared role names below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are:

- `Anonymous` — placeholder used only to exercise the auth layer; possesses no permissions.
- `RegionalAllocator` — OEM regional allocation staff. Owns regions, dealers, model lines, allocation runs, appeal decisions, trade execution, incentive programs, and the logical clock.
- `Dealer` — franchised dealer user. Enters orders, proposes and negotiates trades, files appeals, and reads own allocations and order visibility.
- `ProductionScheduler` — plant scheduling. Schedules and builds orders and completes retrofits.
- `LogisticsCoordinator` — transportation management. Owns carriers and the shipment lifecycle.
- `CommodityManager` — commodity supply team. Owns commodities and commodity restrictions.

Role identity is resolved as follows. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Dealer` entity; ownership checks on any resource that references a `Dealer` (an order's `dealer_id`, a trade's `from_dealer_id` or `to_dealer_id`, an appeal's `dealer_id`) compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `RegionalAllocator`, `ProductionScheduler`, `LogisticsCoordinator`, `CommodityManager`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it against an entity `id`.
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

All list endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0, with a minimum of 0. List results are always sorted by `created_at` ascending. The `meta` object on a list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full count of matching records before pagination is applied and `has_more` reports whether any records exist beyond the current window.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. There are no exceptions to common-field coverage in this domain: all entities, including the child `DealerAllocation` and the parallel-dimension `CommodityRestriction`, carry the full set. Whenever any rule below says an entity's `version` is bumped, `updated_at` is refreshed to the mutation instant as well.

### 2.5. Validation Pipeline Ordering

Requests are evaluated against a fixed pipeline of checks; the first failure determines the rejection. The pipeline order is:

1. Authentication headers present and role recognized — otherwise `ERR_UNAUTHENTICATED` (401).
2. Role permitted on this endpoint — otherwise `ERR_FORBIDDEN` (403).
3. Entity-backed identity match: for dealer-scoped endpoints, the acting `Dealer` must own the resource — otherwise `ERR_FORBIDDEN` (403).
4. Referenced resources exist, validated left-to-right along the path, then body foreign keys in declared field order — otherwise `ERR_NOT_FOUND` (404).
5. Target resource is in a state from which the requested transition exists — otherwise `ERR_INVALID_STATE` (409).
6. Parent lifecycle gate: the run is `PUBLISHED` for order entry, appeal grant, and trade execution; the dealer is `ACTIVE` for order entry; the carrier is `ACTIVE` for shipment creation — otherwise `ERR_PARENT_NOT_ACTIVE` (409).
7. Configuration constraints on order entry: every commodity code in `configuration.commodity_codes` is a declared `Commodity`, and `customer_ref` is present if and only if `order_kind` is `RETAIL` — otherwise `ERR_INVALID_CONFIGURATION` (422).
8. Commodity cap evaluation for the order — otherwise `ERR_COMMODITY_CAP_EXCEEDED` (422).
9. Allocation pool availability: remaining pool, and retail pool for a `RETAIL` order, must each be at least 1 — otherwise `ERR_ALLOCATION_EXHAUSTED` (422).
10. Trade-execute pool check: the from-dealer's remaining pool must be at least `units` — otherwise `ERR_TRADE_EXCEEDS_POOL` (422).
11. Temporal windows: appeal filing within the filing window, trade action before `expires_at`, `pickup_week` not before the order's `scheduled_week` nor before the current week, and build not before `scheduled_week` — otherwise `ERR_WINDOW_CLOSED` (422). A pickup week strictly earlier than the order's `scheduled_week` specifically is rejected with `ERR_PICKUP_BEFORE_BUILD_WEEK` (422). A trade action at or after `expires_at` specifically is rejected with `ERR_TRADE_EXPIRED` (422).
12. Restriction window overlap: a new restriction for a `(commodity, model line)` pair whose effective window is contained within an `ACTIVE` restriction's window without fully superseding it is rejected with `ERR_RESTRICTION_OVERLAP` (422).
13. Trade referential integrity: the counterpart is in the same region as the proposer, the two dealers differ, and `units` is at least 1 — otherwise `ERR_TRADE_INVALID` (422).
14. Retrofit gate: a retrofit may complete only when the omitting restriction is no longer `ACTIVE` — otherwise `ERR_RETROFIT_BLOCKED` (409).
15. Appeal eligibility: `NEW_POINT` requires the dealer's `opened_on` to be within six months of the run's `published_at`; `MARKET_GAP` requires the dealer's regional share of the line to sit below the regional average — otherwise `ERR_APPEAL_INELIGIBLE` (422).
16. Uniqueness: codes on region, dealer, model line, commodity, and carrier are unique; the `(dealer_id, model_line_id)` `DealerModelLine` pair is unique; at most one non-`CANCELLED` `Shipment` exists per order — otherwise `ERR_DUPLICATE` (409).
17. Request shape: required fields present, enums valid, integer ranges respected — otherwise `ERR_VALIDATION` (400).

Because the pipeline is evaluated in this order, an early failure masks all later ones: a request that is both unauthenticated and malformed returns `ERR_UNAUTHENTICATED`, not `ERR_VALIDATION`.

### 2.6. Optimistic Concurrency Control on Pool-Mutating Writes

Three writes mutate a parent entity's pool and therefore require the caller to assert the parent's last-observed version. The required field and the stale-version rejection are fixed:

- **Order entry.** A dealer creating an order must carry `expected_dealer_allocation_version` equal to the current `version` of the `DealerAllocation` for the order's `(run_id, dealer_id)` pair. If another writer (a prior order accept, a trade execution, or an appeal grant) has advanced that `DealerAllocation`'s `version` since the client last read it, the request is rejected with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412). This prevents the client from pricing an order against a pool it has not observed.
- **Trade execution.** A `RegionalAllocator` executing an accepted dealer trade must carry `expected_run_version` equal to the current `version` of the parent `AllocationRun`. A mismatch — caused, for example, by an intervening lock or appeal grant — is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412).
- **Appeal grant.** A `RegionalAllocator` granting an appeal must carry `expected_run_version` equal to the current `version` of the parent `AllocationRun`. A mismatch — caused by an intervening grant or trade execution — is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412).

Endpoints not listed above do not accept a version field. Every successful pool-mutating write increments the parent's `version` by 1; specifically, an accepted order bumps the `DealerAllocation`'s `version`, a trade execution bumps the `AllocationRun`'s `version` and both affected `DealerAllocation` versions, an appeal grant bumps the `AllocationRun`'s `version` and the affected `DealerAllocation`'s `version`, a run publish or lock bumps the `AllocationRun`'s `version`, and a dealer-allocation lock bumps that `DealerAllocation`'s `version`. A dealer cancelling an `ACCEPTED` order releases pool and therefore also bumps the `DealerAllocation`'s `version`.

### 2.7. Nested Path Resolution

Nested URLs are resolved left-to-right, one path parameter at a time. A request to lock a specific `DealerAllocation` under a specific `AllocationRun` first resolves the run, then resolves the dealer allocation within that run; a missing run yields `ERR_NOT_FOUND` before the dealer allocation is even considered, and a dealer allocation whose `run_id` does not match the path's run is likewise `ERR_NOT_FOUND`. The same discipline applies to all nested reads and writes.

### 2.8. Precision and Rounding

All monetary and unit calculations obey the following precision rules. Earned credits and per-unit incentive figures are carried to 2 decimal places with round-half-up. `days_supply` is reported at 2 decimal places with round-half-up. Raw turn-and-earn share scores (used at run publish and lock) are carried to 6 decimal places with round-half-up before the waterfall distribution runs. Unit counts, thresholds, and install-rate computations are integers, with floor semantics wherever a fractional intermediate would otherwise arise; specifically, the per-dealer turn-and-earn "want" is floored to a whole unit before the waterfall, and the commodity-cap right-hand side is floored to a whole unit before comparison. The retail-reserved figure uses round-half-up exactly once per `final_units` change and is never re-rounded downstream.

### 2.9. Logical Clock and Time-Sensitive Sweeps

The server maintains a logical clock, separate from wall-clock time. At startup, before any clock-set call, the clock reads exactly `2026-09-01T00:00:00Z` and never silently falls back to wall-clock. A `RegionalAllocator` advances the clock by posting a target `to_iso8601` instant to the clock-set capability; the response echoes the resulting `current_utc`. All time-dependent rules — trade expiry, restriction expiry, build eligibility, pickup eligibility, incentive windows, appeal filing windows — are evaluated against this logical clock. Sweep transitions (a `PROPOSED`, `COUNTERED`, or `ACCEPTED` trade moving to `EXPIRED` once `now >= expires_at`, and an `ACTIVE` restriction moving to `EXPIRED` once `now >= effective_to`) are evaluated lazily on read, so a list or detail call reflects the state the logical clock implies at that moment.

### 2.10. Cross-Aggregate Cascades and Parent-Child Propagation

Several operations propagate beyond their primary target. When a `Commodity` is resolved, every `ACTIVE` `CommodityRestriction` on that commodity cascades to `EXPIRED`. When a `Shipment` is marked delivered, its linked `VehicleOrder` cascades from `BUILT` to `DELIVERED`, with the order's `delivered_at` set equal to the shipment's `delivered_at`. When a run is locked, the final earned-credit surplus is written into each affected `DealerModelLine.earned_credit_units` so the next run can pick it up; this is the only persistence path for earned credit across runs. When a new run is created for a model line that already has a `PUBLISHED` run, the existing run transitions to `SUPERSEDED` and every child `DealerAllocation` on the superseded run is frozen at `LOCKED`; the unconsumed pool is not carried over automatically. When a trade executes, the from-dealer's `DealerModelLine.earned_credit_units` is reduced according to the trade-earn penalty so the next run's earned term reflects the traded-away capacity.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup: Regions, Dealers, and Model Lines

Before any allocation can be computed, a `RegionalAllocator` establishes the catalog. Regions are created with a short uppercase alphanumeric `code` (2 to 20 characters, dashes permitted, immutable after creation) and a human-readable `name`; a new region starts in `ACTIVE` status, and may later transition to `CLOSED` (at which point its dealers cease to be eligible for new allocation). Dealers are created inside a region with a unique OEM-facing `dealer_code` (immutable), a `name`, and an `opened_on` date that will later drive the new-point grace window for appeals and allocation floors. A new dealer starts in `ACTIVE` status; the full dealer lifecycle is `ACTIVE`, `SUSPENDED`, and `CLOSED`, and only `ACTIVE` dealers may enter orders or receive allocation. Model lines are created with a unique `model_code` (immutable) and a display `name`, starting in `ACTIVE` status; a retired line is marked `DISCONTINUED`.

On reads, a dealer's `carryover_credit_units` surfaces the aggregate of earned credits across the dealer's `DealerModelLine` rows; it is computed from those rows and not directly writable. Listing endpoints for regions, dealers, and model lines support the usual `limit`/`offset` pagination; region and dealer lists additionally accept `status` filters, and the dealer list accepts a `region_id` filter.

### 3.2. Commodity Constraints and Rationing Windows

A `CommodityManager` owns the supply-side catalog of constrained features. Creating a `Commodity` requires a unique `code` and a `name`; a new commodity starts in `CONSTRAINED` status. When a feature is no longer supply-limited, the manager resolves it, transitioning the commodity to `RESOLVED`; resolving cascades every `ACTIVE` restriction on that commodity to `EXPIRED`. A `RESOLVED` commodity can later be constrained again, returning it to `CONSTRAINED`, at which point new restrictions may be created against it.

A `CommodityRestriction` ties a commodity to a specific model line over a rationing window. The manager supplies `commodity_id`, `model_line_id`, `effective_from` (closed start of the window), `effective_to` (open end; null means open-ended), `install_rate_pct` (an integer from 0 to 100 expressing what percentage of a dealer's accepted orders for the line may carry the feature), and `allow_partial_build` (a boolean, defaulting to false, that permits build-without-feature "surge mode" for overflow units). `effective_to`, when present, must be strictly after `effective_from`. A new restriction starts `ACTIVE` while the logical clock is within `[effective_from, effective_to)` and the commodity is `CONSTRAINED`. When the clock advances past `effective_to`, the restriction becomes `EXPIRED` on the next read. When a newer restriction is created for the same `(commodity_id, model_line_id)` pair, the prior `ACTIVE` restriction becomes `SUPERSEDED`.

The overlap rule is conservative: a new restriction whose window would be contained within an existing `ACTIVE` restriction's window for the same pair, without fully superseding it, is rejected with `ERR_RESTRICTION_OVERLAP`. An `install_rate_pct` of 100 lifts the cap in practice (every accepted order may carry the feature) but the restriction still gates retrofits until the commodity is `RESOLVED`; an `install_rate_pct` of 0 forbids the feature on any new order entirely.

### 3.3. Allocation Runs: From Draft to Published

A `RegionalAllocator` opens an allocation cycle by creating an `AllocationRun` for a `model_line_id` and a `period` label (unique within that line). The run carries `base_units`, the total production pool it distributes, plus a `lookback_start` and `lookback_end` defining the sales-lookback window for turn-and-earn, and a `retail_priority_pct` (an integer from 0 to 100) expressing what share of each dealer's allocation is reserved for retail (customer-named) orders. A `retail_priority_pct` of 0 means stock-only; 100 means retail-only. `lookback_end` must be strictly after `lookback_start`. A new run starts in `DRAFT`, with `published_at` null, and creation auto-creates one `DealerAllocation` child in `OPEN` status per `ACTIVE` dealer in `ACTIVE` regions.

If a run for the same `model_line_id` is already `PUBLISHED` when a new run is created, the existing run is superseded: it transitions to `SUPERSEDED` and every child `DealerAllocation` freezes at `LOCKED`. Only `DealerModelLine.earned_credit_units` persists across the supersede — unconsumed pool does not carry over automatically.

Publishing a `DRAFT` run transitions it to `PUBLISHED`, stamps `published_at`, and bumps its `version` by 1. Publishing is the moment the turn-and-earn math runs against current data: each `DealerAllocation`'s `base_units`, `final_units`, and `retail_reserved_units` are computed at publish. A publish is rejected with `ERR_INVALID_STATE` if the run is not in `DRAFT`. A run with no `DealerAllocation` children (because no eligible dealers exist) cannot be published. A publish that would put a second run for the same line into `PUBLISHED` is rejected with `ERR_RUN_PERIOD_CONFLICT` (HTTP 409).

### 3.4. Turn-and-Earn Base Share (the allocation_share Calculation)

The heart of the run is the turn-and-earn waterfall, computed per `DealerAllocation` at publish (provisional variant) and again at lock (final variant). Only dealers in `ACTIVE` regions whose own status is `ACTIVE` are eligible; anyone else contributes zero.

For each eligible dealer `d` on the run's line:

- `sales[d]` is the count of `d`'s `DELIVERED` orders for the line whose `delivered_at` falls inside the run's lookback window — `lookback_start` inclusive, `lookback_end` exclusive.
- `inv[d]` is the dealer's current `avg_inventory_units` for the line — point-in-time, not a lookback average.
- `turn[d]` is `sales[d]` divided by `inv[d]`, with `inv[d]` floored at 1 when it would otherwise be zero (a dealer with zero inventory is treated as having one unit for the turn rate).

The raw score is a weighted blend: 0.6 times the dealer's share of total eligible sales plus 0.4 times the dealer's share of total eligible turn. If the sum of eligible sales is zero, the sales term contributes zero; likewise for the turn term. If both sums are zero, every eligible dealer receives a raw score of 1 divided by the eligible count. Raw scores are rounded half-up to 6 decimal places before the waterfall.

The waterfall itself: for each dealer, compute the dealer's `want` as `floor(raw[d] * base_units) + earned_credit_units[d]`, where `earned_credit_units` is the carryover from the prior `LOCKED` run recorded on `DealerModelLine`. Process dealers in order of `raw[d]` descending, breaking ties by `opened_on` ascending (older dealers first) and then by `created_at` ascending. Each dealer takes the minimum of its `want` and the remaining pool. The surplus (`want - taken`) accrues to the dealer's `DealerModelLine.earned_credit_units` and rolls into the next run's earned term.

At publish, the result is written to each `DealerAllocation.base_units` (provisional variant — the earned-credit term from the prior `LOCKED` run is included). At lock, the waterfall is recomputed as the final variant: surplus is recomputed as `want - consumed` and written into `DealerModelLine.earned_credit_units` for the next run; `base_units` is not changed by the final variant.

### 3.5. New-Point Floor and Final Pool Arithmetic

A new dealership receives a stocking floor to encourage market entry. If a dealer's `opened_on` is strictly less than 6 months before the run's `published_at`, that dealer's `final_units` is the greater of `base_units + adjustment_units` and the floor of 2 units. If exactly 6 months or more have elapsed, no floor applies and `final_units` is the straight sum `base_units + adjustment_units`. The floor is evaluated at publish and re-evaluated after every appeal grant. A dealer whose `base_units + adjustment_units` is already 2 or more sees no change from the floor.

The retail reserve is then derived from `final_units`: `retail_reserved_units` is `final_units` multiplied by the run's `retail_priority_pct` and divided by 100, rounded half-up. This rounding happens exactly once per `final_units` change and is never re-applied downstream. The retail pool available for new `RETAIL` orders is `retail_reserved_units` minus `retail_consumed_units`. The stock pool available is `(final_units - retail_reserved_units) - (consumed_units - retail_consumed_units)`.

A `RETAIL` order consumes from the retail pool first. When the retail pool is exhausted and the run's `retail_priority_pct` is strictly between 0 and 100, the order may spill into the stock pool provided the stock pool has at least 1 remaining; the spilled unit counts toward `retail_consumed_units` even though it draws from stock capacity. A `STOCK` order may only consume the stock pool — it never touches the retail reserve. When `retail_priority_pct` is exactly 0 or exactly 100, the two pools are exclusive and no spillover occurs.

### 3.6. Dealer Order Entry and the Accept-or-Reject Decision

A `Dealer` enters an order against a `PUBLISHED` run by posting the dealer's own `dealer_id`, the `model_line_id`, the `run_id` of the published run, the `order_kind` (`RETAIL` for a customer-named unit, `STOCK` for inventory), and the `configuration` object — a `trim` string plus a `commodity_codes` array. A `RETAIL` order must also carry `customer_ref`; a `STOCK` order must not. Because order entry mutates the dealer's pool, the request must also carry `expected_dealer_allocation_version` matching the current `version` of the `DealerAllocation` for the `(run_id, dealer_id)` pair, as specified in §2.6.

Order entry creates the order directly in `SUBMITTED` and immediately evaluates accept-or-reject:

1. The dealer must be `ACTIVE`, the run must be `PUBLISHED`, and the dealer's own allocation must have at least 1 unit of remaining pool (with the retail-pool check applied additionally for a `RETAIL` order). If the total pool is exhausted, the order is rejected with `ERR_ALLOCATION_EXHAUSTED`. If a `RETAIL` order finds the retail pool empty and stock spillover is unavailable (either because the stock pool is also empty or because `retail_priority_pct` is 100), the order is likewise rejected with `ERR_ALLOCATION_EXHAUSTED`.
2. For every commodity code in `configuration.commodity_codes` that has an `ACTIVE` `CommodityRestriction` on the order's line, the commodity cap must admit this order. Let `A` be the count of this dealer's orders for the line in this run in any of `ACCEPTED`, `SCHEDULED`, `BUILT`, `DELIVERED`, and let `F` be those among `A` whose configuration includes the commodity code. The cap admits the order if and only if `F + 1` is at most `floor((A + 1) * install_rate_pct / 100)`, evaluated with the pre-accept values of `A` and `F`. An `install_rate_pct` of 100 never binds; an `install_rate_pct` of 0 forbids any order carrying the feature. Failure is `ERR_COMMODITY_CAP_EXCEEDED`.
3. Configuration shape: every entry of `configuration.commodity_codes` must be a declared `Commodity`, and `customer_ref` must be present exactly when `order_kind` is `RETAIL`. Violations yield `ERR_INVALID_CONFIGURATION`.

On accept, the order transitions `SUBMITTED → ACCEPTED`, its `consumed_units` becomes 1, the parent `DealerAllocation`'s `consumed_units` increments by 1 (and `retail_consumed_units` increments by 1 additionally for a `RETAIL` order), the `DealerAllocation`'s `version` bumps by 1, and the dealer's `avg_inventory_units` for the line is recomputed. On reject, the order transitions `SUBMITTED → REJECTED`, which is terminal for ordering — the dealer must create a fresh order to retry.

A dealer may also cancel an order. From `DRAFT` or `SUBMITTED`, cancellation is a simple state change to `CANCELLED`. From `ACCEPTED`, cancellation additionally releases the pool: the order's `consumed_units` becomes 0, the parent `DealerAllocation`'s `consumed_units` decrements by 1 (and `retail_consumed_units` decrements by 1 for a `RETAIL` order), the `DealerAllocation`'s `version` bumps by 1, and the dealer's `avg_inventory_units` is recomputed. The compensating invariant — `consumed_units` on the allocation equals the count of pool-holding children — is preserved. Cancellation accepts an optional `cancel_reason`. Cancelling from any other state is `ERR_INVALID_STATE`. A dealer may only cancel its own orders; attempting to cancel another dealer's order is `ERR_FORBIDDEN`.

### 3.7. Scheduling, Building, and Commodity Surge Mode

Once accepted, an order waits for production. A `ProductionScheduler` schedules an `ACCEPTED` order by posting a `build_week` — an ISO week string in `YYYY-Www` form — that is not earlier than the current logical week. The order transitions `ACCEPTED → SCHEDULED`, stamps `scheduled_week` with the requested `build_week` and `scheduled_at` with the current timestamp, and the scheduling commitment becomes visible to the ordering dealer for customer-order visibility. A `build_week` earlier than the current week is rejected with `ERR_WINDOW_CLOSED`. Scheduling also recomputes the dealer's `avg_inventory_units`.

Building advances the order `SCHEDULED → BUILT`. The build is gated on the logical clock reaching or passing the order's `scheduled_week` — building before the scheduled week is `ERR_WINDOW_CLOSED`. The scheduler may optionally request `build_mode` set to `WITHOUT_FEATURE`. When the order carries a commodity that has an `ACTIVE` restriction on its line and the scheduler requests `WITHOUT_FEATURE`, the restriction must have `allow_partial_build` true; otherwise the build is rejected with `ERR_PARTIAL_BUILD_NOT_ALLOWED`. On a successful `WITHOUT_FEATURE` build, the order's `build_state` transitions to `PENDING_RETROFIT` and the commodity code is dropped from the built configuration. On a normal build (or when no constrained feature is involved), `build_state` remains `NOT_APPLICABLE`. Build stamps `built_at`.

A `PENDING_RETROFIT` order awaits a retrofit work order. A `ProductionScheduler` completes the retrofit once the omitting restriction is no longer `ACTIVE` — either because the commodity was resolved, or because the logical clock has moved past the restriction's `effective_to`, or because the restriction has been superseded by one whose window has not yet started. Completing the retrofit transitions the order's `build_state` to `RETROFITTED` and creates a child `VehicleOrder` row whose `retrofit_of_order_id` points back to the original; the child is immediately `ACCEPTED` but does not consume allocation pool (its `consumed_units` is 0). A retrofit attempted while the omitting restriction is still `ACTIVE` is rejected with `ERR_RETROFIT_BLOCKED`. A retrofit on an order whose state is neither `BUILT` nor `DELIVERED`, or whose `build_state` is not `PENDING_RETROFIT`, is rejected with `ERR_INVALID_STATE`.

### 3.8. Shipments, Carrier Capacity, and Delivery Cascade

A `LogisticsCoordinator` owns carriers and the shipment lifecycle. Carriers are created with a unique `code`, a `name`, and a `weekly_capacity` — the maximum number of `BUILT` units the carrier can pick up per ISO week across all assignments, an integer of at least 1. A new carrier starts `ACTIVE`.

Once an order is `BUILT`, the coordinator assigns it to a carrier by creating a `Shipment` with the `order_id`, the `carrier_id`, and a `pickup_week` in `YYYY-Www` form. Three temporal rules govern the pickup week. It must not be earlier than the order's `scheduled_week` — a violation is `ERR_PICKUP_BEFORE_BUILD_WEEK`. It must not be earlier than the current logical week — a violation is `ERR_WINDOW_CLOSED`. A `pickup_week` equal to the order's `scheduled_week` is allowed (adjacent weeks, gap zero). ISO week strings compare lexicographically after zero-padding. A shipment may be assigned to a carrier for a given `pickup_week` only when the count of that carrier's shipments in `PLANNED` or `PICKED_UP` state with the same `pickup_week` is strictly less than the carrier's `weekly_capacity`. An at-capacity week rejects the assignment with `ERR_CARRIER_CAPACITY`. Each order has at most one non-`CANCELLED` shipment; a second active shipment for the same order is rejected with `ERR_DUPLICATE`. The carrier must be `ACTIVE`; otherwise `ERR_PARENT_NOT_ACTIVE`.

A `PLANNED` shipment can be picked up once the current logical week has reached or passed the `pickup_week`; pickup stamps `picked_up_at` and transitions the shipment `PLANNED → PICKED_UP`. Picking up before the `pickup_week` is `ERR_WINDOW_CLOSED`. A `PICKED_UP` shipment can be marked delivered; delivery stamps `delivered_at` and cascades the linked order `BUILT → DELIVERED`, setting the order's `delivered_at` to the shipment's `delivered_at`. The cascade recomputes the dealer's `reported_sales_units` for the line (chronological inclusion by `delivered_at`), recomputes the dealer's `avg_inventory_units`, and recomputes the provisional incentive accrual. A `PLANNED` shipment may be cancelled; cancellation is `ERR_INVALID_STATE` from any later state.

### 3.9. Dealer-to-Dealer Trades

A `Dealer` may propose shifting allocation to another dealer in the same region by creating a `DealerTrade` with `from_dealer_id` (the proposer, which must match the acting `Dealer`), `to_dealer_id` (the counterpart, which must differ from the proposer and share the proposer's region), the `run_id` of the `PUBLISHED` run whose allocation is being traded, and a `units` count of at least 1. Cross-region trades, self-trades, and `units` below 1 are rejected with `ERR_TRADE_INVALID`. A new trade starts `PROPOSED` and stamps `expires_at` as `created_at` plus the trade time-to-live; after `expires_at`, the system sweeps the trade to `EXPIRED` on the next read.

The counterpart may accept a `PROPOSED` trade, transitioning it to `ACCEPTED`. The counterpart may alternatively counter with a different `counter_units` (at least 1), transitioning `PROPOSED → COUNTERED` and recording the amended `counter_units`. The original proposer may then re-counter, transitioning `COUNTERED → PROPOSED` and updating `units` to the new `counter_units`. This `PROPOSED ↔ COUNTERED` loop may iterate any number of times before expiry. Either party may decline from `PROPOSED` or `COUNTERED`, transitioning to `DECLINED`. The proposer (only) may cancel from `PROPOSED` or `COUNTERED`, transitioning to `CANCELLED`. Any accept, counter, or re-counter attempted at or after `expires_at` is rejected with `ERR_TRADE_EXPIRED`.

An `ACCEPTED` trade is executed by a `RegionalAllocator`. Execution requires the run to still be `PUBLISHED`, requires the from-dealer's `DealerAllocation` remaining pool (`final_units` minus `consumed_units`) to be at least `units` — otherwise `ERR_TRADE_EXCEEDS_POOL` — and requires the request to carry `expected_run_version` matching the run's current `version`, per §2.6. On execution, the trade transitions to `EXECUTED`, stamps `executed_at`, decrements the from-dealer's `final_units` by `units`, increments the to-dealer's `final_units` by `units`, bumps the `AllocationRun`'s `version` by 1 and both affected `DealerAllocation` versions by 1, and applies the trade-earn penalty to the from-dealer: the from-dealer's `DealerModelLine.earned_credit_units` is reduced by `units * 0.5`, floored at 0, rounded half-up to 2 decimals. The to-dealer receives no earned credit for traded-in units — trades do not earn. The penalty is waived entirely when, at execution time, the from-dealer is within 6 months of its `opened_on`.

### 3.10. Allocation Appeals

A `Dealer` may appeal its allocation on a `PUBLISHED` run by filing an `Appeal` with its own `dealer_id`, the `run_id`, an `appeal_type`, and `requested_units` of at least 1. The `appeal_type` is either `NEW_POINT` (the dealer is within the new-point grace window) or `MARKET_GAP` (the dealer claims regional under-representation). Filing stamps `filed_at` and starts the appeal in `FILED` status.

The filing window is measured against the run's `published_at`: an appeal must be filed within the filing window of publication or it is rejected with `ERR_WINDOW_CLOSED`. Eligibility is checked at filing. A `NEW_POINT` appeal requires the dealer's `opened_on` to be within 6 months of the run's `published_at`; outside that window the appeal is rejected with `ERR_APPEAL_INELIGIBLE`. A `MARKET_GAP` appeal requires the dealer's regional share of the line to sit below the regional average; an unsupported claim is likewise `ERR_APPEAL_INELIGIBLE`.

A `RegionalAllocator` moves a `FILED` appeal to `UNDER_REVIEW` by reviewing it. From `UNDER_REVIEW`, the allocator may deny the appeal (transitioning to `DENIED`) or grant it. Granting requires `granted_units` of at least 0 in the payload — a grant of 0 is a denial-in-effect — and requires the run to still be `PUBLISHED`. Granting also requires the request to carry `expected_run_version` matching the run's current `version` per §2.6. For a `NEW_POINT` appeal, eligibility is rechecked at grant: the dealer must still be within 6 months of `opened_on` relative to `published_at`. On grant, the appeal transitions to `GRANTED`, records `granted_units`, the target `DealerAllocation`'s `adjustment_units` increments by `granted_units`, `final_units` is recomputed (with the new-point floor re-applied per §3.5), and both the `AllocationRun`'s `version` and the affected `DealerAllocation`'s `version` bump by 1. Appeal grants do not earn — the dealer's `DealerModelLine.earned_credit_units` is unchanged. The filing dealer may withdraw a `FILED` appeal at any time, transitioning it to `WITHDRAWN`.

### 3.11. Run Lock and the Final Earned-Credit Ledger

When the allocator is satisfied with a cycle, the run is locked in two stages. Each individual `DealerAllocation` must first be locked: locking a child requires the parent run to be `PUBLISHED` and the child to be `OPEN`, transitions the child to `LOCKED`, freezes the child's `consumed_units` and `retail_consumed_units` snapshot, and bumps the child's `version` by 1. Once every child is `LOCKED`, the allocator may lock the run itself.

Run lock requires every child `DealerAllocation` to be `LOCKED` — otherwise `ERR_CHILDREN_NOT_LOCKED` (HTTP 409). It also requires that no `Appeal` on the run be in `FILED` or `UNDER_REVIEW` — otherwise `ERR_APPEALS_OPEN` (HTTP 409). On lock, the run transitions `PUBLISHED → LOCKED`, its `version` bumps by 1, and the final variant of the turn-and-earn waterfall runs: for each child, surplus is recomputed as `want - consumed` and written into the dealer's `DealerModelLine.earned_credit_units`, ready for the next run. Lock does not modify `base_units`. `LOCKED` is absorbing except for supersede — and supersede only fires from `PUBLISHED`, never from `LOCKED`. A locked child still shows trades and appeals that executed before the lock; no further order entry consumes its pool.

### 3.12. Incentive Programs and the Accrual Ledger

A `RegionalAllocator` may attach incentive programs to a model line. An `IncentiveProgram` carries a unique `code`, the `model_line_id`, a `kind`, a `params` object whose shape depends on the kind, a `window_start` (inclusive) and a `window_end` (exclusive, strictly after `window_start`). A new program starts `ACTIVE` while the logical clock is within the window; outside the window its status reads `CLOSED`.

The two kinds are:

- **`AGED_INVENTORY_CREDIT`** — per-unit credit for aged stock. `params` supplies `age_threshold_days`, `credit_per_unit_cents`, `tier2_age_days`, and `tier2_credit_per_unit_cents`. For each `DELIVERED` order by the dealer on the program's line with `delivered_at` inside `[window_start, window_end)`, the order's `age_days` is `delivered_at` minus `scheduled_at` in whole days (floor of any hour remainder). The per-unit credit is `tier2_credit_per_unit_cents` if `age_days` is at least `tier2_age_days`, else `credit_per_unit_cents` if `age_days` is at least `age_threshold_days`, else 0. The boundary is inclusive: an `age_days` exactly equal to `age_threshold_days` pays the tier-1 rate.
- **`VOLUME_BONUS`** — marginal volume tiers over the period's sales. `params` supplies `tier1_threshold`, `tier1_bonus_cents`, `tier2_threshold`, and `tier2_bonus_cents`. Let `S` be the count of `DELIVERED` orders by the dealer on the program's line inside the window. Sales up to and including `tier1_threshold` pay nothing — the first tier pays only on volume strictly above the threshold. Sales from `tier1_threshold + 1` up to and including `tier2_threshold` pay `tier1_bonus_cents` per unit. Sales beyond `tier2_threshold` pay `tier2_bonus_cents` per unit. The boundary is strict: an `S` exactly equal to `tier1_threshold` pays zero.

Accrual is computed in two variants. The provisional variant runs on every order `DELIVERED` event and is readable through the program's per-dealer accruals listing; it may shift as more deliveries land (a volume-bonus tier straddle). The final variant runs at program close and freezes the per-dealer ledger. A `RegionalAllocator` closes a program by calling its close capability; closing transitions the program to `CLOSED`, freezes the final accrual per dealer as a single `amount_cents` figure, and rejects any further accrual mutation with `ERR_PROGRAM_CLOSED`. Operating on a program outside its window, or on an already-`CLOSED` program, is likewise `ERR_PROGRAM_CLOSED`. The per-dealer accruals listing returns one row per dealer with `dealer_id`, the accrued `amount_cents`, and a `variant` field indicating whether the figure is `provisional` or `final`. Incentive amounts are integer cents throughout.

### 3.13. DealerModelLine Aggregates and Customer Visibility

The `DealerModelLine` aggregate is the per-dealer, per-line running ledger that ties the loop together. Its `reported_sales_units` counts the dealer's `DELIVERED` orders for the line whose `delivered_at` falls in the referencing run's lookback window; it is recomputed per run. Its `avg_inventory_units` is the current count of the dealer's orders for the line in `SCHEDULED` or `BUILT` state — point-in-time at evaluation, not a lookback average. Its `days_supply` divides `avg_inventory_units` by the daily sales rate implied by `reported_sales_units` over the lookback window (the lookback window's length in days). When `reported_sales_units` is zero and `avg_inventory_units` is positive, `days_supply` is reported as the sentinel value -1 (positive infinity in mathematical terms); when both are zero, `days_supply` is 0. `days_supply` is reported at 2 decimal places with round-half-up.

The `earned_credit_units` field on `DealerModelLine` is the cross-run carryover: the surplus earned from the last `LOCKED` run, written by the final allocation variant, consumed by the next run's waterfall, reduced by executed trades per the penalty rule, and unaffected by appeals. The dealer's `carryover_credit_units` (visible on the `Dealer` resource) is the read-aggregated sum across the dealer's `DealerModelLine` rows against the latest closed run.

A dealer sees its own `DealerModelLine` rows through the dealer-scoped sub-resource listing, and sees its orders with scheduling commitments (the `scheduled_week` and `scheduled_at` stamps) through the orders listing — the dealer's view is filtered to its own `dealer_id`, and queries accept filters on `run_id`, `model_line_id`, `state`, `order_kind`, and `retrofit_of_order_id` for navigating retrofit work orders. Cross-dealer visibility is denied with `ERR_FORBIDDEN`.

### 3.14. Test-Driving Hooks

Two endpoints exist purely to make the system deterministic under test. The clock-set capability was described in §2.9. Separately, a `RegionalAllocator` may seed an already-built order for a dealer by posting `dealer_id`, `model_line_id`, `run_id`, `order_kind`, an arbitrary past `scheduled_week`, and an optional `customer_ref`. The seeded order is created directly in `BUILT` state with `built_at` and `scheduled_week` derived from the supplied week, bypassing the current-week gates on scheduling and build, and consumes 1 unit of pool exactly as a normal accept would. This hook exists so aged-inventory and lookback-window fixtures can be constructed without driving the full lifecycle.

## 4. Endpoint Definitions

All endpoints are mounted under `/wholesale`. Creating a new resource returns HTTP 201; modifying an existing resource, listing, and detail reads return HTTP 200. Request bodies, response payloads, and side effects are described in §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /wholesale/_clock/set_current_utc | Advance the logical clock to a supplied instant | RegionalAllocator |
| POST | /wholesale/_seed/order-at-week | Seed an already-BUILT order at a pinned past week | RegionalAllocator |
| POST | /wholesale/regions | Create a region | RegionalAllocator |
| GET | /wholesale/regions | List regions | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| GET | /wholesale/regions/{id} | Get one region | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| POST | /wholesale/dealers | Create a dealer | RegionalAllocator |
| GET | /wholesale/dealers | List dealers | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| GET | /wholesale/dealers/{id} | Get one dealer | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| GET | /wholesale/dealers/{id}/model-lines | List the dealer's DealerModelLine rows | RegionalAllocator, Dealer, ProductionScheduler |
| POST | /wholesale/model-lines | Create a model line | RegionalAllocator |
| GET | /wholesale/model-lines | List model lines | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| GET | /wholesale/model-lines/{id} | Get one model line | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| POST | /wholesale/commodities | Create a commodity (starts CONSTRAINED) | CommodityManager |
| GET | /wholesale/commodities | List commodities | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator, CommodityManager |
| POST | /wholesale/commodities/{id}/resolve | Mark a commodity RESOLVED; cascades restrictions to EXPIRED | CommodityManager |
| POST | /wholesale/commodities/{id}/constrain | Return a RESOLVED commodity to CONSTRAINED | CommodityManager |
| POST | /wholesale/commodity-restrictions | Create a restriction; supersedes the ACTIVE restriction for the pair | CommodityManager |
| GET | /wholesale/commodity-restrictions | List restrictions | RegionalAllocator, Dealer, ProductionScheduler, CommodityManager |
| GET | /wholesale/commodity-restrictions/{id} | Get one restriction | RegionalAllocator, Dealer, ProductionScheduler, CommodityManager |
| GET | /wholesale/dealer-model-lines | List DealerModelLine aggregates | RegionalAllocator, Dealer, ProductionScheduler |
| GET | /wholesale/dealer-model-lines/{id} | Get one DealerModelLine | RegionalAllocator, Dealer, ProductionScheduler |
| POST | /wholesale/allocation-runs | Create a run in DRAFT; supersedes existing PUBLISHED run for the line | RegionalAllocator |
| GET | /wholesale/allocation-runs | List runs | RegionalAllocator, Dealer, ProductionScheduler |
| GET | /wholesale/allocation-runs/{id} | Get one run | RegionalAllocator, Dealer, ProductionScheduler |
| POST | /wholesale/allocation-runs/{id}/publish | Publish: compute provisional allocation per child | RegionalAllocator |
| POST | /wholesale/allocation-runs/{id}/lock | Lock the run; writes final earned credits | RegionalAllocator |
| GET | /wholesale/allocation-runs/{id}/dealer-allocations | List the run's DealerAllocation children | RegionalAllocator, Dealer, ProductionScheduler |
| GET | /wholesale/dealer-allocations | List dealer allocations | RegionalAllocator, Dealer, ProductionScheduler |
| GET | /wholesale/dealer-allocations/{id} | Get one DealerAllocation | RegionalAllocator, Dealer, ProductionScheduler |
| POST | /wholesale/allocation-runs/{id}/dealer-allocations/{da_id}/lock | Lock a single dealer allocation | RegionalAllocator |
| POST | /wholesale/orders | Dealer order entry; immediate accept-or-reject | Dealer |
| GET | /wholesale/orders | List orders | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator |
| GET | /wholesale/orders/{id} | Get one order | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator |
| POST | /wholesale/orders/{id}/cancel | Cancel an order from DRAFT/SUBMITTED/ACCEPTED | Dealer |
| POST | /wholesale/orders/{id}/schedule | Assign a build week | ProductionScheduler |
| POST | /wholesale/orders/{id}/build | Build the unit; optional WITHOUT_FEATURE mode | ProductionScheduler |
| POST | /wholesale/orders/{id}/retrofit | Complete a pending retrofit; spawns a retrofit child order | ProductionScheduler |
| POST | /wholesale/dealer-trades | Propose a dealer-to-dealer allocation trade | Dealer |
| GET | /wholesale/dealer-trades | List trades | RegionalAllocator, Dealer |
| GET | /wholesale/dealer-trades/{id} | Get one trade | RegionalAllocator, Dealer |
| POST | /wholesale/dealer-trades/{id}/counter | Counter-propose; loops PROPOSED and COUNTERED | Dealer |
| POST | /wholesale/dealer-trades/{id}/accept | Counterpart accepts a PROPOSED trade | Dealer |
| POST | /wholesale/dealer-trades/{id}/decline | Either party declines | Dealer |
| POST | /wholesale/dealer-trades/{id}/cancel | Proposer cancels | Dealer |
| POST | /wholesale/dealer-trades/{id}/execute | Allocator executes an ACCEPTED trade | RegionalAllocator |
| POST | /wholesale/appeals | File an allocation appeal | Dealer |
| GET | /wholesale/appeals | List appeals | RegionalAllocator, Dealer |
| GET | /wholesale/appeals/{id} | Get one appeal | RegionalAllocator, Dealer |
| POST | /wholesale/appeals/{id}/review | Move appeal to UNDER_REVIEW | RegionalAllocator |
| POST | /wholesale/appeals/{id}/grant | Grant units; adjusts the dealer allocation | RegionalAllocator |
| POST | /wholesale/appeals/{id}/deny | Deny an appeal under review | RegionalAllocator |
| POST | /wholesale/appeals/{id}/withdraw | Filing dealer withdraws a FILED appeal | Dealer |
| POST | /wholesale/incentive-programs | Create an incentive program | RegionalAllocator |
| GET | /wholesale/incentive-programs | List programs | RegionalAllocator, Dealer, ProductionScheduler |
| GET | /wholesale/incentive-programs/{id} | Get one program | RegionalAllocator, Dealer, ProductionScheduler |
| POST | /wholesale/incentive-programs/{id}/close | Close the program; freeze final accruals | RegionalAllocator |
| GET | /wholesale/incentive-programs/{id}/accruals | Per-dealer accrual figures | RegionalAllocator, Dealer |
| POST | /wholesale/carriers | Create a carrier | LogisticsCoordinator |
| GET | /wholesale/carriers | List carriers | RegionalAllocator, ProductionScheduler, LogisticsCoordinator |
| GET | /wholesale/carriers/{id} | Get one carrier | RegionalAllocator, ProductionScheduler, LogisticsCoordinator |
| POST | /wholesale/shipments | Assign a BUILT order to a carrier for a pickup week | LogisticsCoordinator |
| GET | /wholesale/shipments | List shipments | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator |
| GET | /wholesale/shipments/{id} | Get one shipment | RegionalAllocator, Dealer, ProductionScheduler, LogisticsCoordinator |
| POST | /wholesale/shipments/{id}/pickup | Mark picked up | LogisticsCoordinator |
| POST | /wholesale/shipments/{id}/deliver | Mark delivered; cascades the order to DELIVERED | LogisticsCoordinator |
| POST | /wholesale/shipments/{id}/cancel | Cancel a PLANNED shipment | LogisticsCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflow they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_PARENT_NOT_ACTIVE | 409 |
| ERR_STALE_ALLOCATION_VERSION | 412 |
| ERR_STALE_RUN_VERSION | 412 |
| ERR_INVALID_CONFIGURATION | 422 |
| ERR_COMMODITY_CAP_EXCEEDED | 422 |
| ERR_ALLOCATION_EXHAUSTED | 422 |
| ERR_TRADE_EXCEEDS_POOL | 422 |
| ERR_TRADE_INVALID | 422 |
| ERR_TRADE_EXPIRED | 422 |
| ERR_WINDOW_CLOSED | 422 |
| ERR_PICKUP_BEFORE_BUILD_WEEK | 422 |
| ERR_RESTRICTION_OVERLAP | 422 |
| ERR_RETROFIT_BLOCKED | 409 |
| ERR_APPEAL_INELIGIBLE | 422 |
| ERR_APPEALS_OPEN | 409 |
| ERR_CHILDREN_NOT_LOCKED | 409 |
| ERR_DUPLICATE | 409 |
| ERR_CARRIER_CAPACITY | 422 |
| ERR_RUN_PERIOD_CONFLICT | 409 |
| ERR_PARTIAL_BUILD_NOT_ALLOWED | 422 |
| ERR_PROGRAM_CLOSED | 409 |
