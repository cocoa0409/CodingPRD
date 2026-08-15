# Frozen Novelty Plant API — Product Requirements Document

## 1. Introduction

A frozen novelty and dessert manufacturer runs a multi-line plant where mix formulation, allergen-aware changeovers, hardening tunnel scheduling, cold-chain distribution, and co-pack contract fulfillment collide inside one operational surface. Bars, sandwiches, pints, and tubs move from liquid mix to frozen pallet under tight thermal discipline: a pasteurized batch has a 72-hour usable life, a hardening tunnel has finite throughput, a freezer zone holds a bounded number of pallets, and a product's shelf life ticks down from the moment a run completes.

This document specifies the REST API that orchestrates that plant. It covers master data (products, customers, lines, tunnels, freezer zones), the production lifecycle (mix batches, changeovers, production runs, tunnel bookings, inventory lots), outbound logistics (shipments, allocations, temperature readings), and the financial and quality loops that surround them (co-pack contracts, temperature-abuse claims, quality complaints, seasonal build plans).

A few cross-cutting themes define the system's character. First, segregation of duties is enforced at every quality-critical hand-off: the operator who pasteurizes a batch may not release it, the operator who completes a clean may not verify it, and the manager who quarantines a lot may not release it. Second, optimistic concurrency control guards two particularly contentious writes — product reformulation and contract amendment — where a stale writer must re-read before retrying. Third, the plant runs on a logical clock (not wall-clock), and several lifecycle transitions (mix expiry, lot expiry, tunnel booking expiry, contract activation) fire automatically as that clock advances.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header — a header that is present but blank or whitespace-only counts as missing — or carrying a role not in the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are: `PlantManager`, `ProductionPlanner`, `LineOperator`, `QAManager`, `WarehouseLead`, `CustomerRep`, `ClaimsAdjuster`.

For `PlantManager`, `ProductionPlanner`, `LineOperator`, `QAManager`, `WarehouseLead`, and `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `pasteurized_by` on a `MixBatch`, `completed_by` on a `Changeover`, or `quarantined_by` on an `InventoryLot`) but does not compare it to any entity's `id` for ownership purposes.

When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `CustomerRep` filing a temperature-abuse claim must be filing against a shipment whose `customer_id` matches their own id; a `CustomerRep` submitting a contract must be the contract's customer; a `CustomerRep` appealing or withdrawing a claim must be the claim's filer; a `CustomerRep` withdrawing a quality complaint must be the complaint's customer. Violations are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an `offset` beyond the end of the result set returns an empty page. List responses sort by `created_at` ascending, with ties broken by creation order (earlier-created first). The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`. Filter query parameters are exact-match on the named field; a null-valued field matches the literal filter value `null`, and query parameters outside an endpoint's declared filter set are ignored.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID with no type prefix. Every resource also carries `created_at` (ISO 8601 UTC with three fractional digits) set at creation. Resources that support mutation additionally carry `updated_at` (same format, refreshed on every mutation) and `version` (an integer starting at 1, incremented by exactly 1 on every mutation — including state transitions, side-effect cascades, and explicit edits).

`TempReading` is the sole exception: it is append-only and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from `TempReading`.

### 2.5. Precision, Rounding, and Currency

All monetary values are integer cents. When a calculation produces a fractional cent, it is rounded half-up to the nearest integer. Percentages and litre figures that the specification marks as two-decimal are rounded half-up to 2 decimal places. Temperature readings are compared at one decimal place. Pallet counts are integers, computed per lot by ceiling, then summed.

The plant prices liquid mix at 85 cents per litre (`MIX_COST_CENTS_PER_LITRE`); this constant underpins every run-completion costing.

### 2.6. Optimistic Concurrency Control

Two write endpoints are OCC-guarded. Creating a reformulation of a `Product` requires the request to carry `expected_product_version` equal to the parent product's current `version`. Amending a `CoPackContract` requires the request to carry `expected_contract_version` equal to the contract's current `version`. In either case, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the stale writer to re-read the resource before retrying. No other endpoint takes a version field.

### 2.7. The Logical Clock

The server maintains a logical clock independent of wall-clock time. On startup, before any clock call, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock. A `PlantManager` may set the clock to a supplied `to_iso8601` instant; the clock is set exactly as supplied, with no monotonicity check, and datetimes supplied without a UTC offset are interpreted as UTC. The endpoint responds with an object payload carrying the new logical time as `current_utc`. Setting the clock processes all time-based transitions whose trigger instant has been reached: a `RELEASED` `MixBatch` whose `expires_at` has been reached flips to `EXPIRED`; an `AVAILABLE` `InventoryLot` whose `best_before` has been reached flips to `EXPIRED`; a `BOOKED` `TunnelBooking` whose `end_at` has passed while its owning run is neither `IN_PRODUCTION` nor `ON_HOLD` flips to `EXPIRED`; an `APPROVED` `CoPackContract` whose `start_date` has been reached flips to `ACTIVE`.

### 2.8. Segregation of Duties

Three hand-offs are segregated. The `QAManager` releasing a `MixBatch` must not be the same `X-User-ID` as the `LineOperator` who pasteurized it. The `QAManager` verifying a `Changeover` must not be the same `X-User-ID` as the `LineOperator` who completed it. The `QAManager` releasing an `InventoryLot` from quarantine must not be the same `X-User-ID` recorded in the lot's `quarantined_by`. A violation on any of these is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Validation Ordering

