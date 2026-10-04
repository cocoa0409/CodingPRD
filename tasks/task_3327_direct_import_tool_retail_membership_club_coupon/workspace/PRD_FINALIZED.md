# Direct Import Tool Retail API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a direct-import tool retailer's merchandising, logistics, and customer-facing operations. The business model is built on direct sourcing from overseas manufacturers, with a private brand portfolio tiered into `VALUE`, `MID`, and `PROFESSIONAL` lines, long ocean-freight replenishment lead times, and aggressive everyday price positioning held in check by a strict per-item margin floor.

The API covers the full commercial loop: catalog and purchase-order management by the purchasing organization; containerized freight movement from origin port to destination customs; allocation of inbound inventory to stores (including small-format secondary-market expansion stores with tightly capped assortments); club membership enrollment and renewal with savings-tracked tiered fees; a coupon cadence across print, email, and app channels with per-customer limits and promotional budget controls; point-of-sale with member pricing, store credit, and extended warranty plans; warranty claim adjudication; and product recall handling with safety holds that cascade into allocations and customs clearance.

A distinctive property of the domain is that time is never wall-clock. All time-gated rules — coupon redemption windows, return windows, membership expiry, and allocation ETAs — read a logical clock that the platform operator can set for testing. Before any clock call, the clock reads exactly 2026-09-01T00:00:00Z. Readers should assume every timestamp comparison in this document is against that logical clock unless stated otherwise.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting party and `X-User-Role` names their operational role. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, each endpoint enforces its authorized role set; an authenticated caller whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares nine roles, spelled exactly: `OpsAdmin`, `PurchasingManager`, `LogisticsCoordinator`, `ComplianceOfficer`, `InventoryPlanner`, `MarketingManager`, `StoreClerk`, `WarrantyAdjuster`, and `Customer`.

For eight of the nine roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: `OpsAdmin` (platform operator; clock control, store setup, read-mostly elsewhere), `PurchasingManager` (item catalog, pricing, purchase orders), `LogisticsCoordinator` (container booking and freight movement), `ComplianceOfficer` (customs decisions and product recalls), `InventoryPlanner` (store allocation of inbound inventory), `MarketingManager` (coupon campaigns and promotional cadence), `StoreClerk` (store associate; runs sales, returns, enrollments, warranty intake), and `WarrantyAdjuster` (extended warranty claim adjudication). For these roles the server may record the identifier but never compares it to an entity's `id`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's customer-reference field to `X-User-ID`. Customers perform self-service membership management, warranty claim filing, and claim appeals.

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

List endpoints accept two query parameters: `limit` specifies the maximum number of items returned (default 10, minimum 1, maximum 100) and `offset` specifies the number of items to skip (default 0). Unless otherwise specified, all list endpoints return resources sorted by `created_at` ascending. List responses include `limit`, `offset`, `total_count`, and `has_more` in the response envelope's `meta` object.

### 2.4. Common Resource Properties

Every primary resource carries four system-managed fields:

- `id` — a unique, server-minted UUID string with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that increments by 1 on every mutation, and is the field optimistic concurrency checks compare against.

Computed aggregates on a resource (for example, a container's `unallocated_quantities` map or a purchase order's `received_quantities`) are part of the resource; recomputing them is a mutation that refreshes `updated_at` and increments `version` exactly as an explicit edit would. All twelve top-level entity types — Item, PurchaseOrder, Container, Store, StoreAllocation, Customer, Membership, Coupon, Sale, SaleLine, WarrantyClaim, and Recall — carry the full common-field set, including nested SaleLine rows.

### 2.5. The Logical Clock and Lazy Expiry

The system never consults wall-clock time. All temporal evaluations read a logical clock whose initial value, before any clock-setting call, is exactly 2026-09-01T00:00:00Z. An `OpsAdmin` may advance or set the clock through an admin-only test-driving capability that accepts a `to_iso8601` parameter and reports the resulting `current_utc`. Setting the clock performs lazy expiry sweeps: a Membership whose `expires_at` lies in the past without renewal moves from `ACTIVE` to `LAPSED`, and a Coupon in `ACTIVE` or `PAUSED` whose `window_end` has been reached moves to `EXPIRED`. The same lazy evaluation also happens whenever the membership or coupon is accessed, so readers always observe the time-corrected status.

### 2.6. Referential Integrity and Nested Resource Retrieval

Path identifiers are validated in strict left-to-right order: the first identifier in the URL hierarchy that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and later identifiers are not even examined. Body-referenced identifiers — an `item_id` on a sale line, a `container_id` on an allocation, a `sale_line_id` on a warranty claim, and so on — must also refer to existing resources, with the same `ERR_NOT_FOUND` for a missing reference. Cross-reference rules that are stronger than mere existence (for example, that a container's lines must be a subset of its purchase order's lines) are validated separately and surface as `ERR_INVALID_REFERENCE` (HTTP 422), as detailed throughout §3.

### 2.7. Monetary Precision and Integer Arithmetic

All monetary amounts are integer cents unless a field is explicitly documented as a fraction or ratio. Percentage-style discount computations truncate (floor) to whole cents. The one field with fractional precision is `warranty_claim_rate`, which is expressed to exactly 4 decimal places using round-half-up. Landed-cost allocation math works in integer cents with floor division and, for the final variant, a millicent-scale remainder carry (see §3.2). Margin-floor comparisons are exact rational comparisons performed in hundred-thousandths of a cent so that no floating-point drift can flip a boundary decision; a price exactly at the floor is allowed.

### 2.8. Optimistic Concurrency Control

Exactly one write path carries an optimistic concurrency check: committing a store allocation. Such a request must include `expected_container_version`, a non-optional field carrying the client-observed `version` of the Container the allocation draws from. If the container's current `version` differs from `expected_container_version` — for example because another commit or decommit on the same container legitimately moved the shared unallocated pool forward — the commit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the container before retrying. No other endpoint accepts or requires a version field.

