# Waste Energy Plant Operations API — Product Requirements Document

## 1. Introduction

Municipal solid waste does not arrive on a convenient schedule, and neither does the revenue that pays for burning it. A waste-to-energy plant sits at the intersection of three commercial worlds: municipalities that contractually guarantee tonnage under put-or-pay supply agreements, energy offtakers buying power under fixed-rate or merchant terms, and a tightly regulated environmental envelope covering boiler capacity, ash disposal, and stack emissions. This document specifies the API that runs that plant.

The system governs the full operating cycle: registering municipal counterparties and their host-community privileges, executing waste supply agreements with guaranteed annual tonnage and per-tonne tipping fees, scheduling and accepting waste deliveries at the tip floor under a daily capacity allocation, managing boiler availability through deratings and maintenance outages with approved diversion plans, producing daily throughput reports that reconcile thermal input against effective boiler capacity, billing energy deliveries under power purchase agreements, settling metals recovery from ash, disposing of ash residue in permitted landfills after passing regulatory tests, and monitoring emissions readings against permit limits.

Two structural concerns shape every workflow below. First, the plant operates on a **logical clock** rather than wall-clock time: agreement expirations, host-community priority windows, and emissions rolling windows are all evaluated against a server-maintained logical time that starts at exactly `2026-09-01T00:00:00Z` on server startup and advances only when an authorized caller sets it. Second, several write operations are guarded by optimistic concurrency control — a client that read a resource, then acts on it, must present the version it last observed, and a mismatch is rejected outright rather than silently overwriting an intervening change.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/wte` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming one of the five declared roles. The recognized roles are `PlantOperator`, `ContractsManager`, `EnergyTrader`, `EnvironmentalOfficer`, and `Regulator`. A request whose `X-User-Role` header is missing or does not name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All five roles use an **opaque** identity model. When `X-User-Role` is `PlantOperator`, `ContractsManager`, `EnergyTrader`, `EnvironmentalOfficer`, or `Regulator`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes, but it never compares `X-User-ID` against any resource's `id` or foreign-key field; authorization is decided purely by role.

Role responsibilities in brief: a `PlantOperator` runs the tip floor, boilers, outages, diversion plans, throughput reporting, and metals batch recording. A `ContractsManager` manages municipalities, host community agreements, waste supply agreements and their amendments, metals recovery contracts and batch settlement, diversion plan approval, and put-or-pay settlement runs. An `EnergyTrader` manages power purchase agreements and energy delivery billing. An `EnvironmentalOfficer` manages landfills, ash shipments and their tests, emissions permits, and emissions readings. A `Regulator` has read access across the business surface, may suspend emissions permits, and is the only role permitted to drive the logical clock.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and at most 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in this document: agreement and PPA expiry, host-community priority windows, diversion outage lengths, and emissions rolling windows are all evaluated against it, never against wall-clock time. At server startup, before any clock call has been made, the logical time is exactly `2026-09-01T00:00:00Z`; the logical clock never falls back to wall-clock time thereafter. A `Regulator` may advance the clock to a supplied instant by providing `to_iso8601` to the clock-setting capability, which responds with the resulting `current_utc`. Advancing the clock fires any system transitions whose preconditions depend on the time — in particular, an `ACTIVE` waste supply agreement whose `term_end` has been reached transitions to `EXPIRED`, and an `ACTIVE` power purchase agreement whose `term_end` has been reached transitions to `EXPIRED`.

### 2.5. Common Resource Properties

Every primary resource in the system — municipalities, host community agreements, waste supply agreements, waste deliveries, boilers, outage windows, diversion plans, diversion legs, daily throughput reports, power purchase agreements, energy deliveries, metals recovery contracts, metals recovery batches, landfills, ash shipments, ash tests, emissions permits, and emissions readings — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on related resources.

Any change to a resource — whether a direct client write or a cascade such as a delivery acceptance bumping its parent agreement's cumulative tonnage — refreshes `updated_at` and increments `version` on each resource actually mutated.

### 2.6. Validation Ordering

When a request fails for more than one reason, the error returned is decided by a fixed evaluation order, not by whichever check happens to run first. The checks run in this sequence:

1. Authentication — the `X-User-Role` header must be present and name a declared role, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role must be permitted for the endpoint, else `ERR_UNAUTHORIZED`.
3. Path existence — every identifier in the URL path must reference an existing resource, validated left to right, else `ERR_NOT_FOUND`.
4. Body reference existence — every foreign key in the request body must reference an existing resource, else `ERR_NOT_FOUND`.
5. Target state — the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE`; this category also covers referenced parents that must be in a permitting state (for example, an agreement that must be `ACTIVE` before a delivery under it can be accepted).
6. Business rules — capacity checks, safety checks, temporal overlap checks, fiscal checks, uniqueness checks, and optimistic concurrency checks, each carrying its own error identifier as described in §3.
7. Field shape and range — numeric positivity and range constraints, interval ordering, and enum membership, else `ERR_INVALID_REQUEST`.
8. Required-field presence — missing required body fields, reported as `ERR_INVALID_REQUEST`.

The ordering means, for example, that a state error wins over a body-shape error: a request that is both addressed to a resource in the wrong state and missing a required field is rejected with the state error.

### 2.7. Nested Resource Retrieval

When an endpoint path contains a resource identifier, the server validates that the identifier references an existing resource before evaluating any other rule. Requests are rejected with `404` and `ERR_NOT_FOUND` at the first identifier in the path — checked left to right — that does not correspond to an existing resource. Foreign keys supplied in a request body (for example, the `agreement_id` on a new waste delivery) are likewise validated for existence before business rules run, and a dangling reference is rejected with `ERR_NOT_FOUND`.

