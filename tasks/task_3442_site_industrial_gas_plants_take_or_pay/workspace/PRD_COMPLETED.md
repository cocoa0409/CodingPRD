# Onsite Gas Take-or-Pay API — Product Requirements Document

## 1. Introduction

Industrial gas reaches a customer through four very different channels — a dedicated plant built on the customer's own fence line, a supplier pipeline running past the site, cryogenic tankers topping up a bulk liquid tank, or cylinders for the smallest offtakes — and choosing among them is a commercial decision worth millions of dollars over a decade. This document specifies the API for a supplier platform that manages that decision and everything that follows it: supply-mode evaluation, long-term take-or-pay contracting with minimum-volume commitments and power-cost pass-through, plant construction and maintenance turnarounds, pipeline capacity reservation, telemetry-driven liquid logistics with certified product quality, and monthly settlement against a capped makeup-credit bank.

Two design commitments shape every rule below. First, time inside the platform is logical, not wall-clock: renewal windows, contract expiry, and turnaround completion are all consequences of a controllable clock advancing, so the entire lifecycle can be exercised deterministically. Second, the commercial model is uncompromisingly take-or-pay — the monthly minimum is billed whether or not the gas is taken, shortfall payments accrue credit under a strict bank ledger, and every cent is accounted for in integer arithmetic. All business resources are mounted under the `/gas-supply` prefix; the logical clock is a platform-level capability that sits outside that prefix.

## 2. Global Specifications & System-Wide Principles

This section fixes the system-wide contract: authentication, response shape, pagination, timekeeping, resource conventions, numeric discipline, concurrency control, and the order in which the server evaluates every request.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the nine declared roles. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to call the endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The nine roles are:

- `PlatformAdmin` — the supplier's platform administrator; owns customer onboarding, pipeline network registration, and the logical clock.
- `SupplyPlanner` — the supplier's commercial planner; runs supply-mode evaluations and owns the contract lifecycle.
- `CustomerOps` — a customer-side operations user; accepts mode evaluations and negotiates turnaround windows for their own sites.
- `PlantOperator` — supplier plant operations; builds plants, registers tanks, and drives maintenance turnarounds.
- `PipelineDispatcher` — pipeline and logistics dispatcher; reserves network capacity and confirms deliveries.
- `TelemetryGateway` — the automated ingestion gateway through which tank telemetry arrives.
- `QualityAnalyst` — laboratory analyst; records analytical results.
- `QualityCertifier` — laboratory certifier; certifies or fails recorded results, and must never certify a result they recorded themselves.
- `BillingSpecialist` — settlement accountant; runs provisional and final take-or-pay settlements.

Identity semantics differ by role. When `X-User-Role` is `CustomerOps`, `X-User-ID` is the `id` of the acting Customer: ownership checks on any resource that references a customer compare that customer reference to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is `PlatformAdmin`, `SupplyPlanner`, `PlantOperator`, `PipelineDispatcher`, `TelemetryGateway`, `QualityAnalyst`, `QualityCertifier`, or `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `analyst_user_id` on a quality certificate — but never compares it to any entity's `id`.

Read access is broad: every declared role may call any GET endpoint. Write access is segregated per the endpoint table in §4.

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

Endpoints that return collections accept two pagination query parameters. `limit` sets the maximum number of items returned; when omitted it defaults to 10, and it may not be less than 1 or greater than 100. `offset` sets how many items are skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION`. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by monotonic creation sequence, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Collection endpoints additionally accept resource-specific filters, combinable with `limit` and `offset`: the contract list filters by `customer_id`, `evaluation_id`, or `status`; the plant list by `customer_id` or `contract_id`; the connection list by `network_id`, `contract_id`, or `status`; the tank list by `customer_id` or `status`; and the delivery list by `tank_id`, `customer_id`, `transport_status`, or `quality_status`.

### 2.4. The Logical Clock and Scheduled Sweeps

The platform never consults wall-clock time. At server startup, before any client call, the logical clock reads exactly 2026-09-01T00:00:00Z, and it advances only when a `PlatformAdmin` sets it through the clock capability mounted at the server root — `/_clock/set_current_utc`, deliberately outside the `/gas-supply` prefix — by supplying a `current_utc` ISO 8601 instant; the call answers 200. The setter places the clock at the supplied instant unconditionally — no monotonicity guard is applied. Everywhere the business logic says "now" or "today" — the `route_date` stamped onto a created delivery, the `confirmed_at` of a delivery confirmation, the `decided_at` of a quality decision, the due check on a turnaround start — the value is read from this clock.

Every clock set runs a three-part sweep across the platform:

- Any contract in `ACTIVE` whose `end_date` is at most ninety days away — the current time is at or after `end_date` minus ninety days, with `end_date` read as midnight UTC at the start of that calendar day — moves to `RENEWAL_OPEN`.
- Any contract whose `end_date` has passed — the current time is strictly after midnight UTC at the start of `end_date`'s calendar day — moves from `RENEWAL_OPEN` to `EXPIRED`. Both contract rules run inside the same clock set, so a contract still `ACTIVE` when its `end_date` has already passed moves through `RENEWAL_OPEN` to `EXPIRED` in a single set.
- Any turnaround in `IN_PROGRESS` whose `window_end` is at or before the current time completes, returning its plant to `OPERATING` if the plant is still parked in `TURNAROUND` and clearing the contract's failover flag either way (see §3.7).

### 2.5. Common Resource Properties