### 2.9. Validation Ordering

When a request could violate several rules, the server evaluates checks in a fixed priority order and reports the first failure:

1. Authentication — `X-User-ID` and `X-User-Role` present and the role declared (`ERR_UNAUTHENTICATED`).
2. Authorization — the role is permitted for the endpoint (`ERR_FORBIDDEN`).
3. Existence — path ids exist, checked left-to-right, and body-referenced ids exist (`ERR_NOT_FOUND`).
4. State — the target resource's state permits the attempted transition (`ERR_INVALID_STATE`).
5. Field-shape and domain constraints — required fields present, enums valid, quantities at least 1, `member_price_cents` not exceeding `unit_retail_cents`, `window_end` strictly after `window_start`, small-format assortment caps, warranty lines carrying a `covered_item_id` present on the same sale (`ERR_VALIDATION`).
6. Referential integrity — purchase-order line items exist, container lines are a subset of PO lines, an allocation's item is on the container, a warranty's covered item is another line's item on the same sale, the store's assortment contains the sale line items (`ERR_INVALID_REFERENCE`, or `ERR_ITEM_NOT_IN_STORE_ASSORTMENT` for the assortment case).
7. Recall safety gate (`ERR_SAFETY_HOLD`).
8. Item lifecycle gate — items must be `ACTIVE` where required (`ERR_ITEM_NOT_ACTIVE`).
9. Coupon time window (`ERR_COUPON_OUTSIDE_WINDOW`).
10. Coupon audience and per-customer limit (`ERR_COUPON_MEMBERS_ONLY`, `ERR_COUPON_CUSTOMER_LIMIT_REACHED`).
11. Margin floor (`ERR_MARGIN_FLOOR_VIOLATION`).
12. Coupon budget and store-credit sufficiency (`ERR_COUPON_BUDGET_EXCEEDED`, `ERR_INSUFFICIENT_STORE_CREDIT`, HTTP 402).
13. Return window (`ERR_RETURN_WINDOW_EXPIRED`).
14. Allocation pool and store dock capacity (`ERR_OVER_ALLOCATION`, `ERR_STORE_DOCK_CAPACITY_EXCEEDED`).
15. Stale container version on allocation commit (`ERR_STALE_VERSION`).

An earlier failure masks all later ones; for example, a commit on a container the caller may not touch surfaces as `ERR_FORBIDDEN` long before any over-allocation question is considered.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Items, Pricing, and the Margin Floor

A `PurchasingManager` introduces merchandise by creating an Item with a unique `sku`, a display `name`, a `brand_tier` drawn from `VALUE`, `MID`, or `PROFESSIONAL`, the `origin_country` of the overseas manufacturer, an everyday `unit_retail_cents` that must be greater than zero, a `member_price_cents` that must be greater than zero and must not exceed `unit_retail_cents`, a `floor_margin_pct` (the minimum allowed gross margin as a fraction, such as 0.15), an overseas replenishment `lead_time_days` of at least 1 day, and a positive `unit_weight_kg`. Duplicate SKU codes are rejected with `ERR_VALIDATION`. A newly created item starts with `lifecycle_status` in `DRAFT`, an `open_recall_count` of zero, a `warranty_claim_rate` of zero, and `current_landed_unit_cost_cents` null until the first receipt of a container carrying the item establishes a landed cost.

Activation by a `PurchasingManager` moves `lifecycle_status` from `DRAFT` to `ACTIVE`; only `ACTIVE` items may be placed on an issued purchase order, added to a sale line, or sold at completion — any of those operations attempted on a `QUARANTINED` or `DISCONTINUED` item is rejected with `ERR_ITEM_NOT_ACTIVE`. Discontinuation by a `PurchasingManager` moves an item from either `ACTIVE` or `QUARANTINED` to `DISCONTINUED`, which is terminal.

Pricing changes flow through a reprice action by a `PurchasingManager`, which may update `unit_retail_cents`, `member_price_cents`, or both. Repricing is gated by the margin-floor rule, which probes the retail price — the new `unit_retail_cents` when supplied, otherwise the current one — evaluated before any member-versus-retail adjustment: that retail price must not fall below the item's floor. The floor is computed against the item's `current_landed_unit_cost_cents` as that landed cost multiplied by one plus `floor_margin_pct`. A candidate price violates the floor only when the price scaled by one hundred thousand is strictly smaller than the floor value scaled by one hundred thousand and truncated to a whole number — an exact rational comparison, so a price landing precisely on the floor is allowed. When `current_landed_unit_cost_cents` is still null the check passes vacuously. A violating reprice is rejected with `ERR_MARGIN_FLOOR_VIOLATION`, and this floor check runs before the member-versus-retail consistency rule. The `member_price_cents` must not exceed `unit_retail_cents` invariant is enforced as follows: when both prices are supplied in one reprice and the new member price would exceed the new retail price, the reprice is rejected with `ERR_VALIDATION`; when only one side is supplied and the invariant would break, the unspecified side is adjusted to the supplied side's new value (a retail-only reprice below the current member price lowers the member price to the new retail price; a member-only reprice above the current retail price raises the retail price to the new member price), so a one-sided reprice never leaves member above retail. A successful reprice increments the item's `version`. The item listing supports filtering by `brand_tier` and `lifecycle_status`.

### 3.2. Import Pipeline: Purchase Orders, Landed Costs, and Containers

Purchasing assembles a PurchaseOrder with a unique `po_number`, at least one entry in `lines` (each naming an `item_id`, a `quantity` of at least 1, and a non-negative `unit_cost_cents`), and whole-PO cost estimates `estimated_duty_cents` and `estimated_freight_cents`, both at least zero. The `actual_duty_cents` and `actual_freight_cents` fields stay null until the first container receipt supplies them. A PO is created in `DRAFT`.

