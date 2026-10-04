# Communal Teppanyaki Service Floor API — Product Requirements Document

## 1. Introduction

A teppanyaki dining room is an unusual piece of hospitality infrastructure: the kitchen is a counter that seats strangers side by side, the entertainment is a timed performance, and the economics depend on filling every stool at a shared grill bank before the chef walks up. This document specifies the service-floor API that a multi-venue teppanyaki chain will use to run those dining rooms. The API is mounted under the `/service-floor` path prefix and is responsible for the full operational arc of a visit: registering guest parties, drafting and holding bookings, combining separate parties at one grill table so that each seating episode reaches its tier minimum, matching party size against table capacity, selecting the next chef off the rotation, sequencing the sushi and grill courses so the show starts at the right minute, accounting for protein issued tableside, and scheduling ventilation and grill downtime without stranding seated guests.

The system is deliberately built around two hard realities of the format. The first is that a grill table is a shared, capacity-bounded resource — several bookings may occupy the same table at once, and the floor must know, at every instant, how many guests are standing at each grill and when the table is expected to come free. The second is that a communal table only turns a profit when the combined check clears the tier minimum and when the chef's show is neither rushed nor stalled, so every pricing decision, every hold, and every show start is evaluated against a running account of turn debt, protein cost, and per-epoch floor charges. Nothing in the API accumulates silently; every derived figure is recomputed from the underlying rows so that a venue can always be audited back to the events that produced it.

This document is written for the engineering team that will implement the service. It states the global contracts first, then narrates the business workflows in the order the floor actually experiences them, and closes with the endpoint inventory and the error catalogue. Field names, state values, and error identifiers are given as literal tokens throughout; the endpoint table is a reference index only, and the authoritative behaviour for any operation lives in the narrative sections.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that hold for every operation in the API. Where a rule is stated here, it is not repeated per endpoint; where a workflow has a special case, the special case is stated in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the actor, and `X-User-Role` declares the capacity in which the actor is acting. If either header is absent, or if the role is not one of the five roles the API recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Every endpoint except creating a venue and setting the logical clock requires these headers. If the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The API recognises exactly five roles: `PlatformAdmin`, `FloorManager`, `Host`, `Chef`, and `SushiChef`. Their spellings are load-bearing and must be matched exactly.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is never compared to any entity's `id`. The same is true for `FloorManager` and `Host` — all three are unbacked operators. When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the acting `ChefAssignment`, and ownership checks on any resource that references a `ChefAssignment` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `SushiChef`, the same holds: `X-User-ID` is the `id` of the acting `ChefAssignment` row, and a `SushiChef` may only operate on tickets whose owning foreign key resolves to that same chef row.

A `PlatformAdmin` is the chain operator who opens venues and configures table tiers, and is the only role permitted to open a venue, retire a table tier and set the logical clock. A `FloorManager` owns the physical floor: commissioning grill tables, posting grill-table events, advancing the venue's batch epoch, adding chefs to the roster, clearing a chef back into rotation, extending an occupancy window, and owning the maintenance-window lifecycle and its accept, cancel and reopen actions, as well as adjusting issued protein and skipping or reinstating show phases. A `Host` is the front-of-house role that registers guest parties, drafts bookings, and drives every booking action — holds, seating, party-size changes, closing, reopening and voiding a posted charge. A `Chef` clocks in and out, clears a finished show, starts and finishes show phases, and posts protein variance and protein void events. A `SushiChef` fires sushi tickets and advances, restages, restarts or voids them. Every role shares read access to every list and single-resource read operation.

Two operations additionally require segregation of duties: accepting a maintenance window and closing a booking are rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403) when the acting role does not hold the required grant or has not been explicitly delegated it.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. A show-phase event response returned for a `GRILL` phase carries, alongside the updated phase object, the booking's money slots — its `final_bill_cents`, `check_cents` and `quote_final_cents`.
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

List responses are paginated through query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10, and its smallest permitted value is 1 while its largest is 100. The `offset` parameter says how many items to skip from the front of the result and defaults to 0. Values outside the permitted band, or of the wrong type, are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a workflow states otherwise, list endpoints order their results by creation timestamp ascending. Recognised `limit` and `offset` values are echoed, together with `total_count` and `has_more`, into the `meta` object of the response envelope whenever a list is returned. The same four pagination fields are the only ones added to `meta` by pagination; nothing else varies between a paginated and a non-paginated list response.

### 2.4. Floor-Truth Identifiers, Timestamps and Versioning

Every persisted resource in this API is fully addressable and fully auditable. All twelve resource families — `Venue`, `Party`, `TableTier`, `GrillTable`, `Reservation`, `TableSeating`, `ChefAssignment`, `ShowPerformance`, `MaintenanceWindow`, `SushiTicket`, `VenueLedgerEntry`, and `ProteinTicket` — carry the same four system-managed properties.

- `id` is a server-minted UUID string. It carries no type prefix and no human-readable component; callers must never parse it.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, re-stamped on every mutation of the row, including mutations the server performs on the caller's behalf during a cascade.
- `version` is an integer that starts at its initial value and increments by exactly one on every mutation of the row. It is the anchor for the optimistic-concurrency contract in §2.8.

Because every family in this API declares the common field set, there are no partial resources: every row carries all four properties, and a cascade that touches a child row bumps that child's `version` and refreshes its `updated_at` just as an explicit client write would. Derived figures such as `guests_seated`, `shortfall_turn_debt_minutes`, `protein_cost_cents`, `restaurant_charge_cents`, `completed_show_count`, `pounds_protein_issued` and `minutes_since_show` are read-only projections; a mutation that changes their inputs counts as a mutation of the owning row and increments that row's `version`.

### 2.5. The Hood Bank, the Freeze, and Ventilation Discipline

Each venue declares the hood bank that serves its grill line through `ventilation_zone`, which is one of `ZONE_A`, `ZONE_B`, `ZONE_C` or `ZONE_D`. Every chef likewise declares the zone of the grill bank they work through `station_zone`, drawn from the same four values, and the floor will not put two chefs on station in the same zone at the same time.

A venue's ventilation load is tracked cumulatively. `hood_filter_life_index` counts cooking minutes across every grill table at the venue and advances by exactly one each time a `GRILL` course finishes. The venue also carries `filter_service_threshold_index`, the index at which the bank must be taken out of service; it is supplied when the venue is opened and defaults to 40. `ops_epoch` is a separate counter, starting at 0, that advances by exactly one each time the venue's batch epoch is run.

`status` is the venue's operational lifecycle value and is either `ACTIVE` or `VENTILATION_HOLD`. It begins at `ACTIVE`. While the venue is in `VENTILATION_HOLD`, the boolean `occupancy_freeze` is true, and while that boolean holds no seating episode may begin anywhere on the floor. A venue enters `VENTILATION_HOLD` and leaves it only through the acceptance and release of a ventilation service window, described in §3.7.

### 2.6. Shared-Grill Occupancy: Half-Open Intervals and the Closed Counter

A grill table is not exclusively booked. A `GrillTable` row tracks `guests_seated` — the running sum of `party_size` across the `TableSeating` rows at that table that are still `ACTIVE` — against its own `seat_capacity`. Several bookings may therefore occupy the same table at once, and the arithmetic of capacity is always evaluated against the current sum, never against a single booking.