All primary resources — customers, evaluations, contracts, plants, networks, connections, tanks, deliveries, certificates, turnarounds, and settlement statements — share four system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version`: an integer that starts at 1 at creation and increments on every mutation of the resource; `updated_at` initially equals `created_at`.

Timestamps supplied by clients — `measured_at`, `window_start`, `window_end`, `sampled_at`, and blackout `start_iso`/`end_iso` values — are stored and echoed verbatim in the exact string form submitted; the canonical three-fractional-digit UTC form above applies only to server-generated timestamps. For ordering and window comparisons, a submitted datetime without an offset is read as UTC.

`TelemetryReading` is the single exception. As an append-only measurement it carries only `id` and `created_at`; `updated_at` and `version` are absent from it entirely.

### 2.6. Money, Units, and Rounding Discipline

Money is integer cents everywhere — prices, fees, charges, and credits — and no API field ever carries a fractional cent. Where a computed monetary value is not naturally integral, it is rounded half up to whole cents at exactly the point the specification says so. Gas volumes are normal cubic meters (Nm3) and flows are Nm3/h; cryogenic product is measured in liters; power indices are currency per kWh. Two computations deliberately depart from plain round-half-up: the facility-fee escalation multiplier is kept at four decimal places with round-half-up applied once per elapsed year (§3.8), and monthly capital recovery is rounded down with floor semantics. Tank burn rates are carried as exact rational liters-per-hour values, while projected runout timestamps are rounded half up to whole seconds. On the API, burn rates are emitted as ordinary JSON numbers computed from those exact rationals.

### 2.7. Optimistic Concurrency Control

Two write operations — and only these two — carry an optimistic-concurrency guard. Amending or renewing a supply contract requires the request to include `expected_contract_version`, holding the contract `version` the client last observed. Responding to a turnaround proposal likewise requires `expected_turnaround_version`, matching the turnaround's current `version`. In both cases, whenever the supplied version differs from the resource's current version — the resource having typically advanced past the client's observed value since the client last read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's picture of the commercial terms — or of the turnaround window on the table — is stale and must be re-read before writing. No other endpoint accepts a version field.

### 2.8. Validation Order and Nested Path Resolution

Every request is checked against a fixed sequence of priority tiers, and a failure at an earlier tier masks every later check:

1. Authentication: `X-User-Role` and `X-User-ID` are present and valid (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted for the endpoint (`ERR_UNAUTHORIZED_ROLE`). The `CustomerOps` ownership comparison of §2.1 is not evaluated here; it is defined at tier 3 below, because it needs the resolved resource.
3. Existence: path identifiers resolve, validated left to right — customer, then evaluation, contract, plant, network, connection, tank, delivery, certificate, turnaround — each failure producing its resource-specific 404 (`ERR_CUSTOMER_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`, `ERR_CONNECTION_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, or `ERR_TURNAROUND_NOT_FOUND`). Resource identifiers carried in the request body resolve at this same tier, in the left-to-right order the operation's own narrative introduces them — customer before evaluation for a contract, network before contract for a connection — and a body identifier that is absent or not a string skips this tier and fails later at tier 9. Immediately after the target resource resolves, the `CustomerOps` ownership comparison runs: `X-User-ID` is compared against the customer reference stored on the resource, and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE` before any tier-4 guard runs — a nonexistent resource therefore draws its 404 ahead of any ownership check.
4. State guards: the stale-version checks of §2.7, the evaluation-accepted requirement, from-state legality for the requested transition (`ERR_INVALID_STATE_TRANSITION`), the contract-active requirement (`ERR_CONTRACT_NOT_ACTIVE`), the plant-operating requirement (`ERR_PLANT_NOT_OPERATING`), and the delivery-delivered requirement (`ERR_DELIVERY_NOT_DELIVERED`).
5. Business safety: segregation of duties, analytical result consistency, and delivery overfill.
6. Business temporal rules: window durations, turnaround overlap, blackout conflicts, turnaround due-ness, telemetry ordering, and settlement period-in-term.
7. Business constraints: pipeline capacity, the primary-connection requirement, purpose/mode matching, minimum-volume floors, one-plant and one-certificate uniqueness, and settlement uniqueness.
8. Fiscal gates: credit watch and makeup-credit sufficiency.
9. Structural validation (`ERR_VALIDATION`): malformed bodies, missing required fields, fields of the wrong JSON type, invalid enum values, syntactically invalid date, datetime, or period strings, a peak demand below average demand, a tank reorder point at or below its safety stock, an out-of-range level, or `apply_makeup_cents` supplied on a provisional statement. Structural validation also enforces numeric domains: quantities stated in whole units — integer cents, liters, Nm3 volumes and flows, month terms, and version counters — must be integers (an integral JSON float such as 100.0 is accepted); `term_months`, plant and network `nameplate_capacity_nm3h`, and tank `capacity_liters` must be at least 1; and money, volume, demand, escalation, impurity, `base_power_index`, and `power_kwh_per_nm3` fields reject negative values — while `required_purity_percent`, `measured_purity_percent`, `power_index_actual`, and `makeup_credit_cap_pct` accept any JSON number. Unrecognized body fields are ignored.

This ordering has visible consequences. A settlement request with a structurally invalid payload against a `DRAFT` contract is rejected with `ERR_CONTRACT_NOT_ACTIVE` — never `ERR_VALIDATION` — because tier 4 runs five tiers before tier 9. A telemetry reading whose level lies outside the tank's bounds surfaces as `ERR_READING_OUT_OF_ORDER` from tier 6 rather than the tier-9 catch-all. And nested paths resolve at tier 3 before any business rule runs: recording a certificate under a nonexistent delivery yields `ERR_DELIVERY_NOT_FOUND` before any certificate rule is consulted, whatever else is wrong with the payload.

