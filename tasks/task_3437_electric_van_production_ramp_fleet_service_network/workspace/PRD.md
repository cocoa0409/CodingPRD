# Electric Van Fleet Ops API — Product Requirements Document

## 1. Introduction

Commercial fleet electrification fails in the seams: a van can be built on time and still sit useless at a depot because the utility never energized the site, because the one battery module lot that matched the order was quarantined after a supplier audit, or because a staged software rollout bricked a vehicle mid-route two days before a contractual uptime measurement closed. This document specifies the Electric Van Fleet Ops API, the manufacturer's operating system for the full arc from production ramp to in-life fleet service: supplier readiness scoring, battery-module quality gating, franchise-law-compliant direct sales, depot charging build-out, staged software campaigns, a mobile-plus-fixed service network with parts logistics, battery end-of-life planning, and uptime commitments measured in money.

The API is mounted under `/evfleet` and serves eleven distinct operator roles, from the `ProductionPlanner` watching weekly ramp capacity to the `TelematicsIngestion` pipeline pushing state-of-health reports. Two design commitments run through everything that follows. First, immediate consistency: every mutation and every cascade it triggers is visible in the same response, so a client never has to poll for side effects. Second, segregation of duties: the operator who registers a supplier may not audit it, the operator who registers a battery module may not inspect it, and the technician who diagnoses a warranty claim may not adjudicate it. Where the document appears to describe a circular dependency — charging capacity gating vehicle commissioning while vehicle demand pressures charging build-out — the evaluation order is pinned explicitly and is part of the contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); on transition endpoints shared by several roles, the requested `to_state` further restricts which of the listed roles may perform that specific transition, exactly as each entity's state machine assigns actors.

The declared roles, spelled exactly as the `X-User-Role` header must carry them, are: `PlatformAdmin`, `ProductionPlanner`, `QualityInspector`, `ComplianceOfficer`, `ChargingCoordinator`, `FleetManager`, `ServiceDispatcher`, `ServiceTechnician`, `ClaimsAdjuster`, `ReleaseManager`, and `TelematicsIngestion`.

`FleetManager` is the only entity-backed identity. When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `FleetCustomer`; ownership checks on any resource that references a `FleetCustomer` compare the resource's foreign-key field to `X-User-ID`. A fleet manager whose `X-User-ID` does not equal the owning customer's id is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403) on depot creation, charging-project creation, vehicle-order creation and the order's submission or cancellation, service-visit creation and cancellation, and warranty-claim creation.

For the remaining ten roles — `PlatformAdmin`, `ProductionPlanner`, `QualityInspector`, `ComplianceOfficer`, `ChargingCoordinator`, `ServiceDispatcher`, `ServiceTechnician`, `ClaimsAdjuster`, `ReleaseManager`, and `TelematicsIngestion` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands provenance (for example as `created_by_user_id` on a `Supplier`, `registered_by_user_id` on a `BatteryModule`, `last_inspector_user_id` on an inspected module, `completed_by_user_id` on a completed visit, or `diagnosed_by_user_id` and `adjudicated_by_user_id` on a warranty claim) but never compares it to any entity's `id`.

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

List endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are always sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through any collection.

### 2.4. The Logical Clock

The server runs on a logical clock, not wall-clock time. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it MUST NOT fall back to wall-clock time under any circumstance. A `PlatformAdmin` advances it through a test-driving capability that lives deliberately outside the `/evfleet` mount: the endpoint `POST /_clock/set_current_utc` is unprefixed, accepts `to_iso8601`, returns the resulting `current_utc`, and mutates no entity. Everything time-derived in this document — the promised delivery date computed at order confirmation, the current ISO week for the production ramp gate, month boundaries for uptime close — reads this clock.

Two calendar conventions are contractual. The production ramp gate counts registrations per ISO week, where a week runs from Monday 00:00:00Z to the next Monday 00:00:00Z on the logical clock. Uptime measurement works in whole UTC calendar months and whole UTC calendar days; dates promised to customers are whole ISO dates in `YYYY-MM-DD` form, and a close-month request names its month as a `YYYY-MM` string.

### 2.5. Common Resource Properties

Every resource in this API — fleet customers, depots, charging projects, suppliers, battery modules, vehicle orders, vehicles, service centers, mobile vans, service visits, parts stock rows, software campaigns, uptime contracts, and warranty claims — carries the same four system-maintained properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every successful mutation of the resource. `version` is an integer that increments by exactly 1 on every successful mutation, including mutations caused by a cascade rather than a direct write — so when a charging project's transition bumps its depot, the depot's `version` advances even though no client wrote to the depot directly. Lifecycle-bearing entities expose their state machine's current value: charging projects, vehicle orders, software campaigns, service visits, and warranty claims carry it in a `status` field, battery modules in `quality_status`, and vehicles in the two parallel fields `delivery_status` and `telematics_status`.

### 2.6. Optimistic Concurrency Control on Parent Aggregates

Three write endpoints guard a parent aggregate with optimistic concurrency control. Each requires a non-optional input field carrying the client's last observed `version` of the parent entity; if that value does not match the parent entity's current `version` — because another write has advanced the parent since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Creating a charging project requires `expected_depot_version` matching the target depot's current `version`. The client's view of `committed_capacity_kw` — hence the headroom against which it sized `requested_capacity_kw` — is stale when the versions disagree, and the create is refused.
- Registering a vehicle VIN requires `expected_vehicle_order_version` matching the target order's current `version`. The client's belief that a registration slot remains (`registered_count` versus `quantity`) is stale when the versions disagree, and the registration is refused.
- Appending a downtime event to an uptime contract requires `expected_uptime_contract_version` matching the contract's current `version`. The client may otherwise be extending an event list it has never observed, and the append is refused.

No other endpoint takes a version field; these three checks are expressed purely as stale-version rejection and do not depend on requests overlapping in time.

### 2.7. Numeric Precision and Rounding

All money is integer cents. Wherever a calculation produces a fractional cent, the result is rounded half-up to integer cents, and the rounding step a calculation specifies is applied exactly where specified — in particular the warranty settlement rounds each component of each claim line to integer cents before any summation, and summing raw values with a single rounding at the end is non-conforming. Percentages submitted to the API (audit measurements, state of health, committed uptime) are compared at one decimal place exactly as submitted. Measured fleet uptime is rounded half-up to one decimal place; campaign success rate is compared exactly, as a rational comparison, with no pre-rounding. Electrical capacities are compared in kW at the exact submitted precision with no rounding for depot headroom accounting, and at one decimal place with exact comparison for the commissioning demand gate. Registration-capacity counts are integer units with no rounding.

### 2.8. Validation Priority and Error Ordering

