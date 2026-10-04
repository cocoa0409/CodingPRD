# No-Haggle Auto Retail API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a no-haggle used-vehicle retail platform in the style of a national car superstore operator. The platform orchestrates the entire commercial lifecycle of a used vehicle across a network of stores: a customer-facing standing appraisal offer that holds regardless of whether the customer buys anything, a reconditioning pipeline with formal inspection and disposition between retail and wholesale channels, an algorithmic no-negotiation pricing engine that reprices inventory as it ages, customer-paid inter-store transfers with hold periods, financing offers from a fixed panel of lenders presented simultaneously, and a liberal return policy backed by a full accounting-reversal waterfall.

Two design principles dominate the domain. First, **no-haggle pricing**: list prices are system-computed, never negotiated, never client-supplied, and associate compensation is deliberately decoupled from vehicle price to remove any incentive to steer or haggle. Second, **segregation of duties**: the associate who appraises a vehicle may not inspect it, and the associate who sells a vehicle may not also act as its finance approver. The system enforces both principles at the API layer, with state-machine, optimistic-concurrency, and role-based controls described below.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level, system-wide rules that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifies the acting principal and `X-User-Role` names their operational role. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

The system recognizes eight roles: `PlatformAdmin`, `StoreManager`, `Appraiser`, `ReconditioningInspector`, `SalesAssociate`, `FinanceManager`, `AuctionManager`, and `Customer`.

Identity is resolved in one of two ways:

- When `X-User-Role` is `StoreManager`, `Appraiser`, `ReconditioningInspector`, `SalesAssociate`, or `FinanceManager`, `X-User-ID` is the `id` of the acting `Associate` record; the associate's `role_kind` field gates which role's operations the associate may perform (`MANAGER` for `StoreManager`, `APPRAISER` for `Appraiser`, `INSPECTOR` for `ReconditioningInspector`, `SALES` for `SalesAssociate`, `FINANCE` for `FinanceManager`); an associate whose `role_kind` does not match the presented `X-User-Role` is likewise rejected with `ERR_UNKNOWN_IDENTITY`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on customer-owned resources (transfer requests, returns, financing acceptances) compare the resource's `customer_id` to `X-User-ID`, and an ownership mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`. Customer-role read access is ownership-restricted only on the customer record itself (`GET /v1/customers/{id}`) and on a sale (`GET /v1/sales/{id}` — mismatches are likewise rejected with `ERR_UNAUTHORIZED_ROLE`); the other Customer-readable GET endpoints are not ownership-filtered. For these six entity-backed roles, an `X-User-ID` that does not reference an existing backing entity is rejected with `ERR_UNKNOWN_IDENTITY`.
- When `X-User-Role` is `PlatformAdmin` or `AuctionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00Z",
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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp at second precision (form `YYYY-MM-DDTHH:MM:SSZ`, matching the canonical clock format of §2.5).
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00Z"
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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. A `limit` or `offset` that is not a non-negative integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION`. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Individual list endpoints also accept equality filters on resource fields: store ledger entries filter by `entry_kind`; associates by `store_id` and `role_kind`; vehicles by `current_store_id`, `lifecycle_status`, and `hold_status`; appraisals by `customer_id`, `appraiser_id`, and `status`; inspections by `inspector_id` and `status`; transfer requests by `customer_id`, `from_store_id`, `to_store_id`, `supersedes_request_id`, and `status`; sales by `vehicle_id`, `customer_id`, `associate_id`, `store_id`, `trade_in_appraisal_id`, and `status`; financing applications by `customer_id` and `status`; returns by `sale_id` and `status`; auction lots by `status`. Unrecognized query parameters are ignored.

### 2.4. Common Resource Properties

Every primary resource — `Store`, `CustomerAccount`, `Associate`, `Vehicle`, `Appraisal`, `ReconditioningInspection`, `TransferRequest`, `Sale`, `FinancingApplication`, `ReturnRequest`, and `AuctionLot` — carries a standard set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp at second precision (form `YYYY-MM-DDTHH:MM:SSZ`) recording when the resource was first persisted.
- `updated_at`: an ISO 8601 UTC timestamp at the same second precision, refreshed on every mutation.
- `version`: an integer incremented by exactly one on every mutation, serving as the basis for optimistic concurrency control.

Three resources are lighter-weight and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent: `RepairLineItem`, `PricingEvent`, and `LedgerEntry`. `LenderOffer` is likewise lightweight, carrying only `id` and `created_at`. This convention provides a consistent audit trail while keeping ledger and event records append-only.

### 2.5. The Logical Clock

All temporal reasoning in the system — appraisal validity windows, transfer hold expiry, financing offer expiry, and days-in-inventory aging — is driven by a **logical clock**, never by wall-clock time. Before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time. A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant via an admin-only test-driving capability; the response reports the new `current_utc`. Advancing the clock re-evaluates every pending automatic transition: an `ACTIVE` appraisal whose `valid_until` has passed becomes `EXPIRED`; a `DELIVERED` transfer request whose `hold_expires_at` has passed becomes `HOLD_EXPIRED`; and a financing application whose offers have outlived their validity window becomes `EXPIRED`.

### 2.6. Monetary Values and Precision

All monetary amounts are integer cents. Wherever a calculation produces a fractional cent, the final step of that calculation rounds **half-up** to a whole cent; intermediate values are carried at full precision unless a specific rule pins per-step rounding. Score-like quantities (notably the financing credit score) are computed to four decimal places, also rounded half-up, before any threshold comparison.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and only those two:

- Creating a customer transfer request requires the request body to carry `expected_vehicle_version` holding the `version` of the target `Vehicle` as the client last observed it. If the vehicle's current `version` no longer matches — because another writer has since mutated the vehicle (a repricing run, a hold placement, a store move from a delivered transfer) — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the vehicle's availability and price.
- Applying a scheduled algorithmic markdown to a vehicle likewise requires `expected_vehicle_version` matching the vehicle's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the pricing run to re-read the vehicle and recompute against fresh state.

Endpoints not listed here do not take a version field at all.