When a single request violates multiple rules, the rejection surfaces the highest-priority violation. The evaluation order, from highest priority to lowest, is: authentication first, then role authorization, then path-parameter existence (validated left-to-right through the URL hierarchy), then body foreign-key existence, then request shape (required fields, types, enum membership, positive quantities, end-after-start; a body field not declared for the endpoint is rejected, and an explicit JSON `null` on an optional field is treated as omitted), then state-machine validity, then optimistic-concurrency version equality (§2.6), then ownership, then segregation of duties, then the domain-specific business, temporal, referential, and fiscal checks detailed in §3. This ordering means a caller who is both unauthenticated and forbidden sees the authentication error, and a run-start request that fails both allergen verification and mix expiry surfaces the allergen error first. Any state transition attempted from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409). A request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404); a request body that is not a JSON object is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Product Master Data and Reformulation Lineage

A `PlantManager` creates a `Product` by supplying `sku_code`, `product_name`, `format`, `flavor_family`, `allergens`, `fill_volume_ml_per_unit`, `target_overrun_pct`, `units_per_pallet`, `shelf_life_days`, and an optional `co_pack_only` flag (default false). `format` is either `NOVELTY` (bars, sandwiches) or `BULK` (pints, tubs) and constrains which lines may run the product. `flavor_family` is one of `VANILLA`, `CHOCOLATE`, `FRUIT`, `CARAMEL`, `NUT_BAKERY`, `COFFEE` and drives the changeover matrix. `allergens` is a subset of `MILK`, `EGG`, `SOY`, `WHEAT`, `PEANUT`, `TREE_NUT`, `SESAME`. `fill_volume_ml_per_unit` must be greater than 0; `target_overrun_pct` must lie between 0 and 100 inclusive; `units_per_pallet` and `shelf_life_days` must both be positive. New products start in `ACTIVE` status.

Editing a product's spec is permitted only while no `APPROVED` or `ACTIVE` co-pack contract has pinned this product's version; an edit attempted while pinned is rejected with `ERR_PRODUCT_VERSION_PINNED` (HTTP 409). The editable fields are `product_name`, `flavor_family`, `allergens`, `fill_volume_ml_per_unit`, `target_overrun_pct`, `units_per_pallet`, `shelf_life_days`, and `co_pack_only`; `sku_code` and `format` are immutable. Discontinuing moves the product from `ACTIVE` to `DISCONTINUED`. A `DISCONTINUED` product cannot be referenced by new production runs, new changeovers, or new build plans — such references are rejected with `ERR_PRODUCT_DISCONTINUED` (HTTP 422) — and it cannot be the target of a new contract approval.

Reformulation creates a successor. The request names the parent product and supplies `expected_product_version` along with the full new-product spec. On success the new product's `predecessor_product_id` points at the parent, the parent's `successor_product_id` points at the new product, and the parent's `version` increments. A stale `expected_product_version` is rejected with `ERR_STALE_VERSION` (HTTP 412), per §2.6. Reformulation is not blocked by contract pinning or by the parent being `DISCONTINUED`; beyond shape validation, the OCC version check is its only guard.

Products are listed with optional filters on `format`, `status`, `flavor_family`, `predecessor_product_id`, and `successor_product_id`.

### 3.2. Customers and Co-Pack Contracts

A `PlantManager` registers a `Customer` with `customer_code`, `display_name`, and `kind` (`PRIVATE_LABEL` for co-pack accounts, `DISTRIBUTOR` for ordinary distribution). Customers are listed with an optional filter on `kind`.

A co-pack contract begins life in `DRAFT` when a `PlantManager` creates it with `contract_code`, `customer_id`, `product_id`, `committed_units`, `unit_price_cents`, `start_date`, and `end_date`. `committed_units` must be positive, `unit_price_cents` non-negative, and `end_date` strictly after `start_date`. The `CustomerRep` owning the contract then submits it, moving `DRAFT → SUBMITTED`. A `PlantManager` approves a `SUBMITTED` contract, but only when the referenced product is `ACTIVE` and `co_pack_only` is true — a product that is not `ACTIVE` rejects with `ERR_PRODUCT_DISCONTINUED` (HTTP 422), and a product whose `co_pack_only` is false rejects with `ERR_INVALID_REQUEST` (HTTP 400); approval captures `pinned_product_version` from the product's current `version` at that instant and moves the contract `SUBMITTED → APPROVED`.

The contract becomes `ACTIVE` automatically when the logical clock's UTC date reaches `start_date` (the comparison is date-granular; time of day is irrelevant). From `ACTIVE`, delivery of shipments against the contract accumulates `delivered_units`; when `delivered_units` reaches or exceeds `committed_units` (exact equality fulfills), the contract auto-transitions `ACTIVE → FULFILLED`.

Cancellation behaves differently depending on the source state. Cancelling from `DRAFT` or `SUBMITTED` leaves `shortfall_penalty_cents` null. Cancelling from `APPROVED` or `ACTIVE` computes a shortfall penalty when `delivered_units` is less than `committed_units`: first the contract's `fulfillment_pct` is computed as `delivered_units` divided by `committed_units`, multiplied by 100, rounded half-up to 2 decimal places; then a tier rate is selected — 0.10 when `fulfillment_pct` is at least 90, 0.20 when `fulfillment_pct` is at least 50 but less than 90, and 0.35 when `fulfillment_pct` is below 50; then `shortfall_penalty_cents` is the shortfall in units (committed minus delivered) multiplied by `unit_price_cents` multiplied by that tier rate. When `delivered_units` already meets or exceeds `committed_units`, the penalty is 0. Amending a contract's `committed_units`, `unit_price_cents`, or `end_date` is permitted while `APPROVED` or `ACTIVE`, but requires `expected_contract_version` matching the contract's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Contracts are listed with optional filters on `customer_id`, `product_id`, and `status`.

### 3.3. Mix Batches and the 72-Hour Pasteurization Clock