### 2.8. Precision and Rounding

All monetary amounts in the system are integer cents. Fees, billed amounts, revenues, and settlement figures are computed by multiplying quantities by rates and then rounding the final product to whole cents using round-half-up; quantities are never rounded before the multiplication. Tonnes and megawatt quantities are carried to three decimal places, rounded half-up, wherever a computed quantity is persisted. Rolling averages used in emissions evaluation are carried to six decimal places, rounded half-up. The period fraction used in capacity payment proration is likewise computed to six decimal places.

### 2.9. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control. Each requires a dedicated request field carrying the client's last-observed `version` of a parent entity; if the value presented does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guarded operations are:

- Creating a waste supply agreement that amends an existing one (the payload's `amendment_of_agreement_id` is set) requires `expected_base_agreement_version` matching the base agreement's current `version`. A stale value means another writer has changed the base's terms — through activation, a prior amendment, or a delivery-driven version bump — since the client read it, and the amendment is refused.
- Accepting a received waste delivery requires `expected_agreement_version` matching the delivery's waste supply agreement's current `version`. A stale value means the agreement's rate or cumulative tonnage changed since the client read it, so the fee computed from the client's view would be wrong and the accept is refused.
- Starting an outage window requires `expected_boiler_version` matching the outage's boiler's current `version`. A stale value means the boiler's capacity or status was changed since the client read it, and starting the outage against that stale view is refused.
- Completing an ash shipment requires `expected_landfill_version` matching the receiving landfill's current `version`. A stale value means remaining capacity or status changed since the client read it, invalidating the disposal-capacity check, and the completion is refused.

Endpoints not named above take no version field; mutations on them are processed without an OCC check.

## 3. Business Logic & Workflows

### 3.1. Municipal Counterparties and Host Community Privilege

A `ContractsManager` begins the commercial setup by registering each municipal counterparty, supplying the municipality's `legal_name`, the `population_served` covered by its collection system, and optionally the `is_host_community` flag and `priority_group`. The `is_host_community` flag defaults to `false`, and `priority_group` defaults to `STANDARD`; the only other recognized value is `HOST`, and claiming `HOST` priority requires `is_host_community` to be `true`. The municipality list may be filtered by `is_host_community`.

The municipality that hosts the plant receives special treatment through a **Host Community Agreement**. A `ContractsManager` creates one by naming the host `municipality_id`, the fixed `annual_payment_cents`, the `payment_due_month` (a calendar month from 1 to 12 on which the annual payment falls due), the effective window from `effective_start` to `effective_end`, and optionally `local_waste_priority_enabled`, which defaults to `true`. The named municipality must actually be flagged `is_host_community`; a host agreement pointing at an ordinary municipality is rejected with `ERR_NOT_HOST_COMMUNITY`. Only one host agreement may be in force for a municipality at a time: the effective windows of a municipality's host agreements must not overlap, and these intervals are treated as closed on both ends — `effective_end` is inclusive — so a new agreement whose `effective_start` equals an existing agreement's `effective_end` *is* an overlap and is rejected with `ERR_HOST_AGREEMENT_OVERLAP`. When `local_waste_priority_enabled` is `true` and the logical clock falls inside the agreement's effective window, deliveries from that municipality pre-empt `STANDARD`-priority allocations at the tip floor, as described in §3.3.

### 3.2. Waste Supply Agreements and Put-or-Pay Terms

Each waste supply agreement binds a municipality to deliver — or pay for — a guaranteed tonnage. A `ContractsManager` creates an agreement with the counterparty `municipality_id`, the term running from `term_start` to `term_end` (the end is exclusive and must be after the start), the `guaranteed_annual_tonnage` the municipality must deliver or pay for, the `tipping_fee_per_tonne_cents` charged per accepted tonne, and optionally the `put_or_pay_settlement_cadence`, which is `ANNUAL` by default and may alternatively be `MONTHLY`. A new agreement begins life in `DRAFT` state.

Activation moves an agreement from `DRAFT` to `ACTIVE`. A `ContractsManager` may activate an agreement only while its `term_end` is still in the future relative to the logical clock and its `guaranteed_annual_tonnage` is greater than zero; activation increments the agreement's `version` by one. Thereafter the agreement accumulates delivered tonnage in its computed `cumulative_delivered_tonnes` field, which is the sum of tonnes on `ACCEPTED` deliveries for the agreement since `term_start` and is recomputed on every delivery state change. Agreements expire automatically: when the logical clock reaches or passes an `ACTIVE` agreement's `term_end`, the agreement's state becomes `EXPIRED` and its `version` increments. A `ContractsManager` may also terminate an `ACTIVE` agreement outright; termination cascades to every delivery still `SCHEDULED` under that agreement, moving each to `DIVERTED` with `diversion_outage_id` left null, then recomputes the agreement's `cumulative_delivered_tonnes` so the just-diverted rows are excluded, and increments the agreement's `version`. `TERMINATED` is the only terminal state reachable by direct action; agreements in `EXPIRED` or `TERMINATED` state take no further transitions.

Commercial terms may be renegotiated mid-term through an **amendment**. An amendment is itself a waste supply agreement, created by a `ContractsManager` with `amendment_of_agreement_id` set to the base agreement's id. The base must be `ACTIVE`, and — because this is an OCC-guarded write — the request must carry `expected_base_agreement_version` equal to the base's current `version`, failing which the creation is rejected with `ERR_STALE_VERSION`. The amendment row is created directly in `ACTIVE` state and supersedes the base's commercial terms: the base agreement's `guaranteed_annual_tonnage` and `tipping_fee_per_tonne_cents` are overwritten with the amendment's values, the base's `version` increments by one, and the base remains `ACTIVE` and continues to accumulate deliveries. The agreement list is filterable by `municipality_id`, by `state`, and by `amendment_of_agreement_id` so that the amendment chain of a base agreement can be inspected.

### 3.3. Scheduling, Receiving, and Accepting Waste at the Tip Floor

A `PlantOperator` schedules a delivery against an agreement by submitting the `agreement_id`, the hauler's `manifest_ref`, the weighed `tonnes`, the sampled `heating_value_mj_per_kg` of the load, and the weighbridge timestamp `delivered_at`. The manifest reference is unique across every delivery in the system; a duplicate `manifest_ref` is rejected with `ERR_DUPLICATE_MANIFEST`. Both `tonnes` and `heating_value_mj_per_kg` must be greater than zero. The delivery is scheduled against the UTC calendar day of its `delivered_at` timestamp, and it begins life in `SCHEDULED` status. While a delivery is `SCHEDULED`, a `PlantOperator` may edit its `tonnes`, `heating_value_mj_per_kg`, or `delivered_at`; each edit increments the delivery's `version`. The delivery list is filterable by `agreement_id`, by `status`, and by `diversion_outage_id`.

While a delivery remains `SCHEDULED`, reads of it surface an advisory `projected_fee_cents`: the projection of the fee the load would incur at the agreement's current `tipping_fee_per_tonne_cents`, computed as the delivery's `tonnes` multiplied by that current rate and rounded half-up to whole cents. The projection is advisory only — it is never persisted as the actual fee, and because an amendment may supersede the base rate at any moment, the projection may differ from the fee eventually charged at acceptance.

Receipt at the tip floor moves a delivery from `SCHEDULED` to `RECEIVED` and is gated by the daily tip-floor allocation. The plant accepts at most 1000 tonnes per UTC calendar day: the total tonnes of same-day deliveries in `SCHEDULED` or `RECEIVED` status — deliveries already `ACCEPTED`, `REJECTED`, or `DIVERTED` do not count against the cap — plus this delivery's tonnes must be at most 1000. The comparison is inclusive: a delivery that lands the day exactly at the cap is allowed through. The delivery's agreement must also be `ACTIVE` for the receive to proceed. There is one override. When the delivery's municipality is the host community and holds a host community agreement whose effective window contains the logical clock now and whose `local_waste_priority_enabled` is `true`, the cap check is skipped entirely and the receive is always allowed — host waste takes priority. When the cap is exceeded and no effective priority agreement covers the delivery, the receive is rejected with `ERR_PRIORITY_NOT_AVAILABLE`.

Acceptance moves a delivery from `RECEIVED` to `ACCEPTED` and is the point at which money changes hands. A `PlantOperator` accepts a delivery only while its agreement is `ACTIVE` and at least one boiler is in `ONLINE` or `DERATED` status; with no boiler able to take the load, the accept is rejected with `ERR_NO_BOILER_AVAILABLE`. Acceptance is an OCC-guarded write: the request must carry `expected_agreement_version` equal to the delivery's agreement's current `version`, else `ERR_STALE_VERSION`. On acceptance the delivery's `tipping_fee_cents` is set — authoritatively, this once — to the delivery's `tonnes` multiplied by the agreement's `tipping_fee_per_tonne_cents` at the moment of acceptance, rounded half-up to whole cents; until acceptance the field is null. The agreement's `cumulative_delivered_tonnes` grows by the delivery's `tonnes`, so the put-or-pay base grows immediately, and both the delivery's and the agreement's `version` increment by one.

A received delivery that the plant will not take is moved from `RECEIVED` to `REJECTED`, with a `reject_reason` supplied in the request body; rejection increments the delivery's `version`. `ACCEPTED`, `REJECTED`, and `DIVERTED` are the delivery's terminal states.

### 3.4. Boilers, Deratings, and Outage Windows

The plant's boilers are registered by a `PlantOperator` with a `name`, a `max_thermal_capacity_mw`, and a `max_steam_tph`; both capacities must be greater than zero. A boiler is created in `ONLINE` status. When a boiler cannot run at full capacity but need not be taken out of service, the operator derates it, supplying a `derated_capacity_mw` strictly greater than zero and strictly less than the boiler's `max_thermal_capacity_mw`; the boiler moves from `ONLINE` to `DERATED` and the supplied value is recorded on the boiler. Restoring moves the boiler from `DERATED` back to `ONLINE` and clears `derated_capacity_mw` to null. Decommissioning is permanent: a boiler in `ONLINE` may be moved to the terminal `OFFLINE` status only when no outage window for that boiler is `SCHEDULED` or `ACTIVE`; attempting it otherwise is rejected with `ERR_OUTAGE_IN_PROGRESS`. Each of these transitions increments the boiler's `version`, and the boiler list is filterable by `status`.

Maintenance is planned as an **outage window**. A `PlantOperator` schedules one by naming the `boiler_id`, the window from `starts_at` (inclusive) to `ends_at` (exclusive, and after `starts_at`), a free-text `reason`, and the outage `kind`, which is either `PLANNED` or `EMERGENCY`. The window begins in `SCHEDULED` status. Two windows for the same boiler must not overlap while either is `SCHEDULED` or `ACTIVE`; the intervals are half-open, so back-to-back outages — one window's `ends_at` exactly equal to the other's `starts_at` — are allowed, and any true overlap is rejected with `ERR_OUTAGE_OVERLAP`. The outage list is filterable by `boiler_id` and `status`.

Starting an outage moves it from `SCHEDULED` to `ACTIVE` and takes the boiler out of service. The operator may start an outage only when an approved diversion plan exists for it (see §3.5) — starting without one is rejected with `ERR_DIVERSION_PLAN_REQUIRED` — and only when no other outage window for the same boiler is already `ACTIVE`. Starting is an OCC-guarded write requiring `expected_boiler_version` equal to the boiler's current `version`, else `ERR_STALE_VERSION`. On start, the boiler's status becomes `OUTAGE`, which drops it out of the effective capacity pool used by daily throughput reporting, so the next report's capacity check is computed against the reduced capacity; both the outage's and the boiler's `version` increment. Completing an `ACTIVE` outage returns the boiler to `ONLINE` and clears its `derated_capacity_mw` to null, again incrementing both versions. A `SCHEDULED` outage may instead be cancelled, moving it to the terminal `CANCELLED` status; `COMPLETED` is the other terminal state.

### 3.5. Diversion Plans and Diverting Deliveries

Every outage that will actually take a boiler down needs an approved plan for where the waste goes instead. A `PlantOperator` creates a diversion plan for an outage by naming the `outage_id` and the `max_diversion_tpd` — the maximum tonnes per day the plan may divert, which must be greater than zero. The plan is created unapproved, with `approved` false and `planned_diverted_tonnes` at zero. The operator then adds legs to the unapproved plan; each leg carries the `diversion_plan_id` of the plan it belongs to, and names a `receiving_facility_name` and its `planned_tonnes` (greater than zero). Each leg added increases the plan's `planned_diverted_tonnes` — the sum of `planned_tonnes` across the plan's legs — by the leg's amount and increments the plan's `version`. Once the plan is approved its leg set is frozen: adding a leg to an approved plan is rejected with `ERR_PLAN_ALREADY_APPROVED`.

Approval is performed by a `ContractsManager` and is permitted only when the plan has at least one leg, i.e. its `planned_diverted_tonnes` is greater than zero; approving an empty plan is rejected with `ERR_NO_DIVERSION_LEGS`. Approval sets `approved` to true and increments the plan's `version`. The plan list is filterable by `outage_id`, and a plan's legs are listed through the plan.

With an outage `ACTIVE` and its plan approved, a `PlantOperator` may divert a `SCHEDULED` delivery onto the outage by supplying the `outage_id`. Diversion is capacity-bounded: the total tonnes of deliveries already `DIVERTED` under that outage, plus this delivery's tonnes, must be at most the plan's `max_diversion_tpd` multiplied by the outage's length in whole days — the length being the number of days in the exclusive-end interval from `starts_at` to `ends_at`, computed as the ceiling of the interval's seconds divided by 86400. Breaching that bound, or naming an outage that is not `ACTIVE` or has no approved plan, is rejected with `ERR_DIVERSION_CAPACITY_EXCEEDED`. On a successful divert the delivery moves to `DIVERTED`, its `diversion_outage_id` is set to the outage's id, and its `version` increments. Diversion also advances plan execution: among the plan's legs that have not yet been executed, the leg with the largest `planned_tonnes` — ties broken by earliest `created_at` — has its `executed` flag set to true; if every leg is already executed, no leg is updated. The plan's `planned_diverted_tonnes` is unchanged by execution (it is a planned quantity), but the leg flags track progress, and when every leg is executed the plan is fully executed.

### 3.6. Daily Throughput Reporting

Each operating day is closed out with a **daily throughput report**. A `PlantOperator` creates one by supplying the `report_date` — a UTC calendar day in year-month-day form, unique across all reports, with duplicates rejected as `ERR_DUPLICATE_REPORT_DATE` — the `waste_processed_tonnes` combusted that day, the weighted `avg_heating_value_mj_per_kg` of the combusted waste (greater than zero), and the `operating_hours` the plant ran, which must be greater than zero and at most 24. While the report is `DRAFT` the operator may edit any of `waste_processed_tonnes`, `avg_heating_value_mj_per_kg`, and `operating_hours`; every create and every such edit recomputes all computed fields and each edit increments the report's `version`. The report list is filterable by `status`.

Four computed fields are produced in a pinned evaluation order. First, `thermal_input_mw` is computed as the `waste_processed_tonnes` multiplied by the `avg_heating_value_mj_per_kg`, multiplied by 1000 kilograms per tonne, divided by 3600 seconds per hour, divided by the `operating_hours`, rounded half-up to three decimal places. Second, the `capacity_check` compares that thermal input against the sum of effective capacities over all boilers, where a `DERATED` boiler contributes its `derated_capacity_mw`, an `ONLINE` boiler contributes its `max_thermal_capacity_mw`, and a boiler in `OUTAGE` or `OFFLINE` contributes zero; the check is `OK` when the thermal input is less than or equal to that sum — a report landing exactly at capacity passes — and `EXCEEDS` otherwise. Third, `steam_output_tph` is the raw steam figure — the thermal input from the first step multiplied by the plant's steam efficiency of 0.32 tonnes of steam per hour per megawatt — capped at the boiler steam cap, which is the sum of `max_steam_tph` over boilers in `ONLINE` or `DERATED` status; the result is rounded half-up to three decimal places. Fourth, `ash_generated_tonnes` is one quarter of the `waste_processed_tonnes`, rounded half-up to three decimal places.

Finalizing a report moves it from `DRAFT` to the terminal `FINALIZED` status and is permitted only when the report's `capacity_check` is `OK`; finalizing a report whose thermal input exceeds effective boiler capacity is rejected with `ERR_CAPACITY_EXCEEDED`. Finalization increments the report's `version`.

### 3.7. Power Purchase Agreements and Energy Billing

Energy revenue runs through power purchase agreements managed by an `EnergyTrader`. Creating one takes the `counterparty_name`, the contract `kind` — either `PPA` for a fixed-rate agreement or `MERCHANT` for market-priced sales — the `energy_rate_cents_per_mwh`, the `capacity_payment_cents_per_mw_month`, the `contracted_mw` (greater than zero), and the term from `term_start` to `term_end` (exclusive, after the start). The agreement begins in `DRAFT`. Activation moves it to `ACTIVE` while its `term_end` is still in the future, subject to a kind-specific shape rule: a `PPA` agreement must have a `capacity_payment_cents_per_mw_month` greater than zero, while a `MERCHANT` agreement must carry exactly zero there. Termination moves an `ACTIVE` agreement to the terminal `TERMINATED` status, and expiry to `EXPIRED` happens automatically when the logical clock reaches or passes `term_end`; both transitions and activation increment the agreement's `version`. The agreement list is filterable by `kind` and `status`.

Against an `ACTIVE` agreement, the trader records metered energy deliveries, each spanning a billing period from `period_start` to `period_end` (exclusive) and carrying the `delivered_mwh` (greater than zero). The period must fall entirely within the agreement's term — a delivery whose period lies outside the interval from `term_start` to `term_end` is rejected with `ERR_PERIOD_OUTSIDE_TERM`. For a `MERCHANT` agreement, each delivery must additionally carry its `merchant_price_cents_per_mwh` snapshot; omitting it is rejected with `ERR_MERCHANT_PRICE_REQUIRED`. For a `PPA` agreement the merchant price field is ignored if supplied.

Billing has two variants over the same fields. Under the contracted variant (`PPA`), the `billed_amount_cents` is the `delivered_mwh` multiplied by the agreement's `energy_rate_cents_per_mwh`. Under the merchant variant, it is the `delivered_mwh` multiplied by the delivery's own `merchant_price_cents_per_mwh`. In both variants the multiplication is performed first and the product rounded half-up to whole cents exactly once; the megawatt-hour quantity is never rounded first. Because the two variants draw on different rates, the same delivered quantity under the two kinds generally yields different billed amounts.

Each delivery also accrues a `capacity_payment_cents`. For a `MERCHANT` agreement this is unconditionally zero. For a `PPA` agreement it is the prorated capacity payment: the lesser of the agreement's `contracted_mw` and the plant's available megawatts at submission time — available megawatts being the sum over boilers of effective capacity, counting a `DERATED` boiler at its `derated_capacity_mw`, an `ONLINE` boiler at its `max_thermal_capacity_mw`, and any other boiler at zero — multiplied by the agreement's `capacity_payment_cents_per_mw_month`, multiplied by the period fraction. The period fraction is the length of the delivery's period in seconds divided by the number of seconds in the UTC calendar month containing `period_start`, computed to six decimal places and capped at one so an over-long period can never bill more than a full month. The result is rounded half-up to whole cents. The delivery list is filterable by `ppa_id`.

### 3.8. Metals Recovery from Ash

Ferrous and non-ferrous metals recovered from ash are sold under contracts a `ContractsManager` registers with the `processor_name`, the contractual `ferrous_recovery_pct` (a fraction of ash greater than zero and at most 0.15), the `nonferrous_recovery_pct` (greater than zero and at most 0.05), and the `processing_fee_cents_per_tonne` charged per tonne of ash processed. A contract is created in `ACTIVE` status; it may be suspended (to `SUSPENDED`) or terminated (to the terminal `TERMINATED`), each transition incrementing its `version`. The contract list is filterable by `status`.

Against an `ACTIVE` contract, a `PlantOperator` records each recovery batch with the `contract_id`, the `ash_input_tonnes` processed (greater than zero), and the commodity price snapshots `ferrous_price_cents_per_tonne` and `nonferrous_price_cents_per_tonne`. Settlement fields are computed with a pinned rounding order: each recovered-tonnage line is rounded to three decimal places first, then multiplied by its price, then each revenue line is rounded half-up to whole cents, then summed — summing raw values and rounding once at the end produces different cents and is forbidden. Concretely, `ferrous_tonnes` is the `ash_input_tonnes` multiplied by the contract's `ferrous_recovery_pct`, rounded to three decimals; `nonferrous_tonnes` is the same against `nonferrous_recovery_pct`. The ferrous revenue line is the rounded `ferrous_tonnes` multiplied by `ferrous_price_cents_per_tonne`, rounded half-up to whole cents, and likewise for non-ferrous; `gross_revenue_cents` is their sum. The `processing_fee_cents` is the `ash_input_tonnes` multiplied by the contract's `processing_fee_cents_per_tonne`, rounded half-up to whole cents, and `net_settlement_cents` is the gross revenue minus the processing fee. A batch begins in `RECORDED` status.

Settlement lifecycle actions belong to the `ContractsManager`. Settling moves a `RECORDED` batch to the terminal `SETTLED` status, but only while its contract is `ACTIVE`. Disputing moves a `RECORDED` batch to `DISPUTED`, and resolving moves a `DISPUTED` batch back to `RECORDED`, recomputing every settlement field from the contract's current rates at resolution time. Each transition increments the batch's `version`. The batch list is filterable by `contract_id` and `status`.

### 3.9. Ash Disposal, Testing, and Landfill Capacity

Residual ash goes to permitted landfills registered by an `EnvironmentalOfficer` with a `name`, the disposal `permit_number`, the `remaining_capacity_tonnes` (zero or greater), and the `daily_receipt_limit_tonnes` (greater than zero). A landfill is created in `ACTIVE` status and later reaches `CLOSED` only through exhaustion, as described below. The landfill list is filterable by `status`.

Shipments are planned by an `EnvironmentalOfficer` naming the `landfill_id`, the ash `tonnes` (greater than zero), the `shipped_on` UTC calendar day on which the shipment arrives — used for daily receipt cap accounting — and the `disposal_fee_cents_per_tonne` rate applied to the shipment. A shipment begins in `PLANNED` status. Submitting it for testing moves it to `TEST_PENDING`. While a shipment is `TEST_PENDING`, the officer records ash tests against it, each referencing the shipment through its `shipment_id` and carrying the analyte `parameter` (for example lead, cadmium, or TCLP-lead), the `measured_value`, and the regulatory `limit_value`; the test's `passed` flag is computed as the `measured_value` being less than or equal to the `limit_value`, and `recorded_at` captures the server logical clock at recording. Recording a test also increments the shipment's `version`.

Completion moves a shipment from `TEST_PENDING` to the terminal `DISPOSED` status and carries the heaviest guard set in the system. Completion is an OCC-guarded write requiring `expected_landfill_version` equal to the receiving landfill's current `version`, else `ERR_STALE_VERSION`. At least one ash test must have been recorded for the shipment — completing with none is rejected with `ERR_TEST_REQUIRED` — and every recorded test must have `passed`; a failing test rejects completion with `ERR_ASH_TEST_FAILED`. The landfill must still be `ACTIVE`, its `remaining_capacity_tonnes` must be at least the shipment's `tonnes`, and the daily receipt cap must hold: the sum of tonnes of shipments already `DISPOSED` at that landfill on the same `shipped_on` day, plus this shipment's tonnes, must be at most the landfill's `daily_receipt_limit_tonnes`. Breaching the capacity or daily-cap checks is rejected with `ERR_LANDFILL_CAPACITY`. On completion the landfill's `remaining_capacity_tonnes` is decremented by the shipment's `tonnes`, and if that brings it to exactly zero the landfill's status becomes `CLOSED`, after which further shipments to it are rejected; both the shipment's and the landfill's `version` increment. A shipment under testing that will not proceed is instead moved to the terminal `REJECTED` status with a `reject_reason` supplied. The shipment list is filterable by `landfill_id` and `status`, and a shipment's tests are listed through the shipment.

### 3.10. Emissions Permits and Continuous Monitoring

Stack emissions are governed by permits an `EnvironmentalOfficer` registers with the `pollutant` code (for example NOx, SO2, CO, or Hg), the `hourly_limit` for the rolling one-hour average, the `daily_limit` for the rolling daily average, and optionally the `rolling_avg_window_hours`, which defaults to 24. At most one permit per pollutant may be `ACTIVE` at a time; registering a second active permit for a pollutant already covered is rejected with `ERR_DUPLICATE_PERMIT`. A permit is created `ACTIVE`; a `Regulator` may suspend it, moving it to `SUSPENDED` and incrementing its `version`. The permit list is filterable by `pollutant` and `status`.

Against an `ACTIVE` permit, the officer records continuous-emissions readings, each carrying the `permit_id`, the measured `value` (greater than zero), and the `measured_at` timestamp. Each reading's `exceedance` flag is computed at recording. An hourly breach occurs when the reading's `value` is strictly greater than the permit's `hourly_limit` — a value exactly equal to the limit is not a breach. The daily rolling average is the mean of the values of all readings for the same permit whose `measured_at` falls inside the window from the new reading's `measured_at` minus the permit's `rolling_avg_window_hours` hours up to and including the new reading's `measured_at` — both ends inclusive, and the new reading itself is included in the mean — carried to six decimal places. A daily breach occurs when that rolling average is strictly greater than the permit's `daily_limit`. The reading's `exceedance` is true when either breach fires. The reading list is filterable by `permit_id`.

### 3.11. Put-or-Pay Settlement Runs

The put-or-pay provision settles, for each agreement and period, the difference between what a municipality promised and what it delivered. A `ContractsManager` runs the settlement for an agreement by supplying its `agreement_id`; the agreement may be `ACTIVE` or `EXPIRED`. The response reports the `agreement_id`, the resolved `period_start` and `period_end`, the `cadence`, the `guarantee_tonnes`, the `delivered_base_tonnes`, the `shortfall_tonnes`, the `shortfall_cents`, and the `already_billed_cents`.

Period indexing depends on the agreement's `put_or_pay_settlement_cadence`. Under the annual variant the period is the agreement's contract year starting at the `term_start` anniversary, and a single settlement covers the whole contract year. Under the monthly variant the period is the UTC calendar month containing the logical clock now. The guarantee for the period is the agreement's `guaranteed_annual_tonnage` for an annual cadence, or one twelfth of it for a monthly cadence. The delivered base is the sum of tonnes of the agreement's deliveries in `ACCEPTED` status whose `delivered_at` falls inside the period — the period end exclusive — with `REJECTED` and `DIVERTED` rows excluded, carried to three decimal places.

Under the monthly cadence, earlier periods must not be billed twice: the amounts already billed for earlier periods of the same agreement are converted back to a tonnage equivalent by dividing the already-billed cents by the agreement's current `tipping_fee_per_tonne_cents`, and the shortfall is the guarantee minus the delivered base minus that tonnage equivalent, floored at zero — never negative. The annual cadence bills once, so it has no such deduction. The shortfall in cents is the shortfall tonnage multiplied by the `tipping_fee_per_tonne_cents`, rounded half-up to whole cents. Each run records the settlement so that subsequent monthly runs deduct the already-billed tonnage equivalent; a re-run for the same period supersedes the earlier record, and only the latest record per period counts toward the already-billed total.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including all lifecycle actions such as activate, accept, start, complete, settle, and finalize — return `200 OK`. The clock-setting capability returns `200 OK`. The full request and response shapes for each endpoint are defined by the narratives in §2 and §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wte/_clock/set_current_utc` | Set the server's logical clock | Regulator |
| POST | `/wte/municipalities` | Create a municipality counterparty | ContractsManager |
| GET | `/wte/municipalities` | List municipalities | PlantOperator, ContractsManager, EnergyTrader, EnvironmentalOfficer, Regulator |
| GET | `/wte/municipalities/{id}` | Get one municipality | PlantOperator, ContractsManager, EnergyTrader, EnvironmentalOfficer, Regulator |
| POST | `/wte/host-community-agreements` | Create a host community agreement | ContractsManager |
| GET | `/wte/host-community-agreements` | List host community agreements | PlantOperator, ContractsManager, Regulator |
| GET | `/wte/host-community-agreements/{id}` | Get one host community agreement | PlantOperator, ContractsManager, Regulator |
| POST | `/wte/waste-supply-agreements` | Create a waste supply agreement (or an amendment) | ContractsManager |
| GET | `/wte/waste-supply-agreements` | List waste supply agreements | PlantOperator, ContractsManager, Regulator |
| GET | `/wte/waste-supply-agreements/{id}` | Get one waste supply agreement | PlantOperator, ContractsManager, Regulator |
| POST | `/wte/waste-supply-agreements/{id}/activate` | Activate a DRAFT agreement | ContractsManager |
| POST | `/wte/waste-supply-agreements/{id}/terminate` | Terminate an ACTIVE agreement | ContractsManager |
| POST | `/wte/waste-deliveries` | Schedule a waste delivery | PlantOperator |
| GET | `/wte/waste-deliveries` | List waste deliveries | PlantOperator, ContractsManager, EnvironmentalOfficer, Regulator |
| GET | `/wte/waste-deliveries/{id}` | Get one waste delivery | PlantOperator, ContractsManager, Regulator |
| PUT | `/wte/waste-deliveries/{id}` | Edit a SCHEDULED delivery | PlantOperator |
| POST | `/wte/waste-deliveries/{id}/receive` | Receive a scheduled delivery at the tip floor | PlantOperator |
| POST | `/wte/waste-deliveries/{id}/accept` | Accept a received delivery | PlantOperator |
| POST | `/wte/waste-deliveries/{id}/reject` | Reject a received delivery | PlantOperator |
| POST | `/wte/waste-deliveries/{id}/divert` | Divert a scheduled delivery to an outage | PlantOperator |
| POST | `/wte/boilers` | Register a boiler | PlantOperator |
| GET | `/wte/boilers` | List boilers | PlantOperator, EnergyTrader, EnvironmentalOfficer, Regulator |
| GET | `/wte/boilers/{id}` | Get one boiler | PlantOperator, EnergyTrader, EnvironmentalOfficer, Regulator |
| POST | `/wte/boilers/{id}/derate` | Derate a boiler | PlantOperator |
| POST | `/wte/boilers/{id}/restore` | Restore a derated boiler | PlantOperator |
| POST | `/wte/boilers/{id}/decommission` | Permanently take a boiler offline | PlantOperator |
| POST | `/wte/outage-windows` | Schedule an outage window | PlantOperator |
| GET | `/wte/outage-windows` | List outage windows | PlantOperator, ContractsManager, Regulator |
| GET | `/wte/outage-windows/{id}` | Get one outage window | PlantOperator, ContractsManager, Regulator |
| POST | `/wte/outage-windows/{id}/start` | Start a scheduled outage | PlantOperator |
| POST | `/wte/outage-windows/{id}/complete` | Complete an active outage | PlantOperator |
| POST | `/wte/outage-windows/{id}/cancel` | Cancel a scheduled outage | PlantOperator |
| POST | `/wte/diversion-plans` | Create a diversion plan for an outage | PlantOperator |
| GET | `/wte/diversion-plans` | List diversion plans | PlantOperator, ContractsManager, Regulator |
| GET | `/wte/diversion-plans/{id}` | Get one diversion plan | PlantOperator, ContractsManager, Regulator |
| POST | `/wte/diversion-plans/{id}/approve` | Approve a diversion plan | ContractsManager |
| POST | `/wte/diversion-plans/{id}/legs` | Add a leg to an unapproved plan | PlantOperator |
| GET | `/wte/diversion-plans/{id}/legs` | List a plan's legs | PlantOperator, ContractsManager, Regulator |
| POST | `/wte/daily-throughput-reports` | Create a daily throughput report | PlantOperator |
| GET | `/wte/daily-throughput-reports` | List daily throughput reports | PlantOperator, EnergyTrader, EnvironmentalOfficer, Regulator |
| GET | `/wte/daily-throughput-reports/{id}` | Get one daily throughput report | PlantOperator, EnergyTrader, EnvironmentalOfficer, Regulator |
| PUT | `/wte/daily-throughput-reports/{id}` | Edit a DRAFT report | PlantOperator |
| POST | `/wte/daily-throughput-reports/{id}/finalize` | Finalize a DRAFT report | PlantOperator |
| POST | `/wte/power-purchase-agreements` | Create a power purchase agreement | EnergyTrader |
| GET | `/wte/power-purchase-agreements` | List power purchase agreements | EnergyTrader, PlantOperator, Regulator |
| GET | `/wte/power-purchase-agreements/{id}` | Get one power purchase agreement | EnergyTrader, PlantOperator, Regulator |
| POST | `/wte/power-purchase-agreements/{id}/activate` | Activate a DRAFT agreement | EnergyTrader |
| POST | `/wte/power-purchase-agreements/{id}/terminate` | Terminate an ACTIVE agreement | EnergyTrader |
| POST | `/wte/energy-deliveries` | Record a metered energy delivery | EnergyTrader |
| GET | `/wte/energy-deliveries` | List energy deliveries | EnergyTrader, Regulator |
| GET | `/wte/energy-deliveries/{id}` | Get one energy delivery | EnergyTrader, Regulator |
| POST | `/wte/metals-recovery-contracts` | Create a metals recovery contract | ContractsManager |
| GET | `/wte/metals-recovery-contracts` | List metals recovery contracts | ContractsManager, PlantOperator, Regulator |
| GET | `/wte/metals-recovery-contracts/{id}` | Get one metals recovery contract | ContractsManager, PlantOperator, Regulator |
| POST | `/wte/metals-recovery-contracts/{id}/suspend` | Suspend an ACTIVE contract | ContractsManager |
| POST | `/wte/metals-recovery-contracts/{id}/terminate` | Terminate a contract | ContractsManager |
| POST | `/wte/metals-recovery-batches` | Record a metals recovery batch | PlantOperator |
| GET | `/wte/metals-recovery-batches` | List metals recovery batches | ContractsManager, PlantOperator, Regulator |
| GET | `/wte/metals-recovery-batches/{id}` | Get one metals recovery batch | ContractsManager, PlantOperator, Regulator |
| POST | `/wte/metals-recovery-batches/{id}/settle` | Settle a RECORDED batch | ContractsManager |
| POST | `/wte/metals-recovery-batches/{id}/dispute` | Dispute a RECORDED batch | ContractsManager |
| POST | `/wte/metals-recovery-batches/{id}/resolve` | Resolve a disputed batch | ContractsManager |
| POST | `/wte/landfills` | Register a permitted ash landfill | EnvironmentalOfficer |
| GET | `/wte/landfills` | List landfills | EnvironmentalOfficer, PlantOperator, Regulator |
| GET | `/wte/landfills/{id}` | Get one landfill | EnvironmentalOfficer, PlantOperator, Regulator |
| POST | `/wte/ash-shipments` | Plan an ash shipment | EnvironmentalOfficer |
| GET | `/wte/ash-shipments` | List ash shipments | EnvironmentalOfficer, PlantOperator, Regulator |
| GET | `/wte/ash-shipments/{id}` | Get one ash shipment | EnvironmentalOfficer, PlantOperator, Regulator |
| POST | `/wte/ash-shipments/{id}/submit-testing` | Submit a planned shipment for testing | EnvironmentalOfficer |
| POST | `/wte/ash-shipments/{id}/complete` | Complete disposal after tests pass | EnvironmentalOfficer |
| POST | `/wte/ash-shipments/{id}/reject` | Reject a shipment under testing | EnvironmentalOfficer |
| POST | `/wte/ash-shipments/{id}/tests` | Record an ash test result | EnvironmentalOfficer |
| GET | `/wte/ash-shipments/{id}/tests` | List a shipment's tests | EnvironmentalOfficer, Regulator |
| POST | `/wte/emissions-permits` | Register an emissions permit | EnvironmentalOfficer |
| GET | `/wte/emissions-permits` | List emissions permits | EnvironmentalOfficer, PlantOperator, Regulator |
| GET | `/wte/emissions-permits/{id}` | Get one emissions permit | EnvironmentalOfficer, PlantOperator, Regulator |
| POST | `/wte/emissions-permits/{id}/suspend` | Suspend an ACTIVE permit | Regulator |
| POST | `/wte/emissions-readings` | Record a continuous-emissions reading | EnvironmentalOfficer |
| GET | `/wte/emissions-readings` | List emissions readings | EnvironmentalOfficer, Regulator |
| GET | `/wte/emissions-readings/{id}` | Get one emissions reading | EnvironmentalOfficer, Regulator |
| POST | `/wte/settlements/put-or-pay/run` | Run the put-or-pay settlement for an agreement's current period | ContractsManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_MANIFEST` | 422 |
| `ERR_DUPLICATE_REPORT_DATE` | 422 |
| `ERR_DUPLICATE_PERMIT` | 422 |
| `ERR_OUTAGE_OVERLAP` | 422 |
| `ERR_HOST_AGREEMENT_OVERLAP` | 422 |
| `ERR_NOT_HOST_COMMUNITY` | 422 |
| `ERR_DIVERSION_PLAN_REQUIRED` | 422 |
| `ERR_NO_DIVERSION_LEGS` | 422 |
| `ERR_PLAN_ALREADY_APPROVED` | 422 |
| `ERR_DIVERSION_CAPACITY_EXCEEDED` | 422 |
| `ERR_NO_BOILER_AVAILABLE` | 422 |
| `ERR_OUTAGE_IN_PROGRESS` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_TEST_REQUIRED` | 422 |
| `ERR_ASH_TEST_FAILED` | 422 |
| `ERR_LANDFILL_CAPACITY` | 422 |
| `ERR_PERIOD_OUTSIDE_TERM` | 422 |
| `ERR_MERCHANT_PRICE_REQUIRED` | 422 |
| `ERR_PRIORITY_NOT_AVAILABLE` | 422 |
