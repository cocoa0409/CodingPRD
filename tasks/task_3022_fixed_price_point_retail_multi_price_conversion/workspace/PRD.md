# Fixed-Price-Point Retail Multi-Price Conversion API — Product Requirements Document

## 1. Introduction

The buying office of a fixed-price-point retailer operates under an unusual constraint: the shopper-visible price is not a decision variable. Every selling unit on the shelf is charged at one of a small set of uniform shelf prices, and the entire cost-engineering discipline of the business consists of making a supplier's landed cost fit inside that price. This document specifies the API that governs that discipline end to end — from the moment a new item is denominated at a fixed retail, through the application of import freight and vendor cost revisions, to the decision either to clear the item for sale or to terminate it because its landed cost has outrun the price point it sits on.

The same uniform price creates a second, operational problem that this API must also solve. Stores do not all carry the same price point, and a store that moves from one ladder rung to another must change its signage, its shelf tags and its register file in a coordinated way, while carrying a mixed assortment on the sales floor for the duration of the changeover. Seasonal aisle resets are pinned to a fixed calendar, and an aisle cannot be re-cut outside its window or on top of another reset sharing the same store-day. Meanwhile the import side of the business is absorbing ocean freight volatility against a retail price that cannot move, so container receipts must be apportioned to stores by shelf capacity and their freight must be pushed down to the individual item on a defensible, auditable basis.

A third theme runs through the whole specification: the same operator must never both author a cost and attest to it. Item cost engineering, physical store conversion, container movement, distribution-center allocation, reset-calendar planning and independent cost review are separate duties assigned to separate roles, and price-integrity audits exist to catch the moment the shelf tag and the register file disagree. The rules below are written so that an implementation can reproduce that separation exactly.

## 2. Global Specifications & System-Wide Principles

This section establishes the contract-level rules that hold across every endpoint: authentication and role assignment, the shape of every response envelope, pagination, the fixed price ladder, the standard resource properties, monetary precision, optimistic concurrency, path validation order, the logical clock, and the store-day shelf budget.

### 2.1. User and Role-Based Access Control

Every request to the merchandise API must carry two mandatory headers. `X-User-ID` identifies the acting party and `X-User-Role` declares the operational capacity in which that party is acting. If either header is absent, or if `X-User-Role` is not one of the seven declared roles, the request is rejected with `ERR_MISSING_USER_CONTEXT` and an HTTP 401 response. Independently of authentication, every endpoint declares the set of roles permitted to call it; a request whose role is authenticated but not listed for that endpoint is rejected with `ERR_INSUFFICIENT_ROLE` and an HTTP 403 response. These two checks run before any resource lookup or business rule, and they apply to every endpoint in the catalogue without exception.

The seven roles are `MerchandiseBuyer`, `StoreOperationsManager`, `ImportCoordinator`, `DistributionCenterOperator`, `ResetCalendarPlanner`, `MerchandiseAnalyst` and `LegalCostEngineer`, plus the harness-only `PlatformAdmin`.

None of these roles is entity-backed. When `X-User-Role` is `MerchandiseBuyer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it does not compare it to any entity's `id`. The same is true of `StoreOperationsManager`, `ImportCoordinator`, `DistributionCenterOperator`, `ResetCalendarPlanner`, `MerchandiseAnalyst`, `LegalCostEngineer` and `PlatformAdmin`: in every case `X-User-ID` is an opaque operator identifier not tied to any persisted entity, is never resolved against a database row, and is never used in an ownership comparison. There is no `owner_id`-style field anywhere in this API and no resource is scoped to the caller who created it.

Role assignment is a segregation-of-duties instrument rather than a data-visibility instrument. A `MerchandiseBuyer` owns cost engineering, price-point assignment and release, deletion disposition, exclusive pack development, price-point definition and activation, vendor registration, landed-cost application, and multi-price issue batches; a `MerchandiseBuyer` cannot begin a store conversion, file its artefacts, or file a compliance audit. A `StoreOperationsManager` registers stores, begins and completes conversions and reversions, files the signage, shelf-tag and register artefacts, opens and starts conversion projects, files and resolves price-integrity audits, and abandons aisle resets — but cannot alter an item's cost or its price-point binding. An `ImportCoordinator` books containers, moves them through departure, arrival, customs hold, customs release and receipt, and cannot allocate units to stores or author a landed-cost charge. A `DistributionCenterOperator` creates allocation lines and releases or shorts them, and cannot book, move or receive containers. A `ResetCalendarPlanner` defines, publishes and withdraws season windows and plans, begins and executes aisle changeovers, and cannot convert a store or audit price integrity. `MerchandiseAnalyst` is read-only across the whole surface and owns no state transition. `LegalCostEngineer` is also read-only, restricted to items, their landed-cost history, their break-even projections, stores and price-integrity audits, and deliberately holds no write operation at all so that the same operator cannot both author a cost and attest to it. `PlatformAdmin` holds the logical-clock control and nothing else on the business surface.

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

Every endpoint that returns a collection is paginated through two query parameters. `limit` is the maximum number of rows to return; when it is omitted the server uses 10, and the accepted range is a minimum of 1 and a maximum of 100. `offset` is the number of leading rows to skip; when omitted it defaults to 0. Unless a call is otherwise documented, all list endpoints return resources sorted by their creation timestamp in ascending order, and the ordering is stable across pages.

Paginated list responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count` and `has_more`. `total_count` is the count of rows matching the filters irrespective of the current page, and `has_more` indicates whether further rows remain beyond the returned page.

### 2.4. The Fixed Price Ladder and Its Issuance Rules

A `PricePoint` is the anchor of every commercial rule in this system. It is registered with a `label` — a human-readable name such as `DOLLAR_25_LEGACY` — a `shelf_price_cents` value that is the single fixed retail charged to the shopper at that point, and a `target_landed_cost_ratio` expressing the maximum landed cost the buying office may commit to as a fraction of that shelf price. The shelf price must be greater than zero, and the ratio must be greater than zero and less than or equal to one. A newly registered price point begins in `DRAFT` status and its `issued_store_count` is zero; a price point in `DRAFT` is editable but may not be issued to anything. A price point becomes issuable only once it has been moved to `ACTIVE`, and until it is `ACTIVE` every attempt to issue it — to an item, to a store conversion, to a store reversion, or to an exclusive pack program — is rejected with `ERR_PRICE_POINT_NOT_ACTIVE` and HTTP 409.

The `issued_store_count` field is computed, not stored as a free number: it is the number of distinct stores whose active aisle-reset assignment carries a `price_point_id` equal to this price point, counting each store exactly once no matter how many aisles that store happens to carry under the same point.

### 2.5. Common Resource Properties and Derived-Field Mutation

Every primary resource in this API — `PricePoint`, `SeasonWindow`, `ExclusivePackProgram`, `Item`, `Vendor`, `Container`, `Store`, `AisleReset`, `ConversionProject`, `LandedCostHistory` and `AllocationLine` — carries the standard system-managed field set. `id` is a unique, server-minted UUID used for addressability and carries no type prefix of any kind. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was first created. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was last modified, and it is refreshed on every mutation of the row. `version` is a system-managed integer that starts at its initial value and increments by one on every modification to the row. Because a derived field is still a mutation, a recomputation of a computed field updates `updated_at` and increments `version` exactly as a client-supplied edit would.

There is one deliberate exception. A `PriceIntegrityAudit` is an immutable event log and does not carry the common field set: it exposes `id` and `created_at` only, and neither `updated_at` nor `version` is present on it. A `PriceIntegrityAudit` is therefore never an optimistic-concurrency target and never reports a modification timestamp.

### 2.6. Monetary Precision and the Cent-Exact Ledger

All money in this system is carried as integer cents. `shelf_price_cents`, `quoted_landed_cost_cents`, `target_landed_cost_cents`, `unit_retail_cents`, `base_landed_cost_cents`, `fixed_store_handling_cents`, `variable_store_cost_cents`, `landed_cost_cents`, `net_contribution_cents_per_unit`, `total_freight_cents` and `applied_amount_cents` are all integers and are never returned as fractional or string values. Intermediate steps that involve ratios or division are computed as exact rationals and are narrowed to an integer only at the single point the rule specifies.