A `ProductionPlanner` creates a `MixBatch` in `PLANNED` status with `batch_code`, `product_id`, and `litres_produced` (must be greater than 0). A `LineOperator` pasteurizes the batch, moving `PLANNED → PASTEURIZED`; this stamps `produced_at` from the current logical clock, computes `expires_at` as `produced_at` plus 72 hours, and records `pasteurized_by` as the acting `X-User-ID`.

Release is a quality gate. A `QAManager` releases a `PASTEURIZED` batch, moving it to `RELEASED` and recording `released_by`. The releaser must differ from the pasteurizer (§2.8), and the release must occur strictly before `expires_at`; a release attempted at or after expiry fails with `ERR_MIX_EXPIRED` (HTTP 422). Rejection is permitted from either `PASTEURIZED` or `RELEASED`; rejecting a batch writes off the unconsumed litres — `litres_wasted` becomes `litres_produced` minus `litres_consumed`, and `litres_remaining` becomes 0 — and moves the batch to `REJECTED`.

Two system transitions complete the lifecycle. When a run completes and consumes the last of a `RELEASED` batch (that is, `litres_remaining` reaches exactly 0 at 2 decimal places), the batch flips `RELEASED → CONSUMED`. When the logical clock reaches `expires_at` on a still-`RELEASED` batch, the batch flips `RELEASED → EXPIRED` and the same litre write-off fires as on rejection.

Throughout, `litres_consumed` is the running sum of metered litres consumed by completed runs, `litres_wasted` is the litres written off at reject or expiry, and `litres_remaining` is always `litres_produced` minus `litres_consumed` minus `litres_wasted`. Batches are listed with optional filters on `product_id` and `status`.

### 3.4. Lines, Changeovers, and the Allergen Cleaning Matrix

A `PlantManager` registers a `Line` with `line_code`, `format` (`NOVELTY` or `BULK`), and `rate_units_per_hour` (must be positive). New lines start `IDLE` with `last_product_id` and `last_allergens` null. Lines are listed with optional filters on `format`, `status`, and `last_product_id`.

A `ProductionPlanner` opens a `Changeover` on a line by naming `line_id` and `to_product_id`. Creation evaluates its gates in this order: the `to_product`'s `format` must equal the line's `format`, else `ERR_LINE_FORMAT_MISMATCH` (HTTP 422); the line must be `IDLE` — a line with a run in flight or another open changeover rejects with `ERR_CHANGEOVER_SEQUENCE` (HTTP 422); and the §3.1 discontinued-product rejection (`ERR_PRODUCT_DISCONTINUED`) applies to a `DISCONTINUED` `to_product`. Creation snapshots `from_product_id` from the line's `last_product_id`, computes `required_clean_level` and `duration_minutes` from the changeover matrix, and flips the line `IDLE → CLEANING`.

The changeover matrix evaluates three cases in order. When `from_product_id` is null (the line has never run), the level is `RINSE`. Otherwise, when the line's `last_allergens` snapshot (captured from the from-product when its last run completed) is not a subset of the to-product's allergen set — that is, some residue allergen is not declared by the target product — the level is `ALLERGEN_CIP`. Otherwise, when the from-product's current `flavor_family` differs from the to-product's `flavor_family`, the level is `WASH`. Otherwise the level is `RINSE`. Duration is fixed by level: 30 minutes for `RINSE`, 90 minutes for `WASH`, 240 minutes for `ALLERGEN_CIP`.

A `LineOperator` completes the clean, moving the changeover `REQUIRED → AWAITING_VERIFICATION` and recording `completed_by`. A `QAManager` then verifies by supplying an `outcome`: on `PASS` the changeover moves to `VERIFIED`, the line returns `CLEANING → IDLE`, and `verified_by` is recorded; on `FAIL` the changeover returns to `REQUIRED`, `completed_by` is cleared, and the line stays `CLEANING` — the redo loop permits unlimited cleaning retries. The verifier must differ from the completer (§2.8).

When a production run starts against a `VERIFIED` changeover, the changeover flips `VERIFIED → CONSUMED`. Changeovers are listed with optional filters on `line_id`, `from_product_id`, `to_product_id`, and `status`.

### 3.5. Production Runs and Hardening Tunnel Bookings

A `ProductionPlanner` schedules a `ProductionRun` with `run_code`, `product_id`, `line_id`, `planned_units` (positive), and `scheduled_start`. The line's `format` must equal the product's `format` (`ERR_LINE_FORMAT_MISMATCH`). If the product has `co_pack_only` true, an `ACTIVE` co-pack contract covering that product must exist, else `ERR_COPACK_CONTRACT_REQUIRED` (HTTP 422). These gates evaluate in the order stated — format, then the co-pack contract requirement, then the §3.1 discontinued-product rejection.

Before a run can start, three prerequisites must be in place. First, mix: the planner assigns a `RELEASED` `MixBatch` whose `product_id` equals the run's `product_id` and whose `expires_at` is strictly after the run's `scheduled_start`. Assigning mix moves the run `SCHEDULED → MIX_ASSIGNED` and sets `mix_batch_id`. A batch not yet `RELEASED` rejects with `ERR_MIX_NOT_RELEASED`; a product mismatch rejects with `ERR_MIX_PRODUCT_MISMATCH`; an expiry at or before `scheduled_start` rejects with `ERR_MIX_EXPIRED`. Second, allergen control: a `VERIFIED` `Changeover` to the run's product must exist on the run's line, else `ERR_ALLERGEN_CLEAN_NOT_VERIFIED` (HTTP 422); when several match, the earliest-created one is the match. Third, tunnel capacity: a `BOOKED` `TunnelBooking` for the run must exist, else `ERR_TUNNEL_BOOKING_REQUIRED` (HTTP 422).