### 2.8. Validation Order and Error Selection

When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order, and the first failing rule determines the error returned:

1. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Entity-backed identity resolution (`ERR_UNKNOWN_IDENTITY`).
4. Existence of path- and body-referenced resources, validated left-to-right — store, then vehicle, then appraisal, inspection, lot, sale, application, return, and transfer as applicable (`ERR_NOT_FOUND`).
5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`, except where a workflow section names a more specific error (notably, sale creation against a vehicle that is not `RETAIL_LISTED`, or that is held for another customer's transfer, yields `ERR_CROSS_ENTITY_STATE` per §3.5).
6. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
7. Field shape and uniqueness (`ERR_VALIDATION`), including hammer-price positivity on auction close (`ERR_HAMMER_BELOW_RESERVE_INVALID`).
8. Temporal windows (`ERR_WINDOW_CLOSED` family, with state-aware sub-codes: an expired appraisal surfaces as `ERR_APPRAISAL_EXPIRED`, a closed return window as `ERR_RETURN_WINDOW_CLOSED`, and a transfer fulfilment past hold expiry as `ERR_WINDOW_CLOSED`).
9. Cross-entity referential rules (`ERR_CROSS_ENTITY_STATE` family, again with state-aware sub-codes such as `ERR_APPRAISAL_NOT_ACTIVE`, `ERR_APPRAISAL_CUSTOMER_MISMATCH`, `ERR_OFFER_NOT_PRESENTED`, and `ERR_FINANCING_DECLINED`).
10. Aggregate and collection rules (`ERR_AGGREGATE_RULE`).
11. Fiscal rules (`ERR_FISCAL_RULE`), including the optimistic-concurrency version match where declared.
12. Stale optimistic-concurrency version (`ERR_STALE_VERSION`).

One consequence of this ordering: a financing offer that has passed its validity window is unreachable through the temporal rule, because the clock's automatic transition moves the application to `EXPIRED` first, and a subsequent accept then fails the priority-5 state check with `ERR_INVALID_STATE`.

### 2.9. Segregation of Duties

Two independence rules are enforced wherever personnel references cross:

- The `inspector_id` on a newly opened reconditioning inspection must differ from the `appraiser_id` of the vehicle's latest sourcing appraisal — the newest non-terminal appraisal on that vehicle. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.
- On any sale, the selling associate and the finance approver must be different people: the associate referenced by a financing application on a sale must differ from the sale's selling associate, with violations likewise rejected as `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. The Ledger

Every financially meaningful event posts one or more `LedgerEntry` records onto a store's books. Each entry carries an `entry_kind`, a signed `amount_cents` (positive for a receivable or asset, negative for a payable or refund), a polymorphic reference composed of `ref_entity` (one of `Sale`, `TransferRequest`, `ReturnRequest`, or `AuctionLot`) and `ref_id` identifying the source record, and the `store_id` of the store whose books carry the entry. The recognized entry kinds are `SALE_REVENUE`, `TRADE_IN_PAYABLE`, `TRANSFER_FEE`, `TRANSFER_FEE_REFUND`, `COMMISSION_ACCRUAL`, `COMMISSION_CLAWBACK`, `REFUND_PAYABLE`, `LENDER_REVERSAL`, and `AUCTION_PROCEEDS`. Ledger entries are append-only; corrections are expressed as new, opposite-signed entries, never as edits.

### 2.11. Store Lifecycle and Regions

A `Store` is identified by a unique `store_code` (for example, `PHX-01`) and a human-readable `display_name`. Each store belongs to a `region` — `WEST`, `CENTRAL`, or `EAST` — which determines the transfer lane band for shipping-fee calculation. A store's `retail_threshold_pct` (default 0.20, expressed as a fraction of appraisal value) sets the reconditioning-cost ceiling beyond which a vehicle is forced to wholesale disposition, and its `transfer_hold_days` (default 7) sets how long a customer-paid transfer hold keeps a vehicle off the open market at the destination store. `retail_threshold_pct` must be a JSON number and `transfer_hold_days` a non-negative integer, or store creation fails validation with `ERR_VALIDATION`. Stores are created with `status` `ACTIVE`; a `CLOSED` store rejects all new operations — vehicle intake at a `CLOSED` store is rejected with `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Vehicle Intake and the Standing Appraisal Offer

A `StoreManager` intakes a vehicle by supplying its `vin` (a 17-character identifier unique across all vehicles), `make`, `model`, `model_year` (between 1990 and 2027 inclusive), `odometer_miles` (zero or greater), `book_value_cents` (the wholesale book value at intake, strictly positive), and `current_store_id`. The vehicle begins life with `lifecycle_status` `INTAKE`, `hold_status` `NONE`, `condition_grade` `UNGRADED`, `recon_cost_total_cents` zero, and `inventory_acquired_at` stamped to the current logical time. Its `days_in_inventory` is derived, never stored as input: it is the whole number of days elapsed since `inventory_acquired_at`, recomputed on every read and on every repricing run.

From `INTAKE`, an `Appraiser` creates a standing **appraisal offer** by referencing the `vehicle_id`, the `customer_id` of the offer's owner, and their own `appraiser_id` — which must name an `ACTIVE` associate whose `role_kind` is `APPRAISER` (any other value fails validation with `ERR_VALIDATION`) and must equal the acting `X-User-ID` (a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`). Creation moves the vehicle from `INTAKE` to `APPRAISED` and computes a `provisional_offer_cents`. The new appraisal begins in `PENDING_INSPECTION` status with `final_offer_cents`, `valid_from`, and `valid_until` unset (null). A vehicle already in `APPRAISED` whose prior appraisal has reached a terminal state and which never entered inspection may be re-appraised — in that case the vehicle remains `APPRAISED` unchanged; but if any non-terminal appraisal (one in `PENDING_INSPECTION` or `ACTIVE`) still exists for the vehicle, a second appraisal is rejected with `ERR_CROSS_ENTITY_STATE`. An appraisal attempt against a vehicle in any other lifecycle state is rejected with `ERR_INVALID_STATE`.