Where a rule produces an integer by moving from a rational, the direction of that narrowing is part of the contract. Cost ceilings are floored. Break-even counts are rounded up to the next whole case. Freight rates are floored once. Coverage ratios and mismatch ratios are the two ratio-valued outputs in this system, and each is rounded half up to exactly 3 decimal places, with the tolerance comparisons evaluated against the rounded value rather than the raw quotient.

### 2.7. Optimistic Concurrency on Store-Bound Conversion Writes

Two write operations in this API are guarded by the version of the store they act upon. A conversion project created against a store must supply `expected_store_version`, and a conversion project adjusted after creation must supply `expected_store_version` as well. In both cases the supplied value is the `version` of the target store that the client last observed. If the store's version has advanced since that observation — because the store's price-point binding moved, because one of its conversion artefact flags was filed, because `conversion_price_point_id` was set or cleared, or because an aisle reset began under it — the request is rejected with `ERR_STALE_VERSION` and HTTP 412. This is a stale-version rejection, not a timing rule: the server compares the supplied value to the store's current `version` and rejects on inequality.

No other endpoint in the catalogue accepts an expected-version field. Endpoints that are not named above neither read nor validate a version token, and a client that sends one to them has it ignored.

### 2.8. Left-to-Right Path Validation and Nested Retrieval

For any request whose path names more than one resource identifier, the system resolves those identifiers in the order the path declares them, left to right, and rejects the request at the first identifier that does not resolve. The rejection carries an HTTP 404 and an error id specific to the resource type that failed: `ERR_ITEM_NOT_FOUND`, `ERR_CONTAINER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRICE_POINT_NOT_FOUND`, `ERR_SEASON_WINDOW_NOT_FOUND`, `ERR_AISLE_RESET_NOT_FOUND`, `ERR_ALLOCATION_LINE_NOT_FOUND`, `ERR_CONVERSION_PROJECT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND` or `ERR_PACK_PROGRAM_NOT_FOUND`. A request against a sub-resource of a non-existent parent therefore fails on the parent, before the child is ever looked up.

Foreign keys supplied in a request body follow the same principle but are validated after path resolution and before any business rule. Body-supplied references are resolved in the order the endpoint's input list declares them, and an unresolvable body reference is rejected with the 404 error id of the missing resource type. This ordering means that a request carrying both a missing reference and a violated business constraint reports the missing reference.

The full precedence chain, from first to last, is: the two authentication checks of §2.1; path-identifier resolution, left to right; body foreign-key resolution, in declared order; the acting resource's required source state, checked against the `from` state its transition declares and reported with that transition's state error at HTTP 409; the optimistic-concurrency token check of §2.7, reported as `ERR_STALE_VERSION` at HTTP 412; declared request-shape constraints such as a count below its floor, an upper bound not strictly after its lower bound, a `to_price_point_id` equal to its `from_price_point_id`, a `decision` outside `RETAIN` and `DELETE`, or a `method` outside `FREIGHT_PASS_THROUGH` and `VENDOR_PRICE_CHANGE`, all reported as `ERR_INVALID_REQUEST` at HTTP 400; unique-key collisions on item SKU, vendor name, store number and container number, reported as `ERR_DUPLICATE_SKU` at HTTP 409; and finally the endpoint-specific business constraints, each reported with its own error id. When several validations could fire on one request, the earlier category in this chain wins and its error id is the one returned.

### 2.9. The Logical Clock and Clock-Derived Re-evaluation

Parts of this specification are evaluated against a server logical clock rather than wall-clock time. The server starts with the clock reading exactly 2026-09-01T00:00:00Z and never falls back to real time; that fixed instant stands until the clock is changed. `PlatformAdmin` may set the clock to a supplied `to_iso8601` instant, which is the only way time advances in this system. The call returns the resulting `current_utc`, a `recomputed_item_count` and a `recomputed_season_window_count`.

Advancing the clock is not a passive bookkeeping operation: it re-derives every clock-dependent computed field in the system. Season windows are re-evaluated against the new instant, every item's `break_even_units` is recomputed, and the shelf allocation waterfall is swept across allocation lines. Any implementation that stores clock-derived values without re-deriving them at this point will diverge from the specification.

Season window status is itself clock-derived rather than freely assigned. While the clock is before the window's `opens_on`, the stored status stands as `DRAFT` or `SCHEDULED`. Once the clock reaches `opens_on` and remains at or before `closes_on`, the window reads `OPEN`. Once the clock passes `closes_on`, the window reads `CLOSED`. The upper bound is inclusive: the instant of `closes_on` itself is still `OPEN`, and only the instant after it is `CLOSED`.

### 2.10. The Store-Day Shelf Budget

Physical shelf capacity is the scarce resource that constrains two otherwise unrelated parts of this system. A store declares `shelf_facing_capacity_sqft`, the total shelf facing the store can commit across concurrent aisle resets, and that figure is the ceiling against which the store-day aggregate is summed. Aisle resets commit `allocated_shelf_sqft` each, and the same store-day aggregate that governs reset planning is the quantity an implementation must be able to recompute when a reset is added or abandoned.

Two interval conventions coexist in this API and must not be conflated. Same-aisle conflict detection treats intervals as half-open: two resets on the same aisle of the same store conflict only when one starts strictly before the other ends and the other starts strictly before the first ends, so intervals that merely touch at an endpoint do not conflict. The store-day aggregate, by contrast, uses the closed convention: a reset shares a day with another when its start is at or before the other's end and its end is at or after the other's start, so intervals that touch at an endpoint do share the day and their shelf square footage is summed together.

### 2.11. Segregation of Duties Across the Cost and Compliance Boundary

The role matrix in §2.1 is not merely a permissions list; it encodes the controls the business relies on. The operator who quotes a vendor's landed cost is never the operator who attests that the shelf and the register agree. The operator who moves a container is never the operator who decides which store receives its units. The operator who plans an aisle changeover is never the operator who completes the store's price conversion. `LegalCostEngineer` exists in the role list precisely so that landed-cost pass-through, break-even projections and price-integrity exposure can be reviewed by a party holding no write permission on any of them.

## 3. Business Logic & Workflows

### 3.1. Denominating an Item and Fixing It to a Shelf Price Point

An item enters the assortment by being denominated. A `MerchandiseBuyer` supplies the `sku`, which must be unique across all items, a human-readable `description` that will be reproduced on both the shelf tag and the register file, a `commodity_class` that aisle changeover planning later reads, an optional `season_code` identifying the season the item belongs to and left as an empty string when the item is a year-round staple, a `unit_retail_cents` that is the fixed retail charged per selling unit, a `sqft_per_unit` expressing the shelf facing one selling unit consumes, a `shelf_package_capacity` giving the square feet of shelf facing allocated to the item at its home store and therefore the maximum the shelf can present, a `units_per_case` giving how many selling units a store-orderable case contains, a `base_landed_cost_cents` that is the vendor's free-on-board landed cost per unit before any freight pass-through, a `fixed_store_handling_cents` per case that the item must recover at the fixed retail, a `variable_store_cost_cents` per unit that is subtracted when net contribution and break-even are derived, and a `sourcing_vendor_id` naming the vendor the item is bought from. The denomination call answers with the new item in `DENOMINATED`, its `price_point_id` null, its `on_hand_units` zero, and its computed fields settled.

Four derived fields are settled at that moment. `broken_case_allowance` is true exactly when one full case cannot fit on the shelf — that is, when `units_per_case` multiplied by `sqft_per_unit` is greater than `shelf_package_capacity`. `is_shelf_overflow` is true exactly when `on_hand_units` multiplied by `sqft_per_unit` is greater than `shelf_package_capacity`, meaning the quantity on hand exceeds what the shelf can present. `landed_cost_cents` reads zero until the first landed-cost row exists and thereafter reports the item's current per-unit landed cost taken from its latest cost row. `net_contribution_cents_per_unit` and `break_even_units` are settled under §3.3 below. A denomination whose `units_per_case` is below one, whose `sqft_per_unit` or `shelf_package_capacity` is not greater than zero, or whose `unit_retail_cents`, `base_landed_cost_cents`, `fixed_store_handling_cents` or `variable_store_cost_cents` is negative is refused as malformed, and a denomination repeating an existing `sku` is refused as a duplicate.

