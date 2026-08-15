# Protein Trading Desk API — Product Requirements Document

## 1. Introduction

A protein trading desk lives between the packing plant and the retail meat case. It books carcasses and primals against supplier establishments, takes scale weight at the receiving dock, holds product in chillers and freezers while it ages, breaks selected carcasses into primals and subprimals under yield specifications, and sells the position twice over — forward, through fixed-price contracts with committed tonnage, and spot, through a weekly price sheet that allocates scarce supply across ranked customers. This document specifies the API that operates that desk end to end: procurement, cold storage, fabrication, pricing, allocation, load-out, and settlement.

The desk's economics depend on a handful of computations that must be reproduced exactly. A purchase is valued twice — once at booking against the current market sheet, once at grading against the sheet that governed the grading week — using a cutout model that rounds per product line before summing. Every lot in storage carries a market value that decays with age and flexes with USDA grade. Every customer carries a live credit exposure that can force an automatic credit hold in the middle of an allocation run. Shipments accumulate a temperature-compliance verdict that is sticky once breached, and claims negotiated against those shipments settle under a liability cap with a conditional freight allowance. Finally, the desk's net hedging exposure per product-week nets physical stock, inbound purchases, forward commitments, and spot allocations into a single number that risk officers watch.

Seven roles operate the API under strict segregation of duties: traders write contracts and sheets, risk officers run allocations and cancel contracts, warehouse operators receive, fabricate, and ship, quality graders inspect and certify, claims adjusters settle, customer representatives act on behalf of a single customer house, and desk administrators govern reference data and the market calendar. All endpoints are mounted under the `/api` prefix. Time inside the system is a logical clock, not wall-clock time, so that aging, expiry, week boundaries, and contract defaults are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. When either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other evaluation.

The system recognizes exactly seven roles. `DeskAdmin` is the trading desk administrator: it owns reference data (suppliers, customers, warehouses, products, yield specifications), publishes and closes price sheets, voids fabrication batches, and drives the logical clock. `Trader` is the desk trader: it books and cancels purchase orders, drafts price sheets and their lines, and creates and amends forward contracts. `RiskOfficer` is the risk manager: it runs the weekly allocation waterfall and cancels forward contracts — deliberately segregated from the `Trader` who writes them. `QualityGrader` is the QA and USDA documentation officer: it inspects lots, quarantines and releases them, and issues and revokes inspection certificates — deliberately segregated from receiving. `WarehouseOperator` is the cold-storage operator: it receives purchase orders, runs fabrication, loads out and departs shipments, and records temperatures. `ClaimsAdjuster` is the claims settlement officer: it posts settlement offers and denies claims — segregated from the customer side that files, counters, and accepts. `CustomerRep` is a customer representative: it requests allocations, accepts or rejects shipments at the receiving dock, and files, counters, accepts, or withdraws claims for its own house. Every role may use every read endpoint; the exposure report is additionally restricted to `DeskAdmin`, `Trader`, and `RiskOfficer`. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity is bound to `X-User-ID` in two different ways. For `DeskAdmin`, `Trader`, `RiskOfficer`, `QualityGrader`, `WarehouseOperator`, and `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it against an entity's `id`. For `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any customer-owned resource compare the resource's owning-customer reference to `X-User-ID`. Concretely, when a `CustomerRep` requests an allocation, cancels an allocation, accepts or rejects a shipment at the dock, or files, counters, accepts, or withdraws a claim, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) unless `X-User-ID` equals the `id` of the `Customer` that owns the acted resource — the allocation's `customer_id`, the customer of the shipment's allocation, or the customer behind the claim's shipment, respectively.

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

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, individual list endpoints accept optional filter query parameters that narrow the result set. Suppliers and customers filter by `status`. Products filter by `kind`. Yield specifications filter by `carcass_product_id` and `output_product_id`. Price sheets filter by `status` and `supersedes_sheet_id`. Price sheet lines — whether listed within a sheet or across sheets — filter by `product_id` and `price_sheet_id`. Purchase orders filter by `supplier_id`, `product_id`, and `status`. Inventory lots filter by `warehouse_id`, `product_id`, `status`, `po_id`, `parent_lot_id`, and `fabrication_batch_id`. Fabrication batches filter by `input_lot_id` and `status`. Forward contracts filter by `customer_id`, `product_id`, and `status`. Allocations filter by `customer_id`, `price_sheet_line_id`, `forward_contract_id`, and `status`. Shipments filter by `allocation_id`, `status`, and `temp_compliance`. Claims filter by `shipment_id` and `status`. Inspection certificates filter by `lot_id`, `certificate_type`, and `status`. The exposure report takes `product_id` and `week_start` as its query parameters.

### 2.4. The Logical Trading Clock

The system keeps its own logical clock. Before any operator advances it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. Every logical timestamp the system records — sheet publication times, grading-date interpretations, lot ages — is read from this clock.

A `DeskAdmin`-only test-driving capability advances the logical clock to a supplied instant carried in the `to_iso8601` field. Advancing the clock is never a pure time change: it triggers two automatic sweeps, and the response reports the new `current_utc` together with the swept victims as `expired_lot_ids` and `defaulted_contract_ids`. In the first sweep, every `AVAILABLE` lot whose `age_days` has moved strictly beyond its product's `shelf_life_days` transitions to `EXPIRED`, drops out of its warehouse's occupancy figure, and is excluded from the physical component of the net exposure report. In the second sweep, every `OPEN` forward contract whose delivery week has fully elapsed — the logical date is on or after the Monday immediately following the delivery week — while its `delivered_lbs` remains below its `committed_lbs` transitions to `DEFAULTED` and is removed from the forward component of net exposure. Lot aging itself is clock-derived: a lot's `age_days` is the whole number of days between the logical clock date and the lot's `production_date`, rounded down; the production date itself is age zero.

### 2.5. Resource Identity, Timestamps, and Versions

Most resources share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource, including mutations caused by cascades, and underpins optimistic concurrency control.

Four resources are deliberately lighter. `Product`, `YieldSpec`, `TemperatureReading`, and `InspectionCertificate` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Products and yield specifications are immutable configuration once created, temperature readings are append-only facts, and a certificate's only lifecycle change is revocation, so none of them needs modification bookkeeping.

### 2.6. Weights, Money, and Rounding Discipline

Three measurement conventions hold across the entire API, and every calculation in §3 obeys them. Weights are expressed in pounds carried to two decimal places. Monetary amounts are expressed as integer cents; prices on sheet lines and forward contracts are cents per pound, while a purchase order's contract price is cents per hundredweight. Temperatures are Fahrenheit, and temperature compliance comparisons are exact decimal comparisons at tenth-of-a-degree precision.

Rounding is pinned down wherever a calculation produces a derived value. Whenever this document says an amount is "rounded", it means round half up to the nearest whole cent unless explicitly stated otherwise. Two calculations choose deliberately different rounding architectures, and both are contractual: the cutout model rounds each per-product line to integer cents first and then sums the rounded lines — never summing raw values and rounding once at the end — while the lot valuation model performs a single rounding at the very end of its multiplication chain, leaving intermediate values unrounded.

### 2.7. Trading Weeks and the Published-Sheet Selector

The desk trades in weekly epochs. A price sheet's `week_start_date` and a forward contract's `delivery_week_start` are each the ISO date of a Monday, and each names the half-open week that runs from that Monday up to but not including the following Monday. A date value that is not a Monday is rejected with `ERR_INVALID_WEEK_START` (HTTP 422). A forward contract's delivery week may not be earlier than the current logical week — neither at creation nor when amended — and such a request is rejected with `ERR_FORWARD_WEEK_PASSED` (HTTP 422).

Several calculations need "the most recently published sheet". That phrase has one exact meaning everywhere it appears: among sheets in `PUBLISHED` status, select the one with the latest `week_start_date`; if several share that week, select the one with the latest `published_at`; if a tie still remains, select the one with the earliest `created_at`. The booking-time cutout estimate, the lot market-value base price, and the exposure report's basis price all use this selector. The grading-time cutout uses a different selector — the sheet whose half-open week contains the grading date — which §3.4 specifies in full.

