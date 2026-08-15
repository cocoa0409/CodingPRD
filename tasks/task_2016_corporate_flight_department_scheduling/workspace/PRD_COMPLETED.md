# Corporate Flight Department Scheduling API — Product Requirements Document

## 1. Introduction

A corporate flight department lives at the intersection of executive service and regulatory bookkeeping. Executives expect a tail and a qualified crew to be ready when business demands it; the IRS expects every personal-use mile flown on the company aircraft to surface as imputed income under Standard Industry Fare Level rules; and the CFO expects every block minute to land on the right business unit's budget. When the owned fleet cannot cover a trip, the department buys charter capacity on the open market and still owes the same fiscal discipline. This document specifies an API that runs that entire operation: trip origination and approval, aircraft selection and crew pairing under strict legality rules, catering and ground-transport coordination per leg, maintenance and document-currency tracking per tail, charter supplementation, and a finance-driven settlement that computes SIFL imputed income and allocates cost.

All endpoints described here are mounted under the `/flight-ops` prefix. The system is organized as a dual-axis view of a trip — an approval dimension owned by department management and an assignment dimension owned by dispatch — with segregation-of-duties guarantees wherever money or personal-use governance is involved, and a server-owned logical clock that drives every time-sensitive rule in the document.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `ExecutiveRequester`, `Dispatcher`, `FlightDeptManager`, `MaintenancePlanner`, and `FinanceAdmin`. A request whose headers are missing — an empty `X-User-ID` value counts as missing — or whose declared role is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ExecutiveRequester`, `X-User-ID` is the `id` of the acting `PassengerProfile`; ownership checks on any resource that references a `PassengerProfile` compare the resource's foreign-key field to `X-User-ID` — most notably, a trip submission is only valid when the trip's `requester_id` equals the acting requester's header value. The ownership comparison is enforced at exactly three places: trip submission, trip cancellation by an `ExecutiveRequester`, and leg creation by an `ExecutiveRequester` — in each case evaluated once the path resources have resolved and before any body-schema validation, with a failed comparison rejected as `ERR_UNAUTHORIZED` (HTTP 403). Trip creation and all read endpoints apply no ownership comparison. When `X-User-Role` is `Dispatcher`, `FlightDeptManager`, `MaintenancePlanner`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assigned_by_user_id`, `dispatched_by_user_id`, or `personal_use_approved_by` on a `TripRequest` where a workflow writes it) but does not compare it to any entity's `id`.

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

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100; a `limit` outside that range, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION` (HTTP 400). The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with insertion order breaking any creation-timestamp ties.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is smaller than `total_count`.

### 2.4. The Logical Clock

Every time-sensitive rule in this API — document lapse, maintenance-window overlap, training currency, charter-quote expiry, completion gating — reads a single server-owned **logical clock**, never the host's wall clock. On startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it advances only when an operator advances it; the server must never silently fall back to wall-clock time. A `FlightDeptManager`-only capability advances the clock by supplying a `to_iso8601` instant, and the response reports the resulting `now_utc`. The supplied instant replaces the current reading unconditionally — the server performs no monotonicity check — and transitions already applied by earlier clock events are never reversed.

Advancing the clock is a system-wide event with four automatic consequences. Every `DocumentPermit`'s `status` is recomputed against the new instant. Every `Aircraft`'s `posture` is recomputed. Any `MaintenanceWindow` still in `PLANNED` whose start has been reached moves to `IN_PROGRESS`. Any `CharterSupplement` still in `QUOTED` whose trip's requested departure has passed moves to `EXPIRED`. Clients that need deterministic behavior for document expiry, duty windows, or settlement should always reason against the logical clock.

### 2.5. Common Resource Properties

Every resource in this API — aircraft, documents, crew members, business units, passenger profiles, trip requests, flight legs, maintenance windows, catering orders, ground transports, charter quotes, and SIFL rate periods — carries a standard set of system-managed fields:

- **`id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T12:00:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, again with three fractional digits, indicating when the resource was last modified. It is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer, starting at 1 on creation, that increments with every modification to the resource, including mutations driven by cascades or settlement math. It is the basis for optimistic concurrency control.

### 2.6. Nested Resource Retrieval and Validation Ordering

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example, a catering order addressed under a specific flight leg under a specific trip — the system validates the existence of each identifier in sequential, left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the *first* path identifier that does not correspond to an existing resource. Separately, any foreign key carried in a request body — `requester_id`, `charge_bu_id`, `home_bu_id`, entries of `passenger_ids`, the `pic_crew_id` and `sic_crew_id` pair, or `trip_request_id` — must resolve to an existing entity, or the request fails with `ERR_FK_NOT_FOUND` (HTTP 404). A malformed body — wrong types, missing required fields, unparseable payloads — is rejected with `ERR_VALIDATION` (HTTP 400). Timestamp fields accept ISO 8601 strings, and a value without an explicit offset is interpreted as UTC. Unknown or system-managed fields supplied in a request body are ignored rather than rejected, and an optional field explicitly set to null is treated as absent.