Occupancy on a grill table is modelled as a half-open interval. A `TableSeating` row records `seated_at`, an `expected_vacate_at` derived by the turn-over rule in §3.4, and an `actual_vacated_at` that stays null while the row is `ACTIVE`. The interval the row occupies is `seated_at` up to but not including `expected_vacate_at`. Two seatings that merely abut — where the earlier row's `expected_vacate_at` equals the later row's `seated_at` — do not conflict, because the earlier interval's endpoint is excluded from it. `occupied_minutes` reports the whole number of minutes between `seated_at` and `actual_vacated_at` once the row is `VACATED`, and between `seated_at` and the current clock while it is `ACTIVE`. `status` on the row is either `ACTIVE` or `VACATED`, beginning at `ACTIVE`.

The sushi counter uses the opposite convention and this contrast is intentional. A plated ticket holds the counter over the closed interval running from `requested_at` through `requested_at` plus the plate dwell constant, with both endpoints included. The counter's capacity is exactly one seated ticket. The consequences of that difference are worked out in §3.5.

### 2.7. Monetary Precision and Rounding Discipline

Every amount in this API is an integer number of cents; monetary values are never strings and are never fractional. Two different rounding conventions are used and they must not be conflated.

The `protein_cost` calculation produces a value rounded half up to exactly two decimal places. Every other rounding site in the system is an integer-cent operation: `table_minimum_trueup` and `seat_surcharge` both ceiling their result to the next whole multiple of 25 cents, `venue_cost_report` ceilings its summed total once to the next whole multiple of 100 cents, `credit_application` floors its cap term, and `turn_debt` rounds half up to whole minutes. The settlement calculation performs no rounding at any step: its inputs and outputs are already integer cents and are combined by exact addition and subtraction.

Two ordering rules are pinned and are not interchangeable with any naive or "fairer-looking" alternative. In the table-minimum true-up, the band factor is applied first and the ceiling is applied once to the band result; ceiling each guest's share separately and summing the ceilings is explicitly wrong, and so is ceiling the shortfall before applying the band factor. In the credit application, `check_cents` is evaluated first with `credit_applied_cents` held at the reservation's stored value, and only then is `credit_applied_cents` recomputed, after which `check_cents` is re-evaluated exactly once. The cap term is defined over the first evaluation and is never re-derived from the second.

### 2.8. Optimistic Concurrency on Holds, Clock-Ins and Check Closing

Optimistic concurrency protection applies to exactly three write operations, and to no others. Each of the three requires a version field in its request body, and each rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412).

Granting or re-parking a hold against a grill table requires the request to carry `expected_table_version`, the client's last-observed `version` of the target `GrillTable`. If the table's `version` has advanced since the client read it, the hold is rejected with `ERR_STALE_VERSION` at HTTP 412, because the client's view of the table's capacity and occupants cannot be honoured under the table's current state.

Posting a chef event — the clock-in family — requires `expected_venue_version`, the client's last-observed `version` of the `Venue`. A chef clocking in against a venue whose version has advanced is rejected with `ERR_STALE_VERSION` at HTTP 412, because the rotation pointer the client computed its rotation position from is stale.

Closing a booking requires `expected_reservation_version`, the client's last-observed `version` of the `Reservation`. Closing a booking whose version has advanced since the closing client read it is rejected with `ERR_STALE_VERSION` at HTTP 412, because the party size and the quote from which the check was computed are stale.

No other endpoint takes a version field under this contract. In particular, the maintenance-release operation on a grill table carries its own `expected_venue_version` input field as part of its declared body, but the three operations above are the complete set of optimistic-concurrency rules the system enforces.

### 2.9. Downtime, Cascades and Compensation

Maintenance is expressed as a `MaintenanceWindow` with a `maintenance_kind` drawn from `VENTILATION_SERVICE`, `GRILL_REBUILD` or `HOOD_DEEP_CLEAN`, a `planned_start_at` and a `planned_end_at`, and a `status` that begins at `SCHEDULED`, may be taken `ACTIVE`, and reaches its terminal `COMPLETED` state when the downtime is over or cancelled. The row may name a `table_id` when the downtime is scoped to one grill table; it is null for a venue-wide ventilation service.

A table-scoped window that is accepted does not just take the table out of service — it also cascades a follow-on `GRILL_REBUILD` window into existence against the same table, scheduled to begin when the first window ends and to run for the grill-rebuild duration constant. Cancelling a scheduled window completes any window cascaded from it and leaves the target table untouched. A ventilation service window that is accepted freezes the entire venue: the venue transitions into `VENTILATION_HOLD`, every grill table at the venue moves into `MAINTENANCE` with its `maintenance_resume_at` set to the window's `planned_end_at`, and the guests then on the floor are unwound through the staged cascade described in §3.7.

The venue also exposes a batch-epoch operation. Running an epoch advances `ops_epoch` by one, releases every hold whose window has already closed, retires every active maintenance window whose end has passed, lifts the venue out of `VENTILATION_HOLD` once the hood filter index has reached the service threshold and no active window remains, and recomputes the per-epoch floor charge and the turn-debt sweep from scratch. It increments the venue's `version` by one. Because these derived figures are recomputed rather than accumulated, a venue whose inputs are unchanged between two consecutive epochs is charged exactly the same amount twice and drifts by zero.

### 2.10. Nested Resource Retrieval and Left-to-Right Resolution

Requests that address a resource nested under a parent — a tier under a venue, a table under a venue, an occupancy under a booking — are resolved left to right, in the order the path and the request input list declare their identifiers. Every id in the path and every foreign key in the body must resolve before any business rule is evaluated. The first unresolvable segment determines the error returned, and the sibling returned always corresponds to that segment: `ERR_VENUE_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_TABLE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_SEATING_NOT_FOUND`, `ERR_CHEF_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_SUSHI_TICKET_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_PROTEIN_TICKET_NOT_FOUND`, each carrying HTTP 404. A request that resolves only part of its path never reaches a state check or a fiscal check; existence is settled first.

The system also enforces a fixed order across the whole validation cascade, and the order matters wherever several rules guard the same operation. Authentication is settled first, then permission, then existence, then whether the target is in a state from which the requested transition is declared (otherwise `ERR_INVALID_STATE`, HTTP 409), and only then the business rules. Within the business rules, a request that a workflow declares to be guarded by more than one rule is always reported against the highest-priority rule it violates, so a booking that both exceeds its hold limit and names a retired tier surfaces the hold-limit failure rather than the tier failure.

## 3. Business Logic & Workflows

### 3.1. Opening the Floor: Venues, Tiers and Grill Tables

A `PlatformAdmin` opens a venue by supplying `venue_name`, `city_code` and `ventilation_zone`; `filter_service_threshold_index` may be supplied and otherwise defaults to 40. The new `Venue` row starts `ACTIVE`, with `occupancy_freeze` false, `hood_filter_life_index` at 0 and `ops_epoch` at 0. From that point the venue's floor is configured by the same role, which defines a `TableTier` per capacity class. A tier names its `tier_code` — one of `T2`, `T4`, `T6`, `T8` or `T10` — its `seat_capacity`, its `base_rate_per_guest_cents`, its `minimum_bill_cents`, its `protein_gram_standard`, its per-table performance duration `chef_show_minutes`, its `turn_time_standard_minutes` and its `turn_time_celebration_minutes`. A tier also carries `over_capacity_ratio`, the fraction by which a party may exceed the tier's seat capacity before the tier is refused; it defaults to 1.25. Every tier is created `ACTIVE` and may later be retired, after which it is `RETIRED` and no new booking may name it, though bookings already naming it are unaffected. The `PlatformAdmin` may also create a `Party`-independent administrative act: retiring a tier.