### 2.9. Hierarchical Consistency and Cascading Side Effects

State changes ripple outward across aggregate boundaries, and the ripples are part of the specification rather than implementation detail. Terminating a contract decommissions its plant, cancels its pending turnarounds, releases its pipeline connections, and cancels its scheduled deliveries. Starting a turnaround takes its plant off-line, raises the contract's failover flag, and dispatches backup deliveries to the affected tanks. Certifying a delivery's analysis completes the delivery; failing it rejects the delivery and spawns a replacement. Creating or releasing a pipeline connection re-aggregates the network's reserved and available capacity. Each cascade mutates every resource it touches — refreshing its `updated_at` and incrementing its `version` — and the full enumeration of each cascade lives with its workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Supply-Mode Evaluation

A `PlatformAdmin` onboards each customer with a legal `name`, a market `segment` — one of `ELECTRONICS`, `MEDICAL`, `METALS`, or `CHEMICAL` — and two optional fields: `credit_standing`, one of `PRIME`, `STANDARD`, or `WATCH` and defaulting to `STANDARD` when omitted, and `blackout_windows`, a list of production blackout periods each carrying a `start_iso` and an `end_iso` timestamp and defaulting to an empty list. Each window's `start_iso` and `end_iso` are validated at registration only for ISO 8601 well-formedness — no ordering constraint between them is enforced. Blackout windows are closed intervals: both the start instant and the end instant belong to the blackout, which matters when turnaround windows are checked against them in §3.7. A customer whose standing is `WATCH` can be registered and evaluated normally, but the standing blocks contract activation later (§3.2).

With a customer on file, a `SupplyPlanner` commissions a supply-mode evaluation for a particular site by submitting the `customer_id`, a free-form `site_label`, the site's `demand_avg_nm3h` and `demand_peak_nm3h`, the `required_purity_percent` (99.999 is typical for electronics-grade nitrogen), the `required_product` (`N2`, `O2`, `H2`, `AR`, or `HE`), and a `pipeline_available` flag recording whether pipeline frontage exists at the site. A peak demand below the average demand is rejected with `ERR_VALIDATION`. The recommendation itself is computed once, at creation, and is immutable thereafter: a site averaging at least 4,000 Nm3/h is recommended `ONSITE_PLANT`; below that, a site with pipeline frontage averaging at least 1,500 Nm3/h is recommended `PIPELINE`; otherwise a site averaging at least 200 Nm3/h is recommended `BULK_LIQUID`; anything smaller falls to `CYLINDER`. The thresholds are inclusive — a demand exactly equal to a threshold takes the higher mode. The evaluation's `recommended_mode` and its `status`, initially `EVALUATED`, complete the record.

Only one evaluation per customer and site may be live at a time, and the system enforces this by supersession rather than by rejection. Creating a fresh evaluation for the same `customer_id` and `site_label` moves every sibling still in `EVALUATED` to `SUPERSEDED`. Acceptance is performed by `CustomerOps`, and only when the caller's `X-User-ID` equals the evaluation's `customer_id` — otherwise the call is rejected with `ERR_UNAUTHORIZED_ROLE`; acceptance is legal only from `EVALUATED`, any other current state drawing `ERR_INVALID_STATE_TRANSITION`. Acceptance moves the evaluation to `ACCEPTED` and supersedes every sibling in either `EVALUATED` or `ACCEPTED`. Should an `ACCEPTED` evaluation later be superseded by a sibling's acceptance, a contract already created from it keeps its `evaluation_id` but cannot activate while the evaluation is no longer `ACCEPTED`.

### 3.2. Take-or-Pay Contracts: Formation, Activation, Renewal, Termination

Contract drafting starts from an accepted evaluation. A `SupplyPlanner` creates the take-or-pay contract with a `customer_id` — which must equal the evaluation's own customer, a mismatch being rejected with `ERR_VALIDATION` — the `evaluation_id`, the `term_months` (120 months is typical for a dedicated asset), the `start_date` as an ISO `YYYY-MM-DD` calendar date, and the commercial terms: `min_monthly_volume_nm3` (the take-or-pay monthly minimum), `unit_price_cents_per_nm3`, `monthly_facility_fee_cents`, `facility_fee_escalation_pct_annual` (for example 0.03), `base_power_index` in currency per kWh (for example 0.08), `power_kwh_per_nm3` as the specific power consumption used for pass-through (for example 0.42), and optionally `makeup_credit_cap_pct`, which defaults to 0.10 — ten percent. The server copies `mode`, `product`, and `site_label` from the evaluation, computes `end_date` as `start_date` plus `term_months` calendar months — clamping the day to the target month's last day when the start day does not exist in it, so 31 January plus one month yields the last day of February — initializes `makeup_credit_balance_cents` to 0 and `failover_active` to false, and parks the contract in `DRAFT`. The referenced evaluation must be `ACCEPTED` — at creation and again at activation — or the call fails with `ERR_EVALUATION_NOT_ACCEPTED`.

Activation moves `DRAFT` to `ACTIVE` behind four gates, which fire in the tier order of §2.8: the state-level evaluation gate first, the constraint-level connection and volume gates next, and the fiscal credit gate last. The evaluation must still be `ACCEPTED` (`ERR_EVALUATION_NOT_ACCEPTED`). A `PIPELINE`-mode contract must already hold an `ACTIVE` pipeline connection with purpose `PRIMARY` (`ERR_PIPELINE_CONNECTION_REQUIRED`). The monthly minimum must meet its mode floor — 2,000,000 Nm3 for `ONSITE_PLANT`, 800,000 Nm3 for `PIPELINE`, 150,000 Nm3 for `BULK_LIQUID`, and no floor at all for `CYLINDER` — or activation is refused with `ERR_MIN_VOLUME_BELOW_FLOOR`. Finally, the customer's `credit_standing` must not be `WATCH` (`ERR_CUSTOMER_CREDIT_WATCH`). Activation increments the contract's `version`.