Tunnel bookings are made by a `ProductionPlanner` naming `tunnel_id`, `run_id`, `start_at`, and `end_at` (strictly after `start_at`). The referenced run must be in `SCHEDULED` or `MIX_ASSIGNED`, else `ERR_RUN_NOT_SCHEDULABLE`. A run may hold at most one active booking; a second attempt while one is still `BOOKED` rejects with `ERR_BOOKING_EXISTS` (HTTP 409). Two further checks guard the tunnel itself. The conflict check treats every existing non-cancelled booking on the same tunnel (status `BOOKED` or `COMPLETED`; `CANCELED` and `EXPIRED` are excluded) as occupying a half-open interval that ends 30 minutes after its nominal `end_at` — a trailing cleanup buffer. A new booking conflicts when its `start_at` falls strictly before an existing booking's buffered end AND that existing booking's `start_at` falls strictly before the new booking's `end_at`; exact adjacency — new `start_at` equal to an existing booking's `end_at` plus the 30-minute buffer — is allowed. A conflict rejects with `ERR_TUNNEL_WINDOW_CONFLICT` (HTTP 409). The throughput check requires the run's `planned_units` to be no greater than the tunnel's `max_units_per_hour` multiplied by the window's length in hours; exact equality is permitted, and a violation rejects with `ERR_TUNNEL_CAPACITY_EXCEEDED` (HTTP 422). At booking creation these guards evaluate in this order: window conflict, then throughput, then run schedulability, then the one-active-booking rule.

A `LineOperator` starts the run when the line is `IDLE` and the assigned mix is still `RELEASED` with `expires_at` strictly in the future. Starting moves the run `MIX_ASSIGNED → IN_PRODUCTION`, flips the matched changeover `VERIFIED → CONSUMED`, and flips the line `IDLE → RUNNING`. While in production, a `QAManager` may hold the run (`IN_PRODUCTION → ON_HOLD`) and later resume it (`ON_HOLD → IN_PRODUCTION`); the hold/rework loop permits unlimited cycles.

