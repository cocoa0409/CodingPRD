# Dealer Network One-Way Rental API — Product Requirements Document

## 1. Introduction

A national equipment-rental brand does not own most of its storefronts. Instead, a network of independent dealers holds company-owned trucks, trailers, and tow dollies at their own lots, rents them to walk-in and online customers, and earns commission on every settled rental. Because one-way rentals return equipment at the destination rather than the origin, the fleet continuously drifts: college towns empty out in May, Sun Belt cities accumulate trailers all winter, and somebody has to pay to haul the surplus back. That somebody is the network, and the cost of those repositioning moves is exactly what the pricing engine must anticipate when it sets a lane's rate for a season.

This document specifies the Dealer Network One-Way Rental API, the system of record for that operating model. It covers dealer and location lifecycle, fleet registration and unit-level status, lane-and-season rate management with imbalance-driven surcharges, the reservation funnel from quote through confirmation with a guaranteed-unit promise, towing-compatibility screening against the customer's registered vehicle, pickup and return of rental agreements, damage protection products and the claims workflow behind them, repositioning tasks that rebalance the fleet, moving-supply and self-storage cross-sell at the counter, and the quarterly settlement that pays dealers their commission — minus a clawback when performance falls short.

The design assumes segregation of duties throughout: the person who files a damage claim may not approve it, the person who approves a settlement may not pay it, and only central network operators may suspend dealers, orchestrate repositioning, or advance the logical clock. All monetary values are integer cents. Time inside the system is governed by a controllable logical clock so that pickup windows, no-show deadlines, idle penalties, and settlement quarters are deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which that principal acts. A request missing either header, presenting an empty `X-User-ID`, or naming a role outside the declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the API expects them, are `NetworkAdmin`, `DealerAgent`, `Customer`, `PricingManager`, `RepositionDriver`, and `FinanceReviewer`.

Identity semantics differ per role, and they matter because several checks compare `X-User-ID` against persisted rows:

- When `X-User-Role` is `DealerAgent`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` — such as the holding dealer of an `EquipmentUnit` or the `dealer_id` of a `DealerSettlement` — compare the resource's dealer foreign key to `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on a `Reservation` compare the reservation's `customer_id` to `X-User-ID`.
- When `X-User-Role` is `RepositionDriver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity of its own; the server compares it to the `assigned_driver_id` recorded on a `RepositionTask` when the driver completes that task.
- When `X-User-Role` is `NetworkAdmin`, `PricingManager`, or `FinanceReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `filer_user_id` on a `DamageClaim` when a claim is filed, or as the approver identity consulted at settlement pay time) but does not compare it to any entity's `id`.

Segregation of duties is enforced on two specific pairs of operations, and the identity comparison is always between the `X-User-ID` values of the two human steps, regardless of role. First, the operator who approves or denies a `DamageClaim` must not be the operator whose identifier was recorded as that claim's `filer_user_id` at filing time. Second, the `FinanceReviewer` who pays a `DealerSettlement` must not be the operator who approved it. A violation of either pairing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts `limit` and `offset` as query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. The `meta` envelope of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filter, not just the page), and `has_more` (true when rows exist beyond the returned page). Unless a listing states otherwise, list results are ordered by `created_at` ascending.

### 2.4. Common Resource Fields and Entity Identity

Every persistent resource carries an `id` — a server-minted UUID with no type prefix — assigned at creation and never reused. With one exception noted below, every entity also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at its initial value and increments by exactly 1 on every mutation of that entity, including mutations caused by cascades (for example, a damage-claim approval that recomputes an agreement's damage charges bumps that agreement's `version`). The exception is `ReservationEvent`, the append-only audit row: it carries `id` and `created_at` only; `updated_at` and `version` are absent because events are never modified after being appended.

### 2.5. The Logical Clock

The system does not consult wall-clock time for business decisions. A logical clock governs every time-dependent rule: the minimum `pickup_date` at reservation creation, the no-show deadline, the `checkout_at` and `returned_at` stamps on a rental agreement, the `scheduled_after` instant on a reposition task, the idle-penalty measurement on a repositioning unit, and the projected-days computation behind a settlement preview. Before any administrative call adjusts it, the logical clock reads exactly 2026-09-01T00:00:00Z — the server startup default — and it must never fall back to wall-clock time. A `NetworkAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` value.

### 2.6. Monetary Precision and Rounding

All money is integer cents; no fractional cents exist anywhere in the system. Where a formula produces a non-integer intermediate (a discounted day rate, a per-agreement commission, a per-order cross-sell commission, a bundle discount, a per-line supply extension, a late-day rate, a long-duration protection premium), that intermediate is rounded half-up to the nearest integer cent at the step the formula specifies — and only there. Two rounding disciplines recur and are binding: per-line rounding, where each agreement, order, or line item is rounded individually and the rounded values are then summed (summing first and rounding once is forbidden), and step-order rounding, where a daily rate is rounded before being multiplied by a day count, never the reverse. The lane imbalance factor is the one non-monetary computed quantity with its own precision: 4 decimal places, rounded half-up. Allocation scores are computed to 2 decimal places, rounded half-up.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint takes a version field. Confirming a reservation requires the request to carry `expected_reservation_version`, the client's last observed `version` of that reservation; if the reservation's current `version` has advanced since the client last read it — for example because another writer reassigned the reservation to a different dealer and recomputed its price snapshot — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a quoted price and dealer it has not observed. Settling a rental agreement requires the request to carry `expected_agreement_version`, the client's last observed `version` of that agreement; if another writer has advanced the agreement's `version` since — for example a damage-claim approval that recomputed `damage_charge_cents` — the settle is rejected with `ERR_STALE_VERSION` (HTTP 412), so a settle carrying a pre-approval version cannot freeze a stale total.

### 2.8. Layered Request Validation