Every request is checked against the following ordered rule stack, and the first failing check wins — a request that would fail two checks always surfaces the earlier one. The order is contractual:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is declared (`ERR_UNAUTHENTICATED`, 401).
2. **Role authorization.** The role is listed for the endpoint; on multi-role transition endpoints the requested `to_state` further restricts which listed role may act (`ERR_FORBIDDEN`, 403).
3. **Existence.** Path-template ids exist, validated left to right along the URL; then body-supplied foreign keys — `fleet_customer_id`, `depot_id`, `battery_supplier_id`, `vehicle_order_id`, `battery_module_id`, `service_center_id`, `mobile_van_id`, `vehicle_id`, `service_visit_id` — must each reference an existing resource (`ERR_NOT_FOUND`, 404).
4. **Ownership.** A `FleetManager` may act only on their own customer's resources: `X-User-ID` must equal the owning `FleetCustomer` id (`ERR_OWNERSHIP_MISMATCH`, 403).
5. **Optimistic concurrency.** On the three OCC-guarded writes, `expected_depot_version`, `expected_vehicle_order_version`, or `expected_uptime_contract_version` must equal the parent's current `version` (`ERR_STALE_VERSION`, 412).
6. **State preconditions.** The target resource must be in a state that offers the requested transition or action — including `ERR_CAMPAIGN_NOT_ACTIVE` for vehicle results outside `CANARY`/`EXPANDED`/`GENERAL`, `ERR_CLAIM_NOT_DIAGNOSED` for adjudicating a `SUBMITTED` claim, `ERR_MONTH_ALREADY_CLOSED` and `ERR_MONTH_OUT_OF_ORDER` for close-month chronology, and `ERR_SOFTWARE_HOLD` plus `ERR_TELEMATICS_NOT_ACTIVE` for delivery advance (`ERR_INVALID_STATE`, 409). At the same rank, any transition attempted from a terminal state is refused as `ERR_ALREADY_TERMINAL` (409).
7. **Segregation of duties.** The three registrar/actor separations of §2.9 (`ERR_SEGREGATION_VIOLATION`, 403).
8. **Franchise law.** Approving a `DIRECT_DELIVERY` order delivering into a franchise-blocked state without an exemption (`ERR_FRANCHISE_EXEMPTION_REQUIRED`, 422).
9. **Window sanity.** Visit `window_end` strictly after `window_start`; project `install_window_end` at or after `install_window_start`; close-month `month` in `YYYY-MM` form (`ERR_WINDOW_INVALID`, 400).
10. **Uniqueness and shape.** `vin` globally unique and `van_code` globally unique (`ERR_DUPLICATE_VIN`, 409); exactly one of `service_center_id`/`mobile_van_id` set on a visit, and `claim_lines` non-empty on a claim (`ERR_VALIDATION`, 400).
11. **Van travel separation.** The 45-minute same-van buffer rule of §3.8 (`ERR_VAN_SCHEDULE_CONFLICT`, 409).
12. **Install-crew aggregate.** The overlapping-window crew ceiling of §3.2 (`ERR_INSTALL_WINDOW_CONFLICT`, 409), checked both at project creation and at entry to `PERMITTING`.
13. **Cross-entity references.** Module pack matches the order's pack (`ERR_MODULE_PACK_MISMATCH`, 422); module is `PASSED` (`ERR_MODULE_NOT_PASSED`, 409); a claim's referenced visit belongs to the same vehicle and is `COMPLETED` (`ERR_SERVICE_VISIT_NOT_COMPLETED`, 422); the vehicle is `COMMISSIONED` for visits and claims (`ERR_VEHICLE_NOT_IN_SERVICE`, 409); vehicle telematics is `ACTIVE` for campaign results and battery reports (`ERR_TELEMATICS_NOT_ACTIVE`, 409).
14. **Capacity and quota.** Weekly ramp capacity (`ERR_RAMP_CAPACITY_EXCEEDED`, 422), depot electrical headroom (`ERR_DEPOT_CAPACITY_EXCEEDED`, 422), parts availability (`ERR_PARTS_INSUFFICIENT`, 409), and the commissioning charging gate (`ERR_CHARGING_CAPACITY_INSUFFICIENT`, 422). Note that registering more VINs than an order's `quantity` is unreachable as a quota error: the registration that makes `registered_count` equal `quantity` auto-fulfills the order, so any further attempt lands on terminal `FULFILLED` and is refused with `ERR_ALREADY_TERMINAL`.
15. **Rollout gates.** Cohort-size and success-rate gates on campaign stage advance (`ERR_EMPTY_COHORT` / `ERR_ROLLOUT_GATE_FAILED`, 409), and duplicate per-vehicle results (`ERR_DUPLICATE_VEHICLE_RESULT`, 409).

### 2.9. Segregation of Duties

Three separations are enforced as hard rules, each surfacing `ERR_SEGREGATION_VIOLATION` (HTTP 403). A `QualityInspector` may not inspect a battery module they themselves registered: on every inspection transition the caller's `X-User-ID` must differ from the module's `registered_by_user_id`. A `QualityInspector` may not audit a supplier they registered: the audit caller's `X-User-ID` must differ from the supplier's `created_by_user_id`. And a `ClaimsAdjuster` may not adjudicate a claim they diagnosed: the adjudication caller's `X-User-ID` must differ from the claim's `diagnosed_by_user_id`. The provenance fields exist precisely so these checks are enforceable.

### 2.10. Depot Electrical Capacity Accounting

Depot headroom has a deliberately circular-looking shape — approving a charging project changes committed capacity, and vehicle commissioning later depends on commissioned capacity — so the evaluation order below is pinned and is part of the contract. Commissioning demand never feeds back into the headroom check.

