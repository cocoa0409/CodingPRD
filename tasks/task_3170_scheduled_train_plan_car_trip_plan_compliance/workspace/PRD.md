# Scheduled Train Plan Compliance API — Product Requirements Document

## 1. Introduction

Railroad service quality lives or dies on two documents: the scheduled train plan, which promises when and where trains run, and the car trip plan, which promises each shipment an itinerary of connections across the network. This document specifies the Scheduled Train Plan & Car Trip Plan Compliance API, a system that operationalizes both documents and measures the network against them. A `NetworkPlanner` authors train plans specifying scheduled departures and cutoff times; a `TerminalSuperintendent` operates departures and records car movements; the system continuously measures terminal dwell, car velocity, and connection outcomes against the plan and raises exceptions the moment reality diverges.

The compliance program this API supports is deliberately closed-loop. Yards carry a derived posture that degrades as terminal dwell accumulates beyond benchmark, and that posture in turn gates new shipment acceptance, trip-plan assignment, and departure operation. Missed connections cascade through an itinerary automatically, customer service credits accrue when last-mile commitments are broken, and hours-of-service law constrains which crews may be booked. All deadlines, arrival evaluations, and dwell measurements are anchored to a server-owned logical clock so that every rule in this document is deterministic and testable.

The API is mounted under `/rail` and serves five operator roles with clearly separated resource ownership: network design, crew administration, power distribution, terminal operations, and customer service management.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational role. The system recognizes six role names with exact spelling: `NetworkPlanner`, `CrewDispatcher`, `PowerPlanner`, `TerminalSuperintendent`, `ServiceManager`, and `Any`. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

All six roles have an `identity` of the opaque form: `X-User-ID` is an opaque operator identifier not tied to any persisted entity for `NetworkPlanner`, `CrewDispatcher`, `PowerPlanner`, `TerminalSuperintendent`, `ServiceManager`, and `Any` alike. The server never compares `X-User-ID` against any resource's `id` for ownership; role alone governs authorization.

Resource ownership by role is as follows. A `NetworkPlanner` owns the logical clock, yard registration, train plan design/activation/retirement, and trip-plan assignment and replanning. A `CrewDispatcher` owns crew pools: opening them, replenishing exhausted pools, and closing pools at end of service day. A `PowerPlanner` owns locomotive registration and the bad-order lifecycle. A `TerminalSuperintendent` owns scheduling, finalizing, and cancelling departures, and records every car movement event. A `ServiceManager` owns customer registration, service-credit adjustment, shipment creation and cancellation, and exception triage and resolution. The `Any` role token is accepted on every GET endpoint; when `X-User-Role` is `Any`, `X-User-ID` may be any operator identifier. Every GET endpoint is declared with authorized role `Any`, and the authorization layer maps every authenticated role — the five business roles plus `Any` itself — onto read access.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — yards, train plans, crew pools, locomotives, customers, shipments, trip legs, departures, and service exceptions — carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is a system-managed integer that increments by exactly one on every mutation to the resource, including mutations driven by system cascades such as posture recomputation, replan supersession, or departure finalization.

Car events are the single exception: as an append-only event log, a car event carries only `id` and `created_at` beyond its declared fields; both `updated_at` and `version` are absent from car event resources.

### 2.5. The Logical Clock

All temporal rules in this document — departure earliness, dwell measurement, pickup and delivery commitment checks, connection windows, and exception timestamps — read a single server-owned logical clock. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `NetworkPlanner` advances the clock through an admin-only test-driving capability by supplying a `current_utc` instant; the capability returns the new `current_utc` and, as a side effect, recomputes every yard's posture, because open dwell sessions accrue overage against the new current instant. Exception records stamp `detected_at` from this clock, and car events are required to match it (see §3.6).

### 2.6. Derived Yard Posture and Congestion Gating

Every yard carries a derived `posture` in the band set `OPEN`, `CONGESTED`, or `EMBARGOED`, alongside a derived `current_dwell_overage_hours`. Posture is not a lifecycle — a yard has no terminal state — and no client endpoint sets it directly. It is recomputed by the system after every car event recorded at that yard, and again whenever the logical clock advances, from the aggregate dwell overage of cars currently dwelling there (the aggregation rule itself is specified in §3.6). Posture is a hard gate on network intake and operation: shipment creation is forbidden when the origin or destination yard is `EMBARGOED`, trip-plan assignment is forbidden when any leg endpoint yard is `EMBARGOED`, and departure finalization is forbidden when the origin yard is `EMBARGOED` — all three rejections carry `ERR_YARD_EMBARGOED` (HTTP 409). A yard begins life `OPEN` with zero overage.

### 2.7. Optimistic Concurrency Control