A `FloorManager` commissions the physical tables. Each `GrillTable` is created with its `venue_id`, the `tier_code` it was built to, and its physical `seat_capacity`, and starts `AVAILABLE` with `pending_turn` false and `guests_seated` at 0. A table's `tier_code` need not match the seat capacity of the tier of the same code; the two are recorded separately because the floor may seat a party at a table whose physical seats differ from the tier's nominal band. A `FloorManager` also adds chefs to the venue's rotation roster: a `ChefAssignment` is created with its `venue_id`, `chef_name` and `station_zone`, and starts `OFF_SHIFT` with no `sequence_index` and no `current_table_id`.

Grill tables move through four floor states: `AVAILABLE`, `SEATED`, `TURNING` and `MAINTENANCE`. A table becomes `SEATED` when the first guests arrive at it, `TURNING` when a `FloorManager` or the chef signals that the show has concluded and the table must be stripped and reset, back to `AVAILABLE` once it is empty and clear of shows, and into `MAINTENANCE` when it is taken out of service. Two guards apply to leaving `TURNING`: the table may only return to `AVAILABLE` when its `guests_seated` has fallen to zero and no show phase at that table still carries the status `PLANNED` or `STARTED`, and it may only be moved into `MAINTENANCE` from `TURNING` when `guests_seated` is zero. A table already in `SEATED` may also be put into `MAINTENANCE` directly, but only when no `TableSeating` row at that table remains `ACTIVE`; a `MAINTENANCE_ENTER` in that situation stamps `maintenance_resume_at` with the supplied `resume_at` and drives any active show phases at the table to `SKIPPED`. `last_seated_at` records the clock instant of the most recent seating and is left untouched when a table merely moves from `TURNING` back to `AVAILABLE`. `pending_turn` is the flag that marks a full table: it becomes true the moment `guests_seated` reaches the table's `seat_capacity`, and it is cleared when the table begins turning. A venue's grill table may also be released from maintenance early through a `FloorManager` action carrying `expected_venue_version`; the table returns to `AVAILABLE` with `maintenance_resume_at` cleared, the matching scheduled window is completed, and a grill-rebuild window additionally resets `hood_filter_life_index`.

Chef rotation status is tracked through three values: `OFF_SHIFT`, `ON_STATION` and `CLEARING`. A chef clocks in with the `event_type` `CLOCK_IN` and moves from `OFF_SHIFT` to `ON_STATION`; the clock-in is refused with `ERR_STATION_OCCUPIED` (HTTP 409) when another chef at the same venue already holds the same `station_zone` while on station, and refused with `ERR_VENTILATION_FREEZE` (HTTP 409) while the venue's `occupancy_freeze` is true. On clock-in the chef's `sequence_index` is set to one more than the highest `sequence_index` among chefs at the venue already on station, or to 1 when there are none. When the chef leaves the grill, the `CLEAR_FINISH` event moves the row from `ON_STATION` to `CLEARING` and clears `current_table_id`. From `CLEARING` the chef either clocks out with `CLOCK_OUT`, returning to `OFF_SHIFT` with `sequence_index` cleared, or is pushed back onto the line by a `FloorManager` using `ROTATE_SUPPRESS`, which returns the chef to `ON_STATION` with a freshly assigned `sequence_index` computed the same way as on clock-in, and which is refused with `ERR_STATION_OCCUPIED` when the target zone is already held.

### 3.2. Parties, Draft Bookings and the Provisional Quote

A `Host` registers a `Party` with its `venue_id`, the `lead_guest_name`, the `contact_phone`, and optionally a `loyalty_tier`. The tier is one of `NONE`, `SILVER`, `GOLD` or `PLATINUM` and defaults to `NONE`. A new party starts `ACTIVE` with `no_show_count` and `loyalty_credit_cents` both at 0. `loyalty_credit_cents` is a reusable balance that is only ever granted when a posted charge is voided back to the party; it is strictly non-negative and the system never charges it into a negative. A party whose `status` has become `RESTRICTED` may not start or join a seating episode at all, and any attempt to submit, hold or seat such a party is rejected with `ERR_PARTY_RESTRICTED` (HTTP 403).

Drafting a booking requires a `venue_id`, a `party_id`, a `tier_id`, a `party_size`, a `scheduled_time`, and a `payment_mode` drawn from `CARD_ONLY`, `CARD_THEN_CREDIT` or `CREDIT_ONLY`. Optionally the host supplies `credit_to_apply_cents` (defaulting to 0), a `celebration` drawn from `NONE`, `BIRTHDAY`, `ANNIVERSARY`, `GRADUATION` or `CORPORATE` (defaulting to `NONE`), and an `invite_code`. The booking begins in `DRAFT` with `hold_count` at 0, and a provisional quote is stamped into `quote_final_cents` immediately. That provisional figure is the quote variant of the settlement rule, in which the celebration fee term is dropped and the booking is priced as the smaller of the tier's capacity-derived ceiling and the party's entitlement. The practical consequence is that a booking carrying a non-`NONE` celebration quotes strictly below the final bill for the same inputs whenever the entitlement plus the celebration fee would still sit under the tier ceiling.

Submitting a booking is the `SUBMIT` event and drives `DRAFT` to `REQUESTED`. Four conditions gate it. The party must be `ACTIVE`; the venue must be `ACTIVE`; the `party_size` must be at least 1 and no greater than the `seat_capacity` of the tier named by `tier_code` at that venue; and the `scheduled_time` must land exactly on the five-minute grid and sit within `BOOKING_HORIZON_MINUTES` of the current clock, that constant being 20160 minutes in either direction. A time off the grid or beyond that horizon is rejected with `ERR_BOOKING_HORIZON_EXCEEDED` (HTTP 422). A booking whose party size does not fit the named tier's capacity band is rejected with `ERR_TIER_MISMATCH` (HTTP 422), and one naming a tier that has been retired is rejected with `ERR_TIER_RETIRED` (HTTP 409). Where more than one of these applies, the earlier-priority rule is the one reported. On a successful submission the quote is recomputed and `last_ops_epoch` is stamped with the venue's current `ops_epoch`, so the floor can later tell which epoch the booking was priced against. The same five-minute-grid and horizon discipline applies when a maintenance window is scheduled.

### 3.3. Hold Windows and Combining Strangers at One Grill

Holding is the moment a party is provisionally promised a grill. A `Host` grants a hold by naming the target table, and the booking moves from `REQUESTED` to `HELD`. `hold_until` is stamped at the current clock plus the hold window, and `hold_count` advances by one. The request must carry `expected_table_version` as described in §2.8; a client whose last-observed table version no longer matches the table's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The hold is also refused while the venue's `occupancy_freeze` is true, with `ERR_VENTILATION_FREEZE` (HTTP 409); refused with `ERR_HOLD_LIMIT_EXCEEDED` (HTTP 409) once `hold_count` has already reached the cap of 3 holds in the current episode; and refused with `ERR_TABLE_OVER_CAPACITY` (HTTP 409) when the guests to be seated would push the table's `guests_seated` plus the incoming `party_size` past its `seat_capacity`.

The table a hold is granted against need not be empty. A table already carrying an `ACTIVE` seating is eligible provided the combined occupancy still fits under `seat_capacity`, which is what allows separate parties to be matched onto one grill. The grant is refused with `ERR_MAINTENANCE_CONFLICT` (HTTP 409) when a scheduled or active maintenance window on that table would overlap the window the hold would occupy, and refused with `ERR_TIER_MISMATCH` when the tier no longer suits the party.