When several checks could fail on the same request, the server evaluates them in a fixed order so the surfaced error is deterministic: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then path-resource existence left-to-right (`ERR_NOT_FOUND`), then body-schema validation (`ERR_VALIDATION`), then body foreign-key resolution (`ERR_FK_NOT_FOUND`), then state-machine validity — whether the target entity's current state even permits the requested transition (`ERR_INVALID_STATE`, HTTP 409) — then optimistic-concurrency freshness (`ERR_STALE_VERSION`, HTTP 412), and only then the business rules. Within the business tier the order is likewise fixed: crew legality (`ERR_CREW_ILLEGAL`), aircraft availability (`ERR_AIRCRAFT_NOT_AVAILABLE`), aircraft interval conflict (`ERR_AIRCRAFT_INTERVAL_CONFLICT`), crew interval conflict (`ERR_CREW_INTERVAL_CONFLICT`), maintenance and training conflicts (`ERR_MAINTENANCE_CONFLICT`), capacity and roster constraints (`ERR_CONSTRAINT_VIOLATION`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), personal-use approval (`ERR_PERSONAL_USE_NOT_APPROVED`), and finally charter state validity (`ERR_CHARTER_STATE_INVALID`) — so, for instance, a stale-version rejection surfaces before any business-rule complaint, and an authentication failure masks everything downstream. Action endpoints that take no meaningful payload disregard any well-formed JSON body, but a malformed JSON body there surfaces `ERR_VALIDATION` ahead of path-resource resolution. Requests to undefined paths — or to methods not defined on a defined path — are rejected with `ERR_NOT_FOUND` (HTTP 404) without further checks.

### 2.7. Aircraft Posture and Document Currency

Each aircraft carries, alongside its lifecycle `status` (`ACTIVE`, `GROUNDED`, `RETIRED`), a derived airworthiness posture exposed as `posture`, with a human-readable explanation in `posture_reason` whenever the posture is not `AVAILABLE`. The derivation is deterministic. The posture is `MAINTENANCE_HOLD` when the aircraft is `GROUNDED`, when any of its maintenance windows is `IN_PROGRESS`, or when any `PLANNED` maintenance window's half-open interval — start inclusive, end exclusive — contains the current logical clock. Otherwise, the posture is `DOCUMENT_LAPSE` when any attached `DocumentPermit` whose `doc_kind` is `AIRWORTHINESS_CERT`, `REGISTRATION`, or `INSURANCE` has an `expires_at` equal to or earlier than the current logical clock. Otherwise the posture is `AVAILABLE`. When both conditions apply, `MAINTENANCE_HOLD` dominates. Posture is recomputed on every mutation of the aircraft's maintenance-window or document children, whenever the logical clock advances, and on every read of the aircraft.

A document's own `status` is likewise derived rather than stored: it reads `CURRENT` while its `expires_at` is strictly later than the logical clock and flips to `EXPIRED` the moment the clock reaches or passes that instant. The status is recomputed whenever the logical clock advances and on every read.

### 2.8. Monetary Precision and Rounding

All money in this API — budgets, vendor quotes, charter prices, SIFL charges, allocated costs — is represented as integer cents; no floating-point arithmetic is permitted anywhere in the calculation chain. Where a computation produces a fractional cent, the rounding rule is **round half up to a whole number of cents**, and the point at which rounding is applied is part of the contract: SIFL imputed income is rounded per (leg, passenger) line *before* any summation, and trip cost allocation is rounded per leg, with the charter-proration remainder rule described in §3.7 guaranteeing that prorated shares sum exactly to the quote. Percentage-based adjustments use whole-percent multipliers: the SIFL control-employee adjustment applies `control_employee_multiplier_pct` as a percentage, so a configured value of 400 means the charge is multiplied by four.

### 2.9. Optimistic Concurrency Control

Two trip-level write operations are guarded by optimistic concurrency control: the aircraft-assignment action and the settlement action. Each of these requests must carry `expected_trip_request_version`, a non-optional input field holding the `version` of the `TripRequest` the client last observed. If that value does not match the trip's current `version` on the server — because another writer has advanced the trip since the client read it, for example through a leg insertion on a trip past `DRAFT`, a charter acceptance, or a prior settle — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from freezing assignment or settlement numbers against a trip state it has not observed. Endpoints not named above do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Registering the Fleet, the People, and the Rate Tables

Before any trip can fly, the department populates its registries. A `FlightDeptManager` registers each aircraft by its `tail_number` — a registration string such as N123CF that is unique across the fleet — together with its `aircraft_type` (one of `LIGHT_JET`, `MIDSIZE_JET`, `HEAVY_JET`, or `TURBOPROP`), its certified `passenger_capacity` of at least one seat, and its `home_base_icao`; a `passenger_capacity` below one or a duplicate `tail_number` is rejected with `ERR_VALIDATION` (HTTP 400). A newly registered aircraft starts with `status` set to `ACTIVE`; its `posture` and `posture_reason` are derived continuously per §2.7 rather than accepted as input. The aircraft list endpoint accepts optional `status` and `posture` query filters alongside `limit` and `offset`.

Document currency is tracked per tail. A `MaintenancePlanner` attaches each document to its aircraft with a `doc_kind` drawn from `AIRWORTHINESS_CERT`, `REGISTRATION`, `INSURANCE`, `OPS_SPECS`, `NOISE_CERT`, or `INTERNATIONAL_PERMIT`, plus the document `identifier`, its `issued_at` timestamp, and its `expires_at` timestamp; the document's `aircraft_id` identifies the owning tail. Attaching a document recomputes the parent aircraft's posture immediately, and attaching is not gated on the aircraft's lifecycle status.

Crew registration, also a `FlightDeptManager` operation, records each pilot's unique `employee_number` (a duplicate is rejected with `ERR_VALIDATION`, HTTP 400), `full_name`, `seat_qualification` (`PIC` for pilot-in-command, `SIC` for second-in-command), the list of `type_ratings` naming every aircraft type the pilot is rated on, and `training_valid_until`, the instant at which the pilot's recurrent training expires. A crew member's `status` begins at `ACTIVE`; `ON_LEAVE` and `INACTIVE` are defined status values, but this API exposes no operation that moves a crew member out of `ACTIVE`. The system maintains two duty-tracking fields on its own: `duty_window_start_utc`, marking the start of the pilot's current rolling duty window, and `duty_minutes_used`, the block minutes already charged inside that window — initially null and zero respectively. The crew list supports `status` and `seat_qualification` filters.