Three write operations require optimistic concurrency control against a parent resource's `version`; each names its version field explicitly, and the field is non-optional on those requests.

- Activation of a train plan requires `expected_train_plan_version`, carrying the client's last observed `version` of the plan. If another writer has advanced the plan's version since that read — by a successful activation or retirement — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the plan is stale and must be re-read.
- Retirement of a train plan likewise requires `expected_train_plan_version` matching the plan's current `version`; a mismatch means another mutation (activation, or a prior retirement) has already advanced the plan, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Trip-plan assignment or replanning for a shipment requires `expected_shipment_version` matching the shipment's current `version`. If the shipment's version has advanced since the client last read it — a prior replan, or a compliance-relevant cascade such as a missed connection — the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing an itinerary designed for a stale shipment from overwriting the current one.

Endpoints not listed above do not take a version field of any kind.

### 2.8. Numeric Precision and Schedule Constants

All velocity, dwell, and overage figures are computed and stored to 4 decimal places using round-half-up rounding. Connection-window slack is computed in whole minutes, truncated toward zero. Service-credit balances are whole integer units, never fractional. Two network-wide schedule constants apply: scheduled transit speed for every train plan is 25.0 miles per hour, and the hours-of-service maximum for a single crew assignment is 12.0 hours. A departure more than 30 minutes behind schedule raises delay exceptions (see §3.5).

### 2.9. Referenced-Resource Existence and Validation Ordering

Every path and body identifier that references a resource — yards, train plans, crew pools, locomotives, customers, shipments, trip legs, departures, exceptions — is validated for existence, and references are checked left-to-right in the order they appear in the request, so a request naming a nonexistent yard and a nonexistent plan is rejected for the yard first. Existence failures surface as the resource-specific identifiers `ERR_YARD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_LEG_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, and `ERR_EXCEPTION_NOT_FOUND` (each HTTP 404).

When several validations could reject the same request, the server applies them in a fixed priority order, and the client observes only the earliest failing check. The order is: first, header presence and role recognition; second, role authorization for the endpoint; third, referenced-resource existence, evaluated left-to-right; fourth, optimistic-concurrency version match; fifth, source-state legality of the transition; sixth, structural integrity of trip plans and same-origin/destination checks; seventh, car-event sequence integrity; eighth, hours-of-service and crew availability at finalize; ninth, yard-embargo gating; tenth, the first-mile pickup window; eleventh, resource positioning, craft, operating-day, and occupancy constraints; and twelfth, the service-credit non-negativity floor. Because embargo gating (priority 9) sits ahead of the pickup window (priority 10), an itinerary assignment through an embargoed yard after the pickup deadline surfaces `ERR_YARD_EMBARGOED`, not `ERR_PICKUP_WINDOW_MISSED`; similarly, a stale `expected_shipment_version` (priority 4) surfaces `ERR_STALE_VERSION` before any trip-plan structural defect (priority 6) is reported as `ERR_TRIP_PLAN_DISJOINT`.

### 2.10. Malformed Requests

Bodies that are malformed, missing a required field, carrying an invalid enum value, or supplying a non-positive number where a positive value is required are rejected with `ERR_INVALID_REQUEST` (HTTP 400). This includes a replenishment request whose `additional_crews` is less than 1, and a triage request missing `triage_notes` or `root_cause_code`.

## 3. Business Logic & Workflows

### 3.1. Designing and Activating the Train Plan

A `NetworkPlanner` designs a **train plan** by supplying its `train_symbol` (a unique identifier such as "MNPRV-14"), the `origin_yard_id` and `destination_yard_id` of the two yards it connects, its `scheduled_departure_utc`, the `cutoff_minutes` by which cars must arrive ahead of departure to make the train (at least 1 minute), a `frequency_mask` naming the operating days as a non-empty subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`, the `route_distance_miles` of the run (greater than 0), and the `dwell_benchmark_hours` the plan enforces at its origin and destination yards (zero or greater). Origin and destination must differ; a plan naming the same yard for both is rejected with `ERR_SAME_ORIGIN_DESTINATION` (HTTP 422). A new plan is born in `DRAFT` status.

Activation moves a plan from `DRAFT` to `ACTIVE` and is the network planner's commitment that the schedule is publishable; activating a plan not in `DRAFT` is rejected with `ERR_PLAN_NOT_DRAFT` (HTTP 409), and the activation carries the OCC field described in §2.7. Activation increments the plan's `version` by one.