Shared bookings are joined by the `invite_code`. When a booking carries a non-null `invite_code`, every other booking already holding the same code must still have `hold_until` later than the clock, and its `scheduled_time` must fall within the shared grace band of this booking's — otherwise the hold is rejected with `ERR_SHARED_SPLIT_INVALID` (HTTP 422). This is the mechanism by which two families who intend to share a grill are kept in step: if one of them lets its hold lapse, the other cannot quietly proceed as though the pair were still combined. A booking without an `invite_code` is solo and forms its own combination set of one.

A live hold can also be re-parked. Once `hold_until` has passed and the window has closed, a `Host` may grant a fresh hold onto a different table; the booking stays `HELD`, `hold_count` advances by one, the previous table is released, and a new `hold_until` is set twenty minutes out. Because the re-park is still a hold grant, it is subject to the same cap of 3 holds per episode and the same stale-version protection as a first hold, and it must find a table that satisfies every condition a first hold would.

A hold that is never claimed expires on its own. When the batch epoch runs, any booking still `HELD` whose `hold_until` has passed moves back to `REQUESTED`, `hold_until` and `table_id` are both cleared, and the released grill table returns to `AVAILABLE` unless it still carries another `ACTIVE` seating.

### 3.4. Seating, the Chef Rotation, and the Turn-over Window

Seating is the transition from `HELD` to `SEATED`, and it is the densest moment in the workflow. The request is refused with `ERR_VENTILATION_FREEZE` while the venue is frozen; refused with `ERR_HOLD_WINDOW_CLOSED` (HTTP 409) when the clock has already reached or passed `hold_until`, because an expired window is released rather than seated; refused with `ERR_TABLE_OVER_CAPACITY` when the guests would overflow the table; refused with `ERR_DUPLICATE_SEATING` (HTTP 409) when the booking already holds an `ACTIVE` occupancy at the target table; and refused with `ERR_MAINTENANCE_CONFLICT` when the interval the seating would occupy overlaps a scheduled or active maintenance window on that table. A held booking whose own table can no longer take the party rolls onto another fitting table, preferring one whose `tier_code` matches the booking's own tier before any other fitting table.

Two further gates are specific to seating. The first is the chef gate: at least one `ChefAssignment` at the venue must be `ON_STATION` and not already committed to a table that still carries an `ACTIVE` occupancy, and that chef must either have no finished show yet at this venue or have `minutes_since_show` of at least the minimum chef reset constant of 3 minutes. When no such chef exists the seating is refused with `ERR_CHEF_ROTATION_EXHAUSTED` (HTTP 409), and nothing is queued server-side; the floor must retry rather than assume a chef will materialise. The second is the party gate: a `RESTRICTED` party is refused with `ERR_PARTY_RESTRICTED`.

The chef is chosen by a deterministic rotation selector. The candidate set is every `ChefAssignment` at the venue that is `ON_STATION`, is not committed to a table that still carries an `ACTIVE` occupancy, and satisfies the reset condition above; chefs who are `OFF_SHIFT` or `CLEARING` are excluded from the candidate set entirely. Candidates are ranked by a composite key: first by a station bonus on the target table's `tier_code`, where a table tiered `T2` or `T4` carries a bonus of 80 and every other tier carries none, with the bonus negated in the key so that a larger bonus ranks earlier; then by `minutes_since_show` descending, so the chef who has rested longest goes first; then by `sequence_index` ascending; and finally by `chef_name` ascending as the canonical tie-break, never by `id`. The chosen chef is pinned to the table: his `current_table_id` is set to that table and the booking's `chef_assignment_id` records him. When no candidate satisfies the candidate set, the selector falls back to the venue's `ON_STATION` chefs, and it is that fallback population — empty when no chef is on station — that leaves the seating to be refused with `ERR_CHEF_ROTATION_EXHAUSTED`.

Seating then fires the grill table's own arrival transition in full. A `TableSeating` row is opened `ACTIVE` with its `guest_count`, `seated_at` at the clock and its `expected_vacate_at` computed by the turn-over rule below; `guests_seated` is recomputed and `last_seated_at` is stamped; `pending_turn` is set true the instant the recomputed `guests_seated` equals the table's `seat_capacity`; three `ShowPerformance` rows are planned for the booking at `course_phase` `SUSHI`, `GRILL` and `DESSERT`, all `PLANNED` with their `planned_start_at` values laid down by the course-timing rule; a seat surcharge is posted into the booking's `seat_surcharge_cents` and a `VenueLedgerEntry` of kind `SEAT_SURCHARGE` is written `POSTED`; and the booking's own pointers `current_seating_id`, `current_sushi_show_id` and `current_grill_show_id` are stamped by that cascade. The `TableSeating` row opened by the seating also carries its own `venue_id`, `table_id` and `reservation_id`, all of which are carried into its `status` transitions.

The turn-over window is computed from the booking's `scheduled_time`, snapped to the nearest earlier instant on the five-minute grid, and then advanced by one bucket width of five minutes to give the seating's start instant; the `expected_vacate_at` is that start instant plus the tier's `turn_time_standard_minutes` when the booking's `celebration` is `NONE`, and plus the tier's `turn_time_celebration_minutes` when it is not. Every instant in this computation lands on the five-minute grid. A `FloorManager` may extend a running occupancy by supplying `extension_minutes`, which advances `expected_vacate_at` by that many minutes; the extension is refused with `ERR_MAINTENANCE_CONFLICT` when the lengthened interval would collide with a maintenance window, and it is refused outright when the lengthened interval would run into another booking's hold on the same table.

### 3.5. The Course Sequence: Sushi, Grill, Dessert and Celebration

Each booking carries a phase chain that must run in order. `SUSHI` must finish before `GRILL` starts; `GRILL` must finish before `DESSERT` starts; and a `CELEBRATION` phase, which only ever comes into existence when a `DESSERT` phase starts on a booking whose `celebration` is not `NONE`, must wait until `DESSERT` finishes. Because the `CELEBRATION` row does not exist until `DESSERT` starts, a booking never carries a `CELEBRATION` row while its `DESSERT` row is still `PLANNED`. A show phase begins `PLANNED`, moves to `STARTED` when it is begun, and reaches its terminal `FINISHED` state when it is completed; a phase may instead be driven to `SKIPPED` from either `PLANNED` or `STARTED`, and a skipped phase may be reinstated back to `PLANNED`. `actual_start_at` is null until the phase starts, and `duration_minutes` reports the whole minutes between `actual_start_at` and the finish while the phase is not yet finished, defaulting to 0.

The minute at which a course is planned is derived from the booking's `scheduled_time` rather than taken literally. If the scheduled minute of the hour is below the hourly trigger minute of 35, the phase is planned on minute 6; otherwise it is planned on minute 35. The phase's `planned_start_at` is then `scheduled_time` with its minute replaced by that planned minute and its seconds and microseconds zeroed, so every planned start lands on a clean minute. The floor allows the planned minute to sit at most the early-grill tolerance of 10 minutes past the originally requested minute; a plan whose replaced minute would exceed that hard cap is rejected before it is ever scheduled. These planned starts are what the lateness accounting measures against: a grill phase whose `actual_start_at` is more than 6 minutes later than its `planned_start_at` adds 3 minutes to the venue's `shortfall_turn_debt_minutes`, and a grill phase that starts more than the early-grill tolerance of 10 minutes before its `planned_start_at` adds 2 minutes to the same account. Phases that are `SKIPPED` contribute nothing to either figure.

Starting a phase is refused with `ERR_SHOW_DEPENDENCY` (HTTP 409) when its prerequisite phase has not reached `FINISHED` — that is, a `GRILL` start requires the booking's `SUSHI` phase to be `FINISHED`, a `DESSERT` start requires its `GRILL` phase to be `FINISHED`, and a `CELEBRATION` start requires the assigned `ChefAssignment` to be `CLEARING` rather than still on station. When the start is accepted, `actual_start_at` is stamped with the clock.