Issuing, a `PurchasingManager` action, moves the PO from `DRAFT` to `ISSUED` and computes `provisional_landed_costs` using the forward-looking variant of landed-cost allocation: first form each line's goods value as its `quantity` multiplied by its `unit_cost_cents`, then form the goods total as the sum of those goods values across all lines, then form the cost pool as `estimated_duty_cents` plus `estimated_freight_cents`. For each line, in the order the lines appear in the PO, the provisional landed unit cost is the line's `unit_cost_cents` plus the pool multiplied by that line's goods value, divided by the goods total, then divided by the line's quantity — each division truncating to whole cents with no remainder redistribution. Issuing requires the PO to carry at least one line and every line item to be `ACTIVE` at issue time, otherwise `ERR_ITEM_NOT_ACTIVE`; the PO's `version` increments on issue. A `PurchasingManager` may cancel a PO from `DRAFT` without conditions, or from `ISSUED` provided no container of the PO has reached `DEPARTED`, `AT_PORT`, `CUSTOMS_HOLD`, `CLEARED`, or `RECEIVED` — a PO with shipped containers is rejected with `ERR_PO_HAS_SHIPPED_CONTAINERS`. Cancelling an issued PO moves all its `BOOKED` containers to `CANCELLED` and releases every StoreAllocation on those containers to `RELEASED` with a full release of their quantities.

Once a PO is `ISSUED` or `PARTIALLY_RECEIVED`, a `LogisticsCoordinator` books a Container against it with a unique `container_number` and `lines` whose every item already appears on the PO (a container line item not on the PO is rejected with `ERR_INVALID_REFERENCE`), each line quantity at least 1. The container's `unallocated_quantities` map initially equals its line quantities and shrinks as allocations commit units against it. Freight then advances through `BOOKED` → `DEPARTED` (a `LogisticsCoordinator` marks departure from the origin port) → `AT_PORT` (arrival at destination port). Customs handling belongs to the `ComplianceOfficer`: a container at `AT_PORT` may be placed on `CUSTOMS_HOLD` and later released back to `AT_PORT` — that hold/release cycle may repeat, each pair counting as a full cycle. Clearance moves a container from `AT_PORT` to `CLEARED`, but clearance is blocked with `ERR_CONTAINER_QUARANTINE_BLOCK` while the container holds any line item whose `lifecycle_status` is `QUARANTINED` under an `ACTIVE` recall of severity `HAZARD`. This quarantine guard covers containers sitting at `AT_PORT` or `CUSTOMS_HOLD` and is evaluated before the `AT_PORT` state gate, so a `CUSTOMS_HOLD` container holding such an item is rejected with `ERR_CONTAINER_QUARANTINE_BLOCK` rather than a state error.

Receipt at the distribution center — a `LogisticsCoordinator` action moving the container from `CLEARED` to `RECEIVED` — is the most consequential operation in the pipeline. The checks evaluate in this order: first, if this is the PO's first receipt, the payload must supply `actual_duty_cents` and `actual_freight_cents` (both at least zero), otherwise `ERR_PO_ACTUAL_COSTS_REQUIRED`; then the store dock capacity rule described in §3.3 runs per store with `COMMITTED` allocations on this container, and a breach rejects the entire receive with `ERR_STORE_DOCK_CAPACITY_EXCEEDED`. On success, a three-stage cascade fires. First, the PO recomputes `final_landed_costs` and `received_quantities`, and transitions automatically: `ISSUED` → `PARTIALLY_RECEIVED` when quantity remains unreceived, or directly to `RECEIVED` when a single receipt completes all quantities; a `PARTIALLY_RECEIVED` PO transitions to `RECEIVED` when `received_quantities` equal the PO line quantities for every item, recomputing final costs in a full chronological sweep. The final variant of landed-cost allocation uses the actual pool (`actual_duty_cents` plus `actual_freight_cents`) and a chronological remainder redistribution over the PO's lines in line order: maintain a running remainder starting at zero; for each line, compute its exact share in millicents as the pool multiplied by the line's goods value multiplied by one thousand, divided by the goods total; take the whole-cent share as that millicent figure floored to cents; add the leftover millicents into the running remainder; whenever the running remainder reaches at least one thousand millicents, add one cent to the line's share and subtract one thousand from the remainder; the line's final landed unit cost is its `unit_cost_cents` plus its share divided by its `quantity`, truncated. Earlier lines absorb the rounding pennies first. The provisional and final variants must produce different results whenever the estimated and actual pools differ, and may differ per line even with equal pools because of the remainder carry. Second, every line item's `current_landed_unit_cost_cents` updates to the new final landed cost and each touched item's `version` increments. Third, each updated item's margin floor is rechecked against its current pricing as a flag-only recheck that never blocks the receipt. Finally, all `COMMITTED` allocations on the container are delivered to their stores.

A `LogisticsCoordinator` may cancel a container while it is `BOOKED`; cancellation moves it to `CANCELLED` and releases all of its allocations to `RELEASED`, returning their quantities to the unallocated pool. Container listings support filtering by `status` and `po_id`; purchase-order listings support filtering by `status`.

### 3.3. Stores, Assortment Caps, and the Allocation Pool

An `OpsAdmin` opens a Store with a unique `store_code`, a `name`, a `format` of `SMALL_FORMAT` or `STANDARD`, a `market_tier` of `PRIMARY` or `SECONDARY`, a dock `receiving_capacity_units` of at least 1 unit per calendar day, and an `assortment_item_ids` list naming the items the store carries. Secondary-market expansion leans on the small format: a `SMALL_FORMAT` store's assortment may contain at most 8 entries (duplicates counted); exceeding that cap is rejected with `ERR_VALIDATION`. Store listings filter by `format` and `market_tier`.