### 2.8. Request Validation Pipeline and Nested Resource Retrieval

Every request is evaluated against an ordered validation pipeline. Earlier stages mask later ones: a request that fails an earlier check reports that check's error and is never evaluated against later checks, so the reported error is always the highest-priority failure. The stages, in order, are:

1. **Authentication context.** `X-User-ID` and `X-User-Role` are present and the role is one of the seven declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to every endpoint.
2. **Role authorization.** The role is permitted for the target endpoint; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). This applies to every endpoint.
3. **Customer ownership.** For the customer-facing mutations — requesting an allocation, cancelling an allocation, delivering or rejecting a shipment, and filing, countering, accepting, or withdrawing a claim — a `CustomerRep` caller must own the resource; otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
4. **Request shape.** Required fields are present, types are correct, enum members are valid, and quantities are positive; otherwise `ERR_INVALID_REQUEST` (HTTP 400). This applies to every endpoint with a request body.
5. **Path existence.** Resource identifiers in the URL path exist, validated strictly left to right; the first missing identifier produces that resource's not-found error (HTTP 404): `ERR_SUPPLIER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, `ERR_PRICE_SHEET_LINE_NOT_FOUND`, `ERR_YIELD_SPEC_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_FABRICATION_BATCH_NOT_FOUND`, `ERR_FORWARD_CONTRACT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_CERTIFICATE_NOT_FOUND`. On a nested path such as a sheet's line collection or a shipment's reading collection, the parent is validated before the child, so a request aimed at lines of a non-existent sheet reports `ERR_PRICE_SHEET_NOT_FOUND` before any line-level check runs.
6. **Body reference existence.** Every body-referenced identifier — `supplier_id`, `product_id`, `warehouse_id`, `customer_id`, `price_sheet_line_id`, `forward_contract_id`, `allocation_id`, `shipment_id`, `lot_id`, `input_lot_id`, and each element of `lot_ids` — must resolve to an existing resource; otherwise `ERR_REFERENCE_NOT_FOUND` (HTTP 422).
7. **Target state precondition.** The acted resource must be in the state its endpoint requires; the rejection is the state-specific conflict (HTTP 409) — for example `ERR_PO_NOT_BOOKED`, `ERR_PRICE_SHEET_NOT_DRAFT`, `ERR_PRICE_SHEET_NOT_PUBLISHED`, `ERR_LOT_NOT_IN_INSPECTION`, `ERR_LOT_NOT_AVAILABLE`, `ERR_BATCH_NOT_DRAFT`, `ERR_CONTRACT_NOT_OPEN`, `ERR_ALLOCATION_NOT_REQUESTED`, `ERR_ALLOCATION_NOT_CANCELLABLE`, `ERR_SHIPMENT_NOT_STAGING`, `ERR_SHIPMENT_NOT_IN_TRANSIT`, `ERR_CLAIM_STATE_INVALID`, `ERR_CERTIFICATE_ALREADY_REVOKED`, or the generic `ERR_INVALID_STATE` where no specific code exists.
8. **Cross-entity state.** State requirements that reach across resources: the supplier must be `ACTIVE` when a purchase order is created or received (`ERR_SUPPLIER_SUSPENDED`, HTTP 409); the sheet behind an allocation's line must be `PUBLISHED` when the allocation is requested (`ERR_PRICE_SHEET_NOT_PUBLISHED`, HTTP 409); a claim may only be filed against a shipment that is `DELIVERED` or `REJECTED_AT_RECEIVING` (`ERR_SHIPMENT_NOT_CLAIMABLE`, HTTP 409).
9. **Product and cold-chain safety.** Every lot a shipment draws — whether named explicitly or selected by the FIFO rule — must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`, HTTP 409) and must not be `EXPIRED` (`ERR_LOT_EXPIRED`, HTTP 409); a `TEMPERATURE_ABUSE` claim requires the shipment's `temp_compliance` to be `BREACHED` (`ERR_CLAIM_TYPE_NOT_SUPPORTED`, HTTP 422); departure requires at least one recorded temperature reading (`ERR_NO_TEMPERATURE_READING`, HTTP 409).
10. **Uniqueness and structural constraints.** Unique codes do not collide — supplier `establishment_number`, `customer_code`, `product_code`, `po_number`, `lot_code`, `contract_number`, and `certificate_number` — else `ERR_DUPLICATE_CODE` (HTTP 409); at publish time no other `DRAFT` or `PUBLISHED` sheet may cover the same `week_start_date` (`ERR_PRICE_SHEET_WEEK_CONFLICT`, HTTP 409); a sheet being published must carry at least one line (`ERR_SHEET_HAS_NO_LINES`, HTTP 409); fabrication mass must balance exactly (`ERR_MASS_BALANCE_VIOLATION`, HTTP 422); a shipment's weight may not exceed its allocation's remaining unshipped weight (`ERR_SHIPMENT_EXCEEDS_ALLOCATION`, HTTP 422).
11. **Warehouse capacity.** Aggregate cold-store capacity is respected at receiving and at fabrication posting (`ERR_WAREHOUSE_CAPACITY_EXCEEDED`, HTTP 409).
12. **Temporal rules.** Week-start dates are Mondays (`ERR_INVALID_WEEK_START`, HTTP 422); forward delivery weeks are not in the past (`ERR_FORWARD_WEEK_PASSED`, HTTP 422); production dates are neither in the future nor already beyond shelf life at receiving (`ERR_PRODUCTION_DATE_INVALID`, HTTP 422).
13. **Kind and reference compatibility.** Product kinds and cross-references must fit the operation (`ERR_PRODUCT_KIND_MISMATCH`, `ERR_LOT_PRODUCT_MISMATCH`, `ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH`, `ERR_FORWARD_CONTRACT_WEEK_MISMATCH`, all HTTP 422) as §3 details per workflow.
14. **Credit gate.** A customer on `CREDIT_HOLD` may not request allocations (`ERR_CUSTOMER_CREDIT_HOLD`, HTTP 402).
15. **Optimistic concurrency.** Superseding writes carry the expected version of the entity they supersede; a mismatch yields `ERR_STALE_CLAIM_VERSION` or `ERR_STALE_CONTRACT_VERSION` (HTTP 412), as §2.9 specifies.
16. **Supply sufficiency.** When a shipment relies on the FIFO selector, the pool of `AVAILABLE` product must cover the shipped weight in full (`ERR_INSUFFICIENT_SUPPLY`, HTTP 409).

### 2.9. Optimistic Concurrency Control on Superseding Writes

Two write operations are superseding writes: each replaces a negotiated value while leaving the resource's business state unchanged, which means a client holding an outdated read would otherwise overwrite terms it never observed. Both are guarded by optimistic concurrency control, and these are the only two endpoints in the API that take a version field — no other endpoint accepts or requires one.

Posting a settlement offer against a claim requires the request to carry `expected_claim_version` equal to the claim's current `version`. A new offer legitimately supersedes the previous offer without changing the claim's status, so a second sequential offer carrying a stale `expected_claim_version` sees identical business state and would otherwise succeed; the version check is the only thing that rejects it. A mismatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412).

Amending a forward contract requires the request to carry `expected_contract_version` equal to the contract's current `version`. An amendment replaces the contract's terms while the contract stays `OPEN`, so a second sequential amendment carrying a stale `expected_contract_version` likewise sees identical business state; a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).

### 2.10. Customer Credit Exposure and the Automatic Credit Hold

Each customer carries a live credit exposure, `outstanding_exposure_cents`, which starts at zero when the customer is created. Its value is an aggregation: sum, over the customer's allocations in `CONFIRMED` or `SHIPPED` status, each allocation's `allocated_lbs` multiplied by its `unit_price_cents`; then subtract the `final_settlement_cents` of the customer's claims in `SETTLED_PAID` status. If the result is negative, the exposure is floored at zero. Desk policy holds allocation value inside exposure until the allocation is cancelled or a claim against it settles: shipment movement — load-out, departure, delivery — triggers a recompute but never changes the figure itself.

The exposure is recomputed immediately after every exposure-affecting mutation: an allocation being confirmed or cancelled, a shipment being delivered, a claim being settled as paid. After each recompute, the customer's credit standing is re-evaluated automatically against `credit_limit_cents`, the customer's maximum permitted outstanding exposure. The comparison is strict. An `ACTIVE` customer whose exposure rises strictly above the limit transitions to `CREDIT_HOLD`; a customer on `CREDIT_HOLD` whose exposure falls to the limit or below transitions back to `ACTIVE`. Exposure exactly equal to the limit therefore leaves the customer `ACTIVE`, while exposure one cent above the limit forces the hold. A customer starts life `ACTIVE`, and no manual endpoint changes this status — it moves only through these automatic transitions.

### 2.11. Cold-Store Occupancy, Capacity, and Cascade Bookkeeping

A warehouse's `occupied_lbs` is a live aggregate: the sum of `current_weight_lbs` over all lots stored at that warehouse whose status is `IN_INSPECTION`, `AVAILABLE`, or `QUARANTINED`. Lots in `DEPLETED` or `EXPIRED` status are excluded. The figure starts at zero when the warehouse is created and is recomputed whenever a lot is created, whenever a lot's weight changes, whenever a lot enters or leaves the counted statuses, and at fabrication posting and voiding.

Capacity is a hard constraint, enforced twice in the workflow. At receiving, the warehouse's `occupied_lbs` plus the incoming received weight must not exceed its `capacity_lbs`. At fabrication posting, the check is run again for the same cold store, because output lots land in the same warehouse as the consumed input lot — `occupied_lbs` plus the incoming output weight must not exceed `capacity_lbs`. Either violation is rejected with `ERR_WAREHOUSE_CAPACITY_EXCEEDED` (HTTP 409).

Cascades throughout this document are ordered cause-and-effect chains, and bookkeeping follows every link: whenever a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments, and every derived figure the mutation touches — occupancy, customer exposure, sheet-line allocation totals, contract earmarks — is recomputed as part of the same operation. Where a multi-link cascade is specified (publishing a superseding sheet, revoking a grade certificate, rejecting a shipment at the dock, voiding a posted fabrication batch, accepting a claim), §3 states the links in their causal order.

## 3. Business Logic & Workflows

### 3.1. Desk Reference Data: Suppliers, Customers, Warehouses, Products, and Yield Specifications

Before any trading happens, a `DeskAdmin` builds the desk's reference data. Each **supplier** is registered with its legal `name`, its USDA `establishment_number` — unique across all suppliers, with a collision rejected by `ERR_DUPLICATE_CODE` — and a primary `contact_email`. A supplier's `status` begins at `ACTIVE` and can be moved to `SUSPENDED` by a `DeskAdmin` through the supplier status operation; the request carries the target `status` and, on suspension, a `reason` that is recorded into the supplier's `suspension_reason`. Suspension is forceful: every purchase order of that supplier still in `BOOKED` status is cancelled automatically with `cancel_reason` set to `SUPPLIER_SUSPENDED`, and each such cancelled order is removed from the inbound component of the net exposure calculation. Attempting to suspend a supplier that is not `ACTIVE` fails with `ERR_INVALID_STATE`. Reinstatement moves the supplier from `SUSPENDED` back to `ACTIVE` — attempting it on a supplier that is not `SUSPENDED` likewise fails with `ERR_INVALID_STATE` — clears `suspension_reason` to null, and pointedly does not reinstate the previously cancelled purchase orders.

Customers are registered with a legal `name`, a unique `customer_code`, a `credit_limit_cents` ceiling, and an `allocation_tier` of `TIER_1`, `TIER_2`, or `TIER_3` that fixes their priority in the weekly allocation waterfall, `TIER_1` first. A new customer starts `ACTIVE` with `outstanding_exposure_cents` at zero; from then on the exposure aggregate and the automatic credit-hold transitions of §2.10 govern the `status` field, which is either `ACTIVE` or `CREDIT_HOLD`.

Cold storage is modeled as warehouses. Each warehouse is created with a `name`, a `zone` of `CHILLER` or `FROZEN`, and a `capacity_lbs` ceiling on aggregate stored weight. Its `occupied_lbs` is the computed occupancy of §2.11 and starts at zero.

The **product catalog** defines what the desk trades. A product carries a unique `product_code`; a `kind` of `CARCASS`, `PRIMAL`, or `SUBPRIMAL`; a `species` of `BEEF` or `PORK`; a `shelf_life_days` value counted from a lot's `production_date`, after which the lot auto-expires; and a `required_temp_max_f` shipment temperature ceiling — any recorded reading strictly greater than this ceiling breaches temperature compliance. Products also declare their trim specification through `max_fat_pct`: a lot's measured fat percent must be less than or equal to this value to be specification-compliant. For products of kind `CARCASS`, `max_fat_pct` is null and carcasses are always treated as compliant. Products are immutable configuration once created.

Finally, **yield specifications** describe how a carcass converts into saleable cuts. A yield spec's `carcass_product_id` must reference a product of kind `CARCASS`, and its `output_product_id` must reference a product of kind `PRIMAL` or `SUBPRIMAL`; a mismatch on either side is rejected with `ERR_PRODUCT_KIND_MISMATCH` (HTTP 422). Each spec states an `expected_yield_pct` — the expected output weight as a percentage of carcass weight, between 0 and 100 — and a compliance band with an inclusive lower bound `min_yield_pct` and an inclusive upper bound `max_yield_pct`, which the fabrication workflow of §3.5 uses to route output lots. Yield specifications are likewise immutable configuration.

### 3.2. The Weekly Price Sheet Cycle

Every Monday epoch is priced through a **price sheet**. A `Trader` creates a sheet by supplying its `week_start_date` — a Monday per §2.7 — and optionally a `supersedes_sheet_id` naming the published sheet it replaces. The sheet is born in `DRAFT` status with `published_at` null. While a sheet is `DRAFT`, the `Trader` adds lines to it; each line references a `product_id` and declares a `price_per_lb_cents` and a `weekly_supply_lbs` cap that bounds how much of that product the sheet will allocate for the week. Every line belongs to its parent sheet through `price_sheet_id`, and each line's `allocated_lbs` — the running total of weight the waterfall has granted against the line — starts at zero. Adding a line to a sheet that is not `DRAFT` is rejected with `ERR_PRICE_SHEET_NOT_DRAFT`.

Publication is a `DeskAdmin` act and a market-epoch event, guarded by four preconditions evaluated as part of the §2.8 pipeline. The sheet must be `DRAFT`, else `ERR_PRICE_SHEET_NOT_DRAFT`. It must carry at least one line, else `ERR_SHEET_HAS_NO_LINES`. No other sheet in `DRAFT` or `PUBLISHED` status may cover the same `week_start_date`, else `ERR_PRICE_SHEET_WEEK_CONFLICT`. And when `supersedes_sheet_id` is set, the referenced sheet must currently be `PUBLISHED`, else `ERR_PRICE_SHEET_NOT_PUBLISHED`. On successful publication the sheet's `published_at` is stamped from the logical clock, the sheet's `version` increments, and a three-link cascade fires when the sheet supersedes another. First, the referenced sheet transitions from `PUBLISHED` to `SUPERSEDED`. Second, every still-`REQUESTED` allocation on the superseded sheet's lines, and every `CONFIRMED` allocation on those lines that has no shipment in `STAGING` or `IN_TRANSIT`, is cancelled with `cancel_reason` `SHEET_SUPERSEDED`. Third, each of those cancellations recomputes the affected customer's `outstanding_exposure_cents` and re-evaluates the automatic credit-hold release of §2.10.

A sheet can also be closed. Closing a `PUBLISHED` sheet — the only state from which a close produces `CLOSED`; a sheet in any other non-`DRAFT` state has already left the market — moves it to `CLOSED` and fires the same style of cascade: the sheet's remaining `REQUESTED` allocations, and its `CONFIRMED` allocations with no `STAGING` or `IN_TRANSIT` shipments, are cancelled with `cancel_reason` `SHEET_CLOSED`, each cancellation again recomputing customer exposure and re-evaluating credit-hold release. The close operation accepts exactly two from-states — `PUBLISHED`, producing `CLOSED` as described, and `DRAFT`; the `PUBLISHED` path's state precondition is enforced with `ERR_PRICE_SHEET_NOT_PUBLISHED`. Closing a `DRAFT` sheet instead discards it: the sheet moves to `DISCARDED` with no further effect. `CLOSED`, `SUPERSEDED`, and `DISCARDED` are terminal.

### 3.3. Booking and Receiving Purchase Orders

Procurement begins when a `Trader` books a **purchase order** against a supplier. The booking payload carries a unique `po_number`, the `supplier_id`, the `product_id`, the `ordered_weight_lbs`, the `contract_price_per_cwt_cents` — the purchase price per hundredweight, in cents — and the `required_delivery_date` on which the product is due. The product's kind must be `CARCASS` or `PRIMAL`; booking anything else is rejected with `ERR_PRODUCT_KIND_MISMATCH`. The supplier must be `ACTIVE`: booking against a `SUSPENDED` supplier is rejected with `ERR_SUPPLIER_SUSPENDED`. A successfully booked order starts in `BOOKED` status with `received_weight_lbs` null and `actual_cutout_value_cents` null, and it immediately enters the inbound component of the desk's net exposure.

Booking also prices the purchase against the market. The desk's booking-time estimate, `estimated_cutout_value_cents`, values the order's product by its cutout: for a `CARCASS` product, the system collects every yield specification whose `carcass_product_id` names the ordered product and prices each expected output. For each specification, the expected output weight is the basis weight — `ordered_weight_lbs` at booking — multiplied by the specification's `expected_yield_pct` and divided by one hundred. That expected weight is multiplied by the `price_per_lb_cents` that the selected sheet's line carries for the specification's `output_product_id`; if the selected sheet has no line for that output product, the specification contributes zero cents. Each per-product line value is rounded half-up to whole cents first, and only then are the rounded lines summed — the rounding order is pinned per-line-then-sum and is never sum-then-round. The sheet selected at booking is the most recently published sheet under the §2.7 selector. When the ordered product is a `PRIMAL` — which by definition has no yield specifications — the estimate is a single line instead: the `ordered_weight_lbs` multiplied by the selected sheet's line price for that product, rounded half-up to whole cents.

Receiving is a `WarehouseOperator` act with four preconditions. The purchase order must be `BOOKED`, else `ERR_PO_NOT_BOOKED`. Its supplier must be `ACTIVE`, else `ERR_SUPPLIER_SUSPENDED`. The destination warehouse must have room: its `occupied_lbs` plus the incoming `received_weight_lbs` must not exceed `capacity_lbs`, else `ERR_WAREHOUSE_CAPACITY_EXCEEDED`. And the product must be fresh enough to receive: the payload's `production_date` may not lie in the future of the logical clock, and the lot's age at receiving — logical date minus `production_date` — must be less than or equal to the product's `shelf_life_days`; either failure is `ERR_PRODUCTION_DATE_INVALID` (HTTP 422). The receiving payload names the scale weight `received_weight_lbs`, the storage site `warehouse_id`, the new lot's `lot_code` (unique across lots, enforced by `ERR_DUPLICATE_CODE`), and the `production_date`. On success the purchase order's `received_weight_lbs` is recorded, its `status` moves from `BOOKED` to `RECEIVED`, and its `version` increments; exactly one inventory lot is created in `IN_INSPECTION` status, stamped with the payload's `lot_code` and `production_date`, tied to the order through `po_id`, holding both `received_weight_lbs` and `current_weight_lbs` equal to the payload weight; and the warehouse's occupancy is recomputed.

A `Trader` may cancel an order only while it is `BOOKED` — otherwise `ERR_PO_NOT_BOOKED`. Cancellation moves the order to `CANCELLED` with `cancel_reason` `MANUAL`, removes it from the inbound component of net exposure, and increments its `version`. `GRADED` and `CANCELLED` are the terminal states; the grading transition itself belongs to the certification workflow of §3.4.

### 3.4. Inspection, Grading, and the Lot's Market Value

An **inventory lot** is the desk's unit of physical stock. However it is born — at receiving, from fabrication, or as a rejection return — a lot carries a unique `lot_code`, a `product_id`, the `warehouse_id` of its cold store, a `production_date`, a `received_weight_lbs` recording its weight at creation, and a `current_weight_lbs` that shipment load-out and fabrication consumption decrement over its life. Lots born at receiving are tied to their purchase order through `po_id`; fabrication outputs instead carry `parent_lot_id` and `fabrication_batch_id` for genealogy, with `po_id` null. A lot's `usda_grade` is one of `UNGRADED`, `PRIME`, `CHOICE`, `SELECT`, `STANDARD`, or `NO_ROLL`, starting at `UNGRADED`; its `measured_fat_pct` is null until inspected; its `spec_compliant` flag is null until inspected; its `unit_value_cents_per_lb` is null until the lot is graded; and its `quarantine_reason` is null unless the lot is `QUARANTINED`. A lot's `status` walks the states `IN_INSPECTION`, `AVAILABLE`, `QUARANTINED`, `DEPLETED`, and `EXPIRED`, beginning at `IN_INSPECTION`; `DEPLETED` and `EXPIRED` are terminal.

Inspection is a `QualityGrader` act that records the lot's `measured_fat_pct` and derives `spec_compliant`: the measured fat percent must be less than or equal to the product's `max_fat_pct`, with carcass-kind products — whose `max_fat_pct` is null — always compliant. Inspection requires the lot to be `IN_INSPECTION`, else `ERR_LOT_NOT_IN_INSPECTION`. A compliant result routes the lot to `AVAILABLE`; if a grade has already been recorded on the lot, its `unit_value_cents_per_lb` is recomputed at the same time. A non-compliant result routes the lot to `QUARANTINED` with `quarantine_reason` `SPEC_NONCOMPLIANCE`.

Quarantine has three doors in and one door out. Beyond a failed inspection, a `QualityGrader` may manually quarantine an `AVAILABLE` lot — a USDA hold — recording `quarantine_reason` `USDA_HOLD`; and the certificate-revocation cascade described below quarantines with `quarantine_reason` `CERT_REVOKED`. Both the manual action and any other operation that requires an `AVAILABLE` lot reject a lot in the wrong state with `ERR_LOT_NOT_AVAILABLE`. Release returns a `QUARANTINED` lot to `AVAILABLE`: the lot must be `QUARANTINED`, else `ERR_INVALID_STATE`, and its `age_days` must not exceed the product's `shelf_life_days`, else `ERR_LOT_EXPIRED`. Release clears `quarantine_reason` to null and recomputes `unit_value_cents_per_lb`.

A lot's market value, `unit_value_cents_per_lb`, is the aging- and grade-adjusted figure at the heart of the desk's inventory accounting. It is recomputed at lot grading — both when a grade certificate is issued and when one is revoked — at inspection completion when a grade is already set, at release from quarantine, and whenever the logical clock advances. The value is the product of three factors, with a single rounding half-up to whole cents at the very end and no rounding of intermediate values. The first factor is a base price: the `price_per_lb_cents` of the most recently published sheet's line for the lot's product, selected exactly as §2.7 prescribes; when no published sheet line exists for the product, the base price is zero. The second factor is a grade multiplier: 1.08 for `PRIME`, 1.00 for `CHOICE`, 0.94 for `SELECT`, 0.90 for `STANDARD`, 0.85 for `NO_ROLL`, and 0.97 for `UNGRADED`. The third factor is an age multiplier over boundary-inclusive bands of `age_days`: a lot seven days old or younger multiplies by 1.00; from its eighth through its fourteenth day, inclusive, by 0.95; from its fifteenth through its twenty-first day, inclusive, by 0.88; and from its twenty-second day onward by 0.75.

Two automatic transitions close the lot lifecycle. When a lot's `current_weight_lbs` reaches zero — through shipment load-out or fabrication consumption — the lot moves from `AVAILABLE` to `DEPLETED` and its warehouse's occupancy is recomputed. And when a clock advance finds an `AVAILABLE` lot whose `age_days` has moved strictly beyond its product's `shelf_life_days`, the lot moves to `EXPIRED`, the warehouse's occupancy is recomputed, and the lot is excluded from the physical component of net exposure.

USDA paperwork rides on **inspection certificates**. A `QualityGrader` issues a certificate by supplying the `lot_id`, a `certificate_type` of `USDA_GRADE`, `USDA_INSPECTION`, or `COA`, a unique `certificate_number` (collisions rejected with `ERR_DUPLICATE_CODE`), the `issued_by` inspector identification, and the `issue_date`. The `grade_result` field — one of `PRIME`, `CHOICE`, `SELECT`, `STANDARD`, or `NO_ROLL` — is required if and only if the `certificate_type` is `USDA_GRADE`; omitting it there is a request-shape failure under `ERR_INVALID_REQUEST`. A certificate is born `VALID`. Issuing a `USDA_GRADE` certificate sets the lot's `usda_grade` to the `grade_result` and recomputes the lot's `unit_value_cents_per_lb`. When the graded lot belongs to a purchase order in `RECEIVED` status, the grading also advances the order from `RECEIVED` to `GRADED`, increments the order's `version`, and computes the order's `actual_cutout_value_cents` using the grading-time variant of the cutout model: the formula is the per-line-rounded sum of §3.3, but the basis weight is the order's `received_weight_lbs` and the selected sheet is the one whose half-open week contains the certificate's `issue_date` — a sheet in `PUBLISHED`, `CLOSED`, or `SUPERSEDED` status qualifies. If no sheet's week contains the issue date, the grading-time cutout falls back to the booking estimate: `actual_cutout_value_cents` takes the value of `estimated_cutout_value_cents`.

Revoking a certificate is a `QualityGrader` act permitted only while the certificate is `VALID`; otherwise the request fails with `ERR_CERTIFICATE_ALREADY_REVOKED`. Revocation moves the certificate to `REVOKED` and, when the revoked certificate is a `USDA_GRADE` certificate, fires a three-link cascade. First, the lot's `usda_grade` reverts to `UNGRADED` and its `unit_value_cents_per_lb` is recomputed. Second, that lot, if it is `AVAILABLE`, moves to `QUARANTINED` with `quarantine_reason` `CERT_REVOKED`. Third, if the lot belongs to a purchase order that is `GRADED`, the order reverts to `RECEIVED` and its `actual_cutout_value_cents` is cleared to null — revocation is the single path that moves a purchase order backward out of its terminal `GRADED` state.

### 3.5. Fabrication: Breaking Carcasses into Saleable Cuts

Fabrication converts a carcass lot into saleable cuts. A `WarehouseOperator` drafts a **fabrication batch** by naming the `input_lot_id`, the recorded shrink and evaporation `loss_lbs`, and an `outputs` array in which each entry names a `product_id` and a `weight_lbs`. The input lot must reference an existing lot, must be `AVAILABLE` (else `ERR_LOT_NOT_AVAILABLE`), and must be a carcass — its product's kind must be `CARCASS`, else `ERR_PRODUCT_KIND_MISMATCH`. Every output entry must be covered by a yield specification running from the input lot's product to that output product; an output with no such specification is rejected with `ERR_PRODUCT_KIND_MISMATCH`. A drafted batch starts in `DRAFT` status, and its totals are computed at drafting: `total_output_weight_lbs` is the sum of the `weight_lbs` values across the `outputs` entries, and `yield_efficiency_pct` is that total divided by the input weight consumed — the input lot's on-hand weight — multiplied by one hundred.

Posting the batch, again a `WarehouseOperator` act, is where fabrication becomes real, and it carries three preconditions beyond existence. The batch must be `DRAFT`, else `ERR_BATCH_NOT_DRAFT`. The input lot must still be `AVAILABLE`, else `ERR_LOT_NOT_AVAILABLE`. And mass must balance exactly: the batch's `total_output_weight_lbs` plus its `loss_lbs` must equal the input lot's `current_weight_lbs` with no tolerance; any discrepancy is rejected with `ERR_MASS_BALANCE_VIOLATION` (HTTP 422). Posting also re-verifies the warehouse capacity rule of §2.11, since the output lots land in the same cold store as the consumed input. On a successful post, the input lot's `current_weight_lbs` falls to zero and the lot transitions to `DEPLETED`; one output lot is created per `outputs` entry with `received_weight_lbs` equal to the entry's `weight_lbs`, a system-minted `lot_code`, `parent_lot_id` pointing at the input lot, `fabrication_batch_id` pointing at the batch, `production_date` copied from the input lot, and `warehouse_id` copied from the input lot; the batch's totals are computed; and the warehouse's occupancy is recomputed. Each output lot's starting status depends on its yield band: the output's actual yield — its `weight_lbs` as a percentage of the input weight consumed — is compared against the inclusive band from `min_yield_pct` to `max_yield_pct` of the yield specification covering it; inside the band the lot starts `IN_INSPECTION`, and outside the band it starts `QUARANTINED` with `quarantine_reason` `YIELD_OUT_OF_BAND`.

Voiding is a `DeskAdmin` act with two distinct paths. Voiding a `DRAFT` batch simply moves it to `VOIDED` with no further effect. Voiding a `POSTED` batch is an unwind, permitted only when every output lot is untouched — each output's `current_weight_lbs` still equals its `received_weight_lbs`; if any output has been drawn down, the void is rejected with `ERR_BATCH_NOT_VOIDABLE`. Both paths report a batch in the wrong from-state as `ERR_BATCH_NOT_DRAFT`. The unwind fires a two-link cascade: first, every output lot moves to `DEPLETED` with its `current_weight_lbs` driven to zero; second, once the outputs are depleted, the input lot's `current_weight_lbs` is restored to its pre-post weight and the input lot returns to `AVAILABLE`; the warehouse's occupancy is then recomputed. `POSTED` and `VOIDED` are the batch's terminal states.

### 3.6. Forward Contracts and the Weekly Allocation Waterfall

The desk sells future production through **forward contracts**. A `Trader` creates one by supplying a unique `contract_number`, the `customer_id`, the `product_id`, the total `committed_lbs` over the contract's life, the `fixed_price_per_lb_cents`, and the `delivery_week_start` — a Monday naming the half-open delivery week, which may not be earlier than the current logical week; the Monday rule and the not-in-the-past rule are enforced with `ERR_INVALID_WEEK_START` and `ERR_FORWARD_WEEK_PASSED` respectively. A new contract is `OPEN`, with `delivered_lbs`, `earmarked_lbs`, and `amendment_round` all starting at zero.

Terms can be renegotiated while the contract is `OPEN` through amendment, a `Trader` act guarded by optimistic concurrency per §2.9. The amendment must name the contract's current version through `expected_contract_version` — a mismatch is `ERR_STALE_CONTRACT_VERSION` (HTTP 412) — the contract must be `OPEN`, else `ERR_CONTRACT_NOT_OPEN`, and the replacement `delivery_week_start` must again be a Monday not earlier than the current logical week. A successful amendment replaces `committed_lbs`, `fixed_price_per_lb_cents`, and `delivery_week_start` wholesale with the payload values, increments `amendment_round` by one, and increments the contract's `version` by one; the contract remains `OPEN`.

Three events close a contract. When a delivery against an earmarked allocation pushes the contract's cumulative `delivered_lbs` to meet or exceed its `committed_lbs`, the contract settles automatically to `SETTLED`. When a clock advance finds the delivery week fully elapsed — the logical date on or after the Monday immediately following `delivery_week_start` — with `delivered_lbs` still below `committed_lbs`, the contract moves to `DEFAULTED` and leaves the forward component of net exposure. And a `RiskOfficer` may cancel an `OPEN` contract — else `ERR_CONTRACT_NOT_OPEN` — provided no `CONFIRMED` allocation is earmarked to it, a block reported as `ERR_CONTRACT_HAS_CONFIRMED_ALLOCATIONS`; cancellation moves the contract to `CANCELLED`, cancels every still-`REQUESTED` allocation earmarked to it with `cancel_reason` `CONTRACT_CANCELLED`, and removes the contract from the forward component of net exposure. `SETTLED`, `DEFAULTED`, and `CANCELLED` are terminal.

On the spot side, a `CustomerRep` requests a weekly **allocation** by naming the `customer_id` — which must equal the caller's `X-User-ID` under §2.1 — the `price_sheet_line_id` being requested, and the `requested_lbs`. The line must sit on a `PUBLISHED` sheet, else `ERR_PRICE_SHEET_NOT_PUBLISHED`, and the customer must be `ACTIVE`: a customer on `CREDIT_HOLD` may not request allocations and is turned away with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402). The request may optionally earmark a forward contract through `forward_contract_id`, in which case pricing and supply come from the contract rather than the sheet line; the earmark is validated three ways — the contract must belong to the same customer, else `ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH`; the contract's product must be the same product as the line's, else `ERR_PRODUCT_KIND_MISMATCH`; and the contract's delivery week must equal the sheet's week, else `ERR_FORWARD_CONTRACT_WEEK_MISMATCH`. A requested allocation starts in `REQUESTED` status with `allocated_lbs` at zero and `unit_price_cents` null.

Granting supply is the `RiskOfficer`'s weekly act: running the allocation waterfall over a sheet, which requires the sheet to be `PUBLISHED` and is otherwise rejected with `ERR_PRICE_SHEET_NOT_PUBLISHED`. The engine walks the sheet's lines in the order the lines were created, earliest first, considering only the sheet's own `REQUESTED` allocations. For each line, the remaining sheet supply is the line's `weekly_supply_lbs` minus its `allocated_lbs`. Within a line, requests are considered in tier order — `TIER_1` before `TIER_2` before `TIER_3` — and, within a tier, in request creation order, earliest first. When the allocation under consideration carries a `forward_contract_id`, the engine prices and supplies it from the contract: the contract must be `OPEN`; the available pool is the contract's `committed_lbs` minus its `delivered_lbs` minus its `earmarked_lbs`; the applicable price is the contract's `fixed_price_per_lb_cents`; and the sheet's remaining supply is not consumed by the grant. Without an earmark, the pool is the line's remaining sheet supply and the price is the line's `price_per_lb_cents`. The grant is the lesser of the allocation's `requested_lbs` and the available pool, never negative. A grant greater than zero confirms the allocation: it moves from `REQUESTED` to `CONFIRMED`, its `allocated_lbs` is set to the grant — a partial grant confirms below the requested quantity — its `unit_price_cents` is set to the applicable price, and the granted weight is added to the line's `allocated_lbs` or, for an earmarked grant, to the contract's `earmarked_lbs`. A grant of exactly zero — supply exhausted or the credit gate's aftermath — moves the allocation from `REQUESTED` to `SHORTFALL`. Immediately after each confirmation the customer's `outstanding_exposure_cents` is recomputed per §2.10, and if the recompute pushes exposure strictly above `credit_limit_cents` the customer moves to `CREDIT_HOLD` on the spot; grants are supply-limited only, and the credit gate never reduces a grant. The run returns a summary carrying `confirmed_count`, `shortfall_count`, and the full `allocations` collection as processed.

Allocations unwind in several ways, all landing in `CANCELLED`. A `CustomerRep` may cancel a still-`REQUESTED` allocation — otherwise `ERR_ALLOCATION_NOT_REQUESTED` — which releases nothing and simply closes the request with `cancel_reason` `MANUAL`; the sheet-supersede, sheet-close, and contract-cancel cascades issue the same transition themselves, bypassing the role check. A `CustomerRep` may also cancel a `CONFIRMED` allocation, but only when it has no shipment in `STAGING` or `IN_TRANSIT`; otherwise the request fails with `ERR_ALLOCATION_NOT_CANCELLABLE`. Cancelling a confirmed allocation releases its supply: the line's `allocated_lbs` — or, for an earmarked allocation, the contract's `earmarked_lbs` — is decremented by the allocation's `allocated_lbs`, and the customer's exposure is recomputed with credit-hold release re-evaluated. Cascade-initiated cancellations carry `cancel_reason` values of `SHEET_SUPERSEDED`, `SHEET_CLOSED`, or `CONTRACT_CANCELLED` as §3.2 and this section describe. `SHORTFALL`, `SHIPPED`, and `CANCELLED` are terminal.

One automatic transition completes the allocation's arc: when the cumulative weight delivered on `DELIVERED` shipments against an allocation reaches or exceeds its `allocated_lbs`, the allocation moves from `CONFIRMED` to `SHIPPED`, and the customer's exposure is recomputed — though per §2.10 a `SHIPPED` allocation still counts toward exposure exactly as a `CONFIRMED` one does, so the figure itself does not move.

### 3.7. Load-Out, the Cold Chain, and Dock Decisions

Physical fulfillment starts with load-out: a `WarehouseOperator` creates a **shipment** against a confirmed allocation, naming the `allocation_id`, the `carrier_name`, the reefer `trailer_temp_setpoint_f`, the loaded `shipped_lbs`, and optionally an explicit `lot_ids` list. The referenced allocation must be in `CONFIRMED` status; a request naming an allocation in any other status is rejected as a state-precondition conflict (HTTP 409). The loaded weight may not exceed the allocation's remaining unshipped balance — its `allocated_lbs` minus the weight already shipped on earlier shipments — else `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 422). Lots may be drawn two ways. When `lot_ids` is supplied, each named lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`), must not be `EXPIRED` (`ERR_LOT_EXPIRED`), and must be of the allocation line's product (`ERR_LOT_PRODUCT_MISMATCH`, HTTP 422). When `lot_ids` is omitted, the FIFO selector runs instead: eligible lots are the `AVAILABLE` lots of the allocation's product across all warehouses, ranked by `production_date` ascending with earlier `created_at` breaking ties; the selector walks that ranked list drawing from each lot the lesser of the remaining need and the lot's `current_weight_lbs` until the shipped weight is covered, and any lot drawn to zero moves to `DEPLETED`. If the total `AVAILABLE` weight of the product cannot cover `shipped_lbs`, the whole request is rejected with `ERR_INSUFFICIENT_SUPPLY` and nothing is decremented. A created shipment starts in `STAGING` status with `temp_compliance` `UNKNOWN`, with `min_temp_f_reading` and `max_temp_f_reading` null until the first reading, and with `rejection_reason` null; the drawn lots' weights are decremented as part of creation, and warehouse occupancy is recomputed.

Temperature surveillance runs on a second, parallel state axis that is independent of the shipment's `status`. Each reading a `WarehouseOperator` appends records the observed `reading_f` and its `recorded_at` timestamp, creating a `TemperatureReading` tied to the shipment through `shipment_id`, and immediately updates the shipment: `min_temp_f_reading` and `max_temp_f_reading` fold the new reading into the running minimum and maximum, and `temp_compliance` re-evaluates against the product's `required_temp_max_f`. A reading strictly greater than the ceiling moves the axis to `BREACHED` — from `UNKNOWN` or from `COMPLIANT` alike — while a reading less than or equal to the ceiling moves an `UNKNOWN` axis to `COMPLIANT`. A reading exactly equal to the ceiling therefore keeps or sets `COMPLIANT`; the breach comparison is strict. Once `BREACHED`, the axis is sticky: no later reading ever reverts it.

Departure, delivery, and rejection move the shipment's `status` axis through `STAGING`, `IN_TRANSIT`, `DELIVERED`, and `REJECTED_AT_RECEIVING`, with the latter two terminal. A `WarehouseOperator` departs a `STAGING` shipment — else `ERR_SHIPMENT_NOT_STAGING` — only after at least one temperature reading exists, else `ERR_NO_TEMPERATURE_READING`; departure moves the shipment to `IN_TRANSIT` and triggers a customer-exposure recompute that, per §2.10's desk policy, leaves the figure unchanged. At the destination dock the owning `CustomerRep` either accepts or refuses the load. Acceptance requires `IN_TRANSIT`, else `ERR_SHIPMENT_NOT_IN_TRANSIT`, and moves the shipment to `DELIVERED`: if the allocation is earmarked, the contract's `delivered_lbs` increases by the shipment's `shipped_lbs`, settling the contract automatically when the cumulative delivered weight reaches or exceeds `committed_lbs`; the allocation itself moves to `SHIPPED` when cumulative delivered weight reaches or exceeds its `allocated_lbs`; and the customer's exposure is recomputed with credit-hold release re-evaluated. Refusal likewise requires `IN_TRANSIT`, else `ERR_SHIPMENT_NOT_IN_TRANSIT`, records the payload's `rejection_reason`, and moves the shipment to `REJECTED_AT_RECEIVING`; a two-link cascade then fires — first, a returns lot is created at the shipment's source warehouse, of the same product as the shipment's allocation, with a system-minted `lot_code`, weight equal to `shipped_lbs`, `production_date` copied from the oldest lot drawn for the shipment, and status `QUARANTINED` with `quarantine_reason` `RETURNED_REJECTED`; second, that warehouse's occupancy is recomputed to account for the returned weight.

### 3.8. Claims, Negotiation, and Settlement

When a delivery goes wrong, the owning `CustomerRep` files a **claim** against the shipment, naming the `shipment_id`, a `claim_type` of `TEMPERATURE_ABUSE`, `SPEC_NONCONFORMANCE`, `WEIGHT_SHORTAGE`, or `QUALITY_DEFECT`, and the `claimed_amount_cents` the customer demands. The shipment must be `DELIVERED` or `REJECTED_AT_RECEIVING`, else `ERR_SHIPMENT_NOT_CLAIMABLE`. A `TEMPERATURE_ABUSE` claim additionally requires the shipment's `temp_compliance` axis to be `BREACHED`, else `ERR_CLAIM_TYPE_NOT_SUPPORTED` (HTTP 422). A filed claim starts in `FILED` status with `offer_round` at zero, `current_offer_cents` null, and `final_settlement_cents` null.

Filing immediately computes a provisional credit, `provisional_credit_cents`: the smaller of the `claimed_amount_cents` and a claim-type percentage of the shipment's value. The shipment's value is its `shipped_lbs` multiplied by the allocation's `unit_price_cents`. The percentage is sixty percent for `TEMPERATURE_ABUSE`, fifty percent for `SPEC_NONCONFORMANCE`, one hundred percent for `WEIGHT_SHORTAGE`, and forty percent for `QUALITY_DEFECT`; the percentage of shipped value is rounded half-up to whole cents before the minimum against the claimed amount is taken.

Negotiation then alternates between the `ClaimsAdjuster` and the customer, capped at three offers overall. The adjuster posts an offer by supplying `offer_cents` together with `expected_claim_version` per §2.9 — a stale version is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). An offer may be posted from `FILED`, from `COUNTERED`, or from `OFFER_MADE` itself, where the adjuster revises the offer before any customer response and the new offer supersedes the old; from any other status the request fails with `ERR_CLAIM_STATE_INVALID`, and once `offer_round` has reached three a further offer is rejected with `ERR_CLAIM_OFFER_LIMIT_EXCEEDED` (HTTP 422). Each posted offer increments `offer_round` by one, sets `current_offer_cents` to the payload's `offer_cents` — superseding any prior offer — moves the claim to `OFFER_MADE`, and increments the claim's `version`. The customer answers from `OFFER_MADE`. A counter, carrying `counter_amount_cents`, moves the claim to `COUNTERED` and increments its `version`; it is permitted only while `offer_round` remains below three, else `ERR_CLAIM_OFFER_LIMIT_EXCEEDED`, and from any status other than `OFFER_MADE` it fails with `ERR_CLAIM_STATE_INVALID`. A counter does not itself alter `current_offer_cents` or `offer_round`; the adjuster's next offer does both.

Three outcomes close a claim, all terminal. Acceptance by the owning `CustomerRep` requires `OFFER_MADE`, else `ERR_CLAIM_STATE_INVALID`, and moves the claim to `SETTLED_PAID`, computing `final_settlement_cents` at that moment: the shipment's value is again `shipped_lbs` times the allocation's `unit_price_cents`; the liability cap is eighty percent of that value, rounded half-up to whole cents; the base settlement is the smaller of `current_offer_cents` and the liability cap; and a flat freight allowance of 15000 cents is added only when the claim's `claim_type` is `TEMPERATURE_ABUSE` and the shipment's `temp_compliance` is `BREACHED`, with the allowance otherwise zero. The final settlement is the base plus the allowance. Acceptance then fires a two-link cascade: the customer's `outstanding_exposure_cents` is reduced by `final_settlement_cents` through the §2.10 recompute, and the credit-hold auto-release is re-evaluated from the lowered exposure. Denial by a `ClaimsAdjuster` is permitted from `OFFER_MADE` or `COUNTERED` — otherwise `ERR_CLAIM_STATE_INVALID` — and moves the claim to `SETTLED_DENIED` with no payment. Withdrawal by the owning `CustomerRep` is permitted from `FILED`, `OFFER_MADE`, or `COUNTERED` — otherwise `ERR_CLAIM_STATE_INVALID` — and moves the claim to `WITHDRAWN`.

### 3.9. Net Exposure Reporting

Risk officers, traders, and desk administrators watch the desk's hedging position through the exposure report, which answers one question per product-week: given a `product_id` and a `week_start` (an ISO Monday), how long or short is the desk? The report assembles four pound components. `physical_lbs` is the sum of `current_weight_lbs` over lots of the product in `AVAILABLE` status. `inbound_lbs` is the sum of `ordered_weight_lbs` over the product's purchase orders in `BOOKED` status. `forward_lbs` is the sum, over the product's `OPEN` forward contracts whose `delivery_week_start` equals the requested week, of each contract's `committed_lbs` minus its `delivered_lbs`. `spot_lbs` is the sum of `allocated_lbs` over `CONFIRMED` allocations whose line prices the product and whose line's sheet has `week_start_date` equal to the requested week. The net pound figure, `exposure_lbs`, is physical plus inbound minus forward minus spot. The basis price is the most recently published sheet's line price for the product under the §2.7 selector — zero when no such line exists — and `exposure_value_cents` is `exposure_lbs` multiplied by that basis price, rounded half-up to whole cents. The response carries `product_id`, `week_start`, the four components, `exposure_lbs`, and `exposure_value_cents`.

Because the components are live, several workflows already documented move the report without touching it directly: booking a purchase order adds to inbound, while cancelling one — manually or through supplier suspension — removes it; lot expiry removes physical pounds; contract default or cancellation removes forward pounds; and allocation confirmations and cancellations move spot pounds.

## 4. Endpoint Definitions

Operations that create a new resource — registering a supplier, customer, warehouse, product, or yield specification; drafting a price sheet, a sheet line, a purchase order, a fabrication batch, a forward contract, an allocation, a shipment, a claim, or an inspection certificate; and appending a temperature reading, which creates a `TemperatureReading` resource — return a `201 Created` status code. Operations that act on an existing resource without creating a new one — status transitions, publishes, closes, allocation runs, inspections, offers, counters, acceptances, denials, withdrawals, revocations, and the clock advance — return `200 OK`. Read endpoints return `200 OK`. Readers should reconstruct each operation's request payload and side effects from the §3 narratives; this table is deliberately a summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; runs the lot-expiry and contract-default sweeps | DeskAdmin |
| POST | `/api/suppliers` | Create supplier | DeskAdmin |
| GET | `/api/suppliers` | List suppliers | All roles |
| GET | `/api/suppliers/{supplierId}` | Get supplier | All roles |
| PUT | `/api/suppliers/{supplierId}/status` | Suspend or reinstate a supplier | DeskAdmin |
| POST | `/api/customers` | Create customer | DeskAdmin |
| GET | `/api/customers` | List customers | All roles |
| GET | `/api/customers/{customerId}` | Get customer, including computed exposure | All roles |
| POST | `/api/warehouses` | Create cold-storage warehouse | DeskAdmin |
| GET | `/api/warehouses` | List warehouses | All roles |
| GET | `/api/warehouses/{warehouseId}` | Get warehouse, including computed occupied_lbs | All roles |
| POST | `/api/products` | Create product (immutable configuration) | DeskAdmin |
| GET | `/api/products` | List products | All roles |
| GET | `/api/products/{productId}` | Get product | All roles |
| POST | `/api/yield-specs` | Create yield spec (immutable configuration) | DeskAdmin |
| GET | `/api/yield-specs` | List yield specs | All roles |
| GET | `/api/yield-specs/{yieldSpecId}` | Get yield spec | All roles |
| POST | `/api/price-sheets` | Create weekly price sheet in DRAFT | Trader |
| GET | `/api/price-sheets` | List price sheets | All roles |
| GET | `/api/price-sheets/{sheetId}` | Get price sheet | All roles |
| POST | `/api/price-sheets/{sheetId}/lines` | Add a line to a DRAFT sheet | Trader |
| GET | `/api/price-sheets/{sheetId}/lines` | List lines of a sheet | All roles |
| GET | `/api/price-sheet-lines` | List lines across sheets | All roles |
| GET | `/api/price-sheet-lines/{lineId}` | Get a line | All roles |
| POST | `/api/price-sheets/{sheetId}/publish` | Publish a DRAFT sheet (market epoch advance) | DeskAdmin |
| POST | `/api/price-sheets/{sheetId}/close` | Close a PUBLISHED sheet or discard a DRAFT sheet | DeskAdmin |
| POST | `/api/price-sheets/{sheetId}/run-allocation` | Run the allocation waterfall over the sheet's REQUESTED allocations | RiskOfficer |
| POST | `/api/purchase-orders` | Book a carcass/primal purchase; computes estimated cutout | Trader |
| GET | `/api/purchase-orders` | List purchase orders | All roles |
| GET | `/api/purchase-orders/{poId}` | Get purchase order | All roles |
| POST | `/api/purchase-orders/{poId}/receive` | Receive against a BOOKED purchase order; creates the inventory lot | WarehouseOperator |
| POST | `/api/purchase-orders/{poId}/cancel` | Cancel a BOOKED purchase order | Trader |
| GET | `/api/inventory-lots` | List lots with filters | All roles |
| GET | `/api/inventory-lots/{lotId}` | Get lot, including age_days and unit_value_cents_per_lb | All roles |
| POST | `/api/inventory-lots/{lotId}/inspect` | Record trim/fat inspection; routes lot AVAILABLE or QUARANTINED | QualityGrader |
| POST | `/api/inventory-lots/{lotId}/quarantine` | Manually quarantine an AVAILABLE lot (USDA hold) | QualityGrader |
| POST | `/api/inventory-lots/{lotId}/release` | Release a QUARANTINED lot back to AVAILABLE | QualityGrader |
| POST | `/api/fabrication-batches` | Draft a fabrication batch converting a carcass lot | WarehouseOperator |
| GET | `/api/fabrication-batches` | List fabrication batches | All roles |
| GET | `/api/fabrication-batches/{batchId}` | Get fabrication batch | All roles |
| POST | `/api/fabrication-batches/{batchId}/post` | Post the batch: consume the input lot, create output lots | WarehouseOperator |
| POST | `/api/fabrication-batches/{batchId}/void` | Void a DRAFT or POSTED batch with untouched outputs | DeskAdmin |
| POST | `/api/forward-contracts` | Create a forward contract | Trader |
| GET | `/api/forward-contracts` | List forward contracts | All roles |
| GET | `/api/forward-contracts/{contractId}` | Get forward contract | All roles |
| POST | `/api/forward-contracts/{contractId}/amend` | Amend terms of an OPEN contract (OCC-guarded) | Trader |
| POST | `/api/forward-contracts/{contractId}/cancel` | Cancel an OPEN contract with no CONFIRMED earmarked allocations | RiskOfficer |
| POST | `/api/allocations` | Customer requests a weekly allocation | CustomerRep |
| GET | `/api/allocations` | List allocations | All roles |
| GET | `/api/allocations/{allocationId}` | Get allocation | All roles |
| POST | `/api/allocations/{allocationId}/cancel` | Cancel a REQUESTED allocation, or a CONFIRMED one with no open shipments | CustomerRep |
| POST | `/api/shipments` | Load-out against a CONFIRMED allocation (LTL) | WarehouseOperator |
| GET | `/api/shipments` | List shipments | All roles |
| GET | `/api/shipments/{shipmentId}` | Get shipment | All roles |
| POST | `/api/shipments/{shipmentId}/temperature-readings` | Append a temperature reading; updates min/max and the temp_compliance axis | WarehouseOperator |
| GET | `/api/shipments/{id}/temperature-readings` | List readings of a shipment | All roles |
| POST | `/api/shipments/{shipmentId}/depart` | Depart a STAGING shipment (requires at least one temperature reading) | WarehouseOperator |
| POST | `/api/shipments/{shipmentId}/deliver` | Customer receiving accepts the shipment | CustomerRep |
| POST | `/api/shipments/{shipmentId}/reject` | Customer rejects at the receiving dock | CustomerRep |
| POST | `/api/claims` | Customer files a claim on a delivered/rejected shipment; provisional credit computed | CustomerRep |
| GET | `/api/claims` | List claims | All roles |
| GET | `/api/claims/{claimId}` | Get claim | All roles |
| POST | `/api/claims/{claimId}/offers` | Adjuster posts a settlement offer (OCC-guarded, supersedes prior offer) | ClaimsAdjuster |
| POST | `/api/claims/{claimId}/counter` | Customer counters the current offer | CustomerRep |
| POST | `/api/claims/{claimId}/accept` | Customer accepts the current offer; final settlement computed | CustomerRep |
| POST | `/api/claims/{claimId}/deny` | Adjuster denies the claim | ClaimsAdjuster |
| POST | `/api/claims/{claimId}/withdraw` | Customer withdraws the claim | CustomerRep |
| POST | `/api/inspection-certificates` | Issue a USDA grading/inspection certificate for a lot | QualityGrader |
| GET | `/api/inspection-certificates` | List certificates | All roles |
| GET | `/api/inspection-certificates/{certId}` | Get certificate | All roles |
| POST | `/api/inspection-certificates/{certId}/revoke` | Revoke a certificate; grade-revert cascades | QualityGrader |
| GET | `/api/exposure` | Hedging exposure report for a product-week | DeskAdmin, Trader, RiskOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is only the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PRICE_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_PRICE_SHEET_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_YIELD_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_PURCHASE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_FABRICATION_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_FORWARD_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SUPPLIER_SUSPENDED` | 409 Conflict |
| `ERR_PRICE_SHEET_NOT_DRAFT` | 409 Conflict |
| `ERR_PRICE_SHEET_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PO_NOT_BOOKED` | 409 Conflict |
| `ERR_LOT_NOT_IN_INSPECTION` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_BATCH_NOT_DRAFT` | 409 Conflict |
| `ERR_BATCH_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_OPEN` | 409 Conflict |
| `ERR_CONTRACT_HAS_CONFIRMED_ALLOCATIONS` | 409 Conflict |
| `ERR_ALLOCATION_NOT_REQUESTED` | 409 Conflict |
| `ERR_ALLOCATION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_STAGING` | 409 Conflict |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_CLAIM_STATE_INVALID` | 409 Conflict |
| `ERR_CERTIFICATE_ALREADY_REVOKED` | 409 Conflict |
| `ERR_PRICE_SHEET_WEEK_CONFLICT` | 409 Conflict |
| `ERR_SHEET_HAS_NO_LINES` | 409 Conflict |
| `ERR_MASS_BALANCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SHIPMENT_EXCEEDS_ALLOCATION` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_SUPPLY` | 409 Conflict |
| `ERR_NO_TEMPERATURE_READING` | 409 Conflict |
| `ERR_CLAIM_TYPE_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_CLAIM_OFFER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_WEEK_START` | 422 Unprocessable Entity |
| `ERR_FORWARD_WEEK_PASSED` | 422 Unprocessable Entity |
| `ERR_PRODUCTION_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_PRODUCT_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LOT_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORWARD_CONTRACT_WEEK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