Every request is checked against a fixed ladder of validations, evaluated in the order given here; the first failing layer determines the error. (1) Authentication: `X-User-Role` present and one of the declared roles, then `X-User-ID` present and non-empty — failures are `ERR_UNAUTHENTICATED`. (2) Authorization: the role is permitted on the endpoint — `ERR_FORBIDDEN`. (3) Path existence: every identifier embedded in the URL is resolved left-to-right — a dangling path id yields `ERR_NOT_FOUND` (HTTP 404). (4) Body referential integrity: every foreign key in the request body — dealer, location, customer, reservation, agreement, vehicle profile, and so on — resolves to an existing row, else `ERR_REFERENCE_NOT_FOUND` (HTTP 404). (5) Natural-key uniqueness on creation, else `ERR_DUPLICATE_RESOURCE`. (6) State admissibility: the target entity's current state must permit the requested transition, else `ERR_INVALID_STATE` (HTTP 409). (7) Optimistic concurrency, where §2.7 applies, else `ERR_STALE_VERSION`. (8) Segregation of duties on claim adjudication and settlement payment, else `ERR_SEGREGATION_OF_DUTIES`.

Below those generic layers, domain checks run in this pinned order where several apply to the same endpoint: towing compatibility (`ERR_TOW_INCOMPATIBLE`, HTTP 422), driver-license verification (`ERR_LICENSE_NOT_VERIFIED`, HTTP 422), origin-dealer posture (`ERR_DEALER_SUSPENDED`, HTTP 409), location posture (`ERR_LOCATION_CLOSED`, HTTP 409), date-range coherence (`ERR_INVALID_DATE_RANGE`, HTTP 400), unit availability (`ERR_NO_UNIT_AVAILABLE`, HTTP 409), active-rate presence (`ERR_NO_ACTIVE_RATE`, HTTP 422), reassignment-candidate pool (`ERR_NO_REASSIGNMENT_CANDIDATE`, HTTP 409), open claims at settle (`ERR_OPEN_CLAIMS`, HTTP 409), zone storage capacity (`ERR_STORAGE_CAPACITY_EXCEEDED`, HTTP 409), reposition driver identity (`ERR_DRIVER_MISMATCH`, HTTP 403), claim-amount validity (`ERR_INVALID_CLAIM_AMOUNT`, HTTP 422), dealer holdings at deactivation (`ERR_DEALER_HAS_ACTIVE_HOLDINGS`, HTTP 409), and finally the existence of an active dealer at a unit's destination (`ERR_NO_ACTIVE_DEALER_AT_LOCATION`, HTTP 409). A missing required field, a value of the wrong type, or an unknown enum value anywhere in a request is `ERR_INVALID_REQUEST` (HTTP 400). The ordering matters: on a reservation confirm, for instance, a towing failure surfaces as `ERR_TOW_INCOMPATIBLE` rather than being masked by a later license or availability check, and a state-layer rejection (not `QUOTED`, or a stale `expected_reservation_version`) always precedes every one of the domain checks.

### 2.9. Lifecycle Vocabulary

Every entity carries a `status` field whose value is one of its machine's states; the `status` strings below are exact uppercase values, and the API never accepts or emits synonyms. A `Dealer` is `ACTIVE`, `SUSPENDED`, or `DEACTIVATED` (terminal). A `Location` is `OPEN` or `CLOSED`. An `EquipmentUnit` is `AVAILABLE`, `HELD`, `OUT`, `REPOSITIONING`, `MAINTENANCE`, or `RETIRED` (terminal). A `LaneRate` is `DRAFT`, `ACTIVE`, or `SUPERSEDED` (terminal). A `Reservation` is `QUOTED`, `CONFIRMED`, `REASSIGNED`, `FULFILLED`, `CANCELLED`, `EXPIRED`, or `NO_SHOW` (the last four terminal). A `RentalAgreement` is `ACTIVE`, `RETURNED`, or `SETTLED` (terminal). A `DamageProtectionPlan` is `ACTIVE`, `EXPIRED`, or `CANCELLED` (the last two terminal). A `DamageClaim` is `FILED`, `APPROVED`, `DENIED`, or `PAID` (the last three terminal, though `DENIED` may be reopened while the agreement is unsettled). A `RepositionTask` is `OPEN`, `ASSIGNED`, `COMPLETED`, or `CANCELLED` (the last two terminal). A `DealerSettlement` is `DRAFT`, `APPROVED`, `PAID` (terminal), or `DISPUTED`. A `ReservationEvent`'s `event_type` is one of `CREATED`, `CONFIRMED`, `REASSIGNED`, `CANCELLED`, `EXPIRED`, `NO_SHOW`.

Shared vocabularies: equipment categories are `TRUCK_10FT`, `TRUCK_15FT`, `TRUCK_26FT`, `TRAILER_4X8`, `TRAILER_6X12`, and `TOW_DOLLY`; geographic zones are `NORTH`, `SOUTH`, `EAST`, `WEST`, and `CENTRAL`; seasons are `PEAK`, `SHOULDER`, and `OFF_PEAK`; hitch classes are `CLASS_I`, `CLASS_II`, `CLASS_III`, `CLASS_IV`, and `NONE`; rental kinds are `ROUND_TRIP` and `ONE_WAY`; protection tiers are `BASIC`, `STANDARD`, and `PREMIUM`; a reservation's `tow_check_result` is `PASS`, `FAIL`, or `NOT_REQUIRED`.

### 2.10. Natural Keys and Uniqueness

Several entities carry human-meaningful natural keys that must be globally unique across their collection: a dealer's `dealer_code` (for example UH-4821), a location's `location_code` (for example PHX-07), a unit's `unit_code`, and a customer's `email`. Two singleton-per-parent constraints also hold: at most one `RentalAgreement` may exist for a given `reservation_id`, and at most one `DamageProtectionPlan` may exist for a given `agreement_id`. A creation that collides on any of these keys is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Network: Locations, Dealers, and Fleet

A `NetworkAdmin` builds the physical network first. Each site is registered with a unique `location_code`, a `city`, a `geo_zone`, and a non-negative `storage_capacity` counting the self-storage units at that site; the zone value drives both the reassignment search radius and the storage capacity pool, and a new location opens in the `OPEN` state. Dealers are then attached to sites: a dealer record carries a unique `dealer_code`, a business `name`, the `location_id` of the site it operates, and optionally a `commission_rate_override` — a decimal between 0 and 1 that, when present, replaces the lane rate's commission for every settlement quarter; when null, the lane's own rate applies. A dealer is born `ACTIVE`, begins with an `allocated_unit_count` of zero, and starts with a `performance_score` of zero until the first quarterly review posts.