Finance owns the cost centers and the IRS rate tables. A `FinanceAdmin` registers each business unit with a unique `bu_code` such as BU-EXEC, a display `name`, and an `annual_flight_budget_cents` of zero or more (a negative budget or a duplicate `bu_code` is rejected with `ERR_VALIDATION`, HTTP 400); the unit's `allocated_cents` starts at zero and accumulates the cost of settled trips, with no periodic reset. Passenger profiles are registered by a `FlightDeptManager` with a unique `employee_number` (a duplicate is rejected with `ERR_VALIDATION`, HTTP 400), a `full_name`, a `priority_tier` of `TIER_1`, `TIER_2`, or `TIER_3` — where `TIER_1` preempts `TIER_2`, which preempts `TIER_3` — a `home_bu_id` naming the passenger's default cost center, and an `sifl_control_employee` flag that marks IRS control employees and drives the SIFL multiplier at settlement. The passenger list can be filtered by `home_bu_id` for reverse reachability from a business unit.

SIFL rates are published as half-open periods. A `FinanceAdmin` publishes each period with `period_start_utc` (inclusive) and `period_end_utc` (exclusive and strictly after the start, enforced as `ERR_VALIDATION`, HTTP 400), the `terminal_charge_cents` applied per flight (zero or more), the per-mile band rates `rate_band_1_cents_per_mile`, `rate_band_2_cents_per_mile`, and `rate_band_3_cents_per_mile` (each zero or more; a negative terminal charge or band rate is rejected with `ERR_VALIDATION`, HTTP 400), and the `control_employee_multiplier_pct`, which is accepted as any integer. Two rate periods covering the same lookup date must not overlap: a new period whose half-open interval intersects an existing one is rejected with `ERR_OVERLAPPING_RATE_PERIOD` (HTTP 422).

### 3.2. Originating a Trip: From Draft to Approval

An `ExecutiveRequester` originates a trip by supplying the `requester_id` of the requesting passenger profile, the `charge_bu_id` of the business unit that will carry the cost, a `trip_kind` of `BUSINESS`, `PERSONAL`, or `MIXED`, a free-text `purpose`, the desired `requested_departure_utc` for the first leg and `requested_return_utc` for the final arrival, and the roster `passenger_ids`. The roster must contain at least one entry and must include the requester; the return instant must be strictly after the departure instant; violations of these rules are rejected with `ERR_CONSTRAINT_VIOLATION` (HTTP 422). An optional `personal_use_flag` — defaulting to false — declares that some leg carries personal-use passengers and will require finance approval before dispatch. A new trip opens with `approval_status` in `DRAFT`, `assignment_status` in `UNASSIGNED`, and `settlement_status` in `UNSETTLED`; `max_priority_tier` reads null until the first submission, and `sifl_imputed_income_cents` and `allocated_cost_cents` read zero until settlement. The trip list can be filtered by `approval_status`, `assignment_status`, `requester_id`, or `charge_bu_id`.

Legs give the trip its shape. Either the requester or a `Dispatcher` adds a leg under the trip — in any of the trip's states; there is no state gate — with an integer `leg_sequence` that is unique within the trip (a duplicate is rejected with `ERR_CONSTRAINT_VIOLATION`, HTTP 422), the `origin_icao` and `destination_icao` airports, the planned `scheduled_departure_utc` and `scheduled_arrival_utc` — arrival strictly after departure, again enforced as `ERR_CONSTRAINT_VIOLATION` — and the great-circle `distance_statute_miles`, zero or more (a negative value is `ERR_VALIDATION`, HTTP 400), that will later drive SIFL banding. The system derives `block_minutes` as the difference between arrival and departure in whole minutes, and each leg carries a `trip_request_id` back to its parent. Until assignment, the leg's `aircraft_id`, `pic_crew_id`, and `sic_crew_id` remain unset, and the leg sits in `PLANNED`. Adding a leg to a trip that has left `DRAFT` also advances the parent trip's `version`; while the trip is in `DRAFT`, leg additions leave the trip's `version` untouched.

Submitting the draft is the requester's own act: the trip must have at least one `PLANNED` leg (a trip without one is rejected with `ERR_INVALID_STATE`, HTTP 409), and the acting header identity must be the trip's `requester_id`. Submission moves `approval_status` from `DRAFT` to `SUBMITTED` and recomputes `max_priority_tier` as the highest-priority tier present on the roster — `TIER_1` outranking `TIER_2` outranking `TIER_3`. From `SUBMITTED`, a `FlightDeptManager` either approves or rejects. Approval requires that every leg's `scheduled_departure_utc` still lies strictly in the future relative to the logical clock (a violation is rejected with `ERR_INVALID_STATE`, HTTP 409), and it moves `approval_status` to `APPROVED`. Approval itself persists no assignments: every leg remains `PLANNED` and the trip `UNASSIGNED` until a `Dispatcher` explicitly runs the aircraft-assignment action of §3.3. Rejection moves `approval_status` to `REJECTED` — a terminal state for the trip — and cascades: every `PLANNED` leg drops to `CANCELLED`, and every catering order or ground transport still in `REQUESTED` or `CONFIRMED` is cancelled with it.