An `InventoryPlanner` steers inbound inventory to stores through StoreAllocation rows created in `PLANNED`, naming a `container_id`, an `item_id` that must be one of that container's line items (otherwise `ERR_INVALID_REFERENCE`), and a `quantity` of at least 1. At creation the system stamps `eta_date`: while the container is `BOOKED` or `DEPARTED`, the expected store-delivery date is the current logical-clock date plus the item's `lead_time_days`; once the container has reached `AT_PORT`, `CUSTOMS_HOLD`, or `CLEARED`, the ETA is the current logical-clock date plus 7 days of inland transfer — long replenishment lead times dominate until the container reaches port.

Committing a `PLANNED` allocation reserves pool units. The commit payload carries `expected_container_version` per §2.8. Two preconditions then guard the commit, and the container-state check comes first: the container must be `BOOKED` or `DEPARTED`, otherwise `ERR_CONTAINER_NOT_ALLOCATABLE`; and the allocation's `quantity` must not exceed the container's `unallocated_quantities` entry for the item, otherwise `ERR_OVER_ALLOCATION`. A successful commit moves the allocation to `COMMITTED`, decrements the container's `unallocated_quantities` entry by the committed quantity, and increments the container's `version` — which is exactly why a second planner holding an older view of the pool must re-read before committing. Decommitting moves an allocation from `COMMITTED` back to `PLANNED`, returns its quantity to the pool, and increments the container's `version`; the `PLANNED` ↔ `COMMITTED` cycle may repeat. Releasing an allocation moves it to `RELEASED`: from `PLANNED` nothing returns to the pool, while from `COMMITTED` the quantity returns to `unallocated_quantities`. `RELEASED` and `BLOCKED` are terminal.

Recall activations intrude on this pool automatically: when a recall on an allocation's item reaches `ACTIVE` with severity `STOP_SALE` or `HAZARD`, non-terminal allocations of that item move to `BLOCKED`; a `COMMITTED` allocation that is blocked this way returns its committed quantity to the container's unallocated pool. Allocation listings exist both per-store and globally, filterable by `status`, `store_id`, `container_id`, and `item_id`.

Store dock capacity is enforced at container receipt. For each store with `COMMITTED` allocations on the receiving container, the system sums the quantities already delivered to that store on the same logical-clock date by containers received earlier that day; if that delivered-today total plus this container's committed quantity to the store exceeds the store's `receiving_capacity_units`, the entire receive is rejected with `ERR_STORE_DOCK_CAPACITY_EXCEEDED`. The comparison is strict — a total landing exactly on capacity is allowed.
### 3.4. Customers and the Membership Club

A customer record is created with a unique `email` (duplicates rejected with `ERR_VALIDATION`) and a `full_name`, either by a `StoreClerk` or `OpsAdmin` on the customer's behalf or by the customer self-registering. Each Customer carries a `store_credit_cents` balance that starts at zero, is credited by returns and warranty settlements, is debited when applied to sales, and is never allowed to go negative.

Club enrollment — by a `StoreClerk` or the customer — creates at most one Membership per customer; a second enrollment attempt is rejected with `ERR_MEMBERSHIP_EXISTS`. The enrollment payload chooses a `tier` of `CLUB` or `CLUB_PLUS`. A membership is born `ACTIVE` with `started_at` set to the current logical time and `expires_at` set 365 days later. While `ACTIVE`, or within 30 days after expiry, the member's `return_window_days` is 90; otherwise the extended window does not apply. The club also tracks two savings ledgers on the membership: `settled_savings_cents` — the ledger of record — and `optimistic_savings_cents`, a marketing projection; both start at zero, and `renewal_fee_cents` records the fee charged at the most recent enrollment or renewal.

The enrollment fee, and every renewal fee, is tiered off the member's settled savings at that moment (zero for a brand-new enrollment). For the `CLUB` tier: settled savings of at least 20000 cents bring the fee down to 1999 cents; at least 5000 cents but below 20000 bring it to 2999 cents; below 5000 cents the full 3999 cents applies. The boundaries are inclusive — savings exactly at 5000 cents earn the 2999-cent fee. `CLUB_PLUS` charges a flat 6999 cents with no savings tiers.

Time wears on memberships lazily. When the logical clock passes `expires_at` without renewal, the membership moves from `ACTIVE` to `LAPSED`, evaluated lazily on any membership access and on the clock sweep. Lapsing does not reprice any existing `OPEN` sale lines, but member pricing no longer applies to that customer's open sales from that point on. Renewal is performed by a `StoreClerk` or the customer in two shapes: early renewal while still `ACTIVE`, or renewal from `LAPSED` within the grace window. A lapsed renewal is rejected with `ERR_RENEWAL_WINDOW_CLOSED` once the current logical time has reached 30 days past `expires_at`; the grace boundary is strict, so renewal at exactly 30 days after expiry is already closed. Either renewal shape sets `expires_at` to the later of the existing `expires_at` and the current logical time, plus 365 days, recomputes `renewal_fee_cents` per the tiered fee rule, and returns the membership to `ACTIVE`; the `ACTIVE` → `LAPSED` → `ACTIVE` cycle may repeat. Cancellation, by a `StoreClerk` or the customer, moves a membership from `ACTIVE` to `CANCELLED` with no fee refund; benefits end immediately and `CANCELLED` is terminal.

### 3.5. Coupon Campaigns and the Promotional Cadence