Fixing an item to a price point is a separate act, and it is strictly gated. A price assignment moves the item from `DENOMINATED` to `PRICE_ASSIGNED`, and it is refused unless the item is currently `DENOMINATED` — an item that is not is rejected with `ERR_ITEM_NOT_DENOMINATED`. The assignment must pass the item's `unit_retail_cents` and the target price point's `shelf_price_cents` through an exact equality test: they must be equal to the cent, and any difference is rejected with `ERR_PRICE_POINT_MISMATCH`. The target price point must be `ACTIVE`, and a point that is not is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`. When the assignment lands, the item's `price_point_id` is set to the requested price point, its status becomes `PRICE_ASSIGNED`, and its `updated_at` is refreshed. This equality requirement is not a one-time creation check: an item's `unit_retail_cents` must equal the `shelf_price_cents` of its assigned price point for the whole time the item is price-assigned.

Before an item has taken any cost, that binding may be undone. A price-assignment release returns an item from `PRICE_ASSIGNED` to `DENOMINATED`, nulls `price_point_id`, and is refused with `ERR_ITEM_NOT_PRICE_ASSIGNED` for any item not currently in `PRICE_ASSIGNED`.

### 3.2. Applying Landed Cost: Freight Pass-Through and Vendor Revisions

With an item fixed to a price point, the buying office applies its landed cost. The item moves from `PRICE_ASSIGNED` into `COST_PENDING`, and from that point the cost may be revised any number of times while the item has not yet been cleared to sell: a `COST_PENDING` item accepts further landed-cost applications that leave it in `COST_PENDING`, each one appending a fresh history row and re-deriving the item's cost fields. This is the cyclical part of the item's life — freight lands, a vendor revises a quote, the numbers are re-run — and it continues until the item is either cleared to `ACTIVE` or pushed into `DELETE_REVIEW`.

Every application is recorded as a `LandedCostHistory` row, is classified by its `method`, and carries a `container_id`. A row whose `method` is `FREIGHT_PASS_THROUGH` records freight from a received container; a row whose `method` is `VENDOR_PRICE_CHANGE` records a vendor's revision of the quoted cost, carries no container, and leaves `container_id` null. The row also carries an `applied_amount_cents` that is the per-unit landed cost it records, and a server-minted `effective_sequence`. That sequence is a strictly increasing integer, unique across all landed-cost rows, assigned in the order rows are created; the row holding the highest sequence for an item is that item's current cost row, and ties are impossible by construction. The item's `landed_cost_cents` is recomputed from whichever row currently holds that highest sequence — not from the most recent call the server happened to serve, and not from a running tally.

A freight pass-through is subject to two hard gates on the container it draws on. The container must be in `RECEIVED`; a pass-through naming a container that is not is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409. The container must also belong to the same vendor the item is sourced from — the container's vendor must equal the item's sourcing vendor — and a mismatch is rejected with `ERR_CONTAINER_VENDOR_MISMATCH` and HTTP 409. A vendor price change is subject to neither gate because it references no container. Omitting a reference that the request method requires, or supplying an unknown `method` value, is refused as malformed with `ERR_INVALID_REQUEST`, and a `method` value must be one of `FREIGHT_PASS_THROUGH` or `VENDOR_PRICE_CHANGE`.

The freight itself is apportioned by a container-level waterfall rather than per item. For the container as a whole, the system first totals `container_total_units` by summing `allocated_units` across every allocation line on that container whose status is not `REVERSED`. It then divides the container's `total_freight_cents` by that total using exact rational arithmetic and floors the quotient exactly once to whole cents, producing a single `freight_per_unit_cents` rate for the container. Every item receiving a pass-through from that container is then charged the same rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide `freight_per_unit_cents`. The flooring happens once, at container level, before any per-item application. Apportioning each item an individually floored share instead — which would compute, for each item separately, the total freight multiplied by that item's units divided by the container total and then floored — is explicitly not the sanctioned behaviour; it produces a different per-unit rate for different items on the same container and is rejected by this specification. The residual cents left by the single floor are dropped and never redistributed to any item, which is what keeps the freight absorbed on a container from ever exceeding the freight actually billed for it.

### 3.3. Break-Even, Net Contribution and the Three Cost Regimes

Every landed-cost application re-derives two numbers that decide whether the item can live at its fixed retail. The first is `net_contribution_cents_per_unit`, a signed integer computed as the item's `unit_retail_cents` minus its `landed_cost_cents` minus its `variable_store_cost_cents`. The evaluation order is pinned at retail, then landed cost, then variable store cost, so the sign remains well defined when the landed cost exceeds the retail. A negative value means the fixed price point no longer absorbs the landed cost. The second is `break_even_units`, the minimum number of full-case units that must move at the committed landed cost to cover the retail.

Break-even is evaluated in a pinned order. The system first computes `total_landed_cost_cents` as the item's `landed_cost_cents` multiplied by its `units_per_case`, plus its `fixed_store_handling_cents`. It then computes `unit_margin_cents` as `unit_retail_cents` minus `variable_store_cost_cents`. Only then does it branch, into exactly one of three declared regimes.

The first regime is `PRICE_PENDING`, and it applies when the item carries a `landed_cost_cents` of zero and has no landed-cost history row at all. In that regime `break_even_units` is zero, because there is no committed cost to evaluate a ratio against. This is a distinct declared shape, not a special case of a losing item: a brand-new item that has taken no cost is neither convergent nor divergent. The second regime is `CONVERGENCE`, and it applies when `unit_margin_cents` is strictly greater than zero. In that regime `break_even_units` is the exact rational `total_landed_cost_cents` divided by `unit_margin_cents`, rounded up to the next whole unit, so the item's contribution turns positive at exactly that count. The third regime is `DIVERGENCE_OR_ZERO_MARGIN`, and it applies when `unit_margin_cents` is zero or negative. No finite break-even exists at a non-positive unit margin, so the rule pins the sentinel value zero — not null, not a negative number, and not an unbounded or infinite marker. The last two regimes are the dual-variant pair: identical inputs can flow into either, and they return different result shapes.

For a reader of the item's cost position, the projection is available directly. A break-even read reports the item's `item_id`, its `break_even_units`, its `unit_retail_cents`, its `landed_cost_cents`, its `variable_store_cost_cents`, its `net_contribution_cents_per_unit`, and a `regime` string that reads `PRICE_PENDING`, `CONVERGENCE` or `DIVERGENCE_OR_ZERO_MARGIN` under exactly the conditions above. An item's landed-cost history may also be read on its own, filterable by `method` and by `container_id`, and a cross-item history listing is available filterable by `item_id`, `container_id` and `method`; a container's own freight pass-through history may likewise be listed. The item's history reads newest applicable row first.

### 3.4. Clearing an Item to Sell, or Pushing It into Deletion Review

The moment of truth for an item is its activation. An item may be cleared to sell only from `COST_PENDING`; an item in any other state is rejected with `ERR_ITEM_NOT_COST_PENDING`. Beyond the state precondition, the gate is the item's contribution: activation requires `net_contribution_cents_per_unit` to be zero or positive. An item whose contribution is negative may be activated only if it is cured by an exclusive pack — there must exist an `ExclusivePackProgram` row whose vendor equals the item's `sourcing_vendor_id`, whose price point equals the item's `price_point_id`, and whose status is `ACTIVE`. That three-field join is pinned exactly; a pack that matches on two of the three does not cure the item. An activation that fails this requirement is rejected with `ERR_ITEM_NOT_COST_CLEARED` and HTTP 422. On success the item becomes `ACTIVE`, retains its `price_point_id`, and its `unit_retail_cents` is unchanged.

The negative-contribution case has a second, parallel branch that is decided by the same pack test. When a landed-cost application drives `net_contribution_cents_per_unit` below zero, the item's fate depends entirely on whether an `ACTIVE` exclusive pack cures it. If no such pack exists, the item is pushed automatically from `COST_PENDING` into `DELETE_REVIEW` — this transition is reached from the landed-cost write's own side-effect chain and is never triggered by a direct client call. If such a pack does exist, the item stays in `COST_PENDING` and the response reports the loss with `ERR_COST_EXCEEDS_PRICE_POINT` and HTTP 422, so the buying office sees the miss without the item being queued for deletion. When the contribution is zero or positive, the item simply stays in `COST_PENDING` awaiting activation. The same branching governs the cyclical `COST_PENDING` re-application path: each additional landed-cost write on an already-`COST_PENDING` item re-runs the identical test and can push it to `DELETE_REVIEW` on the same terms.

The drop into `DELETE_REVIEW` is not free of consequences for the item's own derived numbers. In that regime `break_even_units` is set to zero — the divergence regime, since the break-even ratio is undefined at a non-positive unit margin. The transition changes nothing else: `Store.open_violation_count` is not affected, and `PriceIntegrityAudit` rows for the item's price point are unaffected. Deleting an item is a cost-engineering act, not a compliance act.

A `DELETE_REVIEW` item is disposed by a decision. The `decision` value must be either `RETAIN` or `DELETE`; any other value is refused as malformed with `ERR_INVALID_REQUEST`. A decision on an item that is not in `DELETE_REVIEW` is rejected with `ERR_ITEM_NOT_IN_DELETE_REVIEW`. Choosing `RETAIN` returns the item to `ACTIVE` and retains its `price_point_id`. Choosing `DELETE` terminates the item and begins a cascade that reaches well beyond it, described in §3.9.

### 3.5. The Exclusive Pack Program and the Landing-Cost Ceiling

A vendor-developed exclusive pack is the buying office's structural answer to an item that will not fit its price point on the standard formulation. The program is opened against a vendor with a target `price_point_id`, a `pack_qty` giving the units in the exclusive pack, a `case_pack_qty` giving the units per shipping carton, a `formulation_code` such as `LOW_SUDS_V3` that distinguishes the exclusive pack from the standard formulation, and a `quoted_landed_cost_cents` that is the vendor's quoted landed cost per unit. Both quantity fields must be at least one, and the quoted cost may be zero but not negative. A newly opened program is `DRAFT`, and its `target_landed_cost_cents` is derived immediately by the cost ceiling rule below.

The cost ceiling is re-derived on every advance of the program, and it is the number the program must fit beneath. It is computed from the price point's `shelf_price_cents`, the price point's `target_landed_cost_ratio`, and a margin buffer of twelve percent: the shelf price is first multiplied by the target landed cost ratio as an exact rational, that product is then multiplied by one minus the buffer, and the result is floored at the cent, with the cent rounding performed half down. That floored value is the program's `target_landed_cost_cents`. The comparison against the vendor's quote is inclusive on the passing side: a quoted cost at or below the ceiling passes, and only a quoted cost strictly above the ceiling fails.

The same ceiling behaves in two declared ways depending on where the program sits. While the program is still `DRAFT` the ceiling is reported for planning only and does not gate anything — a draft program may quote far above the ceiling without being refused. Once the program is advancing from `PENDING_ACTIVATION` to `ACTIVE`, the same ceiling becomes fatal: a `quoted_landed_cost_cents` strictly above it raises `ERR_PACK_COST_TARGET_MISSED` and HTTP 422 and the transition does not occur. Because the advance call may carry a fresh `quoted_landed_cost_cents`, a vendor can re-quote at landing time and the ceiling is recomputed against that new figure before the gate is applied.

A program advances `DRAFT` to `PENDING_ACTIVATION`, `PENDING_ACTIVATION` to `ACTIVE`, and `ACTIVE` to `TERMINATED`. The target price point must be `ACTIVE` for the advance — a program pointed at a non-active price point is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`. Landing a program at `ACTIVE` has a cross-entity consequence: the owning vendor's `exclusivity_program_count` is incremented, and that count reports how many of the vendor's programs are currently `ACTIVE`. The count is read on the vendor, and programs may also be listed against a vendor or filtered across all vendors by `vendor_id` and `price_point_id`.