Fleet registration is per physical unit. Registering a unit takes a unique `unit_code`, an `equipment_type`, and the `dealer_id` of the dealer that will hold it; the unit is born `AVAILABLE`, its `current_dealer_id` is the registering dealer, its `current_location_id` mirrors that dealer's site, and the dealer's `allocated_unit_count` recomputes to count every unit whose `current_dealer_id` points at it. That count is a maintained derived field, not a stored counter the caller can write: it recomputes whenever a unit is registered, handed off at a return or reposition completion, or retired. Units never change hands except through returns, repositioning completions, allocation rounds, and retirement — there is no direct "transfer" operation.

A dealer may take one of its own units out of service and bring it back: the status-change operation accepts a `to_status` and an optional free-text `status_note` (customarily the reason recorded when a unit enters `MAINTENANCE`). It moves a unit `AVAILABLE → MAINTENANCE` when `to_status` is `MAINTENANCE`, and `MAINTENANCE → AVAILABLE` when `to_status` is `AVAILABLE` — no other target is reachable through this operation — and in both directions the acting `DealerAgent`'s own dealer must be the unit's current holding dealer.

Location closure is deliberately conservative. A `NetworkAdmin` may close a location only while no unit at that site is `AVAILABLE`, `HELD`, `OUT`, or `REPOSITIONING`, and while no reservation with that site as `origin_location_id` is `QUOTED`, `CONFIRMED`, or `REASSIGNED`; violating either condition leaves the location untouched. Reopening a `CLOSED` location requires nothing further. Dealer deactivation is likewise guarded and terminal: it proceeds only from `ACTIVE`, only while no reservation promises fulfilment from that dealer (none in `QUOTED`, `CONFIRMED`, or `REASSIGNED`), and only while the dealer holds no unit in `AVAILABLE`, `HELD`, or `OUT` — otherwise the attempt fails with `ERR_DEALER_HAS_ACTIVE_HOLDINGS`. A `DEACTIVATED` dealer has left the allocation pool permanently. Retirement is the fleet-side terminal act: retiring requires the unit to be `AVAILABLE`, and the current dealer's `allocated_unit_count` recomputes afterward.

### 3.2. Lane Rates and the Imbalance Signal

Pricing is owned by the `PricingManager` and expressed per lane: an origin location, a destination location, an equipment category, and a season. A rate row is drafted with `origin_location_id`, `dest_location_id`, `equipment_type`, `season`, a non-negative `base_rate_cents` per day, a non-negative `reposition_surcharge_cents` per day, and a `commission_rate` between 0 and 1 that becomes the default dealer commission for settled rentals on that lane and season. New rows are `DRAFT`. Activation moves a row `DRAFT → ACTIVE` and, in the same act, any other row with the identical lane key — same origin, destination, equipment type, and season — that was `ACTIVE` becomes `SUPERSEDED`; uniqueness of the active rate per lane key is enforced here and nowhere else. A rate may also be moved `ACTIVE → SUPERSEDED` manually. Only `ACTIVE` rows are ever consulted by quoting or by commission pinning; `DRAFT` and `SUPERSEDED` rows are invisible to both.

Each rate row also carries a computed `imbalance_factor`, the network's accumulation signal for that lane, starting at 1.0 when the row is created. The signal blends realized flows with pending demand. For the lane from origin O to destination D in equipment type T, take the count of one-way rental agreements whose reservation ran from O to D in type T and whose agreement is `RETURNED` or `SETTLED`, and subtract the symmetric count for the reverse lane from D to O — that is the net flow. Then take the count of reservations in `CONFIRMED` or `REASSIGNED` from O to D in type T for a one-way rental and subtract the symmetric reverse-lane count — that is the deficit. The imbalance factor is 1.0 plus one half of the sum of net flow and deficit, divided by the total fleet of type T (units in any status other than `RETIRED`), with the divisor floored at 1 so an empty fleet cannot divide by zero; the result is rounded half-up to 4 decimal places. The window is all time — there is no date filter, and tie-breaking does not arise because the inputs are pure counts. Only lanes that have an `ACTIVE` rate row are recomputed. The recomputation fires on three events: a reposition task completing, a reposition task being cancelled, and a one-way rental returning (the unit landing at a new location).

The factor has two readings. The forward-looking reading — including the deficit term, so unmet confirmed demand pushes the factor up — is the one the quoting engine consults when deciding whether the surcharge applies. The historical reading omits the deficit term and reflects only realized net flow; it is what the planning report returns as its `lanes` array, and whenever unmet demand exists the historical figure for a lane is smaller than the forward-looking one. The report is available to `NetworkAdmin` and `PricingManager` and may be filtered by `equipment_type`.

### 3.3. Customers, Vehicles, and the Reservation Funnel

A renter enters the system by registering a customer account with a unique `email`, a `full_name`, and the `vehicle_profile_id` of the tow vehicle they will present; the account's `driver_license_verified` flag starts false and can be flipped to true only by a `DealerAgent` performing license verification at the counter. The vehicle profile itself is registered first, by the customer, with a human `label` (for example "2019 F-150 SuperCrew 2WD"), the `make`, `model`, and `year` (1980 or later), the `curb_weight_lbs` (at least 1000), the rated `tow_capacity_lbs` (zero meaning the vehicle is not rated to tow at all), and the installed receiver `hitch_class` (`NONE` meaning no receiver).

A reservation begins life as a quote. The customer supplies `customer_id`, the `origin_dealer_id` of the dealer promising fulfilment, the `dest_location_id` where the equipment will be dropped off, the requested `equipment_type`, the `rental_kind` (`ROUND_TRIP` returns to the origin, `ONE_WAY` returns at the destination), and the planned `pickup_date` and `dropoff_date` as ISO 8601 instants. The drop-off must fall strictly after the pickup, and the pickup must not lie in the past relative to the logical clock — a violation is `ERR_INVALID_DATE_RANGE` (HTTP 400). From these inputs the system derives the rest: `origin_location_id` mirrors the origin dealer's site at creation; `season` is the season bucket of the pickup date; `rental_days` is the number of whole 24-hour days between pickup and drop-off rounded up, with a floor of one day. The reservation is born `QUOTED` and carries a computed `price_snapshot` whose components — `quoted_rate_cents_per_day`, `applied_imbalance_factor`, `commission_rate`, and `total_quoted_cents` — come from the quoting engine described in §3.5; the snapshot also receives a `tow_check_result` that begins as `NOT_REQUIRED` and stays that way unless a towed equipment type is confirmed. A `ReservationEvent` of type `CREATED` is appended at birth. Quoting requires an `ACTIVE` lane rate for the origin, destination, equipment type, and pickup season; without one the creation fails with `ERR_NO_ACTIVE_RATE`.