The provisional offer starts from the vehicle's `book_value_cents`, subtracts eight hundred dollars (`80000` cents) for each full model-year of age (the age in years being the current logical year minus `model_year`, never less than zero), and subtracts fifteen dollars (`1500` cents) for each whole block of one thousand miles by which the odometer exceeds an allowance of twelve thousand miles per year of age (the excess itself never less than zero). The result is floored at five hundred dollars (`50000` cents) and rounded half-up to whole cents only at the final step.

The offer is **standing**: once activated, it is redeemable at any store until its validity expires, regardless of whether the customer buys anything. An `Appraiser` may void an `ACTIVE` offer; a `StoreManager` may do the same. Voiding an offer that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. When the acting role is `Appraiser`, voiding is restricted to the appraiser who issued the offer — the acting `appraiser_id` must equal the appraisal's `appraiser_id`, and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE` — whereas a `StoreManager` may void any active offer. Voiding sets the appraisal's `status` to `VOIDED`.

A `PlatformAdmin` registers a `CustomerAccount` with the customer's `full_name` (legal name), a unique `email`, a `credit_score` between 300 and 850 inclusive, and a `stated_annual_income_cents` (self-reported, zero or greater). The credit score and stated income feed the financing tier scoring of §3.6. A customer may read only their own record.

### 3.2. Inspection, Repair Lines, and the Retail-versus-Wholesale Decision

A `ReconditioningInspector` opens a reconditioning inspection on a vehicle in `APPRAISED` (or, after a return, in `RETURNED` — see §3.7) by supplying an `inspector_id`; the inspector must name an `ACTIVE` associate whose `role_kind` is `INSPECTOR` (otherwise `ERR_VALIDATION`) and must equal the acting `X-User-ID` (otherwise `ERR_UNAUTHORIZED_ROLE`). Opening an inspection on a `RETURNED` vehicle additionally requires its `hold_status` to be `RETURN_REVIEW_HOLD` (otherwise `ERR_INVALID_STATE`), and opening on a vehicle in any other lifecycle state is likewise `ERR_INVALID_STATE`. The new inspection's `status` is `OPEN`, its `opened_at` is stamped to the logical clock, and its `disposition` begins `UNDECIDED`. Opening moves the vehicle from `APPRAISED` to `IN_INSPECTION` and resets its `recon_cost_total_cents` to zero. The segregation-of-duties rule of §2.9 applies: the inspector must not be the appraiser who sourced the vehicle. Only one `OPEN` inspection may exist per vehicle; a second attempt is rejected with `ERR_INSPECTION_ALREADY_OPEN`. A `StoreManager` may cancel an `OPEN` inspection while the vehicle is `IN_INSPECTION`; cancellation moves the inspection to `CANCELLED` and compensates by reverting the vehicle to `APPRAISED`.

While the inspection is `OPEN`, the inspector adds repair line items against its `inspection_id`, each with a `category` — `MECHANICAL`, `BODY`, `COSMETIC`, or `SAFETY` — and a `cost_cents` strictly greater than zero. Line items may be added or the inspection completed only by the inspector who opened it — the acting `X-User-ID` must equal the inspection's `inspector_id`, else `ERR_UNAUTHORIZED_ROLE` — while approval or rejection of a line item may be performed by any `ReconditioningInspector`. Adding a line item, approving or rejecting one, completing, or cancelling an inspection that is not `OPEN` is rejected with `ERR_INVALID_STATE`, as is approving or rejecting a line item that is not `PROPOSED`. Each line begins `PROPOSED` and is individually approved or rejected; both actions recompute the inspection's `estimated_repair_total_cents`, which is always the sum of `cost_cents` over line items whose `line_status` is not `REJECTED`.

Completion is allowed only when no line item remains `PROPOSED`; otherwise the attempt is rejected with `ERR_LINE_ITEMS_UNRESOLVED`. At completion the system computes the disposition. First it recomputes the provisional appraisal offer for the vehicle at completion time — book value, age depreciation, and mileage depreciation exactly as in §3.1, with no reconditioning haircut — and takes the `retail_threshold_pct` fraction of the store the vehicle currently sits at (its `current_store_id`) of that figure, rounded down to whole cents, as the threshold. If the inspection's `estimated_repair_total_cents` is **strictly greater** than that threshold, the disposition is `WHOLESALE`; otherwise (including exact equality with the threshold) it is `RETAIL`.

