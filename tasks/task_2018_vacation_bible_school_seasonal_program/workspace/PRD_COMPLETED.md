# Vacation Bible School API — Product Requirements Document

## 1. Introduction

Every summer the congregation runs its Vacation Bible School: a week of themed mornings where children rotate through age-banded classrooms, volunteer teachers lead lessons from ordered curriculum kits, snacks and crafts move out of a shared stock room, and every pickup is verified against a printed security tag. Behind that single week sits a season-long operation — recruiting and screening volunteers, grouping children by age and grade, balancing finite classroom seats against a waitlist, accommodating allergies and medical needs, keeping families informed, and capturing next year's interest before the closing program ends.

This document specifies the API that runs that season end to end, mounted under the `/vbs` prefix. Eight acting roles span anonymous public intake, parents, volunteers, front-desk check-in staff, and three segregated coordinator and officer functions under a program director. The API covers program setup and calendar building, household registration with age-banded classroom placement and a waitlist waterfall, volunteer screening with role assignment, curriculum-kit ordering against a supply budget, stock reservation and distribution, tag-audited daily check-in and check-out, family messaging, and next-year retention. Every date- and time-sensitive rule — the registration window, offer expiries, day scheduling, late pickup — reads a single server-side logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the target endpoint, or that violates an ownership rule, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The eight roles, spelled exactly as the API expects them:

- `Anonymous` — the unauthenticated public caller, admitted only to self-service intake: household self-registration and volunteer self-application. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Parent` — a family contact managing their own household's children, registrations, and accommodation plans. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a family — a child, a registration, an accommodation plan — compare the resource's family reference to `X-User-ID`, and acting on another family's resources is rejected with `ERR_FORBIDDEN`. On list endpoints the same rule scopes rather than rejects: a `Parent` sees only rows belonging to their own household, and a filter naming another family yields an empty page rather than an error.
- `Volunteer` — a prospective or cleared helper managing their own screening and role applications. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a volunteer — screening checks, role applications — compare the resource's `volunteer_id` to `X-User-ID`, and acting on another volunteer's records is rejected with `ERR_FORBIDDEN`.
- `CheckInStaff` — the front-desk operator running daily drop-off and pickup; cannot register children or decide screenings. When `X-User-Role` is `CheckInStaff`, `X-User-ID` is an opaque operator identifier; the server records it (as `checked_in_by` and `checked_out_by` on attendance records) but does not compare it to any entity's `id`.
- `RegistrationCoordinator` — the registrar owning classrooms, families, and the waitlist; cannot decide screenings or confirm role assignments. `X-User-ID` is opaque and never compared to an entity `id`.
- `VolunteerCoordinator` — the volunteer scheduler confirming role assignments; cannot decide screenings. `X-User-ID` is opaque and never compared to an entity `id`.
- `SafetyOfficer` — the child-safety reviewer owning screening decisions and accommodation approvals; cannot confirm role assignments. `X-User-ID` is opaque; the server records it as `reviewer_id` on screening decisions and `reviewed_by` on plan reviews but does not compare it to any entity's `id` for ownership.
- `ProgramDirector` — the program administrator owning the lifecycle, the calendar, the supply budget, messaging, the retention list, and the logical clock. `X-User-ID` is opaque and never compared to an entity `id`.

Segregation of duties is deliberate throughout: the screener is never the assigner, the registrar never touches screening decisions, front-desk staff never register children, and no one reviews their own screening check.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Out-of-range values are clamped to those bounds rather than rejected, and an unparseable `limit` or `offset` falls back to its default. `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`. Query parameters other than the declared filters and pagination keys are ignored. List responses carry the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`. Every list sorts by `created_at` ascending, using server-assigned monotonic timestamps; an entity's `id` is never used as an ordering key or tie-break. Individual list endpoints additionally expose resource-specific filters — `status`, `program_id`, `family_id`, `child_id`, `classroom_id`, `volunteer_id`, `email`, `category`, `supply_item_id`, `program_day_id`, `registration_id`, `priority_tier`, and `include_archived` — which §3 introduces with the workflows and §4 enumerates per endpoint.

### 2.4. The Logical Clock and Calendar Semantics

The server maintains a logical clock. At startup the clock reads exactly 2026-08-01T00:00:00Z; before any set call the clock reads that default and never falls back to wall-clock time. A `ProgramDirector`-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The supplied instant may lie ahead of or behind the previous reading; a datetime supplied without a UTC offset is read as UTC. Every clock-sensitive rule in this document reads that logical clock: the registration window bounded by `registration_opens_at` and `registration_closes_at`, the offer expiry carried in `offer_expires_at`, the rule that only the program day whose `date` is today may open, and the late-pickup comparison against `pickup_cutoff_time`.

Calendar conventions: dates are ISO calendar dates; `start_date` and `end_date` are inclusive bounds wherever a range is tested; `pickup_cutoff_time` is an HH:MM 24-hour clock time defaulting to 12:00; datetimes are ISO 8601 UTC.

### 2.5. Resource Identity, Versioning, and Optimistic Concurrency

Every one of the seventeen resources carries the same four common properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits assigned at creation; `updated_at`, maintained in the same format on every mutation; and `version`, an integer that starts at 1 when the resource is created and increments by exactly one on every mutation — including system-driven mutations such as a classroom flipping from `ACCEPTING` to `FULL`, so observers always see a state flip as a version advance.

Three write operations are guarded by optimistic concurrency control:

- Editing a classroom's configuration (`PATCH /vbs/classrooms/{classroom_id}`) requires the non-optional field `expected_classroom_version`, carrying the `version` the client last observed on that classroom. If the classroom's version has advanced since — through a status flip or a prior edit — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because a configuration edit does not inspect any state a prior edit changed and would otherwise succeed silently on a stale view.
- Approving an accommodation plan (`POST /vbs/accommodation-plans/{plan_id}/approve`) requires the non-optional field `expected_child_version`, matching the current `version` of the plan's child. Approval supersedes the child's currently approved plan; a client whose last read of the child predates another approval would supersede a plan set it never observed, so the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Running the expired-offer sweep (`POST /vbs/programs/{program_id}/sweep-expired-offers`) requires the non-optional field `expected_program_version`, matching the program's current `version`. A sweep that finds nothing to expire is a legitimate no-op, so a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than detected by any state precondition.

No endpoint other than these three accepts a version field.

### 2.6. Numeric Precision and Rounding Discipline

Money is integer cents: `supply_budget_cents`, `unit_cost_cents`, `total_cost_cents`, and `budget_remaining_cents` are whole cents with no fractional part, and an order's total is its `quantity` multiplied by its `unit_cost_cents` in integer arithmetic with no rounding. Counts — seats, adults, kits, craft packs, recipients, queue positions — are integers; wherever a division must yield a whole thing, such as adults, kits, or packs, the result rounds up to the next whole unit, and the per-classroom rounding order for craft packs is pinned in §3.6. Rates are decimal numbers rounded half-up to four decimal places, and tier thresholds compare inclusively against that rounded value. Ages are whole years computed by calendar month-and-day comparison, never by day-count approximation. The late-pickup comparison runs at second precision on the logical clock with a strict inequality.

### 2.7. Seat Reservation and Waitlist Allocation Principles

A classroom's `open_seats` is its `capacity` minus the number of its `ENROLLED` registrations minus the number of its `OFFERED` registrations: an outstanding waitlist offer reserves a seat, while a `WAITLISTED` registration consumes none. When a registration fills the last open seat, the classroom flips from `ACCEPTING` to `FULL`; when a cancellation or a capacity increase lifts `open_seats` to one or more while the classroom is `FULL`, it flips back to `ACCEPTING` and immediately runs the waitlist promotion waterfall. Each flip increments the classroom's `version` by one.