A `GRILL` start has the richest side-effect set in the system. It issues protein: a `ProteinTicket` row is created carrying `standard_grams`, `issued_grams` and the status `POSTED`, with its `show_id` pointing at the phase, and the phase's `protein_ticket_id` points back at that row; the phase also records the grams it cooked in `protein_grams_served`, a field that is only meaningful for a `GRILL` phase and defaults to 0 elsewhere. The venue's `protein_cost_cents` and the chef's `pounds_protein_issued` are both recomputed. The venue's `hood_filter_life_index` advances by exactly one, because a completed grill course is a cooking minute against the hood bank. And on a booking whose `celebration` is not `NONE`, a `GRILL` start that occurs earlier than the phase's `planned_start_at` minus the early-grill tolerance of 10 minutes posts a `VenueLedgerEntry` of kind `CELEBRATION_CHARGE` and records the amount in `celebration_fee_cents`. A `DESSERT` start on a celebration booking additionally creates the `CELEBRATION` row at `PLANNED` if none exists yet; once that row is started, the dessert and celebration phases progress independently at the same table.

The protein issue itself is governed by a portion standard. The `standard_grams` for a grill phase is the sum of `guest_count` across the `ACTIVE` `TableSeating` rows at the show's table — which may be more than one row when separate parties share the grill — multiplied by the tier's `protein_gram_standard`. The `issued_grams` actually staged is that standard less one quarter of it, computed by dividing the standard by one port per guest and then by a guest-port share divisor of four and discarding the remainder with floor division; in effect the kitchen holds back one port's share in every four. `ports_per_guest` is the issued grams divided by the 30-gram port size, floored. `variance_grams` is `issued_grams` minus `standard_grams`, signed, so a shortfall is negative. A variance adjustment may raise the issue by at most 40 grams above `standard_grams` and may never take it below 1 gram; an adjustment outside that band, supplied as `delta_grams`, is rejected with `ERR_PROTEIN_VARIANCE_EXCEEDED` (HTTP 422). An accepted adjustment adds `delta_grams` to `issued_grams`, recomputes `variance_grams`, recomputes the ticket's `cost_cents`, and refreshes both the venue rollup and the chef's issued pounds.

A phase that is completed moves to `FINISHED` and records `duration_minutes`. A `GRILL` phase may only be finished once its measured duration is at least the tier's `chef_show_minutes` less the show under-run tolerance of 4 minutes; finishing short of that is rejected with `ERR_SHOW_UNDERRUN` (HTTP 409). Finishing a `GRILL` phase recomputes `final_bill_cents` and `check_cents` for the booking under the final variant of the settlement rule and leaves the chef's status untouched; the `ON_STATION` to `CLEARING` move remains the exclusive effect of the explicit `CLEAR_FINISH` chef event described in §3.1. When every phase row for a booking is `FINISHED`, the booking itself moves to `CLOSED`.

A `FloorManager` may skip a phase: from `PLANNED` the skip is refused with `ERR_INVALID_STATE` when the booking is already `CLOSED`, and from `STARTED` a skip is legal for a phase of any course. Skipping never voids sushi tickets automatically — a skipped sushi phase leaves its tickets where they stand. Reinstate, the reverse move from `SKIPPED` back to `PLANNED`, clears `actual_start_at` and is only legal while the booking is `HELD` or `SEATED`, and for a `GRILL` phase only when no `POSTED` protein ticket exists for this booking and chef pairing.

The sushi counter is managed separately and runs on a different interval convention from the grill. A `SushiTicket` is fired with its `venue_id`, `reservation_id`, `item_code`, `quantity`, `requested_at` and `unit_price_cents`, and starts with `prep_phase` `RAW_CUT` and `status` `OPEN`. Preparation advances `RAW_CUT` to `ROLLED` and then `ROLLED` to `PLATED`, and both moves are refused with `ERR_INVALID_STATE` unless the ticket is still `OPEN`. The second step is additionally time-gated: it may only happen while the clock is no later than `requested_at` plus the sushi plate lateness constant of 8 minutes, after which the only legal move on a plated ticket is backwards to `RAW_CUT`. A plating that would exceed that lateness bound is reported at the sushi-plate rule with `ERR_SUSHI_PLATE_LATE` rather than as a state failure. A plated ticket that is restaged stays `PLATED` and moves its `requested_at` forward by the restage constant of 5 minutes; a restart moves `PLATED` back to `RAW_CUT` and retains `quantity`, so the plate is remade from raw, and a void takes a ticket out of the `OPEN` state.

Every sushi advance moves the ticket forward by the same fixed delta, and that delta is the largest of three quantities: the base advance of 6 minutes; a lead figure of 9 minutes less one third of itself, with the division discarded to a whole minute by floor division; and the late-grill threshold of 6 minutes plus the late-or-early-grill debt of 3 minutes. Only `OPEN` tickets advance at all; a voided ticket is frozen at the phase it had reached, and its counter capacity is released immediately. The counter holds exactly one plated ticket at a time, and its occupancy is a closed interval from `requested_at` through `requested_at` plus the five-minute dwell constant, with both endpoints included. Any plating whose interval touches an already-occupying ticket at any point, including a single shared instant, is rejected at the sushi-plate-late rule with `ERR_SUSHI_PLATE_LATE` (HTTP 409); a second plating at exactly the first ticket's `requested_at` plus five minutes is therefore rejected and must begin strictly later. Only `OPEN` tickets with `prep_phase` `PLATED` occupy the counter; a voided ticket releases its capacity immediately, and a restage rebuilds the interval rather than extending it, because it moves `requested_at` forward rather than lengthening the dwell.

### 3.6. Celebrations, Party-Size Changes, and Settling the Check

A celebration is a service moment the floor must stage, and it costs money. When a celebration is present, a `CELEBRATION_CHARGE` is posted to the ledger and recorded in `celebration_fee_cents` if the grill show starts early by more than the tolerance, and the settlement rule adds a celebration fee term built from a base fee of 900 cents scaled by a per-occasion multiplier: `NONE` contributes nothing, `BIRTHDAY` and `ANNIVERSARY` both scale by 1.0, `GRADUATION` by 1.2, and `CORPORATE` by 1.5. Where several bookings share one grill through a common `invite_code`, every celebration present on those paired bookings is gathered up and the celebration term is scaled by the highest multiplier among them, so a corporate booking seated with a birthday booking carries the corporate scale.

Party size can change mid-episode. A `Host` raises or adjusts a seated booking's `party_size`, and optionally restates the `celebration`, and the booking remains `SEATED`. The change is refused with `ERR_TABLE_OVER_CAPACITY` (HTTP 409) when the new `party_size` exceeds the assigned table's `seat_capacity`, and refused with `ERR_VENTILATION_FREEZE` while the venue is frozen. An accepted change recomputes the provisional quote and may switch the settlement variant from a combined arrangement to a tier-up arrangement. The `SUSHI` and `GRILL` phases already planned for the booking are not rescheduled by a party-size change.