A `RETAIL` disposition also assigns the vehicle's `condition_grade`: `A` when the estimated repair total is exactly zero, `B` when it is positive but no more than half the threshold (rounded down), and `C` otherwise. The vehicle's `recon_cost_total_cents` is set to the inspection's `estimated_repair_total_cents`, the vehicle moves to `RECON`, and the sourcing appraisal is activated — its `status` moves from `PENDING_INSPECTION` to `ACTIVE`, its `final_offer_cents` is computed, and `valid_from` / `valid_until` are stamped. The final offer equals the provisional offer minus one half of the vehicle's `recon_cost_total_cents` (that is, fifty percent of the just-completed inspection's estimated repair total), again floored at five hundred dollars and rounded half-up to whole cents at the final step; `valid_until` is exactly seven days after `valid_from`. A `WHOLESALE` disposition instead sets `condition_grade` to `WHOLESALE_ONLY` and moves the vehicle to `WHOLESALE_PENDING` — but the standing offer is still issued: the sourcing appraisal transitions to `ACTIVE` with its final offer computed exactly as above.

Once an appraisal is `ACTIVE`, the clock governs its end. When the logical clock reaches or passes `valid_until`, the appraisal becomes `EXPIRED`; the same `EXPIRED` outcome is applied lazily whenever the appraisal is read or a redemption is attempted at or after `valid_until`.

### 3.3. Listing and Algorithmic No-Haggle Repricing

A `StoreManager` lists a vehicle that is in `RECON` with `hold_status` `NONE`; a listing attempt in any other state or hold condition is rejected with `ERR_INVALID_STATE`, as is a listing attempt when no appraisal on the vehicle has a computed `final_offer_cents`. Listing moves the vehicle to `RETAIL_LISTED`, writes a `PricingEvent` of `trigger_kind` `INITIAL_LISTING` (whose `old_price_cents` is null and whose `new_price_cents` records the computed price, along with `days_in_inventory_at_event` capturing the vehicle's age at that moment), and sets `current_list_price_cents` for the first time. The initial list price is the sourcing appraisal's `final_offer_cents` marked up by twelve percent — that is, multiplied by 112 and divided by 100 — rounded half-up to whole cents. This is the no-haggle price: it is system-computed, never negotiable, and never supplied by a client.

Thereafter the price moves only through scheduled markdowns. A `StoreManager` applies a pricing event to a `RETAIL_LISTED` vehicle with `hold_status` `NONE`; the request must carry `expected_vehicle_version` per §2.7. The markdown tier is chosen by the vehicle's `days_in_inventory` at run time: fewer than 30 days yields no change; at least 30 but fewer than 45 days yields a three-percent markdown; at least 45 but fewer than 60 days yields five percent; 60 days or more yields eight percent. A single run applies exactly one tier — tiers never stack within one event. Even the no-change tier counts as an applied pricing event: the run still writes a `PricingEvent` recording the (unchanged) price and still increments the vehicle's `version`. The new price is the current list price multiplied by one hundred minus the tier percentage, divided by one hundred, rounded half-up to whole cents **per event** (each event re-rounds from the current price; unrounded intermediates are never carried across events, so successive markdowns compose multiplicatively). The result is floored at the sourcing appraisal's `final_offer_cents` — the system never lists below the acquisition offer. Each markdown writes a `PricingEvent` with `trigger_kind` `SCHEDULED_MARKDOWN` (or `REPRICING_RUN` when applied by a bulk repricing run), updates `current_list_price_cents`, and increments the vehicle's `version`.

### 3.4. Inter-Store Transfer with Customer-Paid Hold

A `Customer` who wants a specific vehicle shipped to another store creates a transfer request naming the `vehicle_id`, their own `customer_id`, the destination `to_store_id`, an optional `expedited` flag (default false), an optional `supersedes_request_id` chaining a re-booking after a previously cancelled request on the same vehicle, and the OCC field `expected_vehicle_version` (§2.7). The vehicle must be `RETAIL_LISTED` — a request against a vehicle in any other lifecycle state is rejected with `ERR_VEHICLE_NOT_LISTED` — and its `hold_status` must be `NONE`; a request against an already-held vehicle is rejected with `ERR_VEHICLE_ALREADY_HELD`. The destination store must differ from the vehicle's current store, or the request fails validation with `ERR_VALIDATION`. When `supersedes_request_id` is supplied, the referenced request must exist (`ERR_NOT_FOUND` otherwise), must belong to the same vehicle, and must be in `CANCELLED` status; a supersession reference that names a request for a different vehicle or one not `CANCELLED` fails with `ERR_VALIDATION`. These request-shape checks — destination difference and supersession validity — are evaluated before the vehicle state and hold checks below.

Creation snapshots the vehicle's `current_store_id` into `from_store_id`, computes `shipping_fee_cents` (immutable thereafter), sets the vehicle's `hold_status` to `TRANSFER_HOLD` — removing it from open-market sale eligibility — and increments the vehicle's `version`. The shipping fee depends on the lane band between the origin and destination store regions: same region is band 0 at one hundred fifty dollars (`15000` cents); adjacent regions (`WEST`–`CENTRAL` or `CENTRAL`–`EAST`) are band 1 at four hundred fifty dollars (`45000` cents); cross-country (`WEST`–`EAST`) is band 2 at nine hundred dollars (`90000` cents). If `expedited` is set, the band base is multiplied by three and divided by two (a 1.5× multiplier), rounded half-up to whole cents. Finally, if the vehicle is nearly new — its `model_year` is at least the current logical year minus one — an enclosed-carrier surcharge of two hundred dollars (`20000` cents) is added.

The request begins in `REQUESTED`. The customer — and only that customer, matched by `customer_id` — pays the fee, moving the request to `FEE_PAID` and posting a `TRANSFER_FEE` ledger entry for `shipping_fee_cents` at the destination store's books; payment is refused with `ERR_VEHICLE_NO_LONGER_AVAILABLE` if the vehicle has meanwhile left `RETAIL_LISTED`. A `StoreManager` at the origin store ships the vehicle (`FEE_PAID` → `IN_TRANSIT`); a `StoreManager` at the destination store confirms delivery (`IN_TRANSIT` → `DELIVERED`). The store scoping is enforced against the acting manager's home store: a shipping attempt by a manager whose store is not the origin store, or a delivery confirmation by a manager whose store is not the destination store, is rejected with `ERR_UNAUTHORIZED_ROLE`. Delivery moves the vehicle's `current_store_id` to the destination store, sets `hold_expires_at` to the delivery instant plus the destination store's `transfer_hold_days`, and increments the vehicle's `version`. While the hold is active the vehicle is reserved for the requester.

Three endings are possible from `DELIVERED`. If the requester buys the vehicle before `hold_expires_at`, the sale completion cascade (§3.5) moves the request to `FULFILLED`, clears the hold, and sells the vehicle. If the clock reaches `hold_expires_at` first, the request becomes `HOLD_EXPIRED`: the hold is cleared, the vehicle's `version` increments, the vehicle — still `RETAIL_LISTED` — returns to the open market at the destination store, and the shipping fee is **not** refunded. The hold release on expiry is conditional on the vehicle still being `RETAIL_LISTED`; if it was somehow sold meanwhile, the hold field is simply cleared.

The customer may cancel from `REQUESTED`, `FEE_PAID`, or `IN_TRANSIT`. Cancelling from `REQUESTED` just clears the hold and increments the vehicle's `version`. Cancelling from `FEE_PAID` additionally refunds the full fee via a `TRANSFER_FEE_REFUND` ledger entry of `shipping_fee_cents` at the destination store. Cancelling from `IN_TRANSIT` refunds half the fee — half of `shipping_fee_cents`, rounded half-up — as a `TRANSFER_FEE_REFUND` entry, retaining the other half as restocking; the vehicle remains at the origin store and its hold is cleared.

### 3.5. The No-Haggle Sale

A `SalesAssociate` opens a sale by supplying the `vehicle_id`, the buyer's `customer_id`, their own `associate_id` (an associate whose `role_kind` is `SALES` and whose `status` is `ACTIVE`, failing `ERR_VALIDATION` otherwise) — the `associate_id` must equal the acting `X-User-ID`, else `ERR_UNAUTHORIZED_ROLE` — and optionally a `trade_in_appraisal_id`. The vehicle must be `RETAIL_LISTED` at its current store and unheld — a sale against a vehicle not `RETAIL_LISTED`, or one held for someone else's transfer, is rejected with `ERR_CROSS_ENTITY_STATE` (with the transfer-hold exception described below). The sale's `store_id` is snapshotted from the vehicle's location. The sale begins `PENDING_FINANCE` with `sale_price_cents` taken from the vehicle's `current_list_price_cents` — never client-supplied; a price field supplied in the request body is ignored (the request is not rejected on that account) and the system-computed price is snapshotted — and `amount_due_cents` equal to `sale_price_cents` minus `trade_in_credit_cents`, floored at zero.

When a trade-in appraisal is attached, it must be `ACTIVE`; a trade-in appraisal in `PENDING_INSPECTION`, `REDEEMED`, or `VOIDED` status is rejected with `ERR_APPRAISAL_NOT_ACTIVE`, while one already `EXPIRED` (or past `valid_until`) is rejected with `ERR_APPRAISAL_EXPIRED`. The appraisal must also belong to the buyer — its `customer_id` must equal the sale's `customer_id` — or the sale is rejected with `ERR_APPRAISAL_CUSTOMER_MISMATCH`. When present, `trade_in_credit_cents` equals the appraisal's `final_offer_cents`; otherwise it is zero.

Completion is the pivotal moment. A `SalesAssociate` completes a `PENDING_FINANCE` sale — and only the selling associate on the sale may complete it, a mismatch being rejected with `ERR_UNAUTHORIZED_ROLE` — only when its financing posture is settled: either no financing application exists for the sale (a cash deal), or the application is `ACCEPTED`; completing with an application in any other state is rejected with `ERR_FINANCING_NOT_ACCEPTED`. Completing when the vehicle has meanwhile left `RETAIL_LISTED` is rejected with `ERR_INVALID_STATE`. The `sale_price_cents` is recomputed from the vehicle's `current_list_price_cents` at completion time, and `amount_due_cents` is recomputed alongside it as the new `sale_price_cents` minus `trade_in_credit_cents`, floored at zero. Completion stamps `completed_at`, moves the sale to `COMPLETED`, and fires a multi-hop cascade:

- The vehicle moves from `RETAIL_LISTED` to `SOLD`. For this to be permitted, the vehicle's `hold_status` must be `NONE` — or the hold must belong to this buyer's own `DELIVERED` transfer request being fulfilled by this very sale (if the vehicle is held but no such request exists for this buyer, completion is rejected with `ERR_VEHICLE_ALREADY_HELD`). In the latter case, completing before `hold_expires_at` clears the hold, moves the transfer request to `FULFILLED`, and then sells the vehicle; if the hold has already lapsed, the request must first have transitioned to `HOLD_EXPIRED`, and completing against it is rejected with `ERR_WINDOW_CLOSED`.
- A `SALE_REVENUE` ledger entry of `sale_price_cents` posts at the sale store.
- When a trade-in is redeemed, a `TRADE_IN_PAYABLE` entry of negative `trade_in_credit_cents` posts, the appraisal moves from `ACTIVE` to `REDEEMED`, and the trade-in vehicle enters inventory at the sale store as a fresh `INTAKE` acquisition — a system-driven re-entry that bypasses the usual appraisal-first trigger.
- A `COMMISSION_ACCRUAL` entry posts the selling associate's `flat_commission_cents`.

A pending sale may instead be cancelled by a `SalesAssociate` — only the selling associate on the sale, a mismatch being rejected with `ERR_UNAUTHORIZED_ROLE` — provided no completed financing disbursement exists; cancellation moves the sale to `CANCELLED` and transitions any `SUBMITTED` or `OFFERS_PRESENTED` financing application attached to it to `WITHDRAWN`, superseding that application's `PRESENTED` offers.

### 3.6. Financing: One Panel, Three Lenders, Presented at Once

A `FinanceManager` submits a financing application against a `PENDING_FINANCE` sale by referencing the `sale_id`; a submission against a sale in any other status is rejected with `ERR_INVALID_STATE`, and a submission while the sale already has an application in `SUBMITTED` or `OFFERS_PRESENTED` status is likewise rejected with `ERR_INVALID_STATE`. The segregation-of-duties rule applies: the finance manager must not be the selling associate on the same sale. The application copies `customer_id` from the sale and snapshots `requested_amount_cents` from the sale's `amount_due_cents` at submission. Scoring happens immediately and sets the application's computed `approval_tier`. The customer's `credit_score` (between 300 and 850 inclusive) is normalized by subtracting 300 and dividing by 550. A debt-to-income ratio is formed by dividing the sale's `amount_due_cents` by the customer's `stated_annual_income_cents` (with a denominator of at least 1); the normalized DTI is one minus the ratio divided by a cap of 0.5, clamped to never fall below zero. The final score is seven-tenths of the normalized credit plus three-tenths of the normalized DTI, computed to four decimal places with round-half-up before any comparison. A score of at least 0.8000 earns `TIER_1`; at least 0.6000 earns `TIER_2`; at least 0.4000 earns `TIER_3`; anything lower is `DECLINED`.

For a non-declined tier the system immediately creates the full lender panel — three `LenderOffer` rows, one each for `LENDER_A`, `LENDER_B`, and `LENDER_C`, all in `PRESENTED` status, within the same submission call (the submission response body itself carries the application object; the offers are retrievable via the application's offers endpoint); the application moves from `SUBMITTED` to `OFFERS_PRESENTED`. The whole panel is always presented at one time; offers are never drip-fed. Each offer references its application via `application_id`, carries an `apr_bps` annual percentage rate in basis points, and sets its `max_amount_cents` equal to `requested_amount_cents` — every lender funds the full request at its own tier rate. The rate per lender and tier is: `LENDER_A` offers 490, 690, or 990 for tiers one through three; `LENDER_B` offers 515, 740, or 1040; `LENDER_C` offers 540, 780, or 1090. Each offer's `offer_status` begins at `PRESENTED` and ends at `ACCEPTED` or `SUPERSEDED`. A `DECLINED` application creates zero offers and remains `SUBMITTED` until withdrawn.

The customer — the application's owner — accepts by naming a `lender_code`. The named offer must be one of the application's `PRESENTED` offers; naming any other lender is rejected with `ERR_OFFER_NOT_PRESENTED`, and attempting to accept on a `DECLINED` application is rejected with `ERR_FINANCING_DECLINED`. Acceptance moves the chosen offer to `ACCEPTED` and every other offer on the application to `SUPERSEDED`, and the application itself to `ACCEPTED`. The customer may instead withdraw from `SUBMITTED` or `OFFERS_PRESENTED`, moving the application to `WITHDRAWN` and superseding all presented offers. Offers also age out: when the logical clock passes the application's `created_at` by more than three days, an application in `OFFERS_PRESENTED` status becomes `EXPIRED` and all its presented offers are superseded — after which an accept attempt fails the state check with `ERR_INVALID_STATE` (see §2.8). An application still in `SUBMITTED` status (notably a `DECLINED` one, which has no offers) never ages out.

### 3.7. Returns and the Reversal Waterfall

A `Customer` opens a return against a `COMPLETED` sale, supplying the `sale_id`, a `reason_code` — `CHANGED_MIND`, `MECHANICAL_DEFECT`, or `MISREPRESENTATION` — and the `odometer_at_return`. Only the buyer on the sale may open the return (an ownership mismatch is `ERR_UNAUTHORIZED_ROLE` per §2.1); a return against a sale not in `COMPLETED` status is rejected with `ERR_INVALID_STATE`. The return begins `OPEN` with `opened_at` stamped.

A `StoreManager` approves or rejects an `OPEN` return. Approval requires that `opened_at` fall within seven days (`RETURN_WINDOW_DAYS`) of the sale's `completed_at`; a return opened later is rejected with `ERR_RETURN_WINDOW_CLOSED`. Approval also requires the sale to be `COMPLETED`. Settlement, also by a `StoreManager`, is restricted to the store whose books carried the sale — the acting manager's store must equal the sale's `store_id`.

Settlement executes the reversal waterfall in a pinned evaluation order. First, the gross refund is the sale's `amount_due_cents` — what the buyer actually paid out of pocket. Second, a mileage deduction is computed: the excess of `odometer_at_return` over the vehicle's recorded `odometer_miles` beyond a 400-mile cap (`RETURN_MILEAGE_CAP`), never less than zero, multiplied by fifty cents per mile (`PER_MILE_CENTS`). Third, `refund_total_cents` is the gross refund minus the mileage deduction, never less than zero. Fourth, the refund is allocated to buckets in order: bucket A, a `LENDER_REVERSAL` entry, applies only when the sale was financed and sends the smaller of the refund total and the accepted offer's principal outstanding (the application's `requested_amount_cents`) to the lender as a negative entry, with the remainder carrying down; bucket B, a `REFUND_PAYABLE` entry, pays the remainder to the customer in cash as a negative entry; bucket C, a `COMMISSION_CLAWBACK` entry of negative `flat_commission_cents`, posts unconditionally and independently of the refund remainder. Each settlement entry that does post references the `ReturnRequest` (its `ref_entity` is `ReturnRequest`, its `ref_id` the return's id) and posts at the sale's store. Fifth — and this is pinned — the trade-in credit is never cash-refunded; it unwinds through the appraisal reactivation cascade instead.

Settlement cascades outward. The return becomes `SETTLED` (terminal), the sale becomes `RETURNED`, and the vehicle moves from `SOLD` to `RETURNED` with `hold_status` set to `RETURN_REVIEW_HOLD`. The redeemed trade-in appraisal on the sale reactivates if the logical clock is still before its `valid_until`: it returns from `REDEEMED` to `ACTIVE` for the remainder of its original validity window, and the trade-in vehicle's re-acquisition is unwound — the vehicle returns to the customer and leaves inventory, recorded as `DISPOSED` with no ledger entry posted (a zero-value ledger treatment). If the validity window has already passed, the appraisal instead becomes `EXPIRED` and the trade-in stays with the store, with no cash reversal of the trade-in credit beyond the waterfall rules.

A returned vehicle re-enters the reconditioning pipeline: a `ReconditioningInspector` opens a fresh inspection on the `RETURNED` vehicle (whose `hold_status` must be `RETURN_REVIEW_HOLD`), which clears the hold to `NONE`, resets `recon_cost_total_cents` to zero, resets `inventory_acquired_at` to the current logical time (so `days_in_inventory` restarts), and moves the vehicle back to `IN_INSPECTION`. From there the inspection-completion machinery of §3.2 applies unchanged — the vehicle may be graded, relisted, repriced (its `days_in_inventory` now measuring the re-acquisition), and sold again.

### 3.8. Wholesale Disposition and the Auction Lane

A vehicle in `WHOLESALE_PENDING` — whether routed there by inspection disposition or by a failed auction round — is disposed through the auction lane. An `AuctionManager` lists the vehicle, provided no `LISTED` lot already exists for it, creating an `AuctionLot` in `LISTED` status with `auction_round` 1 and moving the vehicle to `AT_AUCTION`.

The `reserve_price_cents` depends on whether the lot is a first listing or a relist. On a first listing, the reserve is eighty-five percent of the vehicle's `book_value_cents` — book value multiplied by 85 and divided by 100, rounded half-up — plus fifty percent of `recon_cost_total_cents` as reconditioning-cost recovery, the recon addend likewise rounded half-up to whole cents before being added. On a relist, book value is ignored entirely: the reserve is the prior lot's `reserve_price_cents` decayed by ten percent — multiplied by 90 and divided by 100, rounded half-up — and in either case the reserve is floored at one thousand dollars (`100000` cents).

Closing a lot requires a `hammer_price_cents` strictly greater than zero (a non-positive hammer is rejected with `ERR_HAMMER_BELOW_RESERVE_INVALID`). When the hammer price is at least the reserve, the lot becomes `SOLD`, an `AUCTION_PROCEEDS` entry of `hammer_price_cents` posts at the vehicle's current store, and the vehicle reaches its terminal state `DISPOSED`. When the hammer price falls below the reserve, the lot becomes `UNSOLD` and the vehicle returns to `WHOLESALE_PENDING` to await relist. Relisting creates a new lot for the same vehicle with `auction_round` incremented, provided the previous lot is `UNSOLD` (any other prior-lot status is rejected with `ERR_INVALID_STATE`) and its `auction_round` was below 3; once three rounds are exhausted, a relist attempt is rejected with `ERR_AUCTION_ROUNDS_EXHAUSTED` — though a below-reserve close itself still completes, leaving the lot `UNSOLD`.

### 3.9. Associate Compensation: Flat by Design

Associate pay is engineered to remove haggling incentives. On every completed sale the system accrues the selling associate's `flat_commission_cents` (default `25000` cents, two hundred fifty dollars) as a `COMMISSION_ACCRUAL` entry — identical for every vehicle regardless of `sale_price_cents`, so commission is never a function of price. An associate record carries a `display_name`, a home `store_id`, a `role_kind`, and a `status` of `ACTIVE` or `INACTIVE`; associates are created `ACTIVE`.

A monthly volume bonus layers on top, measured against the logical-clock calendar month of each sale's `completed_at` at the associate's home store. The count is per-associate — all of the associate's sales in `COMPLETED` or `RETURNED` status whose `completed_at` falls in that calendar month, regardless of which store the sale occurred at. When an associate's count of completed sales in a month reaches at least 5, a bonus of five hundred dollars (`50000` cents) accrues; at least 10 earns fifteen hundred dollars (`150000` cents); at least 20 earns four thousand dollars (`400000` cents). Each tier bonus accrues as a single `COMMISSION_ACCRUAL` ledger entry referencing the `Sale` that first crosses that tier's boundary and posting at the associate's home store (the boundary is inclusive — reaching the tier count exactly triggers the bonus). Two things are pinned: returned sales still count toward the monthly volume (a fifth sale returned later the same month still triggered the tier-1 bonus when it completed), and volume bonuses are never clawed back on return settlement — only the flat per-sale commission is reversed via `COMMISSION_CLAWBACK`.

## 4. Endpoint Definitions

Operations that create new stand-alone resources return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints are mounted under the `/v1` prefix, except the administrative clock endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |
| POST | `/v1/stores` | Create a store | PlatformAdmin |
| GET | `/v1/stores` | List stores | PlatformAdmin, StoreManager, Appraiser, ReconditioningInspector, SalesAssociate, FinanceManager, AuctionManager, Customer |
| GET | `/v1/stores/{id}` | Get a store | PlatformAdmin, StoreManager, Appraiser, ReconditioningInspector, SalesAssociate, FinanceManager, AuctionManager, Customer |
| GET | `/v1/stores/{id}/ledger-entries` | List ledger entries on a store's books | PlatformAdmin, StoreManager, FinanceManager |
| POST | `/v1/customers` | Register a customer account | PlatformAdmin |
| GET | `/v1/customers` | List customers | PlatformAdmin, StoreManager, SalesAssociate, FinanceManager |
| GET | `/v1/customers/{id}` | Get a customer (customers read only their own record) | PlatformAdmin, StoreManager, SalesAssociate, FinanceManager, Customer |
| POST | `/v1/associates` | Create an associate | PlatformAdmin |
| GET | `/v1/associates` | List associates | PlatformAdmin, StoreManager |
| GET | `/v1/associates/{id}` | Get an associate | PlatformAdmin, StoreManager |
| POST | `/v1/vehicles` | Intake a vehicle at a store | StoreManager |
| GET | `/v1/vehicles` | List vehicles with filters | PlatformAdmin, StoreManager, Appraiser, ReconditioningInspector, SalesAssociate, FinanceManager, AuctionManager, Customer |
| GET | `/v1/vehicles/{id}` | Get a vehicle (`days_in_inventory` recomputed on read) | PlatformAdmin, StoreManager, Appraiser, ReconditioningInspector, SalesAssociate, FinanceManager, AuctionManager, Customer |
| POST | `/v1/vehicles/{id}/list` | Move a `RECON` vehicle to `RETAIL_LISTED` at the initial no-haggle price | StoreManager |
| POST | `/v1/vehicles/{id}/pricing-events` | Apply one scheduled algorithmic markdown (OCC-guarded) | StoreManager |
| GET | `/v1/vehicles/{id}/pricing-events` | List pricing events for a vehicle | PlatformAdmin, StoreManager, SalesAssociate |
| GET | `/v1/vehicles/{id}/appraisals` | List appraisals for a vehicle | PlatformAdmin, StoreManager, Appraiser, SalesAssociate |
| GET | `/v1/vehicles/{id}/inspections` | List inspections for a vehicle | PlatformAdmin, StoreManager, ReconditioningInspector |
| GET | `/v1/inspections` | List inspections across stores | PlatformAdmin, StoreManager |
| GET | `/v1/vehicles/{id}/transfer-requests` | List transfer requests for a vehicle | PlatformAdmin, StoreManager, SalesAssociate, Customer |
| GET | `/v1/vehicles/{id}/auction-lots` | List auction lots for a vehicle | PlatformAdmin, AuctionManager, StoreManager |
| POST | `/v1/appraisals` | Create a standing appraisal offer for a vehicle in `INTAKE` | Appraiser |
| GET | `/v1/appraisals` | List appraisals | PlatformAdmin, StoreManager, Appraiser, SalesAssociate |
| GET | `/v1/appraisals/{id}` | Get an appraisal | PlatformAdmin, StoreManager, Appraiser, SalesAssociate, Customer |
| POST | `/v1/appraisals/{id}/void` | Void an `ACTIVE` standing offer | Appraiser, StoreManager |
| POST | `/v1/vehicles/{id}/inspections` | Open a reconditioning inspection (`APPRAISED` or `RETURNED` vehicles) | ReconditioningInspector |
| GET | `/v1/inspections/{id}` | Get an inspection | PlatformAdmin, StoreManager, ReconditioningInspector |
| POST | `/v1/inspections/{id}/line-items` | Add a repair line item to an `OPEN` inspection | ReconditioningInspector |
| GET | `/v1/inspections/{id}/line-items` | List line items of an inspection | PlatformAdmin, StoreManager, ReconditioningInspector |
| POST | `/v1/inspections/{id}/line-items/{id}/approve` | Approve a `PROPOSED` line item | ReconditioningInspector |
| POST | `/v1/inspections/{id}/line-items/{id}/reject` | Reject a `PROPOSED` line item | ReconditioningInspector |
| POST | `/v1/inspections/{id}/complete` | Complete an inspection; computes disposition and cascades | ReconditioningInspector |
| POST | `/v1/inspections/{id}/cancel` | Cancel an `OPEN` inspection (vehicle returns to `APPRAISED`) | StoreManager |
| POST | `/v1/transfer-requests` | Customer requests shipment of a `RETAIL_LISTED` vehicle (OCC-guarded) | Customer |
| GET | `/v1/transfer-requests` | List transfer requests | PlatformAdmin, StoreManager, SalesAssociate, Customer |
| GET | `/v1/transfer-requests/{id}` | Get a transfer request | PlatformAdmin, StoreManager, SalesAssociate, Customer |
| POST | `/v1/transfer-requests/{id}/pay` | Customer pays the shipping fee | Customer |
| POST | `/v1/transfer-requests/{id}/ship` | Origin store ships the vehicle | StoreManager |
| POST | `/v1/transfer-requests/{id}/deliver` | Destination store receives the vehicle; hold period starts | StoreManager |
| POST | `/v1/transfer-requests/{id}/cancel` | Customer cancels; refund depends on stage | Customer |
| POST | `/v1/sales` | Open a no-haggle sale for a `RETAIL_LISTED` vehicle | SalesAssociate |
| GET | `/v1/sales` | List sales | PlatformAdmin, StoreManager, SalesAssociate, FinanceManager |
| GET | `/v1/sales/{id}` | Get a sale | PlatformAdmin, StoreManager, SalesAssociate, FinanceManager, Customer |
| POST | `/v1/sales/{id}/complete` | Complete a `PENDING_FINANCE` sale; fires the full cascade | SalesAssociate |
| POST | `/v1/sales/{id}/cancel` | Cancel a pending sale | SalesAssociate |
| POST | `/v1/sales/{id}/financing-applications` | Submit a financing application; full three-lender panel at once | FinanceManager |
| GET | `/v1/sales/{id}/financing-applications` | List financing applications for a sale | PlatformAdmin, StoreManager, FinanceManager, Customer |
| GET | `/v1/financing-applications` | List financing applications | PlatformAdmin, StoreManager, FinanceManager |
| GET | `/v1/financing-applications/{id}` | Get a financing application | PlatformAdmin, StoreManager, FinanceManager, Customer |
| GET | `/v1/financing-applications/{id}/offers` | List lender offers of an application | PlatformAdmin, StoreManager, FinanceManager, Customer |
| POST | `/v1/financing-applications/{id}/accept` | Customer accepts one offer from the panel | Customer |
| POST | `/v1/financing-applications/{id}/withdraw` | Customer withdraws the application | Customer |
| POST | `/v1/returns` | Open a return against a `COMPLETED` sale | Customer |
| GET | `/v1/returns` | List returns | PlatformAdmin, StoreManager, Customer |
| GET | `/v1/returns/{id}` | Get a return | PlatformAdmin, StoreManager, Customer |
| POST | `/v1/returns/{id}/approve` | Approve an `OPEN` return | StoreManager |
| POST | `/v1/returns/{id}/reject` | Reject an `OPEN` return | StoreManager |
| POST | `/v1/returns/{id}/settle` | Settle an `APPROVED` return; executes the reversal waterfall | StoreManager |
| POST | `/v1/auction-lots` | List a `WHOLESALE_PENDING` vehicle at auction; also the relist path | AuctionManager |
| GET | `/v1/auction-lots` | List auction lots | PlatformAdmin, AuctionManager, StoreManager |
| GET | `/v1/auction-lots/{id}` | Get an auction lot | PlatformAdmin, AuctionManager, StoreManager |
| POST | `/v1/auction-lots/{id}/close` | Close a lot with a hammer price | AuctionManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_UNKNOWN_IDENTITY` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_INSPECTION_ALREADY_OPEN` | 409 Conflict |
| `ERR_LINE_ITEMS_UNRESOLVED` | 409 Conflict |
| `ERR_VEHICLE_ALREADY_HELD` | 409 Conflict |
| `ERR_VEHICLE_NOT_LISTED` | 409 Conflict |
| `ERR_VEHICLE_NO_LONGER_AVAILABLE` | 409 Conflict |
| `ERR_APPRAISAL_EXPIRED` | 409 Conflict |
| `ERR_APPRAISAL_CUSTOMER_MISMATCH` | 409 Conflict |
| `ERR_APPRAISAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_RETURN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_FINANCING_NOT_ACCEPTED` | 409 Conflict |
| `ERR_OFFER_NOT_PRESENTED` | 409 Conflict |
| `ERR_FINANCING_DECLINED` | 409 Conflict |
| `ERR_AUCTION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_HAMMER_BELOW_RESERVE_INVALID` | 422 Unprocessable Entity |
| `ERR_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CROSS_ENTITY_STATE` | 409 Conflict |
| `ERR_AGGREGATE_RULE` | 409 Conflict |
| `ERR_FISCAL_RULE` | 409 Conflict |