The waterfall works one seat at a time: while at least one open seat and at least one waiting registration remain, the waiting registration with the earliest `created_at` is promoted to `OFFERED` and stamped with an `offer_expires_at` of the promotion instant plus the program's `waitlist_offer_ttl_hours` (default 48 hours, at least 1). Because the fresh offer itself consumes a seat, `open_seats` is recomputed after every single promotion; the loop promotes exactly one, recomputes, and repeats, stopping as soon as no open seat or no waiting registration remains. Queue order is `created_at` ascending on server-assigned monotonic timestamps with no id-based tie-break; `waitlist_position` is the 1-based dense rank in that order, is null whenever the registration is not `WAITLISTED`, and recomputes whenever a registration enters or leaves the queue. When the operator-run sweep expires offers across several classrooms, the affected classrooms are processed in ascending classroom `created_at` order.

### 2.8. Child-Safety Gates and Segregation of Duties

Four standing safety gates sit ahead of ordinary business checks in the pipeline of §2.9. First, segregation of duties: a `SafetyOfficer` may not decide a screening check whose `volunteer_id` equals the officer's own `X-User-ID` — self-review is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403). Second, ratio staffing with a two-adult minimum: a classroom with any enrolled children requires at least two confirmed, cleared, adult volunteers, scaled by the program's `child_staff_ratio`, and a program day cannot open while any enrolled classroom falls short (`ERR_STAFFING_INADEQUATE`). Third, allergen safety: a snack distribution whose `allergen_tags` intersect the approved food-allergy plans of children enrolled in the target classroom is rejected (`ERR_ALLERGEN_CONFLICT`), and a child flagged `has_special_needs` cannot check in without an `APPROVED` accommodation plan (`ERR_ACCOMMODATION_NOT_APPROVED`). Fourth, tag-audited pickup and site control: checkout requires the day's active tag code, and a day cannot close while any child remains `CHECKED_IN` (`ERR_CHILDREN_ON_SITE`).

### 2.9. Validation Pipeline and Priority Order

Every endpoint evaluates the same eleven-tier validation pipeline. Tiers run in ascending priority number, and when several checks fail at once the lowest-numbered failure wins and produces the response.

- **Priority 0 — well-formedness** (`ERR_INVALID_REQUEST`, HTTP 400, all endpoints): the body parses; all required fields are present; no undeclared fields appear; enums, integers, and dates parse; the conditional-field rules hold — `allergens` is required and non-empty exactly when `severity` is `FOOD_ALLERGY` and forbidden otherwise, and `classroom_id` is required exactly when `audience` is `CLASSROOM` and forbidden otherwise; `age_min` is not greater than `age_max`; `capacity` is at least 1; `quantity` is at least 1; `end_date` is not before `start_date`; and `registration_closes_at` is strictly after `registration_opens_at`.
- **Priority 1 — authentication** (`ERR_UNAUTHENTICATED`, HTTP 401, all endpoints): both headers present and the role declared, per §2.1.
- **Priority 2 — authorization and ownership** (`ERR_FORBIDDEN`, HTTP 403, all endpoints): the role is listed for the endpoint and the ownership rules of §2.1 hold — a parent acting on another family's child, registration, or plan, or a volunteer acting on another volunteer's check, is rejected here.
- **Priority 3 — existence** (`ERR_NOT_FOUND`, HTTP 404, all endpoints): path and body references exist, validated left to right — program first, then classroom, day, or item, then child, volunteer, registration, plan, order, message, or entry.
- **Priority 4 — optimistic concurrency** (`ERR_STALE_VERSION`, HTTP 412): only on the three guarded endpoints of §2.5, ahead of every business rule.
- **Priority 5 — child-safety gates** (HTTP 409 unless noted): self-review (`ERR_SELF_REVIEW_FORBIDDEN`, 403), the accommodation gate (`ERR_ACCOMMODATION_NOT_APPROVED`), the allergen gate (`ERR_ALLERGEN_CONFLICT`), the staffing gate (`ERR_STAFFING_INADEQUATE`), and the children-on-site gate (`ERR_CHILDREN_ON_SITE`). This tier applies to screening decisions, attendance check-in, supply-distribution creation, and day open and close.
- **Priority 6 — state permission** (`ERR_INVALID_STATE`, HTTP 409, all action endpoints): the target resource is in a state that permits the operation — program lifecycle gates, the classroom `ACCEPTING`-or-`FULL` gate for registration, the registration `OFFERED` gate for accept and decline, the check `SUBMITTED` gate for decide, the order `DRAFT` and `SUBMITTED` gates, the day `SCHEDULED` and `OPEN` gates, the attendance `NOT_ARRIVED` and `CHECKED_IN` gates, the message `DRAFT` gate, the entry `LISTED` and `INVITED` gates, the family `ACTIVE` gate for archive, and every terminal-state lockdown.
- **Priority 7 — clock-relative rules** (HTTP 409), evaluated within this tier in a fixed order: (i) registration only while the program is `REGISTRATION_OPEN` and the clock reads within the inclusive registration window (`ERR_REGISTRATION_WINDOW_CLOSED`); (ii) offer acceptance only strictly before expiry (`ERR_OFFER_EXPIRED`); (iii) day open only when the day's `date` equals the current logical date (`ERR_DAY_NOT_TODAY`); (iv) a new program's inclusive date range must not intersect any non-`ARCHIVED` program's inclusive range (`ERR_PROGRAM_DATE_OVERLAP`); (v) a new program day must lie within the program's inclusive range (`ERR_DAY_OUT_OF_RANGE`); (vi) a new program day must be the program's `start_date` when it is the first day, or exactly one calendar day after the previously appended day (`ERR_DAY_NOT_SEQUENTIAL`). Rule (v) outranks rule (vi): an out-of-range date reports `ERR_DAY_OUT_OF_RANGE` even when it also breaks adjacency.
- **Priority 8 — constraint rules**: the inclusive age band (`ERR_AGE_OUT_OF_RANGE`, HTTP 422); one active registration per child per program (`ERR_DUPLICATE_REGISTRATION`); family email uniqueness (`ERR_DUPLICATE_EMAIL`); one active screening check per volunteer per type (`ERR_DUPLICATE_CHECK`); one active assignment per volunteer per classroom (`ERR_DUPLICATE_ASSIGNMENT`); one confirmed lead teacher per classroom (`ERR_LEAD_TEACHER_TAKEN`); the child-facing double-booking ban (`ERR_VOLUNTEER_DOUBLE_BOOKED`); no minor as lead teacher (`ERR_MINOR_ROLE_FORBIDDEN`, HTTP 422); classroom close requires zero enrolled (`ERR_CLASSROOM_NOT_EMPTY`); capacity may not shrink below the enrolled count (`ERR_CAPACITY_BELOW_ENROLLED`); start-session requires at least one day (`ERR_NO_PROGRAM_DAYS`); completion requires all days closed (`ERR_DAYS_STILL_OPEN`); retention regeneration without `force` (`ERR_RETENTION_EXISTS`); the checkout tag code must match an issued tag (`ERR_TAG_MISMATCH`, `ERR_TAG_NOT_ACTIVE`); check-in requires an enrolled registration (`ERR_NOT_ENROLLED`); and acceptance requires remaining room (`ERR_CLASSROOM_FULL`).
- **Priority 9 — cross-entity references**: the family must be `ACTIVE` to create children or registrations (`ERR_FAMILY_ARCHIVED`); the volunteer must be `CLEARED` to confirm an assignment (`ERR_VOLUNTEER_NOT_CLEARED`); a distribution's item, classroom, and day must all belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`). This tier applies to child and registration creation, assignment confirmation, and distribution creation.
- **Priority 10 — fiscal and stock rules**, evaluated last: submit quantity against the final kit requirement (`ERR_KIT_QUANTITY_SHORT`); approval total against the remaining budget (`ERR_BUDGET_EXCEEDED`, HTTP 402); distribution quantity against available stock (`ERR_INSUFFICIENT_STOCK`). This tier applies to supply-order submit and approve and to distribution creation.

So, for example, a screening decision that is both self-review and aimed at an already-decided check reports the self-review error; a distribution that is both cross-program and over stock reports `ERR_CROSS_PROGRAM_REFERENCE`; and a plan approval carrying a stale child version reports `ERR_STALE_VERSION` ahead of any state problem.

### 2.10. Derived Fields and Immediate Consistency

Consistency is immediate: every mutation and all of its cascades are visible in the same request's response and in any subsequent read. Derived counters and rollups are recomputed from their source rows rather than cached: classroom `enrolled_count`, `offered_count`, `waitlist_count`, `open_seats`, `required_adults`, `confirmed_adult_count`, and `staffing_status`; program `enrolled_total`, `waitlist_total`, and `current_day_index`; registration `age_at_registration` and `waitlist_position`; volunteer `is_minor`; order `total_cost_cents`, `recommended_provisional`, and `required_final`; item `reserved_quantity` and `available_quantity`; day `checked_in_count`, `checked_out_count`, and `absent_count`; attendance `late_pickup`; message `recipient_count`; and each retention entry's `attended_days`, `attendance_rate`, `family_volunteer_bonus`, and `priority_tier`. The formulas live with the workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Calendar, Classrooms, and the Supply Budget

A `ProgramDirector` opens the season by creating the program with its `name`, `program_year`, inclusive `start_date` and `end_date`, the registration window `registration_opens_at` and `registration_closes_at` (both inclusive instants, with close strictly after open), and the `supply_budget_cents` that caps curriculum-kit spending (zero or more cents). Three settings carry defaults: `child_staff_ratio` defaults to 8 and must be at least 1, `waitlist_offer_ttl_hours` defaults to 48 and must be at least 1, and `pickup_cutoff_time` defaults to 12:00. A new program's inclusive date range must not intersect any other non-`ARCHIVED` program's inclusive range — overlapping ranges are rejected with `ERR_PROGRAM_DATE_OVERLAP`. The program is born `DRAFT` with `current_day_index` 0 and `version` 1.

Classrooms come next. A `RegistrationCoordinator` creates each classroom against a `program_id` with a `name`, an inclusive age band `age_min` and `age_max` in whole years measured at the program's `start_date` (`age_min` at least 0), and a `capacity` of at least 1. Creation is permitted while the program is `DRAFT` or `REGISTRATION_OPEN`; against any later program status it fails with `ERR_INVALID_STATE`. A classroom created while the program is still `DRAFT` is born `SETUP`; one created while the program is already `REGISTRATION_OPEN` is born `ACCEPTING`.

The director then builds the calendar by appending program days: each creation supplies a `program_id` and a `date`, receives the next 1-based `day_index` in append order, and starts `SCHEDULED`. The first day must equal the program's `start_date`; every later day must be exactly one calendar day after the previously appended day, with violations reported as `ERR_DAY_NOT_SEQUENTIAL`; and every day must lie within the program's inclusive range, with violations reported as `ERR_DAY_OUT_OF_RANGE` — and the out-of-range error outranks the adjacency error when a date breaks both. Days may be appended while the program is `DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`.

Opening registration moves the program `DRAFT` → `REGISTRATION_OPEN` and cascades: every `SETUP` classroom of the program flips to `ACCEPTING`, each such classroom's `version` incrementing by one. Closing registration moves `REGISTRATION_OPEN` → `REGISTRATION_CLOSED`. Starting the session requires at least one program day — otherwise `ERR_NO_PROGRAM_DAYS` — and moves `REGISTRATION_CLOSED` → `IN_SESSION`. Completing requires every day `CLOSED` — otherwise `ERR_DAYS_STILL_OPEN` — and moves `IN_SESSION` → `COMPLETED`. Archiving moves `COMPLETED` → `ARCHIVED`, after which the program is read-only: every write targeting it or its children returns `ERR_INVALID_STATE`. Each lifecycle step increments the program's `version` by one, and each step's state gate reports `ERR_INVALID_STATE` when the program stands in the wrong state.

Classroom configuration can be revisited mid-season: a coordinator edits `capacity`, `age_min`, or `age_max` while the program is `DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`, subject to the concurrency rule of §2.5 — a stale `expected_classroom_version` fails with `ERR_STALE_VERSION` ahead of any other check — and to the floor that `capacity` may not drop below the current `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`). The age-band rules apply to the merged result of stored and supplied values (`age_min` at least 0 and not greater than `age_max`), and a `CLOSED` classroom accepts no edits (`ERR_INVALID_STATE`). A successful edit increments the classroom's `version` by one; if the edit lifts `open_seats` to one or more while the classroom is `FULL`, the classroom flips back to `ACCEPTING` and the promotion waterfall of §2.7 runs immediately.

Closing a classroom requires `enrolled_count` zero — otherwise `ERR_CLASSROOM_NOT_EMPTY` — and is permitted from `SETUP`, `ACCEPTING`, or `FULL`; the `FULL` case is reachable only after a capacity edit and is handled identically. On close, every `WAITLISTED` or `OFFERED` registration of the classroom transitions to `CANCELLED` with `cancellation_reason` `CLASSROOM_CLOSED`; `PROPOSED` role assignments of the classroom are unaffected, while `CONFIRMED` ones transition to `RELEASED`; and the classroom's `version` increments by one.

### 3.2. Household Intake: Families, Children, and Registration

Households self-register through the public intake as `Anonymous` callers, supplying `household_name`, `primary_contact_name`, `email`, `phone`, and optionally `preferred_contact` — one of `EMAIL`, `PHONE`, or `TEXT`, defaulting to `EMAIL`. The `email` must be unique across all families including `ARCHIVED` ones, or creation fails with `ERR_DUPLICATE_EMAIL`. The family is born `ACTIVE`. Family lists exclude archived households unless the caller passes `include_archived` true (the values `true`, `1`, and `yes`, case-insensitive, count as true), and support an `email` filter.

A `RegistrationCoordinator` soft-deletes a family by archiving it — `ACTIVE` → `ARCHIVED`, with `ERR_INVALID_STATE` if the family is not `ACTIVE`. The cascade is immediate: for every child of the family, processed in creation order, every registration in `ENROLLED`, `WAITLISTED`, or `OFFERED` transitions to `CANCELLED` with `cancellation_reason` `ADMIN`, and each `ENROLLED` or `OFFERED` cancellation runs its normal cascade — the seat flip and promotion waterfall of §3.3. The family's `version` increments by one.

Children join a family through a `Parent` — whose payload `family_id` must equal the caller's `X-User-ID` — or through a `RegistrationCoordinator`, supplying `first_name`, `last_name`, `birth_date`, the `grade_completed` (one of `PRE_K`, `KINDERGARTEN`, `GRADE_1`, `GRADE_2`, `GRADE_3`, `GRADE_4`, `GRADE_5`, `GRADE_6`), and optionally `has_special_needs` (default false) and a free-text `allergy_summary` (default empty). The family must be `ACTIVE`: creating a child, and likewise creating a registration, against an archived family fails with `ERR_FAMILY_ARCHIVED`.

Registration itself is a single act with a two-way fork. A `Parent` (own children only) or a `RegistrationCoordinator` submits a `child_id` and a `classroom_id`, and the creation runs the full validation pipeline of §2.9: the program must be `REGISTRATION_OPEN` with the clock reading within the inclusive registration window (`ERR_REGISTRATION_WINDOW_CLOSED`); the classroom must be `ACCEPTING` or `FULL` (`ERR_INVALID_STATE`); the child must not already hold an `ENROLLED`, `WAITLISTED`, or `OFFERED` registration in the same program (`ERR_DUPLICATE_REGISTRATION`); and the child's age must fit the classroom's band.

Age is computed as `age_at_registration`: the child's age in whole years on the program's `start_date`, taken as the difference of calendar years, minus one when the month-and-day of `start_date` falls earlier in the year than the month-and-day of the child's `birth_date`. A birthday falling exactly on `start_date` counts as already turned, so nothing is subtracted in that case. The band check is inclusive on both ends: an age below `age_min` or above `age_max` is rejected with `ERR_AGE_OUT_OF_RANGE` (HTTP 422).

When the classroom has at least one open seat, the registration is born `ENROLLED` with `enrolled_at` stamped to the current instant; if that enrollment consumed the last open seat, the classroom flips `ACCEPTING` → `FULL`. When no seat is open, the registration is born `WAITLISTED` and receives its `waitlist_position` per §2.7. One mid-season nuance: when the owning program is already `IN_SESSION` and a program day is currently `OPEN`, a registration entering `ENROLLED` — directly or via offer acceptance — immediately spawns an attendance record in `NOT_ARRIVED` for the child on that day.

Cancellation splits by state. Cancelling an `ENROLLED` registration — by a `Parent`, with `cancellation_reason` `FAMILY_REQUEST`, or by a `RegistrationCoordinator`, with `ADMIN` — drops the classroom's `enrolled_count` by one; if the classroom was `FULL` it flips back to `ACCEPTING` and the promotion waterfall runs; and the child's attendance records still `NOT_ARRIVED` on days that are `SCHEDULED` or `OPEN` are deleted, because the child is no longer expected. Cancelling a `WAITLISTED` registration removes it from the queue and recomputes the remaining positions. Cancelling from any other state — including `OFFERED`, whose answer paths live in §3.3 — fails with `ERR_INVALID_STATE`.

### 3.3. The Waitlist: Offers, Expiry, and the Promotion Waterfall

The waterfall of §2.7 is the only path off the queue. When it promotes, the head registration moves `WAITLISTED` → `OFFERED`, its `waitlist_position` clears to null, the remaining queue re-ranks, and `offer_expires_at` is stamped as the promotion instant plus the program's `waitlist_offer_ttl_hours`.

From `OFFERED`, a registration has exactly three exits. The offered family — and only that family, acting as `Parent` — answers. Acceptance requires the registration to be `OFFERED` (`ERR_INVALID_STATE` otherwise) and the clock to read strictly before `offer_expires_at`: an acceptance at or after the expiry is rejected with `ERR_OFFER_EXPIRED`, the registration itself flips to `EXPIRED`, and the waterfall runs for the classroom. Acceptance also re-checks capacity, because an offer's reserved seat survives a capacity shrink: if `enrolled_count` has reached `capacity`, acceptance fails with `ERR_CLASSROOM_FULL`. A successful acceptance moves the registration `OFFERED` → `ENROLLED`, stamps `enrolled_at`, clears `offer_expires_at`, and — when the program is `IN_SESSION` with a day `OPEN` — spawns the `NOT_ARRIVED` attendance record described in §3.2.

Declining moves `OFFERED` → `DECLINED`, frees the reserved seat, and runs the waterfall for the classroom. Expiry moves `OFFERED` → `EXPIRED` with the same freeing effect, and fires in two ways: inline, on a late acceptance as above; and in batch, through the coordinator-run sweep, which flips every `OFFERED` registration of the program whose `offer_expires_at` reads at or before the current instant and then runs the waterfall per affected classroom in ascending classroom `created_at` order. The sweep carries the concurrency rule of §2.5 — `expected_program_version` must match the program's current `version`, with `ERR_STALE_VERSION` (HTTP 412) on mismatch, evaluated ahead of everything else — and a sweep that finds nothing to expire is a legitimate no-op. A sweep increments the program's `version` by one.

### 3.4. Volunteers: Application, Screening, and Classroom Staffing

Volunteers self-apply as `Anonymous` callers against a `program_id`, supplying `full_name`, `email`, `phone`, `birth_date`, and optionally a `family_id` linking their household for the retention bonus of §3.8 (default null); a `family_id` naming no existing family is rejected with `ERR_NOT_FOUND`. The application is born `APPLIED`, and `is_minor` is derived at once: true when the volunteer's age at the program's `start_date` — computed by the same calendar method as `age_at_registration` — is strictly under 18; a volunteer who turns eighteen exactly on `start_date` is not a minor.

Screening runs as one `ScreeningCheck` per type: each submission names a `volunteer_id` and a `check_type` of `BACKGROUND`, `REFERENCE`, or `SAFE_MINISTRY_TRAINING`, filed by the volunteer — whose payload `volunteer_id` must equal the caller's `X-User-ID` — or by a `VolunteerCoordinator` on the volunteer's behalf. A volunteer may hold only one active check per type, active meaning `SUBMITTED`, `INFO_REQUESTED`, or `CLEARED`; a duplicate is rejected with `ERR_DUPLICATE_CHECK`. Creation of a volunteer's first check moves the volunteer `APPLIED` → `SCREENING`.

A fresh check is `SUBMITTED`. A `SafetyOfficer` decides it in one of three directions supplied as `decision`, recording `reviewer_id`, `decision_notes` (optional, null when omitted), and `decided_at` on any decision: `CLEARED`, `REJECTED`, or `INFO_REQUESTED`. Self-review is forbidden — a decision on a check whose `volunteer_id` equals the officer's own `X-User-ID` fails with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403), ahead of the state gate — and deciding a check that is not `SUBMITTED` fails with `ERR_INVALID_STATE`. An `INFO_REQUESTED` check loops: the owning volunteer — and only that volunteer, `ERR_FORBIDDEN` otherwise — resubmits it with an optional `response_notes`, returning it `INFO_REQUESTED` → `SUBMITTED` and incrementing `resubmission_count` by one; the cycle may repeat.

Two recomputes follow every decision. When any check of a volunteer turns `REJECTED`, the volunteer moves `SCREENING` → `REJECTED` — a terminal state — while their other checks still `SUBMITTED` or `INFO_REQUESTED` remain unchanged. When the volunteer holds a `CLEARED` check for every one of the three required types, the volunteer moves `SCREENING` → `CLEARED`, and every `PROPOSED` role assignment of that volunteer auto-confirms, processed in creation order — except any that would violate the one-lead-teacher-per-classroom rule or the child-facing double-booking rule, which stay `PROPOSED`. Each auto-confirm stamps `confirmed_at` and recomputes the classroom's staffing.

Role assignments join a volunteer to a classroom in one of five roles: `LEAD_TEACHER`, `ASSISTANT_TEACHER`, `SNACK_COORDINATOR`, `CRAFT_LEADER`, or `CHECKIN_DESK`. A `VolunteerCoordinator`, or the volunteer themselves, proposes an assignment with `volunteer_id`, `classroom_id`, and `role`; the proposal is born `PROPOSED`. A minor may never be proposed as `LEAD_TEACHER` (`ERR_MINOR_ROLE_FORBIDDEN`, HTTP 422), and a volunteer may hold only one active assignment per classroom — active meaning `PROPOSED` or `CONFIRMED` — with duplicates rejected as `ERR_DUPLICATE_ASSIGNMENT`.

Confirmation — by a `VolunteerCoordinator`, or by the auto-confirm above — is gated four deep: the assignment must be `PROPOSED` (`ERR_INVALID_STATE`); the volunteer must be `CLEARED` (`ERR_VOLUNTEER_NOT_CLEARED`); for `LEAD_TEACHER`, no other `CONFIRMED` lead teacher may exist in the classroom (`ERR_LEAD_TEACHER_TAKEN`); and for the child-facing roles `LEAD_TEACHER` and `ASSISTANT_TEACHER`, the volunteer may hold no other `CONFIRMED` child-facing assignment in any other classroom of the same program (`ERR_VOLUNTEER_DOUBLE_BOOKED`). Where several gates fail together, the pipeline order of §2.9 decides which surfaces: state first, then the uniqueness and double-booking constraints, then clearance. A successful confirm stamps `confirmed_at` and recomputes staffing; releasing a `CONFIRMED` assignment moves it `CONFIRMED` → `RELEASED`, stamps `released_at`, and recomputes again.

Staffing arithmetic runs as follows. A classroom's `required_adults` is zero when `enrolled_count` is zero, and otherwise the larger of two — the two-adult minimum — and `enrolled_count` divided by the program's `child_staff_ratio` rounded up to the next whole adult. `confirmed_adult_count` counts the classroom's `CONFIRMED` assignments in the two teaching roles whose volunteer is `CLEARED` and not a minor. `staffing_status` is `ADEQUATE` when the confirmed count meets the requirement — or when no adults are required at all — `UNSTAFFED` when the confirmed count is zero while adults are required, and `UNDERSTAFFED` otherwise.

### 3.5. Accommodation Plans and Allergen Safety

A child flagged `has_special_needs` cannot check in until a plan is approved — the gate itself lives in §3.7 — so families file early. A `Parent` (for their own children) or a `SafetyOfficer` creates a plan against a `child_id` with a `severity` of `FOOD_ALLERGY`, `ENVIRONMENTAL_ALLERGY`, `MEDICATION_ADMIN`, `MOBILITY`, or `BEHAVIORAL`; free-text care `instructions`; an optional `requires_epinephrine` flag (default false) marking that an epinephrine kit travels with the child; and, exactly when the severity is `FOOD_ALLERGY`, a non-empty `allergens` array drawn from `PEANUT`, `TREE_NUT`, `MILK`, `EGG`, `GLUTEN`, `SOY`, `SESAME`, and `OTHER` — required then, and forbidden for every other severity, with violations reported as `ERR_INVALID_REQUEST`. The plan is born `DRAFT`.

The owning `Parent` submits the plan, moving it `DRAFT` → `SUBMITTED` — or `NEEDS_REVISION` → `SUBMITTED` after a revision round; submitting from any other state fails with `ERR_INVALID_STATE`. A `SafetyOfficer` then either requests revision, moving `SUBMITTED` → `NEEDS_REVISION` and recording a required `revision_notes` and `reviewed_by`, or approves. Approval carries the concurrency rule of §2.5: `expected_child_version` must match the child's current `version`, and that version check runs ahead of the state gate, so a stale version reports `ERR_STALE_VERSION` (HTTP 412) even when the plan is otherwise approvable. A successful approval moves `SUBMITTED` → `APPROVED`, records `reviewed_by`, and supersedes the child's prior plan set: every other plan of the same child standing in `APPROVED` transitions to `SUPERSEDED`, and the child's `version` increments by one on every approval, because the approval mutates the child's plan set.

Those approved plans feed the allergen gate of §3.6: for any classroom, the blocked-allergen set is the union of `allergens` across plans that are `APPROVED`, carry severity `FOOD_ALLERGY`, and belong to a child holding an `ENROLLED` registration in that classroom. Front-desk staff can read plans, so the gate and the flag stay visible exactly where they matter.

### 3.6. Curriculum Kits, Stock, and Supply Distribution

Kit planning starts from enrollment. A program's `enrolled_total` counts `ENROLLED` registrations across its classrooms whose status is not `CLOSED`, and its `waitlist_total` counts `WAITLISTED` registrations across its classrooms. The kit recommendation comes in two variants from one base: the program's enrolled total multiplied by 1.10 — a ten-percent buffer — rounded up to the next whole kit, so five enrolled children yield a base of six kits. The provisional variant, surfaced on an order as `recommended_provisional`, is exactly that base. The final variant, surfaced as `required_final`, adds one teacher kit per classroom whose status is not `CLOSED`; whenever at least one such classroom exists, the final figure exceeds the provisional.

A `ProgramDirector` builds an order with `program_id`, `kit_name`, `vendor`, `quantity` (at least 1), and `unit_cost_cents` (zero or more); the order is born `DRAFT`, and its `total_cost_cents` is the quantity multiplied by the unit cost in integer cents. While `DRAFT`, the director may patch `kit_name`, `vendor`, `quantity`, or `unit_cost_cents` — each edit increments the order's `version` by one — and editing a non-`DRAFT` order fails with `ERR_INVALID_STATE`. Submitting moves `DRAFT` → `SUBMITTED` and enforces the final kit requirement at submit time: a `quantity` below `required_final` is rejected with `ERR_KIT_QUANTITY_SHORT`. A submitted order can be returned for revision (`SUBMITTED` → `DRAFT`), cancelled (`DRAFT` or `SUBMITTED` → `CANCELLED`), or approved. Approval re-checks the budget at approval time: `total_cost_cents` must not exceed `budget_remaining_cents`, or the approve fails with `ERR_BUDGET_EXCEEDED` (HTTP 402).

The budget itself is derived: `budget_remaining_cents` is the program's `supply_budget_cents` minus the sum of `total_cost_cents` over the program's `APPROVED` orders only — `DRAFT`, `SUBMITTED`, and `CANCELLED` orders consume nothing — so a successful approval lowers the remaining budget by exactly the approved total.

The supply-plan read rolls all of this up for a program: `enrolled_total`, the non-`CLOSED` `classroom_count`, `kit_quantity_provisional`, `kit_quantity_final`, `craft_packs_required` with its per-classroom breakdown `craft_packs_per_classroom`, and `budget_remaining_cents`. The breakdown `craft_packs_per_classroom` is a list with one row per non-`CLOSED` classroom in classroom creation order, each row carrying that classroom's `classroom_id` and its rounded pack count under `packs`. Craft packs follow a pinned rounding order — round per classroom first, then sum: for each classroom not `CLOSED`, multiply its `enrolled_count` by 3 craft units per child and round up to whole packs of 10; the program total is the sum of those per-classroom pack counts. Pooling first would under-order: two classrooms of four enrolled children each need twelve units apiece, rounding up to two packs per classroom and four in total — whereas pooling the twenty-four units first would round up to three.

The stock room tracks one `SupplyItem` per stocked good: `program_id`, `name`, a `category` of `SNACK` or `CRAFT`, a stocking `unit` label (pack, box, bottle), the physical `quantity_on_hand` (zero or more, set at creation), optional `allergen_tags` drawn from the allergen enum (default empty, meaningful for snack items), and an advisory `restock_threshold` low-water mark (zero or more, default 0). On-hand changes in only two ways after creation: a restock adds the supplied `additional_quantity` (at least 1) to `quantity_on_hand` and increments the item's `version` by one, and a distribution issue subtracts. Two quantities derive continuously: `reserved_quantity`, the sum of `quantity` over the item's `PLANNED` distributions, and `available_quantity`, the on-hand minus the reserved.

Distribution moves stock from shelf to classroom on a given day. A `ProgramDirector` or `RegistrationCoordinator` plans a distribution with `supply_item_id`, `classroom_id`, `program_day_id`, and `quantity` (at least 1); the plan is born `PLANNED` and immediately reserves its quantity — `reserved_quantity` rises by `quantity`. Planning is gated, in pipeline order: the body references are validated in payload order — item, then classroom, then day — each missing reference reporting `ERR_NOT_FOUND`; when the item is a snack, any overlap between the item's `allergen_tags` and the target classroom's blocked-allergen set of §3.5 rejects the plan with `ERR_ALLERGEN_CONFLICT`; the referenced day must be `SCHEDULED` or `OPEN` (`ERR_INVALID_STATE`); item, classroom, and day must all belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`); and `quantity` must not exceed the item's `available_quantity` (`ERR_INSUFFICIENT_STOCK`). Issuing moves `PLANNED` → `ISSUED`: `quantity_on_hand` and `reserved_quantity` each drop by `quantity`, and `issued_at` is stamped. Cancelling moves `PLANNED` → `CANCELLED`: the reservation releases — `reserved_quantity` drops by `quantity` — while on-hand stays untouched, the compensating mirror of planning.

### 3.7. Program Days: Opening Gates, Check-In, Security Tags, and Pickup

Each morning the `ProgramDirector` opens the program day. Opening is gated on four fronts: the day must be `SCHEDULED` and the program `IN_SESSION` (`ERR_INVALID_STATE`); the day's `date` must equal the current logical date (`ERR_DAY_NOT_TODAY`); and every classroom of the program with `enrolled_count` above zero must show `staffing_status` `ADEQUATE` (`ERR_STAFFING_INADEQUATE`) — the safety gate outranking the state and temporal gates when several fail together. A successful open moves `SCHEDULED` → `OPEN`, sets the program's `current_day_index` to the day's `day_index`, and pre-creates an attendance record in `NOT_ARRIVED` for every `ENROLLED` registration of the program.

Check-in is a `CheckInStaff` act carrying a `child_id` and a `program_day_id`. Its gates fire in pipeline order: the safety gate first — a child with `has_special_needs` true must hold an `APPROVED` accommodation plan, failing with `ERR_ACCOMMODATION_NOT_APPROVED`; then state — the day must be `OPEN` and the record `NOT_ARRIVED`, failing with `ERR_INVALID_STATE`; then enrollment — the child must hold an `ENROLLED` registration for the day's program, failing with `ERR_NOT_ENROLLED`. When no attendance record exists for the child on that day at all, it is the enrollment check that decides the error. A successful check-in moves the record `NOT_ARRIVED` → `CHECKED_IN`, stamps `checked_in_at` and `checked_in_by` from the caller, and mints a security tag: an `ISSUED` tag for the child and day whose `tag_code` the record copies. Check-in is classified as a creation and returns 201 with the attendance record as `data`.

Tag codes are six digits, zero-padded, assigned deterministically per program day in issuance order starting at 000001, and unique among the day's non-`VOIDED` tags. When a printed tag is lost, staff reprint it for a `CHECKED_IN` child: the active tag moves `ISSUED` → `VOIDED` with `void_reason` `REPRINT`, a replacement `ISSUED` tag takes the next sequence value for the day, the record's `tag_code` updates to the new code, and the response carries the updated attendance record. The tag lifecycle also declares a voiding path at day close, but it is unreachable by construction — close is blocked while any child is `CHECKED_IN`, and a tag exists only for a `CHECKED_IN` child — so `void_reason` is null unless the tag is `VOIDED`, and in practice only ever `REPRINT`.

Checkout presents the day's tag: staff submit `child_id`, `program_day_id`, the presented `tag_code`, and the `pickup_person` name. The record must be `CHECKED_IN` (`ERR_INVALID_STATE`), and the presented code is matched against the day's tags for that child: matching a `VOIDED` or `REDEEMED` tag fails with `ERR_TAG_NOT_ACTIVE`; matching no tag at all fails with `ERR_TAG_MISMATCH`; only a code on an `ISSUED` tag proceeds. A successful checkout moves the record `CHECKED_IN` → `CHECKED_OUT`, stamps `checked_out_at`, `checked_out_by`, and `pickup_person`, computes `late_pickup`, and redeems the matched tag — `ISSUED` → `REDEEMED` with `redeemed_at` stamped.

`late_pickup` reads false until a checkout computes it, then compares the checkout instant against the cutoff formed by the day's `date` and the program's `pickup_cutoff_time`: a checkout strictly after the cutoff is late; a checkout exactly at the cutoff is not late.

Closing the day requires that no child remain on site — any record in `CHECKED_IN` blocks the close with `ERR_CHILDREN_ON_SITE` — and moves `OPEN` → `CLOSED`, transitions every record still `NOT_ARRIVED` to `ABSENT`, and resets the program's `current_day_index` to 0. Day counters derive continuously: `checked_in_count` counts the day's records in `CHECKED_IN` or `CHECKED_OUT`, `checked_out_count` counts those in `CHECKED_OUT`, and `absent_count` counts those in `ABSENT`. Every record also carries `registration_id`, the `ENROLLED` registration backing it, alongside its `child_id` and `program_day_id`.

Mid-program, a per-child attendance summary reports `attended_days` (records in `CHECKED_OUT`), `days_closed`, `total_days`, and two rates, each rounded half-up to four decimal places: `provisional_rate`, attended days divided by days closed so far — zero when no day has closed, so a mid-program child with perfect attendance reads 1.0000 — and `projected_final_rate`, attended days divided by all program days regardless of status — zero when the program has no days. Whenever unclosed days remain, the projected figure sits below the provisional one for identical attendance data.

### 3.8. Family Messaging, Close-Out, and Next-Year Retention

A `ProgramDirector` drafts a `FamilyMessage` with `program_id`, `subject`, `body`, and an `audience` of `ALL_FAMILIES`, `CLASSROOM`, `ALLERGY_ALERT`, or `VOLUNTEERS`; `classroom_id` is required exactly when the audience is `CLASSROOM` and forbidden otherwise (`ERR_INVALID_REQUEST`). The draft stands in `DRAFT` with `recipient_count` 0 until sent. Sending requires `DRAFT` (`ERR_INVALID_STATE` otherwise), resolves recipients at send time, stamps `sent_at`, and stores the count: for `ALL_FAMILIES`, the distinct families with at least one child holding an `ENROLLED`, `WAITLISTED`, or `OFFERED` registration in the program; for `CLASSROOM`, the same rule restricted to registrations in the message's classroom; for `ALLERGY_ALERT`, the distinct families with at least one child holding an `APPROVED` `FOOD_ALLERGY` plan and an `ENROLLED` registration in the program; for `VOLUNTEERS`, the program's volunteers in `CLEARED`. Family-level dedup applies throughout: one recipient per family no matter how many qualifying children it has. Cancelling moves `DRAFT` → `CANCELLED`.

Once every day is `CLOSED`, the director completes the program, and with the program `COMPLETED` the retention list can be generated: one `RetentionEntry` per child with at least one `CHECKED_OUT` day, each born `LISTED`. Regenerating while entries already exist is rejected with `ERR_RETENTION_EXISTS` unless the caller passes `force` true, which regenerates entries still `LISTED` or `INVITED` and preserves those already `RESPONDED_YES` or `RESPONDED_NO`; the response reports `created_count` and whether the run was a `regenerated` one.

Each entry derives three values. `attended_days` counts the child's `CHECKED_OUT` records in the program. `attendance_rate` is the final variant of §3.7: attended days divided by total program days, rounded half-up to four decimal places. `family_volunteer_bonus` is true when some volunteer whose `family_id` equals the child's family holds an assignment that reached `CONFIRMED` — whether still `CONFIRMED` or since `RELEASED`. From these, `priority_tier`: tier `A` when the rate is at least 0.80, or at least 0.60 with the bonus; otherwise tier `B` when the rate is at least 0.50, or the bonus holds at any rate; otherwise tier `C`. The comparisons are inclusive against the four-decimal rounded rate — 0.8000 earns `A`; 0.7999 does not. The director then works the list: inviting moves `LISTED` → `INVITED`, and recording a response with `outcome` `YES` or `NO` moves `INVITED` → `RESPONDED_YES` or `INVITED` → `RESPONDED_NO`; every other state pairing fails with `ERR_INVALID_STATE`. With responses in hand, the program archives and the season closes.

## 4. Endpoint Definitions

All endpoints are mounted under `/vbs`. Endpoints that create a new resource return 201; reads, modifications, and action operations return 200. Check-in is classified as a creation — it mints a new security tag — and returns 201; retention-list generation likewise returns 201. Error responses follow §2.2 with the codes of §5. Request and response field semantics are defined by the narratives of §2 and §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/vbs/programs` | Create a program (`DRAFT`) | ProgramDirector |
| GET | `/vbs/programs` | List programs; filter `status` | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff |
| GET | `/vbs/programs/{program_id}` | Get one program | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff, Parent, Volunteer |
| POST | `/vbs/programs/{program_id}/open-registration` | `DRAFT` → `REGISTRATION_OPEN`; flips `SETUP` classrooms | ProgramDirector |
| POST | `/vbs/programs/{program_id}/close-registration` | `REGISTRATION_OPEN` → `REGISTRATION_CLOSED` | ProgramDirector |
| POST | `/vbs/programs/{program_id}/start-session` | `REGISTRATION_CLOSED` → `IN_SESSION`; needs a day | ProgramDirector |
| POST | `/vbs/programs/{program_id}/complete` | `IN_SESSION` → `COMPLETED`; needs all days closed | ProgramDirector |
| POST | `/vbs/programs/{program_id}/archive` | `COMPLETED` → `ARCHIVED`; program read-only | ProgramDirector |
| POST | `/vbs/programs/{program_id}/sweep-expired-offers` | Expire stale offers; run the waterfall (OCC) | RegistrationCoordinator |
| GET | `/vbs/programs/{program_id}/supply-plan` | Computed kit, craft, and budget rollup | ProgramDirector, RegistrationCoordinator |
| GET | `/vbs/programs/{program_id}/attendance-summaries/{child_id}` | Per-child attendance counters and rates | ProgramDirector, RegistrationCoordinator, SafetyOfficer, Parent |
| POST | `/vbs/classrooms` | Create a classroom (`SETUP` or `ACCEPTING`) | RegistrationCoordinator |
| GET | `/vbs/classrooms/{classroom_id}` | Get one classroom | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff, Parent, Volunteer |
| GET | `/vbs/classrooms` | List classrooms; filters `program_id`, `status` | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff, Parent |
| PATCH | `/vbs/classrooms/{classroom_id}` | Edit capacity or age band (OCC) | RegistrationCoordinator |
| POST | `/vbs/classrooms/{classroom_id}/close` | Close a classroom; cancel its queue; release staff | RegistrationCoordinator |
| POST | `/vbs/families` | Household self-registration | Anonymous |
| GET | `/vbs/families/{family_id}` | Get one family | ProgramDirector, RegistrationCoordinator, SafetyOfficer, Parent |
| GET | `/vbs/families` | List families; filters `email`, `include_archived` | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/families/{family_id}/archive` | Soft-delete a family with registration cascade | RegistrationCoordinator |
| POST | `/vbs/children` | Register a child into a family | Parent, RegistrationCoordinator |
| GET | `/vbs/children/{child_id}` | Get one child | ProgramDirector, RegistrationCoordinator, SafetyOfficer, CheckInStaff, Parent |
| GET | `/vbs/children` | List children; filter `family_id` | ProgramDirector, RegistrationCoordinator, SafetyOfficer, CheckInStaff, Parent |
| POST | `/vbs/registrations` | Create a registration (`ENROLLED` or `WAITLISTED`) | Parent, RegistrationCoordinator |
| GET | `/vbs/registrations/{registration_id}` | Get one registration | ProgramDirector, RegistrationCoordinator, Parent |
| GET | `/vbs/registrations` | List registrations; filters `child_id`, `classroom_id`, `status` | ProgramDirector, RegistrationCoordinator, Parent |
| POST | `/vbs/registrations/{registration_id}/cancel` | Cancel an `ENROLLED` or `WAITLISTED` registration | Parent, RegistrationCoordinator |
| POST | `/vbs/registrations/{registration_id}/accept` | Accept a waitlist offer | Parent |
| POST | `/vbs/registrations/{registration_id}/decline` | Decline a waitlist offer | Parent |
| POST | `/vbs/volunteers` | Volunteer self-application | Anonymous |
| GET | `/vbs/volunteers/{volunteer_id}` | Get one volunteer | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, Volunteer |
| GET | `/vbs/volunteers` | List volunteers; filters `program_id`, `family_id`, `status` | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer |
| POST | `/vbs/screening-checks` | Submit a screening check | Volunteer, VolunteerCoordinator |
| POST | `/vbs/screening-checks/{check_id}/decide` | Decide a `SUBMITTED` check | SafetyOfficer |
| POST | `/vbs/screening-checks/{check_id}/resubmit` | Resubmit an `INFO_REQUESTED` check | Volunteer |
| GET | `/vbs/screening-checks/{check_id}` | Get one screening check | VolunteerCoordinator, SafetyOfficer, Volunteer |
| GET | `/vbs/screening-checks` | List screening checks; filters `volunteer_id`, `status` | VolunteerCoordinator, SafetyOfficer |
| POST | `/vbs/role-assignments` | Propose a role assignment (`PROPOSED`) | VolunteerCoordinator, Volunteer |
| POST | `/vbs/role-assignments/{assignment_id}/confirm` | Confirm a `PROPOSED` assignment | VolunteerCoordinator |
| POST | `/vbs/role-assignments/{assignment_id}/release` | Release a `CONFIRMED` assignment | VolunteerCoordinator |
| GET | `/vbs/role-assignments/{assignment_id}` | Get one role assignment | ProgramDirector, VolunteerCoordinator, SafetyOfficer, Volunteer |
| GET | `/vbs/role-assignments` | List assignments; filters `volunteer_id`, `classroom_id`, `status` | VolunteerCoordinator, SafetyOfficer |
| POST | `/vbs/accommodation-plans` | Create an accommodation plan (`DRAFT`) | Parent, SafetyOfficer |
| POST | `/vbs/accommodation-plans/{plan_id}/submit` | `DRAFT`/`NEEDS_REVISION` → `SUBMITTED` | Parent |
| POST | `/vbs/accommodation-plans/{plan_id}/approve` | `SUBMITTED` → `APPROVED`; supersedes siblings (OCC) | SafetyOfficer |
| POST | `/vbs/accommodation-plans/{plan_id}/request-revision` | `SUBMITTED` → `NEEDS_REVISION` | SafetyOfficer |
| GET | `/vbs/accommodation-plans/{plan_id}` | Get one plan | SafetyOfficer, Parent, CheckInStaff |
| GET | `/vbs/accommodation-plans` | List plans; filters `child_id`, `status` | SafetyOfficer, CheckInStaff, Parent |
| POST | `/vbs/supply-orders` | Create a kit order (`DRAFT`) | ProgramDirector |
| PATCH | `/vbs/supply-orders/{order_id}` | Edit a `DRAFT` order | ProgramDirector |
| POST | `/vbs/supply-orders/{order_id}/submit` | `DRAFT` → `SUBMITTED` with kit-quantity gate | ProgramDirector |
| POST | `/vbs/supply-orders/{order_id}/return-for-revision` | `SUBMITTED` → `DRAFT` | ProgramDirector |
| POST | `/vbs/supply-orders/{order_id}/approve` | `SUBMITTED` → `APPROVED` with budget gate | ProgramDirector |
| POST | `/vbs/supply-orders/{order_id}/cancel` | `DRAFT`/`SUBMITTED` → `CANCELLED` | ProgramDirector |
| GET | `/vbs/supply-orders/{order_id}` | Get one order | ProgramDirector, RegistrationCoordinator |
| GET | `/vbs/supply-orders` | List orders; filters `program_id`, `status` | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/supply-items` | Create a stock item | ProgramDirector |
| GET | `/vbs/supply-items/{item_id}` | Get one item | ProgramDirector, RegistrationCoordinator, SafetyOfficer |
| GET | `/vbs/supply-items` | List items; filters `program_id`, `category` | ProgramDirector, RegistrationCoordinator, SafetyOfficer |
| POST | `/vbs/supply-items/{item_id}/restock` | Add stock | ProgramDirector |
| POST | `/vbs/supply-distributions` | Plan a distribution (reserves stock) | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/supply-distributions/{distribution_id}/issue` | `PLANNED` → `ISSUED` | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/supply-distributions/{distribution_id}/cancel` | `PLANNED` → `CANCELLED` | ProgramDirector, RegistrationCoordinator |
| GET | `/vbs/supply-distributions/{distribution_id}` | Get one distribution | ProgramDirector, RegistrationCoordinator, SafetyOfficer |
| GET | `/vbs/supply-distributions` | List distributions; filters `supply_item_id`, `classroom_id`, `program_day_id`, `status` | ProgramDirector, RegistrationCoordinator, SafetyOfficer |
| POST | `/vbs/days` | Append a program day (`SCHEDULED`) | ProgramDirector |
| POST | `/vbs/days/{day_id}/open` | `SCHEDULED` → `OPEN`; pre-create attendance | ProgramDirector |
| POST | `/vbs/days/{day_id}/close` | `OPEN` → `CLOSED`; mark absences | ProgramDirector |
| GET | `/vbs/days/{day_id}` | Get one program day | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff |
| GET | `/vbs/days` | List program days; filters `program_id`, `status` | ProgramDirector, RegistrationCoordinator, VolunteerCoordinator, SafetyOfficer, CheckInStaff |
| POST | `/vbs/attendance/check-in` | Check a child into an `OPEN` day; mint a tag | CheckInStaff |
| POST | `/vbs/attendance/check-out` | Check a child out against the active tag | CheckInStaff |
| POST | `/vbs/attendance/reprint-tag` | Void the active tag (`REPRINT`) and issue a replacement | CheckInStaff |
| GET | `/vbs/attendance/{record_id}` | Get one attendance record | ProgramDirector, RegistrationCoordinator, SafetyOfficer, CheckInStaff, Parent |
| GET | `/vbs/attendance` | List attendance; filters `child_id`, `program_day_id`, `registration_id`, `status` | ProgramDirector, RegistrationCoordinator, SafetyOfficer, CheckInStaff |
| GET | `/vbs/security-tags/{tag_id}` | Get one security tag | ProgramDirector, SafetyOfficer, CheckInStaff |
| GET | `/vbs/security-tags` | List tags; filters `child_id`, `program_day_id`, `status` | ProgramDirector, SafetyOfficer, CheckInStaff |
| POST | `/vbs/messages` | Draft a family message | ProgramDirector |
| POST | `/vbs/messages/{message_id}/send` | `DRAFT` → `SENT`; resolve recipients | ProgramDirector |
| POST | `/vbs/messages/{message_id}/cancel` | `DRAFT` → `CANCELLED` | ProgramDirector |
| GET | `/vbs/messages/{message_id}` | Get one message | ProgramDirector, RegistrationCoordinator |
| GET | `/vbs/messages` | List messages; filters `program_id`, `classroom_id`, `status` | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/programs/{program_id}/retention-list/generate` | Generate the retention list at `COMPLETED` | ProgramDirector |
| GET | `/vbs/retention-entries/{entry_id}` | Get one retention entry | ProgramDirector, RegistrationCoordinator |
| GET | `/vbs/retention-entries` | List entries; filters `program_id`, `child_id`, `priority_tier`, `status` | ProgramDirector, RegistrationCoordinator |
| POST | `/vbs/retention-entries/{entry_id}/invite` | `LISTED` → `INVITED` | ProgramDirector |
| POST | `/vbs/retention-entries/{entry_id}/record-response` | `INVITED` → `RESPONDED_YES`/`RESPONDED_NO` | ProgramDirector |
| POST | `/vbs/_clock/set_current_utc` | Advance the logical clock | ProgramDirector |

## 5. Error Code Catalogue

Trigger conditions for each code are defined in the narratives of §2 and §3; this table is the identifier-to-status contract.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SELF_REVIEW_FORBIDDEN` | 403 |
| `ERR_ACCOMMODATION_NOT_APPROVED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 409 |
| `ERR_STAFFING_INADEQUATE` | 409 |
| `ERR_CHILDREN_ON_SITE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_PROGRAM_DATE_OVERLAP` | 409 |
| `ERR_DAY_NOT_SEQUENTIAL` | 409 |
| `ERR_DAY_OUT_OF_RANGE` | 409 |
| `ERR_DAY_NOT_TODAY` | 409 |
| `ERR_AGE_OUT_OF_RANGE` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_CHECK` | 409 |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 |
| `ERR_LEAD_TEACHER_TAKEN` | 409 |
| `ERR_VOLUNTEER_DOUBLE_BOOKED` | 409 |
| `ERR_MINOR_ROLE_FORBIDDEN` | 422 |
| `ERR_CLASSROOM_NOT_EMPTY` | 409 |
| `ERR_CAPACITY_BELOW_ENROLLED` | 409 |
| `ERR_CLASSROOM_FULL` | 409 |
| `ERR_NO_PROGRAM_DAYS` | 409 |
| `ERR_DAYS_STILL_OPEN` | 409 |
| `ERR_RETENTION_EXISTS` | 409 |
| `ERR_TAG_MISMATCH` | 409 |
| `ERR_TAG_NOT_ACTIVE` | 409 |
| `ERR_NOT_ENROLLED` | 409 |
| `ERR_FAMILY_ARCHIVED` | 409 |
| `ERR_VOLUNTEER_NOT_CLEARED` | 409 |
| `ERR_CROSS_PROGRAM_REFERENCE` | 409 |
| `ERR_BUDGET_EXCEEDED` | 402 |
| `ERR_KIT_QUANTITY_SHORT` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
