# Baggage Handling Operations API — Product Requirements Document

## 1. Introduction

Thirty million bags a year move through a hub's in-line sortation system, and each one passes through a dozen custody hand-offs, two independent screening decisions, and at least one hard deadline before it reaches an aircraft. The Baggage Handling Operations API is the operational system of record for that journey. It covers bag acceptance and tag printing at the ticket counter and curb, weight and size screening with interline routing determination, the in-line explosive-detection flow with alarm resolution and manual inspection queues, sortation into make-up areas under flight-bank timing and minimum connect time constraints, transfer-bag handling for connecting itineraries with the rush-bag procedure, scan-point capture at every induction point, load and delivery with tracking visibility back to the passenger, mishandled bag reporting with delivery arrangement and compensation, oversize, fragile and special-item handling including sports equipment and mobility devices, and system outage contingency with manual sortation.

The system's defining difficulty is that a bag occupies two independent state dimensions at once. Custody — where the bag physically is in the handling chain — advances on one axis, while screening clearance advances on another, and the two axes constrain each other: a bag may not be sorted, made up, loaded or delivered while its screening clearance is unresolved. Beside those two axes sit several more clocks and ledgers that all move together. Make-up areas hand out capacity in bucketed intervals; screening lanes hand out windows in half-open intervals with no buffer; flights publish a sortation window that opens two hours before departure and slams shut forty-five minutes before it; stations carry an occupancy posture derived from their live bag count and their free make-up slots; and the baggage service office carries a liability ledger that must partition cleanly between open and settled money at every instant.

This document specifies the API contract — resource shapes, state machines, calculation rules, validation priorities, endpoints and error identifiers — for a full implementation of the baggage handling operations platform. It is written for the engineering team that will build the service: the business rules are stated as prose requirements, and the structural contracts (response envelope, pagination, common resource properties, concurrency guarding) are stated precisely enough to be implemented without further clarification.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, invariants and boilerplate that apply across the whole API. Subsection 2.2 is a fixed response contract; the remaining subsections are the domain's cross-cutting principles, drawn from the system's calculations, validations and state machines.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting capacity. A request missing either header, or carrying a role value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` and an HTTP 401 status. A request whose role does not permit the requested operation, or an entity-backed role acting on a resource it does not own, is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403.

The system recognizes eight roles, spelled exactly as follows: `PlatformAdmin`, `AcceptanceAgent`, `SortationAgent`, `Screener`, `LoadAgent`, `TransferAgent`, `BaggageServiceAgent`, and `Passenger`. Their spheres of authority are:

- `PlatformAdmin` — the airport operations administrator. Owns the reference data (stations, airlines, flights, make-up areas, screening lanes), the logical clock, and the outage and ops-run checkpoints.
- `AcceptanceAgent` — the ticket-counter and curbside acceptance agent. Accepts bags, prints tags, weighs and screens weight and size, and registers special items.
- `SortationAgent` — the sortation system operator. Assigns make-up intervals, works the sortation queue and monitors station posture.
- `Screener` — the in-line explosive-detection screener. Raises and resolves screening alarms, works the manual inspection queue, and records anomaly notes.
- `LoadAgent` — the make-up and ramp load agent. Loads bags, delivers them to the passenger or reclaim belt, and offloads mis-loaded bags.
- `TransferAgent` — the transfer-bag desk agent. Confirms connecting itineraries against minimum connect time, declares the rush-bag procedure and re-accommodates missed connections.
- `BaggageServiceAgent` — the central baggage service office agent. Files and works mishandled bag reports, arranges deliveries, files and decides claims, and pays compensation.
- `Passenger` — the travelling passenger, whose visibility is limited to their own bag tracking trail and reports.

For seven of these roles — `PlatformAdmin`, `AcceptanceAgent`, `SortationAgent`, `Screener`, `LoadAgent`, `TransferAgent` and `BaggageServiceAgent` — the identity is opaque: when `X-User-Role` is one of them, `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server does not compare it to any entity's `id`. The server may nevertheless record it where a workflow stamps the acting operator, for example as `resolved_by` on a screening event, as `assigned_to` on a manual inspection task, or as `decided_by` on a claim.

The `Passenger` role is the exception, and it is entity-backed by the `Bag` row's `passenger_ref`: when `X-User-Role` is `Passenger`, `X-User-ID` is the passenger reference of the acting bag, and ownership checks compare a resource's `passenger_ref` to `X-User-ID`. A passenger reading a bag, its scan trail, its reports or its deliveries may only reach rows whose `passenger_ref` matches their own identity; anything else is rejected with `ERR_FORBIDDEN_ROLE`.

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

List endpoints accept a `limit` query parameter giving the maximum number of items to return; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. A second query parameter, `offset`, gives the number of items to skip and defaults to 0. Unless a filter implies otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order.

The pagination-related fields `limit`, `offset`, `total_count` and `has_more` are reported in the `meta` object of the response envelope for list endpoints. Non-list responses omit them.

### 2.4. Common Resource Properties

Every principal resource in the system — `Station`, `Airline`, `Flight`, `MakeupArea`, `ScreeningLane`, `Bag`, `BagScan`, `ScreeningEvent`, `ManualInspectionTask`, `Connection`, `SpecialItem`, `MishandledReport`, `Claim` and `Delivery` — carries the same four system-managed attributes:

- `id` (string) — a unique, server-minted UUID. It carries no type prefix and no domain-specific formatting; nothing about the resource's kind may be inferred from the identifier.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row's own properties or derived counters.
- `version` (integer) — a system-managed counter that increments by one on every modification to the row. It is the anchor of the optimistic concurrency mechanism described in §2.12.

All fourteen principal resources listed above carry both `updated_at` and `version`; there are no entities in this system that omit them. Derived attributes — a bag's `priority_score`, a station's `posture`, a flight's `makeup_ready` — are mutations like any other: when the server recomputes one, the owning row's `updated_at` refreshes and its `version` increments.

Two resources publish timestamps under domain names in addition to the standard pair, and the distinction matters to callers. A `Bag` additionally exposes `assigned_makeup_utc`, `loaded_utc` and `delivered_utc`; a `ScreeningEvent` exposes `start_utc` and `end_utc`; a `Delivery` exposes `scheduled_utc` and `delivered_utc`; a `Connection` exposes `rush_declared_utc`. These are business instants, not audit fields, and they are only populated when the corresponding business event has occurred — a bag that has not been sorted has no `assigned_makeup_utc`, and a screening event with no decision behind it has no `resolved_by`.

### 2.5. Nested Resource Retrieval and Identifier Validation

Several collections are reached through their parent: the make-up areas, flights, bags, inspections and reports of a station; the screenings, connections, special items, reports and deliveries of a bag; the flights, bags and connections of an airline or a make-up area; and the screening events and inspection tasks of a screening event. When a request path carries more than one resource identifier, the server validates them left to right and rejects immediately on the first identifier that does not resolve. A request naming a bag that does not exist, or one scoped to a different station, is rejected with `ERR_BAG_NOT_FOUND`; a request naming a report that does not exist with `ERR_REPORT_NOT_FOUND`; a request naming a flight that does not exist with `ERR_FLIGHT_NOT_FOUND`. This ordered validation runs ahead of any business check, so a request that would also fail a state or capacity rule is reported first as a missing-resource failure.