While a reservation is still `QUOTED`, the customer may amend the `pickup_date` or `dropoff_date`; doing so recomputes the season and the quoted snapshot and bumps the reservation's `version` by 1. This is the state-mutation that makes the confirm-time version check meaningful — a client holding the pre-amendment quote cannot confirm against it.

Confirmation is the moment the network's availability guarantee engages, and its checks run in a pinned order. First the state layer: the reservation must be `QUOTED`, and the request must carry `expected_reservation_version` matching the reservation's current `version` per §2.7 — a mismatch is `ERR_STALE_VERSION`. Then the domain checks, in this order. Towing compatibility: when the requested equipment is a towed type — `TRAILER_4X8`, `TRAILER_6X12`, or `TOW_DOLLY` — the customer's vehicle profile is screened as described in §3.4, and a failure is `ERR_TOW_INCOMPATIBLE`. License: the customer's `driver_license_verified` must be true, else `ERR_LICENSE_NOT_VERIFIED`. Dealer posture: the origin dealer must be `ACTIVE`, else `ERR_DEALER_SUSPENDED` — this gate is what stops a `QUOTED` reservation whose dealer was suspended after quoting, since the suspension sweep does not touch quotes. Rate presence: an `ACTIVE` lane rate must exist for the lane and season at the confirm instant, else `ERR_NO_ACTIVE_RATE`. Availability: an `AVAILABLE` unit of the requested type must exist at the origin dealer, free for the entire pickup-to-drop-off interval, else `ERR_NO_UNIT_AVAILABLE` (HTTP 409).

When all checks pass, confirmation freezes the quote: the pricing engine runs again against whatever lane rate is `ACTIVE` at the confirm instant, and the result — potentially different from the originally quoted total if the rate row changed between quote and confirm, which is intended — becomes the frozen `price_snapshot`, and the frozen value wins. The selected unit moves `AVAILABLE → HELD`, which pins it to this reservation without changing its holding dealer or the dealer's `allocated_unit_count`. A `ReservationEvent` of type `CONFIRMED` is appended, the reservation's `version` increments by 1, and the reservation stands `CONFIRMED`.

### 3.4. Towing Compatibility Screening

The towing screen is a three-gate threshold evaluation run at confirm time against the customer's single registered vehicle profile, and it applies only to the towed equipment types `TRAILER_4X8`, `TRAILER_6X12`, and `TOW_DOLLY` — for every other equipment type the `tow_check_result` is `NOT_REQUIRED` and no screening occurs. Each towed type has a fixed gross vehicle weight rating: 2500 pounds for the `TRAILER_4X8`, 4400 pounds for the `TRAILER_6X12`, and 3450 pounds for the `TOW_DOLLY`. All comparisons use exact integer pounds with no rounding.

The gates are evaluated in order, and the first failure determines the outcome. Gate one, hitch class: the vehicle's `hitch_class` must be among the accepted classes for the equipment — the `TRAILER_4X8` accepts `CLASS_I`, `CLASS_II`, `CLASS_III`, or `CLASS_IV`; the `TOW_DOLLY` accepts `CLASS_II`, `CLASS_III`, or `CLASS_IV`; the `TRAILER_6X12` accepts only `CLASS_III` or `CLASS_IV`. A vehicle with `NONE` therefore fails every towed type. Gate two, tow capacity: the vehicle's `tow_capacity_lbs` must be at least the equipment's gross vehicle weight rating multiplied by 0.8. Gate three, curb weight: the vehicle's `curb_weight_lbs` must be at least the equipment's gross vehicle weight rating multiplied by 0.8 — the curb-weight ratio passes at the boundary exactly, so a vehicle weighing precisely 0.8 times the rating passes this gate. Passing all three gates records `PASS`; failing any gate records `FAIL` and the confirm is rejected with `ERR_TOW_INCOMPATIBLE`.

### 3.5. Quoting and the Rated Price

The quoting engine produces the per-day rate and total that live in a reservation's `price_snapshot`, and it runs at three moments: at reservation creation (the quoted reading, stored but not frozen), at confirm (the frozen reading), and at reassignment when the origin location changes. The engine first locates the single `ACTIVE` lane rate for the origin location, destination location, equipment type, and the season of the pickup date — where the season is `PEAK` for pickup months June through August, `SHOULDER` for April, May, September, and October, and `OFF_PEAK` in every other month, judged by the calendar month of the pickup instant in UTC. The daily rate starts at the rate row's `base_rate_cents`. When the row's forward-looking `imbalance_factor` exceeds 1.0 — the threshold that signals destination accumulation — the row's `reposition_surcharge_cents` is added to the daily rate; a factor of exactly 1.0 does not trigger the surcharge. When the rental runs at least 7 days, the daily rate is then discounted by 10 percent and rounded half-up to the nearest integer cent — the day rate is rounded first, before any multiplication. The quoted total is the rounded daily rate multiplied by `rental_days`. Damage protection never appears in a quote: it is sold at pickup, so the protection component of a quote is always zero and the `total_quoted_cents` equals the day-rate subtotal. The `applied_imbalance_factor` and the lane's `commission_rate` are captured into the snapshot alongside the rate and total. The difference between the quoted and frozen readings is deliberate: the quote reflects the rate active at quote time, the frozen snapshot reflects the rate active at the confirm instant, and when the two rows differ the frozen value governs everything downstream, including settlement.

### 3.6. Reassignment: The Availability Guarantee's Second Half

A promise is only as good as the dealer behind it, so a confirmed reservation can be moved. A `NetworkAdmin` may reassign any reservation in `CONFIRMED` or `REASSIGNED` — reassigning a `REASSIGNED` reservation again is legal and simply appends another event — and the same machinery runs automatically when a dealer is suspended. The reassignment selector builds a candidate pool of dealers that are `ACTIVE`, operate in the same `geo_zone` as the reservation's origin location, are not the current origin dealer, and hold an `AVAILABLE` unit of the requested `equipment_type` that is free for the whole pickup-to-drop-off interval. Candidates are ranked by `performance_score` descending, then `allocated_unit_count` ascending, then `created_at` ascending as the final tie-break; entity ids are never used anywhere in the ranking. An explicit reassignment with an empty pool is rejected with `ERR_NO_REASSIGNMENT_CANDIDATE` (HTTP 409).