A trip may also be abandoned before completion: a `Dispatcher`, the originating `ExecutiveRequester`, or a `FlightDeptManager` can cancel a trip whose `assignment_status` is `UNASSIGNED` or `ASSIGNED` — but never a `REJECTED` trip, which is terminal and rejects cancellation with `ERR_INVALID_STATE` (HTTP 409). Cancellation moves the trip's `assignment_status` to the terminal `CANCELLED` while leaving `approval_status` unchanged, and cascades identically — every non-terminal leg is cancelled, and services still in `REQUESTED` or `CONFIRMED` are cancelled alongside.

### 3.3. Assigning Aircraft: The Selector and Its Conflicts

Once a trip is `APPROVED` and still `UNASSIGNED`, a `Dispatcher` runs the aircraft-assignment action (any other state combination is `ERR_INVALID_STATE`, HTTP 409). The request must carry `expected_trip_request_version` matching the trip's current `version`; a mismatch means the dispatcher's view of the trip is stale and the attempt is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.9. At least one `PLANNED` leg must exist (otherwise `ERR_INVALID_STATE`, HTTP 409). On success, every `PLANNED` leg moves to `AIRCRAFT_ASSIGNED` with its `aircraft_id` set by the selector, the trip's `assigned_by_user_id` records the acting dispatcher's `X-User-ID` for later segregation-of-duties checks, `assignment_status` becomes `ASSIGNED`, and the trip's `version` increments by one.

The selector builds its candidate set by strict elimination. A candidate aircraft must be `ACTIVE` with posture `AVAILABLE`, must offer a `passenger_capacity` at least equal to the number of passengers on the trip roster, and must be free of schedule conflicts: any existing leg on the same tail in `AIRCRAFT_ASSIGNED`, `CREWED`, or `RELEASED` whose buffered interval intersects the candidate leg's buffered interval disqualifies the tail. (The trip and leg model carries no equipment-preference field, so equipment matching never eliminates a candidate.) Each leg's buffered interval opens ninety minutes before its `scheduled_departure_utc` and closes ninety minutes after its `scheduled_arrival_utc` — a turn-buffer of an hour and a half on each side — and the comparison is half-open, so a back-to-back pairing in which one leg's buffered start exactly equals another leg's buffered end does *not* count as an overlap. Eligible tails are ranked smallest-sufficient-first: ascending `passenger_capacity`, then preferring a tail whose `home_base_icao` equals the leg's `origin_icao`, with `created_at` ascending as the deterministic tie-break and insertion order breaking any remaining ties. The pass walks the trip's `PLANNED` legs in ascending `leg_sequence` order and is atomic: if selection fails for any leg, no leg or trip field is modified. The conflict set is a snapshot of legs already holding tails, taken before the pass begins; legs assigned earlier in the same pass do not join it, so legs of one trip may share a tail when their buffered intervals permit.

The assignment attempt fails loudly when the rules are breached, and because the attempt always ends in an empty-pool report, the surfaced error is attributed by the stage at which the pool emptied, in fixed stage order: posture (`ERR_AIRCRAFT_NOT_AVAILABLE`, HTTP 422), then buffered-interval collision (`ERR_AIRCRAFT_INTERVAL_CONFLICT`, HTTP 422), then maintenance — any `PLANNED` or `IN_PROGRESS` maintenance window on the candidate tail whose half-open interval intersects the leg's own scheduled interval, departure inclusive through arrival exclusive (`ERR_MAINTENANCE_CONFLICT`, HTTP 422) — and finally capacity (`ERR_NO_CANDIDATE_AIRCRAFT`, HTTP 422, likewise reported when the fleet contains no aircraft at all). When the candidate pool comes up empty, the leg is left in `PLANNED`, the attempt reports `ERR_NO_CANDIDATE_AIRCRAFT` (HTTP 422), and the trip becomes charter-eligible — a `CharterSupplement` may then be recorded under §3.6.

### 3.4. Crewing, Passenger Services, and the Leg Pipeline

With an aircraft on the leg, a `Dispatcher` pairs the cockpit crew by submitting `pic_crew_id` and `sic_crew_id`. The two seats must be filled by different people. Both crew members must be `ACTIVE`, must each hold the assigned aircraft's `aircraft_type` within their `type_ratings`, and must each have `training_valid_until` strictly later than the leg's `scheduled_departure_utc` — a pilot whose recurrent training expires at or before departure is illegal for that leg. Crew-legality failures — training currency included — are rejected with `ERR_CREW_ILLEGAL` (HTTP 422); the maintenance-and-training conflict gate at crewing covers only maintenance windows on the assigned tail, reported as `ERR_MAINTENANCE_CONFLICT` (HTTP 422), and because crew legality is evaluated first (§2.6), a training failure never surfaces as `ERR_MAINTENANCE_CONFLICT`.

Duty time is enforced against a rolling window. A crew member's duty window runs exactly 24 hours from `duty_window_start_utc`. When the leg being crewed departs outside the crew member's current window — or no window is open at all — a fresh window opens at that leg's `scheduled_departure_utc` and the pilot's `duty_minutes_used` resets to zero. The pairing is legal only when the minutes already used in the window plus the leg's `block_minutes` total at most 840 minutes — fourteen hours — and a total landing exactly on the limit is permitted. Crew scheduling also forbids time collisions with unbuffered half-open semantics: a crew member already committed, as either `PIC` or `SIC`, to another leg in `CREWED` or `RELEASED` whose scheduled interval intersects the new leg's scheduled interval triggers `ERR_CREW_INTERVAL_CONFLICT` (HTTP 422). Unlike the aircraft rule, no turn buffer is added for crew, so adjacent legs that share an endpoint are permitted. A successful pairing sets `pic_crew_id` and `sic_crew_id` on the leg and moves it from `AIRCRAFT_ASSIGNED` to `CREWED`.

