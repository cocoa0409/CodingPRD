# Refrigerated Pet Food Cold Chain API — Product Requirements Document

## 1. Introduction

Building a refrigerated pet food category inside conventional retail stores is, at its core, an asset-placement problem: the company owns the chillers, negotiates floor footprint store by store, and stakes its brand on the product never leaving a safe temperature band between the plant and the shopper's basket. This document specifies the API that runs that program end to end. It governs how candidate stores are registered and scored for placement priority, how placement agreements are negotiated and signed, how company-owned chillers are manufactured, installed, monitored, and repaired, and how refrigerated product moves from plant lots through dedicated trucks into store inventory with strict date-checking discipline.

The program is deliberately numbers-driven. Site selection weighs demographic fit, category velocity, footprint, and competitor density through a published scoring model with a payback eligibility gate; installation is fenced by budget, footprint, and freshness-of-evidence checks; a rolling temperature-excursion accumulator can suspend a placement, quarantine its inventory, and dispatch a repair in one cascade; and a manufacturing capacity ledger decides when expansion projects may be commissioned and in what order. Underperforming placements are measured on a trailing velocity floor and can be removed or relocated, returning their chiller to stock for redeployment. All business resources are mounted under the `/cold-chain` URL prefix; a single platform capability for driving the logical clock lives outside that prefix and is specified in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level structures, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing or blank, or if the supplied role is not one of the declared roles, the request is rejected with 401 `ERR_UNAUTHENTICATED`. The system recognizes exactly seven roles: `PlatformAdmin`, `PlacementManager`, `StoreOperator`, `ServiceDispatcher`, `FieldTechnician`, `LogisticsCoordinator`, and `ProductionPlanner`. Each endpoint authorizes a specific subset of these roles (see §4); an authenticated caller whose role is not in the endpoint's list is rejected with 403 `ERR_FORBIDDEN_ROLE`.

Role identity semantics differ by role and are normative. When `X-User-Role` is `StoreOperator`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` compare the resource's store foreign key to `X-User-ID`, and a mismatch is rejected with 403 `ERR_STORE_OWNERSHIP_MISMATCH`. When `X-User-Role` is any of `PlatformAdmin`, `PlacementManager`, `ServiceDispatcher`, `FieldTechnician`, `LogisticsCoordinator`, or `ProductionPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `CapacityProject`, where the approver must be a different `X-User-ID` than the creator under the segregation-of-duties rule — but it does not compare it to any entity's `id` for those roles.

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

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, and an `offset` that is not an integer or is negative, are rejected with 400 `ERR_VALIDATION` — out-of-range values are rejected, never clamped. Unless a list endpoint states otherwise in §3, results are sorted by `created_at` in ascending order, with ties broken by creation order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Query parameters an endpoint does not declare are ignored; declared filter parameters compare by exact string equality, and a filter value that matches no row yields an empty page, not an error.

### 2.4. The Logical Clock and Lazy State Materialization

All time-dependent behavior in the system is governed by a single logical clock, never by wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; until it is explicitly set, every time-dependent rule evaluates against that default, and the clock never silently falls back to the host's wall clock.

A platform capability advances the logical clock: the endpoint `POST /_clock/set_current_utc` lives outside the `/cold-chain` prefix (it is an unprefixed platform endpoint) and is restricted to `PlatformAdmin`. The request body carries `to_iso8601`, the target instant. The clock is forward-only: `to_iso8601` must be strictly greater than the current logical time, and a value equal to or earlier than the current logical time is rejected with 400 `ERR_CLOCK_REGRESSION`. On success the endpoint responds 200 with the new `current_utc`.

Advancing the clock does not, by itself, rewrite any resource. Time-dependent states materialize lazily: a `QUARANTINE` or `RELEASED` product lot reads as `EXPIRED` once the logical now is later than its `expires_at`; an `IN_TRANSIT` shipment reads as `SPOILED` once the logical now is later than 48 hours after its `departed_at`; and an `ACTIVE` trial campaign reads as `COMPLETED` once the logical now is later than one day after its `end_date`. These materializations are applied on any read or use of the affected resource, and each materialization increments the resource's `version` by 1. The 24-hour excursion window described in §2.10 and §3.5 slides with the logical clock as well.

### 2.5. Common Resource Properties

Every primary resource — `Store`, `SiteEvaluation`, `PlacementAgreement`, `Chiller`, `Placement`, `ServiceTicket`, `Shipment`, `ProductLot`, `InventoryPosition`, `CapacityProject`, and `TrialCampaign` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource, including mutations caused by cascade side effects originating on another entity.

`TemperatureReading` is the one exception: it is an append-only telemetry record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from temperature readings.

Datetime-valued business fields other than `created_at`/`updated_at` — for example `signed_at`, `terminated_at`, `last_repair_at`, `recorded_at`, `produced_at`, `expires_at`, `departed_at`, `delivered_at`, `expiry_date`, `window_start`, `window_end`, `start_date`, `end_date`, and the clock endpoint's `current_utc` — are echoed as UTC with a `Z` suffix: with three fractional digits when the value carries sub-second precision, and without a fractional part when it falls exactly on a whole second. Datetime inputs are ISO 8601; a missing timezone designator is read as UTC, and offsets are normalized to UTC.

### 2.6. Nested Resource Retrieval