A successful reassignment is transactional in effect: any unit `HELD` for the reservation at the prior dealer is released back to `AVAILABLE` there, a unit at the selected new dealer moves `AVAILABLE → HELD`, the reservation's `origin_dealer_id` and `origin_location_id` are updated, and — when the origin location actually changed — the `price_snapshot` is recomputed against the new lane's active rate. The reservation's `version` increments, its state becomes `REASSIGNED`, and a `ReservationEvent` of type `REASSIGNED` is appended recording `from_dealer_id`, `to_dealer_id`, and a free-text `note` giving the reason. These events are the audit spine of the guarantee: they can be listed per reservation in `created_at` ascending order, listed globally filtered by `reservation_id`, `from_dealer_id`, or `to_dealer_id`, and listed per dealer — where the dealer view returns every event in which that dealer appears as either `from_dealer_id` or `to_dealer_id` and accepts a `direction` filter to narrow to one side.

Dealer suspension is the mass-application of this machinery. Suspending a dealer — allowed only from `ACTIVE` — flips the dealer to `SUSPENDED` and immediately sweeps every reservation whose `origin_dealer_id` is that dealer and whose status is `CONFIRMED` or `REASSIGNED`: each such reservation auto-reassigns per the selector, and if the selector's candidate pool is empty for a given reservation, that reservation moves to `EXPIRED` instead, appending the corresponding event. Reservations still `QUOTED` are deliberately not swept; they remain `QUOTED`, and their confirm is subsequently blocked at the dealer-posture gate with `ERR_DEALER_SUSPENDED`. While a dealer is `SUSPENDED`, no new assignments of any kind may land on it. Reactivation returns a `SUSPENDED` dealer to `ACTIVE` with no side effects — swept reservations are not restored.

### 3.7. Pickup, Protection Sales, and the Open Agreement

Pickup is the `DealerAgent`'s act of turning a promise into a contract: the agent presents a payload containing the `reservation_id`, the `equipment_unit_id` being handed over, and the `return_location_id` where the unit will come back — the destination for a one-way rental, the origin site for a round trip. The reservation must be `CONFIRMED` or `REASSIGNED`; the origin dealer must be `ACTIVE` and the presented unit must be exactly the unit `HELD` for this reservation, at that dealer; the pickup dealer's location must be `OPEN`, else `ERR_LOCATION_CLOSED`. Because at most one agreement may exist per reservation, a second pickup against the same reservation is `ERR_DUPLICATE_RESOURCE`. On success the agreement is born `ACTIVE` with `checkout_at` stamped from the logical clock, `checkout_dealer_id` set to the reservation's origin dealer, `late_fee_cents` and `damage_charge_cents` initialized to zero, and `returned_at`, `actual_days`, and `total_settled_cents` all null. The unit moves `HELD → OUT`, and the reservation auto-transitions to `FULFILLED` — terminal — with no further events required of it.

At the same counter visit the agent may sell a damage protection plan: one plan per agreement, created with the `agreement_id` and a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`, born `ACTIVE`. The premium is the tier's daily price — 1400 cents per day for `BASIC`, 2400 for `STANDARD`, 3900 for `PREMIUM` — multiplied by the reservation's frozen `rental_days`; when the rental runs at least 7 days, the whole premium (not the per-day amount) is discounted by 15 percent and rounded half-up to integer cents, and the result is stored as `premium_cents`. The tiers carry coverage caps that the claims workflow consults: 200000 cents for `BASIC`, 750000 for `STANDARD`, and 2500000 for `PREMIUM`. A plan may be cancelled while its agreement is still `ACTIVE` — cancellation moves the plan `ACTIVE → CANCELLED` and, because coverage is withdrawn, every claim on the same agreement still `FILED` is moved to `DENIED` in the same act. If the plan is never cancelled, it expires automatically when the agreement is returned, moving `ACTIVE → EXPIRED`.

### 3.8. Return, Damage Claims, and Settlement of the Agreement

Return lands the equipment at `return_location_id` and is the moment one-way accumulation physically happens. The agreement must be `ACTIVE` and the return location must be `OPEN`. On return, `actual_days` is computed as the number of whole 24-hour periods from `checkout_at` to the logical-clock instant stamped into `returned_at`, rounded up, floored at one day. The unit moves `OUT → AVAILABLE`, its `current_location_id` becomes the return location, and its `current_dealer_id` becomes the `ACTIVE` dealer operating at that location — if no active dealer exists there, the return cannot complete and fails with `ERR_NO_ACTIVE_DEALER_AT_LOCATION` (HTTP 409), because the unit would have nowhere to live. The destination dealer's `allocated_unit_count` recomputes. Any `ACTIVE` protection plan on the agreement moves to `EXPIRED`. The `late_fee_cents` figure is computed at this point from the settlement inputs (below). And when the underlying reservation was one-way, the lane imbalance recomputation fires for every `ACTIVE` lane rate touching the affected locations. The agreement is now `RETURNED`.

Damage claims may be filed against an agreement by a `DealerAgent`, supplying the `agreement_id` and a `claimed_amount_cents` strictly greater than zero — a non-positive amount is `ERR_INVALID_CLAIM_AMOUNT` (HTTP 422). At filing, the acting operator's `X-User-ID` is recorded as `filer_user_id`, permanently, for the segregation-of-duties check. A claim is born `FILED`. Adjudication requires a different pair of hands: approving or denying demands that the acting `X-User-ID` differ from `filer_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and approval additionally requires the agreement to be `ACTIVE` or `RETURNED` — never `SETTLED`. Approval sets `approved_amount_cents` to the lesser of the claimed amount and the coverage cap of the agreement's active plan tier — with a cap of zero when the agreement has no active plan at all — then runs the agreement's damage reconciliation: `damage_charge_cents` becomes the sum of `approved_amount_cents` over every claim on the agreement in `APPROVED` or `PAID` status, and the agreement's `version` increments by 1. Either decision may carry an optional free-text `resolution_note`. A denied claim is not necessarily dead: while its agreement remains unsettled, reopening moves it `DENIED → FILED`, and the appeal loop of filing, adjudication, and reopening may repeat until the agreement settles, which seals the loop. Payment is the claim's final act and is deliberately sequenced after settlement: only an `APPROVED` claim whose agreement is `SETTLED` may be paid, moving it `APPROVED → PAID`, so approved amounts are always frozen into the agreement's total before money moves.

