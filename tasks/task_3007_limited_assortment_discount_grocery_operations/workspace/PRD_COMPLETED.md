# Limited-Assortment Grocery API — Product Requirements Document

## 1. Introduction

Discount grocery retail runs on a ruthlessly simple economic engine: carry one or two options per category instead of thirty, source them through aggressive private-label tendering, receive them in shelf-ready cases that go straight from pallet to sales floor, and staff the store with a handful of multi-role employees instead of specialized departments. Every one of those disciplines is a rule that must be enforced, not a guideline that can drift. A category that quietly grows past its curated SKU count erodes the buying scale the model depends on; a promotional "Finds" buy that gets replenished stops being a treasure hunt; a coin-deposit cart fleet that is not reconciled is a slow cash leak. The service starts empty on every boot: nothing is seeded and nothing is persisted across restarts.

This document specifies the product requirements for the Limited-Assortment Grocery Operations API, the system of record for that operating model. It governs category assortment discipline with hard SKU caps, dual-source supplier tendering adjudicated partly through blind quality panels, weekly one-time promotional buys allocated to stores by a tier-aware waterfall, cart-deposit coin reconciliation, cashier scan-rate performance measurement against a fixed standard, a lean weekly labor-window budget, and a double-refund quality guarantee with tracked claim liability. All endpoints are mounted under the `/v1` prefix, with a single administrative clock endpoint outside it. The intended readers are the engineers implementing the service and the operators who will run it.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, presenting either header as empty or whitespace-only, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `OperationsAdmin`, `CategoryManager`, `ProcurementLead`, `QualityAssuranceLead`, `SupplierRep`, `StoreManager`, `Cashier`, and `CustomerServiceAgent`.

Role identity semantics differ across roles and are contractual:

- When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's foreign-key field to `X-User-ID`. A supplier representative bids only as their own supplier.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` compare the resource's store foreign-key field to `X-User-ID`. A store manager operates exactly one store.
- When `X-User-Role` is `Cashier`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` (such as the cashier staffing a register shift) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `OperationsAdmin`, `CategoryManager`, `ProcurementLead`, `QualityAssuranceLead`, or `CustomerServiceAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Segregation of duties is deliberate: the `QualityAssuranceLead` runs blind quality panels but cannot create, open, evaluate, or award tenders; the `ProcurementLead` runs tendering but never scores panels; the `OperationsAdmin` provisions stores and drives the logical clock but touches neither.

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
- The `api_request_timestamp` in `meta` is the wall-clock moment the response is generated (not the server logical clock of §2.7); the pagination fields appear in `meta` only on success list responses.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and a non-integer or out-of-range value is rejected with `ERR_VALIDATION`. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; rows created in the same clock instant are tie-broken by creation sequence. The `has_more` field of `meta` is true exactly when `offset` plus the number of returned items is less than `total_count`. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All primary resources carry a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` field is a system-managed integer that increments by exactly 1 on every mutation and underpins optimistic concurrency control. Recomputing a derived field — an assortment count, a liability balance, an allocation remainder — is a mutation of the owning resource and therefore refreshes `updated_at` and increments `version`.

The one exception is the `CartCoinEvent`, which is an append-only ledger entry: it carries `id` and `created_at` only, and has neither `updated_at` nor `version`. A resource's `created_at` and `updated_at` are stamped from the server logical clock of §2.7, so a mutation leaves `updated_at` textually unchanged when the clock has not advanced. A resource is created with `version` 1. Resources whose every change flows through an explicit mutating endpoint (such as `Supplier`) refresh `updated_at` and increment `version` only when a field value actually changes; resources with system-recomputed fields (such as `Store`) are refreshed on every recomputation, whether or not the value moved.

### 2.5. Monetary Units, Precision, and Rounding

All money in the system is expressed in integer cents — prices, costs, ceilings, budgets, liabilities, and refunds alike. Rates and percentages that carry fractions (panel weighting scores, scan rates, sell-through percentages) are computed to exactly 2 decimal places using the round-half-up method. Where a calculation specifies integer output (an allocation quota, a clearance unit price, a refund amount, a labor cost), the value is rounded half-up to a whole number at the point the calculation states, and not before. Counts are plain integers and never rounded.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent entity's `version`, and no other endpoint accepts a version field.

- Re-planning a Finds buy's allocations requires the request to carry `expected_finds_buy_version` holding the client's last observed `version` of the buy. If the buy's current `version` has advanced since that read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a category's SKU cap requires the request to carry `expected_category_version` holding the client's last observed `version` of the category. If the category's current `version` has advanced since that read — for example because a product activation or discontinuation moved the assortment count — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

In both cases the client must re-read the resource and retry against the fresh version; a cap change or re-plan based on a stale assortment view could otherwise silently violate SKU discipline or replace a plan the client never saw.

### 2.7. The Server Logical Clock

The server maintains a logical clock, distinct from wall-clock time, that is the single source of "now" for the entire domain. An `OperationsAdmin` may advance it through an administrative capability that accepts a `to_iso8601` instant (ISO 8601 UTC) and responds with the resulting `current_utc`. Before any such call, the clock's startup default is exactly `2026-09-01T00:00:00Z`; the clock never falls back to wall-clock time on its own. Register-shift open and close timestamps, the 45-day quality-claim filing window, sale-window checks on allocation sells, the clearance gap, and the ISO-week boundaries used by labor budgeting are all evaluated against this clock.

### 2.8. Validation Precedence

When a request violates more than one rule, the error surfaced is determined by a fixed evaluation order. The nine tiers are, from first to last:

1. Authentication: presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`).
2. Authorization and ownership: the acting role is permitted for the endpoint and entity-backed ownership checks pass (`ERR_FORBIDDEN`).
3. Request shape: required fields present, types correct, enum members valid (`ERR_VALIDATION`).
4. Existence: every path identifier and body foreign-key reference resolves to an existing resource (`ERR_NOT_FOUND`). Unrecognized paths and unsupported methods also produce `ERR_NOT_FOUND` (HTTP 404), and a request body that is not a JSON object produces `ERR_VALIDATION` (HTTP 400).
5. State admissibility: the target resource is in a state that permits the operation (`ERR_INVALID_STATE`, and its state-specific counterparts such as `ERR_TENDER_NOT_OPEN` and `ERR_SHIFT_NOT_OPEN`).
6. Blind-panel integrity (`ERR_BLIND_VIOLATION`).
7. Temporal and window rules (`ERR_WINDOW_OVERLAP`, `ERR_SALE_WINDOW_CONFLICT`, `ERR_CLEARANCE_GAP_VIOLATION`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SALE_WINDOW_INACTIVE`).
8. Structural business constraints (`ERR_SKU_CAP_EXCEEDED`, `ERR_SKU_CAP_BELOW_CURRENT`, `ERR_DUPLICATE_SKU`, `ERR_BARCODE_COUNT_INVALID`, `ERR_SHELF_READY_REQUIRED`, `ERR_BID_DUPLICATE`, `ERR_DUAL_SOURCE_REQUIRED`, `ERR_SUPPLIER_SUSPENDED`, `ERR_ALLOCATION_INCOMPLETE`, `ERR_PRODUCT_NOT_ACTIVE`, `ERR_FINDS_NO_REPLENISHMENT`, `ERR_WINDOW_LIMIT_EXCEEDED`, `ERR_CASHIER_ROLE_REQUIRED`).
9. Fiscal rules, always last (`ERR_BID_CEILING_EXCEEDED`, `ERR_LABOR_BUDGET_EXCEEDED`, `ERR_COIN_BALANCE_NEGATIVE`, `ERR_ALLOCATION_EXHAUSTED`).

A structural violation therefore surfaces before a budget violation on the same request, and a blind-panel violation before a window conflict.

### 2.9. Nested Resource Retrieval

Endpoints whose paths nest one resource beneath another validate identifiers strictly left to right. The first identifier in the path that fails to resolve to an existing resource produces the `ERR_NOT_FOUND` response, and no later identifier is examined. A request addressing a bid under a tender that does not exist fails on the tender; a request addressing an employee under a store that does not exist fails on the store.

---

## 3. Business Logic & Workflows

### 3.1. Categories and the Discipline of the SKU Cap

Every category in the assortment is created by a `CategoryManager` with a unique short `code` (such as DAIRY or BAKERY) and a display `name`. The defining attribute is the `sku_cap`: the maximum number of `ACTIVE` products the category may hold at any moment. It defaults to 2 when not supplied and must be at least 1 and at most 5 — the limited-assortment model tolerates narrow variation between categories, never breadth. A newly created category starts in `OPEN` status with an `active_sku_count` of 0.

The `active_sku_count` is a computed field, not a stored guess: it counts the category's products whose `kind` is `CORE` and whose status is `ACTIVE`. Proposed and discontinued products are excluded, and `FINDS` products are always excluded — weekly promotional items live outside the cap entirely. The count recomputes whenever a `CORE` product of the category is activated (through a tender award or a reactivation) or discontinued.

The category's status is a direct read-out of that count. When the count reaches the cap, the category auto-transitions `OPEN → LOCKED`, refreshing its `updated_at` and incrementing its `version`; while `LOCKED`, no further activations are permitted. When the count later drops below the cap — because a product was discontinued — the category auto-transitions `LOCKED → OPEN` on the same terms. These transitions are system-driven; no endpoint flips a category's status directly.

A `CategoryManager` may adjust the cap itself. The update requires `expected_category_version` under the OCC rule of §2.6, increments the category's `version`, and immediately re-evaluates the category's status against the new cap (a re-evaluation that changes nothing applies no further increment). The stale-version check runs before the structural guards. Two guards apply: raising or lowering the cap can never leave the cap below the category's current `active_sku_count` — such a request is rejected with `ERR_SKU_CAP_BELOW_CURRENT` — and the cap must remain within the 1-to-5 band. Categories may be listed with an optional `status` filter, and individual categories fetched, by `CategoryManager`, `ProcurementLead`, and `OperationsAdmin` readers.

### 3.2. Product Onboarding: Proposed Until Awarded

A `CategoryManager` creates a product by supplying its `category_id`, a globally unique `sku_code`, a display `name`, its `kind`, whether it ships in `shelf_ready_packaging`, its `barcode_count`, a target `unit_cost_cents`, and a shelf `price_cents`. Every product is born in `PROPOSED` status: creation alone never places an item on the shelf. Activation happens only as a side effect of a dual-source tender award, or later through reactivation of a discontinued item.

The `kind` field splits the assortment in two. `CORE` products are permanent line items, fully subject to the owning category's `sku_cap`. `FINDS` products are weekly one-time promotional buys: exempt from the cap, but held to a stricter merchandising standard — a `FINDS` product created without `shelf_ready_packaging` set to true is rejected with `ERR_SHELF_READY_REQUIRED`, because pallet-display merchandising admits no decanting labor. Barcode design supports the cashier scan-rate standard: every product needs at least 1 barcode, and any product with `shelf_ready_packaging` must carry at least 2 scannable barcodes so a cashier can always find one without re-orienting the case. A `barcode_count` below those minimums is rejected with `ERR_BARCODE_COUNT_INVALID`, and a `sku_code` that collides with any existing product is rejected with `ERR_DUPLICATE_SKU`; the duplicate-SKU check runs before the barcode check, which runs before the shelf-ready check. The `unit_cost_cents` and `price_cents` must each be a non-negative integer (`ERR_VALIDATION` otherwise).

A product's sourcing is recorded in `primary_supplier_id` and `secondary_supplier_id`. Both are null at creation and are populated only by a tender award; the secondary must always be a different supplier from the primary, so the supply base is genuinely dual-sourced.

Discontinuation is an explicit `CategoryManager` action available only while the product is `ACTIVE`. It moves the product `ACTIVE → DISCONTINUED`, recomputes the owning category's `active_sku_count` (which may auto-`OPEN` a `LOCKED` category), refreshes the product's `updated_at`, and increments its `version`. Reactivation reverses this for a `DISCONTINUED` product, but only when two conditions hold: the owning category is `OPEN`, and — for `CORE` products — the category's `active_sku_count` is below its `sku_cap`. A reactivation that would fill the last slot is fine; one attempted against a category already at its cap is rejected with `ERR_SKU_CAP_EXCEEDED`. For a `CORE` product, the at-cap condition is evaluated before the `OPEN` condition: because the auto-transition invariant makes `LOCKED` equivalent to `active_sku_count >= sku_cap`, a `CORE` reactivation against an at-cap category surfaces `ERR_SKU_CAP_EXCEEDED`, not `ERR_INVALID_STATE`. For a `FINDS` product, the at-cap condition does not apply, and the `OPEN` condition is the only category-level guard. A successful reactivation moves the product `DISCONTINUED → ACTIVE`, recomputes the category count (which may auto-`LOCK` the category), and applies the standard `updated_at`/`version` mutation. Products may be listed with `category_id`, `kind`, and `status` filters; a `category_id` filter matches only products whose `category_id` equals it exactly, without any existence check on the filtered value.

### 3.3. Suppliers and the Quality History Score

A `ProcurementLead` registers a supplier with a legal `name` and a `contact_email`. Every supplier begins in `ACTIVE` status with a `quality_score` of exactly 80.0 — a neutral starting point on a 0-to-100 scale that subsequent tender outcomes move. The `SUSPENDED` status exists in the model but no endpoint transitions a supplier into or out of it.

The `quality_score` is recomputed each time a tender the supplier participated in reaches `AWARDED`: suppliers whose bids won (primary or secondary) gain 2 points, suppliers whose bids were disqualified lose 5 points, and all other participating suppliers are unchanged. The result is clamped so it never falls below 0 or exceeds 100. A supplier in `SUSPENDED` status cannot bid; any bid submitted on its behalf is rejected with `ERR_SUPPLIER_SUSPENDED`.

Three read views exist: fetching a single supplier, listing the products that source from a supplier as either primary or secondary, and listing the bids a supplier has placed.

### 3.4. Private-Label Tendering and the Blind Panel

Tendering is the only path by which a `PROPOSED` product becomes `ACTIVE`, and it is built around a dual-source requirement with a blind quality gate. A `ProcurementLead` creates a tender for a `product_id` with a `bid_ceiling_cents` — the maximum acceptable unit cost, an integer of at least 1 — and an optional `min_sources`, which defaults to 2 and in this domain is fixed at 2: the request's `min_sources`, when supplied, must be an integer of at least 1 and is validated, but the tender's stored `min_sources` is always 2 and every awarded product must have two distinct suppliers. A tender may be created for a product of any kind and any status.

**Lifecycle.** A tender is born in `DRAFT`. Opening it moves it `DRAFT → OPEN` and admits bids; closing it moves it `OPEN → CLOSED` and freezes the bid set. A tender still in `DRAFT` or `OPEN` may instead be cancelled, moving to the terminal `CANCELLED` state. Each of these transitions refreshes the tender's `updated_at` and increments its `version`.

**Bidding.** A `SupplierRep` submits a bid on an `OPEN` tender, naming their `supplier_id` and an offered `unit_cost_cents` (a non-negative integer); the tender to which the bid belongs is recorded as `tender_id`. One bid per supplier per tender — a second submission is rejected with `ERR_BID_DUPLICATE`. A bid on a tender that is not `OPEN` is rejected with `ERR_TENDER_NOT_OPEN`, and an offer above the tender's `bid_ceiling_cents` is rejected with `ERR_BID_CEILING_EXCEEDED` at submission time. Each bid starts in `SUBMITTED` status with a null `award_score`.

**Blind panels.** Before a tender can be evaluated, every one of its bids must be panel-tested — and blinded. A `QualityAssuranceLead` schedules a panel for a bid by supplying an opaque `sample_code`; the panel records its `bid_id` and starts in `SCHEDULED` status with a null `score`. The blindness rule is hard: the `sample_code` must not equal or contain the bidding supplier's `id` or the supplier's `name`, and there is exactly one panel per bid — a second panel for the same bid is likewise refused. Either violation is rejected with `ERR_BLIND_VIOLATION`, and the duplicate-panel check runs before the sample-code content check. The blindness rule is enforced only at scheduling time; panels may be scheduled for a bid regardless of its tender's current status. Panels may be listed with `bid_id` and `status` filters.

**Scoring.** While the owning bid's tender is `OPEN` or `CLOSED`, a `QualityAssuranceLead` records the panel's `score` — an integer from 0 to 100 — moving the panel `SCHEDULED → SCORED` with the standard `updated_at`/`version` mutation. Scoring against a panel that is not `SCHEDULED`, or whose tender has moved past `CLOSED`, is a state violation.

**Evaluation.** Evaluating a `CLOSED` tender moves it `CLOSED → EVALUATING` and requires that every bid of the tender has exactly one panel and that every such panel is `SCORED`; otherwise the evaluation is rejected with `ERR_PANEL_INCOMPLETE`. Evaluation computes each bid's `award_score` as follows. If the bid's panel `score` is below 60, or the bid's `unit_cost_cents` exceeds the tender's `bid_ceiling_cents`, the bid is marked `DISQUALIFIED` and its `award_score` is set to the marker value −1.0. Otherwise the bid is marked `ELIGIBLE`, and its score is a weighted blend: one-half of the panel `score`, plus three-tenths of a price score, plus one-fifth of the bidding supplier's `quality_score`. The price score is 100 times the headroom between the ceiling and the offered cost, expressed as a fraction of the ceiling — that is, the difference between `bid_ceiling_cents` and the bid's `unit_cost_cents`, divided by `bid_ceiling_cents`, multiplied by 100. The blended result is rounded half-up to 2 decimal places. Evaluation also locks every panel of the tender's bids, moving each `SCORED → LOCKED`, and applies the tender's standard mutation.

**Award.** Awarding an `EVALUATING` tender requires the request to name a `primary_bid_id` and a `secondary_bid_id`. Both must reference `ELIGIBLE` bids of this tender, and the two bids must come from two distinct suppliers; an award naming bids from the same supplier, or made when fewer than `min_sources` distinct suppliers hold `ELIGIBLE` bids, is rejected with `ERR_DUAL_SOURCE_REQUIRED`, and the same-supplier check runs before the eligibility checks. A named bid that is not `ELIGIBLE` (or that belongs to another tender) surfaces `ERR_INVALID_STATE`, not `ERR_DUAL_SOURCE_REQUIRED`; naming the same bid twice therefore also surfaces `ERR_DUAL_SOURCE_REQUIRED`. The tendered product must still be `PROPOSED` — a product already `ACTIVE` or `DISCONTINUED` surfaces `ERR_INVALID_STATE` — and — for a `CORE` product — its category must have `active_sku_count` below `sku_cap`, or the award is rejected with `ERR_SKU_CAP_EXCEEDED`.

Selection guidance for the award is deterministic: the primary should be the `ELIGIBLE` bid with the highest `award_score`, breaking ties toward the lower `unit_cost_cents` and then toward the earlier bid `created_at`; the secondary should be the highest-scored `ELIGIBLE` bid whose supplier differs from the primary's, using the same tie-breaks. The bid `id` never participates in ranking or tie-breaking.

An accepted award cascades broadly. The two winning bids move `ELIGIBLE → AWARDED_PRIMARY` and `ELIGIBLE → AWARDED_SECONDARY`; every other bid of the tender moves to the terminal `NOT_SELECTED` state, each with the standard `updated_at`/`version` mutation. The tender records the winners in `winning_primary_bid_id` and `winning_secondary_bid_id` and moves `EVALUATING → AWARDED`, a terminal state. The product's `primary_supplier_id` and `secondary_supplier_id` are set from the winning bids, the product transitions `PROPOSED → ACTIVE`, and the resulting recomputation of the category's `active_sku_count` may auto-transition the category `OPEN → LOCKED`. Finally, the `quality_score` of every supplier that bid is recomputed as described in §3.3 — winners up 2, disqualified bidders down 5, clamped to the 0–100 band.

**Retender.** When evaluation leaves fewer than `min_sources` distinct suppliers holding `ELIGIBLE` bids, the tender cannot be awarded but it is not dead: a retender loops it `EVALUATING → OPEN`. A retender attempted while at least `min_sources` distinct suppliers hold `ELIGIBLE` bids is rejected with `ERR_INVALID_STATE`. Every bid of the tender reverts to `SUBMITTED` with its `award_score` reset to null — including bids that had been `DISQUALIFIED`, which return to `SUBMITTED` the same way — and every panel reverts `LOCKED → SCORED`. The cycle `OPEN → CLOSED → EVALUATING → OPEN` may repeat as often as procurement needs.

### 3.5. Weekly Finds Buys and the Allocation Waterfall

The weekly Finds program is a one-time buy: a fixed quantity is purchased, allocated across stores, sold through a fixed window, and never replenished — the scarcity is the merchandising. A `CategoryManager` creates a Finds buy by naming a `product_id`, a `week_start_date`, a `week_end_date` (the last sale day, inclusive, which must not precede the start date), and a `total_quantity` of at least 1 (an end date preceding the start date is `ERR_VALIDATION`). The referenced product must be a `FINDS` product in `ACTIVE` status; buying against any other product — a `CORE` product, or a `FINDS` product not `ACTIVE` — is rejected with `ERR_PRODUCT_NOT_ACTIVE`. A new buy is in `PLANNED` status with `allocated_quantity` and `remaining_quantity` both 0. Buys may be listed with `product_id` and `status` filters.

**Planning the allocation.** Running allocation planning on a `PLANNED` buy moves it `PLANNED → ALLOCATED` and requires that at least one store exists in `ACTIVE` status; planning against zero active stores is rejected with `ERR_INVALID_STATE`. Every planning request — the initial plan and every superseding re-plan alike — must carry `expected_finds_buy_version` under the OCC rule of §2.6, and the state-admissibility check (`PLANNED` with active stores, or `ALLOCATED`) runs before the version check. Stores of status other than `ACTIVE` (a store may also be `CLOSED`) receive no allocation. The waterfall distributes `total_quantity` across all `ACTIVE` stores. Stores carry a `tier` of either `HIGH_VOLUME` or `STANDARD`; tiers are processed in priority order, `HIGH_VOLUME` first. Each tier's pool is the buy's `total_quantity` multiplied by the tier's share — 60 percent for `HIGH_VOLUME`, 40 percent for `STANDARD` — rounded down to whole units. Shares renormalize over the tiers actually present: if only one tier has stores, its share is the entire quantity. Within a tier, the pool is divided evenly, each store's per-store quota being the tier pool divided by the tier's store count, again rounded down. Whatever remains after quotas are assigned is distributed one unit at a time to stores ordered first by tier priority and then by store `created_at`, earliest first, until nothing remains. Each store's resulting `FindsAllocation` records the buy's `finds_buy_id`, the receiving `store_id`, and its computed `allocated_quantity`; `sold_quantity` starts at 0, and `remaining_quantity` is `allocated_quantity` minus `sold_quantity`. An allocation's `sale_start_date` and `sale_end_date` stay null until the buy is activated. The buy's `allocated_quantity` becomes the sum over all allocations, its `remaining_quantity` is its `allocated_quantity` minus the sum of all `sold_quantity` values, and its `version` increments. Allocation rows start in `RESERVED` status. Planning returns the buy object. A `StoreManager` reading one buy fetches any buy but must present an `X-User-ID` equal to the id of some existing store (`ERR_FORBIDDEN` otherwise), and listing a buy's allocations as a `StoreManager` returns only that store's rows.

**Superseding a plan.** While the buy is `ALLOCATED`, planning may run again: every existing allocation row — all still `RESERVED` — is deleted and the waterfall recreates the plan from scratch. Because a re-plan legitimately replaces the prior draft, it is OCC-guarded per §2.6, and a stale `expected_finds_buy_version` is rejected with `ERR_STALE_VERSION`. Once the buy has moved past `ALLOCATED`, planning is closed forever — there is no replenishment — and any further planning attempt is rejected with `ERR_FINDS_NO_REPLENISHMENT`.

**Activation.** Activating an `ALLOCATED` buy moves it `ALLOCATED → ON_SALE` under three conditions, all enforced. First, sale-window exclusivity: for every store receiving an allocation, no other allocation of that store in `ON_SALE` or `CLEARANCE` status may have an inclusive sale window overlapping the buy's `[week_start_date, week_end_date]` window; a conflict is rejected with `ERR_SALE_WINDOW_CONFLICT`. Second, conservation: the buy's `allocated_quantity` must equal its `total_quantity` exactly — an activation with any unit unallocated is rejected with `ERR_ALLOCATION_INCOMPLETE`. Third, the buy's product must still be `ACTIVE`, else `ERR_PRODUCT_NOT_ACTIVE`. The conditions are evaluated in the stated order — a window conflict surfaces before a conservation gap, which surfaces before a dead product. On activation, every allocation of the buy transitions `RESERVED → ON_SALE`, with `sale_start_date` and `sale_end_date` copied from the buy's window, and the buy's `version` increments.

**Selling.** A `StoreManager` records a sale against one of their store's allocations in `ON_SALE` or `CLEARANCE` status, supplying a `quantity` of at least 1. A sale against an allocation in any other status is rejected with `ERR_INVALID_STATE`. The sale must fall within the allocation's current sale window as read from the logical clock — the comparison uses the clock's calendar date against the inclusive `[sale_start_date, sale_end_date]` bounds, and a sell outside the window is rejected with `ERR_SALE_WINDOW_INACTIVE` — and must not exceed the allocation's `remaining_quantity`, else `ERR_ALLOCATION_EXHAUSTED`. A recorded sale increases `sold_quantity` by `quantity` and recomputes `remaining_quantity`. If that leaves the allocation at zero remaining, it auto-transitions to `SOLD_OUT`; the buy's `remaining_quantity` is then recomputed, and if it too reaches zero the buy auto-transitions `ON_SALE → SOLD_OUT`. When a buy reaches `SOLD_OUT`, every store holding an allocation of it has its `finds_sell_through_pct` recomputed — the percentage, from 0 to 100, of allocated Finds quantity sold across that store's allocations that sit in terminal sell states, where the terminal sell states are `SOLD_OUT` and `CLOSED`; a store with no such allocations reports 0. The endpoint returns the allocation.

**Clearance.** A `StoreManager` may move an `ON_SALE` allocation with `remaining_quantity` above zero into `CLEARANCE`, supplying a `clearance_markdown_pct` — a markdown fraction strictly between 0 and 1, such as 0.30 (`ERR_VALIDATION` otherwise) — plus a `clearance_start_date` and a `clearance_end_date`, the latter not preceding the former (`ERR_VALIDATION` otherwise). An allocation that is not `ON_SALE`, or whose `remaining_quantity` is zero, is rejected with `ERR_INVALID_STATE`. A mandatory gap day separates the programs: the clearance start must be at least one day after the allocation's `sale_end_date`, and an earlier start is rejected with `ERR_CLEARANCE_GAP_VIOLATION`. The allocation's sale window is replaced by the clearance window, and its `clearance_value_cents` is computed: the unit clearance price is the product's `price_cents` multiplied by one minus the markdown fraction, rounded half-up to a whole cent per unit first, and that rounded unit price is then multiplied by the allocation's `remaining_quantity`. The per-unit-first rounding order is contractual — rounding only after multiplying by quantity can differ by cents and is not equivalent. The `clearance_markdown_pct` and `clearance_value_cents` fields remain null on any allocation that has never entered clearance. A `CLEARANCE` allocation that sells out auto-transitions to `SOLD_OUT` on the same cascade as above.

**Closing the week.** Once the logical clock's date has moved strictly past `week_end_date` — closing on the end date itself is premature — and no allocation of the buy remains in `ON_SALE` status (all are `SOLD_OUT`, `CLEARANCE`, or `CLOSED`), a `CategoryManager` closes the buy. A close attempted on a buy that is not `ON_SALE`, or while any allocation is still `ON_SALE`, is rejected with `ERR_INVALID_STATE`; a close attempted before the week has fully ended is rejected with `ERR_WINDOW_OVERLAP`. Closing moves the buy `ON_SALE → CLOSED`, any `CLEARANCE` allocations move to `CLOSED` with it, and `finds_sell_through_pct` is recomputed for every participating store. `SOLD_OUT` and `CLOSED` are the buy's terminal states.

Every store is created by an `OperationsAdmin` with a unique short `code`, a display `name`, a `tier` of `HIGH_VOLUME` or `STANDARD`, and a non-negative integer `weekly_labor_budget_cents`. A new store starts in `ACTIVE` status — stores may also be `CLOSED`, though no endpoint performs that transition — with `coins_outstanding` 0, `coin_liability_cents` 0, `refund_liability_cents` 0, `refund_paid_cents` 0, and `finds_sell_through_pct` 0. A `StoreManager` hires an employee into their own store with a `name` and a `role` of `CASHIER`, `STOCKER`, or `SHIFT_LEAD`; a new employee is `ACTIVE` and never changes status, and employees may be listed with an optional `role` filter.

### 3.6. The Cart-Deposit Coin Ledger

Customers deposit a quarter to release a cart and reclaim it on return; staff periodically sweep stray coins from corrals back to the float. Every store tracks this as an append-only ledger of `CartCoinEvent` rows, each stamped against a `store_id` with an `event_type` and a `coin_count`. A `Cashier` or `StoreManager` appends events; there are four types. `INSERT` records a customer depositing a coin; `RETURN` records a coin given back; `CORRAL_COLLECT` records staff collecting stray coins back to the float; `AUDIT_ADJUST` records a signed reconciliation adjustment. The `coin_count` is strictly positive for `INSERT`, `RETURN`, and `CORRAL_COLLECT` (zero or negative counts are rejected with `ERR_VALIDATION`), and signed for `AUDIT_ADJUST`. Each appended event also mutates the owning store — recomputing its derived coin balance and liability — and so refreshes the store's `updated_at` and increments its `version`.

The store's `coins_outstanding` — coins currently held by customers in carts — is derived by replaying the store's events in `created_at` ascending order (timestamps carry three fractional digits, and `id` is never used for ordering): an `INSERT` adds its `coin_count`, a `RETURN` and a `CORRAL_COLLECT` each subtract theirs, and an `AUDIT_ADJUST` adds its signed `coin_count`. The balance is checked against the running prefix: any `RETURN`, `CORRAL_COLLECT`, or `AUDIT_ADJUST` that would drive it negative is rejected with `ERR_COIN_BALANCE_NEGATIVE`. The store's `coin_liability_cents` is the outstanding count multiplied by 25 — the quarter deposit per cart. A reconciliation snapshot for a store reports `coins_inserted`, `coins_returned`, `coins_collected`, `coins_adjusted`, `coins_outstanding`, and `coin_liability_cents`, and events may be listed chronologically with an optional `event_type` filter.

### 3.7. Register Shifts and the Scan-Rate Standard

Cashier productivity is managed against a fixed standard: a compliant register shift scans at least 1000 items per hour, with voided items penalized at final accounting. A `StoreManager` opens a shift at their store by naming a `cashier_id`. The named employee must have the role `CASHIER` — opening a register for a `STOCKER` or `SHIFT_LEAD` is rejected with `ERR_CASHIER_ROLE_REQUIRED` — and the named employee need not belong to the shift's store. The shift's `started_at` is stamped from the server logical clock; `closed_at` stays null while the shift is `OPEN`. Counters `items_scanned` and `voids` start at 0, `provisional_scan_rate` at 0.0, and `final_scan_rate` and `compliance` stay null until close.

While the shift is `OPEN`, the staffing `Cashier` records scan batches, supplying a non-negative integer `items_count` and optionally a non-negative integer `voids_count` defaulting to 0. Each batch increments `items_scanned` and `voids` accordingly and recomputes the provisional rate: `items_scanned` multiplied by 3600 and divided by the number of seconds elapsed since `started_at` (with a denominator of at least 1 second), rounded half-up to 2 decimal places. The provisional variant ignores voids and diverges from the final figure whenever voids exist or the shift keeps running; it is a live dashboard number, not the standard of record. Any scan or close attempted on a shift not in `OPEN` status is rejected with `ERR_SHIFT_NOT_OPEN`.

Closing a shift — a `StoreManager` action restricted to the manager's own store — moves it `OPEN → CLOSED`, stamps `closed_at` from the logical clock, and computes the final variant exactly once: the count of scanned items minus 2 per void — a quantity that may go negative when voids dominate — multiplied by 3600 and divided by the shift's full duration in seconds (again with a denominator of at least 1), rounded half-up to 2 decimal places, stored as `final_scan_rate`. The `compliance` flag follows directly: `COMPLIANT` when the final rate is at least 1000, `BELOW_STANDARD` below it — a shift landing exactly on 1000 is compliant. Shifts may be listed per store or per employee, with an optional `status` filter on the store view.

### 3.8. Labor Windows and the Weekly Staffing Budget

Replenishment labor is booked in lean, multi-role windows. A `StoreManager` books a window for their store by supplying an `aisle_zone`, a staffing `role` (`CASHIER`, `STOCKER`, or `SHIFT_LEAD`), a `starts_at`, and an `ends_at`, both ISO 8601 UTC instants with the end strictly after the start (`ERR_VALIDATION` otherwise). The window is treated as a half-open interval — it occupies time from `starts_at` up to but not including `ends_at`. Its `cost_cents` is computed before any budget check: the duration in seconds divided by 3600 and rounded half-up to 2 decimal places gives the hours, and the hours multiplied by the role's hourly rate — 1700 cents for a `CASHIER`, 1800 cents for a `STOCKER`, 2400 cents for a `SHIFT_LEAD` — rounded half-up to whole cents gives the cost. A new window is born in `PLANNED` status.

Two structural guards and one fiscal guard apply at booking. Within the same store and `aisle_zone`, a new window must not overlap any existing `PLANNED` or `CONFIRMED` window under half-open semantics — back-to-back windows touching at an endpoint are fine — else `ERR_WINDOW_OVERLAP`. A store may hold at most 6 non-cancelled windows whose `starts_at` falls in the same ISO week, counted from Monday 00:00 UTC up to but not including the next Monday 00:00 UTC; a seventh is rejected with `ERR_WINDOW_LIMIT_EXCEEDED`. And the money rule runs last: the store's weekly spend — the sum of `cost_cents` over its `PLANNED` and `CONFIRMED` windows in that same ISO week — plus the new window's cost must not exceed the store's `weekly_labor_budget_cents`, or the booking is rejected with `ERR_LABOR_BUDGET_EXCEEDED`.

Confirmation moves a `PLANNED` window `PLANNED → CONFIRMED`; it is a `StoreManager` action restricted to the manager's own store. Cancellation is available from either `PLANNED` or `CONFIRMED` and moves the window to the terminal `CANCELLED` state, removing its cost from the weekly spend aggregation so the budget re-aggregates without it. Windows may be listed per store with a `status` filter.

### 3.9. The Double-Refund Quality Guarantee

The quality guarantee is simple to state and expensive to honor: if a product fails on quality, the customer gets double their money back. A `CustomerServiceAgent` files a claim naming the `product_id`, the `store_id` of purchase (where the refund liability accrues), the `quantity` claimed (at least 1), the `unit_price_cents` paid (a non-negative integer), the `purchase_date`, and a `reason` of `QUALITY_DEFECT`, `DAMAGED`, or `OTHER`. The purchase must be recent: a `purchase_date` more than 45 days before the logical clock's date at filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`; a purchase date exactly 45 days in the past is admissible. A new claim is in `FILED` status with a null `refund_amount_cents`. Claims may be listed with `product_id`, `store_id`, and `status` filters.

Review moves a claim `FILED → UNDER_REVIEW`, and the same action re-opens a `DISPUTED` claim — the cycle `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` may repeat. From `UNDER_REVIEW` three outcomes are possible. Rejection moves the claim to the terminal `REJECTED` state. Dispute moves it to `DISPUTED`, awaiting re-review. Approval moves it `UNDER_REVIEW → APPROVED` and prices the refund: for a `QUALITY_DEFECT` claim the `refund_amount_cents` is the `unit_price_cents` multiplied by the `quantity` and doubled, rounded half-up to whole cents; for `DAMAGED` or `OTHER` the same inputs are refunded at face value, identically rounded. (With integer inputs these products are already whole; the rounding is fixed so fractional inputs, if ever admitted, resolve identically.) Identical inputs under the guarantee reason therefore yield exactly double the standard refund. Approval immediately increases the store's `refund_liability_cents` by the computed amount.

An approved claim has two exits. Payout moves it `APPROVED → PAID`: the store's `refund_liability_cents` decreases by `refund_amount_cents` and its `refund_paid_cents` increases by the same amount — the cumulative record of refunds actually disbursed. Rescission is the compensating reversal for an approval that should not have stood: it moves the claim `APPROVED → RESCINDED` and decreases the store's `refund_liability_cents` by `refund_amount_cents`, fully compensating the approval without touching `refund_paid_cents`. `PAID`, `REJECTED`, and `RESCINDED` are terminal. Every claim transition increments the claim's `version`; approval, payout, and rescission each additionally refresh the store's `updated_at` and increment its `version`. Every claim transition endpoint returns the claim object.

---

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources and all action endpoints return HTTP 200. Reads return HTTP 200. The table below is a navigation summary only — request payloads, computed fields, and side effects are specified in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/categories | Create a category with SKU cap | CategoryManager |
| GET | /v1/categories | List categories | CategoryManager, ProcurementLead, OperationsAdmin |
| GET | /v1/categories/{id} | Fetch one category | CategoryManager, ProcurementLead, OperationsAdmin |
| PATCH | /v1/categories/{id} | Update sku_cap under OCC | CategoryManager |
| POST | /v1/suppliers | Register a supplier | ProcurementLead |
| GET | /v1/suppliers/{id} | Fetch one supplier | ProcurementLead, CategoryManager, QualityAssuranceLead |
| GET | /v1/suppliers/{id}/products | List products sourced from this supplier | ProcurementLead, CategoryManager |
| GET | /v1/suppliers/{id}/bids | List bids placed by this supplier | ProcurementLead, QualityAssuranceLead |
| POST | /v1/products | Create a product (starts PROPOSED) | CategoryManager |
| GET | /v1/products | List products, filterable | CategoryManager, ProcurementLead, OperationsAdmin, CustomerServiceAgent |
| GET | /v1/products/{id} | Fetch one product | CategoryManager, ProcurementLead, OperationsAdmin, CustomerServiceAgent |
| POST | /v1/products/{id}/discontinue | Discontinue an ACTIVE product | CategoryManager |
| POST | /v1/products/{id}/reactivate | Reactivate a DISCONTINUED product | CategoryManager |
| GET | /v1/products/{id}/tenders | List tenders for this product | ProcurementLead, CategoryManager |
| POST | /v1/tenders | Create a supplier tender | ProcurementLead |
| GET | /v1/tenders/{id} | Fetch one tender | ProcurementLead, QualityAssuranceLead, CategoryManager |
| POST | /v1/tenders/{id}/open | Open a DRAFT tender | ProcurementLead |
| POST | /v1/tenders/{id}/close | Close an OPEN tender | ProcurementLead |
| POST | /v1/tenders/{id}/evaluate | Score all bids and lock panels | ProcurementLead |
| POST | /v1/tenders/{id}/award | Award primary and secondary bids | ProcurementLead |
| POST | /v1/tenders/{id}/retender | Loop EVALUATING back to OPEN | ProcurementLead |
| POST | /v1/tenders/{id}/cancel | Cancel a DRAFT or OPEN tender | ProcurementLead |
| POST | /v1/tenders/{id}/bids | Submit a bid on an OPEN tender | SupplierRep |
| GET | /v1/tenders/{id}/bids | List bids of a tender | ProcurementLead, QualityAssuranceLead |
| GET | /v1/bids/{id} | Fetch one bid | ProcurementLead, QualityAssuranceLead, SupplierRep |
| POST | /v1/bids/{id}/panels | Schedule a blind quality panel | QualityAssuranceLead |
| GET | /v1/panels | List panels, filterable by bid | QualityAssuranceLead, ProcurementLead |
| GET | /v1/panels/{id} | Fetch one panel | QualityAssuranceLead, ProcurementLead |
| POST | /v1/panels/{id}/score | Record the blind panel score | QualityAssuranceLead |
| POST | /v1/stores | Create a store | OperationsAdmin |
| GET | /v1/stores/{id} | Fetch one store with ledger fields | OperationsAdmin, StoreManager, CategoryManager, CustomerServiceAgent |
| POST | /v1/stores/{id}/employees | Hire an employee into a store | StoreManager |
| GET | /v1/stores/{id}/employees | List employees of a store | StoreManager, OperationsAdmin |
| GET | /v1/employees/{id} | Fetch one employee | StoreManager, OperationsAdmin |
| POST | /v1/finds-buys | Create a weekly Finds one-time buy | CategoryManager |
| GET | /v1/finds-buys | List Finds buys | CategoryManager, OperationsAdmin, StoreManager |
| GET | /v1/finds-buys/{id} | Fetch one Finds buy | CategoryManager, OperationsAdmin, StoreManager |
| POST | /v1/finds-buys/{id}/allocations | Run or supersede the allocation waterfall | CategoryManager |
| GET | /v1/finds-buys/{id}/allocations | List allocations of a buy | CategoryManager, OperationsAdmin, StoreManager |
| POST | /v1/finds-buys/{id}/activate | Activate an ALLOCATED buy | CategoryManager |
| POST | /v1/finds-buys/{id}/close | Close an ON_SALE buy after week end | CategoryManager |
| GET | /v1/allocations/{id} | Fetch one allocation | CategoryManager, OperationsAdmin, StoreManager |
| POST | /v1/allocations/{id}/sell | Record a sale against an allocation | StoreManager |
| POST | /v1/allocations/{id}/clearance | Move unsold stock to clearance | StoreManager |
| GET | /v1/stores/{id}/finds-allocations | List allocations of a store | StoreManager, OperationsAdmin, CategoryManager |
| POST | /v1/stores/{id}/cart-coin-events | Append a cart coin event | Cashier, StoreManager |
| GET | /v1/stores/{id}/cart-coin-events | List cart coin events of a store | StoreManager, OperationsAdmin |
| GET | /v1/stores/{id}/cart-reconciliation | Coin reconciliation snapshot | StoreManager, OperationsAdmin |
| POST | /v1/stores/{id}/register-shifts | Open a register shift for a cashier | StoreManager |
| GET | /v1/stores/{id}/register-shifts | List register shifts of a store | StoreManager, OperationsAdmin |
| GET | /v1/register-shifts/{id} | Fetch one register shift | StoreManager, Cashier, OperationsAdmin |
| GET | /v1/employees/{id}/register-shifts | List shifts staffed by an employee | StoreManager, OperationsAdmin |
| POST | /v1/register-shifts/{id}/scan | Record a batch of scanned items | Cashier |
| POST | /v1/register-shifts/{id}/close | Close a shift and compute compliance | StoreManager |
| POST | /v1/stores/{id}/labor-windows | Book a staffing window | StoreManager |
| GET | /v1/stores/{id}/labor-windows | List labor windows of a store | StoreManager, OperationsAdmin |
| GET | /v1/labor-windows/{id} | Fetch one labor window | StoreManager, OperationsAdmin |
| POST | /v1/labor-windows/{id}/confirm | Confirm a PLANNED window | StoreManager |
| POST | /v1/labor-windows/{id}/cancel | Cancel a PLANNED or CONFIRMED window | StoreManager |
| POST | /v1/claims | File a quality-guarantee claim | CustomerServiceAgent |
| GET | /v1/claims | List claims, filterable | CustomerServiceAgent, StoreManager, OperationsAdmin |
| GET | /v1/claims/{id} | Fetch one claim | CustomerServiceAgent, StoreManager, OperationsAdmin |
| POST | /v1/claims/{id}/review | Move a claim under review | CustomerServiceAgent |
| POST | /v1/claims/{id}/approve | Approve a claim and price the refund | CustomerServiceAgent |
| POST | /v1/claims/{id}/reject | Reject a claim under review | CustomerServiceAgent |
| POST | /v1/claims/{id}/dispute | Send a claim into dispute | CustomerServiceAgent |
| POST | /v1/claims/{id}/pay | Pay out an approved claim | CustomerServiceAgent |
| POST | /v1/claims/{id}/rescind | Reverse an approved-but-unpaid claim | CustomerServiceAgent |
| POST | /_clock/set_current_utc | Set the server logical clock | OperationsAdmin |

---

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narrative of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_TENDER_NOT_OPEN | 409 |
| ERR_PANEL_INCOMPLETE | 409 |
| ERR_BLIND_VIOLATION | 422 |
| ERR_DUAL_SOURCE_REQUIRED | 409 |
| ERR_SKU_CAP_EXCEEDED | 409 |
| ERR_SKU_CAP_BELOW_CURRENT | 409 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_BARCODE_COUNT_INVALID | 422 |
| ERR_SHELF_READY_REQUIRED | 422 |
| ERR_BID_DUPLICATE | 409 |
| ERR_BID_CEILING_EXCEEDED | 422 |
| ERR_SUPPLIER_SUSPENDED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_FINDS_NO_REPLENISHMENT | 409 |
| ERR_ALLOCATION_INCOMPLETE | 409 |
| ERR_PRODUCT_NOT_ACTIVE | 409 |
| ERR_SALE_WINDOW_CONFLICT | 409 |
| ERR_CLEARANCE_GAP_VIOLATION | 409 |
| ERR_ALLOCATION_EXHAUSTED | 409 |
| ERR_SALE_WINDOW_INACTIVE | 409 |
| ERR_COIN_BALANCE_NEGATIVE | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_WINDOW_LIMIT_EXCEEDED | 409 |
| ERR_LABOR_BUDGET_EXCEEDED | 422 |
| ERR_CLAIM_WINDOW_EXPIRED | 422 |
| ERR_SHIFT_NOT_OPEN | 409 |
| ERR_CASHIER_ROLE_REQUIRED | 422 |