A `MarketingManager` authors a Coupon with a `code` (unique case-insensitively; duplicates rejected with `ERR_VALIDATION`), a distribution `channel` of `PRINT`, `EMAIL`, or `APP`, an `audience` of `ALL` or `MEMBERS_ONLY`, a `discount_type` of `PERCENT_OFF_ITEM`, `AMOUNT_OFF_ITEM`, `PERCENT_OFF_BASKET`, or `FIXED_AMOUNT_OFF_BASKET`, and a `discount_value` whose interpretation depends on the type: a percentage strictly between 0 and 100 for the `PERCENT_` types, or a positive cent amount for the `AMOUNT_` and `FIXED_` types. The campaign also carries `min_basket_cents` (the minimum post-member-price basket subtotal required to redeem, where 0 means no minimum and which defaults to 0 when omitted), `max_discount_cents` (an optional cap on the computed discount, where null means uncapped), a `per_customer_limit` of at least 1, a promotional `budget_cents` of at least 1, a redemption window from `window_start` (inclusive) to `window_end` (exclusive, and required to be strictly after `window_start`), and an optional `member_early_start` which, when set, must be at or before `window_start` and opens redemption to members early. Coupons track `budget_spent_cents`, `budget_reserved_cents`, and `usage_records` — a per-customer redemption count map used to enforce `per_customer_limit` — all starting at zero. A coupon is created in `DRAFT`.

Activation by a `MarketingManager` moves a coupon from `DRAFT` to `ACTIVE`, and may also resume a `PAUSED` coupon back to `ACTIVE`; activation is allowed at any time regardless of the redemption window — redemption itself stays time-gated. Pausing moves an `ACTIVE` coupon to `PAUSED`, and the `ACTIVE` ↔ `PAUSED` cycle may repeat. The clock moves a coupon from `ACTIVE` or `PAUSED` to `EXPIRED` once the logical time reaches `window_end`, evaluated lazily. Finally, when a sale completion pushes `budget_spent_cents` to at least `budget_cents`, the coupon moves from `ACTIVE` to `EXHAUSTED` and accepts no further redemptions, which surface as `ERR_COUPON_EXHAUSTED`.

### 3.6. Point of Sale: Lines, Member Pricing, and Extended Warranties

A `StoreClerk` opens a Sale by naming the `store_id` and `customer_id`; the sale starts `OPEN` with `coupon_discount_cents` and `store_credit_applied_cents` at zero, `completed_at` null, and an empty `returned_line_quantities` map.

Lines are added to an `OPEN` sale with an `item_id` and a `quantity` of at least 1. Two line shapes exist. A merchandise line resolves its `unit_price_cents` by member-price resolution: if the customer is an effective member at the current logical time — meaning the customer holds a Membership whose status is `ACTIVE` or `LAPSED` and the current time is at or before `expires_at` plus 30 days of grace (a `CANCELLED` membership never qualifies) — the unit price is the lower of the item's `member_price_cents` and `unit_retail_cents`; otherwise it is `unit_retail_cents`. An extended warranty line sets `is_warranty_line` to true, carries a `warranty_price_cents` greater than zero, and must name a `covered_item_id` that is the item of another line on the same sale — a covered item not present as a merchandise line on the sale is rejected with `ERR_INVALID_REFERENCE`, and a warranty line missing either `covered_item_id` or `warranty_price_cents` is rejected with `ERR_VALIDATION`. Warranty lines are excluded from coupon discounts and from member savings. Each line's `line_total_cents` is its `unit_price_cents` multiplied by `quantity` (for warranty lines, `warranty_price_cents` multiplied by `quantity`), and the sale's `subtotal_cents` is the sum of per-line totals before any coupon. Prices resolve when the line is added and re-resolve at completion; the completion-time value wins.

### 3.7. Coupon Redemption, Completion, and Settlement

A `StoreClerk` applies a coupon to an `OPEN` sale by presenting the `coupon_code`. A sale carries at most one coupon: if `applied_coupon_id` is already set, a second application is rejected with `ERR_COUPON_ALREADY_APPLIED`. Otherwise the redemption gate runs as an ordered sequence — the first failure wins:

1. An `EXHAUSTED` coupon is rejected with `ERR_COUPON_EXHAUSTED`.
2. The time window: when the customer is an effective member now and the coupon has `member_early_start` set, redemption is valid from `member_early_start`; otherwise it is valid from `window_start`; either way, redemption at or after `window_end` is invalid — the start is inclusive and the end is exclusive. A violation is rejected with `ERR_COUPON_OUTSIDE_WINDOW`. The window check runs before the not-`ACTIVE` status check: a coupon whose `window_end` has passed (which lazy expiry would show as `EXPIRED`) reports `ERR_COUPON_OUTSIDE_WINDOW`.
3. Coupon status must otherwise be `ACTIVE`; a coupon in `DRAFT` or `PAUSED` (or `EXPIRED` not already caught by the window check) is rejected with `ERR_COUPON_NOT_ACTIVE`.
4. Audience: a `MEMBERS_ONLY` coupon requires the redeeming customer to be an effective member now, otherwise `ERR_COUPON_MEMBERS_ONLY`.
5. Per-customer limit: the customer's `usage_records` count for the coupon must be below `per_customer_limit`; a count equal to the limit rejects with `ERR_COUPON_CUSTOMER_LIMIT_REACHED`. Channel cadence refines what the count means: for `PRINT` coupons the limit applies per calendar day of redemption (the count resets daily), while for `EMAIL` and `APP` coupons it applies across the coupon's entire life.
6. Budget: the coupon's computed discount for this sale plus `budget_spent_cents` plus `budget_reserved_cents` must be at most `budget_cents`; equality is allowed. When the gate re-runs at completion on a sale that already holds a reservation from its own earlier application, that sale's existing reservation is excluded from `budget_reserved_cents` for this check, so the sale's own discount is not double-counted. A breach is rejected with `ERR_COUPON_BUDGET_EXCEEDED`.