Settlement closes the financial life of the agreement, and it is OCC-guarded per §2.7: the request carries `expected_agreement_version`, and a stale version is `ERR_STALE_VERSION`. Two further gates apply in order: the agreement must be `RETURNED`, and no claim on it may still be `FILED` — an open claim blocks settlement with `ERR_OPEN_CLAIMS` (HTTP 409), while `DENIED` or `PAID` claims do not block. The settlement computation runs in a pinned evaluation order. First, `actual_days` is already known from the return. Second, billable days are the greater of `actual_days` and the reservation's `rental_days` — an early return never refunds. Third, the base charge is the frozen snapshot's `quoted_rate_cents_per_day` multiplied by billable days. Fourth, the late fee: late days are `actual_days` minus the reservation's `rental_days`, floored at zero; the per-day late rate is the frozen daily rate multiplied by 1.5 and rounded half-up to integer cents, and that rounded rate is then multiplied by the late-day count — multiplying the count first and the rate second would yield different cents and is not the rule. Fifth, damage reconciliation runs as described above. Sixth, `total_settled_cents` is the base charge plus the late fee plus the reconciled damage charges, and it is frozen onto the agreement, whose `version` increments as it moves to `SETTLED` — terminal. While an agreement is still `ACTIVE`, a provisional estimate of this same computation is available for counter conversations: it projects `actual_days` as the whole 24-hour periods from `checkout_at` to the current logical clock, rounded up and floored at one, excludes damage claims entirely since none have been reconciled, and persists nothing — the estimate and the final settled figure differ whenever the return happens after the estimate was taken or any claim is approved in between.

### 3.9. Repositioning the Fleet

When accumulation outpaces organic demand, a `NetworkAdmin` opens a reposition task by naming the `from_location_id` of the surplus site, the `to_location_id` of the deficit site, and the `equipment_type` to move. The system selects the unit itself: among `AVAILABLE` units of that type physically at the from-location, the one with the earliest `created_at` is chosen, and it moves `AVAILABLE → REPOSITIONING`, with the new task's `equipment_unit_id` pointing at it. The task is born `OPEN` with `scheduled_after` defaulting to the logical clock at creation and with `estimated_reposition_cost_cents` set from the distance band between the two sites' zones. The band table is fixed: identical zones are SHORT at 9000 cents; the pairs NORTH–SOUTH and EAST–WEST, in either direction, are LONG at 52000 cents; every other distinct zone pair is MEDIUM at 24000 cents. The provisional estimate is the band cost alone — no driver fee, no idle penalty — so it never exceeds the executed cost of the same task when the idle penalty applies.

Assignment is an admin act that names the `assigned_driver_id` and requires the task to be `OPEN` with its unit still `REPOSITIONING`; the task moves `OPEN → ASSIGNED`. Completion belongs to the driver alone: the acting `X-User-ID` must equal the task's `assigned_driver_id`, else `ERR_DRIVER_MISMATCH` (HTTP 403). On completion the unit moves `REPOSITIONING → AVAILABLE`, its `current_location_id` becomes the task's destination, and its `current_dealer_id` becomes the `ACTIVE` dealer at that location — with `ERR_NO_ACTIVE_DEALER_AT_LOCATION` if there is none. The executed cost, recorded as `executed_reposition_cost_cents`, is the band cost plus a flat driver fee of 6000 cents, plus an idle penalty of 15000 cents when the unit sat in `REPOSITIONING` for more than 48 hours on the logical clock; exactly 48 hours incurs no penalty. Finally, lane imbalance recomputes for every `ACTIVE` lane rate whose origin or destination is either of the task's two locations — a recomputation that may flip a lane's factor across the 1.0 threshold and thereby change what the quoting engine charges on that lane from the next quote onward. Cancellation, allowed only while `OPEN`, returns the unit to `AVAILABLE` at the from-location with no location change and likewise triggers the imbalance recomputation.

### 3.10. Cross-Sell: Supplies, Storage, and the Zone Pool

A `DealerAgent` ringing up a rental can attach a cross-sell order — moving supplies with optional months of self-storage — supplying the selling `dealer_id`, optionally the `agreement_id` of the rental being cross-sold, the `line_items` as an array of `sku` and `qty` pairs, and `storage_months` (defaulting to zero, never negative). The supply catalogue is fixed: `BOX_SMALL` at 125 cents, `BOX_LARGE` at 245, `TAPE` at 399, `BLANKET` at 899, and `LOCK` at 1299. The `supplies_subtotal_cents` extends each line at its catalogue price times quantity, rounding each line half-up to integer cents before summing. The `storage_charge_cents` is the number of months multiplied by the monthly storage rate of the dealer's zone: 8900 cents in `NORTH`, 7900 in `SOUTH`, 9500 in `EAST`, 9900 in `WEST`, and 6900 in `CENTRAL`. When the order buys both supplies and storage — `storage_months` above zero and a positive supplies subtotal — a bundle discount of 10 percent of the supplies subtotal, rounded half-up to integer cents, is recorded as `bundle_discount_cents`; otherwise the discount is zero. The order's `total_cents` is the supplies subtotal plus the storage charge minus the bundle discount.

Storage capacity is pooled at the zone level, not per site. Before an order is accepted, the system sums `storage_months` over every cross-sell order at locations sharing the dealer's `geo_zone`, sums `storage_capacity` over the `OPEN` locations in that zone, and rejects the order with `ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 409) when the occupied months plus the new months would exceed the pooled capacity — hitting the cap exactly is allowed, only exceeding it rejects.

### 3.11. Performance Reviews, Allocation Rounds, and Quarterly Settlement

Dealer performance feeds two machines. A `NetworkAdmin` posts quarterly performance reviews in bulk — a `period` label such as 2026-Q3 plus the `scores` — and each entry writes the dealer's `performance_score`, the figure used both as the reassignment ranking key and as an input to allocation; the response reports the `updated_dealer_ids` actually touched. An allocation round, also admin-run, takes a body of `unit_codes` to distribute and scores every `ACTIVE` dealer that filed a request for the round: the score is one half of the dealer's `performance_score`, plus three tenths of the dealer's utilization percentage — one hundred times the count of the dealer's units in `OUT` or `HELD`, divided by the dealer's `allocated_unit_count` with the divisor floored at one — plus two tenths of a zone-deficit bonus worth 10 when the dealer's zone shows negative net flow on the imbalance signal and 0 otherwise, with the score computed to 2 decimal places rounded half-up. Units are dealt in score-descending order, ties broken by `created_at` ascending and never by id, until the requested units of each type are exhausted; allocated units have their `current_dealer_id` reassigned, each affected dealer's `allocated_unit_count` recomputes, and the round reports the `allocated` array alongside any `skipped_unit_codes` it could not place.

The quarterly `DealerSettlement` is where commission becomes money. A `FinanceReviewer` opens one in `DRAFT` with the `dealer_id` and a `period` quarter label; the draft computation scopes every agreement whose `checkout_dealer_id` is this dealer, whose status is `SETTLED`, and whose `returned_at` falls inside the quarter's closed-open window — inclusive of the first instant, exclusive of the last. `gross_rental_cents` is the sum of `total_settled_cents` over that scope. The commission pins a rate per agreement: when the dealer's `commission_rate_override` is set, that flat rate governs every agreement in scope regardless of lane; when it is null, each agreement uses the `commission_rate` of the lane rate that was `ACTIVE` at that agreement's `checkout_at` for its lane and season, so two agreements with equal totals on different lanes contribute different commissions. Each agreement's commission is its settled total multiplied by its pinned rate, rounded half-up to integer cents per agreement, and the rounded per-agreement values are then summed into `commission_cents` — sum-then-round is forbidden. Cross-sell commission works the same way at the order level: every cross-sell order of the dealer in the quarter, regardless of whether it links to an agreement, contributes its `total_cents` multiplied by 5 percent, rounded half-up per order, then summed into `cross_sell_commission_cents`. Underperformance has a price: when the dealer's `performance_score` is below the floor of 60, a clawback of 10 percent of the sum of the two commission figures, rounded half-up, is charged as `clawback_cents`; at exactly 60 or above the clawback is zero. `net_cents` is the two commissions minus the clawback.