1. A depot's `committed_capacity_kw` is the sum of `requested_capacity_kw` over that depot's charging projects in `SURVEY`, `UTILITY_REVIEW`, `PERMITTING`, or `INSTALLATION`, plus the sum of `commissioned_capacity_kw` over that depot's projects in `COMMISSIONED`. `CANCELLED` projects contribute nothing.
2. Headroom is `total_capacity_kw` minus `committed_capacity_kw`.
3. At creation, a project is eligible when its `requested_capacity_kw` is less than or equal to the headroom — the comparison is inclusive, so requesting exactly the available headroom is allowed; anything more is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED`.

Vehicle-side demand is evaluated separately, at commissioning time, by the charging demand gate of §3.6, and never enters steps 1–3. Because `SURVEY` already commits its requested kW, creating a project immediately moves `committed_capacity_kw`; commissioning a project moves its capacity from the in-flight sum to the commissioned sum for a net-zero change; cancelling a project removes its request from the committed set. The depot's `version` increments on every one of these events, which is what the `expected_depot_version` check of §2.6 protects.

## 3. Business Logic & Workflows

### 3.1. Fleet Customer Onboarding and Depot Establishment

Everything begins with the commercial account. A `PlatformAdmin` registers a fleet customer with its legal `company_name`, a primary operations `contact_email`, and an `account_tier` of either `STANDARD` or `PRIORITY`. The customer's id becomes the identity anchor for every `FleetManager` who acts on its behalf, per §2.1.

Once onboarded, the customer's fleet manager establishes depots. Creating a depot requires the manager's `fleet_customer_id` to equal their own `X-User-ID` — a manager planting a depot under another customer's account is refused with `ERR_OWNERSHIP_MISMATCH`. Each depot carries a display `name`, a street `address`, a two-letter uppercase `state_code` naming the US state the depot sits in, and a `total_capacity_kw` strictly greater than zero describing the electrical service the site can draw. The state code is not decorative: it later drives franchise-law review of orders delivering to that depot (§3.5). A fresh depot's `committed_capacity_kw` initializes to 0 and is maintained automatically thereafter by the capacity accounting of §2.10 — it is never set directly. Depots can be read back individually, listed per customer, and their charging projects listed per depot.

### 3.2. Charging Build-Out Projects: Survey to Commissioning

A charging build-out starts when the owning fleet manager requests a project at one of their depots, supplying the `depot_id`, the `requested_capacity_kw` (strictly positive), a planned installation window `install_window_start` to `install_window_end`, the electrician `crew_count` demanded during that window (at least 1), and the `expected_depot_version` guard of §2.6. Both window bounds are inclusive closed bounds, and the end must be at or after the start or the request fails with `ERR_WINDOW_INVALID`. Two gates are evaluated at creation, in the priority order of §2.8: the depot headroom rule of §2.10 (`requested_capacity_kw` may equal but not exceed headroom), and the install-window crew rule — across closed install windows at one depot, any set of mutually overlapping projects in `PERMITTING` or `INSTALLATION`, the candidate project included, must have a combined `crew_count` of at most 4; a breach is `ERR_INSTALL_WINDOW_CONFLICT`. A created project lands in `SURVEY` with `utility_denial_reason` null and `commissioned_capacity_kw` null, and because `SURVEY` commits capacity, the depot's `committed_capacity_kw` and `version` move immediately.

From there a `ChargingCoordinator` drives the project by naming a `to_state`. Survey completion advances `SURVEY → UTILITY_REVIEW`. The utility then either grants capacity — `UTILITY_REVIEW → PERMITTING`, which re-evaluates the crew-window rule because the project is now entering the regulated set — or denies it, sending the project `UTILITY_REVIEW → REDESIGN`; a denial must carry a non-empty `utility_denial_reason` in the request or it is rejected with `ERR_VALIDATION`, and the reason is recorded on the project. A redesigned project resubmits `REDESIGN → UTILITY_REVIEW`, which clears `utility_denial_reason` back to null; the loop can repeat as often as needed. Permits in hand, `PERMITTING → INSTALLATION` starts the build, and energization closes `INSTALLATION → COMMISSIONED`, at which point `commissioned_capacity_kw` is set equal to `requested_capacity_kw` and the depot's committed figure is recomputed (the request leaves the in-flight sum and enters the commissioned sum — net zero).

Cancellation is available from `SURVEY`, `UTILITY_REVIEW`, `REDESIGN`, or `PERMITTING` and drops the project's requested kW out of the committed set. A project in `INSTALLATION` offers no cancellation — the attempt fails with `ERR_INVALID_STATE` — and a `COMMISSIONED` project is terminal, so cancelling it fails with `ERR_ALREADY_TERMINAL`. `COMMISSIONED` and `CANCELLED` are the two terminal states. Every successful transition, whatever the target, increments the parent depot's `version` by 1, which is why stale depot views are caught by the creation-time OCC check rather than corrupting headroom math.

### 3.3. Supplier Readiness Audits and the Quarantine Cascade

Battery supply starts with a `ProductionPlanner` registering each supplier by `name` and `contact_email`. The registering operator's `X-User-ID` is stored as `created_by_user_id`, and the supplier's `readiness_tier` starts at `UNAUDITED`, with `last_on_time_pct`, `last_first_pass_yield_pct`, and `open_corrective_actions` all null until the first audit.

A `QualityInspector` — never the same operator who registered the supplier, or the audit is rejected with `ERR_SEGREGATION_VIOLATION` — records a readiness audit carrying `on_time_pct`, `first_pass_yield_pct`, and `open_corrective_actions`. Audits are not averaged: the latest audit fully determines the tier, and its three measurements are recorded on the supplier as `last_on_time_pct`, `last_first_pass_yield_pct`, and `open_corrective_actions`. Scoring is conjunctive and checked tier `A` first, then `B`, else `C`. Tier `A` requires on-time delivery of at least 95.0 percent, first-pass yield of at least 98.0 percent, and exactly zero open corrective actions. Tier `B` requires on-time of at least 85.0 percent, yield of at least 92.0 percent, and no more than 2 open corrective actions. Anything else is tier `C`. All boundaries are inclusive, so exactly 95.0 on-time with a 98.0 yield and zero corrective actions earns `A`.

A tier change is never local. When an audit drops a supplier to `C`, two cascades fire in the same response. First, every battery module of that supplier currently in `REGISTERED`, `IN_QA`, `REWORK`, or `FAILED` is moved to `QUARANTINED`, freezing the questionable stock. Second, every vehicle order that nominated this supplier through `battery_supplier_id` and is currently `CONFIRMED` or `IN_PRODUCTION` has its `supply_risk_flag` set true and its `promised_delivery_date` pushed out by 14 days. When a later audit recovers the supplier from `C` to `A` or `B`, the mirror cascade runs: `QUARANTINED` modules re-enter inspection at `IN_QA` from scratch — their `failure_count` is NOT reset — and flagged orders clear `supply_risk_flag` to false, but their promised dates are NOT pulled back. The push-out is one-directional by design, as §3.5's promise rule states.

### 3.4. Battery Module Quality Gating

A `ProductionPlanner` registers each battery module lot against its source `supplier_id` with the manufacturer `module_serial` and a `pack_kwh` energy class of exactly `52` or `77`. Registration records the operator as `registered_by_user_id`, sets `quality_status` to `REGISTERED`, zeroes `failure_count`, and leaves `last_inspector_user_id` null.

Quality progression is a gate with a rework loop. A `QualityInspector` — always someone other than the module's registrar, enforced per §2.9 — sends the module `REGISTERED → IN_QA`, then from `IN_QA` either passes it (`PASSED`) or fails it (`FAILED`). Every inspection transition stamps `last_inspector_user_id` with the inspector's `X-User-ID`. Each `FAILED` outcome increments `failure_count` by 1, and the moment `failure_count` reaches 2 the module auto-transitions from `FAILED` to `SCRAPPED` inside the same request — no separate scrap action exists. A failed module that has not yet hit that ceiling can be sent `FAILED → REWORK` by a `ProductionPlanner`, and after rework a `QualityInspector` returns it `REWORK → IN_QA` for a fresh inspection; the failure count survives rework.

Two transitions belong to the system rather than to an inspector. When a VIN is registered against a passed module (§3.5), the module moves `PASSED → ALLOCATED` as a cascade of vehicle creation. And the supplier quarantine cascade of §3.3 moves modules between `QUARANTINED` and `IN_QA` without touching the inspector fields. `SCRAPPED` and `ALLOCATED` are the terminal states; only a `PASSED`, never-allocated module can fulfill an order.

### 3.5. Vehicle Orders: Franchise Review, Promise Dates, and VIN Registration

A fleet manager places an order in `DRAFT` for their own customer — `fleet_customer_id` must equal the caller's `X-User-ID` — naming the destination `depot_id`, the nominated `battery_supplier_id`, a `quantity` between 1 and 500 vans, a uniform `battery_pack_kwh` of `52` or `77` for every van, a `telematics_tier` of `STANDARD` or `ADVANCED` for every van, a `delivery_method`, and a `requires_depot_charging` flag that decides whether commissioning at the depot is gated on real charging capacity (§3.6). The delivery method matters legally: `DIRECT_DELIVERY` means the manufacturer delivers to the depot and is franchise-law sensitive, while `CUSTOMER_PICKUP` means the customer collects and is exempt. A new order's `supply_risk_flag` is false, `registered_count` and `hold_count` are 0, and `promised_delivery_date` and `exemption_document_ref` are null.

Submission moves the order `DRAFT → SUBMITTED` and is performed by the owning fleet manager — the same `X-User-ID`-equals-`fleet_customer_id` ownership check applies, with `ERR_OWNERSHIP_MISMATCH` on mismatch. From `SUBMITTED` a `ComplianceOfficer` either approves the order to `CONFIRMED` or parks it in `FRANCHISE_HOLD`; a hold is not terminal, and an order in `FRANCHISE_HOLD` can still be approved to `CONFIRMED` later under exactly the same review rule. Direct-sales law is the gate: when the delivery depot's `state_code` is one of the franchise-blocked states `TX`, `MI`, or `WV` and the order's `delivery_method` is `DIRECT_DELIVERY`, approval is refused with `ERR_FRANCHISE_EXEMPTION_REQUIRED` unless the request carries a non-empty `exemption_document_ref`, which is then stored on the order. `CUSTOMER_PICKUP` orders and unblocked states need no exemption.

Approval is also the moment the customer gets a date. On entry to `CONFIRMED`, `promised_delivery_date` is computed from the logical clock as the confirm date plus 28 base days, plus 7 additional days for each started block of ten vans — the order's `quantity` divided by ten and rounded up to a whole number. An order of 2 vans confirmed on 2026-09-01 is promised 35 days later, on 2026-10-06; if a supplier downgrade later sets `supply_risk_flag`, the date pushes to 2026-10-20, and a subsequent recovery never pulls it back (§3.3). The date is recomputed only at confirmation and by the downgrade cascade — never otherwise.

The owning fleet manager may cancel from `DRAFT`, `SUBMITTED`, or `FRANCHISE_HOLD`; attempting cancellation from `FULFILLED` or `CANCELLED` is refused with `ERR_ALREADY_TERMINAL`, and any other out-of-state transition attempt draws `ERR_INVALID_STATE`. Every successful order transition increments the order's `version` by 1.

Production registration is the second half of the order's life. A `ProductionPlanner` registers each produced van against the order with `vehicle_order_id`, the allocated `battery_module_id`, a globally unique `vin` (a duplicate anywhere in the fleet is `ERR_DUPLICATE_VIN`), and the `expected_vehicle_order_version` guard of §2.6. Three cross-checks fire, in §2.8 priority order: the module's `pack_kwh` must equal the order's `battery_pack_kwh` (`ERR_MODULE_PACK_MISMATCH`), the module must be `PASSED` (`ERR_MODULE_NOT_PASSED`), and the weekly ramp gate must have room. The ramp gate is a shared production ceiling: the weekly capacity is 8 base units plus, summed over every supplier, 24 units for each supplier at tier `A`, 10 for each at `B`, and 0 for `C` or `UNAUDITED`. A registration is allowed only while the count of vehicles already registered in the current ISO week (Monday 00:00:00Z to the next Monday 00:00:00Z on the logical clock), across all customers' orders, is strictly below that capacity; when the count equals capacity the next registration is rejected with `ERR_RAMP_CAPACITY_EXCEEDED`.

Each accepted registration cascades within the same response: the module moves `PASSED → ALLOCATED`, the order's `registered_count` increments by 1, and the order's `version` increments by 1. The first VIN registered against a `CONFIRMED` order moves it `CONFIRMED → IN_PRODUCTION`; when `registered_count` reaches `quantity` the order moves `IN_PRODUCTION → FULFILLED` automatically. Because that auto-fulfillment closes the order, attempting one registration beyond `quantity` never reaches a quota check — it dies against terminal `FULFILLED` with `ERR_ALREADY_TERMINAL`, as §2.8 notes. `FULFILLED` and `CANCELLED` are the terminal states. Orders can be read individually or listed filtered by `fleet_customer_id`, `depot_id`, or `battery_supplier_id`.

### 3.6. Vehicle Delivery, Telematics, and Depot Commissioning

A freshly registered vehicle carries two parallel, independent state dimensions plus a telemetry profile. The delivery dimension starts at `ASSEMBLED`; the telematics dimension starts at `OFFLINE`. Its `software_version` begins at the `1.0.0` factory baseline, `software_hold` is false, `current_soh_pct` starts at 100.0, `battery_eol_status` is `NONE`, both end-of-life valuation fields (`eol_valuation_refurbish_cents`, `eol_valuation_recovery_cents`) are null, and `last_battery_report_at` is null until the first report.

A `ServiceDispatcher` advances one dimension at a time by naming a `dimension` (`DELIVERY` or `TELEMATICS`) and a `to_state`. On the delivery dimension the van moves `ASSEMBLED → IN_TRANSIT → AT_DEPOT → COMMISSIONED` in strict sequence; `COMMISSIONED` is the soft terminal for delivery. On the telematics dimension the van is provisioned `OFFLINE → PROVISIONED`, activated `PROVISIONED → ACTIVE`, may be suspended `ACTIVE → SUSPENDED`, and re-activated `SUSPENDED → ACTIVE`; telematics has no terminal state. Out-of-sequence requests on either dimension fail with `ERR_INVALID_STATE`.

Commissioning is the guarded gate of the delivery path. Moving `AT_DEPOT → COMMISSIONED` requires, beyond the state precondition itself, that `software_hold` be false (a held vehicle is refused with `ERR_SOFTWARE_HOLD`) and that `telematics_status` be `ACTIVE` (otherwise `ERR_TELEMATICS_NOT_ACTIVE`). When the parent order's `requires_depot_charging` is true, one further gate applies — the depot charging demand gate, which looks only at finished infrastructure: sum `commissioned_capacity_kw` over the depot's `COMMISSIONED` charging projects (in-flight projects never count), multiply by a utilization factor of 0.8, and require the result to be at least the draw of the in-service fleet plus the commissioning candidate — the number of vehicles already `COMMISSIONED` at that depot across all customers' orders, plus one, times 19.2 kW per vehicle. Equality passes, because the comparison is at-least. A shortfall is rejected with `ERR_CHARGING_CAPACITY_INSUFFICIENT`. A van that clears the gate enters the in-service fleet set that the uptime calculation of §3.9 measures.

Two hooks keep the parent order truthful. The move `ASSEMBLED → IN_TRANSIT` recomputes the parent order's `hold_count`, and every vehicle mutation — however caused — recomputes `hold_count` as the number of the order's vehicles whose `software_hold` is true. A campaign rollback (§3.7) can also reach into this dimension: a held vehicle caught `IN_TRANSIT` is recalled, reverting to `ASSEMBLED`.

### 3.7. Software Campaigns: Staged Rollout and Rollback Recall

A `ReleaseManager` opens a campaign in `DRAFT` with the `target_version` it deploys fleet-wide and a `telematics_tier_scope` of `STANDARD`, `ADVANCED`, or `ALL` selecting which vehicles' results are eligible. The campaign's `results` array starts empty — an append-only list of one entry per vehicle, each carrying the `vehicle_id`, a `result` of `SUCCESS` or `FAILED`, and a `reported_at` timestamp — and the derived counters `succeeded_count` and `failed_count` start at 0 and recompute on every accepted result.

The rollout is staged: `DRAFT → CANARY → EXPANDED → GENERAL → COMPLETE`, with `COMPLETE` and `ROLLED_BACK` terminal. Advancing out of `CANARY` or `EXPANDED` is gated on the recorded evidence. The cohort size is `succeeded_count` plus `failed_count`. A stage advance with a zero cohort is rejected with `ERR_EMPTY_COHORT`. Leaving `CANARY` requires a cohort of at least 3 vehicles; leaving `EXPANDED` requires at least 10; a shortfall is `ERR_ROLLOUT_GATE_FAILED`. The success rate — succeeded divided by cohort, compared exactly with no pre-rounding — must be at least 0.95 or the advance is refused with `ERR_ROLLOUT_GATE_FAILED`; the boundary is inclusive, so 19 successes out of 20 passes.

Pausing is first-class. From any of `CANARY`, `EXPANDED`, or `GENERAL` the campaign can move to `PAUSED`, which records the abandoned stage in `paused_from`. Resuming returns to exactly that recorded stage — a campaign paused from `EXPANDED` resumes only to `EXPANDED` — and clears `paused_from` to null; a resume to any other stage is `ERR_INVALID_STATE`. A campaign may be rolled back from `CANARY`, `EXPANDED`, `GENERAL`, or `PAUSED`; attempting any transition out of `COMPLETE` or `ROLLED_BACK` is `ERR_ALREADY_TERMINAL`.

Rollback carries the widest cascade in the system, in three linked steps, all visible in the same response. Link 1: every vehicle holding a `SUCCESS` entry in this campaign's `results` and currently telematics `ACTIVE` gets `software_hold` set true. Link 2: each such vehicle whose `delivery_status` is `IN_TRANSIT` reverts to `ASSEMBLED` — a physical recall of vans on the road. Link 3: each affected order's `hold_count` is recomputed from its vehicles' hold flags. A held vehicle is then blocked from commissioning (§3.6) until the hold clears.

Results flow in from the `TelematicsIngestion` pipeline, one vehicle at a time. A result is accepted only while the campaign is in `CANARY`, `EXPANDED`, or `GENERAL` — otherwise `ERR_CAMPAIGN_NOT_ACTIVE` — only for a vehicle whose telematics is `ACTIVE` (`ERR_TELEMATICS_NOT_ACTIVE`) and whose tier falls inside the campaign's `telematics_tier_scope`, and only once per vehicle: a second result for the same vehicle is `ERR_DUPLICATE_VEHICLE_RESULT`. An accepted `SUCCESS` also advances that vehicle's `software_version` to the campaign's `target_version`.

### 3.8. The Service Network: Centers, Mobile Vans, and Parts Stock

The after-sales network is deliberately thin: a small number of fixed service centers, each dispatching mobile vans. A `PlatformAdmin` stands up a center with its display `name`, the operating `region_code` it and its vans cover, the two-letter uppercase `state_code` it sits in, and a `bay_count` of at least 1 describing its fixed capacity. A `ServiceDispatcher` then commissions mobile vans homed at a center by pairing the `service_center_id` with a fleet `van_code`; the code must be unique across all mobile vans, and a collision is refused with `ERR_DUPLICATE_VIN`.

Parts live at centers, never on vans — a van draws stock from its home center. Stock rows are keyed by the pair of `service_center_id` and `sku`, and the stocking write is an upsert: when no row exists for the pair it is created, and when one exists the supplied `qty_delta` is applied — a positive delta is a receipt, a negative delta an adjustment, though an adjustment may never drive `on_hand_qty` below 0 (`ERR_VALIDATION`). Every accepted delta adds to both `on_hand_qty` and `received_total_qty`. The caller also supplies the `reorder_threshold` (zero or more). Three invariants hold on every row: `reserved_qty` (stock committed to open visits) is a subset view of `on_hand_qty` — reserved units remain physically on hand until consumed; the conservation identity `received_total_qty` equals `on_hand_qty` plus `consumed_total_qty` holds after every mutation; and `restock_needed` is recomputed after every mutation as true exactly when `on_hand_qty` falls strictly below `reorder_threshold`. A row at exactly its threshold does not need restock.

### 3.9. Service Visits and Battery Health in the Field

A fleet manager books a service visit for a vehicle of their own customer — ownership follows the visited vehicle's order, and a mismatch is `ERR_OWNERSHIP_MISMATCH` — and only for a vehicle that is `COMMISSIONED`, otherwise `ERR_VEHICLE_NOT_IN_SERVICE`. The booking names the `vehicle_id`, a `purpose` of `MAINTENANCE`, `REPAIR`, or `RECALL`, a half-open window from `window_start` to `window_end` (the start is inclusive, the end exclusive, and the end must lie strictly after the start or the request fails `ERR_WINDOW_INVALID`), exactly one destination — `service_center_id` for a fixed-center visit or `mobile_van_id` for a mobile visit, never both and never neither, else `ERR_VALIDATION` — and a `parts_lines` list that may be empty but, when present, carries entries of `sku` with a `qty` greater than zero.

Two checks protect the calendar and the stockroom. For a mobile visit, the new window must not collide with any other visit on the same van in `SCHEDULED` or `IN_PROGRESS`: a conflict exists unless the new window ends at or before 45 minutes before the existing window's start, or begins at or after 45 minutes after the existing window's end — the travel buffer applies on both sides of every existing engagement, and a violation is `ERR_VAN_SCHEDULE_CONFLICT`. For every parts line, the stocking center — the visit's `service_center_id`, or the van's home center for a mobile visit — must have at least the requested quantity available, where available means `on_hand_qty` minus `reserved_qty`; a shortfall is `ERR_PARTS_INSUFFICIENT`. On acceptance, each line's quantity is added to that row's `reserved_qty`, and the visit lands in `SCHEDULED` with `completed_by_user_id` null. Visits are listed with filters by `vehicle_id`, `service_center_id`, or `mobile_van_id`.

A `ServiceTechnician` then works the visit `SCHEDULED → IN_PROGRESS → COMPLETED`. Completion consumes the reserved parts in the same response: for each parts line, the stocking row's `reserved_qty` and `on_hand_qty` each decrease by the line quantity while `consumed_total_qty` increases by it — the reservation converts to consumption and the conservation identity of §3.8 holds — every touched row recomputes `restock_needed`, and the technician's `X-User-ID` is recorded as `completed_by_user_id`. Cancellation is the owning fleet manager's action, offered only from `SCHEDULED`; cancelling an `IN_PROGRESS` visit is `ERR_INVALID_STATE`, and `COMPLETED` or `CANCELLED` are terminal (`ERR_ALREADY_TERMINAL`). A cancellation releases each line's reservation — `reserved_qty` decreases, nothing else moves in aggregate — and each touched row recomputes `restock_needed`.

While vans are in service, the `TelematicsIngestion` pipeline streams battery-health reports carrying `measured_soh_pct` and `measured_at`; reports are accepted only for vehicles with telematics `ACTIVE` (`ERR_TELEMATICS_NOT_ACTIVE`). Each accepted report sets `current_soh_pct` to the measured value and `last_battery_report_at` to `measured_at`. When a report's `measured_soh_pct` falls strictly below 70.0, the vehicle's `battery_eol_status` moves from `NONE` to `EOL_REVIEW` and stays there — the flag is sticky — and both end-of-life valuations are computed and stored on the vehicle at that moment, because the two accounting views disagree on the same inputs. The refurbishment-resale view, stored in `eol_valuation_refurbish_cents`, multiplies a pack base value of 1800000 cents by a band multiplier keyed on the reported state of health: 0.85 at 90 or above, 0.70 from 80 up to but not including 90, 0.55 from 70 up to but not including 80, and 0.35 below 70, rounded half-up to integer cents; it is insensitive to pack size. The materials-recovery view, stored in `eol_valuation_recovery_cents`, multiplies the allocated module's `pack_kwh` by 12000 cents per kWh and by the exact reported state of health divided by 100, rounded half-up to integer cents; it scales with pack size and moves continuously with health. A vehicle reporting 68.4 with a 77 kWh pack records 630000 cents under refurbishment and 632016 cents under recovery — the two views genuinely diverge, and both are the contract.

### 3.10. Uptime Contracts, Downtime Events, and the Monthly Close

Commercial customers buy availability, and the uptime contract is where that promise becomes arithmetic. A `PlatformAdmin` creates the contract for a `fleet_customer_id` with a `committed_uptime_pct` strictly greater than 0 and at most 100 (expressed at one decimal), a `monthly_service_fee_cents` strictly greater than zero that credits are computed against, a `pro_rating` selector of `ROUTE_DAY` or `VEHICLE_HOUR`, and a `measurement_start_date` in `YYYY-MM-DD` form naming the first day measurements cover. A new contract's `downtime_events` list is empty, `last_closed_month` is null, `last_uptime_pct` and `last_credit_cents` are null, and `lifetime_credit_cents` is 0. A customer's contracts can be listed under the customer.

Downtime flows in from the `TelematicsIngestion` pipeline as append-only events naming the `vehicle_id`, a `started_at`, and optionally an `ended_at`; an event without `ended_at` is open and counts through the last instant of any month it overlaps. Each append carries the `expected_uptime_contract_version` guard of §2.6 and increments the contract's `version` by 1.

Closing a month is a `PlatformAdmin` action naming the `month` as `YYYY-MM`. The month must be well-formed (`ERR_WINDOW_INVALID`), may not precede the month containing `measurement_start_date` (`ERR_MONTH_OUT_OF_ORDER`), and months close strictly chronologically, each exactly once: closing the month already recorded in `last_closed_month` is `ERR_MONTH_ALREADY_CLOSED`, and closing an earlier one is `ERR_MONTH_OUT_OF_ORDER`. The close measures the customer's in-service fleet — the vehicles whose orders belong to this customer and whose `delivery_status` is `AT_DEPOT` or `COMMISSIONED` at close time. If that fleet count is zero there is nothing to measure and the close is refused with `ERR_INVALID_STATE`.

The downtime measure depends on the contract's `pro_rating`. Under `ROUTE_DAY`, downtime is summed per vehicle as the count of distinct UTC calendar days in the month overlapped by any of that vehicle's events — any overlap with a day, however brief, counts the whole day once. Under `VEHICLE_HOUR`, each event's overlap with the month is measured in hours, rounded half-up to a tenth of an hour per event before any summation, the per-event figures are summed, and the total is divided by 24 to yield vehicle-days. Open events count through the month's last instant under both variants. Measured uptime is then one minus downtime-vehicle-days divided by the product of fleet size and the number of UTC calendar days in the month, converted to a percentage and rounded half-up to one decimal.

The breach credit is a marginal tiered rate on the shortfall — the committed percentage minus the measured percentage, floored at zero. The first 2.0 percentage points of shortfall earn 2 percent of the monthly fee per point, the next 3.0 points (beyond 2.0, up to 5.0) earn 5 percent per point, and any shortfall beyond 5.0 points earns 10 percent per point; the summed credit percentage is capped at 30.0 percent. The credit in cents is the monthly fee multiplied by the capped percentage over 100, rounded half-up to integer cents. A worked contrast: with 4 in-service vehicles, a 30-day month, a 97.0 commitment, a 2000000-cent fee, and one event on one vehicle running 2026-09-01T06:00Z to 2026-09-09T18:00Z, `ROUTE_DAY` counts 9 vehicle-days, measures 92.5 percent uptime, a 4.5-point shortfall, a 16.5 percent credit, and 330000 cents; `VEHICLE_HOUR` counts 204.0 hours — 8.5 vehicle-days — measures 92.9 percent, a 4.1-point shortfall, a 14.5 percent credit, and 290000 cents. A successful close records the `month` into `last_closed_month`, the measured figure into `last_uptime_pct`, the credit into `last_credit_cents`, accumulates the credit into `lifetime_credit_cents`, and increments the contract's `version`.

### 3.11. Warranty Claims: Diagnosis, Adjudication, and Settlement

A warranty claim starts with the owning fleet manager — ownership again follows the vehicle's order customer — naming the `vehicle_id`, which must be `COMMISSIONED` (`ERR_VEHICLE_NOT_IN_SERVICE`), an optional `service_visit_id` that, when present, must belong to the same vehicle and be `COMPLETED` (`ERR_SERVICE_VISIT_NOT_COMPLETED`), and a non-empty `claim_lines` list (`ERR_VALIDATION` when empty), each line naming a `component_class` of `BATTERY`, `POWERTRAIN`, `CHARGING`, or `BODY`, a `part_cost_cents` of zero or more, and `labor_hours` of zero or more. The claim opens `SUBMITTED` with `diagnosed_by_user_id`, `diagnosis_notes`, `adjudicated_by_user_id`, `settlement_cents`, and `denial_reason` all null. Claims are listed with filters by `vehicle_id` or `service_visit_id`.

A `ServiceTechnician` diagnoses the claim, moving `SUBMITTED → DIAGNOSED` with a non-empty `diagnosis_notes` narrative (`ERR_VALIDATION` when empty); the technician's `X-User-ID` is stored as `diagnosed_by_user_id`. Adjudication belongs to a `ClaimsAdjuster`, and the segregation rule of §2.9 forbids the same operator who diagnosed the claim from adjudicating it (`ERR_SEGREGATION_VIOLATION`). Adjudicating a claim still sitting in `SUBMITTED` is refused with `ERR_CLAIM_NOT_DIAGNOSED`; `SETTLED` and `DENIED` are terminal, and touching them draws `ERR_ALREADY_TERMINAL`.

The adjudicator's `decision` selects the branch. `DENY` requires a non-empty `denial_reason` (`ERR_VALIDATION`), records it along with `adjudicated_by_user_id`, and leaves `settlement_cents` null. `APPROVE` computes `settlement_cents` and moves the claim to `SETTLED`, and the arithmetic is pinned: for each line, the covered part cost is the line's `part_cost_cents` multiplied by the coverage fraction for its class — 1.0 for `BATTERY`, 1.0 for `POWERTRAIN`, 0.9 for `CHARGING`, 0.8 for `BODY` — rounded half-up to integer cents; the covered labor cost is the line's `labor_hours` multiplied by 17500 cents per hour and by the same class fraction, also rounded half-up to integer cents; the line total is the sum of those two rounded components. The settlement is the sum of all line totals minus a single per-claim deductible of 25000 cents, floored at zero. The nested rounding order is contractual: rounding each component of each line before summing is not the same number as summing raw values and rounding once. A claim with lines of `CHARGING` at 125 cents, `CHARGING` at 135 cents, and `POWERTRAIN` at 100000 cents with 1.0 labor hour settles at 92735 cents — 113 plus 122 plus 117500, minus 25000 — where sum-then-round would wrongly yield 92734.

## 4. Endpoint Definitions

Status codes follow one rule: endpoints that create a new resource return 201, and endpoints that modify or act on an existing resource return 200. This includes the logical-clock endpoint, which mutates server state rather than a resource and returns 200, and the campaign vehicle-results write, which appends a new result entry and returns 201 even though the response body carries the updated campaign. Request payloads, OCC fields, cascade behavior, and preconditions for each endpoint are specified in §2 and §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server's logical clock (unprefixed, outside /evfleet) | PlatformAdmin |
| POST | /evfleet/fleet-customers | Register a commercial fleet customer | PlatformAdmin |
| GET | /evfleet/fleet-customers/{id} | Read one fleet customer | PlatformAdmin, FleetManager |
| GET | /evfleet/fleet-customers/{id}/depots | List depots of a customer | PlatformAdmin, FleetManager, ChargingCoordinator |
| GET | /evfleet/fleet-customers/{id}/uptime-contracts | List uptime contracts of a customer | PlatformAdmin, FleetManager |
| POST | /evfleet/depots | Create a depot for the calling FleetManager's customer | FleetManager |
| GET | /evfleet/depots/{id} | Read one depot incl. computed committed_capacity_kw | PlatformAdmin, FleetManager, ChargingCoordinator |
| GET | /evfleet/depots/{id}/charging-projects | List charging projects at a depot | PlatformAdmin, FleetManager, ChargingCoordinator |
| POST | /evfleet/charging-projects | Request a charging build-out; OCC on the depot; headroom and crew-window checks at create | FleetManager |
| POST | /evfleet/charging-projects/{id}/transition | Advance, deny, or cancel a charging project per its state machine | ChargingCoordinator |
| POST | /evfleet/suppliers | Register a battery/component supplier | ProductionPlanner |
| GET | /evfleet/suppliers/{id} | Read one supplier incl. computed readiness_tier | PlatformAdmin, ProductionPlanner, QualityInspector |
| GET | /evfleet/suppliers/{id}/battery-modules | List battery modules of a supplier | PlatformAdmin, ProductionPlanner, QualityInspector |
| POST | /evfleet/suppliers/{id}/readiness-audits | Record a readiness audit; recomputes the tier and fires the quarantine / supply-risk cascade on tier change | QualityInspector |
| POST | /evfleet/battery-modules | Register a battery module lot from a supplier | ProductionPlanner |
| POST | /evfleet/battery-modules/{id}/transition | Quality-gate progression (IN_QA / PASSED / FAILED by QualityInspector; REWORK by ProductionPlanner) | QualityInspector, ProductionPlanner |
| POST | /evfleet/vehicle-orders | Place a fleet vehicle order (DRAFT) for the caller's customer | FleetManager |
| GET | /evfleet/vehicle-orders/{id} | Read one vehicle order incl. computed promise date, counters, and risk flag | PlatformAdmin, FleetManager, ComplianceOfficer, ProductionPlanner |
| GET | /evfleet/vehicle-orders | List vehicle orders, filterable by any foreign key | PlatformAdmin, FleetManager, ComplianceOfficer, ProductionPlanner |
| POST | /evfleet/vehicle-orders/{id}/transition | Order lifecycle: SUBMITTED / CANCELLED by the owning FleetManager; CONFIRMED / FRANCHISE_HOLD by ComplianceOfficer | FleetManager, ComplianceOfficer |
| POST | /evfleet/vehicles | Register a produced VIN against an order, allocating a PASSED battery module; OCC on the order; weekly ramp gate applies | ProductionPlanner |
| GET | /evfleet/vehicles/{id} | Read one vehicle incl. SOH, software hold, and EOL valuation fields | PlatformAdmin, FleetManager, ServiceDispatcher, ServiceTechnician, ReleaseManager, ProductionPlanner, TelematicsIngestion |
| GET | /evfleet/vehicles | List vehicles, filterable by order or battery module | PlatformAdmin, FleetManager, ServiceDispatcher, ServiceTechnician, ReleaseManager, ProductionPlanner |
| POST | /evfleet/vehicles/{id}/transition | Advance one parallel state dimension: DELIVERY or TELEMATICS | ServiceDispatcher |
| POST | /evfleet/vehicles/{id}/battery-health | Ingest a telematics battery-health report; crossing below the EOL threshold computes both valuation variants | TelematicsIngestion |
| POST | /evfleet/service-centers | Stand up a limited service center | PlatformAdmin |
| GET | /evfleet/service-centers/{id} | Read one service center | PlatformAdmin, ServiceDispatcher, ServiceTechnician |
| GET | /evfleet/service-centers/{id}/mobile-vans | List mobile vans homed at a center | PlatformAdmin, ServiceDispatcher, ServiceTechnician |
| GET | /evfleet/service-centers/{id}/parts-stocks | List parts stock rows at a center | PlatformAdmin, ServiceDispatcher, ServiceTechnician |
| POST | /evfleet/mobile-vans | Commission a mobile service van homed at a service center | ServiceDispatcher |
| POST | /evfleet/service-visits | Book a service visit for a COMMISSIONED vehicle at a center or mobile van; reserves parts and enforces the van travel-buffer rule | FleetManager |
| GET | /evfleet/service-visits/{id} | Read one service visit | PlatformAdmin, FleetManager, ServiceDispatcher, ServiceTechnician |
| GET | /evfleet/service-visits | List service visits, filterable by vehicle, center, or van | PlatformAdmin, FleetManager, ServiceDispatcher, ServiceTechnician |
| POST | /evfleet/service-visits/{id}/transition | IN_PROGRESS / COMPLETED by ServiceTechnician; CANCELLED by the owning FleetManager (releases reserved parts) | FleetManager, ServiceTechnician |
| POST | /evfleet/parts-stocks | Upsert a parts stock row at a center; applies qty_delta as receipt or adjustment | ServiceDispatcher |
| POST | /evfleet/software-campaigns | Create a staged-rollout software campaign (DRAFT) | ReleaseManager |
| GET | /evfleet/software-campaigns/{id} | Read one campaign incl. results array and counters | PlatformAdmin, ReleaseManager, TelematicsIngestion |
| POST | /evfleet/software-campaigns/{id}/transition | Stage advance (gated), pause/resume, complete, or roll back with the vehicle-hold cascade | ReleaseManager |
| POST | /evfleet/software-campaigns/{id}/vehicle-results | Record one vehicle's update outcome from telematics | TelematicsIngestion |
| POST | /evfleet/warranty-claims | Submit a warranty claim for a COMMISSIONED vehicle of the caller's customer | FleetManager |
| GET | /evfleet/warranty-claims/{id} | Read one warranty claim incl. computed settlement_cents | PlatformAdmin, FleetManager, ServiceTechnician, ClaimsAdjuster |
| GET | /evfleet/warranty-claims | List warranty claims, filterable by vehicle or service visit | PlatformAdmin, FleetManager, ServiceTechnician, ClaimsAdjuster |
| POST | /evfleet/warranty-claims/{id}/diagnose | ServiceTechnician records diagnosis (SUBMITTED to DIAGNOSED) | ServiceTechnician |
| POST | /evfleet/warranty-claims/{id}/adjudicate | ClaimsAdjuster approves (computes settlement) or denies; adjudicator must differ from diagnostician | ClaimsAdjuster |
| POST | /evfleet/uptime-contracts | Create an uptime commitment contract for a fleet customer | PlatformAdmin |
| POST | /evfleet/uptime-contracts/{id}/downtime-events | Append a vehicle downtime event (open when ended_at omitted); OCC on the contract | TelematicsIngestion |
| POST | /evfleet/uptime-contracts/{id}/close-month | Close a measurement month; computes the uptime credit per the contract's pro_rating variant | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3, next to the workflow each guards; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_VALIDATION | 400 |
| ERR_WINDOW_INVALID | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_VIOLATION | 403 |
| ERR_FRANCHISE_EXEMPTION_REQUIRED | 422 |
| ERR_DUPLICATE_VIN | 409 |
| ERR_MODULE_NOT_PASSED | 409 |
| ERR_MODULE_PACK_MISMATCH | 422 |
| ERR_RAMP_CAPACITY_EXCEEDED | 422 |
| ERR_DEPOT_CAPACITY_EXCEEDED | 422 |
| ERR_INSTALL_WINDOW_CONFLICT | 409 |
| ERR_CHARGING_CAPACITY_INSUFFICIENT | 422 |
| ERR_SOFTWARE_HOLD | 409 |
| ERR_TELEMATICS_NOT_ACTIVE | 409 |
| ERR_CAMPAIGN_NOT_ACTIVE | 409 |
| ERR_DUPLICATE_VEHICLE_RESULT | 409 |
| ERR_EMPTY_COHORT | 409 |
| ERR_ROLLOUT_GATE_FAILED | 409 |
| ERR_VAN_SCHEDULE_CONFLICT | 409 |
| ERR_PARTS_INSUFFICIENT | 409 |
| ERR_SERVICE_VISIT_NOT_COMPLETED | 422 |
| ERR_VEHICLE_NOT_IN_SERVICE | 409 |
| ERR_CLAIM_NOT_DIAGNOSED | 409 |
| ERR_MONTH_ALREADY_CLOSED | 409 |
| ERR_MONTH_OUT_OF_ORDER | 409 |
