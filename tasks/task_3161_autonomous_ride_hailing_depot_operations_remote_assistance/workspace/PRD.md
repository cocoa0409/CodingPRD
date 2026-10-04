# Autonomous Ride-Hailing Depot Operations API — Product Requirements Document

## 1. Introduction

An autonomous ride-hailing fleet is only as good as its worst morning. The vehicles themselves are capable, but the operation around them is a tangle of physical constraints: a car must charge, be cleaned, have its sensors recalibrated and its software brought to the mandated release before it is allowed to carry a rider again. Those four obligations compete for a finite number of depot bays, and a depot that runs out of bays stops producing service-ready cars within the hour. Meanwhile the demand curve does not wait — peak windows need vehicles staged and released on schedule, and a territory whose mapping coverage or supervised validation hours lag behind can carry no passengers at all, no matter how many cars sit in its depot.

Safety obligations sit on top of the operational ones and cut against them directly. Weather suspends peak-window service. Road-type restrictions define where the fleet may legally operate at all. When a vehicle meets a situation it cannot resolve by itself, a human operator has to be found, and if that operator does not resolve the matter the ride must be unwound and the vehicle re-queued rather than left holding a passenger. Collisions carry evidentiary retention duties measured in calendar days, and the number of severe incidents attributed to a territory is itself a governed quantity that can shrink when a report is voided.

This document specifies the REST interface for that operation. It covers territory onboarding through mapping and validation gates, depot bay reservation and service cycles, vehicle readiness and staging, demand-driven deployment waves, the ride lifecycle from matching through settlement, remote assistance escalation, incident filing and retention, roadside response dispatch, and service-area expansion. Every state, threshold, and arithmetic rule the implementation must satisfy is stated here in prose; nothing is left to interpretation by the builder.

## 2. Global Specifications & System-Wide Principles

This section collects the rules that cut across the whole interface: how callers identify themselves, what every response body looks like, how lists are paginated, how resources are identified and versioned, and the four or five governing doctrines — readiness, bay utilization, territory posture, route gating, credit arithmetic — that every later workflow depends on. The system is mounted under the top-level path `/fleet`.

### 2.1. Operational Roles and Header Identity

Every request carries two mandatory headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the operational capacity in which that principal is acting. The role value must be one of the six declared roles, spelled exactly: `FleetOperations`, `DepotTechnician`, `RemoteAssistanceOperator`, `TerritoryPlanner`, `SafetyReviewer`, and `MappingEngineer`. A request that omits either header, that supplies a malformed value, or that names a role outside this enumeration is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the operation being attempted is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this is how a peer role's exclusive operation is denied.

`FleetOperations` runs the ride and roadside desk: registering vehicles, staging them at depots, matching and advancing rides, clearing roadside cases, and managing response teams. `DepotTechnician` owns the bay floor: reserving bays, driving vehicle service cycles, and executing the depot operations checkpoint. `RemoteAssistanceOperator` works the assistance desk: acknowledging, resolving and escalating sessions, opening roadside cases alongside `FleetOperations`, and filing incident reports. `TerritoryPlanner` creates territories and depots, plans and dispatches deployment waves, publishes demand curves, and submits service-area expansion requests. `SafetyReviewer` holds the safety mandate: approving operational-design-domain rules, activating exclusion zones, adjudicating incident reports, approving or rejecting expansions, suspending and clearing vehicles, and authoring curb rules. `MappingEngineer` maintains the HD map and curb corpus: logging mapping ticks and validation runs, drafting area rules, creating pickup locations, completing expansion mapping gates, reclassifying curb segments, retiring area rules, and — jointly with `SafetyReviewer` — scheduling exclusion zones, logging validation runs, and setting weather tiers.

Identity in this system is entirely opaque. For every one of the six roles, when `X-User-Role` names that role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server does not compare `X-User-ID` against any entity's `id`, and no ownership check anywhere in the interface is derived from it. There is exactly one place where the value is persisted: when a `RemoteAssistanceOperator` acknowledges an assistance session, the acknowledging operator's `X-User-ID` is recorded on the session as `op_user_id`. Every other use of the header is limited to authenticating the request and evaluating role permissions.

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

List responses are paginated through query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless a workflow states otherwise, list endpoints order resources by `created_at` ascending. The `meta` object of a paginated response carries `limit`, `offset`, `total_count`, and `has_more`. Filter parameters documented per endpoint — for example `status`, `route_class`, `window_code`, or `territory_id` — narrow the result set before pagination is applied.

### 2.4. Common Resource Properties and Identifier Semantics

Every persisted resource in this interface carries a system-minted `id` formatted as a plain UUID with no type prefix or resource-name prefix of any kind. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, and `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation of the row. The `version` field is a system-managed integer that starts at 1 on creation and increments by exactly 1 on every mutation a resource undergoes, whether that mutation was requested by a client or performed by the server's own recomputation logic. Derived-field writes are mutations: when a recomputation changes a value on a row, that row's `updated_at` is refreshed and its `version` advances.

This convention is uniform across the whole model. Every entity in this system — from a `ServiceTerritory` down to a `BaySlot`, a `RoadsideTeam` and a `CurbRule` — is created with the standard property set, and there are no resource types in this interface that omit `updated_at` or `version`. Where the workflows in §3 state that a transition advances a resource's `version`, that statement restates the general rule for the row being mutated and not a per-endpoint special case.

### 2.5. The Fleet Readiness Doctrine

Whether a vehicle may carry riders is decided by a single computed verdict, `service_status`, which is recalculated on every change to a vehicle's `battery_pct`, `cleanliness_score`, `calib_valid`, `software_version`, `is_roadside_blocked`, `current_depot_id`, or `status`. The verdict is derived in a fixed evaluation order. Four readiness predicates are evaluated on the vehicle's own current values, and the vehicle is *service ready* only when all four hold simultaneously: `battery_pct` is at least 80, `cleanliness_score` is at least 70, `calib_valid` is true, and `software_version` equals `target_software_version`.

Boundary behaviour is inclusive on both numeric predicates — a vehicle sitting exactly at 80 percent charge, or exactly at a cleanliness score of 70, is treated as satisfying that predicate and is therefore eligible to be reported `AVAILABLE`. Implementations that read either comparison as a strict inequality will wrongly hold such a vehicle out of service.

Once the readiness flag is known, the verdict is assigned: a vehicle whose `is_roadside_blocked` is true is `DISPATCHED`; otherwise a vehicle whose `status` is `IN_SERVICE` is `DISPATCHED`; otherwise a vehicle whose `status` is `AT_DEPOT` is `AVAILABLE` when it is service ready and `UNAVAILABLE` when it is not; and any other combination — including `DRAFT`, `ROADSIDE` and `SUSPENDED` — yields `UNAVAILABLE`. Because reaching `AVAILABLE` requires `status` to be `AT_DEPOT`, a freshly registered or suspended vehicle can never read `AVAILABLE`.

### 2.6. Depot Bay Utilization and Posture Escalation

A depot's posture is entirely a function of how full its bay pool is at the current logical clock. The occupied count is the number of distinct `service_type` and `bay_index` pairings across that depot's bay slots whose `status` is either `RESERVED` or `ACTIVE` and whose window already contains the reference instant — the window being half-open, meaning a slot counts from its `start_utc` up to but not including its `end_utc`. Slots in `COMPLETED` or `RELEASED` status, and slots whose windows lie entirely in the future, do not count. Note that a slot counts from the moment its window opens even if the cycle that owns it has not yet begun, so a depot can read as crowded purely on the strength of reservations.

The pool size is the sum of `charge_positions`, `cleaning_positions`, `calib_positions`, and `software_positions` for that depot. `occupancy_pct` is the occupied count divided by the pool size, multiplied by 100, floored to a whole integer, and capped at 100. The floor is applied before any boundary comparison, so a depot at 79.9 percent occupancy is compared as 79, not as a fractional value.

Posture then follows three ordered outcomes: at exactly 100 percent occupancy the depot is `LOCKDOWN`; otherwise at 80 percent occupancy or above it is `CONGESTED`; otherwise it is `OPEN`. Movement between `OPEN` and `CONGESTED` is symmetric in the threshold — the depot returns to `OPEN` the moment `occupancy_pct` falls back below 80, and drops out of `LOCKDOWN` back into `CONGESTED` the moment occupancy falls below 100. A depot in `LOCKDOWN` refuses new cycle starts with `ERR_POSTURE_LOCKDOWN`.

### 2.7. Territory Posture and the Exclusion Geometry

A `ServiceTerritory` carries a derived `posture` that is recomputed on every mapping tick, validation run, exclusion-zone activation or expiry, and incident review. Two accumulators feed it: `mapped_pct`, the share of road segments with validated HD maps, and `validation_hours`, the cumulative supervised validation drive time. The zone accumulator is `active_zone_count`, the number of that territory's exclusion zones currently in `ACTIVE` status — zones that are still `SCHEDULED` or have passed to `EXPIRED` are not counted at all.

The posture is decided by a strict evaluation order in which the zone gates always win. Five or more active zones puts the territory in `SUSPENDED`; three or four active zones puts it in `RESTRICTED`; only when fewer than three zones are active do mapping and validation figures come into play. With `mapped_pct` at 95 or above and `validation_hours` at 100 or above the territory is `ACTIVE`. With `mapped_pct` at 95 or above but fewer than 100 validation hours it is `VALIDATING`. With `mapped_pct` above zero but below 95 it is `MAPPING`. With no mapping progress at all it is `PENDING`. Every one of these gates is inclusive on the low side, so a territory whose `mapped_pct` sits at exactly 0 is `PENDING` rather than `MAPPING`, and one at exactly 95 percent with exactly 100 hours is `ACTIVE`.

Because the zone gates are evaluated first, a territory with three active zones reads `RESTRICTED` even if its mapping coverage has not yet reached 95 percent; the mapping-first reading, which would call it `MAPPING`, is wrong. The posture also relaxes in the same order: dropping from five active zones to four moves `SUSPENDED` back to `RESTRICTED`, and dropping below three moves `RESTRICTED` back to `ACTIVE`.

Two cadence rules govern exposure windows. An exclusion zone's own window is closed and inclusive at both edges: it runs from `start_utc` through `end_utc` with both instants inside the window, so a zone whose `start_utc` equals the reference instant is already in force. Bay slot windows, by contrast, are half-open as described in §2.6. An exclusion zone's `end_utc` is derived as `start_utc` plus `duration_seconds`. A bay slot's `end_utc` is derived the same way from its own `duration_seconds`.

### 2.8. Operational Design Domain and Route Gating

Not every road may be driven autonomously, and the permission set is data, not code. `ServiceAreaRule` rows record, per `route_class` — one of `FREEWAY`, `ARTERIAL`, `RESIDENTIAL`, or `ALLEY` — whether that class lies inside the approved operational design domain via the `allowed` boolean, together with an optional human-readable `notes` annotation. Rules are created in `DRAFT` status with `rule_version` set to 1, and only become authoritative once a `SafetyReviewer` approves them, at which point they move to `APPROVED` and their `rule_version` is incremented by 1. A rule may later be retired, moving to `RETIRED`, and retired rules no longer confer permission.

Gating is applied at three points: matching a ride, activating a deployment wave, and dispatching a wave. When a requested `route_class` is not permitted by an approved rule for the relevant territory, the request is rejected with `ERR_ROUTE_NOT_ALLOWED` (HTTP 422).

A second, sharper gate sits alongside it. An exclusion zone whose `route_class` matches the requested class and whose inclusive window contains the reference instant blocks the same three operations with `ERR_EXCLUSION_ZONE_ACTIVE` (HTTP 422). Exclusion zones are created `SCHEDULED` and become blocking only once activated to `ACTIVE`; activation is also what changes `active_zone_count` and therefore territory posture. Zone `kind` values are `CONSTRUCTION`, `EVENT`, `EMERGENCY`, `WEATHER`, and `TEMPORARY`.

The third gate is weather. Weather is recorded per territory and service window through a forecast tick that names the `window_code` and supplies the forecast `tier`; recording a tier refreshes the territory's own `version`. The tiers that matter here are the peak windows: when the forecast `tier` for a `MORNING_PEAK` or `EVENING_PEAK` window is 3 or higher, wave activation for that window is rejected with `ERR_WEATHER_SUSPENDED` (HTTP 422). The `MIDDAY` and `OVERNIGHT` windows are not subject to this gate.

Curb access is gated separately and per rider profile. `CurbRule` rows bind a `curb_access` class to a `sub_service_type`, with an `allowed` boolean deciding whether pickup and dropoff selection may use that class for rides of that service type. Pickup location `curb_access` values are `SAFE`, `NO_STOPPING`, and `LOADING_ONLY`; the `sub_service_type` values they are bound against are `STANDARD` and `ASSISTED`. Rules are created `ACTIVE` and may be retired to `RETIRED`. A `PickupLocation` also carries an `is_valid` flag that starts true and is driven false when the curb segment is reclassified as `NO_STOPPING`. A selected curb whose access class is not permitted for the ride's service type is rejected with `ERR_CURB_ACCESS_DENIED`, and a curb that is no longer valid is rejected with `ERR_LOCATION_INVALID`; both carry HTTP 422.

### 2.9. Optimistic Concurrency Control on Versioned Writes

Two write operations in this interface are guarded by optimistic concurrency, in each case against the version of the parent resource the write depends on.

Matching a ride to a vehicle carries `expected_vehicle_version`, which must equal the target vehicle's current `version`. If a depot service cycle completion, a roadside dispatch, or any other mutation has advanced the vehicle's `version` since the client last read it, the match is rejected with `ERR_STALE_VERSION` (HTTP 412). The client's view of the vehicle is stale and it must re-read before matching. Note that the field is required — omitting it is not a way to skip the check.

Submitting a service-area expansion request carries `expected_territory_version`, which must equal the target territory's current `version`. If mapping ticks, exclusion-zone activation, or any other mutation has advanced the territory's `version` since the client last observed it, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). The precondition snapshot the expansion is being taken against is stale.

The same stale-version guard applies to one further transition, described with its workflow in §3.5: confirming pickup carries `expected_vehicle_version` and is rejected with `ERR_STALE_VERSION` when it does not equal the matched vehicle's current `version`. No other endpoint in this interface accepts a version field in its request body, and clients must not send one.

### 2.10. Ride-Credit Provisioning and Integer Cent Arithmetic

Territories and vehicles hold a ride-credit economy denominated in whole cents: `territory.total_credit_cents` is the territory's pool and `Vehicle.credit_cents` is the balance carried by an individual vehicle. Both are integers, and every division in the credit arithmetic floors to a whole number before any multiplication is applied. There is no rounding of credit amounts to fractions of a cent, ever.

The territory pool is provisioned from its demand curve at match time. A `DemandSignal` is keyed by `window_code` — `MORNING_PEAK`, `MIDDAY`, `EVENING_PEAK`, or `OVERNIGHT` — and carries `projected_rides` and `manual_only_rides`, the latter counting forecast requests that cannot be served autonomously. The signal's derived `effective_demand` is the greater of zero and the projected rides minus the manual-only rides; the zero floor matters because a curve can be entered with more manual-only demand than total demand, and it must not yield a negative figure. Provision is ten times `effective_demand` when the territory is in any posture other than `RESTRICTED`, and five times `effective_demand` when the territory's posture is `RESTRICTED` at the moment of the match — the restricted multiplier halves the pool for identical demand input.

Both published credit figures are then derived from that provision against a fixed denominator of the provision plus 500. The per-ride credit is 5,000,000 divided by that denominator, floored, and `total_credit_cents` is 5,000,000 multiplied by the provision and divided by the denominator, floored. Because each division floors independently, the two figures must be computed separately rather than one being derived from the other.

Debits follow the same integer discipline. When a ride is cancelled after being matched, or when a cyclic re-dispatch unwinds a matched ride, the matched vehicle's `credit_cents` is reduced by the amount carried in the request's `credit_cents` field. The balance is bounded below at zero: a debit larger than the current balance leaves the vehicle at zero rather than producing a negative balance.

### 2.11. Nested Retrieval Order and Cross-Territory Consistency

Where a request path names more than one resource, existence is validated left to right — outermost first. The territory is resolved before the depot it contains, the depot before the nested resource inside it, and so on down the chain. The first identifier in the path that does not correspond to an existing resource determines the response: the request fails with `ERR_NOT_FOUND` (HTTP 404), and no later identifier in the path is examined. A request naming a bay slot under a depot that does not exist therefore reports the missing depot, not the missing slot.

A separate consistency rule applies to any request whose body references a resource belonging to a territory other than the one named in the path. Such a reference is rejected with `ERR_CROSS_TERRITORY` (HTTP 409). The clearest instance is staging a vehicle: the `depot_id` supplied to a staging request must name a depot whose `territory_id` equals the vehicle's own `territory_id`, and a mismatch is rejected with `ERR_CROSS_TERRITORY`.

Two uniqueness constraints complete the global picture. A vehicle's `vin` is unique within its territory, so a second registration of the same `vin` under the same `territory_id` collides and is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). Ride request creation is idempotent on the pair of `territory_id` and `idempotency_key`; replaying a creation with the same pair must return the originally created ride and must not create a second row. Genuine malformed input — an absent required field or a value of the wrong type — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The logical clock governs every time comparison in this interface. It is set through an administrative endpoint that accepts a `current_utc` value, and at server startup — before any such call — it reads exactly `2026-09-01T00:00:00Z`. The clock never falls back to real wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Bringing a Territory Online: Mapping, Validation and Expansion Gates

A territory is the outer container for everything else in this system, and it cannot serve a single rider until it has cleared two independent gates. A `TerritoryPlanner` opens the process by registering a territory with a display `name`, an operating `region_code` such as `PHX-METRO`, and — optionally at creation — a starting `mapped_pct`, a starting `validation_hours`, and a `road_type_risk` classification of `LOW`, `MEDIUM`, or `HIGH`. Registration freezes the accumulators into their starting values: `active_zone_count` begins at zero, `total_credit_cents` begins at zero, and `total_severe_incidents` begins at zero. The `posture` is then derived from those figures under the rules in §2.7, which for a fresh territory with no mapping progress means `PENDING`.

Progress arrives as ticks. A `MappingEngineer` records an HD-mapping tick carrying a `mapped_pct_delta`; the territory's `mapped_pct` becomes the smaller of 100 and the current coverage plus that delta, so the accumulator saturates rather than overshooting. A tick is accepted only while the territory's `posture` is still `PENDING` and it is what moves the territory from `PENDING` to `MAPPING`; once coverage reaches 95 percent the territory advances on its own, without any further client action, from `MAPPING` to `VALIDATING`.

The second gate is supervised road time. A `MappingEngineer` or a `SafetyReviewer` logs a validation run carrying an `hours` figure, which is added to the territory's cumulative `validation_hours`. Runs are accepted while the territory's `posture` is either `MAPPING` or `VALIDATING`, and repeated runs while the territory remains in `VALIDATING` form a self-loop that simply keeps accumulating hours. The territory reaches `ACTIVE` on its own once coverage is at 95 percent or above and cumulative validation hours are at 100 or above. A run logged in any other posture — including `PENDING`, `RESTRICTED` or `SUSPENDED` — is refused with `ERR_INVALID_STATE` (HTTP 409), and so is a mapping tick logged outside `PENDING`.

Where the fleet may physically drive is governed by the operational-design-domain rules described in §2.8. A `MappingEngineer` drafts a `ServiceAreaRule` for a single `route_class`, declaring through the `allowed` boolean whether that class is inside the domain, and may attach an explanatory `notes` string. Drafting sets `rule_version` to 1 and leaves the rule in `DRAFT` status. The rule only becomes binding when a `SafetyReviewer` approves it, which moves it to `APPROVED` and increments its `rule_version` by one — so an approved rule on its first approval carries `rule_version` 2. A rule can also be retired to `RETIRED` by a `MappingEngineer`, who may supply a `reason` with the retirement.

Territory growth is governed rather than open-ended. A `TerritoryPlanner` proposes expansion by submitting a request naming a `target_region_code` for the neighbouring area, optionally flagging `requires_road_type_validation`, and — mandatorily — supplying `expected_territory_version`, which is checked against the territory exactly as §2.9 describes; a mismatch is rejected with `ERR_STALE_VERSION`. Submission records a `mapped_pct_at_submit` snapshot of the territory's coverage at that instant, leaves `rule_version_at_approval` null, opens the request in `SUBMITTED` status, and advances the territory's own `version`.

The mapping gate on the expansion is then closed out separately. A `MappingEngineer` completes the mapping gate carrying `expected_territory_version`, again OCC-checked against the territory in the same way, and the request lands in `MAPPING_COMPLETE` when the territory's coverage is at 95 percent or above; if coverage has not reached that bar the request is recorded as `VALIDATION_FAILED` instead.

Approval is where the road-type risk gate bites. A `SafetyReviewer` approving an expansion pins the territory's rule set by setting `rule_version_at_approval` to the highest `rule_version` among that territory's `APPROVED` area rules, or to 0 when the territory has no approved rule at all. The resulting status depends on two facts together: when `requires_road_type_validation` is true and the territory's `road_type_risk` is `HIGH`, the request becomes `CONDITIONALLY_APPROVED`; in every other combination it becomes `APPROVED`. A `SafetyReviewer` may instead reject the expansion outright, supplying a `reason`, which places the request in `REJECTED`. Those six statuses — `SUBMITTED`, `MAPPING_COMPLETE`, `VALIDATION_FAILED`, `CONDITIONALLY_APPROVED`, `APPROVED`, `REJECTED` — are the complete set for an expansion request.

### 3.2. Depot Bays, Service Cycles and Vehicle Readiness

The physical throughput of the operation lives in the depot. A `TerritoryPlanner` creates a `DepotSite` with a `name` and four bay-pool dimensions: `charge_positions`, `cleaning_positions`, `calib_positions`, and `software_positions`. A new depot opens in `OPEN` posture with `occupancy_pct` at 0 and `ops_run_index` at 0. The `ops_run_index` is the depot's monotone operations epoch — a plain counter that only ever rises, advanced once per checkpoint run, and used throughout this document as a unit of elapsed operating time.

Bay capacity is reserved, not assigned. A `DepotTechnician` reserves a slot by naming the `service_type` — `CHARGE`, `CLEAN`, `CALIBRATION` or `SOFTWARE` — the physical `bay_index` within that service type's bay pool, the window `start_utc` and its `duration_seconds`, the `vehicle_id` that will occupy the bay, and the `cycle_id` the slot belongs to. The slot opens in `RESERVED` status with its `end_utc` derived from the start and duration. Two slots on the same depot, the same service type and the same `bay_index` may never overlap: a reservation whose half-open window intersects an existing `RESERVED` or `ACTIVE` slot on that bay is rejected with `ERR_BAY_SLOT_CONFLICT` (HTTP 409), because the sharing of a half-open interval means a slot starting exactly at another slot's `end_utc` is legal while one starting a second earlier is not. A technician may also release a reservation, taking it from `RESERVED` to `RELEASED`, which frees the window immediately.

A vehicle enters the shop through a `DepotCycle`. A `DepotTechnician` creates one against a `vehicle_id` and a `service_kind` of `CHARGE`, `CLEAN`, `CALIBRATION` or `SOFTWARE`; the cycle opens in `STAGED` status, carries `is_scheduled` false, and records `last_ops_run_index` as the depot's `ops_run_index` at the moment of creation. A cycle is not runnable until it holds a bay, which is what the scheduling step provides: supplying a `bay_slot_id` attaches the reservation and sets `is_scheduled` true.

Starting the cycle is guarded three ways. The cycle must be scheduled — a start attempt against an unscheduled cycle is refused with `ERR_INVALID_STATE` (HTTP 409), the same code that guards the other invalid-transition attempts on this resource. The vehicle must not already have another cycle in progress: a `DepotCycle` in `IN_PROGRESS` referencing the same `vehicle_id` blocks the start with `ERR_VEHICLE_IN_CYCLE` (HTTP 409). And the depot must not be sealed: a depot in `LOCKDOWN` posture refuses the start with `ERR_POSTURE_LOCKDOWN` (HTTP 409). When all three pass, the cycle moves from `STAGED` to `IN_PROGRESS`, its reserved bay slot moves to `ACTIVE`, and the depot's occupancy is recomputed — which is exactly the point at which a previously roomy depot can tip into `CONGESTED` or `LOCKDOWN`.

Completion is where the service is actually delivered, and the four service kinds do four different things to the vehicle. Completing a cycle whose `service_kind` is `CHARGE` sets the vehicle's `battery_pct` to 100. Completion of a `CLEAN` cycle sets the vehicle's `cleanliness_score` to the `cleanliness_score` supplied in the completion request. Completion of a `CALIBRATION` cycle sets the vehicle's `calib_valid` to the `signed_off` value supplied in the request. Completion of a `SOFTWARE` cycle sets the vehicle's `software_version` to its own `target_software_version`. In every case the cycle's bay slot moves to `COMPLETED` and its window is released back to the pool, the vehicle's readiness verdict is recomputed under §2.5 — which is what can finally make it `AVAILABLE` — and the depot's occupancy is recomputed under §2.6.

Two preconditions make that completion conditional on evidence rather than assertion. A `CLEAN` cycle may not be completed without a `cleanliness_score` in the request; omitting it is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than an invalid-state error. A `CALIBRATION` cycle may not be completed unless the request carries `signed_off` set to true; a completion without it is rejected with `ERR_CALIBRATION_SIGNOFF_REQUIRED` (HTTP 400). A cycle that cannot finish is aborted instead: aborting takes an `IN_PROGRESS` cycle to `ABORTED`, releases its bay slot to `RELEASED`, and recomputes the vehicle's readiness — but note that an aborted cycle delivers none of the four service effects, so a vehicle whose cycle is aborted comes out no better equipped than it went in.

Vehicle registration and staging sit alongside the cycle machinery. A `FleetOperations` operator registers a vehicle with a `vin`, an initial `battery_pct`, an optional `cleanliness_score`, an optional `calib_valid`, its `software_version`, and the fleet-mandated `target_software_version`. A new vehicle comes up in `DRAFT` status with `service_status` `UNAVAILABLE`, `credit_cents` 0, `is_roadside_blocked` false, `current_depot_id` null, and `delay_ops_runs` 0. Registration is subject to the per-territory `vin` uniqueness rule from §2.11; a colliding `vin` is rejected with `ERR_DUPLICATE_RESOURCE`.

Staging moves a vehicle into a depot. A `FleetOperations` operator or a `DepotTechnician` supplies a `depot_id`, and the vehicle moves from either `DRAFT` or `IN_SERVICE` into `AT_DEPOT`, recording that depot as its `current_depot_id`; the depot must belong to the vehicle's own territory or the request is rejected with `ERR_CROSS_TERRITORY` (HTTP 409), as §2.11 sets out. Because the vehicle is now staged rather than in service, its readiness verdict is recomputed — and a vehicle that is fully charged, clean, calibrated and on the mandated software becomes `AVAILABLE` the moment it is staged, provided it is not roadside-blocked.

Returning a vehicle to service is deliberately harder than staging it. Moving from `AT_DEPOT` back to `IN_SERVICE` requires that the vehicle is not blocked by an open roadside response — a vehicle whose `is_roadside_blocked` is true is refused with `ERR_VEHICLE_ROADSIDE_BLOCKED` (HTTP 409) — and that its readiness verdict is `AVAILABLE`; a vehicle that fails any of the four readiness predicates is refused with `ERR_VEHICLE_NOT_SERVICE_READY` (HTTP 409). On success the vehicle's `current_depot_id` is cleared back to null and its readiness is recomputed, which now reads `DISPATCHED` because the vehicle is in service.

Suspension is a `SafetyReviewer` action on a staged vehicle, and it may not be used to interrupt work already underway. A vehicle can be suspended only from `AT_DEPOT`, and only when no `DepotCycle` in `IN_PROGRESS` references it; the presence of such a cycle blocks the suspension with `ERR_VEHICLE_HAS_ACTIVE_CYCLE` (HTTP 409). Suspension moves the vehicle to `SUSPENDED` and recomputes its readiness, which drops it to `UNAVAILABLE`. Clearing a suspension returns it to `DRAFT`, from which it must be staged again. Note that clearing a suspension does not restore readiness: the vehicle returns to `DRAFT`, not to `AT_DEPOT`.

### 3.3. Demand Curves and Staged Fleet Deployment

Deployment is planned against a forecast rather than a live queue. A `TerritoryPlanner` publishes a `DemandSignal` for one of the four service windows — `MORNING_PEAK`, `MIDDAY`, `EVENING_PEAK`, `OVERNIGHT` — by supplying `projected_rides` and `manual_only_rides`. Publishing for a window code that already has a signal replaces it rather than creating a second row for the same window. The signal's derived `effective_demand` is the greater of zero and the projected rides minus the manual-only rides, and this quantity is what feeds the credit arithmetic in §2.10.

A `TerritoryPlanner` then plans a `DeploymentWave` for a `window_code` with a `planned_vehicle_count`. A new wave opens `PLANNED` with `deployed_vehicle_count` at 0 and its `last_ops_run_index` set to the territory's current operations epoch.

Activation is the point at which all three safety gates from §2.8 converge on a single request. A wave may be activated only when the territory's `posture` is `ACTIVE` — anything else, including `RESTRICTED` or `SUSPENDED`, is refused with `ERR_TERRITORY_NOT_ACTIVE` (HTTP 409); only when the territory has no active exclusion zones at all — a single `ACTIVE` zone is enough to refuse the activation with `ERR_ZONE_BLOCKED_WAVE` (HTTP 409), even though three zones would be needed to push the posture out of `ACTIVE`; and only when the forecast weather tier for the wave's own window is below 3, since a tier of 3 or higher for a `MORNING_PEAK` or `EVENING_PEAK` window is refused with `ERR_WEATHER_SUSPENDED` (HTTP 422). The activation request may also carry a `route_class`, which is subjected to the domain and exclusion gates like any other routing decision — an unapproved class is refused with `ERR_ROUTE_NOT_ALLOWED` and a class under an active exclusion zone with `ERR_EXCLUSION_ZONE_ACTIVE`. On success the wave moves from `PLANNED` to `ACTIVE`.

Dispatching is the allocation itself, and it is deliberately not "everything you planned". The wave's budget is its own `planned_vehicle_count`, and against that budget it must leave a staged reserve behind. The reserve floor is 6 divided by the wave's `planned_vehicle_count`, rounded up to a whole number; this rounding is performed once per wave, before any subtraction, and it rounds up rather than down. A wave planning 4 vehicles therefore keeps a reserve floor of 2, not 1, and consequently deploys one fewer vehicle than a floor-based reading would allow. A wave planning 7 or more vehicles keeps a reserve floor of 1.

The candidate pool is every vehicle in the wave's territory whose `status` is `AT_DEPOT`, whose `is_roadside_blocked` is false, and whose `service_status` is `AVAILABLE`. Vehicles in `DRAFT`, `IN_SERVICE`, `ROADSIDE` or `SUSPENDED` are excluded by the status requirement, and a staged vehicle that has not yet met all four readiness predicates is excluded by the availability requirement. The number of candidates is counted, and the actual allocation cap is the smaller of the wave's budget and the candidate count minus the reserve floor — floored at zero, so a territory with fewer available vehicles than its reserve floor deploys nothing at all rather than deploying a negative number. Candidates are then ranked by `battery_pct` descending and, where batteries tie, by `created_at` ascending; ties are never broken by `id`. The top candidates up to the cap are taken, each is moved from `AT_DEPOT` into `IN_SERVICE` — a mutation that advances each vehicle's `version` and recomputes its readiness to `DISPATCHED` — and the wave's `deployed_vehicle_count` is set to the number actually moved. The wave itself moves from `ACTIVE` to `COMPLETED`.

A wave that should not run may be aborted from either `PLANNED` or `ACTIVE`, landing in `ABORTED`. No vehicles move as a result of an abort.

### 3.4. Matching Rides and Advancing Them to Settlement

A ride begins with a `FleetOperations` operator registering a `RideRequest` for a territory, supplying the `rider_name`, a `sub_service_type` of either `STANDARD` or `ASSISTED`, an optional `manual_only_reason` drawn from `MOBILITY_ASSIST`, `CHILD_SEAT` or `NONE` and set for assisted requests, and a client-supplied `idempotency_key`. The ride opens in `REQUESTED` status with `vehicle_id`, `pickup_location_id` and `dropoff_location_id` all null and `dispatch_attempts` at 0. Because idempotency is keyed on the pair of `territory_id` and `idempotency_key`, a retried submission must hand back the original ride untouched rather than opening a second one.

A `MappingEngineer` creates a `PickupLocation` by naming the stable `curb_segment_code` that identifies the segment and its `curb_access` class; the new location comes up with `is_valid` true. A curb is invalidated when a `MappingEngineer` reclassifies it as `NO_STOPPING`, the reclassification also applying the new `curb_access` value to the location and advancing the location's `version`; a reclassification to `SAFE` or `LOADING_ONLY` leaves the location valid.

Matching a ride to a car is the most heavily guarded transition in the interface, and its guards are evaluated in the fixed order set out in §3.7. Four things must hold. The territory's `posture` must be `ACTIVE`, or the match is refused with `ERR_TERRITORY_NOT_ACTIVE` (HTTP 409). The `pickup_location_id` named in the match request must reference a `PickupLocation` whose `is_valid` is true, or the match is refused with `ERR_LOCATION_INVALID` (HTTP 422). The curb's access class must be permitted for the ride's `sub_service_type` by an `ACTIVE` `CurbRule`, or the match is refused with `ERR_CURB_ACCESS_DENIED` (HTTP 422) — this is the priority-10 curb check, and §2.8 gives the rule semantics. Finally, the selector must find a car, and if it finds none the match is refused with `ERR_NO_VEHICLE_AVAILABLE` (HTTP 409).

The selector searches only the ride's own territory, and only among vehicles whose `status` is `IN_SERVICE` and whose `is_roadside_blocked` is false. There is deliberately no fallback to staged vehicles: a vehicle sitting `AT_DEPOT` cannot be dispatched to a rider even if its readiness verdict reads `AVAILABLE`, because a staged vehicle has not been returned to service. Candidates are ranked by `battery_pct` descending with `created_at` ascending as the tie-break, and the first-ranked candidate is selected.

The match request also carries `expected_vehicle_version`, the optimistic-concurrency field described in §2.9; it must match the selected vehicle's current `version` or the match is rejected with `ERR_STALE_VERSION` (HTTP 412). Note the ordering consequence: because this check is applied at match time against the vehicle the selector chose, a client that read a vehicle's version, then performed a depot service cycle completion, then attempted to match will be refused even though its chosen vehicle is still the ranked winner.

A successful match records the selected vehicle on the ride as `vehicle_id`, records the chosen `pickup_location_id`, moves the vehicle's readiness verdict to `DISPATCHED`, and advances the vehicle's `version`. It also triggers the territory credit provisioning described in §2.10: the territory's `total_credit_cents` is recomputed from the demand signal for the ride's window code, and the matched vehicle's `credit_cents` is credited. The ride moves from `REQUESTED` to `MATCHED`.

Pickup confirmation is the next step, and it carries two fields. The operator supplies the chosen `dropoff_location_id` and an `expected_vehicle_version`. The ride must currently be `MATCHED`, and the dropoff curb is subjected to the same access check as the pickup curb under §2.8 — a dropoff class not permitted for the ride's service type is refused with `ERR_CURB_ACCESS_DENIED` (HTTP 422). The supplied `expected_vehicle_version` must equal the matched vehicle's current `version` or the request is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the ride records the `dropoff_location_id`, moves from `MATCHED` to `PICKED_UP`, and the vehicle's readiness verdict becomes `ON_TRIP`.

Completion closes a ride that has already collected its rider. Moving from `PICKED_UP` to `COMPLETED` requires that the vehicle is not roadside-blocked; a vehicle with `is_roadside_blocked` true blocks the completion with `ERR_VEHICLE_ROADSIDE_BLOCKED` (HTTP 409). On success the vehicle's readiness verdict is recomputed, and a vehicle that is back to `AT_DEPOT` and service-ready returns to `AVAILABLE` rather than staying `ON_TRIP`.

Cancellation comes in two flavours with different arithmetic. Cancelling a ride outright is permitted from `REQUESTED` or from `MATCHED`; any other status — including `PICKED_UP`, which has already collected a rider — is refused with `ERR_INVALID_STATE` (HTTP 409). Cancelling a `REQUESTED` ride has no financial consequence. Cancelling a `MATCHED` ride carries a `credit_cents` value: the matched vehicle's readiness verdict is recomputed back out of `DISPATCHED`, and its `credit_cents` is reduced by the supplied amount, bounded below at zero so the balance can never go negative. Marking a no-show is the narrower operation and works only from `REQUESTED`; it takes the ride to `CANCELLED_NO_SHOW` and recomputes the vehicle's readiness. The four terminal ride statuses are `COMPLETED`, `CANCELLED_NO_SHOW`, `CANCELLED`, and `FAILED`.

### 3.5. Remote Assistance, Cyclic Re-Dispatch and Incident Filing

When a vehicle reaches a situation it cannot resolve on its own, an operator — `RemoteAssistanceOperator` or `FleetOperations` — escalates the ride to a remote assistance session, supplying a `reason` drawn from `STUCK`, `ROAD_BLOCKED`, `SENSOR_FAULT`, `PASSENGER_ASSIST` or `OTHER`. The session opens in `ESCALATED` status with `escalation_tier` set to 1, `attempt_count` at 0, `op_user_id` null, and `last_ops_run_index` recording the depot's operations epoch; the vehicle under assistance is copied onto the session as its `vehicle_id` from the ride's `vehicle_id` at the moment of creation, so a session keeps pointing at the car it was opened for even if the ride is later un-matched. The ride the session was opened against is recorded on the session as its `ride_request_id`.

Escalation records a dispatch attempt against the ride: the ride's `dispatch_attempts` is incremented by one. This counter is what drives cyclic re-dispatch. When the attempt being recorded is the third attempt against a ride that is still `MATCHED` — that is, when `dispatch_attempts` reaches 3 as a result of this recording — the system unwinds the pairing rather than leaving it in place: the matched vehicle's `credit_cents` is reduced by the `credit_cents` amount carried on the escalation request, bounded below at zero, the vehicle's readiness verdict is recomputed back out of `DISPATCHED`, the ride's `vehicle_id` is cleared to null, and the ride returns from `MATCHED` to `REQUESTED` so that it can be matched afresh. A ride is therefore never stuck holding a vehicle that has failed it three times.

An escalated session is worked by a `RemoteAssistanceOperator`. Acknowledging a session moves it from `ESCALATED` to `ACKNOWLEDGED` and records the acknowledging operator's `X-User-ID` on the session as `op_user_id`; acknowledging a session that is not `ESCALATED` is refused with `ERR_INVALID_STATE` (HTTP 409), as are the other out-of-sequence actions below. Acknowledged sessions that nobody actioned do not sit indefinitely: the depot operations checkpoint, described in §3.7, returns any session that has been `ACKNOWLEDGED` across three depot operations runs back to `ESCALATED`, raising its `escalation_tier` by one, incrementing its `attempt_count` by one, and refreshing its `last_ops_run_index` to the depot's current epoch.

From `ACKNOWLEDGED` the session has two endings. The operator may resolve it, moving it to `RESOLVED`, which is one of the two terminal statuses and carries no further cascade. Or the operator may declare it unresolvable, which requires that the session's `attempt_count` is at least 3; an attempt below that threshold is refused with `ERR_MAX_ATTEMPTS_NOT_REACHED` (HTTP 409). A successful declaration moves the session to `UNRESOLVED` — the other terminal status — and cascades outward: the ride referencing the session moves to `FAILED`, which in turn recomputes the matched vehicle's readiness verdict and advances the vehicle's `version`.

Incident filing hangs off the assistance session rather than the ride directly, and its reachability is narrow by design. A `RemoteAssistanceOperator` or a `SafetyReviewer` files an incident against a ride by supplying a `severity` of `MINOR`, `MODERATE` or `SEVERE` and a narrative `description`. The filing is accepted only while an assistance session for that ride is still in `ESCALATED` or `ACKNOWLEDGED`; once the session has been driven to `UNRESOLVED`, the ride is `FAILED` and no further session — and therefore no further report — can be created against it. A filing attempted in that condition is rejected with `ERR_SESSION_TERMINAL` (HTTP 409). This is a structural cap on the severe-incident count rather than an incidental rule: a territory's severe-incident total cannot grow through a ride that has already been closed out as unresolvable.

A report that is accepted opens in `FILED` status and carries two derived retention fields. `crash_evidence_retained` is true exactly when the report's `severity` is `MODERATE` or `SEVERE`, and false for `MINOR`. `retention_expires_at` is the report's `created_at` offset by a fixed number of exact seconds: 365 days — 31,536,000 seconds — when crash evidence is retained, and 180 days — 15,552,000 seconds — when it is not. The offset is applied as exact seconds from `created_at`, not as a calendar-month calculation. Both fields are recomputed from the report's own severity and creation instant, so a `MINOR` report's expiry lands roughly half as far out as a `SEVERE` one filed at the same moment.

Incident reports are adjudicated by a `SafetyReviewer` along a fixed track with one branch. Beginning review moves a `FILED` report to `UNDER_REVIEW`. Closing moves an `UNDER_REVIEW` report to `CLOSED`, one of the two terminal statuses. Voiding is the branch: a `FILED` report may be voided directly to `VOIDED`, the other terminal status, without ever passing through review; an `UNDER_REVIEW` report cannot be voided.

The territory-level severe-incident counter is an aggregate over reports, not a running tally. Whenever it is recomputed — on filing and on voiding — it is set to the number of `IncidentReport` rows whose `vehicle_id` equals the ride's matched vehicle and whose `severity` is `SEVERE` and whose `status` is anything other than `VOIDED`. Reports in `FILED`, `UNDER_REVIEW` or `CLOSED` all count; `VOIDED` reports are excluded entirely, which means voiding a severe report reduces the territory's `total_severe_incidents` by one. A `SEVERE` report filed against a vehicle that later becomes associated with a different ride still counts toward the territory, because the aggregate keys on the vehicle rather than the ride.

### 3.6. Roadside Response, Team Selection and the Vehicle Cascade

A vehicle that stops dead gets a physical response. A `FleetOperations` operator registers a `RoadsideTeam` in a territory with a human-readable `team_code` and a `road_class` of `ARTERIAL`, `FREEWAY` or `RESIDENTIAL` describing the roads the team is equipped for; a new team comes up `AVAILABLE`. A team can be taken off shift, moving it to `OFF_SHIFT`, and the `team_code` is a stable ranking key — it is the only ranking key the selector uses, which is what makes ranking ties impossible.

A `FleetOperations` operator or a `RemoteAssistanceOperator` opens a `RoadsideCase` for a disabled vehicle by naming the `road_class` the vehicle is stranded on and, optionally, the `assistance_session_id` it was escalated from; the vehicle itself is taken from the path and recorded on the case as its `vehicle_id`. Opening the case both selects a team and assigns it, so the case never exists in an unassigned state: it opens directly in `TEAM_ASSIGNED` with the selector's pick recorded as `team_id`, and the territory operations epoch at creation captured as `created_ops_run_index` — that epoch value is what later drives the response SLA. The selected team's status moves to `ON_CASE`.

Selection itself is ordered and has two filters before any capacity or SLA consideration. The pool is the territory's teams whose status is `AVAILABLE` or `ON_CASE`; teams that are `OFF_SHIFT` are excluded from selection entirely. The road-class filter then narrows it, and it is deliberately asymmetric. When the case's `road_class` is `FREEWAY` the pool widens to accept teams equipped for either `FREEWAY` or `ARTERIAL`, so a territory with no freeway-qualified team available can still respond using an arterial team. For every other road class the pool narrows to teams whose `road_class` matches the case exactly. If the filtered pool is empty the case cannot be opened and the request is refused with `ERR_NO_TEAM_AVAILABLE` (HTTP 409). Otherwise the pool is ranked by `team_code` ascending and the first team is selected.

Two further checks are applied against the selected team and the case's age. Because `ON_CASE` teams remain candidates until the cap binds, a team already working can still be picked; the check is on load, not on status: the number of `RoadsideCase` rows assigned to the selected team whose status is `RESPONSE_DISPATCHED` is counted, and if that count is already 2 or more, the assignment is refused with `ERR_TEAM_CAPACITY_EXCEEDED` (HTTP 409). Separately, a case that has been sitting too long is refused rather than assigned: when the territory's current operations epoch minus the case's `created_ops_run_index` is 4 or more and the case is still `OPEN`, the request is refused with `ERR_RESPONSE_SLA_BREACHED` (HTTP 409). Elapsed operating time is counted in territory operations epochs, not in wall-clock hours, and four epochs is the whole allowance.

Dispatching is the moment the road is actually closed. Moving a case from `TEAM_ASSIGNED` to `RESPONSE_DISPATCHED` stamps `dispatched_at` with the current logical clock and increments the case's `raise_count` by one. It also fires the cascade that matters most for fleet operations: the referencing vehicle's `status` moves from `IN_SERVICE` to `ROADSIDE`, its `is_roadside_blocked` flag becomes true, its readiness verdict is recomputed — which reads `DISPATCHED` while the block is in force — and the vehicle's `version` advances. This cascade is the serialization point described in §2.9: any client holding a vehicle `version` captured before the dispatch will find its subsequent match attempt refused with `ERR_STALE_VERSION`, because the vehicle it thought it was matching is now blocked and roadside.

Clearing reverses the cascade. Moving a dispatched case to `CLEARED` returns the referencing vehicle's `status` from `ROADSIDE` back to `AT_DEPOT`, clears its `is_roadside_blocked` flag back to false, recomputes its readiness, and advances its `version`. Note that clearing returns the vehicle to the depot, not to service; it must be staged and returned to service again through the flow in §3.2 before it can take riders. Clearing also releases the assigned team: the team returns to `AVAILABLE` when it has no other case in `RESPONSE_DISPATCHED`.

Cancellation is available only while a case is still on the near side of dispatch. A case in `OPEN` or `TEAM_ASSIGNED` may be cancelled to `CANCELLED`, and the assigned team is released back to `AVAILABLE` on the same condition — that it holds no other `RESPONSE_DISPATCHED` case. A case that has already been dispatched cannot be cancelled; it must be cleared through the response path, which is what releases the vehicle. The terminal statuses for a case are `CLEARED` and `CANCELLED`.

### 3.7. Validation Precedence and the Depot Operations Checkpoint

When several checks could fire on the same request, the order in which they are evaluated is itself part of the specification, because the code a caller receives tells it which condition to fix first. The following precedence is fixed and applies wherever two of these checks overlap on one request; a check earlier in the list masks every check later in it.

Authentication is absolute and evaluated first: a request missing its role headers, carrying a malformed value, or naming a role outside the six declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined. Authorization follows immediately: a well-formed caller attempting an operation that belongs to a peer role is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Resource existence comes third, validated strictly left to right along the path as §2.11 describes, so a request naming a nonexistent outer resource reports `ERR_NOT_FOUND` (HTTP 404) even if a later path segment would also have failed. Uniqueness collisions come fourth and only on the two collections that have them — vehicle registration on the per-territory `vin`, and ride creation on the per-territory `idempotency_key` — both reported as `ERR_DUPLICATE_RESOURCE` (HTTP 409).

The safety gate cluster comes next, and it is where the ordering has the sharpest consequences. Route-class permission is evaluated before exclusion zones: a request whose route class is outside the approved operational design domain is rejected with `ERR_ROUTE_NOT_ALLOWED` (HTTP 422) rather than being reported as zone-blocked, so a class that is both unapproved and currently excluded surfaces as a domain violation. Exclusion zones are evaluated next, and an `ACTIVE` zone covering the requested class at the reference instant is rejected with `ERR_EXCLUSION_ZONE_ACTIVE` (HTTP 422). Weather comes after both, and only for peak windows: a tier of 3 or higher on a `MORNING_PEAK` or `EVENING_PEAK` wave activation is rejected with `ERR_WEATHER_SUSPENDED` (HTTP 422). This ordering means a peak-window wave in a territory that is not `ACTIVE` reports `ERR_TERRITORY_NOT_ACTIVE` rather than any of the three safety codes, since territory posture is checked before the safety cluster.

Temporal and structural checks follow. A vehicle that already carries a depot cycle in `STAGED` or `IN_PROGRESS` blocks a new cycle start with `ERR_VEHICLE_IN_CYCLE` (HTTP 409), and a reservation whose bay window intersects an existing slot on that bay is rejected with `ERR_BAY_SLOT_CONFLICT` (HTTP 409). Curb access and location validity are evaluated together and reported as distinct codes per §2.8: `ERR_CURB_ACCESS_DENIED` or `ERR_LOCATION_INVALID`, both HTTP 422. State-transition validity is evaluated after all of these, and a transition attempted from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409). Pool exhaustion is evaluated last: a match that finds no candidate vehicle is rejected with `ERR_NO_VEHICLE_AVAILABLE` (HTTP 409), a bay-pool or wave-budget overrun with `ERR_CAPACITY_EXCEEDED` (HTTP 409), and a roadside case that finds no team with `ERR_NO_TEAM_AVAILABLE` (HTTP 409). Observe the consequence of this last position: a match against a territory in a non-`ACTIVE` posture reports `ERR_TERRITORY_NOT_ACTIVE`, never `ERR_NO_VEHICLE_AVAILABLE`, even though both would have fired.

The depot operations checkpoint is the system's heartbeat, and it is an explicit capability rather than a timer. A `DepotTechnician` runs it against a depot; the run advances that depot's `ops_run_index` by exactly one and then sweeps four things in the same execution.

The cycle SLA sweep closes out cycles that have stalled. Every `DepotCycle` in `STAGED` or `IN_PROGRESS` is examined against the depot's operations epoch: when the depot's current `ops_run_index` minus the cycle's `last_ops_run_index` is 2 or more, the cycle is abandoned — the vehicle under service returns to `DRAFT`, the cycle moves to `ABORTED`, and its bay slot moves to `RELEASED`. Two operations epochs is the entire allowance for a cycle, inclusive at the boundary. The assistance timeout sweep follows the same shape: any session that has been `ACKNOWLEDGED` across three depot operations runs is returned to `ESCALATED` with its `escalation_tier` raised by one and its `attempt_count` raised by one, as §3.5 sets out.

The third sweep refreshes a waiting-time counter rather than moving anything. A vehicle whose `status` is `AT_DEPOT` and which has not yet been re-deployed has its `delay_ops_runs` refreshed to reflect how many depot operations runs have elapsed while it sat staged and idle; the counter is what makes a stalled vehicle visible without changing its serviceability. The fourth action recomputes the depot's posture under §2.6 from the bay slots that are `RESERVED` or `ACTIVE` and whose windows contain the current logical clock.

Every one of those mutations obeys §2.4: each row that changes is refreshed with a new `updated_at` and its `version` advances by one, whether the change came from a client request or from this checkpoint's own sweep.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a territory, a depot, a vehicle, a bay slot, a cycle, a wave, an area rule, an exclusion zone, an expansion request, a ride, a pickup location, a curb rule, a response team, an assistance session, an incident report or a roadside case — return `201 Created`. Operations that modify an existing resource, including state transitions, approvals, retirements, checkpoint runs and reclassifications, return `200 OK`. The one exception to the mount convention is the logical clock setter, which is reachable at the server root rather than under the fleet prefix; the liveness probe and everything else live under `/fleet`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/fleet/health` | Liveness probe returning a fixed object envelope | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock used for every time comparison | Any |
| POST | `/fleet/territories` | Create a ServiceTerritory | TerritoryPlanner |
| GET | `/fleet/territories` | List ServiceTerritories with optional posture filter | Any |
| GET | `/fleet/territories/{territoryId}` | Get a ServiceTerritory | Any |
| POST | `/fleet/territories/{territoryId}/mapping-ticks` | Record an HD-mapping progress tick | MappingEngineer |
| POST | `/fleet/territories/{territoryId}/validation-runs` | Log supervised validation drive hours | MappingEngineer, SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/weather-tier-ticks` | Record the forecast weather tier for a service window | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/depots` | Create a DepotSite | TerritoryPlanner |
| GET | `/fleet/territories/{territoryId}/depots` | List DepotSites for a territory | Any |
| GET | `/fleet/depots` | List DepotSites across territories | Any |
| GET | `/fleet/depots/{depotId}` | Get a DepotSite | Any |
| GET | `/fleet/depots/{depotId}/vehicles` | List Vehicles currently staged at a depot | FleetOperations, DepotTechnician, TerritoryPlanner, SafetyReviewer |
| POST | `/fleet/depots/{depotId}/run-depot-ops` | Run the depot operations checkpoint | DepotTechnician |
| POST | `/fleet/depots/{depotId}/bay-slots` | Reserve a BaySlot for a service type and half-open window | DepotTechnician |
| GET | `/fleet/depots/{depotId}/bay-slots` | List BaySlots for a depot | FleetOperations, DepotTechnician |
| GET | `/fleet/bay-slots` | List BaySlots across depots | Any |
| GET | `/fleet/bay-slots/{baySlotId}` | Get a BaySlot | FleetOperations, DepotTechnician |
| POST | `/fleet/depots/{depotId}/bay-slots/{baySlotId}/release` | Release a reserved BaySlot | DepotTechnician |
| POST | `/fleet/territories/{territoryId}/vehicles` | Register a Vehicle | FleetOperations |
| GET | `/fleet/territories/{territoryId}/vehicles` | List Vehicles for a territory | FleetOperations, DepotTechnician, RemoteAssistanceOperator, TerritoryPlanner, SafetyReviewer |
| GET | `/fleet/vehicles` | List Vehicles across territories | Any |
| GET | `/fleet/vehicles/{vehicleId}` | Get a Vehicle | FleetOperations, DepotTechnician, RemoteAssistanceOperator, TerritoryPlanner, SafetyReviewer |
| POST | `/fleet/vehicles/{vehicleId}/stage` | Stage a Vehicle at a depot | FleetOperations, DepotTechnician |
| POST | `/fleet/vehicles/{vehicleId}/return-to-service` | Return a service-ready Vehicle to service | FleetOperations |
| POST | `/fleet/vehicles/{vehicleId}/suspend` | Suspend a staged Vehicle | SafetyReviewer |
| POST | `/fleet/vehicles/{vehicleId}/clear-suspension` | Clear a suspension | SafetyReviewer |
| GET | `/fleet/vehicles/{vehicleId}/assistance-sessions` | List AssistanceSessions opened for a vehicle | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| POST | `/fleet/depots/{depotId}/cycles` | Create an unscheduled DepotCycle | DepotTechnician |
| GET | `/fleet/depots/{depotId}/cycles` | List DepotCycles for a depot | FleetOperations, DepotTechnician |
| GET | `/fleet/cycles` | List DepotCycles across depots | Any |
| GET | `/fleet/cycles/{cycleId}` | Get a DepotCycle | FleetOperations, DepotTechnician |
| POST | `/fleet/depots/{depotId}/cycles/{cycleId}/schedule` | Attach a reserved BaySlot to a cycle | DepotTechnician |
| POST | `/fleet/depots/{depotId}/cycles/{cycleId}/start` | Start a scheduled cycle | DepotTechnician |
| POST | `/fleet/depots/{depotId}/cycles/{cycleId}/complete` | Complete a cycle and apply its service effect | DepotTechnician |
| POST | `/fleet/depots/{depotId}/cycles/{cycleId}/abort` | Abort a cycle | DepotTechnician |
| POST | `/fleet/territories/{territoryId}/demand-signals` | Upsert the DemandSignal for a window code | TerritoryPlanner |
| GET | `/fleet/territories/{territoryId}/demand-signals` | List DemandSignals for a territory | FleetOperations, TerritoryPlanner |
| GET | `/fleet/demand-signals` | List DemandSignals across territories | Any |
| GET | `/fleet/demand-signals/{signalId}` | Get a DemandSignal by id | Any |
| POST | `/fleet/territories/{territoryId}/deployment-waves` | Plan a DeploymentWave for a window code | TerritoryPlanner |
| GET | `/fleet/territories/{territoryId}/deployment-waves` | List DeploymentWaves for a territory | FleetOperations, TerritoryPlanner |
| GET | `/fleet/deployment-waves` | List DeploymentWaves across territories | Any |
| GET | `/fleet/deployment-waves/{waveId}` | Get a DeploymentWave by id | Any |
| POST | `/fleet/territories/{territoryId}/deployment-waves/{waveId}/activate` | Activate a planned wave | TerritoryPlanner |
| POST | `/fleet/territories/{territoryId}/deployment-waves/{waveId}/dispatch` | Dispatch a wave's vehicles into service | TerritoryPlanner |
| POST | `/fleet/territories/{territoryId}/deployment-waves/{waveId}/abort` | Abort a wave | TerritoryPlanner |
| POST | `/fleet/territories/{territoryId}/area-rules` | Create a ServiceAreaRule | MappingEngineer |
| GET | `/fleet/territories/{territoryId}/area-rules` | List ServiceAreaRules for a territory | FleetOperations, MappingEngineer, SafetyReviewer |
| GET | `/fleet/area-rules` | List ServiceAreaRules across territories | Any |
| GET | `/fleet/area-rules/{ruleId}` | Get a ServiceAreaRule by id | Any |
| POST | `/fleet/territories/{territoryId}/area-rules/{ruleId}/approve` | Approve a ServiceAreaRule and bump its rule version | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/area-rules/{ruleId}/retire` | Retire a ServiceAreaRule | MappingEngineer |
| POST | `/fleet/territories/{territoryId}/exclusion-zones` | Schedule an ExclusionZone for a route class | SafetyReviewer, MappingEngineer |
| GET | `/fleet/territories/{territoryId}/exclusion-zones` | List ExclusionZones for a territory | FleetOperations, MappingEngineer, SafetyReviewer, TerritoryPlanner |
| GET | `/fleet/exclusion-zones` | List ExclusionZones across territories | Any |
| GET | `/fleet/exclusion-zones/{zoneId}` | Get an ExclusionZone by id | Any |
| POST | `/fleet/territories/{territoryId}/exclusion-zones/{zoneId}/activate` | Activate an exclusion zone | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/expansion-requests` | Submit a ServiceAreaExpansionRequest | TerritoryPlanner |
| GET | `/fleet/territories/{territoryId}/expansion-requests` | List expansion requests for a territory | TerritoryPlanner, SafetyReviewer, MappingEngineer |
| GET | `/fleet/expansion-requests` | List expansion requests across territories | Any |
| GET | `/fleet/expansion-requests/{expansionId}` | Get a ServiceAreaExpansionRequest | TerritoryPlanner, SafetyReviewer, MappingEngineer |
| POST | `/fleet/expansion-requests/{expansionId}/mapping-complete` | Mark the expansion's mapping gate complete | MappingEngineer |
| POST | `/fleet/expansion-requests/{expansionId}/approve` | Approve an expansion and pin the territory rule version | SafetyReviewer |
| POST | `/fleet/expansion-requests/{expansionId}/reject` | Reject an expansion | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/ride-requests` | Create an idempotent RideRequest | FleetOperations |
| GET | `/fleet/territories/{territoryId}/ride-requests` | List RideRequests for a territory | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| GET | `/fleet/ride-requests` | List RideRequests across territories | Any |
| GET | `/fleet/ride-requests/{rideId}` | Get a RideRequest by id | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| GET | `/fleet/territories/{territoryId}/ride-requests/{rideId}` | Get a RideRequest | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/match` | Match a ride to a vehicle via the selector | FleetOperations |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/pickup` | Confirm pickup | FleetOperations |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/complete` | Complete a ride | FleetOperations |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/cancel` | Cancel a ride | FleetOperations |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/cancel-no-show` | Mark a no-show | FleetOperations |
| POST | `/fleet/territories/{territoryId}/pickup-locations` | Create a PickupLocation for a curb segment | MappingEngineer |
| GET | `/fleet/territories/{territoryId}/pickup-locations` | List PickupLocations for a territory | FleetOperations, MappingEngineer, RemoteAssistanceOperator |
| GET | `/fleet/pickup-locations` | List PickupLocations across territories | Any |
| GET | `/fleet/pickup-locations/{pickupLocationId}` | Get a PickupLocation | FleetOperations, MappingEngineer, RemoteAssistanceOperator |
| GET | `/fleet/pickup-locations/{pickupLocationId}/ride-requests` | List RideRequests using a curb as pickup or dropoff | FleetOperations, RemoteAssistanceOperator |
| POST | `/fleet/pickup-locations/{pickupLocationId}/reclassify` | Reclassify a curb segment | MappingEngineer |
| POST | `/fleet/territories/{territoryId}/curb-rules` | Create a CurbRule | SafetyReviewer |
| GET | `/fleet/territories/{territoryId}/curb-rules` | List CurbRules for a territory | FleetOperations, SafetyReviewer, MappingEngineer |
| GET | `/fleet/curb-rules` | List CurbRules across territories | Any |
| GET | `/fleet/curb-rules/{curbRuleId}` | Get a CurbRule by id | Any |
| POST | `/fleet/territories/{territoryId}/curb-rules/{curbRuleId}/retire` | Retire a CurbRule | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/ride-requests/{rideId}/assistance-sessions` | Escalate a ride to remote assistance | RemoteAssistanceOperator, FleetOperations |
| GET | `/fleet/assistance-sessions` | List AssistanceSessions | RemoteAssistanceOperator, FleetOperations, SafetyReviewer |
| GET | `/fleet/assistance-sessions/{sessionId}` | Get an AssistanceSession | RemoteAssistanceOperator, FleetOperations, SafetyReviewer |
| GET | `/fleet/ride-requests/{rideId}/assistance-sessions` | List the AssistanceSessions for a ride | RemoteAssistanceOperator, FleetOperations, SafetyReviewer |
| POST | `/fleet/assistance-sessions/{sessionId}/acknowledge` | Acknowledge an escalated session | RemoteAssistanceOperator |
| POST | `/fleet/assistance-sessions/{sessionId}/resolve` | Resolve an acknowledged session | RemoteAssistanceOperator |
| POST | `/fleet/assistance-sessions/{sessionId}/escalate-unresolved` | Mark a session unresolvable | RemoteAssistanceOperator |
| POST | `/fleet/ride-requests/{rideId}/film-incident` | File an incident report against the ride's current vehicle | RemoteAssistanceOperator, SafetyReviewer |
| GET | `/fleet/incident-reports` | List IncidentReports | SafetyReviewer, FleetOperations |
| GET | `/fleet/incident-reports/{incidentId}` | Get an IncidentReport with its computed retention fields | SafetyReviewer, FleetOperations |
| GET | `/fleet/assistance-sessions/{sessionId}/incident-reports` | List IncidentReports filed from an assistance session | SafetyReviewer, FleetOperations |
| POST | `/fleet/incident-reports/{incidentId}/begin-review` | Move a report into review | SafetyReviewer |
| POST | `/fleet/incident-reports/{incidentId}/close` | Close a reviewed report | SafetyReviewer |
| POST | `/fleet/incident-reports/{incidentId}/void` | Void a filed report | SafetyReviewer |
| POST | `/fleet/territories/{territoryId}/roadside-teams` | Register a RoadsideTeam | FleetOperations |
| GET | `/fleet/territories/{territoryId}/roadside-teams` | List RoadsideTeams for a territory | FleetOperations, RemoteAssistanceOperator |
| GET | `/fleet/roadside-teams` | List RoadsideTeams across territories | Any |
| GET | `/fleet/roadside-teams/{teamId}` | Get a RoadsideTeam | FleetOperations, RemoteAssistanceOperator |
| GET | `/fleet/roadside-teams/{teamId}/roadside-cases` | List RoadsideCases assigned to a response team | FleetOperations, RemoteAssistanceOperator |
| POST | `/fleet/territories/{territoryId}/roadside-teams/{teamId}/mark-off-shift` | Take a team off shift | FleetOperations |
| POST | `/fleet/vehicles/{vehicleId}/roadside-cases` | Open a RoadsideCase and assign a response team | FleetOperations, RemoteAssistanceOperator |
| GET | `/fleet/territories/{territoryId}/roadside-cases` | List RoadsideCases for a territory | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| GET | `/fleet/roadside-cases` | List RoadsideCases across territories | Any |
| GET | `/fleet/roadside-cases/{caseId}` | Get a RoadsideCase | FleetOperations, RemoteAssistanceOperator, SafetyReviewer |
| GET | `/fleet/assistance-sessions/{sessionId}/roadside-cases` | List RoadsideCases opened from an assistance session | FleetOperations, RemoteAssistanceOperator |
| POST | `/fleet/roadside-cases/{caseId}/dispatch` | Dispatch the assigned team | FleetOperations |
| POST | `/fleet/roadside-cases/{caseId}/clear` | Clear a dispatched case and release the vehicle | FleetOperations |
| POST | `/fleet/roadside-cases/{caseId}/cancel` | Cancel an undispatched case | FleetOperations |

## 5. Error Code Catalogue

Trigger conditions for every one of these codes are stated in the narrative of §2 and §3; this table supplies only the identifiers and their status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_EXCLUSION_ZONE_ACTIVE` | 422 Unprocessable Entity |
| `ERR_WEATHER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_CURB_ACCESS_DENIED` | 422 Unprocessable Entity |
| `ERR_LOCATION_INVALID` | 422 Unprocessable Entity |
| `ERR_VEHICLE_IN_CYCLE` | 409 Conflict |
| `ERR_VEHICLE_NOT_SERVICE_READY` | 409 Conflict |
| `ERR_VEHICLE_ROADSIDE_BLOCKED` | 409 Conflict |
| `ERR_VEHICLE_HAS_ACTIVE_CYCLE` | 409 Conflict |
| `ERR_BAY_SLOT_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_POSTURE_LOCKDOWN` | 409 Conflict |
| `ERR_TERRITORY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ZONE_BLOCKED_WAVE` | 409 Conflict |
| `ERR_NO_VEHICLE_AVAILABLE` | 409 Conflict |
| `ERR_NO_TEAM_AVAILABLE` | 409 Conflict |
| `ERR_TEAM_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RESPONSE_SLA_BREACHED` | 409 Conflict |
| `ERR_CALIBRATION_SIGNOFF_REQUIRED` | 400 Bad Request |
| `ERR_MAX_ATTEMPTS_NOT_REACHED` | 409 Conflict |
| `ERR_SESSION_TERMINAL` | 409 Conflict |
| `ERR_CROSS_TERRITORY` | 409 Conflict |