Completion is the busiest transition in the system. A `LineOperator` completes the run by supplying `actual_units` (positive), `mix_metered_litres` (positive, and no greater than the batch's `litres_remaining` — else `ERR_INSUFFICIENT_MIX`), and `zone_id` for the destination freezer zone. Completion runs the dual-variant mix costing (§3.6), stamps `completed_at` from the current logical clock, creates an `InventoryLot` (see §3.7), adds `mix_metered_litres` to the batch's `litres_consumed` (flipping the batch to `CONSUMED` if `litres_remaining` reaches exactly 0 at 2 decimal places), flips this run's `BOOKED` tunnel bookings to `COMPLETED`, and returns the line `RUNNING → IDLE` with `last_product_id` set to the run's product and `last_allergens` snapshotted from that product. Completion also runs the freezer-zone day-aggregate capacity check (§3.7); a failure rejects with `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 422). Of the two rejection checks at completion, the zone capacity check is evaluated before the `mix_metered_litres` sufficiency check.

Cancelling a run is permitted from `SCHEDULED`, `MIX_ASSIGNED`, or `ON_HOLD`. Cancellation flips this run's `BOOKED` tunnel bookings to `CANCELED`; from `ON_HOLD` it also returns the line `RUNNING → IDLE` without touching `last_product_id` and without creating a lot; from `MIX_ASSIGNED` it clears `mix_batch_id` to null with no litres consumed.

Runs are listed with optional filters on `product_id`, `line_id`, `mix_batch_id`, and `status`. Tunnels are registered with `tunnel_code` and `max_units_per_hour` (positive). Bookings are listed with optional filters on `tunnel_id`, `run_id`, and `status`; a planner may cancel a `BOOKED` booking directly.

### 3.6. Run-Completion Costing: Standard vs. Metered Variants

Run completion prices mix usage in two parallel variants. Both share the same 85-cents-per-litre mix cost constant but differ in the litre figure they multiply.

The **standard variant** ignores the flow meter and prices at target overrun. `mix_litres_theoretical` is `actual_units` multiplied by `fill_volume_ml_per_unit`, divided by (1 plus `target_overrun_pct` divided by 100), divided by 1000 to convert millilitres to litres — rounded half-up to 2 decimal places. The standard cost is that litre figure multiplied by 85, rounded half-up to integer cents.

The **metered variant** takes the flow-meter reading supplied at complete. `mix_litres_actual` is exactly `mix_metered_litres`; the run records it under `mix_metered_litres`, and no separate `mix_litres_actual` field is stored. From it, `overrun_actual_pct` is computed as `actual_units` multiplied by `fill_volume_ml_per_unit`, divided by the product of `mix_metered_litres` and 1000, then subtracting 1, then multiplying by 100 — rounded half-up to 2 decimal places. The actual cost is `mix_metered_litres` multiplied by 85, rounded half-up to integer cents.

`mix_cost_variance_cents` is the standard cost minus the actual cost; a positive value means the run used less mix than standard. The two variants diverge whenever actual overrun differs from target overrun.

### 3.7. Freezer Zones, Inventory Lots, and Pallet Capacity

A `PlantManager` registers a `FreezerZone` with `zone_code` and `pallet_capacity` (positive). The zone's `occupied_pallets` is the sum, over every lot in the zone whose status is `AVAILABLE` or `QUARANTINED` and whose occupancy window covers the current logical day, of that lot's `pallets`.

A lot is born at run completion. Its `lot_code` is `LOT-` followed by the run's `run_code`; `run_id` and `product_id` are taken from the run; `zone_id` from the completion payload; `units_produced` equals `actual_units`; `produced_at` equals the completion timestamp; `best_before` is `produced_at` plus the product's `shelf_life_days`. `units_available` is the unreserved, unshipped, undestroyed count; `units_reserved` is the count under `ACTIVE` allocations; `units_shipped` is the count under `FULFILLED` allocations; `units_destroyed` starts at 0. A lot's `pallets` is the ceiling of (`units_available` plus `units_reserved`) divided by the product's `units_per_pallet` — the ceiling is taken per lot, and zone occupancy sums those per-lot integers after rounding (never ceiling of summed units).

The zone capacity check is day-granular and aggregate. A lot occupies its zone on every logical day `d` from its `produced_at` date (inclusive) to its `best_before` date (exclusive). For each such day, the sum of `pallets` over existing lots in the zone with status `AVAILABLE` or `QUARANTINED` whose window covers `d`, plus the new lot's `pallets`, must be no greater than `pallet_capacity`. Lots in `DESTROYED` or `EXPIRED` do not occupy space.

Quarantine is the first link in the complaint-substantiation cascade. A `QAManager` may manually quarantine an `AVAILABLE` lot, recording `quarantined_by`. Quarantine flips the lot `AVAILABLE → QUARANTINED` and immediately releases every `ACTIVE` `ShipmentAllocation` on the lot (release_reason `COMPLAINT_CASCADE`), moving those units from `units_reserved` back to `units_available`. Every shipment losing an allocation recomputes `allocated_units`; a `LOADED` shipment that had any allocation released regresses `LOADED → PLANNED`. Releasing quarantine returns the lot `QUARANTINED → AVAILABLE` and requires the caller to differ from `quarantined_by` (§2.8) and is blocked while any `QualityComplaint` on any lot sharing this lot's `run_id` is in `UNDER_REVIEW` or `LAB_TEST`, else `ERR_COMPLAINT_STILL_OPEN` (HTTP 422). Destroying a `QUARANTINED` lot moves all of `units_available` into `units_destroyed` and zeroes `units_available`. Expiry is system-driven: when the logical clock reaches `best_before` on an `AVAILABLE` lot, the lot flips to `EXPIRED` and any `ACTIVE` allocations are system-released with `release_reason` left null.

Lots are listed with optional filters on `product_id`, `run_id`, `zone_id`, and `status`.

### 3.8. Shipments, Allocations, and the Cold-Chain Lifecycle

A `WarehouseLead` creates a `Shipment` in `PLANNED` with `shipment_code`, `customer_id`, and optionally `contract_id` and `carrier_liability` (default false). When `contract_id` is supplied, the contract must be `ACTIVE` and its `customer_id` must equal the shipment's `customer_id`, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 422).

Allocations reserve lot units against a `PLANNED` shipment. The lead names `lot_id` and `units` (positive). The lot must be `AVAILABLE` with `best_before` strictly in the future, else `ERR_LOT_NOT_AVAILABLE`; the requested `units` must not exceed `lot.units_available`, else `ERR_INSUFFICIENT_LOT_UNITS`. On a contract-linked shipment, the contract link is re-validated at allocation time — the contract must still be `ACTIVE` and its `customer_id` must still equal the shipment's `customer_id`, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 422) — and then the lot's `product_id` must equal the contract's `product_id`, else `ERR_CONTRACT_PRODUCT_MISMATCH` (HTTP 422). Creating an allocation flips it to `ACTIVE`, moves `units` from the lot's `units_available` to `units_reserved`, and adds `units` to the shipment's `allocated_units`. A manual release is permitted only while the shipment is still `PLANNED`; it returns the units to `units_available`, decrements `allocated_units`, and marks the allocation `RELEASED` with `release_reason` `MANUAL`.

Loading requires `allocated_units` greater than 0, else `ERR_SHIPMENT_EMPTY`. Loading moves `PLANNED → LOADED`. Dispatch moves `LOADED → IN_TRANSIT` and stamps `dispatched_at` from the logical clock. Delivery moves `IN_TRANSIT → DELIVERED`, stamps `closed_at`, flips every `ACTIVE` allocation to `FULFILLED`, and on each lot moves the allocated units from `units_reserved` to `units_shipped`. When the shipment carries a `contract_id`, delivery also adds the sum of the allocation units to the contract's `delivered_units` and recomputes `fulfillment_pct`; when `delivered_units` reaches or exceeds `committed_units`, the contract auto-transitions `ACTIVE → FULFILLED`. Rejection at delivery moves `IN_TRANSIT → REJECTED`, stamps `closed_at`, and releases every `ACTIVE` allocation back to its lot (`units_reserved` returns to `units_available`) with `release_reason` `SHIPMENT_REJECTED`, and the shipment's `allocated_units` resets to 0.

Temperature readings are append-only logger events. While a shipment is `IN_TRANSIT`, the lead appends a batch of `readings`, each with `recorded_at` and `temp_c`; the append responds with HTTP 201 and an array envelope containing the created readings. Readings are stored against the shipment and listed in `created_at` ascending order.

Shipments are listed with optional filters on `customer_id`, `contract_id`, and `status`. Allocations are listed with optional filters on `shipment_id`, `lot_id`, and `status`.

### 3.9. Temperature-Abuse Claims and the Replay Engine

A `CustomerRep` files a `TempAbuseClaim` against a shipment that is `DELIVERED` or `REJECTED` — any other status rejects with `ERR_CLAIM_NOT_ALLOWED` — supplying `claim_code`, `shipment_id`, and `declared_value_cents` (positive). The filer's `X-User-ID` becomes `filed_by_customer_id` and must equal the shipment's `customer_id`. At most one non-terminal claim per shipment: a second filing while an existing claim is `SUBMITTED`, `EVIDENCE_REVIEW`, `APPEALED`, or `APPROVED` rejects with `ERR_DUPLICATE_CLAIM` (HTTP 409).

A `ClaimsAdjuster` opens evidence review on a `SUBMITTED` or `APPEALED` claim. The shipment must carry at least 2 stored temperature readings — in-window or not — else `ERR_INSUFFICIENT_READINGS`. Opening review runs the temperature replay and computes both payout variants, then moves the claim to `EVIDENCE_REVIEW`.

The replay walks the shipment's in-window readings — those with `recorded_at` between `dispatched_at` and `closed_at`, inclusive on both ends — sorted by `recorded_at` ascending, with ties broken by append order (earlier-appended readings first). Readings before dispatch (logger warm-up) and after closure (late uploads) are excluded. `abuse_minutes` accumulates, for each consecutive pair, the minutes between the two timestamps whenever the earlier reading's `temp_c` is strictly above -18.0; a reading at exactly -18.0 contributes zero abuse. Each contributing interval adds only its whole minutes; sub-minute remainders are discarded per interval. Threshold comparisons use the recorded `temp_c` values exactly as submitted. The final interval closes at `closed_at`: when the last in-window reading is before `closed_at` and its `temp_c` is strictly above -18.0, the minutes from that reading to `closed_at` are added. `peak_temp_c` is the maximum `temp_c` over the in-window readings, reported rounded half-up to one decimal place; when no readings fall in the window, `abuse_minutes` and `heat_shock_events` are 0 and `peak_temp_c` is null. `heat_shock_events` counts upward crossings of -12.0 across consecutive in-window readings — that is, pairs where the earlier reading is at or below -12.0 and the later reading is strictly above -12.0; a reading at exactly -12.0 does not start a crossing.

Both payout variants are computed at open-review. The **standard variant** tiers marginally on `abuse_minutes`: the first 30 minutes are free; minutes beyond 30 up to and including 120 pay 200 cents per minute; minutes beyond 120 pay 350 cents per minute on top of the 90-minute low-tier amount (90 minutes times 200 cents). The result is capped at `declared_value_cents`. The **carrier variant** applies to shipments with `carrier_liability` true: zero abuse minutes yields zero; otherwise the payout is `abuse_minutes` multiplied by 150 cents, minus a fixed 5000-cent deductible, floored at zero, then capped at 80% of `declared_value_cents`, with that cap truncated down to a whole cent (overriding the §2.5 half-up rule for this cap). Evaluation order is pinned: tiers, then deductible, then cap.

Approval selects a variant. When the shipment's `carrier_liability` is true, `payout_variant` becomes `CARRIER` and `payout_cents` becomes `payout_carrier_cents`; otherwise `payout_variant` becomes `STANDARD` and `payout_cents` becomes `payout_standard_cents`. Approval moves `EVIDENCE_REVIEW → APPROVED` and stamps `decided_at`. Denial moves `EVIDENCE_REVIEW → DENIED` and stamps `decided_at`. Payment moves `APPROVED → PAID` and stamps `paid_at`.

The filer may appeal a `DENIED` claim, moving it to `APPEALED`, provided the current logical clock is no later than `decided_at` plus 14 days (the boundary is inclusive; day 14 still appeals). A later appeal rejects with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422). The `DENIED → APPEALED → EVIDENCE_REVIEW` loop permits unlimited appeals. The filer may withdraw from `SUBMITTED` or `EVIDENCE_REVIEW`, moving to `WITHDRAWN`.

Claims are listed with optional filters on `shipment_id`, `filed_by_customer_id`, and `status`.

### 3.10. Quality Complaints and the Substantiation Cascade

A `QAManager` or a `CustomerRep` files a `QualityComplaint` against a lot, supplying `complaint_code`, `lot_id`, and `complaint_type` (one of `HEAT_SHOCK`, `TEXTURE`, `SHELF_LIFE_SHORTFALL`, `FOREIGN_MATERIAL`). When filed by a `CustomerRep`, `customer_id` is set from `X-User-ID`; QA-internal filings leave it null. New complaints start `UNDER_REVIEW` with `lab_cycle_count` 0.

Sending to lab moves `UNDER_REVIEW → LAB_TEST` and increments `lab_cycle_count`; the cap is 3, and a fourth send rejects with `ERR_LAB_CYCLE_EXHAUSTED` (HTTP 409). Recording a lab result moves `LAB_TEST → UNDER_REVIEW`; the request may carry `measured_ice_crystal_um`, which is required when the complaint's `complaint_type` is `HEAT_SHOCK` — omitting it there rejects with `ERR_INVALID_REQUEST` (HTTP 400). The `UNDER_REVIEW ↔ LAB_TEST` loop permits retesting within the cycle cap.

Disposition closes the loop. An `outcome` of `UNFOUNDED` moves the complaint to `CLOSED_UNFOUNDED`. An `outcome` of `SUBSTANTIATED` moves it to `DISPOSITIONED_SUBSTANTIATED`, but for `HEAT_SHOCK` complaints two gates apply first: `measured_ice_crystal_um` must be recorded, else `ERR_LAB_RESULT_REQUIRED` (HTTP 422); and the measured value must be strictly greater than the format threshold — 120 microns for `NOVELTY`, 150 microns for `BULK` — else `ERR_HEAT_SHOCK_NOT_PROVEN` (HTTP 422). A measurement exactly equal to the threshold is not substantiable.

Substantiation triggers the cascade. Every `InventoryLot` sharing the complaint's lot's `run_id` that is currently `AVAILABLE` flips to `QUARANTINED` with `quarantined_by` set to the acting QA `X-User-ID`. Each such quarantined lot's `ACTIVE` allocations are released with `release_reason` `COMPLAINT_CASCADE`, returning reserved units to available. Every shipment that loses an allocation recomputes `allocated_units`; any such shipment in `LOADED` status regresses to `PLANNED`.

Withdrawal is permitted from `UNDER_REVIEW` or `LAB_TEST`. A `CustomerRep` may withdraw only their own complaint; a `QAManager` may withdraw any. Complaints are listed with optional filters on `lot_id`, `customer_id`, `status`, and `complaint_type`. An optional `disposition_rationale` may accompany disposition.

### 3.11. Seasonal Build Plans

A `ProductionPlanner` drafts a `SeasonalBuildPlan` with `plan_code`, `product_id`, `zone_id`, `production_week_start` (the ISO date of the build week's Monday), `sale_week_start` (the sale week's Monday), and `target_units` (positive). Drafting computes `required_pallets` as the ceiling of `target_units` divided by the product's `units_per_pallet`.

Approval is a `PlantManager` action with two gates, evaluated in the order stated here. The zone week-capacity gate sums `required_pallets` over all `APPROVED` plans sharing this plan's `zone_id` and `production_week_start`, adds this plan's `required_pallets`, and requires the total to be no greater than the zone's `pallet_capacity`; a violation rejects with `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 422). The shelf-life window gate requires the number of whole days between `production_week_start` and `sale_week_start`, plus a 30-day minimum-remaining-shelf buffer, to be no greater than the product's `shelf_life_days` — the boundary is inclusive, so equality passes; a violation rejects with `ERR_SHELF_LIFE_WINDOW` (HTTP 422). Approval moves the plan `DRAFT → APPROVED`. Cancellation moves from `DRAFT` or `APPROVED` to `CANCELED`.