Requests that address nested resources are validated from left to right along the URL path. The system checks each path identifier in order — for example, the store identifier before the nested collection under it — and rejects the request with 404 `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing row, without examining later identifiers. The same rule then continues into the request body: foreign keys supplied in the payload are resolved in field order, and the first unresolvable reference is likewise rejected with 404 `ERR_NOT_FOUND`.

### 2.7. Validation Priority Order

When several checks could reject the same request, the system evaluates them in a fixed priority order, and the earliest failing tier determines the response:

1. **Authentication and request shape.** Missing or blank `X-User-ID` / `X-User-Role` headers, or an undeclared role, yield 401 `ERR_UNAUTHENTICATED`. A malformed body, an undeclared payload field, a missing required field, or a scalar range violation (a non-positive `quantity_units`, a `temp_c` outside the sensor-plausible range, an `end_date` earlier than `start_date`, a future `recorded_at` or `produced_at`, an enum value outside its declared set) yields 400 `ERR_VALIDATION`. These request-shape errors share the top tier with authentication. A required free-text string field is satisfied by the empty string; only its presence and JSON string type are enforced.
2. **Role, ownership, and segregation of duties.** A role outside the endpoint's authorized list yields 403 `ERR_FORBIDDEN_ROLE`; a `StoreOperator` acting outside their own store's scope yields 403 `ERR_STORE_OWNERSHIP_MISMATCH`; a capacity-project approver who is also the project's creator yields 403 `ERR_SEGREGATION_OF_DUTIES`. Where an ownership check derives the store from the target resource's stored references (as with the reading-posting rule of §3.5), the target's existence is necessarily resolved first, so an unresolvable identifier on such a path yields 404 `ERR_NOT_FOUND` before ownership is evaluated.
3. **Existence.** Unresolvable path identifiers or body foreign keys yield 404 `ERR_NOT_FOUND`, left to right per §2.6.
4. **State.** State-machine preconditions of the target transition yield the machine-specific codes `ERR_AGREEMENT_NOT_SIGNED`, `ERR_CHILLER_NOT_IN_STOCK`, `ERR_PLACEMENT_NOT_ACTIVE`, `ERR_PLACEMENT_NOT_OPERATIONAL`, `ERR_DUPLICATE_ACTIVE_PLACEMENT`, `ERR_LOT_NOT_RELEASED`, `ERR_DELIVERY_ROUTE_INACTIVE`, `ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT`, `ERR_EXPANSION_SEQUENCE_VIOLATION`, and `ERR_SERIAL_NOT_UNIQUE` (all 409), with the generic 409 `ERR_INVALID_STATE` as the fallthrough when no more specific code applies. Optimistic-concurrency failures are not state errors, but they are evaluated in this tier immediately after the state preconditions: a stale `expected_agreement_version` yields 412 `ERR_STALE_VERSION` (see §2.8).
5. **Business safety.** Cold-chain product safety: a lot that has materialized `EXPIRED` at shipment creation or dock delivery yields 422 `ERR_LOT_EXPIRED`.
6. **Business temporal.** Time-window rules: delivering beyond the transit window yields 422 `ERR_TRANSIT_WINDOW_EXCEEDED`; installing or relocating against a stale site evaluation yields 422 `ERR_EVALUATION_STALE`; trial-campaign windows yield 409 `ERR_TRIAL_WINDOW_OVERLAP` or 422 `ERR_TRIAL_GAP_VIOLATION`, and within this tier the trial overlap check is evaluated before the trial gap check.
7. **Business constraint.** Constraint-satisfaction failures: 409 `ERR_SERVICE_WINDOW_OVERLAP`, 422 `ERR_STORE_FOOTPRINT_INSUFFICIENT`, 422 `ERR_SHIPMENT_QUANTITY_EXCEEDS`, 422 `ERR_CAPACITY_EXCEEDED`, and 422 `ERR_SHIPMENT_RECONCILE_MISMATCH`.
8. **Business referential.** Cross-reference coherence failures: 422 `ERR_AGREEMENT_STORE_MISMATCH` and 422 `ERR_RETIRE_TARGET_INVALID`.
9. **Business fiscal.** Fiscal gates: 422 `ERR_CAPEX_BUDGET_EXCEEDED` and 422 `ERR_PAYBACK_INELIGIBLE`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the `PlacementAgreement`, and both use the same mechanism. Revising a placement agreement's commercial terms requires the request to carry `expected_agreement_version`, the caller's last observed `version` of that agreement; if the agreement's current `version` has advanced past that value — because another editor has revised the terms since the caller last read it — the revise is rejected with 412 `ERR_STALE_VERSION`, preventing the caller from overwriting terms it has not observed. Installing a chiller against a placement agreement is guarded the same way: the install request must carry `expected_agreement_version` matching the agreement's current `version`, because the terms the caller priced the installation against may have been superseded by a revision; a mismatch is rejected with 412 `ERR_STALE_VERSION`, and the caller must re-read the agreement and resubmit with the current version. `expected_agreement_version` is non-optional on both endpoints, and the comparison is exact equality: any `expected_agreement_version` not equal to the agreement's current `version` — whether behind it or ahead of it — is rejected with 412 `ERR_STALE_VERSION`. Endpoints not named here do not take any version field.

### 2.9. Precision, Rounding, and Monetary Conventions

All money is expressed in whole cents as integers. Scores and payback figures are reported to exactly 2 decimal places using round-half-up. Where a calculation has intermediate steps, the rounding order is pinned per calculation and stated alongside the formula in §3: the installation quote rounds each cost component to whole cents individually (round half up) before summation — summing unrounded components and rounding once at the end is a different, non-conformant algorithm — and the payback estimate rounds weekly units to a whole number of monthly units first, before any margin multiplication or final division. The derived lot shrink rate is reported to 4 decimal places, round half up. The expansion priority indicator on the manufacturing ledger is reported to 2 decimal places, round half up. Durations and minute counts are integers.

### 2.10. Cold-Chain Temperature Governance

The safe cabinet band is 0.0 to 4.0 degrees Celsius, inclusive at both ends. A posted temperature reading is an excursion when its `temp_c` is below 0.0 or above 4.0; exactly 0.0 and exactly 4.0 are in range. Each chiller maintains `excursion_minutes_24h`, a rolling accumulator computed from its own readings only: the sum of `duration_minutes` over excursion readings whose `recorded_at` falls within the inclusive window from 24 hours before the current logical time up to the current logical time, and whose `recorded_at` is strictly later than the chiller's `last_repair_at` (when no repair has ever occurred, that cutoff does not apply). Late-arriving readings — readings posted after readings with a later `recorded_at` — are accepted and count by their `recorded_at`, regardless of posting order. When a newly posted reading pushes the recomputed accumulator to 120 minutes or more, the chiller is deemed severely excursioned and the breach cascade of §3.5 fires: the placement is suspended, its store's sellable inventory is quarantined, and a service ticket is minted automatically. A completed repair stamps `last_repair_at` with the logical now, which recomputes the accumulator to 0 because the window excludes readings at or before that instant.

### 2.11. Conservation Invariants: Product Units and the Chiller Fleet

Product units are conserved across the cold chain. Every `ProductLot` carries five bucket counters — `unshipped_qty`, `in_transit_qty`, `in_store_qty`, `removed_qty`, and `spoiled_qty` — and at all times the lot's `quantity_units` equals the sum of those five buckets; the lot's `conservation_invariant` field documents this equation verbatim as the string `quantity_units == unshipped_qty + in_transit_qty + in_store_qty + removed_qty + spoiled_qty`. Shipment creation moves units from `unshipped_qty` to `in_transit_qty`; dock delivery moves the shipped units out of `in_transit_qty` into `in_store_qty` (accepted units) and `spoiled_qty` (rejected units); spoiling a shipment in transit moves all of its units from `in_transit_qty` to `spoiled_qty`; and a date-check sweep removal moves units from `in_store_qty` to `removed_qty`. A derived shrink rate — the sum of `removed_qty` and `spoiled_qty` divided by `quantity_units`, rounded half up to 4 decimal places — is the program's waste observable.

The chiller fleet obeys three invariants. First, fleet size changes only through batch registration of new chillers — never through installation, retirement, relocation, agreement termination, or decommissioning; decommissioning changes a chiller's status, not the count. Second, at every moment each chiller's `status` is exactly one of `IN_STOCK`, `INSTALLED`, `ACTIVE`, `NEEDS_REPAIR`, or `DECOMMISSIONED`, so the per-status counts always sum to the fleet size. Third, installed capacity — the sum of `capacity_units` over chillers in `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` — is restored exactly by compensating operations: a relocation followed later by a re-install of the same chiller leaves it unchanged net-net, and a removal followed by re-install of the same chiller likewise restores it (for a `STANDARD` unit, 240 units installed dropping to 0 and later returning to 240).

### 2.12. Manufacturing Capacity and Expansion Sequencing

Chiller manufacturing is governed by a capacity ledger with a pinned, top-down evaluation order that must never be reordered:

1. `commissioned_capacity` is the sum of `capacity_delta_units` over all `CapacityProject` rows with `status` `COMMISSIONED`, taken in ascending `sequence_no`.
2. `total_capacity_units` is the base manufacturing capacity of 200 units plus `commissioned_capacity`.
3. `registered_units` is the count of all `Chiller` rows ever created, in any status including `DECOMMISSIONED`.
4. `headroom` is `total_capacity_units` minus `registered_units`.
5. `placement_backlog` is the count of `PlacementAgreement` rows in `SIGNED` or `ACTIVE` status that have no `Placement` with `status` `ACTIVE`.
6. `expansion_priority` is `placement_backlog` multiplied by 100 and divided by the larger of `headroom` and 1, an informational ledger quantity at 2 decimal places, round half up, that is not surfaced on any endpoint response.

Registering a manufactured batch of size `quantity` requires `quantity` to be no greater than `headroom` evaluated at registration time; otherwise the entire batch is rejected atomically with 422 `ERR_CAPACITY_EXCEEDED` — no partial registration occurs. Expansion projects themselves are commissioned strictly in approval order, as detailed in §3.3.

## 3. Business Logic & Workflows

### 3.1. Store Onboarding and Site Evaluation

A `PlatformAdmin` registers each candidate retail store with its display `name`, a free-form `region` label, and the trade-area evidence used by the scoring model: `demographic_index`, `weekly_category_velocity_index`, and `competitor_density_index` — each an integer from 0 to 100 inclusive — plus `available_sqft`, the total floor square footage the store could conceivably allocate (an integer greater than 0), and `distance_miles_from_plant`, the road miles from the manufacturing plant (zero or greater; may be fractional).

Before any agreement is negotiated, a `PlacementManager` commissions a **SiteEvaluation** for the store, supplying a `model_variant` of `DEMOGRAPHIC_LED` or `VELOCITY_LED`, a `chiller_model` of `STANDARD` or `COMPACT`, a `forecast_weekly_units` figure greater than 0 with at most one decimal place (a more precise value is rejected with 400 `ERR_VALIDATION`), and a proposed `allocated_sqft` footprint greater than 0. The evaluation is fully computed at creation and immutable afterwards.

The computed `footprint_score` is the smaller of 100 and the value of 100 times `allocated_sqft` divided by 32 — the reference footprint — rounded half up to a whole number. The `composite_score` then weights the evidence according to the chosen variant. Under `DEMOGRAPHIC_LED`, the score is 0.45 times `demographic_index`, plus 0.25 times `weekly_category_velocity_index`, plus 0.20 times `footprint_score`, minus 0.10 times `competitor_density_index`. Under `VELOCITY_LED`, the same inputs are weighted 0.20, 0.55, 0.15, and 0.10 respectively. The composite is rounded half up to 2 decimal places. Identical inputs can therefore produce different verdicts under the two variants: a store with demographic 80, velocity 90, footprint score 50, and competitor density 20 scores 66.50 under `DEMOGRAPHIC_LED` but 71.00 under `VELOCITY_LED`.

The evaluation also prices the installation. The `install_quote_cents` is the all-in placement capex in whole cents: a unit cost of 325000 cents for a `STANDARD` chiller or 218000 cents for a `COMPACT`, plus a flat installation fee of 45000 cents, plus the footprint component (the `allocated_sqft` times 1250 cents per square foot, rounded half up to whole cents), plus the distance component (the store's `distance_miles_from_plant` times 925 cents per mile, rounded half up to whole cents). Each component is rounded to whole cents individually, round half up, before the four components are summed.

A pro-forma payback accompanies the quote. Weekly units are converted to monthly units by multiplying by 13 and dividing by 3, rounding half up to a whole number of units first; that integer is multiplied by the unit margin of 180 cents to obtain monthly margin; and `payback_months` is the `install_quote_cents` divided by the monthly margin, rounded half up to 2 decimal places. If the rounded monthly units are zero, `payback_months` is null — the zero-velocity guard. Carrying fractional monthly units into the margin multiplication is non-conformant: at a cost of 291600 cents and 10.4 forecast weekly units, the pinned order yields 36.00 months, while the unrounded variant would yield 35.95.

The evaluation's `verdict` is `ELIGIBLE` when the `composite_score` is at least 60.0 and `payback_months` is at most 36.0 — both boundaries inclusive — and `INELIGIBLE` otherwise. Evaluations for a store are listed in `created_at` ascending order, newest evidence last.

### 3.2. Placement Agreements: Negotiation, Signing, and Termination

With a favorable evaluation in hand, a `PlacementManager` opens a **PlacementAgreement** with the store, recording the negotiated `allocated_sqft` (greater than 0), the `max_capex_cents` ceiling on all-in placement spend under the agreement (greater than 0), and a `term_months` duration between 1 and 120 inclusive. An agreement is born `PROPOSED`, with `signed_at` and `terminated_at` both null.

Negotiation rounds rewrite the commercial terms in place: revising a `PROPOSED` agreement loops it back to `PROPOSED`, applying whichever of `allocated_sqft`, `max_capex_cents`, or `term_months` are supplied and keeping prior values for the rest. This revise is OCC-guarded per §2.8 — the request must carry `expected_agreement_version` equal to the agreement's current `version`, or it fails with 412 `ERR_STALE_VERSION` — and each successful revise increments the agreement's `version` by 1.

Signing moves `PROPOSED` to `SIGNED`, stamps `signed_at` with the logical now, and increments `version`. A `SIGNED` agreement becomes `ACTIVE` automatically the first time an installation naming it succeeds — a system transition, not a client call.

Termination is available from `PROPOSED`, `SIGNED`, or `ACTIVE` and always lands in the terminal `TERMINATED` state with `terminated_at` stamped and `version` incremented. Terminating an `ACTIVE` agreement fires a three-hop cascade: every `ACTIVE` placement governed by that agreement becomes `RETIRED` with `retired_reason` set to `AGREEMENT_TERMINATION` (each placement's `version` increments); each such placement's chiller returns from `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` to `IN_STOCK` (each chiller's `version` increments); and every `OPEN` or `DISPATCHED` service ticket naming one of those chillers becomes `CANCELLED` (each ticket's `version` increments).

### 3.3. Chiller Manufacturing, Fleet Registration, and Capacity Expansion

A `ProductionPlanner` registers each manufactured batch of identical chillers by declaring the `model` (`STANDARD` or `COMPACT`), a `serial_prefix`, and a `quantity` of at least 1. The system mints each unit's `serial_no` as the prefix, a hyphen, and a 4-digit zero-padded sequence number — for example `FP-0007`. Numbering starts at `serial_start_seq` when the caller supplies it (a value of at least 1, otherwise 400 `ERR_VALIDATION`), and otherwise at one more than the largest numeric suffix currently in use for that prefix across the fleet — or at 1 when the prefix is unused. Serial numbers are unique across the fleet: if the batch would mint any `serial_no` that already exists, the whole batch is rejected with 409 `ERR_SERIAL_NOT_UNIQUE`. The batch is also checked against manufacturing headroom per §2.12; a batch whose `quantity` exceeds current headroom is rejected atomically with 422 `ERR_CAPACITY_EXCEEDED`. A successful registration responds 201 with the array of the minted chiller objects. Derived unit economics are fixed by model: a `STANDARD` chiller holds 240 units of product on a `footprint_sqft` of 8, while a `COMPACT` holds 120 units on 5 square feet. New chillers arrive `IN_STOCK` with `last_repair_at` null. A `PlatformAdmin` may decommission an `IN_STOCK` chiller, moving it to the terminal `DECOMMISSIONED` state; attempting it in any other status is rejected with 409 `ERR_INVALID_STATE`. The fleet list endpoint's pagination `total_count` doubles as the fleet-size observable, with optional `status` and `model` filters.

When placement growth outruns the base capacity of 200 units, a `ProductionPlanner` proposes a **CapacityProject** with a `name` and a `capacity_delta_units` greater than 0; the system records the creator's `X-User-ID` as `created_by_user_id`. Approval is a `PlatformAdmin` action on a `PROPOSED` project — any other starting state yields 409 `ERR_INVALID_STATE` — and segregation of duties forbids the approver's `X-User-ID` from equalling `created_by_user_id`, on pain of 403 `ERR_SEGREGATION_OF_DUTIES`. Approval pins the project's `sequence_no` to one more than the maximum `sequence_no` over all projects that already have one, or 1 when none do; once set, the sequence number is immutable. Commissioning moves `APPROVED` to the terminal `COMMISSIONED` state and updates the ledger's `commissioned_capacity`, but only in strict approval order: if any other project is still `APPROVED` with a strictly smaller `sequence_no`, the commission is rejected with 409 `ERR_EXPANSION_SEQUENCE_VIOLATION`.

### 3.4. Installing a Chiller: The Placement Gate

Installation is the program's most heavily fenced operation. A `PlacementManager` installs by naming a `store_id`, an `agreement_id`, a `chiller_id`, and — per §2.8 — the `expected_agreement_version` of the governing agreement. The gates, in validation-tier order: the agreement must be `SIGNED` (otherwise 409 `ERR_AGREEMENT_NOT_SIGNED`); the chiller must be `IN_STOCK` (otherwise 409 `ERR_CHILLER_NOT_IN_STOCK`); the store must not already have a placement with `status` `ACTIVE` (otherwise 409 `ERR_DUPLICATE_ACTIVE_PLACEMENT`); the `expected_agreement_version` must match the agreement's current `version` (otherwise 412 `ERR_STALE_VERSION`); the store's latest SiteEvaluation must be fresh, created within 90 days of the logical now, the boundary inclusive (a latest evaluation older than 90 days yields 422 `ERR_EVALUATION_STALE`; a store with no SiteEvaluation at all is not stale — it instead fails the final fiscal gate below with 422 `ERR_PAYBACK_INELIGIBLE`); the chiller's `footprint_sqft` must not exceed the agreement's `allocated_sqft` (otherwise 422 `ERR_STORE_FOOTPRINT_INSUFFICIENT`); the placement's `store_id` must equal the agreement's own store (otherwise 422 `ERR_AGREEMENT_STORE_MISMATCH`); and two fiscal gates close the review — the freshly computed `installed_quote_cents` must not exceed the agreement's `max_capex_cents` (otherwise 422 `ERR_CAPEX_BUDGET_EXCEEDED`), and the store's latest SiteEvaluation `verdict` must be `ELIGIBLE` (otherwise 422 `ERR_PAYBACK_INELIGIBLE`).

A successful installation creates the **Placement** in `status` `ACTIVE` with `performance_status` `PENDING`, `operational_status` `OK`, and `underperforming_streak` 0. Three parallel state dimensions govern the placement from then on — lifecycle `status`, velocity-driven `performance_status`, and chiller-health-driven `operational_status`; the performance and operational dimensions evolve independently and never gate each other, and only the lifecycle `status` gates them. The installation snapshots `installed_quote_cents` from the installation-quote calculation using the chiller's model, the agreement's `allocated_sqft`, and the store's `distance_miles_from_plant`, and initializes `standing_deliveries_per_week` and `safety_stock_units` from the governing evaluation's `forecast_weekly_units` per the delivery plan of §3.6. `last_reported_weekly_units` and `payback_actuals_months` start null, as do `retired_reason` and `relocated_to_placement_id`. In the same transaction the chiller moves `IN_STOCK` to `INSTALLED` (its `version` increments) and the agreement moves `SIGNED` to `ACTIVE` (its `version` increments). Placements can be listed with optional filters on `store_id`, `chiller_id`, `agreement_id`, `status`, and `relocated_to_placement_id`.

### 3.5. Telemetry, Excursions, and the Service Network

Once a chiller is installed, telemetry flows in from the store. A reading posts a `recorded_at` timestamp, a `temp_c` in Celsius, and the `duration_minutes` it represents. The chiller must be `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` — readings for an `IN_STOCK` or `DECOMMISSIONED` unit are rejected with 409 `ERR_INVALID_STATE`. The `recorded_at` must not lie in the future of the logical clock, `temp_c` must stay within the sensor-plausible range of -40.0 to 60.0 inclusive, and `duration_minutes` must be between 1 and 1440 inclusive; any of these shape failures yields 400 `ERR_VALIDATION`. Either a `PlatformAdmin` or the `StoreOperator` of the store hosting the chiller's `ACTIVE` placement may post; a `StoreOperator` whose `X-User-ID` names any other store — or who posts for a chiller with no `ACTIVE` placement at all — is rejected with 403 `ERR_STORE_OWNERSHIP_MISMATCH`. Because this ownership check derives the store from the chiller's `ACTIVE` placement, the chiller's existence is resolved first, so an unresolvable chiller identifier yields 404 `ERR_NOT_FOUND` before ownership is evaluated. Each reading's `is_excursion` is computed per the safe band of §2.10, and readings are listed in `recorded_at` ascending order — ties break by arrival order — and late-arriving readings still count in the accumulator by their `recorded_at`.

Two automatic transitions hang off the accumulator. The first in-range reading posted to an `INSTALLED` chiller activates it: `INSTALLED` becomes `ACTIVE`, and the chiller's `version` increments. Conversely, when a posted reading pushes the recomputed `excursion_minutes_24h` to 120 minutes or more — the severe threshold, boundary inclusive — a chiller in `INSTALLED` or `ACTIVE` degrades to `NEEDS_REPAIR` and a three-hop cascade fires: the placement using this chiller, if `ACTIVE`, has its `operational_status` driven to `SUSPENDED` (placement `version` increments); every `SELLABLE` inventory position at that placement's store becomes `QUARANTINED` (each position's `version` increments); and a service ticket is minted against the chiller with `origin` `AUTO_EXCURSION`, `status` `OPEN`, and the `issue_summary` text "AUTO: severe temperature excursion". The chiller's own `version` increments as well.

The service network works tickets through a simple machine. A `ServiceDispatcher` or the hosting `StoreOperator` can also open a ticket manually with a `chiller_id` and free-text `issue_summary`; no store-ownership check applies to manual creation — any `ServiceDispatcher` or `StoreOperator` may open a ticket for any existing chiller — and such tickets carry `origin` `MANUAL` and start `OPEN`, with `window_start`, `window_end`, and `resolution_note` all null. Dispatching is the `ServiceDispatcher`'s exclusive action and moves `OPEN` to `DISPATCHED` — dispatching a ticket in any other state yields 409 `ERR_INVALID_STATE`. The dispatch window is a half-open interval from `window_start` (inclusive) to `window_end` (exclusive): `window_end` must be strictly later than `window_start` (otherwise 400 `ERR_WINDOW_INVALID`), and the window must not overlap any other `DISPATCHED` ticket's window on the same chiller — touching endpoints are not an overlap, so an existing window ending exactly when the new one starts, or the new one ending exactly when an existing one starts, is allowed — otherwise 409 `ERR_SERVICE_WINDOW_OVERLAP`. Dispatch records `window_start` and `window_end` and increments the ticket's `version`. Tickets for a chiller are listed with an optional `status` filter, in `created_at` ascending order.

Resolution is the `FieldTechnician`'s exclusive action, available from either `OPEN` or `DISPATCHED`, and lands the ticket in the terminal `RESOLVED` state with the technician's `resolution_note` recorded and `version` incremented. Resolving a terminal ticket is rejected with 409 `ERR_INVALID_STATE`. When the resolved ticket's chiller is `NEEDS_REPAIR`, the resolution doubles as the repair: the chiller returns to `ACTIVE`, `last_repair_at` is stamped with the logical now (which recomputes `excursion_minutes_24h` to 0, since the window excludes readings at or before `last_repair_at`), and the placement's `operational_status` lifts from `SUSPENDED` back to `OK` with its `version` incrementing. Quarantined inventory positions are deliberately not auto-restored by the repair — they await the date-check sweep of §3.7. The remaining ticket transition is a cancellation cascade: whenever a chiller returns to `IN_STOCK` — through placement retirement, agreement termination, or relocation — every `OPEN` or `DISPATCHED` ticket naming that chiller becomes `CANCELLED`, terminal, with its `version` incremented.

### 3.6. Performance Evaluation, Delivery Planning, and Removal

A `PlacementManager` reports each placement's trailing 13-week average weekly velocity by calling evaluate-performance with `trailing_weekly_units`, a non-negative integer (any other value fails request shape with 400 `ERR_VALIDATION`). The placement must be `ACTIVE`, or the call fails with 409 `ERR_PLACEMENT_NOT_ACTIVE`. The verdict threshold is the velocity floor of 40 units per week, boundary inclusive: at 40 or more the placement's `performance_status` becomes `PERFORMING` and its `underperforming_streak` resets to 0; below 40 it becomes `UNDERPERFORMING` and the streak advances — to 1 when arriving from `PERFORMING` or from a `PENDING` state whose streak is 0, and otherwise one more than the previous streak. Every evaluation also records the report in `last_reported_weekly_units`, recomputes the delivery plan and the actuals payback, and increments the placement's `version`.

The delivery plan tiers standing frequency by velocity: 5 deliveries per week at 300 or more units, 3 at 150 or more, 2 at 60 or more, 1 at 25 or more, and 0 below 25 — each tier boundary inclusive on its lower bound. The `safety_stock_units` ceiling is the smaller of the chiller's `capacity_units` and the velocity times the 45-day shelf life divided by 7 days and multiplied by the safety factor 1.25, rounded half up to whole units. The actuals payback, `payback_actuals_months`, reruns the payback calculation of §3.1 on `trailing_weekly_units` against the placement's snapshot `installed_quote_cents` — same pinned rounding order, same zero-velocity guard leaving the field null when rounded monthly units are zero. The two variants answer different questions with the same economics: at a snapshot cost of 399000 cents, a forecast of 200 units per week implies a 2.56-month pro-forma payback, while reported actuals of 100 units per week imply 5.12 months.

Removal works through the retire action with a `mode`. Under `mode` `REMOVE`, a `removal_reason` is required — omitting it yields 422 `ERR_RETIRE_TARGET_INVALID` — and must be one of `UNDERPERFORMANCE_REMOVAL`, `AGREEMENT_TERMINATION`, or `RELOCATION` (any other value fails request shape with 400 `ERR_VALIDATION`). Only the reason `UNDERPERFORMANCE_REMOVAL` is gated on evidence: the placement's `performance_status` must be `UNDERPERFORMING` with an `underperforming_streak` of at least 2, otherwise 409 `ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT`; the other two reasons retire without an evidence gate. Fields not applicable to the chosen `mode` are inert: `target_store_id` and `target_agreement_id` supplied under `REMOVE`, or `removal_reason` supplied under `RELOCATE`, are accepted and ignored, without even being resolved for existence. Retirement stamps `retired_reason`, returns the chiller from `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` to `IN_STOCK` (chiller `version` increments), cancels that chiller's `OPEN` and `DISPATCHED` tickets, and increments the placement's `version` as it lands in terminal `RETIRED`.

Under `mode` `RELOCATE`, the caller supplies `target_store_id` and `target_agreement_id`; either one omitted yields 422 `ERR_RETIRE_TARGET_INVALID` at the referential tier, and either one supplied but unresolvable yields 404 `ERR_NOT_FOUND`, with supplied references resolved in field order (`target_store_id`, then `target_agreement_id`). The target agreement must hold `status` `SIGNED` — a state-tier precondition of the transition, rejected with 409 `ERR_AGREEMENT_NOT_SIGNED`. The remaining gates evaluate in validation-tier order: first the target store's latest SiteEvaluation must be fresh, created within 90 days of logical now (otherwise 422 `ERR_EVALUATION_STALE`; a target store with no SiteEvaluation at all is not stale and fails the fiscal gate instead); then the chiller's `footprint_sqft` must fit the target agreement's `allocated_sqft` (otherwise 422 `ERR_STORE_FOOTPRINT_INSUFFICIENT`); then the referential checks — the target store must differ from the placement's current store (otherwise 422 `ERR_RETIRE_TARGET_INVALID`) and the target agreement must belong to the target store (otherwise 422 `ERR_AGREEMENT_STORE_MISMATCH`); and finally the two fiscal gates — the freshly computed installation quote at the target must not exceed the target agreement's `max_capex_cents` (otherwise 422 `ERR_CAPEX_BUDGET_EXCEEDED`), and the target store's latest SiteEvaluation `verdict` must be `ELIGIBLE` (otherwise 422 `ERR_PAYBACK_INELIGIBLE`, which is also the outcome when the target store has no SiteEvaluation). The duplicate-active-placement gate of §3.4 does not apply to a relocation target. A relocation retires the old placement with `retired_reason` `RELOCATION`, creates a successor placement at the target store under the same `chiller_id` — born `ACTIVE`, `PENDING`, `OK`, with `standing_deliveries_per_week` and `safety_stock_units` initialized from the target store's latest evaluation's `forecast_weekly_units` and `installed_quote_cents` re-snapshotted from the target agreement's terms — and points the old placement's `relocated_to_placement_id` at the successor. The target agreement advances `SIGNED` to `ACTIVE`, the chiller passes logically through `IN_STOCK` and lands `INSTALLED` at the target with a single net `version` increment, and the chiller's open tickets are cancelled as in a plain removal. Both retire modes respond 200 with the retired placement object — under `RELOCATE`, the one whose `relocated_to_placement_id` now names the successor.

### 3.7. Distribution: Lots, Shipments, and In-Store Inventory

Production starts at the plant, where a `ProductionPlanner` registers each **ProductLot** with its `sku`, a `produced_at` timestamp that must not lie in the future of the logical clock, and a `quantity_units` greater than 0. A new lot enters `QUARANTINE`; its `expires_at` is computed as `produced_at` plus the 45-day shelf life; and its buckets initialize with `unshipped_qty` equal to `quantity_units` and `in_transit_qty`, `in_store_qty`, `removed_qty`, and `spoiled_qty` all 0. Quality release is the same planner's gate: calling release with `qc_passed` true moves the lot to `RELEASED`, while false rejects it terminally as `REJECTED`; releasing a lot not in `QUARANTINE` yields 409 `ERR_INVALID_STATE`. Thereafter the lazy expiry rule of §2.4 applies to both `QUARANTINE` and `RELEASED` lots.

With released stock and a live route, a `LogisticsCoordinator` dispatches a refrigerated shipment naming `store_id`, `lot_id`, and `quantity_units`. The destination store must have a placement with `status` `ACTIVE` (otherwise 409 `ERR_PLACEMENT_NOT_ACTIVE`), that placement's `operational_status` must be `OK` (otherwise 409 `ERR_PLACEMENT_NOT_OPERATIONAL`), and its `standing_deliveries_per_week` must be greater than 0 (otherwise 409 `ERR_DELIVERY_ROUTE_INACTIVE`). The lot must be `RELEASED` — a `QUARANTINE` or `REJECTED` lot yields 409 `ERR_LOT_NOT_RELEASED` — and must not have materialized `EXPIRED`, which yields 422 `ERR_LOT_EXPIRED`; the lazy expiry materialization of §2.4 applies before these checks, so a lot past its `expires_at` yields 422 `ERR_LOT_EXPIRED` even if it never left `QUARANTINE`. The `quantity_units` must not exceed the lot's `unshipped_qty` nor the placement's `safety_stock_units`, on pain of 422 `ERR_SHIPMENT_QUANTITY_EXCEEDS`. The truck departs immediately: `departed_at` is stamped with the logical now at creation, the shipment is born `IN_TRANSIT`, and the lot's buckets move `quantity_units` from `unshipped_qty` to `in_transit_qty`. Shipments are listed with optional `store_id`, `lot_id`, and `status` filters.

Dock reconciliation delivers an `IN_TRANSIT` shipment — any other status yields 409 `ERR_INVALID_STATE`. Safety is checked before the transit window: a lot that has materialized `EXPIRED` rejects the delivery with 422 `ERR_LOT_EXPIRED`. The transit window then allows delivery only while the logical now is at most 48 hours after `departed_at`, boundary inclusive. If the window is exceeded, the shipment is persisted as `SPOILED` — its units move from `in_transit_qty` to `spoiled_qty` — and the call then responds 422 `ERR_TRANSIT_WINDOW_EXCEEDED`; the same lazy spoiling materializes on any read that observes the logical now past the window. A successful delivery requires the counts to reconcile: `accepted_units` plus `rejected_units` — each a non-negative integer — must equal the shipment's `quantity_units`, otherwise 422 `ERR_SHIPMENT_RECONCILE_MISMATCH`. On success `delivered_at` is stamped, rejected units land in `spoiled_qty`, and accepted units move into `in_store_qty`; when `accepted_units` is greater than 0 the system creates or merges an **InventoryPosition** for the store-and-lot pair — at most one non-`REMOVED` position exists per pair, and delivery into an existing position merges by adding the accepted units to `qty_on_hand` without changing the position's `status`, so a `QUARANTINED` position stays `QUARANTINED` — while a newly created position carries `status` `SELLABLE` and `expiry_date` copied from the lot's `expires_at`. Positions can be listed with `store_id`, `lot_id`, and `status` filters.

In-store date checking is the final line of defense. The date-check sweep at a store is run by the `StoreOperator` who owns that path store (otherwise 403 `ERR_STORE_OWNERSHIP_MISMATCH`) or by a `PlacementManager`. It removes three kinds of positions, evaluating reasons in a fixed order — `EXPIRED` first, then `COLD_CHAIN_BREACH`, then `NEAR_EXPIRY`. A `SELLABLE` position whose `expiry_date` is earlier than the logical now is removed with `removal_reason` `EXPIRED`; a `SELLABLE` position whose whole days until expiry — the difference between `expiry_date` and now, floored to days — is 7 or fewer is removed with `removal_reason` `NEAR_EXPIRY`; and a `QUARANTINED` position is removed with `removal_reason` `EXPIRED` when past expiry, otherwise `COLD_CHAIN_BREACH`. Each removal moves the position's `qty_on_hand` from the lot's `in_store_qty` into `removed_qty` and increments the position's `version` as it reaches terminal `REMOVED`. The sweep reports `positions_removed` and `units_removed` in total, broken out as `expired_units`, `cold_chain_breach_units`, and `near_expiry_units`.

### 3.8. Consumer Trial Campaigns

Building the category takes shopper-facing effort, so a `PlacementManager` can launch a **TrialCampaign** at a store that has at least one placement with `status` `ACTIVE` — a store with none is rejected with 409 `ERR_PLACEMENT_NOT_ACTIVE`. The campaign carries a `name`, a `start_date`, and an `end_date`, each submitted as an ISO 8601 timestamp — conventionally a date at 00:00:00Z, which is the expected representation but is not server-enforced; any valid timestamp is accepted — and the pair delimits a closed interval: the `end_date` must be on or after the `start_date`, or the request fails 400 `ERR_VALIDATION`. The overlap rule compares the two closed intervals by their exact timestamps, while the 14-day gap is day-granular: the difference between the boundary timestamps is floored to whole days, so a gap of exactly 14 days is allowed and any difference flooring to fewer than 14 days violates the rule. Two campaigns at the same store must keep clear of each other under two rules evaluated in a fixed intra-tier order, and both rules are checked against every existing campaign at the store, whatever its status — including campaigns that have already materialized `COMPLETED`. First, their closed-interval windows must not intersect at all — sharing even a single start or end date counts as overlap and is rejected with 409 `ERR_TRIAL_WINDOW_OVERLAP`. Second, a 14-day gap must separate one campaign's `end_date` from the next campaign's `start_date`; the boundary is inclusive, so a start exactly 14 days after a prior `end_date` is allowed, while fewer than 14 days in either direction yields 422 `ERR_TRIAL_GAP_VIOLATION`. A campaign is `ACTIVE` on creation, materializes `COMPLETED` lazily once the logical now passes one day beyond its `end_date`, and campaigns are listed in `start_date` ascending order.

## 4. Endpoint Definitions

Operations that create a new resource — registering a store, evaluation, agreement, chiller batch, reading, placement, ticket, shipment, lot, capacity project, or trial campaign — return 201. Operations that modify an existing resource in place — revise, sign, terminate, decommission, evaluate-performance, retire, dispatch, resolve, deliver, release, sweep, approve, commission — return 200, as does the logical-clock endpoint. Readers should reconstruct each operation's full request and side effects from the §3 narratives; this table is intentionally a summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (unprefixed platform endpoint) | PlatformAdmin |
| POST | `/cold-chain/stores` | Register a retail store candidate | PlatformAdmin |
| GET | `/cold-chain/stores/{id}` | Fetch one store | Any declared role |
| POST | `/cold-chain/stores/{id}/site-evaluations` | Create a computed SiteEvaluation for a store | PlacementManager |
| GET | `/cold-chain/stores/{id}/site-evaluations` | List a store's evaluations, created_at ascending | Any declared role |
| POST | `/cold-chain/stores/{id}/placement-agreements` | Open a placement agreement (PROPOSED) | PlacementManager |
| GET | `/cold-chain/stores/{id}/placement-agreements` | List a store's agreements, created_at ascending | Any declared role |
| POST | `/cold-chain/placement-agreements/{id}/revise` | Revise a PROPOSED agreement's terms (OCC-guarded) | PlacementManager |
| POST | `/cold-chain/placement-agreements/{id}/sign` | Sign a PROPOSED agreement | PlacementManager |
| POST | `/cold-chain/placement-agreements/{id}/terminate` | Terminate an agreement; cascades over placements, chillers, tickets | PlacementManager |
| POST | `/cold-chain/chillers` | Register a manufactured batch of chillers | ProductionPlanner |
| GET | `/cold-chain/chillers` | List the fleet with optional status/model filters | Any declared role |
| GET | `/cold-chain/chillers/{id}` | Fetch one chiller including excursion_minutes_24h | Any declared role |
| POST | `/cold-chain/chillers/{id}/decommission` | Decommission an IN_STOCK chiller | PlatformAdmin |
| POST | `/cold-chain/chillers/{id}/temperature-readings` | Post a telemetry reading for a chiller | StoreOperator, PlatformAdmin |
| GET | `/cold-chain/chillers/{id}/temperature-readings` | List a chiller's readings, recorded_at ascending | Any declared role |
| POST | `/cold-chain/placements` | Install a chiller at a store under a SIGNED agreement (OCC-guarded) | PlacementManager |
| GET | `/cold-chain/placements` | List placements with optional FK/status filters | Any declared role |
| GET | `/cold-chain/placements/{id}` | Fetch one placement including computed plan fields | Any declared role |
| POST | `/cold-chain/placements/{id}/evaluate-performance` | Report trailing weekly velocity; drives performance, plan, payback | PlacementManager |
| POST | `/cold-chain/placements/{id}/retire` | Retire a placement via REMOVE or RELOCATE | PlacementManager |
| POST | `/cold-chain/service-tickets` | Manually open a service ticket for a chiller | ServiceDispatcher, StoreOperator |
| GET | `/cold-chain/chillers/{id}/service-tickets` | List a chiller's tickets, created_at ascending | Any declared role |
| POST | `/cold-chain/service-tickets/{id}/dispatch` | Dispatch an OPEN ticket into a half-open service window | ServiceDispatcher |
| POST | `/cold-chain/service-tickets/{id}/resolve` | Resolve an OPEN or DISPATCHED ticket; performs the repair | FieldTechnician |
| POST | `/cold-chain/shipments` | Dispatch a refrigerated shipment (departs immediately) | LogisticsCoordinator |
| GET | `/cold-chain/shipments` | List shipments with optional FK/status filters | Any declared role |
| GET | `/cold-chain/shipments/{id}` | Fetch one shipment (lazy SPOILED applies on read) | Any declared role |
| POST | `/cold-chain/shipments/{id}/deliver` | Dock reconciliation of an IN_TRANSIT shipment | LogisticsCoordinator |
| POST | `/cold-chain/product-lots` | Register a produced lot (enters QUARANTINE) | ProductionPlanner |
| GET | `/cold-chain/product-lots/{id}` | Fetch one lot including conservation buckets (lazy EXPIRED on read) | Any declared role |
| POST | `/cold-chain/product-lots/{id}/release` | Quality gate: release or terminally reject a QUARANTINE lot | ProductionPlanner |
| GET | `/cold-chain/inventory-positions` | List inventory positions with optional FK/status filters | Any declared role |
| GET | `/cold-chain/inventory-positions/{id}` | Fetch one inventory position | Any declared role |
| POST | `/cold-chain/stores/{id}/inventory/date-check-sweep` | Run date-check removal at a store; reports removal counts | StoreOperator, PlacementManager |
| POST | `/cold-chain/capacity-projects` | Propose a manufacturing-capacity expansion project | ProductionPlanner |
| POST | `/cold-chain/capacity-projects/{id}/approve` | Approve a PROPOSED project; pins sequence_no (SoD enforced) | PlatformAdmin |
| POST | `/cold-chain/capacity-projects/{id}/commission` | Commission the lowest-sequence APPROVED project | PlatformAdmin |
| POST | `/cold-chain/stores/{id}/trial-campaigns` | Launch a consumer trial campaign at a store | PlacementManager |
| GET | `/cold-chain/stores/{id}/trial-campaigns` | List a store's campaigns, start_date ascending (lazy COMPLETED on read) | Any declared role |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is a summary of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_CLOCK_REGRESSION` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_STORE_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_NOT_SIGNED` | 409 |
| `ERR_CHILLER_NOT_IN_STOCK` | 409 |
| `ERR_PLACEMENT_NOT_ACTIVE` | 409 |
| `ERR_PLACEMENT_NOT_OPERATIONAL` | 409 |
| `ERR_DUPLICATE_ACTIVE_PLACEMENT` | 409 |
| `ERR_LOT_NOT_RELEASED` | 409 |
| `ERR_DELIVERY_ROUTE_INACTIVE` | 409 |
| `ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT` | 409 |
| `ERR_EXPANSION_SEQUENCE_VIOLATION` | 409 |
| `ERR_SERIAL_NOT_UNIQUE` | 409 |
| `ERR_SERVICE_WINDOW_OVERLAP` | 409 |
| `ERR_TRIAL_WINDOW_OVERLAP` | 409 |
| `ERR_TRIAL_GAP_VIOLATION` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_TRANSIT_WINDOW_EXCEEDED` | 422 |
| `ERR_EVALUATION_STALE` | 422 |
| `ERR_STORE_FOOTPRINT_INSUFFICIENT` | 422 |
| `ERR_SHIPMENT_QUANTITY_EXCEEDS` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_SHIPMENT_RECONCILE_MISMATCH` | 422 |
| `ERR_AGREEMENT_STORE_MISMATCH` | 422 |
| `ERR_RETIRE_TARGET_INVALID` | 422 |
| `ERR_CAPEX_BUDGET_EXCEEDED` | 422 |
| `ERR_PAYBACK_INELIGIBLE` | 422 |
| `ERR_WINDOW_INVALID` | 400 |