The discount itself is computed from the non-warranty lines only. Let the basket B be the sum of `line_total_cents` over non-warranty lines, using the per-line rounded prices. The eligible base E depends on `discount_type`: for `PERCENT_OFF_ITEM` and `AMOUNT_OFF_ITEM`, E is the `line_total_cents` of the single line whose item has the lowest per-line `unit_price_cents`, breaking ties toward the line created earliest; for `PERCENT_OFF_BASKET` and `FIXED_AMOUNT_OFF_BASKET`, E is the whole basket B. The raw discount is, for the percent types, E multiplied by `discount_value` and divided by 100, truncated to whole cents; for the amount types, the smaller of `discount_value` and E. If `max_discount_cents` is set, the final discount is the smaller of the raw discount and the cap; otherwise it is the raw discount. When B is below `min_basket_cents`, redemption fails with `ERR_COUPON_MIN_BASKET_NOT_MET`. The evaluation order is pinned: B is computed from per-line totals first; the discount is computed from B second; the sale total is computed third. The discount never feeds back into B, even though B's own eligibility gate references B. Applying a coupon computes the discount, records it in `coupon_discount_cents`, and adds the discount to the coupon's `budget_reserved_cents` as a reservation.

Completion is the settlement point. Completing an `OPEN` sale requires: at least one line, otherwise `ERR_EMPTY_SALE`; the store's `assortment_item_ids` to carry every line item, otherwise `ERR_ITEM_NOT_IN_STORE_ASSORTMENT`; the redemption gate to pass again when `applied_coupon_id` is set; no line item to sit under an `ACTIVE` recall of severity `STOP_SALE` or `HAZARD`, otherwise `ERR_SAFETY_HOLD` — the recall safety gate is evaluated before the item lifecycle gate at completion, so a quarantined item under an active recall surfaces `ERR_SAFETY_HOLD` rather than `ERR_ITEM_NOT_ACTIVE`; every line item to be `ACTIVE`, otherwise `ERR_ITEM_NOT_ACTIVE`; every non-warranty line's `unit_price_cents` to pass the margin-floor check, otherwise `ERR_MARGIN_FLOOR_VIOLATION`; and, when the payload requests `store_credit_applied_cents`, that amount to be at most the customer's `store_credit_cents` balance, otherwise `ERR_INSUFFICIENT_STORE_CREDIT`. On success the sale moves to `COMPLETED`, `completed_at` is stamped with the current logical time, `total_cents` becomes `subtotal_cents` minus `coupon_discount_cents` minus `store_credit_applied_cents`, the coupon reservation settles (`budget_reserved_cents` shrinks by the discount while `budget_spent_cents` grows by it, and a spent total reaching the budget pushes the coupon to `EXHAUSTED`), the customer's `usage_records` count for the coupon increments by one, the membership savings ledgers recompute in their settled variant, and the customer's `store_credit_cents` decreases by the applied credit.

Voiding an `OPEN` sale moves it to `VOID`; when a coupon had been applied, its reservation is released (`budget_reserved_cents` shrinks by the discount) while `applied_coupon_id` is retained for audit. `VOID` is terminal.

The membership savings ledgers update on completion and on returns, and are also recomputed lazily whenever the membership is read, so the optimistic variant reflects `OPEN` sales created since the last settlement. The settled variant sums, over the member's `COMPLETED` and `RETURNED_PARTIAL` sales and per non-warranty line, the difference between the item's `unit_retail_cents` and the line's `unit_price_cents` multiplied by the not-yet-returned quantity, counting only lines where the retail price exceeds the price paid — that is, where the member actually saved. The optimistic variant is the settled figure plus projected savings on the member's `OPEN` sales computed as though member pricing will apply, even if the membership lapses before those sales complete. The two variants diverge whenever open sales exist; the settled figure is the ledger of record and the optimistic figure is the projection view.

### 3.8. Returns and Store Credit

Returns are processed by a `StoreClerk` against a `COMPLETED` or `RETURNED_PARTIAL` sale, naming a `sale_line_id` and a `quantity` to return. Two preconditions guard the return. The return window runs from `completed_at` against the logical clock: 90 days when the customer is an effective member now, otherwise 30 days; a return past its window is rejected with `ERR_RETURN_WINDOW_EXPIRED`. However, when any returned line's item sits under an `ACTIVE` recall of severity `HAZARD`, the refund is always allowed regardless of the window — a safety override. The cumulative returned quantity per line, tracked in `returned_line_quantities`, must never exceed the line's quantity, otherwise `ERR_RETURN_QUANTITY_EXCEEDED`.

The refund for returning q units of a line starts as the line's `unit_price_cents` multiplied by q. If the sale had an applied coupon and the returned line was the coupon's eligible line under the eligible-line rule of §3.7, a proportional clawback applies: the sale's `coupon_discount_cents` multiplied by q and divided by the line's quantity as it stood at coupon application, truncated to whole cents, subtracted from the line refund but never below zero. The refund is credited to the customer's `store_credit_cents` — store credit only, never cash. When returned lines had contributed to membership savings, `settled_savings_cents` is reduced accordingly, upholding the invariant that settled savings and refunds never double-count. Returning some but not all units moves a `COMPLETED` sale to `RETURNED_PARTIAL`; further returns on a `RETURNED_PARTIAL` sale keep it there; returning the remaining units moves it to `RETURNED_FULL`, which is terminal. A full return does not decrement the coupon's `usage_records` count — the coupon stays consumed.

### 3.9. Warranty Claims and Adjudication

A warranty claim is filed — by the customer or a `StoreClerk` — against a `sale_line_id` that must be a warranty line on a `COMPLETED` or `RETURNED_PARTIAL` sale, with a free-text `reason` and a `claim_amount_cents` greater than zero. The claim starts in `FILED`, and filing already feeds the covered item's `warranty_claim_rate`.

A `WarrantyAdjuster` then drives adjudication: `FILED` → `UNDER_REVIEW` via start-review, then `UNDER_REVIEW` → `APPROVED` via approve or `UNDER_REVIEW` → `DENIED` via deny. A denied claim may be appealed by the customer back to `UNDER_REVIEW`, but only within two limits: `appeal_count` must still be below 1 — appealing a claim that has already been appealed once is rejected with `ERR_CLAIM_APPEAL_EXHAUSTED` — and `claim_amount_cents` must be at most 100000 cents, because claims above 1000 dollars are final on first denial, rejected with `ERR_CLAIM_FINAL`. A successful appeal increments `appeal_count`; the `UNDER_REVIEW` → `DENIED` → `UNDER_REVIEW` cycle is allowed exactly once. Settling an `APPROVED` claim — a `WarrantyAdjuster` action supplying `settled_amount_cents` — requires the settlement not to exceed `claim_amount_cents`, otherwise `ERR_SETTLEMENT_EXCEEDS_CLAIM`; on success the claim moves to `SETTLED`, the settled amount is credited to the customer's `store_credit_cents`, and the item's `warranty_claim_rate` recomputes. `DENIED` and `SETTLED` are terminal.