Once `ACTIVE`, commercial terms evolve through amendments: a call with `kind` set to `AMENDMENT` carries `expected_contract_version` (guarded per §2.7) plus any of `new_monthly_facility_fee_cents`, `new_min_monthly_volume_nm3`, or `new_unit_price_cents_per_nm3`, applies the supplied terms going forward, and increments `version` while the contract remains `ACTIVE`.

Ninety days before `end_date`, the clock sweep of §2.4 opens the renewal window by moving the contract from `ACTIVE` to `RENEWAL_OPEN` — the cyclic renegotiation state for an asset dedicated to a single customer. A renewal is an amendment call with `kind` set to `RENEWAL`: it carries the same `expected_contract_version` guard, requires `new_end_date` to be present and strictly later than the current `end_date` (otherwise `ERR_VALIDATION`), moves the contract back to `ACTIVE` with the new `end_date` and any new fee, minimum, or price terms applied, and increments `version`. When no renewal lands before the clock passes `end_date`, the sweep instead moves the contract from `RENEWAL_OPEN` to `EXPIRED`.

Termination is available from `DRAFT`, `ACTIVE`, or `RENEWAL_OPEN` and lands the contract in `TERMINATED`. A `DRAFT` contract terminates quietly — nothing has been built against it yet. Terminating from `ACTIVE` or `RENEWAL_OPEN` fires the full cascade in a single action: any non-`DECOMMISSIONED` plant of the contract is decommissioned and its `effective_capacity_nm3h` zeroed; every turnaround of that plant in `PROPOSED`, `AGREED`, or `SCHEDULED` moves to `CANCELLED` — one already `IN_PROGRESS` is deliberately not cancelled and runs to completion; every `ACTIVE` pipeline connection of the contract moves to `RELEASED`, which re-aggregates the network's reserved and available capacity per §3.4; every delivery still `SCHEDULED` for a tank of this customer whose product matches the contract's `product` moves to `CANCELLED`; and the contract's `version` increments.

### 3.3. Dedicated On-Site Plants: Construction Through Decommissioning

A dedicated plant is how an `ONSITE_PLANT` contract becomes physical. A `PlantOperator` creates it with the `contract_id`, a plant `name`, the `nameplate_capacity_nm3h`, the total `capital_cost_cents` that will anchor capital recovery at settlement, and the measured `power_kwh_per_nm3`. Creation is gated: the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), its mode must be `ONSITE_PLANT` (`ERR_MODE_MISMATCH`), and at most one live plant may exist per contract — attempting a second while a non-`DECOMMISSIONED` one exists is refused with `ERR_PLANT_ALREADY_EXISTS`. The new plant's `customer_id` is denormalized from its contract, and it starts life in `PROPOSED` status with `effective_capacity_nm3h` at 0.

Construction proceeds one stage per advance action: `PROPOSED` to `UNDER_CONSTRUCTION`, then `COMMISSIONING`, then `OPERATING` — the moment effective capacity rises to the nameplate value. From `OPERATING` there are exactly two ways out. A maintenance turnaround (§3.7) parks the plant in `TURNAROUND` with effective capacity 0 until the work completes and nameplate capacity is restored. Decommissioning, driven only by the contract-termination cascade, moves the plant from whatever state it occupies into `DECOMMISSIONED`, again zeroing effective capacity — permanently.

### 3.4. Pipeline Networks and Firm Capacity Reservation

Pipeline supply begins with network registration: a `PlatformAdmin` creates a network with a `name` and a total firm `nameplate_capacity_nm3h`; `reserved_capacity_nm3h` starts at 0 and `available_capacity_nm3h` equals the nameplate.

A `PipelineDispatcher` reserves firm capacity for a contract by creating a connection with `network_id`, `contract_id`, `reserved_flow_nm3h`, and a `purpose`. The referenced contract must be in `DRAFT` or `ACTIVE` — a contract in any other state is rejected with `ERR_INVALID_STATE_TRANSITION` — and the reserved flow must be at least 1 Nm3/h — a non-positive flow is rejected with `ERR_VALIDATION`. Purpose and contract mode must agree: `PRIMARY` serves a contract whose mode is `PIPELINE`, while `BACKUP` serves an `ONSITE_PLANT` contract; either mismatch is rejected with `ERR_MODE_MISMATCH`. Admission is a capacity check: the requested flow must fit within the network's currently available capacity, where an exact fit — reservations totaling precisely the nameplate — is allowed, while a single Nm3/h over is rejected with `ERR_PIPELINE_CAPACITY_EXCEEDED`. A connection is born with `status` `ACTIVE` and immediately adds its flow to the network's reserved total.

The aggregation invariant is maintained continuously: `reserved_capacity_nm3h` is the sum of `reserved_flow_nm3h` over the network's `ACTIVE` connections, `available_capacity_nm3h` is the nameplate minus the reserved total, and the two always sum back to the nameplate. Releasing a connection — by a `PipelineDispatcher`, or through the contract-termination cascade — is legal only from `ACTIVE`, any other state drawing `ERR_INVALID_STATE_TRANSITION`, and moves it to `RELEASED`, subtracting its flow from the reservation as a compensating action that restores availability.

### 3.5. Tank Telemetry, Burn Analytics, and Replenishment Triggering