Settlement governance mirrors the claims workflow's segregation of duties. Approval — by a `FinanceReviewer` — requires the settlement to be `DRAFT` or `DISPUTED` and every agreement in scope to be `SETTLED`; approval recomputes every figure as of that moment and freezes them, moving the settlement to `APPROVED`. A dealer who disagrees with a draft disputes it: the acting `DealerAgent`'s own dealer must be the settlement's `dealer_id`, and the settlement moves `DRAFT → DISPUTED`, from which a fresh approval (the cycle's back-edge) recomputes and freezes again. Payment requires `APPROVED` and, per §2.1, a payer whose `X-User-ID` differs from the approver's — the same person approving and paying is `ERR_SEGREGATION_OF_DUTIES`. Payment moves the settlement to `PAID`, terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/rental-network` (plus the single clock capability at the root). Creating a new resource returns 201; every other successful operation — modifications, state transitions, reads, previews, reports — returns 200. Requests failing validation return the 4xx status paired with the error identifier in §5, in the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /rental-network/locations | Create a location | NetworkAdmin |
| GET | /rental-network/locations | List locations; optional filters | NetworkAdmin, PricingManager, DealerAgent, FinanceReviewer |
| GET | /rental-network/locations/{id} | Fetch one location | NetworkAdmin, PricingManager, DealerAgent, FinanceReviewer |
| POST | /rental-network/locations/{id}/close | Close a location (blocked while fleet or live reservations attached) | NetworkAdmin |
| POST | /rental-network/locations/{id}/reopen | Reopen a closed location | NetworkAdmin |
| POST | /rental-network/dealers | Create a dealer | NetworkAdmin |
| GET | /rental-network/dealers | List dealers; optional filters | NetworkAdmin, PricingManager, FinanceReviewer |
| GET | /rental-network/dealers/{id}/reservation-events | Audit events where this dealer appears as from- or to-dealer | NetworkAdmin, FinanceReviewer |
| GET | /rental-network/dealers/{id} | Fetch one dealer | NetworkAdmin, DealerAgent, FinanceReviewer |
| POST | /rental-network/dealers/{id}/suspend | Suspend dealer; mass-reassigns its live reservations | NetworkAdmin |
| POST | /rental-network/dealers/{id}/reactivate | Reactivate a suspended dealer | NetworkAdmin |
| POST | /rental-network/dealers/{id}/deactivate | Deactivate a dealer (terminal) | NetworkAdmin |
| POST | /rental-network/dealers/allocate | Run an allocation round over ACTIVE dealers | NetworkAdmin |
| POST | /rental-network/performance-reviews | Post quarterly performance scores (bulk) | NetworkAdmin |
| POST | /rental-network/equipment-units | Register a unit into the fleet at a dealer | NetworkAdmin |
| GET | /rental-network/equipment-units | List units; optional filters | NetworkAdmin, DealerAgent, PricingManager |
| GET | /rental-network/equipment-units/{id} | Fetch one unit | NetworkAdmin, DealerAgent |
| POST | /rental-network/equipment-units/{id}/status | Move a unit into or out of MAINTENANCE | DealerAgent |
| POST | /rental-network/equipment-units/{id}/retire | Retire a unit (terminal) | NetworkAdmin |
| POST | /rental-network/vehicle-profiles | Register a customer tow vehicle profile | Customer |
| GET | /rental-network/vehicle-profiles/{id} | Fetch one vehicle profile | Customer, DealerAgent, NetworkAdmin |
| POST | /rental-network/customers | Register a customer | Customer |
| GET | /rental-network/customers | List customers; optional vehicle-profile filter | NetworkAdmin, DealerAgent |
| GET | /rental-network/customers/{id} | Fetch one customer | Customer, DealerAgent, NetworkAdmin |
| POST | /rental-network/customers/{id}/verify-license | Mark the customer's driver license verified | DealerAgent |
| POST | /rental-network/lane-rates | Create a lane rate (DRAFT) | PricingManager |
| GET | /rental-network/lane-rates | List lane rates; optional filters | PricingManager, NetworkAdmin, FinanceReviewer, DealerAgent |
| GET | /rental-network/lane-rates/{id} | Fetch one lane rate | PricingManager, NetworkAdmin, DealerAgent |
| POST | /rental-network/lane-rates/{id}/activate | Activate a DRAFT rate; supersedes the conflicting ACTIVE row | PricingManager |
| POST | /rental-network/lane-rates/{id}/supersede | Manually supersede an ACTIVE rate | PricingManager |
| POST | /rental-network/reservations | Create a QUOTED reservation with a quoted price snapshot | Customer |
| GET | /rental-network/reservations | List reservations; optional filters | Customer, DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/reservations/{id} | Fetch one reservation | Customer, DealerAgent, NetworkAdmin, FinanceReviewer |
| PATCH | /rental-network/reservations/{id} | Change pickup/dropoff dates on a QUOTED reservation | Customer |
| GET | /rental-network/reservation-events | Filtered list of reservation audit events | NetworkAdmin, FinanceReviewer |
| GET | /rental-network/reservations/{id}/events | List the reservation's audit events in created_at ascending order | Customer, DealerAgent, NetworkAdmin, FinanceReviewer |
| POST | /rental-network/reservations/{id}/confirm | Confirm a quote: tow check, availability, price freeze, unit hold | Customer |
| POST | /rental-network/reservations/{id}/reassign | Move the reservation to another dealer per the selector | NetworkAdmin |
| POST | /rental-network/reservations/{id}/cancel | Customer cancels a live reservation | Customer |
| POST | /rental-network/reservations/{id}/expire | Expire a QUOTED reservation | NetworkAdmin |
| POST | /rental-network/reservations/{id}/mark-no-show | Mark a confirmed reservation as no-show after pickup_date | NetworkAdmin |
| POST | /rental-network/rental-agreements | Pickup: create the rental agreement against a confirmed reservation | DealerAgent |
| GET | /rental-network/rental-agreements | List agreements; optional filters | DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/rental-agreements/{id} | Fetch one agreement | DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/rental-agreements/{id}/settlement-preview | Provisional settlement estimate for an ACTIVE agreement | DealerAgent, NetworkAdmin |
| POST | /rental-network/rental-agreements/{id}/return | Return the equipment at the return location | DealerAgent |
| POST | /rental-network/rental-agreements/{id}/settle | Settle a returned agreement; OCC-guarded | DealerAgent |
| POST | /rental-network/damage-protection-plans | Sell a damage protection plan at pickup | DealerAgent |
| GET | /rental-network/damage-protection-plans | List plans; optional agreement filter | DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/damage-protection-plans/{id} | Fetch one plan | DealerAgent, NetworkAdmin, FinanceReviewer |
| POST | /rental-network/damage-protection-plans/{id}/cancel | Cancel a plan before return; open claims auto-deny | DealerAgent |
| POST | /rental-network/damage-claims | File a damage claim against an agreement | DealerAgent |
| GET | /rental-network/damage-claims | List claims; optional filters | DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/damage-claims/{id} | Fetch one claim | DealerAgent, NetworkAdmin, FinanceReviewer |
| POST | /rental-network/damage-claims/{id}/approve | Approve a claim (capped by plan coverage) | DealerAgent |
| POST | /rental-network/damage-claims/{id}/deny | Deny a claim | DealerAgent |
| POST | /rental-network/damage-claims/{id}/reopen | Reopen a denied claim while the agreement is unsettled | DealerAgent |
| POST | /rental-network/damage-claims/{id}/pay | Pay an approved claim after settlement | DealerAgent |
| POST | /rental-network/reposition-tasks | Create a repositioning task; selector picks the unit | NetworkAdmin |
| GET | /rental-network/reposition-tasks | List tasks; optional filters | NetworkAdmin, RepositionDriver, FinanceReviewer |
| GET | /rental-network/reposition-tasks/{id} | Fetch one task | NetworkAdmin, RepositionDriver |
| GET | /rental-network/reposition-tasks/imbalance-report | Historical imbalance factors per ACTIVE lane | NetworkAdmin, PricingManager |
| POST | /rental-network/reposition-tasks/{id}/assign | Assign a driver to an OPEN task | NetworkAdmin |
| POST | /rental-network/reposition-tasks/{id}/complete | Driver completes the move; unit lands at destination | RepositionDriver |
| POST | /rental-network/reposition-tasks/{id}/cancel | Cancel an OPEN task; unit returns to AVAILABLE in place | NetworkAdmin |
| POST | /rental-network/cross-sell-orders | Create a cross-sell order (supplies plus optional storage) | DealerAgent |
| GET | /rental-network/cross-sell-orders | List cross-sell orders; optional filters | DealerAgent, NetworkAdmin, FinanceReviewer |
| GET | /rental-network/cross-sell-orders/{id} | Fetch one cross-sell order | DealerAgent, NetworkAdmin, FinanceReviewer |
| POST | /rental-network/dealer-settlements | Create a DRAFT quarterly settlement for a dealer | FinanceReviewer |
| GET | /rental-network/dealer-settlements | List settlements; optional filters | FinanceReviewer, NetworkAdmin, DealerAgent |
| GET | /rental-network/dealer-settlements/{id} | Fetch one settlement | FinanceReviewer, NetworkAdmin, DealerAgent |
| POST | /rental-network/dealer-settlements/{id}/approve | Approve a DRAFT or DISPUTED settlement; recompute and freeze | FinanceReviewer |
| POST | /rental-network/dealer-settlements/{id}/dispute | Dealer disputes a DRAFT settlement | DealerAgent |
| POST | /rental-network/dealer-settlements/{id}/pay | Pay an APPROVED settlement; payer must differ from approver | FinanceReviewer |
| POST | /_clock/set_current_utc | Test-driving endpoint: set the logical clock | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_TOW_INCOMPATIBLE | 422 |
| ERR_LICENSE_NOT_VERIFIED | 422 |
| ERR_DEALER_SUSPENDED | 409 |
| ERR_LOCATION_CLOSED | 409 |
| ERR_INVALID_DATE_RANGE | 400 |
| ERR_NO_UNIT_AVAILABLE | 409 |
| ERR_NO_ACTIVE_RATE | 422 |
| ERR_NO_REASSIGNMENT_CANDIDATE | 409 |
| ERR_OPEN_CLAIMS | 409 |
| ERR_STORAGE_CAPACITY_EXCEEDED | 409 |
| ERR_DRIVER_MISMATCH | 403 |
| ERR_INVALID_CLAIM_AMOUNT | 422 |
| ERR_DEALER_HAS_ACTIVE_HOLDINGS | 409 |
| ERR_NO_ACTIVE_DEALER_AT_LOCATION | 409 |