Closing the check is the terminal act of a seated visit. The booking moves from `SEATED` to `CLOSED`, and the request must carry `expected_reservation_version` as described in §2.8; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). Close is refused with `ERR_NO_ACTIVE_SEATING` (HTTP 409) when no `TableSeating` row is `ACTIVE` for the booking, and refused with `ERR_SEGREGATION_VIOLATION` (HTTP 403) when the acting role lacks the required grant. The check is settled in a pinned order: `final_bill_cents` is computed by the final variant of the settlement rule, the table-minimum true-up is computed from that settled `final_bill_cents` and folded into the `check_cents` term, `check_cents` is next evaluated with `credit_applied_cents` held at its stored value, then `credit_applied_cents` is recomputed as the smallest of the party's `loyalty_credit_cents`, the requested `credit_to_apply_cents`, and the credit cap, and `check_cents` is re-evaluated exactly once — the cap being read over that first (true-up-bearing) evaluation of the check.

Credit has four gates, all evaluated at close. A booking whose party carries `loyalty_tier` `NONE` or `SILVER` may not apply reusable credit at all, and a non-zero `credit_to_apply_cents` on such a booking is rejected with `ERR_CREDIT_INELIGIBLE` (HTTP 422). A non-zero application smaller than the 500-cent minimum ticket amount is rejected with `ERR_CREDIT_BELOW_MINIMUM` (HTTP 422). An application exceeding the cap — the smaller of 2500 cents and twelve percent of the pre-credit check — is rejected with `ERR_CREDIT_OVER_CAP` (HTTP 422), the cap being floored to a whole cent and taken from the first evaluation of the check. Finally, an application the party's `loyalty_credit_cents` cannot cover is rejected with `ERR_CREDIT_EXCEEDED` (HTTP 402). Where more than one gate fails, the higher-priority one is reported. When credit is applied, the consumed amount moves out of `loyalty_credit_cents`; the balance is floored at zero and the shortfall is never charged back as a negative credit.

Closing also unwinds the floor. Every `ACTIVE` occupancy row for the booking is vacated, the assigned table is driven from `SEATED` through `TURNING`, and the whole turn-debt cascade below runs. If the settled `final_bill_cents` falls below the tier's `minimum_bill_cents`, a table-minimum true-up is posted as a `VenueLedgerEntry` of kind `TABLE_MINIMUM_TRUEUP` with status `POSTED`. The true-up works on the raw shortfall — the tier minimum less the final bill, floored at zero — and bands it: a zero shortfall yields a band of zero; a shortfall of up to 1000 cents takes a factor of 0.50; a shortfall of up to 2000 cents takes a factor of 0.60; and any larger shortfall takes a factor of 0.75 applied against a fixed 2000-cent ceiling rather than against the shortfall itself, which makes the banded amount jump discontinuously as the shortfall crosses 2000 cents. The banded amount is then ceilinged once to the next whole multiple of 25 cents. For a 1200-cent shortfall the banded amount is 720 cents and the true-up is 725 cents; ceiling each guest's share separately and summing would produce 800 and is explicitly wrong, and ceiling before applying the band factor is wrong as well.

### 3.7. Ventilation Holds, Maintenance Accept, and the Abandonment Cascade

Downtime begins as a scheduled window. A `FloorManager` schedules a `MaintenanceWindow` with a `maintenance_kind`, a `planned_start_at`, a `planned_end_at`, and optionally a `table_id`, and the row starts `SCHEDULED`. Accepting a window moves it to `ACTIVE` and is gated three ways: the `planned_start_at` may not be earlier than the clock minus the maintenance late grace constant, so a window cannot be accepted long after it was meant to start; no other window against the same `table_id` may already be `ACTIVE`; and a grill-rebuild window may only be accepted against a table that is `AVAILABLE` or `TURNING`. A window accepted outside those bounds is rejected with `ERR_MAINTENANCE_WINDOW_LATE` (HTTP 409) when the lateness is the problem and with `ERR_INVALID_STATE` otherwise; where more than one of these gates applies to the same request, the state guards — the sibling-window hold and the grill-rebuild target-state condition — are reported ahead of the lateness guard. Accept additionally requires the segregation-of-duties grant, and is rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403) when the role lacks it. Cancelling a `SCHEDULED` window completes it and completes any window cascaded from it, leaving the target table untouched. Reopening an `ACTIVE` window returns it to `SCHEDULED` and releases the venue from any freeze it caused; where the window is venue-wide, the tables the freeze took out of service return to the floor — a table that no longer carries an `ACTIVE` occupancy returns to `AVAILABLE` and a table that still carries one returns to `SEATED`, each with `maintenance_resume_at` cleared — and where the window is table-scoped, its own target table returns to `AVAILABLE` with `maintenance_resume_at` cleared. The reopen is refused with `ERR_INVALID_STATE` when the venue still holds a `SEATED` booking under its freeze or holds another window that is `ACTIVE`. A window that is still `ACTIVE` at the clock past its `planned_end_at` is completed by the batch epoch, and a ventilation window additionally requires `hood_filter_life_index` to have reached `filter_service_threshold_index` before the venue may be unfrozen.

Accepting a table-scoped window also cascades a companion. A second `MaintenanceWindow` of kind `GRILL_REBUILD` is created `SCHEDULED` against the same `table_id`, beginning at the accepted window's `planned_end_at` and ending one grill-rebuild duration later. The accepted window drives its table into `MAINTENANCE` with `maintenance_resume_at` set to the window's `planned_end_at`, and a grill-rebuild window that completes resets the venue's `hood_filter_life_index` to 0, because the rebuild replaces the filter bank.

Accepting a venue-wide ventilation window is the most destructive single operation in the API, because it unwinds a floor mid-service. It cascades in five hops. First, the venue's `status` moves from `ACTIVE` to `VENTILATION_HOLD` and `occupancy_freeze` becomes true, which blocks every seating episode at the venue while it holds. Second, each grill table at the venue that is `AVAILABLE` or `SEATED` moves to `MAINTENANCE` with `maintenance_resume_at` set to the accepted window's `planned_end_at`. Third, because each of those tables has left the floor, each table drives its own occupancy rows from `ACTIVE` to `VACATED`, which stamps `actual_vacated_at` at the clock, recomputes `occupied_minutes`, recomputes the table's `guests_seated`, and recomputes the venue's `shortfall_turn_debt_minutes`. Fourth, each booking left with no remaining `ACTIVE` occupancy row moves to `ABANDONED`, with `hold_until` and `table_id` both cleared. Fifth, each booking that has just been abandoned drives every `POSTED` `VenueLedgerEntry` for it to `VOIDED`, and each such void credits the party's `loyalty_credit_cents` by the entry's positive amount.

An abandoned booking can be recovered. Reopening it moves `ABANDONED` back to `HELD`, with a fresh `table_id` and a fresh `hold_until` set exactly as on a first hold; it requires the venue to be `ACTIVE` and to hold no booking still `SEATED`, requires `hold_count` to still be under the cap of 3, and requires a table that satisfies every condition a first hold would, and is otherwise rejected with `ERR_INVALID_STATE` or, where the hold cap is the problem, with `ERR_HOLD_LIMIT_EXCEEDED`. The ledger entries voided by the abandonment cascade are restored to `POSTED` and the party's credit is reduced again by the same amount, but only for entries voided by the abandonment cascade — an entry voided by an explicit void stays `VOIDED` through a reopen. `hold_count` is not reset by abandonment or reopen, so an episode that has already burned its three holds cannot manufacture a fourth by being abandoned. When a fresh seating follows a reopen, new seat surcharges are posted normally.