Retirement moves an `ACTIVE` plan to its terminal state `RETIRED`. Retirement is refused with `ERR_PLAN_NOT_ACTIVE` if the plan is not `ACTIVE`, with `ERR_PLAN_HAS_OPEN_DEPARTURES` (HTTP 409) if any departure in `SCHEDULED` status still references the plan, and with `ERR_PLAN_IN_USE` (HTTP 409) if any trip leg in `PLANNED` or `EN_ROUTE` status still rides it; it too carries the OCC version field and increments `version` by one on success.

Train plans are listable with optional filters on `origin_yard_id`, `destination_yard_id`, and `status`, alongside the standard `limit` and `offset` pagination parameters.

### 3.2. Yards, Classification Capacity, and Posture Derivation

A `NetworkPlanner` registers each yard with a unique `yard_code` (for example "NPL" for North Platte), a `dwell_benchmark_hours` benchmark for terminal dwell (greater than 0), and the `classification_capacity_cars` the yard can classify per day (at least 1 car). Yard posture bands are defined by strictly-greater boundaries against the yard's own benchmark: with B standing for `dwell_benchmark_hours`, aggregate overage up to and including B keeps the yard `OPEN`; overage strictly above B and up to and including twice B moves it to `CONGESTED`; overage strictly above twice B moves it to `EMBARGOED`. Recovery is symmetric: an `EMBARGOED` yard returns to `CONGESTED` once overage falls back to strictly above B but at most twice B, and either congested or embargoed yards return to `OPEN` once overage is at most B. An `OPEN` yard can also jump directly to `EMBARGOED` when overage crosses twice the benchmark in a single recompute. The exact boundary semantics matter: overage equal to the benchmark exactly stays `OPEN`, and overage equal to twice the benchmark exactly stays `CONGESTED`.

The embargo consequences described in §2.6 make posture operationally expensive, so yard design is a deliberate act: the benchmark a planner registers is simultaneously the congestion tripwire and the dwell target the plan literature advertises.

### 3.3. Crew Pools and the Service-Day Epoch

A `CrewDispatcher` opens a **crew pool** for one home yard, one craft, and one service day by supplying `home_yard_id`, `craft` (either `CONDUCTOR` or `ENGINEER`), `service_date` in `YYYY-MM-DD` form (a pool covers exactly one calendar day), and `crews_available` (at least 1). The pool opens in `OPEN` status with `crews_booked` at zero; crews are committed from the pool only when departures finalize (§3.5), and `crews_booked` always reflects crews currently committed — booked minus released.

When a booking leaves `crews_booked` equal to `crews_available`, the system flips the pool to `EXHAUSTED` automatically, whether it was `OPEN` or `REOPENED`. A dispatcher restores an exhausted pool by replenishing it with `additional_crews`; replenishment requires the pool to be `EXHAUSTED` (otherwise `ERR_POOL_NOT_REPLENISHABLE`, HTTP 409) and a positive crew count (otherwise `ERR_INVALID_REQUEST`), adds the additional crews to `crews_available`, moves the pool to `REOPENED`, and increments its `version`.

At end of service day the dispatcher closes the pool, moving it from `OPEN` or `REOPENED` to the terminal `CLOSED` state and incrementing `version`. Closing is refused with `ERR_POOL_ALREADY_CLOSED` (HTTP 409) when the pool is not in `OPEN` or `REOPENED`, and with `ERR_POOL_HAS_BOOKED_CREWS` (HTTP 409) while any crews remain committed. Crew pools are listable with filters on `home_yard_id`, `craft`, `service_date`, and `status`.

### 3.4. Locomotive Positioning and the Bad-Order Lifecycle

A `PowerPlanner` registers each locomotive with its unique `unit_number` (for example "UP 8821"), the `current_yard_id` where the unit is positioned, and its rated `horsepower` (at least 1000). A registered unit is `AVAILABLE`. Scheduling a departure consumes the unit into `ASSIGNED`; finalization of that departure repositions the unit by setting its `current_yard_id` to the train plan's destination yard and returns it to `AVAILABLE`, while cancelling the departure returns it to `AVAILABLE` still at the origin. A power planner may mark an `AVAILABLE` unit bad-order, moving it to `BAD_ORDER` (a unit not `AVAILABLE` is rejected with `ERR_UNIT_NOT_AVAILABLE`, HTTP 409), and later release it from repair back to `AVAILABLE` (a unit not `BAD_ORDER` is rejected with `ERR_UNIT_NOT_BAD_ORDER`, HTTP 409). Locomotives are listable with filters on `current_yard_id` and `status`. The cyclic `AVAILABLE → ASSIGNED → AVAILABLE` flow and the `AVAILABLE → BAD_ORDER → AVAILABLE` repair loop have no terminal state — power is never retired in this system.

### 3.5. Operating Departures: Scheduling, Finalization, Cancellation