### 3.6. Container Movement from Port to Distribution Center

The import side of the business is a strict linear progression with one revert edge. A vendor is registered first, by a `MerchandiseBuyer`, with a `vendor_name` that must be unique across all vendors, a `country_of_origin` given as an ISO-3166 alpha-two code such as `CN`, `VN` or `US`, and an `import_flag` that is true when the vendor ships on ocean import lanes and therefore carries freight pass-through. The `import_flag` may also be used to filter a vendor listing, and a newly registered vendor reports an `exclusivity_program_count` of zero. A container is then booked against that vendor with a `container_number` that must be unique, a `port_code` such as `LAX`, a `dc_code` such as `DC-ATL`, and a `total_freight_cents` for ocean and drayage. It begins `BOOKED` with `customs_cleared` false. Departure moves it from `BOOKED` to `IN_TRANSIT` and is refused from any other status with `ERR_CONTAINER_NOT_BOOKED`. Arrival discharges it at the port, moving it from `IN_TRANSIT` to `AT_PORT` and refused otherwise with `ERR_CONTAINER_NOT_IN_TRANSIT`.

From `AT_PORT` three things can happen. A customs hold moves the container to `CUSTOMS_HOLD` and clears `customs_cleared` back to false; it is refused from any status other than `AT_PORT` with `ERR_CONTAINER_NOT_AT_PORT`. A customs release is the revert edge: a held container returns to `AT_PORT` once the broker clears it, and because `customs_cleared` is set true on arrival at `AT_PORT`, the receipt gate is satisfied at that point. Pressing customs release on a container that is not on hold is rejected with `ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD`. The third option is receipt, which requires the container to be in `AT_PORT` — otherwise `ERR_CONTAINER_NOT_AT_PORT` — and requires `customs_cleared` to be true, otherwise `ERR_CUSTOMS_NOT_CLEARED` and HTTP 409. A received container becomes `RECEIVED`, and that is precisely what makes its freight eligible as the container reference of a `FREIGHT_PASS_THROUGH` landed-cost row.

Two automatic transitions close the container's life, and they run in both directions. Once every allocation line on a received container has reached a terminal status — `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to `ALLOCATED`. A container carrying no allocation lines at all never auto-advances, because the precondition requires at least one line to exist. Conversely, when a fresh `ALLOCATED` allocation line is created against a container that has already reached `ALLOCATED`, the container reverts from `ALLOCATED` back to `RECEIVED`, reopening it for release. `ALLOCATED` is the terminal state of the forward path but is not a sink.

### 3.7. Allocating Container Units Against the Shelf

Units on a received container are placed by a `DistributionCenterOperator`, one allocation line at a time, each line naming a `container_id`, a `store_id`, an `item_id`, a `sequence` and a `requested_units`. The `sequence` is a client-supplied pallet sequence number that must be at least one and must be unique within the container; it is stable for the container's whole life and it is the ordering key the allocation waterfall reads, precisely so that the waterfall never has to break a tie. `requested_units` may be zero or positive but may not be negative. A line whose sequence is below one or duplicated within its container, or whose requested units are negative, is refused as malformed. A line whose container, store, item or referenced price point does not resolve is refused with the 404 error of the missing type before any capacity logic runs.

The core of allocation is the shelf waterfall, and it is grouped, ordered and capped in a way that admits no pooling. For each item, the system first computes a per-item `unit_shelf_capacity` by dividing the item's `shelf_package_capacity` by its `sqft_per_unit` and flooring to whole units. That per-item figure is then adjusted into a per-line `capacity_ceiling`. When the item's `broken_case_allowance` is true — that is, when one full case genuinely cannot fit on the shelf — the ceiling becomes the item's unit shelf capacity plus one full case of that item, an extra-case allowance that lets a broken-case line place one additional full case on the base deck beside the shelf. In the worked shape of that rule, a shelf that holds 40 units belonging to an item whose case is 100 units accepts 140 units, not 40. When `broken_case_allowance` is false, the ceiling is the item's unit shelf capacity alone, so a 150-unit request against a 40-unit shelf is capped at 40 and the 110 units that do not fit are recorded as overflow. The broken-case branch and the strict branch are the pair that must both be carried into implementation; neither is the general case.

Capacity is held per (container, item, store) group, never pooled across stores and never pooled across containers, so two stores drawing on one container for one item each get their own ceiling rather than sharing a combined one. Within a group, the lines are processed in ascending `sequence` order, tracking an `already` running total that starts at zero. For each line the system computes `remaining_capacity` as the group's capacity ceiling minus `already`, taken at a minimum of zero. The line's `allocated_units` is then the smaller of its `requested_units` and that `remaining_capacity`, and its `overflow_units` is `requested_units` minus `allocated_units` — the units the store must hold back-of-house rather than on the shelf. `already` is then increased by the line's `allocated_units` before the next line is considered. A line that ends with zero allocated units while requesting at least one is placed in `OVERFLOW`; every other line is `ALLOCATED`. Evaluation order is pinned: the capacity ceiling is derived first, then the running total, then the minimum is taken.

Not every line draws units at all. Only items in `PRICE_ASSIGNED`, `COST_PENDING` or `ACTIVE` may draw container units; items in `DENOMINATED` or `DELETE_REVIEW` never do. Lines already in `REVERSED` status are skipped entirely and are excluded from every aggregation over the container. The container's allocated-unit total that the freight apportionment later divides by is the sum of `allocated_units` across all of its lines whose status is not `REVERSED`, and a reversed line's units are given back rather than counted.

Releasing and shorting are the two ways a line is worked down. A release carries a `release_units` value that must be at least one and must not exceed the line's current `remaining_units`; a value above the remainder is rejected with `ERR_RELEASE_EXCEEDS_ALLOCATION` and HTTP 422, and a value below one is refused as malformed. A release is also gated on the container, not merely on the line: the line's container must be in `RECEIVED`, and a release attempted against a line whose container has not been received is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409. This gate is the reason a line's own status is never sufficient authority to release. A successful release adds `release_units` to the line's `released_units`, recomputes `remaining_units` as `allocated_units` minus `released_units`, and — this is the cross-entity hop that matters — adds the same quantity to the item's `on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand units multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`. When the line's `remaining_units` reaches zero the line becomes `RELEASED` and its `released_units` equals its `allocated_units`. Either way the container's status is then recomputed: it becomes `ALLOCATED` when every line on it is terminal, and `RECEIVED` otherwise.

Shorting is a terminal write requiring no quantity. A short moves an `ALLOCATED` line to `SHORTED`, sets its `remaining_units` to zero, recomputes the affected store's `open_violation_count`, and recomputes the line's container status. Both release and short are refused on a line that is not currently `ALLOCATED`, with `ERR_ALLOCATION_LINE_NOT_ALLOCATED` and HTTP 409. A third route to a terminal line exists but has no client call behind it: when the line's item is deleted, the line is reversed automatically as described next. Whichever route terminates the last line on a container, the container's state is recomputed by the same rule, which is what allows the `RECEIVED → ALLOCATED` advance and the `ALLOCATED → RECEIVED` revert to fire without any client ever naming the container.

### 3.8. Converting a Store Between Price Points

A store is registered by a `StoreOperationsManager` with a `store_number` that must be unique and a `shelf_facing_capacity_sqft` that is the total shelf facing it can commit across concurrent aisle resets. It begins in `SINGLE_PRICE`, with a null `conversion_price_point_id`, no filed artefacts, and an `open_violation_count` of zero.