Bulk-liquid service centers on the storage tank. A `PlantOperator` registers one with `customer_id`, `site_label`, `product` (`N2`, `O2`, `H2`, `AR`, or `HE`), `capacity_liters`, `reorder_point_liters`, `safety_stock_liters`, and the quality envelope for certified deliveries into this tank: `required_purity_percent` and `max_impurity_ppm`. The safety stock must sit strictly below the reorder point — a reorder point at or below the safety stock is rejected with `ERR_VALIDATION`. A new tank's `status` reads `NORMAL`, and its `current_level_liters` stays null until the first reading arrives.

Readings flow in through the `TelemetryGateway`, each carrying `measured_at` and `level_liters`, and each is recorded as an immutable `TelemetryReading` whose `tank_id` comes from the path. Two rules keep the series clean, and both are enforced before any analytics run: `measured_at` must be strictly later than the tank's latest existing reading, and the level must lie within 0 and the tank's capacity inclusive — either violation is rejected with `ERR_READING_OUT_OF_ORDER`. An accepted reading refreshes `current_level_liters`, `last_reading_at`, both burn-rate variants, both runout projections, and the tank's posture. The append call answers `201 Created` and returns the updated tank — not the new reading — in its `data` field.

Burn analytics work over the tank's readings ordered by `measured_at`, earliest first. Each adjacent pair of readings yields an interval burn: the liters the level dropped between the two readings divided by the hours between their timestamps, with a non-positive drop — the level rose or merely held — contributing zero for that interval. Two variants are maintained in parallel. The instantaneous variant, exposed as `burn_rate_instant_lph`, is simply the latest interval's burn, and it reacts immediately to a consumption change. The weighted-moving-average variant, exposed as `burn_rate_wma_lph`, smooths over up to the four most recent intervals, latest first, with weights of one half, one quarter, and one eighth for each of the third and fourth. When fewer than four intervals exist, only the leading weights are used — a single interval contributes its burn multiplied by one half; two intervals use one half and one quarter; three use one half, one quarter, and one eighth — and the unused weights are discarded rather than redistributed.

Each variant projects a safety-stock runout: `projected_runout_instant_at` and `projected_runout_wma_at` are the timestamp of the latest reading plus the hours needed to consume the liters standing between the current level and the safety stock at that variant's burn rate, rounded half up to whole seconds. Both are null while the tank has fewer than two readings, and both are null whenever the applicable burn rate is zero or negative. The two burn-rate fields are likewise null until the tank has at least two readings. Because the variants weight history differently, the same readings generally yield two different runouts; the weighted-moving-average runout is the one that drives delivery urgency in §3.6.

Posture is recomputed on every accepted reading. A level at or below `safety_stock_liters` puts the tank into `CRITICAL`; a level above the safety stock but at or below `reorder_point_liters` puts it into `REORDER_DUE`; anything above the reorder point is `NORMAL`. The tank's `status` follows the levels through all six transitions among the three states as inventory falls and recovers.

Replenishment is edge-triggered, never level-triggered: a delivery is considered only when a reading moves the tank into `REORDER_DUE` or `CRITICAL`, and a reading that merely deepens an existing low posture triggers nothing. Any change of posture that lands in `REORDER_DUE` or `CRITICAL` counts as such an entry edge — including a partial recovery from `CRITICAL` up to `REORDER_DUE`. On such an entry edge, if the tank has no open delivery — open meaning `transport_status` `SCHEDULED`, or `DELIVERED` with `quality_status` still `QC_PENDING` — the system creates one automatically: `triggered_by` set to `TELEMETRY`, `quantity_liters` equal to the tank's headroom (capacity minus current level — a null level counting as 0 — an integer number of liters), `route_date` set to the current logical date, and `required_purity_percent` with `max_impurity_ppm` snapshotted from the tank. When an open delivery already exists, the trigger is skipped — a tank never accumulates duplicate open deliveries.

### 3.6. Delivery Routing, Confirmation, and Analytical Certification

Every delivery, however triggered, records its `tank_id`, a `customer_id` denormalized from the tank, the `product` copied from the tank, the headroom-based `quantity_liters` fixed at trigger time, a `triggered_by` of `TELEMETRY`, `BACKUP`, or `REDELIVERY`, the logical `route_date` of its creation, and a `route_code` formed by prefixing that date with `RT-` — deliveries sharing a `route_date` form a single route. Its lifecycle runs on two parallel axes: `transport_status` (`SCHEDULED`, `DELIVERED`, `COMPLETED`, `REJECTED`, or `CANCELLED`) and `quality_status` (`QC_PENDING`, `CERTIFIED`, or `FAILED`), starting as `SCHEDULED` with `QC_PENDING`.

Stop sequencing keeps each route ordered by urgency. Whenever a delivery is created for a route date, `stop_sequence` is recomputed across every `SCHEDULED` delivery of that date: deliveries are ordered by their tank's weighted-moving-average runout, earliest runout first, with deliveries whose tank has no computable runout placed after all tanks that have one; ties break by the tank's creation time, then by the delivery's own creation time, and any tie still remaining by monotonic creation sequence. Ranks are then assigned as a dense sequence starting at 1. A delivery whose rank the recomputation leaves unchanged is not mutated — its `version` and `updated_at` stay put.

Physical confirmation is the `PipelineDispatcher`'s act, and it is legal only from `SCHEDULED` — any other transport state is refused with `ERR_INVALID_STATE_TRANSITION`. Confirming a delivery records the `delivered_quantity_liters`, stamps `confirmed_at` with the logical time, and moves transport to `DELIVERED` while quality remains `QC_PENDING`. The delivered quantity must be at least 1 liter and no more than the tank's headroom at that moment — capacity minus current level, a null level counting as 0 — or the confirmation is rejected with `ERR_DELIVERY_OVERFILL`.