Passenger services are coordinated per leg while crewing proceeds; ordering is permitted under a leg in any state. A `Dispatcher` orders catering with a `vendor_name`, a vendor `menu_code`, a `headcount` of at least one, and a `quoted_cost_cents` of zero or more (a shortfall below either bound is `ERR_VALIDATION`, HTTP 400); the order opens in `REQUESTED`, moves to `CONFIRMED` when the vendor confirms, and can be marked `DELIVERED` only once the parent leg is `CREWED` or `RELEASED`; an order still in `REQUESTED` or `CONFIRMED` may be cancelled. Ground transport follows a parallel track: booked with a `provider_name`, a `pickup_minutes_after_arrival` of zero or more minutes after the leg's scheduled arrival, and a `quoted_cost_cents` of zero or more (negative values are `ERR_VALIDATION`, HTTP 400); it moves `REQUESTED` to `CONFIRMED` and reaches `COMPLETED` only after the parent leg itself has completed, with cancellation available from either pre-terminal state. Both resources carry a `flight_leg_id` naming their leg.

A crewed leg is released once its services are squared away. Release requires the parent trip's `approval_status` to be `APPROVED` and no catering order or ground transport on the leg to remain in `REQUESTED` — any later service state, `DELIVERED` catering included, passes the gate; an attempt to release while a catering order or ground transport is still in `REQUESTED` is rejected with `ERR_SERVICE_NOT_READY` (HTTP 422). A released leg completes once the logical clock has reached its `scheduled_arrival_utc`; completing a leg that is not in `RELEASED` fails with `ERR_LEG_NOT_RELEASED` (HTTP 422) — except that a `PLANNED` leg of a trip covered by an `ACCEPTED` charter supplement completes directly, the charter vendor having flown it — and an early completion ahead of the arrival instant is rejected with `ERR_INVALID_STATE` (HTTP 409). When the final sibling leg completes — every leg of the trip now `COMPLETED` — the parent trip's `assignment_status` automatically moves from `DISPATCHED` to `COMPLETED`, while its `settlement_status` deliberately remains `UNSETTLED` until finance closes the books. Individual legs can also be cancelled outright: from `PLANNED`, `AIRCRAFT_ASSIGNED`, or `CREWED`, a `Dispatcher` (or a parent cascade) drops the leg to `CANCELLED`, and its `REQUESTED` or `CONFIRMED` services cascade to `CANCELLED` with it. The flat leg list supports `aircraft_id`, `pic_crew_id`, `sic_crew_id`, `status`, and `trip_request_id` filters so schedules can be reconstructed from the aircraft or crew side.

### 3.5. Personal-Use Governance and Dispatch