A `TerminalSuperintendent` schedules a departure from an `ACTIVE` train plan by naming the `train_plan_id`, a `service_date`, the `crew_pool_id` to draw crew from, the lead `locomotive_id`, the `car_count_planned` (at least 1), and `crew_hours_estimated` for the run (greater than 0). Scheduling validates positioning and eligibility: the plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`); the locomotive must be `AVAILABLE` (otherwise `ERR_UNIT_NOT_AVAILABLE`) and positioned at the plan's origin yard, meaning the unit's `current_yard_id` equals the plan's `origin_yard_id` (otherwise `ERR_UNIT_WRONG_YARD`, HTTP 409); the named pool's `craft` must be `CONDUCTOR` and its `home_yard_id` must equal the plan's origin yard (otherwise `ERR_POOL_CRAFT_MISMATCH`, HTTP 409); and the `service_date` must be an operating day under the plan's `frequency_mask` (otherwise `ERR_DEPARTURE_DAY_NOT_OPERATED`, HTTP 409). A scheduled departure sits in `SCHEDULED` status with the locomotive flipped to `ASSIGNED`; no crew is consumed at scheduling time — the pool is committed only at finalization.

Finalization operates the train. Finalizing a departure not in `SCHEDULED` is rejected with `ERR_DEPARTURE_NOT_FINALIZABLE` (HTTP 409), and the plan must still be `ACTIVE`. The crew gate then applies in full: the named pool must be in `OPEN` or `REOPENED` with `crews_booked` strictly below `crews_available` — an `EXHAUSTED` or `CLOSED` pool, or a fully booked one, is rejected with `ERR_NO_CREW_AVAILABLE` (HTTP 422) — and `crew_hours_estimated` must not exceed the 12.0-hour hours-of-service maximum, with a strictly-greater comparison: an estimate of exactly 12.0 hours is allowed, anything above it is rejected with `ERR_HOS_EXCEEDED` (HTTP 422). The origin yard must not be `EMBARGOED`. Finally, the logical clock must have reached the plan's `scheduled_departure_utc`; an early finalize is rejected with `ERR_DEPARTURE_TOO_EARLY` (HTTP 409).

A successful finalize stamps `actual_departure_utc` from the logical clock, computes `departure_variance_minutes` as actual minus scheduled in whole minutes (positive values mean late), moves the departure to `DEPARTED`, increments its `version`, and books one crew from the pool (`crews_booked` increases by one, which may flip the pool `OPEN` or `REOPENED` to `EXHAUSTED`). The lead locomotive repositions to the destination yard and becomes `AVAILABLE` again. If the variance exceeds 30 minutes, the system raises a `ServiceException` of type `DEPARTURE_DELAY` against every shipment holding a `PLANNED` leg on this plan, and each such shipment's `compliance_status` degrades from `ON_PLAN` to `AT_RISK` (a shipment already `AT_RISK` stays `AT_RISK`). Simultaneously, every `PLANNED` trip leg riding this plan whose planned departure matches this departure's slot — with its shipment in `OPEN` or `IN_TRANSIT` — advances to `EN_ROUTE` and stamps its own `actual_departure_utc` from the departure. Departures are listable with filters on `train_plan_id`, `crew_pool_id`, `locomotive_id`, `service_date`, and `status`.

Cancellation of a `SCHEDULED` departure (a non-`SCHEDULED` one is again `ERR_DEPARTURE_NOT_FINALIZABLE`) moves it to `CANCELLED`, increments its `version`, releases the locomotive back to `AVAILABLE` at the origin yard, and leaves the crew pool untouched — no booking was ever consumed. Every `PLANNED` trip leg whose `planned_departure_utc` matches this departure's slot instead misses: each such leg moves to `MISSED` and the full missed-connection cascade of §3.7 fires per leg.

### 3.6. Car Events, Dwell, and Posture Recomputation

A `TerminalSuperintendent` records every physical car movement as a **car event**, supplying the `shipment_id`, the `yard_id` where the event occurred, an `event_type` of `TRAIN_DEPARTURE`, `YARD_ARRIVAL`, `CLASSIFICATION_COMPLETE`, or `PLACED_DELIVERED`, the `occurred_at` instant, and the `car_count` covered (at least 1 and no more than the shipment's own `car_count`). Two integrity rules are enforced at recording time: `occurred_at` must equal the logical clock exactly, and the event sequence must be coherent — an outbound event (`TRAIN_DEPARTURE`, or `CLASSIFICATION_COMPLETE`) with no open `YARD_ARRIVAL` for that shipment at that yard, an event recorded against a shipment already in a terminal state (`DELIVERED` or `CANCELLED`), a clock mismatch, or a car count exceeding the shipment's remaining cars is rejected with `ERR_EVENT_SEQUENCE_INVALID` (HTTP 409). Car events are append-only and carry no `updated_at` or `version` (§2.4). They are listable network-wide with filters on `shipment_id`, `yard_id`, and `event_type`, per-yard through the yard's event listing, and per-shipment through the shipment's event history.

Each event drives the yard's dwell accounting. A shipment's cars begin a **dwell session** at a yard when a `YARD_ARRIVAL` is recorded there; the session closes when the first outbound event — a `TRAIN_DEPARTURE` or a `CLASSIFICATION_COMPLETE` — is recorded for that shipment at that yard, whichever comes first. A `PLACED_DELIVERED` event also closes any open dwell at that yard. The dwell time of one such session is the elapsed hours from the arrival event's `occurred_at` to the outbound event's `occurred_at`, computed at 4-decimal precision. When multiple events share a timestamp, ordering ties break by `created_at` ascending.

The yard's `current_dwell_overage_hours` aggregates every open dwell session at the yard — shipments with a `YARD_ARRIVAL` recorded and no matching outbound or delivery event yet. For each open session, the session's overage is the elapsed hours from its arrival to the current logical-clock instant minus the yard's `dwell_benchmark_hours`, floored at zero so a session inside its benchmark contributes nothing. The yard's overage is the sum of these session overages, itself floored at zero, expressed at 4-decimal precision. Posture then follows the band mapping of §3.2, recomputed after every event at the yard and after every clock advance.

Car events also drive the shipment lifecycle directly. The first `TRAIN_DEPARTURE` event recorded for a shipment flips it from `OPEN` to `IN_TRANSIT`. A `YARD_ARRIVAL` completes the `EN_ROUTE` leg whose train's destination is that yard (§3.7) and immediately evaluates the next leg's connection window. A `PLACED_DELIVERED` at the shipment's destination yard completes the shipment once the cumulative delivered car count there reaches the shipment's full `car_count` (§3.8).

### 3.7. Trip-Plan Assignment, Connection Windows, and Miss Cascades

A `NetworkPlanner` assigns a shipment's full itinerary by submitting `expected_shipment_version` together with the complete `legs` list. Each leg names its `train_plan_id` and a 1-based `leg_sequence`; the legs of a shipment must form a contiguous sequence from 1 to N with no gaps or duplicates. The itinerary must be structurally whole: consecutive legs chain, meaning the destination yard of leg k's train equals the origin yard of leg k+1's train; the first leg's train must originate at the shipment's `origin_yard_id`; and the last leg's train must terminate at the shipment's `destination_yard_id`. Any break in this chain — non-contiguous sequence numbers, a yard mismatch between consecutive legs, or endpoints that fail to meet the shipment's own origin and destination — is rejected with `ERR_TRIP_PLAN_DISJOINT` (HTTP 422). Assignment is additionally gated by embargo (any leg endpoint yard `EMBARGOED` → `ERR_YARD_EMBARGOED`) and by the first-mile commitment: if the logical clock has passed the shipment's `first_mile_pickup_by` at assignment time, the request is rejected with `ERR_PICKUP_WINDOW_MISSED` (HTTP 409) and the shipment's `compliance_status` is stamped `OFF_PLAN` at that moment — the pickup miss is recorded even though no itinerary was accepted.

On a successful first assignment, each new leg is created in `PLANNED` status with `planned_departure_utc` pinned from its train plan's `scheduled_departure_utc`. The first leg's `planned_connection_time` is null — it has no inbound train — and its `connection_status` is set to `NOT_APPLICABLE`; every later leg's `planned_connection_time` equals its inbound train's scheduled arrival at the connection yard, which is the previous leg's train's scheduled arrival at its own destination, and its `connection_status` starts `PENDING`. The shipment's `trip_plan_status` moves from `UNASSIGNED` to `ASSIGNED`, its `version` increments by one, and the planned velocity of the itinerary is computed (below). The same endpoint replans: submitting a new itinerary supersedes every prior leg still in `PLANNED` or `MISSED` to `REPLACED`, stamps the shipment's `trip_plan_status` as `REPLANNED` when superseding a `MISSED_CONNECTION` itinerary, and recomputes planned velocity against the new horizon. Leg history is preserved — a shipment's leg listing returns all generations including `REPLACED` ones, and trip legs are also listable network-wide with filters on `shipment_id`, `train_plan_id`, `status`, and `connection_status`.

**Planned velocity** prices the itinerary before any wheel turns. Each train plan's scheduled transit time is its `route_distance_miles` divided by the fixed scheduled speed of 25.0 miles per hour; a leg's planned arrival is its pinned `planned_departure_utc` plus that transit time. The itinerary's total planned elapsed hours run from the first leg's `planned_departure_utc` to the last leg's planned arrival, and the plan velocity is the shipment's `committed_route_miles` divided by those total hours, at 4-decimal precision. At initial assignment this figure is purely provisional, using pinned schedule times only. On a replan after a missed connection, the first leg's departure is the new itinerary's first departure, so the same committed miles divided by a longer horizon yields a strictly lower planned velocity — the quantified cost of the miss, visible directly in the plan numbers.

**Connection windows** are evaluated when an inbound leg completes — that is, when a `YARD_ARRIVAL` car event for the shipment is recorded at the completed leg's train destination, moving that leg from `EN_ROUTE` to `COMPLETED`. If the completed leg is not the last, the system measures the slack at the connection yard: the minutes from the arrival event's `occurred_at` to the next leg's pinned `planned_departure_utc`, in whole minutes truncated toward zero. If the slack is strictly less than the next leg's train plan's `cutoff_minutes`, the next leg misses; slack exactly equal to the cutoff still makes the connection, and the next leg's `connection_status` is set to `MADE`. A leg also misses when its carrying departure is cancelled out from under it (§3.5), or when a departure for its train plan finalizes while the leg sat `EN_ROUTE` at the origin without departure coverage — the car simply was not on the outbound train.

A missed leg moves from `PLANNED` (or `EN_ROUTE`) to `MISSED`, its `connection_status` is set to `MISSED`, the shipment's `total_missed_connections` increments by one, and the shipment's `trip_plan_status` becomes `MISSED_CONNECTION`. The system raises a `ServiceException` of type `MISSED_CONNECTION` for the shipment with `detected_at` stamped from the logical clock. The miss then cascades: every later leg of the same shipment still in `PLANNED` moves to `MISSED` as well, each with `connection_status` `MISSED` by the same induction — a single missed connection poisons the remainder of the itinerary, which is exactly why replanning exists.

### 3.8. Delivery, Actual Velocity, and Service Credits

A shipment completes when a `PLACED_DELIVERED` car event at its destination yard brings the cumulative delivered car count there to the shipment's full `car_count`; the shipment moves from `IN_TRANSIT` to `DELIVERED`. Delivery prices reality: **actual car velocity** is the shipment's `committed_route_miles` divided by the observed elapsed hours from the first `TRAIN_DEPARTURE` event's `occurred_at` to the final completing `PLACED_DELIVERED` event's `occurred_at`, stored on the shipment as `car_velocity_mph` at 4-decimal precision. If departure and delivery happen at the same instant, the elapsed time is treated as one hour, so the velocity floor is the committed mileage itself. Because dwell and delay are fully priced into the observed timestamps, actual velocity lands below the planned velocity whenever any dwell or delay occurred — the plan-versus-actual gap this compliance program exists to surface.

A delivery whose completing event's `occurred_at` is later than the shipment's `last_mile_delivery_by` commitment is a broken promise: the shipment's `compliance_status` is set to `OFF_PLAN`, a `ServiceException` of type `DELIVERY_MISS` is raised, and the customer's `service_credit_balance` increases by the shipment's `car_count`. Credits are whole units, never fractional; partial-car deliveries accrue credit per delivered car only when the shipment as a whole reaches `DELIVERED`. A `ServiceManager` may also adjust a customer's balance directly by a signed `delta` — added to `service_credit_balance` — but no adjustment may drive the balance below zero; one that would is rejected with `ERR_CREDIT_BALANCE_NEGATIVE` (HTTP 422).

### 3.9. Shipments, Customers, and the Compliance Ledger

A `ServiceManager` registers a customer with a unique `customer_code` and a legal `name`; the customer's `service_credit_balance` starts at zero. Customers are listable, and each customer record exposes its credit balance.

Against a registered customer, the service manager creates a **shipment** by naming the `customer_id`, the `origin_yard_id` and `destination_yard_id` (which must differ, else `ERR_SAME_ORIGIN_DESTINATION`), the `car_count` (at least 1), the `first_mile_pickup_by` and `last_mile_delivery_by` commitment instants, and the `committed_route_miles` the trip plan must cover end-to-end (greater than 0). Creation is refused with `ERR_YARD_EMBARGOED` if either endpoint yard is `EMBARGOED`. A new shipment is `OPEN`, its `trip_plan_status` is `UNASSIGNED`, its `compliance_status` is `ON_PLAN`, `total_missed_connections` is zero, and `car_velocity_mph` is null until delivery. Shipments are listable with filters on `customer_id`, `origin_yard_id`, `destination_yard_id`, `status`, and `compliance_status`.

A shipment that has not yet departed may be cancelled by a `ServiceManager` — only an `OPEN` shipment is cancellable, otherwise `ERR_SHIPMENT_NOT_CANCELLABLE` (HTTP 409). Cancellation moves the shipment to `CANCELLED`, increments its `version`, and supersedes every one of its trip legs to `REPLACED` (all still `PLANNED`, since the shipment never departed).

**Compliance status** is derived per shipment from three inputs — its legs, its exceptions, and its commitment timestamps against the logical clock — and is recomputed on any leg state change, any exception raised for the shipment, and at delivery. A shipment is `OFF_PLAN` when any of three conditions holds: it was delivered late (the completing event's `occurred_at` later than `last_mile_delivery_by`); its first-mile pickup was missed, meaning the logical clock passed `first_mile_pickup_by` while the shipment was still `OPEN`, still `UNASSIGNED`, and without any `TRAIN_DEPARTURE` event — detected and stamped when a trip-plan assignment is attempted after the deadline (§3.7); or its `total_missed_connections` has reached 2 or more. Failing that, a shipment is `AT_RISK` when it has exactly one missed connection or any open `DEPARTURE_DELAY` exception against it. Otherwise the shipment is `ON_PLAN`.

### 3.10. Exception Triage and Service Recovery

Every service failure the system detects surfaces as a **service exception** carrying the affected `shipment_id`, an `exception_type` of `MISSED_CONNECTION`, `DWELL_OVERAGE`, `DEPARTURE_DELAY`, `PICKUP_MISS`, or `DELIVERY_MISS`, and a `detected_at` instant stamped from the logical clock. Exceptions are raised by the system itself — at a missed connection, at a late finalization's delay cascade, and at a late delivery — and begin in `OPEN` status. Exceptions are listable network-wide with filters on `shipment_id`, `exception_type`, and `status`, and per-shipment through the shipment's exception listing.

A `ServiceManager` begins investigation by triaging an `OPEN` exception (triaging one not `OPEN` is rejected with `ERR_EXCEPTION_NOT_OPEN`, HTTP 409), supplying non-empty `triage_notes` and a `root_cause_code` of `CREW_SHORTAGE`, `POWER_SHORTAGE`, `YARD_CONGESTION`, `CUSTOMER_DELAY`, or `OTHER`; a triage missing either field is rejected with `ERR_INVALID_REQUEST`. Triage moves the exception to `INVESTIGATING` and increments its `version`. Resolution moves an `INVESTIGATING` exception to the terminal `RESOLVED` state and again increments `version`; resolving one not under investigation is rejected with `ERR_EXCEPTION_NOT_INVESTIGATING` (HTTP 409). One recovery rule is absolute: a `MISSED_CONNECTION` exception cannot resolve until the shipment has been replanned — its `trip_plan_status` must be `ASSIGNED` or `REPLANNED` — otherwise the resolution is rejected with `ERR_EXCEPTION_NOT_RECOVERABLE` (HTTP 409). The recovery loop therefore runs through the network planner's replan before the service manager can close the file.

## 4. Endpoint Definitions

Operations that create new stand-alone resources (a yard, a train plan, a crew pool, a locomotive, a customer, a shipment, a departure, a car event) or assign a new itinerary generation return `201 Created`. Operations that modify an existing resource — activation, retirement, replenishment, closure, bad-order transitions, credit adjustment, cancellation, finalization, triage, resolution, and clock advancement — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rail/_clock/set_current_utc` | Advance the logical clock | NetworkPlanner |
| POST | `/rail/yards` | Register a yard | NetworkPlanner |
| GET | `/rail/yards` | List yards | Any |
| GET | `/rail/yards/{id}` | Get a yard (posture and current dwell overage) | Any |
| POST | `/rail/train-plans` | Design a train plan (DRAFT) | NetworkPlanner |
| GET | `/rail/train-plans` | List train plans | Any |
| GET | `/rail/train-plans/{id}` | Get a train plan | Any |
| POST | `/rail/train-plans/{id}/activate` | Activate a DRAFT plan (OCC) | NetworkPlanner |
| POST | `/rail/train-plans/{id}/retire` | Retire an ACTIVE plan (OCC; blocked by open departures/legs) | NetworkPlanner |
| POST | `/rail/crew-pools` | Open a crew pool for a home yard / craft / service date | CrewDispatcher |
| GET | `/rail/crew-pools` | List crew pools | Any |
| GET | `/rail/crew-pools/{id}` | Get a crew pool | Any |
| POST | `/rail/crew-pools/{id}/replenish` | Add crews to an EXHAUSTED pool (REOPENED) | CrewDispatcher |
| POST | `/rail/crew-pools/{id}/close` | Close a pool at end of service day (requires zero booked crews) | CrewDispatcher |
| POST | `/rail/locomotives` | Register a locomotive at a yard | PowerPlanner |
| GET | `/rail/locomotives` | List locomotives | Any |
| GET | `/rail/locomotives/{id}` | Get a locomotive | Any |
| POST | `/rail/locomotives/{id}/bad-order` | Mark a unit bad-order (out of service) | PowerPlanner |
| POST | `/rail/locomotives/{id}/release-repair` | Return a bad-order unit to service | PowerPlanner |
| POST | `/rail/customers` | Register a customer | ServiceManager |
| GET | `/rail/customers` | List customers | Any |
| GET | `/rail/customers/{id}` | Get a customer (includes service credit balance) | Any |
| POST | `/rail/customers/{id}/service-credits` | Adjust service-credit balance (signed delta; must not go negative) | ServiceManager |
| POST | `/rail/shipments` | Create a shipment (OPEN); forbidden through EMBARGOED yards | ServiceManager |
| GET | `/rail/shipments` | List shipments | Any |
| GET | `/rail/shipments/{id}` | Get a shipment | Any |
| POST | `/rail/shipments/{id}/cancel` | Cancel an OPEN shipment | ServiceManager |
| POST | `/rail/shipments/{id}/trip-legs` | Assign or replan the full itinerary (OCC on the shipment) | NetworkPlanner |
| GET | `/rail/shipments/{id}/trip-legs` | List a shipment's legs (all generations) | Any |
| GET | `/rail/trip-legs` | List trip legs network-wide, filterable | Any |
| GET | `/rail/trip-legs/{id}` | Get a trip leg | Any |
| POST | `/rail/train-departures` | Schedule a departure from an ACTIVE plan | TerminalSuperintendent |
| GET | `/rail/train-departures` | List departures | Any |
| GET | `/rail/train-departures/{id}` | Get a departure | Any |
| POST | `/rail/train-departures/{id}/finalize` | Operate the departure: HOS, crew, and embargo gates; fires cascades | TerminalSuperintendent |
| POST | `/rail/train-departures/{id}/cancel` | Cancel a SCHEDULED departure; releases the locomotive | TerminalSuperintendent |
| POST | `/rail/car-events` | Record a car movement event at the logical-clock instant | TerminalSuperintendent |
| GET | `/rail/car-events` | List car events (filterable) | Any |
| GET | `/rail/yards/{id}/car-events` | List car events recorded at a yard | Any |
| GET | `/rail/shipments/{id}/car-events` | List one shipment's event history | Any |
| GET | `/rail/service-exceptions` | List service exceptions | Any |
| GET | `/rail/shipments/{id}/service-exceptions` | List one shipment's exceptions | Any |
| GET | `/rail/service-exceptions/{id}` | Get a service exception | Any |
| POST | `/rail/service-exceptions/{id}/triage` | Begin investigation (requires notes and root cause) | ServiceManager |
| POST | `/rail/service-exceptions/{id}/resolve` | Resolve an investigated exception; MISSED_CONNECTION requires replan first | ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SAME_ORIGIN_DESTINATION` | 422 Unprocessable Entity |
| `ERR_YARD_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTURE_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEPTION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_HAS_OPEN_DEPARTURES` | 409 Conflict |
| `ERR_PLAN_IN_USE` | 409 Conflict |
| `ERR_POOL_NOT_REPLENISHABLE` | 409 Conflict |
| `ERR_POOL_ALREADY_CLOSED` | 409 Conflict |
| `ERR_POOL_HAS_BOOKED_CREWS` | 409 Conflict |
| `ERR_POOL_CRAFT_MISMATCH` | 409 Conflict |
| `ERR_NO_CREW_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_HOS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_UNIT_WRONG_YARD` | 409 Conflict |
| `ERR_UNIT_NOT_BAD_ORDER` | 409 Conflict |
| `ERR_DEPARTURE_DAY_NOT_OPERATED` | 409 Conflict |
| `ERR_DEPARTURE_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_DEPARTURE_TOO_EARLY` | 409 Conflict |
| `ERR_TRIP_PLAN_DISJOINT` | 422 Unprocessable Entity |
| `ERR_YARD_EMBARGOED` | 409 Conflict |
| `ERR_PICKUP_WINDOW_MISSED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_EVENT_SEQUENCE_INVALID` | 409 Conflict |
| `ERR_EXCEPTION_NOT_OPEN` | 409 Conflict |
| `ERR_EXCEPTION_NOT_INVESTIGATING` | 409 Conflict |
| `ERR_EXCEPTION_NOT_RECOVERABLE` | 409 Conflict |
| `ERR_CREDIT_BALANCE_NEGATIVE` | 422 Unprocessable Entity |