Plans are listed with optional filters on `product_id`, `zone_id`, and `status`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications and state transitions return HTTP 200. Read endpoints return HTTP 200. All list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/products` | Create a product (SKU master) | PlantManager |
| GET | `/products` | List products with filters | All roles |
| GET | `/products/{id}` | Get one product | All roles |
| PATCH | `/products/{id}` | Edit product spec; forbidden while pinned by an APPROVED/ACTIVE contract | PlantManager |
| POST | `/products/{id}/discontinue` | Discontinue a product | PlantManager |
| POST | `/products/{id}/reformulations` | Create successor product (OCC-guarded); parent gains successor_product_id | PlantManager |
| POST | `/customers` | Register a customer (private label or distributor) | PlantManager |
| GET | `/customers` | List customers | All roles |
| POST | `/co-pack-contracts` | Create contract in DRAFT | PlantManager |
| GET | `/co-pack-contracts` | List contracts | All roles |
| GET | `/co-pack-contracts/{id}` | Get one contract | All roles |
| POST | `/co-pack-contracts/{id}/submit` | Customer submits DRAFT contract | CustomerRep |
| POST | `/co-pack-contracts/{id}/approve` | Approve contract; pins product version | PlantManager |
| POST | `/co-pack-contracts/{id}/amend` | Amend APPROVED/ACTIVE contract terms (OCC-guarded) | PlantManager |
| POST | `/co-pack-contracts/{id}/cancel` | Cancel contract; computes shortfall penalty from APPROVED/ACTIVE | PlantManager |
| POST | `/mix-batches` | Create mix batch (PLANNED) | ProductionPlanner |
| GET | `/mix-batches` | List mix batches | All roles |
| GET | `/mix-batches/{id}` | Get one mix batch | All roles |
| POST | `/mix-batches/{id}/pasteurize` | Pasteurize batch; stamps produced_at/expires_at | LineOperator |
| POST | `/mix-batches/{id}/release` | QA release (segregated from pasteurizer) | QAManager |
| POST | `/mix-batches/{id}/reject` | QA reject; wastes remaining litres | QAManager |
| POST | `/lines` | Register a production line | PlantManager |
| GET | `/lines` | List lines | All roles |
| GET | `/lines/{id}` | Get one line | All roles |
| POST | `/changeovers` | Open a changeover on a line; computes required_clean_level | ProductionPlanner |
| GET | `/changeovers` | List changeovers | All roles |
| GET | `/changeovers/{id}` | Get one changeover | All roles |
| POST | `/changeovers/{id}/complete` | Operator marks cleaning done | LineOperator |
| POST | `/changeovers/{id}/verify` | QA verifies (PASS or FAIL) | QAManager |
| POST | `/production-runs` | Schedule a production run | ProductionPlanner |
| GET | `/production-runs` | List production runs | All roles |
| GET | `/production-runs/{id}` | Get one production run | All roles |
| POST | `/production-runs/{id}/assign-mix` | Assign a RELEASED mix batch to a SCHEDULED run | ProductionPlanner |
| POST | `/production-runs/{id}/start` | Start the run | LineOperator |
| POST | `/production-runs/{id}/hold` | QA hold | QAManager |
| POST | `/production-runs/{id}/resume` | QA resume from hold | QAManager |
| POST | `/production-runs/{id}/complete` | Complete run: costing, lot creation, line/tunnel release | LineOperator |
| POST | `/production-runs/{id}/cancel` | Cancel run | ProductionPlanner |
| POST | `/tunnels` | Register a hardening tunnel | PlantManager |
| GET | `/tunnels` | List tunnels | All roles |
| POST | `/tunnel-bookings` | Book a hardening tunnel window | ProductionPlanner |
| GET | `/tunnel-bookings` | List tunnel bookings | All roles |
| GET | `/tunnel-bookings/{id}` | Get one tunnel booking | All roles |
| POST | `/tunnel-bookings/{id}/cancel` | Cancel a BOOKED booking | ProductionPlanner |
| POST | `/freezer-zones` | Register a freezer zone | PlantManager |
| GET | `/freezer-zones` | List freezer zones | All roles |
| GET | `/freezer-zones/{id}` | Get one zone | All roles |
| GET | `/inventory-lots` | List inventory lots | All roles |
| GET | `/inventory-lots/{id}` | Get one lot | All roles |
| POST | `/inventory-lots/{id}/quarantine` | QA quarantine; cascades allocation release | QAManager |
| POST | `/inventory-lots/{id}/release-quarantine` | QA release from quarantine | QAManager |
| POST | `/inventory-lots/{id}/destroy` | Destroy quarantined lot | QAManager |
| POST | `/shipments` | Create shipment (PLANNED) | WarehouseLead |
| GET | `/shipments` | List shipments | All roles |
| GET | `/shipments/{id}` | Get one shipment | All roles |
| POST | `/shipments/{id}/allocations` | Allocate lot units to a PLANNED shipment | WarehouseLead |
| GET | `/shipment-allocations` | List allocations | All roles |
| GET | `/shipment-allocations/{id}` | Get one allocation | All roles |
| POST | `/shipment-allocations/{id}/release` | Manual release (shipment must be PLANNED) | WarehouseLead |
| POST | `/shipments/{id}/load` | Load truck | WarehouseLead |
| POST | `/shipments/{id}/dispatch` | Depart; stamps dispatched_at | WarehouseLead |
| POST | `/shipments/{id}/deliver` | Deliver; fulfills allocations; credits contract | WarehouseLead |
| POST | `/shipments/{id}/reject` | Reject at delivery; releases allocations | WarehouseLead |
| POST | `/shipments/{id}/temperature-readings` | Append logger readings (bulk) | WarehouseLead |
| GET | `/shipments/{id}/temperature-readings` | List a shipment's readings | All roles |
| POST | `/temp-abuse-claims` | File a temperature-abuse claim | CustomerRep |
| GET | `/temp-abuse-claims` | List claims | All roles |
| GET | `/temp-abuse-claims/{id}` | Get one claim | All roles |
| POST | `/temp-abuse-claims/{id}/open-review` | Open evidence review; runs replay and both payout variants | ClaimsAdjuster |
| POST | `/temp-abuse-claims/{id}/approve` | Approve; selects payout variant | ClaimsAdjuster |
| POST | `/temp-abuse-claims/{id}/deny` | Deny claim | ClaimsAdjuster |
| POST | `/temp-abuse-claims/{id}/pay` | Pay approved claim | ClaimsAdjuster |
| POST | `/temp-abuse-claims/{id}/appeal` | Customer appeals a denial within 14 days | CustomerRep |
| POST | `/temp-abuse-claims/{id}/withdraw` | Customer withdraws an open claim | CustomerRep |
| POST | `/quality-complaints` | File a complaint against a lot | QAManager, CustomerRep |
| GET | `/quality-complaints` | List complaints | All roles |
| GET | `/quality-complaints/{id}` | Get one complaint | All roles |
| POST | `/quality-complaints/{id}/send-to-lab` | Send to lab (cycle cap 3) | QAManager |
| POST | `/quality-complaints/{id}/record-lab-result` | Record lab measurement | QAManager |
| POST | `/quality-complaints/{id}/disposition` | Disposition: SUBSTANTIATED or UNFOUNDED | QAManager |
| POST | `/quality-complaints/{id}/withdraw` | Withdraw complaint | QAManager, CustomerRep |
| POST | `/seasonal-build-plans` | Create a seasonal inventory build plan | ProductionPlanner |
| GET | `/seasonal-build-plans` | List build plans | All roles |
| GET | `/seasonal-build-plans/{id}` | Get one build plan | All roles |
| POST | `/seasonal-build-plans/{id}/approve` | Approve plan | PlantManager |
| POST | `/seasonal-build-plans/{id}/cancel` | Cancel plan | PlantManager |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | PlantManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ALLERGEN_CLEAN_NOT_VERIFIED` | 422 |
| `ERR_MIX_NOT_RELEASED` | 422 |
| `ERR_MIX_PRODUCT_MISMATCH` | 422 |
| `ERR_MIX_EXPIRED` | 422 |
| `ERR_LINE_FORMAT_MISMATCH` | 422 |
| `ERR_CHANGEOVER_SEQUENCE` | 422 |
| `ERR_TUNNEL_WINDOW_CONFLICT` | 409 |
| `ERR_TUNNEL_CAPACITY_EXCEEDED` | 422 |
| `ERR_RUN_NOT_SCHEDULABLE` | 422 |
| `ERR_BOOKING_EXISTS` | 409 |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 422 |
| `ERR_SHELF_LIFE_WINDOW` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_TUNNEL_BOOKING_REQUIRED` | 422 |
| `ERR_LOT_NOT_AVAILABLE` | 422 |
| `ERR_INSUFFICIENT_LOT_UNITS` | 422 |
| `ERR_SHIPMENT_EMPTY` | 422 |
| `ERR_CLAIM_NOT_ALLOWED` | 422 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_INSUFFICIENT_READINGS` | 422 |
| `ERR_LAB_RESULT_REQUIRED` | 422 |
| `ERR_HEAT_SHOCK_NOT_PROVEN` | 422 |
| `ERR_LAB_CYCLE_EXHAUSTED` | 409 |
| `ERR_COMPLAINT_STILL_OPEN` | 422 |
| `ERR_CONTRACT_NOT_ACTIVE` | 422 |
| `ERR_CONTRACT_PRODUCT_MISMATCH` | 422 |
| `ERR_COPACK_CONTRACT_REQUIRED` | 422 |
| `ERR_PRODUCT_VERSION_PINNED` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 422 |
| `ERR_INSUFFICIENT_MIX` | 422 |