The `warranty_claim_rate` on an item is its claim-exposure ratio: the numerator counts WarrantyClaim rows whose sale line's covered item is this item and whose status is `FILED`, `UNDER_REVIEW`, `APPROVED`, or `SETTLED`; the denominator counts non-warranty SaleLine rows of this item on sales in `COMPLETED` or `RETURNED_PARTIAL` — warranty lines reference the covered item but are not its merchandise rows and never count. The rate is the numerator divided by the denominator, or zero when the denominator is zero, expressed to 4 decimal places rounded half-up. The rate recomputes on every claim write path — filing, start-review, approve, deny, appeal, and settle — not only on filing and settlement.

### 3.10. Recalls and Safety Compliance

A `ComplianceOfficer` opens a Recall against an `item_id` with a `severity` of `NOTICE`, `STOP_SALE`, or `HAZARD` and a free-text `reason` describing the safety compliance concern; the recall starts in `DRAFT`. Activating the recall fires a three-stage cascade. First, the item's `lifecycle_status` moves from `ACTIVE` to `QUARANTINED`, its `open_recall_count` increments by one, and its `version` increments. Second — for `STOP_SALE` or `HAZARD` severities only — every non-terminal StoreAllocation for the item moves to `BLOCKED`, committed quantities return to their containers' `unallocated_quantities`, and each affected container's `version` increments. Third, containers sitting at `AT_PORT` or `CUSTOMS_HOLD` that hold the item cannot clear customs until the recall closes — the guard described in §3.2 on the `AT_PORT` → `CLEARED` transition. The `ACTIVE` ↔ `QUARANTINED` item cycle may repeat as recalls activate and close. Closing an `ACTIVE` recall decrements the item's `open_recall_count`; when the count reaches zero and the item is `QUARANTINED`, the item returns to `ACTIVE` automatically. `CLOSED` is terminal. Recall listings filter by `status`, `item_id`, and `severity`; sale listings filter by `store_id`, `customer_id`, and `status`; sale-line listings filter by `sale_id` and `item_id`; warranty-claim listings filter by `status` and `sale_line_id`.

## 4. Endpoint Definitions

