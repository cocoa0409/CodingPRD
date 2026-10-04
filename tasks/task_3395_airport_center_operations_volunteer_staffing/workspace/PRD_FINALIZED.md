# Airport Center Operations & Volunteer Staffing API — Product Requirements Document

## 1. Introduction

Airport centers run on an unusual mix of constraints: donated space inside secured terminals and installations, a volunteer workforce that must be vetted and scheduled continuously, guests whose eligibility rests on documents that expire, donated food and supplies that must rotate before they spoil, and donor money that must be accounted for center by center. This document specifies the API for operating such a center network — the system of record for site agreements covering space, utilities, and access terms; for volunteer recruitment, background screening, and shift staffing; for guest check-in and center services such as sleeping areas, showers, connectivity, and family rooms; for deployment, homecoming, and entertainment-tour events; and for grant-funded cost accountability.

The design is posture-driven: each center derives an operating posture from the health of its site agreement and the day's confirmed staffing, and that posture gates what guests and volunteers may do. A single logical clock governs every temporal rule so that eligibility windows, renewal windows, expiries, and quotas are deterministic. Section 2 fixes the global contracts — identity, response envelopes, pagination, concurrency control, precision, and the ordering in which checks run; Section 3 walks each business workflow in narrative form; Sections 4 and 5 tabulate the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the target endpoint — or that violates an entity-backed ownership scope — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist. `PlatformAdmin` is the headquarters operator: it creates centers, drafts, activates, and renews site agreements, records funding grants, approves entertainment-tour security, and drives the logical clock. `CenterManager` is the center operations lead: it runs the operations checkpoint, claims and decides background screenings, builds shifts and assignments, checks guests in, books services, intakes and consumes donation lots, manages events, and posts expenses. `Volunteer` is a cleared center volunteer acting on its own assignments. `Guest` is an eligible center guest booking services for itself. `Anonymous` covers public intake — volunteer applications and guest registration; even these two endpoints require both headers, with `X-User-Role` set to the literal role name `Anonymous`.

Identity semantics differ by role. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a volunteer compare the resource's `volunteer_id` field to `X-User-ID` — a volunteer may confirm or cancel only its own assignments and sees only its own assignment listings. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting Guest; a guest booking a service must pass its own `id` as the booking's `guest_id`, and guest-scoped listings are confined to the caller's own `id`. When `X-User-Role` is `PlatformAdmin`, `CenterManager`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `claimed_by_user_id` or `decided_by_user_id` on a background screening — but never compares it to any entity's `id`.

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

List endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10 and must be between 1 and 100 inclusive; `offset` defaults to 0. Every list is sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` so clients can page deterministically through a collection.

### 2.4. The Logical Clock

The server maintains a single logical UTC clock, and every temporal rule in this document — date comparisons, expiry checks, renewal windows, quota windows, and sweep eligibility — reads that clock rather than wall-clock time. A `PlatformAdmin`-only, test-driving capability sets the clock by accepting a `to_iso8601` timestamp and returns the resulting `current_utc`. Before any such call, the clock starts at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time afterwards. Calendar-date fields are written `YYYY-MM-DD` and compared at day granularity against the clock's current date; timestamps are ISO 8601 UTC.

### 2.5. Common Resource Properties and Optimistic Concurrency

Every resource carries four server-maintained properties alongside its domain fields: `id`, a server-minted UUID in canonical hyphenated string form (e.g., `550e8400-e29b-41d4-a716-446655440000`) with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments by exactly one on every mutation of the resource. `created_at` never changes after creation; `updated_at` refreshes on the same mutations that bump `version`.

Three write operations are optimistic-concurrency guarded and require a non-optional expected-version field in the request body. Opening a background screening for a volunteer requires `expected_volunteer_version` matching that volunteer's current `version`, because a new screening legitimately supersedes the client's view of the volunteer's vetting state. Activating a site agreement requires `expected_center_version` matching the center's current `version`, because activation supersedes any currently active agreement of the same center. Posting a center expense likewise requires `expected_center_version`, because the grant-waterfall allocation depends on funding state the client may not have observed. In all three cases, if the parent entity's `version` has advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is applied. Endpoints not named here do not accept any version field.

### 2.6. Center Posture as a Derived Gate

A center's `posture` is computed — never written directly — and takes one of three values: `CLOSED`, `RESTRICTED`, or `OPEN`. The derivation uses the confirmed-only coverage variant: `coverage_ratio` is the number of `CONFIRMED` shift assignments whose shift's `start_at` falls on the current clock date, divided by the center's `required_daily_confirmed_assignments`; assignments in `ASSIGNED`, `CANCELLED`, `NO_SHOW`, or `COMPLETED` never count toward it. The ratio is kept as an exact rational value and compared with a greater-than-or-equal threshold. If the center has no `ACTIVE` site agreement, posture is `CLOSED`. Otherwise, when `coverage_ratio` is at least 0.75 the posture is `OPEN`, and below that threshold it is `RESTRICTED`.

Posture is recomputed whenever its inputs move: agreement activation, expiry, or supersession; assignment confirm, cancel, no-show, or the suspension cascade; and every operations checkpoint. When the recomputed value is stored, the center's `version` increments by one and `updated_at` refreshes. Posture then gates guest-facing operations: check-ins and service bookings are rejected with `ERR_CENTER_CLOSED` while a center is `CLOSED`, and a `RESTRICTED` center narrows which services may be booked (§3.5). A freshly created center starts `CLOSED` with `current_occupancy` 0, `coverage_ratio` 0, an empty `expense_ledger`, `ops_run_count` 0, and `active_agreement_id` null. The current posture is always visible on the center resource, together with `current_occupancy`, `coverage_ratio`, `active_agreement_id`, `expense_ledger`, and `ops_run_count`.

### 2.7. Validation Pipeline and Error Ordering

Incoming requests pass through a fixed pipeline of checks, and an earlier failure always masks every later one. First, authentication: both identity headers must be present and the role declared, else `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted on the endpoint and any entity-backed ownership scope honored, else `ERR_FORBIDDEN`. Third, request shape: required fields present, enums in range, dates well-formed, `end_at` later than `start_at`, quantities at least 1, a renewal's new end date later than the current one, and creation-time dates not in the past where this document requires it — else `ERR_VALIDATION`. Fourth, existence: path resources are validated left to right — the center first, then the child within it — and a missing resource yields `ERR_NOT_FOUND`. Fifth, optimistic concurrency: a stale expected-version field yields `ERR_STALE_VERSION`.

Only then do business rules run, in this relative order: state admissibility — the target entity must be in a from-state its transition allows, covering `ERR_INVALID_STATE`, `ERR_CENTER_CLOSED`, `ERR_ALREADY_CHECKED_IN`, `ERR_SCREENING_ALREADY_OPEN`, and `ERR_RENEWAL_WINDOW_NOT_OPEN`; then safety and compliance — `ERR_GUEST_INELIGIBLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_SECURITY_LEVEL_INSUFFICIENT`, `ERR_TALENT_AGREEMENT_UNSIGNED`, and `ERR_SEGREGATION_OF_DUTIES`; then temporal conflicts — `ERR_SHIFT_OVERLAP`, `ERR_BOOKING_OVERLAP`, and `ERR_EVENT_OVERLAP`; then capacity, quota, and selection — `ERR_CENTER_AT_CAPACITY`, `ERR_SHIFT_FULL`, `ERR_BOOKING_DURATION_INVALID`, `ERR_QUOTA_EXCEEDED`, `ERR_FEFO_VIOLATION`, `ERR_LOT_EXPIRED`, `ERR_INSUFFICIENT_QUANTITY`, and `ERR_STAFFING_SHORTFALL`; and finally fiscal sufficiency — `ERR_BUDGET_EXCEEDED`. A state error therefore surfaces before an overlap error, and an overlap error before a capacity one.

### 2.8. Precision, Rounding, and Money

All monetary amounts are integer cents; no monetary value is ever stored or returned as a fractional quantity. Where a monetary computation requires rounding — the per-lot partner match and the two cost-per-visit figures — the rule is round half up to the nearest integer cent. The grant waterfall allocates integer cents with no rounding at all. Coverage ratios are kept exact and compared without rounding. Service durations are measured in whole minutes, and overlap decisions resolve at minute granularity. Calendar-date comparisons (`expiry_date`, `spend_by_date`, `verification_expires_on`, agreement start and end dates) resolve at day granularity against the logical clock's current date.

### 2.9. The Operations Checkpoint

Each center is swept by an operations checkpoint that a `CenterManager` triggers for one center at a time. A single run performs, for that center: expiry of `CLEARED` screenings whose `expires_at` has been reached, with the linked volunteer's lapse to `INACTIVE` when no unexpired cleared screening remains; renewal-window flagging and expiry of site agreements; discarding of expired donation lots; automatic no-show marking of assignments still `CONFIRMED` after their shift has ended; day-end check-out of stale visits; completion of elapsed service bookings; execution of elapsed confirmed events and cancellation of stale unconfirmed ones; and expiry of funding grants past their spend-by date. After the sweeps, the checkpoint recomputes the center's coverage and posture, increments the center's `ops_run_count` by exactly one, and increments the center's `version` by one; the updated center is returned. `ops_run_count` is monotone — it counts how many checkpoints the center has ever run. The per-entity details of each sweep live with their workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Center and Its Site Agreement

A `PlatformAdmin` opens a new center by supplying its `name`, its `airport_code` (the IATA airport or installation code, such as LAX), an `occupancy_cap` of at least 1 (the maximum number of simultaneously checked-in guests), and a `required_daily_confirmed_assignments` of at least 1 (the confirmed assignment slots on the current day's shifts that constitute full coverage). The center is born `CLOSED`: no posture gate opens until a site agreement is activated.

Site agreements are drafted against a center with `facility_space_sqft` greater than 0, a `utilities_included` flag recording whether the airport covers utilities, free-text `access_terms` describing arrangements such as badge rules, a `security_level` from 1 to 5 inclusive, and a `start_date` that must not be later than `end_date` (`ERR_VALIDATION` otherwise). A draft agreement sits in `SUBMITTED`. Activation is a guarded, superseding act: the caller presents `expected_center_version`, and if the center's `version` has advanced since that reading the activation is rejected with `ERR_STALE_VERSION`; the date ordering is re-verified at this point as well, so a `start_date` later than `end_date` is `ERR_VALIDATION`. On success, any other `ACTIVE` agreement of the same center cascades to `TERMINATED`, the center's `active_agreement_id` is set to the newly activated agreement, posture is recomputed against current coverage, and the center's `version` increments by one. Activating an agreement that is not `SUBMITTED` is a plain `ERR_INVALID_STATE`.

Agreements age under the operations checkpoint. When the number of days from the current clock date to `end_date` falls between 0 and 60 inclusive, an `ACTIVE` agreement is flagged `RENEWAL_DUE`. Renewal is open only in that window: a `PlatformAdmin` presents a `new_end_date` strictly later than the current `end_date` — anything else is `ERR_VALIDATION` — and the agreement returns to `ACTIVE` with its `end_date` extended and the center's posture recomputed. Attempting renewal on an agreement that is not `RENEWAL_DUE`, including one still plainly inside its active term, is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. Once the current date passes `end_date`, the checkpoint moves an `ACTIVE` or `RENEWAL_DUE` agreement to `EXPIRED`, clears the center's `active_agreement_id` when it pointed at the expired agreement, and recomputes posture — which, with no active successor, drops the center to `CLOSED`. `EXPIRED` and `TERMINATED` are terminal states.

### 3.2. Recruiting, Screening, and the Standing of Volunteers

Anyone may apply: the public intake records a volunteer's `full_name`, `email`, and `home_center_id`, and the application rests in `APPLIED`, with `no_show_strikes` and `total_hours` both starting at 0. The roster can be listed with an optional `home_center_id` filter. Vetting begins when a `CenterManager` opens a background screening against a volunteer in `APPLIED`, `INACTIVE`, or `SUSPENDED`, presenting `expected_volunteer_version`; a stale version is rejected with `ERR_STALE_VERSION`. Opening the screening moves the volunteer to `SCREENING` and increments the volunteer's `version`. A volunteer who already has an open screening — one `SUBMITTED` or `IN_REVIEW`, which is exactly the `SCREENING` state — cannot be re-opened: the attempt fails with `ERR_SCREENING_ALREADY_OPEN`.

Review is a two-person protocol. A `CenterManager` first claims a `SUBMITTED` screening, moving it to `IN_REVIEW` and recording the caller's `X-User-ID` in `claimed_by_user_id`; claiming a screening that is not `SUBMITTED` is a plain `ERR_INVALID_STATE`. A decision is then taken on the `IN_REVIEW` screening by supplying a `verdict` of `CLEARED` or `REJECTED` — but segregation of duties forbids the decider from being the claimer: when the caller's `X-User-ID` equals the screening's `claimed_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The decider's `X-User-ID` is recorded in `decided_by_user_id`. A `CLEARED` verdict stamps `expires_at` at exactly 24 months after the decision time and moves the linked volunteer from `SCREENING` to `CLEARED`; a `REJECTED` verdict sends the volunteer back to `APPLIED`, making the apply–screen–reject loop cyclic. Until a screening is claimed, its `claimed_by_user_id` is null; `decided_by_user_id` remains null until a decision is recorded, and `expires_at` remains null unless the verdict is `CLEARED`. `REJECTED` and `EXPIRED` are a screening's terminal states. Every one of these volunteer status moves, system-driven or not, increments the volunteer's `version` by one.

Clearance is not yet active duty. The volunteer's first assignment to reach `CONFIRMED` flips the volunteer from `CLEARED` to `ACTIVE`. Standing then erodes in two ways. Each no-show adds a strike to `no_show_strikes`, and when the count reaches the strike limit of 3 the volunteer is `SUSPENDED`: every future-dated `ASSIGNED` or `CONFIRMED` assignment of that volunteer is cancelled, each affected shift's `confirmed_count` is decremented where applicable — a `FILLED` shift that drops below `capacity` reopens to `OPEN` — and coverage and posture are recomputed for the affected centers. Separately, screenings expire: when the operations checkpoint finds a `CLEARED` screening whose `expires_at` has been reached, that screening becomes `EXPIRED`, and a volunteer left with no other unexpired `CLEARED` screening lapses to `INACTIVE` — quietly from `CLEARED` or `SUSPENDED`, but from `ACTIVE` with the same future-assignment cancellation cascade as suspension. The volunteer's `total_hours`, the sum of `actual_hours` across the volunteer's `COMPLETED` assignments, survives all of these transitions. A volunteer's record always exposes `status`, `no_show_strikes`, `total_hours`, and `version`.

### 3.3. Shifts and the Assignment Lifecycle

A `CenterManager` shapes the day's coverage by creating shifts with a `start_at` strictly before `end_at` (`ERR_VALIDATION` otherwise), a `role_required` of `DESK`, `KITCHEN`, `EVENTS`, or `FAMILY`, and a `capacity` of at least 1 (the maximum number of `CONFIRMED` assignments the shift will hold). A shift is born `OPEN` with `confirmed_count` 0; its `status` is derived — `FILLED` exactly when `confirmed_count` equals `capacity`, and back to `OPEN` whenever the count drops below. The cycle between `OPEN` and `FILLED` is driven entirely by assignment side effects, never set directly.

Assignment places a volunteer on a shift. The manager supplies a `volunteer_id`; the volunteer must be `CLEARED` or `ACTIVE` (`ERR_VOLUNTEER_NOT_ELIGIBLE` otherwise), and the new shift must not collide with the volunteer's existing commitments. Overlap is evaluated half-open against the shifts of that volunteer's `ASSIGNED` or `CONFIRMED` assignments — `CANCELLED`, `NO_SHOW`, and `COMPLETED` assignments are ignored — and any overlap is rejected with `ERR_SHIFT_OVERLAP`. Back-to-back adjacency, the new shift starting exactly when an existing one ends, does not overlap. A created assignment rests in `ASSIGNED`. Assignments can be listed filtered by `shift_id` and/or `volunteer_id`; a `Volunteer` caller is scoped to its own identity, and passing any other `volunteer_id` is rejected with `ERR_FORBIDDEN`.

Confirmation belongs to the volunteer. Confirming moves an `ASSIGNED` assignment to `CONFIRMED` — a volunteer caller whose `X-User-ID` differs from the assignment's `volunteer_id` is `ERR_FORBIDDEN` — provided the volunteer is still `CLEARED` or `ACTIVE` (`ERR_VOLUNTEER_NOT_ELIGIBLE`) and the shift still has room: confirming into a shift whose `confirmed_count` has reached `capacity` is rejected with `ERR_SHIFT_FULL`. Success increments the shift's `confirmed_count` by one, flips the shift to `FILLED` when the count reaches `capacity`, promotes a `CLEARED` volunteer to `ACTIVE` on this first confirm, and recomputes the center's coverage ratio and posture — the confirmed slot counts toward today's coverage when the shift starts on the current clock date.

After a shift's `end_at` has passed, a `CenterManager` closes out its confirmed assignments in one of two ways. Completion records `actual_hours`, which must be greater than 0 (`ERR_VALIDATION`), on the assignment, moves it to `COMPLETED`, and adds those hours into the volunteer's `total_hours`; attempting completion before the shift has ended is `ERR_INVALID_STATE`. Marking a no-show moves `CONFIRMED` to `NO_SHOW`, adds a strike to `no_show_strikes`, decrements the shift's `confirmed_count` (reopening a `FILLED` shift to `OPEN` when it falls below `capacity`), and recomputes the center's coverage and posture; when the strike count reaches 3, the suspension cascade of §3.2 fires. Marking a no-show before the shift has ended is likewise `ERR_INVALID_STATE`. The operations checkpoint applies the identical no-show cascade automatically to any assignment still `CONFIRMED` once its shift's `end_at` has passed.

Cancellation compensates confirmation. From `ASSIGNED`, cancelling — by the owning volunteer, or by a `CenterManager` without restriction — moves the assignment to `CANCELLED` with no counts touched. From `CONFIRMED`, cancelling releases the reserved slot: `confirmed_count` decrements by one, a `FILLED` shift reopens to `OPEN` when it drops below `capacity`, and coverage and posture are recomputed, returning the shift's count to its pre-confirm value. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal. An assignment record exposes its `shift_id`, `volunteer_id`, `status`, and — once completed — its `actual_hours`, which is null until then.

### 3.4. Guest Eligibility and Center Visits

Guest registration is public: `full_name`, a `category` of `ACTIVE_DUTY`, `GUARD_RESERVE`, `DEPENDENT`, `RETIREE`, or `VETERAN`, and the `verification_expires_on` date of the guest's eligibility document. Unlike other creation-time dates, an already-past `verification_expires_on` is accepted at registration — eligibility lapse is applied lazily — and the guest starts `ELIGIBLE`. Thereafter, whenever a check-in or a service booking is attempted and the guest's `verification_expires_on` is earlier than the current clock date, the guest's `eligibility_status` flips to `EXPIRED` on the spot and the attempted operation is rejected with `ERR_GUEST_INELIGIBLE`. A `CenterManager` restores standing through reverification: supplying a new `verification_expires_on` on or after the current clock date (anything earlier is `ERR_VALIDATION`) sets the date and returns the guest to `ELIGIBLE`, so `ELIGIBLE` and `EXPIRED` form a cycle.

Checking a guest into a center is a `CenterManager` act that runs a gauntlet of gates in the pipeline order of §2.7. The center must not be `CLOSED` — no active agreement, no visits — or the check-in fails with `ERR_CENTER_CLOSED`. The guest must not already hold a `CHECKED_IN` visit at that center, else `ERR_ALREADY_CHECKED_IN`. Eligibility is then enforced with the lazy flip described above. Finally, occupancy: when the center's `current_occupancy` has reached `occupancy_cap`, the check-in is rejected with `ERR_CENTER_AT_CAPACITY`. A successful check-in records `checked_in_at` from the logical clock, leaves `checked_out_at` null, holds the visit in `CHECKED_IN`, increments the center's `current_occupancy` by one, and increments the center's `version` by one. Check-ins can be listed filtered by `guest_id` and/or `center_id`.

There is no manual check-out. The operations checkpoint performs a day-end sweep: any visit still `CHECKED_IN` whose `checked_in_at` date is earlier than the current clock date is moved to `CHECKED_OUT`, with `checked_out_at` stamped at the checkpoint's clock time and `current_occupancy` decremented by one. A guest checked in earlier the same day therefore remains counted until the clock rolls past midnight, and a check-in followed by its own day-end sweep leaves the center's occupancy unchanged. `CHECKED_OUT` is terminal.

### 3.5. Center Services and Booking Policy

Centers offer four bookable services — `SLEEPING_AREA`, `SHOWER`, `CONNECTIVITY`, and `FAMILY_ROOM` — each with its own duration ceiling and capacity pool. A booking names the `guest_id`, the `service_type`, and a `start_at`/`end_at` window; the window must not start in the past (`start_at` at or after the current clock time), and its length, measured in whole minutes, must be positive with `end_at` later than `start_at` (`ERR_VALIDATION` otherwise). A new booking lands in `BOOKED`. A `Guest` caller may book only for itself — the `guest_id` must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN` — while a `CenterManager` books on any guest's behalf. Bookings can be listed filtered by `center_id` and/or `guest_id`, with `Guest` callers scoped to their own `id`.

Posture and eligibility gate first, in pipeline order. A `CLOSED` center rejects every booking with `ERR_CENTER_CLOSED`. A `RESTRICTED` center runs reduced services: only `SHOWER` and `CONNECTIVITY` may be booked, and a `SLEEPING_AREA` or `FAMILY_ROOM` request is rejected with `ERR_POSTURE_SERVICE_BLOCKED`. Guest eligibility is then enforced with the same lazy expiry flip as check-in, rejecting an ineligible guest with `ERR_GUEST_INELIGIBLE`.

Duration is checked against the service ceiling: 480 minutes for `SLEEPING_AREA`, 30 minutes for `SHOWER`, 120 minutes for `CONNECTIVITY`, and 240 minutes for `FAMILY_ROOM`; a longer request is rejected with `ERR_BOOKING_DURATION_INVALID`. The daily quota follows: a guest may hold at most 360 minutes of services per day — 240 minutes when the guest's `category` is `DEPENDENT` — where the minutes already used are the sum of durations of that guest's `BOOKED` bookings, at any center and of any service type, whose `start_at` falls on the current clock date; `COMPLETED` bookings no longer count. When the new booking's minutes exceed the remaining allowance, it is rejected with `ERR_QUOTA_EXCEEDED`.

Finally, the booking must fit the center's capacity pool for its type, considering only the center's `BOOKED` bookings of the same `service_type`. For `SLEEPING_AREA` (pool capacity 8), `SHOWER` (capacity 4), and `CONNECTIVITY` (capacity 20), overlap is half-open: if at any instant the number of pool bookings overlapping the new window, plus the new booking itself, would exceed the type's capacity, the booking is rejected with `ERR_BOOKING_OVERLAP`; back-to-back adjacency — the new booking starting exactly when an existing one ends — does not count as overlap. The `FAMILY_ROOM` is exclusive, capacity 1, and carries a 45-minute cleaning buffer on each side: every existing pool booking blocks the buffered interval from 45 minutes before its `start_at` until 45 minutes after its `end_at`, and a new booking whose window intersects any buffered interval is rejected with `ERR_BOOKING_OVERLAP`. A gap of exactly 45 minutes is allowed — the new booking passes when it starts at or after an existing booking's buffered end, or ends at or before an existing booking's buffered start. Once a booking's `end_at` has passed, the operations checkpoint moves it from `BOOKED` to `COMPLETED`, releasing it from both the quota and the overlap pool; `COMPLETED` is terminal.

### 3.6. Donated Inventory and FEFO Rotation

Donation intake, by a `CenterManager`, records an `item_name`, a `category` of `FOOD`, `BEVERAGE`, `SUPPLY`, or `HYGIENE`, a `received_qty` greater than 0, an `expiry_date` that must not be earlier than the current clock date (`ERR_VALIDATION`), and a `declared_value_cents` of zero or more. When the donation rides a corporate partner program, the optional `partner_name` is supplied, and the lot's `partner_match_cents` is computed at intake as the declared value multiplied by 0.25, rounded half-up to whole cents; without `partner_name` the match is 0. The lot starts `AVAILABLE` with `remaining_qty` initialized to `received_qty`.

Consumption follows first-expiry-first-out, enforced across the whole center. The candidate set is the center's `AVAILABLE` lots with `remaining_qty` greater than 0 and `expiry_date` on or after the current clock date; the FEFO head is the candidate with the earliest `expiry_date`, ties broken by `created_at` ascending — never by `id`. A consume call names a `quantity` of at least 1 (`ERR_VALIDATION`). When the candidate set is empty, the failure is `ERR_LOT_EXPIRED` if the target lot itself is expired — its `expiry_date` earlier than the current date — and `ERR_INVALID_STATE` when the target is simply not `AVAILABLE`. Consuming a lot that is not the FEFO head is rejected with `ERR_FEFO_VIOLATION`, and asking for more than the lot's `remaining_qty` is `ERR_INSUFFICIENT_QUANTITY`. A successful consume decrements `remaining_qty` by the quantity; a lot drawn to exactly 0 becomes `DEPLETED`, while a partial consume leaves the lot `AVAILABLE` with stock remaining. Lots whose `expiry_date` falls behind the current clock date are moved to `DISCARDED_EXPIRED` by the operations checkpoint and leave the FEFO candidate set — and, as §3.8 details, the center's donation value totals. `DEPLETED` and `DISCARDED_EXPIRED` are terminal.

### 3.7. Deployment Support, Homecomings, and Entertainment Tours

Events are created at a center with a `kind` of `DEPLOYMENT`, `HOMECOMING`, or `ENTERTAINMENT_TOUR`, a `name`, and a `start_at`/`end_at` window in which `end_at` must be later than `start_at` (`ERR_VALIDATION` otherwise). A deployment or homecoming may name the `unit_name` whose movement schedule the event supports. Staffing and security parameters are optional with fixed defaults: `min_volunteers` defaults to 2, `required_security_level` defaults to 1 within its range of 1 to 5, `talent_agreement_signed` defaults to false, and `event_budget_cents` — the committed budget that feeds the loaded cost-per-visit figure of §3.8 — defaults to 0. Creation forks the lifecycle by kind: a tour stop begins in `SECURITY_REVIEW`, while deployment and homecoming events begin in `PLANNED`. Creation also enforces the center's event calendar: a new event whose window overlaps — half-open, with adjacency permitted — any non-`CANCELLED` event at the same center is rejected with `ERR_EVENT_OVERLAP`.

Tour stops carry a security gate that only a `PlatformAdmin` can pass. Security approval requires the event to be an `ENTERTAINMENT_TOUR` sitting in `SECURITY_REVIEW` — anything else is `ERR_INVALID_STATE` — the host center to hold an `ACTIVE` site agreement (`ERR_AGREEMENT_NOT_ACTIVE`), that agreement's `security_level` to be at least the event's `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`), and `talent_agreement_signed` to be true (`ERR_TALENT_AGREEMENT_UNSIGNED`). Passing moves the event to `SECURITY_APPROVED`.

Confirmation, by a `CenterManager`, rejoins the two branches under one staffing gate. Deployment and homecoming events confirm from `PLANNED`; tours confirm from `SECURITY_APPROVED`; confirming from the wrong branch state is `ERR_INVALID_STATE`. The gate is the optimistic staffing variant: pledged staffing is the count of `CONFIRMED` assignments plus 0.5 times the count of `ASSIGNED` assignments, taken over the host center's shifts whose windows overlap the event window half-open. When pledged staffing is at least `min_volunteers` the event becomes `CONFIRMED`; otherwise confirmation is rejected with `ERR_STAFFING_SHORTFALL` and the event stays in its branch state.

A `CenterManager` may cancel any non-terminal event — `PLANNED`, `SECURITY_REVIEW`, `SECURITY_APPROVED`, or `CONFIRMED` — moving it to `CANCELLED`. The operations checkpoint resolves the rest: a `CONFIRMED` event whose `end_at` has passed becomes `EXECUTED`, while an event still in `PLANNED`, `SECURITY_REVIEW`, or `SECURITY_APPROVED` once its `start_at` has arrived is swept to `CANCELLED`. `EXECUTED` and `CANCELLED` are terminal.

### 3.8. Funding, Expenses, and Center Cost Accountability

A `PlatformAdmin` records donor money as a funding grant restricted to one center, supplying the `center_id`, a `donor_name`, an `amount_cents` greater than 0, a `spend_by_date` not earlier than the current clock date (`ERR_VALIDATION`), and an optional restricted-`purpose` note. A grant starts `ACTIVE` with `spent_cents` 0, and its `remaining_cents` is always the amount minus what has been spent. When the operations checkpoint finds an `ACTIVE` grant whose `spend_by_date` has passed, the grant becomes `EXPIRED` and its remaining money is no longer spendable. `EXHAUSTED` and `EXPIRED` are terminal.

Center expenses are posted by a `CenterManager` with an `amount_cents`, a `description`, and the obligatory `expected_center_version`; a stale center version rejects the posting with `ERR_STALE_VERSION`, because the allocation below depends on grant state the client may not have seen. Posting runs an all-or-nothing waterfall across the center's `ACTIVE` grants, ordered by `spend_by_date` ascending with ties broken by `created_at` ascending — never by `id`. If the expense exceeds the sum of `remaining_cents` across those grants, the posting is rejected with `ERR_BUDGET_EXCEEDED` and nothing is debited. Otherwise the waterfall walks the grants in order, debiting each the smaller of its own `remaining_cents` and the amount still unallocated; a grant drawn to exactly zero flips to `EXHAUSTED`. An expense exactly equal to the total remaining succeeds and exhausts every candidate. The response returns `posted_cents` together with a `debits` list that preserves the allocation order, and the posting appends an entry carrying `posted_at`, `amount_cents`, and `description` to the center's append-only `expense_ledger`, incrementing the center's `version` by one. `EXPIRED` and `EXHAUSTED` grants are never waterfall candidates.

The cost accountability report consolidates the picture for one center. It echoes the `center_id`, `posture`, `current_occupancy`, and `coverage_ratio`; reports `month_expenses_cents`, the sum of ledger entries whose `posted_at` falls in the current clock calendar month, and `month_visits`, the count of the center's check-ins — of any status — whose `checked_in_at` falls in that same month; and derives two cost-per-visit figures. `cost_per_visit_actual_cents` divides month expenses by month visits, rounded half-up to whole cents. `cost_per_visit_loaded_cents` first adds the committed event budgets — the `event_budget_cents` of the center's `CONFIRMED` or `EXECUTED` events whose `start_at` falls in the current clock month — to the month expenses, then divides by month visits and rounds half-up to whole cents; the loaded figure therefore exceeds the actual one whenever any such event carries a positive budget. When `month_visits` is 0, both per-visit fields are null. The report also totals donations: `donation_value_total_cents` sums `declared_value_cents` over the center's `AVAILABLE` and `DEPLETED` lots — `DISCARDED_EXPIRED` lots are excluded — and `partner_match_total_cents` sums the per-lot matches. The rounding order is pinned: each lot's match is rounded half-up first — declared value multiplied by 0.25 — and only then summed. The alternative of summing declared values and rounding once is forbidden, because the two genuinely differ: three lots of 3 cents each yield a per-lot total of 3 cents (each 0.75 rounds up to 1) against a sum-first total of 2 cents (2.25 rounds to 2).

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Operations that create a new resource — centers, agreement drafts, volunteer applications, screenings, shifts, assignments, guest registrations, check-ins, service bookings, donation lots, events, funding grants, and expense postings — return 201 with the created resource; all other successful operations, including reads and state-transition actions, return 200 with the affected resource or collection. Request payloads, response fields, and side effects are specified in the narratives of §2 and §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock | PlatformAdmin |
| POST | /centers | Create a center | PlatformAdmin |
| GET | /centers/{id} | Get a center with computed posture, coverage, and occupancy | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /centers/{id}/run_ops | Run the operations checkpoint for a center | CenterManager |
| POST | /centers/{id}/site-agreements | Draft a site agreement for a center | PlatformAdmin |
| GET | /centers/{id}/site-agreements | List a center's site agreements | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /site-agreements/{id}/activate | Activate a submitted agreement, superseding any active one | PlatformAdmin |
| POST | /site-agreements/{id}/renew | Renew an agreement inside its renewal window | PlatformAdmin |
| POST | /volunteers | Volunteer application intake | Anonymous |
| GET | /volunteers/{id} | Get a volunteer | PlatformAdmin, CenterManager, Volunteer |
| GET | /volunteers | List volunteers, optionally filtered by home center | PlatformAdmin, CenterManager |
| POST | /volunteers/{id}/screenings | Open a background screening for a volunteer | CenterManager |
| GET | /volunteers/{id}/screenings | List a volunteer's background screenings | PlatformAdmin, CenterManager, Volunteer |
| POST | /screenings/{id}/claim | Claim a submitted screening for review | CenterManager |
| POST | /screenings/{id}/decide | Decide an in-review screening | CenterManager |
| POST | /centers/{id}/shifts | Create a shift slot at a center | CenterManager |
| GET | /centers/{id}/shifts | List a center's shifts | PlatformAdmin, CenterManager, Volunteer, Guest |
| GET | /shifts/{id} | Get one shift | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /shifts/{id}/assignments | Assign a volunteer to a shift | CenterManager |
| GET | /shift-assignments/{id} | Get one shift assignment | PlatformAdmin, CenterManager, Volunteer |
| GET | /shift-assignments | List assignments filtered by shift and/or volunteer | PlatformAdmin, CenterManager, Volunteer |
| POST | /shift-assignments/{id}/confirm | Volunteer confirms its own assignment | Volunteer |
| POST | /shift-assignments/{id}/complete | Record completed hours after shift end | CenterManager |
| POST | /shift-assignments/{id}/mark-no-show | Mark a confirmed assignment as no-show | CenterManager |
| POST | /shift-assignments/{id}/cancel | Cancel an assigned or confirmed assignment | Volunteer, CenterManager |
| POST | /guests | Register a guest | Anonymous |
| GET | /guests/{id} | Get a guest | PlatformAdmin, CenterManager, Guest |
| POST | /guests/{id}/reverify | Renew a guest's eligibility verification | CenterManager |
| POST | /centers/{id}/check-ins | Check a guest into a center | CenterManager |
| GET | /check-ins/{id} | Get one check-in | PlatformAdmin, CenterManager, Guest |
| GET | /check-ins | List check-ins filtered by guest and/or center | PlatformAdmin, CenterManager |
| POST | /centers/{id}/service-bookings | Book a center service | CenterManager, Guest |
| GET | /service-bookings/{id} | Get one service booking | PlatformAdmin, CenterManager, Guest |
| GET | /service-bookings | List service bookings filtered by center and/or guest | PlatformAdmin, CenterManager, Guest |
| POST | /centers/{id}/donation-lots | Intake a donated food or supply lot | CenterManager |
| GET | /centers/{id}/donation-lots | List a center's donation lots | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /donation-lots/{id}/consume | Consume quantity from a lot, FEFO enforced | CenterManager |
| POST | /centers/{id}/events | Create a deployment, homecoming, or entertainment-tour event | CenterManager |
| GET | /centers/{id}/events | List a center's events | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /events/{id}/approve-security | Security-approve an entertainment tour stop | PlatformAdmin |
| POST | /events/{id}/confirm | Confirm an event once staffing is met | CenterManager |
| POST | /events/{id}/cancel | Cancel a non-terminal event | CenterManager |
| POST | /funding-grants | Record a donor grant restricted to a center | PlatformAdmin |
| GET | /centers/{id}/funding-grants | List a center's funding grants | PlatformAdmin, CenterManager, Volunteer, Guest |
| POST | /centers/{id}/expenses | Post a center expense through the grant waterfall | CenterManager |
| GET | /centers/{id}/cost-report | Center cost accountability report | PlatformAdmin, CenterManager, Volunteer, Guest |

## 5. Error Code Catalogue

Error responses carry the `error_id` values below in the envelope described in §2.2. The conditions under which each error fires, and the order in which competing checks run, are specified in §2.7 and throughout §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_CENTER_CLOSED | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 409 |
| ERR_SCREENING_ALREADY_OPEN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_GUEST_INELIGIBLE | 403 |
| ERR_ALREADY_CHECKED_IN | 409 |
| ERR_CENTER_AT_CAPACITY | 409 |
| ERR_POSTURE_SERVICE_BLOCKED | 409 |
| ERR_SECURITY_LEVEL_INSUFFICIENT | 409 |
| ERR_TALENT_AGREEMENT_UNSIGNED | 409 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_SHIFT_FULL | 409 |
| ERR_VOLUNTEER_NOT_ELIGIBLE | 409 |
| ERR_BOOKING_OVERLAP | 409 |
| ERR_BOOKING_DURATION_INVALID | 422 |
| ERR_QUOTA_EXCEEDED | 409 |
| ERR_EVENT_OVERLAP | 409 |
| ERR_STAFFING_SHORTFALL | 409 |
| ERR_FEFO_VIOLATION | 409 |
| ERR_LOT_EXPIRED | 409 |
| ERR_INSUFFICIENT_QUANTITY | 409 |
| ERR_BUDGET_EXCEEDED | 409 |
