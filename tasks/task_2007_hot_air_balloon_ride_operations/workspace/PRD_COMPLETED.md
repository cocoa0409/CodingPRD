# Hot Air Balloon Ride Operations API — Product Requirements Document

## 1. Introduction

A commercial hot air balloon operator in Albuquerque lives and dies by a ninety-minute dawn window. Every morning flight is the convergence of four scarce resources — a launch site whose landowner permission must still be valid, an aircraft whose annual inspection must not have lapsed, a pilot whose recency-of-flight currency must satisfy both federal-style and operator-internal yardsticks, and a basket whose seats and lift capacity are sold weeks in advance. When any one of those resources falls through — a gusty cold front, a grounded envelope, a landowner who revokes access — the operator does not merely scrub a flight; it must unwind every reservation, every dollar collected, and every goodwill promise attached to that flight, in a consistent and auditable way.

This document specifies the Hot Air Balloon Ride Operations API, the system of record for that entire operating loop. It covers launch-site permission lifecycles, balloon registration and inspection tracking, pilot currency computation, flight composition and publication, a wind-margin-ranked site selector, shared-basket and whole-basket charter pricing, dawn weather review with a computed go/no-go decision, passenger check-in with weight-and-balance enforcement, chase crew coordination through landing recovery, and a refund pipeline with policy-driven amounts, wallet credits, and operator goodwill. The API is mounted under the `/v1` prefix and is consumed by the operations desk, assigned pilots, paying customers, and chase crew leads.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across the API: identity and access, response envelopes, pagination, resource metadata, the logical clock, monetary precision, concurrency control, cascade consistency, and the order in which requests are validated.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes five roles, spelled exactly as follows: `OperationsManager`, `Pilot`, `Customer`, `ChaseCrewLead`, and `Anonymous`. A request that arrives without both headers, or whose role value is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list — including a request whose `event_type` belongs to a different role's slice of a shared events endpoint — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot`; ownership checks on any resource that references a pilot — chiefly a flight's `pilot_id` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FLIGHT_NOT_ASSIGNED` (HTTP 403). When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer — a reservation's `customer_id` — compare that field to `X-User-ID`, and a mismatch is rejected with `ERR_RESERVATION_NOT_OWNED` (HTTP 403).

The remaining three roles are opaque. When `X-User-Role` is `OperationsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same holds for `ChaseCrewLead` and for `Anonymous`. The server does not compare those identifiers to any entity's `id`. The `Anonymous` role exists solely so an unauthenticated visitor can self-register as a customer; it authorizes no other operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100 — a non-integer `limit`, or an integer outside that range, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than clamped. The `offset` parameter sets the number of items skipped and defaults to 0; a non-integer or negative `offset` is likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is still below `total_count`.

### 2.4. Common Resource Properties

Every primary resource — launch sites, balloons, pilots, customers, flights, reservations, chase assignments, and refunds — exposes a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation of the resource; it backs the optimistic concurrency checks described in §2.7.

Three resources are deliberately lighter-weight because they are immutable, append-only records: a `Passenger` manifest entry, a `WeatherBriefing` observation, and a `PhotoPackageRecord`. These three carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock

All temporal reasoning in the system — dawn-window containment, permission and inspection expiry, pilot currency windows, cancellation deadlines — is evaluated against a server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never silently falls back to the host's wall clock thereafter. An `OperationsManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Everywhere this document says "now", it means the logical clock's current instant; everywhere it says "today" or "the current date", it means the date portion of that instant. Business timestamps — `permission_granted_at`, `observed_at`, `weather_decision_at`, `paid_at`, and `delivered_at` — are stamped from this logical clock, while the `created_at`/`updated_at` metadata of §2.4 and the envelope's `api_request_timestamp` come from the host wall clock. The clock-advance operation responds with an object carrying the new instant as `current_utc`.

### 2.6. Money, Weights, and Precision

All monetary amounts in the system are integer cents. Wherever a division or multiplication in a fare, refund, or credit computation produces a fractional cent, the result is rounded half-up to the nearest integer cent. The rounding order pinned by each calculation in §3 is part of the specification: rounding per passenger first and then multiplying is a different answer from multiplying first and rounding the total, and only the order stated in §3 is correct. Weight figures (`weight_lbs`, `declared_weight_lbs`, payload figures) are integer pounds. Flight durations and pilot experience hours are numbers carried to one decimal place; counts such as takeoffs-and-landings are integers. Wind figures — the site limits `surface_wind_limit_kts` and `aloft_wind_limit_kts` and the observed `surface_wind_kts` and `aloft_wind_kts` — are integer knots, while `visibility_mi` is a number. Unless a workflow states otherwise, every numeric input field must be non-negative — and `party_size`, `basket_capacity_passengers`, `max_gross_weight_lbs`, and `crew_size` must be at least 1 — with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, because in each case a stale write is a legitimate-looking product operation that cannot be detected from state alone — only from a version check:

- Changing a flight's launch site requires the request to carry `expected_flight_version`, holding the client's last-observed `version` of the flight. If the flight's current `version` has advanced past that value, the write is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Recording a balloon inspection requires the request to carry `expected_balloon_version`, holding the client's last-observed `version` of the balloon. If the balloon's current `version` no longer matches, the write is rejected with `ERR_STALE_VERSION` (HTTP 412).

Both fields are mandatory on their respective operations. No other endpoint takes a version field; clients must not supply one elsewhere.

### 2.8. Cascade Consistency

A flight is never cancelled in isolation. When a flight reaches `CANCELLED` — whether by operator decision, by a weather no-go that the operator chooses not to reschedule, or by its balloon being grounded — the system walks every attached reservation whose `booking_status` is `PENDING`, `CONFIRMED`, or `CHECKED_IN`, cancels it with the reason dictated by the cascade, and auto-creates a policy-computed `Refund` for each such reservation that had already paid. These cascades are immediate: every effect is visible within the same request/response that triggered it. Each mutation — the flight's own transition, each reservation's cancellation, each computed field that changes as a consequence — refreshes that resource's `updated_at` and increments its `version`. A related one-directional rule governs weather observations: at most one briefing per flight may hold `RECORDED` status at a time, because recording a newer briefing automatically supersedes the older one.

### 2.9. Request Validation Order and Nested Resource Retrieval

Every request passes through a fixed validation pipeline, and earlier failures mask later ones. The order is:

1. Authentication: the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted on this endpoint, and on shared events endpoints the `event_type` belongs to the acting role's slice (`ERR_UNAUTHORIZED`).
3. Path existence, validated left to right: for a nested path such as a reservation's passenger collection, the parent identifier is resolved first and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource.
4. Body shape: the body is valid JSON, all required fields are present with the right types, enum fields take only their declared values, and — where a dawn window is supplied — the window is exactly ninety minutes long with its start's date portion equal to the flight's `scheduled_date` (`ERR_INVALID_REQUEST`, HTTP 400). Identifiers carried in the request body rather than the path (a flight's `launch_site_id`/`balloon_id`/`pilot_id`, a booking's `customer_id`, a site change's `launch_site_id`) are resolved at the end of this step, and an unresolvable body reference is rejected with `ERR_NOT_FOUND` (HTTP 404). Body fields an operation does not declare are ignored. On the shared events endpoints only `event_type` is validated at this step; each event's own payload fields are validated inside its handler — for the customer-owned reservation events that is after the step-6 ownership check, and for `LAND` it is after the step-7 from-state check.
5. Optimistic concurrency: on the two OCC-guarded writes of §2.7, the expected version matches the parent's current `version` (`ERR_STALE_VERSION`).
6. Ownership: an entity-backed actor owns the target — a customer matches the reservation's `customer_id`, a pilot matches the flight's `pilot_id` (`ERR_RESERVATION_NOT_OWNED` or `ERR_FLIGHT_NOT_ASSIGNED`).
7. From-state validity: the resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`, HTTP 409).
8. Business rules, in the order each workflow in §3 states them.

### 2.10. Pilot Currency Governance

A pilot may only be published onto a flight when their recency-of-experience satisfies two independent yardsticks at once, and the system computes both from a mixture of self-reported external experience and this operator's own closed flights. At registration the operator records the pilot's `external_pic_hours_180d` (pilot-in-command hours flown elsewhere in the trailing 180 days, defaulting to 0) and `external_takeoffs_landings_90d` (takeoffs and landings flown elsewhere in the trailing 90 days, defaulting to 0). The system adds to these the operator-internal figures: `internal_pic_hours_180d` is the sum of `duration_hours` over this operator's `CLOSED` flights flown by this pilot whose `scheduled_date` falls within the trailing 180 days relative to the logical clock's current date, and `internal_takeoffs_landings_90d` is the count of this operator's `CLOSED` flights for this pilot whose `scheduled_date` falls within the trailing 90 days. Both trailing windows include their endpoints: a `scheduled_date` qualifies when it falls on or after the current date minus the window length and on or before the current date.

Two totals derive from those four figures: `pic_hours_180d_total` is the sum of `external_pic_hours_180d` and `internal_pic_hours_180d`, and `takeoffs_landings_90d_total` is the sum of `external_takeoffs_landings_90d` and `internal_takeoffs_landings_90d`. The FAA-style check, `faa_currency_met`, is true exactly when `takeoffs_landings_90d_total` is at least 3 — it looks at the takeoffs-and-landings count only and ignores hours entirely. The operator's rolling-hours check, `operator_currency_met`, is true exactly when `pic_hours_180d_total` is at least 12.0 hours — it looks at hours only and ignores the takeoffs-and-landings count, so the two methods can diverge on the same pilot record. The pilot's `currency_status` is `CURRENT` when both checks are met and `EXPIRED` otherwise. These fields are recomputed whenever a pilot record is read, whenever a flight is published, and at flight closeout, when the just-closed flight begins contributing to the internal figures.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Operation: Launch Sites, Fleet, Pilots, and Customers

Before any seat can be sold, the operations desk builds up four registries. An `OperationsManager` creates each launch site with its display `name`, two wind tolerances — `surface_wind_limit_kts` for the maximum surface wind and `aloft_wind_limit_kts` for the maximum winds aloft the site tolerates — the `per_use_fee_cents` landowner fee recorded against each published flight that uses the site (the fee is a stored attribute of the site; the API computes no charge from it), and a `permission_expires_on` ISO date after which the landowner's permission lapses. A new site's `permission_status` starts at `PENDING`. Granting landowner permission moves it to `GRANTED` and stamps `permission_granted_at` with the logical clock's current instant (the field stays null until the first grant); revoking permission moves a `GRANTED` site to `REVOKED`; and a revoked site can be re-granted, which again refreshes `permission_granted_at`. `PENDING` and `REVOKED` sites are never eligible for flight operations.

Balloons are registered by an `OperationsManager` with their FAA tail number in `registration`, the basket's `basket_capacity_passengers` seat count, the certified `max_gross_weight_lbs` covering envelope, basket, fuel, and passengers together, and the `empty_weight_lbs` of the aircraft without fuel or passengers. A new balloon starts `ACTIVE`. The operations desk records each annual inspection through the balloon's event stream with an `inspected_on` date; that write is one of the two OCC-guarded operations in §2.7 and must carry `expected_balloon_version`. Recording an inspection sets `last_inspection_on` to the supplied date, recomputes `inspection_due_on` as exactly 365 days after `last_inspection_on`, and increments the balloon's `version`. Until a balloon's first inspection, both `last_inspection_on` and `inspection_due_on` are null. When an aircraft must be taken out of service, grounding it moves its `status` from `ACTIVE` to `GROUNDED` and triggers the aircraft cascade described in §3.7. Returning a grounded balloon to service requires that `last_inspection_on` is present and that `inspection_due_on` falls on or after the current date; a balloon that fails either condition is rejected with `ERR_BALLOON_GROUNDED` (HTTP 409).

Pilots are registered with their full `name`, FAA `certificate_number`, the `medical_expires_on` date of their medical certificate, and optionally their externally logged experience — `external_pic_hours_180d` and `external_takeoffs_landings_90d`, both defaulting to 0. The currency fields of §2.10 are computed at registration and kept current thereafter. Customers self-register as `Anonymous` by supplying a `name` and `email`; the account opens with `wallet_credit_cents` at 0, a balance that later grows through fare overpayment settle-downs, goodwill credits, and refunds paid out as wallet credit.

### 3.2. Composing and Publishing a Flight

A flight begins life in `DRAFT`. An `OperationsManager` composes it by choosing a `scheduled_date`, a dawn launch window (`dawn_window_start` and `dawn_window_end` as ISO 8601 UTC instants), the `launch_site_id`, the `balloon_id`, the `pilot_id`, and the flight's `kind` — `SHARED` for per-seat shared-basket sales or `CHARTER` for a whole-basket booking. The dawn window must be exactly ninety minutes long, and the date portion of `dawn_window_start` must equal `scheduled_date`; a window that violates either rule is rejected with `ERR_INVALID_REQUEST`. `fuel_lbs` may be supplied to override the default 200 pounds of fuel. A new flight opens with `weather_decision` `NONE` and with `weather_decision_at`, `cancel_reason`, and `duration_hours` all null. At creation the system derives the flight's `season_tier`: `PEAK` when `scheduled_date` falls within October 1 through October 14 — the Balloon Fiesta window — and `REGULAR` otherwise.

Publishing the draft is the most heavily guarded transition in the system. An `OperationsManager` publishes a flight, moving `status` from `DRAFT` to `SCHEDULED`, only when a five-part precondition battery passes, evaluated in this order:

1. **Site permission.** The launch site's `permission_status` is `GRANTED` and its `permission_expires_on` falls on or after `scheduled_date`; otherwise the publish is rejected with `ERR_SITE_PERMISSION_NOT_GRANTED` (HTTP 409).
2. **Aircraft readiness.** The balloon's `status` is `ACTIVE`, its `inspection_due_on` is not null, and `inspection_due_on` falls on or after `scheduled_date`; otherwise `ERR_BALLOON_GROUNDED`.
3. **Pilot currency.** The pilot's `currency_status` is `CURRENT` per §2.10; otherwise `ERR_PILOT_NOT_CURRENT` (HTTP 409).
4. **Balloon schedule.** No other flight using the same `balloon_id` and sitting in `SCHEDULED`, `WEATHER_REVIEW`, `CLEARED_FOR_LAUNCH`, or `AIRBORNE` has a dawn window that overlaps this flight's window, where overlap is judged on the half-open interval from `dawn_window_start` (inclusive) to `dawn_window_end` (exclusive) — two windows that merely touch at an endpoint do not conflict. A violating overlap is rejected with `ERR_BALLOON_SCHEDULE_CONFLICT` (HTTP 409).
5. **Pilot schedule.** No other flight using the same `pilot_id` in those same four states shares this flight's `scheduled_date`; otherwise `ERR_PILOT_SCHEDULE_CONFLICT` (HTTP 409).

When several committed flights conflict at once, the two schedule checks walk the committed flights in creation order and report the first conflict found; a single flight that trips both rules reports the balloon conflict.

A successful publish increments the flight's `version`. Flights can be listed with optional reverse-lookup filters on `launch_site_id`, `balloon_id`, `pilot_id`, and `status`, so the desk can see everything committed against a site, an aircraft, or a pilot.

### 3.3. Launch-Site Selection and the Wind-Margin Ranking

While a flight is `SCHEDULED` or in `WEATHER_REVIEW`, an `OperationsManager` may change its launch site. The write names an explicit `launch_site_id`, or omits it to let the system's selector choose. Either way the request must carry `expected_flight_version` per §2.7, and a stale value is rejected with `ERR_STALE_VERSION`. An explicit choice is validated like a publish: the site must be `GRANTED` with `permission_expires_on` on or after the flight's `scheduled_date`, else `ERR_SITE_PERMISSION_NOT_GRANTED`. A successful change increments the flight's `version` by one.

When `launch_site_id` is omitted, the selector applies the site-candidacy calculation over every launch site in the registry. A site is eligible when all of the following hold: its `permission_status` is `GRANTED`; its `permission_expires_on` is on or after the flight's `scheduled_date`; and either no `RECORDED` weather briefing exists for the flight yet, or the site tolerates the observed conditions — meaning the site's `surface_wind_limit_kts` is at least the briefing's `surface_wind_kts` and its `aloft_wind_limit_kts` is at least the briefing's `aloft_wind_kts`. Eligible sites are ranked by wind margin: each site's `wind_margin_kts` is the smaller of two differences — the site's `surface_wind_limit_kts` minus the briefing's `surface_wind_kts`, and the site's `aloft_wind_limit_kts` minus the briefing's `aloft_wind_kts` — and the ranking sorts by `wind_margin_kts` descending, so the site with the most headroom against the observed winds wins. Ties break toward the site whose `permission_granted_at` is earliest, and any remaining tie falls back to `created_at` ascending. When no `RECORDED` briefing exists yet, every eligible site's `wind_margin_kts` is null and the ranking is entirely the `permission_granted_at`-then-`created_at` order. If the eligible pool is empty, the operation is rejected with `ERR_NO_SUITABLE_SITE` (HTTP 422).

The same ranking powers a read model: the operations desk and the assigned pilot can fetch the flight's ranked candidate sites, where each row exposes `site_id`, `wind_margin_kts`, and `permission_granted_at`.

### 3.4. Booking Shared Seats and Charters: Quotes, Payment, and the Manifest

Once a flight is `SCHEDULED`, customers book against it. The booking payload carries the `customer_id` — which must equal the acting customer's `X-User-ID`, with a mismatch rejected as `ERR_RESERVATION_NOT_OWNED` — plus the `party_size`, the party's total `declared_weight_lbs`, and an optional `photo_package_tier` of `NONE`, `STANDARD`, or `DELUXE` (defaulting to `NONE`). The reservation's `flight_id` comes from the booking path itself. A new reservation opens with `booking_status` `PENDING` and `payment_status` `UNPAID`, with `paid_cents`, `refunded_cents`, and `goodwill_credit_cents` all at 0 and with `final_fare_cents` and `cancel_reason` null.

Two capacity rules guard the booking, checked in this order. First, weight-and-balance: the declared party weight plus the balloon's `empty_weight_lbs` plus the flight's `fuel_lbs` must not exceed the balloon's `max_gross_weight_lbs`; a violation is rejected with `ERR_PAYLOAD_EXCEEDED` (HTTP 422). Second, seats: on a `SHARED` flight, the flight's `seats_sold` plus the new `party_size` must not exceed the balloon's `basket_capacity_passengers`, else `ERR_BASKET_CAPACITY_EXCEEDED` (HTTP 422); on a `CHARTER` flight the whole basket is exclusive — at most one non-cancelled reservation may exist, and its `party_size` must still fit within `basket_capacity_passengers` — so a second booking, or an oversized charter party, is rejected with `ERR_CHARTER_EXCLUSIVE` (HTTP 409). The flight's `seats_sold` is the sum of `party_size` over its reservations whose `booking_status` is `PENDING`, `CONFIRMED`, `CHECKED_IN`, `FLOWN`, or `COMPLETED`, and `seats_available` is the balloon's `basket_capacity_passengers` minus `seats_sold`.

Booking also produces the provisional fare quote, stored as `quoted_fare_cents`. The fare calculation has two variants that share one algorithm and differ only in the weight source: the provisional variant computed at booking divides the reservation's `declared_weight_lbs` by `party_size` for the average weight, while the final variant computed at check-in divides the sum of the actual `weight_lbs` over the reservation's passenger records by `party_size`. The algorithm itself:

- **Shared flights.** The per-person base fare is 39900 cents during `PEAK` season and 29900 cents during `REGULAR` season. When the party's average weight per person is strictly greater than 200 pounds, a weight surcharge of 2500 cents per person applies; at exactly 200 pounds or below there is no surcharge. The fare is `party_size` times the sum of the base and any surcharge, plus the photo add-on.
- **Charter flights.** The flat charter fare is keyed on the balloon's `basket_capacity_passengers`: 120000 cents when the capacity is 4 or fewer, 180000 cents when it is 5 through 8, and 250000 cents when it is 9 or more. During `PEAK` season the flat fare is multiplied by 1.25 with the result rounded half-up to the nearest cent; during `REGULAR` season the flat fare stands as-is. The photo add-on is then added.
- **Photo add-on.** Zero cents for `NONE`, 4900 cents for `STANDARD`, and 9900 cents for `DELUXE`, identical for both kinds.

When `photo_package_tier` is anything other than `NONE`, the booking cascade-creates a `PhotoPackageRecord` for the reservation in `PENDING` status, with its `tier` copied from the reservation, `photo_count` 0, and `delivered_at` null. Manifest entries are added by the owning customer while the reservation is `PENDING` or `CONFIRMED`; each `Passenger` record takes the passenger's `name`, actual `weight_lbs`, and an optional `is_minor` flag defaulting to false, and carries the `reservation_id` from the path. Manifest entries are immutable once created.

Payment is exact. The customer confirms a `PENDING` reservation by paying exactly the quoted fare. Confirmation first requires the flight to still be `SCHEDULED` — otherwise the event is rejected with `ERR_INVALID_STATE` (HTTP 409) — and then requires the confirming event's `paid_cents` to equal `quoted_fare_cents` to the cent, with any mismatch rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402). On success the reservation moves `PENDING → CONFIRMED`, the payment dimension moves `UNPAID → PAID`, and the collected amount is recorded in `paid_cents`. Reservations can be listed with optional filters on `flight_id`, `customer_id`, and `booking_status`.

### 3.5. Dawn Operations: Weather Review, Go/No-Go, and Passenger Check-In

On the morning of the flight, the assigned pilot drives the flight through its dawn window. Entering weather review moves the flight `SCHEDULED → WEATHER_REVIEW` and is permitted only while the logical clock reads within the dawn window — at or after `dawn_window_start` and at or before `dawn_window_end`, both ends inclusive; an attempt outside that window is rejected with `ERR_DAWN_WINDOW_EXPIRED` (HTTP 409). Every pilot-scoped flight event first verifies that the acting pilot's `X-User-ID` equals the flight's `pilot_id`, rejecting impostors with `ERR_FLIGHT_NOT_ASSIGNED`, and an event attempted from the wrong state is rejected with `ERR_INVALID_STATE` (HTTP 409).

While in `WEATHER_REVIEW`, the assigned pilot records weather observations. Each briefing captures `surface_wind_kts`, `aloft_wind_kts`, `visibility_mi` in statute miles, and a boolean `precipitation`, and is stamped with `observed_at` at record time. The system computes the briefing's `decision`: `GO` exactly when the surface wind is at or below the site's `surface_wind_limit_kts`, the aloft wind is at or below the site's `aloft_wind_limit_kts`, visibility is at least 3.0 miles, and no precipitation is occurring; any other combination computes `NO_GO`. Recording a new briefing on the same flight supersedes the previous one: the prior `RECORDED` briefing flips to `SUPERSEDED`, so exactly one `RECORDED` briefing exists per flight at any moment.

The go decision moves the flight `WEATHER_REVIEW → CLEARED_FOR_LAUNCH`. It requires the clock to read at or before `dawn_window_end` (`ERR_DAWN_WINDOW_EXPIRED` otherwise) and it requires the latest briefing by `observed_at` — which must still be `RECORDED` — to carry a computed `decision` of `GO`; attempting to record a go against a `NO_GO` briefing, or with no qualifying briefing, is rejected with `ERR_WEATHER_LIMITS_EXCEEDED` (HTTP 422). Of these two business checks, the weather-limits check is evaluated before the dawn-window check. On success the flight's `weather_decision` is set to `GO` and `weather_decision_at` to the current instant. The no-go decision moves the flight `WEATHER_REVIEW → NO_GO`, sets `weather_decision` to `NO_GO` with `weather_decision_at` stamped, and — crucially — leaves every attached reservation in place: bookings in `PENDING` or `CONFIRMED` simply ride along, waiting for the operator to either reschedule the flight or cancel it per §3.7.

Passenger check-in happens while the flight is in `WEATHER_REVIEW` or `CLEARED_FOR_LAUNCH`, performed by an `OperationsManager` on each `CONFIRMED` reservation. Check-in is guarded by three business checks evaluated in order. First, the prospective weight-and-balance check: the flight's current `payload_used_lbs` plus the sum of this reservation's actual passenger weights must remain at or below the balloon's `max_gross_weight_lbs` — the limit is inclusive, so a total exactly equal to max gross is allowed — else `ERR_PAYLOAD_EXCEEDED`. The flight's `payload_used_lbs` itself is defined as the balloon's `empty_weight_lbs` plus the flight's `fuel_lbs` plus the sum of `weight_lbs` over every passenger whose reservation belongs to this flight and sits in `CHECKED_IN`, `FLOWN`, or `COMPLETED`. Second, manifest completeness: the number of `Passenger` records on the reservation must equal its `party_size`, else `ERR_MANIFEST_INCOMPLETE` (HTTP 422). Third, payment settlement, described next.

Check-in reprices the reservation with the final variant of the fare algorithm from §3.4 — same algorithm, but the party weight is now the sum of the actual passenger `weight_lbs` — and stores the result in `final_fare_cents`. The settle delta is `final_fare_cents` minus the already-collected `paid_cents`. When the delta is positive, the event's `additional_paid_cents` — an optional field defaulting to 0 — must equal that delta exactly and `paid_cents` rises by it; when the delta is negative, no money is collected — instead the customer's `wallet_credit_cents` grows by the absolute value of the delta and `paid_cents` falls accordingly. Either way, a supplied amount that does not match the required delta is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful check-in moves the reservation `CONFIRMED → CHECKED_IN` and recomputes the flight's payload.

### 3.6. Launch, Chase Crew Recovery, and Post-Flight Closeout

No balloon leaves the ground without a chase crew behind it. An `OperationsManager` assigns a crew to a flight by naming the `crew_lead_name`, the `vehicle_id`, and the `crew_size`; the assignment opens in `ASSIGNED`. The assigned pilot may then launch — moving the flight `CLEARED_FOR_LAUNCH → AIRBORNE` — only when the clock still reads at or before `dawn_window_end` (`ERR_DAWN_WINDOW_EXPIRED`), when at least one chase assignment for the flight sits in `ASSIGNED` or `EN_ROUTE` (`ERR_CHASE_NOT_READY`, HTTP 409, otherwise — this chase-readiness check is evaluated before the window check), and when the flight's `payload_used_lbs` remains within the balloon's `max_gross_weight_lbs` (`ERR_PAYLOAD_EXCEEDED`, HTTP 422, otherwise).

Meanwhile the chase crew lead walks their own track. Dispatching moves the assignment `ASSIGNED → EN_ROUTE`. Arriving at the landing site — permitted only while the flight is `AIRBORNE` or `LANDED` — moves the assignment to `AT_LANDING` and records the `landing_lat` and `landing_lon` coordinates supplied with the event. Recovery moves it `AT_LANDING → RECOVERED`, and the final debrief moves it `RECOVERED → DEBRIEFED`.

Back on the ground, the pilot lands the flight, moving it `AIRBORNE → LANDED` and optionally recording the actual `duration_hours` flown — the figure that will feed the pilot's internal currency; when omitted, `duration_hours` stays null and the closed flight contributes takeoffs-and-landings but no hours. The operations desk then marks each `CHECKED_IN` reservation as flown (`CHECKED_IN → FLOWN`, permitted once the flight is `LANDED`) and completes each `FLOWN` reservation with the post-flight ceremony — completion, like marking flown, is permitted only while the flight is `LANDED`: the completion event optionally carries a `photo_count` (defaulting to 0), and if a `PhotoPackageRecord` exists for the reservation in `PENDING`, it flips to `DELIVERED` with `photo_count` copied from the event payload and `delivered_at` stamped with the current instant. Completion moves the reservation to its terminal `COMPLETED` state.

Closing the flight is the final act, moving it `LANDED → CLOSED`, and it is permitted only when every chase assignment for the flight has reached `RECOVERED` or `DEBRIEFED` and every `CHECKED_IN` reservation has been advanced to `FLOWN` (or cancelled) — an attempt that violates either precondition is rejected with `ERR_INVALID_STATE` (HTTP 409). At close, the flight begins contributing to the pilot's internal currency: `internal_pic_hours_180d` and `internal_takeoffs_landings_90d` are recomputed, and with them the currency fields of §2.10. `CLOSED` is terminal, as is `CANCELLED`.

### 3.7. Cancellations, Rescheduling, and the Refund Pipeline

A flight in `NO_GO` has two exits. Rescheduling — an `OperationsManager` action carrying `new_scheduled_date`, `new_dawn_window_start`, and `new_dawn_window_end` — returns the flight to `SCHEDULED`. The new window must again be exactly ninety minutes, the balloon and pilot must be free under the same overlap rules that govern publishing (`ERR_BALLOON_SCHEDULE_CONFLICT`, `ERR_PILOT_SCHEDULE_CONFLICT`), and on success the flight's `scheduled_date` and dawn window are replaced, `season_tier` is recomputed from the new date, and `weather_decision` / `weather_decision_at` reset to `NONE` and null. Attached reservations keep their `booking_status` and their `paid_cents`; rescheduling never auto-refunds.

Cancellation is the other exit, and its cascade depends on the door it leaves through:

- **Weather cancel.** Cancelling an `NO_GO` flight sets the flight's `cancel_reason` to `WEATHER`. Every reservation in `PENDING`, `CONFIRMED`, or `CHECKED_IN` cascades to `CANCELLED` with its own `cancel_reason` of `WEATHER_CANCEL`, and for each such reservation whose `payment_status` is `PAID`, a `Refund` is auto-created in `REQUESTED` with its `reason` set to `WEATHER_CANCEL` and a policy-computed `requested_amount_cents`.
- **Operator cancel.** Cancelling a `SCHEDULED` flight sets `cancel_reason` to `OPERATOR`. The same reservation cascade runs with reason `OPERATOR_CANCEL`, the same refund auto-creation applies, and additionally each refunded reservation's `goodwill_credit_cents` is set to ten percent of its `paid_cents`, rounded half-up to the nearest cent.
- **Aircraft cascade.** Grounding a balloon is itself an operator-level cancel: every `SCHEDULED` flight using that balloon cascades to `CANCELLED` with `cancel_reason` `AIRCRAFT`, those flights' reservations in `PENDING`, `CONFIRMED`, or `CHECKED_IN` cascade to `CANCELLED` with reason `OPERATOR_CANCEL`, refunds are auto-created for the paid ones, and the same ten-percent goodwill credit applies.

Customers cancel their own reservations too. Cancelling a `PENDING` reservation simply moves it to `CANCELLED`; nothing was paid, so no refund is created. Cancelling a `CONFIRMED` reservation forks on timing: when the cancellation lands before the point 24 hours ahead of the flight's `dawn_window_start` — that is, strictly earlier than `dawn_window_start` minus 24 hours — the reason is `CUSTOMER_CANCEL_EARLY` and a `Refund` is auto-created in `REQUESTED`; otherwise the reason is `CUSTOMER_CANCEL_LATE`, no refund is created at all, and the fare is forfeited with `payment_status` left at `PAID`. Either way the flight's payload and seat figures are recomputed.

The policy-computed `requested_amount_cents` follows a pinned procedure. The policy percentage is 100 for `WEATHER_CANCEL`, 100 for `OPERATOR_CANCEL`, 80 for `CUSTOMER_CANCEL_EARLY`, and 0 for `CUSTOMER_CANCEL_LATE` — and a zero percentage means no refund record is created at all. On a `CHARTER` flight, the requested amount is the reservation's `paid_cents` multiplied by the policy percentage, divided by 100, rounded half-up to the nearest cent. On a `SHARED` flight, a 100-percent policy triggers the full-fare carve-out: the requested amount is simply `paid_cents`, exactly. Otherwise — the 80-percent early-cancel case — the computation rounds per passenger first: divide `paid_cents` by `party_size` and round half-up to get the per-passenger paid amount, multiply that per-passenger figure by 80 and divide by 100 with a half-up round to get the per-passenger refund, then multiply the per-passenger refund by `party_size` for the requested amount. Multiplying first and rounding the total is a different answer and is not the specification.

Refunds then flow through an operator-driven pipeline. An `OperationsManager` approves a `REQUESTED` refund by supplying `approved_amount_cents`, which must not exceed `requested_amount_cents` — an over-cap approval is rejected with `ERR_REFUND_POLICY_VIOLATION` (HTTP 422) — moving the refund to `APPROVED`. Denying moves a `REQUESTED` refund to `DENIED`, terminal. Paying an `APPROVED` refund requires a `paid_via` of `ORIGINAL_PAYMENT` or `WALLET_CREDIT`, stamps `paid_at` with the current instant, and settles the books: the reservation's `refunded_cents` grows by `approved_amount_cents`; its `payment_status` moves to `PARTIALLY_REFUNDED` when the cumulative refunded total is still below `paid_cents`, and to `REFUNDED` when a payment brings the cumulative `refunded_cents` exactly level with `paid_cents`; the reservation's `retained_revenue_cents` is always `paid_cents` minus `refunded_cents`. When `paid_via` is `WALLET_CREDIT`, the approved amount is also credited to the customer's `wallet_credit_cents`. Independently of the payment channel, paying a refund whose reason is `OPERATOR_CANCEL` additionally credits the reservation's `goodwill_credit_cents` to the customer's wallet. A reservation's refunds can be listed through its refund collection.

### 3.8. Wallets, Goodwill, and Photo Delivery Aftermath

The customer wallet threads the whole lifecycle together. It starts at zero, absorbs overpayment settle-downs at check-in, receives refund payouts that choose `WALLET_CREDIT`, and receives the ten-percent operator goodwill whenever an operator-cancel refund is paid. The wallet never drives a state machine; it is a running balance, readable with the customer record.

Photo packages close the loop on the commercial side. A booking that opted into `STANDARD` or `DELUXE` carries its `PhotoPackageRecord` from creation (`PENDING`, `photo_count` 0) through delivery at the reservation's completion event (`DELIVERED`, `photo_count` and `delivered_at` stamped from the ceremony). A reservation's photo package records can be listed through its photo-package collection, just as its manifest, its weather context on the flight, and its chase assignments are listable through their respective collections — briefings per flight, assignments per flight, passengers and refunds and photo records per reservation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all lifecycle events, return `200 OK`. Request and response bodies are not repeated here — §2 and §3 define every field, guard, and side effect.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/launch-sites` | Create a launch site (permission starts `PENDING`) | OperationsManager |
| GET | `/v1/launch-sites/{site_id}` | Read a launch site | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/launch-sites/{site_id}/events` | Landowner permission lifecycle: `GRANT_PERMISSION`, `REVOKE_PERMISSION` | OperationsManager |
| POST | `/v1/balloons` | Register a balloon | OperationsManager |
| GET | `/v1/balloons/{balloon_id}` | Read a balloon | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/balloons/{balloon_id}/events` | Balloon lifecycle: `RECORD_INSPECTION` (with `inspected_on` and OCC), `GROUND`, `RETURN_TO_SERVICE` | OperationsManager |
| POST | `/v1/pilots` | Register a pilot with externally logged experience | OperationsManager |
| GET | `/v1/pilots/{pilot_id}` | Read a pilot, including computed currency fields | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/customers` | Self-register a customer | Anonymous |
| GET | `/v1/customers/{customer_id}` | Read a customer (wallet balance) | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/flights` | Create a flight in `DRAFT` (dawn window exactly 90 minutes, on `scheduled_date`) | OperationsManager |
| GET | `/v1/flights` | List flights; filters `launch_site_id`, `balloon_id`, `pilot_id`, `status` | OperationsManager, Pilot, Customer, ChaseCrewLead |
| GET | `/v1/flights/{flight_id}` | Read a flight | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/flights/{flight_id}/events` | Flight lifecycle. OperationsManager: `PUBLISH`, `RESCHEDULE`, `CANCEL`, `CLOSE`. Assigned Pilot: `ENTER_WEATHER_REVIEW`, `RECORD_GO`, `RECORD_NO_GO`, `LAUNCH`, `LAND` | OperationsManager, Pilot |
| POST | `/v1/flights/{flight_id}/select-launch-site` | Change the launch site while `SCHEDULED` or `WEATHER_REVIEW`; `launch_site_id` optional (selector picks when omitted); OCC-guarded | OperationsManager |
| GET | `/v1/flights/{flight_id}/site-candidates` | Ranked eligible launch sites for the flight | OperationsManager, Pilot |
| POST | `/v1/flights/{flight_id}/reservations` | Book a reservation on a `SCHEDULED` flight; computes `quoted_fare_cents` | Customer |
| GET | `/v1/reservations` | List reservations; filters `flight_id`, `customer_id`, `booking_status` | OperationsManager, Pilot, Customer, ChaseCrewLead |
| GET | `/v1/reservations/{reservation_id}` | Read a reservation | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/reservations/{reservation_id}/events` | Reservation lifecycle. Customer (own): `CONFIRM`, `CANCEL`. OperationsManager: `CHECK_IN`, `MARK_FLOWN`, `COMPLETE` | Customer, OperationsManager |
| POST | `/v1/reservations/{reservation_id}/passengers` | Add a passenger manifest entry (while `PENDING` or `CONFIRMED`) | Customer |
| GET | `/v1/reservations/{id}/passengers` | List a reservation's passenger manifest | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/flights/{flight_id}/weather-briefings` | Record a dawn weather observation (assigned pilot, flight in `WEATHER_REVIEW`); supersedes prior briefing; decision computed | Pilot |
| GET | `/v1/flights/{id}/weather-briefings` | List weather briefings for a flight | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/flights/{flight_id}/chase-assignments` | Assign a chase crew to a flight | OperationsManager |
| GET | `/v1/flights/{id}/chase-assignments` | List chase assignments for a flight | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/chase-assignments/{assignment_id}/events` | Chase crew progress: `DISPATCH`, `ARRIVE_AT_LANDING`, `RECOVER`, `DEBRIEF` | ChaseCrewLead |
| GET | `/v1/reservations/{id}/refunds` | List refunds for a reservation | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/refunds/{refund_id}/events` | Refund processing: `APPROVE`, `PAY`, `DENY` | OperationsManager |
| GET | `/v1/reservations/{id}/photo-packages` | List photo package records for a reservation | OperationsManager, Pilot, Customer, ChaseCrewLead |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock (startup default `2026-08-01T00:00:00Z`) | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RESERVATION_NOT_OWNED` | 403 |
| `ERR_FLIGHT_NOT_ASSIGNED` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PILOT_NOT_CURRENT` | 409 |
| `ERR_BALLOON_GROUNDED` | 409 |
| `ERR_SITE_PERMISSION_NOT_GRANTED` | 409 |
| `ERR_PAYLOAD_EXCEEDED` | 422 |
| `ERR_WEATHER_LIMITS_EXCEEDED` | 422 |
| `ERR_CHASE_NOT_READY` | 409 |
| `ERR_DAWN_WINDOW_EXPIRED` | 409 |
| `ERR_BALLOON_SCHEDULE_CONFLICT` | 409 |
| `ERR_PILOT_SCHEDULE_CONFLICT` | 409 |
| `ERR_BASKET_CAPACITY_EXCEEDED` | 422 |
| `ERR_CHARTER_EXCLUSIVE` | 409 |
| `ERR_MANIFEST_INCOMPLETE` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 |
| `ERR_REFUND_POLICY_VIOLATION` | 422 |
| `ERR_NO_SUITABLE_SITE` | 422 |