A posted charge can also be voided directly by a `Host`. Voiding moves a `VenueLedgerEntry` from `POSTED` to `VOIDED` and credits the party's `loyalty_credit_cents` by its `amount_cents` when that amount is positive. Each ledger row records which kind of movement it is through `entry_kind`, one of `SEAT_SURCHARGE`, `CELEBRATION_CHARGE` or `TABLE_MINIMUM_TRUEUP`, and its signed `amount_cents` where a positive value charges the party and a negative value credits it. The entry's own `status` is `POSTED` when written and becomes `VOIDED` when it is voided, and `version` advances on that change like any other mutation. A voided entry can only return to `POSTED` through the reopen path just described, and only when the referenced booking is `HELD` and the entry was voided by the abandonment cascade rather than by an explicit void.

### 3.8. Turn Debt, Protein Cost, and the Per-Epoch Floor Charge

Three venue-level accounts are maintained continuously and are recomputed rather than accumulated.

The first is protein cost. Each `ProteinTicket` carries a `show_id` pointing at the grill phase that posted it, the `chef_assignment_id` of the chef who issued it, its `standard_grams`, its `issued_grams`, its signed `variance_grams`, and a `cost_cents` computed as the issued grams multiplied by a pinned cost of 4.0 cents per gram and rounded half up to two decimal places. The venue's `protein_cost_cents` is the sum of that per-ticket cost across every ticket at the venue whose status is `POSTED`; voided tickets are excluded from the rollup and from the chef's `pounds_protein_issued`, which is the sum of issued grams across the chef's posted tickets divided by 453.6 and rounded to two decimals. `completed_show_count` counts the chef's phases that have reached `FINISHED`, and `minutes_since_show` is the whole minutes between the clock and the `actual_start_at` of the chef's most recent finished show at the venue, reported as 0 when the chef has no finished show yet. The read-only protein cost report presents the rolled-up cost, an integer count of variance grams, and a control allowance computed as five percent of the cost, which is never persisted into `protein_cost_cents`.

The second is turn debt. Whenever an occupancy row is vacated, its over- or under-run against the tier's turn-time standard is bucketed. The bucket index is the shortfall in whole minutes divided by the five-minute bucket width, floored, and then capped at one less than the number of buckets, which is twenty. The bucket's base minutes run from 3 minutes for the first bucket through to 12 minutes for the last, in the ascending sequence 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12. The base minutes are then multiplied by a burst multiplier of 1.5 when every table at the venue is turning at the same clock instant and by 1 otherwise, and the product is rounded half up to whole minutes and added to the venue's `shortfall_turn_debt_minutes`. The account is recomputed from the closed occupancy rows on every write and is never permitted to exceed the per-reservation turn-debt cap multiplied by the count of closed bookings at the venue. The batch epoch's sweep allocates the venue's 480-minute shortfall pool across the closed occupancies in bucket order, filling bucket 0 before bucket 1 and so on; whatever does not fill the last bucket is allocated whole, with no fractional carry, and a tie inside a bucket is broken by `reservation_id` ascending — a canonical key, never the `id`.

Turn debt also has a disciplinary consequence. The venue records `shortfall_turn_debt_minutes`, and when a table turns and the recomputed total exceeds the turn-debt escalation threshold, every party at that venue whose `no_show_count` has reached 2 is moved to `RESTRICTED`. The same restriction is applied directly when a party's own no-show count reaches the constant of 2, as described below.

The third is the per-epoch floor charge. Each time the batch epoch advances, the venue's `restaurant_charge_cents` is recomputed from scratch — never accumulated — as the billable guest count multiplied by a per-guest assignment fee of 299 cents. The billable guest count is the sum, across the venue's grill tables, of the smaller of each table's `seat_capacity` and the assignable guest cap of 12. Every table whose tier is `ACTIVE` is counted, regardless of the table's own status, so a table sitting in `MAINTENANCE` still contributes. A multiplier band is then applied: a billable count below 50 is `LOW` at 0.90, a count from 50 through 70 inclusive is `MEDIUM` at 1.00, and a count above 70 is `HIGH` at 1.20. The read-side venue cost report is computed differently and is never persisted: it sums, across the venue's grill tables whose tier is one of `T2`, `T4`, `T6` or `T8`, the product of the tier's `base_rate_per_guest_cents` and its `protein_gram_standard`, and then ceilings that summed total once to the next whole multiple of 100 cents; ceiling each table's product before summing is a different figure and is wrong.

No-shows are the fourth thread in this accounting. Marking a booking `NO_SHOW` from `REQUESTED` requires the clock to be past `scheduled_time` and is otherwise rejected with `ERR_INVALID_STATE`; marking it from `HELD` requires the clock to be past `scheduled_time` plus the no-show grace constant. A `Host` posts the `MARK_NO_SHOW` event, the party's `no_show_count` advances by one, and the booking's `hold_until` and `table_id` are cleared. When the party's count reaches exactly 2 the party moves to `RESTRICTED` in the same transition, and the booking's posted ledger entries are voided, each void crediting the party's `loyalty_credit_cents` by its positive amount. A no-show or abandoned reservation also has its seat surcharge reversed, not by the surcharge calculation itself but by that voided-ledger cascade. `NO_SHOW` and `CLOSED` are the booking's terminal statuses.

### 3.9. The Settlement Ledger: How a Check Is Priced

The settlement rule is the spine of the business logic and is evaluated at a booking's submission, at every hold grant, at every party-size change, at a `GRILL` finish, at a no-show, at abandonment, at an occupancy vacating, and at close. It carries two variants. The quote variant runs while the booking is `DRAFT`, `REQUESTED` or `HELD` and writes `quote_final_cents`; the final variant runs when a `GRILL` phase finishes, when an occupancy vacates, or when the booking closes, and writes `final_bill_cents` and `check_cents`. The only difference between them is the celebration term: the quote drops it, so a celebration booking quotes strictly lower than the final bill of the same inputs whenever the entitlement plus the celebration fee would still sit under the tier ceiling.

The combination set for a booking, called T, is the set of distinct bookings at the same venue that carry the same non-null `invite_code`, tier `TABLE_TIER`, and `hold_until` later than the clock. A booking without an `invite_code` has an empty T. Bookings that have reached `NO_SHOW`, `ABANDONED` or `CLOSED` are excluded from T. The guests billed for a tier is the smaller of the party size and a cap of 3.

The entitlement for the booking's own tier is its `party_size` multiplied by that tier's `base_rate_per_guest_cents`. The secured figure is the sum of the tier minimums over every booking in T. The capacity ceiling is the tier's `seat_capacity` multiplied by its `base_rate_per_guest_cents`. The celebration term is the 900-cent base fee scaled by the multiplier of the highest celebration present across the booking itself and every booking in T. The provisional figure P is the smaller of the capacity ceiling and the entitlement plus the celebration term — note that the tier minimum is deliberately not a floor under P, because a small party is allowed to fall under the minimum and attract a true-up instead. The other-parties figure is the sum, over every booking in T, of that booking's tier rate multiplied by the smaller of its party size and the cap of 3, with the booking's own share removed when the booking is itself in T so that it is counted once and only once. The sushi figure is the sum of `quantity` times `unit_price_cents` over the booking's `OPEN` sushi tickets. The compliment figure is 500 cents when every booking in T has a party at `PLATINUM` loyalty tier and zero otherwise.

The base is then chosen by three cases. When T is empty the base is P floored at zero. When the secured figure is smaller than P the base is the larger of the secured figure plus the sushi figure plus the other-parties figure, and P, floored at zero. When the secured figure is at least P the base is the smaller of the secured figure and P, floored at zero. The final bill is the base less the compliment figure. The check is the final bill plus the seat surcharge less the applied credit plus the true-up, the four terms evaluated strictly left to right, each already an integer cent amount, with no rounding anywhere in that step.