The same left-to-right discipline applies to body-supplied foreign keys on creation calls. `ERR_BAG_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and `ERR_FLIGHT_NOT_FOUND` are the three existence failures the system publishes, and they all carry HTTP 404.

### 2.6. Station Posture and Sorter Capacity

An airport administrator opens a station envelope by supplying its three-letter IATA `code`, a display `name`, and the design capacity of its in-line sortation system in the field `sorter_capacity_bags`. The `code` is unique across stations and must be exactly three capital letters; the station's posture — the field `posture`, one of `OPEN`, `CONGESTED` or `SUSPENDED` — is derived from how full the station and its make-up areas actually are. The derivation runs in a strict order. First, if the station's `active_bag_count` has reached or exceeded `sorter_capacity_bags`, the posture is `SUSPENDED`. Otherwise, if the station has no active make-up capacity at all — the total of `capacity_slots` across its `ACTIVE` make-up areas is zero — the posture is `OPEN`, a guard that prevents a station with no configured make-up areas from ever reading as congested. Otherwise, if the free make-up slots remaining across the station's active areas have fallen to fifteen percent of total capacity or below — where the threshold is computed as that fraction of the total rounded up to a whole slot, so two total slots yield a threshold of one and three total slots also yield a threshold of one — the posture is `CONGESTED`. In every other case the posture is `OPEN`.

The bag count that drives this rule is the count of the station's bags whose custody status is one of `ACCEPTED`, `SCREENING`, `SORTED`, `IN_MAKEUP`, `LOADED` or `HELD`; bags that have been `DELIVERED` or `OFFLOADED` are outside the station envelope and are not counted. A bag held at screening still counts as physically present.

`CONGESTED` is advisory: it drives escalation of overdue inspection work and it feeds the priority score, but it does not by itself block sortation, loading or delivery. `SUSPENDED` is not advisory. While a station reads `SUSPENDED` — whether because a sortation outage is active or because its sorter is full — every sortation, loading and delivery write against a bag of custody at that station is refused with `ERR_STATION_SUSPENDED` and HTTP 409, and that refusal is applied before any state precondition is examined. The only writes that may proceed against a suspended station are the outage declaration and clearance calls themselves.

A station also carries an outage flag pair. `outage_active` is true while a sortation-system outage is declared and unresolved, and `outage_started_utc` records the instant it was declared, remaining null while no outage is active.

### 2.7. Make-Up Area Capacity and the Interval Bucket Rule

A `MakeupArea` is the physical staging lane a sorted bag is sent to, and it publishes a slot ledger rather than a simple counter. The area is created against a station with a `station_id`, a `code` such as `MA-3`, a `capacity_slots` maximum, and a `buffer_minutes` changeover buffer that defaults to 15 minutes; it begins in status `ACTIVE` with no slots occupied. The field `capacity_slots` is the maximum number of bags that may hold concurrent sortation intervals in the area. The field `occupied_slots` counts the bags whose custody status is `SORTED` or `IN_MAKEUP` and whose `makeup_area_id` is this area — note that a bag still merely sorted already occupies a slot for the area it is destined to. The field `released_slots` counts the bags that still carry this `makeup_area_id` but have moved on to `LOADED`, `OFFLOADED`, `DELIVERED` or `HELD`. Together the two halves form the area's slot ledger, and `free_slots` reports `capacity_slots` minus `occupied_slots` as a plain integer.

Capacity is granted in identity buckets rather than as a continuous resource. Each area declares a changeover buffer in `buffer_minutes`, and a claim on the area is evaluated as membership in the occupied-interval list at the area's buffer granularity: the requested interval is the half-open span beginning at the requested induction instant floored to the buffer granularity and ending one interval-length later. Any existing occupied interval that falls in the same identity bucket conflicts with the claim regardless of how far apart the two intervals actually are, and the area may never hold more than `capacity_slots` distinct occupied identity buckets. A claim that collides is rejected with `ERR_MAKEUP_SLOT_CONFLICT` (HTTP 409), and an attempt to sort into an area whose `status` is `CLOSED` is rejected with `ERR_MAKEUP_AREA_CLOSED` (HTTP 409).

### 2.8. Screening Lane Windows

A `ScreeningLane` is an explosive-detection line with a `lane_code` such as `EDS-2`, a `status` of `ACTIVE` or `OFFLINE` — `ACTIVE` when the lane is first created, and `OFFLINE` once it is taken out of service — and a derived `last_event_end_utc` recording the latest `end_utc` among its non-`FAILED` screening events, or null when the lane has hosted none. Lanes are governed by a stricter timing rule than make-up areas. A screening window is the half-open interval from a supplied `start_utc` to twenty minutes later, and it is the strict half-open span `[start_utc, end_utc)` with no changeover buffer: a lane may host a back-to-back window that starts at exactly the instant another window ends, and that adjacency is legal. What the lane may not do is host two different non-`FAILED` windows in the same twenty-minute identity bucket, where the bucket is derived by flooring the window's start instant to twenty-minute granularity. The lane's status must also be `ACTIVE`; no new window may be opened on a lane reading `OFFLINE`. Both refusals — `ERR_LANE_OFFLINE` and `ERR_LANE_INTERVAL_CONFLICT` — carry HTTP 409.

Taking a lane out of service or returning it to service affects only future windows: windows already open on the lane when it goes offline continue unaffected.

### 2.9. Sortation Windows and the Flight Timeline

Every `Flight` publishes three instants. `scheduled_departure_utc` is the planned departure; `sortation_open_utc` is derived as exactly 120 minutes before it and is the earliest instant a bag may be inducted for that flight; `sortation_close_utc` is derived as exactly 45 minutes before it and is the latest instant a bag may be inducted for that flight. Any change to the scheduled departure recomputes both boundaries from the new instant.

Induction and loading are refused once the current logical clock instant has passed `sortation_close_utc`, with `ERR_SORTATION_WINDOW_CLOSED` (HTTP 409). Assignment onto a flight is refused unless the flight's `status` is `SCHEDULED` or `SORT_OPEN`, with `ERR_FLIGHT_NOT_SORTING` (HTTP 409). A bag with no `flight_id` at all has no sortation window to induct against and is refused with `ERR_FLIGHT_NOT_ASSIGNED` (HTTP 409). The inverse deadline governs departure: a flight may not be marked departed before the current clock instant has reached its `sortation_close_utc`, and an attempt to do so is refused with `ERR_SORTATION_WINDOW_OPEN` (HTTP 409). A bag whose flight has not reached `DEPARTED` may not be marked delivered, which is refused with `ERR_FLIGHT_NOT_DEPARTED` (HTTP 409).

A flight also exposes `bank_code`, the departure bank the flight belongs to, and `makeup_ready`, a derived flag covered in §2.11. Its `loaded_bag_count` is the count of its bags whose custody status is `LOADED`.

### 2.10. Monetary Values, Rounding and Precision

All monetary amounts in the system are integers in cents; there are no fractional currency values anywhere in this API. Where a calculation produces a non-integral intermediate value, the system applies `round_half_up` at the point the scaffold's rule pins the rounding, and every monetary field is stored and returned as an integer number of cents with zero decimal places.

Rounding position is not incidental here — several rules pin it explicitly and the results differ depending on order:

- For the excess-weight fee, the measured weight is first rounded half-up to the nearest whole pound, and only then is the pound ceiling division over the threshold performed. The pound rounding is never applied after the grouping.
- For the handling charge, the measured weight is rounded to a whole pound, the three component terms are summed, the subtotal is rounded once, and only then are manual-handling parameters added. The added parameters are never re-rounded.
- For the oversize handling fee, each special item's fee is rounded to a whole cent individually and the rounded per-item figures are then summed. Summing first and rounding once is a different number and is not the specified behaviour.
- For the mishandled compensation offer, the declared-value fraction is applied first and the two caps are applied second, with no rounding between them.
- The final liability figure applies the haircut or the settled amount in the branch indicated by the report's status, then rounds half-up to a whole cent.

Time arithmetic is similarly pinned. Where a rule converts a duration to whole minutes, the duration is truncated toward zero. Where a duration difference feeds a minimum-connect-time subtraction, the truncation happens on the departure difference first and the required connect time is subtracted afterwards.

### 2.11. Derived Counters and the Flight Readiness Flag

Several aggregates are recomputed whenever their inputs move, and they are read from the owning resource rather than recomputed by the caller.

The station's `manual_queue_depth` counts the station's manual inspection tasks whose status is `QUEUED` or `IN_PROGRESS`; tasks that have been `RESOLVED` or `ESCALATED` are excluded. Because a task's `due_utc` is set to exactly 30 minutes after the task's `created_at`, this counter is the live size of the staffed inspection queue.

A flight's `makeup_ready` flag is true only when two conditions hold together: the flight has no bag whose custody status is `HELD`, and none of its bags has an open manual inspection task in status `QUEUED` or `IN_PROGRESS`. `ESCALATED` and `RESOLVED` tasks do not block readiness, and a bag merely held at screening does block it. The flag is recomputed on every bag custody write and on every inspection-task write for one of the flight's bags.

The station's `open_liability_cents` and `settled_liability_cents` are covered in §2.14, and its `active_bag_count` in §2.6.

### 2.12. Optimistic Concurrency Control

Three write operations in this API are guarded against lost updates through optimistic concurrency control, and each requires a version token in the request body that carries the client's last observed version of the guarded parent.

- Editing a bag's particulars through the bag correction write requires `expected_bag_version`, which must equal the target bag's current `version`. A bag's version advances legitimately whenever its screening axis is written — an alarm resolution, an anomaly note, or a custody advance — so a client that read the bag before any of those and then writes back is carrying a stale view.
- Assigning a make-up interval requires `expected_bag_version` as well, matching the same bag's current `version`. Resolution of a screening alarm or a recorded anomaly note advances the bag's version between the client's read and this assignment.
- Reopening a report requires `expected_report_version`, which must equal the target report's current `version`. Every report transition — investigate, arrange-delivery, mark-delivered, compensate and close — bumps the report's version, so a client carrying a version read before any of them is stale.

In all three cases the version token is a non-optional input field. A mismatch between the supplied token and the parent entity's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412, and no part of the operation is applied. Operations not listed above take no version field at all.

### 2.13. Validation Priority Order

Where several rules bear on a single request, they are evaluated in a fixed priority order, and the first failure is the error the caller sees. Later checks are never reached once an earlier one has failed.

1. **Authentication.** `X-User-Role` and `X-User-ID` must both be present and the role must be a declared role, else `ERR_UNAUTHENTICATED` (401). This runs first on every request.
2. **Authorization.** The acting role must permit the operation, and an entity-backed role may act only on resources it owns, else `ERR_FORBIDDEN_ROLE` (403). This runs on every request, immediately after authentication.
3. **Station suspension.** For the sortation, loading and delivery writes, a station in `SUSPENDED` posture is refused with `ERR_STATION_SUSPENDED` (409) before any state check is examined. A station outage is declared or cleared only through the outage operations; no other write may lift it.
4. **Screening clearance gate.** A bag whose screening status is `ALARMED`, `FAILED` or `IN_INSPECTION` may not advance past the screening stage. This is checked ahead of every custody-advance state precondition and is reported as `ERR_SCREENING_NOT_CLEARED` (409). It guards make-up assignment, loading, and connection confirmation.
5. **State admissibility.** The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409). This applies to every state-transition operation.
6. **Weight and size envelope.** On acceptance and weighing, the declared weight must not exceed the carrier's `max_excess_weight_lb` plus 20 pounds, and the declared `linear_in` must not exceed 130 inches. The two failures are `ERR_BAG_OVERWEIGHT` and `ERR_BAG_OVERSIZE`, both HTTP 422.
7. **Sortation scheduling.** Induction must fall inside the flight's sortation window and loading must not occur after its close; the failures are `ERR_SORTATION_WINDOW_CLOSED`, `ERR_FLIGHT_NOT_SORTING` and `ERR_SORTATION_WINDOW_OPEN`, all HTTP 409.
8. **Make-up interval claim.** The claimed identity bucket must be free at the area's buffer granularity and the area must not already hold `capacity_slots` distinct occupied buckets, else `ERR_MAKEUP_SLOT_CONFLICT` (409).
9. **Screening lane admission.** The lane must be `ACTIVE` and must not already host a non-`FAILED` window in the same twenty-minute identity bucket, else `ERR_LANE_OFFLINE` or `ERR_LANE_INTERVAL_CONFLICT` (409).
10. **Interline integrity.** A bag declaring `INTERLINE` itinerary type requires a carrier whose `interline_agreement_active` is true, else `ERR_INTERLINE_AGREEMENT_INACTIVE` (422).
11. **Manual inspection gate.** A sortation or load advance is refused while the bag has an open inspection task in status `QUEUED` or `IN_PROGRESS`, reported as `ERR_MANUAL_INSPECTION_REQUIRED` (409).
12. **Uniqueness within scope.** A bag's `tag_number` is unique, a connection is unique on the pair of `bag_id` and `onward_flight_id`, and the station `code` and airline `code` are unique. Duplicate airline codes yield `ERR_DUPLICATE_AIRLINE` and duplicate connections yield `ERR_DUPLICATE_CONNECTION`, both HTTP 409.
13. **Claim settlement fiscal gates.** A claim may be approved only once, and compensation may be paid only once per report and only within the carrier's `compensation_cap_cents`; the failures are `ERR_CLAIM_ALREADY_DECIDED` and `ERR_COMPENSATION_ALREADY_PAID`, both HTTP 409.
14. **Concurrency.** The supplied version token must equal the guarded parent's current version, else `ERR_STALE_VERSION` (412), exactly as described in §2.12.
15. **Existence.** The identifiers in the path, and then the foreign keys in the body, must resolve, else `ERR_BAG_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` or `ERR_FLIGHT_NOT_FOUND` (404).

### 2.14. The Station Liability Ledger and Constraint Intake

Every station of custody carries a liability ledger split across the two fields `open_liability_cents` and `settled_liability_cents`. The open figure is the sum of `final_liability_cents` across the station's mishandled reports whose status is one of `REPORTED`, `INVESTIGATING`, `DELIVERY_ARRANGED` or `REOPENED`. The settled figure is the sum over reports whose status is one of `DELIVERED`, `COMPENSATED` or `CLOSED`. Every report row lands in exactly one of the two halves, so a status change moves value between them and never creates or destroys it: at every instant the two halves together equal the sum of `final_liability_cents` over all the station's reports. A report that has been `DELIVERED` is not yet settled money, and it belongs to the settled half only because the delivery leg is complete — the compensation may still follow.

Two constraint-intake rules complete the picture. A malformed body, an unknown enum member, a missing required field, or a re-accommodation naming the connection's existing onward flight all yield `ERR_INVALID_REQUEST` with HTTP 400, and an enum member outside a field's declared value set yields `ERR_INVALID_ENUM_VALUE`, also HTTP 400.

## 3. Business Logic & Workflows

### 3.1. Acceptance, Tag Printing and Routing Determination

An `AcceptanceAgent` opens a bag's record at the moment it is handed over at the counter or curbside, supplying the `station_id` where custody begins, the `passenger_name` as printed on the tag, the `passenger_ref` locator the bag is attached to, the `itinerary_type` as one of `DOMESTIC`, `INTERNATIONAL` or `INTERLINE`, the declared `weight_lb`, and the three declared dimensions `length_in`, `width_in` and `height_in`. A `flight_id` may be supplied at acceptance or left unset — a bag accepted without a flight has no sortation window to induct against and remains in the acceptance pool until one is assigned. The server mints the `tag_number` itself as a unique ten-digit string; the client never supplies it and may not influence it. The baggage linear measure `linear_in` is derived at acceptance as the sum of the three declared dimensions, and it is the figure every oversize test later consults.

Two envelope checks run at acceptance. The declared `weight_lb` may not exceed the carrier's `max_excess_weight_lb` plus 20 pounds, and the declared `linear_in` may not exceed 130 inches; the first failure is `ERR_BAG_OVERWEIGHT` and the second `ERR_BAG_OVERSIZE`, both HTTP 422. A bag declaring `INTERLINE` itinerary type additionally requires a carrier whose `interline_agreement_active` is true — a false agreement is rejected with `ERR_INTERLINE_AGREEMENT_INACTIVE` and HTTP 422, and this is the point at which the interline agreement is enforced. Duplicate `tag_number` values and duplicate carrier codes are refused as described in §2.13.

The new bag begins life in the `ACCEPTED` custody state and the `PENDING` screening state, with `routing_class` defaulting to `STANDARD`, `excess_weight_fee_cents` and `manual_sortation_delay_minutes` at zero, and `rush_declared` false. One field is stamped at acceptance and governs the bag for its whole life: `ops_run_index_at_acceptance` records the station's `ops_run_index` as it stands at that instant, and §3.2 explains what happens when it falls behind.

A special item may be registered on the bag by an `AcceptanceAgent` or a `BaggageServiceAgent`, declaring its `item_type` as `OVERSIZE`, `FRAGILE`, `SPORTS_EQUIPMENT` or `MOBILITY_DEVICE` along with a `declared_value_cents`. Registering one computes three derived fields on the item and refreshes the bag's handling charge. The item's `requires_manual_screening` flag is set when the item type is `MOBILITY_DEVICE` or `SPORTS_EQUIPMENT`, or when the bag's `linear_in` is strictly greater than 115 inches — note that a bag measuring exactly 115 inches does not trigger the flag through the linear test, though it still would through the item-type test for the two listed types. The item's per-item handling fee is the field `handling_fee_cents`, and its carrier liability ceiling is `liability_cap_cents`, both computed by the rules in §3.4.

`AcceptanceAgent`, `SortationAgent`, `LoadAgent` and `Screener` may each append a manual scan capture at any point in the life of a bag, naming one of the scan points `INDUCTION`, `SCREENING`, `SORTATION`, `MAKEUP`, `LOAD` or `DELIVERY`. A capture records the `scan_point`, a `scan_source` of `AUTOMATED` or `MANUAL`, the `scan_utc` instant, and a `result` of `OK` or `REJECT`. While a station's outage is active the source is forced to `MANUAL` regardless of what the caller asked for; the resulting manual captures are what the outage delay projection in §3.9 counts.

### 3.2. Weighing, Screening Induction and Routing Class

Weighing is the step that moves a bag off the counter and onto the belt. An `AcceptanceAgent` supplies the measured `scale_weight_lb`, and a bag in the `ACCEPTED` custody state advances to `SCREENING` while its screening status moves from `PENDING` to `IN_LINE`. Weighing is also the re-induction path for a bag that holds at screening, and §3.5 covers that second use.

The weigh step recomputes a cluster of derived fields at once. The measured `scale_weight_lb` is stored alongside a derived `weight_variance_lb`, the signed difference between the measured and declared weights. The `excess_weight_fee_cents` is computed by the rule below, the `handling_charge_cents` is set to its provisional figure by §3.4, the `routing_class` is determined by the routing rule below, and the `priority_score` is recomputed by §3.10. A scan capture at the induction point is then appended. Weighing is refused outright if the bag's `linear_in` exceeds 130 inches, with `ERR_BAG_OVERSIZE`.

The excess-weight fee is charged in whole five-pound groups above the carrier's allowance, at a flat 7500 cents per group. The measured weight is first rounded half-up to the nearest whole pound — this rounding happens before the grouping, never after — and compared against the carrier's `max_excess_weight_lb`. If the rounded weight is at or below that threshold, the fee is exactly zero. Otherwise the number of five-pound groups is the difference between the rounded weight and the threshold divided by five and rounded up to a whole number of groups, and the fee is that group count multiplied by 7500 cents. Two variants of the fee exist. When the station's `outage_active` is false at the instant of weighing, the fee is charged as computed. When the station is in outage contingency at that instant, the fee is pinned to exactly zero regardless of the bag's weight — it is deferred, not waived, and the two variants therefore differ by the full group amount for identical bag data.

The routing class — the field `routing_class`, one of `STANDARD`, `MANUAL` or `BULK_HOLD` — is determined by a top-to-bottom evaluation in which the first matching rule wins. If the bag's `itinerary_type` is `INTERLINE` and the carrier's `interline_agreement_active` is false, the class is `MANUAL`. Otherwise, if the itinerary type is `INTERLINE` and the pound-rounded `scale_weight_lb` is strictly greater than the carrier's `max_excess_weight_lb`, the class is `MANUAL`. Otherwise, if the itinerary type is `INTERNATIONAL`, the class is `BULK_HOLD`. Otherwise the class is `STANDARD`. The weight comparison uses the same pound-rounded weight the excess-weight fee uses, so the two tests agree.

Shortly after induction the bag enters the in-line screening system. A `Screener` inducts it onto a chosen lane, identified by `lane_id`, at a supplied `start_utc`, and the system derives the event's `end_utc` as exactly twenty minutes later; the event begins in status `IN_PROGRESS`. The screening event records the `bag_id` it concerns alongside the `lane_id`, and a screener working the manual inspection queue may filter it by the `screening_event_id` it was raised from. The window is a strict half-open interval, so a lane may accept a window starting at exactly the instant another window ends, but the lane must be `ACTIVE` and must not already carry a non-`FAILED` window in the same twenty-minute identity bucket. A lane reading `OFFLINE` refuses the induction with `ERR_LANE_OFFLINE` (409), and a colliding bucket refuses it with `ERR_LANE_INTERVAL_CONFLICT` (409); the lane's derived `last_event_end_utc` is refreshed from its non-`FAILED` events after each admission.

What happens next depends on whether the caller supplied an `alarm_code`. With no alarm code the window resolves itself immediately: the event moves to `CLEARED` with its `resolution_outcome` recorded as `CLEARED`, the bag's screening status moves to `CLEARED`, and the bag's custody advances from `SCREENING` straight to `SORTED`. An alarm-free induction is the clearance — no screener action and no separate resolution call is required, and this is the ordinary path for the overwhelming majority of bags.

When an `alarm_code` is supplied, the event moves to `ALARMED` and the bag's screening status moves to `ALARMED`; the screening axis then pushes the custody axis, and a bag whose custody status was `ACCEPTED` or `SCREENING` at that moment is dropped to `HELD` and stops advancing until the alarm is resolved. A `Screener` resolves the alarm with an `outcome` of either `CLEARED` or `REJECTED`, supplying the resolution through the alarm-resolution operation, which requires the event to actually be in `ALARMED` status — an attempt to resolve an event that is not alarmed is refused with `ERR_SCREENING_EVENT_NOT_ALARMED` (409). A `CLEARED` outcome records `resolution_outcome` as `CLEARED`, stamps the acting screener into `resolved_by`, moves the event to `CLEARED`, and advances a bag still in `SCREENING` custody to `SORTED`; a bag that had already been dropped to `HELD` keeps its held custody, and its alarm clearance alone does not release it — §3.5 describes the release path. A `REJECTED` outcome moves the event to `FAILED` with `resolution_outcome` recorded as `REJECTED`, moves the bag's screening status to `FAILED`, and drops the bag's custody to `HELD`.

Server-side ordering on this path is pinned and matters: the screening axis is written first, and the custody axis is then evaluated against the value the screening axis has just taken. The check that a bag may not advance past the screening stage — `ERR_SCREENING_NOT_CLEARED`, HTTP 409, described in §2.13 — is what holds the two axes in alignment wherever a later custody advance is attempted.

### 3.3. The Manual Inspection Queue

An alarm does not always resolve at the lane. A bag whose screening needs human examination leaves the in-line system and enters the station's manual inspection queue as a `ManualInspectionTask`, opened against the screening event that raised it. Each task begins in status `QUEUED` and carries a `queue_position` assigned at creation — a stable position within the station's queue, where position 1 is the head of the queue — and an optional `assigned_to` naming the screener it is handed to. Its `resolution` is null until a screener decides it, and its `due_utc` is computed as exactly thirty minutes after the task's `created_at`; that deadline is what the operations checkpoint in §3.11 escalates against.

Two routes create a task. The first is an alarm that has already been resolved by rejection: a bag whose screening status has reached `FAILED` enters the inspection queue directly. The second is the special-item safeguard — when a bag carries a special item whose `requires_manual_screening` flag is true and the bag has no open inspection task for its latest screening event, the task is created automatically with status `QUEUED` and a `queue_position` of the station's current `manual_queue_depth` plus one. The second route fires during sortation, described in §3.6.

A `Screener` claims a queued task, which moves it to `IN_PROGRESS` and stamps the acting screener into `assigned_to`; a task may only be claimed while it is `QUEUED`, and the claim additionally requires its screening event to still be `ALARMED`, else `ERR_SCREENING_EVENT_NOT_ALARMED` (409). A screener then resolves the task with a `resolution` of `CLEARED` or `BAG_REJECTED`. A resolution of `CLEARED` moves the task to `RESOLVED` with `resolution` recorded as `CLEARED` and moves the bag's screening status to `CLEARED`. A resolution of `BAG_REJECTED` moves the task to `RESOLVED` with `resolution` recorded as `BAG_REJECTED` and moves the bag's screening status to `FAILED`. Both resolutions are permitted from either `QUEUED` or `IN_PROGRESS`, both require the screening event still to be `ALARMED`, and both refresh the station's `manual_queue_depth` and the flight's `makeup_ready`. Clearing a task does not by itself release the bag from `HELD` custody; that happens only through re-induction, described in §3.5.

The station's queue depth is the count of its tasks in status `QUEUED` or `IN_PROGRESS`; tasks that have reached `RESOLVED` or `ESCALATED` are outside the count, as §2.11 records.

### 3.4. Handling Charges, Special Items and Fee Waivers

A bag's `handling_charge_cents` is an aggregation over the bag's weight, its special items and its itinerary type, and it exists in two variants that differ only in a manual-handling parameter added at the end. The measured `scale_weight_lb` is first rounded half-up to the nearest whole pound. A base term of 700 cents plus 25 cents for each rounded pound is formed. A special-item term of 2600 cents for each `SpecialItem` row on the bag is added — every row counts, regardless of its `item_type`. An international term of 1800 cents is added when, and only when, the bag's `itinerary_type` is `INTERNATIONAL`. Those three terms are summed into a subtotal, the subtotal is rounded half-up to a whole cent once, and only then are the manual-handling parameters added — the parameters are never re-rounded. In the provisional variant the parameter term is zero, so the charge equals the subtotal. In the final variant the parameter term is 3700 cents when the bag was ever held at screening, and zero when it never was.

Which variant applies is a function of custody. While the bag's custody status is `ACCEPTED`, `SCREENING`, `SORTED` or `IN_MAKEUP` the charge is provisional, and it is recomputed at every weighing. Once the bag's custody status has reached `LOADED`, `DELIVERED` or `OFFLOADED` the charge is final, and it is recomputed on load, delivery and offload. For a 52.4-pound domestic bag carrying no special items, the rounded weight is 52 pounds, so the base term is 700 cents plus 25 cents for each of those 52 pounds, or 1300 cents, giving a subtotal of 2000 cents with nothing added for special items or an international itinerary. The bag therefore reads 2000 while provisional, and 5700 once final if it was ever held at screening.

Special items carry their own per-item fee, the field `handling_fee_cents`, which is computed per item and then summed across the bag's items. A size scale is derived from the bag's `linear_in`: scale 1 when the baggage linear measure is 62 inches or less, scale 2 when it is greater than 62 and at most 115 inches, and scale 3 when it exceeds 115 inches. Each item then has a raw fee determined by its `item_type` — 4500 cents for `OVERSIZE`, 6725 cents for `FRAGILE`, 11250 cents for `SPORTS_EQUIPMENT`, and 0 cents for `MOBILITY_DEVICE` — which is multiplied by 1.25 when the bag's `linear_in` is at least 115 inches. That raw fee is multiplied by the scale, rounded half-up to a whole cent individually for that item, and only then are the rounded per-item figures summed into the bag's oversize handling fee. The per-item rounding position is load-bearing: three `FRAGILE` items on a bag measuring 120 inches give a raw 25218.75 cents per item, which rounds per item to 25219 and sums to 75657, whereas summing first gives 75656.25 and rounds once to 75656 — a one-cent divergence in which the per-item order is the specified one. A bag carrying no special items has an oversize handling fee of zero, and the field is not recomputed during weighing for such a bag.

Each special item also carries a carrier liability ceiling, the field `liability_cap_cents`, which is the lesser of the item's `declared_value_cents` and a type-based cap: 200000 cents for `MOBILITY_DEVICE`, 50000 cents for `FRAGILE`, and 100000 cents for every other type. The figure is an integer number of cents with no rounding applied.

One further operation touches special-item money without touching the bag's charge. A `BaggageServiceAgent` or `PlatformAdmin` may waive a single special item's handling fee, supplying the guarded `expected_bag_version` described in §2.12. The waive writes the item's single-item fee into the field `waived_fee_cents` — evaluated at that item's own `item_type`, not at the historically lowest fee on the bag — and deliberately leaves `handling_charge_cents` on the bag unchanged. A freshly registered item reads `waived_fee_cents` as zero until something is waived on it. A bag version token that no longer matches the bag's current version is rejected with `ERR_STALE_VERSION` (412).

### 3.5. Holding, Re-induction and the Two Cycle Edges

A bag whose screening clearance is unresolved sits in `HELD` custody. Holding is not a terminal state: two distinct routes release a bag, and both are deliberate.

The first route is re-induction through weighing. An `AcceptanceAgent` may re-weigh a held bag, which moves its custody back to `ACCEPTED` and, in the same breath, resets its screening axis to `PENDING` and then immediately to `IN_LINE` — the alarm, failure or inspection state the bag carried is discarded and the bag re-enters the screening pipeline from the start. The re-induction repeats the whole weigh computation: `scale_weight_lb` and `weight_variance_lb` are refreshed, `excess_weight_fee_cents` is recomputed in the variant selected by the station's outage flag, `routing_class` is redetermined, `handling_charge_cents` returns to its provisional figure, `priority_score` is recomputed, and a fresh induction scan capture is appended. Re-induction is refused unless the bag has no open inspection task — a task in status `QUEUED` or `IN_PROGRESS` blocks it with `ERR_MANUAL_INSPECTION_REQUIRED` (409) — and it is refused unless one of two conditions holds: either the station's `outage_active` is true, or the bag's screening status is currently `ALARMED` or `CLEARED`. Neither condition holding yields `ERR_OUTAGE_NOT_ACTIVE` with HTTP 409. The second of those two conditions is what permits a bag to be released after an alarm was cleared in place: such a bag carries `CLEARED` screening status while its custody is still `HELD`.

The second route is the anomaly note, and it is the mechanism behind the two cycle edges in the screening axis. A `Screener` or `AcceptanceAgent` may correct a bag's particulars through the bag correction operation, which the caller guards with `expected_bag_version`. When that operation supplies an `anomaly_note` — a screener's free-text note — the presence of the note is itself what drives one of two cycle edges, and which edge fires depends on where the bag's screening status stands.

A bag whose screening status is currently `CLEARED` is re-induced: its screening status moves back to `IN_LINE` and a scan capture at the `SCREENING` point is appended. This is permitted only while the bag's custody status is `ACCEPTED`, `SCREENING`, `SORTED` or `HELD`; anything else is refused with `ERR_INVALID_STATE` (409). This is the first cycle edge, and it means a cleared bag can be sent back through screening without returning to the counter.

A bag whose screening status is currently `FAILED` is instead re-inspected: its screening status moves to `IN_INSPECTION` and its custody status stays `HELD` while it reads `IN_INSPECTION`. This is the second cycle edge, and it exists because a failed bag needs the manual inspection queue rather than a fresh in-line pass. A bag sitting in `IN_INSPECTION` cannot be moved by either the alarm-resolution path or a further anomaly note; it leaves that state only through a resolution of its inspection task — `CLEARED` or `BAG_REJECTED`, as §3.3 describes — and even then it reaches `ACCEPTED` only through a subsequent re-induction weigh.

Because the two cycle edges loop back into the pipeline, the screening axis has no terminal state at all: a cleared bag can be re-induced and a failed bag re-inspected, indefinitely. Every one of these writes advances the bag's `version`, which is exactly why the version tokens described in §2.12 go stale so readily.

### 3.6. Sortation into Make-Up Areas and Dispatch Priority

Once a bag is `CLEARED` and `SORTED`, a `SortationAgent` claims its make-up interval, supplying the target `makeup_area_id`, the `induction_utc` instant the interval opens, the `makeup_interval_minutes` duration, and the version token `expected_bag_version` described in §2.12. The claim is evaluated against a fixed ladder of conditions, and the first failure is the error the caller sees: the bag's custody status must be `SORTED` (`ERR_INVALID_STATE`, 409); its screening status must be `CLEARED` (`ERR_SCREENING_NOT_CLEARED`, 409); it must already have a `flight_id` (`ERR_FLIGHT_NOT_ASSIGNED`, 409); that flight must be in status `SCHEDULED` or `SORT_OPEN` (`ERR_FLIGHT_NOT_SORTING`, 409); the station must not be reading `SUSPENDED` (`ERR_STATION_SUSPENDED`, 409, with `CONGESTED` deliberately advisory); the target area's status must be `ACTIVE` (`ERR_MAKEUP_AREA_CLOSED`, 409); and the claimed interval must clear the area's changeover buffer and fit within its capacity (`ERR_MAKEUP_SLOT_CONFLICT`, 409). The bag must also carry no open inspection task, which is the `ERR_MANUAL_INSPECTION_REQUIRED` gate at priority 11.

An accepted claim moves the bag's custody to `IN_MAKEUP`, writes the target into `makeup_area_id`, and records the supplied `induction_utc` into `assigned_makeup_utc` as the instant the current make-up interval opened. The bag's `priority_score` is recomputed, the bag's `version` increments by one, and a scan capture at the `SORTATION` point is appended — sourced `MANUAL` when the station's outage is active and `AUTOMATED` otherwise, since the bag is being routed by hand during a contingency.

The claim then ripples outward in three directions, and the implementation must land all three. First, the area's slot ledger is recomputed: `occupied_slots` and `free_slots` are refreshed from the bag's new `IN_MAKEUP` entry. Second, the station's posture is recomputed, and with the station's active make-up areas down to one free slot or fewer the posture tips to `CONGESTED`. Third, when the area reaches exactly zero free slots the station's inspection queue is re-prioritised: every `ManualInspectionTask` of the station that is still `QUEUED` and whose `due_utc` has already arrived at the current logical clock instant is re-stamped, with its `queue_position` recomputed and its priority flagged, and the station's `manual_queue_depth` is refreshed. At the same time the special-item safeguard fires: if the bag carries a special item whose `requires_manual_screening` is true and the bag has no inspection task for its latest screening event, one is created in status `QUEUED` with a `queue_position` of the station's `manual_queue_depth` plus one, and the queue depth and the flight's `makeup_ready` are recomputed in that order.

Sortation is also offered in bulk. A `SortationAgent` may hand a batch of assignments to the bulk operation in a single call, supplying the `assignments` collection. Each item in the batch is validated exactly as the single-bag claim is — independently of the others, in the order the items were supplied — and a rejected item never aborts the batch. The response separates the two outcomes into an `assigned` collection of the bags that were accepted and a `rejected` collection in which each entry names its `bag_id` and the `error_code` that refused it. The make-up occupancy, station posture, manual queue depth and flight readiness aggregates are recomputed once after each accepted item rather than once at the end of the batch.

Ranking for dispatch is carried by the field `priority_score`, an integer recomputed on every custody or screening write, every connection write and every flight transition, so it is always current when a sortation agent reads it. The score starts from the bag's routing class — `STANDARD` contributes nothing, `BULK_HOLD` adds 40, and `MANUAL` adds 80 — to which the connecting itinerary's contribution is added: no connection contributes nothing, `PENDING` adds 20, `CONFIRMED` adds 50, and both `RUSH` and `REACCOMMODATED` add the elevated figure of 150, while a `MISSED` connection adds nothing at this step. Three situational adjustments then apply. A bag with no connection at all receives a flat 120-point bonus for being a local bag; a bag whose connection has a non-negative `connect_slack_minutes` receives 20 points for being comfortably connectable; and a bag whose connection slack is negative loses 60 points. A bag whose recorded weight variance differs from its declared weight by 10 pounds or more, in either direction, loses 40 points. A bag whose screening status is `CLEARED` gains 30 points, since it is ready to move. A bag whose flight has already passed its `sortation_close_utc` loses 100 points. Finally, a bag whose connection has been marked `MISSED` gains a large 200-point adjustment, because the transfer desk must find it before it can be re-accommodated. To make the arithmetic concrete: a `MANUAL`-class bag with no connection, a cleared screening status and a clock still inside the sortation window scores 80 plus 120 plus 30, or 230; and the same bag burdened with a connection eight minutes short of its minimum, a `RUSH` connection status and a clock past the close scores 80 plus 150 minus 60 plus 30 minus 100, or 100.

### 3.7. Loading, Delivery, Offloading and Passenger Tracking Visibility

A `LoadAgent` loads a bag from make-up onto its aircraft. The load advance requires the bag's custody status to be `IN_MAKEUP` (`ERR_INVALID_STATE`, 409), its screening status to be `CLEARED` (`ERR_SCREENING_NOT_CLEARED`, 409), its `duplicate_flag` to be false — a bag flagged as a duplicate of an earlier-accepted bag on the same flight may not be loaded at all, and the refusal is `ERR_DUPLICATE_BAG_ON_FLIGHT` (409) — and, when the bag carries a connection, that connection's status to be `CONFIRMED` or `RUSH` (`ERR_CONNECTION_MISSED`, 409). The current logical clock instant must also still be at or before the flight's `sortation_close_utc`, else `ERR_SORTATION_WINDOW_CLOSED` (409). The `duplicate_flag` itself is derived from acceptance history: it is true when another bag sharing this bag's `passenger_ref` was accepted for the same flight at an earlier `created_at`.

An accepted load moves the bag's custody to `LOADED`, stamps the current logical clock instant into `loaded_utc` — which is what closes the make-up interval the bag was holding — recomputes `handling_charge_cents` in its final variant per §3.4, and refreshes the flight's `loaded_bag_count`, the flight's `makeup_ready` and the area's slot ledger as the bag's slot is released. Two scan captures are appended on this path: a `MAKEUP` capture before the load itself, and the `LOAD` capture that records it. A bag that reaches `LOADED` and then has to come back off the aircraft is `OFFLOADED`; the offload recomputes the flight's `loaded_bag_count` and the station's `active_bag_count`, returns the bag's handling charge to its final variant, and settles the bag's connection — to `MISSED` when the current logical clock instant has passed the onward flight's `sortation_close_utc`, and to `CONFIRMED` otherwise. An offload also raises a mishandled report directly, as §3.11 describes.

Delivery is the last custody advance. A `LoadAgent` marks a loaded bag delivered to the passenger or the reclaim belt, which requires the bag's custody status to be `LOADED` (`ERR_INVALID_STATE`, 409) and the bag's flight to have actually reached `DEPARTED` (`ERR_FLIGHT_NOT_DEPARTED`, 409). The successful advance moves the custody to `DELIVERED`, stamps the current logical clock instant into `delivered_utc`, returns the handling charge to its final variant, recomputes the station's `active_bag_count` — the bag has now left the station envelope and drops out of the count — and appends a scan capture at the `DELIVERY` point. `DELIVERED` is the only terminal state on the custody axis; once a bag is delivered it does not move again.

Passengers see the journey through a read-only tracking lookup addressed by the ten-digit tag number rather than by the bag's identifier. The lookup returns the `tag_number`, the `custody_status`, the `screening_status`, the `last_scan_point` and `last_scan_utc` of the most recent capture, an `onboard` boolean, the `connection_status`, the `manual_sortation_delay_minutes` figure, and an `open_reports` count summarising the reports still being worked on the bag. The scan trail that backs those last-scan fields is the bag's `scan_trail`, a passenger-visible chain of captures each carrying its `scan_point`, its `scan_source` and its `scan_utc`, ordered by `scan_utc` ascending with `created_at` ascending breaking ties. A passenger may read only their own bags: the `Passenger` role's identity is entity-backed by `passenger_ref`, so the tracking lookup and the per-bag reads all compare the acting identity against that field and reject anything else with `ERR_FORBIDDEN_ROLE` (403).

### 3.8. Connecting Itineraries and the Rush-Bag Procedure

A transfer bag's itinerary is described by a `Connection` that a `TransferAgent` records, naming the `bag_id` it belongs to, the `inbound_flight_id` the bag arrives on, the `onward_flight_id` it departs on, and the `required_mct_minutes` the itinerary was built to satisfy.

The connection's derived slack, the field `connect_slack_minutes`, is the whole-minute difference between the onward flight's scheduled departure and the inbound flight's scheduled departure — that difference truncated toward zero before anything else is done to it — less the connection's `required_mct_minutes`. Worked through: an onward departure at 17:30 against an inbound departure at 15:00 gives 150 whole minutes, which against a required minimum of 75 minutes yields a slack of 75; the same 150 minutes against a required minimum of 165 minutes yields a slack of negative 15, which is exactly the boundary at which the rush-bag procedure remains available. Slack is recomputed whenever a connection is created, whenever it is re-accommodated onto a replacement flight, and whenever an onward flight is rescheduled — a shifted departure ripples into the slack of every connection that flies onward on it.

A new connection begins in status `PENDING`. The ordinary confirmation path settles it against the minimum connect time: a `TransferAgent` confirms the itinerary, which requires the connection to be in `PENDING` or in `RUSH` (`ERR_INVALID_STATE`, 409), requires a slack of zero or more (`ERR_MCT_VIOLATION`, 409), and requires the bag's screening status to be `CLEARED` (`ERR_SCREENING_NOT_CLEARED`, 409). A successful confirmation moves the connection to `CONFIRMED` and recomputes the bag's priority score.

When slack is non-negative but thin, the transfer desk may declare the rush-bag procedure speculatively rather than waiting. Declaring rush is available from `PENDING`, from `CONFIRMED` and from `REACCOMMODATED`, and it requires a slack of at least negative fifteen minutes; a slack below negative fifteen is refused with `ERR_RUSH_WINDOW_PASSED` (409). The declaration moves the connection to `RUSH` and stamps the current logical clock instant into `rush_declared_utc`. A rush declaration is provisional: once slack recovers to non-negative the connection can be released back to `CONFIRMED` through the ordinary confirmation path, and that release requires the same clearance and minimum-connect-time conditions the original confirmation did.

The system also drives connection state on its own. A connection in `CONFIRMED` or `RUSH` whose bag's custody status is `LOADED`, `OFFLOADED`, `SORTED` or `IN_MAKEUP` is marked `MISSED` by the operations checkpoint once the current logical clock instant has passed the onward flight's `sortation_close_utc` — the connection depends on the flight for its timing, and once the onward sortation window has shut the itinerary cannot be made. A bag that is marked `MISSED` cannot be loaded onto its onward flight as it stands: the load advance refuses with `ERR_CONNECTION_MISSED` (409). A missed connection is not stranded, however. It returns to `CONFIRMED` on its own if its slack recovers to non-negative after a reschedule, and a `TransferAgent` may instead re-accommodate it onto a replacement onward flight.

Re-accommodation is available from `MISSED` and takes the replacement flight as its input. The supplied flight must be different from the connection's current `onward_flight_id` — naming the same flight is refused as `ERR_INVALID_REQUEST` (400) — and the replacement's status must be `SCHEDULED` or `SORT_OPEN`, else `ERR_FLIGHT_NOT_SORTING` (409). An accepted re-accommodation replaces the connection's `onward_flight_id`, recomputes `connect_slack_minutes` against the replacement flight's schedule, moves the connection to `REACCOMMODATED`, and recomputes the bag's priority score. Re-accommodation is not always a cure, and the system accepts that: a `REACCOMMODATED` connection whose replacement onward flight's sortation window has already shut is pushed back to `MISSED` by the same checkpoint rule, and the desk may re-accommodate it again onto a later flight — so `MISSED` and `REACCOMMODATED` form a legal loop across successive re-accommodations. A `REACCOMMODATED` connection may also be rushed directly, under the same negative-fifteen-minute floor, and it may recover to `CONFIRMED` on its own once its slack returns to non-negative.

Two derived properties follow the connection's status. The bag's `rush_declared` flag is true whenever its connection is in `RUSH` or `REACCOMMODATED`, and that flag is what exempts the bag from the outage allowance described in §3.9. Connections in the `MISSED` state also carry the largest single adjustment in the priority score, as §3.6 records.

### 3.9. Outage Contingency and Manual Sortation

An airport administrator declares a sortation-system outage by naming the station, which sets the station's `outage_active` flag to true, stamps the current logical clock instant into `outage_started_utc`, and forces the station's posture to `SUSPENDED`. From that instant the station's in-line sortation is untrusted, and the platform switches to a manual posture on four fronts.

First, all sortation, loading and delivery writes against bags of custody at the station are refused with `ERR_STATION_SUSPENDED` (409) — the station is suspended and no bag may advance through the automated path. Second, scan capture is diverted: every scan appended while the outage is active is stamped with a `scan_source` of `MANUAL` regardless of the source the caller requested, so the manual captures accumulate on the bag's trail and feed the delay projection at the end of this subsection. Third, weighing becomes fee-deferred: the excess-weight fee takes its pinned-to-zero hold variant, as §3.2 describes, and the charge is not collected while the station is under contingency. Fourth, the manual re-induction path opens: §3.5's re-induction of a held bag is permitted while the station's outage is active, whether or not the bag's screening status would otherwise qualify it, so bags holding at screening can be walked back through the counter during an outage.

Loading under contingency is rate-limited rather than open. The rule applies only while the station's `outage_active` is true and only to a bag whose `routing_class` is `MANUAL`; bags outside the manual routing class, and all bags at a station without an active outage, face no allowance at all. For a manual-class bag, the system counts the station's bags already loaded since the outage began — those whose `loaded_utc` is at or after `outage_started_utc` and whose `routing_class` is `MANUAL` — and refuses the load once that count has reached five, with `ERR_MAKEUP_RATE_LIMITED` (409). The boundary is inclusive: the fifth manual-class bag is refused while the fourth is admitted. The count looks backward from the outage's start instant rather than forward from the present, so it is a cumulative allowance that does not reset however long the outage drags on. A bag that has been rush-declared — its connection in `RUSH` or `REACCOMMODATED` — is exempt from the allowance entirely.

The outage is cleared through a dedicated clearance operation, which flips `outage_active` to false and recomputes the station's posture from the ordinary posture rule, leaving `outage_started_utc` as the historical record of when the last outage began. No other write may lift the flag, and while the flag is set the station's suspension is the first business rule any advance encounters.

Two passenger-facing figures describe the cost of the contingency. The field `manual_sortation_delay_minutes` is derived at read time on every fetch of a bag. It is zero whenever the station's outage is not active. While the outage is active it is the sum of two terms: the dwell from the outage's start to the current logical clock instant, in whole minutes truncated toward zero, capped at 45 minutes — the cap applies to the dwell term only — and fifteen minutes for each manual-scan capture recorded on the bag while the outage was active, which is an uncapped term. A bag that has sat through a long outage and been scanned by hand repeatedly therefore shows a delay well beyond the 45-minute dwell cap.

### 3.10. The Re-Inducement Loop and Screening Dwell

Read together, the paths in §3.2 and §3.5 describe a pipeline that never terminates. A cleared bag can be sent back to `IN_LINE` by an anomaly note. A failed bag can be sent to `IN_INSPECTION` by an anomaly note. A resolved inspection clears or rejects the bag's screening status, and a rejection can in turn be re-inspected. A held bag can be re-inducted by weighing, which resets its screening axis to `PENDING` and then `IN_LINE` and starts the whole sequence over. This is deliberate: baggage screening genuinely does loop when a bag is re-screened or a screener corrects an observation, and the API models it faithfully rather than collapsing it into a single pass.

The consequence for callers is that no screening status is final and no custody status short of `DELIVERED` is final. Every loop traversal rewrites the bag's screening axis and therefore advances the bag's `version`, which is why the version tokens in §2.12 have a short useful life during an active alarm investigation.

Looping also produces a dwell metric. The field `screen_alarm_resolution_time_minutes` is derived at read time on every fetch of a bag and reports, in whole minutes truncated toward zero, how long the bag's screening has been in play. A bag that has never had a screening event reports zero. Otherwise the figure is the latest `updated_at` among the bag's screening events less the earliest `created_at` among them, with ties in either selection broken by `created_at` ascending — that is, the span from the bag's first screening window to the most recent write against any of its windows. A bag that has looped through screening several times accumulates a correspondingly long dwell, and a bag that cleared on its first in-line pass shows a span clipped at the twenty-minute screening window it occupied.

### 3.11. Mishandled Bag Reports and the Liability Ledger

When a bag goes wrong, the baggage service office opens a `MishandledReport` naming the `bag_id` it concerns, the `station_id` of custody that must work it, and a `report_type` of `DELAYED`, `DAMAGED`, `LOST` or `PILFERED`. Reports also arise without an explicit filing: offloading a bag raises one directly with a `report_type` of `DELAYED`, and a station outage contingency sweep raises them for bags the outage has stranded. A report raised by that sweep carries the flag `outage_context` set to true, which distinguishes contingency-driven work from a passenger complaint; a report filed or raised by an offload carries it false. The filing call accepts an optional `anomaly_note` alongside the particulars.

A new report begins in status `REPORTED` and begins the investigation path. Moving it into investigation requires it to actually be `REPORTED` or `REOPENED` (`ERR_INVALID_STATE`, 409) and recomputes its money fields. From `INVESTIGATING` a `BaggageServiceAgent` may either arrange delivery — which requires a `delivery_method` to be supplied, one of `COURIER`, `PASSENGER_PICKUP` or `FORWARD_ON_NEXT_FLIGHT`, and which refuses a missing method with `ERR_INVALID_REQUEST` (400) — or close the report outright. Closing from `INVESTIGATING` is permitted only when the report's `claim_status` is `NONE` or `DENIED`; a report with a filed-but-undecided claim cannot be closed and is refused with `ERR_CLAIM_PENDING` (409). A report that has been closed may be reopened, and so may a compensated one.

The full path runs `REPORTED` to `INVESTIGATING` to `DELIVERY_ARRANGED` to `DELIVERED` to `COMPENSATED` to `CLOSED`, with a `REOPENED` state reachable from both `COMPENSATED` and `CLOSED` and exiting back to `INVESTIGATING`. The `DELIVERED` to `COMPENSATED` step requires the report's `claim_status` to be `APPROVED` — anything else is refused with `ERR_CLAIM_NOT_APPROVED` (409) — and it is the step that recognises the payout. The `COMPENSATED` to `CLOSED` step is the terminal one. Reopening a compensated report is a compensating action, not a status edit: besides moving the report to `REOPENED` and setting `claim_status` back to `FILED`, it zeroes both `compensation_settled_cents` and `approved_cents`, returns `final_liability_cents` to its provisional haircut figure, and moves the bag's delivery row back from `COMPENSATED` to `DELIVERED`, reversing the credit that the compensation had applied. Reopening also demands the `expected_report_version` token described in §2.12, and a stale token is refused with `ERR_STALE_VERSION` (412). The loop from `REOPENED` back through investigation, arrangement, delivery, compensation and close is a legal cycle: a report can be paid, reopened on new information, and paid again.

Two money fields are recomputed on nearly every report transition. The field `compensation_offer_cents` is the provisional offer the carrier is prepared to make. It takes a fraction of the baggage value — nothing at all for a `DELAYED` report, one half for `DAMAGED`, three quarters for `LOST`, and three fifths for `PILFERED` — applied to the highest `declared_value_cents` among the bag's special items, or to zero when the bag carries no special items, with the product rounded half-up to a whole cent. That figure is then clamped twice: against the carrier's `compensation_cap_cents` and against the lowest `liability_cap_cents` among the bag's special items, when the bag has any. The order is pinned — the fraction is applied first and the two caps second, and since a minimum is commutative the two caps' relative order makes no difference. The offer exists in two variants. While the report's status is `REPORTED`, `INVESTIGATING` or `DELIVERY_ARRANGED` the fraction is used as declared. Once the report reaches `DELIVERED` or `COMPENSATED` the fraction is multiplied by 1.25 before the caps are applied, so a `DAMAGED` report moves from one half to five eighths, a `LOST` report to fifteen sixteenths, and a `PILFERED` report to three quarters. Worked through on identical inputs: a `DAMAGED` report on a bag whose highest declared special-item value is 120000 cents, with a carrier cap of 300000, offers 60000 while provisional and 75000 once the report has delivered.

The field `final_liability_cents` is the money the carrier recognises on the report, and it has exactly two branches with no third fallback. While the report's status is `REPORTED`, `INVESTIGATING`, `DELIVERY_ARRANGED`, `REOPENED` or `DELIVERED`, the recognised figure is three quarters of `compensation_offer_cents`, rounded half-up to a whole cent — note that `DELIVERED` sits in this branch, so a delivered-but-unsettled report still carries the haircut. Once the report's status is `COMPENSATED` or `CLOSED`, no haircut is applied and the recognised figure is `compensation_settled_cents` in full.

Because the recognised figure is a pure function of the report's status and its offer or settled amount, the station ledger stays consistent across the compensate and reopen pair. Reopening zeroes the settled amount and returns the report to the haircut branch, so the recognised figure returns to three quarters of the offer; compensating records the settled amount and moves the report to the realised branch. The two branches agree exactly when the settled amount equals three quarters of the offer, which is what the settlement rule in §3.12 produces whenever the approved claim reaches the full offer.

Every one of these transitions refreshes the station's liability ledger — `open_liability_cents` and `settled_liability_cents`, partitioned by report status as §2.14 sets out — so the station's two figures always reflect the reports in their current states, and a report moving between the halves moves value rather than duplicating it.

### 3.12. Claims, Settlement Clamping and Direct Loss Settlement

A passenger's ask is recorded as a `Claim` filed against a report, carrying a `requested_amount_cents`. Exactly one claim row may exist per report: the filing operation mints the single row and a second filing against the same report is rejected. Filing also moves the report's `claim_status` to `FILED` and copies the requested amount into the report's `claim_amount_cents` as the amount claimed by the passenger; that report-side field stays at zero until a claim is filed.

A `BaggageServiceAgent` decides the claim, supplying a `decision` and, when approving, an optional `approved_amount_cents`. The claim carries its own decision state — `PENDING` until decided, then `APPROVED` or `DENIED`, with the deciding operator recorded in `decided_by` and the decision instant in `decided_utc`. A claim that has already been approved or denied cannot be decided again, and a repeat decision is refused with `ERR_CLAIM_ALREADY_DECIDED` (409). Deciding also moves the report's `claim_status` to `APPROVED` or `DENIED`, and an approved decision writes the approved amount into the report's `approved_cents` and recomputes the report's `final_liability_cents`.

The approved amount is clamped by a two-step waterfall. First, the approved figure is the smallest of three quantities: the claim's `requested_amount_cents`, the report's `compensation_offer_cents`, and the carrier's `compensation_cap_cents`. A request exceeding the carrier's cap is refused outright with `ERR_COMPENSATION_OVER_CAP` (422). Second, the amount actually applied — the figure written to the report's `compensation_settled_cents` — is the approved figure further limited by the report's `final_liability_cents` as that field stood before the transition began. All three terms of the waterfall are already integral cents, so no rounding is applied at any step.

The clamp in the second step can legitimately leave the two report fields disagreeing, and that disagreement is specified behaviour rather than a bug: when the approved figure exceeds the pre-transition recognised liability, the applied amount is held down to the liability while the approved amount keeps its higher value. A report in that condition therefore carries an `approved_cents` larger than its `compensation_settled_cents`.

Paying compensation is a separate, later act performed on the report once it has been delivered, and it is what realises the money: the report moves to `COMPENSATED`, its `claim_status` moves to `SETTLED`, the approved and settled amounts are computed by the waterfall above, `final_liability_cents` moves to its realised branch, and the bag's delivery row is moved to `COMPENSATED`. Compensation may be paid only once per report, and a second payment attempt is refused with `ERR_COMPENSATION_ALREADY_PAID` (409). The earlier gate applies here too: a report whose `claim_status` is not `APPROVED` cannot be compensated at all, and the refusal is `ERR_CLAIM_NOT_APPROVED` (409).

A lost bag may instead be settled directly, bypassing the claim-and-decide sequence. The direct loss settlement takes the amount the carrier has actually paid as its input, the field `paid_cents`, and moves the report straight to `COMPENSATED` with `claim_status` set to `SETTLED`. Its approved figure is the smallest of three quantities — the supplied paid amount, the report's `compensation_offer_cents`, and the carrier's `compensation_cap_cents` — and the settled amount is set equal to that approved figure, so the realised branch reflects the full payout. If the bag has no delivery row at all, one is created and moved straight through to `COMPENSATED`. The station ledger is refreshed afterwards, as it is on every report transition.

### 3.13. The Flight Timeline and the Operations Checkpoint

Time in this system is driven by a logical clock rather than by wall-clock time, and the clock is a control the platform administrator sets. Setting it supplies the desired instant as the field `to_iso8601`, and from then on every deadline, sortation window, outage dwell and escalation test derives from that instant. Before the clock is ever set, the server reads exactly 2026-09-01T00:00:00Z and must not fall back to the host's real time.

Flights are created with a station, a carrier — supplied as `station_id` and `airline_id` respectively — a marketing `flight_number` such as `DL1423`, a `bank_code` such as `B1`, and a `scheduled_departure_utc`. On creation the flight derives its sortation boundaries — opening exactly 120 minutes before the scheduled departure and closing exactly 45 minutes before it — begins in status `SCHEDULED`, reads `makeup_ready` as true because it has no bags at all, and reads `loaded_bag_count` as zero.

Four statuses describe a flight's progression: `SCHEDULED`, `SORT_OPEN`, `BOARDING`, `DEPARTED` and `CANCELLED`, of which `DEPARTED` and `CANCELLED` are terminal. The first two advances are automatic and occur during the operations checkpoint. A `SCHEDULED` flight becomes `SORT_OPEN` once the current logical clock instant reaches its `sortation_open_utc`, so bags may begin to be inducted against it. A `SORT_OPEN` flight becomes `BOARDING` once two things hold together: its `makeup_ready` flag is true, and the current logical clock instant has reached fifteen minutes before its `sortation_close_utc`. This is the gate that keeps a flight from boarding while a bag of its own is still held at screening or still sitting in the manual inspection queue — baggage readiness is a precondition of boarding, not an afterthought.

Departure is an administrator's act rather than an automatic one. Marking a boarding flight departed requires the flight to actually be `BOARDING` (`ERR_INVALID_STATE`, 409) and requires the current logical clock instant to have reached the flight's `sortation_close_utc` (`ERR_SORTATION_WINDOW_OPEN`, 409). Once departed, the flight unlocks the last custody advance: bags loaded onto it may now be marked delivered, which §3.7 describes.

An administrator may also move a flight's departure, and this one change ripples widely. Rescheduling is available only from `SORT_OPEN` (`ERR_INVALID_STATE`, 409), takes the new `scheduled_departure_utc` as its input, recomputes `sortation_open_utc` as 120 minutes before it and `sortation_close_utc` as 45 minutes before it, recomputes `connect_slack_minutes` for every connection whose onward flight is this flight, and returns the flight to status `SCHEDULED` so that it re-enters the automatic sweep against its new boundaries. Because the sweep re-runs, a rescheduled flight that has already opened its sortation will simply open it again on the next checkpoint. The slack recomputation is the widest consequence: every transfer bag flying onward on the rescheduled flight has its connection slack recalculated, and a connection that had gone negative may recover, and one that had been comfortable may go thin.

Cancellation is available from `SCHEDULED` or `SORT_OPEN` and is refused from any later status (`ERR_INVALID_STATE`, 409). Cancelling releases the flight's sorted bags back into the sortation pool: every bag whose `flight_id` is this flight and whose custody status is `SORTED` or `IN_MAKEUP` has its custody status returned to `SORTED` and both its `flight_id` and its `makeup_area_id` cleared, so it carries no flight assignment and holds no make-up slot. The affected make-up areas' slot ledgers are recomputed and the station's posture is recomputed afterwards, since the released bags have given their slots back. A cancelled flight is terminal, and it cannot be rescheduled or departed.

The checkpoint itself is the administrator-driven tick that advances all of this at once. Running it increments the station's `ops_run_index` — a monotone counter, starting at zero, that only ever increases and which is what the acceptance stamp ages against — and then performs four sweeps in the same pass. It expires stale acceptances: any bag of the station whose custody status is still `ACCEPTED` and whose `ops_run_index_at_acceptance` is at least two behind the station's current `ops_run_index` is moved to `HELD` custody with a screening status of `FAILED`, on the reasoning that a bag sitting unweighed through two full checkpoints has missed its window. It marks missed connections: connections whose onward flight's sortation window has closed and whose bag is `LOADED`, `OFFLOADED`, `SORTED` or `IN_MAKEUP` become `MISSED`, as §3.8 describes. It escalates overdue inspection work: manual inspection tasks still in status `QUEUED` or `IN_PROGRESS` whose `due_utc` has arrived are moved to `ESCALATED`, but only while the station's posture is `CONGESTED` or `SUSPENDED` — a station running normally does not escalate its queue. It sweeps flights: `SCHEDULED` flights whose `sortation_open_utc` has arrived become `SORT_OPEN`, and `SORT_OPEN` flights that are `makeup_ready` and within fifteen minutes of `sortation_close_utc` become `BOARDING`. Finally it recomputes the station's posture, the station's manual queue depth, and each affected flight's readiness.

The ordering rules the sweep follows are pinned. Bags are walked in `created_at` ascending order, and the primary key is never consulted as a tie-break. Where two bags share a `created_at`, the one with the lower `ops_run_index_at_acceptance` is processed first; only then does `created_at` ascending settle the order. Inspection tasks are escalated whenever their `due_utc` has arrived at the current logical clock instant and the station is `CONGESTED` or `SUSPENDED`, with `ESCALATED` being a terminal state for the task and the station's queue depth and the flight's readiness recomputed afterwards.

### 3.14. Delivery Logistics and the Compensation Cascade

Physical return of a bag is tracked separately from the bag itself. Every bag carries at most one `Delivery` row, and a bag that reaches `HELD` or `OFFLOADED` without one has it synthesized automatically, so a delivery record always exists from the moment a bag stops moving normally. A delivery row can also be attached to a specific mishandled report through `mishandled_report_id`, which is null for a routine reclaim-belt delivery.

A delivery names its `method` — `COURIER`, `PASSENGER_PICKUP` or `FORWARD_ON_NEXT_FLIGHT`, defaulting to `PASSENGER_PICKUP` — an optional free-text `address_note` carrying delivery instructions and null for reclaim-belt deliveries, a promised `scheduled_utc`, and a `proof_required` flag defaulting to false that controls whether a signed proof of delivery must be produced before the row can be closed out. Its status runs `PENDING`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `DELIVERED` and `COMPENSATED`, beginning at `PENDING`, and its `delivered_utc` and `courier_ref` stay null until the corresponding events occur — `courier_ref` is only ever populated for a courier delivery.

A pending delivery moves to `IN_TRANSIT` on its own, without a dedicated call: it happens either when the linked mishandled report reaches `DELIVERY_ARRANGED` — at which point the delivery takes its `method` and `scheduled_utc` from the report's arrangement — or when a bag is delivered on the ordinary routine path. Arranging delivery is where the promised instant is pinned down, and the instant must not precede the current logical clock instant; a promise set in the past is refused with `ERR_DELIVERY_IN_PAST` (422). Only a delivery that has reached `IN_TRANSIT` can be dispatched, and dispatch is available only when the delivery's `method` is `COURIER` — dispatching a passenger-pickup or forward-on-next-flight delivery is refused with `ERR_INVALID_REQUEST` (400). A successful dispatch moves the row to `OUT_FOR_DELIVERY` and records the supplied courier reference.

Completing a delivery is available from `IN_TRANSIT` or from `OUT_FOR_DELIVERY`, and both routes carry the same proof requirement: unless the row's `proof_required` flag is false, a `proof_of_delivery` must be supplied, and its absence is refused with `ERR_PROOF_OF_DELIVERY_REQUIRED` (409). A completed delivery moves to `DELIVERED` and stamps the current logical clock instant into `delivered_utc`.

The final hop is driven by the report rather than by the delivery. When the linked mishandled report is compensated, the delivery row moves to `COMPENSATED` — it is the report that mutates the delivery, never the bag. Ordering is pinned in both directions. Forward, the report's delivery-marking step flips the delivery row to `DELIVERED` first, and only afterwards may compensation move it on to `COMPENSATED`; a delivery whose report has not yet been marked delivered cannot skip to the compensated status. Backward, reopening a compensated report moves the delivery row back to `DELIVERED`, reversing the credit. The four-status loop `PENDING` to `IN_TRANSIT` to `DELIVERED` to `COMPENSATED` and back to `DELIVERED` is a legal cycle, and it mirrors the report's own reopen cycle exactly. A delivery that has already been compensated and reversed is not re-compensated by the reversal itself; it is simply restored to `DELIVERED`, ready for the report to be worked again.

## 4. Endpoint Definitions

The whole API is mounted under `/baggage`, with one exception: the logical-clock control endpoint is mounted at the service root. Operations that create a new, stand-alone resource or add a new, distinct row to a collection — opening a station, creating an airline, a make-up area, a screening lane, a flight, accepting a bag, filing a report, filing a claim, inducting a screening event, recording a transfer connection, registering a special item, recording a scan capture, and re-accommodating a live connection — return `201 Created`. Operations that modify an existing resource, including adding data to a resource's internal collection (such as a claim on a report or a special item on a bag), return `200 OK`. Table entries describe each operation's purpose and the role or roles permitted to invoke it; the request and response bodies, the side effects each operation carries and the trigger conditions for its failures are specified in the narrative of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; the clock starts at 2026-09-01T00:00:00Z and derives every deadline, sortation window and outage dwell | PlatformAdmin |
| POST | `/baggage/stations` | Open a station envelope | PlatformAdmin |
| GET | `/baggage/stations` | List stations, filterable by code and posture | PlatformAdmin, BaggageServiceAgent |
| GET | `/baggage/stations/{id}` | Get a station | PlatformAdmin, AcceptanceAgent, TransferAgent, BaggageServiceAgent |
| POST | `/baggage/stations/{id}/outage` | Declare a sortation-system outage | PlatformAdmin |
| POST | `/baggage/stations/{id}/outage/clear` | Clear an active outage | PlatformAdmin |
| POST | `/baggage/stations/{id}/run_ops` | Run the operations checkpoint: stale-acceptance expiry, task escalation, connection and flight swept | PlatformAdmin |
| POST | `/baggage/airlines` | Create a carrier record | PlatformAdmin |
| GET | `/baggage/airlines` | List airlines, filterable by code and interline agreement | PlatformAdmin, BaggageServiceAgent |
| GET | `/baggage/airlines/{id}` | Get an airline | PlatformAdmin, AcceptanceAgent, TransferAgent, BaggageServiceAgent |
| POST | `/baggage/makeup-areas` | Create a make-up area | PlatformAdmin |
| GET | `/baggage/makeup-areas` | List make-up areas, filterable by station and status | PlatformAdmin, SortationAgent, LoadAgent |
| GET | `/baggage/makeup-areas/{id}` | Get a make-up area | PlatformAdmin, SortationAgent, LoadAgent |
| GET | `/baggage/stations/{id}/makeup-areas` | List the make-up areas of a station | PlatformAdmin, SortationAgent, LoadAgent |
| POST | `/baggage/screening-lanes` | Create an explosive-detection screening lane | PlatformAdmin |
| GET | `/baggage/screening-lanes` | List screening lanes, filterable by station and status | PlatformAdmin, Screener, SortationAgent |
| GET | `/baggage/screening-lanes/{id}` | Get a screening lane | PlatformAdmin, Screener, SortationAgent |
| POST | `/baggage/screening-lanes/{id}/offline` | Take a screening lane out of service | PlatformAdmin |
| POST | `/baggage/screening-lanes/{id}/online` | Return a screening lane to service | PlatformAdmin |
| POST | `/baggage/flights` | Create a flight and derive its sortation window | PlatformAdmin |
| GET | `/baggage/flights` | List flights, filterable by station, airline, bank and status | PlatformAdmin, AcceptanceAgent, SortationAgent, TransferAgent |
| GET | `/baggage/flights/{id}` | Get a flight | PlatformAdmin, AcceptanceAgent, SortationAgent, LoadAgent, TransferAgent |
| GET | `/baggage/stations/{id}/flights` | List the flights built at a station | PlatformAdmin, AcceptanceAgent, SortationAgent |
| GET | `/baggage/airlines/{id}/flights` | List the flights operated by an airline | PlatformAdmin, TransferAgent |
| GET | `/baggage/makeup-areas/{id}/flights` | List the flights built in a make-up area | PlatformAdmin, SortationAgent |
| POST | `/baggage/flights/{id}/reschedule` | Move a flight's scheduled departure and recompute its sortation window | PlatformAdmin |
| POST | `/baggage/flights/{id}/depart` | Mark a boarding flight departed | PlatformAdmin |
| POST | `/baggage/flights/{id}/cancel` | Cancel a flight and release its sorted bags back to the sortation pool | PlatformAdmin |
| POST | `/baggage/bags` | Accept a bag, mint and print its tag, and record its declared particulars | AcceptanceAgent |
| GET | `/baggage/bags` | List bags, filterable by station, flight, make-up area, custody status, screening status and passenger reference | AcceptanceAgent, SortationAgent, LoadAgent, BaggageServiceAgent, Passenger |
| GET | `/baggage/bags/{id}` | Get a bag, including its passenger-visible tracking fields | AcceptanceAgent, SortationAgent, LoadAgent, Screener, TransferAgent, BaggageServiceAgent, Passenger |
| PUT | `/baggage/bags/{id}` | Correct bag particulars, or record an anomaly note that drives the screening cycle edges | Screener, AcceptanceAgent |
| POST | `/baggage/bags/{id}/weigh` | Weigh, dimension-screen and route a bag; also the re-induction path for a held bag | AcceptanceAgent |
| POST | `/baggage/bags/{id}/assign-makeup` | Assign a make-up interval to a sorted bag | SortationAgent |
| POST | `/baggage/bags/bulk-assign-makeup` | Assign make-up intervals to many sorted bags in one call, reporting per-bag outcomes | SortationAgent |
| POST | `/baggage/bags/{id}/load` | Load a bag onto its flight | LoadAgent |
| POST | `/baggage/bags/{id}/deliver` | Deliver a loaded bag to the passenger or reclaim belt | LoadAgent |
| POST | `/baggage/bags/{id}/offload` | Offload a loaded bag and raise its mishandled report | LoadAgent |
| GET | `/baggage/stations/{id}/bags` | List the bags in a station envelope | AcceptanceAgent, SortationAgent, LoadAgent, BaggageServiceAgent |
| GET | `/baggage/flights/{id}/bags` | List the bags built for a flight | LoadAgent, SortationAgent, TransferAgent |
| GET | `/baggage/makeup-areas/{id}/bags` | List the bags currently occupying a make-up area | SortationAgent, LoadAgent |
| GET | `/baggage/airlines/{id}/bags` | List the bags on an airline's flights | BaggageServiceAgent, PlatformAdmin |
| POST | `/baggage/bags/{id}/scans` | Record a manual scan-point capture, the outage-contingency capture path | AcceptanceAgent, SortationAgent, LoadAgent, Screener |
| GET | `/baggage/bags/{id}/scans` | List the scan-point captures on a bag, the passenger tracking trail | AcceptanceAgent, SortationAgent, LoadAgent, Screener, Passenger, BaggageServiceAgent |
| GET | `/baggage/scans` | List scan captures, filterable by bag and scan point | BaggageServiceAgent, PlatformAdmin |
| POST | `/baggage/screenings` | Induct a bag onto a screening lane for a window; a non-null alarm code raises the in-line alarm | Screener |
| GET | `/baggage/screenings` | List screening events, filterable by bag, lane and status | Screener, PlatformAdmin |
| GET | `/baggage/screenings/{id}` | Get a screening event | Screener, PlatformAdmin |
| POST | `/baggage/screenings/{id}/resolve` | Resolve an in-line alarm as cleared or rejected | Screener |
| POST | `/baggage/screenings/{id}/reopen` | Reopen a cleared screening window, the compensating action | Screener |
| GET | `/baggage/bags/{id}/screenings` | List the screening events of a bag | Screener, PlatformAdmin |
| GET | `/baggage/screening-lanes/{id}/screenings` | List the screening events on a lane | Screener, PlatformAdmin |
| GET | `/baggage/inspections` | List the manual inspection queue, filterable by station, status and screening event | Screener, PlatformAdmin, BaggageServiceAgent |
| GET | `/baggage/inspections/{id}` | Get a manual inspection task | Screener, PlatformAdmin |
| POST | `/baggage/inspections/{id}/claim` | Claim a queued manual inspection task | Screener |
| POST | `/baggage/inspections/{id}/resolve` | Resolve a manual inspection task as cleared or bag-rejected | Screener |
| GET | `/baggage/stations/{id}/inspections` | List the manual inspection queue of a station | Screener, PlatformAdmin |
| GET | `/baggage/screenings/{id}/inspections` | List the manual inspection tasks raised from a screening event | Screener, PlatformAdmin |
| POST | `/baggage/connections` | Record a transfer-bag connection between an inbound and an onward flight | TransferAgent |
| GET | `/baggage/connections` | List connections, filterable by bag, flight and status | TransferAgent, SortationAgent, BaggageServiceAgent |
| GET | `/baggage/connections/{id}` | Get a connection | TransferAgent, SortationAgent, LoadAgent |
| GET | `/baggage/bags/{id}/connections` | List the connections of a transfer bag | TransferAgent, SortationAgent |
| GET | `/baggage/flights/{id}/connections` | List the connections touching a flight as the onward leg | TransferAgent, SortationAgent |
| POST | `/baggage/connections/{id}/confirm` | Confirm a connection against the minimum connect time | TransferAgent |
| POST | `/baggage/connections/{id}/declare-rush` | Invoke the rush-bag procedure on an at-risk connection | TransferAgent |
| POST | `/baggage/connections/{id}/reaccommodate` | Re-accommodate a missed connection onto a replacement onward flight | TransferAgent |
| POST | `/baggage/bags/{id}/special-items` | Register an oversize, fragile, sports-equipment or mobility-device item on a bag | AcceptanceAgent, BaggageServiceAgent |
| GET | `/baggage/bags/{id}/special-items` | List the special items on a bag | AcceptanceAgent, BaggageServiceAgent, LoadAgent |
| GET | `/baggage/special-items` | List special items, filterable by bag and item type | BaggageServiceAgent, PlatformAdmin |
| POST | `/baggage/reports` | File a mishandled bag report | BaggageServiceAgent |
| GET | `/baggage/reports` | List reports, filterable by station, bag, type and status | BaggageServiceAgent, PlatformAdmin |
| GET | `/baggage/reports/{id}` | Get a mishandled bag report | BaggageServiceAgent, PlatformAdmin, Passenger |
| GET | `/baggage/stations/{id}/reports` | List the reports a station of custody must work | BaggageServiceAgent, PlatformAdmin |
| GET | `/baggage/bags/{id}/reports` | List the mishandled bag reports raised for a bag | BaggageServiceAgent, Passenger, PlatformAdmin |
| POST | `/baggage/reports/{id}/investigate` | Move a report into investigation | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/arrange-delivery` | Arrange delivery of a delayed bag, optionally requiring a signed proof of delivery | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/mark-delivered` | Mark the bag delivered under the report | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/compensate` | Settle an approved claim and recognise the compensation | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/close` | Close a report | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/reopen` | Reopen a compensated or closed report, reversing any compensation | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/loss-settlement` | Settle a lost report directly, recording the payout and releasing the delivery row | BaggageServiceAgent |
| POST | `/baggage/reports/{id}/claims` | File a claim against a report | BaggageServiceAgent |
| GET | `/baggage/reports/{id}/claims` | List the claims filed on a report | BaggageServiceAgent, PlatformAdmin |
| POST | `/baggage/claims/{id}/decide` | Approve or deny a filed claim | BaggageServiceAgent |
| GET | `/baggage/deliveries` | List delivery rows, filterable by bag, report and status | BaggageServiceAgent, PlatformAdmin |
| GET | `/baggage/deliveries/{id}` | Get a delivery row | BaggageServiceAgent, Passenger, PlatformAdmin |
| GET | `/baggage/bags/{id}/deliveries` | List the delivery rows of a bag | BaggageServiceAgent, Passenger |
| GET | `/baggage/reports/{id}/deliveries` | List the delivery rows arranged under a report | BaggageServiceAgent, PlatformAdmin |
| POST | `/baggage/deliveries/{id}/dispatch` | Dispatch a courier delivery | BaggageServiceAgent |
| POST | `/baggage/deliveries/{id}/complete` | Complete a delivery, optionally with proof | BaggageServiceAgent |
| POST | `/baggage/bags/{id}/special-items/{itemId}/waive-handling-fee` | Waive one special item's handling fee, recording the waived amount on the item | BaggageServiceAgent, PlatformAdmin |
| GET | `/baggage/tracking/{tag_number}` | Passenger-facing bag tracking lookup by tag number | Passenger, BaggageServiceAgent, PlatformAdmin |

## 5. Error Code Catalogue

Each error identifier below is returned in the `error_id` field of the standard error envelope described in §2.2. The HTTP status each carries is listed alongside it; the conditions that trigger them are specified in the narrative of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_BAG_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_FLIGHT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STATION_SUSPENDED` | 409 |
| `ERR_SCREENING_NOT_CLEARED` | 409 |
| `ERR_SCREENING_EVENT_NOT_ALARMED` | 409 |
| `ERR_SCREENING_WINDOW_CLOSED` | 409 |
| `ERR_LANE_OFFLINE` | 409 |
| `ERR_LANE_INTERVAL_CONFLICT` | 409 |
| `ERR_BAG_OVERWEIGHT` | 422 |
| `ERR_BAG_OVERSIZE` | 422 |
| `ERR_INTERLINE_AGREEMENT_INACTIVE` | 422 |
| `ERR_DUPLICATE_AIRLINE` | 409 |
| `ERR_DUPLICATE_CONNECTION` | 409 |
| `ERR_DUPLICATE_BAG_ON_FLIGHT` | 409 |
| `ERR_SORTATION_WINDOW_CLOSED` | 409 |
| `ERR_SORTATION_WINDOW_OPEN` | 409 |
| `ERR_FLIGHT_NOT_SORTING` | 409 |
| `ERR_FLIGHT_NOT_ASSIGNED` | 409 |
| `ERR_FLIGHT_NOT_DEPARTED` | 409 |
| `ERR_MAKEUP_SLOT_CONFLICT` | 409 |
| `ERR_MAKEUP_AREA_CLOSED` | 409 |
| `ERR_MAKEUP_RATE_LIMITED` | 409 |
| `ERR_MANUAL_INSPECTION_REQUIRED` | 409 |
| `ERR_MCT_VIOLATION` | 409 |
| `ERR_RUSH_WINDOW_PASSED` | 409 |
| `ERR_CONNECTION_MISSED` | 409 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_CLAIM_PENDING` | 409 |
| `ERR_CLAIM_ALREADY_DECIDED` | 409 |
| `ERR_COMPENSATION_OVER_CAP` | 422 |
| `ERR_COMPENSATION_ALREADY_PAID` | 409 |
| `ERR_DELIVERY_IN_PAST` | 422 |
| `ERR_PROOF_OF_DELIVERY_REQUIRED` | 409 |
| `ERR_OUTAGE_NOT_ACTIVE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM_VALUE` | 400 |