A conversion is a sequence of three artefact filings followed by a completion, with an aisle-coverage aggregate watched throughout. The first call begins the change: a store currently in `SINGLE_PRICE` may be converted to a target price point, and if it is not in `SINGLE_PRICE` the attempt is rejected with `ERR_STORE_NOT_SINGLE_PRICE`; if its `conversion_price_point_id` is already set the attempt is rejected with `ERR_STORE_ALREADY_CONVERTING`; and if the target price point is not `ACTIVE` the attempt is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`. On acceptance the store moves to `CONVERTING`, `conversion_price_point_id` is set to the target, and `sign_order_filed`, `shelf_tag_filed` and `register_file_locked` are all reset to false. The target is supplied as `to_price_point_id`.

The three artefacts are filed one at a time, and each filing, completion and rollback call names the store together with the `conversionId` of the conversion being worked on. A filing call carries an `artifact` naming which of the three is being filed — the signage order, the shelf-tag file, or the register file lock — and sets the matching boolean among `sign_order_filed`, `shelf_tag_filed` and `register_file_locked` to true while incrementing the store's `version`. A `StoreOperationsManager` cannot complete the conversion until all three booleans are true; completing while any one of them is false is rejected with `ERR_CONVERSION_PREREQUISITES_UNMET`.

Completion is also gated on a second store state and on the project's coverage. The store must still be in `CONVERTING` — a completion attempted elsewhere, including on a `REVERTING` store through the wrong path, is rejected with `ERR_STORE_NOT_CONVERTING`. The conversion project for the change must be `IN_PROGRESS`, and a project in any other state is rejected with `ERR_CONVERSION_NOT_IN_PROGRESS`. The coverage test then applies: `coverage_delta_pct` must be at least negative one half, and a value below that is rejected with `ERR_AISLE_COVERAGE_SHORTFALL` and HTTP 422. The boundary is inclusive on the passing side — a coverage delta of exactly negative one half passes — and the comparison runs against the rounded value rather than the raw quotient.

The coverage aggregate answers the question of how much of the store's aisle work is actually done. `completed_aisle_count` counts the store's aisle resets in `EXECUTED`; `projected_convertible_aisle_count` counts those in `PLANNED` or `EXECUTING`; abandoned resets are excluded from both counts. An `adjusted_baseline` is then taken as the larger of the projected convertible count and a floor of one aisle, so a store with no projected resets is measured against a baseline of one rather than dividing by zero. `coverage_delta_pct` is the completed count minus that baseline, divided by that baseline, rounded half up to three decimal places. A shortfall is declared exactly when the rounded delta is below negative one half, and the same aggregate is exposed for reading on the project alongside `completed_aisle_count`, `projected_convertible_aisle_count`, `adjusted_baseline`, `coverage_delta_pct` and the boolean `shortfall`.

A conversion project is the vehicle that carries the change, and it is opened against a store that is already `CONVERTING`. Creating one requires `store_id`, an input `from_price_point_id` that is the price point being converted away from, the destination `to_price_point_id`, and `expected_store_version`. The destination must differ from the source, since a project whose `to_price_point_id` equals its `from_price_point_id` is refused as malformed. The store and both price points must resolve. Creation is version-guarded: the supplied `expected_store_version` must equal the store's current `version` or the request is rejected with `ERR_STALE_VERSION` and HTTP 412, which is what prevents a project being opened against a store whose binding, artefact flags or conversion price point have moved since the client last read it. When a project is created it begins `DRAFT` and the store's `version` is incremented by one. A project is started into execution only from `DRAFT` — a start from any other state is rejected with `ERR_CONVERSION_NOT_DRAFT` — and the store must be `CONVERTING` at that moment or the start is rejected with `ERR_STORE_NOT_CONVERTING`. Starting moves the project to `IN_PROGRESS`.

A project's destination may be adjusted before the change completes, and that adjustment is guarded the same way. It carries the new `to_price_point_id` and `expected_store_version`, updates the destination, and increments the store's `version` by one when accepted; a stale token is rejected with `ERR_STALE_VERSION` and HTTP 412 for the same reason as at creation, because the completion gate reads the store's artefact flags and those flags are only meaningful against the observed store version.

Completing a conversion is the point at which the store's price really changes, and it does more than flip the store's own status. It moves the store from `CONVERTING` to `MULTI_PRICE`, nulls `conversion_price_point_id`, and moves the project to `COMPLETED`. It then cascades: every `PriceIntegrityAudit` on that store currently `OPEN` is closed to `RESOLVED`, and the store's `open_violation_count` is recomputed to zero. A completed conversion reconciles shelf tags to the register file, so every open integrity violation on the store closes with it.

A conversion may instead be abandoned. Rolling back returns the store to `SINGLE_PRICE`, nulls `conversion_price_point_id`, moves the project to `ROLLBACK`, and resets all three artefact flags to false. A rollback is permitted while the store is in `CONVERTING` or in `REVERTING`, and is refused from any other state with `ERR_STORE_NOT_CONVERTING`; a project that is not `IN_PROGRESS` is likewise refused with `ERR_CONVERSION_NOT_IN_PROGRESS`. The rollback is the compensating action for an opening, and the pair is designed to be net-neutral on how many stores are bound to a price point: after a rollback, the number of stores carrying a non-null `conversion_price_point_id` is the same as it was immediately before the matching conversion began. A multi-price store is not a sink, either — a reversion may pull it back toward a single price point. A reversion is begun on a store that must be in `MULTI_PRICE` (otherwise `ERR_STORE_NOT_MULTI_PRICE`) against a target price point that must be `ACTIVE` (otherwise `ERR_PRICE_POINT_NOT_ACTIVE`); it sets `conversion_price_point_id` to the target and moves the store to `REVERTING`. A reversion completes through the same completion path, requiring the same three filed artefacts and the same coverage tolerance (below which it is rejected with `ERR_AISLE_COVERAGE_SHORTFALL`), and lands the store in `SINGLE_PRICE` with the project at `COMPLETED` and the conversion price point nulled.

Issuing an assortment to a converting store is its own act, performed by a `MerchandiseBuyer` rather than the store operator. A multi-price issue batch names a `store_id`, a `from_price_point_id` that is the store's outgoing single price point, a list of `item_ids`, and a `to_price_point_id`. Every item in the batch must currently sit at the batch's own source price point: an item whose current `price_point_id` differs from the batch's `from_price_point_id` is rejected with `ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT` and HTTP 409. The batch answers with the `store_id`, an `issued_item_count`, the `to_price_point_id`, and a `rejected_item_ids` array identifying the items that could not be issued, and it opens a conversion project whose source is set to the request's `from_price_point_id`.

### 3.9. Deleting an Item and the Cascade It Starts

Terminating an item is the one operation in this specification whose blast radius extends past the item itself, and the cascade is a three-hop chain that must be carried out in order. The trigger is a `DELETE` decision on a `DELETE_REVIEW` item, which moves the item to `DELETED` and nulls its `price_point_id`.

The first hop is on the item's allocation lines. Every allocation line whose item is this item and whose status is `ALLOCATED` or `SHORTED` is moved to `REVERSED`, and each such line's `released_units` is reset to zero. Lines already `RELEASED` are not reversed by this hop, and lines already `REVERSED` are untouched. The second hop propagates outward from those affected lines: each affected line's store has its `open_violation_count` recomputed, and each affected line's container has its remaining `ALLOCATED` line count recomputed. The third hop retracts containers: any container whose remaining `ALLOCATED` line count has fallen to zero and which is currently in `ALLOCATED` is moved back to `RECEIVED`.

Deleting an item also gives back the freight that had been absorbed on its behalf. This is a container-level invariant that must hold once the cascade settles: for each affected container, the sum over all of its non-`REVERSED` allocation lines of the quantity `applied_amount_cents` minus the item's `base_landed_cost_cents`, multiplied by the line's `allocated_units`, is exactly zero. In other words, the freight pass-through that was absorbed on the container is fully cancelled by the deletion rather than left stranded on a container that no longer carries the item.

### 3.10. The Reset Calendar: Season Windows and Aisle Changeovers

Aisle changeover planning runs on a fixed calendar owned by the `ResetCalendarPlanner`. A season window is defined with a `season_code` such as `HARVEST_2026`, an `opens_on` that is the first instant the window is open and is inclusive, and a `closes_on` that is the last instant the window is open and is also inclusive. `closes_on` must be strictly after `opens_on`; a window satisfying neither is rejected as malformed with `ERR_INVALID_SEASON_WINDOW` and HTTP 400. A window begins `DRAFT`. Scheduling it moves it to `SCHEDULED` and is refused from any other state with `ERR_SEASON_WINDOW_NOT_DRAFT`; because the clock is re-evaluated immediately after scheduling, a window whose `opens_on` the clock has already reached advances straight on to `OPEN` at that same moment. Unscheduling pulls a window back to `DRAFT` and is refused with `ERR_SEASON_WINDOW_NOT_SCHEDULED` unless the window is `SCHEDULED`, and it further requires the clock to be before `opens_on`, since a window that has already opened is no longer eligible to be pulled back. Windows are read with their status derived from the clock as described in §2.9, and may be listed filtered by `season_code` and `status`. A season window also reports `overlapping_reset_count`, the number of aisle resets whose occupation interval overlaps the window's own `[opens_on, closes_on]` range under the half-open convention — a reset starts inside the window when its `starts_at` is at or before the window's `closes_on` and its `ends_at` is at or after the window's `opens_on`.

An aisle reset is planned inside a window and against a price point. Planning carries a `store_id`, a `price_point_id` for the price point the reset aisle will carry, a `season_window_id`, an `aisle_code` such as `A14`, a `starts_at` and `ends_at` bounding the aisle occupation interval inclusively, an `allocated_shelf_sqft` for the shelf facing the changeover commits, and a `seasonal_changeover` flag that is true when the reset swaps the aisle to a new season and false for a same-season refresh. `ends_at` must be strictly after `starts_at`, `allocated_shelf_sqft` must be greater than zero, and a violation of either is refused as malformed. A new reset begins `PLANNED`.

Three interval rules are checked when a reset is planned, and the first two of them use different conventions from each other. Same-aisle conflict detection is half-open: the candidate interval must not overlap any non-terminal reset — that is, any reset currently in `PLANNED` or `EXECUTING` — on the same `aisle_code` of the same store, where two intervals conflict only when the existing reset starts strictly before the candidate's end and the candidate starts strictly before the existing reset's end. Intervals that merely touch at an endpoint do not conflict and are permitted. A same-aisle conflict is rejected with `ERR_AISLE_RESET_OVERLAP` and HTTP 409. Calendar containment is a separate, inclusive test: the candidate interval must fall entirely inside its season window's bounds, inclusive at both ends, and an interval starting before `opens_on` or ending after `closes_on` is rejected with `ERR_RESET_OUTSIDE_CALENDAR` and HTTP 409. The same containment rule is re-checked at the moment the reset begins executing, so a reset that was legal at planning time but is being begun outside its window is still refused.

The third rule is the store-day aggregate, and it uses the closed convention rather than the half-open one. When a reset is planned, the system sums the `allocated_shelf_sqft` of every non-terminal reset on the same store whose interval overlaps the candidate under the closed reading — that is, where one interval's start is at or before the other's end and its end is at or after the other's start, so intervals sharing only an endpoint do share the day. That sum must not exceed the store's `shelf_facing_capacity_sqft`; an over-commitment is rejected with `ERR_STORE_DAY_CAPACITY_EXCEEDED` and HTTP 422.

A reset moves from `PLANNED` to `EXECUTING` only when three conditions hold together: the reset is currently `PLANNED`, otherwise `ERR_AISLE_RESET_NOT_PLANNED`; its season window is `OPEN`, otherwise `ERR_SEASON_WINDOW_NOT_OPEN`; and the logical clock has reached the reset's `starts_at`, otherwise `ERR_RESET_OUTSIDE_CALENDAR`. From `EXECUTING` the reset may be executed, which requires it to be in `EXECUTING` — otherwise `ERR_AISLE_RESET_NOT_EXECUTING` — and requires at least one item to exist in `ACTIVE` status whose `price_point_id` equals the reset's own `price_point_id`; an execution finding no such item is rejected with `ERR_NO_ELIGIBLE_ITEMS` and HTTP 422. A successful execution moves the reset to `EXECUTED` and refreshes the store's `updated_at`. A reset may also be abandoned, which moves it to `ABANDONED` and is performed by a `StoreOperationsManager` rather than the planner; abandonment is permitted only from `PLANNED` or from `EXECUTING`, and a reset that satisfies neither is rejected with `ERR_AISLE_RESET_NOT_PLANNED`.

One cross-entity rule binds resets to the store's conversion state. While a store is `CONVERTING`, every reset opened on it must carry a `price_point_id` equal to the store's `conversion_price_point_id`; a mixed price point inside a single conversion is rejected with `ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION` and HTTP 409.

### 3.11. Price Integrity Audits and the Mixed-Price-Point Guard

A price integrity audit records a physical store visit. It is filed by a `StoreOperationsManager` with a `store_id`, a `price_point_id` the auditor observed on the shelf and at the register, an `audited_at` instant, an `observed_item_count` counting the facings examined, and a `mismatched_item_count` counting the facings whose shelf tag disagreed with the register file. Both counts must be non-negative, and the mismatched count must not exceed the observed count; a negative count or a mismatch count above the observed count is refused as malformed.

The audit's `mismatch_ratio` and its `result` are computed at creation and are then fixed for the life of the row. When `observed_item_count` is zero the ratio is zero and the result is `WITHIN_TOLERANCE`. Otherwise the ratio is the mismatched count divided by the observed count, rounded half up to three decimal places, and the result is `VIOLATION` when that rounded ratio is strictly greater than the tolerance of 0.052, and `WITHIN_TOLERANCE` otherwise. The boundary is strict on the tolerance side: a ratio exactly equal to 0.052 is `WITHIN_TOLERANCE` and only a ratio strictly above it is a `VIOLATION`. Because the comparison runs on the rounded value rather than the raw quotient, ratios that differ in their raw form can land on the same rounded figure and take the same branch; the branch flips only when the rounded three-decimal value exceeds 0.052. A newly filed audit begins `OPEN`, its store's `price_integrity_audit_count` is incremented, and the store's `open_violation_count` is recomputed.

A second price point may not be opened against a store that already has unresolved integrity trouble. Filing an audit whose `price_point_id` differs from that of an existing `OPEN` violation on the same store is rejected with `ERR_MIXED_PRICE_POINT_OPEN_VIOLATION` and HTTP 422. This guard is what keeps a store from accumulating open violations under two different price points at once, which is precisely the state a botched conversion produces. Audits may be listed filtered by `store_id`, `price_point_id`, `result` and `status`.

An audit closes one of two ways. A `StoreOperationsManager` may resolve it directly once the shelf and the register have been reconciled; that call requires the audit to be `OPEN` and is refused with `ERR_AUDIT_ALREADY_RESOLVED` if it is not. Or the audit closes as a secondary effect of the store's own conversion completing, as described in §3.8 — every open violation on a converting store closes to `RESOLVED` when that store completes its change. In both cases the audit moves to `RESOLVED` and the store's `open_violation_count` is recomputed, so the count always reflects exactly the violations still open.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a distinct new resource to a collection, answer with a `201 Created` status. Operations that modify an existing resource, or advance it along its lifecycle, answer with a `200 OK` status. The logical-clock control also answers with `200 OK`.

The table below is a summary only. Request bodies, query parameters, response shapes and side effects are specified in §2 and §3 above; readers reconstructing a call should work from those narratives rather than from this list.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and re-derive clock-dependent fields | PlatformAdmin |
| POST | `/merchandise/price-points` | Register a shelf price point | MerchandiseBuyer |
| GET | `/merchandise/price-points` | List shelf price points | MerchandiseBuyer, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/price-points/{id}` | Read one shelf price point | MerchandiseBuyer, StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/price-points/{id}/activate` | Activate a price point so it may be issued | MerchandiseBuyer |
| GET | `/merchandise/price-points/{id}/aisle-resets` | List aisle resets scheduled to carry a price point | MerchandiseBuyer, ResetCalendarPlanner, MerchandiseAnalyst |
| GET | `/merchandise/price-points/{id}/conversion-projects` | List conversion projects sourced from or destined for a price point | MerchandiseBuyer, StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/vendors` | Register a vendor | MerchandiseBuyer |
| GET | `/merchandise/vendors` | List vendors | MerchandiseBuyer, MerchandiseAnalyst |
| GET | `/merchandise/vendors/{id}` | Read one vendor | MerchandiseBuyer, MerchandiseAnalyst |
| GET | `/merchandise/vendors/{id}/exclusive-pack-programs` | List a vendor's exclusive pack programs | MerchandiseBuyer, MerchandiseAnalyst |
| POST | `/merchandise/exclusive-pack-programs` | Open an exclusive pack program | MerchandiseBuyer |
| GET | `/merchandise/exclusive-pack-programs` | List exclusive pack programs | MerchandiseBuyer, MerchandiseAnalyst |
| GET | `/merchandise/exclusive-pack-programs/{id}` | Read one exclusive pack program | MerchandiseBuyer, MerchandiseAnalyst |
| PATCH | `/merchandise/exclusive-pack-programs/{id}` | Advance an exclusive pack program's status | MerchandiseBuyer |
| POST | `/merchandise/items` | Denominate a new item at a fixed retail | MerchandiseBuyer |
| GET | `/merchandise/items` | List items | MerchandiseBuyer, MerchandiseAnalyst, StoreOperationsManager, LegalCostEngineer |
| GET | `/merchandise/items/{id}` | Read one item with its derived cost fields | MerchandiseBuyer, MerchandiseAnalyst, StoreOperationsManager, LegalCostEngineer |
| POST | `/merchandise/items/{id}/price-assignments` | Fix an item to a shelf price point | MerchandiseBuyer |
| POST | `/merchandise/items/{id}/price-assignment-release` | Release an item back to DENOMINATED | MerchandiseBuyer |
| POST | `/merchandise/items/{id}/landed-costs` | Apply a freight pass-through or vendor price change | MerchandiseBuyer |
| GET | `/merchandise/items/{id}/landed-costs` | List an item's landed cost history | MerchandiseBuyer, MerchandiseAnalyst, LegalCostEngineer |
| GET | `/merchandise/landed-cost-history` | List landed cost history across items | MerchandiseBuyer, MerchandiseAnalyst, LegalCostEngineer |
| GET | `/merchandise/items/{id}/break-even` | Read an item's break-even projection and regime | MerchandiseBuyer, MerchandiseAnalyst, LegalCostEngineer |
| POST | `/merchandise/items/{id}/activations` | Clear an item to sell at its fixed price point | MerchandiseBuyer |
| POST | `/merchandise/item-deletions/{id}/decision` | Disposition a deletion-review item as RETAIN or DELETE | MerchandiseBuyer |
| POST | `/merchandise/containers` | Book an import container | ImportCoordinator |
| GET | `/merchandise/containers` | List containers | ImportCoordinator, MerchandiseAnalyst, DistributionCenterOperator |
| GET | `/merchandise/containers/{id}` | Read one container | ImportCoordinator, MerchandiseAnalyst, DistributionCenterOperator |
| POST | `/merchandise/containers/{id}/depart` | Move a booked container onto the water | ImportCoordinator |
| POST | `/merchandise/containers/{id}/arrive` | Discharge the container at the port | ImportCoordinator |
| POST | `/merchandise/containers/{id}/customs-hold` | Place a discharged container on customs hold | ImportCoordinator |
| POST | `/merchandise/containers/{id}/customs-release` | Clear the broker hold and return the container to the port queue | ImportCoordinator |
| POST | `/merchandise/containers/{id}/receive` | Receive a customs-cleared container at the DC | ImportCoordinator |
| GET | `/merchandise/containers/{id}/landed-cost-history` | List freight pass-through rows from a container | MerchandiseBuyer, MerchandiseAnalyst, LegalCostEngineer |
| POST | `/merchandise/allocation-lines` | Allocate container units to a store and item | DistributionCenterOperator |
| GET | `/merchandise/allocation-lines` | List allocation lines | DistributionCenterOperator, ImportCoordinator, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/allocation-lines/{id}` | Read one allocation line | DistributionCenterOperator, ImportCoordinator, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/containers/{id}/allocation-lines` | List a container's allocation lines | DistributionCenterOperator, ImportCoordinator, StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/allocation-lines/{id}/release` | Release allocated units to the store's on-hand | DistributionCenterOperator |
| POST | `/merchandise/allocation-lines/{id}/short` | Short an allocation line | DistributionCenterOperator |
| POST | `/merchandise/stores` | Register a store with its shelf facing capacity | StoreOperationsManager |
| GET | `/merchandise/stores` | List stores | StoreOperationsManager, MerchandiseAnalyst, MerchandiseBuyer, LegalCostEngineer |
| GET | `/merchandise/stores/{id}` | Read one store | StoreOperationsManager, MerchandiseAnalyst, MerchandiseBuyer, LegalCostEngineer |
| POST | `/merchandise/stores/{id}/conversions` | Begin converting a single-price store | StoreOperationsManager |
| POST | `/merchandise/stores/{id}/conversions/{conversionId}/filing` | File one conversion artefact | StoreOperationsManager |
| POST | `/merchandise/stores/{id}/conversions/{conversionId}/complete` | Complete a conversion or a reversion | StoreOperationsManager |
| POST | `/merchandise/stores/{id}/conversions/{conversionId}/rollback` | Roll back an in-progress conversion | StoreOperationsManager |
| POST | `/merchandise/stores/{id}/reversions` | Begin pulling a multi-price store back to one price point | StoreOperationsManager |
| GET | `/merchandise/stores/{id}/price-integrity-audits` | List a store's price integrity audits | StoreOperationsManager, MerchandiseAnalyst, LegalCostEngineer |
| GET | `/merchandise/stores/{id}/aisle-resets` | List a store's aisle resets | StoreOperationsManager, ResetCalendarPlanner, MerchandiseAnalyst |
| GET | `/merchandise/stores/{id}/conversion-projects` | List a store's conversion projects | StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/conversion-projects` | Open a conversion project against a CONVERTING store | StoreOperationsManager |
| GET | `/merchandise/conversion-projects` | List conversion projects | StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/conversion-projects/{id}` | Read one conversion project | StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/conversion-projects/{id}/coverage` | Read a project's aisle coverage shortfall | StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/conversion-projects/{id}/start` | Move a draft conversion project into execution | StoreOperationsManager |
| PATCH | `/merchandise/conversion-projects/{id}` | Adjust a conversion project's destination price point | StoreOperationsManager |
| POST | `/merchandise/multi-price-issues` | Issue a batch of items to a converting store's new price point | MerchandiseBuyer |
| POST | `/merchandise/season-windows` | Define a seasonal reset calendar window | ResetCalendarPlanner |
| GET | `/merchandise/season-windows` | List season windows with clock-derived status | ResetCalendarPlanner, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/season-windows/{id}` | Read one season window | ResetCalendarPlanner, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/season-windows/{id}/aisle-resets` | List aisle resets planned inside a season window | ResetCalendarPlanner, StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/season-windows/{id}/schedule` | Publish a draft season window | ResetCalendarPlanner |
| POST | `/merchandise/season-windows/{id}/unschedule` | Pull a scheduled season window back to draft | ResetCalendarPlanner |
| POST | `/merchandise/aisle-resets` | Plan an aisle changeover inside a season window | ResetCalendarPlanner |
| GET | `/merchandise/aisle-resets` | List aisle resets | ResetCalendarPlanner, StoreOperationsManager, MerchandiseAnalyst |
| GET | `/merchandise/aisle-resets/{id}` | Read one aisle reset | ResetCalendarPlanner, StoreOperationsManager, MerchandiseAnalyst |
| POST | `/merchandise/aisle-resets/{id}/begin` | Begin executing a planned aisle reset | ResetCalendarPlanner |
| POST | `/merchandise/aisle-resets/{id}/execute` | Complete the aisle changeover | ResetCalendarPlanner |
| POST | `/merchandise/aisle-resets/{id}/abandon` | Abandon a planned or executing aisle reset | StoreOperationsManager |
| POST | `/merchandise/price-integrity-audits` | File a store price integrity audit | StoreOperationsManager |
| GET | `/merchandise/price-integrity-audits` | List price integrity audits | StoreOperationsManager, MerchandiseAnalyst, LegalCostEngineer |
| GET | `/merchandise/price-integrity-audits/{id}` | Read one price integrity audit | StoreOperationsManager, MerchandiseAnalyst, LegalCostEngineer |
| POST | `/merchandise/price-integrity-audits/{id}/resolve` | Resolve an open price integrity violation | StoreOperationsManager |

## 5. Error Code Catalogue

The table below lists every error identifier this API may return and its HTTP status. Trigger conditions are not repeated here; they are stated in §2 and §3 next to the rule each error guards.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_ROLE` | 403 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_CONTAINER_NOT_FOUND` | 404 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_PRICE_POINT_NOT_FOUND` | 404 |
| `ERR_SEASON_WINDOW_NOT_FOUND` | 404 |
| `ERR_AISLE_RESET_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_LINE_NOT_FOUND` | 404 |
| `ERR_CONVERSION_PROJECT_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_PACK_PROGRAM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_PRICE_POINT_MISMATCH` | 422 |
| `ERR_PRICE_POINT_NOT_ACTIVE` | 409 |
| `ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION` | 409 |
| `ERR_ITEM_NOT_DENOMINATED` | 409 |
| `ERR_ITEM_NOT_PRICE_ASSIGNED` | 409 |
| `ERR_ITEM_NOT_COST_PENDING` | 409 |
| `ERR_ITEM_NOT_IN_DELETE_REVIEW` | 409 |
| `ERR_ITEM_NOT_COST_CLEARED` | 422 |
| `ERR_COST_EXCEEDS_PRICE_POINT` | 422 |
| `ERR_CONTAINER_NOT_BOOKED` | 409 |
| `ERR_CONTAINER_NOT_IN_TRANSIT` | 409 |
| `ERR_CONTAINER_NOT_AT_PORT` | 409 |
| `ERR_CONTAINER_NOT_RECEIVED` | 409 |
| `ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD` | 409 |
| `ERR_CUSTOMS_NOT_CLEARED` | 409 |
| `ERR_CONTAINER_VENDOR_MISMATCH` | 409 |
| `ERR_ALLOCATION_LINE_NOT_ALLOCATED` | 409 |
| `ERR_RELEASE_EXCEEDS_ALLOCATION` | 422 |
| `ERR_STORE_NOT_SINGLE_PRICE` | 409 |
| `ERR_STORE_NOT_MULTI_PRICE` | 409 |
| `ERR_STORE_NOT_CONVERTING` | 409 |
| `ERR_STORE_ALREADY_CONVERTING` | 409 |
| `ERR_CONVERSION_NOT_DRAFT` | 409 |
| `ERR_CONVERSION_NOT_IN_PROGRESS` | 409 |
| `ERR_CONVERSION_PREREQUISITES_UNMET` | 409 |
| `ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT` | 409 |
| `ERR_SEASON_WINDOW_NOT_DRAFT` | 409 |
| `ERR_SEASON_WINDOW_NOT_SCHEDULED` | 409 |
| `ERR_SEASON_WINDOW_NOT_OPEN` | 409 |
| `ERR_INVALID_SEASON_WINDOW` | 400 |
| `ERR_AISLE_RESET_NOT_PLANNED` | 409 |
| `ERR_AISLE_RESET_NOT_EXECUTING` | 409 |
| `ERR_AISLE_RESET_OVERLAP` | 409 |
| `ERR_RESET_OUTSIDE_CALENDAR` | 409 |
| `ERR_STORE_DAY_CAPACITY_EXCEEDED` | 422 |
| `ERR_NO_ELIGIBLE_ITEMS` | 422 |
| `ERR_AUDIT_ALREADY_RESOLVED` | 409 |
| `ERR_MIXED_PRICE_POINT_OPEN_VIOLATION` | 422 |
| `ERR_PACK_COST_TARGET_MISSED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AISLE_COVERAGE_SHORTFALL` | 422 |