Quality assurance then takes over under a strict two-person rule. A `QualityAnalyst` records the laboratory result for a `DELIVERED` delivery — attempting it any earlier fails with `ERR_DELIVERY_NOT_DELIVERED` — by submitting `sampled_at`, `measured_purity_percent`, and `measured_impurity_ppm`. At most one certificate may ever exist per delivery (`ERR_CERTIFICATE_EXISTS`). The new certificate's `analyst_user_id` is the caller's `X-User-ID`, its `delivery_id` ties it to the delivery, and its `result` starts as `RECORDED`.

Certification belongs to a different pair of hands: a `QualityCertifier` decides with a `decision` of `CERTIFIED` or `FAILED`. A certificate can be decided only once: the certify call is legal only while the certificate's `result` is `RECORDED`, and any later attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. The certifier's `X-User-ID` must differ from the certificate's `analyst_user_id` — self-certification is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `CERTIFIED` decision additionally requires the measurements to satisfy the delivery's snapshotted specification: measured purity at least the delivery's `required_purity_percent` and measured impurities at most its `max_impurity_ppm`, otherwise the decision is rejected with `ERR_RESULT_INCONSISTENT`. A `FAILED` decision carries no such gate, since failing an out-of-spec delivery is always legitimate. Either way the decision stamps `certifier_user_id` and `decided_at`, and then it cascades. A `CERTIFIED` outcome moves the certificate to `CERTIFIED` and the delivery to `COMPLETED` with `CERTIFIED` quality. A `FAILED` outcome moves the certificate to `FAILED`, the delivery to `REJECTED` with `FAILED` quality, and immediately auto-creates a replacement delivery for the same tank — `triggered_by` `REDELIVERY`, quantity equal to the tank's current headroom — with stop sequences recomputed for the affected route date.

Deliveries can also be cancelled without ever shipping: the contract-termination cascade of §3.2 moves `SCHEDULED` deliveries of the matching customer and product to `CANCELLED`, where they rest terminally with quality still `QC_PENDING`.

### 3.7. Maintenance Turnarounds and Failover Coordination

Turnarounds are how a dedicated plant is maintained without breaching the customer's production calendar. A `PlantOperator` proposes a window on an `OPERATING` plant — any other plant state is refused with `ERR_PLANT_NOT_OPERATING` — supplying `window_start`, `window_end`, and a free-text `scope`; the turnaround's `plant_id` comes from the path. The window must end after it starts, and its duration must run at least 24 hours and no more than 720 hours (thirty days), or creation fails with `ERR_WINDOW_DURATION_INVALID`. The proposal is born `PROPOSED` with `proposal_round` at 1.

The customer answers through `CustomerOps`, whose `X-User-ID` must equal the customer owning the plant's contract (`ERR_UNAUTHORIZED_ROLE` otherwise), and whose call carries `expected_turnaround_version` per §2.7 — a mismatch there is `ERR_STALE_VERSION`. A `decision` of `AGREE` moves the turnaround to `AGREED` and increments its `version`. A `decision` of `COUNTER` keeps it `PROPOSED` but replaces the window with `counter_window_start` and `counter_window_end` — both required, the end after the start, the duration again within 24 to 720 hours, else `ERR_WINDOW_DURATION_INVALID` — increments `proposal_round` by 1, and increments `version`. Negotiation can iterate through several counters, each bumping the round by one.

Scheduling is the `PlantOperator`'s next act, moving an `AGREED` turnaround to `SCHEDULED` behind three gates. First, the plant's contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). Second, the window must not overlap any other `SCHEDULED` or `IN_PROGRESS` turnaround of the same plant under half-open semantics: two windows conflict when the existing window starts before the new window ends and the new window starts before the existing window ends, while mere adjacency — one window ending exactly as the other begins — is allowed (`ERR_TURNAROUND_OVERLAP`). Third, the window must not share any instant with any of the customer's blackout windows, which are closed intervals: a conflict exists when the turnaround window starts at or before a blackout's end and ends after that blackout's start (`ERR_TURNAROUND_IN_BLACKOUT`).

Starting the work is due-gated: the logical clock must have reached `window_start`, or the start is rejected with `ERR_TURNAROUND_NOT_DUE`. A successful start moves the turnaround to `IN_PROGRESS` and fires the failover cascade: the plant moves from `OPERATING` to `TURNAROUND` with `effective_capacity_nm3h` zeroed, the contract's `failover_active` becomes true, and for every tank of the customer whose `product` matches the contract's product the system auto-creates a backup delivery — `triggered_by` `BACKUP`, quantity equal to the tank's current headroom — unless that tank already has an open delivery; stop sequences are then recomputed for the affected route date.

Completion is clock-driven. When the logical clock reaches `window_end`, the turnaround moves to `COMPLETED`; the plant returns to `OPERATING` with effective capacity restored to the nameplate only if it is still in `TURNAROUND` — a plant decommissioned mid-window by contract termination stays `DECOMMISSIONED` — and the contract's `failover_active` clears to false either way. Contract termination cancels turnarounds in `PROPOSED`, `AGREED`, or `SCHEDULED` — an `IN_PROGRESS` turnaround is never cancelled and always runs out its window.

### 3.8. Monthly Settlement and the Makeup-Credit Bank

