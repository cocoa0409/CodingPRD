# Leisure Route Bundling API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Leisure Route Bundling API, a system that models the operating discipline of a low-frequency leisure carrier. The carrier's strategy is unusual by industry standards: it flies point-to-point between small origin cities and a curated set of leisure destinations, publishes schedules far in advance, operates only on selected days of the week, accepts lower daily aircraft utilization in exchange for aggressive peak-day flying, and suspends entire routes for whole seasons when demand thins out.

Two revenue philosophies sit on top of this schedule skeleton. First, fares are unbundled — the published base fare buys a seat only, and seat assignment, carry-on bags, checked bags, and priority boarding are all sold separately as ancillaries. Second, the airline acts as a packager: it bundles the air component with hotel rooms, rental cars, and attraction tickets sourced from third-party suppliers, sells the bundle to the customer at retail, and later settles with each supplier at a wholesale net cost. When a customer cancels a packaged trip after a provisional supplier settlement has been issued, the airline claws the supplier payment back through a clawback adjustment on the open settlement.

Because the network is dispersed and many stations are served only by this carrier, irregular operations have outsized consequences. A cancellation at a single-station airport strands passengers until the next scheduled departure on the same route — which may be days away — and the system must track that stranding explicitly, support rebooking onto later flights, and recognize when a disruption has been fully recovered. Crew basing mirrors the dispersed topology: crew members are permanently based at origin stations, and a crew assignment is only valid when the member's home base matches the route's origin. The API exists to coordinate all of these concerns — network planning, schedule publication, aircraft utilization, crew assignment, retail booking, ancillary sales, disruption handling, and supplier settlement — under a single, logically consistent contract.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request carries `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity under which the action is taken. The system recognizes five roles, spelled exactly as follows: `NetworkPlanner`, `OpsController`, `CrewScheduler`, `CustomerService`, and `FinanceAnalyst`. A request missing either header, or carrying a malformed header value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Each of the five roles is an opaque operator identity: when `X-User-Role` is `NetworkPlanner`, `OpsController`, `CrewScheduler`, `CustomerService`, or `FinanceAnalyst`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record the identifier on resources it mutates, but it never compares `X-User-ID` against any entity's `id` for ownership checks. Role-to-endpoint authorization is the only access-control dimension.

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
- Resource payloads expose only the public fields defined for each entity. Server-internal bookkeeping fields — whose names begin with an underscore — are never exposed: they are stripped from every success response payload, at any nesting depth.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Resources created within the same timestamp tie on `created_at`; such ties are broken by `id` in ascending order so that list ordering is always deterministic.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server maintains a logical clock that is used for every time-dependent decision in the system: publication horizon checks, mark-operated eligibility, and settlement period boundaries all compare against the logical clock, never against real wall-clock time. Before any client call, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never silently falls back to wall-clock time thereafter. Any of the five roles may advance the logical clock through a test-driving capability that sets the clock to a supplied `current_utc` instant; the response echoes back the new `current_utc`. The clock moves only when explicitly set.

### 2.5. Common Resource Properties

Every persisted resource in this API carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording when the resource was last modified; refreshed on every mutation.
- `version` (integer): a system-managed integer that increments with every modification to the resource; this is the value used by the optimistic concurrency control rules described in §2.9.

All fifteen entities in this domain (Station, Route, SeasonWindow, SchedulePublication, Aircraft, FlightInstance, CrewBase, CrewMember, CrewAssignment, SupplierOffer, Booking, PackageBundle, AncillaryPurchase, DisruptionEvent, SupplierSettlement) carry the full common set. Any derived-field update, cascade, or cross-entity write that mutates a row refreshes `updated_at` and increments `version` on that row.

### 2.6. Money, Counts, and Precision

All monetary values in this domain are stored as integer cents. Base fares, ancillary charges, supplier net costs, supplier sell prices, bundle prices, settlement gross payables, and clawback amounts are all integer cent quantities; no decimal rounding is ever applied to them. Derived counts — seats sold, suspended season counts, minutes of daily block time, published departures per week — are plain integers. Dates are ISO calendar dates, and durations such as `block_minutes` are integer minutes.

### 2.7. Nested Resource Retrieval and Existence Ordering

For every request that references resources by identifier — whether the identifier appears in the URL path or in the request body — the server validates existence before any business rule is evaluated, and it validates path identifiers in left-to-right order. A request to a nested path such as a season window under a route, or a publication under a route, or a crew assignment under a flight instance, is rejected with the not-found error corresponding to the first identifier in the path that does not exist: `ERR_ROUTE_NOT_FOUND` surfaces before `ERR_WINDOW_NOT_FOUND`, which surfaces before `ERR_PUBLICATION_NOT_FOUND`, and so on. Each entity family has its own not-found error — `ERR_STATION_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_CREW_BASE_NOT_FOUND`, `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`, `ERR_ANCILLARY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_DISRUPTION_NOT_FOUND`, and `ERR_ASSIGNMENT_NOT_FOUND` — and all are returned with HTTP 404.

### 2.8. Validation Ordering Across the Request Lifecycle

When several checks apply to a single request, the server evaluates them in a fixed priority order so that the error a client sees is deterministic. Authentication context is checked first — a missing or malformed `X-User-ID` or `X-User-Role` header always produces `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is inspected. Role authorization comes next, producing `ERR_INSUFFICIENT_PERMISSIONS` when the caller's role is not entitled to the endpoint. Existence checks follow, in the left-to-right order described in §2.7, surfacing the appropriate not-found error. State preconditions are evaluated after existence — for example, activation of a route that is not in `PLANNING` posture is rejected with `ERR_ROUTE_NOT_PLANNING`, and an analogous state gate applies to every transition named in §3. Only after authentication, authorization, existence, and state have all passed does the server evaluate business rules: temporal rules first (publication horizon and window containment, producing `ERR_PUBLISH_HORIZON_VIOLATION` or `ERR_PUBLICATION_OUTSIDE_WINDOW`), then structural rules about station kinds (`ERR_ROUTE_ENDPOINT_KIND_MISMATCH`), then referential rules about crew basing (`ERR_CREW_BASE_MISMATCH`, `ERR_CREW_MEMBER_INACTIVE`) and bundle offers (`ERR_OFFER_WRONG_KIND`, `ERR_OFFER_WRONG_DESTINATION`, `ERR_OFFER_NOT_OPEN`), then capacity constraints (`ERR_FREQUENCY_CAP_EXCEEDED`, `ERR_UTILIZATION_CAP_EXCEEDED`, `ERR_REBOOK_FLIGHT_INVALID`, `ERR_REBOOK_NO_AIRCRAFT`, `ERR_REBOOK_CAPACITY_EXCEEDED`), then fiscal period rules (`ERR_SETTLEMENT_PERIOD_OPEN`). The optimistic concurrency check described in §2.9 is evaluated last, so a stale version surfaces as `ERR_STALE_VERSION` only when every other rule would have allowed the write.

### 2.9. Optimistic Concurrency Control

Three write endpoints in this API take a mandatory expected-version field, and only those three. Publishing a schedule against a season window requires the request to carry `expected_window_version`, the client-observed value of that window's `version`. Creating a booking requires `expected_flight_version`, the client-observed value of the target flight's `version`. Rebooking a stranded booking requires `expected_booking_version`, the client-observed value of the booking's `version`. In each case the supplied value must equal the parent entity's current `version` at the moment the write is attempted; if another writer has advanced the entity's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept an expected-version field at all.

### 2.10. Cascading State Changes and Hierarchical Consistency

This domain is deeply hierarchical — a route owns season windows, publications, and disruptions; a publication owns flight instances; a flight owns bookings, crew assignments, and ancillaries; a booking may own a package bundle — and the system maintains consistency across that hierarchy by cascading state changes. When a route is suspended, every open window on it suspends, every published publication in those windows freezes, and every still-scheduled flight is cancelled, with the cancellation further stranding confirmed bookings and releasing crew assignments. When a booking is cancelled, its ancillaries void, its bundle cancels, and the bundle's cancellation can in turn claw back a supplier settlement. Each cascade step mutates the affected row — refreshing `updated_at` and incrementing `version` — so a single operator action can advance the version of many rows at once. Clients that cache entities must therefore treat any operator action on an ancestor as potentially invalidating their view of every descendant.

### 2.11. Boundary Semantics for Capacity and Threshold Checks

Three thresholds in this domain — the weekly frequency cap, the aircraft daily utilization caps, and the rebook seat capacity — all share the same boundary semantics: the check rejects only when the proposed total is strictly greater than the applicable cap. A proposal that lands exactly on the cap is allowed. The publication horizon rule has the opposite orientation — it rejects only when the lead time is strictly less than the minimum, so a first operating date exactly at the minimum lead time is allowed. These boundary choices are deliberate and are restated in §3 next to each rule that uses them.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Stations, Routes, and Season Windows

A `NetworkPlanner` begins by registering airports as **Stations**. Each station record carries an `iata_code` that is unique across the network, a `station_kind` that classifies the airport as either `ORIGIN_SMALL_CITY` or `LEISURE_DESTINATION`, an IANA `timezone` such as `America/Phoenix`, and a `single_station_flag` that defaults to `false` and is set to `true` when this airline is the only scheduled carrier at the station — the flag drives the stranded-passenger semantics described in §3.6.

With stations in place, the planner creates a **Route** by supplying an `origin_station_id`, a `destination_station_id`, a `base_fare_cents`, and a `weekly_frequency_cap`. The base fare is the unbundled fare in cents: it covers carriage only, and seat assignment, bags, and priority boarding are never included. The weekly frequency cap is the maximum number of published departures the route may operate in any ISO week, and for this low-frequency network it is typically between one and four. The station kinds are structural: the origin must be a station of kind `ORIGIN_SMALL_CITY` and the destination must be of kind `LEISURE_DESTINATION`, and a route whose endpoints violate either constraint is rejected with `ERR_ROUTE_ENDPOINT_KIND_MISMATCH` (HTTP 422). A new route begins life in the `PLANNING` posture with its `suspended_seasons_count` at zero; the posture field is named `route_posture`.

A route's flying is organized into **Season Windows**. The planner opens a window on a route by providing a human-readable `season_label` such as `Winter 2026-27`, an inclusive `window_start_date`, and an inclusive `window_end_date` that must be on or after the start date. A new window's `window_status` begins at `OPEN`. The planner may attach an optional `suspension_reason` note, which the server records when the window later transitions to `SUSPENDED`.

A route leaves `PLANNING` and becomes `SEASONAL_ACTIVE` only when the planner activates it, and activation requires at least one `OPEN` window to already exist on the route; a route with no open window cannot activate and the attempt is rejected with `ERR_NO_OPEN_SEASON`. Attempting to activate a route that is not currently in `PLANNING` is rejected with `ERR_ROUTE_NOT_PLANNING`. Both errors carry HTTP 409.

### 3.2. Publishing the Schedule: Day-of-Week Masks, Horizons, and Flight Generation

Against an `OPEN` window on an active route, the planner publishes a **SchedulePublication**. The publication request names the target window via `season_window_id`, declares the pattern of operation through `operating_days_mask` (an array of ISO weekday numbers from 1 for Monday through 7 for Sunday on which flights operate — this is the variable day-of-week operation at the heart of the leisure model), and bounds the operating period with an inclusive `first_operating_date` and an inclusive `last_operating_date`. The request also carries the local `departure_time_local` at the origin in `HH:MM` form and the scheduled `block_minutes`.

Three temporal rules guard publication, and they are evaluated in the order given here. First, the operating dates must lie inside their window: `first_operating_date` must be on or after the window's `window_start_date`, and `last_operating_date` must be on or before the window's `window_end_date`; a violation produces `ERR_PUBLICATION_OUTSIDE_WINDOW`. Second, the schedule must be published far ahead of operation: the number of whole days between the logical clock's current date and `first_operating_date` must be at least 180 days, and a shorter lead time is rejected with `ERR_PUBLISH_HORIZON_VIOLATION`. A first operating date exactly 180 days ahead is allowed — only a strictly smaller lead time rejects. Third, the frequency cap must hold in every ISO week the publication touches, as described below. All three failures surface with HTTP 422 for the first two and HTTP 409 for the frequency rule.

The weekly frequency check works as follows. For each ISO week overlapped by the operating range from `first_operating_date` through `last_operating_date`, the server counts how many days in that week both appear in `operating_days_mask` and fall inside the operating range; that is the number of new departures this publication would add to the week. It then adds the count of flight instances already generated on the same route for that week by other publications that have not been retired. If the combined total exceeds the route's `weekly_frequency_cap`, the publication is rejected with `ERR_FREQUENCY_CAP_EXCEEDED`. A week landing exactly on the cap is allowed; only a strict excess rejects.

Because publication is a concurrency-sensitive write on the window, the publication request must also carry `expected_window_version` equal to the window's current `version`; if the window's version has advanced since the planner last observed it — for instance because another planner has just suspended or re-opened it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

A successful publication's `publication_status` lands at `PUBLISHED`, the server stamps its `published_at` with the logical clock, and the system generates one **FlightInstance** for every calendar date from `first_operating_date` through `last_operating_date` inclusive whose ISO weekday appears in `operating_days_mask`. Each generated flight carries a `publication_id` pointing back to its publication, its `flight_date`, a denormalized `route_id` copied from the publication's route for query speed, an `aircraft_id` that is null until tail assignment, an `is_peak_day` flag that is `true` when the flight's ISO weekday is contained in the route's peak-day set recorded at publish time, a `seats_sold` counter that starts at zero, and an initial `flight_status` of `SCHEDULED`. Each generated flight's `cancelled_by_disruption_id` is null. The act of publishing mutates the window as well, incrementing the window's `version` by one — which is exactly why the OCC rule above exists.

A publication that is no longer wanted can be retired by the planner. Retiring from `PUBLISHED` requires that no flight under the publication still be `SCHEDULED` with `seats_sold` greater than zero; if any such booked flight exists, the retire is rejected with `ERR_PUBLICATION_HAS_BOOKED_FLIGHTS`. Otherwise every remaining `SCHEDULED` flight with zero seats sold is cancelled silently — no disruption event is created for an empty flight — and the publication lands in `RETIRED`. A publication in `FROZEN` status may also be retired through the same action; in that case there are no scheduled flights left to cancel. Retiring a publication that is neither `PUBLISHED` nor `FROZEN` is rejected with `ERR_PUBLICATION_NOT_PUBLISHED`. Retired is terminal.

### 3.3. Fleet and Utilization: Aircraft, Tail Assignment, and Peak-Day Flying

An `OpsController` registers each tail as an **Aircraft** by supplying its `tail_number` (unique), its certified `seat_capacity`, a `daily_utilization_cap_minutes`, and a `peak_day_cap_minutes` that must be greater than or equal to the daily cap. The lower-than-industry daily cap is the deliberate leisure utilization strategy: the airline accepts flying each tail fewer block hours per day in exchange for the right to push harder on peak days, and `peak_day_cap_minutes` is the elevated cap that applies on days whose ISO weekday belongs to the route's peak-day set. A new aircraft's `aircraft_status` begins at `IN_SERVICE`.

Tail assignment attaches an aircraft to a specific flight. Before accepting the assignment, the server computes the utilization check: it sums `block_minutes` across every still-`SCHEDULED` flight already assigned to that aircraft whose `flight_date` equals the target flight's `flight_date`, then adds the target flight's own `block_minutes` to form the proposed total for the day. The applicable cap is `peak_day_cap_minutes` when the target flight's `is_peak_day` flag is `true`, and `daily_utilization_cap_minutes` otherwise. If the proposed total is strictly greater than the applicable cap, the assignment is rejected with `ERR_UTILIZATION_CAP_EXCEEDED` (HTTP 409). A proposed total exactly equal to the cap is allowed. On success the flight's `aircraft_id` is set.

An aircraft may be retired when it is no longer needed, moving it from `IN_SERVICE` to `OUT_OF_SERVICE`. Retirement is blocked while any `SCHEDULED` flight still references the tail; the attempt is rejected with `ERR_AIRCRAFT_HAS_LIVE_FLIGHTS`.

Once the logical clock reaches a flight's `flight_date`, the ops controller may mark the flight as `OPERATED`. The flight must still be `SCHEDULED` — attempting the transition on a flight in any other status is rejected with `ERR_FLIGHT_NOT_SCHEDULED` — and the logical clock must be on or after the flight date. Marking operated has a bookkeeping side effect on rebooked passengers, described in §3.6: any booking in `STRANDED_REBOOKED` status whose rebooked flight is this one returns to `CONFIRMED` as the flight actually departs.

### 3.4. Crew Basing and Assignment

Because the network is dispersed, crew members are permanently based at origin stations rather than at a central hub. A `CrewScheduler` opens a **CrewBase** at a station by providing its `base_station_id` and a short `base_code` such as `PIE`; the new base's `base_status` begins at `ACTIVE` (the alternative being `CLOSED`). The scheduler then hires crew into a base by supplying an `employee_number` (unique) and a `crew_role` of `CAPTAIN`, `FIRST_OFFICER`, or `FLIGHT_ATTENDANT`; the new member's `crew_base_id` records the home base, and the member's `member_status` begins at `ACTIVE` (the alternative being `FURLOUGHED`).

A crew assignment attaches one crew member to one flight; the assignment records the target `flight_instance_id` and the chosen `crew_member_id`. The basing rule is strict and referential: the crew member's base station — that is, the `base_station_id` of the crew base the member belongs to — must equal the route's `origin_station_id`, because crews are based at the small-city origins to support the dispersed network. A member whose base station differs from the route origin is rejected with `ERR_CREW_BASE_MISMATCH`. Both the crew member and the crew base must be `ACTIVE`; assigning a furloughed member or a member of a closed base is rejected with `ERR_CREW_MEMBER_INACTIVE`. Both failures carry HTTP 422. A successful assignment's `assignment_status` begins at `ASSIGNED`. The scheduler may later release an assignment, moving its `assignment_status` from `ASSIGNED` to `RELEASED`; releasing an assignment that is not currently `ASSIGNED` is rejected with `ERR_ASSIGNMENT_NOT_ASSIGNED` (HTTP 409). Cancellation of the underlying flight also releases its crew assignments automatically, as described in §3.6.

### 3.5. Selling the Trip: Bookings, Ancillaries, and Package Bundles

A `CustomerService` agent creates a **Booking** against a scheduled flight. The request names the target flight via `flight_instance_id`, gives the `passenger_count` (at least one seat), and declares the `booking_kind` as either `AIR_ONLY` or `PACKAGE`. Because booking consumes inventory on the flight, the request must carry `expected_flight_version` equal to the flight's current `version`; if another writer has advanced the flight's version since the agent last read it — for instance because a prior booking just consumed the remaining seats and bumped both `seats_sold` and `version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

The booking's `base_fare_total_cents` is computed at creation as the `passenger_count` multiplied by the route's `base_fare_cents`, and that product is pinned onto the booking row as a snapshot: a later change to the route's base fare does not retroactively modify existing bookings. The booking's `ancillary_total_cents` begins at zero. Creating the booking increments the flight's `seats_sold` by the passenger count and increments the flight's `version` by one. A new booking's `booking_status` begins at `CONFIRMED`, with `stranded_until_date` null and `package_bundle_id` null for an air-only booking.

Ancillaries are sold against a confirmed booking. Each **AncillaryPurchase** records the owning `booking_id`, names an `ancillary_kind` of `SEAT_ASSIGNMENT`, `CHECKED_BAG`, `CARRY_ON_BAG`, or `PRIORITY_BOARDING`, and carries an `amount_cents` that must be greater than zero. A new purchase's `purchase_status` begins at `ACTIVE`, and the booking's `ancillary_total_cents` is recomputed eagerly on every ancillary mutation as the sum of `amount_cents` across that booking's purchases whose `purchase_status` is still `ACTIVE`. An agent may void a single purchase; voiding requires the purchase's `purchase_status` to be `ACTIVE` (otherwise `ERR_ANCILLARY_NOT_ACTIVE`, HTTP 409), moves it to `VOIDED`, and decrements the booking's `ancillary_total_cents` by the voided `amount_cents` — which is exactly the recompute just described.

When `booking_kind` is `PACKAGE`, the booking creation additionally builds a **PackageBundle** in the same call. The agent supplies a `hotel_offer_id`, and may optionally supply a `rental_car_offer_id` and an `attraction_offer_id`; when either optional identifier is null, that component is simply not bundled. The hotel component is always included. Each referenced **SupplierOffer** must satisfy three referential rules, and a violation of any of them rejects the booking: the offer's `component_kind` must match the slot it fills — `HOTEL` for the hotel slot, `RENTAL_CAR` for the rental car slot, `ATTRACTION_TICKET` for the attraction slot — with a mismatch producing `ERR_OFFER_WRONG_KIND`; the offer's `destination_station_id` must equal the route's destination station, with a mismatch producing `ERR_OFFER_WRONG_DESTINATION`; and the offer must be in `OPEN` status, with a withdrawn offer producing `ERR_OFFER_NOT_OPEN`. All three errors carry HTTP 422.

The bundle's `bundle_price_cents` is computed at creation as the sum of the `sell_price_cents` of the included components: first each offer's sell price is resolved and frozen at booking time, then the prices are summed in the order hotel, then rental car, then attraction, and the result is stored as integer cents with no rounding needed because every input is already integer cents. The bundle's `booking_id` ties it back to the owning booking, the booking's `package_bundle_id` is set to the new bundle, and the bundle's `bundle_status` begins at `ACTIVE`.

Supplier offers themselves are registered by a `FinanceAnalyst`. Each offer names its `supplier_code`, its `component_kind` (`HOTEL`, `RENTAL_CAR`, or `ATTRACTION_TICKET`), the `destination_station_id` of the leisure destination it serves, the `net_cost_cents` the airline owes the supplier per consumed unit, and the `sell_price_cents` the customer pays for the component inside a bundle. A new offer's `offer_status` begins at `OPEN`; its alternative status is `WITHDRAWN`.

### 3.6. Irregular Operations: Disruptions, Stranding, and Rebooking

When an `OpsController` declares a disruption on a route, the request names the `flight_instance_id` being cancelled and a `reason_code` of `WEATHER`, `MAINTENANCE`, `CREW_SHORTAGE`, or `LOW_DEMAND`. The flight must be `SCHEDULED`; otherwise the declaration is rejected with `ERR_FLIGHT_NOT_SCHEDULED`. A **DisruptionEvent** is created with its `route_id` set to the route on which the disruption was declared, its `flight_instance_id` set to the cancelled flight, and its `disruption_status` beginning at `DECLARED`, and the cancellation cascades: the flight moves to `CANCELLED` with its `cancelled_by_disruption_id` set to the new disruption's id; every crew assignment on the flight moves to `RELEASED`; and every `CONFIRMED` booking on the flight moves to `STRANDED`.

Stranding is tracked explicitly because of the single-station reality: at a station where this airline is the only scheduled carrier, a cancelled passenger cannot simply be walked to a competitor, and the next departure on the same route may be days away. The booking's `stranded_until_date` is therefore computed at cancellation time as the `flight_date` of the next `SCHEDULED` flight on the same route. The candidate set is every flight instance on the same route that is still `SCHEDULED` and whose `flight_date` is strictly later than the cancelled flight's date; cancelled and operated flights never count. The candidates are ordered by `flight_date` ascending, with ties broken by `created_at` ascending — never by id — and the head of that ordering supplies the date. If no candidate exists, `stranded_until_date` is null: the passenger is stranded with no published rescue flight.

A `CustomerService` agent rebooks a stranded passenger onto a later flight. Rebooking requires the booking to be in `STRANDED` status — any other status is rejected with `ERR_BOOKING_NOT_STRANDED` — and the request names the `target_flight_instance_id`. The target flight must be `SCHEDULED` on the same route as the original flight; a target that fails either condition is rejected with `ERR_REBOOK_FLIGHT_INVALID`. The target must have an aircraft assigned; a target with no tail is rejected with `ERR_REBOOK_NO_AIRCRAFT`. Capacity is then checked: the projected load is the target flight's current `seats_sold` plus the booking's `passenger_count`, and if that projected load is strictly greater than the assigned aircraft's `seat_capacity`, the rebook is rejected with `ERR_REBOOK_CAPACITY_EXCEEDED`; a projected load exactly equal to the seat capacity is allowed. All three rebook errors carry HTTP 409. Because rebooking is a write against the booking, the request must also carry `expected_booking_version` equal to the booking's current `version`; if the booking's version has advanced since the agent last observed it — for instance because a cancellation cascade has already moved the booking out of `STRANDED` — the rebook is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the booking's `flight_instance_id` is re-pointed to the target flight, its `stranded_until_date` is cleared, the booking moves to `STRANDED_REBOOKED`, the booking's `version` increments by one, and `seats_sold` is recomputed on both the old and the new flight. When the rebooked flight later departs and is marked operated, the booking returns from `STRANDED_REBOOKED` to `CONFIRMED`.

A disruption is fully recovered when every booking it stranded has been either rebooked or cancelled; at that point the system moves the disruption's `disruption_status` from `DECLARED` to `RECOVERED` automatically. To make that determination well-defined for synthesized cascade disruptions as well as declared ones, the system internally records, on every booking stranded by a flight cancellation, which disruption event stranded it — whether the disruption was declared through the disruptions endpoint or synthesized by a suspension cascade (§3.9). This attribution is internal bookkeeping and is never exposed in API responses. After each booking rebook and each booking cancellation, the system re-examines the disruption that stranded the booking, and when no booking attributed to that disruption remains unresolved (that is, every attributed booking is now in `STRANDED_REBOOKED` or `CANCELLED`), the disruption moves to `RECOVERED`.

### 3.7. Cancelling a Trip and Its Cascades

A customer or a `CustomerService` agent may cancel a booking in any of `CONFIRMED`, `STRANDED`, or `STRANDED_REBOOKED` status; a booking in any other status is rejected with `ERR_BOOKING_NOT_CANCELLABLE` (HTTP 409). Cancellation cascades through everything the booking owns. Every ancillary purchase on the booking moves to `VOIDED`, and the booking's `ancillary_total_cents` is recomputed to zero. The flight's `seats_sold` is decremented by the booking's `passenger_count`. And if the booking's `package_bundle_id` is set, the bundle moves from `ACTIVE` to `CANCELLED`, which in turn triggers the supplier-settlement clawback described next.

### 3.8. Supplier Settlement: Provisional Runs, Finalization, and Clawback

The airline pays each third-party supplier at the wholesale net cost for the units actually consumed, reconciled over a settlement window. A `FinanceAnalyst` issues a **SupplierSettlement** by naming the `supplier_code` and an inclusive `period_start_date` and `period_end_date`. The new settlement's `settlement_status` begins at `PROVISIONAL` with `clawback_cents` at zero, and its `gross_payable_cents` is computed under the provisional variant: it sums the `net_cost_cents` of the supplier's offer for every package bundle that consumes one of that supplier's offers, whose `bundle_status` is either `ACTIVE` or `CANCELLED`, and whose booking's flight date falls within the settlement period inclusive of both end dates.

When the period has fully passed, the analyst finalizes the settlement. Finalization requires the settlement's `settlement_status` to still be `PROVISIONAL` — otherwise the request is rejected with `ERR_SETTLEMENT_NOT_PROVISIONAL` (HTTP 409) — and requires the logical clock to be strictly after the `period_end_date`; finalizing while the period is still open is rejected with `ERR_SETTLEMENT_PERIOD_OPEN` (HTTP 422). At finalization the gross payable is recomputed under the final variant: the same window applies, but only bundles whose `bundle_status` is still `ACTIVE` at finalization are counted. Bundles that were cancelled between the provisional run and finalization are excluded from the gross, and their value lives in the settlement's `clawback_cents` instead. The two variants therefore produce different totals exactly when some bundle in the window was cancelled in between. Every counted bundle's `bundle_status` moves from `ACTIVE` to `SETTLED`, and the settlement's `settlement_status` lands at `FINALIZED`.

The clawback path runs the other way. When a bundle is cancelled while a `PROVISIONAL` settlement covering it still exists — that is, a settlement for one of the bundle's suppliers whose period covers the booking's flight date — that settlement's `clawback_cents` increases by the offer's `net_cost_cents`, and the settlement's `settlement_status` becomes `CLAWED_BACK`. A clawed-back settlement is terminal: it records that the airline is owed a refund for a bundle the provisional run had already counted.

### 3.9. Suspending, Reactivating, and Closing Routes

Seasonal suspension is the carrier's core demand-matching move, and it comes in two flavors. A window-level suspension moves a single `OPEN` window to `SUSPENDED` — the planner may attach a `suspension_reason` — and freezes every `PUBLISHED` publication in that window. Freezing a publication in turn cancels every `SCHEDULED` flight under it, and each such flight spawns its own disruption event, so window suspension strands passengers flight by flight exactly as §3.6 describes. Because one cascade can cancel a flight that an earlier-stranded booking was counting on as its rescue flight, once the cascade completes the server recomputes `stranded_until_date` by the rule in §3.6 for every booking still in `STRANDED` status on the route, so no stranded booking is left pointing at a rescue flight the same cascade cancelled. If the suspended window was the route's last `OPEN` window — that is, after the suspension every window on the route is in `SUSPENDED` or `CLOSED` — the route itself moves from `SEASONAL_ACTIVE` to `SEASONALLY_SUSPENDED` automatically, and the route's `suspended_seasons_count` increments by one.

A route-level suspension is the planner's explicit version of the same move. Suspending a route that is not `SEASONAL_ACTIVE` is rejected with `ERR_ROUTE_NOT_ACTIVE`. Otherwise the full cascade fires: every `OPEN` window on the route moves to `SUSPENDED`; every `PUBLISHED` publication in those windows moves to `FROZEN`; every `SCHEDULED` flight under those publications moves to `CANCELLED`, each via a synthesized disruption event whose `reason_code` is `LOW_DEMAND`; every `CONFIRMED` booking on those flights moves to `STRANDED` with `stranded_until_date` recomputed by the rule in §3.6; and the route's `suspended_seasons_count` increments by one. As with window-level suspension, once the cascade completes the server performs a final recomputation pass over every booking still in `STRANDED` status on the route, applying the §3.6 rule again so that no stranded booking's `stranded_until_date` references a flight the cascade itself cancelled.

A suspended route can be brought back. Reactivation requires the route to be in `SEASONALLY_SUSPENDED` — otherwise `ERR_ROUTE_NOT_SUSPENDED` — and requires a new `OPEN` season window to exist for the route, either created in the same call or already present. The route returns to `SEASONAL_ACTIVE`.

Closure is permanent and guarded. Closing a route — whether from `SEASONAL_ACTIVE` or from `SEASONALLY_SUSPENDED` — requires that no flight instance on the route remain in `SCHEDULED` status; a live flight blocks the close with `ERR_ROUTE_HAS_LIVE_FLIGHTS`. It also requires that no booking on the route remain in `CONFIRMED`, `STRANDED`, or `STRANDED_REBOOKED` status; a live booking blocks the close with `ERR_ROUTE_HAS_LIVE_BOOKINGS`. Both errors carry HTTP 409. A closed route lands in `PERMANENTLY_CLOSED`, which is terminal.

A window can also be closed outright, moving from `OPEN` or `SUSPENDED` to `CLOSED`. Closing requires that no `PUBLISHED` publication remain in the window; a live publication blocks the close with `ERR_PUBLICATIONS_STILL_LIVE`. Attempting to close a window that is not in `OPEN` or `SUSPENDED` status is rejected with `ERR_WINDOW_NOT_SUSPENDED` when the window was expected to be suspended, and symmetrically, suspending a window that is not `OPEN` is rejected with `ERR_WINDOW_NOT_OPEN`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, assignments, voids, cancellations, finalizations — return a `200 OK` status code. List and single-resource reads return `200 OK`. The table below summarizes the HTTP contract; the full request and response semantics for each operation are defined by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock | NetworkPlanner, OpsController, CustomerService, FinanceAnalyst, CrewScheduler |
| POST   | `/stations` | Register an airport | NetworkPlanner |
| GET    | `/stations` | List stations | Any of the five roles |
| GET    | `/stations/{stationId}` | Get one station | Any of the five roles |
| POST   | `/routes` | Create a leisure route | NetworkPlanner |
| GET    | `/routes` | List routes | Any of the five roles |
| GET    | `/routes/{routeId}` | Get one route | Any of the five roles |
| POST   | `/routes/{routeId}/activate` | Move a route from `PLANNING` to `SEASONAL_ACTIVE` | NetworkPlanner |
| POST   | `/routes/{routeId}/suspend` | Suspend a route with the full cascade | NetworkPlanner |
| POST   | `/routes/{routeId}/reactivate` | Return a suspended route to `SEASONAL_ACTIVE` | NetworkPlanner |
| POST   | `/routes/{routeId}/close` | Permanently close a route | NetworkPlanner |
| POST   | `/routes/{routeId}/season-windows` | Open a season window on a route | NetworkPlanner |
| GET    | `/routes/{routeId}/season-windows` | List windows for a route | Any of the five roles |
| GET    | `/routes/{routeId}/season-windows/{windowId}` | Get one window | Any of the five roles |
| POST   | `/routes/{routeId}/season-windows/{windowId}/suspend` | Suspend an open window | NetworkPlanner |
| POST   | `/routes/{routeId}/season-windows/{windowId}/close` | Close a window | NetworkPlanner |
| GET    | `/season-windows` | List season windows across routes | Any of the five roles |
| GET    | `/season-windows/{windowId}` | Get one season window by id | Any of the five roles |
| POST   | `/routes/{routeId}/publications` | Publish a seasonal day-of-week schedule | NetworkPlanner |
| GET    | `/routes/{routeId}/publications` | List publications for a route | Any of the five roles |
| GET    | `/routes/{routeId}/publications/{publicationId}` | Get one publication | Any of the five roles |
| POST   | `/routes/{routeId}/publications/{publicationId}/retire` | Retire a publication | NetworkPlanner |
| GET    | `/schedule-publications` | List publications across routes | Any of the five roles |
| GET    | `/schedule-publications/{publicationId}` | Get one publication by id | Any of the five roles |
| POST   | `/aircraft` | Register a tail | OpsController |
| GET    | `/aircraft` | List aircraft | Any of the five roles |
| GET    | `/aircraft/{aircraftId}` | Get one aircraft | Any of the five roles |
| POST   | `/aircraft/{aircraftId}/retire` | Retire a tail | OpsController |
| GET    | `/flight-instances` | List flight instances, filterable | Any of the five roles |
| GET    | `/flight-instances/{flightInstanceId}` | Get one flight instance | Any of the five roles |
| POST   | `/flight-instances/{flightInstanceId}/assign-aircraft` | Assign a tail to a flight | OpsController |
| POST   | `/flight-instances/{flightInstanceId}/mark-operated` | Mark a flight as operated | OpsController |
| POST   | `/crew-bases` | Open a crew base at a station | CrewScheduler |
| GET    | `/crew-bases` | List crew bases | Any of the five roles |
| GET    | `/crew-bases/{crewBaseId}` | Get one crew base | Any of the five roles |
| POST   | `/crew-bases/{crewBaseId}/members` | Hire a crew member into a base | CrewScheduler |
| GET    | `/crew-bases/{crewBaseId}/members` | List members of a base | Any of the five roles |
| GET    | `/crew-members` | List crew members across bases | Any of the five roles |
| GET    | `/crew-members/{crewMemberId}` | Get one crew member | Any of the five roles |
| POST   | `/flight-instances/{flightInstanceId}/crew-assignments` | Assign a crew member to a flight | CrewScheduler |
| GET    | `/flight-instances/{flightInstanceId}/crew-assignments` | List crew assignments for a flight | Any of the five roles |
| DELETE | `/flight-instances/{flightInstanceId}/crew-assignments/{assignmentId}` | Release a crew assignment | CrewScheduler |
| GET    | `/crew-assignments` | List crew assignments across flights | Any of the five roles |
| GET    | `/crew-assignments/{assignmentId}` | Get one crew assignment by id | Any of the five roles |
| POST   | `/supplier-offers` | Register a third-party offer | FinanceAnalyst |
| GET    | `/supplier-offers` | List offers | Any of the five roles |
| GET    | `/supplier-offers/{offerId}` | Get one offer | Any of the five roles |
| POST   | `/bookings` | Create an `AIR_ONLY` or `PACKAGE` booking | CustomerService |
| GET    | `/bookings` | List bookings | Any of the five roles |
| GET    | `/bookings/{bookingId}` | Get one booking | Any of the five roles |
| POST   | `/bookings/{bookingId}/rebook` | Rebook a stranded booking onto a later flight | CustomerService |
| POST   | `/bookings/{bookingId}/cancel` | Cancel a booking | CustomerService |
| GET    | `/bookings/{bookingId}/bundle` | Get the bundle for a package booking (array of 0 or 1) | Any of the five roles |
| GET    | `/package-bundles` | List package bundles across bookings | Any of the five roles |
| GET    | `/package-bundles/{bundleId}` | Get one bundle | Any of the five roles |
| POST   | `/bookings/{bookingId}/ancillaries` | Sell an ancillary against a booking | CustomerService |
| GET    | `/bookings/{bookingId}/ancillaries` | List ancillaries for a booking | Any of the five roles |
| POST   | `/bookings/{bookingId}/ancillaries/{purchaseId}/void` | Void one ancillary | CustomerService |
| GET    | `/ancillary-purchases` | List ancillary purchases across bookings | Any of the five roles |
| GET    | `/ancillary-purchases/{purchaseId}` | Get one ancillary purchase by id | Any of the five roles |
| POST   | `/routes/{routeId}/disruptions` | Declare a disruption cancelling one flight | OpsController |
| GET    | `/routes/{routeId}/disruptions` | List disruptions on a route | Any of the five roles |
| GET    | `/disruptions` | List disruptions across routes | Any of the five roles |
| GET    | `/disruptions/{disruptionId}` | Get one disruption | Any of the five roles |
| POST   | `/supplier-settlements` | Issue a provisional settlement for one supplier over a period | FinanceAnalyst |
| GET    | `/supplier-settlements` | List settlements | Any of the five roles |
| GET    | `/supplier-settlements/{settlementId}` | Get one settlement | Any of the five roles |
| POST   | `/supplier-settlements/{settlementId}/finalize` | Finalize a provisional settlement | FinanceAnalyst |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return, together with its HTTP status code. The conditions that trigger each error are defined in the narratives of §2 and §3, not here. One generic identifier, `ERR_VALIDATION` (HTTP 422), covers request-shape failures that the domain narratives do not assign a dedicated error: a missing required field, a field of the wrong type, a value outside a named enum (such as an unknown `booking_kind` or `ancillary_kind`), a non-positive quantity where a positive one is required, a malformed date or time string, a malformed or out-of-range pagination parameter, and a missing or non-integer expected-version field on the three OCC endpoints. Requests carrying extra fields not named by the request contract are not rejected; unrecognized fields are ignored.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_PUBLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_NOT_FOUND` | 404 Not Found |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_BASE_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_BUNDLE_NOT_FOUND` | 404 Not Found |
| `ERR_ANCILLARY_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISRUPTION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_PLANNING` | 409 Conflict |
| `ERR_ROUTE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUTE_NOT_SUSPENDED` | 409 Conflict |
| `ERR_NO_OPEN_SEASON` | 409 Conflict |
| `ERR_ROUTE_HAS_LIVE_FLIGHTS` | 409 Conflict |
| `ERR_ROUTE_HAS_LIVE_BOOKINGS` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_WINDOW_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PUBLICATIONS_STILL_LIVE` | 409 Conflict |
| `ERR_PUBLICATION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PUBLICATION_HAS_BOOKED_FLIGHTS` | 409 Conflict |
| `ERR_FLIGHT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_BOOKING_NOT_STRANDED` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_ANCILLARY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ASSIGNED` | 409 Conflict |
| `ERR_AIRCRAFT_HAS_LIVE_FLIGHTS` | 409 Conflict |
| `ERR_ROUTE_ENDPOINT_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PUBLISH_HORIZON_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PUBLICATION_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_FREQUENCY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_UTILIZATION_CAP_EXCEEDED` | 409 Conflict |
| `ERR_CREW_BASE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_MEMBER_INACTIVE` | 422 Unprocessable Entity |
| `ERR_OFFER_WRONG_KIND` | 422 Unprocessable Entity |
| `ERR_OFFER_WRONG_DESTINATION` | 422 Unprocessable Entity |
| `ERR_OFFER_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_REBOOK_FLIGHT_INVALID` | 409 Conflict |
| `ERR_REBOOK_NO_AIRCRAFT` | 409 Conflict |
| `ERR_REBOOK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SETTLEMENT_PERIOD_OPEN` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |


