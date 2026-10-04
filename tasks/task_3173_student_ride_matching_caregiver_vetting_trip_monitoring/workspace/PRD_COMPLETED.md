# Student Ride Matching API — Product Requirements Document

## 1. Introduction

Districts and placing agencies need a dependable way to move students — many of them in foster
care, experiencing homelessness under McKinney-Vento, or receiving special-education services —
between home and school every day of the school year. Ordinary rideshare supply does not meet that
need: the drivers who carry these students must have demonstrable caregiving experience, must clear
fingerprint-level background screening and periodic vehicle inspection beyond what a standard
rideshare platform requires, and must be trusted to hand a child over to the correct adult at the
right curb. This document specifies the API that a district contracts with in order to request,
schedule, dispatch, monitor and bill that service.

The product has to hold several concerns together at once. Intake arrives as ride requests that a
district submits and later approves; approved requests either produce one dated trip or expand into
a recurring school-year series that must respect the district's no-school calendar and the
academic term window. Once a trip exists it is offered to a vetted driver, claimed, driven through a
sequence of monitored handoffs, and finally priced and rolled into a periodic statement computed
against the district's contract rates. Throughout, a student's safety posture and the driver's
qualification posture are live constraints: a lapsed clearance, a failed inspection, an
unverified handoff, or a reported absence can each cascade across trips, drivers and districts
without anyone asking for the cascade explicitly.

Because the participants are children and the payers are public agencies, the API is written as a
strict contract. Every state a resource can occupy is enumerated, every automatic reaction to a
failure is pinned, and the arithmetic that decides what a district is owed is fixed to the cent.
Sections 2 and 3 describe those system-wide principles and workflows; Section 4 lists the
operations and the roles permitted to call them; Section 5 catalogues the machine-readable error
identifiers referenced throughout.

## 2. Global Specifications & System-Wide Principles

This section establishes the rules that hold across the whole API: who may act, how responses are
shaped, how collections are paged, and the invariant principles — vetting integrity, safety posture,
window geometry, monetary precision, concurrency and time — that every workflow in Section 3
depends on.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, which identifies the acting party, and
`X-User-Role`, which names the capacity in which that party acts. Both headers are mandatory. A
request that omits either header, or that names a role the platform does not recognise, is rejected
with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but is not permitted to
perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403). The only exception to
both rules is the district self-registration operation, which is deliberately reachable without
credentials because it is how a district first comes into existence.

The platform recognises five roles, spelled exactly as follows:

- `Anonymous`
- `DistrictAdmin`
- `Driver`
- `SupportCenterAgent`
- `PlatformAdmin`

The binding between the two headers and resource ownership differs by role. When `X-User-Role` is
`Driver`, `X-User-ID` is the `id` of the acting `Driver` entity; ownership checks on any resource
that references a `Driver` compare the resource's foreign-key field to `X-User-ID`, and every
driver-scoped trip action requires `X-User-ID` to equal the trip's assigned driver. When
`X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted
entity; the anonymous role exists solely so that district self-registration is reachable and holds
no other permission. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is an opaque operator
identifier not tied to any persisted entity: the server records the acting operator where a
workflow stamps it but does not compare it to any entity's `id`. The same is true for
`SupportCenterAgent`, whose `X-User-ID` is an opaque safety-desk identifier, and for
`PlatformAdmin`, whose `X-User-ID` is an opaque platform-operator identifier. In short, only the
`Driver` role is entity-backed; the other four are opaque.

The `PlatformAdmin` role is a superset: every operation available to `DistrictAdmin` or
`SupportCenterAgent` is also available to `PlatformAdmin`, alongside a small set of operations
reserved to it alone — releasing a locked trip, reopening an adjudicated incident, setting the
logical clock, running a monitoring sweep, and emitting a system event. `Driver` is the narrowest
role: it may act only on trips assigned to it and reads a student's contact detail only in masked
form. Authorisation is evaluated before any business rule: a caller who is not permitted to perform
an operation never learns whether the target resource would have satisfied that operation's
preconditions.

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
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints. A list response that is not driven by the paging query parameters of §2.3 still reports all four: it reports `offset` as `0` and `total_count` as the number of items in the whole set, and it reports `limit` as the number of items the whole set holds, or as the default of ten when the set is empty.
- A successful response whose `data` is a collection is `response_type` `"array"`; a single resource or a computed aggregate object is `"object"`.

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

List operations are paged through two query parameters. `limit` caps how many items a single
response may carry; it defaults to 10, must be at least 1, and must not exceed 100. `offset` states
how many leading items to skip and defaults to 0. Unless a workflow explicitly says otherwise, list
responses are ordered by `created_at` ascending, so the oldest record appears first. A caller that
does not name a `limit` or an `offset` receives the first page under those defaults rather than the
whole collection, except for the three list operations named below that are not paged at all. `limit` and `offset` are read as
ordinary integers: a value that cannot be parsed as one falls back to the parameter's default, a
`limit` below the minimum is raised to it and one above the maximum is lowered to it, and a negative
`offset` is raised to zero. Paged and non-paged list responses alike report `limit`, `offset`,
`total_count` and `has_more` inside the
`meta` object of the envelope described in §2.2.

Three list operations — the driver-availability block's returned ride-request set (§3.6), the
driver-supply run's returned trip set (§3.6) and the geofence-check recording's returned checks
(§3.9) — are not driven by the paging parameters at all: they ignore any `limit` and `offset` a
caller supplies and report the whole set they produced, under the envelope described in §2.2.
Operations that return a computed object — the supply plan and the billing statement — are not lists
and carry no pagination fields.

### 2.4. Driver Qualification Integrity

Qualification is the load-bearing invariant of this platform: a driver who is not fully vetted must
never appear as supply, and a driver whose vetting lapses must stop appearing even though nothing
about the driver record was edited. Two derived values carry that invariant, and both are recomputed
whenever the underlying clearance or inspection rows change.

The first is the driver's approved seat count, `approved_seat_count`. It gates every dispatch
decision and is also a display value on the driver record. The count collapses to zero unless the
driver is simultaneously in a qualifying lifecycle status and holding complete, unexpired paperwork.
Specifically, it is zero when any one of the following holds: the driver's `status` is not one of
`INSPECTION`, `ACTIVE` or `SUSPENDED`; the driver's declared `caregiver_experience_months` is below
the minimum caregiving-experience requirement of twelve months; the number of the driver's
background checks whose `result` is `CLEARED` is smaller than the number of that driver's background
checks whose `result` is not `FAILED`; any background check has an `expires_on` on or before the
logical clock date; any vehicle inspection has a `result` of `FAILED`; no vehicle inspection has a
`result` of `PASSED`; any vehicle inspection has an `expires_on` on or before the logical clock
date; or the largest `seat_count` across the driver's `PASSED` inspections is smaller than the
number of that driver's non-terminal trips. When none of those conditions holds, the approved seat
count is the smaller of the driver's declared `seat_capacity` and that same largest `seat_count`
across the `PASSED` inspections, and it is never reported above the platform ceiling of ten seats.
The count is a whole number and is never rounded. Note the asymmetry between the two guard families:
background-check expiry removes a seat and clearing a fresh check restores exactly one, so
approvals added and removed in this dimension cancel out, whereas a single `FAILED` inspection row
zeroes the count outright — the action that restores it is a later attestation of a fresh pending
inspection, never the un-failing of the old row. Because the trip-load veto reads the driver's
current non-terminal trip count, the value behaves partly like a running remaining-capacity counter,
truncated by the declared capacity of the vehicle class.

Two documented alternative readings of this rule exist and must not be conflated with it. Under the
declared-class-cap reading, the result is capped by the seat ceiling of the driver's declared
`vehicle_class` — four for `SEDAN`, six for `SUV`, eight for `WHEELCHAIR_VAN` — and the declared
`seat_capacity` is ignored entirely, so a driver declaring nine seats in an `SUV` reports nine under
the base rule and six under this reading. Under the on-road-only reading, the trip-load veto is
omitted, so a driver whose approved seats are already fully spoken for still reports a positive
count; that reading is used for onboarding display only and never for dispatch eligibility.

The second derived value is the driver's compliance expiry, `compliance_expires_at`: the instant
after which the driver's coverage lapses. It is null whenever the driver's `status` is `PENDING` or
`INACTIVE`, or whenever any background check for that driver has a `result` other than `CLEARED`.
Otherwise it is the earlier of two instants — the earliest `expires_on` among the driver's `CLEARED`
fingerprint-type background checks, and the latest `expires_on` among the driver's `PASSED` vehicle
inspections. When the driver holds no cleared check of a fingerprint type, the earliest-of comparison
falls back to the driver's cleared checks as a whole rather than producing a null, so a driver whose
only clearance is of another type still carries a coverage instant. When the driver holds no `PASSED`
inspection at all, the field is null — the comparison has only one operand and the driver has no
coverage to report. The instant is rendered as a bare `YYYY-MM-DD` date string, not as a timestamp,
because the comparison it expresses is day-granular. The asymmetry is deliberate: fingerprint
clearances fold into the earliest-of
comparison, but the inspection contributes its most recent passing date, so re-inspecting a vehicle
extends coverage instead of pinning the driver to the oldest pass. Expiry comparisons are day
granular and inclusive at the boundary date, while comparison against the logical clock instant is
exclusive. A background-check-only reading of the same field reports the earliest `expires_on` across
all `CLEARED` checks regardless of type and ignores inspections altogether, so a driver whose
fingerprint expires in March 2027 but whose only passing inspection lapsed in October 2026 reports
March 2027 under that reading and October 2026 under the base rule. A driver declared in `PENDING`
and a driver declared in `INACTIVE` both report no expiry at all.

### 2.5. Safety Posture Governance

Every trip carries a second, independent state dimension called the safety posture, `safety_state`,
whose values are `NORMAL`, `DISCREPANCY` and `LOCKED`. The trip's movement state, `trip_state`,
records where the vehicle is in its journey; the safety posture records whether the platform is
still willing to let the journey continue. The posture gates the movement: while a trip's
`safety_state` is `DISCREPANCY` or `LOCKED`, every attempt to advance `trip_state` out of
`AWAITING_STUDENT`, `STUDENT_ONBOARD` or `IN_TRANSIT` is refused with `ERR_TRIP_DISCREPANCY_LOCK`
(HTTP 409). Moving out of a clean posture is automatic and never client-requested: a trip drops into
`DISCREPANCY` when its `exception_code` is set to `UNAUTHORIZED_DROPOFF`, when a reported absence
grades `MEDIUM`, or when a trip alert of `MEDIUM` severity is created against it; it drops into
`LOCKED` when a reported absence grades `HIGH`, when a trip alert of `HIGH` severity is created
against it, or when an active driver-suspension cascade cancels the trip.

Recovery is deliberately asymmetric between the two degraded postures. A `SupportCenterAgent` may
clear a discrepancy — returning the trip from `DISCREPANCY` to `NORMAL` — but only once the trip has
reached `COMPLETED`; the same action against a locked trip moves it only as far as `DISCREPANCY`.
A trip in `LOCKED` can reach `NORMAL` only when a `PlatformAdmin` releases the lock, and only when
every alert raised against that trip has been resolved; otherwise the release is refused with
`ERR_OPEN_ALERTS` (HTTP 409). The release carries a trip the discrepancy hop left in `DISCREPANCY`
on to `NORMAL` under the same open-alert bar, so the two-hop reverse loop completes; a trip whose
posture is already `NORMAL` is refused with `ERR_INVALID_STATE` (HTTP 409). Locked trips are also
structurally unforgiving: a resource that has
already reached a terminal state for the dimension in question reports `ERR_ALREADY_TERMINAL` (HTTP
409) rather than the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409), so a probe that
targets an already-terminal resource can be distinguished from one that merely approached the wrong
state. A resource enters a posture the moment the transition that implies it is committed, so a trip
reported absent at a `MEDIUM` or `HIGH` grade, a trip whose dropoff names an unauthorised party, a
trip carrying a `MEDIUM` or `HIGH` alert, and a trip cancelled by a suspension cascade all read their
new posture from the same response that produced it, without a separate write.

### 2.6. Trip Window Geometry and Booking Collisions

Trips and ride requests are defined by a pickup window that opens at `window_start_at` and closes at
`window_end_at`. Whether two windows collide depends on whose schedule they are being tested
against, because the two resources obey opposite adjacency rules and neither rule is derived from
the other.

Against a driver resource, windows are half-open: a candidate window occupies from its open instant
up to but not including its close instant, so a window that begins exactly at another window's close
is accepted and a gap of zero minutes is permitted. An availability block or a generated series
window that overlaps an interval already occupied by that driver under these semantics is refused
with `ERR_DRIVER_WINDOW_OVERLAP` (HTTP 409). Series-interval checking uses no additional buffer, so
the boundary is evaluated at second precision.

Against a rider resource, windows are closed on both ends: a trip window that merely touches an
existing non-terminal window for the same student is a collision, because a student cannot leave one
vehicle at the instant they are due in another. Such a booking is refused with
`ERR_RIDER_WINDOW_OVERLAP` (HTTP 409). Availability blocking applies an additional twenty-minute
buffer when a driver's route segment is tested; the platform applies no such buffer, so the
availability block's overlap test and the series-to-series comparison alike evaluate the boundary at
second precision and a driver's availability block that begins exactly at another of that driver's
window closes is accepted.
Conflating the two geometries either turns an allowed hand-off into a rejection or lets a genuine
student double-booking pass silently, so the two checks are implemented separately even though they
compare the same pair of instants.

### 2.7. Common Resource Properties

Every addressable resource in this API — districts, riders, drivers, background checks, vehicle
inspections, contracts, ride requests, trips, handoff verifications, safety incidents, trip alerts,
geofences, geofence checks and billing statements — shares a common set of system-managed fields.

- `id` (string): the resource's unique identifier, minted by the server as a bare UUID with no type
  prefix and no namespace decoration.
- `created_at` (string): an ISO 8601 UTC timestamp recording when the resource was created, rendered
  with three fractional digits (for example `2025-05-24T10:30:00.123Z`).
- `updated_at` (string): an ISO 8601 UTC timestamp recording when the resource was last modified,
  updated on every mutation of the resource's properties, including mutations the server performs
  automatically. A mutation that drives a state transition advances the resource's `version` without
  re-stamping `updated_at`; the stamp belongs to property mutations alone.
- `version` (integer): a monotonically increasing counter that is incremented on every mutation of
  the resource and is used as the basis for optimistic concurrency control. It is rendered as an
  integer, never as a float or a JSON number carrying a fractional part.

No entity in this API opts out of the common field set, so every resource carries all four fields.
Identifier values are opaque and UUID-shaped; they are never used to decide the outcome of a
business rule, an ordering, a tie-break or a cascade. Where a deterministic fallback is required
between otherwise equal candidates, the platform uses registration or creation time, never the
identifier.

### 2.8. Monetary Precision and Rate Provenance

All money in this API is expressed in integer cents and named with a `_cents` suffix. Rates carried
on a district or a contract, statement totals, credit pools, outstanding balances and the per-trip
charges that feed them are all integers. Where a calculation produces a fractional intermediate
value it is rounded half up to the cent — a value ending in exactly half a cent rounds to the next
higher cent — and the rounding is applied at the moment the scaffolded rule names, not carried as a
running fractional total. Percentage-style factors, such as a credit-draw cap or a posture discount,
are applied to already-rounded cent amounts and the product is itself rounded half up.

Price provenance is also part of the contract. The rates and the per-trip floor that a statement is
computed under are stamped onto the statement itself as a `contract_id`, and that stamp is
deliberately not a live foreign key: a statement outlives the contract it was computed under and
must remain resolvable after that contract is no longer reachable by traversal. The stamped
identifier remains retrievable through the filtered list form of the billing-statement collection,
which accepts a contract filter, a district filter and a status filter. Non-monetary derived
quantities have their own precisions: the supply ratio is reported to four decimal places, rounded
half up, while seat counts, strike counts, block counts and impact scores are whole numbers.

### 2.9. Optimistic Concurrency Control

Two write operations are protected against lost updates by optimistic concurrency control, and only
those two. Creating a ride request requires a non-optional `expected_district_version` field
carrying the client's last-observed `version` of the target district. Running a district billing run
requires the same non-optional `expected_district_version` field against the target district. In
both cases, if the district's current `version` has already advanced past the value the client
supplied, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no resource is created or
modified. Both rules exist because the underlying operations are otherwise legitimately repeatable —
a second ride request may supersede an earlier one under the intake policy, and re-running a billing
run is ordinary product behaviour — so the stale version is the only signal that distinguishes an
authorised second attempt from one made against information the client has not observed. Operations
that are not named by a concurrency rule take no version field and perform no such check.

### 2.10. The Logical Clock

The platform evaluates every temporal rule — window ordering, lead times, term boundaries, clearance
expiry, wait-time accrual, statement period lapses — against a single logical clock rather than wall
time. At server start the logical clock reads exactly `2026-09-01T00:00:00Z` and it never falls back
to the host's wall clock. A `PlatformAdmin` advances the clock through an admin-only capability that
accepts a `to_iso8601` instant and sets the clock to it. Because every staleness, expiry and
term-boundary decision reads this clock, tests and operational runbooks can move the platform
through time deterministically without waiting for real time to pass.

### 2.11. Nested Resource Retrieval

Collection and sub-resource reads are validated left to right along the address hierarchy. When a
path addresses a child collection under a parent — a district's trips, a trip's alerts, a driver's
background checks, a geofence's checks — the platform first resolves the leading identifier, then
the child collection within it, and only then the addressed child. The first identifier that does
not resolve produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier in the same path is
consulted. for the API's unpaged list answers of §2.3 as well, and it is the same collection-read rule that
answers a parent's child collection with the whole filtered set rather than a page. The same ordering governs writes: a mutation addressed to a nested resource whose parent
does not exist, or exists outside the addressed district, is rejected as not found before any
business rule attached to the mutation is evaluated. A path identifier that resolves is not required
to match the acting role's own identity outside the `Driver` role, and a collection read under a
parent that resolves is answered with the whole filtered set the caller is permitted to see.

## 3. Business Logic & Workflows

Every operation in this section evaluates its guards in a fixed order, and the order is observable
because the first failing guard decides the error a caller receives. Authentication comes first:
the two identity headers must be present and the role must be one the platform recognises, or the
call is refused as unauthenticated; only the district self-registration path skips this. Authorisation
comes second: the acting role must be permitted for the operation, and any entity-backed or
driver-scoped check on the acting identity is settled here, so a caller who is not allowed to reach
an operation never learns whether that operation's later business rules would have passed.
Existence comes third, resolved left to right along the path as described in §2.11, so a missing or
out-of-scope ancestor is reported before any child rule. Only after those three gates do the
operation's own business checks run, and those checks have a settled order of their own: posture and
safety gates run before state gates, state gates run before referential and sibling-availability
gates, and referential gates run before fiscal gates. Within a single gate, the checks are evaluated
in the order the relevant workflow below describes them, and a request that would fail two checks in
the same gate reports the one named first. This ordering is what makes a trip in a locked posture
report a discrepancy lock rather than a wrong-state error, and what makes a district whose paperwork
is incomplete report the incompleteness rather than a downstream arithmetic failure.

### 3.1. District Onboarding, Contracting and the Credit Pool

A district enters the platform by self-registering, supplying its legal `name`, an accounts-payable
`billing_email` for statements, a default `contract_rate_per_ride_cents` and
`contract_rate_per_mile_cents`, and, optionally, a per-trip `minimum_billable_cents` floor that
defaults to zero, a list of `no_school_dates`, the district's earliest bell time as a `HH:MM` local
string in `bell_schedule_start`, and a `support_center_alert_enabled` switch that defaults to true
and decides whether `HIGH`-severity alerts also page the support desk. Self-registration is the only
operation in the API reachable without credentials; every walk of the retirement path below is
performed by a `DistrictAdmin` or a `PlatformAdmin`. Registration seeds the district's
`outstanding_balance_cents` and `credit_balance_cents` at zero, sets `account_status` to `ACTIVE`,
initialises `trips_scheduled_total` at zero, and stamps the district's first `version`; the account's
`account_status` therefore starts out able to issue statements. Every member of the registration body
beyond the fields named here — including a server-managed field such as `account_status`,
`trips_scheduled_total` or either balance — is refused with `ERR_INVALID_REQUEST` (HTTP 400), so
registration is never a route to seeding those values directly.

Commercial terms are carried on a contract that a `DistrictAdmin` drafts against the district with
`effective_from` and `through_date` bounds, a `per_ride_rate_cents` applied to each completed trip's
billable ride units, a `per_mile_rate_cents` applied to each completed trip's billable miles, an
optional `minimum_billable_cents` per-trip floor, and a `billing_period` of `WEEKLY`, `SEMI_MONTHLY`
or `MONTHLY` that decides the period key a generated trip is stamped with. A drafted contract begins
in `DRAFT`. Activation requires the contract's `effective_from` to fall on or before its
`through_date` — otherwise the attempt is refused with `ERR_CONTRACT_DATE_ORDER` (HTTP 422) — and
requires that no other contract for the same district is already `ACTIVE`, since a second active
contract is refused with `ERR_CONTRACT_OVERLAP` (HTTP 409). On successful activation the contract
moves to `ACTIVE`, every other `DRAFT` contract for that district is retired to `EXPIRED`, and the
district's `account_status` is set to `ACTIVE`. A contract may then be suspended, which moves it to
`SUSPENDED`, sets the district's `account_status` to `SUSPENDED`, and voids every `OPEN` billing
statement belonging to that district. Reactivating a suspended contract moves it back to `ACTIVE`
and returns the district to `ACTIVE`, but only while the logical clock date has not passed the
contract's `through_date`; a later attempt is refused with `ERR_CONTRACT_TERM_ENDED` (HTTP 409).
`EXPIRED` is terminal for a contract, and every later suspension, reactivation or second activation
attempt against an expired contract is refused with `ERR_ALREADY_TERMINAL` (HTTP 409) rather than the
ordinary wrong-state error — this is how a terminal-lockdown probe is told apart from a merely
wrong-state one. A drafted contract carries no server-set field beyond `status`, and any other member
of the drafting body is refused with `ERR_INVALID_REQUEST` (HTTP 400). A contract's own transitions
carry no version field and take no optimistic-concurrency check beyond the two operations §2.9 names;
they advance the contract's `version`, and the district-side effects the transitions carry (its
`account_status`) advance the district's `version` as well.

Districts also carry a credit pool that offsets future statements. A `DistrictAdmin` or
`PlatformAdmin` may apply a service-credit adjustment to the pool, providing an `amount_cents` and a
`reason`; the amount is added to `credit_balance_cents` and the district's `version` advances.
Credit is consumed rather than gifted: when a statement is computed the credit that will be applied
is reserved out of the pool immediately, and only the credit actually consumed by a statement
returns to the pool if that statement is later voided. A district's `credit_balance_cents` is
therefore a live figure that moves on statement computation, statement voiding and manual
adjustments alike. The `reason` member is accepted but optional, and a negative amount is applied
like any other: the pool is a signed figure, so an adjustment of two hundred cents against a five-
thousand-cent pool reads four thousand nine hundred. The adjustment is the one district mutation that
advances the district's `version` without being an optimistic-concurrency operation, so the field
that names the observed version is not accepted here and a body carrying `expected_district_version`
is refused as an unknown member.

### 3.2. Student Placement and Authorised-Adult Roster

A `DistrictAdmin` registers a student by supplying the district's identifier together with the
student's `full_name`, `date_of_birth`, `program_type`, `home_address`, `school_name`,
`emergency_contact_phone`, and optionally a `spi_level` that defaults to 1, a list of
`authorized_adults`, and the two notification switches `notify_on_pickup` and `notify_on_dropoff`,
both of which default to true. The `program_type` must be one of `FOSTER_CARE`,
`HOMELESS_MCKINNEY_VENTO`, `SPECIAL_EDUCATION` or `GENERAL`. The `spi_level` is a service priority
band running from 1 to 5 in which a lower number ranks the student higher when a driver is chosen
for a shared date. The band is a ranking convention rather than a validated range: a level outside
it is accepted and carried, and the ranking that reads it treats the stored integer as the whole of
the student's priority rather than clamping it into the band. A new student record begins in `ACTIVE` status with a zero
`active_ride_request_count`, and the platform derives the student's masked contact digest
`support_center_phone_masked` from the emergency contact number by retaining only the final four
digits. That masked digest is the only caregiver contact value a `Driver` ever sees: on the driver
read the real `emergency_contact_phone` member is not merely hidden but replaced by the masked
digest itself, so a driver who reads the field named `emergency_contact_phone` is handed the masked
value rather than the raw number.

The `authorized_adults` list is the student's handoff roster: each entry is an object carrying a
`name`, a `relationship` and a `phone`, and the `name` member is what the handoff authorisation
logic matches against — the other members are recorded but never consulted by the authorisation
rule. The student's `school_name` doubles as the name of the school-of-record party that a dropoff
verification may always name. Placement details are editable: a `DistrictAdmin` may update a
student's `home_address`, `school_name`, `emergency_contact_phone`, `authorized_adults`,
`notify_on_pickup`, `notify_on_dropoff` or `spi_level` after registration, and each such update
advances the student's `version`. The update admits only those seven members — the student's
identity, placement district, program type, status and the derived contact digest and request count
are not editable through it, and a body naming any of them is refused with `ERR_INVALID_REQUEST`
(HTTP 400) rather than silently ignoring the member. A member that is present is replaced wholesale,
and the posted list of `authorized_adults` replaces the stored roster rather than being merged into
it. A `Driver` addressing a student record on a trip assigned to them
receives the masked contact value in place of the real number; the real `emergency_contact_phone`
never leaves the platform toward a driver.

The student record also exposes a derived `active_ride_request_count`, which counts only ride
requests in `SUBMITTED` or `APPROVED` status. Requests that have already produced trips are tracked
by their trips instead and are deliberately excluded — counting a `SCHEDULED` request as well would
double-count a series that already has a live trip on the same date. Only ride-request rows
contribute to the count; trip rows never do.

### 3.3. Driver Qualification, Clearance Gating and Revocation

Driver supply is onboarded by a `DistrictAdmin`, who supplies the driver's `full_name`, `phone`,
`employer_org`, declared `caregiver_experience_months`, spoken `language_codes`, a `vehicle_class`
of `SEDAN`, `SUV` or `WHEELCHAIR_VAN`, a declared `seat_capacity`, and an optional `child_seat_type`
of `NONE`, `BOOSTER`, `HARNESS` or `INTEGRATED` that defaults to `NONE`. Caregiving experience is a
declared quantity because it is one of the qualification gates: a driver's declared months must
reach the twelve-month minimum in force, and a shortfall is refused with
`ERR_CAREGIVER_EXPERIENCE_SHORT` (HTTP 422) at the points named below. A newly onboarded driver
begins in `PENDING` status with a zero `approved_seat_count`, a null `compliance_expires_at` and a
zero `incident_strike_count`. The onboarding body admits only the declared onboarding fields: any
other member of the body — in particular a server-managed qualification or lifecycle field such as
`status`, `approved_seat_count`, `compliance_expires_at` or `incident_strike_count` — is refused with
`ERR_INVALID_REQUEST` (HTTP 400), so this operation is never a route to setting those four values
directly. The declared quantities are carried as supplied rather than range-checked: a
`caregiver_experience_months` below the twelve-month minimum, or a `seat_capacity` of zero or less,
is accepted at onboarding and disqualifies the driver later, when the qualification pipeline reads
it, rather than being refused here.

The qualification pipeline is a strictly forward-moving succession of three gates. From `PENDING`,
opening a `check_type` background check under the driver — providing a `reference_code` and an
`expires_on` — moves the driver into `BACKGROUND_CHECK` and creates the check record in `PENDING`
result with a null `cleared_after_months`. This first step is legal while the driver is in `PENDING`
or in `BACKGROUND_CHECK` — the state a failure returns the roster to is rebuildable, so a covering
paperwork set may be rebuilt from a fresh check — and refuses a driver who already holds a
`FINGERPRINT_FBI` check with `ERR_DUPLICATE_CLEARANCE`
(HTTP 409); the guard reads only the driver's `FINGERPRINT_FBI` rows, so a check of another type —
`FINGERPRINT_STATE`, `COUNTY_COURT` or `SEX_OFFENDER_REGISTRY` — may still be opened while a
`FINGERPRINT_FBI` check is on file. From `BACKGROUND_CHECK`, recording a vehicle inspection —
supplying a `vehicle_class`, a
`seat_count`, an optional `child_seat_type`, an `inspector_note` and an `expires_on` — moves the
driver into `INSPECTION` and creates the inspection in `PENDING` result with zero seat credit. That
second step requires the driver's declared caregiving experience to meet the twelve-month minimum,
refusing a shortfall with `ERR_CAREGIVER_EXPERIENCE_SHORT` (HTTP 422), and requires at least one
background check for the driver already to be in `CLEARED` result, refusing a driver with no cleared
check on file with `ERR_CLEARANCE_INCOMPLETE` (HTTP 409). An `INACTIVE` driver is the terminal
exception: because deactivation is the lifecycle's terminal move, the same refused step reports
`ERR_ALREADY_TERMINAL` (HTTP 409) for a driver who has already been deactivated rather than the
ordinary wrong-state error. The move into `INSPECTION` also advances
the driver's `version`.

The third gate closes the pipeline. Attesting a pending inspection as passed moves the driver to
`ACTIVE`, sets the inspection `result` to `PASSED`, sets its `seat_credit` to the inspected `seat_count`,
recomputes the driver's approved seat count and compliance expiry, and advances the driver's
`version`. Attestation requires the inspection to still be `PENDING`, requires its `expires_on` to
fall strictly after the logical clock date — a lapsed date is refused with `ERR_CLEARANCE_EXPIRED`
(HTTP 422) — requires the inspected `seat_count` to be at least one, since an inspection that counts
no usable seats is refused with `ERR_INSPECTION_SEAT_COUNT` (HTTP 422), and requires the driver to be
in `INSPECTION` specifically, refusing any other driver status with `ERR_INVALID_STATE` (HTTP 409)
even when the inspection itself is still pending. In other words the pipeline will not skip a stage:
a driver sitting in `PENDING` or `BACKGROUND_CHECK` cannot be promoted by attesting an inspection
that happens to be pending.

From `ACTIVE` there are two exits. A `DistrictAdmin` may deactivate the driver, moving them to
`INACTIVE` with a zeroed approved seat count; `ACTIVE` and `SUSPENDED` are the operation's only legal
source states, so a driver still working through `PENDING`, `BACKGROUND_CHECK` or `INSPECTION` is
refused with the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409), while a driver already
`INACTIVE` reports `ERR_ALREADY_TERMINAL` (HTTP 409). Deactivation is refused with
`ERR_DRIVER_ON_TRIP` (HTTP 409)
while the driver holds any trip in `AWAITING_STUDENT`, `STUDENT_ONBOARD` or `IN_TRANSIT`, because a
driver already carrying a student cannot be removed from the roster. A `SUSPENDED` driver may be
deactivated along the same route, under the same in-progress trip bar. `INACTIVE` is terminal for
the driver dimension, so the reactivation path below is never legal from it and reports
`ERR_ALREADY_TERMINAL` (HTTP 409) rather than a wrong-state refusal.
Alternatively the platform
itself may suspend a driver: when an incident is resolved with the driver adjudicated at fault and
the recomputed strike count reaches the three-strike suspension threshold, the driver moves from
`ACTIVE` to `SUSPENDED`, and every trip for that driver still sitting in `SCHEDULED` or
`DRIVER_EN_ROUTE` is cancelled — with the assigned driver cleared, the claimed operator cleared, the
acceptance instant cleared, any pinned candidate cleared, and the trip's safety posture locked — and
the district's scheduled-trip total is decremented once for every trip cancelled by that cascade.
Reactivation of a suspended driver is available to a `DistrictAdmin` only while the driver's
compliance expiry still falls strictly after the logical clock instant; an expired driver is refused
with `ERR_CLEARANCE_EXPIRED` (HTTP 422), and a suspended driver whose compliance expiry is unset is
refused the same way. Reactivation returns the driver to `ACTIVE` and advances
their `version`.

#### 3.3.1. Background-Check Content Gating and Revocation

Background checks are typed records, and the type matters. A check's `check_type` is one of
`FINGERPRINT_FBI`, `FINGERPRINT_STATE`, `COUNTY_COURT` or `SEX_OFFENDER_REGISTRY`. A pending check
may be cleared by a `DistrictAdmin` while its `result` is still `PENDING`, and only while the check's
`expires_on` falls strictly after the logical clock date; a lapsed date is refused with
`ERR_CLEARANCE_EXPIRED` (HTTP 422). Clearing sets the check's result to `CLEARED`, computes
`cleared_after_months` as the whole number of months between the check's creation and the moment the
result became `CLEARED`, and recomputes the driver's approved seat count and compliance expiry. The
month count is the number of whole calendar months completed between the check's creation date and
the clearing date, never negative, so a check cleared in the same month it was opened reports zero.
Clearing a check whose result is already `CLEARED` or `FAILED` is refused with
`ERR_ALREADY_TERMINAL` (HTTP 409) rather than the ordinary wrong-state error. When
the driver still holds an existing background check that has already failed, the driver's status
stays in `BACKGROUND_CHECK` after the clear — a failure is not erased by a later clearance, and the
driver's covering paperwork must be rebuilt from a fresh check. Clearing a check also advances the
check's own `version`.

Failure is the load-bearing branch of this machine and it behaves differently from each source
state. Failing a check whose result is `PENDING` sets that check to `FAILED`, flips every other
pending check for the same driver to `FAILED` as well, returns the driver to `PENDING`, zeroes the
driver's approved seat count, nulls the compliance expiry, and cancels every trip for that driver
still sitting in `SCHEDULED` or `DRIVER_EN_ROUTE` with the assigned driver and any pinned candidate
cleared and the trip's safety posture locked. Failing a check that is already `CLEARED` is the
revocation path, and it is available only for the three revocation-eligible types —
`FINGERPRINT_FBI`, `FINGERPRINT_STATE` and `SEX_OFFENDER_REGISTRY`; a cleared `COUNTY_COURT` check
cannot be revoked this way and the attempt is refused with `ERR_INVALID_STATE` (HTTP 409). Revoking a
cleared fingerprint clearance moves the driver to `SUSPENDED`, recomputes the approved seat count,
and cancels every trip for that driver still in `SCHEDULED` or `DRIVER_EN_ROUTE`, clearing the
assigned driver and locking the trip's safety posture. The recomputation that follows the revocation
reads `SUSPENDED` as one of the lifecycle statuses the approved-seat rule counts as qualifying, so
the seat count is reported at the value the revoked paperwork still supports rather than collapsing
to zero. Failing a check whose result is already `FAILED` is refused with `ERR_ALREADY_TERMINAL`
(HTTP 409), the failure branch being terminal for the check row itself.

Inspections have their own terminal behaviour and their own compensating action. Rejecting a
`PENDING` inspection sets it to `FAILED` with zero seat credit and recomputes the driver's approved
seat count. Rejecting an inspection that has already been `PASSED` does the same, and in addition
suspends the driver and cancels every trip for that driver still in `SCHEDULED` or `DRIVER_EN_ROUTE`
with the assigned driver cleared and the trip posture locked. Because rejection zeroes the seat
credit, the rejected driver's approved seat count falls back to exactly the value it held before the
attestation — rejection is the compensating action for attestation, and the way to restore a
driver's seats is a later attestation of a fresh pending inspection, never the un-failing of the
rejected row. A `FAILED` inspection is terminal for its own dimension: rejecting it a second time, or
attesting it after the rejection, is refused with `ERR_ALREADY_TERMINAL` (HTTP 409) rather than the
ordinary wrong-state error, and the same terminal answer is given to an attestation attempted
against an inspection that has already been `PASSED`. An `INACTIVE` driver is likewise terminal, so
the attestation step reports `ERR_ALREADY_TERMINAL` (HTTP 409) for a deactivated driver as well as
the `ERR_INVALID_STATE` (HTTP 409) it reports for any other driver status.

### 3.4. Ride Request Intake and Approval

Intake begins when a `DistrictAdmin` opens a ride request for a student, supplying the `district_id`
and `rider_id` the request belongs to, a `trip_type` of `AM_SCHOOL`, `PM_SCHOOL`, `MIDDAY` or
`ACTIVITY`, a `window_start_at` and `window_end_at` bounding the acceptable pickup-to-dropoff span,
a `pickup_address` and a `dropoff_address`, and optionally a `required_specialty` of `NONE`,
`CAREGIVER_REQUIRED` or `WHEELCHAIR` that defaults to `NONE`, a `max_window_minutes` cap that
defaults to 30, a `min_lead_time_hours` that defaults to 12, a `planned_miles` route distance, an
`is_recurring` flag that defaults to false and turns the request into a school-year series, and the
series descriptors `days_of_week`, `series_effective_from`, `series_through_date` and
`series_no_school_dates`, which are live only when the request is recurring. This create is one of the two operations protected by
optimistic concurrency: the payload carries `expected_district_version`, and a value that no longer
matches the district's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The
stale-version guard is what separates an authorised superseding request from one made against
information the caller has not observed, because intake policy does permit a second request to
supersede an earlier one for the same student and window. A new request begins in `DRAFT` with a
zero `revision_count` and an inactive `recurring_series_active` flag, and its creation advances the
district's `version`. The body admits only the declared intake fields; any other member is refused
with `ERR_INVALID_REQUEST` (HTTP 400). The stale-version guard is evaluated before the `rider_id`
is resolved, so a caller holding a stale district version is answered `ERR_STALE_VERSION` (HTTP 412)
even when the student it names does not exist, and the student is resolved — and reported as
`ERR_NOT_FOUND` (HTTP 404) when it does not — only once the version matches. A recurring request
whose `series_effective_from` falls after its `series_through_date` is refused at creation with
`ERR_INVALID_REQUEST` (HTTP 400).

A draft is submitted for review by a `DistrictAdmin`, which requires the request to be in `DRAFT`,
requires `window_start_at` to fall strictly before `window_end_at` — otherwise the attempt is
refused with `ERR_WINDOW_TOO_WIDE` (HTTP 422) — and requires the span from window start to window
end to be no greater than the request's `max_window_minutes`, again refused with
`ERR_WINDOW_TOO_WIDE` (HTTP 422). The same window-order and window-width checks guard approval, so
an over-wide or inverted window is refused at both the submit and the approve gate. Submission moves
the request to `SUBMITTED` and recomputes the student's active request count.

Approval is the intake gate that decides whether the request is acceptable product at all, and it
enforces several conditions together. The request must be in `SUBMITTED`, and the student must be in
`ACTIVE` status — a request for an inactive student is refused with `ERR_RIDER_INACTIVE` (HTTP 409).
For a one-off request, the interval between the logical clock instant and the window's start must be
at least the request's `min_lead_time_hours`, so a request approved with too little notice is
refused with `ERR_LEAD_TIME_TOO_SHORT` (HTTP 422) — the twelve-hour default is the ordinary case.
For a recurring request the lead-time gate does not apply; instead the series' `series_effective_from`
must fall on or after the academic term opening date of `2026-08-15`, and a series starting before
the term opens is refused with `ERR_OUTSIDE_SCHOOL_TERM` (HTTP 409). A recurring request must also
carry at least one entry in `days_of_week`, drawn as ISO weekday integers from 1 to 7; an empty or
out-of-range selection is refused with `ERR_INVALID_REQUEST` (HTTP 400). On success the request moves
to `APPROVED`.

Not every submitted request is approved. A `DistrictAdmin` may return a submitted request for
revision, moving it to `REVISION_REQUESTED`, incrementing its `revision_count`, and recording a
`revision_note` describing what must change; the revision count is the observable record of how many
times the request has been sent back. The requester then resubmits, moving the request back to
`SUBMITTED`; the submit-and-revise cycle may repeat without bound. A submitted or approved request
may instead be rejected outright with `reason`, moving it to `REJECTED` and clearing its recurring
series flag; a draft request may be cancelled with a `reason`, which also clears the series flag. `REJECTED` and
`CANCELLED` are terminal for a ride request, and once a request is in either state no further intake
transition is accepted from it. Every one of those intake transitions is a state change on an
existing request and answers `200 OK`; the two refusal branches are distinguished, because a request
already sitting in `REJECTED` or `CANCELLED` reports `ERR_ALREADY_TERMINAL` (HTTP 409) while a request
in any other state that the operation does not accept reports the ordinary wrong-state error
`ERR_INVALID_STATE` (HTTP 409). The `reason` and `revision_note` members are accepted but optional,
and neither is persisted on the request: the revision counter, not the note, is the record of how
often the request was sent back. Cancellation is admitted from `DRAFT` and `SERIES_SUSPENDED` only, so
a `SUBMITTED` or `APPROVED` request is not cancellable through it and must instead be rejected.

### 3.5. Scheduling, Recurring Series and No-School Calendars

Scheduling is where a request becomes work. A `DistrictAdmin` schedules a request with a
`scheduled_date` for a one-off request, and the platform generates one trip per included date for a
recurring series. Scheduling requires the request to be in `APPROVED`. For a one-off request, the
target `scheduled_date` must not already carry a trip for the same request; a duplicate is refused
with `ERR_ALREADY_SCHEDULED` (HTTP 409). For a recurring series the included-date count must be
greater than zero — a series whose window contains no school day at all is refused with
`ERR_NO_SCHOOL_DAYS_IN_RANGE` (HTTP 409) — and for every included date the driver selector must
yield at least one eligible candidate, otherwise the whole scheduling call fails with
`ERR_NO_ELIGIBLE_DRIVER` (HTTP 409), with no silent skip and no deferred queue. Series scheduling
also runs the driver-occupancy test described in §2.6 and refuses a date whose driver already holds
an overlapping interval with `ERR_DRIVER_WINDOW_OVERLAP` (HTTP 409). Finally, no included date may
carry a window that touches or overlaps an existing non-terminal trip window for the same student,
refused under the closed-interval rider rule with `ERR_RIDER_WINDOW_OVERLAP` (HTTP 409). On success
the request moves to `SCHEDULED`, its `recurring_series_active` flag is set to whether the request is
recurring, one trip is created per included date with the request and student attached and no driver
assigned, and the district's `trips_scheduled_total` rises by the number of trips created. The
request also carries the driver the selection rule picked for each date as that trip's pinned
candidate, so scheduling pins a candidate per date even though no driver is assigned; a subsequent
dispatch step re-pins the candidate by recomputing the same rule. Dates
that are not included produce no trip at all. Scheduling a request — one-off or recurring — adds new
trips to the district's trip collection, so both forms answer with `201 Created`. The scheduling body
admits `scheduled_date` alone and refuses any other member with `ERR_INVALID_REQUEST` (HTTP 400); the
member is ignored for a recurring request, whose dates come from the series' own calendar, and is
required for a one-off. The guard order within scheduling is settled: the rider's own closed-interval
collision against existing trips is evaluated before the driver search, so a duplicate student window
is reported as `ERR_RIDER_WINDOW_OVERLAP` (HTTP 409) ahead of any driver-side outcome.

The included-date set for a series is computed from the series' own calendar intersected with the
district's. The window opens at the later of the series' `series_effective_from` and the logical
clock date, and closes at the series' `series_through_date`; both ends are inclusive. Note that the
window opens at the later of the two, not the earlier, so a series whose effective date already lies
in the past contributes nothing from the past — reading the window as the earlier of the two would
silently back-fill trips the district never asked for. A candidate date is excluded when it appears
in either the series' own `series_no_school_dates` list or the district's `no_school_dates` list, and
is further excluded when it falls before the academic term opening date, when its ISO weekday is not
among the request's `days_of_week`, or when a trip for the same request already sits on that date in
a state other than `CANCELLED`. A date suppressed only by an existing trip becomes creatable again
once that trip is cancelled, which is what lets a resumed series restore a date it had previously
issued.

A `DistrictAdmin` may suspend a recurring series, moving the request to `SERIES_SUSPENDED` with the
series flag cleared and cancelling every trip for that request still sitting in `SCHEDULED` or
`DRIVER_EN_ROUTE` — clearing any pinned candidate and decrementing the district's scheduled-trip
total once per cancelled trip. Suspension requires the request to actually be recurring, refusing a
one-off request with `ERR_NOT_RECURRING` (HTTP 409), and requires that no trip in the series is
currently `STUDENT_ONBOARD` or `IN_TRANSIT`, refusing a series with a trip in progress with
`ERR_TRIP_IN_PROGRESS` (HTTP 409). A suspended series may be resumed, which requires the logical
clock date not to have passed the series' `series_through_date` — a late resume is refused with
`ERR_SERIES_ENDED` (HTTP 409) — and requires the included-date count to be greater than zero, refused
with `ERR_NO_SCHOOL_DAYS_IN_RANGE` (HTTP 409). A successful resume returns the request to
`SCHEDULED`, reactivates the series flag, and generates one trip per included date. The date set a
resume uses is derived afresh, so the dates its suspension released — which the relaxation of §3.5's
existing-trip exclusion makes creatable again — are regenerated as new trip rows while the cancelled
rows remain on the district's trip collection; the live scheduled load, not the row count, is what
the district reports. Resume guards the series' own end before its date set, so a series whose
`series_through_date` has passed reports `ERR_SERIES_ENDED` (HTTP 409) ahead of
`ERR_NO_SCHOOL_DAYS_IN_RANGE` (HTTP 409), and it re-runs the same rider-side closed-interval
collision against trips belonging to the student's other requests, refused as
`ERR_RIDER_WINDOW_OVERLAP` (HTTP 409) with every trip it had generated being rolled back rather than
left behind. Resuming is a
state transition of an existing request rather than the creation of a stand-alone resource, so it
answers with `200 OK`; suspension is the same shape and also answers `200 OK`. Both answer with the
updated request object rather than with the trips they cancelled or generated, so a resumed series
reports the request's new `SCHEDULED` status and active series flag and the generated trips are read
back through the request's trip collection. Suspension requires `SCHEDULED` as its source state and
reports the ordinary wrong-state error for any other; the two refusal branches that follow it are
evaluated in the order named above, so a one-off series reports `ERR_NOT_RECURRING` (HTTP 409) ahead
of the in-progress-trip check. Suspension releases the series' trips without rewriting their safety
posture, so a cancelled trip in a suspended series keeps the posture it held.

The district calendar is itself addressable: a `DistrictAdmin` or `PlatformAdmin` may emit a system
event carrying an `event_type`, an `effective_date` and a `district_id`. An event of type
`NO_SCHOOL_DAY` appends the effective date to the district's `no_school_dates`, and every ride
request in that district that is `SCHEDULED` with an active recurring series immediately cancels the
trips whose `scheduled_date` equals that date, decrementing the district's scheduled-trip total once
per cancelled trip. This is how a school closure declared mid-term reaches a series that is already
generating trips, without any per-request intervention. The event body admits `event_type`,
`effective_date` and `district_id` and refuses any other member with `ERR_INVALID_REQUEST` (HTTP
400); `NO_SCHOOL_DAY` is the platform's only event type, so any other value is refused the same way.
A date already present in the district's calendar is not appended a second time, and the answer is
the updated district object, whose `no_school_dates` list carries the closure. The fan-out is
date-scoped and state-scoped: it cancels only trips on that exact date whose ride request is
`SCHEDULED` with an active recurring series, and it leaves the trips it cancelled in the posture they
held rather than locking them.

### 3.6. Driver Selection and Dispatch

Choosing which driver covers a date is governed by a single published selection rule, and every code
path that needs a driver for a date reads that same rule rather than re-deriving it. The candidate
set is first filtered to drivers who simultaneously satisfy all of the following: the driver's
`status` is `ACTIVE`; the driver's approved seat count is at least one; the driver's
`caregiver_experience_months` reaches the twelve-month minimum; the driver's compliance expiry falls
after the start instant of the selected date; and the request's `required_specialty` is satisfied —
`NONE` accepts any candidate, `CAREGIVER_REQUIRED` requires at least twelve months of declared
caregiving experience, and `WHEELCHAIR` requires a `WHEELCHAIR_VAN` vehicle class. Drivers in
`INACTIVE`, `PENDING`, `BACKGROUND_CHECK` or `SUSPENDED` status are excluded before any ranking
happens. The surviving candidates are ordered by three ascending keys in sequence: first whether the
driver already has another trip whose window overlaps the date, where a driver with no overlapping
trip sorts ahead of one who does; second the driver's incident strike count; third the student's
`spi_level`, where a lower level ranks ahead. When all three keys tie, the fallback is the driver's
creation time ascending, so the earliest-registered candidate wins; the driver's identifier is never
consulted for this or any other ordering decision.

When the filter returns no candidate at all for a required date, a widened selection pass runs
instead: it relaxes the seat requirement to allow a driver with zero approved seats while still
requiring `ACTIVE` status, then re-ranks using the same three keys plus a fourth — compliance expiry
descending — so the driver with the longest remaining coverage wins. If the widened set is also
empty, the scheduling call fails with `ERR_NO_ELIGIBLE_DRIVER` (HTTP 409). A separate scored
ordering is also available to the dispatcher when a numeric ordering is requested rather than a
lexicographic one: it collapses the three keys into a single score that weights the overlap key most
heavily, the strike count next and the student's priority level least, and ranks ascending, which
gives the strike count a strictly larger influence than the lexicographic ordering whenever the keys
disagree.

A trip that has already been created is offered to a driver through a dispatch step that pins the
selected candidate onto the trip. A `DistrictAdmin` or `PlatformAdmin` asks the platform to pin the
candidate for a dated trip, and the platform resolves the driver for that date and student using the
selection rule above, records the driver in `candidate_driver_id` as the trip's pinned candidate, and refuses with
`ERR_NO_ELIGIBLE_DRIVER` (HTTP 409) when no candidate exists. The pinned candidate is a
recommendation, not an assignment: it is re-checked against the full eligibility filter at the
moment the driver accepts, and a candidate who has slipped out of eligibility — no longer `ACTIVE`,
below the experience minimum, expired coverage, no approved seat, or no longer matching the required
specialty — causes the acceptance to be refused with `ERR_DRIVER_INELIGIBLE` (HTTP 409). The full
eligibility filter is likewise re-applied during series scheduling, so a date whose only candidates
have since become ineligible is refused rather than scheduled optimistically. The selection rule
excludes the trip being dispatched from its own occupancy test, so the candidate is chosen as though
the trip under dispatch did not already speak for the driver's seat. Acceptance is scoped to the
`Driver` and `DistrictAdmin` roles; a `DistrictAdmin` acting on the driver's behalf skips both the
pinned-candidate check and the candidate-freshness re-check, and pins the platform-selected
candidate itself when the trip carries none, so an administrator may carry an undecided trip into
`DRIVER_EN_ROUTE` with the rule's choice recorded as the driver.

A `DistrictAdmin` may also block a driver's availability on a district route segment, supplying the
`driver_id`, a `block_start_at`, a `block_end_at` and a `reason`. The block is refused with
`ERR_DRIVER_WINDOW_OVERLAP` (HTTP 409) when its half-open interval overlaps any trip window already
assigned to that driver; adjacency with a zero-minute gap is accepted. The twenty-minute route-segment
buffer of §2.6 is a planning allowance and is not applied here: the block's boundary against a
driver's existing trip windows is evaluated at second precision with no widening of the collision
window, so a block that begins exactly at a trip's close is accepted. The `reason` member is accepted
but optional, and the block is recorded but not itself addressable afterwards. A successful block returns the
ride requests affected by it. A companion operation re-derives the district's covered-driver roster
and committed-seat counts across a `horizon_start` to `horizon_end` span and returns the district's
trips inside that horizon; the recomputed plan itself is read back through the supply-plan read
described in §3.7. The block's returned ride-request set, the supply run's returned trip set and the
geofence-check recording's returned checks of §3.9 are the API's three unpaged list answers: each
ignores any `limit` or `offset` a caller supplies and reports the whole set it produced, in that
operation's own order. The supply run's body admits `horizon_start` and `horizon_end` and refuses any
other member, and its returned trips are ordered by creation instant ascending.

### 3.7. Supply Planning Against Bell Schedules

Districts plan driver supply against committed seats, and the plan is read over an inclusive horizon
bounded by a `horizon_start` and a `horizon_end`. The published definition of which driver covers
which date is a single predicate that every planning call site reads: a driver covers a date when
the driver's `status` is `ACTIVE`, the driver's `caregiver_experience_months` reaches the twelve-month
minimum, the driver's compliance expiry falls after the start instant of that date, and the driver
holds at least one `PASSED` vehicle inspection whose `expires_on` falls after that date. For a driver
who does not cover the date, the coverable seat count contributed to the plan is the driver's
declared `seat_capacity`; for a driver who does cover the date, the contribution is the larger of
that driver's approved seat count and one. The second branch matters: once a driver is covered for a
date, the roster claims at least one coverable seat even when the trip-load veto inside the approved
seat count has driven that count to zero, so a covered but fully committed driver still counts
toward capacity instead of silently dropping off the roster on every busy day.

The plan itself is an aggregation over the horizon. A date is covered when at least one driver on
that date meets all of: `ACTIVE` status, an approved seat count of at least one, the twelve-month
caregiving minimum, a compliance expiry after the date's start instant, and a `PASSED` inspection
expiring after the date. The plan's `shift_capacity_on_date` is the sum of the coverable-seat
contributions of the drivers covering that date. Its `seats_committed_on_date` is the number of trips
scheduled for that date whose `trip_state` is neither `COMPLETED` nor `CANCELLED` — completed and
cancelled trips consume no seats. The `seat_deficit` for a date is the number of committed seats in
excess of that date's capacity, floored at zero. The `supply_ratio` for a date is the committed
seats divided by that date's capacity, reported to four decimal places with half-up rounding, and it
is null on a date whose capacity is zero. A separate `alerts_sent` figure counts the covered drivers
who have at least one incident strike.

A date can be reported as short in two different ways, and the two definitions are issued side by
side rather than reconciled. The `understaffed_dates` list contains every date whose `supply_ratio` is
not null and is strictly below the staffing ratio of 0.8. The `seat_deficit_dates` list contains
every date whose `seat_deficit` is strictly greater than zero. The two lists diverge whenever the
ratio is low but every committed seat still fits inside capacity — three committed seats against a
capacity of five, for instance, is not understaffed by the deficit test even though it is below the
ratio threshold. The read additionally reports `per_date` detail alongside those two lists. A
restricted reading of the same plan counts committed seats only over trips that already have a driver
assigned, so unassigned `SCHEDULED` trips vanish from demand and a date can report a zero deficit
even though the base rule reports it short by the number of its unassigned trips. The restricted
reading is requested by naming the plan's demand filter as a query parameter on the read; the plan is
a computed object rather than a list, so it carries no pagination fields in its envelope. The plan
reports its horizon bounds, the district's identifier and earliest bell time, and the two lists
alongside `per_date`. The per-date detail and each of the plan's date-keyed maps are keyed by the ISO
scheduled date, and each date-keyed figure is repeated under `per_date` so the two are always
consistent. `per_date` carries one entry per date in the inclusive horizon even when nothing is
covered and nothing is committed, and a coverage figure is read as a whole number while the ratio is
the only fractional one. The plan is derived on read and is not itself a stored resource, so it
carries none of the common properties of §2.7.

### 3.8. Trip Execution, Handoffs and Absence Reporting

A trip can be created either as a by-product of scheduling a request, as described in §3.5, or
directly against an already-scheduled request. Direct creation supplies `expected_district_version`
alongside the `ride_request_id` the trip instantiates, a `scheduled_date`, a `window_start_at` and a
`window_end_at`, and an optional `planned_miles`. A generated trip takes the ride request's
time-of-day for its window start and binds it to the trip's own scheduled date, and inherits the
planned distance the same way. Direct creation is legal only against a request that is already
`SCHEDULED`, refused otherwise with `ERR_INVALID_STATE` (HTTP 409), and it refuses a second trip for
the same request and date with the same wrong-state error rather than `ERR_ALREADY_SCHEDULED` (HTTP
409), that identifier being reserved for the scheduling operation's own duplicate test. Its
`expected_district_version` is checked against the district the request belongs to, so a stale caller
is refused before the date and window are examined, and a window that does not open strictly before
it closes is refused with `ERR_INVALID_REQUEST` (HTTP 400). Every new trip begins with `trip_state` `SCHEDULED` and `safety_state`
`NORMAL`, zero billable ride units and zero billable miles; its `billing_period_key` is derived from
its scheduled date under the district's `ACTIVE` contract, which fixes which statement the trip will
eventually land on. Creating a trip raises the district's scheduled-trip total by one and advances
the district's `version`.

Movement is driven by the assigned `Driver`. Acceptance advances the trip from `SCHEDULED` to
`DRIVER_EN_ROUTE` and is refused with `ERR_INVALID_STATE` (HTTP 409) unless the trip is still
`SCHEDULED`, with `ERR_TRIP_DISCREPANCY_LOCK` (HTTP 409) unless the safety posture is `NORMAL`, with
`ERR_TRIP_ALREADY_CLAIMED` (HTTP 409) once the trip already carries a driver, and with
`ERR_DRIVER_NOT_SELECTED` (HTTP 403) when the caller is not the driver that was pinned as the trip's
dispatch candidate — acceptance re-checks candidate freshness because the roster can change between
the pinning step and the acceptance. A successful acceptance records the driver as both `driver_id`
and `claimed_by_user_id`, stamps the acceptance instant into `accepted_at`, and advances the
driver's `version`. The same acceptance advances the trip's `version`.
Arrival advances the trip from `DRIVER_EN_ROUTE` to `AWAITING_STUDENT`, and requires the caller to be
the trip's assigned driver, refusing anyone else with `ERR_NOT_TRIP_DRIVER` (HTTP 403); departure
advances from `STUDENT_ONBOARD` to `IN_TRANSIT` under the same driver-match rule, and raises a
geofence-breach alert against the trip when the logical clock instant has already passed the trip's
window close.

Handoffs are the content-gated heart of trip execution. A handoff record captures a `leg` of `PICKUP`
or `DROPOFF`, an `expected_party` of `SCHOOL_STAFF`, `AUTHORIZED_ADULT` or `PLACEMENT_WORKER`, the
`verified_party_name` of the person who released or received the student, a `verification_method` of
`PHOTO_ID`, `PIN` or `PHYSICAL_SIGNATURE`, and a `verification_code` that is required when the method
is `PIN`; a dropoff handoff may additionally carry the odometer reading in `billable_miles`. Each
recorded handoff is also stamped with the server instant it was captured in `captured_at`. The
platform derives the handoff's `authorized` verdict and its `result` of `PASSED` or `FAILED`. The
`verification_code` member is admitted on either leg but is read only when the leg's rule names it,
and the `billable_miles` member is read on a `DROPOFF` leg alone: naming it on a `PICKUP` leg is
admitted as a field but never copied onto the trip, the odometer reading being a completion-time
figure.

At a `PICKUP` leg the student is being released to the driver, so the releasing party is checked
against the student's own placement record rather than the driver roster. When the expected party is
an `AUTHORIZED_ADULT`, the handoff passes only when the verified party's name appears among the names
in the student's `authorized_adults` list, and fails otherwise; when the expected party is a
`PLACEMENT_WORKER`, the handoff passes only when the verification method is a `PHYSICAL_SIGNATURE`,
and fails otherwise; and when the expected party is `SCHOOL_STAFF` the handoff fails outright,
because school staff are never a valid releasing party at pickup.

At a `DROPOFF` leg the checks are different, and the code-length rule that the pickup leg does not
apply is applied here. A verified party whose name matches the student's `school_name` always passes,
because the school of record always accepts the student. A verified party whose name appears among
the student's `authorized_adults` passes provided that, when the verification method is `PIN`, the
supplied `verification_code` is exactly six alphanumeric characters; a `PIN` handoff with a code of
any other length fails, and the rule attaches to the `PIN` method alone — a `PHOTO_ID` or
`PHYSICAL_SIGNATURE` handoff is never rejected for the shape of its code. Any other verified party
fails. Across both legs, names are
compared exactly after trimming surrounding whitespace and normalising Unicode, with case ignored,
so a near-match between two differently spelled names is a failed handoff rather than a review item.
A handoff whose derived `authorized` verdict is false is reported
through `ERR_HANDOFF_NOT_AUTHORIZED` (HTTP 403) when it is presented as a transition into a completed
leg; a handoff whose `result` is `FAILED` is refused the same way. A handoff that is refused for its
verdict is nonetheless recorded, so its `FAILED` row is readable afterwards, and a refused `PICKUP`
leaves the trip where it stood while a refused `DROPOFF` still carries the trip through the failing
completion described below. Each trip permits at most two handoff attempts in the relevant sense: a
second pickup handoff on the
same trip, or a second dropoff handoff already recorded as failed, is refused with
`ERR_HANDOFF_ALREADY_ATTEMPTED` (HTTP 409). The attempt cap outranks the trip's own gates: it is
evaluated against the handoffs already recorded before the safety posture and movement state are
consulted, so a second pickup attempt against a trip whose posture has since degraded still reports
`ERR_HANDOFF_ALREADY_ATTEMPTED` (HTTP 409) rather than a posture refusal. A `DROPOFF` may be attempted
again after a dropoff that passed, since only a *failed* dropoff closes the leg.

A passing pickup handoff advances the trip from `AWAITING_STUDENT` to `STUDENT_ONBOARD`, records the
verifying user, and dispatches a pickup notice to the student's `emergency_contact_phone` when the
student's `notify_on_pickup` is true and emits nothing when it is false. A passing dropoff handoff
advances the trip from `IN_TRANSIT` to `COMPLETED`, stamps the completion instant, records the
verifying user and the name of the party recorded on the passing dropoff, dispatches a dropoff
notice when `notify_on_dropoff` is true, recomputes the student's active request count when the
parent request is `SCHEDULED`, and sets the trip's `billable_ride_units` from the completion record.
The completed trip also records `completed_at`, and the dropoff records the verifying operator in
`verified_by_user_id` together with the name of the receiving party in
`verified_authorized_adult_name`.

A failing dropoff is a content-gated graph of its own: the dropoff may be failed outright, or it may
be presented as passing against a party who is not on the student's authorised-adult list. When a
`DROPOFF` handoff fails, the trip still completes — it moves to `COMPLETED` and is stamped with the
completion instant — but the platform records the unauthorised handoff as the trip's exception,
moves the trip's safety posture into `DISCREPANCY`, raises a handoff-dispute alert against the trip,
and opens a safety incident of category `HANDOFF_DISPUTE` with `MEDIUM` reported severity, `REPORTED`
status and the trip's assigned driver attached. The dispute alert is anchored to that incident, so
reviewing or voiding the incident closes the alert with it, and the alert's own severity is derived
by the shared alert rule of §3.9 from the dispute type, the trip's accumulated outside-fence
observations and the assigned driver's strikes — so a dispute on a trip that already carries two
outside-fence observations, or on a driver at three strikes, reads `HIGH` even though the incident
beside it was opened at `MEDIUM`. A failing dropoff does not record the receiving party, so the trip's
`verified_authorized_adult_name` stays unset while `verified_by_user_id` names the acting driver. The penalised ride unit is retained: a trip whose
dropoff failed carries one billable ride unit rather than two, and clearing the exception later does
not refund that unit.

Billable ride units are locked in at completion. A trip that has not completed carries zero units; a
trip that completed with both a passing pickup and a passing dropoff carries two; any other
completed trip carries one. Because the number is set when the trip completes, a later clearing of
the trip's exception leaves it at the completion-time value rather than recomputing it back up.

A student who is absent from the pickup point or refuses to board is reported by the assigned driver
through the exception path, carrying the driver's `note` alongside the issue, which requires the submitted `issue` to be either `RIDER_NOT_PRESENT` or
`RIDER_REFUSED_BOARDING` — any other issue is refused with `ERR_INVALID_REQUEST` (HTTP 400) — and
requires the driver to be the trip's assigned driver, refusing anyone else with `ERR_NOT_TRIP_DRIVER`
(HTTP 403). Reporting is also gated on wait time: the trip's accrued wait-time block count must have
reached the two-block minimum, and an early report is refused with `ERR_WAIT_TIME_NOT_MET` (HTTP
409). The already-reported guard is evaluated ahead of the body's own field checks, so a second
report against a trip that already carries an absence incident reports
`ERR_INCIDENT_ALREADY_REPORTED` (HTTP 409) even when its `issue` member is malformed. Wait time is measured in twelve-minute blocks: the elapsed whole minutes between the logical
clock instant and the trip's arrival are divided into blocks, where an elapsed time of twelve minutes
or less is still the first block, each further full twelve-minute span adds one block, elapsed time
before arrival counts as no block at all, and the count is capped at five blocks. The counter is
meaningful only while the trip sits in `AWAITING_STUDENT`; once the trip leaves that state it does
not advance further, and any trip in another state reports no blocks. Reporting also requires that no
absence incident of category `NO_SHOW_UNVERIFIED` has already been recorded for the trip; a second
report is refused with `ERR_INCIDENT_ALREADY_REPORTED` (HTTP 409).

A successful absence report cancels the trip, stamps the issue as the trip's exception and records
when it was stamped, and grades the absence. The grade is driven by the student's program type, the
accrued wait blocks and the student's priority level, weighted by whether the dispatch was late.
Students in `FOSTER_CARE` and `HOMELESS_MCKINNEY_VENTO` placements weigh most heavily, students in
`SPECIAL_EDUCATION` weigh more than general-education students, and — separately from the weighting —
a student whose service priority `spi_level` is higher raises the points more. The block count used
is the accrued wait blocks with a floor of one, so a zero-block reading still contributes one block's
worth, and the points are the program weight multiplied by that block count multiplied by one plus
half the student's priority level. A dispatch that never assigned a driver applies a halving discount
to those points; a dispatch whose clock instant is at or before the trip's window close applies the
normal multiplier; and a dispatch that ran past the window close applies a one-and-a-half multiplier.
The multiplier branches are exclusive and are settled in that order: a trip with no assigned driver
always takes the halving discount whatever the clock reads, and a trip that does carry a driver
takes the normal multiplier when the logical clock instant is at or before the window's close and
the penalty multiplier otherwise. The grade is computed only from the wait and weighting inputs at
the moment of the report, so a trip whose exception is graded once keeps that grade even if the
clock later advances past its window.
The points are then rounded half up to one decimal place and graded: at least eight points grade
`HIGH`, at least four but fewer than eight grade `MEDIUM`, and fewer than four grade `LOW`. A trip
with no exception never reaches this calculation, and a computed value of exactly zero still grades
`LOW`, so the zero path is never escalated.

The grade sets the trip's postures and its consequences together. A `LOW` grade leaves the safety
posture `NORMAL`; a `MEDIUM` grade moves it to `DISCREPANCY`; a `HIGH` grade moves it to `LOCKED`.
The instant the exception was stamped is retained on the trip as `exception_recorded_at`.
The platform opens a safety incident of category `NO_SHOW_UNVERIFIED` in `REPORTED` status with the
calculated grade as its reported `severity` and the trip's assigned driver attached, and raises a
student-absent alert against the trip; that alert takes the grade itself as its severity rather than
re-running the generic base-severity rule, so a `LOW`-graded absence raises a `LOW` alert and leaves
the posture the grade already set untouched. The overridden alert also takes its routing from the
grade: `notify_school` is set for a `STUDENT_ABSENT` alert at any severity, `notify_caregiver` when
the grade is `MEDIUM` or `HIGH`, and `notify_support_center` when the grade is `HIGH` under the
district's alerting switch. A `HIGH` grade additionally costs the driver a strike
on the spot; if that strike pushes the driver's strike count to the three-strike suspension threshold, the
driver's automatic suspension cascade runs and cancels every other `SCHEDULED` trip for that driver.
A district-wide rollup reading of the absence grade collapses the program weighting to a single flat
weight for every program type, which reduces the points to the block count multiplied by one plus
half the priority level multiplied by the penalty multiplier; a foster-care student at priority level
one with a two-block wait and an on-time dispatch grades `HIGH` at nine points under the base rule
and `MEDIUM` at three points under that flat reading.

Planned cancellations are separate from absence reports. A `DistrictAdmin` may cancel a trip that is
still `SCHEDULED` and in a `NORMAL` posture, optionally with a `reason`, which moves it to
`CANCELLED` and decrements the district's scheduled-trip total; a trip in any other movement state,
including a trip that has already reached `CANCELLED` or `COMPLETED`, is refused with
`ERR_INVALID_STATE` (HTTP 409) rather than the terminal-lockdown error, so this operation compresses
the two terminal states into the ordinary wrong-state refusal. Cancellation's two guards are settled
in that order — the movement state first and the safety posture second — so a trip that is neither
`SCHEDULED` nor in a `NORMAL` posture reports the wrong-state refusal rather than the posture one. Restoration is the compensating
action: a `DistrictAdmin`
may return a `CANCELLED` trip to `SCHEDULED`, but only while the parent request is still `SCHEDULED`
— otherwise the attempt is refused with `ERR_REQUEST_NOT_SCHEDULED` (HTTP 409) — only for a scheduled
date that has not passed, since restoring a trip into the past is refused with `ERR_TRIP_IN_PAST`
(HTTP 409) — and only while the trip's safety posture is `NORMAL`, refused otherwise with
`ERR_TRIP_DISCREPANCY_LOCK` (HTTP 409); a `CANCELLED` trip is the operation's only legal source and
is never itself read as a terminal probe, so a cancelled trip whose parent is not `SCHEDULED`
reports the parent-state refusal above rather than a terminal-lockdown error, while a trip that is
not `CANCELLED` is refused — a `COMPLETED` trip with `ERR_ALREADY_TERMINAL` (HTTP 409), any other
movement state with the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409). Restoration
clears the driver, the claiming user, the
acceptance instant, the pinned candidate, the arrival instant and any exception record, and raises the district's scheduled-trip total back by
one. The parent-state gate is the restoration's first check after its source state, ahead of the date
gate and the posture gate, so a cancelled trip whose parent series is suspended reports the parent
refusal even when its scheduled date has also passed. A trip cancelled because its student never boarded cannot be restored while the absence still
grades `MEDIUM` or `HIGH`, because that grade leaves the trip's posture away from `NORMAL`.

### 3.9. Trip Monitoring, Alerts and Incident Adjudication

Districts register geofences to watch their campuses and routes. A `DistrictAdmin` registers a
geofence with the owning `district_id`, a human `label`, a centre latitude and longitude in
`center_lat` and `center_lon`, and a `radius_miles`; the platform stamps the date the fence took
effect as `registered_on`. Containment is tested against a great-circle distance between the observed
point and the fence centre, measured to three decimal places of a mile, and the comparison is
inclusive at the boundary: a point exactly the fence's `radius_miles` from the centre counts as
inside. A point further than the radius counts as outside. The fence's centre is read as a signed
degree pair and its radius as a distance in miles; `registered_on` is a bare `YYYY-MM-DD` date drawn
from the fence's creation instant, and the fence carries no validation on the sign or magnitude of
its radius.

Monitoring observations are submitted against a trip, carrying an `observed_at` instant together with
`observed_lat` and `observed_lon`, by a `SupportCenterAgent` or a `PlatformAdmin`. One
`GeofenceCheck` is recorded for every `geofence_id` belonging to the trip's district, each holding
its `inside` verdict for that observed point against that particular circle and the observation
instant in `observed_at`; an outside check later carries the identifier of the breach alert it raised in `breach_alert_id`. The
observation is answered with the whole set of checks it produced, one per fence, in the district's
fence order, and it is one of the API's unpaged list answers: any `limit` or `offset` a caller
supplies is ignored, and the whole set is reported. An observation that falls
outside a fence while the trip is
`IN_TRANSIT` raises a geofence-breach alert against the trip; that alert then takes its severity from
the alert-severity rule below. Because the recording walks the district's fences in order, an
observation outside several fences raises one breach alert per outside fence, and each such alert
escalates itself against the breaches the trip has accumulated so far — so the first outside fence
raises the base-`LOW` alert and the second reads `MEDIUM` under the breach-history escalation even
though both were produced by the same observation. A check against a trip that is not `IN_TRANSIT`
records its verdict without raising anything, and the recording is available for a trip in any
movement state, including one already completed or cancelled. A pre-arrival proximity probe is also available as a separate reading
of the same observation, and it deliberately disagrees with the containment test at the boundary:
the proximity reading compares the distance against the fence's `radius_miles` multiplied by a
proximity factor of 1.1 using a strict less-than, so a point at exactly the proximity radius is
outside the proximity test while still being inside the fence itself. A point at 1.05 times the
radius is proximity-inside but fence-outside, and a point at exactly 1.1 times the radius is
proximity-outside while remaining fence-inside. Neither reading is derived from the other.

Continuous monitoring is driven by a support-desk sweep, an operation available to a
`SupportCenterAgent` or a `PlatformAdmin` that accepts a `trip_id` and synthesises delay and
geofence-breach alerts for trips whose window has closed without the corresponding handoff. The
synthesised alerts carry no source incident, because they are generated by monitoring rather than by
a report. The sweep is addressed to one trip and admits a `trip_id` alone, refusing any other member
with `ERR_INVALID_REQUEST` (HTTP 400); it answers with the swept trip object and is refused with the
ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409) for a trip that has already finished, so a
closed window on a `SCHEDULED`, `DRIVER_EN_ROUTE`, `AWAITING_STUDENT`, `STUDENT_ONBOARD` or
`IN_TRANSIT` trip raises one delay alert while a completed or cancelled trip raises nothing. Every alert created by the sweep — and every alert created by a handoff dispute or a
reported absence — takes its severity from one shared rule.

That severity rule reads three inputs: the alert's `alert_type`, the trip's accumulated count of
outside-the-fence observations, and the assigned driver's strike count at the moment of creation.
The base severity by type is `HIGH` for a `HANDOFF_DISPUTE` or a `STUDENT_ABSENT` alert, and `LOW`
for a `GEOFENCE_BREACH` or a `TRIP_DELAY` alert. The severity is then escalated on the trip's
accumulated breach history: two or more outside-fence observations raise the severity to `MEDIUM`.
It is then escalated on the driver's strike count: three or more strikes raise the severity to
`HIGH`, and one or two strikes raise a base-`LOW` severity to `MEDIUM`. The breach-history escalation
is applied first and the strike escalation second, and the second reads the result of the first
rather than the base: a strike count of one or two raises a base-`LOW` alert to `MEDIUM` only when
the breach escalation has not already lifted it past `LOW`, while three or more strikes raise the
alert to `HIGH` whatever the breach count did. A trip with no assigned
driver is scored as though its driver had no strikes, and a trip with no geofences scores no
breaches. One coordination rule caps the outcome: a trip that already carries an unresolved `HIGH`
alert never raises a second `HIGH` alert, and a new alert that would otherwise be `HIGH` is recorded
at `MEDIUM` and joins the existing incident rather than opening a parallel one. The coordination rule
is applied last, to the escalated severity, so it also caps an alert that only became `HIGH` through
the strike escalation; it inspects the trip's existing `OPEN` alerts at `HIGH` and leaves them
unmodified while the newcomer is recorded one grade lower.

Alert routing follows the severity and type. The `notify_caregiver` flag is set when the alert's
severity is `MEDIUM` or `HIGH`, so a caregiver is notified on any alert that is not merely low. The
`notify_school` flag is set when the alert is a `HANDOFF_DISPUTE` or a `STUDENT_ABSENT`, or when its
severity is `HIGH`, whichever applies. The `notify_support_center` flag is set when the alert is
`HIGH` and either the district has support-centre alerting enabled or the driver has three or more
strikes; it is also set — independently of that clause — when the alert notifies the school and is a
`HANDOFF_DISPUTE`. The support-centre clause is the alert's final severity read against the district's
switch and the driver's strikes, so the routing of an overridden absence alert follows the grade it
carries. That last clause is the integration clause: a handoff dispute that notifies the
school notifies the support centre even when the district has opted out of support-centre alerting,
and discounting it collapses support-centre routing on opt-out districts. Once an alert is created it
carries a `source_incident_id` that is null for monitoring-generated alerts and set when the alert
was spawned by a safety incident. Every alert also carries a `released_by_resolution` flag, which is
false when the alert was closed by a direct resolution call from the support desk and true when it
was closed instead by a sweep of the trip's open alerts. The `trip-alerts/{id}/resolve` operation
described below is the direct call embedded in that definition, so it always leaves the flag false;
the flag is set true only when an alert is closed as a side effect of an incident's review or void.
Creating any alert writes its new severity and posture into the trip in the same request that
returns the alert, so no separate write is needed to observe them.

An alert opens in `OPEN` status and is resolved by a `SupportCenterAgent` or a `PlatformAdmin`.
Resolving an open alert closes it; once a trip has no open alerts left and its posture is `LOCKED`,
the trip becomes eligible for a lock release. Resolving an alert that has already been closed is
refused with the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409), since an alert has no
terminal dimension of its own and the closed row is merely in the wrong state. The reverse path is
automatic: a resolved alert on a
trip whose movement state is neither `COMPLETED` nor `CANCELLED` returns to `OPEN` when a new alert
is synthesised for the same trip within the same monitoring window, which is how continuous
monitoring keeps a trip's alert set live until the trip actually finishes. When a new alert is
synthesised while an older alert on the same trip is still open, the older alert's severity is raised
to match the new one, and if the batch is subsequently closed together through an incident review,
the older alert is marked as released by resolution rather than directly resolved.

Safety incidents are the support desk's case records. An incident carries a `category` of
`NO_SHOW_UNVERIFIED`, `DRIVER_MISCONDUCT`, `VEHICLE_UNSAFE`, `HANDOFF_DISPUTE` or `STUDENT_DISTRESS`,
a reported `severity` of `LOW`, `MEDIUM` or `HIGH`, a free-text `reported_by_actor` and `summary`, an
`adjudication` of `DRIVER_AT_FAULT` or `NO_FAULT` that begins unset, an optional `resolution_note`,
a computed `student_impact_score`, and a `status` of `REPORTED`, `UNDER_REVIEW`, `RESOLVED` or
`VOIDED`. The incident's assigned driver is the driver attached to the trip at the time of the
report. Incidents open in `REPORTED`. An incident carries no stored strike tally: its at-fault
adjudication is what contributes to the driver's derived strike count, and the count is recomputed
from the incident rows whenever it is read or acted upon.

A `SupportCenterAgent` moves an incident from `REPORTED` to `UNDER_REVIEW` to open the review; the
move also resolves every open alert linked to that incident. Resolution is the adjudication gate, and
what it accepts depends on the source state. A `REPORTED` incident may be resolved only with a
`NO_FAULT` adjudication — an incident resolved at the reported stage with a driver-at-fault verdict
is refused with `ERR_ADJUDICATION_REQUIRED` (HTTP 422). An `UNDER_REVIEW` incident may be resolved
either at fault or not at fault. Any resolution requires a non-empty `resolution_note`, and a
resolution submitted without one is refused with `ERR_RESOLUTION_NOTE_REQUIRED` (HTTP 422); a
resolution submitted without any adjudication at all, or with an adjudication the source state
forbids, is refused with `ERR_ADJUDICATION_REQUIRED` (HTTP 422). The resolution body admits
`resolution_note` and `adjudication` and refuses any other member with `ERR_INVALID_REQUEST` (HTTP
400), and the note rule is evaluated ahead of the adjudication rule, so a body missing both reports
`ERR_RESOLUTION_NOTE_REQUIRED` (HTTP 422). A not-at-fault resolution of an
incident that is under review additionally requires the driver's strike count to be below the
suspension threshold, because otherwise the resolution would lift a suspension that this incident did
not cause; such an attempt is refused with `ERR_SUSPENSION_REQUIRES_FAULT` (HTTP 409). That
pre-check is skipped for a trip with no assigned driver, since there is no count to read. Every
resolution records the adjudication on the incident and recomputes its student impact score. The
resolution answers with the incident object, whose recomputed score reflects the resolved
multiplier, so the score reported on the resolution is lower than the score the incident carried
while it was still open. The `resolution_note` supplied is stored on the incident rather than merely
validated.

A driver-at-fault resolution cascades. The driver's incident strike count rises by one, and if the
recomputed count reaches the three-strike suspension threshold the driver is suspended. A driver
suspended by this route takes every one of their trips that is still `SCHEDULED` or `DRIVER_EN_ROUTE`
down with them: those trips are cancelled, their assigned driver, claiming user and pinned candidate
are all cleared, their safety posture is locked, and the district's scheduled-trip total is
decremented once per cancelled trip. This is the third hop of the strike cascade — an incident is
resolved, the driver's strike count rises, the driver is suspended, and the driver's unstarted trips
are cancelled — and it runs without any operator asking for the cancellations individually.

A resolved at-fault incident may be reopened by a `PlatformAdmin`, which returns it to
`UNDER_REVIEW`, clears its adjudication, and decrements the driver's strike count by one. Reopening
is the compensating action for a driver-at-fault resolution, and it is the only legal route back out
of a `RESOLVED` verdict: reopening an incident whose adjudication was not at fault is refused with
`ERR_INVALID_STATE` (HTTP 409). The `reason` member is accepted but optional and is not stored. If the decremented count now falls below the suspension threshold
and the driver is currently `SUSPENDED`, the driver returns to `ACTIVE`. A `REPORTED` or
`UNDER_REVIEW` incident may alternatively be voided by a `SupportCenterAgent`, which moves it to
`VOIDED` and resolves every alert linked to it. `VOIDED` is terminal for an incident, and every later
attempt to review, resolve, reopen or void a voided incident is refused with `ERR_ALREADY_TERMINAL`
(HTTP 409) rather than the ordinary wrong-state error. Voiding and review are separate gate families
from the terminal one: an incident already `RESOLVED` is refused both with the ordinary wrong-state
error `ERR_INVALID_STATE` (HTTP 409), reopening being the only way out of that state, while an
incident already `VOIDED` reports `ERR_ALREADY_TERMINAL` (HTTP 409) for all four operations. Both
review and void are also refused for an incident that has not yet reached the state they require
with the ordinary wrong-state error.

The student impact score is a clamped weighted figure computed on every incident state change. It
starts from a base of twenty-five points, multiplied by the incident's category weight — `2.0` for a
`DRIVER_MISCONDUCT` or a `VEHICLE_UNSAFE` incident, `1.5` for a `HANDOFF_DISPUTE`, and `1.0` for a
`NO_SHOW_UNVERIFIED` or a `STUDENT_DISTRESS` — multiplied by the incident's severity weight — `1.0`
for `LOW`, `2.0` for `MEDIUM` and `3.0` for `HIGH` — multiplied by one plus half the driver's
current strike count, and multiplied by `1.2` while the incident is not yet resolved and by `1.0`
once it is. The product is rounded half up to a whole number and then clamped into the range from
zero to one hundred inclusive, so the ceiling is exactly one hundred and never one hundred and one.
The clamp is applied after the rounding. The strike input is the driver's derived strike count as
`§3.9` defines it, but a trip whose own locked posture contributes a strike does not contribute it a
second time to the incident that same absence opened: the score an absence incident carries at
creation is computed from the driver's adjudications alone. The score is written when the incident is
opened and recomputed on every subsequent state change, and it is also recomputed on a plain read of
the incident, so the figure a caller reads is always current. Resolving or reopening an incident
recomputes every other incident belonging to the same driver as well, because the driver's strike
count has moved beneath them. Because the resolved multiplier is applied on resolution and
reapplied on reopening, an incident's score is not stable across a reopen. A summary reading of the
same score omits the open-incident multiplier entirely and scores every incident as though it were
already resolved, so an open misconduct incident at `HIGH` severity on a driver with one strike
scores one hundred under the base rule, clamped down from an unclamped value above the ceiling, and
ninety under that summary reading.

Driver strikes themselves are a derived count rather than a stored tally. A driver's strike count is
the number of that driver's safety incidents adjudicated at fault, plus the number of that driver's
trips whose exception is `RIDER_NOT_PRESENT` or `RIDER_REFUSED_BOARDING` and whose safety posture is
`LOCKED`. That second term is why a `HIGH` absence costs an on-the-spot strike: the absence incident
opened by the exception report carries no adjudication until a support agent resolves it, and the
trip itself — locked by the `HIGH` grade — is what contributes the strike immediately.

Recovering a degraded trip posture is a two-stage affair. A `SupportCenterAgent` or a `PlatformAdmin`
may clear a trip's discrepancy, which returns a `DISCREPANCY` trip to `NORMAL` and moves a `LOCKED`
trip only as far as `DISCREPANCY`; clearing requires the trip to be `COMPLETED` when it is coming
from `DISCREPANCY`, refused otherwise with `ERR_INVALID_STATE` (HTTP 409), and requires every alert on
the trip to be resolved when it is coming from `LOCKED`, refused otherwise with `ERR_OPEN_ALERTS`
(HTTP 409). Clearing also clears the trip's exception code and the instant it was recorded when it
takes a `DISCREPANCY` trip to `NORMAL`, but deliberately does not do so on the `LOCKED`→`DISCREPANCY`
hop — the exception record survives that hop, which is what keeps a `MEDIUM` or `HIGH` absence grade
blocking the trip's restoration — and it
deliberately does not recompute the trip's billable ride units, so the unit penalised by the failed
handoff is not refunded. A trip whose posture is already `NORMAL` is refused with the ordinary
wrong-state error `ERR_INVALID_STATE` (HTTP 409), and so is a `LOCKED` trip that still carries an
open alert, that refusal being the `ERR_OPEN_ALERTS` (HTTP 409) named above. A `PlatformAdmin` may release a trip lock, returning a trip `LOCKED` in
that dimension to `NORMAL`, but only when every alert on that trip is already resolved; the release
is likewise refused
with `ERR_OPEN_ALERTS` (HTTP 409) while any alert remains open, and it likewise carries a trip
already at `DISCREPANCY` on to `NORMAL`, completing the reverse loop. The release's blast radius is
wider than the recovery hop's: it writes the trip's posture to `NORMAL` from either degraded state
without touching the exception record, so a trip the discrepancy hop had carried as far as
`DISCREPANCY` reaches `NORMAL` through it with its exception code and its recorded instant still in
place.

### 3.10. Trip Pricing, Statements and Settlement

Every completed trip is priced twice over its life, once as a quote and once as a settlement, and the
two readings use different distances on purpose. The quote is priced from the distance fixed when the
trip was scheduled, so the number is knowable before the vehicle moves; it multiplies the trip's
billable ride units by the covering contract's `per_ride_rate_cents` and rounds half up to a whole
cent, multiplies the trip's `planned_miles` by the contract's `per_mile_rate_cents` and rounds half
up to a whole cent, sums the two, and then applies the trip's posture: a trip whose safety posture is
`DISCREPANCY` is reduced by one quarter of the summed charge, rounded half up to the cent, and a trip
whose posture is `LOCKED` is priced at zero. The quote deliberately ignores two things — the
contract's per-trip minimum floor entirely, and the trip's actual odometer miles — so a trip quoted
at zero planned miles reads zero even though its contract carries an eight-hundred-cent floor. The
quote exists for every trip regardless of movement state, including cancelled trips, because it is
the record of what was promised at scheduling time, and it is recomputed whenever a trip mutates
while it has not yet completed and whenever the covering contract's rates are edited.

The settlement is priced from the actual odometer distance recorded at completion rather than the
planned distance. It multiplies the trip's billable ride units by the contract's per-ride rate and
rounds half up to a whole cent, multiplies the trip's `billable_miles` by the contract's per-mile
rate and rounds half up to a whole cent, and sums the two. A trip in a `DISCREPANCY` posture has one
quarter of that sum, rounded half up to the cent, deducted; a trip in a `LOCKED` posture instead has
half its charge deducted, rounded half up to the cent, leaving half the summed charge. The contract's
per-trip `minimum_billable_cents` floor is then applied last, so the settled amount is never less
than the floor. The floor is applied here and only here, which is exactly why a completed trip
settles at the contract floor while its quote for otherwise identical inputs reads the bare per-ride
rate. Every trip with a movement state of `COMPLETED` settles under this rule, including trips whose
exception code is set; a cancelled trip settles at zero.

A statement is computed by a `DistrictAdmin` or a `PlatformAdmin` running a billing run for a district
over a `period_key` bounded by a `period_start` and a `period_end`, both inclusive. The run is
protected by optimistic concurrency: the payload carries `expected_district_version`, and a value
that no longer matches the district's current `version` is rejected with `ERR_STALE_VERSION` (HTTP
412), which is the guard that makes a re-run against unobserved data rejectable even though re-running
a billing run is otherwise legitimate. A statement covers the trips whose movement state is
`COMPLETED`, whose `billing_period_key` equals the statement's `period_key`, and whose
`scheduled_date` falls inside the period bounds inclusive. The statement begins in `OPEN`. The run's
body admits `expected_district_version`, `period_key`, `period_start` and `period_end` and refuses any
other member with `ERR_INVALID_REQUEST` (HTTP 400), and the stale-version guard is evaluated first. A
district that holds no `ACTIVE` contract after the automatic expiry sweep has no rates to bill under,
and the run is refused with `ERR_FORBIDDEN` (HTTP 403) rather than being answered with an empty
statement; the sweep that produces that answer has already moved the lapsed contract to `EXPIRED` and
the district to `SUSPENDED`. A run that does find a covering contract opens its statement with `201
Created`, and the reservation of the applied credit advances the district's `version` even when the
credit reserved is zero.

The statement total is computed in a pinned order, because the credit term depends on a total that
itself depends on the credit term. First each included trip's settlement charge is computed by the
rule above. Second, those per-trip charges are summed, accumulated in scheduled-date ascending order
and, within the same date, by completion instant ascending and then by creation instant ascending, to
produce a gross total in cents. Third, the district's available credit is read from its
`credit_balance_cents`. Fourth, the credit applied to this statement is the smaller of that available
credit and the floor of one half of the gross total. Fifth, the statement's `total_amount_cents` is
the gross total less the applied credit. The fourth step is evaluated against the gross total and
never against the post-credit net, so the sequence remains well defined; evaluating the credit cap
against the net instead yields a smaller credit and a different total for identical inputs. The cap
is half the gross rounded half up to the cent, so a gross of twelve thousand three hundred and
twenty cents caps the credit at six thousand one hundred and sixty. The
statement's `total_ride_units` and `total_miles` are plain sums over the included trips and do not
feed the total; the mileage total is a numeric sum that keeps the fractional part of the odometer
readings it adds. The applied credit is reserved out of the district's credit pool as soon as the
statement is computed, so `credit_balance_cents` falls by the applied amount at computation time
rather than at issue time.

A computed statement may be issued by a `DistrictAdmin` or `PlatformAdmin`, which moves it from
`OPEN` to `ISSUED` and stamps the issue instant into `issued_at`. Issuing requires the statement to be in `OPEN`,
refused otherwise with `ERR_INVALID_STATE` (HTTP 409), requires the statement's `total_amount_cents`
to be greater than zero — an empty statement is refused with `ERR_EMPTY_STATEMENT` (HTTP 409) — and
requires the statement's `period_key` to match the billed trips' `billing_period_key` exactly, refused
otherwise with `ERR_PERIOD_MISMATCH` (HTTP 409). The period-key check is evaluated across every
completed trip for the district that falls inside the statement's own bounds, whether or not that
trip's `billing_period_key` matches the statement's: the mismatch is reported when even one trip in
the window carries a different key, and the empty-statement check precedes it. Issuing adds the
statement's total to the district's
`outstanding_balance_cents`. Once that outstanding balance is strictly greater than the district's
overdue threshold — an account-level figure of five hundred thousand cents (500,000), which is the
threshold the platform applies, the same value for every district rather than a per-district setting —
the district's `account_status` is set to `SUSPENDED`, which blocks any further
statement issuance: an issue attempt against a suspended district, or against a district whose
outstanding balance is over that threshold, is refused with `ERR_DISTRICT_OVER_LIMIT` (HTTP 402). The
balance-over-threshold arm is tested with a strict comparison, so a balance of exactly five hundred
thousand cents still issues, and the issuance gate is evaluated after the statement's own empty and
period-key checks. An
issued statement may be paid through a payment record carrying `paid_amount_cents`, moving it to
`PAID` and reducing the district's outstanding balance by the statement's `total_amount_cents`; the
recorded payment amount is accepted but does not change that arithmetic, so a partial payment clears
the whole outstanding amount. `PAID` is terminal,
and a second payment or any issue, void or payment against a paid or voided statement is refused with
`ERR_ALREADY_TERMINAL` (HTTP 409) rather than the ordinary wrong-state error. A payment attempted
against an `OPEN` statement reports the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409).

Voiding is the compensating action for issuing. Voiding an `ISSUED` statement moves it to `VOIDED`,
reduces the district's outstanding balance by the statement's `total_amount_cents`, and returns to the credit pool
exactly the `applied_credit_cents` that this statement had consumed — not the statement's total. Returning the total
instead would drift the district's retained credit, so the platform is careful to return only the
applied amount; the sum of the district's outstanding balance and its credit pool returns exactly to
the value it held before the statement was issued. A statement that is still `OPEN` is voided
automatically and without a client request when the district's active contract transitions to
`SUSPENDED`; that automatic voiding returns the statement's applied credit to the pool in the same
way. The automatic voiding is a side effect of the suspension rather than a statement operation, so
it does not touch the district's outstanding balance and writes no issue or void instant; the
statement simply reads `VOIDED` from then on and can no longer be issued, paid or voided a second
time. Contract expiry is likewise automatic during a billing run: when a contract's `through_date` has
passed the logical clock date, the run expires the contract and suspends the district's account, and
an expired contract can never be reactivated, suspended again or activated a second time, because
every such attempt against a terminal contract is refused with `ERR_ALREADY_TERMINAL` (HTTP 409). The
expiry sweep runs across every contract the district holds, so a district whose term has lapsed
reports both the expiries and the suspended account no matter which statement period the run names.
Contract expiry during a billing run is likewise a sweep rather than a statement operation: it writes
no issue instant and no balance movement, and it is not reported through an error identifier but
simply leaves its artefacts — the expired contract and the suspended account — readable afterwards.
The
rate provenance of a statement — the contract whose rates and floor were applied — is stamped as a
`contract_id` on the statement, and remains resolvable through the filtered list form of the
billing-statement collection after the contract itself is no longer reachable. Like the period key it
stamps, that provenance is captured at the moment the run installs the statement and is never
rewritten afterwards: a later edit to the covering contract's rates leaves both the statement and its
stamp exactly as they were computed. The filtered list form reads its `contract_id`, `district_id` and
`status` filters from the query string and applies them together, and it is the only read that
resolves a statement by its contract stamp rather than by traversal from the contract itself.

### 3.11. Counting Discipline Across Aggregates

Several derived counts recur across the workflows above, and each has a fixed inclusion set that the
whole API honours. The student's active request count covers only ride requests in `SUBMITTED` or
`APPROVED` and never counts trip rows. A district's `trips_scheduled_total` counts the district's
live scheduled load — every trip whose movement state is not `CANCELLED` — so a cancellation
decrements it and a restoration increments it, and a series that is suspended and then resumed reads
the same total as an untouched series while holding twice as many trip rows. A driver's incident
strike count is the at-fault adjudication count plus the count of that driver's `LOCKED`
non-completion trips, as described in §3.9. A statement's ride-unit and mileage totals are plain
sums over its included trips. And the district's `trips_scheduled_total` is the one figure that both
individual trip operations and whole-series cascades move, so any cascade that cancels trips adjusts
it once per cancelled trip rather than once per cascade.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection,
return `201 Created`. Operations that modify an existing resource, including operations that drive a
state transition on an existing resource, return `200 OK`. The table below lists each operation with
the roles permitted to call it; request and response bodies, side effects and the conditions that
guard each call are described in Sections 2 and 3.

The table is the surface the platform exposes and nothing beyond it: a path not listed, or a listed
path called with a method it does not declare, is refused as not found or as a malformed request
rather than being answered with the nearest declared operation. The roles column is the minimum each
operation admits; `PlatformAdmin` reaches every operation that admits `DistrictAdmin` or
`SupportCenterAgent` without being listed beside them, and the operations whose rows name
`PlatformAdmin` alone are reachable by no other role. The `Driver`-scoped operations are the only
ones that read the acting identity as a foreign key, so a `Driver` caller must carry the identifier
of a driver the platform has actually onboarded, while the other four roles carry opaque operator
identifiers that are recorded where a workflow stamps them and never compared to an entity's `id`.
The surface includes the three test-driving operations under `/_`, which exist so that operational
time, monitoring sweeps and district calendar events can be driven deterministically; they are listed
here because they are part of the contract rather than omitted from it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/student-rides/districts` | Self-register a District | Anonymous |
| GET | `/student-rides/districts/{id}` | Get a District | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/riders` | List a District's Riders | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/ride-requests` | List a District's RideRequests | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/contracts` | List a District's Contracts | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/trips` | List a District's Trips | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/billing-statements` | List a District's BillingStatements | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/districts/{id}/geofences` | List a District's Geofences | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/districts/{id}/billing-runs` | Compute a statement from the district's completed trips | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/districts/{id}/supply-plans` | Read the driver supply plan for a horizon | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/districts/{id}/driver-availability-blocks` | Block a driver's availability on a route segment | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/districts/{id}/driver-supply-runs` | Re-derive the covered-driver roster for a horizon | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/districts/{id}/credit-adjustments` | Apply a service-credit adjustment to the district | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/riders` | Register a Rider | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/riders` | List the Riders the platform holds | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/drivers` | List the Drivers the platform holds | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/riders/{id}` | Get a Rider (masked for the Driver role) | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| PUT | `/student-rides/riders/{id}` | Update Rider placement details | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/riders/{id}/ride-requests` | List a Rider's RideRequests | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/riders/{id}/trips` | List a Rider's Trips | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/drivers` | Onboard a Driver | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/drivers/{id}` | Get a Driver | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| POST | `/student-rides/drivers/{id}/background-checks` | Open a background check and enter BACKGROUND_CHECK | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/drivers/{id}/background-checks` | List a Driver's BackgroundChecks | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/drivers/{id}/inspections` | Record a vehicle inspection and enter INSPECTION | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/drivers/{id}/inspections` | List a Driver's VehicleInspections | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/drivers/{id}/trips` | List a Driver's Trips | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| GET | `/student-rides/drivers/{id}/safety-incidents` | List a Driver's SafetyIncidents | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/drivers/{id}/reactivate` | Reactivate a suspended Driver | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/drivers/{id}/deactivate` | Deactivate a Driver | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/background-checks/{id}/clear` | Mark a background check CLEARED | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/background-checks/{id}/fail` | Mark a background check FAILED, including revocation | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/vehicle-inspections/{id}/attest` | Attest a pending inspection as PASSED | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/vehicle-inspections/{id}/reject` | Reject an inspection | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/contracts` | Draft a Contract for a District | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/contracts/{id}` | Get a Contract | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/contracts/{id}/activate` | Activate a Contract | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/contracts/{id}/suspend` | Suspend a Contract and freeze billing | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/contracts/{id}/reactivate` | Reactivate a suspended Contract | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests` | Open a RideRequest for a student | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/ride-requests/{id}` | Get a RideRequest | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/ride-requests/{id}/trips` | List a RideRequest's Trips | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/ride-requests/{id}/submit` | Submit a draft request for review | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/request-revision` | Return a submitted request for revision | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/resubmit` | Resubmit a request after revision | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/approve` | Approve a submitted request | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/reject` | Reject a request | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/schedule` | Schedule a request and generate trips | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/suspend-series` | Suspend a recurring series | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/resume-series` | Resume a suspended recurring series | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/ride-requests/{id}/cancel` | Cancel a draft or suspended-series request | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/trips` | Create a single-date Trip against a scheduled request | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/trips/{id}` | Get a Trip | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| GET | `/student-rides/trips/{id}/alerts` | List a Trip's TripAlerts | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| GET | `/student-rides/trips/{id}/handoffs` | List a Trip's HandoffVerifications | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| GET | `/student-rides/trips/{id}/safety-incidents` | List a Trip's SafetyIncidents | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| GET | `/student-rides/trips/{id}/geofence-checks` | List a Trip's GeofenceChecks | DistrictAdmin, PlatformAdmin, SupportCenterAgent, Driver |
| POST | `/student-rides/trips/{id}/dispatch-candidate` | Pin the eligible driver for a trip | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/trips/{id}/accept` | Driver accepts the pinned dispatch | Driver, DistrictAdmin |
| POST | `/student-rides/trips/{id}/arrive` | Driver arrives at the pickup point | Driver |
| POST | `/student-rides/trips/{id}/depart` | Driver departs with the student on board | Driver |
| POST | `/student-rides/trips/{id}/handoffs` | Record a pickup or dropoff handoff verification | Driver |
| POST | `/student-rides/trips/{id}/exceptions` | Report a student not present or refusing to board | Driver |
| POST | `/student-rides/trips/{id}/cancel` | Cancel a scheduled Trip | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/trips/{id}/restore` | Restore a cancelled Trip | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/trips/{id}/resolve-discrepancy` | Clear a trip's discrepancy posture | SupportCenterAgent, PlatformAdmin |
| POST | `/student-rides/trips/{id}/release-lock` | Release a locked Trip | PlatformAdmin |
| POST | `/student-rides/trips/{id}/geofence-checks` | Check a trip's position against the district's geofences | SupportCenterAgent, PlatformAdmin |
| GET | `/student-rides/safety-incidents/{id}` | Get a SafetyIncident | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/safety-incidents/{id}/alerts` | List a SafetyIncident's linked TripAlerts | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/safety-incidents/{id}/review` | Move an incident under review | SupportCenterAgent, PlatformAdmin |
| POST | `/student-rides/safety-incidents/{id}/resolve` | Resolve an incident with an adjudication | SupportCenterAgent, PlatformAdmin |
| POST | `/student-rides/safety-incidents/{id}/reopen` | Reopen an adjudicated incident | PlatformAdmin |
| POST | `/student-rides/safety-incidents/{id}/void` | Void a reported or under-review incident | SupportCenterAgent, PlatformAdmin |
| POST | `/student-rides/trip-alerts/{id}/resolve` | Resolve an open TripAlert | SupportCenterAgent, PlatformAdmin |
| POST | `/student-rides/geofences` | Register a district Geofence | DistrictAdmin, PlatformAdmin |
| GET | `/student-rides/geofences/{id}` | Get a Geofence | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/geofences/{id}/checks` | List a Geofence's GeofenceChecks | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| GET | `/student-rides/billing-statements` | List BillingStatements, optionally filtered | DistrictAdmin, PlatformAdmin, SupportCenterAgent |
| POST | `/student-rides/billing-statements/{id}/issue` | Issue a computed statement | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/billing-statements/{id}/approve-payment` | Record payment of an issued statement | DistrictAdmin, PlatformAdmin |
| POST | `/student-rides/billing-statements/{id}/void` | Void an issued statement | DistrictAdmin, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_support-center/monitor-sweep` | Run a monitoring sweep for a trip | SupportCenterAgent, PlatformAdmin |
| POST | `/_events/emit` | Emit a system event that fans out to recurring series | DistrictAdmin, PlatformAdmin |

The platform additionally answers `GET /` with a health object confirming the server is up; that
endpoint carries no versioned prefix, takes no credentials, and is the only path outside
`/student-rides` and `/_` the API exposes.

## 5. Error Code Catalogue

The table below lists every machine-readable error identifier this API may return, with the HTTP
status code it carries. The conditions that trigger each identifier are described where the
corresponding workflow is specified, in Sections 2 and 3. The identifiers that share a status code are
told apart by the workflow that raised them, not by the code, and the code is never the whole of an
error's meaning: a caller told `ERR_INVALID_STATE` and a caller told `ERR_ALREADY_TERMINAL` both read
`409`, and the distinction between a merely wrong state and a resource already past its terminal
state is carried by the identifier alone. A single identifier, `ERR_STALE_VERSION`, spans the `412`
band, and the `422` band is the input-shape and expiry refusals raised by the workflows of §3.1,
§3.3, §3.4 and §3.9; no other band carries more than the identifiers listed against it here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_SELECTED` | 403 |
| `ERR_NOT_TRIP_DRIVER` | 403 |
| `ERR_HANDOFF_NOT_AUTHORIZED` | 403 |
| `ERR_DISTRICT_OVER_LIMIT` | 402 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_TRIP_DISCREPANCY_LOCK` | 409 |
| `ERR_TRIP_ALREADY_CLAIMED` | 409 |
| `ERR_DRIVER_INELIGIBLE` | 409 |
| `ERR_DRIVER_ON_TRIP` | 409 |
| `ERR_CLEARANCE_INCOMPLETE` | 409 |
| `ERR_DUPLICATE_CLEARANCE` | 409 |
| `ERR_DRIVER_WINDOW_OVERLAP` | 409 |
| `ERR_RIDER_WINDOW_OVERLAP` | 409 |
| `ERR_NO_ELIGIBLE_DRIVER` | 409 |
| `ERR_NO_SCHOOL_DAYS_IN_RANGE` | 409 |
| `ERR_NOT_RECURRING` | 409 |
| `ERR_TRIP_IN_PROGRESS` | 409 |
| `ERR_OUTSIDE_SCHOOL_TERM` | 409 |
| `ERR_SERIES_ENDED` | 409 |
| `ERR_ALREADY_SCHEDULED` | 409 |
| `ERR_REQUEST_NOT_SCHEDULED` | 409 |
| `ERR_TRIP_IN_PAST` | 409 |
| `ERR_RIDER_INACTIVE` | 409 |
| `ERR_HANDOFF_ALREADY_ATTEMPTED` | 409 |
| `ERR_WAIT_TIME_NOT_MET` | 409 |
| `ERR_INCIDENT_ALREADY_REPORTED` | 409 |
| `ERR_OPEN_ALERTS` | 409 |
| `ERR_SUSPENSION_REQUIRES_FAULT` | 409 |
| `ERR_EMPTY_STATEMENT` | 409 |
| `ERR_PERIOD_MISMATCH` | 409 |
| `ERR_CONTRACT_OVERLAP` | 409 |
| `ERR_CONTRACT_TERM_ENDED` | 409 |
| `ERR_CAREGIVER_EXPERIENCE_SHORT` | 422 |
| `ERR_CLEARANCE_EXPIRED` | 422 |
| `ERR_INSPECTION_SEAT_COUNT` | 422 |
| `ERR_WINDOW_TOO_WIDE` | 422 |
| `ERR_LEAD_TIME_TOO_SHORT` | 422 |
| `ERR_ADJUDICATION_REQUIRED` | 422 |
| `ERR_RESOLUTION_NOTE_REQUIRED` | 422 |
| `ERR_CONTRACT_DATE_ORDER` | 422 |
| `ERR_STALE_VERSION` | 412 |