Settlement is where take-or-pay becomes money. A `BillingSpecialist` runs a statement for a contract in `ACTIVE` or `RENEWAL_OPEN` — any other contract state is rejected with `ERR_CONTRACT_NOT_ACTIVE` — by supplying a `period_month` as a `YYYY-MM` string that must fall within the contract's term, from its start month through its end month inclusive (`ERR_PERIOD_OUT_OF_TERM` otherwise), a `variant` of `PROVISIONAL` or `FINAL`, and the inputs that variant demands; the statement's `contract_id` comes from the path. A `FINAL` statement requires `metered_volume_nm3` and `power_index_actual` and optionally accepts `apply_makeup_cents`; a `PROVISIONAL` statement requires `projected_volume_nm3`. Cross-variant input is forbidden: metered volume or a power index on a provisional, projected volume on a final, or `apply_makeup_cents` on a provisional are all rejected with `ERR_VALIDATION`, as is a missing required field — and per §2.8 these structural checks run at the lowest tier, behind the contract-state, period, duplicate, and makeup gates.

Uniqueness runs per contract and period. Creating a `PROVISIONAL` statement fails with `ERR_DUPLICATE_SETTLEMENT` whenever any non-`SUPERSEDED` statement already exists for that period. Creating a `FINAL` fails with `ERR_DUPLICATE_SETTLEMENT` only when a `FINAL` already exists for the period; otherwise the new `FINAL` supersedes the period's provisional, moving it from `PROVISIONAL` to `SUPERSEDED`.

The invoice itself computes in a pinned fourteen-step order, each step consuming only the results of earlier steps:

1. `months_elapsed` counts whole months from the contract's start month to the period month — twelve times the difference in calendar years plus the difference in month numbers.
2. `escalation_multiplier` compounds the annual facility-fee escalation: take the whole elapsed years (the floor of `months_elapsed` divided by 12), start the multiplier at 1.0000, and for each elapsed year multiply it by one plus `facility_fee_escalation_pct_annual`, rounding the multiplier half up to four decimal places after every annual multiplication. Rounding once at the end instead of once per year yields a different fee and is non-conformant.
3. The effective volume is `metered_volume_nm3` for a `FINAL` and `projected_volume_nm3` for a `PROVISIONAL`.
4. `billable_volume_nm3` is the larger of the effective volume and `min_monthly_volume_nm3` — the take-or-pay floor bills even when offtake falls short.
5. `volume_charge_cents` is the billable volume times `unit_price_cents_per_nm3`.
6. `power_passthrough_cents` for a `FINAL` is the effective volume times `power_kwh_per_nm3` times the difference between `power_index_actual` and `base_power_index`, rounded half up to integer cents — negative when power came in below the contracted base. For a `PROVISIONAL` it is 0.
7. `facility_fee_cents` is `monthly_facility_fee_cents` times the escalation multiplier, rounded half up to integer cents.
8. `capital_recovery_cents` applies only when the contract's mode is `ONSITE_PLANT` and a non-`DECOMMISSIONED` plant exists for it: the plant's `capital_cost_cents` divided by `term_months`, rounded down. Otherwise it is 0.
9. `subtotal_cents` is the sum of the volume charge, the power pass-through, the facility fee, and the capital recovery.
10. `shortfall_volume_nm3` is the amount by which the effective volume fell below the monthly minimum — zero when the minimum was met or exceeded.
11. `makeup_credit_applied_cents` for a `FINAL` is the smallest of `apply_makeup_cents` (treated as 0 when omitted), the bank balance before this period's grant, and the subtotal. Requesting an application larger than that minimum is rejected with `ERR_MAKEUP_CREDIT_EXCEEDED` rather than silently clamped. For a `PROVISIONAL` it is 0.
12. `makeup_credit_granted_cents` is the shortfall volume times the unit price times sixty percent, rounded half up, then capped at the remaining grant room. The credit cap is `makeup_credit_cap_pct` times twelve times `min_monthly_volume_nm3` times `unit_price_cents_per_nm3`, rounded half up to integer cents; grant room is the cap minus the pre-grant balance, floored at zero; and any overflow above the cap is discarded, never banked. A `FINAL` records the grant into the ledger; a `PROVISIONAL` reports the same figure as an estimate and mutates nothing.
13. `total_due_cents` is the subtotal minus the applied credit.
14. For a `FINAL` only, the contract's `makeup_credit_balance_cents` becomes the pre-grant balance plus the grant minus the application, and the contract's `version` increments by 1.