All endpoints are mounted at the API root (no global prefix). Endpoints that create a new resource respond with `201 Created`; all other successful operations — reads, state transitions, and modifications — respond with `200 OK`. Request payloads, response shapes, and side effects for each endpoint are specified by the narratives of §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock (lazy expiry sweeps) | OpsAdmin |
| POST | /items | Create a catalog item (DRAFT) | PurchasingManager |
| GET | /items | List items | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner, MarketingManager, StoreClerk, WarrantyAdjuster, Customer |
| GET | /items/{itemId} | Get an item | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner, MarketingManager, StoreClerk, WarrantyAdjuster, Customer |
| POST | /items/{itemId}/activate | Activate an item for sale | PurchasingManager |
| POST | /items/{itemId}/reprice | Change retail/member price (margin-floor gated) | PurchasingManager |
| POST | /items/{itemId}/discontinue | Discontinue an item | PurchasingManager |
| POST | /purchase-orders | Create a purchase order (DRAFT) | PurchasingManager |
| GET | /purchase-orders | List purchase orders | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner |
| GET | /purchase-orders/{poId} | Get a purchase order | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner |
| POST | /purchase-orders/{poId}/issue | Issue PO to the overseas manufacturer | PurchasingManager |
| POST | /purchase-orders/{poId}/cancel | Cancel a purchase order | PurchasingManager |
| POST | /containers | Book a container against an ISSUED/PARTIALLY_RECEIVED PO | LogisticsCoordinator |
| GET | /containers | List containers | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner |
| GET | /containers/{containerId} | Get a container | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner |
| POST | /containers/{containerId}/depart | Mark container departed origin port | LogisticsCoordinator |
| POST | /containers/{containerId}/arrive-port | Mark container arrived at destination port | LogisticsCoordinator |
| POST | /containers/{containerId}/hold-customs | Place container on customs hold | ComplianceOfficer |
| POST | /containers/{containerId}/release-customs | Release container from customs hold | ComplianceOfficer |
| POST | /containers/{containerId}/clear-customs | Clear customs (blocked by HAZARD recall on held items) | ComplianceOfficer |
| POST | /containers/{containerId}/receive | Receive container at DC (first receipt carries actual duty/freight) | LogisticsCoordinator |
| POST | /containers/{containerId}/cancel | Cancel a BOOKED container | LogisticsCoordinator |
| POST | /stores | Open a store | OpsAdmin |
| GET | /stores | List stores | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner, StoreClerk |
| GET | /stores/{storeId} | Get a store | OpsAdmin, PurchasingManager, LogisticsCoordinator, ComplianceOfficer, InventoryPlanner, StoreClerk |
| POST | /stores/{storeId}/allocations | Create a store allocation from a container line (PLANNED) | InventoryPlanner |
| GET | /stores/{storeId}/allocations | List allocations for a store | OpsAdmin, InventoryPlanner, LogisticsCoordinator, StoreClerk |
| GET | /store-allocations | List allocations filtered by store/container/item | OpsAdmin, InventoryPlanner, LogisticsCoordinator, StoreClerk |
| GET | /store-allocations/{allocationId} | Get an allocation | OpsAdmin, InventoryPlanner, LogisticsCoordinator, StoreClerk |
| POST | /store-allocations/{allocationId}/commit | Commit a PLANNED allocation (OCC-guarded on Container version) | InventoryPlanner |
| POST | /store-allocations/{allocationId}/decommit | Decommit back to PLANNED, returning units to pool | InventoryPlanner |
| POST | /store-allocations/{allocationId}/release | Release an allocation | InventoryPlanner |
| POST | /customers | Register a customer | StoreClerk, Customer, OpsAdmin |
| GET | /customers/{customerId} | Get a customer | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin |
| POST | /customers/{id}/membership | Enroll customer in the club (one membership per customer) | StoreClerk, Customer |
| GET | /customers/{id}/membership | Get the customer's membership | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin |
| GET | /memberships/{membershipId} | Get a membership (includes settled and optimistic savings) | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin, MarketingManager |
| POST | /memberships/{membershipId}/renew | Renew (early while ACTIVE, or within 30-day grace while LAPSED) | StoreClerk, Customer |
| POST | /memberships/{membershipId}/cancel | Cancel membership | StoreClerk, Customer |
| POST | /coupons | Create a coupon campaign (DRAFT) | MarketingManager |
| GET | /coupons | List coupons | OpsAdmin, MarketingManager, StoreClerk |
| GET | /coupons/{couponId} | Get a coupon | OpsAdmin, MarketingManager, StoreClerk |
| POST | /coupons/{couponId}/activate | Activate (or resume from PAUSED) | MarketingManager |
| POST | /coupons/{couponId}/pause | Pause an active campaign | MarketingManager |
| POST | /sales | Open a sale at a store for a customer | StoreClerk |
| GET | /sales/{saleId} | Get a sale | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin |
| GET | /sales | List sales | StoreClerk, OpsAdmin, WarrantyAdjuster |
| POST | /sales/{saleId}/lines | Add a line (merchandise or extended warranty plan) | StoreClerk |
| GET | /sales/{id}/lines | List sale lines | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin |
| GET | /sale-lines/{lineId} | Get a sale line | StoreClerk, Customer, WarrantyAdjuster, OpsAdmin |
| GET | /sale-lines | List sale lines filtered by sale or item | StoreClerk, WarrantyAdjuster, OpsAdmin |
| POST | /sales/{saleId}/apply-coupon | Apply a coupon to an OPEN sale (at most one per sale) | StoreClerk |
| POST | /sales/{saleId}/complete | Complete the sale | StoreClerk |
| POST | /sales/{saleId}/void | Void an OPEN sale | StoreClerk |
| POST | /sales/{saleId}/returns | Return units of a line | StoreClerk |
| POST | /warranty-claims | File a claim against a warranty line | Customer, StoreClerk |
| GET | /warranty-claims | List claims | WarrantyAdjuster, OpsAdmin, StoreClerk |
| GET | /warranty-claims/{claimId} | Get a claim | WarrantyAdjuster, OpsAdmin, StoreClerk, Customer |
| POST | /warranty-claims/{claimId}/start-review | Begin review | WarrantyAdjuster |
| POST | /warranty-claims/{claimId}/approve | Approve a claim | WarrantyAdjuster |
| POST | /warranty-claims/{claimId}/deny | Deny a claim | WarrantyAdjuster |
| POST | /warranty-claims/{claimId}/appeal | Customer appeals a denial (max 1; claims over 1000 dollars final on first denial) | Customer |
| POST | /warranty-claims/{claimId}/settle | Settle an approved claim to store credit | WarrantyAdjuster |
| POST | /recalls | Open a recall record (DRAFT) | ComplianceOfficer |
| GET | /recalls | List recalls | OpsAdmin, ComplianceOfficer, PurchasingManager, StoreClerk |
| GET | /recalls/{recallId} | Get a recall | OpsAdmin, ComplianceOfficer, PurchasingManager, StoreClerk |
| POST | /recalls/{recallId}/activate | Activate recall (quarantines item, blocks allocations, holds customs) | ComplianceOfficer |
| POST | /recalls/{recallId}/close | Close an active recall | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the canonical id-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ITEM_NOT_ACTIVE | 409 |
| ERR_SAFETY_HOLD | 409 |
| ERR_CONTAINER_QUARANTINE_BLOCK | 409 |
| ERR_PO_HAS_SHIPPED_CONTAINERS | 409 |
| ERR_PO_ACTUAL_COSTS_REQUIRED | 422 |
| ERR_OVER_ALLOCATION | 409 |
| ERR_CONTAINER_NOT_ALLOCATABLE | 409 |
| ERR_STORE_DOCK_CAPACITY_EXCEEDED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_MARGIN_FLOOR_VIOLATION | 422 |
| ERR_EMPTY_SALE | 422 |
| ERR_ITEM_NOT_IN_STORE_ASSORTMENT | 422 |
| ERR_COUPON_NOT_ACTIVE | 409 |
| ERR_COUPON_EXHAUSTED | 409 |
| ERR_COUPON_OUTSIDE_WINDOW | 422 |
| ERR_COUPON_MEMBERS_ONLY | 422 |
| ERR_COUPON_CUSTOMER_LIMIT_REACHED | 422 |
| ERR_COUPON_MIN_BASKET_NOT_MET | 422 |
| ERR_COUPON_BUDGET_EXCEEDED | 402 |
| ERR_COUPON_ALREADY_APPLIED | 409 |
| ERR_INSUFFICIENT_STORE_CREDIT | 402 |
| ERR_RETURN_WINDOW_EXPIRED | 422 |
| ERR_RETURN_QUANTITY_EXCEEDED | 422 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_MEMBERSHIP_EXISTS | 409 |
| ERR_CLAIM_APPEAL_EXHAUSTED | 409 |
| ERR_CLAIM_FINAL | 409 |
| ERR_SETTLEMENT_EXCEEDS_CLAIM | 422 |