Dispatch is the moment the department commits the aircraft, and it is guarded accordingly. A `Dispatcher` can dispatch only a trip in `ASSIGNED`, and only when every leg of the trip is `CREWED`, `RELEASED`, or `COMPLETED` — a leg in any other state blocks dispatch with `ERR_INVALID_STATE` (HTTP 409). When the trip's `personal_use_flag` is true, two further gates apply. First, a `FinanceAdmin` must already have recorded personal-use approval on the trip — the approval action sets `personal_use_approved_by` to the acting finance administrator's `X-User-ID` and is itself not state-gated, so approval may be recorded on any trip at any time — and dispatch without that approval is rejected with `ERR_PERSONAL_USE_NOT_APPROVED` (HTTP 422). Second, segregation of duties forbids the same operator from both assigning and dispatching a personal-use trip: when `personal_use_flag` is true, the acting dispatcher's `X-User-ID` must differ from the trip's `assigned_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Per the §2.6 business-tier order, the segregation check is evaluated before the personal-use-approval check.

A successful dispatch moves `assignment_status` from `ASSIGNED` to `DISPATCHED`, records the acting dispatcher in `dispatched_by_user_id`, and charges duty time: for each crew member, the trip's legs are processed in ascending scheduled-departure order and each leg's `block_minutes` are added to `duty_minutes_used` for both the `PIC` and the `SIC` on the leg, applying the §3.4 rolling-window rule — a leg departing outside the crew member's current 24-hour window opens a fresh window at that leg's `scheduled_departure_utc`, resetting `duty_minutes_used` to zero before the leg's minutes are charged. The same segregation-of-duties principle reappears at settlement for personal-use trips, as §3.7 describes.

### 3.6. Charter Supplementation When the Fleet Falls Short

When the selector cannot cover a trip, the department buys capacity outside. A `Dispatcher` records a charter quote with the `trip_request_id` of the uncovered trip, the charter operator's `vendor_name`, a `quoted_cost_cents` of zero or more (a negative value is `ERR_VALIDATION`, HTTP 400), and the `aircraft_type_offered` drawn from the same four-type enumeration as the owned fleet. Recording a quote is not gated on the trip's approval or assignment state, nor on a prior failed assignment attempt. A quote opens in `QUOTED`, and the quote list can be filtered by `trip_request_id` or `status`.

A `FlightDeptManager` decides the quote's fate. Acceptance is valid only while the parent trip is `APPROVED` and still `UNASSIGNED`; an accept attempted against any other combination is rejected with `ERR_CHARTER_STATE_INVALID` (HTTP 422), and an accept or decline attempted on a quote no longer in `QUOTED` is `ERR_INVALID_STATE` (HTTP 409). Accepting a quote moves it to `ACCEPTED` and immediately advances the parent trip's `assignment_status` from `UNASSIGNED` straight to `DISPATCHED` — the charter vendor, not the owned fleet, operates the trip — with cost recognition deferred to settlement per §3.7; neither `assigned_by_user_id` nor `dispatched_by_user_id` is written on this path. A manager may instead decline the quote, moving it to `DECLINED`. Quotes also die of old age: when the logical clock advances past the trip's `requested_departure_utc`, any quote still in `QUOTED` expires to `EXPIRED` automatically.

### 3.7. Settlement: SIFL Imputed Income and Cost Allocation

Settlement is the finance close on a completed trip, performed by a `FinanceAdmin`, and it is the second OCC-guarded write: the request must carry `expected_trip_request_version` matching the trip's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). Settlement is defined only for a trip whose `assignment_status` is `COMPLETED` and whose `settlement_status` is still `UNSETTLED`; a settle attempted in any other state combination is rejected as a state-machine violation with `ERR_INVALID_STATE` (HTTP 409). Segregation of duties applies once more on personal-use trips: when `personal_use_flag` is true, the acting finance administrator's `X-User-ID` must differ from `personal_use_approved_by`, on pain of `ERR_SEGREGATION_OF_DUTIES`. A successful settle moves `settlement_status` from `UNSETTLED` to `SETTLED`, computes and persists both `sifl_imputed_income_cents` and `allocated_cost_cents`, adds the allocated cost to the charging unit's `allocated_cents`, and increments the trip's `version` by one.

The SIFL calculation runs per personal-use passenger, per leg. Which passengers count as personal-use depends on `trip_kind`: on a `PERSONAL` trip, every passenger in `passenger_ids` is personal-use; on a `MIXED` trip, only the `requester_id` is treated as personal-use; on a `BUSINESS` trip, no passenger generates imputed income. Only legs in `COMPLETED` status enter the final computation. For each leg and each personal-use passenger, the system selects the rate period whose half-open interval — `period_start_utc` inclusive, `period_end_utc` exclusive — contains the leg's `scheduled_arrival_utc`; if no published period covers that instant, settlement fails with `ERR_RATE_PERIOD_NOT_FOUND` (HTTP 422). The per-line charge is the period's `terminal_charge_cents` plus a mileage component built by splitting the leg's `distance_statute_miles` into three bands: the first 500 statute miles are priced at `rate_band_1_cents_per_mile` per mile, any miles beyond 500 up to and including 1500 are priced at `rate_band_2_cents_per_mile` per mile, and every mile beyond 1500 is priced at `rate_band_3_cents_per_mile` per mile. When the passenger's `sifl_control_employee` flag is true, the summed charge is then multiplied by `control_employee_multiplier_pct` percent — a configured 400 quadruples the line. Each per-leg, per-passenger line is rounded half-up to a whole number of cents *before* any summation, and the rounded lines are then added across legs and passengers into the trip's `sifl_imputed_income_cents`. Each passenger carries the full charge for the leg; there is no splitting among passengers.

A provisional variant of the same math is available before the money is real. A `FinanceAdmin` or `FlightDeptManager` can request a SIFL preview, which applies the identical banding, terminal charge, control-employee multiplier, and per-line rounding, but across *all* of the trip's legs regardless of leg status — `PLANNED`, `AIRCRAFT_ASSIGNED`, `CREWED`, and `RELEASED` legs included — with no requirement that the trip be completed and nothing persisted. The preview selects the covering rate period exactly as settlement does and likewise fails with `ERR_RATE_PERIOD_NOT_FOUND` (HTTP 422) when a personal-use passenger's leg has an uncovered arrival instant. The preview response carries `provisional_sifl_cents` and `leg_count_included`.

Cost allocation runs in parallel, processed across the trip's completed legs in ascending `leg_sequence` order with `created_at` as the tie-break and insertion order breaking any remaining ties. For a trip flown by the owned fleet, each completed leg's cost is its `block_minutes` multiplied by the per-minute rate of the assigned aircraft's `aircraft_type` — 8,500 cents per block minute for a `LIGHT_JET`, 14,000 for a `MIDSIZE_JET`, 23,000 for a `HEAVY_JET`, and 5,000 for a `TURBOPROP` — plus the sum of `quoted_cost_cents` over that leg's `DELIVERED` catering orders and the sum of `quoted_cost_cents` over its `COMPLETED` ground transports. When an `ACCEPTED` charter quote covers the trip, the aircraft-type rate is ignored entirely: each leg instead carries a prorated share of the charter `quoted_cost_cents`, computed as the quote multiplied by the leg's `block_minutes` and divided by the sum of block minutes across the trip's legs, rounded half-up to whole cents per leg, with any residual cent difference credited or debited to the leg with the highest `leg_sequence` so the shares sum exactly to the quote; if the trip's legs total zero block minutes, every prorated share is zero and the entire quote falls to that remainder leg. Either way, the trip's `allocated_cost_cents` is the sum of per-leg costs over `COMPLETED` legs, and the same amount is added to the charging business unit's `allocated_cents`. Budgets are advisory at settlement: the settle succeeds regardless of the budget, and the response's trip object always carries an `over_budget` field, true exactly when the unit's resulting total ends strictly greater than its `annual_flight_budget_cents`.

### 3.8. Maintenance Windows, Grounding, and Return to Service

Maintenance is planned per tail. A `MaintenancePlanner` schedules a window on an aircraft with `window_start_utc` (inclusive), `window_end_utc` (exclusive and strictly after the start, enforced as `ERR_VALIDATION`, HTTP 400), and a `maintenance_kind` of `SCHEDULED_INSPECTION`, `UNSCHEDULED_REPAIR`, `AVIONICS_UPGRADE`, or `ENGINE_OVERHAUL`; the window's `aircraft_id` names the tail, the window opens in `PLANNED`, scheduling is not gated on the aircraft's lifecycle status, and the window list for a tail accepts a `status` filter. When the logical clock reaches a planned window's start, the window moves itself to `IN_PROGRESS`; completing an in-progress window is permitted only once the clock has reached `window_end_utc`, moving it to `COMPLETED`; a planned window can also be cancelled outright. Every one of these mutations recomputes the parent aircraft's posture per §2.7.

Grounding is the heavy hammer. A `MaintenancePlanner` may ground an `ACTIVE` aircraft, moving it to `GROUNDED` and forcing its posture to `MAINTENANCE_HOLD`. The cascade reaches the schedule: every flight leg holding that tail in `AIRCRAFT_ASSIGNED` or `CREWED` is dropped back to `PLANNED` — unconditionally, without regard to any maintenance window's interval — with its `aircraft_id`, `pic_crew_id`, and `sic_crew_id` cleared; the parent trip's `assignment_status` and `assigned_by_user_id` are left unchanged. Returning a grounded aircraft to service is gated on reality: no maintenance window in `PLANNED` or `IN_PROGRESS` may overlap the current logical clock, and every attached document whose `doc_kind` is `AIRWORTHINESS_CERT`, `REGISTRATION`, or `INSURANCE` must be `CURRENT`; only then does the aircraft return to `ACTIVE` with its posture recomputed.

Retirement ends the story. A `FlightDeptManager` may retire an aircraft from `ACTIVE` or `GROUNDED`, but only while no flight leg holds the tail in `AIRCRAFT_ASSIGNED`, `CREWED`, or `RELEASED`; the tail moves to the terminal `RETIRED` state, and its document permits remain attached for audit.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., an aircraft, a trip request, a catering order, a rate period) return a `201 Created` status code. Operations that modify an existing resource — every state transition, assignment, approval, settle, and clock advance — as well as all reads, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/flight-ops/_clock/set_current_utc` | Advance the logical clock | FlightDeptManager |
| POST | `/flight-ops/aircraft` | Register an aircraft | FlightDeptManager |
| GET | `/flight-ops/aircraft` | List aircraft (`status`, `posture` filters) | FlightDeptManager, Dispatcher, MaintenancePlanner, FinanceAdmin |
| GET | `/flight-ops/aircraft/{id}` | Read one aircraft (posture recomputed on read) | FlightDeptManager, Dispatcher, MaintenancePlanner, FinanceAdmin |
| POST | `/flight-ops/aircraft/{id}/ground` | Ground an aircraft; affected legs cascade to PLANNED | MaintenancePlanner |
| POST | `/flight-ops/aircraft/{id}/return-to-service` | Return a grounded aircraft to service after checks | MaintenancePlanner |
| POST | `/flight-ops/aircraft/{id}/retire` | Retire an aircraft | FlightDeptManager |
| POST | `/flight-ops/aircraft/{id}/documents` | Attach a document/permit to an aircraft | MaintenancePlanner |
| GET | `/flight-ops/aircraft/{id}/documents` | List documents for an aircraft | FlightDeptManager, Dispatcher, MaintenancePlanner |
| POST | `/flight-ops/crew-members` | Register a crew member | FlightDeptManager |
| GET | `/flight-ops/crew-members` | List crew (`status`, `seat_qualification` filters) | FlightDeptManager, Dispatcher, FinanceAdmin |
| GET | `/flight-ops/crew-members/{id}` | Read one crew member | FlightDeptManager, Dispatcher, FinanceAdmin |
| POST | `/flight-ops/business-units` | Register a business unit | FinanceAdmin |
| GET | `/flight-ops/business-units` | List business units | FinanceAdmin, FlightDeptManager |
| GET | `/flight-ops/business-units/{id}` | Read one business unit | FinanceAdmin, FlightDeptManager |
| POST | `/flight-ops/passenger-profiles` | Register a passenger | FlightDeptManager |
| GET | `/flight-ops/passenger-profiles` | List passengers (`home_bu_id` filter) | FlightDeptManager, Dispatcher, FinanceAdmin |
| GET | `/flight-ops/passenger-profiles/{id}` | Read one passenger | FlightDeptManager, Dispatcher, FinanceAdmin |
| POST | `/flight-ops/trip-requests` | Create a trip request | ExecutiveRequester |
| GET | `/flight-ops/trip-requests` | List trip requests (`approval_status`, `assignment_status`, `requester_id`, `charge_bu_id` filters) | FlightDeptManager, Dispatcher, FinanceAdmin, ExecutiveRequester |
| GET | `/flight-ops/trip-requests/{id}` | Read one trip | FlightDeptManager, Dispatcher, FinanceAdmin, ExecutiveRequester |
| POST | `/flight-ops/trip-requests/{id}/submit` | Submit a draft trip for approval | ExecutiveRequester |
| POST | `/flight-ops/trip-requests/{id}/approve` | Approve a submitted trip | FlightDeptManager |
| POST | `/flight-ops/trip-requests/{id}/reject` | Reject a submitted trip; cascades legs and services to CANCELLED | FlightDeptManager |
| POST | `/flight-ops/trip-requests/{id}/assign-aircraft` | Run the aircraft selector over all PLANNED legs; OCC-guarded | Dispatcher |
| POST | `/flight-ops/trip-requests/{id}/dispatch` | Dispatch an assigned trip after crewing | Dispatcher |
| POST | `/flight-ops/trip-requests/{id}/cancel` | Cancel a trip before completion | Dispatcher, ExecutiveRequester, FlightDeptManager |
| POST | `/flight-ops/trip-requests/{id}/approve-personal-use` | Record finance approval of personal use | FinanceAdmin |
| POST | `/flight-ops/trip-requests/{id}/settle` | Close a completed trip; computes SIFL and cost allocation; OCC-guarded | FinanceAdmin |
| GET | `/flight-ops/trip-requests/{id}/sifl-preview` | Provisional SIFL over all legs regardless of leg status | FinanceAdmin, FlightDeptManager |
| POST | `/flight-ops/trip-requests/{id}/flight-legs` | Add a leg to a trip | ExecutiveRequester, Dispatcher |
| GET | `/flight-ops/trip-requests/{id}/flight-legs` | List legs of a trip | FlightDeptManager, Dispatcher, FinanceAdmin, ExecutiveRequester |
| GET | `/flight-ops/flight-legs` | Filtered list of flight legs (`aircraft_id`, `pic_crew_id`, `sic_crew_id`, `status`, `trip_request_id` filters) | FlightDeptManager, Dispatcher, FinanceAdmin, ExecutiveRequester |
| GET | `/flight-ops/flight-legs/{id}` | Read one leg | FlightDeptManager, Dispatcher, FinanceAdmin, ExecutiveRequester |
| POST | `/flight-ops/flight-legs/{id}/assign-crew` | Pair PIC and SIC onto an AIRCRAFT_ASSIGNED leg | Dispatcher |
| POST | `/flight-ops/flight-legs/{id}/release` | Release a crewed leg once services are confirmed | Dispatcher |
| POST | `/flight-ops/flight-legs/{id}/complete` | Mark a released leg completed after arrival time | Dispatcher |
| POST | `/flight-ops/flight-legs/{id}/cancel` | Cancel one leg | Dispatcher |
| POST | `/flight-ops/aircraft/{id}/maintenance-windows` | Schedule a maintenance window on an aircraft | MaintenancePlanner |
| GET | `/flight-ops/aircraft/{id}/maintenance-windows` | List maintenance windows for an aircraft (`status` filter) | FlightDeptManager, Dispatcher, MaintenancePlanner |
| POST | `/flight-ops/maintenance-windows/{id}/cancel` | Cancel a planned window | MaintenancePlanner |
| POST | `/flight-ops/maintenance-windows/{id}/complete` | Mark an in-progress window completed | MaintenancePlanner |
| POST | `/flight-ops/flight-legs/{id}/catering-orders` | Order catering for a leg | Dispatcher |
| GET | `/flight-ops/flight-legs/{id}/catering-orders` | List catering for a leg | Dispatcher, FlightDeptManager |
| POST | `/flight-ops/catering-orders/{id}/confirm` | Confirm a catering order with the vendor | Dispatcher |
| POST | `/flight-ops/catering-orders/{id}/deliver` | Mark catering delivered once the leg is crewed or released | Dispatcher |
| POST | `/flight-ops/catering-orders/{id}/cancel` | Cancel a catering order | Dispatcher |
| POST | `/flight-ops/flight-legs/{id}/ground-transports` | Book ground transport for a leg | Dispatcher |
| GET | `/flight-ops/flight-legs/{id}/ground-transports` | List ground transports for a leg | Dispatcher, FlightDeptManager |
| POST | `/flight-ops/ground-transports/{id}/confirm` | Confirm ground transport | Dispatcher |
| POST | `/flight-ops/ground-transports/{id}/complete` | Complete ground transport after leg completion | Dispatcher |
| POST | `/flight-ops/ground-transports/{id}/cancel` | Cancel ground transport | Dispatcher |
| POST | `/flight-ops/charter-supplements` | Record a charter quote for an unassignable trip | Dispatcher |
| GET | `/flight-ops/charter-supplements` | List charter quotes (`trip_request_id`, `status` filters) | FlightDeptManager, Dispatcher, FinanceAdmin |
| GET | `/flight-ops/charter-supplements/{id}` | Read one charter quote | FlightDeptManager, Dispatcher, FinanceAdmin |
| POST | `/flight-ops/charter-supplements/{id}/accept` | Accept a charter quote; trip moves to DISPATCHED under vendor operation | FlightDeptManager |
| POST | `/flight-ops/charter-supplements/{id}/decline` | Decline a charter quote | FlightDeptManager |
| POST | `/flight-ops/sifl-rate-periods` | Publish an IRS SIFL rate period | FinanceAdmin |
| GET | `/flight-ops/sifl-rate-periods` | List SIFL rate periods | FinanceAdmin, FlightDeptManager |
| GET | `/flight-ops/sifl-rate-periods/{id}` | Read one rate period | FinanceAdmin, FlightDeptManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_CONSTRAINT_VIOLATION` | 422 |
| `ERR_CREW_ILLEGAL` | 422 |
| `ERR_CREW_INTERVAL_CONFLICT` | 422 |
| `ERR_AIRCRAFT_NOT_AVAILABLE` | 422 |
| `ERR_AIRCRAFT_INTERVAL_CONFLICT` | 422 |
| `ERR_MAINTENANCE_CONFLICT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_PERSONAL_USE_NOT_APPROVED` | 422 |
| `ERR_CHARTER_STATE_INVALID` | 422 |
| `ERR_LEG_NOT_RELEASED` | 422 |
| `ERR_SERVICE_NOT_READY` | 422 |
| `ERR_NO_CANDIDATE_AIRCRAFT` | 422 |
| `ERR_RATE_PERIOD_NOT_FOUND` | 422 |
| `ERR_OVERLAPPING_RATE_PERIOD` | 422 |