Two ledger disciplines deserve emphasis. The balance consulted when applying credit in step 11 is deliberately the pre-grant balance: a period's own shortfall grant can never pay its own bill. And across the contract's life, the sum of all grants on `FINAL` statements always equals the sum of all applications plus the contract's current bank balance — nothing is created in the bank and nothing is lost. The statement's own `status` mirrors its variant, `PROVISIONAL` or `FINAL`, until a later final supersedes the provisional into `SUPERSEDED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource answer `201 Created`. Operations that act on an existing resource — state transitions, confirmations, responses, sweeps — and all read endpoints answer `200 OK`. The table below is a locator only; the full request and response semantics of each operation live in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the renewal-open, expiry, and turnaround-completion sweep | PlatformAdmin |
| POST | `/gas-supply/customers` | Create a Customer | PlatformAdmin |
| GET | `/gas-supply/customers/{customerId}` | Get a Customer | All roles |
| POST | `/gas-supply/supply-mode-evaluations` | Create and immediately evaluate a supply-mode study | SupplyPlanner |
| GET | `/gas-supply/customers/{id}/supply-mode-evaluations` | List a customer's evaluations | All roles |
| POST | `/gas-supply/supply-mode-evaluations/{evaluationId}/accept` | Customer accepts the recommendation | CustomerOps |
| POST | `/gas-supply/supply-contracts` | Create a take-or-pay contract from an ACCEPTED evaluation | SupplyPlanner |
| GET | `/gas-supply/supply-contracts/{contractId}` | Get a SupplyContract | All roles |
| GET | `/gas-supply/supply-contracts` | List contracts with optional filters and pagination | All roles |
| POST | `/gas-supply/supply-contracts/{contractId}/activate` | Activate a DRAFT contract | SupplyPlanner |
| POST | `/gas-supply/supply-contracts/{contractId}/amendments` | Amend terms (AMENDMENT) or renew (RENEWAL); OCC-guarded | SupplyPlanner |
| POST | `/gas-supply/supply-contracts/{contractId}/terminate` | Terminate a contract with the full cascade | SupplyPlanner |
| POST | `/gas-supply/onsite-plants` | Create a dedicated on-site plant for an ACTIVE ONSITE_PLANT contract | PlantOperator |
| GET | `/gas-supply/onsite-plants/{plantId}` | Get an OnsitePlant | All roles |
| GET | `/gas-supply/onsite-plants` | List plants with optional filters | All roles |
| POST | `/gas-supply/onsite-plants/{plantId}/advance` | Advance construction one stage toward OPERATING | PlantOperator |
| POST | `/gas-supply/pipeline-networks` | Create a pipeline network | PlatformAdmin |
| GET | `/gas-supply/pipeline-networks/{networkId}` | Get a PipelineNetwork with computed reservation fields | All roles |
| POST | `/gas-supply/pipeline-connections` | Reserve firm pipeline capacity for a contract | PipelineDispatcher |
| GET | `/gas-supply/pipeline-connections/{connectionId}` | Get a PipelineConnection | All roles |
| GET | `/gas-supply/pipeline-connections` | List connections with optional filters | All roles |
| POST | `/gas-supply/pipeline-connections/{connectionId}/release` | Release a connection and compensate network capacity | PipelineDispatcher |
| POST | `/gas-supply/storage-tanks` | Create a bulk liquid storage tank at a customer site | PlantOperator |
| GET | `/gas-supply/storage-tanks/{tankId}` | Get a StorageTank with computed burn, runout, and posture fields | All roles |
| GET | `/gas-supply/storage-tanks` | List tanks with optional filters | All roles |
| POST | `/gas-supply/storage-tanks/{id}/telemetry` | Append a telemetry reading; may auto-create a TELEMETRY delivery | TelemetryGateway |
| GET | `/gas-supply/storage-tanks/{id}/telemetry` | List a tank's telemetry readings in chronological order | All roles |
| GET | `/gas-supply/deliveries/{deliveryId}` | Get a Delivery | All roles |
| GET | `/gas-supply/deliveries` | List deliveries with optional filters and pagination | All roles |
| POST | `/gas-supply/deliveries/{deliveryId}/confirm-delivery` | Confirm physical delivery with the delivered quantity | PipelineDispatcher |
| POST | `/gas-supply/deliveries/{id}/quality-certificates` | Record an analytical result for a DELIVERED delivery | QualityAnalyst |
| GET | `/gas-supply/deliveries/{id}/quality-certificates` | List certificates for a delivery (zero or one) | All roles |
| POST | `/gas-supply/quality-certificates/{certificateId}/certify` | Certify or fail a recorded analysis; segregated from recording | QualityCertifier |
| POST | `/gas-supply/onsite-plants/{id}/turnarounds` | Propose a maintenance turnaround window for an OPERATING plant | PlantOperator |
| GET | `/gas-supply/onsite-plants/{id}/turnarounds` | List a plant's turnarounds | All roles |
| POST | `/gas-supply/turnarounds/{turnaroundId}/respond` | Customer AGREEs or COUNTERs the proposed window; OCC-guarded | CustomerOps |
| POST | `/gas-supply/turnarounds/{turnaroundId}/schedule` | Schedule an AGREED turnaround after overlap, blackout, and contract gates | PlantOperator |
| POST | `/gas-supply/turnarounds/{turnaroundId}/start` | Start a SCHEDULED turnaround at or after window start; fires the failover cascade | PlantOperator |
| POST | `/gas-supply/supply-contracts/{id}/settlements` | Run a PROVISIONAL or FINAL take-or-pay settlement for a period | BillingSpecialist |
| GET | `/gas-supply/supply-contracts/{id}/settlements` | List a contract's settlement statements | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_EVALUATION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_NOT_FOUND` | 404 Not Found |
| `ERR_NETWORK_NOT_FOUND` | 404 Not Found |
| `ERR_CONNECTION_NOT_FOUND` | 404 Not Found |
| `ERR_TANK_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_TURNAROUND_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_EVALUATION_NOT_ACCEPTED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLANT_NOT_OPERATING` | 409 Conflict |
| `ERR_DELIVERY_NOT_DELIVERED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_RESULT_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_DELIVERY_OVERFILL` | 422 Unprocessable Entity |
| `ERR_WINDOW_DURATION_INVALID` | 422 Unprocessable Entity |
| `ERR_TURNAROUND_OVERLAP` | 409 Conflict |
| `ERR_TURNAROUND_IN_BLACKOUT` | 422 Unprocessable Entity |
| `ERR_TURNAROUND_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_READING_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_PERIOD_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_PIPELINE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PIPELINE_CONNECTION_REQUIRED` | 409 Conflict |
| `ERR_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MIN_VOLUME_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SETTLEMENT` | 409 Conflict |
| `ERR_CERTIFICATE_EXISTS` | 409 Conflict |
| `ERR_PLANT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CUSTOMER_CREDIT_WATCH` | 422 Unprocessable Entity |
| `ERR_MAKEUP_CREDIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