The seat surcharge is computed per booking and is charged to every booking regardless of `payment_mode` and regardless of `loyalty_tier`. Its raw value is the tier's `base_rate_per_guest_cents` multiplied by the guests billed — the smaller of the party size and the cap of 3 — and divided by one more than the party size. The raw value is then ceilinged once, per booking and not per guest, to the next whole multiple of 25 cents. Bookings that reach `NO_SHOW` or `ABANDONED` have the surcharge reversed by the voided-ledger cascade rather than by this calculation.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource, or that add a distinct resource to an existing collection, return `200 OK`. Reads return `200 OK`. The table below is an index of the HTTP surface only: it deliberately omits request bodies, response bodies and side effects. The authoritative behaviour for each operation is the workflow narrative in §3, and the request fields an operation accepts are named there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-floor/venues` | Open a new teppanyaki venue | PlatformAdmin |
| GET | `/service-floor/venues` | List venues | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/venues/{venue_id}` | Get one venue | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/venues/{venue_id}/run_ops` | Advance the venue's batch epoch | FloorManager |
| GET | `/service-floor/venues/{venue_id}/cost-report` | Read the venue-wide cost report | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/venues/{venue_id}/tiers/{tier_id}/retire` | Retire a table tier | PlatformAdmin |
| POST | `/service-floor/venues/{venue_id}/tables/{table_id}/maintenance-release` | Release a grill table from maintenance | FloorManager |
| GET | `/service-floor/venues/{venue_id}/protein-cost-report` | Read the protein cost report with its control allowance | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/parties` | Register a guest party | Host |
| GET | `/service-floor/parties` | List parties | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/parties/{party_id}` | Get one party | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/tiers` | Configure a table tier at a venue | PlatformAdmin |
| GET | `/service-floor/tiers` | List table tiers | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/tiers/{tier_id}` | Get one table tier | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/tables` | Commission a physical grill table | FloorManager |
| GET | `/service-floor/tables` | List grill tables | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/tables/{table_id}` | Get one grill table | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/tables/{table_id}/events` | Post a grill-table event (SEAT, TURN, TURN_RELEASE, MAINTENANCE_ENTER) | FloorManager |
| POST | `/service-floor/reservations` | Draft a booking for a guest party | Host |
| GET | `/service-floor/reservations` | List bookings | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/reservations/{reservation_id}` | Get one booking | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/reservations/{reservation_id}/holds` | Grant a hold window or re-park an expired hold | Host |
| POST | `/service-floor/reservations/{reservation_id}/seat` | Seat a held booking at its assigned table | Host |
| POST | `/service-floor/reservations/{reservation_id}/events` | Post a booking event (SUBMIT, MARK_NO_SHOW) | Host |
| POST | `/service-floor/reservations/{reservation_id}/party-size` | Change a seated booking's party size | Host |
| POST | `/service-floor/reservations/{reservation_id}/close` | Close a seated booking and settle the check | Host |
| POST | `/service-floor/reservations/{reservation_id}/reopen` | Reopen a booking abandoned by a ventilation hold | Host |
| GET | `/service-floor/seatings` | List table occupancies | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/seatings/{seating_id}` | Get one table occupancy | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/seatings/{seating_id}/extend` | Extend an active occupancy window | FloorManager |
| POST | `/service-floor/chefs` | Add a chef to a venue's rotation roster | FloorManager |
| GET | `/service-floor/chefs` | List chefs | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/chefs/{chef_id}` | Get one chef | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/chefs/{chef_id}/events` | Post a chef event (CLOCK_IN, CLEAR_FINISH, CLOCK_OUT, ROTATE_SUPPRESS) | Chef, FloorManager |
| GET | `/service-floor/shows` | List show phases | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/shows/{show_id}` | Get one show phase | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/shows/{show_id}/events` | Post a show event (START, FINISH, SKIP, REINSTATE) | Chef, FloorManager |
| POST | `/service-floor/maintenance-windows` | Schedule grill or ventilation downtime | FloorManager |
| GET | `/service-floor/maintenance-windows` | List maintenance windows | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/maintenance-windows/{window_id}` | Get one maintenance window | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/maintenance-windows/{window_id}/accept` | Take the scheduled downtime now | FloorManager |
| POST | `/service-floor/maintenance-windows/{window_id}/cancel` | Cancel a scheduled downtime | FloorManager |
| POST | `/service-floor/maintenance-windows/{window_id}/reopen` | Release an active downtime early | FloorManager |
| POST | `/service-floor/sushi-tickets` | Fire a sushi ticket for a booking | SushiChef |
| GET | `/service-floor/sushi-tickets` | List sushi tickets | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/sushi-tickets/{ticket_id}` | Get one sushi ticket | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/sushi-tickets/{ticket_id}/events` | Post a sushi event (ADVANCE, RESTAGE, RESTART, VOID) | SushiChef |
| GET | `/service-floor/ledger-entries` | List ledger entries | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/ledger-entries/{entry_id}` | Get one ledger entry | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/ledger-entries/{entry_id}/void` | Void a posted ledger entry and credit the party | Host |
| GET | `/service-floor/protein-tickets` | List protein issues | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| GET | `/service-floor/protein-tickets/{ticket_id}` | Get one protein issue | PlatformAdmin, FloorManager, Host, Chef, SushiChef |
| POST | `/service-floor/protein-tickets/{ticket_id}/variance` | Adjust the protein grams issued for a table | Chef, FloorManager |
| POST | `/service-floor/protein-tickets/{ticket_id}/events` | Post a protein event (VOID) | Chef |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

The logical clock is a test-driving capability. It accepts a single `current_utc` instant. The server's startup default time is exactly `2026-09-01T00:00:00Z`, and before the clock is set it must read that default rather than real wall-clock time. Setting the clock re-evaluates every time-gated rule in §3 against the new instant.

## 5. Error Code Catalogue

This catalogue lists the error identifiers and their HTTP status codes only. The conditions that trigger each error are stated in §2 and §3 alongside the workflows they guard; they are deliberately not repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_TABLE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_SEATING_NOT_FOUND` | 404 Not Found |
| `ERR_CHEF_NOT_FOUND` | 404 Not Found |
| `ERR_SHOW_NOT_FOUND` | 404 Not Found |
| `ERR_MAINTENANCE_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SUSHI_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_PROTEIN_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_HORIZON_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MAINTENANCE_CONFLICT` | 409 Conflict |
| `ERR_TIER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TIER_RETIRED` | 409 Conflict |
| `ERR_TABLE_OVER_CAPACITY` | 409 Conflict |
| `ERR_HOLD_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HOLD_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SHARED_SPLIT_INVALID` | 422 Unprocessable Entity |
| `ERR_VENTILATION_FREEZE` | 409 Conflict |
| `ERR_CHEF_ROTATION_EXHAUSTED` | 409 Conflict |
| `ERR_STATION_OCCUPIED` | 409 Conflict |
| `ERR_SHOW_DEPENDENCY` | 409 Conflict |
| `ERR_SHOW_UNDERRUN` | 409 Conflict |
| `ERR_PROTEIN_VARIANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREDIT_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CREDIT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CREDIT_OVER_CAP` | 422 Unprocessable Entity |
| `ERR_CREDIT_EXCEEDED` | 402 Payment Required |
| `ERR_PARTY_RESTRICTED` | 403 Forbidden |
| `ERR_NO_ACTIVE_SEATING` | 409 Conflict |
| `ERR_DUPLICATE_SEATING` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_LATE` | 409 Conflict |
| `ERR_SUSHI_PLATE_LATE` | 409 Conflict |
| `ERR_SEGREGATION_VIOLATION` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |