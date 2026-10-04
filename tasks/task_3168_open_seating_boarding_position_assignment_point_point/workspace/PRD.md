# Open Seat P2P Ops API — Product Requirements Document

## 1. Introduction

A point-to-point carrier running a single fleet type cannot lean on a hub bank to absorb its own mistakes: when a tail is late on the second segment of the day, the third and fourth segments inherit that lateness, crews time out, and gates turn into chokepoints. This document specifies the API surface for an operations platform built around that reality. The system models stations, aircraft tails, crew members, day-line aircraft routings, crew pairings, passenger journeys, boarding assignments, bags, and the travel-credit ledger that flexible fares mint when plans change.

Two design commitments shape everything below. First, **boarding is open seating**: a passenger's place in the jet bridge queue is a computed product of check-in timestamp, loyalty tier, purchased upgrades, and accommodation status — not a seat map. The boarding position algorithm is the central calculation of the platform, and several other workflows (upgrade purchase, delay retiming, upgrade refund) exist primarily to nudge it. Second, **the network is point-to-point**: each tail flies a day line of legs with no hub bank structure, so disruptions propagate mechanically down the line. A delay posted against one leg recomputes slack on the rest of the tail's day, breaks crew pairings whose buffers are exhausted, and re-times boarding queues when the delay crosses a published threshold.

The audience for this document is the engineering team implementing the API. Roles are deliberately peer-style — `Passenger`, `GateAgent`, and `OpsController` — each owning a slice of the workflow. The document is organized so that global contracts come first (§2), domain rules and lifecycle narrative second (§3), and the machine-checkable endpoint and error tables last (§4, §5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The platform recognizes exactly three role names, spelled as follows: `Passenger`, `GateAgent`, `OpsController`. Any request whose role is recognized but not authorized for the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles interpret `X-User-ID` differently, and the difference is load-bearing:

- When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of the acting `Passenger` entity. Ownership checks on any resource that references a `Passenger` — a journey, a credit, an upgrade — compare the resource's `passenger_id` (or the owning journey's passenger chain) against `X-User-ID`. A passenger acting on another passenger's journey, credit, or upgrade is rejected with `ERR_FORBIDDEN`. This ownership check applies to journey check-in (both forms), journey cancel, journey change, upgrade purchase, upgrade refund, and credit redemption.
- When `X-User-Role` is `GateAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `OpsController`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

A `Passenger` registers themselves, creates their own bookings, checks in, purchases boarding upgrades, manages their own journeys (cancel, change), redeems their own travel credits, and requests refunds of their own upgrades. A `GateAgent` runs the gate: opens boarding on a leg, scans passengers aboard, accepts and offloads bags, departs and arrives legs, and runs the no-show sweep. An `OpsController` is the network-side role: they register stations, fare classes, aircraft, and crew, build routings and pairings, post disruptions, claw back credits, and drive the logical clock.

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

List endpoints accept two query parameters. `limit` caps the page size: if omitted it defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100. `offset` skips leading rows: if omitted it defaults to 0. Both parameters are validated before any list work begins.

Every list endpoint returns its rows ordered by `created_at` ascending, unless the endpoint's description in §4 explicitly pins a different ordering (for example, the boarding-order read on a leg, which sorts by boarding sequence). The `meta` block of any list response includes exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Logical Clock and Test-Drive Time

The platform runs on a server-managed logical clock rather than the host wall clock. At startup, before any clock adjustment, the logical clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall time. An `OpsController` advances the clock by setting the current UTC to a supplied `to_iso8601` instant; this is the single time source consulted by check-in windows, upgrade windows, delay floors, credit expiry sweeps, and bag-handling projections.

Advancing the clock has one automatic side effect: every `TravelCredit` whose `credit_status` is `OPEN` or `PARTIALLY_REDEEMED` and whose `expires_on` is strictly earlier than the new logical date transitions to `EXPIRED`, and its remaining balance is forfeited. The clock set operation returns the new `current_utc`.

### 2.5. Common Resource Properties and Versioning

Every entity in this document — `Station`, `FareClass`, `Passenger`, `Aircraft`, `CrewMember`, `FlightLeg`, `AircraftRouting`, `CrewPairing`, `Booking`, `PassengerJourney`, `BoardingAssignment`, `BoardingUpgrade`, `Bag`, `TravelCredit`, `CreditRedemption`, `DisruptionEvent` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at its initial value on creation and increments by exactly 1 on every mutation to the row. State transitions, side-effect-driven field updates (a posted `delay_minutes`, a recomputed `slack_minutes`, a minted `no_show_count`), and explicit writes all count as mutations and therefore bump `updated_at` and `version`.

### 2.6. Nested Resource Retrieval and Validation Order

Endpoints that address a nested path validate path identifiers from left to right. The first identifier that does not correspond to an existing resource short-circuits the request with `ERR_NOT_FOUND` (HTTP 404); later identifiers are not consulted. This left-to-right rule applies uniformly across stations, flight legs, journeys, credits, upgrades, and bags.

Beyond existence, each endpoint runs its guard checks in a fixed priority order so that competing failure modes surface deterministically. Authentication (presence and recognition of `X-User-ID` and `X-User-Role`) runs first, then role authorization, then passenger ownership on the resource in question, then path-resource existence, then the target's state precondition (`ERR_INVALID_STATE`), then business-referential rules (fleet homogeneity, routing chain, turn buffer, double-booked aircraft, crew legality, station connection), then business-safety rules (preboard eligibility, family-anchor eligibility, bag weight), then business constraints (check-in window, upgrade window, sold-out pool, duplicate upgrade, duplicate check-in, boarding capacity, bag count cap, delay floor), and finally business-fiscal rules (fare active, credit redeemable, credit expiry, change fee, upgrade refundability). When two checks could both fail, the earlier one in this ordering is the one the client sees.

### 2.7. Optimistic Concurrency Control

Three write endpoints participate in optimistic concurrency control; no others take a version field.

- The leg-scoped check-in write requires the request to carry `expected_leg_version`, the client-observed `version` of the parent `FlightLeg`. If the leg's version has advanced since the client read it — for example because a delay cascade or a retime recompute bumped the leg — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The client must re-read the leg, re-derive the boarding window, and resubmit against the current version.
- The leg-scoped boarding-upgrade purchase likewise requires `expected_leg_version`, matching the parent `FlightLeg`'s current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so the A1-A15 position counter can never double-allocate against a leg the client has not re-read.
- Credit redemption requires `expected_credit_version`, the client-observed `version` of the parent `TravelCredit`. If a compensating void or another redemption has advanced the credit's version, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the credit's current `remaining_amount_cents`.

Endpoints not listed here do not accept an expected-version field.

### 2.8. Monetary Precision and Rounding

All monetary amounts on the platform are integer cents. Upgrade pricing uses a pinned multiplicative rounding order: each multiplication step rounds down to a whole cent before the next step is applied, so the fare-class discount is applied first and then the status-tier discount, never the reverse. Ratios such as load factor are reported to two decimal places using round-half-up; the per-ramp-agent bag ratio is reported to one decimal place using round-half-up. Boarding positions and bag counts are whole integers with no fractional component.

### 2.9. Single-Fleet Homogeneity

The carrier operates one fleet type, denoted `SINGLE_FLEET`, on every aircraft and every crew member. `Aircraft.fleet_type` is always `SINGLE_FLEET`; `CrewMember.qualified_fleet` is always `SINGLE_FLEET`. Because every crew is qualified on every tail, the pairing rules need no cross-fleet qualification matrix. Any attempt to create an aircraft routing or crew pairing that references a tail or crew whose declared fleet value departs from `SINGLE_FLEET` is rejected with `ERR_FLEET_HETEROGENEITY` (HTTP 422).

### 2.10. Cascades and Aggregation-Level Side Effects

The platform's consistency model is immediate. When an `OpsController` posts a disruption, takes a tail out of service, marks a crew member unavailable, or closes a station, dependent aggregates are reconciled inside the same write. Routings containing a cancelled leg transition to `BROKEN`; pairings whose buffers are exhausted transition to `BROKEN`; bags on a cancelled leg move from `ACCEPTED` to `OFFLOADED`; assignments on a cancelled leg are voided; active upgrades on cancelled journeys are refunded; a booking whose journeys have all reached a terminal state transitions itself to `CANCELLED`. Each cascade mutates the affected row, refreshing `updated_at` and bumping `version` per §2.5.

## 3. Business Logic & Workflows

This section narrates the operational lifecycle from the network side in, then from the passenger side out. State names appear in their exact uppercase form; error IDs are named next to the workflow that raises them.

### 3.1. Building the Network: Stations, Fleet, and Crew

An `OpsController` seeds the network by registering stations. A station is identified by its three-letter `iata_code`, unique across the network, and carries a per-bag `bag_weight_limit_lbs` (default 50), a `min_connection_minutes` connection buffer (default 40) consulted by routings and pairings that connect at this station, and an informational `time_zone_offset_minutes`. On creation a station's `station_status` is `ACTIVE`. An `OpsController` may close a station by posting a status `action` of `CLOSE` to its status endpoint; from that point, any new flight leg referencing the station is rejected with `ERR_STATION_CLOSED` (HTTP 409). Posting `action` `REOPEN` returns the station to `ACTIVE`. The status change increments the station's `version`.

Fare classes are registered with a unique `code`, an `included_bags` allotment (default 2), a `change_fee_cents` per changed journey leg (default 0 — a zero fee means the fare is **flexible**), an `upgrade_discount_pct` in the range 0 to 100 (default 0), a `credit_validity_days` window (default 365) used when minting credits, a `preboard_eligible` flag (default false), and an `is_active` flag (default true). An inactive fare class rejects new bookings with `ERR_FARE_INACTIVE` (HTTP 422); journeys already booked on it are unaffected.

Aircraft are registered with a unique `tail_number`, a physical `seat_count`, a `fleet_type` that is always `SINGLE_FLEET`, and an informational `home_station_code`. A new tail enters service with `maintenance_state` equal to `SERVICEABLE`. Crew members are registered with a unique `employee_ref`, a `crew_role` of `CAPTAIN`, `FIRST_OFFICER`, or `FLIGHT_ATTENDANT`, a `qualified_fleet` of `SINGLE_FLEET`, and a `base_station_code` where all of their pairings must begin; a new crew member starts with `crew_status` `AVAILABLE`, which can later transition to `UNAVAILABLE` and back.

### 3.2. Scheduling the Day Line: Flight Legs, Routings, and Pairings

Flight legs carry a `flight_number`, references to origin and destination stations (`origin_station_id`, `destination_station_id`), a `scheduled_departure_utc`, and a `scheduled_arrival_utc` that must fall strictly after the scheduled departure. Turn planning fields ride along: `turn_target_minutes` (default 35), `gate_agent_count` (default 2), and `ramp_agent_count` (default 4), each feeding ground staffing adequacy. `capacity_seats` is the salable seat count and may not exceed the `seat_count` of whatever aircraft is assigned to fly the leg. A leg enters the world with `leg_status` `SCHEDULED`, `delay_minutes` 0, and `delay_cause` `NONE`; `boarding_start_utc`, `actual_departure_utc`, and `actual_arrival_utc` remain unset until their respective events.

Aircraft routings bind a tail to an ordered list of legs on a service `routing_date` — the tail's day line. Creation validates, in this relative order: fleet homogeneity (`ERR_FLEET_HETEROGENEITY`), then the chain rule that consecutive legs share a station — the destination of the earlier leg equals the origin of the next — and that each leg's arrival precedes the next leg's departure (`ERR_ROUTING_CHAIN_BROKEN`), then the turn-buffer rule that the gap between an earlier leg's arrival and the next leg's departure is at least the next leg's `turn_target_minutes`, with equality allowed (a touching turn is valid; a shortfall rejects creation with `ERR_ROUTING_TURN_VIOLATION`), then a temporal-overlap check that no other `ACTIVE` routing already covers the same tail on the same date with overlapping leg windows — touching endpoints are again allowed, overlaps reject with `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409) — and finally the station-connection rule that no gap falls below the connection station's `min_connection_minutes` (`ERR_STATION_CONNECTION_VIOLATION`, HTTP 422).

A routing's `slack_minutes` is computed at creation and recomputed whenever a contained leg is delayed or cancelled. For each consecutive pair of legs, the per-pair slack is the gap between the next leg's scheduled departure and the previous leg's scheduled arrival, minus the next leg's `turn_target_minutes`. Half-open semantics apply: a pair whose gap equals the turn target exactly yields a slack of zero and is valid; a negative slack rejects creation. The routing's `slack_minutes` is the minimum across all consecutive pairs. A routing is created in `routing_status` `ACTIVE`; it transitions to `BROKEN` when a covered leg is cancelled or its tail is taken out of service. The ordered legs it covers are supplied at creation as `leg_ids`, alongside the `routing_date` and the `aircraft_id` of the tail flying the line. The list endpoint for routings accepts `aircraft_id`, `routing_date`, `routing_status`, and `leg_ids` as filter parameters.

Crew pairings bind a `CrewMember` to an ordered list of legs on a `pairing_date`. The pairing is created by an `OpsController` supplying the `pairing_date`, the `crew_member_id`, and the ordered `leg_ids`; it is born in `pairing_status` `ACTIVE` and may later transition to `BROKEN` or `CLOSED`. The list endpoint accepts `crew_member_id`, `pairing_date`, `pairing_status`, and `leg_ids` as filters. Crew legality is the gating rule, checked at creation: the pairing must begin at the crew member's base station, the legs must form a connected chain (consecutive legs share a station), no per-leg gap may exceed the `MAX_CONNECTION_MINUTES` cap of 120 minutes, the total duty span from first departure to last arrival may not exceed the `MAX_DUTY_MINUTES` cap of 840 minutes (fourteen hours), the crew member must be `AVAILABLE`, and they may not already hold a pairing on an overlapping window. A violation rejects creation with `ERR_CREW_LEGALITY_VIOLATION` (HTTP 422). Station connection buffers are then honored across the pairing the same way they are for routings.

### 3.3. Selling the Journey: Bookings, Fares, and Accommodations

A `Passenger` creates a booking by supplying a unique `record_locator`, an optional `channel` (default `DIRECT`, the alternative being `AGENT`), and a list of embedded `journeys`. Each journey pins a `passenger_id`, a `flight_leg_id`, a `fare_class_id`, and a `base_fare_cents` amount that must be non-negative. Journeys are born with `journey_status` `BOOKED` and `accommodation` `NONE`, and the parent booking begins with `booking_status` `ACTIVE`, with its `journey_count` and `journey_ids` derived from the journeys under it, ordered by journey creation time ascending. The booking's `booking_id` becomes the parent reference on each journey's `booking_id` field, and the booking list read under a booking accepts a `journey_status` filter. The booking transitions to `CANCELLED` automatically when every journey under it has reached `CANCELLED` or `NO_SHOW`.

Two accommodation markers may be requested at booking time and are validated there. A journey may carry `accommodation` `PREBOARD` only when its fare class is `preboard_eligible`; otherwise creation is rejected with `ERR_PREBOARD_NOT_ELIGIBLE` (HTTP 422). A journey may instead participate in the family-boarding accommodation: one journey is the child (the passenger must be under 6 years old on the flight date, computed from `date_of_birth`), and an accompanying adult journey points at the child journey via `family_anchor_journey_id`; the accompanying passenger must have `is_min_eligible` true. An anchor that is not a qualifying child, or an accompanying passenger with `is_min_eligible` false, rejects the booking with `ERR_FAMILY_ANCHOR_INELIGIBLE` (HTTP 422).

Passengers themselves are registered with `full_name`, a `status_tier` of `NONE`, `A_LIST`, or `A_LIST_PREFERRED` (default `NONE`), an `is_min_eligible` flag (default true), and a `date_of_birth`. Newly registered passengers begin with `standing` `GOOD` and `no_show_count` 0. Reaching two `NO_SHOW` journeys flips standing to `NO_SHOW_FLAGGED`.

### 3.4. Check-In and the Boarding Position Algorithm

A `Passenger` checks in a journey either on the leg-scoped path — which carries the OCC field `expected_leg_version` per §2.7 — or on the journey-scoped convenience path, which performs the same business validations without the OCC field. Both paths require that the acting passenger own the journey (else `ERR_FORBIDDEN`), that the journey currently be in `BOOKED` (else `ERR_INVALID_STATE`, HTTP 409), that the leg be in `SCHEDULED` or `DELAYED`, and that the logical clock sit inside the check-in window: no earlier than 24 hours before the scheduled departure, and no later than 30 minutes before it, with both bounds shifted by any posted `delay_minutes`. Outside the window the request is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409). A journey already checked in rejects with `ERR_DUPLICATE_CHECKIN` (HTTP 409). Boarding capacity is enforced against the leg: if the count of `ACTIVE` boarding assignments on the leg already equals `capacity_seats`, the check-in is rejected with `ERR_BOARDING_CAPACITY_EXCEEDED` (HTTP 409). A journey carrying `accommodation` `PREBOARD` on a non-eligible fare also fails here with `ERR_PREBOARD_NOT_ELIGIBLE`. Successful check-in stamps `checked_in_at` from the logical clock, moves the journey to `CHECKED_IN`, bumps the parent leg's `version`, and creates a `BoardingAssignment` via the boarding position algorithm.

The algorithm runs in ordered phases; every passenger appears in exactly one phase, and the global boarding sequence is determined by group rank first (PREBOARD, then A, then FAMILY, then B, then C), then `boarding_position` ascending within the group, then `checked_in_at` ascending, then journey `created_at` ascending as the final tiebreak.

- **Phase 1 — PREBOARD.** Journeys whose `accommodation` is `PREBOARD` are placed in group `PREBOARD` and receive positions 1 through N ordered by `checked_in_at` ascending with `created_at` ascending as tiebreak. Their `assignment_source` is `PREBOARD_ACCOMMODATION`.
- **Phase 2 — the A1-A15 pool.** Journeys holding an `ACTIVE` `UPGRADED_BOARDING` upgrade are placed in group A at the front, in upgrade purchase order (the upgrade's `created_at` ascending). The pool's size is the smaller of 15 and the assigned aircraft's `seat_count`, so a tail with fewer than 15 physical seats shrinks the purchasable pool accordingly. Their `assignment_source` is `UPGRADE_PURCHASE`, and the granted position is recorded on the upgrade as `position_granted`.
- **Phase 3 — status priority.** Remaining `A_LIST_PREFERRED` journeys are placed into group A first, then remaining `A_LIST` journeys, each ordered by `checked_in_at` ascending with `created_at` ascending as tiebreak. Their `assignment_source` is `STATUS_PRIORITY`. Positions in group A continue numbering after the A1-A15 pool.
- **Phase 4 — regular.** Remaining journeys — the `NONE`-tier population without upgrades — fill group A until group A reaches its `GROUP_CAPACITY` of 60 positions, then overflow into group B (positions 1 through 60), then group C. Their `assignment_source` is `CHECKIN_TIME`.
- **Phase 5 — FAMILY.** Journeys with `accommodation` `FAMILY`, plus the child-and-adult pairs participating in the family accommodation, are placed in group `FAMILY`, which sits between A and B in the boarding sequence. A MIN pair — the child anchor and the accompanying adult — receives **consecutive** positions: the pair takes the position of whichever member sorts earlier by `checked_in_at` then `created_at`, and the trailing member is shifted so the two stay adjacent. Their `assignment_source` is `FAMILY_ACCOMMODATION`.

The input set to the algorithm is the leg's journeys currently in `CHECKED_IN` holding `ACTIVE` assignments, plus the leg's `ACTIVE` `UPGRADED_BOARDING` upgrades; journeys that have reached `NO_SHOW` or `CANCELLED`, and assignments already `VOIDED` or `RETIMED`, are excluded. Positions are whole integers; the algorithm produces no fractional positions. Each `BoardingAssignment` row also denormalizes its `flight_leg_id` so the boarding-order read can sort without a join, and is born with `release_reason` `NONE` and `assignment_status` `ACTIVE`. The leg-scoped boarding-order read accepts `assignment_status` and `boarding_group` as filters, and the platform-wide assignment list accepts `journey_id`, `flight_leg_id`, `assignment_status`, and `boarding_group`. The `boarding_group` value is one of `PREBOARD`, `A`, `B`, `C`, or `FAMILY`; `assignment_status` is one of `ACTIVE`, `VOIDED`, or `RETIMED`.

Assignment positions are sticky: when an assignment is voided — for whatever reason — later assignments in the same group are **not** renumbered upward to close the gap. The `release_reason` recorded on a released assignment disambiguates the cause: `JOURNEY_CANCELLED` when the passenger cancelled their own journey, `FLIGHT_CANCELLED` when the entire leg was cancelled, `UPGRADE` when an `UPGRADED_BOARDING` refund freed the purchased position, and `DELAY_RETIME` when a qualifying delay retimed the assignment — the retime path transitions the prior row to `RETIMED` and stamps the reissued row with `assignment_source` `RETIME`; `NONE` is the default at issuance.

### 3.5. Purchased Upgrades: Early Bird and Upgraded Boarding

A `Passenger` may purchase a boarding upgrade on one of their own journeys via the leg-scoped upgrade endpoint, which carries the OCC field `expected_leg_version` alongside the `journey_id` and the desired `upgrade_type`. Two upgrade types exist, identified by `upgrade_type`. `EARLY_BIRD` is the auto-check-in product and may be purchased only while the logical clock is still at least 36 hours before scheduled departure. `UPGRADED_BOARDING` is the day-of-travel A1-A15 purchase and may be purchased only once the logical clock has reached 24 hours before scheduled departure. A purchase outside its window is rejected with `ERR_UPGRADE_WINDOW_CLOSED` (HTTP 409). A journey may hold at most one `ACTIVE` upgrade of each type; a second purchase of the same type is rejected with `ERR_DUPLICATE_UPGRADE` (HTTP 409). For `UPGRADED_BOARDING`, the purchasable pool is capped at the smaller of 15 and the aircraft's `seat_count`: when the count of `ACTIVE` `UPGRADED_BOARDING` upgrades on the leg already equals that cap, the purchase is rejected with `ERR_UPGRADE_SOLD_OUT` (HTTP 409). A successful purchase creates the `BoardingUpgrade` row with `upgrade_status` `ACTIVE`, computes `price_cents`, and — for `UPGRADED_BOARDING` — grants the next A-position, records it on the upgrade as `position_granted`, and bumps the parent leg's `version`. `EARLY_BIRD` upgrades carry no `position_granted`. The platform-wide upgrade list accepts `journey_id`, `upgrade_type`, and `upgrade_status` as filters; `upgrade_status` takes values `ACTIVE`, `REFUNDED`, or `VOIDED`.

Pricing is tiered and multiplicative, with a pinned rounding order. The base price of `UPGRADED_BOARDING` is 4000 cents; the base price of `EARLY_BIRD` is 1500 cents. For `UPGRADED_BOARDING`, the fare-class discount is applied first: the base is multiplied by one hundred minus the fare's `upgrade_discount_pct`, divided by one hundred, and the result is rounded down to a whole cent. The status-tier discount is then applied to that intermediate: a passenger of `A_LIST` tier receives a 10 percent discount, `A_LIST_PREFERRED` receives 25 percent, and `NONE` receives no discount; this second multiplication is likewise rounded down to a whole cent. Because each multiplication floors before the next is applied, fare-first-then-status is not interchangeable with status-first-then-fare. For `EARLY_BIRD`, only the fare-class discount ever applies — the status-tier discount never touches it, regardless of the passenger's tier.

A passenger may refund an `UPGRADED_BOARDING` upgrade on their own journey, but only while boarding has not yet opened on the leg; `EARLY_BIRD` is never refundable. A refund request against `EARLY_BIRD`, or after boarding has opened, is rejected with `ERR_UPGRADE_NOT_REFUNDABLE` (HTTP 422). A successful refund moves the upgrade to `REFUNDED`, voids the granted assignment with `release_reason` `UPGRADE`, and reverts the journey's boarding assignment to its original `CHECKIN_TIME` position, re-issued with `assignment_source` `CHECKIN_TIME` (a retime-sourced position is not reused here). The freed A-position is **not** backfilled — later purchasers do not slide up. When a journey is cancelled, any `ACTIVE` upgrades on it transition to `REFUNDED` and the upgrade price becomes part of the credit mint; when a journey reaches `NO_SHOW`, its `ACTIVE` upgrades instead transition to `VOIDED` — the upgrade price is forfeited, with no refund and no credit component.

### 3.6. The Day of Travel: Boarding, Bags, and Departure

A `GateAgent` opens boarding on a leg; this stamps `boarding_start_utc` from the logical clock and bumps the leg's `version`. From that point, passengers present at the gate. Each successful scan moves a journey from `CHECKED_IN` to `BOARDED`. The scan requires boarding to be open on the leg, the journey to hold an `ACTIVE` assignment on the leg, and the leg to still be in `SCHEDULED` or `DELAYED`.

Bags are accepted against a journey by a `GateAgent`, who supplies the declared `weight_lbs`. The weight is checked first: if it exceeds the origin station's `bag_weight_limit_lbs`, acceptance is rejected with `ERR_BAG_OVERWEIGHT` (HTTP 422) before any fee assessment runs. The fee waterfall then computes the ordinal bag index as the count of the journey's prior bags in `ACCEPTED` or `LOADED` status, plus one. If that ordinal is at most the fare class's `included_bags`, `bag_fee_cents` is zero; beyond the allotment, the bag carries the flat `BAG_FEE_CENTS` fee of 7500 cents. A per-journey cap of `MAX_BAGS_PER_JOURNEY` — 10 bags — applies: if the journey already holds 10 bags in `ACCEPTED` or `LOADED` status, the next acceptance is rejected with `ERR_BAG_LIMIT_EXCEEDED` (HTTP 409); the comparison runs against the pre-acceptance count. A bag is born with `bag_status` `ACCEPTED` and is linked to its owning journey via `journey_id`. The bag list endpoint accepts `journey_id` and `bag_status` as filters; `bag_status` takes values `ACCEPTED`, `LOADED`, `DELIVERED`, or `OFFLOADED`. A `GateAgent` may offload an accepted bag before the leg has departed, moving it to `OFFLOADED`; a manual offload against a leg that has already departed is rejected. Bags also follow the leg's lifecycle automatically: at departure every `ACCEPTED` bag on the leg moves to `LOADED`; at arrival every `LOADED` bag moves to `DELIVERED`; on cancellation every `ACCEPTED` bag moves to `OFFLOADED`.

Departure is gated. A `GateAgent` may depart a `SCHEDULED` leg only when boarding has been opened, when no `ACTIVE` assignment on the leg still belongs to a journey stuck in `CHECKED_IN` (such journeys block departure — run the no-show sweep first to convert them), when no `CrewPairing` covering the leg is `BROKEN`, and when the aircraft assigned via an `ACTIVE` routing is `SERVICEABLE`. Departing a `DELAYED` leg adds the requirement that the logical clock has reached the scheduled departure plus the posted `delay_minutes`. Departure stamps `actual_departure_utc`, moves the leg to `DEPARTED`, and loads all `ACCEPTED` bags into `LOADED`.

The no-show sweep is the gate agent's tool for clearing the stragglers. It may be run once boarding has opened and the logical clock has reached the posted departure time — the scheduled departure plus `delay_minutes`. The sweep converts every journey still in `CHECKED_IN` to `NO_SHOW`. Each conversion increments the passenger's `no_show_count` and recomputes `standing`: a passenger reaching two no-shows is flagged `NO_SHOW_FLAGGED`. The fare treatment splits on flexibility. For a flexible fare — one whose `change_fee_cents` is zero — the no-show journey mints a `TravelCredit` for its `base_fare_cents`. For a non-flexible fare, no credit is minted; instead the journey's `no_show_penalty_cents` is set equal to its `base_fare_cents`. In both cases any `ACTIVE` upgrades on the no-show journey move to `VOIDED`, with the upgrade price forfeited. The same sweep semantics apply whether the leg is `SCHEDULED` or `DELAYED`; the posted-departure threshold is what governs.

Arrival closes the loop. A `GateAgent` arrives a `DEPARTED` leg, stamping `actual_arrival_utc` and moving the leg to `ARRIVED`. Every `BOARDED` journey on the leg moves to `COMPLETED`. Every `LOADED` bag moves to `DELIVERED`. Any `CrewPairing` covering this leg whose covered legs have all reached `ARRIVED` transitions to `CLOSED`. `ARRIVED` and `CANCELLED` are the terminal states of a leg.

### 3.7. Irregular Operations: Delays, Cancellations, and Propagation

An `OpsController` posts a disruption against a leg, choosing a `disruption_type` of `DELAY` or `CANCELLATION`, a `cause` of `WEATHER`, `INBOUND_DELAY`, `CREW`, or `MAINTENANCE`, and — for a delay — a `delay_minutes` value. The posted delay must be at least 15 minutes (the `DELAY_FLOOR_MINUTES` floor); anything shorter is rejected with `ERR_DELAY_BELOW_FLOOR` (HTTP 422). Posting a delay against a leg that has already departed is a state error. A `DELAY` post against a `SCHEDULED` leg moves it to `DELAYED`, records `delay_minutes` and `delay_cause`, and marks `delay_propagated` false (this is a directly-posted event, with `propagation_depth` zero on the `DisruptionEvent`). A subsequent `DELAY` post against an already-`DELAYED` leg is allowed only when the new `delay_minutes` is strictly greater than the current value; an equal or smaller post is rejected with `ERR_DELAY_BELOW_FLOOR`. Either form of delay post bumps the leg's `version` and triggers the propagation cascade.

When the posted `delay_minutes` reaches at least 45 minutes — the `RETIME_THRESHOLD_MINUTES` — the boarding position algorithm re-runs against the delayed boarding start. Phases 2 through 4 are recomputed: the A1-A15 pool, the status-priority block, and the regular check-in-time population are re-positioned, and the new rows are stamped with `assignment_source` `RETIME` while the previous rows move to `RETIMED`. Accommodation rows are never recomputed: `PREBOARD` and `FAMILY` assignments are preserved unchanged through a retime.

Propagation then runs in two hops, aircraft first and crew second — the crew hop reads the post-aircraft-cascade departure times, so order matters. In the aircraft hop, for every `ACTIVE` routing containing the delayed leg, the routing's `slack_minutes` is recomputed, and for the immediately-following leg in that routing, the slack between the delayed leg's arrival and the follower leg's scheduled departure is re-evaluated. When the follower's available slack — its scheduled departure minus the delayed leg's scheduled arrival minus the follower's own `turn_target_minutes` — is smaller than the posted delay, a system `DisruptionEvent` is posted on the follower leg with `cause` `INBOUND_DELAY`, `delay_propagated` true, and `propagation_depth` one greater than the parent's; this drives the follower leg from `SCHEDULED` to `DELAYED` with a propagated delay equal to the parent's delay minus the consumed slack. The hop recurses down the line.

In the crew hop, every `ACTIVE` pairing covering the delayed leg is examined. If the new departure time makes the next covered leg's scheduled departure unreachable given the connection station's `min_connection_minutes` buffer, the pairing transitions to `BROKEN`, and the pairing's next covered leg — if it is still `SCHEDULED` — receives a system `DELAY` event with `cause` `CREW` and `propagation_depth` one greater, driving it to `DELAYED`. Propagation is depth-capped at 3 (`PROPAGATION_DEPTH_CAP`): a leg whose propagated event would exceed depth 3 is skipped, and a leg already `DELAYED` by an earlier event is not re-propagated — the first posted delay wins for propagation bookkeeping, while later direct posts use the delayed-to-delayed transition described above. The full chain — direct post, aircraft-hop downstream leg, crew-hop leg — can therefore reach depth 3 but no further.

Cancelling a leg, whether it is `SCHEDULED` or `DELAYED`, runs a wider cascade. Every journey on the leg in `BOOKED` or `CHECKED_IN` moves to `CANCELLED`, and for each a `TravelCredit` is minted covering the `base_fare_cents` plus the `price_cents` of any `ACTIVE` upgrades on the journey — those upgrades move to `REFUNDED`. Every `ACTIVE` `BoardingAssignment` on the leg moves to `VOIDED` with `release_reason` `FLIGHT_CANCELLED`. Every `ACTIVE` routing containing the leg transitions to `BROKEN`, with downstream legs receiving propagated delay events (cause `INBOUND_DELAY`) when their slack is exhausted. Every `ACTIVE` pairing covering the leg transitions to `BROKEN`. Every `ACCEPTED` bag on the leg moves to `OFFLOADED`. The leg's `version` increments.

Taking a tail out of service — an `OpsController` posting maintenance `action` `TAKE_OUT_OF_SERVICE` — requires that the tail have no legs that are `DEPARTED` but not yet `ARRIVED`; otherwise the request is a state error. The tail's `maintenance_state` moves to `OUT_OF_SERVICE`, its `version` bumps, and every `ACTIVE` routing for the tail transitions to `BROKEN` with downstream legs receiving propagated delay events with cause `MAINTENANCE` where slack is exhausted. Posting `action` `RETURN_TO_SERVICE` reverses the state without further cascade. Marking a crew member unavailable — availability `action` `MARK_UNAVAILABLE`, moving `crew_status` from `AVAILABLE` to `UNAVAILABLE` — similarly breaks every `ACTIVE` pairing they hold, with crew-cause propagation to the next covered leg; `action` `MARK_AVAILABLE` reverses only the crew member's own status, returning them to `AVAILABLE`. A routing or pairing that has reached `BROKEN` is terminal.

### 3.8. Travel Credits: Minting, Redeeming, and Clawback

The credit ledger exists because flexible fares promise that cancelled or disrupted travel becomes future travel, not lost revenue. A `TravelCredit` is minted with a `passenger_id` owner, a `source_journey_id` identifying the journey whose cancellation, no-show, or change produced it, an `initial_amount_cents` greater than zero, and a `remaining_amount_cents` that begins equal to the initial amount and is decremented by redemptions, never below zero. The credit's `expires_on` is the flight leg's service date plus the fare class's `credit_validity_days`. A fresh credit starts in `OPEN` status.

The minted amount is computed with a pinned evaluation order, because cancellation interacts with any redemptions already paying the journey. Step one: any `ACTIVE` `CreditRedemption` paying the journey is voided, and each source credit's `remaining_amount_cents` is restored by the redemption amount — this is the compensation path, and it can move a credit from `PARTIALLY_REDEEMED` back to `OPEN`. Step two: the minted amount is computed from the journey's own fields only — the `base_fare_cents` plus the sum of `price_cents` across the journey's `ACTIVE` upgrades — and the new credit never draws from the balances restored in step one. Step three: the minted amount is floored at zero. The non-flexible no-show variant mints nothing: the journey's `no_show_penalty_cents` carries the forfeiture instead.

Redemption spends a credit against a specific journey in `BOOKED` status. The passenger supplies the target `journey_id`, the `amount_cents` to apply, and the OCC field `expected_credit_version` per §2.7. The credit must be redeemable: a credit that is `EXPIRED`, `VOID`, or already `REDEEMED`, or an `amount_cents` exceeding `remaining_amount_cents`, is rejected with `ERR_CREDIT_EXHAUSTED` (HTTP 422). Separately, if the logical date has passed `expires_on`, the redemption is rejected with `ERR_CREDIT_EXPIRED` (HTTP 410). A successful redemption creates a `CreditRedemption` row with `redemption_status` `ACTIVE`, decrements `remaining_amount_cents`, and bumps the credit's `version`. The redemption row records its parent credit through `credit_id` and the journey it pays through `journey_id`; the redemption list endpoint accepts `credit_id`, `journey_id`, and `redemption_status` as filters, where `redemption_status` is `ACTIVE` or `VOIDED`. The credit's status tracks the balance: a redemption that leaves a positive remainder moves `OPEN` to `PARTIALLY_REDEEMED` (or keeps it there), while a redemption that exactly consumes the remaining balance moves the credit to `REDEEMED`. The expiry sweep driven by the logical clock (§2.4) moves `OPEN` and `PARTIALLY_REDEEMED` credits whose `expires_on` has passed to `EXPIRED`, forfeiting the remainder.

An `OpsController` may claw back a credit by voiding it, but only when no `ACTIVE` redemptions exist against it; the credit moves to `VOID`. When a journey change or cancellation voids an `ACTIVE` redemption, the redemption moves to `VOIDED` and the source credit's `remaining_amount_cents` is restored by the redemption amount, returning a `PARTIALLY_REDEEMED` credit to `OPEN` when the restoration covers all prior redemptions.

### 3.9. Changing a Journey

A `Passenger` may change the flight or fare on their own journey while it is still in `BOOKED`, supplying the `new_flight_leg_id`, the `new_fare_class_id`, and the `new_base_fare_cents`. Both the old and new legs must be undeparted. Flexible fares — those with `change_fee_cents` zero — change free. Non-flexible fares require the change fee to be payable; a change attempted without satisfying the fee is rejected with `ERR_CHANGE_FEE_UNPAID` (HTTP 422), and on a non-flexible fare a downgrade residual — the difference when the new fare is lower than the old — is forfeited rather than credited. On flexible fares, a downgrade residual is converted into a minted `TravelCredit` per the minting rules of §3.8. The change voids any `ACTIVE` `CreditRedemption` paying the journey and restores the source credits' balances as compensation, following the pinned order in §3.8.

### 3.10. Turn Planning and Ground Staffing

The turn-projection read on a leg answers a forward-looking question: given what we know now, will this turn make its target? The projection is built from journeys on the leg in `BOOKED` or `CHECKED_IN` (cancelled and no-show journeys are excluded). Projected bags are the sum of two parts: for each such journey, the count of that journey's currently `ACCEPTED` bags, plus — for each `BOOKED` journey — the fare class's `included_bags` as an expected-but-not-yet-checked allowance; the total is capped at twice the leg's `capacity_seats`. Bag handling contributes one minute per projected bag on top of a base of 12 minutes (`TURN_BASE_MINUTES`). Passenger processing contributes `pax_minutes`, computed by taking the count of booked journeys, multiplying by 18 seconds per passenger, and rounding up to a whole minute. When the leg currently carries any posted delay, a 5-minute risk buffer (`DELAY_RISK_BUFFER_MINUTES`) is added; an on-time leg gets no buffer. The projected turn in minutes is the base plus bag minutes plus pax minutes plus the buffer, and the projection reports `turns_slip` true when that total exceeds the leg's `turn_target_minutes`. All values are integer minutes.

Once the leg has departed, the same read switches to a realized view: actual `LOADED` bag count and actual `BOARDED` passenger count replace the projections, and no buffer is applied — the realized view answers "did we make the turn" rather than "will we".

The staffing-adequacy read is the companion view, consulted when a turn slips. The leg's `load_factor` is the count of booked journeys divided by `capacity_seats`, reported to two decimal places with round-half-up. `staff_units` is the sum of the leg's `gate_agent_count` and `ramp_agent_count`. `bags_per_ramp_agent` is the projected bag count divided by the ramp agent count — with a division-by-zero guard that treats zero ramp agents as one — reported to one decimal place with round-half-up. The leg is flagged `understaffed` when either condition holds: `staff_units` falls below the required 5 units (so exactly 5 units is adequate), or the load factor reaches at least 0.90 — the 0.90 boundary itself triggers — while at the same time `bags_per_ramp_agent` exceeds 15 (so exactly 15.0 bags per ramp agent is adequate). The turn-projection read also surfaces the `understaffed` flag alongside `projected_turn_minutes`, `projected_bags`, `pax_minutes`, `turns_slip`, `load_factor`, and `bags_per_ramp_agent`, so gate leads see staffing risk in the same glance as the turn risk.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. All endpoints are mounted under the `/ops` prefix. Request and response bodies for each endpoint are reconstructed from the workflow narratives in §3; the table below is intentionally minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ops/stations` | Create a station | OpsController |
| GET | `/ops/stations/{station_id}` | Get a station | OpsController, GateAgent, Passenger |
| GET | `/ops/stations` | List stations (filter by `station_status`) | OpsController, GateAgent, Passenger |
| POST | `/ops/stations/{station_id}/status` | Close or reopen a station | OpsController |
| POST | `/ops/fare-classes` | Create a fare class | OpsController |
| GET | `/ops/fare-classes/{fare_class_id}` | Get a fare class | OpsController, GateAgent, Passenger |
| GET | `/ops/fare-classes` | List fare classes (filter by `is_active`) | OpsController, GateAgent, Passenger |
| POST | `/ops/passengers` | Register a passenger | Passenger |
| GET | `/ops/passengers/{passenger_id}` | Get a passenger (self or staff) | Passenger, GateAgent, OpsController |
| POST | `/ops/aircraft` | Register an aircraft tail | OpsController |
| GET | `/ops/aircraft/{aircraft_id}` | Get an aircraft | OpsController, GateAgent |
| GET | `/ops/aircraft` | List aircraft (filter by `maintenance_state`) | OpsController, GateAgent |
| POST | `/ops/aircraft/{aircraft_id}/maintenance` | Take tail out of service / return to service | OpsController |
| POST | `/ops/crew-members` | Register a crew member | OpsController |
| GET | `/ops/crew-members/{crew_member_id}` | Get a crew member | OpsController, GateAgent |
| POST | `/ops/crew-members/{crew_member_id}/availability` | Mark crew available/unavailable | OpsController |
| POST | `/ops/flight-legs` | Create a flight leg | OpsController |
| GET | `/ops/flight-legs/{leg_id}` | Get a flight leg | OpsController, GateAgent, Passenger |
| GET | `/ops/flight-legs` | List flight legs (filter by status, origin, destination) | OpsController, GateAgent, Passenger |
| GET | `/ops/flight-legs/{leg_id}/journeys` | Journeys on a leg | OpsController, GateAgent |
| GET | `/ops/flight-legs/{leg_id}/boarding-assignments` | Assignments on a leg in boarding order (group rank, position, check-in time, creation time) | OpsController, GateAgent, Passenger |
| GET | `/ops/flight-legs/{leg_id}/disruptions` | Disruption events on a leg, ordered `posted_utc` ascending then `created_at` ascending | OpsController, GateAgent |
| POST | `/ops/flight-legs/{leg_id}/disruptions` | Post a DELAY or CANCELLATION; triggers propagation and cancellation cascades | OpsController |
| POST | `/ops/flight-legs/{leg_id}/boarding/open` | Open boarding on a leg | GateAgent |
| POST | `/ops/flight-legs/{leg_id}/no-show-sweep` | Convert still-CHECKED_IN journeys to NO_SHOW | GateAgent |
| POST | `/ops/flight-legs/{leg_id}/depart` | Depart a leg | GateAgent |
| POST | `/ops/flight-legs/{leg_id}/arrive` | Arrive a leg | GateAgent |
| POST | `/ops/flight-legs/{leg_id}/check-ins` | Check a journey in on this leg (OCC on leg version) | Passenger |
| POST | `/ops/flight-legs/{leg_id}/upgrades` | Purchase EARLY_BIRD or UPGRADED_BOARDING (OCC on leg version) | Passenger |
| GET | `/ops/flight-legs/{leg_id}/turn-projection` | Projected vs realized turn minutes and staffing adequacy | OpsController, GateAgent |
| GET | `/ops/flight-legs/{leg_id}/staffing-check` | Ground staffing adequacy detail | OpsController, GateAgent |
| POST | `/ops/aircraft-routings` | Create an aircraft day-routing | OpsController |
| GET | `/ops/aircraft-routings/{routing_id}` | Get an aircraft routing | OpsController, GateAgent |
| GET | `/ops/aircraft-routings` | List routings (filter by aircraft, date, status) | OpsController, GateAgent |
| POST | `/ops/crew-pairings` | Create a crew pairing over ordered legs | OpsController |
| GET | `/ops/crew-pairings/{pairing_id}` | Get a crew pairing | OpsController, GateAgent |
| GET | `/ops/crew-pairings` | List pairings (filter by crew member, date, status) | OpsController, GateAgent |
| POST | `/ops/bookings` | Create a booking with embedded journeys | Passenger |
| GET | `/ops/bookings/{booking_id}` | Get a booking | Passenger, GateAgent, OpsController |
| GET | `/ops/bookings/{booking_id}/journeys` | Journeys under a booking | Passenger, GateAgent, OpsController |
| GET | `/ops/journeys/{journey_id}` | Get a passenger journey | Passenger, GateAgent, OpsController |
| GET | `/ops/journeys` | List journeys (filter by booking, passenger, leg, fare class, family anchor, status) | Passenger, GateAgent, OpsController |
| GET | `/ops/journeys/{journey_id}/boarding-assignments` | Assignment history for a journey, ordered `created_at` descending | Passenger, GateAgent, OpsController |
| GET | `/ops/journeys/{journey_id}/upgrades` | Upgrades on a journey, ordered `created_at` ascending | Passenger, GateAgent, OpsController |
| GET | `/ops/journeys/{journey_id}/bags` | Bags checked on a journey | Passenger, GateAgent, OpsController |
| POST | `/ops/journeys/{journey_id}/check-in` | Direct check-in on a journey (non-OCC convenience path) | Passenger |
| POST | `/ops/journeys/{journey_id}/cancel` | Cancel a journey | Passenger |
| POST | `/ops/journeys/{journey_id}/change` | Change flight/fare on a journey | Passenger |
| POST | `/ops/journeys/{journey_id}/bags` | Check a bag on a journey | GateAgent |
| POST | `/ops/bags/{bag_id}/offload` | Offload an accepted bag before departure | GateAgent |
| POST | `/ops/boarding/scan` | Gate scan: mark a checked-in journey BOARDED | GateAgent |
| POST | `/ops/boarding-upgrades/{upgrade_id}/refund` | Refund an UPGRADED_BOARDING purchase | Passenger |
| GET | `/ops/credits/{credit_id}` | Get a travel credit | Passenger, OpsController |
| GET | `/ops/credits` | List credits (filter by passenger, status, source journey) | Passenger, OpsController |
| POST | `/ops/credits/{credit_id}/redeem` | Redeem credit toward a journey fare (OCC on credit version) | Passenger |
| POST | `/ops/credits/{credit_id}/void` | Admin clawback of a credit with no ACTIVE redemptions | OpsController |
| GET | `/ops/credits/{credit_id}/redemptions` | Redemptions against a credit, ordered `created_at` ascending | Passenger, OpsController |
| GET | `/ops/boarding-assignments` | List boarding assignments (filter by journey, leg, status, group) | Passenger, GateAgent, OpsController |
| GET | `/ops/boarding-upgrades` | List boarding upgrades (filter by journey, type, status) | Passenger, GateAgent, OpsController |
| GET | `/ops/bags` | List bags (filter by journey, status) | GateAgent, OpsController |
| GET | `/ops/credit-redemptions` | List credit redemptions (filter by credit, journey, status) | Passenger, OpsController |
| GET | `/ops/disruption-events` | List disruption events (filter by leg, type) | OpsController, GateAgent |
| POST | `/ops/_clock/set_current_utc` | Set the server's logical clock | OpsController |
| GET | `/ops/boarding-assignments/{assignment_id}` | Get a boarding assignment | Passenger, GateAgent, OpsController |
| GET | `/ops/boarding-upgrades/{upgrade_id}` | Get a boarding upgrade | Passenger, GateAgent, OpsController |
| GET | `/ops/bags/{bag_id}` | Get a bag | GateAgent, OpsController |
| GET | `/ops/credit-redemptions/{redemption_id}` | Get a credit redemption | Passenger, OpsController |
| GET | `/ops/disruption-events/{event_id}` | Get a disruption event | OpsController, GateAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows that raise them; this table is the canonical ID-to-status map.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 |
| `ERR_DUPLICATE_CHECKIN` | 409 |
| `ERR_BOARDING_CAPACITY_EXCEEDED` | 409 |
| `ERR_UPGRADE_WINDOW_CLOSED` | 409 |
| `ERR_UPGRADE_SOLD_OUT` | 409 |
| `ERR_DUPLICATE_UPGRADE` | 409 |
| `ERR_UPGRADE_NOT_REFUNDABLE` | 422 |
| `ERR_PREBOARD_NOT_ELIGIBLE` | 422 |
| `ERR_FAMILY_ANCHOR_INELIGIBLE` | 422 |
| `ERR_BAG_OVERWEIGHT` | 422 |
| `ERR_BAG_LIMIT_EXCEEDED` | 409 |
| `ERR_DELAY_BELOW_FLOOR` | 422 |
| `ERR_FARE_INACTIVE` | 422 |
| `ERR_CREDIT_EXHAUSTED` | 422 |
| `ERR_CREDIT_EXPIRED` | 410 |
| `ERR_CHANGE_FEE_UNPAID` | 422 |
| `ERR_FLEET_HETEROGENEITY` | 422 |
| `ERR_ROUTING_CHAIN_BROKEN` | 422 |
| `ERR_ROUTING_TURN_VIOLATION` | 422 |
| `ERR_AIRCRAFT_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_LEGALITY_VIOLATION` | 422 |
| `ERR_STATION_CONNECTION_VIOLATION` | 422 |
| `ERR_STATION_CLOSED` | 409 |
